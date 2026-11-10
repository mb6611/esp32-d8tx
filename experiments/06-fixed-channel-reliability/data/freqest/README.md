# Session 2 (freqest) bench driver
Receive-only rxdiag fw=9709091a bf=948ba63 quiet_us=2000 proto=5 (P has 9th field freqest). Owner approval is read from
`approval.json` (`approved_at`, written by the parent); the driver refuses without it. Cap: 5 batches / 50 PKT, 2412000 kHz,
power<=127, 0.5 s spacing; batch N>=2 needs batch N-1 complete with post STAT keyed=0. No retry, no replacement envelope.
All evidence is exclusive-create under this directory. Run from the repo root:

    D=bench/d8-tx/results/packet/freqest/session2_driver.py
    python3 $D e8                       # E8 on first; writes control_e8_pre.txt (must be <=3600 s old at each run)
    python3 $D envelope --batch N       # offline, one-use envelope
    python3 $D run --batch N            # E8 off; fresh source-off, gate, batch, post STAT once
    python3 $D classify --batch N       # offline report
    python3 $D e8 --post                # control_e8_post.txt (optional)
    python3 $D summary                  # per-batch + pooled counts, FREQEST/RSSI ESP vs E8, per-miss neighbours

Host gate (batch_gate.verify_controls / parse_control_log) already accepts proto 5 H and 9-field P (tested).
Tests: `python3 -m unittest discover -s bench/d8-tx/tests`.
