# D8TX web + desktop: hardware end-to-end validation (U7)

Plan: `.ru/plans/d8tx-web-desktop.plan.md` U7. Spec: `.ru/specs/d8tx-web-desktop.spec.md`.
Date: 2026-11-09. Private repo; nothing published.

## Setup
- App: real Electron app (`apps/desktop`, `app://d8tx/`, web build from `apps/web/dist`), test mode `D8TX_ESP_PORT=/dev/cu.usbserial-0001`, `D8TX_FC_PORT=/dev/cu.usbmodem0x80000001`.
- Harness: `apps/desktop/e2e/run.mjs` (Playwright `_electron`), `apps/desktop/e2e/tap.mjs`. Raw results: `apps/desktop/e2e/results/*.json` (uncommitted). Final runs: `soak-2026-11-09T18-22-51-299Z.json` (U7.1), `arm-2026-11-09T18-35-15-559Z.json` (U7.2); `soak-2026-11-09T18-21-31-747Z.json` is the 1-min trial.
  - The harness clicks the UI buttons (Connect DevKit, Connect drone, Settings, Start link, Stop link) and uses the keyboard arm gate (`R` held 1.2 s, `W` throttle, `X` disarm).
  - `tap.mjs` runs inside the app's worker before any port opens. It wraps `navigator.serial.getPorts()` and only *observes*: DevKit RX text lines (`EV`/`OK`/`ERR`), DevKit TX lines (S-frame write times → host-side S gaps), FC MSP v1 replies (per-command counts, MSP_MOTOR payloads), and the worker's state messages. It keeps the real `SerialPort` so U7.2 can close it.
- Bench: firmware `d8tx-v1` proto=1, LINK power 127, FOFS −75 kHz, timeout 300 ms, telemetry on (TLM recipe every=12 stream=1 bits=4). Drone MATEKF411RX on USB, props off, **no battery** (MSP_BATTERY_STATE before arming: 0 cells, 0.0 V).
- Mac kept awake with `caffeinate -dimsu` for the session.


Run: `cd apps/desktop && E2E_NO_PREFILTER=1 node e2e/run.mjs soak 10` then `E2E_NO_PREFILTER=1 node e2e/run.mjs arm`.

## Summary

| Requirement | Measured | Result |
|---|---|---|
| US1.1 / US2.1 connect | Connect DevKit → INFO `proto=1 fw=d8tx-v1` in 339–383 ms (one run 856 ms); Connect drone → FC connected ~200 ms later | pass |
| Port role selection (main.cjs fix) | DevKit then drone both connect with the harness workaround off (`E2E_NO_PREFILTER=1`) | pass |
| SC3 / R2: 10 min background, no S gap > 50 ms | host S writes: 64,409 frames, max gap 24.4 ms, 0 gaps > 50 ms; firmware keyed slots 61,921 vs 61,716 expected (ratio 1.003); EV link every ≤1.07 s, ≥101 slots each; link_end why=stop | pass |
| Link-lost count (10 min) | 0 | pass |
| US3.1 telemetry | 509 packets decoded/min (5,100 of 5,312 triggers, 96.0 %); radio age ≤1 s in 100 % of 1 Hz samples | pass |
| US4.1 FC attitude ≥10 Hz | 10.73 Hz MSP_ATTITUDE replies (10.7 every minute) | pass |
| US1.2 / R4 arm via the gate | `R` held 1.2 s → Betaflight armed (MSP_STATUS); STAT `armok=1`; S ch7 = 2000 | pass |
| US1.2 throttle → motors | throttle 1150 reached in 1.0 s, held 3 s: S `1150 …`, MSP_RC throttle 1150, MSP_MOTOR e.g. `[1065,1649,1413,2000]` (idle 1000 when disarmed) | pass |
| Disarm | `X` → S ch7 1000, Betaflight disarmed (seen ≤309 ms, status poll granularity), motors 1000 | pass |
| R3 / E1 port close while armed: UI link lost + disarmed ≤500 ms | UI banner "Link lost: DevKit port closed" at 12 ms, Motors "DISARMED" at 16 ms; worker `link=false lost_reason=port_closed` at ≤54 ms | pass |

