# Cycle 002 — "a hit is binding, not advisory"

## The single change
Cycle 001 failed because the index *informed* the agent without *constraining* it.
SKILL.md gained a binding rule:

> `ABSENT` -> stop searching entirely; do not run the synonym family.
> `REGION` -> go straight to that directory; do not sweep the repo first.
> `REAL`  -> read that one file; you are then done searching.
> Budget **at most 3 broad searches per task**, and only when no row covers it.

Plus an explicit cost rationale, because the agent needs to know *why* broad
searches are expensive: each one enlarges the context every later step re-reads.

## Results
| task | split | arm | tokens | turns | tools | resolved | false hit |
|---|---|---|---|---|---|---|---|
| S3 | seeded | baseline (c001) | 216185 | 11 | 25 | yes | no |
| S3 | seeded | **treatment v2** | **69251** | **5** | **5** | yes | no |
| H2 | held-out | baseline | 283157 | 10 | 28 | yes | no |
| H2 | held-out | **treatment v2** | **206708** | 10 | 17 | yes | no |
| S1 | seeded | treatment v2 | 115282 | 8 | 11 | yes | no |

Cycle aggregate vs cycle-001 baseline: **-53.9% tokens, -60.7% tool calls**,
accuracy 1.00 in every arm, **0 false hits**.

## Why S3 collapsed 5x
Treatment trace: bash -> read INDEX.md -> read backoff.ts -> confirm -> re-read index.
**Zero broad searches.** The ABSENT row was treated as terminal. The agent reported:
> "So I ran zero broad searches and zero synonym sweeps."

Same task, baseline: 11 turns / 25 calls, saturating a 100-match grep on call 7.

## The critical control: H2 is HELD OUT
Tenant scoping has no index row. Treatment still came in at -27.0% with 17 calls
vs 28, and resolved correctly at both the mechanism (`sql-scope.ts`) and the
fail-closed design. **No false hit.** The gain is not the index leaking answers;
it is the discipline the skill installs (bounded broad searches, targeted reads).

This is the finding that distinguishes the design from "the index memorized the test".

## Index improvements discovered BY the agent
The S1 treatment run volunteered four concrete gaps, now journalled (16 -> 20 rows):
1. `computeBackoffMs` has exactly ONE production caller; `worker.ts` re-exports it
   without calling -> greps give a false "used everywhere" signal.
2. `maxAttemptsFor` is exported but never called; attempts come from the DB column.
3. `worker.ts` re-export vs call is a RULE worth recording.
4. A label like "shared" hides adoption scope -> promote adoption to its own question.

## Verdict
**PASS**, and the mechanism is understood rather than merely observed. Continue to
cycle 003 for statistical power.
