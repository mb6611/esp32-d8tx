# Control feasibility review (no keying performed)
Prior evidence: README.md (2412/812 kHz: keyed RF seen, sample dependence untested; pattern line +-1.25 MHz outside slice)
and inband/README.md (2413.25/203 kHz: 0 bursts in every condition incl. keyed zero => no in-slice control).
No same-settings (2413.25 MHz, 203 kHz, agc2 203) positive control exists: the only known radiator is the ESP tone/LO leak
at 2412 (offset 0, outside the slice), BLE adverts are 2402/2426/2480 only. Any sample-dependent line is at an unverified sign,
I/Q order, and crystal offset. A null would again be uninterpretable, so no RF was keyed; ports/images untouched.
Next instrument needed: an independent known source (second ESP/CC2500 TX or SDR) at 2413.25 MHz in the same slice, or an SDR/spectrum
receiver wide enough to see +-1.25 MHz lines; or user approval to retune TX so a known tone lands in-slice.
