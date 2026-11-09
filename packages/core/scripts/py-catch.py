# Dev bench helper (not part of the check): Python d8tx link with the library defaults (FOFS, TLM recipe), telemetry on,
# arm disallowed, for N seconds; prints totals comparable to hw-check.ts. Run with python/.venv/bin/python.
import sys, time
sys.path.insert(0, "python")
from d8tx.link import D8Link

port, power, secs = "/dev/cu.usbserial-0001", int(sys.argv[1]) if len(sys.argv) > 1 else 30, float(sys.argv[2]) if len(sys.argv) > 2 else 20
fofs = int(sys.argv[3]) if len(sys.argv) > 3 else None
ev = {}
link = D8Link(port)
link.on_event(lambda e: ev.__setitem__(e["name"], ev.get(e["name"], 0) + 1))
time.sleep(0.5)
print("PING", link._request("PING"))
link.start(power=power, allow_arm=False, telemetry=True, fofs_hz=fofs)
link.set_sticks([1000, 1500, 1500, 1500, 1500, 1500, 1000, 1500])
time.sleep(secs)
st = link.status()
tr = link._tlm
link.stop()
print("events", ev)
print(f"RESULT py sender_hz={st['sender_hz']:.2f} max_gap_ms={st['sender_max_gap_ms']:.1f} sent={st['sent']} slots={st['slots']}")
print(f"RESULT py telemetry triggers={tr.triggers} decoded_replies={tr.replies} catch={tr.replies / max(1, tr.triggers):.3f}")
link.close()
