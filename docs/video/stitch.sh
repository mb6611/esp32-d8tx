#!/bin/sh
# Join the 11 rendered scenes into one video. Usage: ./stitch.sh [quality dir, default 480p15]
# Each scene is read from its own media dir (render.sh): media/<file>/videos/<file>/<quality>/<Class>.mp4.
# Order: s00_intro S00, s01_key_to_stick S01, s02a_to_esp32 S02A, s02b_packet S02B, s03a_fsk S03A, s03b_gfsk S03B,
# s03c_tones S03C, s04a_hopping S04A, s04b_binding S04B, s05_drone S05, s06_recap S06.
set -eu
cd "$(dirname "$0")"
Q=${1:-480p15}
LIST=$(mktemp)
TMPD=$(mktemp -d)
SILENT=0
# narration comes out of Kokoro at about -30 LUFS (ElevenLabs is louder); bring the joined track to -16 LUFS (web level), true peak -1.5 dB
AUDIO="-af loudnorm=I=-16:TP=-1.5:LRA=11 -ar 48000 -c:a aac -b:a 192k"
for pair in s00_intro:S00 s01_key_to_stick:S01 s02a_to_esp32:S02A s02b_packet:S02B s03a_fsk:S03A s03b_gfsk:S03B s03c_tones:S03C s04a_hopping:S04A s04b_binding:S04B s05_drone:S05 s06_recap:S06; do
  d=${pair%%:*}; c=${pair##*:}
  f="media/$d/videos/$d/$Q/$c.mp4"
  [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }
  # narrated scenes only: a scene without audio would make the joined video drift/lose sound, so fail clearly
  if [ -z "$(ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$f")" ]; then
    [ "${ALLOW_SILENT:-}" = 1 ] && SILENT=1 || { echo "no audio stream in $f (scene not narrated yet; ALLOW_SILENT=1 joins video only)" >&2; exit 1; }
  fi
  # pad audio with silence to the exact video length so the concatenated audio has no PTS jumps
  if [ "$SILENT" != 1 ]; then
    vd=$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of csv=p=0 "$f")
    p="$TMPD/$d.mp4"
    ffmpeg -loglevel error -y -i "$f" -c:v copy -af "apad=whole_dur=$vd" -c:a aac -b:a 192k -t "$vd" "$p"
    f="$p"
    echo "file '$f'" >> "$LIST"
  else
    echo "file '$PWD/$f'" >> "$LIST"
  fi
done
mkdir -p out
[ "$SILENT" = 1 ] && AUDIO="-an"
ffmpeg -loglevel error -y -f concat -safe 0 -i "$LIST" -c:v libx264 -pix_fmt yuv420p -crf 16 $AUDIO "out/d8tx-key-to-thrust-$Q.mp4"
rm -rf "$LIST" "$TMPD"
echo "out/d8tx-key-to-thrust-$Q.mp4"
