# STUDY.md — does a persistent exploration index actually reduce agent token cost?

**Verdict: the effect did not replicate on a second repository.**

GrowiaCRM (31 runs) showed a large, significant reduction. Django (28 runs,
14 per arm) did not confirm it: **Welch t = −1.066, p = 0.297**. The strict
publication gate fails, and this release stays `stage: experimental`.

This document is the full record. It is deliberately written so that the
negative result is as legible as the positive one would have been.

---

## 1. The question

Coding agents repeatedly rediscover a codebase. Every session re-runs the same
repo-wide greps for the same CSRF middleware, the same password hasher, the same
ORM lookup chain — and pays full price for the context each time.

`explore-index` is an Agent Skill that gives the agent a small, persistent,
session-scoped index of what it has already learned, and instructs it to consult
that index *before* firing another broad search.

The claim under test is narrow and falsifiable:

> An agent that consults a persistent exploration index before searching will
> perform fewer tool calls and spend fewer tokens, **at equal accuracy**.

Not "better code". Not "faster". Token cost and accuracy, nothing else.

## 2. Why a second repository was required

The GrowiaCRM result rested on one repository, one model, seven tasks, and a
cohort whose baseline arm happened to be unusually expensive. That is exactly the
shape of result that fails to replicate, so replication was made a **gate**, not
a nice-to-have, before anything could be promoted.

The second repository was chosen to be *structurally different* from the first,
not merely different:

| | GrowiaCRM | Django |
|---|---|---|
| language | TypeScript / React | Python |
| files | — | 7,079 (2,932 `.py`) |
| checkout | local, commit `146b7f19` | shallow clone, commit `80ea222` |
| structure | monorepo, `apps/*/src/` | single flat `django/` package |

Django was also chosen because it is a mature, widely-read codebase where the
answer to any architectural question is genuinely non-obvious — the failure mode
being tested is realistic rather than staged.

## 3. Method

**Tasks.** 7 per repository: 3 **seeded** (the index genuinely contains the
answer, so a correct agent should route straight to it) and 4 **held-out** (no
index row by construction, so the skill must degrade gracefully). H4 deliberately
targets `django/db/models/sql/query.py` — a 122KB file with no index entry — as a
stress case.

**Arms.** Two, differing only in search strategy:

- **baseline** — "search broadly and realistically, the way an agent with no prior
  knowledge would"; try at least 3 phrasings before concluding absence.
- **treatment** — consult `.explore/INDEX.md` first; if a row covers the
  question, follow it; otherwise one narrow grep, one synonym, then widen.

An earlier harness bug gave both arms the same broad-search instruction, which
contradicted the treatment arm's `ABSENT`-is-final rule. Fixed before data
collection; verified by diff that the arms now differ only in strategy.

**Metrics.** Retrieved from the runtime store per session, not self-reported:
`provider_tokens`, `uncached_input`, `cache_read`, `output_tokens`, `turns`,
`tool_calls`. `provider_tokens == uncached_input + cache_read` was verified for
every row.

**Grading.** Deterministic and mechanical — `need` substrings plus required
paths. A run is *resolved* only if it states the answer **and** names a real
source file. False hits are a hard kill gate.

**Ordering.** Runs interleaved across tasks and arms to spread drift rather than
batching one arm at a time.

## 4. Results

### 4.1 GrowiaCRM — the original claim

| Cache-read priced at | Baseline | Treatment | Saving |
|---|---:|---:|---:|
| 1.0× (raw tokens) | 226,708 | 136,156 | −39.9% |
| 0.1× (typical cache discount) | 53,009 | 36,109 | −31.9% |
| 0.0× (fresh tokens only) | 33,709 | 24,992 | −25.9% |

