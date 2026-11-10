# 02: Register map of the ESP32 radio

[01](../01-playback-engine-check/README.md) left the playback engine open: the ESP32 keyed its transmitter, and nothing showed whether the samples went out with it. Before trying more RF tests I wanted to know what the classic ESP32's transmit path actually consists of, and which register could stop the samples from reaching the antenna. Espressif doesn't document this part of the chip, so the map had to come from reading code and from a few reads on my own board.

Most of the work was reading: disassembly of the ESP32 ROM and of the closed vendor libraries (`libphy`, `librftest`, `libpp`), the ESP-IDF headers, and a third-party register reference for the ESP32-S3, which has a working I/Q transmit path. Each row in the map carries how it is known: measured on my board, mapped from the binaries, translated from the S3 by offset or shape, or unknown. I kept those apart because a register at the same offset on another chip proves nothing about this one.

The first thing the reading showed was that no classic ESP32 vendor binary refers to `0x60033d98`. The classic `librftest` has a capture trigger (`adctrig`) but no playback trigger (`dactrig`); the S3 has one, writing a register with the same bit mask. So everything known about the classic engine came from my own experiments, with no vendor recipe to copy. From those experiments, measured on the board: bit 31 starts it, bit 18 reports done, bits 13:0 hold the sample count minus one (up to 16,384 samples), and bit 15 switches the completion time between 80.01 and 40.00 MS/s. A concurrent capture showed the engine stepping through the addresses `0x3ffe8000 + 4·i` at that rate. None of this shows that it reads the data at those addresses, or that its output feeds the DAC (the digital-to-analog converter in front of the transmitter).

Then I looked for something that could block it. On the S3, a tone generator (NCO) left switched on blocks I/Q transmission. The classic chip has three tone registers, `0x600060b8`, `bc` and `c4`, each with an enable at bit 18. With the board idle I read b8 = `0x2003a020`, bc = 0 and c4 = 0, so no enable was set at boot. I then read them during two keyed bursts at 2412 MHz in key mode `K 0` (6,144 samples, power 127 and 0), at five points: after keying, after the firmware cleared b8's enable, right after starting the engine, at done, and after unkeying. b8's enable was set by keying (`0x20060400`) and stayed cleared from then on (`0x20020400`); bc and c4 read 0 at all five points. The FE2 transmit interpolator at `0x600050f0`, which by its IDF name sits just before the DAC, read `0x464` in every phase: its force-power-up bit set and power-down clear, so it was not forced off. The clock and force register `0x600060a0` changed from `0x0100c000` idle to `0x4103c000` while keyed, and I couldn't tell what the changed upper bits mean.

For the DAC clock, the classic ROM has no `rom_dac_rate_set`, the function the S3 uses. I found a `DIV_DAC` bit in the BBPLL's I2C register 11 and read it idle: register 10 = `0x10`, register 11 = `0xc2`, so `DIV_DAC` = 0. I didn't read it while keyed.

So in the one mode I tested, the two blockers I could name, a tone enable left on and the interpolator held down, weren't there. What still decides whether the samples reach the antenna stayed unknown: which input the DAC takes, at what rate, and which memory bank the engine needs to read. The tests that could settle it either write PHY state or need an in-slice positive control, which [01](../01-playback-engine-check/README.md) showed I didn't have. I didn't run them. The map did give me the tone path in detail: `rom_start_tx_tone_step` sets a signed frequency step, and in fine mode (b8 bit 29, set at boot) one step should be 40 MHz / 1024 = 39.06 kHz. That was an inference from the code. Keying that tone is what [03](../03-tone-first-attempt/README.md) tried, and [04](../04-tone-scan/README.md) measured the step at about 39 kHz.

---

## Numbers

| What | Value | Where |
|---|---|---|
| Tone enables b8 / bc / c4 bit 18, idle | clear / clear / clear | `data/idle-check/README.md` |
| bc, c4 during two keyed bursts (5 phases each) | 0 throughout | `data/keyed-read/README.md` |
| FE2 interpolator `0x600050f0`, idle and keyed | `0x464` (power-up forced, power-down clear) | `data/idle-check/`, `data/keyed-read/` |
| BBPLL register 11, `DIV_DAC`, idle | `0xc2`, bit 0 = 0 | `data/dac-clock-read/log.txt` |
| Keyed burst length, power 127 / 0 | 371 / 162 µs | `data/keyed-read/README.md` |

## Files

- `data/README.md`: the map itself (a living document, kept as it was).
- `data/research/`: the long-form audits it cites (`measured.md`, `vendor-tx.md`, `vendor-functions.md`, `tx-path-search.md`).
- `data/*/`: each hardware read with its own README and raw log.
- `scripts/`: the four read scripts.

## How to re-run

There is no offline analysis: the map is text. The read scripts are hardware scripts; they need the ESP32 running the [txeng](../../tools/txeng/README.md) firmware, whose host code the scripts import from there. `keyed-read/keyed_read.py` writes its log and JSON under `data/keyed-read/`. The register census and engine run results the map cites are under `data/register-census/` (`census.csv`, `census.log` and the census source) and `data/engine-runs/` (`results.csv`; the 9.7 MB `results.log` is not included).

## Ran

2026-11-06, finished by 13:38 EST, when commit 8dde1a9 added the map, all four research files and all four hardware reads. The research files say "2026-11-06" (`tx-path-search.md` says "Written 2026-11-07", which can't be right, since it is in that commit). The hardware reads are dated only "2026-11" in their READMEs; no exact time was recorded.

**Overlap:** this may have run alongside 03 (00:37 EST) and 04 (12:20 EST) on 2026-11-06. It is placed here because it follows from 01, not by its start time, which I don't have.

Previous: [01-playback-engine-check](../01-playback-engine-check/README.md) · Next: [03-tone-first-attempt](../03-tone-first-attempt/README.md) · [All experiments](../README.md)
