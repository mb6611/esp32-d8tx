#!/usr/bin/env bash
# Clone betaflight/blackbox-tools at a pinned commit and build blackbox_decode into tools/blackbox/vendor/
# (git-ignored). Idempotent: re-running with the binary present only re-checks the pin.
set -euo pipefail
REPO=https://github.com/betaflight/blackbox-tools.git
# master as of 2026-10-25 ("fix: failsafePhase name table..."); the last tag v0.4.3 is from 2017 and predates
# Betaflight 4.x header fields (e.g. firmware-version voltage scaling), so pin the commit instead.
TAG=master@2026-10-25
COMMIT=d89f96b983d0f5c8f053acf003ee2998b02b5b0f
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/vendor/blackbox-tools"

if [ ! -d "$SRC/.git" ]; then
    mkdir -p "$HERE/vendor"
    git clone --quiet "$REPO" "$SRC"
fi
git -C "$SRC" fetch --quiet --tags origin
git -C "$SRC" checkout --quiet "$COMMIT"
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "pin mismatch: $got != $COMMIT ($TAG)" >&2; exit 1; }

if [ ! -x "$SRC/obj/blackbox_decode" ] || [ "${FORCE:-0}" = 1 ]; then
    # Only the decoder; blackbox_render needs cairo/freetype which we don't use.
    make -C "$SRC" clean >/dev/null 2>&1 || true
    make -C "$SRC" obj/blackbox_decode >"$SRC/build.log" 2>&1 || { tail -20 "$SRC/build.log" >&2; exit 1; }
fi
echo "$SRC/obj/blackbox_decode ($TAG $COMMIT)"
