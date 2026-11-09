# d8tx (Python reference library)

Reference implementation of the ESP32 D8 transmitter client, used by bench scripts and to generate the golden vectors in `../protocol/`. The app itself is now TypeScript (`../packages/*`, `../apps/web`, `../apps/desktop`); the FastAPI server (`d8tx.server`) has been removed. Private research code; see Section 8 of the [write-up](../docs/devkitv1/writeup/tx.md).

- `../protocol/PROTOCOL.md`: firmware protocol v1 (`LINK`, `S`, `STOP`, `FOFS`, `ARMOK`, `INFO`, `STAT`; replies `OK`/`ERR`, events `EV`).
- `python/d8tx`: `D8Link` (slot-rate sender, arm gate), `BetaflightMSP`, telemetry decoding.

## Run

```sh
cd python
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest        # no hardware needed
```

For the app: from the repo root, `pnpm install`, then `pnpm --filter web dev` or `pnpm --filter desktop dev`.

## Keys

Mode 2. **W/S** throttle (non-centering, starts at 0%), **A/D** yaw, **arrows** pitch/roll (eased), mouse drag on the sticks, **hold R** (1 s) arm, **X** disarm. Use one browser tab only.

## Safety

Channel 7 (ARM) is gated in the UI, in the library (`allow_arm`, default off) and in the firmware (`ARMOK`, cleared after each `LINK`). The backend stops after 250 ms of browser silence; the firmware ends the link after its timeout; Betaflight disarms 1.25 s after packets stop. Props off for testing.

## Betaflight gotchas

- Arms only with throttle at minimum when the arm switch rises; a refused arm with the switch left high blocks re-arming (`ARM_SWITCH`) until it goes low. The UI and library hold minimum throttle for 0.5 s after the arm edge.
- `RX_FAILSAFE` lasts about 2.5 s after the link appears.
- Runaway-takeoff protection disarms within seconds with props off; set the arm switch low to clear.

## Scripted hop

`python/examples/up_forward_land.py --dry-run` prints the open-loop timeline; no other process may hold the ESP32 port (close the app) when you fly it. Hover throttle is unknown (above 1550 µs on the bench quad), keep the forward tilt small, and log blackbox to tune.

## Radio telemetry

The ESP32 also listens for the drone's D8 telemetry replies; results and numbers are in Section 9 of the
[write-up](../docs/devkitv1/writeup/tx.md).

**Turning it on.** `D8Link.start(telemetry=True)` is the default. It sends
the `TLM` recipe (a trigger every 48 slots, about 2.3 replies/s; `protocol.TLM_RECIPE`) and, unless you pass `fofs_hz`,
`FOFS 0` (`protocol.DEFAULT_FOFS_HZ`). After an over-the-air bind (`D8Link.bind()`, which also sets FOFS first) the
receiver tunes itself to our carrier, so 0 is right: 94.9% of triggers answered at 0 against 72.9% at -75 kHz. The old
default -75000 only suited the cloned E8 binding (97.8-100% there); pass `fofs_hz=-75000` if you clone that identity. In Python: `D8Link.start(..., telemetry=True, fofs_hz=None)` and `D8Link.telemetry()`.
The drone needs `feature TELEMETRY` on for any hub data (A1/RSSI come regardless).

**Status fields.** the radio status object (same keys in the TypeScript core) has:

| key | meaning |
|---|---|
| `powered`, `link` | a reply within the last 3 s / 1 s |
| `catch_rate`, `triggers`, `replies` | replies/triggers over the last 10 s; running totals |
| `age_ms` | time since the last reply (about 0-430 ms when every trigger is answered) |
| `rssi`, `rssi_dbm` | the drone's RSSI byte, and its received power of our packets in dBm |
| `a1_raw`, `a2_raw`, `vbat_v`, `battery` | A1 = battery in 0.05 V steps (wraps at 12.75 V; hub VFAS used when present); `battery` is `absent` below 2 V |
| `cfo_khz` | carrier offset of the last reply |
| `hub` | `acc_mg`, `heading_deg`, `rpm`, `vfas_v`, `current_a`, `fuel`, `temp1/2`, `raw` (id -> value), `age_ms`; `patched` holds the patched-firmware fields (`armed`, `angle`/`horizon`/`acro`, `flight_mode`, `failsafe`, `arming_disabled`, `arming_disable_flags`, `gyro_dps`, `attitude_deg`) |
| `armed`, `armed_source` | `"patched"`: STATUS bit 0 from the patched firmware; `"rpm"`: inferred from the stock RPM field (can be `None`) |

**Bench notes.**
- Opening the ESP32 port reboots it. Wait about 3 s after connecting before Start link, or it can answer
  409 `no reply to 'FOFS 0'`. If the ESP32 is left streaming after a crash, reset it (EN/RTS) and wait about 4 s.
- Keep the Mac awake (`caffeinate -dimsu`) for long runs; idle sleep freezes the WebSocket.
- Stock Betaflight 4.2 sends ACC truncated to whole g (a level drone reads 0 or 1000 milli-g) and no arm state.

## Patched Betaflight and blackbox

- [`bench/betaflight-patch/`](../bench/betaflight-patch/README.md): Betaflight 4.2.11 for the MATEKF411RX with true
  milli-g ACC, STATUS/arming flags, gyro and attitude in the hub (IDs in `protocol/PROTOCOL.md`), plus the ICM20689 gyro driver this
  Tinyhawk needs. `./build.sh`, flash with CLI `bl` + `dfu-util`, roll back with `recovery/betaflight_4.2.11_MATEKF411RX.bin`.
  Flashing wipes the config: replay it per `bench/d8-tx/results/bf_link/RESTORE.md` (tx id 66,178, hop table, offset
  -32, `feature TELEMETRY`, LEDs off). Bench evidence: `bench/d8-tx/results/betaflight-patch/NOTES.md`.
- [`bench/blackbox/`](../bench/blackbox/README.md): capture, decode and plot Betaflight blackbox logs over the USB VCP.
  **Read `results/NOTES.md` first.** On this F4 the VCP re-initialises USB on every arm and disarm and macOS leaves the
  port silent; repeated host USB resets hung the FC. While blackbox-on-VCP is enabled, MSP and the app lose
  the FC after each arm. Revert with `config/revert_serial_vcp.txt` (steps in `NOTES.md`, "MORNING STEP").
