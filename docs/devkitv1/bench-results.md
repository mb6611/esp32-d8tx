# DevKit V1 bench results (burst mode, plan U5)

Board: ESP32 DevKit V1 (ESP32-D0WD-V3, CP2102) on `/dev/cu.usbserial-0001`, firmware profile
`esp32-devkitv1` (921600 baud), stock PCB antenna, indoors with ambient 2.4 GHz traffic
(Wi-Fi networks seen by the Mac on channels 1, 3 (40 MHz), 6 and 11). Hardware AGC (default),
so levels are uncalibrated dB. Measured 2026-11-05. Host: `host/` package, `esp32sdr` CLI.

All commands below run from `host/` with the venv active (`. .venv/bin/activate`).

## Link fix (prerequisite)

`SerialTransport` used to set `serial.Serial.timeout` before every read (one byte at a time for
`readline`). On this CP2102 link that dropped bytes: `VERSION?` timed out, CAP16 headers and
SPC1 frames came back corrupted. It now opens the port once with a fixed 50 ms timeout, reads
whatever is waiting in bulk into a buffer, and enforces deadlines itself. After the change:
`VERSION?`, `INFO`, `LIMITS?`, `TRANSPORT?` (`TRANSPORT UART 921600`) and `CAPS` answer through
`Device`, and every capture below passed its CRC.

## U5.4 capture at 2437 MHz (US1.2)

```
$ esp32sdr info
chip      ESP32SDR protocol 6 mode burst
max_n     16380
firmware  1d27d848…-dirty (esp32-devkitv1, 2026-11-05)
transport UART 921600
rates     80 40 16 MS/s
bits      8 10
gain      index 0..81 (step 1), hardware AGC default
tuning    1850-2500 MHz (host limit)
caps      VERSION GPIO SPEC SPECN SPECCAPS SPECSTAT DCT UARTBAUD RXLIMITS SERIALLEASE TUNEEXT RX40 RX16 LPFANA GAIN HWAGC IQ8

$ esp32sdr capture --freq 2437 --rate 40 --n 16380 -o ch6 --psd bench/ch6-capture-psd.png
captured 16380 samples at 40 MS/s, 2437 MHz, 8-bit, CRC ok, 0.36 s -> ch6.sigmf-data
peak 2446.297 MHz 17.4 dB, median -5.1 dB (DC ±0.2 MHz excluded)

$ esp32sdr spectrum --freq 2437 --bins 1024 --rate 40 --ms 1000 -o bench/ch6-spec.png
spectrum 1024 bins at 40 MS/s, 2437 MHz: 86 frames, 256 FFTs, mean detector
peak 2437.781 MHz 48.1 dB, median 38.3 dB
$ esp32sdr spectrum ... --detector max -o bench/ch6-spec-max.png
spectrum 1024 bins at 40 MS/s, 2437 MHz: 87 frames, 257 FFTs, max detector
peak 2426.180 MHz 74.0 dB, median 57.0 dB
```

The single 410 µs burst ([ch6-capture-psd.png](bench/ch6-capture-psd.png)) caught a packet
occupying ≈2440–2449 MHz, about 20 dB above the rest of the span, inside 2427–2447 MHz and its
edge. The 1 s on-chip spectra ([mean](bench/ch6-spec.png), [max-hold](bench/ch6-spec-max.png))
show energy across 2427–2447 MHz, with the flat-topped shape of the analog/decimation filter
(≈±8–10 MHz) that stage 0 already described, so the shape alone is not proof of Wi-Fi. The
packet in the burst capture is. US1.2: **pass**.

## U5.5 orientation (R6)

What the plan asked: tune 10 MHz below an active channel and see energy at +10 MHz. With
ambient traffic only, that single-LO test was **ambiguous**: the band is busy on both sides of
every LO (Wi-Fi on 1/3/6/11, plus Bluetooth hopping), and bursts are sparse (≈6–20 % of 410 µs
captures). Burst-gated counts, 120 captures per LO, bursts > 6 dB over the typical level and
dominant on one side (±5..15 MHz):

| LO (MHz) | expected side | upper | lower |
| --- | --- | --- | --- |
| 2452 (ch11 − 10) | upper | 17 | 21 |
| 2472 (ch11 + 10) | lower | 14 | 18 |
| 2427 (ch6 − 10) | upper | 7 | 5 |

So a controlled test was used instead: an LO sweep. The LO steps 2407→2477 MHz in 5 MHz
steps; at each LO the host takes a max-hold PSD of 25 CAP16 bursts (decoded with
`decode_cap`, Q negated) and a 2 s on-chip `SPEC` max-hold. Real RF features stay at the same
RF frequency as the LO moves only under the correct mapping. Correlating spectra of LO pairs
5–15 MHz apart (after removing the fixed baseband shape):

| data | RF = LO + f | RF = LO − f | LO pairs favouring LO + f |
| --- | --- | --- | --- |
| host capture (`decode_cap`) | **+0.218** | −0.007 | 32 / 39 |
| on-chip SPEC bins (raw order) | −0.060 | **+0.276** | 4 / 39 |

