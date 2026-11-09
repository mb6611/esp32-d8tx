# Validation index

Every measured figure or number the project quotes, with the script that produced it and the data it reads. Raw results are kept next to the bench code under `bench/**/results/` and `apps/desktop/e2e/results/`. Plots are regenerated with the commands in [the writeup's "Reproduce the figures"](../devkitv1/writeup/tx.md#reproduce-the-figures); they read files in this repo only.

## Records

| Record | What it covers |
|---|---|
| [d8tx-web-desktop.md](d8tx-web-desktop.md) | Electron app end to end: connect timings, 10-minute background link, telemetry rate, arm/throttle/disarm, port loss while armed (2026-11-09). |
| [bench/d8-tx/results/bind/SUMMARY.md](../../bench/d8-tx/results/bind/SUMMARY.md) | Over-the-air bind with per-ESP identity: registers before/after, catch rates at FOFS 0 and -75 kHz, power 127 and 30 (2026-11-09). |

## Figures and numbers

| Claim | Where quoted | Script | Data |
|---|---|---|---|
| Fixed-channel packet reception about 94% (ESP32 vs real E8) | writeup §5, Figures 5-7 | `docs/devkitv1/writeup/plot_reliability.py` | `bench/d8-tx/results/packet/` |
| Hopping, 921 of 940 slots (run B) vs real E8 2133 of 2204 | writeup §6, Figures 8-11 | `docs/devkitv1/writeup/plot_hop.py` | `bench/d8-tx/results/hop/`, `bf_link/offset_tune/` |
| Tone scan, detector trap, packet outcome | writeup §2-4, Figures 1-3 | `bench/d8-tx/analysis/plot_tx.py` | `bench/d8-tx/results/tone/`, `packet/` |
| Live roll latency | writeup §7, Figure 12 | `docs/devkitv1/writeup/plot_latency.py` | `bench/d8-tx/results/bf_link/live_sticks/` |
| Telemetry catch rate and age, hub fields, armed bit | writeup §9, Figures 14-16 | `docs/devkitv1/writeup/plot_telemetry.py` | `bench/d8-tx/results/telemetry-stack/e2e/`, `betaflight-patch/armtest_log.csv` |
| Blackbox session | writeup §9, Figure 17 | `docs/devkitv1/writeup/plot_telemetry.py` | `bench/blackbox/results/bench/bb_session1_reconstructed.01.csv` |
| EIRP estimate (about -25 dBm, from RSSI, not measured) | writeup "Regulatory status" | `bench/d8-tx/analysis/plot_tx.py --summary` | `hop/e8_control/`, `bf_link/offset_tune/`, `packet/` |
| 111 Hz sender, RC readback exact, 94.9% telemetry catch (power 127, FOFS 0) | [bind SUMMARY](../../bench/d8-tx/results/bind/SUMMARY.md) | `packages/core/scripts/hw-check.ts` | `bench/d8-tx/results/bind/link_p127_fofs0.log` |
| One-click bind path | bind SUMMARY (`ts_bind.log`: 90.9% catch) | `packages/core/scripts/bind-check.ts`, `hw-check.ts --bind` | `bench/d8-tx/results/bind/` |
| 10-minute minimized link: no S gap over 50 ms, 96.0% telemetry catch | [d8tx-web-desktop.md](d8tx-web-desktop.md) | `apps/desktop/e2e/run.mjs soak` | `apps/desktop/e2e/results/soak-2026-11-09T18-22-51-299Z.json` |
| Arm, throttle 1150, disarm, port-close disarm | d8tx-web-desktop.md | `apps/desktop/e2e/run.mjs arm` | `apps/desktop/e2e/results/arm-2026-11-09T18-35-15-559Z.json` |
| Auto-link timings, second instance | e2e `autolink` | `apps/desktop/e2e/run.mjs autolink` | `apps/desktop/e2e/results/autolink-2026-11-09T20-45-56-554Z.json` |

Figures 4, 9, 10 and 13 in the writeup are plotted by the scripts above or are screenshots; see their captions. Offline tests that need no hardware: `make -C firmware test`, `make -C demod check`, `pnpm test`, `python/.venv/bin/pytest python/tests`.

## Not covered

Distance or range, calibrated output power, harmonics and spurious emissions, other drones or receivers, Firefox and Safari. Full list: [writeup, "What this does not show"](../devkitv1/writeup/tx.md#what-this-does-not-show).
