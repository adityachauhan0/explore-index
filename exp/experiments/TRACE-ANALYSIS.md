# Trace-level waste analysis — explore-index A/B (cycles 002–007)

Analysis only. No skill change, no headline re-derivation. Every number below comes from
`local_runtime_message_rows` in `~/.minimax/v2/sqlite/runtime-state.sqlite`, read via
`exp/telemetry.py` semantics (`--toolcalls`). Per-call `tool_call_result_data` was parsed, so
empty-vs-hit is observed, not inferred.

## 1. Coverage

**26 of 29 headline runs reconstructed. 3 were not, and it matters.**

| group | n | traced | notes |
|---|---|---|---|
| cycles 002–007, `v2-binding` treatment | 14 | **14 / 14** | all consulted `.explore/INDEX.md` |
| cycles 002–007, baseline | 12 | **12 / 12** | |
| cycle 001 baseline S1, S3 (`v1-advisory` pair) | 2 | excluded | outside the headline cohort |
| cycle 000 baseline S1 (`tag: probe-retry`) | 1 | excluded | harness probe, not an arm run |

29 = 26 + 2 + 1. The brief says "29-run headline cohort"; the runs file has 31 lines, and the
3 non-cohort lines are the cycle-001 `v1-advisory` pair plus the cycle-000 probe. So the honest
number is: **26 arm runs, all 26 traced, 0 untraceable.** No run was lost to a missing
telemetry store — every one of the 26 session ids is present in `local_runtime_sessions` and
every one has message rows whose `data_json` carries `tool_calls`.

The asymmetric cohort is itself a finding: **baseline has n=12, treatment n=14**, because the
seeded tasks S1 and S3 have no baseline runs in cycles 002–007. Every per-arm mean below is
reported with its own n for that reason. Cross-arm comparison on S1 is impossible (n=0
baseline); on S3 it is 1 vs 2.

## 2. Tier histograms per arm

Tier assignment rules actually applied to the traced calls:

- **tier 0** — a read of `.explore/INDEX.md` or `.explore/journal.md` (the only index surface
  the agents had; no repomap tool was exposed in the trace).
- **tier 1** — glob, bash `ls`/`wc`, a grep whose `path` is a *subdirectory* (scoped), or a read
  under 40 kB that is the first read of that file.
- **tier 2** — a grep rooted exactly at the repo root (unscoped sweep), a first read over
  40 kB, or a repeat read of a file already read in the same run.
- **deadrun** — a read of a path already read earlier in the same run.
- **spiral** — a contiguous run of ≥3 greps containing ≥2 verified-empty results.
- **drift** — a read never referenced by any later call and never cited in the final answer.

| arm | n runs | calls | tier 0 | tier 1 | tier 2 | deadrun | spiral | drift | saturated reads |
|---|---|---|---|---|---|---|---|---|---|
| baseline | 12 | 248 | 0 | 176 (71.0%) | **72 (29.0%)** | 16 | 1 | 0 | 2 |
| treatment | 14 | 158 | **18 (11.4%)** | 103 (65.2%) | **37 (23.4%)** | 13 | 1 | 0 | 3 |

**Tier-2 composition — this is the whole story:**

| tier-2 kind | baseline | treatment |
|---|---|---|
| repo-wide grep (unscoped, path == repo root) | **50** | **16** |
| re-read of an already-read file | 16 | 13 |
| mega whole-file read (≥40 kB, first read) | 6 | 8 |
| total tier 2 | 72 | 37 |

Read that table with care. The index did exactly one thing at scale: **it cut unscoped
repo-root greps by 68% (50 → 16)**. Everything else barely moved. The re-read bill (16 → 13)
and the mega-read bill (6 → 8, i.e. slightly *up*) were untouched, and those two together are
29 of the treatment arm's 37 tier-2 calls.

Per-run tier-2 counts also show the floor. Treatment tier-2 per run is 1–7 (median 2); the
`mvs_47d7b0729d384b4194e4c1694b192591` S3 run is the ideal shape — 3 calls total, 1 index read,
1 verifying grep, 1 confirming read.

