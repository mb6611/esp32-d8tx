---
name: playback-cc2500-check
description: Read before re-testing whether the classic ESP32 stage2 playback engine radiates, or keying it with the CC2500 rxdiag detector; Nov 2026 result and pitfalls.
load: description
---
As of 2026-11-05 (experiments/01-playback-engine-check/data/README.md): with txeng `K 0`, PBUS 127, the CC2500 events
detector at 2412 sees every keyed burst. **Keyed RF detected; sample-dependent RF not established either way.**
Pattern, DC and zero samples gave similar energy (medians within ~1 raw step, n=20, no CI/p-value, so no hard bound).
The test was weak: pattern A's line (±1.25 MHz) was outside the detector's ±406 kHz slice (no in-slice pattern test);
DC +200 may cancel as LO leakage; playback sample format unverified. `K 1` untestable (even the tone not seen).
Tone detections sometimes outlast keyed_us (up to 661 µs vs 322) or split into extra bursts; source unresolved.

In-band follow-up 2026-11-06 (`playback-check/inband/README.md`): CC2500 at 2413.25 MHz/203 kHz, count 6143, 5 slots each
pat/zero/unkey/idle: 0 bursts in any condition, even keyed zero, so it is NO-DIFF and inconclusive (no in-slice positive control).
A rerun needs an in-slice positive control first; the user said do not re-key without approval.

Pitfalls: three keyed bursts exceeded the 444 µs bench rule (483, 445 and 448: each the first keyed slot of its session);
the second session continued after the 483 µs one was known. Use a shorter engine count or budget and stop on any
overrun; raise it with the user before more keying. keyed_us = key()/unkey() overhead + engine poll (poll hard-capped by
the T tmo, overhead is not): K 0 overhead 117–130 µs, first key after boot 243–291 µs. `guard.py`/`test_guard.py` in
playback-check hold the count/tmo preflight and per-slot abort (verify they still exist). A zero-sample keyed control is required; "burst detected" alone is
not evidence of playback. One unexplained ESP reboot (reason 7) is not in any log. `tight_window.py` reproduces the
README stats (duration = per-slot max; peak = all bursts). ESP restore re-flashed the esp-sdr build; the original ESP
image was never read back.

Intended-waveform check 2026-11-06 (`playback-check/intended/README.md`): pat156 (`F 1 16384 200 32`) vs zero at RX 2412.156 and 2411.844 (203 kHz): all 0/8,
NO-DIFF. In-session control at 2412.000 passed (keyed tone 5/5, keyed zero 5/5), but keyed zero at +/-156 kHz offsets is invisible, so no in-slice control there;
the detector is not shown to see a +/-156 kHz line. Sample dependence neither shown nor excluded.
