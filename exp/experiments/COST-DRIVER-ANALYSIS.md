# What actually drives token cost: turns, not tool calls

**Status:** interim analysis, n=18 Django + 31 GrowiaCRM. Not yet a publishable
result. Recorded because it changes what the headline number means.

---

## The observation

Pooled across the Django runs, provider tokens are far better explained by the
number of **turns** than by the number of **tool calls**:

| dataset | n | r(turns, provider_tokens) | r(tool_calls, provider_tokens) |
|---------|---|---------------------------|--------------------------------|
| Django                      | 18 | **0.982** | 0.593 |
| GrowiaCRM (v2-binding arms) | 29 | 0.859 | 0.857 |
| GrowiaCRM (all)             | 31 | 0.800 | 0.816 |

Provider tokens = `uncached_input + cache_read`. Every turn re-sends the whole
accumulated conversation, so `cache_read` grows roughly linearly with turn count
even when the agent is doing very little. Measured cache-read per turn is
remarkably stable at **6,000–12,700 tokens**.

## Why this matters

The study was designed around tool calls: the skill's whole job is to cut the
number of searches an agent performs. That is a real and measurable effect, and
it is the mechanism the skill controls.

But **tool calls are a proxy**. The quantity actually billed is turn count times
context size. Two runs can have identical tool-call counts and wildly different
costs if one narrates across 19 turns and the other answers in 3.

The clearest case in the Django set:

| run | turns | tool calls | provider tokens |
|-----|-------|-----------|-----------------|
| S3 treatment  | 3  | 2  | 27,634  |
| H4 treatment  | 19 | 18 | **259,210** |

H4 treatment is the most expensive single run in the entire study — 2.6x the next
most expensive — despite the index having **no row** for the ORM SQL layer, i.e.
despite the skill having nothing to offer. It is 19 turns of reading a 122KB
file in slices, most of it re-sent cached context.

## The honest implication for the headline

`−39.9%` (GrowiaCRM) and the Django reductions are **real tool-call reductions**.
They are also, partly, turn reductions — because fewer searches means fewer
round-trips, and each round-trip is a turn.

That is a genuine saving and should be reported as one. But the causal chain is:

> skill → fewer searches → fewer round-trips → fewer turns → fewer cached
> context re-sends → fewer tokens

not

> skill → fewer searches → fewer tokens

The second version skips the mechanism that actually does the work, and it is
the version that would mislead a reader who assumes tool calls map linearly to
billable tokens.

## Cross-repo discrepancy, unresolved

GrowiaCRM shows tool calls and turns correlating *equally* (0.86 / 0.86); Django
shows turns dominating (0.98 / 0.59). Plausible cause: task shape. GrowiaCRM's
tasks are TypeScript/React and the agent's searches are individually more
expensive, so call count drives context growth; Django's tasks are Python where
many cheap greps can be issued without growing context much, so turn count is
the binding constraint.

**This is a hypothesis, not a finding.** It needs either more repeats or a
per-task regression with an interaction term to separate turn effect from call
effect. Until then it is flagged as an open confound.

## What this implies for the gates

The strict gate requires the effect to survive at 0.1x cache pricing. That gate
is now clearly the *right* one: it strips out most of the cached-context
advantage and asks whether the skill still saves anything through fewer searches
alone. At 1.0x pricing the skill is largely being paid for turn reduction; at
0.1x it has to stand on call reduction.

H4 is the case that threatens the gate, and it should not be excluded from the
pooled result — it is the honest stress case, and hiding it would be the exact
overclaim this study exists to avoid.
---

## Addendum: H4 is a genuine regression, not a win

Recorded once the H4 baseline finally returned (21 calls, 11 turns).

| H4 (122KB `sql/query.py`, **no index row exists**) | turns | tool calls | provider tokens | uncached input |
|---|---:|---:|---:|---:|
| baseline  | 11 | 21 | 172,873 | 24,552 |
| treatment | 19 | 18 | **259,210** | 17,526 |
| delta     | +8 | **−3** | **+86,337 (+50%)** | **−28.6%** |

This is the only pair in the Django set where the treatment arm is **worse on raw
tokens**, and it is worth being precise about why:

- On the metric the skill is *designed* to move — tool calls — it worked: 21 → 18.
- On the metric that is actually billed, it lost badly: turns 11 → 19, and cached
  context 148,321 → 241,684.
- The uncached-input column (−28.6%) shows the underlying exploration *was*
  cheaper. The regression is entirely in how many round-trips it was spread over.

**The mechanism.** The treatment arm had no index row to route to (H4 is held-out
and deliberately targets a file the index does not mention), so the skill's
contribution reduced to a *reading strategy* — and the strategy it gave was
"grep, then read with offset/limit". On a 122KB file that instruction is
**actively harmful**: it converts one large read into many narrow reads, and each
narrow read is another turn re-sending the accumulated context.

This is the sharpest actionable finding in the study, and it is what prompted the
Round 2 rule now in `SKILL.md`:

> ## Big file, many turns
> Before opening a file you suspect is large, run `wc -l <path>`. Under ~500 lines,
> read it in one or two reads. Over ~500 lines, **anchor first**: one grep, then one
> read spanning that region. If you have already taken **four** reads against the
> same file, stop and either grep for the specific symbol or report what you have.

The pre-existing rule ("one grep before one big read") was correct as advice and
wrong as a control: it described the ideal without bounding the failure mode. On
small files it is a win; on the one genuinely large file in the task set, it was
the mechanism of a 50% regression.

**It must not be excluded from the pooled result.** H4 is the honest stress case.
Dropping it would be exactly the overclaim this study exists to avoid.
