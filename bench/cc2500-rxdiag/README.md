# CC2500 rxdiag events (copied from auto-drone/stage4)

Source of truth for building: auto-drone `stage4/firmware` (overlay + patches, `apply.sh`, `build.sh` docker route); the files here are the changed ones: `firmware/` (overlay/src/main/rx), `tests/` (stage4/tests/core, run `make -C stage4/tests/core test` there: 4883 checks, 0 failures), `host/rxdiag_events.py`, `results/` (bench data). Data paths are relative to this `results/` directory (originally auto-drone `stage4/results/U5-burst`); `run_ab.sh` and `info`/log headers still contain the original absolute auto-drone paths.

## U5: CC2500 short-burst events mode (receive-only), 2026-11-05 local (logs stamp UTC 2026-11-06 00:17 onward)

## What was wrong with `rxdiag stream` for sub-ms bursts
- Old sessions (U4.2): windows of 10 ms tile at 10094 us median (≈94 us end-of-window gap, ~0.9 % dead time).
  `sample_us=59-60` is the time per **accepted** sample; measured now: one attempt (two RSSI reads)
  takes 19.3 us, but **68 % of attempts are rejected** (the two reads differ, CC2500 SPI read-sync rule), and
  every S window has flag BIT1. So RSSI is a point sample every ~60 us on average, with random holes; a
  burst shorter than ~60-100 us is caught only by chance, and the window record keeps only min/max,
  so burst count, start time and duration are lost.
- CC2500 limit (TI DN505): RSSI is a filtered value, updated every ~10 us at 812 kHz BW / FILTER_LENGTH=16, and
  the AGC needs a few gain steps (tens of us) after a signal appears. Bursts down to a few tens of us are
  therefore physically detectable; the ~60 us loop was the limit, not the chip.

## New mode: `rxdiag events <freq_khz> [window_ms=100] [bw=812] [agcctrl2=3] [agcctrl1=64] [ant=1]`
- GDO0 (IOCFG0=0x0E) = CC2500 carrier sense, high while RSSI > threshold (AGCCTRL2 MAX_LNA/MAX_DVGA/MAGN_TARGET,
  AGCCTRL1 CARRIER_SENSE_ABS_THR). GDO0 is wired to PC14 (the stock rx_spi EXTI pin); a both-edge EXTI ISR
  timestamps every edge (microsISR) into a 256-entry ring. No polling gap for detection.
- Main loop still samples RSSI (two equal reads) for peak level per burst and threshold calibration.
- Records: `H` (proto=2, freq word + **register readback**, AGC bytes, FSCAL after cal, `gdo_ok`, ant, level0),
  `B,seq,t_rise_us,dur_us,peak_raw,n_rssi,flags` per burst (peak -128 / n 0 = burst too short for an RSSI sample),
  `C,seq,t_us,span_us,edges,ring_lost,bursts,B_tx_fail,orphan_falls,att,acc,rej,min,max,maxLow,minHigh,nHigh,gapmax_us,open,marc,flags`
  per window; C counters are **cumulative**, so a dropped B or C record never loses counts.
- Safety: before RX the core checks the GDO0 wire (IOCFG0 0x2F → pin 0, 0x6F → pin 1, 0x2F → 0) and refuses
  (`EGDO`) if it fails; every config byte is read back (`ECFG` on mismatch). Exit path disarms the ISR, sets
  IOCFG0 back to 0x2E, SIDLE, LNA off. Same motor gate (DISABLED + null device), PATABLE 0, TX_EN low, no TX strobes.

## Bench (Tinyhawk on USB only, fw BUILD_ID 4cd0deab, bin sha256 c684da38…f7e5b4)
- `I`: reset_ok=1 rb_ok=1 part=0x80 ver=0x03 motor_proto=DISABLED motor_dev=null spi_hz=3375000.
- `H` at 2402 MHz: freq_word 0x5C6276 == freq_rb, gdo_ok=1, fscal1 0x1A, cal 811 us.
- Threshold sweep (ambient, 3 s each, `sweep/`): agc2=3 (max gain, MAGN_TARGET 33 dB) → CS stuck high (0 edges);
  agc2=203/251 with abs thr 0/+7 → 94/53/25/4 bursts/s; 255/+7 → none. Used agc2=251 (MAX_LNA_GAIN=7,
  MAX_DVGA_GAIN=3), agc1=64 (abs thr 0).
