#!/bin/sh
# Run manim one render at a time (parallel renders race on media/Tex). Usage: ./render.sh <manim args>
# e.g. ./render.sh -qh --disable_caching -o S01 scenes/s01_key_to_stick.py S01
set -u
cd "$(dirname "$0")"
LOCK=media/.render.lock
mkdir -p media
while ! mkdir "$LOCK" 2>/dev/null; do
  p=$(cat "$LOCK/pid" 2>/dev/null || echo)
  if [ -n "$p" ] && ! kill -0 "$p" 2>/dev/null; then rm -rf "$LOCK"; continue; fi
  sleep 2
done
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT INT TERM
.venv/bin/manim "$@"
