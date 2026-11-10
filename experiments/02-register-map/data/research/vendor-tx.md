# Classic ESP32 vendor TX functions: ROM, libphy and librftest, mapped by disassembly

Offline only: no hardware, no RF, no firmware changes. Written 2026-11-06. This file goes with
[`measured.md`](measured.md), the audit of what our own runs measured. This file covers what the
vendor binaries *do*. A function name is only a label. Every behaviour claimed below comes from
the disassembly, and the exact instructions or literals are quoted. Where vendor code does
something we have **never** run, the note says so.

## 0. Inputs and how to reproduce

| Input | Path | sha256 |
|---|---|---|
| ESP-IDF (pinned) | `~/esp/esp-idf` @ `25fe69f946311abdaf9ad56591f25fedbc20ac98`; `components/esp_phy/lib` @ `e294ff03` | — |
| `libphy.a` (esp32) | `components/esp_phy/lib/esp32/libphy.a` | `c2521071…5740` |
| `librftest.a` (esp32) | `components/esp_phy/lib/esp32/librftest.a` | `17cdfede…4dc8` |
| `libbttestmode.a` (esp32) | `components/esp_phy/lib/esp32/libbttestmode.a` | `fd512e31…dc8` |
| ROM ELF, classic rev3 | `~/.espressif/tools/esp-rom-elfs/20241011/esp32_rev300_rom.elf` | `920b7063…ca31` |
| ROM ELF, S3 (only for comparison) | same dir, `esp32s3_rev0_rom.elf`; S3 `librftest.a` under `lib/esp32s3/` | — |
| Our firmware | `tools/txeng/main/txeng.c` | `f77deb51…a97d` |
| Toolchain | `~/.espressif/tools/xtensa-esp-elf/esp-16.1.0_20260609/xtensa-esp-elf/bin/xtensa-esp-elf-{nm,ar,objdump}` | — |

Method: `ar x` each library, then `objdump -dr` each object. Literal-pool values appear as
`(0x…)` and relocations as `R_XTENSA_32 <sym>`. ROM code was read with
`objdump -d --start-address=… --stop-address=…`. The ROM PHY function table was read from the ELF's
`.data_phyrom` section (file offset `0x6e830`, VMA `0x3ffae0c0`). The whole table was byte-searched
for register literals across every `components/**/lib/esp32/*.a` and the ROM ELF (16 files).

Alias note: libphy and librftest reach peripherals through `esp_dport_access_reg_read` at
`0x3ff4xxxx` addresses, and ROM uses `0x6000xxxx`. `0x3ff46xxx` is the same register as
`0x60006xxx` (the same pair `0x3ff460b8` / `0x600060b8` appears in libphy's `ram_start_tx_tone` and
in ROM `rom_start_tx_tone_step`). Below, addresses are given in the `0x6000xxxx` form.

## 1. Headline results

1. **No vendor code on the classic chip touches the playback register `0x60033d98`.** The literal
   `0x60033d98` (and its alias `0x3ff73d98`) occurs in none of the 16 binaries. The S3 has a
   vendor playback routine, `dactrig` in S3 `librftest.a:mac_common.o`, which programs
   `0x60033d64` (§5). The classic `librftest.a` has `adctrig` (capture) but no `dactrig`. So
   everything known about the classic engine comes from our own reverse engineering
   (`measured.md` §3), not from a vendor recipe.
2. **The classic chip has three tone/NCO enables.** `rom_stop_tx_tone(n)` clears bit 18 of
   `0x600060b8` (n = 1), `0x600060bc` (n = 2), `0x600060c4` (n = 3), and all three for any other n,
   including 0. This **corroborates** the source audit. One addition and one correction:
   - **Addition:** txeng's key call `rom_start_tx_tone_step(1,0,127,0,0,0)` also writes
     `0x600060bc` with en2 = 0 on every key, and unkey's `g_phyFuns[17](0,…)` writes zeros to both
     b8 and bc. So tone 2 is forced off by our code. It is not left alone.
   - **Correction:** "txeng only clears b8" is wrong for bc and right for c4. **Tone 3 (`0x600060c4`)
     is never written** by txeng, by `wifiscwout`, or by any classic vendor code that starts a
     tone. Its only reference anywhere is in `rom_stop_tx_tone`. Its live value has never been
     read.
