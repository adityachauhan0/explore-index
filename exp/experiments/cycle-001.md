# Cycle 001 — first live interleaved A/B

## Setup
- Repo: GrowiaCRM @ 146b7f19, `.explore/` present with 16 seeded rows.
- Tasks: S1 (seeded, retry helper), S3 (seeded, absent-probe).
- Arms interleaved. Metric: sum of per-turn `providerTokens` (billed volume).
- Grader: mechanical fact+path coverage from `exp/tasks.py`.

## Results
| task | arm | tokens | turns | tools | resolved | coverage |
|---|---|---|---|---|---|---|
| S1 | baseline | 138273 (cycle-000 probe) / 198560 (c1) | 8 / 9 | 15 / 23 | yes | 1.00 |
| S1 | treatment | 198704 | 11 | 25 | yes | 1.00 |
| S3 | baseline | 216185 | 11 | 25 | yes | 1.00 |
| S3 | treatment | 208901 | 14 | 29 | yes | 1.00 |

**Accuracy held at 1.00 in every arm. No false hits. But treatment spent MORE
tokens on S1 and only matched baseline on S3.** No efficiency win.

## Trace diagnosis (the important part)

Cost is ~85% cache-read; each turn re-reads the whole accumulated context, so
total ≈ Σ(context at each turn) and **turn count dominates**.

Treatment call log for S1:
1. read `.explore/INDEX.md` (5100B)  <- index consulted correctly
2-5. glob backoff/retry/retr + grep  <- still swept broadly
7. `withRetry|fetchWithRetry|sendWithRetry|retryWith|...` -> **100000B saturated**
   ...23 further calls, including several that re-ask what an ABSENT row answered.

The index told the agent the answer but did not **constrain** it. Every redundant
broad grep costs a full turn (~15-20k tokens of cache-read) and, worse, each one
enlarges the context that all later turns must re-read — so one saturated grep
compounds.

## Hypothesis for cycle 002
The skill describes a *lookup loop* but never states a stopping rule that binds.
Fix: make the ABSENT row terminal and require the agent to convert a routing row
into exactly ONE targeted read. Add an explicit "if a row answers this, stop
searching" rule and a budget hint (max ~3 broad searches per task).
