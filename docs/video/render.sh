#!/bin/sh
# Render one scene with manim. Every scene file has its OWN media dir, media/<scene file name>/ (Tex, texts,
# voiceovers, videos), so renders of different scenes never share a cache and may run in parallel (no global limit).
# Only one render per scene at a time: a lock in that dir (a second render of the same scene waits).
# Usage: ./render.sh <manim args including the scene file>, e.g.
#   ./render.sh -ql -o S03B scenes/s03b_gfsk.py S03B        (draft, iterate)
#   ./render.sh -qh --disable_caching -o S03B scenes/s03b_gfsk.py S03B   (final 1080p60)
# Output: media/<scene file>/videos/<scene file>/<quality dir>/<Class>.mp4, e.g.
#   media/s03b_gfsk/videos/s03b_gfsk/1080p60/S03B.mp4   (this is where stitch.sh reads from)
# The first render of a scene is slower: its Tex and voiceover caches start empty.
set -u
cd "$(dirname "$0")"
f=""
for a in "$@"; do case "$a" in *.py) f=$a ;; esac; done
[ -n "$f" ] || { echo "render.sh: no scenes/<file>.py among the arguments" >&2; exit 2; }
name=$(basename "$f" .py)
M=media/$name
mkdir -p "$M"
LOCK=$M/.render.lock
while ! mkdir "$LOCK" 2>/dev/null; do
  p=$(cat "$LOCK/pid" 2>/dev/null || echo)
  if [ -n "$p" ] && ! kill -0 "$p" 2>/dev/null; then rm -rf "$LOCK"; continue; fi
  sleep 2
done
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT INT TERM
.venv/bin/manim --media_dir "$M" "$@"
