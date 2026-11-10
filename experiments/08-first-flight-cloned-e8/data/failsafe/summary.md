# Failsafe on host death (props off, battery in, stock Betaflight 4.2.11)
ESP32 fw 038979fb, FOFS -63000, `ARMOK` then `HOP 0 127 300`; host sender (stick_sender.run) with the final `U` suppressed to simulate a crashed Mac. MSP polled at ~10 Hz over USB.

| t (s, from HOP) | event |
|---|---|
| 0.00 | link starting; Betaflight RX_FAILSAFE |
| 2.66 | RX_FAILSAFE clears (link accepted) |
| 3.53 | ARM high -> **armed** (mode_flags 3) |
| 5.51 | host stops sending (no `U`) |
| ~5.81 | ESP32 `why=timeout` after 646 slots, unkeyed |
| 6.27 | Betaflight RX_FAILSAFE, sticks to failsafe values (throttle 885) |
| 6.75 | **disarmed**, FAILSAFE mode, arming blocked (FAILSAFE, RX_FAILSAFE, ARM_SWITCH) |

Host death to disarm: ~1.25 s. ESP STAT keyed=0 afterwards. Raw: failsafe_msp.txt, failsafe_esp.txt, failsafe_sender.csv.
An earlier attempt with an ad-hoc send loop ended after 27 slots with `ERR cmd`, `why=err` (ESP unkeyed); not used.
