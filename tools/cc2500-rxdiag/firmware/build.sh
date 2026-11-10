#!/bin/bash
# Build MATEKF411RXDIAG sequentially, no LTO, with the pinned toolchain. Output: out/<BUILD_ID>/
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/SOURCES.lock"
BF="$HERE/work/betaflight"
TOOLS="$HERE/work/tools"
[ -f "$BF/.rxdiag_applied" ] || { echo "run apply.sh first" >&2; exit 1; }
export PATH="$TOOLS/$TOOLCHAIN_DIR/bin:$PATH"

# BUILD_ID: first 8 hex of sha256 over (sorted relpath, NUL, bytes) of overlay/**, patches/**, SOURCES.lock
BUILD_ID="$(cd "$HERE" && python3 - <<'PY'
import hashlib, os
files = ["SOURCES.lock"]
for d in ("overlay", "patches"):
    for r, _, fs in os.walk(d):
        for f in fs:
            if f != ".DS_Store":
                files.append(os.path.join(r, f))
h = hashlib.sha256()
for p in sorted(files):
    h.update(p.encode() + b"\0" + open(p, "rb").read())
print(h.hexdigest()[:8])
PY
)"
echo "BUILD_ID=$BUILD_ID"
OUT="$HERE/out/$BUILD_ID"
rm -rf "$OUT"; mkdir -p "$OUT"
LOG="$OUT/build.log"

# Stock Betaflight flags (-flto -fuse-linker-plugin -ffast-math, -Os) with GCC 9.2.1 aarch64-linux in docker
# (ubuntu:24.04, arm64 native; no Rosetta). TARGET defaults to MATEKF411RXDIAG; set TARGET=MATEKF411RX for the canary.
TARGET="${TARGET:-MATEKF411RXDIAG}"
LTOOLS="$HERE/work/tools-linux"
[ -x "$LTOOLS/$TOOLCHAIN_DIR/bin/arm-none-eabi-gcc" ] || { mkdir -p "$LTOOLS"; tar xjf "$HERE/work/downloads/$LINUX_TOOLCHAIN_FILE" -C "$LTOOLS"; }
echo "$(shasum -a 256 "$HERE/work/downloads/$LINUX_TOOLCHAIN_FILE" | cut -d' ' -f1)  $LINUX_TOOLCHAIN_FILE" | grep -q "$LINUX_TOOLCHAIN_SHA256" || { echo "linux toolchain sha mismatch" >&2; exit 1; }
BFL="$HERE/work/bf-linux"
rm -rf "$BFL"; rsync -a --exclude obj --exclude .git "$BF/" "$BFL/"
docker run --rm -v "$HERE/work":/w -w /w/bf-linux ubuntu:24.04 bash -c "
  apt-get update -qq >/dev/null && apt-get install -y -qq make python3 git >/dev/null 2>&1
  export PATH=/w/tools-linux/$TOOLCHAIN_DIR/bin:\$PATH
  make $TARGET TOOLS_DIR=/w/tools-linux EXTRA_FLAGS='-DRXDIAG_BUILD_ID=\\\"$BUILD_ID\\\"'" > "$LOG" 2>&1 || { tail -40 "$LOG" >&2; exit 1; }
BF="$BFL"
cp "$BF"/obj/betaflight_4.2.11_${TARGET}_*.hex "$BF"/obj/betaflight_4.2.11_${TARGET}_*.bin "$OUT/"
cp "$BF"/obj/main/betaflight_${TARGET}.map "$OUT/"
cp "$BF"/obj/main/betaflight_${TARGET}.elf "$OUT/" 2>/dev/null || true
echo "$BUILD_ID" > "$OUT/BUILD_ID"
( cd "$OUT" && shasum -a 256 *.hex *.bin *.map $(ls *.elf 2>/dev/null) BUILD_ID > SHA256SUMS )
arm-none-eabi-size "$OUT"/*.elf 2>/dev/null | tee "$OUT/size.txt" || true
echo "build OK: $OUT"
