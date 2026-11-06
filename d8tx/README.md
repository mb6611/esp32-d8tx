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