3. **The tone register encoding is now confirmed by a hardware readback we already have.** From the
   ROM code, `rom_start_tx_tone_step(1, 0, 127, …)` with b8 bit 29 set at boot (`0x2003a020`)
   predicts `0x20060400`. The PB logs show `tone_before = 20060400` in all 218 keyed `E,` lines, and
   `tone_after = 20020400` (bit 18 cleared) in the 159 lines with flag 8. So gain is stored
   **negated**: 127 is written as `0x81` in `[17:10]`.
4. **There is no DAC-rate routine on the classic chip.** The S3's `rom_dac_rate_set` writes
   `0x6000608c[27]` and two analog I2C bits (§6). No classic ROM or library function writes
   `0x6000608c`, and no call with the S3's I2C argument pattern was found. Whether the classic
   DAC clock follows `0x60033d98[15]` by itself is still open.
5. **Our `K 1` and `K 2` keying modes skip steps that the vendor CW path performs.** These are
   `pbus_debugmode` (forces the PBUS mode), `set_txclk_en(1)` (`0x600060a0[17:16]`) and the DCO
   set. That would explain the CW silence measured in `K 1`, but it is a hypothesis (§4).

## 2. ROM PHY function table and libphy's overrides

ROM `phy_get_romfuncs` = `0x40004100`. `rom_phyFuns` (`0x3ffae0c0`) points to `g_phyFuns_instance`
(`0x3ffae0c4`). The slots relevant to TX, from the ROM `.data_phyrom` initial values, are below.
libphy `phy_chip_v7.o:phy_get_romfunc_addr` (called from `register_chipv7_phy`) overwrites some
slots with `ram_*` versions. That overwrite was decoded from its literal pool (`R_XTENSA_32 ram_*`)
and its `s32i aX, a10, <slot>` stores.

| Byte offset | ROM entry | Overridden by libphy? |
|---|---|---|
| 0x3c | `rom_set_txclk_en` `0x40003564` | **yes**, `ram_set_txclk_en` (same register/field) |
| 0x40 | `rom_set_rxclk_en` `0x40003594` | yes, `ram_set_rxclk_en` |
| **0x44** | **`rom_start_tx_tone_step` `0x400035d0`** | **no**, so `g_phyFuns[68/4]` is the ROM function |
| 0x48 | `rom_start_tx_tone` `0x400036b4` | yes, `ram_start_tx_tone` |
| 0x4c | `rom_stop_tx_tone` `0x40003f98` | no |
| 0xb8 | `rom_pbus_force_test` `0x400043c0` | yes |
| 0xc0 | `rom_pbus_debugmode` `0x40004458` | yes |
| 0xd8 | `rom_pbus_xpd_tx_on` `0x400045e0` | yes, `ram_pbus_xpd_tx_on` (differs, §4) |
| 0xdc | `rom_pbus_set_dco` `0x40004638` | no |
| 0x10c | `rom_txbbgain_to_index` | yes |
| 0x11c | `rom_en_pwdet` `0x4000506c` | yes, `ram_en_pwdet` (differs, §4) |
| **0x124** | **`rom_txcal_work_mode` `0x4000510c`** | **yes**, `ram_txcal_work_mode` (differs, §4) |
| 0x128 | `rom_txiq_set_reg` `0x40005154` | no |

So txeng's `unkey()` runs ROM `start_tx_tone_step` but **libphy's** `txcal_work_mode`. This holds
only if `register_chipv7_phy` ran in that firmware. It does on any esp-sdr/IDF PHY init, but that
was not checked at run time.

## 3. Tone / NCO generators

