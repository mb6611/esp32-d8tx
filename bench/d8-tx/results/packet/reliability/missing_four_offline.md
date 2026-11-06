# Offline look at the four unobserved sends (batches 3 #0, 6 #5/#6, 9 #2) — PRIVATE

Read-only analysis of the existing raw logs (`batchN_stm.txt`, `batchN_esp_out/*`, `batchN_anchor.json`,
`batchN_report.txt`, `pre_/post_batchN_esp.txt`). No hardware, port, RF, flash or commit was used. Nothing
in this file changes any class in the reports; "unobserved" stays unobserved.

## Method

1. **Receiver record semantics** (`bench/cc2500-rxdiag/.../rxdiag_core.c`, `doPkt`): `P,seq,t_us,...` where
   `t_us` = device time the first FIFO byte was seen (≈ length byte, i.e. just after sync); packet is read
   after RXBYTES is unchanged for `quiet_us=2000`. Data rate from MDMCFG4/3 = 0xAA/0x39 → 31,044 baud,
   257.7 µs/byte. `PKTLEN=0x19`: a false sync whose random length byte is > 25 is discarded in the packet
   engine *before* the FIFO (CC2500/CC1101 datasheet §"maximum length filtering": "discarded and receive
   mode restarted"), so such events leave **no record**. All recorded noise lengths are ≤ 25 (consistent).
2. **Conservative device-time window per attempt** (same bounds the classifier uses): host T0 of device
   `t0_us` ∈ [`lo`,`hi`] from the report `clock=` line (lo = pre-write anchor, hi from X); attempt host
   window [t_send−0.020, t_send+0.050]; device rate ∈ [1−0.003, 1+0.003]:
   `dev_lo = (t_send−0.020−hi)·(1−0.003)·1e6 + t0`, `dev_hi = (t_send+0.050−lo)·(1+0.003)·1e6 + t0`.
3. **Empirical prediction** (tighter, for proximity only): least-squares fit `tFirst_us = A + R·(t_send−anchor)`
   over the batch's 8–9 matched attempts. Residuals are ≤ 91 µs in all three batches, and the fitted device/host
   rate is 1.00175–1.00177 in every batch (well inside ±0.3 %), so the expected `tFirst` of a missing send is
   known to ~0.1 ms *if the ESP behaved as on the observed sends*. The ESP packet is on air for ~6.7 ms
   (`on_us=6700`; 26 bytes = 4 preamble + 2 sync + 1 len + 17 payload + 2 CRC).
4. Noise proximity: for every P record within the conservative window (and ±0.6 s of the prediction), the
   offset of its `t_us` from the prediction and the time its over-the-air body ends (`t_us + (plen+2)·257.7 µs`).

## Table

| batch/attempt | host `t_send` | cmd→K (ms) | conservative device window (µs, width) | fit-predicted `tFirst` (µs) | nearest matched neighbours (device) | P records inside conservative window | noise/CRC-invalid near prediction |
|---|---|---|---|---|---|---|---|
| 3 / #0 (first send) | 1793994859.435159 | 10.96 | [1505596050, 1505710359] (114.3 ms) | 1505655691 ±60 | next: seq3 at +517.0 ms (attempt #1) | seq0 noise len10 plen9 RSSI −76 LQI127 crc0 at **−54.3 ms** (body ended −51.4 ms); seq1 noise len5 plen4 RSSI −70 LQI127 crc0 at **+41.4 ms** (body ended +43.0 ms) | none within ±41 ms; nothing overlaps the 6.7 ms on-air span |
| 6 / #5 | 1793995369.618482 | 10.77 | [2016658600, 2016780366] (121.8 ms) | 2016726571 ±84 | prev: seq6 at −512.9 ms (#4); next: seq7 at +1033.9 ms (#7) | **none** | nearest noise: seq2 at −2.13 s, seq10 at +2.09 s |
| 6 / #6 | 1793995370.134025 | 11.27 | [2017172596, 2017297456] (124.9 ms) | 2017243024 ±84 | prev: seq6 at −1029.4 ms (#4); next: seq7 at +517.4 ms (#7) | **none** | nearest noise: seq2 at −2.65 s, seq10 at +1.57 s |
| 9 / #2 | 1793995432.613845 | 10.79 | [2079747922, 2079888363] (140.4 ms) | 2079831851 ±91 | prev: seq2 at −516.9 ms (#1); next: seq3 at +516.8 ms (#3) | **none** | nearest noise: seq0 at −1.47 s, seq5 at +1.41 s |

Supporting facts from the same logs:

- Matched-packet spacing around the gaps is an exact multiple of the send cadence: batch 6 seq6→seq7 =
  1546.8 ms ≈ 3 × 515.6 ms (two consecutive misses), batch 9 seq2→seq3 = 1033.7 ms ≈ 2 × 516.9 ms. Host
  `t_send` spacing is 512–517 ms everywhere, so the host did not skip, double or delay a command.
- Receiver errors: no `E` record (no EPART, no EOVF) in batches 3, 6, 9; `X,…,done` present; `unparsed_lines=2`
  are the `#` header lines. Post-batch ESP `STAT` is `keyed=0,b8=20000000,a8=00000000` in all three (and pre).
- Noise load during these runs is tiny: 7/8/9 recorded noise fragments in 11 s, total recorded on-air
  busy fraction 0.20 % / 0.31 % / 0.33 % (batches 3/6/9). Allowing ~9× more *unrecorded* length-filtered
  false syncs (26/256 of random length bytes are ≤ 25), each blind for ≲ 1 ms, the receiver is blind to a
  sync at most ~0.5–1 % of the time. Signal margin is large: matched packets RSSI raw +35/+36 (batches 1b–3)
  and +23…+26 (batches 4–10), i.e. ≈ −54 to −60 dBm estimated, versus noise fragments at −64…−77 raw
  (≈ −104…−110 dBm). LQI is 51 for every matched packet in every batch.
- Pooled: 5 unobserved in 90 attributable attempts (4 in the 80 of batches 3–10). If the only loss mechanism
  were a receiver blind window of 1 %, P(≥4 of 80) ≈ 0.009 and P(≥5 of 90) ≈ 0.002.
- ESP `K` replies for the four attempts (`bits=208, pwr=127, on_us=6700, key_cycles=5211/5214, unkey_cycles
  4485–5433, max_late_ns=1266, late_bits=207`) and their cmd→K latency (10.8–11.3 ms) are indistinguishable from
  the observed sends in the same batches. Per the task rule this is **not** used to infer anything about RF.
- Unrelated but notable: matched RSSI stepped from ~+35 (batches 1b–3, ≤14:54) to ~+25 (batches 4–10, ≥15:01),
  a ≈5 dB change in the physical setup between batch 3 and 4. Losses occurred at both levels, so it does not
  explain the four.

## Hypotheses, ranked by what the logs support

1. **Receiver busy with a recorded noise packet at the ESP's sync instant — not supported.** For all four
   sends the nearest recorded fragment ends ≥ 41 ms away from the predicted sync (batch 3 #0) or > 1.4 s away
   (the other three), while the whole ESP packet lasts 6.7 ms and the prediction is good to ~0.1 ms.
2. **Receiver busy with an unrecorded (length-filtered) false sync — cannot be excluded per event, but
   unlikely as the main cause.** Such events are invisible in `rxdiag pkt`, yet their rate implied by the
   recorded ones gives ≲ 1 % blind time, which under-predicts 4–5 losses in 80–90 attempts (see binomial above).
   Checking this needs a receiver record of sync-detect events (e.g. GDO0 sync/length-discard transitions, or
   counting all false syncs) — a receiver-side diagnostic, no RF needed beyond what is already approved.
3. **Send-side variability at packet start (preamble/sync not decodable at the receiver) — consistent with
   the evidence but not demonstrated.** With 0 CRC-invalid matching records in 93 receptions the payload bit
   error rate is very low, so the loss mechanism must take out the sync acquisition itself (16/16 sync bits
   required, 4-byte preamble, no carrier-sense gating). The earlier tone findings (`d8-tx-findings`: carrier
   lands ±~10 kHz differently per keying, cause unresolved) name a candidate: a keying whose carrier offset
   or settling at the first bits exceeds what the receiver's FOC (limit ±BW/4 ≈ ±34 kHz at bw 135 kHz) and bit
   sync tolerate. Nothing in these logs measures the per-keying frequency, so this remains a hypothesis;
   it is testable offline-free only with a receiver that logs FREQEST/RSSI per packet, or an SDR capture of
   the ESP keyings side-by-side with `rxdiag pkt`.
4. **"Startup" (first send after idle) — not a general pattern.** Only batch 3 lost #0; batches 4–10 all received
   #0, and the batch 6/9 losses are mid-run (#5+#6 consecutive, #2). 1 of 9 first sends vs 4 of 81 later sends.
5. **Host/driver timing, receiver overflow, receiver stall — not supported.** Regular cadence, no E records,
   no STAT anomaly, FIFO never overflowed; the 2 ms quiet wait does not stop the chip receiving.

## Unresolved

- The cause of the four misses is not identified from the logs; they look like clean "no sync detected" events
  with no receiver-side or host-side correlate. Distinguishing hypothesis 2 (invisible receiver blind window)
  from hypothesis 3 (send-side sync quality) needs new evidence: a receiver that records every sync detect /
  length discard, and/or per-packet FREQEST / RSSI-at-sync, run against both the E8 (receiver-loss baseline)
  and the ESP. Not requested here; needs an owner decision.
- The batch 6 double miss (#5, #6 consecutive, 516 ms apart) is the one event where a transient lasting ~1 s on
  either side would fit; nothing in the logs shows such a transient (no noise, no errors, neighbours' RSSI 24–26).

## Reproduce (repo root, offline)

```python
# python3 - <<'EOF'   (run from bench/d8-tx/results/packet/reliability)
import json,re
BODY="1142B2000001CACACACA8888CACACACA8888"; BYTE=257.7; TOL=0.003
for n,missing in ((3,[0]),(6,[5,6]),(9,[2])):
    ps=[]; t0=None; X=None; H=None
    for l in open(f"batch{n}_stm.txt"):
        m=re.match(r"(\d+\.\d+) P,(\d+),(\d+),(\d+),([0-9A-F]*),(-?\d+),(\d+),(\d)",l.strip())
        if m: ps.append(dict(seq=int(m[2]),t=int(m[3]),len=int(m[4]),hex=m[5],rssi=int(m[6]),lqi=int(m[7]),crc=int(m[8])))
        m=re.search(r"^(\d+\.\d+) H,.*t0_us=(\d+)",l)
        if m: H=float(m[1]); t0=int(m[2])
        m=re.match(r"(\d+\.\d+) X,\d+,(\d+)",l)
        if m: X=(float(m[1]),int(m[2]))
    att=json.load(open(f"batch{n}_esp_out/attempts.json"))["attempts"]
    anc=json.load(open(f"batch{n}_anchor.json"))["start_cmd_host"]
    lo=anc; hi=min(H, X[0]-(X[1]-t0)/1e6*(1-TOL))          # clock_window(), slack 0
    mt=[p for p in ps if p["hex"]==BODY and p["crc"]==1]
    pairs=[(a["t_send"]-anc, min(mt,key=lambda r:abs(anc+(r["t"]-t0)/1e6-a["t_send"]))["t"]) for a in att if a["i"] not in missing]
    xs,ys=zip(*pairs); mx=sum(xs)/len(xs); my=sum(ys)/len(ys)
    R=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/sum((x-mx)**2 for x in xs); A=my-R*mx
    print(f"batch{n} rate={R/1e6:.6f} max|res|={max(abs(y-(A+R*x)) for x,y in pairs):.0f}us")
    for i in missing:
        ts=att[i]["t_send"]; dlo=(ts-0.02-hi)*(1-TOL)*1e6+t0; dhi=(ts+0.05-lo)*(1+TOL)*1e6+t0; pred=A+R*(ts-anc)
        print(f"  #{i} window=[{dlo:.0f},{dhi:.0f}] pred={pred:.0f}")
        for p in ps:
            if dlo<=p["t"]<=dhi or abs(p["t"]-pred)<600000:
                plen=int(p["hex"][:2],16)
                print(f"    seq{p['seq']} {'MATCH' if p['hex']==BODY else 'noise'} dt={(p['t']-pred)/1e3:+.1f}ms end={(p['t']+(plen+2)*BYTE-pred)/1e3:+.1f}ms len={p['len']} rssi={p['rssi']} lqi={p['lqi']} crc={p['crc']}")
# EOF
```
(The `hi` here is rebuilt from the raw H/X host stamps without the classifier's 10 ms slack, so the printed
window edges differ from the table's report-derived ones by up to ~20 ms; the proximity conclusions do not change.
The table's windows use the `clock={... 'lo','hi' ...}` values printed in `batchN_report.txt`.)