[orientation-sweep.png](bench/orientation-sweep.png) shows the four mappings. Conclusions:
- Host I/Q (`decode_cap`, Q negated) is correctly oriented: RF above the LO is at +f. **R6 pass.**
- The firmware's SPEC bins are the FFT of the raw `(I, −Q)` words, i.e. mirrored:
  natural bin +f is RF LO − f. `spec_cmd.SpecRun.rf_axis_hz` applies this, matching
  `tools/s3_ring.py`.

Reproduce: `../docs/devkitv1/bench/orientation_sweep.py` (≈4 min). A cleaner literal check
needs a controlled emitter on a known channel (e.g. a phone hotspot pinned to channel 1 with
traffic, tune 2402).

## U5.6 robustness (SC2, R3, E1)

```
50 × `esp32sdr capture --freq 2437 --rate 40 --n 16380 -o …` (each a new process: open, sync,
tune, capture, release): 0 failures, 84 s total (≈1.7 s per run)

One session, 50 back-to-back CAP16/CAP20 16380 at 2437 MHz each:
80 MS/s  8-bit: 0 failures, 361 ms each
40 MS/s  8-bit: 0 failures, 361 ms each
16 MS/s  8-bit: 0 failures, 362 ms each
80 MS/s 10-bit: 0 failures, 451 ms each
40 MS/s 10-bit: 0 failures, 451 ms each
16 MS/s 10-bit: 0 failures, 452 ms each
INFO afterwards: ESP32SDR 6 burst 16380

$ esp32sdr tune 2600
error: 2600 MHz outside supported range 1850-2500 MHz      (exit 1, nothing sent)
$ esp32sdr tune 1849
error: 1849 MHz outside supported range 1850-2500 MHz      (exit 1)
```

350 captures, zero CRC failures, no resets or hangs. Per-capture time is the UART transfer
(32,760 B at 8-bit ≈ 355 ms at 921600 8N1). **Pass.**

## U5.7 fresh clone to first spectrum (SC1)

Method (as U1.6 did): `git clone --recursive` of the local repo into `/tmp/u5-clone`, then copy
the uncommitted working-tree files over it (modified + untracked, minus build dirs and venvs),
then run the commands from `docs/devkitv1/README.md` in order. Wall-clock per step, 2026-11-05:

| Step | Command | Time |
| --- | --- | --- |
| clone + copy | `git clone --recursive …` + copy | < 1 s (local clone) |
| build | `. ~/esp/esp-idf/export.sh; python3 tools/build_firmware.py --profile esp32-devkitv1 --version dev --output /tmp/u5-art` | 49 s (rc 0) |
| host install | `cd host && python3 -m venv .venv && . .venv/bin/activate && pip install -e .[dev]` | 5 s (`pytest`: all passed) |
| flash | `python -m esptool … -b 921600 … write-flash …` (README "Flash") | 11 s |
| info | `esptool` hard reset, then `esp32sdr info` | 2 s (`TRANSPORT UART 921600`) |
| capture | `esp32sdr capture --freq 2437 --rate 40 --n 16380 -o fresh-ch6` | 2 s (CRC ok) |
| spectrum | `esp32sdr spectrum --freq 2437 --bins 1024 -o fresh-spec.csv` | 1 s (44 frames, 128 FFTs) |

Total ≈ 70 s of machine time; with typing, well under the 10 minutes of SC1. **Pass.**
Caveats: the IDF toolchain was already installed and pip packages were cached (a first-time IDF
install is not part of SC1); the local clone hides network time. The working tree at that moment
included uncommitted U6a firmware changes, so this build's `CAPS` also listed `IQS FOFS`.

## U7.5 – 60 s IQS stream at 2402 MHz (2026-11-05)

`esp32sdr stream --freq 2402 --dec 512 --bits 8 --seconds 60 -o /tmp/u75/ble` on the DevKit V1 (921600 baud):

- 1 874 990 samples (31 250 S/s × 60 s), 3663 frames, bad_crc 0, seq_gaps 0.
- Lost 0 samples (0.0000 %, target < 0.01 %): index gaps 0 + tail 0; firmware IQSEND cross-check reports 0 lost pairs / 512 dec. Loss is counted exactly.
- Plot: `docs/devkitv1/bench/u75-ble-2402.png` (4 ms power vs time + spectrogram).
- Bursts: 39 distinct bursts ≥6 dB above the median in 60 s (e.g. t = 0.08, 1.68, 2.29, 2.63, 2.84, 3.18, 3.40, 3.96 s …). They are irregular, median spacing ≈ 1.07 s (10–90 % range 0.34–2.56 s): several nearby devices advertise at once, so no single fixed interval was resolved. The 31 kHz bandwidth sees only a ~31 kHz slice of a 1 MHz BLE channel, so some packets are missed. Bursts are clearly visible; a single known phone was not isolated.

