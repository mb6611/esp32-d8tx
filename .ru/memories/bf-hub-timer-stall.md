---
name: bf-hub-timer-stall
description: Read when D8 hub telemetry from the drone is empty or stops while replies still arrive, or before planning long telemetry runs after the drone sat idle.
load: description
---
Betaflight 4.2.11 (stock and the patched build) sends no hub bytes when its last hub cycle, or its boot if there was none, was 35.8 to 71.6 minutes ago. The check `cmpTimeUs` is a signed 32-bit difference in microseconds, and a skipped cycle doesn't reset the timer. Replies still arrive, but with a hub byte count of 0.

**Why:** On 2026-11-08 the 10-minute run fc_10min_b lost all hub data after 12.9 s for this reason. See experiments/11-telemetry-stack/data/NOTES.md, "Hub stall in 10-min run", and hub-stall/model.py.
**How to apply:** The guard (unsigned time difference in `processFrSkyHubTelemetry`) is in patch 0003, flashed as build c3f351e4 on 2026-11-08; it was NOT re-tested over the 36-71 min idle window, only that hub fields keep arriving. On older builds, run a short link or reboot the FC after >30 min idle. Don't chase this symptom in the d8tx library. Upstream (checked 2026-11-10): the same code is still in Betaflight master and no issue or PR covers frsky_hub.c; the same wrap class was fixed for arming in betaflight#14562. The owner submitted the fix upstream on 2026-11-10 as betaflight/betaflight#15996 (branch fix-frsky-hub-timer-wrap on fork mb6611/betaflight, local clone ~/Developer/personal/betaflight); check its status before re-raising the bug.
