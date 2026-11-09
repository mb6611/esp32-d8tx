---
name: d8tx-server-running
description: Read before finishing any task that stopped or restarted the d8tx backend (python -m d8tx.server); the owner expects it running on :8000 afterwards.
load: description
---
The owner expects the d8tx controller backend to be running on http://localhost:8000 whenever no agent is using the boards. On 2026-11-08 he asked for it repeatedly after agents had stopped it for hardware work and reported "restarted" while it was actually down: a server started from a child agent's shell does not reliably outlive that agent.

**How to apply:** if you stop the server, the orchestrator (root) must restart it after your final yield and confirm with `curl -s localhost:8000/api/status` (ESP connected, drone USB connected). Command, from `d8tx/python`: `nohup .venv/bin/python -m d8tx.server --esp-port /dev/cu.usbserial-0001 --fc-port /dev/cu.usbmodem0x80000001 --port 8000 > /tmp/d8tx_server.log 2>&1 &`. Children should say in their final yield that they stopped it, not claim it is running.
