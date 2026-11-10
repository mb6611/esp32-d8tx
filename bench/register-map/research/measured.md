# Classic ESP32 radio register map: what we measured (living register)

Offline audit of our own experiments on the ESP32 DevKit V1 (ESP32-D0WD-V3 rev 3.0, 40 MHz XTAL).
No new hardware runs were made for this document. Last audit: 2026-11-06.

Sources inventoried (all local, paths relative to `/Users/1unoe/Developer/personal/`):

| Tag | Source | What it holds |
|---|---|---|
| S0 | `auto-drone/stage0/README.md`, `capture.py`, `captures/summary_2437MHz_rate1.json` | esp-sdr CAP16 baseline, 2437 MHz, AGC on |
| S1 | `auto-drone/stage1/README.md`, `census.csv` (128 rows), `census.log`, `census/main/census.c` | RW-mask census of `0x60033d00..0x60033dff`, 2 passes |
| S2 | `auto-drone/stage2/README.md`, `run.py`, `results.csv` (1105 rows), `results.log`, `txeng/main/txeng.c`, `iq.py` | Engine behaviour A–E, keying, loopback |
| PB | `esp32-d8rx/bench/cc2500-rxdiag/playback-check/{README.md,inband/,intended/,bank-check/}` | CC2500 external detector vs keyed engine |
| RF | `esp32-d8rx/docs/devkitv1/ring-feasibility.md` | Capture ring mode and bank ownership (RX side) |
| SRC | `esp32-d8rx/main/targets/esp32/receiver.c`, `iq_stream.c`; `~/esp/esp-idf/components/esp_rom/esp32/ld/esp32.rom.ld`; `components/soc/esp32/register/soc/dport_reg.h` | Source constants we rely on |
| EXT | <https://github.com/whstudio123/esp32-iq-tx/blob/main/docs/REGISTERS.md> | Third-party ESP32-S3 / S31 TX register reference (fetched 2026-11-06) |
| AUD | Parent node's classic-ROM source audit, reported by message 2026-11-06 | Three NCO enables, `0x600060a0`, `0x60006000`; no `dactrig`. Not re-derived here; rows citing it are marked SRC-AUDIT |

## How to read the evidence classes

- **SRC** source constant: an address or bit we use because code (esp-sdr, IDF, ROM linker script) names it. Not itself a measurement.
- **M** measured readback: a value or behaviour read from our board, with the file that holds the raw line.
- **H** hypothesis: our interpretation, not shown.
- **I** inferred cross-chip translation from EXT or the S3 esp-sdr backend; nothing on the classic chip confirms it unless an M row says so.
- **Bank: CAP / TX**: whether a fact was established with the block *capturing* (RF writes the window) or the *playback engine* running (RF reads it, by hypothesis). The window is one memory; ownership facts measured on one side are marked, not assumed for the other.

Confidence: **high** = repeated in ≥ 2 sessions or ≥ 64 reps with identical result; **med** = one session or indirect; **low** = single observation or interpretation only.

---

## 1. Sample memory and bank ownership

| Address | Field / behaviour | Class | Evidence | Conf. | Bank |
|---|---|---|---|---|---|
| `0x3ffe8000..0x3fff7fff` | 64 KiB I/Q window, 16384 words. esp-sdr reserves it (`SOC_RESERVE_MEMORY_REGION`); census and txeng do the same. | SRC | `receiver.c:40`, `census.c:46`, `txeng.c:68` | high | — |
| same | Capture of n samples writes exactly words `0..n-1`, sentinel elsewhere. | M | S1 `T,pre/post` 256 words; S2 `D capture_alone_*` | high | CAP |
| same | Engine running alone writes nothing (all 16384 sentinel words intact, grant 0/2/3). | M | S2 `D engine_alone_sentinel_gmode{0,2,3}` | high | TX |
| same | A capture started while the engine runs lands at the engine's address and rate: words `[3..6, N−1]` regardless of the capture's own count/rate. | M | S2 `D follow_*` table (7 cases) | high | CAP+TX |
| same | Word format (capture): I `[9:0]`, Q `[19:10]`, Q negated for standard I/Q; 8-bit mode also exists (CAP16 `bits` 8/10). | SRC+M | S0 `LIMITS` reply; S2 `iq.py` | high | CAP |
| same | Word format the *engine plays* (I/Q order, width, sign): **unverified**. The fill helpers assume the capture format. | H | S2 README "Unresolved"; PB `inband/README.md` Limits | — | TX |
| `DPORT_IRAM_DRAM_AHB_SEL_REG` = `0x3ff000a8`, bits `[6:5]` `MAC_DUMP_MODE` | Bank ownership. esp-sdr sets 3 for a capture. | SRC | `dport_reg.h:802-808`, `receiver.c:118` | high | — |
| same | 2 = RF owns lower 32 KiB, 1 = upper, 3 = both, 0 = none. In modes 1/2 writer offsets ≥ 8192 are dropped (no alias). CPU reads of an RF-owned bank return constant `0xa55aa55a`. | M | RF `RINGSPLIT`, `RINGPP` | high | CAP |
| same | Grant mode does not change engine timing or completion (0/1/2/3/leave all identical). | M | S2 `A gmode0 vs gmode3`, explore logs | high | TX |
| same | Whether the engine's *reads* obey the same bank map as the capture writer: assumed, not shown. `bank-check` keyed gmode 2 and 1 and saw no sample-dependent RF in either. | H | PB `bank-check/README.md` ("ASSUMED not proven") | — | TX |
| `0x3ffe3f20..0x3ffe8000` | App-CPU ROM boot path; must be reserved in unicore builds that start the app CPU. | SRC | `iq_stream.c:93`, RF notes | high | — |

