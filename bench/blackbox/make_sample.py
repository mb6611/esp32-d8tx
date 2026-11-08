#!/usr/bin/env python3
"""Write the deterministic synthetic test capture tests/data/sample_capture.raw.

It imitates what bbcapture.py records from the shared VCP: MSP replies (the pre-arm MSP_ANALOG check), then
log 1 (arm..disarm, 600 frames), an MSP_STATUS reply after disarm, log 2 (400 frames), trailing MSP. Logs are encoded with bbl.Writer, which reproduces
Betaflight 4.2's field table, predictors and encoders. No public BF 4.2 sample is vendored: this one is
generated, so its sha256 is pinned in tests/test_blackbox.py instead of a download URL.
"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bbl  # noqa: E402


def msp_reply(cmd, payload):
    body = bytes([len(payload), cmd]) + payload
    return b"$M>" + body + bytes([bbl.msp_checksum(body)])


def build():
    analog = msp_reply(110, struct.pack("<BHHhH", 0, 0, 0, 0, 3))     # vbat 0.03 V on USB
    status = msp_reply(101, bytes(22))
    log1, _, _ = bbl.synth_session(600, t0_us=5_000_000, seed=1)
    log2, _, _ = bbl.synth_session(400, t0_us=42_000_000, seed=2)
    return analog + b"\x00\x00" + log1 + status + b"\r\n" + log2 + status


def main():
    out = os.path.join(HERE, "tests", "data", "sample_capture.raw")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    data = build()
    with open(out, "wb") as f:
        f.write(data)
    import hashlib
    print(out, len(data), hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
