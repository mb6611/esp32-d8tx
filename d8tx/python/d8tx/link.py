"""D8Link: protocol v1 UART client with a paced stick sender thread."""
import queue
import threading
import time

ARM_THROTTLE_HOLD_S = 0.5

from .protocol import (ARM_CH, check_line, LO, MID, SLOT_S, ProtocolError, fmt_sticks, parse_line)

SPIN_S = 0.001


class D8Error(ProtocolError):
    pass


class D8Link:
    def __init__(self, port, baud=921600, serial_obj=None, reply_timeout=1.0,
                 clock=time.perf_counter, sleep=time.sleep):
        if serial_obj is None:
            import serial
            serial_obj = serial.Serial(port, baud, timeout=0.02, write_timeout=0)
        self._p = serial_obj
        self._clock, self._sleep = clock, sleep
        self._reply_timeout = reply_timeout
        self._req_lock = threading.Lock()
        self._state = threading.Lock()
        self._replies = queue.Queue()
        self._cbs = []
        self._ch = [LO, MID, MID, MID, MID, MID, LO, MID]
        self._allow_arm = False
        self._linked = False
        self._closed = False
        self._st = {"keyed": 0, "slots": 0, "late_max_us": 0, "last_event": None,
                    "sender_hz": 0.0, "sender_max_gap_ms": 0.0, "sent": 0, "skipped": 0, "fofs": 0}
        self._sender = None
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # --- reading
    def _read_loop(self):
        buf = b""
        while not self._closed:
            try:
                data = self._p.read(256)
            except Exception:
                break
            if not data:
                continue
            buf += data
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self._handle(raw.decode("ascii", "replace"))

    def _handle(self, line):
        kind, val = parse_line(line)
        if kind == "ev":
            name, kv = val
            ev = {"name": name, **kv}
            with self._state:
                self._st["last_event"] = ev
                if name == "link":
                    self._st["slots"] = kv.get("slots", 0)
                    self._st["late_max_us"] = kv.get("late_max_us", 0)
                elif name == "link_end":
                    self._linked = False
                    self._st["keyed"] = 0
                    self._st["slots"] = kv.get("slots", self._st["slots"])
                    self._st["late_max_us"] = kv.get("late_max_us", self._st["late_max_us"])
                cbs = list(self._cbs)
            for cb in cbs:
                try:
                    cb(ev)
                except Exception:
                    pass
        elif kind in ("ok", "err"):
            self._replies.put((kind, val))

    # --- requests
    def _request(self, line):
        check_line(line)
        with self._req_lock:
            sd = self._sender
            if sd is not None and sd.is_alive() and sd is not threading.current_thread():
                if not self._linked:
                    sd.join(1.0)
                    self._sleep(0.02)  # let stray idle-S OK replies arrive
            while not self._replies.empty():
                self._replies.get_nowait()
            self._p.write((line + "\n").encode())
            try:
                kind, val = self._replies.get(timeout=self._reply_timeout)
            except queue.Empty:
                raise TimeoutError(f"no reply to {line!r}")
        if kind == "err":
            raise D8Error(*val)
        return val

    def info(self):
        return self._request("INFO")

    def stat(self):
        r = self._request("STAT")
        with self._state:
            self._st["keyed"] = r.get("keyed", 0)
            self._st["fofs"] = r.get("fofs", 0)
        return r

    def set_fofs(self, hz):
        self._request(f"FOFS {int(hz)}")
        with self._state:
            self._st["fofs"] = int(hz)

    def on_event(self, cb):
        with self._state:
            self._cbs.append(cb)

    # --- link
    def start(self, power=127, timeout_ms=300, allow_arm=False, fofs_hz=None):
        if self._linked:
            raise D8Error("busy", "already linked")
        if fofs_hz is not None:
            self.set_fofs(fofs_hz)
        if allow_arm:
            self._request("ARMOK")
        with self._state:
            self._allow_arm = bool(allow_arm)
            self._ch[ARM_CH] = LO
            self._st.update(slots=0, late_max_us=0, last_event=None, sender_hz=0.0,
                            sender_max_gap_ms=0.0, sent=0, skipped=0)
        try:
            self._request(f"LINK {int(power)} {int(timeout_ms)}")
        except Exception:
            with self._state:
                self._allow_arm = False
            if allow_arm:
                try:
                    self._request("STOP")
                except Exception:
                    pass
            raise
        with self._state:
            self._linked = True
            self._st["keyed"] = 1
        self._sender = threading.Thread(target=self._send_loop, daemon=True)
        self._sender.start()

    def set_sticks(self, ch):
        with self._state:
            _, self._ch = fmt_sticks(ch, self._allow_arm)

    def stop(self):
        with self._state:
            was = self._linked
            self._linked = False
            self._st["keyed"] = 0
        s = self._sender
        if s is not None and s is not threading.current_thread():
            s.join(1.0)
        if was or True:
            try:
                self._request("STOP")
            except (TimeoutError, D8Error):
                pass
        with self._state:
            self._allow_arm = False

    def _send_loop(self, rate=1.0 / SLOT_S):
        period = 1.0 / rate
        clock, sleep = self._clock, self._sleep
        spin = clock is time.perf_counter
        t0 = nxt = clock()
        last = None
        arm_prev, arm_edge_t = False, None
        sent = skipped = 0
        max_gap = 0.0
        while self._linked and not self._closed:
            while True:
                d = nxt - clock()
                if d <= 0:
                    break
                if spin:
                    if d > SPIN_S:
                        sleep(d - SPIN_S)
                else:
                    sleep(d)
            if not self._linked:
                break
            now = clock()
            if getattr(self._p, "out_waiting", 0) > 64:
                skipped += 1
            else:
                with self._state:
                    ch, allow = list(self._ch), self._allow_arm
                # Arm-edge guard: Betaflight only arms with throttle at minimum, and an arm switch that
                # stays high after a refused arm blocks re-arming. Whenever ARM goes low->high, send
                # throttle 1000 for ARM_THROTTLE_HOLD_S regardless of what the caller asks.
                arm_hi = allow and ch[ARM_CH] > 1300
                if arm_hi and not arm_prev:
                    arm_edge_t = now
                arm_prev = arm_hi
                if arm_hi and arm_edge_t is not None and now - arm_edge_t < ARM_THROTTLE_HOLD_S:
                    ch[0] = LO
                line, _ = fmt_sticks(ch, allow)
                try:
                    self._p.write(line.encode())
                except Exception:
                    skipped += 1
                else:
                    if last is not None:
                        max_gap = max(max_gap, (now - last) * 1000)
                    last = now
                    sent += 1
                    with self._state:
                        self._st.update(sent=sent, skipped=skipped, sender_max_gap_ms=max_gap)
                        if sent > 1 and now > t0:
                            self._st["sender_hz"] = (sent - 1) / (now - t0)
            nxt += period
            if clock() - nxt > period:
                nxt = clock()

    def status(self):
        with self._state:
            ch = fmt_sticks(list(self._ch), self._allow_arm)[1]  # exactly what the sender puts on air
            return {"link": int(self._linked), "allow_arm": int(self._allow_arm), "ch": ch, **self._st}

    def close(self):
        if self._linked:
            self.stop()
        self._closed = True
        self._reader.join(1.0)
        try:
            self._p.close()
        except Exception:
            pass