## 2. Capture control block (`0x60033d90..0x60033d94`, `0x60033dc4`)

| Address | Field / behaviour | Class | Evidence | Conf. | Bank |
|---|---|---|---|---|---|
| `0x60033d90` DUMP_CTRL | count `[13:0]` (esp-sdr caps n ≤ 16380), bit 15 = 40 MS/s, bit 16 = 16 MS/s, neither = 80 MS/s, bit 17 = ring, bit 18 = done (RO), bit 19 = trigger pulse, `[23:20]` = source (0..3), bit 31 = enable. | SRC | `receiver.c:120-125`, `iq_stream.c:363-366` | high | CAP |
| same | RW mask `0x7ff3ffff` with bits 31/19 untested (census excluded them); bit 18 not writable; reset 0. | M | S1 `census.csv` row `0x60033d90` | high | CAP |
| same | Rates confirmed by capture-duration slope (esp-sdr) and by ring wraps: 4/2/0 wraps per ms at 80/40/16 MS/s. | M | `receiver.c` comment; RF `RINGPROBE` | high | CAP |
| same | Ring start sequence `ctrl\|BIT18`, `ctrl`, `ctrl\|BIT31`, no bit-19 pulse, count 8192. | M | RF "Notes for U6"; `iq_stream.c:363` | high | CAP |
| `0x60033d94` DUMP_STATUS | `[14:0]` = samples written (esp-sdr checks `== n`); RO, 0 idle; `& 0x3fff` is the ring pointer. | SRC+M | `receiver.c:133`; S1 census row (rw 0); RF | high | CAP |
| same | Stays 0 while the engine runs with no capture armed (88/88 `mid` and `done` snapshots); so it is not an engine progress counter. With a concurrent capture it shows capture counts (`0x27`–`0x1f40` in the other 46), not the engine's position. | M | S2 `results.log` `S,{mid,done}` column 6 | high | TX |
| `0x60033dc4` DUMP_BYTES | esp-sdr writes `0x03020100` ("four distinct bytes, as in mac_init"); fully RW, reset 0. | SRC+M | `receiver.c:119`; S1 row | high | CAP |
| `0x3ff5c02c` RX_GAIN | bit 23 = force gain, `[31:24]` gain code (esp-sdr); forced max (72) in S2 E changed nothing in loopback. | SRC+M | `receiver.c:159-161`; S2 E | med | — |

## 3. Candidate playback engine `0x60033d98` (DUMP_CTRL + 8)