**Drift is 0 in both arms, and this is a real measurement, not a missing bucket.** I checked
all 146 reads across the 26 runs: every single one has its basename present in that run's own
final answer text. The "one-shot" reads (47 of them — read once, directory never revisited,
29 baseline / 18 treatment) are cited as *negative* evidence ("no S3 client exists", "role
seeding has no delay"). Exploration that reads a file to rule it out and says so is not
drift. There is no wasted-exploration bucket to fix here.

13 of 26 runs contain at least one verified-empty call (13 empty calls total: 7 baseline,
6 treatment). Empty results are not a tier-2 problem on their own; they become one only when
they chain into a spiral, which happened twice in the whole cohort.

## 3. Per-task table

| task | split | baseline n / calls / t2 | treatment n / calls / t0 / t2 | dominant waste pattern | tier shift |
|---|---|---|---|---|---|
| **S1** seeded | 0 / – / – | 2 / 18 / 2 / 4 | no baseline in cohort; treatment reads `jobs/backoff.ts` twice (`mvs_067a1c2...`) | t2: 4 calls, half of them re-reads of `backoff.ts` | **not measurable** |
| **S2** auth | 2 / 46 / 2 | 2 / 24 / 3 / 2 | **the one spiral**: `mvs_e2af9a1cbd864b068abce75e1f543daa` runs greps #19→#23 for JWT libraries, 3 of 4 empty (`jose\|jsonwebtoken\|passport\|next-auth\|iron-session` twice) — should have been one "auth tokens :: RULE" index hit | 46 → 24 calls, t2 2 → 2 |
| **S3** absent | 1 / 22 / 7 | 2 / 8 / 3 / 2 | baseline burns 6 repo-wide greps to prove a wrapper is absent (`mvs_73df95c9...`); treatment asks the index, gets `generic retry wrapper :: ABSENT`, stops. 22 → 8 calls | t2 **7 → 2** |
| **H1** storage | 3 / 64 / 22 | 3 / 52 / 3 / 12 | **mega-read + re-read**: every run opens `filesystem-storage.ts` (68,957 B) whole, then 2–4 more times. `mvs_806b6cca` 4x, `mvs_73dd7a4f` 3x | t2 **22 → 12** |
| **H2** tenancy | 2 / 53 / 21 | 2 / 30 / 3 / 4 | baseline `mvs_9f64f930` alone fires **13 repo-wide greps**; treatment spiral at `mvs_7d6c798c` #6–#9 (`scopeTenantSql`, `tenant_organization_id` both empty then hit) | t2 **21 → 4** — largest drop |
| **H3** offline | 2 / 28 / 14 | 2 / 13 / 2 / 6 | `indexedDbEncryptedStore.ts` (67,813 B) read 3x in every single run, both arms. `mvs_85f3b72b`, `mvs_97674f34`, `mvs_d4aee8fe`, `mvs_dbf63333` | t2 **14 → 6** |
| **H4** migrations | 2 / 35 / 6 | 1 / 13 / 2 / 7 | `migrations.ts` (2760 lines, 100,128 B) read **5x** in the single treatment run | t2 **6 → 7 (worse)** |

## 4. Ranked finetune input

### 1. Ban the un-offset whole-file read. Run `wc -l` before `read`. (~29 tier-2 calls)

This is the single biggest remaining bill and it is arm-independent — 16 re-reads baseline,
13 treatment, plus 8 treatment / 6 baseline mega reads.

Evidence, the worst chain in the cohort — `mvs_54f59fb7e3174e7f9bf56a6270873872` (H4, treatment):
`#4 read migrations.ts` → 133,549 B, whole file, no offset. Then `#6` 27,507 B, `#8` 23,787 B,
`#11` 5,544 B, `#12` 4,588 B. **Five reads of one 100 kB file, 195 kB of overlap.** The file is
`2760 lines / 100,128 B` (`wc -c apps/api/src/runtime/mysql/migrations.ts`). Call #9 is the
correct move and arrives too late: a scoped grep `^export (async )?(function)...` inside the
file, 1,080 B.

Identical shape in `mvs_f44aaaf190514734a591d47a229864d4` (H4, baseline) — 4 reads, 133,549 B
first. And `filesystem-storage.ts` is opened whole (68,957 B) in **six** runs across both arms.

The fix is mechanical and already demonstrated in-trace: the treatment run at
`mvs_4559d16df29648a78cc237f5c32e536d` said *"reading line counts first so I don't pull whole
modules into context"* and ran `wc -l …/*.ts` as call #3, then read only `storage.ts` (127
lines) and offset-read `service.ts`. Never did it touch the 1,226-line module whole. That is
the behaviour to finetune toward, and it converts a tier-2 mega read into a tier-1 targeted one.

### 2. Convert every verified-empty grep pair into an Absent entry at task end. (~11 tier-2 calls)

Both spirals in the cohort are "one absent symbol, ≥3 greps":

- `mvs_e2af9a1cbd864b068abce75e1f543daa` (S2, baseline) — #19, #20, #23 all probe JWT
  libraries; #20 and #23 return *"No matches found"*; #21 `CREATE TABLE.*browser_sessions`
  also empty. Three-plus wasted greps to establish a fact the index already carries as
  `auth tokens :: RULE :: … no JWT anywhere`.
