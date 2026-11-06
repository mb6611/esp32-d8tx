# Offset tune (plan bench step 1), E8 off, drone on rxdiag f39fac05
- ESP flashed app-only d8tone.bin sha 3b1f09de… verified; PING d8tone, STAT keyed=0 fofs=0.
- Source-off (ESP idle): no LOCK, no CRC-valid packet (2 E,EPART noise only).
- Receiver `rxdiag hop 2 55 8000 2403937`, ESP `FOFS -63000`, `HOP 556 127`.

| | E8 control | Run A | Run B (same FOFS) |
|---|---|---|---|
| CRC-valid FREQEST mean (raw / Hz) | -0.4998 / -793 | -0.5039 / -800 | -0.4915 / -780 |
| rate | 96.8% (2133/2204) | 91.7% (510/556) | 84.9% (472/556; 47-slot loss run at slot 509) |

Mean diff <=13 Hz, so correction rounds to 0 kHz: **chosen FOFS = -63000** (unchanged).
Mean criterion (<=5 kHz) met; rate criterion (>=95%) NOT met in either run. keyed=0 after each run, no ERR. 2 HOP runs used.
Frequency offset is not the cause of the loss; not investigated (out of scope).