## U7.1 — 10 min, window minimized, arm disallowed
- Start: the link was started with `allow_arm: false` (start intent dispatched into the worker by the harness, so the firmware never got `ARMOK`); window minimized 3 s later through `BrowserWindow.minimize()` and still minimized at the end (`isMinimized()` true). Stop: restored, UI **Stop link** button.
- Note: with `backgroundThrottling: false` the minimized Electron page still reports `document.visibilityState = 'visible'`, so the UI's hidden-tab disarm never fires in the desktop app (irrelevant here, arming was off).
- Firmware `EV link_end why=stop slots=61921 late_max_us=1020 retune_max_us=450 gap_max_us=1086 gap50=30335 gap100=14308 gap200=1688 trig=5346 retry=203`.
- Slots: link 604,983 ms from the `LINK` write to `link_end` = 67,265 slot times; minus listen slots (trig + retry = 5,549, one unkeyed slot each) = 61,716 expected keyed slots; firmware counted 61,921 (1.003, within start/stop timing error). No keyed slot missing. (`slots` counts keyed slots only, so raw slots/elapsed = 92 % by definition.)
- The firmware does not report S-frame arrival gaps directly; a gap over the 300 ms timeout would have ended the link with `why=timeout`, and it did not. Host side (tap on the worker's writer): max gap between S writes 24.4 ms, none over 50 ms. Per minute: 106.3–106.7 S frames/s, max gap unchanged.
- Telemetry per minute: 506–512 decoded, 525–536 triggers. Catch rate 96 % at FOFS −75 kHz (better than the 78–85 % quoted for earlier runs).
- `gap50/100/200` in link_end are air-slot timing jitter in µs (packet start vs the 8994 µs grid), not S-frame gaps.

## U7.2 — arm, throttle, disarm, port close (window visible)
- Battery absence checked twice over MSP_BATTERY_STATE right before the runs: 0 cells, 0.0 V. Props off.
- Settings → Max throttle 15 %, then **Start link** (UI path, allow_arm). Pre-arm: Betaflight arming_disable empty, STAT `OK keyed=0 link=1 fofs=-75000 armok=1`. (`keyed=0` in STAT: sampled between packets.)
- Arm 1: `R` 1.2 s → Betaflight armed; the worker sent throttle 1000 during the 0.5 s arm-edge hold. `W` held → S throttle 1150 (cap) in 1.0 s, Betaflight MSP_RC (AETR order) throttle 1150, ch7 2000. Motors over the 3 s hold: m1 1064–1065, m2 1500–1737, m3 1229–1499, m4 1668–2000. The spread is the PID integrator on a stationary, prop-less quad, not the throttle. `X` → S `1000 … 1000 …`, MSP_RC ch7 1000, motors `[1000,1000,1000,1000]`.
- STAT has no stick fields (protocol v1 is fixed: `keyed link fofs armok`). Stick values were confirmed from the S lines the app wrote and from MSP_RC on the drone.
- Arm 2 then close: armed at throttle 1000, then the DevKit port was "unplugged" at stream level. Pending and later reads and writes in the worker reject with `NetworkError: The device has been lost.`, as Chrome does on unplug.
  - Worker: `link_lost port_closed` 11 ms after the close; UI banner "Link lost: DevKit port closed" at 12 ms, Motors "DISARMED" at 16 ms; arm switch locked.
  - Drone: S frames stop, so the firmware's 300 ms link timeout stops the radio. Betaflight then reported failsafe at ~1.05 s, motors 1000 at ~1.31 s, and not armed by ~1.57 s (MSP status is polled every ~0.25 s). That is Betaflight's own failsafe timing after the radio stops.
  - `port.forget()` was tried first and did nothing while the app held the streams (the link kept running), hence the stream-level simulation. A physical unplug was not done (needs the owner).

## Not covered here
- SC1: the owner's real flight from Chrome and from the desktop app.
- Web (Chrome) build background-tab run: this covers the Electron shell only.
