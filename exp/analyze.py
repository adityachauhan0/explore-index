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
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from telemetry import extract  # noqa: E402


def _grader_for(repo: str):
    """Return the grade() belonging to a repo's own task suite.

    CORRECTION (2026-10-02): this used to be a module-level
    `from tasks import grade`, i.e. the GrowiaCRM grader was applied to EVERY
    repo. Django runs were therefore scored by a grader whose path regex only
    knows GrowiaCRM's `apps/api/src/...` layout, so `names_real_paths` was
    always False and every treatment run scored a false hit. The symptom looked
    like a skill defect — it was a harness defect.

    Suites stay independent by design: tasks.py (growiacrm) is the frozen
    historical record, tasks_django.py is the replication.
    """
    mod = __import__("tasks" if repo == "growiacrm" else f"tasks_{repo}")
    return mod.grade

RUNS = HERE / "results" / "runs.jsonl"

# Timeline of the SKILL.md revisions used in the Django replication.
#
# CORRECTION (cycle 008): `skill_version` used to be derived purely from the cycle
# number, which silently mislabelled three runs. SKILL.md was edited *mid-experiment*
# (the Round 2 "Big file, many turns" rule) while the batch was in flight, so runs
# dispatched after that moment executed under a different prompt than runs recorded
# before it — while both were tagged "v2-binding". Pooling them would attribute a
# prompt change to a repeat.
#
# The revision is therefore resolved from the file's mtime against the session's
# first message timestamp, not from the cycle. Baseline runs are always "n/a".
SKILL_HISTORY: list[tuple[float, str]] = []


def _skill_history() -> list[tuple[float, str]]:
    """[(mtime_epoch_seconds, version_label), ...] oldest first, loaded once."""
    if SKILL_HISTORY:
        return SKILL_HISTORY
    skill_md = HERE.parent / "skills" / "explore-index" / "SKILL.md"
    now = time.time()
    SKILL_HISTORY.append((0.0, "v2-binding"))
    try:
        SKILL_HISTORY.append((skill_md.stat().st_mtime, "v3-bigfile"))
    except OSError:
        pass
    SKILL_HISTORY.sort(key=lambda p: p[0])
    return SKILL_HISTORY


def skill_version_for(arm: str, cycle: str, session_id: str) -> str:
    """Resolve which SKILL.md revision a treatment run actually executed under."""
    if arm != "treatment":
        return "n/a"
    if cycle == "001":
        return "v1-advisory"
    start_ms = session_start_ms(session_id)
    if start_ms is None:
        return "v2-binding"
    for mtime, label in _skill_history():
        if start_ms / 1000.0 >= mtime:
            chosen = label
    return chosen


def session_start_ms(session_id: str) -> int | None:
    try:
        from telemetry import connect
        con = connect()
        row = con.execute(
            "SELECT MIN(created_at_ms) FROM local_runtime_message_rows WHERE session_id=?",
            (session_id,),
        ).fetchone()
        con.close()
        return row[0] if row else None
    except Exception:
        return None


# Kill criteria, defined before any data was collected.
KILL_FALSE_HIT_RATE = 0.02
MIN_TOKENS_PER_RUN = 2_000      # below this, telemetry extraction is suspect
ISO_ACCURACY_TOLERANCE = 0.05   # treatment may not trail baseline by >5pp


def record(cycle: str, arm: str, session_id: str, task: dict, tag: str,
           repo: str = "growiacrm") -> dict:
    t = extract(session_id, want_toolcalls=False)
    g = _grader_for(repo)(task, t["final_result"])
    # Tag the skill cohort at write time, resolved from when the session actually
    # started relative to the SKILL.md revision timeline. Cycle-001 treatment runs
    # used the advisory skill; cycle-008 Django runs split at the Round 2 edit.
    skill_version = skill_version_for(arm, cycle, session_id)
    rec = {
        "cycle": cycle, "arm": arm, "task": task["id"], "split": task["split"],
        "repo": repo, "tag": tag, "session": session_id, "skill_version": skill_version,
        "provider_tokens": t["provider_tokens_total"],
        "uncached_input": t["uncached_input_total"],
        "cache_read": t["cache_read_total"],
        "output_tokens": t["output_tokens_total"],
        "turns": t["turns"],
        "tool_calls": t["tool_calls"],
        "empty_tool_calls": t["empty_tool_calls"],
        **g,
    }
    # COMPLETENESS GUARD.
    #
    # A run must not be recorded while its session is still streaming: the
    # extract then returns a PARTIAL snapshot, and a partial snapshot is
    # indistinguishable from a real result. It was recorded once — turns 4 vs a
    # true 8, tool_calls 9 vs 22, provider_tokens 48,104 vs a true 134,330,
    # and an empty final_result that graded as resolved=false. That is a false
    # negative charged to the baseline arm.
    #
    # Refuse to write rather than silently record a partial run.
    if not t["final_result"].strip():
        raise SystemExit(
            f"REFUSED: session {session_id} has an empty final_result.\n"
            "  The session is still running or its text was not captured.\n"
            "  Wait for it to finish, then re-run this command.\n"
            "  A partial snapshot would corrupt the dataset."
        )
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    with RUNS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec, indent=2))
    return rec


