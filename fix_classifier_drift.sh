#!/bin/bash
# fix_classifier_drift.sh
# Run from repo root: ~/Documents/GitHub/Disaster-Data
#
# Copies the current hardened eo_storm_join.py (reference: virginia's copy,
# confirmed live and matching 38 other states) over the 11 states still on
# the pre-hardening file. This is the same class of bug fixed on 2026-09-11
# for 7 other states: errors="raise" on date_signed parsing means the FIRST
# blank or unparseable date in any of these 11 states' collected data will
# crash that state's entire storm-join run, not just skip that one row.
#
# Confirmed via direct hash census against the live repo (2026-09-16):
#   Reference hash: 8a98131d2972c7184638b148ecf716abcef7b646f9b48a229e762bc4b8ecec86 (39083 bytes)
#   Stale hash:      f0f345c44415adee44664e201759724691b441c9c186b0453ae4b404e1877e71 (37658 bytes)
#   Stale states: alabama arizona arkansas kentucky louisiana mississippi
#                 nevada new-mexico ohio tennessee texas
# Every one of these 11 differs from the reference in exactly the same single
# block (the date-parsing hardening), confirmed by diff before writing this
# script. None of them has an independent fork like Indiana's did, so a
# straight overwrite is safe here.

set -e

REF="plus/virginia/eo_storm_join.py"
EXPECTED_HASH="8a98131d2972c7184638b148ecf716abcef7b646f9b48a229e762bc4b8ecec86"
STALE_STATES="alabama arizona arkansas kentucky louisiana mississippi nevada new-mexico ohio tennessee texas"

if [ ! -f "$REF" ]; then
  echo "ERROR: reference file $REF not found. Run this from the repo root."
  exit 1
fi

REF_HASH=$(shasum -a 256 "$REF" | cut -d' ' -f1)
REF_SIZE=$(stat -f%z "$REF" 2>/dev/null || stat -c%s "$REF")

if [ "$REF_HASH" != "$EXPECTED_HASH" ]; then
  echo "ERROR: reference file's hash doesn't match what was verified against"
  echo "the live repo. Refusing to propagate a possibly-wrong file."
  echo "  Expected: $EXPECTED_HASH"
  echo "  Got:      $REF_HASH"
  exit 1
fi

echo "Reference confirmed: $REF ($REF_HASH, $REF_SIZE bytes)"
echo ""

FAILED=0
for state in $STALE_STATES; do
  TARGET="plus/${state}/eo_storm_join.py"
  if [ ! -f "$TARGET" ]; then
    echo "SKIP  $state - no existing file at $TARGET (unexpected, check manually)"
    FAILED=1
    continue
  fi
  cp "$REF" "$TARGET"
  NEW_HASH=$(shasum -a 256 "$TARGET" | cut -d' ' -f1)
  NEW_SIZE=$(stat -f%z "$TARGET" 2>/dev/null || stat -c%s "$TARGET")
  if [ "$NEW_HASH" == "$EXPECTED_HASH" ] && [ "$NEW_SIZE" == "$REF_SIZE" ]; then
    echo "OK    $state -> $NEW_HASH, $NEW_SIZE bytes"
  else
    echo "FAIL  $state - copy did not verify (hash: $NEW_HASH, size: $NEW_SIZE)"
    FAILED=1
  fi
done

echo ""
echo "Full 50-state census after this fix:"
for d in plus/*/; do
  f="${d}eo_storm_join.py"
  if [ -f "$f" ]; then
    h=$(shasum -a 256 "$f" | cut -d' ' -f1)
    echo "$h  ${d%/}"
  else
    echo "MISSING            ${d%/}"
  fi
done | sort | uniq -c -w64

if [ "$FAILED" -ne 0 ]; then
  echo ""
  echo "One or more copies did not verify. Do not commit until every line"
  echo "above reads OK and the census shows a single hash across all 50 states."
  exit 1
fi

echo ""
echo "All 11 states now on the reference hash. Recommended next steps:"
echo "  1. python scripts/build-plus.py --states all --join-storms"
echo "     (confirm EXIT CODE 0, no unexpected WARNING/traceback lines)"
echo "  2. git add -A"
echo "  3. git commit -m 'Fix classifier drift: 11 states on stale pre-hardening eo_storm_join.py'"
echo "  4. git pull --rebase && git push"
