# SPDX-License-Identifier: GPL-3.0-or-later
import json

import numpy as np

from esp32sdr import sigmf

KW = dict(fs=16e6, fc=2.44e9, bits=8, gain_mode="hardware", gain_index=None, fw_version="test")


def test_write(tmp_path):
    iq = (np.arange(100) + 1j * np.arange(100)).astype(np.complex64)
    d, m = sigmf.write(tmp_path / "cap", iq, **KW)
    assert d.name == "cap.sigmf-data" and d.stat().st_size == 800
    assert np.array_equal(np.fromfile(d, dtype="<c8"), iq)
    meta = json.loads(m.read_text())
    g = meta["global"]
    for k in ("core:datatype", "core:sample_rate", "core:version", "core:hw", "core:sample_count"):
        assert k in g
    assert g["core:datatype"] == "cf32_le" and g["core:sample_count"] == 100
    assert g["core:sample_rate"] == 16e6 and g["esp32sdr:bits"] == 8
    assert meta["captures"][0]["core:frequency"] == 2.44e9
    assert meta["captures"][0]["core:sample_start"] == 0


def test_stream_writer_loss(tmp_path):
    a = np.ones(10, np.complex64)
    with sigmf.StreamWriter(tmp_path / "s", **KW) as w:
        w.append(a)
        w.mark_loss(500)
        w.append(a)
    meta = json.loads(w.meta_path.read_text())
    assert meta["global"]["core:sample_count"] == 20
    assert meta["annotations"][0]["core:sample_start"] == 10
    assert meta["annotations"][0]["esp32sdr:lost_samples"] == 500
    assert w.data_path.stat().st_size == 160
