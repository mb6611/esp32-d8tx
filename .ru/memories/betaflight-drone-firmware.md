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
- Binding the drone's receiver needs no CLI and no reboot: MSP v2 `MSP2_BETAFLIGHT_BIND` (0x3000) over USB works on this 4.2.11 build (Nov 9 2026, 3/3 binds). The app's Bind button and `packages/core/scripts/bind-check.ts` use it; CLI `get frsky_spi_tx_id` verifies, but leaving the CLI reboots the FC.

**Why:** cost Track 2 several reflashes on 2026-11-08.
