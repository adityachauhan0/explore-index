#!/usr/bin/env bash
# Append one entry to the journal. No model judgment: format only.
# Usage: journal.sh <label> <kind> <target> [note]
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "usage: journal.sh <label> <kind> <target> [note]" >&2
  echo "kinds: ABSENT REGION RULE REAL" >&2
  exit 2
fi

LABEL="$1"; KIND="$2"; TARGET="$3"; NOTE="${4:-}"

case "$KIND" in
  ABSENT|REGION|RULE|REAL) ;;
  *) echo "invalid kind: $KIND (expected ABSENT|REGION|RULE|REAL)" >&2; exit 2 ;;
esac

LABEL="$(printf '%s' "$LABEL" | tr '|' '\n' | sed '/^[[:space:]]*$/d' | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
NOTE="$(printf '%s' "$NOTE" | tr '|' '/' | sed 's/[[:space:]]*$//')"

ROOT="${EXPLORE_INDEX_ROOT:-.}"
JOURNAL="$ROOT/.explore/journal.md"

mkdir -p "$(dirname "$JOURNAL")"
printf '%s :: %s :: %s :: %s\n' "$LABEL" "$KIND" "$TARGET" "$NOTE" >> "$JOURNAL"
echo "journalled: $LABEL ($KIND)"