| Field | Behaviour | Class | Evidence | Conf. |
|---|---|---|---|---|
| whole word | RW mask exactly `0x8ff8bfff`; reset 0; never changes on its own; identical in both census passes. | M | S1 `census.csv` rows `0x60033d98` (pass 1 and 2) | high |
| bit 31 | run: starts the engine; done comes after a time proportional to count; works with TX powered down and any grant. | M | S2 `A` 64/64 done every case | high |
| bit 18 | done (RO). Stays set while run stays set; clears with run (`ctrl_after_clr` has no bit 18). | M | S2 `A ctrl_at_done=0x8004xxxx`, `ctrl_after` | high |
| `[13:0]` | count; N = count + 1 samples, 1..16384; count 0 never completes. | M | S2 `A` incl. `rate{0,1}_count0` | high |
| bit 15 | 1 → 80.01 MS/s (2.9995 cyc/sample @240 MHz), 0 → 40.00 MS/s (6.0003 cyc/sample); intercepts 0.25 / 0.17 µs. | M | S2 `A *_fit` | high |
| bit 19 | With run+hold set: no done within 2 ms, reads `0x800883ff`; clearing bit 19 with run kept → done (`0x800483ff`). Interpreted as a **start gate ("hold")**. | M + H | S2 `B hold_set_with_run`, `hold_then_release` | behaviour high; interpretation **low**, see §6 |
| `[27:20]` | Writable; values `0xff`, `0x01`, `0x80` gave the same timing as 0. | M | S2 `B bits27_20=*` | high |
| retrigger | No loop/retrigger: writing run again while done is set does not restart; run must be cleared first. One write `count\|rate\|run` after a clear works. | M | S2 `B noclr_*`, `one_write` | high |
| back-to-back gap | MCU poll-clear-rearm loop: start-to-start minus N/rate = 0.49–0.51 µs @40 (≈20 samples), 0.56–0.59 µs @80 (≈45–48). Upper bound on the on-air seam only. | M | S2 `C` | high |
| memory access | Sequences addresses `0x3ffe8000 + 4·[0..N−1]` at the engine rate (shown via the concurrent-capture landing); **reading the data is not shown**. | M + H | S2 `D follow_*` | sequencing high; data path unknown |
| radiation | Keyed RF (LO/tone leakage) is seen by an external CC2500 at 2412; **sample-dependent RF neither shown nor excluded** in four external sessions (pattern ±1.25 MHz out of slice; DC; pat156 at ±156 kHz; bank 2 vs 1). On-chip self-loopback is blind (positive control fails). | M | PB `README.md`, `inband/`, `intended/`, `bank-check/`; S2 `E1`, `E2` | high that it is unresolved |

## 4. Other registers in `0x60033d00..0x60033dff` (census, pass 1 = pass 2 unless noted)

| Address | Reset | RW mask | Notes | Class | Conf. |
|---|---|---|---|---|---|
| `d00, d08, d10, d18, d20` | 0 | `ffffffff` | Bits 31:30 self-clear within 20 µs; **write-1 RTC-WDT-resets the chip** (reason 7) a few ms later, both passes. Hypothesis: MAC TX DMA descriptor pointers. txeng `W` refuses this range. | M (hang) / H (role) | high / low |
| `d04, d0c, d14, d1c, d24` | 0 (`d24` = 1) | `0f3fffff` (`d24`: 0) | Paired with the hang words. `d24` reads 0 right after write-1 and 1 again at 20 µs: strobe or status. | M | med |
| `d28`, `d34` | 0 | `00ffffff` | | M | high |
| `d2c` | `00000d3c` | `00003f3f` | | M | high |
| `d30` | `01403203` | `ffffff03` | | M | high |
| `d38` | `0c80000a` | `ffffffff` | | M | high |
| `d3c` | `68033210` | `f80fffff` | | M | high |
| `d40` | `00000010` | `000001ff` | | M | high |
| `d44` | `100a1010` | `ffffffff` | | M | high |
| `d48`, `d50` | 0 | `00000001` | | M | high |
| `d4c`, `d54` | 0 | `ffffffff` | | M | high |
| `d58..d74`, `d9c..db0`, `dd8..dfc` | 0 | 0 | Read 0, take no writes. | M | high |
| `d78` | `00000100` | `000001f0` | Bit 8 set at reset, not writable. | M | high |
| `d7c` | `40000000` | `c0000000` | | M | high |
| `d80, d84, d88, d8c` | live | 0 | RO counters, drift over seconds; unchanged across an engine run. | M | high |
| `db4` | `0ff00a0x` | `00000006` (artefact) | Bits `[3:0]` free-run; bits `[11:8]` take values `0xa`/`0x4`/`0x0` in every snapshot phase whether or not the engine runs (checked over 536 `S,` lines), so not an engine progress field. | M | high |
| `db8` | 0 | 0 | Bit 0 toggled spontaneously in pass 1 only. | M | low |
| `dbc` | 0 | `0000003f` | Reads back as written; no effect on engine timing/range. | M | high |
| `dc0` | 0 | `bfffbfff` | Two 14-bit fields + bits 15/31 ("candidate #2"). Ten values incl. all ones: no effect on engine timing or address range. | M | high |
| `dc8` | 0 | `ffffffff` | Three values: no effect on the engine. | M | med |
| `dcc` | 0 | `c000ffff` | Four values: no effect on the engine. | M | med |
| `dd0, dd4` | live | 0 | RO counters, drift over seconds; unchanged across an engine run. | M | high |

