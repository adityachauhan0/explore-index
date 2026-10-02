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
is how the original flat-memo design lost money: it taxed all lookups to serve the minority
that hit.

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
  └─ no row → search normally (grep / glob / read)
                └─ journal what you learned
```

On a miss you pay: one index read, then the normal search. That is the tax. It only pays off
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

- **Absent facts** — highest value. An agent that cannot find `retryWithBackoff` will try
  three synonyms and open three files. That is ~5k tokens to re-derive what one grep settles.
- **Concepts** — "where does auth live" is not a symbol query and has no grep answer.
- **Conventions** — architecture intent, which no parser infers.
- **`REAL` overflow** — places the deterministic repo map genuinely missed.

What is **not** worth journalling:

- Symbols and signatures. The repo map derives those. Storing them grows the index for
  nothing.
- Anything the repo map already answers.

## Validity and staleness

Entries rot. Three transitions cost no tokens:

1. **Born → live** — validated free by the `grep` that located it.
2. **Live → suspect** — if you edit a file, every row naming it is suspect. Mechanical.
3. **Hit → evicted** — when a bucket hits its cap, zero-hit rows die first.

```bash
bash scripts/verify.sh          # report dead rows
bash scripts/verify.sh --prune  # drop them
bash scripts/reindex.sh         # rebuild INDEX.md from the journal
```

Anchor to a literal string, never a line number. Line numbers rot on any edit above them —
including your own.

## Growth discipline

The index is only cheap while it is small. When `reindex.sh` reports entries being dropped by
the cap, that is a signal the index is full of low-value rows. Add fewer, not more.

If the index is not shrinking your exploration, deleting it entirely is better than keeping a
useless one — a stale index that is consulted and trusted is worse than no index.
