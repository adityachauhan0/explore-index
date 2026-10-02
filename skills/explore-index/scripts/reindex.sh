#!/usr/bin/env bash
# Materialise INDEX.md from the journal. Fully deterministic: dedupe, cap, sort.
# The agent never decides where an entry lands — this script does, from the path.
# Usage: reindex.sh [--cap N]
set -euo pipefail

CAP=40
while [ $# -gt 0 ]; do
  case "$1" in
    --cap) CAP="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

ROOT="${EXPLORE_INDEX_ROOT:-.}"
JOURNAL="$ROOT/.explore/journal.md"
OUT="$ROOT/.explore/INDEX.md"

[ -f "$JOURNAL" ] || { echo "no journal at $JOURNAL" >&2; exit 1; }

# Last occurrence wins, then sort by kind for stable grouping.
LAST="$(mktemp)"; trap 'rm -f "$LAST"' EXIT
awk -F' :: ' 'NF>=3 { key=$1; row=$0; seen[key]=row }
                     END { for (k in seen) print seen[k] }' "$JOURNAL" \
  | sort -t' ' -k1,1 > "$LAST"

write_bucket() {
  local kind="$1" title="$2" desc="$3" f="$LAST"
  local rows; rows="$(grep " :: $kind :: " "$f" || true)"
  [ -n "$rows" ] || return 0
  printf '\n## %s\n\n%s\n\n' "$title" "$desc" >> "$OUT"
  printf '%s\n' "$rows" | head -n "$CAP" >> "$OUT"
}

mkdir -p "$(dirname "$OUT")"
{
  echo "# Explore Index"
  echo
  echo "Read before any broad search. Last write wins. Rebuild: bash scripts/reindex.sh"
  echo "Validate:  bash scripts/verify.sh"
} > "$OUT"

write_bucket ABSENT "Absent — proven not to exist" \
  "Answer is no. Stop searching; do not retry synonyms."
write_bucket REGION "Regions — a concept lives here" \
  "Open the directory; already narrowed."
write_bucket RULE "Rules — how this repo works" \
  "Follow it before writing code here."
write_bucket REAL "Real paths — repo map missed these" \
  "Read the file."

TOTAL="$(wc -l < "$LAST" | tr -d ' ')"
KEPT="$(wc -l < "$OUT" | tr -d ' ')"
{
  echo
  echo "---"
  echo "entries: $TOTAL journalled, $(grep -c '^' "$OUT" || true) rendered"
  echo "cap: $CAP per bucket"
} >> "$OUT"

echo "reindexed -> $OUT"
