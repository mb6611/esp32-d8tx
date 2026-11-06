# In-band playback check: +1.25 MHz pattern vs zero samples, CC2500 at 2413.25 MHz (2026-11-05 local / 2026-11-06 UTC)

Question: with the classic-ESP32 stage2 `txeng` (unmodified, existing build), key mode `K 0`, PBUS (5,1)=127,
TX 2412 MHz, does the existing +1.25 MHz pattern (`F 1 16384 200 256`) put more in-band energy at
2413.25 MHz than all-zero samples, seen by the receive-only CC2500 `rxdiag events` diagnostic?

**Result: NO-DIFF, and inconclusive.** The detector recorded **no bursts at all** in the session: pattern 0/5,
zero 0/5, unkey 0/5, idle 0/5 (0 B records). The null is inconclusive. There was no in-slice positive
control: the keyed zero-sample slots were not seen either, and there was no tone condition. The 203 kHz
detector may also be too narrow or too insensitive for this line. So this result does **not** show that
the samples fail to radiate.

## Pre-registration
`prereg.py` was written and saved before any keying: sha256 in `prereg.sha256`, checked `OK` before
analysis; save time in `prereg_saved_at.txt`. The planned slot order is in `planned_order.txt` (seed 2413).
- Window: [t_send+1.5 ms, t_send+4.5 ms]. hit = at least one B record in the window. peak = the maximum
  peak_raw with n_rssi>0, or −128 if there is none.
- Primary test: pattern vs zero hits, one-sided Fisher, α 0.025. Secondary test: one-sided exact
  Mann–Whitney on peak, α 0.025, with a median difference of at least 3 raw.
- Result (`result.txt`, `result.json`): Fisher p=1.0, MWU p=1.0, median diff 0, valid (no validity failures), outcome NO-DIFF.

## Setup (one session, no retry)
- Command: `pbcheck.py --out inband/session --conds pat,zero,unkey,idle --n 5 --seed 2413 --count 6143 --tmo 100
  --km 0 --pwr 127 --agc2 203 --agc1 66 --rx-khz 2413250 --rx-bw 203` (`session_run.txt`). 6144 samples @80 MS/s
  = 76.8 µs engine time, at least 0.35 s (+0..0.3 s) between slots, 20 slots.
- **Envelope risk:** the host abort (`guard.py`, abort above 400 µs) acts only *after* a burst. The key/unkey
  overhead (especially on the first key after boot) and the RF-off timing are not hard-bounded by the firmware.
  The guard's 391 µs worst case is empirical.
- Measured keyed_us: pattern 194–206 µs, zero 194–**320** µs (320 µs = the first keyed slot after boot), all within
  400 µs; unkey 0. pb51 was 127 on every keyed slot, 0 before and after. ndone was 1 on all slots. No hang, no
  abort, and the stop byte was acknowledged (`got_x`).
- Detector: `rxdiag events 2413250 100 203 203 66 1`. H: freq_word 0x5CD13B == freq_rb == expected,
  bw_hz 203125, gdo_ok=1. Final C record: ring_lost 0.
- Sanity run before keying (ESP still on esp-sdr, 5 s, `sanity_2413250_bw203.txt`, `sanity_summary.txt`): same
  readback, 0 bursts, max RSSI raw −7.
- Motors: motor_proto=DISABLED, motor_dev=null (`diag_info.txt`).

## Positive control and limits
- The only detector positive control is the **earlier BLE A/B** (`../../results/README.md`: ESP32 BLE adverts seen,
  2402 MHz, 812 kHz BW, agc2 251/agc1 64). It used different settings, so it does not show sensitivity at
  203 kHz / 2413.25 MHz / agc2 203.
- The earlier 2412 MHz/812 kHz sessions saw every keyed burst (pattern and zero alike). Here even the keyed zero
  slots were not seen. Tuning 1.25 MHz away with a narrow filter removed the keying energy, so nothing
  in-session shows that the detector could see this transmitter in-slice.
- Unverified: the pattern sign and I/Q order (the line could be at 2410.75 MHz), the playback sample format, and
  the ESP-vs-CC2500 crystal offset. An offset of tens of kHz is plausible and would push the line toward the
  edge of the ±101 kHz passband.
- Exploratory, not pre-registered (`exploratory_window_rssi.txt`): the 100 ms C-window max RSSI near slots shows
  no consistent condition pattern (pattern −33/−6/−35/−33/−9; idle and unkey also show −9/−12). The mapping is
  coarse (one 100 ms window). This is not evidence either way.
- The clock-map slope is −1845 ppm (odd). It is irrelevant here because there were no B records.

## Restores
- ESP32: the full 2 MB flash was read back *before* txeng (`esp_preimage.bin`, sha in `esp_preimage.sha256`).
  The partition table lies inside 2 MB, and the app is byte-identical to `build-esp32-devkitv1/esp_sdr.bin`.
  The 921600 and 460800 readbacks failed with serial-noise errors (`esp_readback_fail*.log`); 230400 worked.
  After the test it was written back (`esp_restore_flash.log`, hash verified) and `verify-flash` matched the
  digest (`esp_restore_verify.log`). `esp32sdr info` gives protocol 6, firmware 549bdce9…-dirty, both before and
  after (`esp_sdr_info_before.txt`, `esp_sdr_info_after.txt`).
- Tinyhawk: before flashing, `stock_preflash_capture.txt` / `diff_all_preflash.txt` (287 lines, equal to the earlier
  `../diff_all_final.txt`). The diag firmware 4cd0deab (sha c684da38…) was flashed via DFU (`dfu_flash_diag.txt`).
  Afterwards stock `betaflight_4.2.11_MATEKF411RX.bin` (sha bb32b85a…) went back on via DFU (`dfu_restore_stock.txt`),
  the preflash diff was replayed and saved (`restore_replay.log`, 0 error lines), and `diff_all_final.txt` is
  **`cmp`-identical** to `diff_all_preflash.txt`. The board was left in CLI after the capture: replug it to leave the CLI.
- Ports: `lsof` on /dev/cu.usbserial-0001 and /dev/cu.usbmodem0x80000001 shows no holders (`ports_free.txt`).
