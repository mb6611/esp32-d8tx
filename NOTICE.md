# Notice

This repository is private, all rights reserved (see `LICENSE`), with these exceptions:

- `bench/betaflight-patch/` and `bench/cc2500-rxdiag/` contain patches to, and
  binaries built from, Betaflight (<https://github.com/betaflight/betaflight>,
  GPL-3.0-or-later). They are derivative works of Betaflight and are licensed
  GPL-3.0-or-later; each directory carries a copy of the GPL in `LICENSE`.

The RX-era host tools in `host/esp32sdr/` and notes in `docs/devkitv1/` were
written to talk to the ESPARGOS esp-sdr firmware (<https://github.com/ESPARGOS/esp-sdr>)
over its serial protocol. No esp-sdr source code is in this repository or its history.

ESP-IDF (Espressif, Apache-2.0) is used as the build toolchain; it is not vendored.
