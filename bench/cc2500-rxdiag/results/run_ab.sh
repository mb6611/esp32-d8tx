#!/bin/bash
# BLE ON/OFF A/B for rxdiag events. usage: run_ab.sh FREQ_KHZ AGC2 AGC1 REPS SECS TAG
set -u
F=$1; A2=$2; A1=$3; N=$4; S=$5; T=$6
R=/Users/1unoe/Developer/personal/auto-drone/stage4
PY=/Users/1unoe/Developer/personal/auto-drone/stage0/.venv/bin/python
mkdir -p $R/results/U5-burst/ab
for i in $(seq $N); do
  for m in off on; do
    $PY $R/results/esp_ctl.py $m $((S+3)) > $R/results/U5-burst/ab/$T-$m$i.esp.txt 2>&1 &
    E=$!
    sleep 1.5
    python3 $R/host/rxdiag_events.py run --freq-khz $F --agc2 $A2 --agc1 $A1 --seconds $S --note "$T $m$i" --out $R/results/U5-burst/ab/$T-$m$i.txt >/dev/null
    wait $E
  done
done
