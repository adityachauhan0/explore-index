#!/usr/bin/env python3
"""Generate the benchmark tables in markdown from runs.jsonl.

Every published number is generated from raw telemetry here, never typed by
hand. The original protocol records that two arithmetic errors in the final
report were caught only by regenerating and diffing — this script exists to make
that class of error impossible to ship.

Reads runs.jsonl. Writes BENCHMARKS.md. Prints what it wrote.

Usage:
  python3 benchmark_table.py                    # all repos, headline cohort
  python3 benchmark_table.py --repo django      # one repo
  python3 benchmark_table.py --out ../BENCHMARKS.md
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import costs

HERE = Path(__file__).resolve().parent

REPO_LABEL = {
    "growiacrm": "GrowiaCRM @ `146b7f19`",
    "django": "django/django @ `80ea222`",
}

RATE_NOTE = {
    "1x": "raw billed tokens (`provider_tokens`)",
    "0.1x": "cache reads at a typical 0.1x discount",
    "0x": "fresh tokens only, cache reads ignored",
}


def pct(new: float, old: float) -> str:
    return f"{100 * (new - old) / old:+.1f}%" if old else "n/a"


def section_for(repo_key: str, runs: list[dict]) -> str:
    label = REPO_LABEL.get(repo_key, repo_key)
    out = [f"## {label}", ""]

    # ---- inventory: the complete run log, every single run -------------
    out += ["### Run log", "",
            "Every recorded run. `provider_tokens` = uncached_input + cache_read "
            "(output excluded — see FINAL-REPORT correction note).", "",
            "| session | arm | task | split | skill | tokens | uncached | cache-read | "
            "output | turns | tools | resolved | false hit |",
            "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|:-:|:-:|"]
    for r in sorted(runs, key=lambda x: (x.get("task", ""), x.get("arm", ""),
                                         x.get("session", ""))):
        out.append(
            f"| `{r.get('session','')[-8:]}` | {r['arm']} | {r.get('task','-')} | "
            f"{r.get('split','-')} | {r.get('skill_version','-')} | "
            f"{r['provider_tokens']:,} | {r['uncached_input']:,} | {r['cache_read']:,} | "
            f"{r['output_tokens']:,} | {r['turns']} | {r['tool_calls']} | "
            f"{'Y' if r['resolved'] else 'N'} | {'Y' if r['false_hit'] else 'N'} |")
    out.append("")

    # ---- arm means -----------------------------------------------------
    arms = {}
    for arm in ("baseline", "treatment"):
        rs = [r for r in runs if r["arm"] == arm]
        if rs:
            arms[arm] = rs
    if len(arms) != 2:
        out += ["_Only one arm present for this repo — no comparison is possible yet._", ""]
        return "\n".join(out)

    b, t = arms["baseline"], arms["treatment"]
    out += ["### Arm means", "",
            "| metric | baseline | with skill | delta |",
            "|---|---:|---:|---:|"]
    for key, lab, dp in (("provider_tokens", "billed tokens", 0),
                         ("uncached_input", "uncached input", 0),
                         ("cache_read", "cache-read", 0),
                         ("output_tokens", "output tokens", 0),
                         ("turns", "turns", 1),
                         ("tool_calls", "tool calls", 1)):
        mb = statistics.mean(r[key] for r in b)
        mt = statistics.mean(r[key] for r in t)
        f = f",.0f" if dp == 0 else f",.{dp}f"
        out.append(f"| {lab} | {mb:{f}} | {mt:{f}} | {pct(mt, mb)} |")
    acc_b = statistics.mean(float(r["resolved"]) for r in b)
    acc_t = statistics.mean(float(r["resolved"]) for r in t)
    out.append(f"| accuracy | {acc_b:.3f} | {acc_t:.3f} | "
               f"{'equal' if acc_b == acc_t else 'CHANGED'} |")
    out.append(f"| false hits | {sum(1 for r in b if r['false_hit'])} | "
               f"{sum(1 for r in t if r['false_hit'])} | — |")
    out.append(f"| runs | {len(b)} | {len(t)} | — |")
    out.append("")

    # ---- the saving at every cache rate --------------------------------
    out += ["### Saving by cache-pricing rate", "",
            "The headline denominator is a choice. This is the full range.", "",
            "| cache priced at | baseline | with skill | saving | p | note |",
            "|---|---:|---:|---:|---:|---|"]
    for rate in costs.CACHE_RATES:
        key = f"{rate:g}x"
        bc = [costs.cost(r, rate) for r in b]
        tc = [costs.cost(r, rate) for r in t]
        _, p = costs.welch(bc, tc)
        out.append(f"| {key} | {statistics.mean(bc):,.0f} | {statistics.mean(tc):,.0f} | "
                   f"{pct(statistics.mean(tc), statistics.mean(bc))} | {p:.4f} | "
                   f"{RATE_NOTE[key]} |")
    out.append("")

    # ---- per task ------------------------------------------------------
    out += ["### Per task", "",
            "| task | split | baseline | with skill | saving |",
            "|---|---|---:|---:|---:|"]
    ids = sorted({r["task"] for r in runs})
    for tid in ids:
        tb = [r for r in b if r["task"] == tid]
        tt = [r for r in t if r["task"] == tid]
        if not tb or not tt:
            continue
        split = (tt or tb)[0].get("split", "-")
        mb = statistics.mean(r["provider_tokens"] for r in tb)
        mt = statistics.mean(r["provider_tokens"] for r in tt)
        out.append(f"| {tid} | {split} | {mb:,.0f} | {mt:,.0f} | {pct(mt, mb)} |")
    out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="current")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--out", default=str(HERE.parent / "BENCHMARKS.md"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    runs = costs.load(a.cohort, a.repo)
    if not runs:
        print(f"no runs for cohort={a.cohort} repo={a.repo}")
        return

    # Row-count guard. Defect 6: a filter that matched nothing still produced
    # plausible-looking aggregate statistics. Fail loudly instead.
    arms = {arm: sum(1 for r in runs if r["arm"] == arm) for arm in ("baseline", "treatment")}
    if min(arms.values()) == 0:
        raise SystemExit(f"REFUSED: cohort={a.cohort} repo={a.repo} has {arms} - "
                         "an arm is empty, so any mean would be meaningless.")
    print(f"cohort={a.cohort} repo={a.repo or '(all)'} "
          f"baseline={arms['baseline']} treatment={arms['treatment']}")

    repos: dict[str, list[dict]] = {}
    for r in runs:
        repos.setdefault(r.get("repo", "growiacrm"), []).append(r)

    md = ["# explore-index — benchmarks", "",
          "Generated by `exp/benchmark_table.py` from `exp/results/runs.jsonl`. "
          "Do not hand-edit — regenerate.",
          "",
          f"Cohort: `{a.cohort}`. Every figure below is recomputed from raw "
          "per-run telemetry at generation time.", ""]
    for key in sorted(repos):
        md.append(section_for(key, repos[key]))
        md.append("\n---\n")

    if a.json:
        print(json.dumps({k: len(v) for k, v in repos.items()}, indent=2))
        return

    Path(a.out).write_text("\n".join(md))
    print(f"wrote {a.out}")
    for key, rs in sorted(repos.items()):
        nb = sum(1 for r in rs if r["arm"] == "baseline")
        print(f"  {key}: {len(rs)} runs ({nb} baseline / {len(rs)-nb} treatment)")


if __name__ == "__main__":
    main()