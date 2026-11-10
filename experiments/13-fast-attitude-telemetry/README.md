# 13: Fast attitude over the radio

I wanted the app to show the drone's attitude live, as a 3D model that tilts when the drone tilts. After [10](../10-hub-patch/README.md) the radio carried attitude and gyro, but slowly. A reply came once every 48 slots (432 ms), each reply carries at most about 10 hub bytes, and attitude was one field among many in the hub stream, so gyro refreshed about every 3.5 s and attitude about every 7 s. Two things limit that: how often the ESP32 asks for a reply, and how much of each reply goes to attitude.

For the second, I changed the patch rather than the hub. Patch 0003 (`tools/betaflight-patch/patches/0003-frsky-d-fast-block.patch`) makes Betaflight's D8 reply carry a fixed 10-byte block in place of hub bytes: roll, pitch and yaw in 0.1 degree, gyro x, y and z, and a sequence number, marked by the hub-count byte 0x8A. Two of every three replies carry this block, and every third carries the normal hub bytes, so acceleration, STATUS and the stock fields keep coming. The same patch includes the guard against the hub-timer stall found in [11](../11-telemetry-stack/README.md). An offline check compiles the block encoder and compares it with the host decoder over 2005 cases, with no mismatches.

For the first, the ESP32 has to trigger more often, and each capture then has to be smaller, because it is shipped over the UART in the gaps between packets. I measured the link in 60 s runs with the drone on USB, no battery, changing the telemetry recipe each time. The baseline, a trigger every 48 slots with an int8 capture decimated by 32 (9000 bytes), gave 139 replies, 2.3 a second, and 0.31 s from request to decoded reply. Before going smaller I checked offline that a coarser capture still decodes: of 496 saved replies, decimating by 64 instead of 32 decoded 496, and also cutting the first 1 ms and requantizing to 4 bits decoded 495. Decimating by 128 lost about 30% (345 of 496).

So on the bench I went to decimation 64. With int8 and a trigger every 16 slots (4000 bytes per capture) the link got 5.8 decoded replies a second at 0.15 s latency. With int4 and a trigger every 12 slots (2000 bytes) it got 8.5 a second at 0.10 s, and the host decode took about 0.7 ms instead of 3 ms. Triggering every 8 or every 6 slots gave the same 8.5 a second. That fits how the stream mode works: the next trigger waits until the previous capture has gone out and its telemetry ID has been acknowledged, so about one reply every 13 slots is the ceiling of this path. In all of these runs the drone stayed out of failsafe after Betaflight's start-up period, and a stick value read back over MSP lagged 0.02 s at the median, the same as the baseline. So the faster polling didn't cost the control link anything I could see. I made every 12 slots, decimation 64, int4 the library default.

Then I flashed build `c3f351e4` with patch 0003 and ran the link end to end for 60 s. It got 511 replies (8.5 a second): 340 with the attitude block, 5.7 a second, and 171 with hub bytes. The time between attitude updates was 0.12 s at the median and 0.23 s at the 95th percentile, since every third reply is a hub reply. Acceleration still arrived about every 1.4 s. The radio's attitude agreed with Betaflight's MSP_ATTITUDE read over USB at the same time: roll −1.8°, pitch 1.2° against −18 and 12 in MSP's tenths of a degree.

![The telemetry path: the drone's reply through the ESP32's receive chain, decimation and int4 packing in the firmware, over the UART to the Web Worker, CRC-32 check, the WASM demodulator, and the reply fields to the React UI, with a TID ack back to the ESP32](../../docs/diagrams/overview-telemetry.svg)

*Figure: the telemetry path back, about 8.5 replies a second, decoded in the browser. Source: [`docs/diagrams/overview-telemetry.excalidraw`](../../docs/diagrams/overview-telemetry.excalidraw).*

So attitude now arrives about 5.7 times a second, about 0.1 s after it is requested, which is fast enough for the app's live 3D view. That is what the app's 3D panel uses. It was all on the bench with the drone sitting still, so it doesn't show how the block behaves in motion, and the hub-stall guard in the same patch was not tested against the 36-minute idle condition that triggers the stall.

The numbers are in the per-run result files in `data/`.

---

## Numbers

| What | Before (every 48 slots, dec 32, int8) | After (every 12 slots, dec 64, int4) | Where |
|---|---|---|---|
| Replies per second | 2.3 | 8.5 | `data/baseline.txt`, `data/c2_d64_i4_every12.txt` |
| Request to decoded reply, p50 | 0.31 s | 0.10 s | same |
| Capture size | 9000 bytes | 2000 bytes | same |
| Attitude/gyro updates | about 0.14 / 0.29 Hz (hub, from 10) | 5.7 Hz, interval p50 0.12 s, p95 0.23 s | `data/e2e/run60.txt` |
| Every 8 or 6 slots | | 8.5 replies per second, no gain | `data/c3_*.txt`, `data/c4_*.txt` |

## Files

- `data/baseline.*`, `c1_*` to `c4_*`: one result per capture setting. `data/e2e/`: the end-to-end runs (`run1` 30 s, `run60` 60 s) and the flash log of build c3f351e4.
- `scripts/run_cadence.py`, `runall.sh`, `e2e/run_e2e.py`: hardware. `scripts/offline_dec.py`: re-decodes saved captures at coarser settings.

## How to re-run

Run from the repo root:

```
python3 experiments/13-fast-attitude-telemetry/scripts/offline_dec.py    # needs numpy; reads saved captures from 09 and 10
python3 tools/betaflight-patch/check/fast_block_check.py                 # fast-block encoder check, needs a C compiler
```

The other scripts are hardware scripts (ESP32 and drone).

## Ran

2026-11-08, about 13:34 to 14:15 EST. The data has no timestamps; the time is bounded by commit db7196a (13:34) and commit 2b50eb4 (14:15). Commits 0a8ad85 (13:49, attitude over USB), 2b50eb4 (14:15), adc01bc (14:16).

Previous: [12-blackbox-usb](../12-blackbox-usb/README.md) · Next: [14-app-validation](../14-app-validation/README.md) · [All experiments](../README.md)
