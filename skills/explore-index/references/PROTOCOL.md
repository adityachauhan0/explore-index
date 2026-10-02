# Protocol

Detail behind `SKILL.md`. Load when you need the exact lookup or journaling behaviour.

## When to consult

Consult the index at a **subsystem boundary**, not at every tool call.

| Situation | Consult? |
|---|---|
| Entering an unfamiliar part of the repo to find something | yes |
| About to run a repo-wide grep / glob sweep | yes |
| Symbol or concept appears not to exist | yes — this is the highest-value case |
| Deciding how this repo does X before writing code | yes |
| File already open, navigating inside it | no |
| Reading a file someone just handed you | no |
| Editing code you can already see | no |

Consulting costs a read. On the miss path that read is wasted. Consulting on *every* search
taxes all lookups to serve the minority that hit — consult at subsystem boundaries, not per
tool call.

## The lookup, precisely

```
Cold subsystem, need to locate something
  │
  ├─ read .explore/INDEX.md
  │
  ├─ row found?
  │    ├─ ABSENT   → answer is no. STOP. do not grep synonyms, do not open files hoping.
  │    ├─ REGION   → open the directory. navigate from there.
  │    ├─ RULE     → follow it.
  │    └─ REAL     → read the pointed file.
  │
  └─ no row → BOUNDED search, not your default
               1. one grep, task's own words, path = your subsystem
               2. if empty, one synonym grep
               3. only then widen
               └─ journal what you learned
```

On a miss you pay: one index read, then a bounded search. That is the tax. It only pays off
if the hit rate is high enough — which is why the index is kept small and high-value rather
than comprehensive.

## Journaling

Journal **every** search, hit or miss. The journal is the source of truth; `INDEX.md` is a
deterministic projection of it.

```bash
bash scripts/journal.sh "<label>" <KIND> "<target>" "<note>"
```

Journaling is what makes the *next* lookup cheap. An un-journaled search is a search the
index will make you pay for again.

What is worth journalling:

- **Absent facts** — highest value. An agent that cannot find `retryWithBackoff` will try three
  synonyms and open three files to re-derive what one grep settles. The row ends that search.
- **Concepts** — "where does auth live" is not a symbol query and has no grep answer.
- **Conventions** — architecture intent, which no parser infers.
- **`REAL` overflow** — places the deterministic repo map genuinely missed.

What is **not** worth journalling:

- Symbols and signatures. The repo map derives those. Storing them grows the index for
  nothing.
- Anything the repo map already answers.

## Validity and staleness

Entries rot. Two transitions are mechanical:

1. **Born → live** — validated free by the `grep` that located it.
2. **Live → dead** — only `REAL` rows have a path that can be checked. If you edit a file,
   every row naming it is suspect.

```bash
bash scripts/verify.sh          # report dead REAL rows
bash scripts/verify.sh --prune  # drop them from journal.md
bash scripts/reindex.sh         # rebuild INDEX.md from the journal
```

Prune the **journal**, not `INDEX.md`. `INDEX.md` is generated output; a dead row left in the
journal comes straight back on the next rebuild.

Anchor to a literal string, never a line number. Line numbers rot on any edit above them —
including your own.

## Growth discipline

The index is only cheap while it is small. Each bucket renders at most 40 rows and `reindex.sh`
silently keeps the first 40 it finds after sorting — it does **not** drop zero-hit rows first,
and it does not report what the cap discarded. So a bucket over 40 entries loses rows without
telling you which. Check `entries: N journalled, M rendered` at the foot of `INDEX.md`: if M
is much smaller than N, prune before adding.

If the index is not shrinking your exploration, deleting it entirely is better than keeping a
useless one — a stale index that is consulted and trusted is worse than no index.
