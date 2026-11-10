# 09: Hearing the drone talk back

By [08](../08-first-flight-cloned-e8/README.md) the ESP32 could fly stock Betaflight, but only in one direction. A D8 receiver also talks back: Betaflight's D8 code (`cc2500_frsky_d.c`) answers any packet whose byte 3 satisfies `byte3 % 4 == 2`. It steps to the next hop channel, waits until 1380 µs after the trigger packet, and transmits an 18-byte telemetry frame: the bind ID, A1 (battery voltage), A2, an RSSI byte, a count of FrSky hub bytes, an echo of the telemetry ID from the request, and then the hub bytes themselves. I wanted to know if the ESP32 could receive that reply, so the app could show what the drone is doing.

That means the ESP32 has to stop transmitting, retune to the next channel and start listening within about a millisecond. After each trigger packet the firmware unkeyed, retuned and started an I/Q capture 207 to 368 µs later, recorded 10.3 ms at 500 kS/s, and sent the samples to the Mac, where `tools/d8-tx-host/tlm_listen.py` decoded them with the D8 decoder from the receive project. I sent one trigger every 48 slots at power 127, with FOFS (the frequency offset that the cloned E8 binding needs, from 08) at −50 kHz.

The first run with the drone on battery caught a CRC-valid reply with the drone's ID in 26 of 46 trigger slots. The replies started 1.34 to 1.51 ms after the trigger packet, close to Betaflight's nominal 1380 µs, and carried A1, A2, an RSSI byte of 71 to 76 and the correct telemetry ID. So the turnaround on the hacked transmit path works. But half the replies were missing, the misses came in long runs, and the hub byte count was 0 in every frame.

The long runs of misses happened because the ESP32 stopped transmitting after every trigger. After each one it captured the slot where the reply should be and sent that capture to the host as 20 KB of int16 samples over the UART, and it did nothing else for the roughly 0.22 s that took, about 24 slots with no packets. I saw this by repeating the run with the drone on USB power and logging Betaflight's status over MSP at about 7 Hz: Betaflight saw the packets stop, went into RX failsafe (318 of 400 MSP rows in a 60 s run), and then took seconds to find the hop phase again. That run caught 56 of 139 (40%). I changed the firmware to capture int8, about 9 KB, and stream it out in the roughly 1.9 ms gaps between packets, so the link never stops. The same 60 s run then caught 121 of 139 (87%), with failsafe only in Betaflight's first 2 s after the link starts. I also changed how the telemetry ID advances: the host now sends the next ID only after a reply echoed the last one, otherwise it repeats the same ID, which is Betaflight's own rule.