- **BLE A/B** (ESP32 flashed with stage3 `native_adv`, toggled by `esp_ctl.py`, 3×10 s alternating, `ab/`):

  | 2402 MHz | bursts/s | bursts with peak ≥ 50 raw (threshold chosen post hoc after seeing the data) | median spacing of those | dur p50 |
  |---|---|---|---|---|
  | OFF 1-3 | 27.5 / 23.7 / 26.0 | 0 / 0 / 0 | – | 266-286 us |
  | ON 1-3  | 38.0 / 40.1 / 41.2 | 164 / 168 / 163 | 64-65 ms | 305 us |

  Off-channel control 2414 MHz: 0 bursts OFF and ON. Adv ch 38 (2426 MHz): OFF 22.5/s, ON 39.5/s, peak ≥ 50: 0 vs 19.
  Ambient OFF bursts (~25/s, ~280 us) are *inferred* (not shown) to be other BLE advertisers.
- Accounting over the 6 A/B sessions: ring_lost 0, B_tx_fail 3 total, 2 C records lost (counted via seq gaps;
  totals intact), RSSI gapmax ≈ 236 us (during record emission; edges still captured by ISR).
  10-63 bursts < 100 us per 10 s were captured, many with no RSSI sample at all: the polling loop would have missed them.
- Energy only: a B record is RSSI over the carrier-sense threshold for the given duration. Nothing was demodulated;
  the ESP32 attribution is an inference, not demonstrated; it rests on ON/OFF alternation, channel selectivity and the ~64 ms spacing, not on packet content.
- Threshold in dBm is not calibrated (TI typical table only); `minHigh`/`maxLow` per C window give the observed
  RSSI-vs-CS relation. Antenna: ANT_SEL fixed high for all runs (`ant` arg exists, not compared).

## Restored afterwards
- Tinyhawk: stock `recovery/assets/betaflight_4.2.11_MATEKF411RX.bin` (sha bb32b85a…) via DFU, defaults + evidence
  diff replayed, then acc_calibration/acc_trim set to the pre-flash values; `diff_all_final.txt` == `diff_all_preflash.txt`
  (both 287 lines, `cmp` identical; checked again on re-review). `restore_replay.log` ends in a Python `OSError: [Errno 6] Device not configured` traceback (the replay script's read failed when the board re-enumerated), so the log itself does NOT show a clean replay; the restoration claim rests only on the final-vs-preflash diff equality. The evidence diff in recovery/ has older acc cal values than the board had.
- ESP32: re-flashed esp-sdr `build-esp32-devkitv1`. The claimed `esp32sdr info` output (protocol 6, HOPF) was not logged in `results/`: unlogged, unverified here. d8live not restarted.
- No process holds /dev/cu.usbmodem0x80000001 or /dev/cu.usbserial-0001.

## Files
`../../host/rxdiag_events.py` (run/info/summary), `run_ab.sh`, `ab/`, `sweep/`, `summaries.jsonl`, `dfu_flash.txt`,
`restore_*`, `diff_all_{preflash,final}.txt`, `version_final.txt`, `status_final.txt`.
Static gate: auto-drone `tests/firmware/check_source.sh` now passes (allowlist extended for antSet `IOHi`, table-driven `cfg[i].addr`, GDO0/EXTI cleanup order); copy of the script in `tests/check_source.py`.

## Caveats / not verified
- The `H`/`C` constants (AGC settings, threshold, 812 kHz BW) were not calibrated; the CS threshold in dBm is unknown.
- `gapmax_us` (~236 us) is the longest RSSI polling gap and only a bound on poll gaps, not on edge capture; interpret with care.
- The ISR pending-flag handling at arm time (stale EXTI pending bit) is untested on hardware.
- The unit tests are host-fake only; none exercised a real ISR.