## U8 – rtl_tcp bridge scripted on real board (2026-11-05)

`esp32sdr bridge --listen 127.0.0.1:1234 --freq 2402 --dec 512 --bits 8` plus a Python rtl_tcp client (`/tmp/u75/client.py`):

- Header `RTL0`, tuner type 5, 29 gains: correct.
- Sustained rate 31 086 / 31 181 S/s over 10 s (expected 31 250).
- Cmd 0x01 → 2400, 2483, 2426 MHz: bridge logged each tune, samples kept flowing after each (rates read 38.7 kS/s only because the client slept 1.5 s and drained the backlog), stream stops reported lost 0 samples.
- Disconnect and reconnect worked (second client got the header and ~31.2 kS/s at the last tuned frequency, 2426).
- After: `esp32sdr info` answers normally; no bugs found, no code changed; pytest 62 passed.
- U8.3 (real gqrx) still needs a human.

## US2.2 BLE advertising on/off test (2026-11-05)
Stream at 2480 MHz (BLE ch39, clear of Wi-Fi), dec 512, 8-bit, 31.25 kS/s, 20 s per run, 0 lost samples in every run.
iPhone on top of the board running nRF Connect's advertiser (iOS default interval/power), same position for both runs.
Detection: DC removed, |x|^2 smoothed over 3 samples (96 us), threshold = 99.99th percentile of the OFF run; events merged within 2 ms.

| run | events / 20 s | rate | median interval |
|-----|---------------|------|-----------------|
| advertiser off | 27 | 1.35 /s | 400 ms (no periodicity) |
| advertiser on  | 259 | 12.95 /s | 66 ms; histogram peaks at ~35 ms with multiples at 70/105/140 ms |

Result: ~10x more bursts with the advertiser on, periodic at ~35 ms (advertising interval plus BLE's 0-10 ms random delay; multiples are missed detections). US2.2 passes.
Plots: `bench/ble-onoff/{compare_on_off,on,off,first_unsure}.png`; script `bench/ble-onoff/analyze.py`. Raw SigMF in /tmp/ble (not kept in repo).

### Isolating the phone's packets (timing + strength), same recordings
`bench/ble-onoff/isolate.py` -> `bench/ble-onoff/phone_isolation.png`. Pulses = local peaks >= 18 dB above a 50 ms running-median noise floor (gain-independent SNR).
Periodicity search (pairs with gap in [T, T+10.5 ms], BLE's random advDelay) peaks at T = 29.5 ms in the ON run, with harmonics; nothing at that T in the OFF run.
Greedy chain at T: ON -> 515 of 1026 pulses form one train spanning 19.6 s (89% of the expected events; in-train gaps uniformly 29.5-40 ms = T + U(0,10 ms)); OFF -> only 24 pulses chain by chance (4%).
Train pulses are stronger (median SNR 23.3 dB vs 20.7 dB for other pulses), consistent with the phone lying on the board.
The OFF run shows a different weak periodic source near 90 ms (peaks at ~180/270 ms), i.e. another nearby device.

## FrSky D8 (EMAX E8 transmitter) detection, 2026-11-05
Receive only. E8 ~0.5-1 m from the board, drone off. Hop table, TX id and offset taken from the drone's Betaflight backup (`auto-drone/stage4/recovery/evidence/diff_all.txt`: `frsky_spi_bind_hop_data`, 47 entries). Channel n = 2404.000 MHz + n x 299.93 kHz (CC2500 FREQ 0x5C7627, CHANSPC 0x23/0x7A per Betaflight `cc2500_frsky_shared.c`); D8 modem: GFSK ~31 kbaud, +-31.7 kHz deviation.
1. Full-band max-hold (SPEC, 80 MS/s, 2048 bins, 5 s, E8 on vs off): with gain-independent peak heights, the 47 hop channels average +10.8 dB vs -0.1 dB on the 199 unused grid channels (off: +0.1 / +0.1). Best-fit combined frequency error about -35..-65 kHz (flat optimum -100..-30 kHz). `bench/d8/maxhold_on_off.png`, `hop_alignment.png`.
2. Hop cycle: 20 s of time-stamped wideband snapshots (835 frames) folded at the fitted cycle 422.70 ms = 47 x 8.994 ms. Each slot's energy sits on the table entry for that slot (bright diagonal); matched score 23.4 dB vs 4.5 +- 0.2 dB for random slot assignment (z ~ 89). E8 off at the same period: 3.1 vs 2.9 +- 0.1 dB (no structure). `bench/d8/hop_cycle_on.png`, `hop_cycle_off.png`.
3. Single-channel stream (2421 MHz + FOFS 31, dec 256, 4-bit, shift 10): bursts recur with the hop cycle; the 4-bit default shift (11) rounded almost everything to 0, so `IqsSession` gained an optional `shift`. The single-channel fold picked 425.95 ms, which is wrong (the wideband fit above is authoritative); two strong slots per cycle there are not yet explained.
