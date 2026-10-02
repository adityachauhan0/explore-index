# Hardening & Replication Plan — explore-index v0.3.0

**Created:** 2026-10-02 · **Author:** mavis (orchestrator) · **Goal:** `tg_1p9fmuct0amur3f114`
**Repo:** `/Users/adityachauhan/Documents/Coding/fetch` (skill + experiment harness)
**Repo under test:** `/tmp/djtest` — Django @ `80ea222`

---

## The question this plan answers

> Is the −39.9% result on GrowiaCRM a law, or a property of that one repo?

The existing evidence is **31 runs, one repository, one model, 7 tasks**. The skill is still
`stage: experimental` for exactly that reason. Cross-repo replication is the gate.

---

## Two findings that reshaped the plan (found 2026-10-02, before any run)

### 1. The headline number is cache-read dominated

Decomposing the committed `runs.jsonl`:

| Cache-read priced at | Baseline | Treatment | Delta |
|---|---:|---:|---:|
| 1.0× (raw tokens — the published headline) | 232,101 | 140,242 | **−39.6%** |
| 0.1× (realistic cache pricing) | 58,402 | 40,195 | −31.2% |
| 0.0× (fresh compute only) | 39,102 | 29,078 | −25.6% |

The effect is real and survives at every rate. But **−39.9% is the most flattering
denominator**, and the headline itself must stop being a headline.

**Decision:** the published number becomes a *full data table*, and every metric is reported
at all three cache rates. The cache-read mechanism (85% of billed tokens; cost scales with
turn count, not result size) is reported as the *explanation*, not as the claim.

### 2. `H4` — the weak case — has a named cause, and Django reproduces it

`H4` scored −11.3% because a 2,600-line file cannot be shortcut by any index row. Django has
17 files over 75KB, led by `django/db/models/sql/query.py` (122KB). The weak case is
therefore *testable*, not just acknowledged.

---

## Audience separation — the governing architectural rule

There are two readers, and mixing them is the defect this plan exists to prevent.

| Artifact | Reader | Rule |
|---|---|---|
| `SKILL.md`, `references/*` | **the agent, at runtime** | Pure prompt engineering. **Zero** experiment data, token counts, percentages, or self-congratulation. Every line must buy a specific tool call. |
| `STUDY.md`, `BENCHMARKS.md`, `FINAL-REPORT.md`, `README.md` data sections | **humans, at study time** | Full data log: every run, every tool call, method, results, limitations. |

A skill that cites its own win wastes context budget on every single invocation and teaches
the agent nothing. **The artifact teaches technique; the study documents evidence.** Known
leak to fix: `SKILL.md:53` cites "a 60k run and a 260k one".

---

## Repo selection

**`django/django` @ `80ea222`.** Rationale:

| | |
|---|---|
| Size | 7,079 files / 2,932 `.py` / 74MB — 3–8× smaller than vscode (1.5GB) or next.js (2.5GB) |
| Popularity | 91k+ stars, active (pushed 2026-10-01) |
| Language | Python ≠ the TypeScript repo the skill was tuned on — a real generalization test |
| Structure | Clean subsystem layout, 19 subsystems, 15 contrib apps, 7 DB backends |
| Hard case | 17 files >75KB, reproducing the `H4` blind spot |

---

## Phases

### Phase 0 — Metric hardening *(no agent runs)*

Decompose every reported figure into `uncached_input` / `cache_read` / `output`, and report
delta at 1.0× / 0.1× / 0.0× cache rates. Re-verify all committed numbers from `runs.jsonl`.
Kill any claim that fails to reproduce.

### Phase 1 — Harness portability

- `exp/tasks.py` (GrowiaCRM) stays **frozen** — it is the historical record; re-running must
  reproduce published numbers or something is wrong.
- New `exp/tasks_django.py`: 7 tasks, mechanical graders, same public interface.
- **The harness lives outside every indexed tree.** A test file containing the query string
  becomes its own top-ranked candidate and silently poisons localization scores.

### Phase 2 — Django A/B

7 tasks × ≥3 repeats × 2 arms = 42 runs, interleaved, control re-run inside every batch.

**Non-negotiable gates:** accuracy stays 1.000 · false hits 0 · `resolved` graded
mechanically.

### Phase 3 — Trace analysis → one change per cycle

Tool-call-level reconstruction; classify each call tier 0/1/2, plus `deadrun` / `spiral` /
`drift`. Exactly one variable per cycle.

Questions this answers that current data cannot:

1. Does the skill fire **at all** on a repo it has never seen (cold start)?
2. What is the honest **n = 0** behaviour — no seeded index, nothing to hit?

### Phase 4 — Round 2 hardening

Apply trace findings, re-measure, confirm no GrowiaCRM regression. If round 1 is already clean,
**report that** rather than manufacturing a change.

### Phase 5 — Publish + SEO/AEO

Gated: accuracy 1.000 · false hits 0 · a real win on **two** repos · win holds at the 0.1×
cache rate. Version bump in **both** `package.json` and `SKILL.md` metadata.

If Django disappoints → skill stays `stage: experimental`, negative result written up
honestly, **nothing ships**.

### Phase 6 — Documentation

| File | Purpose |
|---|---|
| `STUDY.md` | Full method, complete run log, results, limitations |
| `BENCHMARKS.md` | Per-repo, per-task, per-arm tables |
| `CONTEXT-ENGINEERING.md` | Why this works — cache-read / turn-count mechanism |
| `README.md` | Landing page: essential, skimmable, install-first |

All numbers **regenerated from `runs.jsonl`**, never hand-typed. Two arithmetic errors in the
previous final report were caught only by recomputing and diffing.

---

## Adopted defaults

| Decision | Choice | Rationale |
|---|---|---|
| Protocol scope | **Full** (3 repeats, 42 runs) | Repeats are what caught the `H1` variance trap (146k → 359k on an identical task) |
| Publish threshold | **Conservative** | Token win at 0.1× cache rate + accuracy 1.000 + zero false hits |
| Task-suite structure | **Separate file** | Overloading `tasks.py` risks silently weakening the original graders |
| Index lifecycle | **Session-scoped** | Promoting an index into a repo is a human decision; `.explore/` stays gitignored |

---

## Non-negotiables carried from the original protocol

- Accuracy is checked **first**; tokens are read only after accuracy is confirmed equal.
- Tag and exclude failed cohorts — **never delete them**. `v1-advisory` is the evidence for
  failure 1 and belongs in the dataset.
- Never expose LSP to the agent — earlier trials measured a token *increase*.
- Verify generated artifacts by rendering them, not by reading them.
- One design variable per cycle.
- **Privacy:** the target repo is private. Trace-level internals stay out of the public repo.

---

## Risks registered up front

1. **Cold-start may dominate.** A repo the index has never seen may show ~0 benefit. That is
   a real finding, not a failure — it would mean the skill is a session-scoped optimizer and
   the claim must narrow accordingly.
2. **Grader drift.** New graders are new code. A wrong grader produces confident nonsense.
   Mitigated by the throwaway grader test per task in Phase 1.
3. **Model-key constraint.** `opencode-go/space-bunny-free` is **not overridable** via the task
   tool in the current catalog; children inherit the parent model. Any model-dependence claim
   must therefore be stated as inherited, not controlled.