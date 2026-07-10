#!/usr/bin/env bash
# FETCH="curl -fsSL" scripts/rehearse-patch.sh <patch-basename>
set -euo pipefail; shopt -s globstar
command -v gpatch >/dev/null || { echo "need gpatch"; exit 3; }
[ "${BASH_VERSINFO:-0}" -ge 4 ] || { echo "need bash>=4"; exit 3; }
: "${FETCH:?set FETCH, e.g. FETCH='curl -fsSL'}"
PATCH="${1:?usage: rehearse-patch.sh <patch-basename>}"
ROOT="$(git rev-parse --show-toplevel)"; PDIR="$ROOT/patches"
WORK="$ROOT/.rehearse/$PATCH"; TREE="$WORK/tree"
# shellcheck disable=SC1091
source "$ROOT/upstream.sh"   # single source of the FF pin (version=X.Y.Z, release=...)
HG="https://hg.mozilla.org/releases/mozilla-release/raw-file/FIREFOX_${version//./_}_RELEASE"
PB="${CAMOU_PATCH:-gpatch}"
pf(){ local n="$1"; [ -f "$PDIR/$n" ] && echo "$PDIR/$n" || find "$PDIR" -name "$n" | head -1; }
edited(){ awk '/^--- \/dev\/null/{s=1;next} /^\+\+\+ b\//{if(!s)print substr($0,7);s=0}' "$1"; }
created(){ awk '/^--- \/dev\/null/{g=1;next} /^\+\+\+ b\//{if(g)print substr($0,7);g=0}' "$1"; }
TPATCH="$(pf "$PATCH")"; [ -f "$TPATCH" ] || { echo "patch not found: $PATCH"; exit 3; }
mapfile -t TARGET_EDIT < <(edited "$TPATCH")
mapfile -t TARGET_NEW  < <(created "$TPATCH")
declare -A NEW_SET; for nf in "${TARGET_NEW[@]}"; do NEW_SET["$nf"]=1; done
mapfile -t ORDER < <(ls "$PDIR"/**/*.patch | xargs -n1 basename | sort -u)
# prereqs = earlier-order patches that edit a file $PATCH also edits (parse each candidate once)
PREREQS=()
for p in "${ORDER[@]}"; do [ "$p" = "$PATCH" ] && break
  [ "${#TARGET_EDIT[@]}" -gt 0 ] || break
  ppath="$(pf "$p")"
  edited "$ppath" | grep -qxFf <(printf '%s\n' "${TARGET_EDIT[@]}") && PREREQS+=("$ppath")
done
# Files a prereq CREATES (from /dev/null) must not be fetched or flagged wrongpath —
# the prereq apply creates them (e.g. webrtc2 edits WebRTCIPManager.{h,cpp} that
# webrtc-ip-spoofing.patch creates).
for p in "${PREREQS[@]}"; do while read -r cf; do [ -n "$cf" ] && NEW_SET["$cf"]=1; done < <(created "$p"); done
rm -rf "$WORK"; mkdir -p "$TREE"; WRONG=0
declare -A SEEN
for src in "${PREREQS[@]}" "$TPATCH"; do
  while read -r f; do
    [ -z "$f" ] && continue; [ -n "${SEEN[$f]:-}" ] && continue; SEEN[$f]=1
    [ -n "${NEW_SET[$f]:-}" ] && continue   # patch creates it — never fetch
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
find . -name '*.rej' -delete   # prereq applies are best-effort; only $TPATCH's rejects count
OUT="$WORK/apply.out"; set +e; "$PB" -p1 --forward -l --binary -i "$TPATCH" >"$OUT" 2>&1; RC=$?; set -e
REJ=$(find "$TREE" -name '*.rej' | wc -l | tr -d ' ')
SKIP=$(grep -ciE 'can.?t find file|ignored|Skipping' "$OUT" || true)
FUZZ=$(grep -oE 'with fuzz [0-9]+' "$OUT" | grep -oE '[0-9]+' | sort -rn | head -1 || true); FUZZ=${FUZZ:-0}
OFF=$(grep -oE 'offset -?[0-9]+' "$OUT" | grep -oE -- '-?[0-9]+' | tr -d - | sort -rn | head -1 || true); OFF=${OFF:-0}
echo "=== $PATCH: rc=$RC rejects=$REJ skipped=$SKIP wrongpath=$WRONG fuzz=$FUZZ max|offset|=$OFF ==="
grep -E 'Hunk|FAILED|ignored|offset|fuzz|find file' "$OUT" || true
[ "$RC" = 0 ] && [ "$REJ" = 0 ] && [ "$SKIP" = 0 ] && [ "$WRONG" = 0 ] && [ "$FUZZ" = 0 ] && [ "$OFF" -le 2 ]
