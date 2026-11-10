# Notice

This repository is licensed under the MIT License (see `LICENSE`), with these exceptions:

- `tools/betaflight-patch/` and `tools/cc2500-rxdiag/` contain patches to, and
  binaries built from, Betaflight (<https://github.com/betaflight/betaflight>,
  GPL-3.0-or-later). They are derivative works of Betaflight and are licensed
  GPL-3.0-or-later; each directory carries a copy of the GPL in `LICENSE`.
- `firmware/test/bf_bind_port.c` and `firmware/test/bf_bind_port.h` are a C port of
  Betaflight `getBind1`/`getBind2` and are GPL-3.0-or-later (SPDX header in each).
  They are host-test-only; the ESP32 firmware does not include or link them.

The RX chapters of `docs/lab-log/` describe receive-only work done with the
ESPARGOS esp-sdr firmware (<https://github.com/ESPARGOS/esp-sdr>); that code lives in
the public RX repository (<https://github.com/mb6611/esp32-d8rx>). No esp-sdr
source code is in this repository or its history.
`firmware/main/tlm_cap.c` is an independent single-core implementation of the
bank-rotation + sentinel capture scheme of esp-sdr's `main/common/ring_capture.c` (itself
after h0m3us3r/eSpDR); it shares only the ESP32 register addresses and start sequence.

ESP-IDF (Espressif, Apache-2.0) is used as the build toolchain; it is not vendored.
