# Telemetry stack bench verification (track 1), 2026-11-08, lock held 10:39:14 - 11:20:51 EST
Drone on USB, no battery. Firmware: PATCHED Betaflight MATEKF411RX 4.2.11 built Nov 8 2026 11:20:01 (track2); diff all in bf-diff-before.txt.
Invariants OK: frsky_spi_tx_id 66,178; bind_hop_data intact; offset -32; RX_SPI_LED NONE (feature lines absent in diff, same as track2's diff_all_after).
Battery: CLI `status` "Voltage 0S NOT PRESENT"; MSP_ANALOG vbat_cv=0 after CLI exit (vbat_dv field reads 241 — bf_msp.parse_analog looks misaligned for this fw, ignore). Radio: vbat_v 0.0, battery "absent".
Note: bfcli.py capture leaves FC in CLI (arming flag CLI, MSP dead); `batch end` then `exit` reboots it out.

## Lib smoke (lib-smoke/out.txt, 60 s, arm low)
catch_rate 1.0 (138/138 triggers/replies, ~2.3 replies/s), age_ms ~215-360, rssi 83-85 (-54..-56 dBm), cfo -13 kHz, sender 111 Hz, max gap 14.8 ms, skipped 0, late_max 173 us.
hub: acc_mg [-28,-46,1005] (true milli-g, patched), heading null, rpm 0, vfas 0.0, current 0, temp1 0; patched block present: armed, angle/acro/horizon, attitude_deg, gyro_dps, arming_disable_flags, failsafe, flight_mode. raw IDs seen: 02 03 04 06 24-26 28 3A 3B 40-47 (+17 18 with fc).
## Backend e2e (e2e/*.jsonl, large ones gzipped, via drive.py, analyze.py)
fc_idle (60 s, with MSP): catch 138/138, age p50 215 / p95 409 ms, radio armed False from t=5.9 s (first hub frame), matches MSP.
fc_arm2 (arm cmd t=12.0 to 17.0, allow_arm, thr min): MSP armed 12.11 (0.11 s after cmd), radio armed 12.84 (+0.73 s after MSP); disarm: MSP 17.21, radio 17.58 (+0.37 s).
nofc_arm (no --fc-port): radio armed True at 13.26 (1.26 s after cmd), False at 18.88 (1.9 s after cmd); armed_source "patched"; catch 0.957 (90/91). Radio-only inference works with patched fw.
rpm/heading/acc armed vs disarmed: only acc_mg non-zero in all runs (heading null, rpm 0, no battery/props) ; armed did not change acc beyond noise.
## Failures
1. fc_arm.jsonl: WS stream froze at t=2.04 for ~459 s (client tx and rx both stalled) then resumed; link state was fine. Not reproduced in fc_arm2/nofc.
2. fc_10min: POST /api/link/start -> 409 "no reply to 'FOFS -75000'" (ESP silent right after previous server was pkill'd with link running), and WS froze t=3.28 -> 871 s. 10-minute run NOT obtained. ESP may need a reset (EN) before next use.
CORRECTED DIAGNOSIS (session 2): the WS freezes were NOT a server/link.py lock bug. The Mac was idle-sleeping on battery (pmset: 'Entering Sleep ... Idle Sleep' 10:39:38, sleeps/DarkWakes to ~10:50; the earlier caffeinate had died), freezing the client and server together. The 409 'no reply to FOFS' had a separate cause: see Session 2 (ESP boot race / ESP left in a stale state).

## Session 2 (2026-11-08, lock held 12:05-12:16 EST, USB power, no battery: radio vbat 0.0 / 'absent')
Run under 'caffeinate -dimsu'. pmset -g log: last Sleep 12:05:04 / DarkWake 12:05:32 (before caffeinate/run start); NO Sleep/DarkWake 12:06-12:16 during the run.
fc_10min_b.jsonl.gz (600 s, backend --fc-port, sticks 20 Hz, arm low, 28580 WS msgs): max WS gap 54 ms, zero gaps > 1 s. No freeze -> earlier freezes confirmed as sleep artifacts.
Catch overall 1387/1395 = 0.994 (final catch_rate field 1.0). Per minute: 1.000, 1.000, 0.972, 1.000, 1.000, 1.000, 0.979, 1.000, 0.993, 1.000.
age_ms p50 215 / p95 410 / max 849. Sender 111 Hz, 66706 sent, skipped 0, max sender gap 26.3 ms, late_max 799 us (earlier 60 s run: 173 us). Never armed (radio and FC), fc error None.
409 'no reply to FOFS' reproduced twice at first: ESP was found streaming raw 0x80/0x00 data (stale stage firmware output / old link) so did not answer; RTS reset fixed PING (OK proto=1). Then a 409 again because the server's own serial open reboots the ESP (DTR/RTS) and start was posted before boot finished; manual retry a few seconds later returned ok. Workaround: wait ~3 s after server start before /api/link/start (a fix would be a retry/boot wait in link.start - not done, no source edits).

## Hub stall in 10-min run (offline analysis, 2026-11-08; no hardware)
Symptom (fc_10min_b): hub frames on replies 1-29 only (t <= 12.9 s), none on replies 30..1387, while replies kept arriving.
Cause: Betaflight, not d8tx. cc2500_frsky_d.c appendFrSkyHubData calls processFrSkyHubTelemetry only on an acked request with an empty buffer,
and frsky_hub.c L517 skips the cycle while `cmpTimeUs(now, frSkyHubLastCycleTime) < 125000`. cmpTimeUs is (int32)(a - b) on uint32 micros
(no USE_64BIT_TIME on F411), and a skipped cycle does not update frSkyHubLastCycleTime. So when the gap since the last hub cycle (or boot) is
2^31..2^32 us (35.8..71.6 min), every ack returns 0 hub bytes until the gap passes 71.6 min. Here: last cycle at the end of nofc_arm (~11:06:01),
stall from 12:06:44 = 60.7 min; it would have cleared ~12:17:36, ~65 s after the run ended (12:16:31).
Evidence: hub-stall/model.py replays BF's buffer logic (patched odd cycle: STATUS, ARMING_DISABLE, GYRO, ACC, tail = 33 B; drone left at
sent 20 / acked 10, expected id 27; server restart reset our id to 0) through the real d8tx Tracker and matches the log reply by reply:
replies 1-27 = stale resend of bytes 10..19 (GYRO Y/Z only, GYRO X header cut off), 28 = ACC X/Y, 29 = ACC Z + tail, 30+ = nothing; with a
10-min gap the same model keeps decoding. `python/.venv/bin/python hub-stall/model.py e2e/fc_10min_b.jsonl.gz` -> "log matches the model".
STATUS was never seen because the stall hit the first fresh cycle. Not directly observed: per-reply hub byte counts (the WS snapshot does not
carry hub_count) and whether the FC rebooted between 11:06 and 12:06 (a boot 36..72 min before 12:06 would stall the same way).
d8tx library: TID ack/resend, duplicate skip, 0x5D stuffing and chunk splitting behave as Betaflight does; no library change.
Fix (not done, firmware): in patch 0001 treat a negative delta as due, e.g. `const timeDelta_t d = cmpTimeUs(...); if (d >= 0 && d < CYCLE) return;`.
