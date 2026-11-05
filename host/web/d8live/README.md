# d8live web UI

Browser view for `esp32sdr d8live` (backend: `host/esp32sdr/d8_live.py`): eight channel bars
(980–2020 µs), stick pads (left ch4/ch3, right ch1/ch2, mode-2 AETR), a 20 s channel plot,
tx id / counter / packet rate / CRC rate / last-update age, and stream loss stats.

```sh
cd host/web/d8live && npm install && npm run build   # once; writes dist/
cd host && .venv/bin/esp32sdr d8live                 # board on /dev/cu.usbserial-0001, E8 on
# open http://127.0.0.1:8765/   (Ctrl-C stops the stream cleanly and prints loss stats)
```

Options: `--center 2421.032` (MHz), `--gain 40` (manual index, or `hw`), `--http-port 8765`,
`--open` (open the browser), `--status 5` (console status every N s, 0 = off).

For UI development run the backend as above plus `npm run dev` (Vite on :5173, `/ws` proxied
to :8765).

The backend serves `dist/` and a broadcast-only WebSocket at `/ws` (JSON text frames):
`{"type":"packet", t, tx_id, counter, ch[8] µs, raw[8], crc_ok, cfo, mode, latency_ms}` per
decoded packet and `{"type":"stats", packets_per_s, crc_rate, n_ok, n_all, mode, period_ms,
decode_frac, latency_ms, frames, samples, lost_samples, loss_frac, bad_crc, short_frames,
center_mhz, gain, gain_index, ...}` once a second. `crc_rate` is over decode attempts (bursts
with a sync word), so false syncs inside the locked window count against it.
