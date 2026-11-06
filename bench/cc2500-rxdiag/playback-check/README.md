# Stage2 playback engine vs CC2500 `rxdiag events`, 2412 MHz (2026-11-05)

Question: does the classic-ESP32 stage2 I/Q playback engine (`0x60033d98`) put its *samples* on air,
as seen by the receive-only CC2500 events diagnostic (Tinyhawk, fw `4cd0deab`)?

**Conclusion: keyed RF is detected; whether the *samples* are radiated is not established either way.**
In key mode `K 0`, power code 127, every keyed burst was detected (tight window), and the detected
duration/RSSI of pattern, DC and all-zero slots looked alike. That is consistent with keying leakage but does
not prove it, and it does not exclude sample-dependent output: the test had little sensitivity to it (see Limits:
A's line was outside the detector slice, DC +200 may be cancelled by LO leakage, the playback sample format is
unverified). Medians differ by about 1 raw RSSI step or less, but with n=20 slots, uncalibrated RSSI and no CI or
p-value computed, that is an observation, not a hard upper bound on any sample-dependent component.

## Setup
- ESP32: stage2 `txeng` (auto-drone/stage2, unmodified), `Q`=2412 (`cap_reg=b0`), `K 0` (txcal mode;
  PBUS (5,1) reads 127 during key, 0 before/after), `T` reps 1, tmo 400, gmode 3, 80 MS/s.
  Dry check first (`dry.txt`, `dry-serial.txt`): an *unkeyed* engine run (flags 0: engine ran, RF key not
  asserted) completed in 98361 cycles (16384 samples), PBUS (5,1)=0. It was not a no-playback dry run.
- Tinyhawk: `rxdiag events 2412000 100 812 203 66 1` (agc2 0xCB, agc1 0x42); `H`: freq_word 0x5CC4EC ==
  freq_rb, gdo_ok=1, fscal1 0x1B. Threshold sweep in `sweep2412/` (251/64: 3 bursts/s ambient, too
  insensitive; agc2=3 stuck high). Motors: motor_proto=DISABLED, motor_dev=null (`diag_info.txt`).
- `pbcheck.py`: one process owns both ports; seeded random slot order; ≥0.35 s (+0..0.3 s) between slots.
  `analyze.py`: maps CC2500 µs → host time by lower envelope of `C` records; counts bursts in a wide window
  [−10 ms, reply+30 ms] (`A.json`/`B.json`). `tight_window.py` (added afterwards; reads raw sessions only; output
  saved in `tight_window_output.txt`) reproduces the tight-window table below: window [t_send+1.5 ms, t_send+4.5 ms]
  (chosen from the tone pilot, lag ~2–3 ms).

## Results (tight window, slots with a hit / slots)
Statistic definitions (reproduced by `tight_window.py`): **duration** = per-slot maximum burst duration (longest
in-window burst of each slot), then median (min–max) over slots. **Peak raw** = over *all* in-window bursts with a
valid peak (a slot can contain several, so n can exceed the slot count, e.g. A zero 21 peaks/20 slots). Per-slot-max
peaks are in `tight_window_output.txt`; they differ slightly for tone (median +22).

| session | condition | hits | max burst dur µs (median, range) | peak raw, all bursts (median, range) | keyed_us |
|---|---|---|---|---|---|
| pilot2-km0 (16384 smp) | tone (bit 18 on) | 6/6 | 310 (256–**661**) | +20 (−14…24) | 322–448 |
| A (15360 smp, 192 µs) | pat ±1.25 MHz | 20/20 | 247 (236–266) | −5 (−9…−1) | 309–322 |
| A | zero samples | 20/20 | 246 (168–355) | −6 (−9…6) | 309–**483** |
| A | tone | 20/20 | 251.5 (217–552) | +20 (−17…27) | 309–322 |
| A | unkeyed engine | 0/20 | | | 0 |
| A | idle (no cmd) | 1/20 | 79 | 0 | |
| B (12288 smp, 154 µs) | DC sample (I=200) | 20/20 | 207 (197–315) | −2 (−4…4) | 271–**445** |
| B | zero samples | 20/20 | 202.5 (197–208) | −1 (−5…6) | 271–272 |
| B | idle | 0/20 | | | |

Sensitivity: excluding slots with keyed_us > 440 (A zero slot 0, B dc slot 0, pilot tone slot 7) the picture is
unchanged: A zero 246 (168–247) peak −6 (−9…−3); B dc 207 (197–208) peak −2 (−4…4); pilot tone 266 (256–661).
The ranges in the table include them.

Ambient 6–11 bursts/s; ring_lost 0. `K 1` (pilot2-km1): even the tone was not detected (0/6), so `K 1` is untested.
Raw (unmodified): `sessions/*/rx.txt` (host-stamped detector lines), `slots.jsonl` (per-slot T replies incl.
keyed_us, tone regs, PBUS), `A.json`/`B.json` (wide-window per-slot hits with lag, duration, peak).

**Tone detections longer than keyed, source unresolved:** pilot slot 15 (keyed 322 µs; longest detection 661 µs,
6 bursts), pilot slot 13 (322 → 375, 4 bursts), A slot 90 (321 → 552), A slot 56 (310 → 443, 10 bursts), and A slots
27/51/74/77/87 with 3–9 bursts. Possible causes (ambient bursts, detector merging/splitting, ringing, RF duration
≠ keyed_us) were not investigated, so tone duration is not a clean reference; the hit rates show only that keyed RF is seen.

## Limits
- **No in-slice pattern test:** pattern A's line is at ±1.25 MHz, outside the detector's ±406 kHz (812 kHz) slice.
  B's DC sample is in-slice, but DC +200 may be cancelled by LO leakage / DC removal in the transmit path, and the
  playback sample format (I/Q order, width, scaling) was not verified, so B could be blind to sample-dependent
  energy even if playback works.
- Energy only, one key mode (`K 0`), one power code (127), one geometry; CC2500 RSSI uncalibrated.
- Detected duration tracks engine length (247→203 µs) but keyed_us shrinks equally, so it doesn't separate
  "engine running" from "TX keyed".
- **Envelope breaches (three):** keyed bursts of 483 µs (A zero slot 0), 445 µs (B dc slot 0) and 448 µs (pilot2-km0
  tone slot 7) exceeded the 444 µs rule; all others 271–323 µs. Each was the first keyed slot of its session (each
  session began with an ESP boot, reason 1). Session A continued after the 483 µs burst was known; B then overran
  too. Keying stopped after B.
- ESP32 rebooted once unexplained (reason 7, `waiti mode`) right after the detector started, no keying in progress;
  this reboot is **not in any saved log** (logs show only boot reason 1 at session start); not reproducible ESP-only.

## Restores
- ESP32: esp-sdr `build-esp32-devkitv1` flashed (hash verified); `esp32sdr info` → protocol 6 (`esp_sdr_info_after.txt`).
  Baseline uncertainty: the ESP's original flash contents were not read back before txeng was flashed, so this
  restores a known esp-sdr build, not a verified copy of the prior image.
- Tinyhawk: stock `betaflight_4.2.11_MATEKF411RX.bin` via DFU; config wiped by flash, `diff_all_preflash.txt`
  replayed + save (`restore_replay.log`, 0 errors); `diff_all_final.txt` identical to preflash (287 lines).
  Board left in CLI after capture (no `exit`): replug to leave CLI.
- Both ports free (lsof empty).
