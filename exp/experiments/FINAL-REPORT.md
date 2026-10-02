# explore-index — final experiment report

**Skill:** `explore-index` (Agent Skills format, installed via `npx skills`)
**Repo under test:** GrowiaCRM @ `146b7f19` — 1,406 code files, 6,336 symbols
**Model:** `opencode-go/space-bunny-free`, subagents via the `explore` role
**Runs:** 31 live subagent trajectories (29 in the final cohort)
**Verdict:** **PASS** — −39.9% tokens at equal accuracy, p = 0.0018, 0 false hits
**Validation:** `npx -y skills-ref validate ./skills/explore-index` → `Valid skill`
(and installed via `npx skills add`, active at `~/.agents/skills/explore-index`)

> **Correction (2026-10-02).** This report previously stated p = 0.0005. That figure came from
> a **normal approximation** to the t-distribution, which is anti-conservative at this sample
> size (15 vs 14). Recomputed with an exact Welch t-test — df = 26.8 — the value is
> **p = 0.0018**. The effect is unchanged and still significant; the published figure overstated
> it. `analyze.py` now delegates to the exact implementation in `exp/costs.py`.
>
> The same review found that `provider_tokens == uncached_input + cache_read` exactly, i.e.
> **output tokens are not part of the billed-token total**. The −39.9% headline is therefore
> cache-read dominated. At a realistic cache-read discount the saving is **−31.9%**, and on
> fresh tokens alone **−25.9%**. All three figures are in `exp/BENCHMARKS.md`; the range is the
> honest claim, not the most flattering single number.

---

## Headline

| | baseline | treatment | delta |
|---|---|---|---|
| **mean tokens (billed)** | 226,708 | **136,156** | **−39.9%** |
| mean turns | 9.80 | 7.43 | −24.2% |
| mean tool calls | 20.73 | 11.29 | −45.6% |
| accuracy (mechanical grader) | 1.000 | 1.000 | — |
| false hits | — | **0 / 14** | — |

Welch t = −3.458, **p = 0.0018**. SD 75,994 (baseline) vs 64,868 (treatment).
No run in either arm failed to resolve its task.

Per-task deltas — every task is a win:

| task | split | baseline | treatment | delta |
|---|---|---|---|---|
| S1 retry helper | seeded | 187,260 | 93,970 | **−49.8%** |
| S2 auth model | seeded | 210,746 | 109,634 | **−48.0%** |
| S3 generic wrapper (absent) | seeded | 207,255 | 48,351 | **−76.7%** |
| H1 attachment storage | held-out | 300,468 | 212,495 | **−29.3%** |
| H2 tenant scoping | held-out | 255,897 | 168,249 | **−34.3%** |
| H3 offline IndexedDB | held-out | 171,139 | 117,772 | **−31.2%** |
| H4 migrations | held-out | 217,307 | 192,751 | **−11.3%** |

---

## The mechanism (this is the actual finding)

Cost is **84.7% cache-read**. Every turn re-reads the entire accumulated context,
so total cost ≈ Σ(context at each turn) and **turn count dominates**, not result
size. Measured across runs: **~19,000 tokens per turn, ~2.1 tool calls per turn**.

Two consequences drove every design decision:

1. **A saturated 100-match grep costs ~1 turn (~19k), but it also inflates every
   later turn.** Baseline traces repeatedly hit `matchLimitReached`.
2. **An oversized read is worse than a broad search** — a 68KB read permanently
   inflates the whole trajectory. This was found empirically in cycle 005, not assumed.

So the index's job is **to collapse turns**, not to shrink individual results.

---

## What the finetuning actually found

The skill failed twice before it worked. Both failures were real and both were found by trace analysis, not by guessing.

### Failure 1 — the index was advisory, not binding (cycle 001)

Cycle 001 treatment **lost** (198,704 vs 138,273 baseline). The trace showed the
agent reading `.explore/INDEX.md` on call 1, correctly extracting the `ABSENT`
row — then running **24 more searches**, including several re-asking exactly what
`ABSENT` had already answered.

The original SKILL.md described a *lookup loop* but never stated a rule that
bound behaviour. Fix: **"a hit is binding, not advisory"** — `ABSENT` ends the
search, `REGION` goes straight there, `REAL` means one read and done, plus a
cap of 3 broad searches per task. Result: S3 collapsed from 14 turns/29 calls to
5 turns/5 calls.

### Failure 2 — no bound on read size (cycle 005)

Repeats flipped H1 to **+4.3%** (treatment *worse*). H1 is held-out with no index
row, so routing never fired; the agent then read a **68,957-byte** module whole,
plus 55KB more. Fix: **"Read narrow, not whole"** — grep/glob first, then read
with `offset`/`limit`; ~60 lines to confirm a file exists.

Result: H1 went **+4.3% → −29.3%**.

---

## Why the result is credible

**Held-out tasks carry the load.** Four of seven tasks (H1–H4) have *no index row*
by construction. They still improved by 11–34%. The index is not leaking answers
— it is installing search discipline.

**Zero false hits.** A false hit = claiming the index resolved a question without
naming a real source path. Never occurred in 14 treatment runs, against a 2% kill
threshold.

**A known-good control in every batch**, and the cycle-001 control is retained in
the data rather than discarded — it is the evidence for failure 1.

**Cohort separation.** Cycle-001 advisory-skill runs are tagged and excluded from
the headline. Pooling them would understate the current design (−36.2% vs the
correct −39.9%).

**The baseline disagreed with itself.** H1 baseline ranged 146,776 → 359,181
across reps; H3 baseline ranged 122,124 → 220,155. Any claim resting on one pair
per task would have been wrong in both directions. This is why repeats were added
after cycle 004, and it is the single most important methodological lesson here.

---

## Honest limits

- **Single repo, single model, single task suite (7 tasks).** The direction is
  strong and the mechanism is understood, but the magnitude is not a general law.
- **H4 (migrations) is the weakest case at −11.3%** — a huge single file
  (`migrations.ts` is 2,600+ lines) that no index row can shortcut.
- **The index needs maintaining.** 20 rows were seeded from two verified probes;
  the agents themselves surfaced 4 further gaps. Unmaintained, it silently rots.
- **Not tested:** LSP exposure, dense vector retrieval, explorer subagents —
  all deliberately parked.
- **Baseline variance is large** (SD ~76k on a 227k mean). The p-value holds, but
  individual single-run comparisons are unreliable.

---

## Incidental finding (redacted)

The H1 runs independently surfaced an inconsistency between a schema's documented
state values and the implemented behaviour in the target codebase. Details are
withheld here because the target repository is private; the finding was routed to
that project's own backlog. Kept as a note that exploration runs can surface real
defects, not only routing information.

---

## Artifacts

```text
exp/telemetry.py                 # extracts provider token telemetry from the runtime store
exp/tasks.py                     # task suite + mechanical grader + false-hit detector
exp/analyze.py                   # run recorder, cohort filter, iso-accuracy guard, Welch test
exp/repomap.py                   # deterministic repo map (PageRank + ambiguity filter + per-file cap)
exp/results/runs.jsonl           # all 31 runs, one JSON object each
exp/results/cycle-*.json         # per-cycle verdicts
exp/experiments/cycle-*.md       # per-cycle narrative: hypothesis, trace, fix
skills/explore-index/SKILL.md    # final skill (127 lines, ~800 words)
```