### `rom_start_tx_tone_step(en, f, g, en2, f2, g2)`, ROM `0x400035d0`, decoded
```
400035d3 l32r a8,(600060b8) ; 400035d6 neg a4,a4 ; 400035de neg a7,a7
400035e1 extui a2,a2,0,8    ; 400035e4 sext a3,a3,15 ; 400035ed extui a4,a4,0,8 (-g)
400035f3 bbci a9,29,…       ; branch on 0x600060b8 bit 29
  bit29=1: 0x600050a8[1:0] = f&3, 0x600050a8[3:2] = f2&3, then f>>=2, f2>>=2
400035c4 lit 0x0fffffff (f mask) ; 400035c8 lit 0xf0000000 (old bits kept)
b8 = (b8 & 0xf0000000) | (f & 0x0fffffff) | en<<18 | ((-g)&0xff)<<10
bc = (bc & 0xf0000000) | (f2 & 0x0fffffff) | en2<<18 | ((-g2)&0xff)<<10
```
- Bits 18 and `[17:10]` are the ROM's own layout. The width of the frequency field is **not**
  enforced: f is sign-extended from 16 bits and masked only to 28 bits. Callers keep it to 10
  bits. `rom_start_tx_tone` (below) masks it to 10 or 12 bits, and librftest
  `wifi.o:sampledeal` treats the value as a signed 10-bit field (`extui a2,a2,0,10`, then `−0x400`
  if > `0x1ff`). en is 8 bits shifted to bit 18, so any en other than 0 or 1 would spill into
  bits 19–25.
- The function writes **only** b8, bc, and (in bit-29 mode) `0x600050a8[3:0]`. It never touches c4.
- Bit 29 of b8 is a mode bit that this function reads. Our boot readback `0x2003a020` has it set
  (`txeng` `I,ready`, 26 lines across logs), so on our board the low 2 frequency bits go to
  `0x600050a8`.

### `rom_start_tx_tone(en, f, g, en2, ?, g2)`, ROM `0x400036b4`, and `ram_start_tx_tone` (libphy)
These convert f before calling slot 0x44. With bit 29 clear: `((f<<5)·0x66666667)>>33`, about
f·6.4, masked to 10 bits. With bit 29 set: f·25.6, masked to 12 bits. If f is in MHz, that is
one LSB = 156.25 kHz = 80 MHz/512, or 39.06 kHz = 80 MHz/2048 in fine mode. **The unit of f is
inferred, not shown.** The ROM version passes the converted f for f2 as well (a14 is reused). The
libphy version converts f and f2 separately (`phy_chip_v7.o` +0x22..0x6a).

### `rom_stop_tx_tone(n)`, ROM `0x40003f98`
`beqi a2,2 → bc`, `beqi a2,3 → c4`, `bnei a2,1 → all`. Each path ANDs with `0xfffbffff`
(clears bit 18 only, leaving frequency and gain fields). Literal `0x600060c4` at `0x40003f94`.

### Who writes which enable (classic, all binaries)
| Register | Set by | Cleared by |
|---|---|---|
| `0x600060b8` bit 18 | `rom_start_tx_tone_step` en | `stop_tx_tone(1/other)`; `start_tx_tone_step(0,…)` |
| `0x600060bc` bit 18 | `rom_start_tx_tone_step` en2 | `stop_tx_tone(2/other)`; any `start_tx_tone_step(…,en2=0,…)` |
| `0x600060c4` bit 18 | **nothing found** (only literal use is in `rom_stop_tx_tone`; `0x3ff460c4` not in any lib) | `stop_tx_tone(3/other)` |

The S3 reference clears `0x60006040/44/4c[18]`. The offsets +0, +4 and +0xc match classic
b8/bc/c4. **This is an inferred correspondence**: the offsets and the shared `rom_stop_tx_tone`
shape agree, but nothing on our chip has shown that c4 is a TX tone.

### Other "tone" names checked (not TX NCOs as far as the code shows)
- `rom_spur_reg_write_one_tone` `0x400037f0`: reads ROM data tables (`0x3ff9667c…`) and writes
  `0x6001ccb0`. By name and register block it is RX spur cancellation. **Not traced further.**
