#!/bin/sh
# Join the rendered scenes S01..S05 into one video. Usage: ./stitch.sh [quality dir, default 480p15]
# Scene files: scenes/s01_key_to_stick.py S01, s02_packet.py S02, s03_tones.py S03, s04_hopping.py S04, s05_drone.py S05.
set -eu
cd "$(dirname "$0")"
Q=${1:-480p15}
LIST=$(mktemp)
for pair in s01_key_to_stick:S01 s02_packet:S02 s03_tones:S03 s04_hopping:S04 s05_drone:S05; do
  d=${pair%%:*}; c=${pair##*:}
  f="media/videos/$d/$Q/$c.mp4"
  [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }
  echo "file '$PWD/$f'" >> "$LIST"
done
mkdir -p out
ffmpeg -loglevel error -y -f concat -safe 0 -i "$LIST" -c:v libx264 -pix_fmt yuv420p -crf 16 "out/d8tx-key-to-thrust-$Q.mp4"
rm -f "$LIST"
echo "out/d8tx-key-to-thrust-$Q.mp4"
