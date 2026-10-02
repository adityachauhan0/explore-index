# Entry formats

Four kinds. Each maps to a different *verb*, which is why kind is the first routing decision.

## Schema

```
<label> :: <kind> :: <target> :: <note>
```

| Field | Decided by | Rule |
|---|---|---|
| `label` | model, free-form | the query it should answer. Write it as the question, not the answer: `shared retry helper`, not `no retry helper` |
| `kind` | model | one of `ABSENT`, `REGION`, `RULE`, `REAL` |
| `target` | script / model | a search scope, directory, text, or path |
| `note` | model, free-form | why it mattered. max ~12 words |

Because the reader is a model, not a matcher, `label` needs no alias table. `who logs you in`,
`auth session`, and `JWT expiry` can all be matched against `auth entry point` by judgement.
This is the whole reason to route semantically rather than with an exact-match index.

## ABSENT — proven not to exist

The highest value per entry. No search can rediscover it cheaply.

```
shared retry helper :: ABSENT :: src/** :: searched backoff, retry, sleep; every service inlines it
jsonwebtoken usage :: ABSENT :: src/** :: nothing wraps it; JWT handled via jose only
```

`target` is **the scope you actually searched**. A negative without a scope is not evidence —
it is a guess. Record what was covered so a future agent knows whether the absence still holds.

## REGION — a concept lives here

For concept queries that have no symbol to grep.

```
auth entry point :: REGION :: src/auth :: middleware chain starts at index.ts
billing totals :: REGION :: packages/billing/src :: three services aggregate into one
```

## RULE — how this repo does something

Architecture intent. No parser infers this; it comes from having traced the code.

```
imports use @/ alias :: RULE :: tsconfig paths; never relative parent paths
migrations run manually :: RULE :: no runner; apply in order, newest last
tests use vitest not jest :: RULE :: npm test resolves to vitest
```

## REAL — the repo map missed it

Overflow for cases the deterministic layer genuinely does not cover — small modules, config,
generated files.

```
billing totals :: REAL :: packages/billing/src/totals.ts :: too small for the map, not ranked
```

`target` must be a real path. `verify.sh` checks these and drops the dead ones.

## Anti-patterns

**Do not store symbols.** The repo map derives them. This index is only for what a parser
cannot know.

**Do not store summaries of code.** Summaries drift — they lose signatures and edge cases,
go stale, and then get trusted. Coordinates and negative facts survive; prose does not.

**Do not store line numbers.** Use a literal anchor and validate with grep.

**Do not store contents.** The index routes. It never answers.

**Do not write conclusions in `label`.** `label` is the question. If it reads
`auth is in src/auth`, an agent cannot tell it is being told a fact rather than being given a
place to look — and a fact it cannot verify is the failure mode that burns you.
