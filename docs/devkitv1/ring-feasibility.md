<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Ring-capture feasibility on the ESP32 DevKit V1 (plan U4)

Measured on 2026-11-05, on the owner's DevKit V1 (ESP32-D0WD-V3, 240 MHz, `/dev/cu.usbserial-0001`,
921600 baud), receive only, tuned to 2412 MHz, hardware AGC. Probe firmware: the devkitv1 profile
built with `-DRING_PROBE=ON`. All probe code is compiled only into that build.

## Verdict: **B** (counted gaps), close to A

- **The capture writer runs as a ring.** With control bit 17 set it loops over its count and never
  stops: `RINGPROBE` shows 4 / 2 / 0 pointer wraps in 1 ms at 80 / 40 / 16 MS/s, matching the rate.
- **The CPU can't read a bank the RF owns.** While `MAC_DUMP_MODE` gives a 32 KiB bank to the RF,
  CPU reads of that bank return the constant `0xa55aa55a`, not memory. So the stock `RINGPROBE`
  `live=8` is an artefact.
- **The 64 KiB window splits into two 32 KiB banks.** `MAC_DUMP_MODE` 2 gives the RF the lower bank,
  1 gives it the upper bank, 3 gives it both and 0 gives it none. In modes 1 and 2 the writer's offsets
  0..8191 land in that mode's bank, and offsets 8192 and up are dropped. They don't alias.
- **Ping-pong works with the ring left running.** The writer runs an 8192-word ring, and the CPU
  toggles the mode 2↔1 when it sees the pointer wrap (`RINGPP8`). Every bank came back fully written
  (`sparse_missing=0`). The run length matched exactly `halves × 8192 / fs`, so the CPU never fell a
  lap behind (`overrun=0`). The only loss is at the seam. The switch lands *k* samples after the
  wrap, so the first *k* samples of the new lap go to the start of the old bank and overwrite the old
  lap's first *k* samples. *k* is exact and known, because the new bank's first *k* words keep the
  sentinel.

| rate | seam loss k per 8192-sample half: mean / max | lost fraction | duty |
|------|------------------------------------------------|---------------|------|
| 16 MS/s | 0.21 / 1 (3 in a repeat run) | 0.0026 % | 99.997 % |
| 40 MS/s | 1.64 / 5 | 0.020 % | 99.98 % |
| 80 MS/s | 3.50 / 7 | 0.043 % | 99.96 % |

- The fallback is a re-armed one-shot (`RINGREARM`, CPU re-arms after `done`). Its steady-state gap
  per capture is 147 / 156 / 159 CPU cycles, which is 9.8 / 26 / 53 samples at 16 / 40 / 80 MS/s.
  The first capture of a run is about 1900 cycles longer. With 16380-sample captures the duty is
  99.94 / 99.84 / 99.68 %. A one-shot also needs mode 3, or the same bank toggle, because the CPU
  can't read during the capture. Ping-pong is about 10–50× better.
- **The DSP fits** (`DSPPROBE`, app CPU started bare metal, IDF still unicore). A decimate-by-16
  boxcar over 16368 captured pairs costs **5.37 cycles/pair** (offset-binary `raw_sum`) or
  **6.12 cycles/pair** (sign-extend `raw_sext`) on the app CPU at 240 MHz. The pass mark is 12,
  with 15 as the ceiling. At 16 MS/s one 8192-pair half takes about 184 µs of the 512 µs it lasts
  (36 % of the app CPU). The app CPU and PRO CPU outputs match bit for bit.
- After all the probes, with the app CPU still parked in its loop, CAP16 at all three rates
  (CRC good) and SPEC (`SPECEND 0 …`) still work.

The result is not strictly gapless (A) because the seam costs 0–7 samples per 8192. Per the plan,
**the user decides whether these counted gaps are acceptable** (B → U6 with gap annotations, or C/U9).

## Notes for U6 if B is accepted

- Bank ownership is `DPORT_IRAM_DRAM_AHB_SEL_REG[6:5]`. The ring needs control bit 17 and count
  8192, and the start sequence is `ctrl|BIT(18)`, `ctrl`, then `ctrl|BIT(31)`. It needs no bit-19
  pulse. The status pointer is `DUMP_STATUS & 0x3fff`.
