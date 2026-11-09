"""FastAPI backend: REST + WebSocket on top of D8Link / BetaflightMSP."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SILENCE_S = 0.25
TELEMETRY_HZ = 50
FC_DEFAULT = {"connected": False, "rc": [], "attitude_deg": None, "motors": None, "armed": None, "failsafe": None,
              "arming_disable": [], "rssi": None, "error": None}
RADIO_DEFAULT = {
    "enabled": False, "powered": False, "link": False, "age_ms": None, "catch_rate": None,
    "triggers": 0, "replies": 0, "rssi": None, "rssi_dbm": None, "a1_raw": None, "a2_raw": None,
    "vbat_v": None, "battery": None, "cfo_khz": None,
    "hub": {"acc_mg": None, "heading_deg": None, "rpm": None, "vfas_v": None, "current_a": None,
            "fuel": None, "temp1": None, "temp2": None, "patched": {}, "raw": {}, "age_ms": None},
    "armed": None, "armed_source": None,
    "fast": None,
}
DEFAULT_DIST = Path(__file__).resolve().parents[2] / "app" / "dist"


class StartReq(BaseModel):
    power: int = 127
    fofs_hz: Optional[int] = None
    timeout_ms: int = 300
    allow_arm: bool = False
    telemetry: bool = True


def create_app(esp: Any, fc: Any = None, dist: Optional[Path] = None,
               fc_factory: Any = None, fc_retry_s: float = 1.0) -> FastAPI:
    state: dict[str, Any] = {"fc_obj": fc, "fc_try": 0.0, "last_msg": time.monotonic(), "info": None,
                             "fc": dict(FC_DEFAULT)}

    def esp_status() -> dict:
        try:
            st = dict(esp.status() or {})
            st.update(connected=True, info=state["info"])
            return st
        except Exception as e:  # noqa: BLE001
            return {"connected": False, "error": str(e)}

    def radio_status() -> dict:
        out = copy.deepcopy(RADIO_DEFAULT)
        try:
            out.update(esp.telemetry())
        except Exception:  # noqa: BLE001
            pass
        return out

    def fetch_info() -> None:
        # INFO ends a running link in firmware: only call while not linked.
        if state["info"] is None:
            try:
                if not (esp.status() or {}).get("link"):
                    state["info"] = esp.info()
            except Exception:  # noqa: BLE001
                pass

    def fc_poll() -> dict:
        out = dict(FC_DEFAULT)
        fc = state["fc_obj"]
        if fc is None and fc_factory is not None:
            now = time.monotonic()
            if now - state["fc_try"] < fc_retry_s:
                out.update(error=(state.get("fc") or {}).get("error"))
                return out
            state["fc_try"] = now
            try:
                fc = state["fc_obj"] = fc_factory()
            except Exception as e:  # noqa: BLE001
                out.update(error=str(e))
                return out
        if fc is None:
            return out
        try:
            prev = state.get("fc") or FC_DEFAULT
            state["fc_n"] = state.get("fc_n", 0) + 1
            out.update(prev)
            out.update(connected=True, rc=list(fc.rc())[:8], error=None,
                       attitude_deg=list(fc.attitude()))  # RC every poll (readback latency)
            if state["fc_n"] % 2 == 0:  # motors every 2nd poll
                m = getattr(fc, "motors", None)
                out["motors"] = list(m())[:4] if m else None
            if state["fc_n"] % 5 == 1:  # status/RSSI change slowly: every 5th poll
                s = dict(fc.status())
                out.update(rssi=fc.rssi(), armed=s.get("armed"), failsafe=s.get("failsafe"),
                           arming_disable=list(s.get("arming_disable") or []))
        except Exception as e:  # noqa: BLE001
            out.update(connected=False, error=str(e))
            if fc_factory is not None:  # drop the dead port; reopen after fc_retry_s
                state["fc_obj"], state["fc_try"] = None, time.monotonic()
                with contextlib.suppress(Exception):
                    fc.close()
        return out

    async def full_status() -> dict:
        return {"esp": await asyncio.to_thread(esp_status), "fc": dict(state["fc"]),
                "radio": await asyncio.to_thread(radio_status)}

    def linked() -> bool:
        try:
            return bool((esp.status() or {}).get("link"))
        except Exception:  # noqa: BLE001
            return False

    def watchdog_tick() -> None:
        if time.monotonic() - state["last_msg"] > SILENCE_S and linked():
            with contextlib.suppress(Exception):
                esp.stop()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        async def watchdog() -> None:
            while True:
                await asyncio.sleep(0.05)
                await asyncio.to_thread(watchdog_tick)

        async def fc_loop() -> None:
            while True:
                state["fc"] = await asyncio.to_thread(fc_poll)
                await asyncio.sleep(0.005)

        await asyncio.to_thread(fetch_info)
        tasks = [asyncio.create_task(watchdog()), asyncio.create_task(fc_loop())]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            with contextlib.suppress(Exception):
                await asyncio.to_thread(esp.stop)

    app = FastAPI(title="d8tx", lifespan=lifespan)

    @app.get("/api/status")
    async def status() -> dict:
        return await full_status()

    @app.post("/api/link/start")
    async def link_start(req: StartReq = StartReq()) -> dict:
        try:
            state["last_msg"] = time.monotonic()
            await asyncio.to_thread(fetch_info)
            await asyncio.to_thread(esp.start, req.power, req.timeout_ms,
                                    req.allow_arm, req.fofs_hz, telemetry=req.telemetry)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(409, str(e))
        return {"ok": True}

    @app.post("/api/link/stop")
    async def link_stop() -> dict:
        try:
            await asyncio.to_thread(esp.stop)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(409, str(e))
        return {"ok": True}

    @app.websocket("/api/ws")
    async def ws(sock: WebSocket) -> None:
        await sock.accept()

        async def sender() -> None:
            while True:
                msg = {"type": "telemetry", **await full_status()}
                await sock.send_json(msg)
                await asyncio.sleep(1 / TELEMETRY_HZ)

        task = asyncio.create_task(sender())
        try:
            while True:
                data = await sock.receive_json()
                state["last_msg"] = time.monotonic()
                if isinstance(data, dict) and data.get("type") == "sticks":
                    ch = data.get("ch")
                    if (isinstance(ch, list) and len(ch) == 8
                            and all(isinstance(v, (int, float)) for v in ch)):
                        with contextlib.suppress(Exception):
                            esp.set_sticks([int(v) for v in ch])
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            task.cancel()

    dist = DEFAULT_DIST if dist is None else dist
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="app")
    return app


def main() -> None:
    import uvicorn
    from .link import D8Link
    p = argparse.ArgumentParser()
    p.add_argument("--esp-port", required=True)
    p.add_argument("--fc-port")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args()
    factory = None
    if a.fc_port:
        from .msp import BetaflightMSP
        factory = lambda: BetaflightMSP(a.fc_port)  # noqa: E731
    uvicorn.run(create_app(D8Link(a.esp_port), None, fc_factory=factory), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