The empty hub came from the drone's configuration. MSP showed `FEATURE_TELEMETRY` off, and Betaflight only adds hub data when that feature is on. With the owner's approval I turned it on (`feature TELEMETRY`, the only line that changed in `diff all` (Betaflight's list of every setting that differs from the defaults)). The next run caught 119 of 139 and carried 836 hub bytes in 196 hub frames. Acceleration read 0 milli-g on all three axes, including Z, while MSP read 0.996 g on Z at the same time. That is how stock Betaflight 4.2 encodes it: it casts the acceleration to a whole number of g before multiplying by 1000, so a level drone reads 0, never 996. That coarse encoding is what led to patching Betaflight in [10](../10-hub-patch/README.md).

That left the remaining 13 to 18% of misses. I went through the saved captures from three runs offline (`data/MISSES.md`). Because every field of the reply was known except the RSSI byte, I could correlate each capture against the roughly 190 known bits. Real replies scored 0.75 to 0.91 and sat 29 to 39 dB above the noise floor. In 118 of the 126 misses the score was 0.10 or lower and there was no burst of energy at all. So no reply was hiding under the noise: the drone had not transmitted where I listened. A better decoder would have recovered at most 1 of 417 captures. Timing didn't explain the misses either: the slot start of a missed trigger was no later than that of a caught one.

The answer was frequency. The replies sat 30 to 42 kHz below my receive frequency, which meant my packets were landing about 34 kHz above where the drone's receiver was tuned. The CC2500's frequency compensation with this drone's setting reaches about ±34 kHz, so the drone was losing some of my trigger packets at the edge of its range. I swept FOFS over twelve 60 s runs of 139 triggers each. At −50 kHz the runs caught 80.6 to 85.6%. From −65 to −80 kHz they caught 95.7 to 99.3%, with the plateau centred near −75 kHz, and further out, at −85 and −95 kHz, it fell back to 94.2 and 93.5%. Late in the evening a plain run at −75 kHz caught 136 of 139 (97.8%), and a control at −50 kHz right after it caught 114 (82.0%).

As a fallback I added a re-trigger to the firmware. After each capture it checks for reply energy: over 586 captures from the evening, every reply filled 11 of 11 half-millisecond blocks and every empty capture at most 8. When fewer than 9 are filled, it sends the same telemetry ID again in the next free slot. At −50 kHz with one retry, all 138 requests were answered, 8 of them on the second try. At −75 kHz with one retry, 139 of 139 were answered on the first try.

So the ESP32 can hear Betaflight's telemetry, and with the offset centred it gets 97.8 to 100% of replies. What I didn't know then is that −75 kHz only suits the cloned E8 binding. Once the drone was bound to the ESP32 itself, the drone's receiver corrected its own offset and FOFS 0 became the right setting ([15](../15-ota-bind/README.md)). None of this was in flight, and only the first run was on battery.

There is no figure for this experiment; the per-run numbers are in the tables of `data/SUMMARY.md`.

---

## Numbers

| What | Value | Where |
|---|---|---|
| First run, on battery, FOFS −50 kHz | 26 of 46 replies | `data/SUMMARY.md`, run `20261107-211006-link` |
| Old blocking capture (60 s) | 56 of 139 (40%) | run `20261107-212358-link` |
| Streamed int8 capture (60 s) | 121 of 139 (87%) | run `20261107-212508-link` |
| With `feature TELEMETRY` on | 119 of 139, 836 hub bytes | run `20261107-213222-link` |
| Misses with no reply energy | 118 of 126 | `data/MISSES.md` |
| FOFS −65 to −80 kHz | 95.7 to 99.3% | `data/SUMMARY.md`, runs `20261107-221012`, `221227`, `221330`, `221432`, `221535` |
| FOFS −75 kHz, plain run / with retry | 136 of 139 (97.8%) / 139 of 139 | runs `20261108-002322`, `20261108-002423` |

## Files

- `data/<date>-<time>-tcap|link/`: one folder per run (captures, events, results). `SUMMARY.md` walks through all of them; `MISSES.md` looks at the missed replies.
- `data/bf-diff-before.txt`, `bf-diff-after.txt`: the drone's config around the `feature TELEMETRY` change.
- `data/leds_off/`: a drone config change for the night runs (LEDs off, 00:34; reverted 2026-11-08 13:34).
- No scripts of its own: the tools are in [tools/d8-tx-host](../../tools/d8-tx-host/).

## How to re-run

From the repo root, offline (`tlm_misses.py` needs numpy):

```
python3 tools/d8-tx-host/tlm_misses.py experiments/09-telemetry/data/20261107-211006-link
python3 tools/d8-tx-host/tlm_why.py experiments/09-telemetry/data/20261108-002208-link
```

Live runs (`tlm_listen.py`) need the ESP32 and the drone; new runs are written to `tools/d8-tx-host/runs/`.

## Ran

2026-11-07 20:40 to 2026-11-08 00:26 EST (run folder names, and the headers in `SUMMARY.md`). Commits 781f20c (11-07 21:11) to 673490f (11-08 00:34).

**Not preserved:** `msp.log`, which `SUMMARY.md` says was written in each run folder, was never committed and is not on disk.

Previous: [08-first-flight-cloned-e8](../08-first-flight-cloned-e8/README.md) · Next: [10-hub-patch](../10-hub-patch/README.md) · [All experiments](../README.md)
