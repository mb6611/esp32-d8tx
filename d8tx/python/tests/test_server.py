import time

from fastapi.testclient import TestClient

from d8tx.server import create_app


class FakeEsp:
    def __init__(self):
        self.link = False
        self.sticks = None
        self.start_args = None
        self.stops = 0

    def info(self): return {"proto": 1}
    def status(self): return {"link": self.link, "keyed": self.link, "slots": 3}
    def start(self, power=127, timeout_ms=300, allow_arm=False, fofs_hz=None, telemetry=True):
        self.start_args = (power, timeout_ms, allow_arm, fofs_hz, telemetry)
        self.link = True
    def stop(self):
        self.stops += 1
        self.link = False
    def set_sticks(self, ch): self.sticks = ch


class FakeFc:
    def rc(self): return [1500] * 8
    def rssi(self): return 90
    def attitude(self): return [1.5, -2.0, 90.0]
    def motors(self): return [1000, 1100, 1200, 1300]
    def status(self): return {"armed": False, "failsafe": False, "arming_disable": ["RXLOSS"]}


def test_status_and_link(tmp_path):
    esp = FakeEsp()
    with TestClient(create_app(esp, FakeFc(), tmp_path / "none")) as c:
        s = c.get("/api/status").json()
        assert s["esp"]["connected"] and s["esp"]["info"] == {"proto": 1}
        assert s["fc"]["rc"] == [1500] * 8 and s["fc"]["rssi"] == 90
        assert s["fc"]["attitude_deg"] == [1.5, -2.0, 90.0]
        assert c.post("/api/link/start", json={"power": 50, "allow_arm": True}).json()["ok"]
        assert esp.start_args == (50, 300, True, None, True)
        c.post("/api/link/stop")
        assert not esp.link


def test_no_fc(tmp_path):
    with TestClient(create_app(FakeEsp(), None, tmp_path / "none")) as c:
        fc = c.get("/api/status").json()["fc"]
        assert fc["connected"] is False and fc["error"] is None and fc["rc"] == []


def test_ws_and_watchdog(tmp_path):
    esp = FakeEsp()
    with TestClient(create_app(esp, None, tmp_path / "none")) as c:
        c.post("/api/link/start", json={})
        with c.websocket_connect("/api/ws") as w:
            w.send_json({"type": "sticks", "ch": [1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000]})
            t = w.receive_json()
            assert t["type"] == "telemetry" and "esp" in t
            w.send_json({"type": "sticks", "ch": [1]})  # invalid ignored
            w.send_json({"type": "sticks", "ch": [1000, 1500, 1500, 1500, 1000, 1000, 1000, 1000]})
            time.sleep(0.05)
            assert esp.sticks[0] == 1000 and esp.link
            time.sleep(0.6)  # silence
            assert not esp.link


def test_info_not_called_while_linked_and_fc_keys(tmp_path):
    esp = FakeEsp()
    calls = []
    orig = esp.info
    esp.info = lambda: (calls.append(esp.link), orig())[1]
    with TestClient(create_app(esp, None, tmp_path / "none")) as c:
        c.post("/api/link/start", json={})
        for _ in range(3):
            s = c.get("/api/status").json()
        assert s["esp"]["info"] == {"proto": 1}
        assert calls == [False]
        assert set(s["fc"]) >= {"connected", "rc", "armed", "failsafe", "arming_disable", "rssi", "error", "motors"}


def test_fc_slow_does_not_block_status(tmp_path):
    class Slow(FakeFc):
        def rc(self):
            time.sleep(0.5)
            return [1500] * 8
    with TestClient(create_app(FakeEsp(), Slow(), tmp_path / "none")) as c:
        t = time.monotonic()
        s = c.get("/api/status").json()
        assert time.monotonic() - t < 0.3
        assert s["fc"]["connected"] is False and s["fc"]["rc"] == []


def test_fc_reconnects_after_error(tmp_path):
    class Dying(FakeFc):
        closed = False
        def rc(self): raise OSError("unplugged")
        def close(self): self.closed = True
    made = []

    def factory():
        if len(made) == 0:
            made.append(Dying())
        elif len(made) == 1:
            made.append(None)
            raise OSError("no port")
        else:
            made.append(FakeFc())
            return made[-1]
        return made[-1]
    with TestClient(create_app(FakeEsp(), None, tmp_path / "none", fc_factory=factory, fc_retry_s=0.1)) as c:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            fc = c.get("/api/status").json()["fc"]
            if fc["connected"]:
                break
            time.sleep(0.05)
        assert fc["connected"] and fc["rc"] == [1500] * 8
        assert made[0].closed and len(made) == 3


class RadioEsp(FakeEsp):
    def telemetry(self): return {"enabled": True, "powered": True, "link": True, "armed": True, "vbat_v": 4.1}


class BrokenRadioEsp(FakeEsp):
    def telemetry(self): raise RuntimeError("boom")


def test_radio_defaults_when_esp_lacks_telemetry(tmp_path):
    with TestClient(create_app(FakeEsp(), None, tmp_path / "none")) as c:
        r = c.get("/api/status").json()["radio"]
        assert r["enabled"] is False and r["armed"] is None and r["hub"]["raw"] == {}
        assert r["fast"] is None
        with c.websocket_connect("/api/ws") as ws:
            assert ws.receive_json()["radio"]["powered"] is False


def test_radio_passthrough_and_error_fallback(tmp_path):
    with TestClient(create_app(RadioEsp(), None, tmp_path / "none")) as c:
        r = c.get("/api/status").json()["radio"]
        assert r["armed"] is True and r["vbat_v"] == 4.1 and "catch_rate" in r
        with c.websocket_connect("/api/ws") as ws:
            assert ws.receive_json()["radio"]["link"] is True
    with TestClient(create_app(BrokenRadioEsp(), None, tmp_path / "none")) as c:
        assert c.get("/api/status").json()["radio"]["enabled"] is False


def test_start_telemetry_flag(tmp_path):
    esp = FakeEsp()
    with TestClient(create_app(esp, None, tmp_path / "none")) as c:
        c.post("/api/link/start", json={"telemetry": False})
        assert esp.start_args[4] is False
