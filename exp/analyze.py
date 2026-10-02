#!/usr/bin/env python3
"""Aggregate per-run telemetry into an A/B cycle verdict.

Usage:
  python3 analyze.py --cycle 001 --arm treatment --session mvs_x --task S1
  python3 analyze.py --report results/cycle-001

Each `--session` invocation writes a run record into results/runs.jsonl.
`--report` recomputes arm means, the iso-accuracy guard, and the kill criteria
from every run recorded so far.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tasks import grade  # noqa: E402
from telemetry import extract  # noqa: E402

RUNS = HERE / "results" / "runs.jsonl"

# Kill criteria, defined before any data was collected.
KILL_FALSE_HIT_RATE = 0.02
MIN_TOKENS_PER_RUN = 2_000      # below this, telemetry extraction is suspect
ISO_ACCURACY_TOLERANCE = 0.05   # treatment may not trail baseline by >5pp


def record(cycle: str, arm: str, session_id: str, task: dict, tag: str) -> dict:
    t = extract(session_id, want_toolcalls=False)
    g = grade(task, t["final_result"])
    # Tag the skill cohort at write time. Cycle-001 treatment runs used the
    # advisory skill; everything from cycle 002 on uses the binding skill.
    # Backfilling this by hand is what let unpooled analysis go stale.
    skill_version = ("n/a" if arm != "treatment"
                     else "v1-advisory" if cycle == "001" else "v2-binding")
    rec = {
        "cycle": cycle, "arm": arm, "task": task["id"], "split": task["split"],
        "tag": tag, "session": session_id, "skill_version": skill_version,
        "provider_tokens": t["provider_tokens_total"],
        "uncached_input": t["uncached_input_total"],
        "cache_read": t["cache_read_total"],
        "output_tokens": t["output_tokens_total"],
        "turns": t["turns"],
        "tool_calls": t["tool_calls"],
        "empty_tool_calls": t["empty_tool_calls"],
        **g,
    }
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    with RUNS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec, indent=2))
    return rec


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _welch(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch's t and a normal-approx two-sided p. Good enough for a directional
    check; n is small, so treat p as indicative rather than definitive."""
    import math, random
    if len(a) < 2 or len(b) < 2:
        return 0.0, 1.0
    ma, mb = _mean(a), _mean(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return 0.0, 1.0
    t = (mb - ma) / se
    # normal approx
    p = math.erfc(abs(t) / math.sqrt(2))
    return t, p


def report(cycle: str | None = None, cohort: str = "v2-binding") -> dict:
    """`cohort` isolates the skill version under test.

    Cycle-001 treatment runs used the ADVISORY skill; pooling them with the
    BINDING runs would understate the current design and conflate two different
    interventions. `--cohort all` still shows everything for transparency."""
    runs = [json.loads(l) for l in RUNS.read_text().splitlines() if l.strip()] \
        if RUNS.exists() else []
    if cycle:
        runs = [r for r in runs if r["cycle"] == cycle]
    if cohort != "all":
        runs = [r for r in runs
                if r.get("arm") != "treatment" or r.get("skill_version") == cohort]
    if not runs:
        print("no runs recorded")
        return {}

    out: dict = {"cycle": cycle or "all", "cohort": cohort, "runs": len(runs)}
    for arm in ("baseline", "treatment"):
        rs = [r for r in runs if r["arm"] == arm]
        if not rs:
            continue
        out[arm] = {
            "n": len(rs),
            "mean_tokens": round(_mean([r["provider_tokens"] for r in rs])),
            "mean_turns": round(_mean([r["turns"] for r in rs]), 2),
            "mean_tool_calls": round(_mean([r["tool_calls"] for r in rs]), 2),
            "cache_read_share": round(
                _mean([r["cache_read"] / max(r["provider_tokens"], 1) for r in rs]), 3),
            "accuracy": round(_mean([float(r["resolved"]) for r in rs]), 3),
            "false_hits": sum(1 for r in rs if r["false_hit"]),
            "suspect_runs": [r["session"] for r in rs
                             if r["provider_tokens"] < MIN_TOKENS_PER_RUN],
        }

    if "baseline" in out and "treatment" in out:
        b, t_ = out["baseline"], out["treatment"]
        out["delta_tokens_pct"] = round(
            100 * (t_["mean_tokens"] - b["mean_tokens"]) / b["mean_tokens"], 1)
        out["delta_turns_pct"] = round(
            100 * (t_["mean_turns"] - b["mean_turns"]) / b["mean_turns"], 1)
        out["delta_tool_calls_pct"] = round(
            100 * (t_["mean_tool_calls"] - b["mean_tool_calls"]) / b["mean_tool_calls"], 1)
        out["iso_accuracy"] = (t_["accuracy"] >= b["accuracy"] - ISO_ACCURACY_TOLERANCE)
        total = t_["n"]
        out["false_hit_rate"] = round(t_["false_hits"] / total, 4) if total else 0.0

        runs_all = [r for r in runs if r["arm"] in ("baseline", "treatment")]
        bt = [r["provider_tokens"] for r in runs_all if r["arm"] == "baseline"]
        tt = [r["provider_tokens"] for r in runs_all if r["arm"] == "treatment"]
        w_t, w_p = _welch(bt, tt)
        out["welch_t"] = round(w_t, 3)
        out["welch_p"] = round(w_p, 4)

        out["verdict"] = (
            "KILL: false-hit rate above 2%"
            if out["false_hit_rate"] > KILL_FALSE_HIT_RATE
            else "PASS" if (out["delta_tokens_pct"] < 0 and out["iso_accuracy"])
            else "INCONCLUSIVE: no token win or accuracy dropped"
        )

    # Per-task breakdown is where the design lessons live.
    per_task: dict[str, dict] = {}
    for r in runs:
        k = r["task"]
        per_task.setdefault(k, {"split": r["split"], "baseline": [], "treatment": []})
        per_task[k][r["arm"]].append(r["provider_tokens"])
    out["per_task"] = {
        k: {
            "split": v["split"],
            "baseline": int(_mean(v["baseline"])) if v["baseline"] else None,
            "treatment": int(_mean(v["treatment"])) if v["treatment"] else None,
            "delta_pct": (round(100 * (_mean(v["treatment"]) - _mean(v["baseline"]))
                                / _mean(v["baseline"]), 1)
                          if v["baseline"] and v["treatment"] else None),
        } for k, v in sorted(per_task.items())
    }

    print(json.dumps(out, indent=2))
    if cycle:
        p = HERE / "results" / f"cycle-{cycle}.json"
        p.write_text(json.dumps(out, indent=2))
        print(f"wrote {p}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycle", default="001")
    ap.add_argument("--arm")
    ap.add_argument("--session")
    ap.add_argument("--task")
    ap.add_argument("--tag", default="")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--cohort", default="v2-binding")
    a = ap.parse_args()

    if a.report:
        report(a.cycle if a.cycle != "all" else None, a.cohort)
        return
    if not (a.arm and a.session and a.task):
        ap.error("need --arm --session --task (or --report)")
    from tasks import TASKS
    task = next((t for t in TASKS if t["id"] == a.task), None)
    if not task:
        ap.error(f"unknown task {a.task}")
    record(a.cycle, a.arm, a.session, task, a.tag)


if __name__ == "__main__":
    main()