- librftest `bt_tx_tone` → `fcc_bt_force_tx_tone` (`wifi.o`): it does not use the tone registers.
  It calls `set_chan_freq_sw_start`, then sets `0x600060a0[11:8] = 0xe` and `[17:16] = 3`, and
  clears them on stop. This is a carrier made by forcing TX on (no NCO). It resembles the S31's
  `0x20100890[11:8] = 0xe` "TX force on" (EXT), but that link is inferred.
- `rom_txtone_linear_pwr` and `ram_meas_tone_pwr_db` only measure (SAR/IQ-est reads).

## 4. Vendor CW (tone) path vs our keying

### Vendor: `esp_phy_wifi_tx_tone(en, ch, backoff)` → `wifiscwout` (`librftest rf_test.o` +0x34)
Enable (en ≠ 0):
1. `RFChannelSel(sext8(ch), 0)`.
2. `txcal_debuge_mode(0)` (libphy `phy_chip_v7_cal.o` +0xc), which runs the following through
   `g_phyFuns`:
   `[0xc0]` `ram_pbus_debugmode()` → `[0xac]` force_mode(1) = `0x600060a0[26:25] = 3`,
   `0x60006094[0] = 1`;
   `[0xd8]` `ram_pbus_xpd_tx_on(0<<8 | tx_rf_ana_gain[0], tx_rf_ana_gain[1])`;
   `[0x10c]` txbbgain_to_index; `[0xdc]` `rom_pbus_set_dco(&chip7_sleep_params[idx*8+12])`;
   `[0x3c]` `set_txclk_en(1)` = `0x600060a0[17:16] = 3`;
   `[0x11c]` `ram_en_pwdet()`.
3. gain = `max(sext8(backoff + 43 − REG(0x60006004)), 0)`, using `esp_dport_access_reg_read` of
   literal `0x3ff46004`.
4. `g_phyFuns[0x44]` = ROM `start_tx_tone_step(1, 0, gain, 0, 0, 0)`: f = 0, so the tone sits on
   the LO.

Disable (en = 0): `g_phyFuns[0x44](0,0,0,0,0,0)`, then `g_phyFuns[0x124]()`.

`ram_pbus_xpd_tx_on(a, b)` (libphy `phy_chip_v7_ana.o` +0x8) calls force_test with
(0,1,1), (1,1,124), `set_dco(table)`, (1,2,b), [if a bit 8: (1,1, rd(1,1)|2)], (4,1,127), (5,1,a).

ROM `rom_pbus_xpd_tx_on(a, b)` (`0x400045e0`) calls force_test with (0,1,1), (1,1,124), (1,2,b),
(4,1,127), (5,1,a). Compared with the RAM version it has **no DCO set and no bit-8 branch**.

`ram_txcal_work_mode` = stop_tx_tone(1), set_txclk_en(0), pbus_xpd_rx_on(0), pbus_workmode().
The ROM `rom_txcal_work_mode` does the same **and** clears `0x6000880c[19:18]`
(`4000513b l32r a8,(fff3ffff)`). ROM `rom_en_pwdet` sets those bits (`or 0xc0000`).
`0x6000880c` is `SENS_SAR_MEAS_WAIT2_REG` and `[19:18]` is `SENS_FORCE_XPD_SAR`
(`soc/esp32/register/soc/sens_reg.h:78,90`). That is SAR-ADC power for the power detector, not
the TX chain. `ram_en_pwdet` does not touch it. It clears `0x6000e05c` bits 23 and 21, clears
`0x6000e050[0]`, sets `0x600060c0[7]`, sets `0x6000e050[7:6]`, then calls `pwdet_sar2_init`.
With libphy's overrides in place, the key/unkey cycle never writes `0x6000880c` directly.

