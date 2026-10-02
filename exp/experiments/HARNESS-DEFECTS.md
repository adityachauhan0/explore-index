# Harness defects found and fixed during the Django replication

Every entry here is a defect in **my measurement apparatus**, not in the model
under test. They are recorded rather than quietly deleted because a benchmark
that hides its own bugs is not a benchmark. Each one changed a recorded number
or a gate verdict, so each is material to the study's integrity.

Timeline note: the Django runs are tagged `dj-rep1` / cycle `008` in
`exp/results/runs.jsonl`. The Django suite itself is `exp/tasks_django.py`.

---

## Defect 1 — wrong grader selected for every repository

**Found:** while recording the first Django `S1` pair.
**Impact:** every Django treatment run would have been scored `false_hit: true`.

`exp/analyze.py` did a module-level `from tasks import grade`. There was no
per-repository grader selection, so Django answers were graded by the GrowiaCRM
grader. GrowiaCRM's "real path" pattern only matches `apps/*/src/...`; Django's
paths (`django/contrib/auth/hashers.py`) never match it, so
`names_real_paths` was unconditionally false and the false-hit detector fired on
every treatment run regardless of answer quality.

This is the more serious class of harness bug: it was **symmetric with the
hypothesis's direction**. It would have manufactured a headline "false hit rate"
out of a path-prefix mismatch and could easily have been misread as the skill
being dangerous.

**Fix:** `analyze.py::_grader_for(repo)` selects `tasks.py` for `growiacrm` and
`tasks_django.py` for `django`. `--repo` is recorded on every run row.

**Evidence:** the tainted rows were removed and `S1` re-recorded. Post-fix, all
6 Django rows score `false_hit: false` with `resolved: true`.

**Generalizable lesson:** when an A/B harness spans two codebases, grader
selection must be data-driven and explicit. A module-level import of the "first"
suite is a silent correctness bug waiting to happen, and it fails *in the
direction that makes a null result look like a strong one*.

---

## Defect 2 — `false_hit` regex could not match nested paths

**Found:** while grading the Django `S3` baseline (absent-probe) run.
**Impact:** one row was scored `false_hit: true` — a **baseline** run flagged as
confidently wrong, on a hard-kill gate metric.

The original pattern was:

```python
REAL_PATH_RE = re.compile(r"django/[a-z_]+/|django/[a-z_]+\.py")
```

That matches `django/tasks/` and `django/utils/` but **not** `django/tasks/base.py`
— it allows exactly one path segment. The `S3` baseline cited
`django/tasks/base.py:246` (`TaskResult.attempts` merely counts attempts; no
backoff loop), which is a correct, honest, load-bearing citation, and the grader
called it a false hit.

**Two sub-bugs, fixed in sequence:**

1. *Shape vs. existence.* Loosening the regex to allow nesting would have made it
   match more but still wouldn't answer the right question. An absent-probe
   grader should ask **"does this file exist on disk?"**, not "does this string
   look like a path?" — a hallucinated citation to a nonexistent file must not
   pass. Added `cites_real_file()`, which resolves each cited path token against
   the checkout (`/tmp/djtest`).

