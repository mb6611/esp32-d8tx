# B1a idle register read (classic ESP32, 2026-11)

Method: flashed existing `auto-drone/stage2/txeng` (unchanged binary), reset via RTS, sent only
`R <addr>` lines (source: plain `REG_READ`, refuses `0x60033d00..23`). No K/T/M/Y/W/Q, no rx_mode,
no playback, no writes. Two passes identical. Script `idle_read.py`, log `logs/idle_read.log`.
State = txeng after its PHY bring-up (wifi started, promiscuous, never keyed). Console 921600.
User waived backups: `preimage-a.bin` (4 MB, sha256 1144890d…430e, taken before the waiver, prior
firmware) is kept only as a convenience, unverified by readback; txeng is left flashed.

| Register | Value | Decode |
|---|---|---|
| `0x600060b8` tone1 | `0x2003a020` | bit29 set (fine mode), **bit18 (enable) clear**; bits 17,16,15,13,5 set (`[17:10]`=0xe8 field, not a keyed gain 0x81) |
| `0x600060bc` tone2 | `0x00000000` | enable clear |
| `0x600060c4` tone3 | `0x00000000` | enable clear |
| `0x600060a0` | `0x0100c000` | `[15:14]`=3 RX clk en; `[17:16]`=0 TX clk en clear; `[26:25]`=0; `[11:8]`=0 no TX force; bit24 set (unmapped); bit31 busy clear |
| `0x600050f0` FE2 interp | `0x00000464` | bit10 FORCE_PU **set**, bit9 PD clear, `[8:0]`=0x64 (100, the tx_delay_cfg value) |
| `0x600050a8` | `0x00000000` | fine tone bits 0 |
| `0x600050dc` | `0xd95e1f43` | unmapped/named only |
| `0x60006004` | `0x02081018` | |
| `0x60006000` | `0x01bb8040` | role unverified |
| `0x6000608c` | `0x00000000` | |

Enable bits set: none of the three NCO enables (bit18). Bits set in the idle state: b8 bit29, `a0[15:14]`, `50f0` bit10.
Consequence: at idle c4 (and bc) read 0, so no stuck NCO enable at boot; this removes "c4 set at boot"
as a blocker explanation. It says nothing about keyed state: keying rewrites b8/bc, a0 and PBUS, and
this idle-only session did not measure their keyed state. A later, separate keyed read (`../keyed-read/README.md`)
found c4=0 and `50f0=0x464` in its two tested bursts. Those results do not cover other modes or channels.
