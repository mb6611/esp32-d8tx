# Classic ESP32: search for vendor TX-IQ / waveform entry points (offline)

Read-only, offline. No hardware, RF or firmware changes. Written 2026-11-07. This file extends
[`vendor-tx.md`](vendor-tx.md) (V§) and was done independently of it. It checks the claims made
there, adds what DWARF debug info shows, and lists where earlier wording was wrong.

**Bottom line:** no classic vendor function drives sample RAM into RF, and none uses `0x60033d98`
as a playback control. One vendor path does *write* that register, but only as part of a 120-word
MAC-register save/restore around sleep (§2). The "txdump" helpers most likely refer to a
**MAC-frame (byte) dump for the crypto test**, not to baseband I/Q (§3). So they do not support
the window being TX *sample* memory, and README §1 row 2 is too strong.

## 0. Inputs and method

| Input | Path / version |
|---|---|
| ESP-IDF | `~/esp/esp-idf` @ `25fe69f9` (same pin as V§0) |
| Classic libs | every `components/**/lib*/esp32/*.a` except openthread: libphy, librftest, libbttestmode, librtc, libpp, libnet80211, libcoexist, libbtdm_app, libcore, libmesh, libespnow, libsmartconfig, libwapi, libble_mesh, libxt_hal (478 objects) |
| S3 libs (only for comparison) | `components/esp_phy/lib/esp32s3/*.a`, `components/esp_wifi/lib/esp32s3/*.a` |
| ROM ELFs | `~/.espressif/tools/esp-rom-elfs/20241011/esp32_rev300_rom.elf`, `esp32s3_rev0_rom.elf` |
| Tools | `xtensa-esp-elf-{ar,objdump -dr,nm,readelf -rW,readelf --debug-dump=info/line}` from `esp-16.1.0_20260609` |
| EXT | [whstudio123/esp32-iq-tx](https://github.com/whstudio123/esp32-iq-tx) @ `cf88cb6a` (`firmware/src/targets/esp32s3.c`, `docs/REGISTERS.md`) |

Method:
1. **Literal index.** Every `l32r` literal in every classic object and the classic ROM was
   indexed by function (91k rows).
2. **Effective-address scan.** A per-function linear register-constant tracker followed
   `l32r`, `movi`, `mov`, `addi` and `addmi` into memory ops (`l32i`/`s32i`/`l16*`/`s16i`/`l8ui`/`s8i`,
   offsets up to 1020). It also checked constants passed in `a10..a15` at `call8`/`callx8`, which
   catches `esp_dport_access_reg_read(addr)`. Both alias forms (`0x6003xxxx` and `0x3ff7xxxx`)
   were checked.
   - *Validation:* on S3 the scan finds `dactrig`'s `0x60033d64` writes, and on classic it finds
     `adctrig`'s `0x60033d90/94` accesses.
   - *Limits:* it cannot see addresses computed by loops or index arithmetic (that is how §2 was
     missed by byte search), and it cannot see addresses held across branches.
3. **Relocations.** All relocations were searched by symbol name (`readelf -rW`) to find callers
   and function-pointer table entries.
4. **DWARF.** The classic esp_phy, rtc, pp, coex and bt libs **carry DWARF** (the S3 ones are
   stripped). Parameter, local and struct-member names were read with `readelf --debug-dump=info`
   (3900 unique names). These are names only: they label code but do not prove behaviour.

## 1. `0x60033d98` (playback control candidate)

| Check | Result |
|---|---|
| Literal `0x60033d98` / `0x3ff73d98`, classic libs + ROM | none (agrees with V§1) |
| Classic ROM literals anywhere in `0x60033xxx` / `0x3ff73xxx` | **none at all**: the classic ROM never touches the Wi-Fi MAC block by literal |
| Effective-address scan, range `0x60033d95..0x60033dbf` (base+offset and call args) | only libpp `dbg_lmac_diag_statis_dump` **reads** `0x3ff73dac/b0/b4/b8/bc` (diagnostic counters; consistent with M§7 "`0x60033db4` mask is a counter artefact") |
| Wider range `0x60033d80..0x60033dfc` | adds `adctrig` `d90/d94`, `bt_bb_dump`/`rw_rx_dump` `d90`, `bt_bb_dump` call arg `dc4`, `mac_init` `dc4` write, `crypto_encap` `dc0` writes, libpp `hal_mac_rx_get_end_info` reads `0x3ff73d84/88` |
| Looped bulk access | **libpp `wdev_mac_reg_store`/`_load` cover it (§2)** |

**No classic function sets `0x60033d98` to a playback value or waits on its done bit.**

## 2. New: bulk MAC save/restore does write `0x3ff73d98`

`libpp wdev.o`:
- `wdev_mac_reg_store(buf)` calls `wdev_bank_store(buf+0x374, 0x3ff73c00, 120)`.
- `wdev_mac_reg_load(buf)` calls `wdev_bank_load(0x3ff73c00, buf+0x374, 120)`.

The store/load routines bulk-copy **six banks** in total (corrected from an earlier "four"; per validator's `wdev_mac_reg_store`/`_load` disassembly, word counts): `0x3ff73000` x188, `0x3ff73400` x16, `0x3ff73800` x17, `0x3ff73c00` x120, `0x3ff74000` x210, `0x3ff74400` x250. `d98` and `dc0` both fall in the `0x3ff73c00` bank, the one that matters here. The disassembly at `+0x61..0x6f` shows `movi a10,0x374`, `l32r a11/a10 (3ff73c00)` and
`movi a12,120`.

`wdev_bank_load` is a plain word-copy loop (`l32i` from the buffer, `memw`, `s32i` to the
register, 120 iterations). So it **rewrites every word in `0x3ff73c00..0x3ff73ddc`**. That range
includes `d98` (playback), `d90` (DUMP_CTRL), `dc0`/`dc4`, and the hang-prone `d00..d20` that M§4
and M§7 flag.

Call chain, from relocations (`pm_mac_sleep` is also reachable via a `libnet80211` `ieee80211_ioctl` reference; whether that runs in OUR image is unverified): `pm_mac_sleep` → `wdev_mac_sleep` → `wdev_mac_reg_store`, and
`pm_mac_wakeup` → `wdev_mac_wakeup` → `wdev_mac_reg_load` (`.rela.wifi0iram.11/.13`).

Meaning:
- This is a save/restore of whatever value was there. It is **not** a playback recipe, and it does
  not invoke the engine on purpose.
- Whether it runs on the classic chip depends on whether the Wi-Fi driver's MAC-sleep path is
  enabled in our build. That is **unverified**. Our SDR firmware does not run Wi-Fi power save,
  as far as V§/M§ record.
- It does correct one wording. "No vendor code touches `0x60033d98`" should read "no vendor code
  *programs* it". A Wi-Fi-enabled build could restore a stale `0x60033d98` value at wake.

## 3. `get_txdumpaddr` / `clear_txdumpmem`: callers and what "txdump" means

**Callers.** No classic object has an external relocation to either function. The only
references are inside `crypto_common.o` (its own literal and debug sections). The ROM does not
have them, and nothing reaches them through a pointer table. `BTAutotest` (`libbttestmode bt.o`,
DWARF DIE `<f9a>`) declares a local `txdump_addr` next to `keycache_addr`. Neither has a location,
so the local is unused or optimised out. That looks like an abandoned call site. **No caller found in the vendor libs** (the ROM was checked only by literals, so ROM callers are not ruled out). (S3: `dactrig` also has no caller, `nm` shows no `U dactrig`. S3's `adctrig`
writes the owner register `0x600c101c`.)

**DWARF signature** (`crypto_common.o`, DIE `<53c>`, `crypto_common.c:279`):
`get_txdumpaddr(txdump_addr /*r2*/, plcp_11g_len /*r3*/)`. It stores `*txdump_addr = 0x3ffe8000`
and `*plcp_11g_len = 12`. So the "unknown 12" in V§5 and V§9 is labelled **`plcp_11g_len`** in the DWARF output name/constant; that is a name, not behavioral proof that it is an 11g PLCP header length.

**Neighbour `crypto_encap`** (same file; DWARF params `que_no, location, keyentry_mask,
amsdu_valid, fc_qos_valid_bit, amsdu_flag, ampdu_flag, rx_location`):
1. Programs MAC crypto/key-cache registers (`0x60033000..4c`, `0x60033800/04/14`).
2. Writes `DPORT_WIFI_BB_CFG_REG` (`0x3ff00024`) = 2.
3. Writes `0x60033dc0 = 0x8000ffff`, then `0x80007fff`.
4. Calls `tx_a_frame()`, then writes `0x60033dc0 = 0`. (Disassembly `+0x194..0x1da`.)

**Inference (not shown; the post-encryption MAC-byte reading and the meanings of the `0x60033dc0` masks are inferences — the buffer may be PLCP-framed, and shared use of the sample RAM cannot be ruled out):** "txdump" is a dump of the **transmitted MAC frame bytes, after
encryption**, into `0x3ffe8000` for checking the crypto engine. It is enabled through `0x60033dc0`
around one `tx_a_frame()`, and `plcp_11g_len` is the PLCP prefix to skip when parsing. Points for:
- the file and function context (crypto test),
- the PLCP-length output,
- the length-like masks `0xffff`/`0x7fff` written with bit 31 (enable-like),
- `0x60033dc0` sits next to `0x60033dc4`, which `mac_init` and esp-sdr set for capture.

Points against: nothing in the code reads the dump back, and the `0x5aa55aa5` fill and
16383-word length only show the region size.

**Consequences:**
- The vendor name "txdump" does not show the window is DAC playback input. README §1 row 2
  ("Supports the window being TX sample memory") should be downgraded to: shared dump RAM that the
  vendor also uses for a MAC-level TX dump (inference).
- `0x60033dc0` gets a candidate role, "MAC TX-frame dump enable/length", BINARY-MAPPED by context
  only. That fits its measured null as a playback control (V§5, M§).

**Parent's question: would a keyed dump separate playback input from TX output?**
- **Via `0x60033dc0` (crypto txdump):** no. On the inference above it records MAC bytes from a
  packet TX, not baseband samples. Whatever it writes would overwrite the same RAM the engine
  plays from. It says nothing about the DAC.
- **Via `adctrig` / DUMP_CTRL source `[23:20]`:** DWARF gives the parameters
  `adctrig(smp_num_aft_trig, trigmode, trigcase, sample_88m, dump_trig, rx_gain_mode, rx_gain,
  rx_gain0, rx_gain0_wait_us)` (`mac_common.c:652`). `trigcase` is the field V§5 maps to `[23:20]`.
  `dump_trig` maps to bit 17, which M§2 measured as "ring". `sample_88m` selects the bit-16 rate
  case.
  - Every vendor caller takes `trigcase` from console arguments (`run_rftest_case`, `BTAutotest`,
    `rw_autotest`) or passes 0 (`BT_rx_dump`: `a10=0x1fff`, `a11..a13=0`).
  - **No vendor code names a TX-side tap value.** If some `trigcase` taps the TX path, only
    keyed testing could find it.
  - Such a test would only discriminate if all three hold:
    1. the capture lands in the bank the engine is *not* reading (`MAC_DUMP_MODE` split, M§1);
    2. the played pattern is non-trivial and unlike leakage (not DC, not a single tone);
    3. there is a control with the engine stopped and the same keying.

    Without (1), capture output and playback input share addresses and cannot be told apart.

## 4. TX IQ/DC calibration and modem test utilities: do any inject samples?

All of these were checked by literal, call and DWARF (no name taken at face value):

| Function (object) | What it actually does | Sample RAM / `d98`? |
|---|---|---|
| `rfcal_txiq`, `ram_txiq_get_mis_pwr`, `ram_txiq_cover`, `txiq_cal_init`, `bt_txiq_cal` (libphy) | tone registers `0x3ff460b8`, TX IQ-correction `0x3ff450dc`/`0x3ff450a8`, `txcal_debuge_mode`, power-detector reads | no; tone + power-detector loop |
| `ram_txdc_cal_v70`, `rom_txdc_cal_init`, `bt_txdc_cal` | pbus `(1,2)` / DCO tables, `0x3ff4e04c` SAR, `0x113cf0..f3` | no |
| `ram_dc_iq_est`, `ram_iq_est_enable/disable`, ROM `rom_iq_est_*` | IQ estimator control `0x6000607c`/`0x60006060`, result reads `0x600060dc..e4` | no; RX-side estimator |
| `rom_loopback_mode_en(en)` | `i2c_writeReg_Mask(103,1,0,6,6,en)` + `set_txclk_en(en)` + `set_rxclk_en(en)` (slots 0xa8/0x3c/0x40) | no; analog loopback switch. Same name as the S3 recipe step `rom_loopback_mode_en(1)` |
| `rom_set_loopback_gain(a,b,c)` | pbus_force_test (4,1,127), (5,1,a), (0,1,b), (1,1,0x1f9), (1,2,c) | no |
| `tx_cont_en/dis/cfg` (libphy) | only `i2c_writeReg_Mask(103,1,{3,4},6,0,cal±k)` analog trims | no; continuous-TX here is analog plus packets |
| `ram_start_tx_tone` (libphy) | DWARF params `tone1_en, freq_1_mhz, tone1_atten, tone2_en, freq_2_mhz, tone2_atten`; local **`cw_gen_sel`** = `0x3ff460b8` bit 29 (see below) | no |
| `fe_force_tx_tone`, `fcc_bt_force_tx_tone` | `0x600060a0[11:8]=0xe` (+`[17:16]`) after `RFChannelSel` | no |
| `BT_tx_if_init(guard, tx_on_ahead, tx_on_behind, init_tx_DC)` (librtc) | `0x3ff5103c` (BT block): `[30:21]` guard, `[20:11]` 1000−fetx_delay, `[10:1]` tx_on_behind, bit31, bit0 = `init_tx_DC` | no; BT radio-interface timing |
| `dac_out(dac_en, tone_en, dac_value, tone_scale, tone_step)`, `dac_pad_init` (librtc; console cmd in `run_rftest_case` +0x30a7) | `SENS_SAR_DAC_CTRL1/2` `0x3ff48898/9c`, `RTC_IO_PAD_DAC1/2` `0x3ff48484/88` | **no; the GPIO25/26 audio pad DAC**, not RF. Name trap |
| `dac_start_addr` (librtc `rtc_analog.c:528`) | file-scope variable, no location (unused) | no evidence |
| `phy_dac_org`, `bt_rx_2440_dac`, `bt_rx_2480_dac` | used by `bt_rx_spur_opt/cal`, `bt_2480_opt_enter` | BT RX spur (name level) |
| Public API `esp_phy_cert_test.h` + `examples/phy/cert_test` | packet TX/RX, tone, `tx_contin_en`, `cbw40m_en` | no waveform entry |

`cw_gen_sel`: `ram_start_tx_tone` reads `b8` and branches on bit 29 (`bbci a10,29`).
- **Set:** `reg = freq·128/5`, 12-bit field.
- **Clear:** `reg = freq·32/5`, 10-bit field. (`mulsh` by `0x66666667` then `srai 1` = ÷5.)
- It then calls `g_phyFuns[0x44]` (`start_tx_tone_step`).
- So bit 29 picks the NCO **frequency resolution**: one register unit is 1/25.6 MHz = 39.0625 kHz
  (= 80 MHz/2048) when set, and 156.25 kHz (= 80 MHz/512) when clear, *if* `freq` is in MHz as
  its DWARF name says.

This partly answers V§9 ("unit of tone frequency", "role of b8 bit 29"). It is BINARY-MAPPED and
not measured. It is **not** a DAC source mux.

## 5. Role analogs, S3 → classic (role only; no behaviour transferred)

| S3 item (EXT recipe / S3 libs) | Classic counterpart found | Notes |
|---|---|---|
| `dactrig` writes `0x60033d64` = DUMP_CTRL(`d5c`)+8 | **none**; `d98` = DUMP_CTRL(`d90`)+8 by offset only | S3 `dactrig` also has no caller |
| `0x600c101c[3:0]` owner (S3 `adctrig`) | `0x3ff000a8[6:5]` MAC_DUMP_MODE (`adctrig`, `bt_bb_dump`) | M§1 |
| `rom_dac_rate_set` | none (V§6) | — |
| `rom_loopback_mode_en`, `rom_set_loopback_gain` | same names in classic ROM (`0x400030f8`, `0x40003060`); body in §4 | classic `loopback_mode_en` also toggles both clocks |
| `force_txon_mode(1,0,10)` | librftest `force_txon_en` (`0x600060a0[9:8]`, V§7) | different signature |
| NCO clears `0x60006040/44/4c[18]` | `0x600060b8/bc/c4[18]` (V§1) | `c4` never written by vendor start paths |
| "DAC source mux" | **none found.** Only capture-side muxes: `adctrig trigcase` → `[23:20]`; `bt_bb_dump(data_sel, dump_len)` toggles `0x600110f4[0]`/`0x6001c0b8[0]` | EXT S3 recipe has no explicit TX source mux either; S31's `0x20109c04[21]` is a rate clock mux |

## 6. Uncertainty

- The effective-address scan is linear and register-local. It misses table-driven or computed
  addresses (it missed §2 until the loop was read by hand). The libpp/libnet80211/coex code was
  only scanned this way, plus byte search for the base literals.
- The txdump = MAC-frame-dump reading (§3) rests on names and context. Nothing in vendor code
  reads the dump back.
- Whether `pm_mac_sleep`/`wakeup` run in any of our builds was not checked.
- DWARF names describe vendor intent and can be stale (for example `freq_1_mhz`).
- The ROM was searched by literal and by the `g_phyFuns` table only. ROM code paths that reach the
  MAC block through computed pointers would be missed. None were seen, but none were looked for
  beyond that.

## 7. Next steps with no RF

1. **Offline:** read `pm_mac_sleep`/`pm_mac_wakeup` callers and their gating (sdkconfig and
   `esp_wifi` power-save path). That settles whether §2 can run on our image.
2. **Offline:** dump the `.rodata.str` command table in `run_rftest_case`, and map each
   `strcmp` string to its handler. Any console command that reaches `adctrig` with a fixed
   `trigcase` would name a capture source (§3).
3. **Idle read only (bench, no writes):** read `0x60033dc0` and `0x3ff00024` at boot next to the
   existing idle-check set. They are passive context for §3.
   *Status:* `0x3ff00024` idle read done (see `dac-clock-read/`: `0x10000002`);
   `0x60033dc0` idle read still outstanding.
4. **Doc fix (owner of README):** change README §1 row 2 (txdump) and §3/V§1 wording per §2–3.
   *Status:* the README wording fix (lines 11 and 203 earlier referenced) has since been applied.
   This file does not edit them.
