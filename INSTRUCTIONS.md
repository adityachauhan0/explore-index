# INSTRUCTIONS — Explore Index Skill: A/B Experiment & Finetune Loop

> **This document is the protocol. Executing it is a separate act.**
> Status: written 2026-10-02. Nothing in this repo has been built or measured yet.
>
> Goal: produce an `npx skills`-compatible skill whose use measurably reduces exploration
> tokens **at iso-accuracy** versus not having it. Iterate until that is true, or until a
> kill criterion fires and we stop honestly.

---

## 0. The one metric that decides everything

**Tokens-to-success at iso-accuracy.** Not token count.

> *"A method that 'saves tokens' by failing earlier has saved nothing."*
> — [arXiv:2608.13568](https://arxiv.org/abs/2608.13568)

Concretely, for every batch:

```
primary   = total_tokens_input + total_tokens_output
         ─────────────────────────────────────────────  (lower is better)
            tasks_resolved

guardrail = tasks_resolved / tasks_total             (must not drop)
```

**If the guardrail drops at all, the run is void.** A skill that routes the agent to the
wrong file and then confidently edits it is worse than no skill, and it will *look* like a
token win. Accuracy is checked first; tokens are only read after accuracy is confirmed equal.

---

## 1. The artifact under test

### 1.1 Package layout — must satisfy the Agent Skills spec

`npx skills` is [vercel-labs/skills](https://github.com/vercel-labs/skills), current `latest`
is **1.7.0**. It installs anything conforming to the
[Agent Skills specification](https://agentskills.io/specification). Hard requirements:

```
skills/explore-index/
├── SKILL.md              # required. frontmatter + body
├── references/           # loaded on demand — keep the bulk here
│   ├── PROTOCOL.md       # the lookup loop, in detail
│   ├── ENTRY-FORMATS.md  # the 4 entry schemas + worked examples
│   └── MEASUREMENT.md    # what to log, how
└── scripts/              # deterministic, zero model judgment
    ├── journal.sh        # append one entry line
    ├── reindex.sh        # journal -> index root + buckets + metrics
    └── verify.sh         # anchor-grep every row, mark dead
```

**Frontmatter constraints that are easy to get wrong** (these are validation failures, not
style nits):

| Field | Rule |
|---|---|
| `name` | 1–64 chars, `a-z0-9-` only, no leading/trailing hyphen, no `--`, **must equal parent directory name** |
| `description` | 1–1024 chars, must state *what it does* **and** *when to use it* |
| `license` | optional |
| `compatibility` | optional, ≤500 chars |
| `metadata` | optional, flat string→string map |
| `allowed-tools` | optional, space-separated, experimental |

Validate before every experiment run:

```bash
skills-ref validate ./skills/explore-index        # spec conformance
npx skills add ./skills/explore-index --list       # CLI can parse it
npx skills add ./skills/explore-index -a opencode -g -y   # actually installs
```

A skill that fails validation is not a data point, it is a broken run. Check first.

### 1.2 The token-budget rule that governs the whole design

The spec's progressive-disclosure ladder is the design constraint, not an afterthought:

| Layer | Loaded | Budget |
|---|---|---|
| `name` + `description` | **at startup, for every skill** | ~100 tokens |
| `SKILL.md` body | on activation | < 5,000 tokens recommended, **< 500 lines** |
| `references/`, `scripts/` | only when needed | as small as possible |

Two consequences that must not be violated during finetuning:

1. **The `description` is the only always-attached text.** It must trigger on "I need to find
   where X lives" and must *not* trigger on ordinary edits. Over-broad triggering taxes every
   session in the repo, including the ~95% of turns that never explore.
2. **`SKILL.md` must stay small.** If the finetune loop keeps appending guidance to the body,
   stop and move it to `references/`. A body that grows past 500 lines is a regression, even
   if it improves accuracy.

### 1.3 What the skill must not do

Hard constraints carried from the research. Violating any of these invalidates the run.

- **No LSP tool exposure.** Measured token *increase*: +6% Opus, +118% Sonnet
  ([2608.13568](https://arxiv.org/abs/2608.13568)). Permitted inside `reindex.sh` (build time);
  never as something the agent calls.
- **No symbol→file entries.** A tree-sitter repomap does that deterministically for ~87 tokens
  where reading source costs ~12,000. The skill covers only what a parser cannot know:
  proven-absent, concept→region, conventions, and cross-file wiring.
- **No line-number coordinates.** They rot on every edit above them, including the agent's own.
  Anchor to a literal string and validate with one `grep`.
- **No file contents in the index.** The index routes; it never answers.
- **No summaries of code.** Summary drift is the documented failure mode
  ([2601.16746](https://arxiv.org/abs/2601.16746)).

---

## 2. The finetune loop

Run this cycle until a stop criterion fires. Each cycle produces exactly one change.

```
        ┌──────────────────────────────────────────┐
        │                                          │
        ▼                                          │
  [ baseline ] → [ variant ] → [ A/B batch ] → [ analyze traces ] → [ ONE change ] ──┘
                  (skill edited)      (interleaved)     (toolcall-level)
```

### Step 1 — Baseline

Run the task set with **no skill installed**. This is the control and it is re-measured
inside every later batch, not just once at the start.

### Step 2 — Change one thing

One edit per cycle. The changes worth trying, in priority order:

| # | Change | Expected effect |
|---|---|---|
| 1 | `description` trigger wording | consultation rate — too narrow = never fires |
| 2 | index consult gate (cold-subsystem-only vs every search) | the single biggest cost lever |
| 3 | entry schema: does `note` earn its tokens? | hit rate vs size |
| 4 | negatives-only vs negatives+concepts | whether concepts are noise |
| 5 | index root in prefix vs on-demand read | marginal token cost |
| 6 | anchor literal length | false-hit rate |

### Step 3 — A/B batch

- **Arm A (control):** baseline, no skill.
- **Arm B (treatment):** skill installed.
- **Interleave.** Alternate tasks between arms. Never run all of A then all of B.
- **≥ 5 seeds per task per arm.** Single-run comparisons are noise.
- **Re-run the control inside the batch.** A control that scored 16/16 earlier has scored 3/5
  inside a batch under load. A batch without a control proves nothing.

### Step 4 — Trace analysis (this is the actual job)

Token totals tell you *that* you won. They do not tell you *where to fix it*. For every run,
reconstruct the **toolcall sequence** and classify each call:

```
tier 0  index consult / repomap read      → the win, target for more of these
tier 1  grep / glob / single file read    → the fallback, acceptable
tier 2  multi-file sweep, repeated reads  → the bill. convert these downward
deadrun read the same file twice          → pure waste, always fixable
spiral  3+ greps for one absent symbol    → should have been a negatives entry
drift   read files never referenced again  → wasted exploration, tighten the gate
```

Then write, per run: **where it went right, where it went wrong, and which single change
would move the most tier-2 calls to tier 0.** The third part is the finetune input.

### Step 5 — Promote or revert

- Promote only if: primary metric improves **and** guardrail holds **and** false-hit rate
  < 2%.
- Revert immediately on any false-hit spike. Do not "give it more cycles" — that is how a
  quietly-lying index ships.

---

## 3. Stop criteria

Stop and report honestly when **any** of these fires. Do not rationalize past them.

| # | Criterion | Meaning |
|---|---|---|
| S1 | guardrail accuracy drops > 2pp in any arm | the skill routes wrong; it lies |
| S2 | false-hit rate > 2% | **design failure, not a tuning knob** |
| S3 | 5 consecutive cycles with no primary-metric improvement | the ceiling is structural |
| S4 | primary metric never beats baseline across all cycles | no win; kill the project |
| S5 | token savings exist only at the cost of accuracy | a fake win |
| S6 | skill exceeds 500 lines / 5,000 tokens in the body | flywheel broken; re-architect |

**S2 deserves emphasis.** A false hit does not announce itself — it produces a confident
answer built on the wrong span. Aggregate savings can look excellent while this climbs. It is
the only failure mode that gets *worse* as the index gets more valuable.

---

## 4. Task set design

Fixed, versioned, and **held out** from the skill's own authoring. A task set the skill was
tuned against measures memorization, not efficiency.

### Arm A — single-symbol localization (expect ~0 win)

- "Where is `X` defined?"
- "What calls `Y`?"

Run these to *falsify*. The prior says structural indexing pays off on multi-file work, so
single-symbol should be near-flat. If it shows a large win, suspect leakage.

### Arm B — multi-file change (expect the win)

- "Add rate limiting to the `/api` routes" — touches middleware, config, tests.
- "Change the auth token expiry" — spans schema, service, UI, tests.

This is where structural ranking pays off ([2606.22417](https://arxiv.org/abs/2606.22417)).

### Arm C — absent-symbol probes (expect the largest single win)

- Ask for a symbol that does not exist, e.g. `retryWithBackoff`, and require the agent to
  correctly report it is absent.
- Baseline behaviour: retry synonyms, open files, burn ~5k tokens.
- These test the negatives table, which is the highest value per entry in the design.

### Eligibility gates

- **Repo ≥ 20 files.** Below that, reading everything fits in context and the skill cannot win
  ([agentpatterns](https://agentpatterns.ai/context-engineering/repository-map-pattern/)).
- **Two repos minimum**, one of which the skill was never tuned on.
- **The harness must live outside the indexed tree.** A test file containing the query string
  becomes its own top-ranked candidate and silently poisons localization scores.

---

## 5. Executing runs with Space Bunny subagents

Subagents are dispatched with the `task` tool, model **`opencode-go/space-bunny-free`**
(confirm the exact key with `mavis agent list` before the first batch).

Each subagent gets a **self-contained** briefing. It does not inherit this conversation.

### Required briefing contents

1. Task prompt, verbatim from the task set.
2. Repo path and the arm it is running (A or B).
3. Whether the skill is installed — and if so, **do not mention that it exists in the
   baseline arm.** Telling the agent an index exists changes its behaviour and destroys the
   comparison.
4. Instruction to log every toolcall with its token cost.
5. Instruction to state the final answer location explicitly, so localization can be scored
   mechanically.

### Scoring

Score mechanically, not by vibes. From the trace:

- **resolved** — did it identify the correct file/symbol?
- **tokens** — sum of input + output across the run
- **rounds** — number of assistant turns
- **tier histogram** — from §Step 4
- **false hits** — index said X, anchor resolved to something else

### Concurrency

Do not exceed the parent session's child limit (default 4). Parallel writers must own
disjoint files; for read-only exploration tasks that is satisfied by giving each subagent its
own worktree or read-only checkout.

---

## 6. Known traps

Each of these has already cost me time. Assume they are live.

| Trap | Consequence | Guard |
|---|---|---|
| No control inside the batch | deltas are load artifacts | control re-run every batch |
| Sequential arms | arms measured under different load | interleave |
| Harness inside the indexed tree | query string becomes a top hit | keep harness outside |
| Task set used for tuning | measures memorization | held-out set, second repo |
| Withdrawn papers treated as settled | building on sand | check the arXiv abs page for a withdrawal banner |
| Reading token counts without accuracy | fake wins | iso-accuracy gate, always |
| Growing `SKILL.md` during finetune | flywheel breaks silently | 500-line / 5k-token cap |
| Trusting a stale index | confident wrong answers | anchor-grep validation on every consult |

---

## 7. Report format

Each cycle produces one file: `experiments/cycle-NNN.md`.

```markdown
# Cycle NNN — <the single change made>

## Result
primary metric   baseline X → treatment Y   (Δ%)
guardrail        accuracy A% vs B%          (PASS / VOID)
false-hit rate   Z%                          (must be < 2%)

## Trace findings
Right:      <what worked>
Wrong:      <what wasted tokens — cite specific toolcalls>
Deadruns:   <count>
Spirals:    <count>
Tier shift: <tier-2 calls before → after>

## Decision
promote / revert / iterate
Reason:      <one sentence>
```

Cycle over. No verdict yet.

---

## 8. Phasing

Build order is strict — each phase is independently falsifiable, and do not run ahead.

| Phase | Build | Measure | Abort if |
|---|---|---|---|
| 0 | tree-sitter repomap baseline | the control itself | — |
| 1 | skill skeleton, spec-valid, negatives only | tier-2 rate | no drop in tier-2 |
| 2 | concepts + conventions | hit rate | hit rate < 25% |
| 3 | journal + reindex scripts | build reproducibility | not reproducible |
| 4 | edit hook | staleness | measurable staleness remains |
| 5 | prefix-resident index root | marginal cost | no change in consult rate |
| 6 | full A/B finetune loop | primary metric | S3 or S4 fires |

Phase 0 is the honest starting point: find out whether the baseline is even beatable before
investing in anything that tries to beat it.

---

## 9. Definition of done

The skill is done when, on the held-out repo:

1. Primary metric beats baseline by a margin that survives the control's own variance.
2. Accuracy is equal or better (never worse — S1).
3. False-hit rate < 2%.
4. `SKILL.md` stays under 500 lines / 5,000 tokens.
5. It passes `skills-ref validate` and installs cleanly via `npx skills add`.
6. The result is reproducible by re-running the batch from a clean checkout.

If the honest answer is "no measurable win," that is a successful outcome of this experiment
and gets written down as such.

---

## Sources

- Agent Skills spec — https://agentskills.io/specification
- `npx skills` CLI — https://github.com/vercel-labs/skills
- Aider repomap — https://aider.chat/docs/repomap.html
- Code Isn't Memory — https://arxiv.org/abs/2606.22417
- Does a Language Server Save Tokens? — https://arxiv.org/abs/2608.13568
- SWE-Pruner — https://arxiv.org/abs/2601.16746
- FastContext — https://arxiv.org/abs/2606.14066 (**withdrawn**, product IP — do not rely on)
