# SPDX-License-Identifier: GPL-3.0-or-later
import json

from esp32sdr import sdrpp_launch as S


def test_client_rate():
    assert S.client_rate(31250) == (250000, 8)
    assert S.client_rate(15625) == (250000, 16)
    assert S.client_rate(62500) == (250000, 4)


def test_write_config_backs_up_and_sets_keys(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"fftSize": 65536, "theme": "Dark"}))
    b = S.write_config(tmp_path, freq_hz=2480_000_000, host="127.0.0.1", port=1234,
                       rate=250000, decim=8, log=lambda m: None, stamp="t")
    assert json.loads((b / "config.json").read_text())["fftSize"] == 65536
    c = json.loads((tmp_path / "config.json").read_text())
    assert c["source"] == "RTL-TCP" and c["frequency"] == 2480e6 and c["decimation"] == 8
    assert c["theme"] == "Dark" and c["fftSize"] == 1024
    assert c["moduleInstances"]["Rigctl Server"]["enabled"]
    r = json.loads((tmp_path / "rtl_tcp_config.json").read_text())
    assert (r["host"], r["port"], r["sampleRate"]) == ("127.0.0.1", 1234, 250000.0)
    g = json.loads((tmp_path / "rigctl_server_config.json").read_text())["Rigctl Server"]
    assert g["autoStart"] and g["port"] == 4532
