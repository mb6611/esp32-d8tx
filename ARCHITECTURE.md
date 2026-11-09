# Architecture

d8tx turns a browser tab and an ESP32 DevKit V1 into a FrSky D8 radio. This is the map; the measurements are in the [writeup](docs/devkitv1/writeup/tx.md), the wire format in [protocol/PROTOCOL.md](protocol/PROTOCOL.md).

## Bird's-eye view

Three programs, no server:

- **UI** (React, `packages/ui`): sticks, 3D drone, pairing, settings. It only sends intents and renders state.
- **Worker** (`packages/core/src/worker`): owns the serial ports, the link to the ESP32, the flight-controller poller and the telemetry demodulator.
- **ESP32 firmware** (`firmware/`): receives UART commands, makes the D8 packets on air, captures the drone's telemetry reply.

```
UI --intents--> Worker --UART (protocol/PROTOCOL.md)--> ESP32 --2.4 GHz D8--> drone (CC2500)
UI <--state---- Worker <--capture, int8--------------- ESP32 <--telemetry reply-- drone
                Worker --MSP over USB--> flight controller (attitude, arming state)
```

## Data flow

1. The UI posts stick values and settings to the worker (`ToWorker` in `packages/core/src/worker/types.ts`); the worker posts state back (`FromWorker`, 50 Hz).
2. The worker's `D8Link` writes `S` stick updates to the ESP32 at the slot rate (111 Hz, one per ~9 ms D8 slot, absolute deadlines).
3. The firmware keys one packet per slot, retuning the oscillator for each hop of the 47-channel table.
4. Every 12th slot is a telemetry trigger. The drone answers; the ESP32 captures the reply as 4-bit I/Q samples (bits=4) and streams them out between packets.
5. The worker decodes each capture with the C demodulator compiled to WASM (`demod/`), acks the telemetry id, and publishes a `radio` state (powered, link, catch rate, RSSI, battery, hub fields).
6. In parallel the worker polls the flight controller over MSP on its own USB port.

The firmware's per-slot loop and the telemetry trigger branch are drawn in [docs/diagrams/slot-detail.svg](docs/diagrams/slot-detail.svg); bind and the drone USB (MSP) path in [docs/diagrams/bind.svg](docs/diagrams/bind.svg).

## Code map

| Path | What lives there |
|---|---|
| `firmware/main/` | `d8tone.c` (commands, link loop, NVS identity), `packet.c` (D8 packet build), `tlm_cap.c` (telemetry capture), `cmd_parse.c` |
| `firmware/tools/` | version stamping and the bundler that copies images into the web app |
| `packages/core/src/` | `link.ts` (D8Link), `protocol.ts`, `telemetry.ts`, `hub.ts`, `msp.ts`/`fc.ts` (Betaflight MSP), `worker/host.ts` (the worker) and `worker/demod.ts` |
| `packages/serial/src/` | `web.ts` (Web Serial), `node.ts` (Node, for the desktop app and tests), `mock.ts` |
| `packages/ui/src/` | `App.tsx`, `PairingPanel.tsx`, `Quad3D.tsx`, `useController.ts`, `flash/` (in-browser esptool flashing) |
| `apps/web/` | Vite shell, the `worker.ts` entry, bundled firmware images in `public/firmware/` |
| `apps/desktop/` | Electron shell around the web build |
| `demod/` | telemetry demodulator: native, WASM and ESP32 builds |
| `protocol/` | the spec, golden vectors and I/Q captures shared by every implementation's tests |
| `python/` | reference library and vector generator |
| `bench/` | bench runner, decoders, results, receiver diagnostics |
| `docs/` | writeup, validation, guides, diagram sources (`docs/diagrams/`) |

## Invariants

- **The worker owns the 9 ms cadence.** Slot timing lives in the worker's `D8Link` and the firmware, never in React; the UI can stall and the link keeps going. If the UI goes silent for 2.5 s the worker disarms and centres the sticks, and every link (re)start holds the arm channel low until the UI sends a disarmed frame.
- **Ports are exclusive.** One owner per serial port (the worker); a second tab or app gets a "port in use" error and the worker retries with backoff.
- **The NVS identity is never erased by flashing.** The per-ESP transmitter id and hop table live in NVS. The bundler ships only bootloader, partition table and app; the flasher never erases all and refuses any image overlapping NVS.
- **`protocol/PROTOCOL.md` is the only spec.** Firmware, TypeScript, Python and the demodulator all test against its golden vectors; if code and spec disagree, fix one of them in the same change.
- **Bench modes stay out of release builds.** They compile only with `CONFIG_D8_BENCH=y` (see [REGULATORY.md](REGULATORY.md)).
