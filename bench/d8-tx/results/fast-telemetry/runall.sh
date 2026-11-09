#!/bin/sh
# usage: runall.sh "name|recipe" ...   (60 s each)
cd "$(dirname "$0")/../../../.."
for r in "$@"; do n=${r%%|*}; rc=${r#*|}
  python/.venv/bin/python bench/d8-tx/results/fast-telemetry/run_cadence.py "$n" "$rc" ${SECS:-60} > bench/d8-tx/results/fast-telemetry/$n.txt 2>&1
  python3 - $n <<'PY'
import json,sys
try:
  r=json.load(open(f"bench/d8-tx/results/fast-telemetry/{sys.argv[1]}.json"))["res"]
  print(r["name"],r["recipe"],"dec/s",round(r["decoded_per_s"],2),"fail",r["decode_fail"],"drop",r["tlm_drop"],"lat",{k:round(v,3) for k,v in (r["latency_s"] or {}).items()},"bytes",r["median_bytes"],"fs",r["failsafe_samples"],"/",r["msp_samples_after_3s"],"rcbad",r["rc_bad"],"rssi",r["rssi_min_mean_max"],"lag",r["ch8_lag_s"],"trig",r["link_end"][0].get("trig") if r["link_end"] else None, flush=True)
except Exception as e: print(sys.argv[1],"FAILED",e)
PY
done
