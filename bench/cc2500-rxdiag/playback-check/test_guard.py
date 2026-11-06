#!/usr/bin/env python3
"""Zero-RF tests for guard.py and pbcheck.py's hard stop (fake ESP + fake detector, no ports opened).

  python3 test_guard.py
1. Recorded sessions: overhead = keyed_us - engine time per keyed slot; new worst case with the default
   count/tmo must stay under guard.ABORT_US even for the worst first-key overhead.
2. pbcheck.main() against a fake Dev that reproduces the first-key transient: must finish with no abort.
3. Same, with one keyed slot over the abort level (and one hang during keyed T): the session must stop
   immediately (no further T commands), still run cleanup, and record the abort.
"""
import glob, json, os, socket, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guard
import pbcheck


def recorded_overheads():
    out = []
    for sd in sorted(glob.glob(os.path.join(HERE, "sessions", "*"))):
        meta = json.load(open(os.path.join(sd, "meta.json")))
        if meta["args"].get("km", 1) != 0:
            continue
        k = [json.loads(l) for l in open(os.path.join(sd, "slots.jsonl"))]
        k = [r for r in k if r.get("keyed_us")]
        for j, r in enumerate(k):
            out.append((os.path.basename(sd), j == 0, r["keyed_us"] - r["cyc_max"] / 240))
    return out


class FakeDev:
    def __init__(self, log=None, over_at=None, hang_at=None):
        self.n_tx, self.hangs, self.over_at, self.hang_at, self.cmds = 0, 0, over_at, hang_at, []
        self.s = type("S", (), {"close": lambda s: None, "reset_input_buffer": lambda s: None})()

    def reset(self):
        return ["I,ready"]

    def cmd(self, line, timeout=10):
        self.cmds.append(line)
        return {"Q": ["V,freq,2412,xtal=40,cap_reg=b0"], "B 5 1": ["V,pbus,5,1,0"]}.get(line, ["OK"])

    def tx(self, ctrl, reps=1, tmo=2000, flags=0, gmode=9, pwr=-1):
        self.n_tx += 1
        self.cmds.append(f"T {ctrl:#x} {tmo} {flags} {pwr}")
        keyed = flags & pbcheck.F_KEY
        if keyed and self.n_tx == self.hang_at:
            raise pbcheck.Hang()
        eng = guard.engine_us(ctrl & 0x7FFF)
        first = keyed and not any(c.startswith("T") and int(c.split()[3]) & 4 for c in self.cmds[:-1])
        ovh = 291 if first else 130
        k = int(ovh + min(eng, tmo)) if keyed else 0
        if keyed and self.n_tx == self.over_at:
            k = 483
        return {"keyed_us": k, "ndone": 1, "pb51": pwr if keyed else 0, "cyc_max": int(eng * 240)}


def run(dev, extra=()):
    out = tempfile.mkdtemp(prefix="pbsim-")
    a, b = socket.socketpair()
    b.setblocking(False)
    pbcheck.Dev = lambda log=None: dev
    fa = a.detach()  # pbcheck os.close()s it
    run.keep = b
    pbcheck.rx.openp = lambda p: fa
    pbcheck.rx.cli = lambda fd: True
    pbcheck.rx.rd = lambda fd, t: b""
    pbcheck.time.sleep = lambda t: None
    sys.argv = ["pbcheck", "--out", out, "--n", "3", "--conds", "pat156,zero,unkey,tone,idle", *extra]
    pbcheck.main()
    return json.load(open(os.path.join(out, "meta.json"))), out


def main():
    ov = recorded_overheads()
    first = max(o for _, f, o in ov if f)
    later = max(o for _, f, o in ov if not f)
    worst = first + guard.TMO_DEFAULT
    print(f"recorded K0 overhead: first-key max {first:.1f} us, later max {later:.1f} us (n={len(ov)})")
    print(f"default count {guard.COUNT_DEFAULT} -> engine {guard.engine_us(guard.COUNT_DEFAULT):.1f} us, "
          f"tmo cap {guard.TMO_DEFAULT}: worst {worst:.1f} us vs abort {guard.ABORT_US} / rule {guard.LIMIT_US}")
    assert first <= guard.OVERHEAD_WORST_US + 0.5 and worst < guard.ABORT_US < guard.LIMIT_US

    # preflight refuses the old settings
    for cnt, tmo in ((0x3BFF, 400), (0x2FFF, 400), (guard.COUNT_DEFAULT, 200)):
        try:
            guard.preflight(cnt, tmo, 0, 127)
            raise AssertionError(f"preflight accepted count {cnt:#x} tmo {tmo}")
        except guard.Abort as e:
            print("preflight refuses:", e)

    meta, _ = run(FakeDev())
    assert meta["abort"] is None, meta["abort"]
    print("sim clean run: abort None, slots", len(meta["order"]))

    for kw in ({"over_at": 4}, {"hang_at": 4}):
        dev = FakeDev(**kw)
        meta, out = run(dev)
        recs = [json.loads(l) for l in open(os.path.join(out, "slots.jsonl"))]
        assert meta["abort"], kw
        assert dev.n_tx == len([r for r in recs if r["flags"] is not None]), "T sent after abort"
        assert dev.cmds[-2:] == ["B 5 1", "Q"], dev.cmds[-3:]
        print(f"sim {kw}: aborted after {dev.n_tx} T commands ({len(recs)}/{len(meta['order'])} slots): {meta['abort']}")
    print("ALL OK")


if __name__ == "__main__":
    main()
