# Fast retune (hop) feasibility on the classic ESP32

Question: can the DevKit V1 follow a FrSky D8 hop schedule (a new channel every ~9 ms,
packets ~6.7 ms, so retune plus settle must fit in ~2 ms) by retuning without the DC/gain
recalibration that `FREQ` runs on every MHz change (25–60 ms)?

**Answer: yes.** The synthesizer-only retune takes 0.19–0.33 ms on-chip. The LO is at the
new frequency when the call returns. One calibration at any channel serves all 47 D8
channels: lock, DC and clipping matched a fully recalibrated tune on every channel.

Measured 2026-11-05 on one board (ESP32-D0WD-V3, 40 MHz crystal), receive only.

## Probe

The probe is compiled only with `-DHOP_PROBE=ON`, in `main/targets/esp32/hop_probe.h`
(included from `receiver.c`). The define sits in `main/CMakeLists.txt` next to
`RING_PROBE`. Default builds are unchanged: the preprocessed `receiver.c` is identical
with and without the hook. Host side: `host/tools/probe_hop.py`.

```
idf.py -B build-esp32-devkitv1-hop -DIDF_TARGET=esp32 -DSDKCONFIG_DEFAULTS=sdkconfig.defaults.esp32-devkitv1 -DHOP_PROBE=ON build
idf.py -B build-esp32-devkitv1-hop -p /dev/cu.usbserial-0001 -b 921600 flash
cd host && .venv/bin/python tools/probe_hop.py timing|settle|sweep
```

| Command | What it does |
|---|---|
| `HOPFULL khz` | Ordinary tune with recalibration (the `FREQ` + `FOFS` path) |
| `HOPT ka kb n mode` | `n` fast retunes alternating between `ka` and `kb`, each phase timed with CCOUNT |
| `HOPCAP khz mode rate n at_us fmt` | One capture, with a fast retune `at_us` into it (0 = retune just before it) |
| `HOPREG` | Dumps I2C block 0x62 (host 1) registers 0–15 |

The retune modes, all without recalibration:

- 0: `set_chanfreq(2412)`, then release the capacitor code (0x62/1/0 bit 7), then
  `rom_set_rf_freq_offset`. This is what `tune_rx` does.
- 1: capacitor-code release, then `rom_set_rf_freq_offset`.
- 2: `rom_set_rf_freq_offset` alone.

## Retune time (on-chip, 200 retunes each)

Calibration was done once at 2440 MHz. Columns are median / max in µs.

| Hops | Mode | set_chanfreq | cap release | ROM retune | total |
|---|---|---|---|---|---|
| 2404 ↔ 2477 | 0 | 164 / 231 | 12 / 16 | 245 / 256 | 421 / 500 |
| 2404 ↔ 2477 | 1 | — | 12 / 17 | 245 / 252 | **257 / 265** |
| 2404 ↔ 2477 | 2 | — | — | 245 / 252 | 245 / 253 |
| 2440 ↔ 2440.3 | 0 | 164 / 227 | 12 / 16 | 271 / 325 | 448 / 519 |

In the settle runs, the ROM call alone took 185–265 µs depending on the pair and direction.
`set_chanfreq` is not needed and should be skipped: its call also produces a ~20 µs
saturating burst (|DC| ≈ 590, +36 dB power) about 240 µs in. Mode 1 is the one to use.
Mode 2 works only while bit 7 of the capacitor code stays clear, and any `set_chanfreq`
sets it again. The 12 µs release is cheap insurance.

## Settle time

Method: the retune runs 100 µs into a 1 ms capture at 16 MS/s, 20 runs per direction, with
manual gain 50. The tracked signals are the board's own 40 MHz crystal harmonics at 2400.000
and 2480.000 MHz: steady narrow lines that sit at an exact baseband offset only if the LO is
locked at the requested frequency. Each line's power is measured in 8 µs sliding windows, and
the median is taken across runs.
(`docs/devkitv1/bench/fast-hop/settle-16msps.txt`)

| Hop | Mode | Call (µs) | Old line gone | New line within 3 dB of final |
|---|---|---|---|---|
| 2404 → 2477 | 1 | 265 | +31 µs after start | 62 µs **before** return |
| 2477 → 2404 | 1 | 265 | +31 | 4 µs before return |
| 2404 → 2410 | 1 | 185 | +31 | 2 µs before return |
| 2410 → 2404 | 1 | 265 | +55 | 3 µs before return |
| 2404 ↔ 2477 | 2 | 253 | +19 | 63 / 4 µs before return |
| 2404 ↔ 2477 | 0 | 500–526 | +56–72 | 35 / 4 µs before return |

