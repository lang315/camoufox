#!/usr/bin/env bash
# FETCH="curl -fsSL" scripts/rehearse-patch.sh <patch-basename>
set -euo pipefail; shopt -s globstar
command -v gpatch >/dev/null || { echo "need gpatch"; exit 3; }
[ "${BASH_VERSINFO:-0}" -ge 4 ] || { echo "need bash>=4"; exit 3; }
: "${FETCH:?set FETCH, e.g. FETCH='curl -fsSL'}"
PATCH="${1:?usage: rehearse-patch.sh <patch-basename>}"
ROOT="$(git rev-parse --show-toplevel)"; PDIR="$ROOT/patches"
WORK="$ROOT/.rehearse/$PATCH"; TREE="$WORK/tree"
HG="https://hg.mozilla.org/releases/mozilla-release/raw-file/FIREFOX_152_0_4_RELEASE"
PB="${CAMOU_PATCH:-gpatch}"
pf(){ local n="$1"; [ -f "$PDIR/$n" ] && echo "$PDIR/$n" || find "$PDIR" -name "$n" | head -1; }
edited(){ awk '/^--- \/dev\/null/{s=1;next} /^\+\+\+ b\//{if(!s)print substr($0,7);s=0}' "$1"; }
created(){ awk '/^--- \/dev\/null/{g=1;next} /^\+\+\+ b\//{if(g)print substr($0,7);g=0}' "$1"; }
mapfile -t TARGET_EDIT < <(edited "$PDIR/$PATCH")
mapfile -t TARGET_NEW  < <(created "$PDIR/$PATCH")
mapfile -t ORDER < <(ls "$PDIR"/**/*.patch | xargs -n1 basename | sort -u)
PREREQS=()
for p in "${ORDER[@]}"; do [ "$p" = "$PATCH" ] && break
  ppath="$(pf "$p")"
  for tf in "${TARGET_EDIT[@]}"; do edited "$ppath" | grep -qxF "$tf" && { PREREQS+=("$ppath"); break; }; done
done
rm -rf "$WORK"; mkdir -p "$TREE"; WRONG=0
declare -A SEEN
for src in "${PREREQS[@]}" "$PDIR/$PATCH"; do
  while read -r f; do
    [ -z "$f" ] && continue; [ -n "${SEEN[$f]:-}" ] && continue; SEEN[$f]=1
    for nf in "${TARGET_NEW[@]}"; do [ "$f" = "$nf" ] && continue 2; done
    mkdir -p "$TREE/$(dirname "$f")"
    code=$($FETCH -w '%{http_code}' -o "$TREE/$f" "$HG/$f" 2>/dev/null || echo 000)
    if [ "$code" = 404 ]; then
      # only a wrong-path bug if THIS patch edits it (not a prereq-only file)
      for tf in "${TARGET_EDIT[@]}"; do [ "$f" = "$tf" ] && { echo "WRONGPATH: $PATCH edits nonexistent FF152 file $f"; WRONG=$((WRONG+1)); }; done
      rm -f "$TREE/$f"
    elif [ "$code" != 200 ]; then echo "FETCH FAIL $f ($code)"; exit 4; fi
  done < <(edited "$src")
done
cd "$TREE"
for p in "${PREREQS[@]}"; do "$PB" -p1 --forward -l --binary -i "$p" >/dev/null 2>&1 || true; done
OUT="$WORK/apply.out"; set +e; "$PB" -p1 --forward -l --binary -i "$PDIR/$PATCH" >"$OUT" 2>&1; RC=$?; set -e
REJ=$(find "$TREE" -name '*.rej' | wc -l | tr -d ' ')
SKIP=$(grep -ciE 'can.?t find file|ignored|Skipping' "$OUT" || true)
FUZZ=$(grep -oE 'with fuzz [0-9]+' "$OUT" | grep -oE '[0-9]+' | sort -rn | head -1); FUZZ=${FUZZ:-0}
OFF=$(grep -oE 'offset -?[0-9]+' "$OUT" | grep -oE -- '-?[0-9]+' | tr -d - | sort -rn | head -1); OFF=${OFF:-0}
echo "=== $PATCH: rc=$RC rejects=$REJ skipped=$SKIP wrongpath=$WRONG fuzz=$FUZZ max|offset|=$OFF ==="
grep -E 'Hunk|FAILED|ignored|offset|fuzz|find file' "$OUT" || true
[ "$REJ" = 0 ] && [ "$SKIP" = 0 ] && [ "$WRONG" = 0 ] && [ "$FUZZ" = 0 ] && [ "$OFF" -le 2 ]
