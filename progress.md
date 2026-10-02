# progress.md — explore-index

**Snapshot:** 2026-10-02 · repo `fetch` @ `adfdcbd` · tree clean · nothing in flight

A working handoff for whoever picks this up next. Read this first, then
`exp/experiments/FINAL-REPORT.md` for the full argument and raw evidence.

---

## Where it stands

An Agent Skill (`SKILL.md` format) that stops an AI coding agent from re-deriving facts a
repository already settled. Before a broad search the agent consults `.explore/INDEX.md`,
and **a hit is binding, not advisory**.

**Shipped.** Both surfaces are live and verified end-to-end:

| | |
|---|---|
| npm | `explore-index@0.2.0` — https://www.npmjs.com/package/explore-index |
| GitHub | https://github.com/adityachauhan0/explore-index — public, 12 topics |
| Install | `npx skills add adityachauhan0/explore-index` |
| Spec | `npx -y skills-ref validate ./skills/explore-index` → `Valid skill` |

---

## The result

31 live subagent runs against GrowiaCRM @ `146b7f19` (1,406 files, 6,336 symbols) on
`opencode-go/space-bunny-free`. Final cohort = **29 runs** (15 baseline / 14 treatment);
the 2 cycle-001 advisory-skill runs are tagged and excluded.

| Metric | Baseline | With skill | Delta |
|---|---:|---:|---:|
| Billed tokens / task | 226,708 | 136,156 | **-39.9%** |
| Turns | 9.8 | 7.4 | -24.2% |
| Tool calls | 20.7 | 11.3 | -45.6% |
| Accuracy (mechanical grader) | 1.000 | 1.000 | equal |
| False hits | — | 0 | pass (2% kill threshold) |

Welch t = -3.458, p = 0.0005. **90,551 tokens saved per task**; 1,494,426 across the
29 runs. All 7 tasks favour treatment, including the 4 `held-out` tasks that have no
matching index row by construction.

**Mechanism — this is the part to internalise.** 84.7% of billed tokens are cache-read,
roughly 19,000 per turn, and every turn re-reads the whole accumulated context. So cost is
driven by *turn count*, not result size. The skill cuts turns; the rest follows.

---

## Layout

```text
skills/explore-index/SKILL.md         the deliverable — 127 lines, ~800 words
skills/explore-index/references/      PROTOCOL.md, ENTRY-FORMATS.md (lazy-loaded)
skills/explore-index/scripts/         journal.sh, reindex.sh, verify.sh

exp/telemetry.py                      provider token telemetry from the runtime store
exp/tasks.py                          7-task suite + mechanical grader + false-hit detector
exp/analyze.py                        run recorder, cohort filter, iso-accuracy guard, Welch
exp/harness.py                        deterministic replay simulation
exp/repomap.py                        deterministic repo map (PageRank + ambiguity filter)
exp/results/runs.jsonl                31 runs, one JSON object each
exp/results/cycle-00*.json            per-cycle verdicts
exp/experiments/FINAL-REPORT.md       full report
exp/experiments/cycle-*.md             per-cycle narrative: hypothesis -> trace -> fix

INSTRUCTIONS.md                       the experiment protocol written up front
explore-index-architecture.md         design rationale
```

Experiment index (session-local; excluded via `.git/info/exclude`, never dirties status):

```text
<GrowiaCRM>/.explore/journal.md       source of truth
<GrowiaCRM>/.explore/INDEX.md         generated from it
```

Last `verify.sh` run: **20 live, 0 dead**.

---

## Two design failures worth reading

The skill lost twice before it worked. Both were found by reading traces, not by guessing,
and both failed cohorts are still in `runs.jsonl` as evidence.

1. **Advisory → binding.** v1 read the index, correctly extracted an `ABSENT` row, then ran
   24 more searches anyway (198,704 tokens vs 138,273 baseline — it *lost*). Fix: "a hit is
   binding, not advisory", plus a 3-broad-search cap. `S3` went 14 turns/29 calls → 5/5.
2. **Unbounded read size.** Repeats flipped `H1` to **+4.3%** (skill *worse*) after a
   68,957-byte whole-file read permanently inflated every later turn. Fix: "read narrow, not
   whole" — grep/glob first, `offset`/`limit` second. `H1` went **+4.3% → -29.3%**.

---

## Open threads, in priority order

