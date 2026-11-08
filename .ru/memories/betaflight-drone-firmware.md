---
name: betaflight-drone-firmware
description: Read before building, flashing or configuring Betaflight on the Tinyhawk drone (MATEKF411RX) for this project; gyro, DFU and CLI pitfalls found Nov 2026.
load: description
---
- The drone's gyro is an ICM20689; a bare 4.2.11 MATEKF411RX source build only enables MPU6000 and boots with NO_GYRO. bench/betaflight-patch/patches/0002 adds it (check it still exists).
- DFU without touching the drone: Betaflight CLI `bl`, then dfu-util 0483:df11 (see bench/betaflight-patch/README.md). Flashing wipes config; replay the saved `diff all`.
- A source build has target defaults the stock image lacked (e.g. `resource LED 1 C13`); set it to NONE after replay to keep LEDs off.
- In the CLI, the first command after the `#` prompt can be swallowed (send a dummy line first), and `exit` without `save` loses changes.
- bf_msp.parse_analog vbat_dv was misaligned (reports 241 on 0 V, Nov 8 2026); check battery absence with CLI `status` or MSP_BATTERY_STATE.

**Why:** cost Track 2 several reflashes on 2026-11-08.
