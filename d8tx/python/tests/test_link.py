import time

import pytest
from d8tx import D8Link, D8Error


def test_info_stat_fofs(port):
    l = D8Link("x", serial_obj=port)
    assert l.info()["proto"] == 1
    assert l.stat()["keyed"] == 0
    l.set_fofs(-1000)
    with pytest.raises(D8Error) as e:
        l.set_fofs(300000)
    assert e.value.code == "range"
    l.close()


def test_link_pacing_events_stop(port):
    l = D8Link("x", serial_obj=port)
    evs = []
    l.on_event(evs.append)
    l.start(power=100, timeout_ms=300, allow_arm=True, fofs_hz=500)
    assert "ARMOK" in port.lines and "LINK 100 300" in port.lines and "FOFS 500" in port.lines
    l.set_sticks([1100, 1500, 1500, 1500, 1500, 1500, 2000, 1500])
    time.sleep(0.8)
    st = l.status()
    assert st["link"] == 1 and st["keyed"] == 1
    assert 100 <= st["sender_hz"] <= 115, st
    armed = [x for x in port.lines if x.startswith("S ") and " 2000 1500" in x]
    # arm-edge guard: first ~0.5 s of the arm edge sends throttle 1000, then the requested 1100
    assert armed[0].startswith("S 1000") and any(x.startswith("S 1100") for x in armed)
    n_hold = next(i for i, x in enumerate(armed) if x.startswith("S 1100"))
    assert 45 <= n_hold <= 60, n_hold
    l.stop()
    assert l.status()["link"] == 0
    assert any(e["name"] == "link_end" for e in evs)
    n = len(port.t_sticks)
    time.sleep(0.05)
    assert len(port.t_sticks) == n
    l.close()


def test_arm_forced_low_without_allow(port):
    l = D8Link("x", serial_obj=port)
    l.start()
    l.set_sticks([1500] * 8)
    time.sleep(0.1)
    l.stop()
    assert "ARMOK" not in port.lines
    assert all(x.split()[7] == "1000" for x in port.lines if x.startswith("S "))
    l.close()


def test_link_end_event_clears_link(port):
    l = D8Link("x", serial_obj=port)
    l.start()
    port._emit("EV link_end why=timeout slots=9 late_max_us=1 retune_max_us=1")
    time.sleep(0.1)
    assert l.status()["link"] == 0 and l.status()["slots"] == 9
    l.close()


def test_start_link_fail_sends_stop_and_resets(port):
    l = D8Link("x", serial_obj=port)
    l.start()
    time.sleep(0.05)
    l.stop()
    port.armok = False
    orig = port._cmd
    def cmd(ln):
        if ln.startswith("LINK"):
            port._emit("ERR range power")
        else:
            orig(ln)
    port._cmd = cmd
    with pytest.raises(D8Error):
        l.start(allow_arm=True)
    assert port.lines[-1] == "STOP"
    st = l.status()
    assert st["sender_hz"] == 0 and st["last_event"] is None and st["allow_arm"] == 0
    l.close()


def test_link_end_clears_keyed_and_no_stray_ok(port):
    l = D8Link("x", serial_obj=port)
    l.start(allow_arm=True)
    assert l.status()["allow_arm"] == 1
    time.sleep(0.05)
    port.linked = False
    port._emit("EV link_end why=timeout slots=2 late_max_us=1 retune_max_us=0")
    time.sleep(0.05)
    assert l.status()["keyed"] == 0
    # stray OKs from idle S must not satisfy a request
    for _ in range(3):
        assert l.info()["proto"] == 1
        assert l.stat()["keyed"] == 0
    l.close()