### Our firmware (`txeng.c` `key()` / `unkey()`)
| Step | Vendor `wifiscwout(1,…)` | txeng `K 0` | txeng `K 1` | txeng `K 2` |
|---|---|---|---|---|
| channel | `RFChannelSel` | `Q` cmd beforehand (separate path) | same | same |
| PBUS debug/force mode | yes (via txcal_debuge_mode) | yes | **no** | **no** |
| xpd_tx_on | RAM version, (1,2) = `tx_rf_ana_gain[1]` | same | **ROM** version `(pwr, 288)`, no DCO set | **no** |
| `0x600060a0[17:16]` txclk | 3 | 3 | **not set** | **not set** |
| en_pwdet | `ram_en_pwdet` | same | no | no |
| tone gain g | `backoff+43−REG(0x60006004)`, clamped ≥ 0 | **127** fixed (→ field `0x81`) | 127 | 127 |
| PBUS (5,1) | `tx_rf_ana_gain[0]` | overwritten with pwr after the tone | pwr | — |
| unkey | `[0x44](0…)` + `[0x124]` | same + `rom_stop_tx_tone(1)` + `rx_mode()` | same | same |

Our logs agree with this: pb01 = 1, pb11 = 124, pb12 = 288 and pb41 = 127 in the keyed `E,` lines
(`playback-check/*/esp.log`). That fits `ram_pbus_xpd_tx_on` with `tx_rf_ana_gain[1] = 288`.

**Hypothesis (not shown):** `K 1` produced no detectable CW (measured.md §5) because it never
forces PBUS debug mode and never enables the TX clock `[17:16]`. That would make the K 1 null a
consequence of keying, not of the engine. Checking it means keying RF, which needs the user's
approval. Nothing here asks for it.

## 5. DAC replay: source select, sample routing, playback control

- **Classic vendor code never touches the playback register.** Byte search: `0x60033d98` and
  `0x3ff73d98` are absent from all classic libraries and the ROM. Capture-side literals present:
  `0x60033d90` (librftest `mac_common.o:adctrig`, libbttestmode `bt_bb_dump`, `rw_rx_dump`),
  `0x60033dc4` (`mac_init` writes `0x03020100`, which esp-sdr copies), `0x60033dc0` (below).
- **TX dump memory helpers exist but nothing calls them.** In `librftest crypto_common.o`,
  `get_txdumpaddr(p, q)` stores `*p = 0x3ffe8000, *q = 12`, and `clear_txdumpmem()` loops `0x3fff`
  times writing `0x5aa55aa5` from `0x3ffe8000`, which is 16383 words, one short of 16384. Running
  `nm` on all esp32 libs shows no `U` reference to either. So the vendor calls our 64 KiB window
  "txdump" memory, which supports the window being TX sample memory. The meaning of `12` is
  unknown. The fill word `0x5aa55aa5` is the byte-rotated form of the `0xa55aa55a` that CPU reads
  of an RF-owned bank return; that may be a coincidence.
- **S3 comparison: `dactrig(count, rate, loop, …)`** in S3 `librftest mac_common.o` +0x44:
  ```
  0x60033d64 &= 0x7fffffff                      ; stop
  for i in 0..0xffff: *(u32*)(0x3fcd0000+i) = (i>>3)+0x100   ; test fill
  [13:0] = count ; bit15 = (rate != 1) ; bit19 = (loop != 0) ; [27:20] = count & 0xff
  |= 0x80000000 ; wait bit18 ; delay 10 ms ; 0x60033d5c = 0
  ```
  It does **not** call `rom_dac_rate_set`, set the bank owner, or touch tones. Those come from the
  caller or from other code. On the classic chip, our bit 15, 18, 19 and 31 semantics for
  `0x60033d98` were measured, not taken from a vendor routine. The `[27:20]` count duplicate and
  the bit 19 = loop reading are S3 vendor behaviour and still **unverified** on the classic chip.
- **Capture source select (classic, for contrast):** `adctrig(a2…a7)` builds
  `DUMP_CTRL = (len+1) | (a5?0:0x10000) | (a6&1)<<17 | a4<<20 | a3<<28`. It writes
  `&0x7fffffff`, then the value, then `|0x80000000`. In mode 1 it forces RX gain at
  `0x3ff5c02c[31:24]` with bit 23, pulses bit 19 if a3 = 0, waits for bit 18, and checks
  `0x60033d94[14:0] == len+1`. libbttestmode `bt_bb_dump` sets `MAC_DUMP_MODE |= 0x60`
  (`0x3ff000a8`), and **toggles `0x600110f4[0]` and `0x6001c0b8[0]` in opposite directions** to
  pick a BT or Wi-Fi capture source, with `[30:28] = 1`. This is a **capture-side** source mux.
  No TX-side equivalent appears in vendor code.
