# Keyed-state read (2026-11-xx, one session, 2 bursts)
Firmware: [`tools/txeng`](../../../../tools/txeng/README.md) + `F_KREAD` (flag 128): read-only probes of b8/bc/c4/a0/50f0 after key(), after F_CLR18, immediately after RUN, at done, after unkey. No RF writes added.
Command: `T 0x97ff 1 100 140 3 {127,0}` (2412 MHz, count 6143, tmo 100 us, flags KEY|CLR18|KREAD), 0.5 s apart. Script `keyed_read.py`, raw `logs/run.txt`, `keyed_read.json`.

| phase | 0x600060b8 | 0x600060bc | 0x600060c4 | 0x600060a0 | 0x600050f0 |
|---|---|---|---|---|---|
| after key, pre-CLR18 | 20060400 | 0 | 0 | 4103c000 | 00000464 |
| after F_CLR18 | 20020400 | 0 | 0 | 4103c000 | 00000464 |
| immediately after RUN | 20020400 | 0 | 0 | 4103c000 | 00000464 |
| at done | 20020400 | 0 | 0 | 4103c000 | 00000464 |
| after unkey | 20000000 | 0 | 0 | 0100c000 | 00000464 |
Identical for PBUS 127 and 0 (50f0 same). Keyed 371 us (127), 162 us (0); engine done 19448/18512 cycles (~81/77 us). Bit18: b8 set after key, cleared by CLR18 and stays clear immediately after RUN and at done; bc/c4 bit18 never set.
`0x600060a0` reads `4103c000` after key, after CLR18, immediately after RUN and at done, then `0100c000` after unkey. The low 16 bits (`c000`) never change; only the upper bits (`4103` vs `0100`) change, at unkey. Not stated: the meaning of those upper bits.
Scope: one session, two slots only, K0, ch1 (2412 MHz), count 6143. Nothing here covers other key modes, channels or counts, and it does not show the RF DAC is wired to the engine. Independent check: the K lines of `logs/run.txt` were re-read separately and match the table (the "mid" timing is the S,mid sample, taken immediately after RUN, not later in the run).
Caveat: reads add ~25 register reads (<~3 us) inside the burst; pbus 127 burst 371 us is under the 400 us abort but longer than 0's 162 us (existing key-path variance).
