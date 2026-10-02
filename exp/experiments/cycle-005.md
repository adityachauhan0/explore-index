# Cycle 005 — repeats expose a regression the first pass hid

## Per-task means (v2-binding cohort, repeats pooled)
| task | split | baseline | treatment | delta |
|---|---|---|---|---|
| S1 | seeded | 187260 (n=2) | 93970 (n=2) | **-49.8%** |
| S2 | seeded | 210746 (n=2) | 109634 (n=2) | **-48.0%** |
| S3 | seeded | 207256 (n=2) | 48351 (n=2) | **-76.7%** |
| H2 | held-out | 283157 | 206708 | -27.0% |
| H3 | held-out | 171140 (n=2) | 117772 (n=2) | -31.2% |
| H4 | held-out | 232593 | 192751 | -17.1% |
| **H1** | held-out | **252978 (n=2)** | **263774 (n=1)** | **+4.3%** |

**H1 flipped to a token LOSS.** First-pass single runs showed H1 at -26.6%.
Pooling repeats shows treatment *worse* than baseline.

## Root cause (trace-diffed)
H1 has no index row, so the routing rule never fires. Treatment then:
- call 5: reads a **68,957-byte** file in full
- calls 7-10: four more reads totalling 55KB

Baseline rep2 happened to find the answer with tighter reads (146,776 tokens).

The mechanism is the same cache-read compounding as before, entered through a
different door: **one oversized read permanently inflates every later turn**.
The skill constrains how many broad *searches* to run, but says nothing about
how large a single read should be. That is a real gap, not noise.

## Honest reading of variance
Single paired runs are not reliable. H1's sign flipped between reps; H3's
baseline varied 122k-220k across reps. Any claim resting on one pair per task
would have been wrong in both directions. This is the measurement-hygiene lesson
from the prior session showing up again in a new form.

## Fix for cycle 006
Add a read-size rule to SKILL.md: when hunting for an unknown file, grep/glob
first and read with a bounded offset/limit rather than opening a whole large
module. Re-run H1 (and a control task) to test the fix.
