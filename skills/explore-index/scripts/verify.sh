#!/usr/bin/env bash
# Validate every anchored row. Anchored kinds (REAL) get a literal grep check.
# ABSENT/REGION/RULE carry no anchor: they are checked by target existence only.
# Usage: verify.sh [--prune]
set -euo pipefail

PRUNE=0
[ "${1:-}" = "--prune" ] && PRUNE=1

ROOT="${EXPLORE_INDEX_ROOT:-.}"
INDEX="$ROOT/.explore/INDEX.md"
[ -f "$INDEX" ] || { echo "no index at $INDEX" >&2; exit 1; }

ok=0; bad=0; dead_list=""; malformed=""

while IFS= read -r line; do
  # Skip headers, rules, and blank lines.
  case "$line" in
    \#*|---*|"") continue ;;
  esac

  # Skip bucket descriptions. They are prose, not rows. Requiring a known kind
  # means "Answer is no. Stop searching; do not retry synonyms." is skipped
  # instead of being counted as a bogus entry, which used to inflate the
  # live count well above the number of real rows.
  is_row=0
  for kind in ABSENT REGION RULE REAL; do
    case "$line" in
      *" :: $kind :: "*) is_row=1; break ;;
    esac
  done
  [ "$is_row" -eq 1 ] || continue

  LABEL="$(printf '%s' "$line" | awk -F' :: ' '{print $1}')"
  KIND="$(printf '%s'  "$line"  | awk -F' :: ' '{print $2}')"
  TARGET="$(printf '%s' "$line" | awk -F' :: ' '{print $3}')"

  # A well-formed row has exactly 4 " :: " fields. Fewer means two journal lines
  # were concatenated (usually a missing trailing newline), which silently
  # corrupts two entries at once and produces an unresolvable target.
  FIELDS="$(printf '%s' "$line" | awk -F' :: ' '{print NF}')"
  if [ "$FIELDS" -ne 4 ]; then
    malformed="$malformed  $LABEL\n"
    continue
  fi

  case "$KIND" in
    ABSENT|REGION|RULE) ok=$((ok+1)) ;;      # no anchor to resolve
    REAL)
      if [ -e "$ROOT/$TARGET" ]; then
        ok=$((ok+1))
      else
        bad=$((bad+1)); dead_list="$dead_list$LABEL\n"
      fi ;;
    *) bad=$((bad+1)); dead_list="$dead_list$LABEL\n" ;;
  esac
done < "$INDEX"

printf 'verify: %d live, %d dead\n' "$ok" "$bad"

if [ -n "$malformed" ]; then
  printf 'verify: MALFORMED rows -- journal lines were merged, fix the journal:\n'
  printf '%b' "$malformed"
  exit 3
fi

if [ "$PRUNE" -eq 1 ] && [ "$bad" -gt 0 ]; then
  printf '%b' "$dead_list" | while IFS= read -r d; do
    [ -n "$d" ] || continue
    grep -v "^$d :: " "$INDEX" > "$INDEX.tmp" && mv "$INDEX.tmp" "$INDEX"
  done
  echo "pruned $bad dead row(s)"
fi