"""D8Link: protocol v1 UART client with a paced stick sender thread."""
import queue
import threading
import time

ARM_THROTTLE_HOLD_S = 0.5

from .protocol import (ARM_CH, ARM_LIMIT, DEFAULT_FOFS_HZ, TLM_RECIPE, check_line, LO, MID, SLOT_S, ProtocolError,
                       fmt_sticks, parse_line)
from .telemetry import Tracker, decode_capture, load_iq, next_tid, parse_tlm_header, payload_ok

SPIN_S = 0.001


class D8Error(ProtocolError):
    pass


def unpack4(payload: bytes) -> bytes:
    """TLM bits=4 payload (I in the low nibble, Q in the high nibble of each byte, signed) -> int8 I,Q interleaved."""
    import numpy as np
    b = np.frombuffer(payload, np.uint8)
    out = np.empty(2 * len(b), np.int8)
    out[0::2] = ((b & 0xF).astype(np.int8) ^ 8) - 8
    out[1::2] = ((b >> 4).astype(np.int8) ^ 8) - 8
    return out.tobytes()


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
        self._wlock = threading.Lock()
        self._tlm = Tracker(clock)
        self._tlm_on = False  # telemetry configured on the current/last link (TLM recipe accepted by the firmware)
        self._tlm_sent = False  # the firmware may still hold a TLM recipe (RAM) from an earlier start
        self._tid = 0  # id for the next trigger; kept across links so the drone's expected id stays locked
        self._shift_hint = None
        self._capq = queue.Queue(maxsize=16)
        self._worker = threading.Thread(target=self._tlm_loop, daemon=True)
        self._worker.start()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # --- reading
    def _read_loop(self):
        # Byte-oriented: `EV tlm ... bytes=N` is followed by N raw payload bytes and "\n" that may contain anything.
        buf = bytearray()
        pending = None
        while not self._closed:
            try:
                n = getattr(self._p, "in_waiting", None)
                data = self._p.read(256 if n is None else max(1, min(int(n), 65536)))
            except Exception:
                break
            if not data:
                continue
            buf += data
            while True:
                if pending is not None:
                    need = pending["bytes"] + 1  # payload + trailing newline
                    if len(buf) < need:
                        break
                    payload = bytes(buf[:pending["bytes"]])
                    del buf[:need]
                    meta, pending = pending, None
                    self._on_capture(meta, payload)
                    continue
                i = buf.find(b"\n")
                if i < 0:
                    if len(buf) > 4096:  # no newline in a long run: garbage, resync
                        del buf[:]
                    break
                raw = bytes(buf[:i])
                del buf[:i + 1]
                line = raw.decode("ascii", "replace")
                if line.startswith("EV tlm "):
                    meta = parse_tlm_header(line)
                    if 0 < meta.get("bytes", 0) <= 65536:
                        pending = meta
                        continue
                self._handle(line)

    def _on_capture(self, meta, payload):
        try:
            self._capq.put_nowait((meta, payload))
        except queue.Full:
            self._tlm.note_trigger_miss()  # decoder behind: this capture is lost (firmware resends the tid on timeout)

    def _tlm_loop(self):
        while not self._closed:
            try:
                meta, payload = self._capq.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._process_capture(meta, payload)
            except Exception:
                pass

    def _process_capture(self, meta, payload):
        if not self._tlm_on:
            return
        rep = None
        if payload_ok(meta, payload):
            bits = meta.get("bits", 16)
            if bits == 4:
                payload, bits = unpack4(payload), 8
            iq = load_iq(payload, meta.get("n", 0), bits)
            rep = decode_capture(iq, float(meta.get("fs", 500000)), hint=self._shift_hint)
        if rep is not None:
            self._shift_hint = rep["shift_hz"]
            self._tlm.note_reply(rep)
        else:
            self._tlm.note_trigger_miss()
        # ack rule: advance the id only after a reply echoed it (see telemetry.next_tid); the firmware's next trigger
        # waits for this TID (<= 1 s), so it goes out before anything else.
        self._tid = next_tid(meta.get("tid", self._tid), None if rep is None else rep["tid"])
        # check _linked and write under _wlock; stop() clears _linked then takes _wlock, so no TID follows STOP.
        # A TID the firmware sees after the link ended answers `OK tid=N`; _request ignores such OKs unless it sent TID.
        with self._wlock:
            if self._linked:
                try:
                    self._p.write(f"TID {self._tid}\n".encode())
                except Exception:
                    pass

    def _write(self, b):
        with self._wlock:
            return self._p.write(b)

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
            if name == "tlm_drop":
                self._tlm.note_trigger_miss()  # on-chip check saw no reply; the firmware re-triggers with the same id
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
            self._write((line + "\n").encode())
            expect_tid = line.startswith("TID ")
            deadline = time.monotonic() + self._reply_timeout
            while True:
                try:
                    kind, val = self._replies.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    raise TimeoutError(f"no reply to {line!r}")
                if kind == "ok" and not expect_tid and "tid" in val:
                    continue  # stray answer to an async TID sent just before the link ended
                break
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
    def start(self, power=127, timeout_ms=300, allow_arm=False, fofs_hz=None, telemetry=True):
        if self._linked:
            raise D8Error("busy", "already linked")
        # Opening the port resets the ESP32 (DTR/RTS); a start right after open can race its boot,
        # so the first request gets a few tries (each waits reply_timeout).
        for attempt in range(3):
            try:
                self.set_fofs(DEFAULT_FOFS_HZ if fofs_hz is None else fofs_hz)
                break
            except TimeoutError:
                if attempt == 2:
                    raise
        self._setup_telemetry(telemetry)
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

    def _setup_telemetry(self, want):
        """Send the TLM recipe before LINK (RAM only in the firmware; kept across LINKs). An older firmware answering
        ERR leaves telemetry off instead of failing the link."""
        ok = False
        if want:
            try:
                self._request(f"TID {self._tid}")  # continue the id sequence: the drone's expected id persists
                self._request(TLM_RECIPE)
                ok = True
                self._tlm_sent = True
            except (D8Error, TimeoutError):
                ok = False
        elif self._tlm_sent:
            try:
                self._request("TLM 0")
                self._tlm_sent = False
            except (D8Error, TimeoutError):
                pass
        self._tlm_on = ok
        self._tlm.reset(enabled=ok)
        self._tlm.note_arm_on_air(False)
        self._shift_hint = None

    def telemetry(self):
        """Thread-safe snapshot of the radio telemetry (see docs/PROTOCOL.md "Telemetry in the library")."""
        return self._tlm.snapshot()

    def set_sticks(self, ch):
        with self._state:
            _, self._ch = fmt_sticks(ch, self._allow_arm)
            on_air = self._ch[ARM_CH] > ARM_LIMIT
        self._tlm.note_arm_on_air(on_air)

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
                    self._write(line.encode())
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
            return {"link": int(self._linked), "allow_arm": int(self._allow_arm), "ch": ch, "tlm_enabled": int(self._tlm_on),
                    **self._st}

    def close(self):
        if self._linked:
            self.stop()
        self._closed = True
        self._reader.join(1.0)
        try:
            self._p.close()
        except Exception:
            pass
