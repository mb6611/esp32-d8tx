# U4 rerun2 (stage envelope: power 127, CC2500 `rxdiag freq 2412000 100 812 203 66`)
Identities: STM fw=3b26d459 (H record), ESP `P,d8tone,1` (flash not re-read; image sha a62d6c24 flashed earlier, no reflash).
Script: rerun2.py (stage control|tone). Raw: control_source_off_2412000.txt, tone_f0_r{1,2,3}_{stm,esp}.txt, out_*.txt, esp_runner_log_*.jsonl.

## Source-off control (30 windows, 100 ms): NOT quiet
All 30/30 windows have CS (ncs 18..149, typically 30-40 per window; fe_min -64, fe_max 63 = saturated range; fe_mean_hz ~50-95 kHz garbage). At agc 203/66 the freq mode sees CS constantly (ambient/noise), so "CS windows overlapping the keyed interval" is not a usable detector here. Per the stop rule, STEP 1 was stopped after the center positive control; f=+-16 and ALT were not run, STEP 2 not run (condition: center "not detected" is undecidable with a saturated detector).

## Center tone f=0, 150 ms, power 127, 3 reps (all ESP replies OK, on_us 150000, key_total 150057-150061, STAT keyed=0)
Keyed at ~0.4 s after H => windows 4-6. Per rep ncs per window (baseline ~20-60):
- r1: w4 253, w5 623, w6 183; fe_mean_hz 27893 / 26228 / 31885 (baseline windows ~50-80k)
- r2: w4 205, w5 744, w6 186; fe_mean_hz 34060 / 25834 / 22472
- r3: w4 271, w5 721, w6  89; fe_mean_hz 29764 / 26339 / 30704
Observation: ncs rises ~5-20x in exactly the keyed windows in all 3 reps, and fe_mean_hz drops to ~26 kHz (still includes saturated min/max, so not a calibrated offset). This is suggestive of keyed RF being seen as increased CS sample count, but the control being 100% CS means the gate "CS windows overlap keyed interval" is not interpretable; ncs elevation is a post-hoc metric, not the pre-agreed one.
## Verdict
Gate not passed/not decided: detector too noisy at 203/66 for 2412 MHz on this bench today (contrast README 2026-11-05 used `events` mode). Offsets +-16 not compared. No overruns or stuck keys.
Not verified: ESP flash hash re-read; any offset discrimination; step 2 txeng comparison. Suggest using `rxdiag events` mode (as playback-check did) rather than `freq` for detection.
