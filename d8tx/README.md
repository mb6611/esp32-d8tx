# d8tx

Fly a FrSky D8 receiver (Betaflight on a CC2500 board) from an ESP32 DevKit V1, from a browser. Private research code; see Section 8 of the [write-up](../docs/devkitv1/writeup/tx.md).

```
browser (React) ⇄ WebSocket/REST ⇄ FastAPI (d8tx.server) ⇄ D8Link ⇄ UART 921600 ⇄ ESP32 ⇄ 2.4 GHz
                                         └─ BetaflightMSP (USB) for readback
```

- `PROTOCOL.md`: firmware protocol v1 (`LINK`, `S`, `STOP`, `FOFS`, `ARMOK`, `INFO`, `STAT`; replies `OK`/`ERR`, events `EV`).
- `python/d8tx`: `D8Link` (slot-rate sender, arm gate), `BetaflightMSP`, FastAPI `server`.
- `app`: Sticks controller (React/Vite/Tailwind).

## Run

```sh
cd d8tx/python
python3 -m venv .venv && .venv/bin/pip install -e '.[server,dev]'
.venv/bin/pytest                                   # no hardware needed
.venv/bin/python -m d8tx.server --esp-port /dev/cu.usbserial-0001 [--fc-port <betaflight usb>]   # serves on 127.0.0.1:8000

cd ../app && npm install && npm run build          # or `npm run dev`
```

After `npm run build` the backend serves the page itself at http://127.0.0.1:8000. Press Start link. `?mock=1` runs the UI against a simulated backend (no hardware).

## Keys

Mode 2. **W/S** throttle (non-centering, starts at 0%), **A/D** yaw, **arrows** pitch/roll (eased), mouse drag on the sticks, **hold R** (1 s) arm, **X** disarm. Use one browser tab only.

## Safety

Channel 7 (ARM) is gated in the UI, in the library (`allow_arm`, default off) and in the firmware (`ARMOK`, cleared after each `LINK`). The backend stops after 250 ms of browser silence; the firmware ends the link after its timeout; Betaflight disarms 1.25 s after packets stop. Props off for testing.

## Betaflight gotchas

- Arms only with throttle at minimum when the arm switch rises; a refused arm with the switch left high blocks re-arming (`ARM_SWITCH`) until it goes low. The UI and library hold minimum throttle for 0.5 s after the arm edge.
- `RX_FAILSAFE` lasts about 2.5 s after the link appears.
- Runaway-takeoff protection disarms within seconds with props off; set the arm switch low to clear.

## Scripted hop

`python/examples/up_forward_land.py --dry-run` prints the open-loop timeline; the backend must not be running when you fly it. Hover throttle is unknown (above 1550 µs on the bench quad), keep the forward tilt small, and log blackbox to tune.

## Radio telemetry

The ESP32 also listens for the drone's D8 telemetry replies; results and numbers are in Section 9 of the
[write-up](../docs/devkitv1/writeup/tx.md).

**Turning it on.** `POST /api/link/start` has `telemetry=true` by default (`{"telemetry": false}` turns it off). It sends
the `TLM` recipe (a trigger every 48 slots, about 2.3 replies/s; `protocol.TLM_RECIPE`) and, unless you pass `fofs_hz`,
`FOFS -75000` (`protocol.DEFAULT_FOFS_HZ`). -75 kHz centres our carrier on the drone's receiver: 97.8-100% of triggers
answered, against 82% at -50 kHz. In Python: `D8Link.start(..., telemetry=True, fofs_hz=None)` and `D8Link.telemetry()`.
The drone needs `feature TELEMETRY` on for any hub data (A1/RSSI come regardless).

**Status fields.** `/api/status` and every WebSocket telemetry message carry a top-level `radio` object:

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

If the ESP object has no `telemetry()` or it raises, `radio` holds the same keys with defaults. Field encodings are in
`PROTOCOL.md` ("Telemetry in the library", "Patched Betaflight hub fields").

**UI.** The "Drone (radio)" cell shows powered / link / battery / armed. Without USB/MSP readback the arm indicator says
ARMED only when `radio.armed` is true, otherwise ARM SENT. With MSP connected, Betaflight readback decides as before.
Radio arm state lags MSP by about 0.4-1 s (replies come every 432 ms). Try it without hardware: `?mock=1&autostart`
(add `&batt=absent`, `&radio=off`, `&fc=off`).

**Bench notes.**
- Opening the ESP32 port reboots it. Wait about 3 s after starting the backend before Start link, or it can answer
  409 `no reply to 'FOFS -75000'`. If the ESP32 is left streaming after a crash, reset it (EN/RTS) and wait about 4 s.
- Keep the Mac awake (`caffeinate -dimsu`) for long runs; idle sleep freezes the WebSocket.
- Stock Betaflight 4.2 sends ACC truncated to whole g (a level drone reads 0 or 1000 milli-g) and no arm state.

## Patched Betaflight and blackbox

- [`bench/betaflight-patch/`](../bench/betaflight-patch/README.md): Betaflight 4.2.11 for the MATEKF411RX with true
  milli-g ACC, STATUS/arming flags, gyro and attitude in the hub (IDs in `PROTOCOL.md`), plus the ICM20689 gyro driver this
  Tinyhawk needs. `./build.sh`, flash with CLI `bl` + `dfu-util`, roll back with `recovery/betaflight_4.2.11_MATEKF411RX.bin`.
  Flashing wipes the config: replay it per `bench/d8-tx/results/bf_link/RESTORE.md` (tx id 66,178, hop table, offset
  -32, `feature TELEMETRY`, LEDs off). Bench evidence: `bench/d8-tx/results/betaflight-patch/NOTES.md`.
- [`bench/blackbox/`](../bench/blackbox/README.md): capture, decode and plot Betaflight blackbox logs over the USB VCP.
  **Read `results/NOTES.md` first.** On this F4 the VCP re-initialises USB on every arm and disarm and macOS leaves the
  port silent; repeated host USB resets hung the FC. While blackbox-on-VCP is enabled, MSP and `d8tx.server` lose
  the FC after each arm. Revert with `config/revert_serial_vcp.txt` (steps in `NOTES.md`, "MORNING STEP").
