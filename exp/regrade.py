#!/usr/bin/env python3
"""Re-grade existing run records after a grader fix, without re-running the model.

WHY THIS EXISTS
---------------
`analyze.py --session ...` grades at *write* time. When a grader defect is found
after rows exist, re-running the experiment is wasteful and would destroy the
original token/tool-call telemetry. This re-applies the CURRENT grader to the
STILL-RETRIEVABLE final answer text and rewrites only the graded fields.

It is deliberately conservative:
  - Only rows matching --repo / --tag / --session are touched.
  - It never edits token, turn or tool-call fields; those came from the runtime,
    not from a grader, and cannot change when a grader changes.
  - It writes a full before/after diff so the change is auditable.
  - --dry-run reports what would change and writes nothing.

Only grader fields recompute:
    resolved, coverage, false_hit, cited_index

PROVENANCE FIELDS (also recomputed):
    skill_version  — resolved from the session start time vs the SKILL.md
                     revision timeline, not from the cycle number. Needed
                     because SKILL.md was edited mid-experiment.

Telemetry fields (provider_tokens, turns, tool_calls, ...) are NEVER touched:
they came from the runtime, not from a grader, and cannot change when either a
grader or a label changes.
"""
from __future__ import annotations

import argparse
import json
import sys

HERE = __import__("pathlib").Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

RUNS = HERE / "results" / "runs.jsonl"
GRADED_FIELDS = ("resolved", "coverage", "false_hit", "cited_index")
PROVENANCE_FIELDS = ("skill_version",)
RECOMPUTED = GRADED_FIELDS + PROVENANCE_FIELDS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--session", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not (args.repo or args.tag or args.session):
        ap.error("scope the rewrite: pass at least one of --repo/--tag/--session")

    import analyze
    import tasks
    import tasks_django

    graders = {"growiacrm": tasks, "django": tasks_django}
    task_sets = {
        "growiacrm": {t["id"]: t for t in tasks.TASKS},
        "django": {t["id"]: t for t in tasks_django.TASKS},
    }

    rows = [json.loads(l) for l in RUNS.read_text().splitlines() if l.strip()]
    changed, checked, skipped = 0, 0, 0
    out_rows = []

    for rec in rows:
        if args.repo and rec.get("repo", "growiacrm") != args.repo:
            out_rows.append(rec)
            continue
        if args.tag and rec.get("tag") != args.tag:
            out_rows.append(rec)
            continue
        if args.session and rec.get("session") != args.session:
            out_rows.append(rec)
            continue

        repo = rec.get("repo", "growiacrm")
        task = task_sets[repo].get(rec["task"])
        if task is None:
            skipped += 1
            print(f"  SKIP  {rec['task']} unknown to {repo} suite")
            out_rows.append(rec)
            continue

        try:
            text = analyze.extract(rec["session"], want_toolcalls=False)["final_result"]
        except Exception as exc:  # session may be pruned or DB moved
            skipped += 1
            print(f"  SKIP  {rec['session']} text unavailable ({exc})")
            out_rows.append(rec)
            continue
        if not text.strip():
            skipped += 1
            print(f"  SKIP  {rec['session']} empty final_result")
            out_rows.append(rec)
            continue

        new = graders[repo].grade(task, text)
        new["skill_version"] = analyze.skill_version_for(
            rec["arm"], rec["cycle"], rec["session"])
        checked += 1
        before = {f: rec.get(f) for f in RECOMPUTED}
        if any(before[f] != new[f] for f in RECOMPUTED):
            print(f"  {rec['arm']:9} {rec['task']:3} {rec['session']}")
            for f in RECOMPUTED:
                mark = "  <-- CHANGED" if before[f] != new[f] else ""
                print(f"      {f:14} {before[f]!r} -> {new[f]!r}{mark}")
            rec.update(new)
            changed += 1
        out_rows.append(rec)

    print(f"\nchecked={checked} changed={changed} skipped={skipped} total={len(rows)}")
    if args.dry_run:
        print("DRY RUN - nothing written")
        return 0
    if changed:
        RUNS.write_text("\n".join(json.dumps(r) for r in out_rows) + "\n")
        print(f"rewrote {RUNS}")
    else:
        print("no changes; file untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())