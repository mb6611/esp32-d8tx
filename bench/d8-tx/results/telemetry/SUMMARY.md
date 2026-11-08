# D8 telemetry reply capture: battery-on trial 2026-11-07 21:10

Command (from bench/d8-tx/host): `tlm_listen.py link --seconds 20 --every 48 --power 127 --fofs -50000`
Run: 20261107-211006-link (arm channel low; drone on battery, stock Betaflight, no config change).

Result: WORKS. 26 of 46 trigger slots captured a CRC-valid 18-byte 0x11 frame from txid 66,178.
The reply came on the NEXT hop channel (Betaflight calls nextChannel(1) before replying).
- Unkey to capture start: 207-368 us. Capture length 10.3 ms at 500 kS/s. lost=0 bad=0.
- Reply start: 1.34-1.51 ms after the trigger packet (Betaflight nominal 1380 us). CFO about -30 to -33 kHz.
- A1=75, A2=26 (raw), RSSI byte 71-76 (decoder's dBm label), telemetry id echoed correctly.
- Hub byte count = 0 in every frame. FrSky hub data has not been seen yet (open question).
- Misses: slots 432, 672-720, and 816-1392 (one long gap) plus scattered ones; cause not investigated.
- LINK timing during the run: late_max 129 us, retune_max 374 us.
