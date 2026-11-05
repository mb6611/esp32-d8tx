# SPDX-License-Identifier: GPL-3.0-or-later
"""SigMF recording (cf32_le) with esp32sdr: custom keys."""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import numpy as np

SIGMF_VERSION = "1.0.0"


def _paths(base):
    base = str(base)
    for suf in (".sigmf-data", ".sigmf-meta"):
        if base.endswith(suf):
            base = base[: -len(suf)]
    return Path(base + ".sigmf-data"), Path(base + ".sigmf-meta")


def _meta(fs, fc, bits, gain_mode, gain_index, fw_version, extra, count):
    glob = {
        "core:datatype": "cf32_le",
        "core:sample_rate": float(fs),
        "core:version": SIGMF_VERSION,
        "core:hw": "ESP32 DevKit V1 (esp-sdr firmware)",
        "core:sample_count": int(count),
        "esp32sdr:bits": int(bits),
        "esp32sdr:gain_mode": gain_mode,
        "esp32sdr:gain_index": gain_index,
        "esp32sdr:firmware": fw_version,
    }
    for k, v in (extra or {}).items():
        glob[k if ":" in k else f"esp32sdr:{k}"] = v
    return {
        "global": glob,
        "captures": [
            {
                "core:sample_start": 0,
                "core:frequency": float(fc),
                "core:datetime": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            }
        ],
        "annotations": [],
    }


def write(path_base, iq, *, fs, fc, bits, gain_mode, gain_index, fw_version, extra=None):
    """Write iq (complex64) and its metadata. Returns (data_path, meta_path)."""
    data, meta = _paths(path_base)
    iq = np.asarray(iq, dtype=np.complex64)
    data.parent.mkdir(parents=True, exist_ok=True)
    iq.astype("<c8").tofile(data)
    m = _meta(fs, fc, bits, gain_mode, gain_index, fw_version, extra, iq.size)
    meta.write_text(json.dumps(m, indent=2))
    return data, meta


class StreamWriter:
    """Append samples as they arrive; metadata is written on close/flush."""

    def __init__(self, path_base, *, fs, fc, bits, gain_mode, gain_index, fw_version, extra=None):
        self.data_path, self.meta_path = _paths(path_base)
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self._args = (fs, fc, bits, gain_mode, gain_index, fw_version, extra)
        self._f = open(self.data_path, "wb")
        self.count = 0
        self._ann: list[dict] = []
        self._meta = _meta(*self._args, 0)

    def append(self, iq):
        iq = np.asarray(iq, dtype=np.complex64)
        iq.astype("<c8").tofile(self._f)
        self.count += iq.size

    def mark_loss(self, lost_samples: int, comment: str = "samples lost"):
        """Record a loss at the current position (samples dropped before next append)."""
        self._ann.append(
            {
                "core:sample_start": self.count,
                "core:sample_count": 0,
                "core:label": "loss",
                "core:comment": comment,
                "esp32sdr:lost_samples": int(lost_samples),
            }
        )

    def flush(self):
        self._f.flush()
        self._meta["global"]["core:sample_count"] = self.count
        self._meta["annotations"] = list(self._ann)
        self.meta_path.write_text(json.dumps(self._meta, indent=2))

    def close(self):
        if not self._f.closed:
            self.flush()
            self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