The LO leaves about 20–55 µs after the call starts. It reaches the new frequency at or
before the moment the call returns, with nothing to wait for afterwards. Within the window
resolution (8 µs) the receiver is usable when `rom_set_rf_freq_offset` returns. Quiet-window
DC stays at 1–5 (10-bit units) through the whole hop. There is a brief +3 dB power bump
about 20 µs into the call.

**Retune plus settle: ≤ 0.27 ms (mode 1) out of the ~2 ms budget.**

## Lock and calibration across the span

`probe_hop.py sweep` covered all 47 D8 channels (2404.000 MHz + n × 299.93 kHz) in hop
order. Calibration was done once at 2404 MHz, the worst case at the band edge. Each channel
was reached by a mode-1 fast retune from the previous hop channel and compared with a
recalibrated `HOPFULL` tune at the same frequency. Settings: 80 MS/s, `BANDWIDTH 67`
(which puts a harmonic ruler line in view for every channel), manual gain 50, 4–6 captures
of 16380 samples per channel and per method.
(`docs/devkitv1/bench/fast-hop/sweep-ref2404-80msps.log`)

| Metric (47 channels) | Fast retune, calibrated once | Recalibrated |
|---|---|---|
| Ruler line position error, max (median) | 4.1 (1.2) kHz, under 1 FFT bin (4.88 kHz) | same bins |
| Ruler line SNR, min / median | 5.4 / 23.9 dB | 2.3 / 23.9 dB |
| Quiet-window DC, median / max | 3.1 / 6.2 | 2.9 / 6.3 |
| Clipped samples, mean / max | 0.35 % / 6.5 % | 0.15 % / 6.2 % |

- **Lock:** on every channel the line sat in the expected bin after the fast retune. The
  three weakest cases (5–9 dB, near 2440 MHz where the line is only 1.8–3.9 MHz from DC)
  were equally weak after a full recalibration.
- **DC and clipping:** no difference beyond capture-to-capture spread. Clipping tracks
  ambient Wi-Fi bursts, which vary minute to minute here, not the tune method.
- An earlier run with calibration at 2440 MHz and 40 MS/s, `LPF AUTO`
  (`sweep-ref2440-40msps.log`) agrees: the line landed in the expected bin wherever it
  cleared 8 dB (24 channels). During a quiet ambient stretch (the last 10 channels), the
  fast and full results matched closely (|DC| 1–6 vs 2–4, noise 6–11 vs 7–9).
- `rx_recalibration_stale()` stayed 0 throughout. The PHY did not replace the DC tables.

**Per-channel stored calibration is not needed** for receive across 2404–2477.5 MHz, at
least at fixed gain. One calibration at boot is enough.

## Lock bit

None found. `HOPREG` showed only register 5 of 0x62/1 changing across a retune
(0x7c → 0x66). That looks like the VCO band code the ROM call selects, not a status flag.
The crystal-harmonic lines are the practical lock check.

## What a hop receiver needs

1. Calibrate once, at boot or at any channel (`rx_recalibrate` via the normal tune).
2. Per hop: precompute (MHz, 1/1024-MHz offset) per channel, then release the capacitor
   code and call `rom_set_rf_freq_offset` (mode 1). Never call `set_chanfreq` or
   `rx_recalibrate` per hop. Budget 0.3 ms of CPU, blocking, with I2C to the analog block.
3. Blank or discard samples from the call's start to its return (≤ 0.27 ms). The LO is
   moving during that time.
4. Retune between packets, then schedule the hop timing: on-chip from a packet or timer,
   because a host round trip (~2.7 ms per command over the UART) eats the budget.
5. Keep watching `rx_recalibration_stale()`. It never fired here, but a recalibration
   (25–60 ms) would cost a few hops.

## Not measured

- Hardware AGC across the span after one calibration. The sweep used manual gain 50.
  Spot checks with AGC showed nothing odd, but ambient bursts dominated them.
- Long runs and temperature drift (each sweep lasted minutes).
- Retuning while an IQS stream runs. The probe uses one-shot captures. In the stream the
  retune would run on core 0 while the app CPU keeps switching banks.