- Whatever toggles the mode sets *k*. In these runs a tight PRO-CPU poll with interrupts masked did
  it. In U6 the bare-metal app CPU has to poll between DSP blocks, or switch at a CCOUNT-predicted
  wrap time, otherwise *k* grows by the poll interval. ESP32 DPORT access from the app CPU while
  the PRO CPU runs IDF is subject to the DPORT access errata (IDF's `DPORT_STALL_OTHER_CPU`).
  Check that before relying on it.
- *k* can be counted exactly from the sentinel left in the new bank, or from the pointer read after
  the switch (`after`, an upper bound). The first *k* samples of each new lap can be recovered from
  the start of the old bank, if they are read before the old lap's data there is needed. Only the
  old lap's first *k* samples are truly lost.
- The app CPU's ROM boot path uses `0x3ffe3f20..0x3ffe8000`, which a unicore build hands to the
  heap. `dsp_probe.c` reserves it, and U6 must do the same. In unicore the app CPU must run from IRAM
  only, because its cache SRAM is heap.
- Keep any interrupt-masked loop under about 250 ms. Two probe runs of about 400–500 ms tripped the
  interrupt watchdog, and the board reset with bootloader noise at 921600.
- Not shown: sample continuity across the seam with a known signal. The sentinel only shows where
  words were written. A CW tone through a seam, checked for phase continuity, would confirm it.

## Host-side issue found (outside U4)

`host/esp32sdr/transport.py` `SerialTransport.readline`/`read_exact` set the pyserial `timeout`
before every read call. On this CP2102 link that drops bytes: `VERSION?` (155 bytes) times out,
and CAP16 headers and SPEC frames arrive corrupted, while a fixed-timeout bulk read of the same
replies is clean. `host/tools/probe_ring.py` therefore reads replies itself (`collect`, `raw_reply`).
This needs fixing in U2's transport.

## Reproduce

```
. ~/esp/esp-idf/export.sh
idf.py -B build-esp32-devkitv1-probe -DIDF_TARGET=esp32 -DSDKCONFIG_DEFAULTS=sdkconfig.defaults.esp32-devkitv1 -DRING_PROBE=ON build
idf.py -B build-esp32-devkitv1-probe -p /dev/cu.usbserial-0001 -b 921600 flash
cd host && .venv/bin/python tools/probe_ring.py --reset --log /tmp/ring.log --quiet 2 \
  "RINGPROBE 0" "RINGPROBE 1" "RINGPROBE 6" "RINGSPLIT 1 0 8192" "RINGSPLIT 1 1 8192" \
  "RINGSPLIT 1 2 8192" "RINGSPLIT 1 2 16384" "RINGSPLIT 1 3 16384" "RINGPP 1 900 256 64" \
  "RINGPP8 6 400" "RINGPP8 1 1000" "RINGPP8 0 2000" "RINGREARM 6 16380 50" "RINGREARM 1 16380 50" \
  "RINGREARM 0 16380 50" "RINGREARM 1 8192 50" "DSPPROBE 6" "DSPPROBE 1" --check
```

Then reflash the plain profile (`build-esp32-devkitv1`, see `README.md` here).

How to read the output:
- `RINGPROBE r first last wraps changes live freed` covers 1 ms.
- `RINGSPLIT` prints six CPU snapshots of 16 words per 16 KiB quarter (`changed/hash/word0`) and
  then `POST`, the number of words the RF wrote per quarter.
- `RINGPP` used a 16384-word ring with mode 3 at the boundaries. Its upper bank gets only the
  margin writes, which is how the drop of offsets 8192 and up was found.
- `RINGPP8` is the ping-pong described above.
- `RINGREARM` periods are in CPU cycles at 240 MHz. One sample is 15 / 6 / 3 cycles at
  16 / 40 / 80 MS/s.
- `DSPK x100` values are cycles per pair × 100.

## Raw output (final run, 2026-11-05 13:01)

```
# 2026-11-05 13:01:51 port=/dev/cu.usbserial-0001
> INFO
ESP32SDR 6 burst 16380
> VERSION?
VERSION {"revision":"1d27d848e976042207d8b4d2b9581749e739c0d4-dirty","build_date":"2026-11-05","build_timestamp":"2026-11-05T18:00:28Z","profile":"esp32"}
> FREQ 2412
OK
> RINGPROBE 0
RINGPROBE 0 3 14144 4 6056 8 8
RINGWORDS a55aa55a a55aa55a a55aa55a a55aa55a / 12121212 0e0e0e0e 0b0b0b0b 09090909
> RINGPROBE 1
RINGPROBE 1 2 7227 2 6153 8 8
RINGWORDS a55aa55a a55aa55a a55aa55a a55aa55a / 09090909 1a1a1a1a 18181818 10101010
> RINGPROBE 6
RINGPROBE 6 1 15998 0 6153 8 8
RINGWORDS a55aa55a a55aa55a a55aa55a a55aa55a / fdfdfdfd 10101010 12121212 e2e2e2e2
> RINGSPLIT 1 0 8192
RINGSPLIT 1 0 8192
SNAP 0 ptr=5555 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 1 ptr=3077 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 2 ptr=599 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 3 ptr=6313 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 4 ptr=3835 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 5 ptr=1357 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
POST 0 0 0 0
> RINGSPLIT 1 1 8192
RINGSPLIT 1 1 8192
SNAP 0 ptr=5710 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
SNAP 1 ptr=3234 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
SNAP 2 ptr=756 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
SNAP 3 ptr=6470 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
SNAP 4 ptr=3992 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
SNAP 5 ptr=1514 q0=0/88888888/a5c33c5a q1=0/88888888/a5c33c5a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
POST 0 0 4096 4096
> RINGSPLIT 1 2 8192
RINGSPLIT 1 2 8192
SNAP 0 ptr=5710 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 1 ptr=3234 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 2 ptr=756 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 3 ptr=6470 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 4 ptr=3992 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 5 ptr=1514 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
POST 4096 4096 0 0
> RINGSPLIT 1 2 16384
RINGSPLIT 1 2 16384
SNAP 0 ptr=5710 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 1 ptr=11424 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 2 ptr=756 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 3 ptr=6470 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 4 ptr=12184 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
SNAP 5 ptr=1514 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=0/88888888/a5c33c5a q3=0/88888888/a5c33c5a
POST 4096 4096 0 0
> RINGSPLIT 1 3 16384
RINGSPLIT 1 3 16384
SNAP 0 ptr=5710 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
SNAP 1 ptr=11426 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
SNAP 2 ptr=756 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
SNAP 3 ptr=6470 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
SNAP 4 ptr=12184 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
SNAP 5 ptr=1514 q0=16/00000000/a55aa55a q1=16/00000000/a55aa55a q2=16/00000000/a55aa55a q3=16/00000000/a55aa55a
POST 4096 4096 4096 4096
> RINGPP 1 900 256 64
RINGPP 1 halves=900 margin=256 stride=64 checked=898 full=449 minw=6 maxw=128 leftover=53882 first=128 late=0 timeout=0 max_busy=5806 total_cycles=44239370
> RINGPP8 6 400
RINGPP8 6 halves=400 checked=398 k_min=0 k_max=1 k_sum=85 sparse_missing=0 after_min=2 after_max=5 overrun=0 timeout=0 max_busy=4920 total_cycles=49156176
> RINGPP8 1 1000
RINGPP8 1 halves=1000 checked=998 k_min=0 k_max=5 k_sum=1640 sparse_missing=0 after_min=7 after_max=13 overrun=0 timeout=0 max_busy=2070 total_cycles=49154260
> RINGPP8 0 2000
RINGPP8 0 halves=2000 checked=1998 k_min=0 k_max=7 k_sum=6993 sparse_missing=0 after_min=20 after_max=27 overrun=0 timeout=0 max_busy=3015 total_cycles=49154275
> RINGREARM 6 16380 50
RINGREARM 6 16380 50 done=50 timeouts=0 total_cycles=12296467 min_period=245847 max_period=247746 mhz=240
> RINGREARM 1 16380 50
RINGREARM 1 16380 50 done=50 timeouts=0 total_cycles=4925913 min_period=98436 max_period=100335 mhz=240
> RINGREARM 0 16380 50
RINGREARM 0 16380 50 done=50 timeouts=0 total_cycles=2469030 min_period=49299 max_period=51198 mhz=240
> RINGREARM 1 8192 50
RINGREARM 1 8192 50 done=50 timeouts=0 total_cycles=2469063 min_period=49299 max_period=51198 mhz=240
> DSPPROBE 6
DSPPROBE 6 n=16368 decim=16 c1=1
DSPK raw_sext c1=100307 pro=128925 c1_x100=612 pro_x100=787 match=1 out0=-88,13
DSPK raw_mask c1=157459 pro=165750 c1_x100=961 pro_x100=1012 match=1 out0=-88,13
DSPK int8 c1=102745 pro=135100 c1_x100=627 pro_x100=825 match=1 out0=-29,-4
DSPK raw_sum c1=88054 pro=110527 c1_x100=537 pro_x100=675 match=1 out0=-88,13
DSPK load_add c1=35863 pro=40954 c1_x100=219 pro_x100=250 match=1 out0=980442024,0
> DSPPROBE 1
DSPPROBE 1 n=16368 decim=16 c1=1
DSPK raw_sext c1=100306 pro=128925 c1_x100=612 pro_x100=787 match=1 out0=159,22
DSPK raw_mask c1=157468 pro=165750 c1_x100=962 pro_x100=1012 match=1 out0=159,22
DSPK int8 c1=102732 pro=135100 c1_x100=627 pro_x100=825 match=1 out0=34,-1
DSPK raw_sum c1=88054 pro=110527 c1_x100=537 pro_x100=675 match=1 out0=159,22
DSPK load_add c1=35861 pro=40954 c1_x100=219 pro_x100=250 match=1 out0=1015050399,0
> CAP16 16380 0
DATA 16380 e703a2ac 206 payload=32760 crc=good
> CAP16 16380 1
DATA 16380 e6ad5ee9 411 payload=32760 crc=good
> CAP16 16380 6
DATA 16380 b096bda8 1025 payload=32760 crc=good
> SPEC 300 1 1 0 1 1024
SPEC 1024 40000000 1024 2412 | SPECEND 0 0 79 80896 313318 0 0 27 0 0 79 0
> INFO
ESP32SDR 6 burst 16380

```
