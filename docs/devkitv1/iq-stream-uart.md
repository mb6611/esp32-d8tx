<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# IQS over UART: link budget (single source)

Firmware (`receiver.c`) and host (`host/esp32sdr/iqs.py`) both implement exactly
the table below. Change it here first.

## Formula

- Link: 921600 baud 8N1 = **92,160 B/s** usable.
- Allowed: total ≤ **85 %** = 78,336 B/s.
- Payload rate = `fs/dec × 2 × bits/8` bytes/s (4 bits: 1 byte per I/Q pair).
- Framing: 28 bytes per frame (24 header + 4 CRC32), frames carry ≤ 1024
  payload bytes, so total = payload × (1 + 28/1024).
- `fs` is 16 MS/s (rate code 6). Rate codes 0 and 1 (80, 40 MS/s) are refused
  on ESP32: the DSP and seam loss only fit at 16 MS/s (`ring-feasibility.md`).

## Allowed table (rate_code 6, dec power of two 64..1024)

| bits | dec | output rate | payload B/s | total B/s | % of 92,160 | allowed |
| --- | --- | --- | --- | --- | --- | --- |
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
ALLOWED rate=6 bits=4 dec=256,512,1024
ALLOWED rate=6 bits=8 dec=512,1024
ALLOWED rate=6 bits=16 dec=1024
```

Anything else gets `ERR args` from the firmware before any reconfiguration.