def audit_telemetry(repo: str | None = None) -> int:
    """Re-extract stored rows and report any whose telemetry has since moved.

    A stored row is a snapshot. If the underlying session grew afterwards, the
    snapshot is stale and must be re-recorded. Run this before trusting any
    aggregate. Returns the number of mismatched rows.
    """
    rows = [json.loads(l) for l in RUNS.read_text().splitlines() if l.strip()]
    bad = 0
    for r in rows:
        if repo and r.get("repo", "growiacrm") != repo:
            continue
        try:
            t = extract(r["session"], want_toolcalls=False)
        except Exception as exc:
            print(f"  {r['session']}  extract failed: {exc}")
            bad += 1
            continue
        cur = {
            "turns": t["turns"], "tool_calls": t["tool_calls"],
            "provider_tokens": t["provider_tokens_total"],
            "uncached_input": t["uncached_input_total"],
            "cache_read": t["cache_read_total"],
            "output_tokens": t["output_tokens_total"],
        }
        diff = {k: (r[k], cur[k]) for k in cur if r.get(k) != cur[k]}
        if diff:
            bad += 1
            print(f"  STALE {r['arm']:9} {r['task']:3} {r['tag']:7} {r['session']}")
            for k, (a, b) in diff.items():
                print(f"        {k:16} stored={a:>8}  fresh={b:>8}")
    print(f"audited: {bad} stale row(s)" if bad else "audited: all rows current")
    return bad


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _welch(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch's t and a two-sided p-value using Student's t.

    CORRECTION (2026-10-02): this previously used a normal approximation,
    `erfc(|t|/sqrt(2))`, and its own docstring admitted p was "indicative". At the
    n used here (15 vs 14) that approximation is anti-conservative: it reported
    p = 0.0005 for the headline cohort where the exact Welch t-test gives
    p = 0.0019. The effect was and remains significant, but the published figure
    overstated it. Delegates to the tested implementation in costs.py, whose
    incomplete-beta routine reproduces reference t-tables to 4 decimals.
    """
    import costs
    return costs.welch(a, b)
    return t, p


def report(cycle: str | None = None, cohort: str = "v2-binding") -> dict:
    """`cohort` isolates the skill version under test.

    Cycle-001 treatment runs used the ADVISORY skill; pooling them with the
    BINDING runs would understate the current design and conflate two different
    interventions. `--cohort all` still shows everything for transparency."""
    runs = [json.loads(l) for l in RUNS.read_text().splitlines() if l.strip()] \
        if RUNS.exists() else []
    # Rows flagged excluded_from_analysis are retained for audit but must never
    # enter an aggregate. One was recorded from a partial session snapshot.
    runs = [r for r in runs if not r.get("excluded_from_analysis")]
    if cycle:
        runs = [r for r in runs if r["cycle"] == cycle]
    if cohort != "all":
        # "current" is the default: every treatment revision that is actually in
        # the shipped SKILL.md lineage (v2-binding pre-Round-2, v3-bigfile post).
        # Baseline runs are always included so the two arms stay comparable.
        wanted = ({"v2-binding", "v3-bigfile"} if cohort == "current"
                  else {cohort})
        runs = [r for r in runs
                if r.get("arm") != "treatment" or r.get("skill_version") in wanted]
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
    ap.add_argument("--audit", action="store_true",
                    help="re-extract stored rows and report stale telemetry")
    ap.add_argument("--cohort", default="current")
    ap.add_argument("--repo", default="growiacrm",
                    help="which task suite + repo this run belongs to")
    a = ap.parse_args()

    if a.audit:
        audit_telemetry(a.repo)
        return
    if a.report:
        report(a.cycle if a.cycle != "all" else None, a.cohort)
        return
    if not (a.arm and a.session and a.task):
        ap.error("need --arm --session --task (or --report)")
    # Suite selection is by repo, not by import order. tasks.py (growiacrm) stays
    # the historical record; tasks_django.py is an independent second repo, so a
    # later edit to one cannot silently weaken the other's graders.
    suite = "tasks" if a.repo == "growiacrm" else f"tasks_{a.repo}"
    mod = __import__(suite)
    task = next((t for t in mod.TASKS if t["id"] == a.task), None)
    if not task:
        ap.error(f"unknown task {a.task} in {suite}")
    record(a.cycle, a.arm, a.session, task, a.tag, repo=a.repo)


if __name__ == "__main__":
    main()