- `0x60033dc0` (our "candidate #2", no effect on the engine): its only vendor use is librftest
  `crypto_encap`, which writes `0x8000ffff`, then `0x80007fff`, then `tx_a_frame()`, then 0. That
  looks like MAC frame/crypto test plumbing, not DAC playback. This is consistent with the census
  null, but the role is name-level.
- `0x60033d00..d20` (writes hang the chip): librftest `mac_common.o` uses `d04/d0c/d14/d1c/d20`
  in `ConfAddrGet`, `Plcp0AddrGet`, `BackOffCountGet` and `fill_tx_frame`. This fits MAC TX
  descriptor/PLCP slots, which is the role measured.md guessed. Still name-level.

## 6. Rate / clock

- Classic: **no `rom_dac_rate_set`** (`esp32.rom.ld` and ROM `nm`). No classic binary writes
  `0x6000608c`. Classic code only loads it in ROM `rom_rxiq_get_mis` (`0x400058f2`) and in
  libphy/librftest `get_iq_est_snr*` and `get_corr_power`, as reads in IQ-estimate code.
- S3 `rom_dac_rate_set(r)` `0x40035eac`: `if i2c_readReg_Mask(102,0,4,1,1) == 0`, then
  `0x6000608c[27] = r&1`, `i2c_writeReg_Mask(102,0,4,4,4,r)`, `i2c_writeReg_Mask(103,0,2,4,4,r)`
  (S3 slots 0x194/0x198 resolved to `rom_i2c_readReg_Mask/writeReg_Mask`). Block 102 = `0x66` =
  `I2C_BBPLL`.
- A constant-argument scan of every classic `call8/callx8` site for `a10 ∈ {102,103}, a13 = a14 = 4`
  found nothing. Classic BBPLL uses hostid 4 (`regi2c_bbpll.h`), so a classic equivalent would
  look different. A null from this simple scan is weak evidence.
- `0x600060a0` clock fields, from ROM: `rom_set_txclk_en` → `[17:16]` (`0x30000`),
  `rom_set_rxclk_en` → `[15:14]` (`0xc000`). Also `rom_pbus_force_mode` → `[26:25]` (`0x6000000`),
  and `rom_pbus_force_test` busy-polls `0x600060a0` bit 31 (`bltz`) after writing
  row/col/value into `0x60006094` (`row<<2 | col<<15 | val<<6 | 2`).

### Block names (IDF headers, `soc/esp32/register/soc/reg_base.h`)
`0x3ff46000`/`0x60006000` = `DR_REG_FE_BASE` (tone, PBUS and force registers live here).
`0x3ff45000`/`0x60005000` = `DR_REG_FE2_BASE` (`0x600050a8` fine tone bits, `0x600050dc` TX IQ).
`0x3ff5d000` = BB, `0x3ff5cc00` = NRX, `0x3ff48800` = SENS. The one TX-chain field the IDF names
on the classic chip is `FE2_TX_INTERP_CTRL` = `0x600050f0`: bit 10 `FE2_TX_INF_FORCE_PU`, bit 9
`_PD` (`fe_reg.h`). `rtc_sleep.c:82` (esp32) sets PU = `~fe_pd`. libphy `tx_delay_cfg` writes
its `[8:0]` (240 or 100), paired with BB `0x6001d030[9:0]`, and ROM `rom_phy_freq_correct`
(`0x40004b64`, `0x40004c3f`) writes `[8:0]` too. The TX interpolator (the stage before the DAC,
by name) is therefore powered and timed by vendor code, but **no vendor code selects its input**.

