---
name: explore-index
description: Consult a persistent index of what was already learned about this repo before running broad searches, so exploration stops repeating itself. Use when you need to find where something lives in a repo you have not fully navigated this session, when a symbol or concept does not appear to exist, or when deciding whether a subsystem has already been traced. Not for ordinary edits to a file you already have open.
license: MIT
metadata:
  version: "0.3.0"
  stage: "experimental"
---

# Explore Index

Find where something lives without paying for the same search twice.

## The rule

Before a **broad** search — repo-wide `grep`, `glob` sweep, or opening files to see what is
inside — check `.explore/INDEX.md`.

- Index exists → read it before the broad search.
- Index does not exist → **do not create it.** Journal the first fact when you learn something;
  `reindex.sh` builds the file.

**Do not check** when the code is already in front of you. If you just read a file, or the target
directory is already open, navigate directly. The index pays off at subsystem boundaries.

## A row that covers your question is binding

A matching row is a **ceiling**, not a suggestion.

**Match on meaning, not on wording.** If your question is "where's the generic retry wrapper"
and a row says `shared retry helper`, that is a **match, not a miss**. An LLM asked to compare
exact strings will call it a miss and go searching; it is not one. Words differ, facts do not.

**Match on scope.** A row scoped to `src/**` answers questions about `src/**`. For a different
scope, treat it as no row and search normally.

Then, by kind:

| Row | What to do | Do not |
|---|---|---|
| `ABSENT` | The answer is **no**. Stop. Report it. | Do not run the synonym family. Do not glob `withRetry`, `retryWith`, `sendWithRetry`. |
| `REGION` | `glob` that one directory, then search inside it. | Do not sweep the repo first. |
| `RULE` | Obey it. | Do not test it. |
| `REAL` | `read` that one file. | Do not search further for this question. |

**If you use a row, name its label in your answer.** It makes the consult visible and costs
nothing.

## Confirm what the row points at — never answer from the index

An index row is a **pointer**, never a fact about code. A wrong row must cost you one wasted
hop, never a confident wrong answer.

So `read` the file a row names, or the directory a `REGION` row names — but only that one. If
what you read contradicts the row, the row is stale: say so and stop trusting it.

This is not a licence to search again. One hop to confirm is correct. Grepping around it is not.

## When no row covers the question

This is the only place you may search — so bound it:

1. Run **one** targeted `grep` using the task's own words, with `path` narrowed to the subsystem
   you are in.
2. If it comes back empty, run **one** with a synonym.
3. Only then widen.

Do not fall back to your default search pattern. That default is the thing this skill exists to
replace.

**Count-anchored check:** if you are about to run your **fourth** repo-wide `grep` or `glob` on
this task, you skipped the index. Stop and read `.explore/INDEX.md` before continuing.

## Read narrow, not whole

`grep` or `glob` to find the symbol or section first, then `read` with `offset`/`limit` around it.
One grep before one big read.

- To confirm a file exists, read the top ~60 lines — not the whole file.
- Only widen when the narrow read actually failed to answer the question.

## Big file, many turns

A large file is not read by slicing your way through it turn after turn. Each round-trip
re-sends everything already read, so a file you are slowly walking is the most expensive
thing you can do.

- Before opening a file you suspect is large, run `wc -l <path>`.
- Under ~500 lines, read it in one or two reads and be done.
- Over ~500 lines, **anchor first**: one `grep` for the symbol, then one read spanning
  that region. Do not page through the whole file.
- If you have already taken **four** reads against the same file, stop reading and either
  grep for the specific symbol you still lack, or report what you have. Do not take a fifth
  read to cover more of the file "for completeness".

## The loop

1. **Cold subsystem, broad search coming?** Read `.explore/INDEX.md`.
2. **Row covers it?** Match on meaning, then follow it per the table above and stop.
3. **No row?** One narrow `grep`, then one synonym, then widen.
4. **Every search journals a line** — hit or miss. That is what makes the next one cheap.

## Rules that matter

- **Absent is an answer.** If the index says a symbol does not exist, that ends the search.
  Do not try `with_backoff`, then `backoff_retry`, then open three files hoping.
- **Anchor, never line numbers.** Line numbers rot the moment anything above them changes,
  including edits you make yourself.
- **Do not store symbols or signatures.** A symbol-level map derives those deterministically for
  a fraction of the cost. This index is only for what a parser cannot know: proven-absent facts,
  concept-to-region pointers, and conventions.
- **Skip this entirely if the file you need is already open on screen.** Do not count files —
  apply it whenever you do not already know where the answer is.

## Writing an entry

One line, four fields:

```
<label> :: <kind> :: <target> :: <note, max 12 words>
```

| Kind | Target | Meaning |
|---|---|---|
| `ABSENT` | search scope | proven not to exist in that scope |
| `REGION` | directory | a concept lives here |
| `RULE` | short text | a convention or gotcha |
| `REAL` | path | the map missed it; here it is |

Examples:

```
shared retry helper :: ABSENT :: src/** :: searched backoff, retry, sleep; every service inlines it
auth entry point :: REGION :: src/auth :: middleware chain starts at index.ts
imports use @/ alias :: RULE :: tsconfig paths; never relative parent paths
billing totals :: REAL :: packages/billing/src/totals.ts :: small module, not in the map
```

Write the label in the words someone would use to **ask** the question. That is what makes the
row match on the next lookup.

Journal with the bundled script so the format stays consistent. Run it from the **repo root**
so `.explore/` lands there — the scripts are working-directory relative, not skill relative:

```bash
bash scripts/journal.sh "shared retry helper" ABSENT "src/**" "searched backoff, retry, sleep"
```

Then rebuild (deterministic, no model judgment):

```bash
bash scripts/reindex.sh
```

Both scripts write to `$EXPLORE_INDEX_ROOT/.explore/` when that variable is set, and to
`.explore/` under your current directory otherwise.

## Staleness

Rows can rot. Do **not** run `verify.sh` mid-task — it is a maintenance command, not a lookup
step. `verify.sh` only checks `REAL` rows, because `ABSENT`, `REGION` and `RULE` rows carry no
path to test; for those, a contradicting read is your only signal.

If you edit a file several rows point at, prune afterwards, then rebuild:

```bash
bash scripts/verify.sh --prune   # drops dead rows from journal.md
bash scripts/reindex.sh          # regenerates INDEX.md from what survived
```

Prune the journal, not `INDEX.md` — `INDEX.md` is generated output and a dead row put back into
the journal reappears on the next rebuild. Each bucket renders at most 40 rows, and `reindex.sh`
does not report which rows the cap dropped.

## Scope

Session-scoped by default. Promoting this index into the repo is a human decision, never
automatic — an index that outlives the code it describes is a lie with extra steps.

Full detail: `references/PROTOCOL.md` (lookup and journaling), `references/ENTRY-FORMATS.md`
(entry schemas and worked examples).