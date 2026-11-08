---
name: blackbox-vcp-hang
description: Read before enabling Betaflight blackbox, arming with blackbox on, or USB-resetting the MATEKF411RX drone FC; what happened on 2026-11-08.
load: description
---
Blackbox logging to the shared USB VCP (`serial 20 129 … 2000000`) on the MATEKF411RX (BF 4.2.11, F4) makes the FC re-init USB on every arm and disarm. On the bench Mac, the port then goes silent: MSP and `d8tx.server` stop working until a host libusb reset (`bench/blackbox/usbreset.py`). Repeated resets (one every 1.5 s) hung the FC: no USB and no radio telemetry, and only a physical replug fixes that, which needs the owner.

**How to apply:** don't leave blackbox on the VCP enabled. Check `bench/blackbox/results/NOTES.md` for the revert and current state. Never loop USB resets on the FC. If you need a log, use at most one reset per arm, or use a UART logger.
