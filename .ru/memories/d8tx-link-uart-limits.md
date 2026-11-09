---
name: d8tx-link-uart-limits
description: Read before changing how a host (TS or Python d8tx link) writes to or polls the DevKit firmware during LINK, or when judging STAT slot counts; firmware UART limits measured Nov 2026.
load: description
---
Measured on the DevKit with hw-check (2026-11, firmware d8tx-v1, TLM recipe every=12 stream=1 bits=4):

- During LINK the firmware ignores STAT with no reply while it ships a capture (`hop_drain`: `if (shp.busy) continue`). With telemetry on that was ~75% of STATs. Hosts must resend (TS D8Link resends on capture end and every 120 ms).
- Keyed and listen slots run with interrupts off for up to ~11.3 ms. Anything beyond the 128-byte UART RX FIFO arriving then is lost, and the firmware reads a torn line (`ERR unknown cmd`, link_end why=err). A host that catches up after a stall with 3 S lines + TID (129 bytes) killed the link. Keep S spacing >= ~0.8 slot.
- Firmware `slots` counts keyed TX slots only; listen slots (one per trigger + one per retry) are not keyed. With telemetry on, slots ~ 89-91% of elapsed slots by definition, not host loss.

**How to apply:** don't treat STAT timeouts or a ~90% slot ratio as link problems before checking these; prefer firmware fixes (answer STAT after shipping, tolerate unknown lines) if the owner wants them.
