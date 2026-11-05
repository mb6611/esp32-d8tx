<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# IQS over UART: link budget (single source)

Firmware (`receiver.c`) and host (`host/esp32sdr/iqs.py`) both implement exactly
the table below. Change it here first.

## Formula

- Link: 921600 baud 8N1 = **92,160 B/s** usable.
- Allowed: total ≤ **85 %** = 78,336 B/s.
- Payload rate = `fs/dec × 2 × bits/8` bytes/s (4 bits: 1 byte per I/Q pair;
  1 bit: 4 I/Q pairs per byte).
- Framing: 28 bytes per frame (24 header + 4 CRC32), frames carry ≤ 1024
  payload bytes, so total = payload × (1 + 28/1024).
- `fs` is 16 MS/s (rate code 6). Rate codes 0 and 1 (80, 40 MS/s) are refused
  on ESP32: the DSP and seam loss only fit at 16 MS/s (`ring-feasibility.md`).

## Allowed table (rate_code 6, dec power of two 64..1024)

| bits | dec | output rate | payload B/s | total B/s | % of 92,160 | allowed |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 64 | 250 kS/s | 62500 | 64209 | 69.7 | yes |
| 1 | 128 | 125 kS/s | 31250 | 32104 | 34.8 | yes |
| 1 | 256 | 62.5 kS/s | 15625 | 16052 | 17.4 | yes |
| 1 | 512 | 31.25 kS/s | 7812 | 8026 | 8.7 | yes |
| 1 | 1024 | 15.625 kS/s | 3906 | 4013 | 4.4 | yes |
| 4 | 64 | 250 kS/s | 250000 | 256836 | 278.7 | no |
| 4 | 128 | 125 kS/s | 125000 | 128418 | 139.3 | no |
| 4 | 256 | 62.5 kS/s | 62500 | 64209 | 69.7 | yes |
| 4 | 512 | 31.25 kS/s | 31250 | 32104 | 34.8 | yes |
| 4 | 1024 | 15.625 kS/s | 15625 | 16052 | 17.4 | yes |
| 8 | 64 | 250 kS/s | 500000 | 513672 | 557.4 | no |
| 8 | 128 | 125 kS/s | 250000 | 256836 | 278.7 | no |
| 8 | 256 | 62.5 kS/s | 125000 | 128418 | 139.3 | no |
| 8 | 512 | 31.25 kS/s | 62500 | 64209 | 69.7 | yes |
| 8 | 1024 | 15.625 kS/s | 31250 | 32104 | 34.8 | yes |
| 16 | 64 | 250 kS/s | 1000000 | 1027344 | 1114.7 | no |
| 16 | 128 | 125 kS/s | 500000 | 513672 | 557.4 | no |
| 16 | 256 | 62.5 kS/s | 250000 | 256836 | 278.7 | no |
| 16 | 512 | 31.25 kS/s | 125000 | 128418 | 139.3 | no |
| 16 | 1024 | 15.625 kS/s | 62500 | 64209 | 69.7 | yes |

Allowed set (machine-readable, for the host test):

```
ALLOWED rate=6 bits=1 dec=64,128,256,512,1024
ALLOWED rate=6 bits=4 dec=256,512,1024
ALLOWED rate=6 bits=8 dec=512,1024
ALLOWED rate=6 bits=16 dec=1024
```

Anything else gets `ERR args` from the firmware before any reconfiguration.

## 1-bit (hard-limited) samples

`bits` = 1 is a devkitv1 addition (not on the S3) for FSK such as FrSky D8
(GFSK ≈31 kbaud, ±31.7 kHz deviation). Use dec 64 (250 kS/s, 8 samples per
symbol, 69.7 % of the link): sign quantization creates odd harmonics, and at
dec 128 (125 kS/s) the −3rd harmonic of one FSK tone aliases onto the other
(simulated D8 BER 1–23 %, against ≈0–0.2 % at dec 64). The filter
chain is unchanged; only the output step differs: each filtered sample keeps
the sign of I and of the (negated) Q word, `shift` is ignored (still echoed).
Framing, CRC and loss accounting are the same IQS1 frames
(`docs/iq-stream.md`); header `bits` = 1 and `samples` counts complex samples
(≤ 4096 per frame). Payload byte *b* holds samples 4*b* … 4*b*+3; sample *k*
of a byte has the I sign in bit 2*k* and the Q-word sign in bit 2*k*+1, 1 =
negative (0 counts as positive). The payload is `ceil(samples/4)` bytes, the
unused bits of the last byte are 0. Hosts decode to ±1 ± 1j (Q negated as for
other widths); amplitude is lost, phase/frequency is kept.

Measured on the bench (2026-11-05, ambient 2440 MHz, `host/tools/bench_iqs1bit.py`):
1-bit dec 64, three 20 s runs and a 20 s `esp32sdr stream`: 0 index gaps, 0
frame drops, 0 lost pairs; app-CPU `work_max` 99886–107620 of 120960; core 0
about 50 % busy (`IQSPROF`, block queue peak ≈1100 of 8192). Dec 128: 43 %.


## Centre frequency and mode 2

`python -m esp32sdr.cli stream --center 2421.032 --mode 2 --bits 1 --dec 64 ...`
puts 2421.032 MHz at 0 Hz: the LO goes 4 MHz below (FREQ 2417, FOFS 32) and the
on-chip j^n rotation shifts it back, keeping the LO leakage out of band
(convention and ruler check: `../iq-stream.md`). `--freq/--fofs` still name the
LO directly; with `--mode 2` the wanted centre is then LO + 4 MHz.