Census caveats (S1): read side effects (clear-on-read, FIFO pops) are indistinguishable from live counters; DUMP_CTRL bits 31/19 were never written; the whole range `0x60033xxx` is the Wi-Fi MAC/BB aperture (alias of `0x3ff73xxx`), so MAC registers are expected.

## 5. TX keying path (classic chip)

| Item | Fact | Class | Evidence | Conf. |
|---|---|---|---|---|
| `0x600060b8` TONE0 (NCO 1) | bit 18 = tone enable (`rom_stop_tx_tone(1)` clears exactly that bit); gain code `[17:10]`; `[9:0]` another field. Boot readback `0x2003a020` (bit 18 clear). | SRC (reverse-engineered from libphy/ROM) + M (readback) | S2 README E; `results.log` `I,ready … tone0=2003a020`; `txeng.c:75` | med |
| `0x600060bc` (NCO 2), `0x600060c4` (NCO 3) | Bit 18 of each is an NCO enable; the classic ROM maps three (homologs of S3 `0x60006040/44/4c`). txeng clears only `b8`; `key()` passes `en2=0` to `rom_start_tx_tone_step`, which writes `bc` off; **`c4` was never read or written in any of our runs**. | SRC-AUDIT (parent's ROM source audit, 2026-11-06; no readback from our board) | parent message; `txeng.c:186,260` | med (source) / none (measured) |
| `0x600060a0` | TX/RX clock and force fields (classic). Never touched or read by txeng. | SRC-AUDIT (parent, 2026-11-06) | parent message | med / none |
| `0x60006000` | Role **UNVERIFIED**: a "digital gain" label came only from an unverified parent audit message and is not confirmed by vendor-tx.md. Do not rely on it. Never touched by txeng. | UNVERIFIED | parent message | med / none |
| ROM symbols | `rom_start_tx_tone_step` `0x400035d0`, `rom_stop_tx_tone` `0x40003f98`, `rom_pbus_xpd_tx_on/off` `0x400045e0/0x40004590`, `rom_set_rf_freq_offset` `0x40004ca8`, `rom_chip_i2c_readReg/writeReg` `0x40004110/0x40004168`. **No `rom_dac_rate_set` in the classic ROM table** (it exists on S3 at `0x400061ec`). | SRC | `esp32.rom.ld`, `esp32s3.rom.ld` | high |
| `K 0` keying | `txcal_debuge_mode(0)` + `rom_start_tx_tone_step(1,0,127,0,0,0)` + PBUS (5,1) = pwr. Keyed RF seen externally at 2412 in every session. RX is deaf in this mode (rms 8 vs ambient 24–130, 43 dB DC line). | M | S2 E1; PB all sessions | high |
| `K 1` keying | `rom_pbus_xpd_tx_on(pwr, 288)` + tone. RX alive, but **not even the tone was detected externally** (0/6). | M | S2 E1; PB `pilot2-km1` | med |
| PBUS (4,1), (5,1) | Set to 127 by keying; (5,1) reads 127 during key, 0 before/after. Power-code scale on the classic chip unknown. | M / H | PB `slots.jsonl` pb51; S2 README Unresolved | high / — |
| Keying overhead | keyed_us = key/unkey overhead + engine poll; K 0 overhead 117–130 µs; first key after boot 243–291 µs (bursts of 483/445/448/368/320 µs recorded, all first keyed slot of a session). | M | PB README Limits; `inband`, `intended` | high |
| Channel select `Q` | `set_chanfreq(2412,0)`, release cap-code pin (`I2C 0x62/1/0` bit 7), `rom_set_rf_freq_offset(xtal, f, 0)`. `cap_reg` 0xb0 → 0x30 after `Q 2402`. Only proves the path ran; no PLL-lock readback; not known whether key()/unkey() preserve it. | M (readback) / H (frequency) | S2 README "Channel select"; stage3 README:53 | low |
| Unkey | `g_phyFuns[68/4](0,…)`, `g_phyFuns[0x124/4]()`, `rom_stop_tx_tone(1)`, then esp-sdr RX-only PBUS setup; PBUS and capture state verified fine afterwards. | M | S2 README E | med |

## 6. S3 → classic side-by-side (per the parent's request)

S3 column: EXT (whstudio123 `docs/REGISTERS.md`) and esp-sdr's S3 backend (`main/targets/esp32s3/receiver.c`). Classic column: our measurements. **Every translation is inferred (I) unless the status column says measured on the classic chip.**

| Role | ESP32-S3 (EXT / esp-sdr S3) | Classic ESP32 counterpart | Status on classic |
|---|---|---|---|
| Sample buffer | `0x3fcd0000..0x3fcdffff`, 64 KiB, packed IQ10 (EXT; esp-sdr S3 `IQ_BUFFER`) | `0x3ffe8000..0x3fff7fff`, 64 KiB | **Measured** as capture/engine address range (§1). Playback word format **inferred** from capture format, unverified. |
| Bank owner | `0x600c101c` low nibble: `0` CPU idle / `4` RF playback (EXT; esp-sdr S3 `SRAM_OWNER_REG` uses 4 for capture too) | `DPORT_IRAM_DRAM_AHB_SEL_REG[6:5]` (`0x3ff000a8`), `MAC_DUMP_MODE` 0..3 | **Measured on the capture side** (mode → bank map, §1). For playback: engine runs identically under 0/1/2/3, and no sample-dependent RF was seen under 2 or 1 (bank-check). Which mode the engine *needs* to read samples is **unknown**. |
| Playback control | `0x60033d64` = capture ctrl (`0x60033d5c`) + 8: count `[13:0]`, **bits 27:20 repeat the low 8 count bits**, **bit 19 = loop**, bit 31 = enable (EXT) | `0x60033d98` = DUMP_CTRL (`0x60033d90`) + 8, mask `0x8ff8bfff` | **Measured**: same offset, same mask, count/run/done/rate as §3. **Discrepancies with EXT:** (a) the count-duplicate bits `[27:20]` are writable on the classic chip (census) but **no keyed session ever set them** (AUD confirms); runs completed without them; `0xff/0x01/0x80` there changed nothing. (b) We read bit 19 as a *hold/start gate*; EXT calls it *loop*. Our data (no done while set, done after clear) fits **both** readings: a looping engine also never asserts done until loop is cleared. **Classification: hypothesis, unresolved.** |
| Playback rate | `0x60033d64[15]` 0/1 = 40/80 MS/s "together with the ROM clock setting" (EXT) | `0x60033d98[15]` 0/1 = 40.00/80.01 MS/s | **Measured** (engine completion time, §3). Whether the *DAC* clock follows without a ROM call is **not measured** (completion time says nothing about the DAC). |
| ROM DAC rate config | `rom_dac_rate_set(1/0)` ↔ 40/80 MS/s (EXT; esp-sdr S3 declares it under `SAMPLE_RATE_PROBE`) | **No `rom_dac_rate_set` and no `dactrig` in the classic ROM** (`esp32.rom.ld`; AUD). txeng never set any DAC rate. | **Source fact** (absence). Classic equivalent, if any, **unknown**; this is a candidate reason for a silent engine. |
| Capture disabled during TX | `0x60033d5c` = 0 (EXT; esp-sdr S3 writes 0 before/after capture) | `0x60033d90` = 0 | **Measured as a state, not as a cause.** S2 `S,pre/mid` snapshots (DUMP_CTRL column) read 0 in all 134 `pre` and all 88 non-capture `mid` lines and PB sessions did not arm a capture (AUD: capture 0 from logs). No test varied it. |
| NCO / tone enables | `0x60006040/44/4c[18]` all cleared after vendor CW prep (EXT); S2 README names `0x60006040` as the S3 tone register | `0x600060b8/bc/c4[18]` (parent's ROM source audit, 2026-11-06) | **Source-mapped, not measured.** txeng flag 8 / `clr18` clears only `b8[18]`; `bc` is written off through `en2=0` in `rom_start_tx_tone_step`; **`c4[18]` was never cleared or read in any keyed session**, so every PB null ran with an unchecked NCO gate (EXT's S3 note: an NCO left on blocks IQ TX). |
| TX force / clocks | EXT S3 path releases forced TX and gates PBUS TX/RX clocks after playback | `0x600060a0` holds the classic TX/RX clock and force fields; `0x60006000` role is UNVERIFIED (an unverified parent audit called it digital gain; not confirmed) | **Source-mapped, not measured.** txeng never reads or writes either; keying goes through the vendor CW path (`txcal_debuge_mode` + tone) only. |
| Vendor TX prep | `esp_phy_wifi_tx_tone(1, ch, backoff)` then stop tone, release forced TX, PBUS TX/RX off (EXT) | `K 0`: `txcal_debuge_mode(0)` + `rom_start_tx_tone_step`; unkey via `g_phyFuns[68/4]`, `[0x124/4]` | **Measured** that it keys RF; **inferred** that it is the equivalent prep. |
| Loop / periodic TX | S31 has REGDMA/ETM timer chains; S3 bit 19 loop (EXT) | Retrigger needs run cleared first; bit 19 semantics open | See playback-control row. |

## 7. Known hazards (do not repeat)

1. Write-1 to `0x60033d00/08/10/18/20` WDT-resets the chip (S1). txeng refuses them.
2. Interrupt-masked loops > ~250–300 ms trip the interrupt WDT (RF).
3. First keyed burst after boot overruns the 444 µs bench rule (483/445/448 µs seen). Use a shorter count/budget and stop on the first overrun; keying needs user approval (`playback-cc2500-check` memory).
4. Reading a bank the RF owns returns `0xa55aa55a`, not memory (RF): "live" readings through a granted bank are artefacts.
5. Analyse only the words the capture wrote; untouched pattern words fake a −625 kHz line (S2).
6. Capture `rw_mask` for `0x60033db4` is an artefact of a free-running counter (S1).
7. On-chip self-loopback cannot see the chip's own TX in any keying mode (S2 E2); only an external receiver counts.
8. CP2102 serial: per-read pyserial timeout drops bytes; read in bulk (RF).
9. One unexplained ESP reboot (reason 7) during PB session A is in no saved log.

## 8. Outstanding discriminating tests (ordered by what they would settle)

| # | Open question | Test (bench, needs approval if it keys RF) | Settles |
|---|---|---|---|
| T1 | Bit 19: hold vs loop | Engine with bit 19 + run set, small N (e.g. 255) and a **concurrent capture** with sentinel-filled window, no keying. Hold → no words written (or only the first few); loop → words `0..N−1` rewritten and the capture pointer wraps. Compare against S2 `D follow_*`. | §3 bit 19 row; S3 EXT discrepancy |
| T2 | Does the engine read the words? | Not answerable on-chip (S2 D shows addresses only). Needs T4 with a line in-slice. | §3 memory access |
| T3 | DAC clock gating | Offline: search libphy/ROM for a classic DAC-rate routine (the S3 has `rom_dac_rate_set`); on bench, read back any PHY register that `txcal_debuge_mode` touches before/after. | §6 DAC-rate row |
| T4 | Sample-dependent radiation | Use a receiver with an in-slice positive control: a wideband SDR for the ±1.25 MHz line, or a close-in pattern (e.g. +50 kHz) compared with keyed zero at the same CC2500 center/BW. The latter tests sample dependence in the passband but does not prove spectral shape. | §3 radiation |
| T5 | NCO 3 (`0x600060c4[18]`) state during keying | Read `0x600060b8/bc/c4` and `0x600060a0` at boot, after `K 0` key, after `clr18`, after unkey (the reads are readbacks, but the sequence includes an actual `K 0` key, so it is an RF-emitting test, not a no-RF observation: it needs explicit user approval; **do not key** without it. `clr18` is also a write). If `c4[18]` is set during keyed slots, a masking NCO becomes a plausible cause; a controlled clear-and-compare test is still needed to show causality. | §5/§6 NCO rows |
| T6 | Count duplicate `[27:20]` | Run with `[27:20]` = low 8 count bits vs 0 under T4's receiver. Timing alone cannot tell (already equal). | §6 playback-control row |
| T7 | Bank mode for playback | Under T4: fill only the lower bank, run with mode 2 vs 1 vs 3. Timing is identical (measured), so only RF can tell. | §1 bank row |
| T8 | `Q` retune actually moves the LO | Read a PLL/lock register or observe externally; `cap_reg` only proves the code ran. | §5 channel select |

---
Maintenance: when a test above runs, move its result into the matching section with the raw-file path, update the class/confidence, and strike the row here. Keep S0–S2 paths pointing at `auto-drone/`, which is outside this repo.