n = 15 baseline / 14 treatment. Welch t = −3.458, **p = 0.0018** (exact
Student's t, df = 26.8). Accuracy 1.000 in both arms. Zero false hits. Tool
calls −45.5%, turns −24.2%.

> **Correction.** An earlier version of this report published p = 0.0005, from a
> normal approximation (`erfc(|t|/√2)`) rather than a real t-distribution. At
> this n the approximation is anti-conservative. The exact Welch p-value is
> **0.0018**. The effect remains significant; the published figure overstated it.

### 4.2 Django — the replication

| Cache-read priced at | Baseline (n=15) | Treatment (n=16) | Saving | p |
|---|---:|---:|---:|---:|
| 1.0× (raw tokens) | 116,119 | 92,504 | −20.3% | 0.287 |
| 0.1× (typical cache discount) | 26,671 | 23,586 | **−11.6%** | **0.363** |
| 0.0× (fresh tokens only) | 16,733 | 15,929 | −4.8% | 0.671 |

Accuracy **1.000** in both arms. False hits **0**. Tool calls: baseline 14.3 →
treatment 7.8 mean.

**The gate requires the effect to hold at 0.1× cache pricing. It does not:**
−11.6% at p = 0.363. No rate reaches significance on the second repository.

Mean paired saving across 13 complete task/repeat pairs was +16.9%, but the
dispersion is enormous: baseline CV = **0.590**, with two repeats of the *same
task* (H1) differing by **3.0×** (112,364 vs 337,879 tokens). At that variance
the mean is not a meaningful summary.

### 4.3 Power analysis — this is not a sample-size quibble

Cohen's *d* for the Django provider-token comparison is **~0.28** (small). At
that effect size, reaching p < 0.05 requires roughly **205 runs per arm (~410
total)**. The design ran 21 per arm as planned; 31 valid Django runs were
recorded before the budget was redirected to the H4 stress test.

So the honest statement is not "the skill does not work on Django" — it is:

> **This study is underpowered by roughly an order of magnitude to detect the
> effect size actually observed.** The result is inconclusive, not negative.

That distinction matters and is preserved everywhere in this repository. What we
can say with confidence:

- ✅ Accuracy was preserved exactly (28/28 resolved, 0 false hits) on both repos.
- ✅ Tool calls fell substantially: **+49.9% mean** reduction across paired runs.
- ❌ **Token cost reduction is not statistically established on the second repo.**

### 4.4 The mechanism, which *did* replicate

Tool-call reduction held up on Django almost as well as on GrowiaCRM, and the
trace analysis explains why. Across 26 GrowiaCRM runs:

| | baseline (n=12) | treatment (n=14) |
|---|---:|---:|
| total tool calls | 248 | 158 |
| tier-2 repo-wide greps | 50 | **16 (−68%)** |
| dead runs (no useful calls) | 16 | 13 |
| spirals | 1 | 1 |

Repo-wide greps fell by 68%. The skill demonstrably changes search behaviour in
the intended direction. It is the translation of that behaviour change into
*billed tokens* that fails to hold up.

### 4.5 What actually drives cost: turns, not tool calls

This is the study's most useful finding, and it was not the one hypothesised.

Across the Django runs:

| predictor | Pearson r with provider tokens |
|---|---:|
| **turns** | **0.982** |
| tool calls | 0.593 |

Every turn re-sends the accumulated conversation as cached context. Measured
cache-read per turn is stable at 6,000–12,700 tokens. So the causal chain is:

```
skill → fewer searches → fewer round-trips → fewer turns → fewer tokens
```

**not** `skill → fewer searches → fewer tokens`. A run can have fewer tool calls
and cost *more*, and in this dataset it did.

The clearest case is H4, the 122KB stress case, where the skill had no index row
to offer:

| H4 | turns | tool calls | provider tokens |
|---|---:|---:|---:|
| baseline | 11 | 21 | 172,873 |
| treatment (pre-Round-2) | **19** | **18** | **259,210** |

The treatment arm reduced tool calls by 3 and **increased cost by 50%**. The
skill's advice — "one grep before one big read", then `read` with
`offset`/`limit` — is correct as advice and actively harmful on a large file,
because it converts one read into many turns.

### 4.6 The hardening loop, and what it fixed

The Round 2 rule added to `SKILL.md` in direct response:

> ## Big file, many turns
> Before opening a file you suspect is large, run `wc -l <path>`. Under ~500
> lines, read it in one or two reads. Over ~500 lines, **anchor first**: one grep,
> then one read spanning that region. If you have already taken **four** reads
> against the same file, stop and either grep for the specific symbol or report
> what you have.

Effect on the only task where it could be tested:

| H4 condition | turns | provider tokens | vs baseline |
|---|---:|---:|---:|
| baseline mean (n=2) | 10.0 | 146,826 | — |
| treatment, `v2-binding` (n=1) | 19 | 259,210 | **−76.5%** |
| treatment, `v3-bigfile` (n=2) | 8.0 | 112,390 | **+23.5%** |

A −76.5% regression became +23.5%. The rule is the single most effective prompt
change in the study.

Caveat: n = 2 after the change, on one task. Directionally strong, statistically
unproven. It is reported as a promising result, not a fix.

## 5. Threats to validity

1. **Power.** d = 0.277; ~205 runs/arm needed. Underpowered by ~10×.
2. **Baseline variance.** CV = 0.590, with one task showing a 3.0× spread
   between identical repeats. A single unlucky run moves the mean substantially.
3. **Prompt drift.** `SKILL.md` was edited mid-experiment. Three treatment runs
   silently executed the new prompt while tagged as the old one. Now detected and
   corrected via timestamp-based provenance (`v2-binding` / `v3-bigfile`); without
   that fix, a prompt change would have been reported as a repeat.
4. **Model.** One model, one provider pricing structure. Cache-read pricing in
   particular is assumed, not measured.
5. **Seed quality.** The Django index was hand-seeded by me. Its quality is a
   confound: a better or worse index would move the treatment arm either way.
6. **Task phrasing.** Both arms receive identical task text. Any prompt effect is
   isolated to the strategy block, which is the intent — but it also means the
   tasks themselves were never varied.
7. **Not blinded.** Arms are labelled in the prompt. The model knows which
   strategy it is following.

## 6. Six harness bugs, all found and documented

Recorded in `HARNESS-DEFECTS.md`. None were deleted. Two of them (5 and 6) were
caught only because the published headline was re-verified against a clean
recomputation — a check that had not been performed since the numbers were first
published.

1. **Wrong grader for all repos** — a module-level `from tasks import grade`
   applied GrowiaCRM's path regex to Django, which would have reported a false-hit
   rate that was purely a path-prefix mismatch. Symptom looked like a skill
   defect; it was an apparatus defect, and it biased *in favour of the
   hypothesis*.
2. **`false_hit` regex could not match nested paths** — `django/[a-z_]+/` matches
   `django/tasks/` but not `django/tasks/base.py`, flagging an honest baseline
   answer as confidently wrong. Fixed by checking on-disk existence and, more
   importantly, by correcting the *logic*: on an absent probe, citing real files is
   evidence of absence, so `false_hit = (not says_absent) and cites_real_file()`.
3. **Mid-experiment prompt edit** — see threat 3 above.
4. **Stale seeded index row** — the seed claimed `csrf_exempt` lived in
   `django/middleware/csrf.py`; it is in `django/views/decorators/csrf.py`. This
   one is a *finding*, not a bug: the treatment agent detected the stale row by
   reading the file, reported the contradiction, and located the correct path. That
   is the confirm-read rule working as designed.
5. **A still-running session recorded as a result** — an S2 baseline run was
   written while it was still streaming, capturing turns 4 (true 8), tool_calls 9
   (true 22) and tokens 48,104 (true 134,330), with an empty final result that
   graded `resolved: false`. `record()` now refuses to write an empty
   `final_result`, and `analyze.py --audit` re-verifies stored rows against source.
6. **Repo filter dropped every legacy row** — `costs.py --repo growiacrm` matched
   **zero** rows, because GrowiaCRM predates the `repo` field and `r.get("repo")`
   returned `None`. The pooled output then reported the published −39.9% headline
   as −28.8%. Caught only by re-deriving the published figure from a clean
   recomputation. Fixed with an explicit default plus a row-count assertion in
   `benchmark_table.py` that refuses to compute an aggregate with an empty arm.

## 7. Where this leaves the project

**Not publishing v0.3.0.** The gate was set in advance — effect must hold at 0.1×
cache pricing — and it did not. Shipping anyway would be exactly the overclaim
this study was built to prevent.

What is defensible today:

- The skill **preserves accuracy exactly** and produces **zero false hits** across
  two repositories and 59 runs. That is a genuine safety property and the most
  solid result here.
- It **substantially reduces tool calls** (+49.9% paired mean; repo-wide greps
  −68%).
- Token-cost reduction is **established on one repository and not on the second**.

What would change the verdict, in order of expected value per run:

1. **Run H4 repeats under `v3-bigfile`.** The turn-explosion mechanism is
   understood and a rule addresses it; confirming it is cheap and directly tests
   the one actionable finding.
2. **Raise n substantially.** ~205/arm for a definitive answer is expensive; 50/arm
   would give a much clearer read and is achievable.
3. **Reduce baseline variance**, or use paired per-task analysis as primary
   rather than arm means. With CV = 0.590 the arm-mean comparison is poorly
   conditioned regardless of n.

---

### Provenance

- Per-run data log: [`../BENCHMARKS.md`](../BENCHMARKS.md) (generated, not hand-edited)
- Tool-call traces: [`TRACE-ANALYSIS.md`](TRACE-ANALYSIS.md)
- Cost-driver analysis: [`COST-DRIVER-ANALYSIS.md`](COST-DRIVER-ANALYSIS.md)
- Apparatus bugs: [`HARNESS-DEFECTS.md`](HARNESS-DEFECTS.md)
- Original report (corrected): [`FINAL-REPORT.md`](FINAL-REPORT.md)
- Raw records: `exp/results/runs.jsonl`