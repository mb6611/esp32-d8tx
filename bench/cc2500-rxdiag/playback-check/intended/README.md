# Intended-waveform check: pat156 (`F 1 16384 200 32`, nominal +156.25 kHz) vs zero vs unkey vs idle (2026-11-06)

**Result: no sample-dependent signal detected at either +/-156 kHz offset; inconclusive because neither offset had an in-slice positive control.**
Limits kept: ch1 2412, K 0, pwr 127/0, count 6143, tmo 100, abort >400 us, slots >=0.35 s. RX always `rxdiag events <khz> 100 203 203 66 1`.

- Offline (`fillcheck.py`/`fillcheck.txt`): firmware cmd_fill emulated; pat156 = I=200cos,Q=200sin, peak +156.25 kHz, 12 whole cycles in the 6144 played words,
  zero = all-zero words. Validates the *fill*, not what the hardware engine plays (10-bit I/Q @80 MS/s assumed; sign/order unverified).
- Preregistered (`prereg.py`, sha in `prereg.sha256`, checked OK; saved 2026-11-06T03:15Z, before keying).
- **Control (`ctrl/`, RX 2412.000):** PASS. tone 5/5 hits (peak 18-23 raw, dur 118-237 us); keyed zero 5/5 hits (peak -6..-3, i.e. LO leak/keying energy
  without the tone); unkey 0/5, idle 0/5. keyed_us 194-368.
- **P1 (`p1/`, RX 2412.156):** pat156 0/8, zero 0/8, unkey 0/8, idle 0/8. Fisher p=1, MWU p=1. NO-DIFF, valid, not saturated.
- **P2 (`p2/`, RX 2411.844):** same, all 0/8. NO-DIFF, valid.
- keyed_us over all sessions: max 368 (first keyed slot after boot), rest 194-206; no hang, no abort, pb51 127 on keyed slots, 0 before/after.

## Interpretation / limits
- The control only shows the detector sees keyed energy at the LO (2412.000), where the 203 kHz slice is centred. The offset slices were not
  controlled: at 2412.156/2411.844 even keyed zero (LO leakage at -/+156 kHz, just outside the +/-101 kHz passband) was invisible, so the detector
  is not shown to see anything at +/-156 kHz. Unkey and idle also being invisible at these offsets adds no information. A null there says only
  that nothing detectable (>~ its threshold) arrived, from either the intended line or leakage.
- Possible reasons for the null (not distinguished): engine not radiating samples; tone/NCO bit not the only gate (research lead: on S3, NCO left on after
  tone prep blocks IQ TX; here pat156 slots used T flag clr18 so bit 18 was cleared, but other gates unchecked); line level below CC2500 carrier-sense threshold
  at 203 kHz/agc2 203; crystal offset; passband edge; 77 us burst. Sample dependence was not shown and not excluded.
- An in-slice positive control for a +/-156 kHz line would need an independent source or a wideband receiver.

## Restore
ESP32: fresh pre-image (`esp_preimage.bin`, sha in `esp_preimage.sha256`; differs from the earlier inband pre-image only in a flash region near 0xB000, NVS)
written back and verified (`esp_restore_flash.log`, `esp_restore_verify.log`: digest matched); `esp32sdr info` identical before/after.
Tinyhawk: diag 4cd0deab flashed via DFU, stock 4.2.11 restored (`dfu_restore_stock.txt`), diff replayed (`restore_replay.log`); final capture differs from pre-flash
only in temp/Vref/uptime/CPU lines. Ports free (lsof empty).
