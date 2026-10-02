# explore-index

**Stop your coding agent from rediscovering your codebase on every single run.**

[![npm](https://img.shields.io/npm/v/explore-index.svg)](https://www.npmjs.com/package/explore-index)
[![npm downloads](https://img.shields.io/npm/dm/explore-index.svg)](https://www.npmjs.com/package/explore-index)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/adityachauhan0/explore-index/blob/main/LICENSE)
[![skills](https://img.shields.io/badge/Agent%20Skills-1.0-orange.svg)](https://agentskills.dev)

An [Agent Skill](https://agentskills.dev) for **Claude Code, OpenCode, Cursor and Codex** that
makes an agent consult a small, persistent index of what it already learned about a repo
*before* it fires another repo-wide grep.

## The measured effect

Two repositories, 59 controlled A/B agent runs, equal accuracy and zero false hits
in every arm. Reported as a range rather than a single headline number, because
~85% of billed tokens are cache-read and the saving depends on how you price those.

| Cache-read priced at | GrowiaCRM baseline | +skill | Django baseline | +skill |
|---|---:|---:|---:|---:|
| 1.0× (raw tokens) | 226,708 | **136,156** (−39.9%) | 116,119 | 92,504 (−20.3%) |
| 0.1× (typical cache discount) | 53,009 | **36,109** (−31.9%) | 26,671 | 23,586 (−11.6%) |
| 0.0× (fresh tokens only) | 33,709 | **24,992** (−25.9%) | 16,733 | 15,929 (−4.8%) |

| | GrowiaCRM (n=15/14) | Django (n=15/16) |
|---|---|---|
| significance (1.0×) | **p = 0.0018** | p = 0.287 |
| significance (0.1×) | **p = 0.0082** | **p = 0.363** |
| accuracy | 1.000 | 1.000 |
| false hits | 0 | 0 |
| tool calls | −45.5% | −45.2% |

**Read the two columns differently, because they say different things.**

On **GrowiaCRM** the effect is large and significant at every cache-pricing rate.

On **Django** it is *not statistically established* at any rate. The point estimate
is consistently favourable and tool calls fell by the same ~45%, but the variance is
so high that the comparison does not clear significance. With Cohen's *d* ≈ 0.28,
roughly **205 runs per arm** would be needed to resolve an effect this size — the
study ran 21. That is a power limitation, not a refutation, and it is the reason
this stays `stage: experimental`.

**Why tool calls fall but tokens don't always follow.** Turns, not searches, drive
the bill: across the Django runs the correlation between turns and billed tokens is
**r = 0.982**, against 0.593 for tool calls. Every round-trip re-sends the
accumulated context. The causal chain is `skill → fewer searches → fewer round-trips
→ fewer tokens`, and an agent can make fewer searches while spending more if it
spreads the work over more turns. This study found and fixed exactly that failure
mode (see [STUDY.md §4.5–4.6](STUDY.md)); it is the main thing that would need to
work reliably for the token win to hold.

**Full data and method** — every run, every session, the failures, and six harness
bugs found along the way:

- [`STUDY.md`](STUDY.md) — the method, both results, power analysis, threats to validity
- [`BENCHMARKS.md`](BENCHMARKS.md) — generated per-run log
- [`exp/experiments/`](exp/experiments/) — tool-call traces, cost-driver analysis, harness defects

---


## Install

```bash
# from GitHub (recommended)
npx skills add adityachauhan0/explore-index

# global, for every agent on this machine
npx skills add adityachauhan0/explore-index -g -y

# pick a single agent
npx skills add adityachauhan0/explore-index -a cursor -y
```

Works with any [Agent Skills](https://agentskills.dev) client — Claude Code, OpenCode,
Cursor, Antigravity, Codex and the rest. It's a plain skill directory: no runtime, no
dependencies, no network calls.

> **On npm:** the package is also published as [`explore-index`](https://www.npmjs.com/package/explore-index),
> but `npx skills add` resolves its argument as a **GitHub source**, not an npm package.
> Installing it from npm means unpacking the tarball and copying the skill directory —
> use the GitHub command above unless you're wiring it into your own tooling.


<details>
<summary>Manual install</summary>

```bash
git clone https://github.com/adityachauhan0/explore-index
cp -r explore-index/skills/explore-index ~/.agents/skills/
```

</details>

---

## The problem

Ask an agent to find something in a repo it has never seen and it will do this:

```
grep "retry" repo-wide  →  412 matches
grep "backoff"          →  96 matches
grep "resilient"        →  11 matches
read the 4 most promising files
grep "retry" again, differently, because nothing was conclusive
...
```

It re-derives facts your repo already settled. Worse, **every one of those steps is
expensive twice** — once for the output, and again on every subsequent turn, because each
turn re-reads the whole accumulated context. In our measurements **84.7% of billed tokens
were cache-read**, roughly **19,000 tokens per turn**.

So the cost isn't the search. It's the *number of turns* the search forced.

## The fix

Before a broad search, the agent reads `.explore/INDEX.md` — a four-field-per-line file
mapping concepts to where things live:

```
shared retry helper :: ABSENT :: src/** :: searched backoff, retry, sleep; every service inlines it
auth entry point    :: REGION :: src/auth :: middleware chain starts at index.ts
imports use @/ alias :: RULE :: tsconfig paths; never relative parent paths
billing totals       :: REAL :: packages/billing/src/totals.ts :: not in repomap, small module
```

Four entry kinds, and **a hit is binding, not advisory**:

| Kind | Meaning | What the agent must do |
|---|---|---|
| `ABSENT` | proven not to exist in scope | **Stop searching.** Do not try the synonym family. |
| `REGION` | a concept lives here | Go straight there. Don't sweep the repo first. |
| `RULE` | a convention or gotcha | Follow it. It replaces a search, not a step of one. |
| `REAL` | the repo map missed it | Read that one file. Done. |

Plus the three rules that actually bind behaviour:

- **No index row, no broad search.** Consult `.explore/INDEX.md` first; if no row
  covers the question, one narrow grep, one synonym, then widen.
- **Count-anchored stop.** If you are about to run your **fourth** repo-wide
  `grep`/`glob` on a task, you skipped the index — stop and read it.
- **Big file, many turns.** `wc -l` before opening a suspected-large file. Under
  ~500 lines, read it whole; over that, anchor with one grep and one spanning
  read. Four reads against one file is the cap — a fifth is a symptom, not a search.

The index **routes; it never answers.** It stores only what a parser cannot derive —
proven absences, region pointers, conventions, and genuine repo-map overflow. No symbols,
no signatures, no line numbers, nothing a repo map already computes.

---

## Benchmarks

**Setup.** Live `explore` subagent runs against two repositories on
`opencode-go/space-bunny-free`. Tokens are **provider-billed** counts read from the agent
runtime's own usage store — not estimates. Accuracy is graded **mechanically** (required
paths/symbols present in the final answer), so "cheaper" can never quietly mean "wrong".

### GrowiaCRM — where the effect is established

[GrowiaCRM](https://github.com/adityachauhan0/GrowiaCRM) at `146b7f19`, 1,406 code files.
Final cohort **29 runs**, 15 baseline vs 14 skill.

| Metric | Baseline | With skill | Delta |
|---|---:|---:|---:|
| Tokens per task | 226,708 | 136,156 | **-39.9%** |
| Turns | 9.8 | 7.4 | **-24.2%** |
| Tool calls | 20.7 | 11.3 | **-45.6%** |
| Cache-read | 192,999 | 111,164 | **-42.4%** |
| Uncached input | 33,709 | 24,992 | **-25.9%** |
| Output | 5,393 | 4,086 | **-24.2%** |

Welch *t* = -3.458, ***p* = 0.0018**. SD 75,994 / 64,868. Accuracy 1.000 / 1.000.
False hits **0**. Total saved **1,494,426 tokens** across 29 runs.

Three **seeded** tasks (covered by seeded index rows) and four **held-out** tasks with *no
matching index row by construction* — the held-out set is the honest test.

| Task | Split | Baseline | With skill | Delta |
|---|---|---:|---:|---:|
| `S1` retry helper | seeded | 187,260 | 93,970 | **-49.8%** |
| `S2` auth model | seeded | 210,746 | 109,634 | **-48.0%** |
| `S3` generic wrapper (absent) | seeded | 207,256 | 48,351 | **-76.7%** |
| `H1` attachment storage | held-out | 300,468 | 212,495 | **-29.3%** |
| `H2` tenant scoping | held-out | 255,898 | 168,249 | **-34.3%** |
| `H3` offline IndexedDB | held-out | 171,140 | 117,772 | **-31.2%** |
| `H4` runtime migrations | held-out | 217,307 | 192,751 | **-11.3%** |

All seven favor the skill. The held-out tasks improving 11-34% is the important part: the
index isn't leaking answers, it's installing search discipline.

### Django — where it did not replicate

[django/django](https://github.com/django/django) at `80ea222`: 7,079 files, Python, a
single flat package. Deliberately a different language and structure from GrowiaCRM.
**31 valid runs**, 15 baseline vs 16 skill.

| Metric | Baseline | With skill | Delta | *p* |
|---|---:|---:|---:|---:|
| Tokens per task | 116,119 | 92,504 | -20.3% | 0.287 |
| Uncached input (0.1x cache) | 26,671 | 23,586 | -11.6% | 0.363 |
| Uncached input (0.0x cache) | 16,733 | 15,929 | -4.8% | 0.671 |
| Tool calls | 14.3 | 7.8 | **-45.2%** | — |

Accuracy 1.000 / 1.000, false hits **0** — the safety property held perfectly.

Not significant at any rate. The point estimate is always favourable and the tool-call
reduction matches GrowiaCRM almost exactly, but run-to-run variance on this repository is
so large (baseline CV 0.59) that the arm means do not separate. Two identical repeats of
one task differed by 3.0x. With *d* ~ 0.28 this needs ~205 runs/arm to resolve; 21 were
run. **Underpowered, not refuted.**

One result worth keeping: `H4`, a 122KB file the index does not mention, initially made
the skill look **76% worse** — it cut tool calls but paged through the file over 19 turns.
The `Big file, many turns` rule was written specifically to fix that, after which the same
task moved to **+23.5%**. That is the clearest evidence in the study that the prompt is the
active ingredient.

### What the traces actually show

The same task, both arms:

```
BASELINE — 22 calls, 198,326 tokens
  bash   ls -la + cat manifests              16,694 B
  glob   **/*.{ts,tsx,js...}                  6,851 B
  grep   repo-wide                             5,219 B
  ...18 more exploratory calls...
  grep   repo-wide   ← matchLimitReached   100,000 B
  grep   repo-wide   ← matchLimitReached   100,000 B
  grep   repo-wide   ← matchLimitReached   100,000 B
  grep   repo-wide   ← matchLimitReached   100,000 B

WITH SKILL — 3 calls, 27,451 tokens
  read   .explore/INDEX.md                     6,118 B
  grep   withInline... (literal anchor)           68 B
  read   apps/api/src/modules/jobs/backoff.ts  5,412 B
```

An `ABSENT` row ends a spiral that the baseline couldn't escape.

---

## How it compares

| | Repo map (aider-style) | RAG / vector retrieval | LSP tooling | **explore-index** |
|---|---|---|---|---|
| Derived or asserted | Derived | Embedded | Derived | **Asserted, human-curated** |
| Catches *"this doesn't exist"* | No | Weakly | No | **Yes — `ABSENT` rows** |
| Catches repo conventions | No | No | No | **Yes — `RULE` rows** |
| Requires a running server | No | **Yes** | **Yes** | **No** |
| Adds process latency | No | Yes | Yes | **No** |
| Token cost of consulting | Low | Medium | **High (measured)** | **~6 KB, once** |
| Goes stale silently | Rarely | Sometimes | No | **Yes — `verify.sh` guards it** |

> We deliberately parked LSP exposure: exposing language-server tooling to the agent
> **increased** token usage in earlier trials. Vector retrieval and dedicated explorer
> subagents are unmeasured — this skill is the cheap, dependency-free baseline they
> would have to beat.

---

## Honest limits

- **One repo, one model, 7 tasks.** The direction is strong and the mechanism is measured,
  but the *magnitude* isn't a universal law. The skill is marked `stage: experimental`.
- **Baseline variance is large** — H1 baseline ranged 146,776 → 359,181 tokens across
  repeats of an identical task. Single-run comparisons are unreliable; that's why every
  number here is pooled over repeats, and why we ship the negative results too.
- **`H4` is the weak case at -11.3%.** One 2,600-line `migrations.ts` that no index row can
  shortcut. Big single files are where this skill does least.
- **Part of the win is preventing a baseline pathology** (saturated greps). A baseline that
  never saturated a grep would close part of the gap. `H4`, with nothing to prevent, shows
  the smaller honest number.
- **The index rots.** `verify.sh` catches dead anchors; run it after editing files several
  rows point at.

## How this was built

The skill failed twice before it worked, and both failures are in the repo:

1. **Advisory → binding.** v1 *lost* (198,704 vs 138,273). Traces showed the agent reading
   the index, correctly extracting an `ABSENT` row, then running 24 more searches anyway.
   Fix: "a hit is binding, not advisory."
2. **Unbounded reads.** Repeats flipped one task to **+4.3%** (skill *worse*) after a
   68,957-byte whole-file read permanently inflated the trajectory. Fix: "read narrow, not
   whole." That task went **+4.3% → -29.3%**.

Both failed cohorts are kept in the dataset as evidence, not deleted.

- Design + experiment protocol: [`INSTRUCTIONS.md`](INSTRUCTIONS.md)
- Architecture: [`explore-index-architecture.md`](explore-index-architecture.md)
- Per-cycle narrative: [`exp/experiments/`](exp/experiments/)
- Raw per-run telemetry: [`exp/results/runs.jsonl`](exp/results/runs.jsonl)

---

## Usage

Once installed, the agent applies it automatically at cold subsystem boundaries. To seed a
repo:

```bash
cd your-repo
mkdir -p .explore

bash <skill>/scripts/journal.sh "shared retry helper" ABSENT "src/**" \
  "searched backoff, retry, sleep"
bash <skill>/scripts/reindex.sh
bash <skill>/scripts/verify.sh
```

`journal.md` is the source of truth; `INDEX.md` is generated deterministically from it.
Add `.explore/` to `.git/info/exclude` to keep it session-local.

**Below ~20 files, ignore all of this** — just read the repo, it fits.

---

## FAQ

**Does this reduce cost, or just token count?**
Both. The saving is 90% cache-read tokens (81,835 of the 90,551 saved per task), which are
billed at a steep discount versus fresh input — so the dollar saving is real, though smaller
than raw token count suggests. Output tokens barely change: both arms write similar-length
reports, because the skill routes the agent, it doesn't shorten answers.

**Will it give my agent wrong answers?**
That is the explicit design constraint. The index **routes; it never answers.** It stores only
what a parser can't derive — proven absences, region pointers, conventions, repo-map overflow.
No symbols, no signatures, no line numbers. A wrong row can cost one wasted hop, never a
confident wrong answer. Across 14 treatment runs there were **0 false hits** against a 2%
kill threshold, and accuracy was 1.000 in both arms under a mechanical grader.

**Why does it help so much when my context window is huge?**
Because cost isn't the search — it's the *turns* the search forces. 84.7% of billed tokens were
cache-read, roughly 19,000 per turn, and every turn re-reads the entire accumulated context.
The skill cuts turns by 24.2%; that compounding is where the 39.9% comes from.

**Does it work for a repo I've never seen?**
Yes, and that's the tested case — the four `held-out` tasks had no matching index row by
construction and still improved 11–34%. A cold agent checks the index, finds nothing, and
falls through to normal search under a 3-search cap.

**Will the index go stale?**
It can. `verify.sh` validates every anchor and exits non-zero on dead rows; run it after
editing files that several rows point at. Unmaintained, it silently rots — which is why
`stage: experimental`.

**How is this different from a repo map (like aider's)?**
A repo map derives structure deterministically from imports. This skill stores only what a
parser *cannot* know: "this symbol provably doesn't exist", "this repo does X instead of Y",
"the real implementation lives over there". They compose — the skill explicitly tells the
agent not to duplicate symbols or signatures. In our repo, a PageRank + ambiguity-filtered
map compressed 3.56M tokens of source to 904 tokens (~3,935×).

## License

MIT © [Aditya Chauhan](https://github.com/adityachauhan0)