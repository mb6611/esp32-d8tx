"""WS driver: start link via API, send sticks at 20 Hz, log every WS telemetry msg to JSONL.
usage: drive.py OUT.jsonl SECS [arm_at arm_for]   (arm: allow_arm + ch7 high for arm_for s starting arm_at s)"""
import asyncio, json, sys, time, httpx, websockets
out, secs = sys.argv[1], float(sys.argv[2])
arm_at = float(sys.argv[3]) if len(sys.argv) > 3 else None
arm_for = float(sys.argv[4]) if len(sys.argv) > 4 else 5
async def main():
    r = httpx.post("http://127.0.0.1:8000/api/link/start",
                   json={"power": 127, "timeout_ms": 300, "allow_arm": arm_at is not None, "telemetry": True}, timeout=10)
    print("start", r.status_code, r.text, flush=True)
    f = open(out, "w"); t0 = time.time()
    async with websockets.connect("ws://127.0.0.1:8000/api/ws") as ws:
        async def tx():
            while time.time() - t0 < secs:
                t = time.time() - t0
                hi = arm_at is not None and arm_at <= t < arm_at + arm_for
                ch = [1000, 1500, 1500, 1500, 1000, 1000, 2000 if hi else 1000, 1000]
                await ws.send(json.dumps({"type": "sticks", "ch": ch, "tcmd": t}))
                await asyncio.sleep(0.05)
        async def rx():
            while time.time() - t0 < secs:
                m = json.loads(await ws.recv()); m["t"] = round(time.time() - t0, 3)
                f.write(json.dumps(m) + "\n")
        await asyncio.gather(tx(), rx())
    httpx.post("http://127.0.0.1:8000/api/link/stop", timeout=10)
asyncio.run(main())