- `mvs_7d6c798c3282449f954472cc1261cfc0` (H2, treatment) — #6 `scopeTenantSql` empty, #7
  `tenant_organization_id` empty, then #8 and #9 re-issue **the identical two patterns** and
  hit. That is a deadrun-equivalent on greps: the first two calls already scoped the directory
  via call #2's glob (`apps/api/src/modules/tenancy/**`).

Neither agent journalled the absence on finding it. The skill's Absent bucket exists precisely
for this, and the S3 treatment runs show it working (`mvs_47d7b0729d384b4194e4c1694b192591`,
3 calls, resolved on the strength of `generic retry wrapper :: ABSENT`).

### 3. Give the mega-file a symbol index row so its interior is never swept. (~8 tier-2 calls)

Four distinct 60–135 kB files absorb the same first-read-plus-reread bill across both arms:
`migrations.ts` (100 kB, H4), `filesystem-storage.ts` (69 kB, H1), `indexedDbEncryptedStore.ts`
(68 kB, H3), `route-capability.ts` (134 kB, H2). `indexedDbEncryptedStore.ts` is read 3x in
**all four** H3 runs regardless of arm — the index has a row for it
(`indexeddb lock retry :: REAL`) but the row names the file, not the *symbols inside* it, so the
agent still has to read it end to end to find what it wants.

A row of the form `file :: SYMBOLS :: <top-N exported names with line numbers>` would let the
agent jump straight to an offset read. This is the only recommendation that pushes a tier-2
call *up* to tier 0 rather than merely down to tier 1.

## 5. The `H4` question — why only −11.3%

**Answer: the stated hypothesis is half right, and the wrong half is the expensive half.**
H4 is genuinely "a mega-file no index row can shortcut" — but the *dominant* cost was not the
missing row. It was the 5x re-read of the file the index row would have pointed at.

H4 means: baseline mean 217,307 provider tokens (n=2: `mvs_ca862b58bfac4f12ac76e84da7d4ae40`
232,593 and `mvs_f44aaaf190514734a591d47a229864d4` 202,021) vs treatment 192,751 (n=1:
`mvs_54f59fb7e3174e7f9bf56a6270873872`) = **−11.3%**. All three resolved.

Why the treatment arm barely moved:

1. **The missing row is real.** `.explore/INDEX.md` has no migration entry in any of its four
   buckets (Absent / Regions / Rules / Real) — I read the whole file. The treatment run's own
   call #0 was `ls -la …/.explore/`, then #1 and #2 read `INDEX.md` and `journal.md`, found
   nothing, and said so: *"No index row covers attachments/files/upload"* is the H1 run; the H4
   run reached the same conclusion and fell back to broad search.
2. **But the baseline was already narrow.** `mvs_ca862b58bfac4f12ac76e84da7d4ae40` never fired a
   single unscoped grep until call #14 and spent calls #0–#13 on `ls`/`wc` and two scoped greps
   — it discovered the module by path shape. It bought the index's routing with 20 cheap calls.
   **There was very little for the index to save.**
3. **The treatment arm then paid the full cost of the mega-file anyway.** 13 calls, of which 7
   are tier 2 — the *worst* tier-2 rate in the treatment arm, and worse than baseline's 6/35.
   It read `migrations.ts` five times (`#4,#6,#8,#11,#12`, 195 kB cumulative) and fired 2
   repo-root greps. The index told it where to go; nothing stopped it from re-reading the file
   it had been sent to.

So H4 is **not** simply "index has no row". It is: *no row, plus an agent that does not
segment-read its target file, in a baseline that was already efficient*. The −11.3% is the
residual after the index removed the only tier-2 work baseline actually had (1 unscoped grep) —
the entire measured gain is call-count reduction (20 → 13), not cost-structure improvement.

This is the direct argument for recommendation #1: had the treatment run opened `migrations.ts`
with `wc -l` first and then offset-read only the runner and the migration-registry function, H4
would likely have been the *best* task in the cohort rather than the worst.

---

### Method / caveats

- Tier boundaries are my operationalisation of the protocol, applied uniformly to both arms;
  they are judgement calls at the margins (40 kB mega-read cutoff; "scoped" = any `path` other
  than the repo root). Counts are reproducible from the sqlite store.
- The two excluded cycle-001 `v1-advisory` treatment runs (`mvs_668824c05d11442d9c12cfe92085596a`,
  `mvs_24e7b32bc08b4cbb9e253de0e4ccd1de`) *are* traceable in the store; they are excluded by
  scope, not availability.
- Baseline/treatment n are unequal (12 vs 14) and per-task cells are small (H4 treatment n=1).
  Per-task tier shifts are directional evidence from traces, not significance tests.