# explore-index

**Stop your coding agent from rediscovering your codebase.**

An [Agent Skill](https://agentskills.dev) that makes an agent consult a small, persistent
index of what it already learned about a repo *before* it fires another repo-wide grep.

Measured on 31 live agent runs: **39.9% fewer tokens to the same answer**, with zero
accuracy loss and zero false hits. p = 0.0005.

```
baseline   226,708 tokens / task  ·  20.7 tool calls  ·  9.8 turns
skill      136,156 tokens / task  ·  11.3 tool calls  ·  7.4 turns
                                ↓
                     90,551 tokens saved per task
```

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

Plus two hard budgets the skill enforces:

- **At most 3 broad searches per task**, and only when no row covers the question.
- **Read narrow, not whole.** `grep`/`glob` first, then `read` with `offset`/`limit`.
  Confirming a file exists means reading ~60 lines, not 70KB.

The index **routes; it never answers.** It stores only what a parser cannot derive —
proven absences, region pointers, conventions, and genuine repo-map overflow. No symbols,
no signatures, no line numbers, nothing a repo map already computes.

---

## Benchmarks

**Setup.** 31 live `explore` subagent runs against [GrowiaCRM](https://github.com/adityachauhan0/GrowiaCRM)
at commit `146b7f19` (1,406 code files, 6,336 symbols), on `opencode-go/space-bunny-free`.
Tokens are **provider-billed** token counts read from the agent runtime's own usage store —
not estimates. Accuracy is graded **mechanically** (required paths/symbols present in the
final answer), so "cheaper" can never mean "wrong".

Final cohort: **29 runs**, 15 baseline vs 14 skill.

| Metric | Baseline | With skill | Delta |
|---|---:|---:|---:|
| Tokens per task | 226,708 | 136,156 | **-39.9%** |
| Turns | 9.8 | 7.4 | **-24.2%** |
| Tool calls | 20.7 | 11.3 | **-45.6%** |
| Cache-read | 192,999 | 111,164 | **-42.4%** |
| Uncached input | 33,709 | 24,992 | **-25.9%** |
| Output | 5,393 | 4,086 | **-24.2%** |

| | |
|---|---|
| Welch *t* | -3.458 |
| *p*-value | **0.0005** |
| SD (baseline / skill) | 75,994 / 64,868 |
| Accuracy | 1.000 / 1.000 |
| False hits | **0** (2% threshold) |
| Total tokens saved | **1,494,426** across 29 runs |

### Per task

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

All seven favor the skill. The held-out tasks improving 11–34% is the important part: the
index isn't leaking answers, it's installing search discipline.

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

## License

MIT