**1. Cross-repo replication — the gap that matters.**
Evidence is one repo, one model, 7 tasks. The direction is strong and the mechanism is
understood, but the *magnitude* is not a general law, which is why the skill is still
`stage: experimental`. Running the harness against a second repository is the test that
would justify promoting it.

**2. `H4` is the weak case at -11.3%.** One 2,600-line `migrations.ts` that no index row can
shortcut. Either accept it (big single files are a known blind spot) or design for it — a
`REAL` row that points at a *section* rather than a whole file.

**3. Registry submissions — none made.** Crawl-based indexes will self-pick-up (SkillsMP,
skills.sh, agskills.dev, explainx.ai). `VoltAgent/awesome-agent-skills` is a human PR and
their guide asks that you not submit something created hours ago — wait for real usage.
No submission was made; that is an outward-facing action on the user's account.

**4. npm token rotation.** The token used for 0.1.0 / 0.1.1 / 0.2.0 is still live and the
owner intends to rotate it. It was never written to disk — the sandbox blocked writing an
`.npmrc` with the auth line, so publishes used an env-var reference instead.

**5. SEO weakness.** On npm the bare name `explore-index` ranks #5 behind `serve-index`,
`lws`, `index-to-position` — generic-term collision, not a metadata failure. Descriptive
queries are the ones to watch. Don't rename on this; it isn't worth breaking package identity.

---

## Privacy boundary — do not undo this

The target repository under test is **private**. Trace-level internals were deliberately
excluded from the public repo and must stay excluded.

Git-ignored:

- `exp/results/probes/` — full agent transcripts naming internal file paths
- `exp/results/repomap.json` — internal file paths plus an absolute home directory

Sanitized in committed prose:

- Two experiment write-ups described a concrete, **still-unpatched defect** surfaced by the
  H1 runs. That wording was removed and replaced with a generic note that the finding was
  routed to the private repo's own backlog. **Do not restore the original wording**, and keep
  any new trace output to aggregate metrics.
- `exp/tasks.py` was changed from a hardcoded absolute path to a `REPO_ROOT`-driven one so
  the harness is portable.

`exp/results/runs.jsonl` and `cycle-*.json` are metrics-only and safe to keep public. Before
adding any new trace data, re-run the leak scan — that check caught three things last time
that were not in the originally agreed exclusion list.

---

## House rules learned here

- **One design variable per cycle.** Both failures were caught by trace analysis, not intuition.
- **Repeats are mandatory.** Baseline `H1` ranged 146,776 → 359,181 tokens on an *identical*
  task. One pair per task would have been wrong in both directions — that's why every headline
  number is pooled over repeats.
- **Tag and exclude failed cohorts; never delete them.** `v1-advisory` is the evidence for
  failure 1 and belongs in the dataset.
- **Recompute before quoting any number externally.** Two arithmetic errors in the final
  report were caught only by regenerating from `runs.jsonl` and diffing.
- **Never expose LSP to the agent** — earlier trials showed it *increases* token usage.
- **Verify generated artifacts by rendering them,** not by reading them.

---

## Commands

```bash
# from the repo root
cd exp

# re-score everything from raw telemetry
python3 analyze.py --report

# narrow to a cycle / task / tag
python3 analyze.py --cycle 007 --tag c7-rep3
python3 analyze.py --cohort v2-binding
python3 analyze.py --cohort all      # includes the failed advisory cohort

# raw token + tool-call trace for a single run
python3 telemetry.py --session-id mvs_xxx --toolcalls

# spec conformance
cd .. && npx -y skills-ref validate ./skills/explore-index

# is the seeded index stale?
cd <GrowiaCRM> && bash <repo>/skills/explore-index/scripts/verify.sh
```

Note: `--report` defaults to cycle 001. For the pooled headline read the JSON directly or
filter with `--cohort v2-binding`; the committed `FINAL-REPORT.md` has the final numbers.

---

## If you change the skill

1. Change **one** variable.
2. Re-run at least 3 repeats of a seeded *and* a held-out task, plus a known-good control.
3. Confirm accuracy stays 1.000 and false hits stay 0 — any accuracy drop voids the run.
4. Bump `version` in **both** `package.json` and `SKILL.md` metadata, `npm publish`, commit, push.
5. Update the tables in `README.md` **and** `exp/experiments/FINAL-REPORT.md` from recomputed
   values, never by hand.
