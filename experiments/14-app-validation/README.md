# 14: Checking the real app

By now the app drove both boards itself, with no Python backend: it sends one stick update per 8.994 ms slot to the ESP32, triggers and decodes telemetry, and polls the flight controller over MSP. I wanted to know if it held the link and the telemetry on real hardware over a long run, and if arming, disarming and losing the ESP32 behaved safely. The drone was on USB, props off, no battery. The first runs used the cloned E8 identity at FOFS −75 kHz, with the fast telemetry recipe from [13](../13-fast-attitude-telemetry/README.md).

The main run was 10 minutes with arming disallowed and the app window minimized. The app sent 64,409 stick updates, 106.5 a second, and the longest gap between two was 24.4 ms, so the firmware's 300 ms silence timeout never fired. The firmware counted 61,921 transmitted slots against 61,716 expected from the elapsed time minus the listen slots, a ratio of 1.003, so no slot was missing. Telemetry decoded 5,100 replies to 5,312 triggers (96.0%), 506 to 512 a minute, and the newest reply was always under 1 s old. Attitude over MSP came at 10.73 Hz.

Next, with the throttle capped at 15%, I armed and ran the motors. Betaflight armed after the arm control was held for 1.2 s, and the drone's own RC channels read throttle 1150 µs, the cap, and arm channel 2000 while the prop-less motors spun up. Disarm took effect within 309 ms, the MSP poll interval, and the motors went back to 1000. Then, armed again, I made the ESP32's serial port fail the way an unplug does. The app showed the link lost and disarmed within 16 ms. With no more stick updates the firmware stopped transmitting after its 300 ms timeout, and Betaflight went to failsafe at about 1.05 s and disarmed at about 1.57 s, which is its own failsafe timing.

The last run was a 2-minute minimized run after the bind of [15](../15-ota-bind/README.md), with the ESP32's own transmitter ID (`3537`) and FOFS 0. The sticks held up the same way (longest gap 23.9 ms, no link loss), but only 946 of 1,292 triggers were answered, 73.2%, against 96.0% in the 10-minute run. Decoded replies per minute fell less than that, 473 and 464 against 506 to 512, because each empty capture is re-requested, which raised the trigger count to 627 and 654 a minute. I haven't found why the answer rate dropped. The identity, the frequency offset, the drone's position and that afternoon's interference all differ from the earlier run, and I didn't isolate any of them. In 15 the same bound setup had answered 94.9% earlier that day.

So the app holds the link and the telemetry for 10 minutes on real hardware, and losing the ESP32 ends in Betaflight's failsafe. This doesn't include a flight from the app or a physical unplug: the port loss was simulated.

There is no figure for this experiment; the numbers are fields in the result files in `data/e2e-results/`.

---

## Numbers

| Run | Telemetry decoded | Where |
|---|---|---|
| 1-min trial (13:21) | 519 of 538 (96.5%) | `data/e2e-results/soak-2026-11-09T18-21-31-747Z.json` |
| 10-min soak (13:22), cloned identity, FOFS −75 kHz | 5100 of 5312 (96.0%) | `data/e2e-results/soak-2026-11-09T18-22-51-299Z.json` |
| Soak after the bind (15:47), txid 3537, FOFS 0 | 946 of 1292 (73.2%) | `data/e2e-results/soak-2026-11-09T20-47-17-909Z.json` |

| 10-min soak | Value |
|---|---|
| Stick updates sent | 64,409, longest gap 24.4 ms, none over 50 ms |
| Keyed slots, firmware vs expected | 61,921 vs 61,716 (1.003) |
| Port loss to the app disarming | 16 ms (`arm-2026-11-09T18-35-15-559Z.json`) |

## Files

- `data/validation-report.md`: the full validation report (it was `docs/validation/d8tx-web-desktop.md`).
- `data/e2e-results/`: raw results per run (file names are UTC times), including a screenshot of the port-in-use message.

## How to re-run

Follow [docs/how-to/hw-check-and-e2e.md](../../docs/how-to/hw-check-and-e2e.md) (needs the ESP32 and the drone). New runs are written to `apps/desktop/e2e/results/`. There is no offline analysis: the numbers are fields in the result JSON (`decoded_total`, `triggers_total`, `host_s_max_gap_ms`).

## Ran

2026-11-09, 13:21 to 13:35 EST, then 15:45 to 15:47 EST (result file names 18:21Z to 18:35Z and 20:45Z to 20:47Z). Commits c830ed9 (13:53), 0b1deb1 (16:01).

**Overlap:** this experiment straddles [15](../15-ota-bind/README.md): the first runs came before the bind, the last soak after it. It is placed by its start time. The lab log tells it the other way round (bind in section 10, validation in section 13).

Previous: [13-fast-attitude-telemetry](../13-fast-attitude-telemetry/README.md) · Next: [15-ota-bind](../15-ota-bind/README.md) · [All experiments](../README.md)