## 7. TX force fields in `0x600060a0` (corroborates the source audit)

| Bits | Writer | Evidence |
|---|---|---|
| `[9:8]` | librftest `force_txon_en(1)` writes 2 (`and 0xfffffcff; or 0x200`), then rx/tx/pa_pbus_set; `force_txon_en(0)` clears it | `wifi.o` +0x45..0x69, +0xed..0xf6 |
| `[11:10]` | `force_txon_en(0)`: 3, 1 µs, 2, 1 µs, 0. libphy `phy_close_pa(1)`: 2, then clears `0x6000609c` bits 2 and 4 | `wifi.o` +0xa1..0xe3; `phy_chip_v7.o` +0x31..0x72 |
| `[11:8]` | `fcc_bt_force_tx_tone`: `0xe` on, 0 off | `wifi.o` +0x59..0xe8 |
| `[15:14]`, `[17:16]` | rx/tx clock enables | ROM `0x40003594`, `0x40003564` |
| `[26:25]` | PBUS force mode | ROM `0x40004270` |
| bit 31 | PBUS busy (read) | ROM `0x400043fe` |

The bit roles are written as the code uses them. "TX force" and "RX force" are names, not
demonstrated behaviour.

## 8. Safe checks vs risky writes

Split by whether anything is written. Each still needs a bench session.

Pure idle reads (no writes, no keying, PHY left as booted):
- Read `0x600060b8, bc, c0, c4, 0x600050a8, 0x600060a0, 0x6000880c, 0x6000608c, 0x60006004` at
  boot. `0x600060c4[18]` is the open item. The test only changes something if it reads 1.
  (Repeating the reads after `rx_mode()` is an unkeyed write experiment, see below.)
- Read `0x60006004` to compute the gain `wifiscwout` *would* have used, compared with our fixed 127.
- Read `0x600050f0` (`FE2_TX_INTERP_CTRL`: PU bit 10, PD bit 9) at idle, and again just before
  a run with the engine not keyed (the idle read is pure; reading with the engine running needs a
  `0x60033d98` write, so it is an unkeyed write experiment). If the TX interpolator is forced down in RX mode, a keyed
  playback through it could never reach the DAC.
- Read BBPLL I2C (`0x66`, hostid 4) registers 2..4 before and after setting `0x60033d98[15]`
  **without** setting run. The rate bit alone may or may not touch the analog side. This writes
  `0x60033d98`, so it is an unkeyed write experiment, not a pure read.

Unkeyed write experiments (expected no radiation, not proven; user say-so required): any read
taken after `rx_mode()` (it writes PHY state) and any read with the playback engine running or
`0x60033d98[15]` set (they require writing `0x60033d98`).

Risky (write → possible RF emission, PHY state change or hang). Do not do these without explicit
user approval. The `playback-cc2500-check` memory and measured.md §7 rules apply:
- Any `start_tx_tone_step`, `txcal_debuge_mode`, `force_txon_en`, `pbus_xpd_tx_on`,
  `set_txclk_en(1)`, or `0x600060a0[11:8]` write **keys or forces TX**.
- Clearing `0x600060c4[18]`: low risk in principle (it turns something off), but it is a write
  into FE state with unknown side effects. Read first. `0x6000880c[19:18]` is SAR force-power,
  not TX. Leave it alone.
- Writing `0x6000608c[27]` or BBPLL I2C bits, copying the S3 rate routine: **can retune the
  CPU/peripheral PLL**. Do not.
- `0x60033d00..d20` writes hang the chip (txeng refuses them). `0x60033dc0` is MAC crypto/frame
  plumbing per §5. Leave both alone.

## 9. What this does not settle

- Whether the engine reads sample memory and drives the DAC. No vendor code on the classic chip
  shows a TX source mux.
- The playback word format, the `[27:20]` duplicate, and bit 19 as loop on the classic chip
  (S3-only vendor evidence).
- The unit of tone frequency, and the role of b8 bit 29 and `0x600050a8` beyond the 2-bit split.
- The role of `get_txdumpaddr`'s second output (`12`).