2. *Citing real files is not the same as falsely localizing.* After fix (1), the
   honest `S3` report still graded as a false hit, because it cited real files.
   But on an absent probe, citing real files is legitimate — it is *evidence that
   nothing reusable exists* ("the only retry helper is test-only,
   `tests/cache/tests.py:95`"). A false hit is a report that claims the missing
   helper **exists** while pointing at a real file. The correct rule is logical,
   not lexical:

   ```python
   false_hit = (not says_absent) and cites_real_file(low)
   ```

**Verification** — four hand-built cases, all correct after the fix:

| case                                            | resolved | false_hit |
|-------------------------------------------------|----------|-----------|
| honest absence + real citations                  | True     | False     |
| clean absence, no citations                     | True     | False     |
| fabricated existence + real file                 | False    | **True**  |
| fabricated existence + nonexistent file         | False    | False     |

**Re-grading rather than re-running:** the runs' token and tool-call telemetry
came from the runtime and cannot change when a grader changes, so re-running the
model would have been wasteful. `exp/regrade.py` re-applies the current grader to
the still-retrievable final answer text and rewrites **only** the four graded
fields (`resolved`, `coverage`, `false_hit`, `cited_index`). It supports
`--dry-run`, prints a per-field before/after diff, and leaves the file untouched
when nothing changes.

Verified after the rewrite: 37 rows in, 37 rows out, **zero drift** across all
13 non-graded metric fields.

---

## Defect 3 — stale seeded index row (data error, not harness error)

The Django seed journal claimed `csrf_exempt` lived in
`django/middleware/csrf.py`; it actually lives in `django/views/decorators/csrf.py`.

Not a harness bug — a bad hand-written ground truth. What is interesting is that
**the treatment agent caught it by itself**: it detected the stale row, read the
whole of `django/middleware/csrf.py`, reported the contradiction, and then located
the correct path. That is the confirm-read rule doing exactly its job, and it is
evidence *for* the design. The seed was corrected and the index rebuilt (13 live,
0 dead).

---

## Standing rules these defects produced

1. **Accuracy is checked before tokens.** A token saving achieved by degrading
   the answer is not a result.
2. **False hits are a hard kill gate**, so grader defects on that gate are
   treated as release-blocking until proven innocent.
3. **Never delete a failed cohort.** Re-grade in place, keep the diff, and record
   the defect and its impact.
4. **Harness code lives outside the indexed repository tree**, and the grader is
   per-repository by construction.
---

## Interim note — H3 coverage 0.75 is REAL, not a grader artifact

I initially suspected the H3 treatment coverage drop (1.0 → 0.75) was a grader
bug, the way Defect 2 was. **It is not.** Verified directly against the session
text (`analyze.extract`):

| run       | `TemplateDoesNotExist` | `find_template` | `app_directories` | coverage |
|-----------|------------------------|-----------------|-------------------|----------|
| baseline  | yes                    | yes             | yes               | 1.00     |
| treatment | yes                    | **no**          | yes               | 0.75     |

The treatment report described the loader chain accurately but named
`cached.Loader.get_template` and `BaseLoader.get_template`, never the engine-level
`find_template`. That is a genuine, if minor, reduction in which symbols the
answer surfaced — and it occurred on a **held-out** task, where the index gave no
help.

Both runs still `resolved: true`, so the accuracy gate is not violated. It is
kept as recorded: it is exactly the kind of small coverage cost that a
tokens-only summary would have hidden. **Do not "fix" this row.**

**Lesson:** resist the reflex to call every surprising metric a harness bug.
Defect 2 was found by checking a specific claim against a specific string;
H3 was found by checking the same claim and finding it *did not* hold. The
discriminator was always: does the report text contain the token, yes or no?

---

## Defect 4 — mid-experiment prompt edit silently relabelled runs

**Found:** while adding the Round 2 hardening, before it could corrupt anything.
**Impact:** 3 of 12 Django treatment runs were executing a *different prompt* than
their recorded `skill_version` claimed.

`analyze.py::record` derived the cohort label from the **cycle number**:

```python
skill_version = ("n/a" if arm != "treatment"
                 else "v1-advisory" if cycle == "001" else "v2-binding")
```

That was fine while one skill version was in play. It stopped being true when
`SKILL.md` was edited at 21:30:56 — the Round 2 "Big file, many turns" rule —
while cycle-008 runs were still being dispatched. Every treatment run in that
cycle was labelled `v2-binding`; three of them had actually read the new file.

**Why this class of bug is dangerous.** It is invisible in the row itself and it
biases in a convenient direction: the runs that picked up a *new* rule are
silently pooled with the runs that did not, so a prompt change is reported as a
repeat. It would have quietly contaminated the exact comparison the Round 2 rule
exists to test.

**Fix:** resolve the revision from the session's first message timestamp against
the `SKILL.md` mtime, not from the cycle.

- `analyze.py::skill_version_for(arm, cycle, session_id)`
- `analyze.py::session_start_ms(session_id)`
- `analyze.py::_skill_history()` — `(mtime, label)` timeline, oldest first
- `regrade.py` recomputes `skill_version` alongside the four graded fields

**Verified.** The resolver flags exactly the 3 expected sessions and no others.
Re-run is idempotent. Across the rewrite, 55 rows in / 55 rows out with **zero
drift** on all 13 telemetry fields.

**Corrected labelling** (Django, cycle 008):

| arm | skill_version | runs |
|---|---|---:|
| baseline | `n/a` | 12 |
| treatment | `v2-binding` (pre-Round-2) | 9 |
| treatment | `v3-bigfile` (post-Round-2) | 3 |

**Standing rule adopted:** never mutate an artifact that a live experiment is
reading. Either finish the batch under a frozen prompt, or version the artifact
and resolve per-run provenance from timestamps. Editing the prompt under a
running batch is the one move that cannot be undone after the fact.

---

## Defect 5 — a still-running session was recorded as a real result

**Found:** an S2 baseline run graded `resolved: false` — the first such result in
the study, and it landed on the *baseline* arm.
**Impact:** a false negative charged against the control, plus materially wrong
telemetry.

The run had 19 real tool calls but an **empty** `final_result`, so it graded
`resolved: false, coverage: 0.0`. Re-extracting the same session gave:

| field | stored | actual |
|---|---:|---:|
| turns | 4 | **8** |
| tool calls | 9 | **22** |
| provider tokens | 48,104 | **134,330** |
| output tokens | 840 | **2,096** |

The session was still streaming when `analyze.py` read it. `extract()` returned a
**partial snapshot**, and a partial snapshot is indistinguishable from a complete
one — no field said "truncated".

**Fixes:**

1. `record()` now **refuses to write** when `final_result` is empty, with an
   explicit message to wait for the session to finish.
2. New `analyze.py --audit [--repo X]` re-extracts every stored row and reports any
   whose telemetry has since moved. Verified across all 32 Django rows: it flags
   **exactly** the one stale row and no others.
3. The bad row is **retained**, tagged `INVALID-partial-snapshot` with
   `excluded_from_analysis: true` and a reason string. Every aggregation path
   (`analyze.report`, `costs.load`, and therefore `benchmark_table.py`) filters it
   out. Nothing was deleted.

**Lesson:** always re-verify a stored row against its source before trusting an
aggregate. Telemetry extraction is a snapshot, and snapshots go stale silently.

---

## Defect 6 — the repo filter silently dropped every legacy row

**Found:** while checking that the published GrowiaCRM headline still reproduced,
after all the cohort changes above.
**Impact:** the published **−39.9% silently recomputed as −28.8%**.

`costs.py --repo growiacrm` returned **zero** GrowiaCRM rows. Cause:

```python
runs = [r for r in runs if r.get("repo") == repo]
```

The 31 GrowiaCRM runs were recorded before the `repo` field existed — Django was
the first repo to need it. `r.get("repo")` therefore returns `None` for every
legacy row, which never equals `"growiacrm"`, so all 31 were filtered out. The
command then pooled a **mixed** set and reported a confident, wrong number.

The giveaway was the header: `repo=(all)` appearing in output that had been
passed `--repo growiacrm`.

**Fix:** `r.get("repo", "growiacrm") == repo` — a missing field means the only
repo that existed at the time.

**Verified after the fix:**

| repo | baseline | treatment | 1.0× | 0.1× | 0.0× | p (1.0×) |
|---|---:|---:|---:|---:|---:|---:|
| GrowiaCRM | 226,708 | 136,156 | −39.9% | −31.9% | −25.9% | 0.0018 |
| Django     | 116,119 | 92,504  | −20.3% | −11.6% | −4.8% | 0.287 |

The published GrowiaCRM figures reproduce exactly.

**Lesson:** a filter that can match nothing must fail loudly, not return an empty
pool that still produces plausible-looking statistics. Any added filter needs an
assertion on the surviving row count.
