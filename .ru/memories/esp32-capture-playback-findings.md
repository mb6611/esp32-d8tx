---
name: esp32-capture-playback-findings
description: Read before planning any I/Q capture, TX playback or self-loopback experiment on the classic ESP32; what stages 0–2 measured (sizes, rates, timing, register facts), the analysis pitfalls, and why the on-chip self-observation test was inconclusive, as of Nov 2026.
load: description
---
Measured facts (details, tables and evidence in the READMEs; rerun with the script named):

- **Capture** (stage 0, `stage0/capture.py`, esp-sdr firmware): CAP16 bursts of 16380 samples
  at 40 MS/s (≈410 µs), 8- or 10-bit I/Q, hardware AGC, rates 80/40/16 MS/s. Q must be negated
  for standard I/Q. One burst per host round trip; it is not a continuous stream.
- **Playback engine exists on the classic ESP32** (stage 1 census, `stage1/collect.py`;
  stage 2 behaviour, `stage2/run.py`): `0x60033d98` (DUMP_CTRL + 8) has the ESP32-S3 TX engine's
  exact mask `0x8FF8BFFF` and behaves like it: run bit 31, done bit 18 (RO), hold bit 19 is a
  start gate, rate bit 15 (1 = 80.01 MS/s, 0 = 40.00 MS/s), N = count + 1 samples, 1…16384,
  count 0 never completes. The 64 KiB window `0x3ffe8000..0x3fff7fff` is the whole buffer.
  No loop/retrigger mode: run must be cleared before rearming. MCU-driven back-to-back gap is
  ≈0.5 µs at 40 MS/s (≈20 samples) and ≈0.57 µs at 80 MS/s (≈45 samples), an upper bound only.
  Bank grant (MAC_DUMP_MODE) and `0x60033dc0/dc8/dcc/dbc` change nothing measurable.
- The engine sequences addresses through sample memory (a concurrent capture lands at the
  engine's pointer and rate) but never writes. Reading the data and reaching the antenna are
  **not shown**.
- Keying facts: tone register `0x600060b8` (bit 18 enable, gain `[17:10]`); keying methods
  are the `K` command in `stage2/txeng/main/txeng.c`.
- **Ring/streaming (fork U4, 2026-11-05, `docs/devkitv1/ring-feasibility.md`)**: capture ctrl bit 17 =
  ring. `MAC_DUMP_MODE` 2/1/3/0 gives RF the lower/upper/both/no 32 KiB bank; CPU reads of an RF-owned
  bank return constant `0xa55aa55a` (so RINGPROBE `live` is an artefact); modes 1/2 drop writer offsets
  ≥ 8192. Ping-pong (8192-word ring, toggle 2↔1 at wrap) loses only k≈0–7 samples per half; app-CPU
  boxcar ÷16 costs ~5.4–6.1 cycles/pair. Interrupt-masked probe loops > ~300 ms trip the interrupt WDT.
- **IQS stream (fork U6b, 2026-11-05, `main/targets/esp32/iq_stream.c` header)**: switching banks every
  8064 pairs (not at the wrap) with sentinel zones gives 0 lost pairs (60 s, 960 M pairs). With the RF
  writing the other bank, app-CPU stage 1 costs ~12–13 cycles/pair, not the probe's 6 (probe ran RF
  stopped). Both CPUs running hot code from IRAM slowed each other badly; core-0 DSP moved to flash fixed
  it. Recheck these if the DSP chain or code placement changes.
- Host serial: setting the pyserial `timeout` before every read drops bytes on this CP2102 link; read
  replies in bulk with a fixed timeout.
- **Orientation (U5.5, 2026-11-05, `docs/devkitv1/bench-results.md`)**: host-decoded CAP16 with Q negated
  puts RF at LO + f; on-chip `SPEC` bins (natural order) are mirrored, RF = LO − f. Ambient-only
  "tune 10 MHz below a channel" tests are ambiguous here (busy band, sparse bursts); an LO sweep
  correlation (`docs/devkitv1/bench/orientation_sweep.py`) settled it.

Analysis pitfalls each README records:
- Stage 0: a 16k-bin single FFT shows ≈22 dB "peak over median" from noise alone; averaged
  spectra show ≈21–28 dB more power inside ±8 MHz, which is the analog low-pass, not WiFi.
  AGC was on, so levels are not calibrated.
- Stage 1: read side effects cannot be told from live counters; `0x60033db4` counts on its own,
  so its RW mask is an artefact. Five addresses (`d00..d20`, 8-byte stride) WDT-reset the chip
  after a write-1.
- Stage 2: analyse only the words the capture actually wrote; taking the first 8000 words of a
  dump produced a fake −625 kHz line from untouched pattern words. The first concurrent capture
  after boot starts ≈4 µs late (later ones 75 ns).

Why self-observation was inconclusive (stage 2, E): with the engine keyed and a concurrent
capture, no line appeared, but the positive control (CPU toggling the tone register at 250 kHz
during a capture) showed nothing either, in every keying mode, with AGC and with forced max
gain. In `K 0` (txcal mode) the RX is effectively deaf. So this chip's RX cannot see its own
TX, and the null says nothing about whether the engine radiates. **Any radiate/not test needs
an external receiver** (an SDR, or a second ESP32 running esp-sdr) pointed at 2412 ± 40 MHz
while `T` with the key flag repeats.

**Why:** the register layout and engine behaviour were reverse-engineered from scratch across three stages, and each pitfall produced a false result once before it was caught.
**How to apply:** treat the numbers as measured on one board; rerun the script if a plan depends
on a tighter bound (the seam, the power scale and the data path remain unmeasured).
