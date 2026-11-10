# 15: Binding over the air

From [08](../08-first-flight-cloned-e8/README.md) to [14](../14-app-validation/README.md) the drone was never bound to the ESP32. The ESP32 sent my E8's transmitter ID (66,178, or 0x42B2) and hop table, which the drone had stored when it was bound to the real E8. That works for one drone as long as nobody turns the E8 on, and it means every ESP32 built from this repository would pretend to be the same E8. I wanted the ESP32 to have an identity of its own and bind the drone to it, the way a FrSky transmitter does.

The identity is four bytes. On its first boot the firmware draws a random two-byte transmitter ID and a hop-table start and step, and stores them in flash. The hop table is entry 0 = 0, the bind channel, then entry i = (start + step·i) mod 256 for i = 1 to 46. This ESP32 drew `txid=6ff3 start=205 step=254`, and still had it after a reset.

Binding is a conversation the receiver mostly runs by itself. A D8 bind packet carries the transmitter ID and five hop-table entries starting at an index. The firmware's `BIND` command sends one per 8.994 ms slot on channel 0, cycling the index 0, 5, …, 45, so the whole table goes out about every 90 ms. Betaflight 4.2 in bind mode first listens on channel 0 and sweeps the CC2500's frequency offset from −126 to +126 in steps of 5, one step every 50 ms, and keeps the first offset at which a bind packet arrives with a good CRC. So the receiver tunes itself to whatever carrier the transmitter really has. Then it collects the ID and the table in order and writes them to its own flash.

On the bench, with props off, the drone on USB power and arming disallowed, I started `BIND 30` at FOFS 0 and typed `bind_rx` into the drone's Betaflight CLI. Four seconds later `get frsky_spi` showed the new identity, saved by the receiver code without a `save`: transmitter ID 111,243 (that is 0x6f, 0xf3), the hop table 0, 203, 201, …, 115, 113, and receiver offset 4 instead of −32. Those three lines were the only difference in `diff all` (Betaflight's list of every setting that differs from the defaults), and they survived a reboot. A second bind also worked: the link that followed got 90.9% of telemetry triggers answered, and the offset settled at 3.

The offset is the interesting part. It moved by +36 steps, about +57 kHz. That is the same correction the cloned binding had needed from my side: FOFS −50 to −75 kHz in [08](../08-first-flight-cloned-e8/README.md) and [09](../09-telemetry/README.md), because the drone's receiver had been tuned to the E8's carrier, not the ESP32's. Now the receiver had made it itself, so FOFS 0 should be right. I checked with four 60 s links, telemetry on, sticks fixed and read back over MSP:

| Power | FOFS | Triggers | Replies | Answered | Drone RSSI |
|---|---|---|---|---|---|
| 127 | 0 | 534 | 507 | 94.9% | −67.6 dBm |
| 127 | −75 kHz | 619 | 451 | 72.9% | −70.2 dBm |
| 30 | 0 | 662 | 431 | 65.1% | −81.8 dBm |
| 30 | −75 kHz | 702 | 371 | 52.8% | −86.2 dBm |

The −75 kHz offset that the clone needed now costs packets at both powers. Power 30 is near the receiver's sensitivity edge on this bench, so the comparison that matters is at 127. In all four runs the sticks read back exactly (235 to 239 MSP samples each), and failsafe never came back after the receiver locked, 2.5 to 3.2 s after the link started. So the default offset went back to 0. The receiver locks to whatever carrier the bind packets are on, so the bind itself has to be sent at FOFS 0 too.

Two things came after this session. Betaflight's MSP command `MSP2_BETAFLIGHT_BIND`, the one Betaflight Configurator's "Bind receiver" button sends, puts this 4.2.11 build into bind mode over USB with no CLI and no reboot; that worked on 3 of 3 binds. And I found that the identity drawn here, step 254, packs all 47 hops into every second channel from 115 to 205, a narrow slice of the band. A real D8 table spreads over the whole band so that one interferer costs a few hops, not most of them. Generated identities now follow the rules of Multiprotocol's FrSkyD transmitter code, which only 142 of the 65,536 start and step pairs pass.

So the ESP32 binds a stock Betaflight receiver to its own identity on the first try, and after binding no frequency offset is needed. This was one drone on one bench and a handful of binds. I didn't test binding at a distance, with a second drone, or with the drone's physical bind button.

![The one-click bind: the laptop sends FOFS 0 and BIND 40 to the ESP32 and MSP2_BETAFLIGHT_BIND to Betaflight; the ESP32 keys bind packets on channel 0; the CC2500 sweeps its offset, locks, takes Bind1 and Bind2, saves; then a confirm link waits for a telemetry reply with this txid](../../docs/diagrams/bind.svg)

*Figure: the one-click bind, across the laptop, the ESP32 and the drone, and the confirm link after it. The bench bind above used the CLI's `bind_rx` instead of the MSP command. Source: `docs/diagrams/bind.excalidraw`.*

---

## Numbers

| What | Value | Where |
|---|---|---|
| Time from `bind_rx` to the new identity | about 4 s | `data/SUMMARY.md`, `data/bind_run.log` |
| Receiver offset before / after | −32 / 4 (second bind 3), +36 steps | `data/diff_all_before.txt`, `data/diff_all_final.txt` |
| Telemetry at FOFS 0 / −75 kHz (power 127) | 94.9% / 72.9% | `data/SUMMARY.md`, `data/link_p127_*.log` |
| Telemetry at FOFS 0 / −75 kHz (power 30) | 65.1% / 52.8% | `data/link_p30_*.log` |
| Second bind, telemetry answered | 250 of 275 (90.9%) | `data/ts_bind.log` |

## Files

- `data/SUMMARY.md`: the original write-up. `data/*.log`: the run logs (they were git-ignored at the time and are now committed). `data/diff_all_*.txt`: the drone's config before and after. `data/p30_uart_debug/`: a low-power debug run.
- `scripts/`: `bind_run.py`, `bfcli.py`, `esp.py` (hardware).

## How to re-run

All scripts here are hardware scripts (ESP32 and drone). For the app's one-click bind, run `packages/core/scripts/bind-check.ts` as described in [docs/how-to/bind.md](../../docs/how-to/bind.md).

## Ran

2026-11-09, 14:10 to 14:22 EST (`SUMMARY.md` "(2026-11-09)", log clock 14:10:07, file times of the logs 14:10 to 14:22). Commits 04aa5ee and dccba19 (14:30); follow-ups 9080330 and 9b2aec3 (16:01).

**Overlap:** happened in the middle of [14](../14-app-validation/README.md).

Previous: [14-app-validation](../14-app-validation/README.md) · Next: none yet · [All experiments](../README.md)
