# d8live web UI

Browser view for `esp32sdr d8live` (backend: `host/esp32sdr/d8_live.py`), in three tabs:

- **Channels** (default): eight channel bars (980–2020 µs), stick pads (left: yaw ch4 X /
  throttle ch1 Y; right: roll ch2 X / pitch ch3 Y) and a 20 s channel plot.
- **Waterfall** (`#waterfall`): baseband waterfall, or the per-channel hop map with `--follow`.
- **Stats for nerds** (`#stats`): three tables. *Packets*: tx id, counter, rate, CRC rate,
  last-update age, decoder state. *Hop follow* (only with `--follow`): see below. *Stream*:
  centre, gain, uptime, CRC-ok count, frames, lost samples, bad-CRC/short frames, decoder
  share of samples, latency.

```sh
cd host/web/d8live && npm install && npm run build   # once; writes dist/
cd host && .venv/bin/esp32sdr d8live                 # board on /dev/cu.usbserial-0001, E8 on
# open http://127.0.0.1:8765/   (Ctrl-C stops the stream cleanly and prints loss stats)
```

Options: `--follow` (follow all 47 hop channels, ~108 packets/s instead of ~2.4; needs the
current devkitv1 firmware with `HOPTAB`, see docs/devkitv1/hop-follow.md), `--center 2421.032` (MHz), `--gain 40` (manual index, or `hw`), `--http-port 8765`,
`--open` (open the browser), `--status 5` (console status every N s, 0 = off).

For UI development run the backend as above plus `npm run dev` (Vite on :5173, `/ws` proxied
to :8765).

The backend serves `dist/` and a broadcast-only WebSocket at `/ws` (JSON text frames):
`{"type":"packet", t, tx_id, counter, ch[8] µs, raw[8], crc_ok, cfo, mode, latency_ms}` per
decoded packet and `{"type":"stats", packets_per_s, crc_rate, n_ok, n_all, mode, period_ms,
decode_frac, latency_ms, frames, samples, lost_samples, loss_frac, bad_crc, short_frames,
center_mhz, gain, gain_index, process_cpu_s, follow?}` once a second. `follow` is present only
with `--follow`: `{hops, ok_locked, slot_pct, losses, reacq_s[], first_lock_s, schedules,
slot_mismatch, counter_mismatch, decode_cpu_s, slot_ok[47], slot_hops[47], slot_mhz[47]}`. `crc_rate` is over decode attempts (bursts
with a sync word), so false syncs inside the locked window count against it.

## Look and code layout

The page follows the write-up (`docs/devkitv1/writeup/index.html`): white paper, Charter
title, system sans for labels and captions, SF Mono for numbers, 1 px `#e3e3e6` rules, link
blue for the tabs, and matplotlib's default colour cycle for the eight channels, as in the
write-up's figures. Styling is Tailwind CSS v4 through `@tailwindcss/vite`.

- `src/theme.css`: the design tokens (`@theme static`: colours, fonts, radii). Tailwind makes
  utilities from them (`text-muted`, `border-line`, `bg-paper-2`, `font-serif`, ...) and they
  are also CSS variables, which `src/tokens.ts` reads for canvas drawing and
  `waterfall.css` / `hitmap.css` use directly. Change colours here only.
- `src/style.css`: Tailwind entry, base element styles, and the repeated components
  (`.card` / `.tbl` stats tables, `.pad`, `.lede` tab intro line, `.tip` tooltip). Everything else is utility classes in `index.html`
  and the modules.
- `src/main.ts`: WebSocket wiring and the animation frame. Packets only update state; bars,
  pads, plot and the packet readouts are redrawn once per frame (and not at all while the
  waterfall tab hides `<main>`), so ~108 packets/s cause no per-packet layout.
- `src/stats.ts` (the Stats tab tables), `src/bars.ts` (channel bars, moved with
  `transform` only), `src/pads.ts` (stick gimbals), `src/plot.ts` (20 s plot with an O(1)-trim
  history), `src/canvas.ts` (HiDPI canvas sizing), `src/channels.ts` (µs range),
  `src/types.ts` (message types), plus `src/hitmap.ts` and `src/waterfall.ts`.

## Follow panel

With `d8_live.py --follow` the Stats tab shows a "Hop follow" table from `stats.follow`: lock state, packets/s, % of slots decoded, hops, lock losses, last re-acquire time, first-lock time, schedules, slot/counter mismatches, and a per-slot hit map (`src/hitmap.ts`, from `slot_ok` / `slot_hops` / `slot_mhz`). It is hidden otherwise.

## Waterfall tab

`src/waterfall.ts` (+ `waterfall.css`, colormaps from `d3-scale-chromatic`) also mounts the
"Channels | Waterfall | Stats for nerds" tab bar and switches tabs; `#waterfall` or `#stats`
in the URL opens that tab directly.
Backend: `host/esp32sdr/waterfall.py`. The stream thread hands each IQS frame to
`Waterfall.tap`; a worker thread makes rows with `numpy.fft` (256-point Hann, all blocks
averaged, 25 rows/s on the stream sample clock). With no subscriber `tap` returns at once
(~20–40 ns per frame) and no FFT runs.

- **baseband**: ±125 kHz around the tuned frequency, 256 bins, MHz axis (plain mode).
- **hop map** (`--follow` only): one 16-bin strip (±125 kHz) per hop channel, sorted by
  frequency, labelled in MHz. A strip is lit only in rows where the receiver was on that
  channel (about once per 422 ms); "hold last visit" fills the gaps with a dimmed copy.
  A channel with no signal shows as an empty (grey) column.

Levels are dB relative to a flat spectrum (1-bit I/Q has no amplitude), shown −10…+25 dB.
The page keeps a fixed ring of 45 s of rows (an offscreen canvas; ~3 MB for the hop map),
so memory does not grow. Pause freezes the display; hover shows slot/frequency and age.

Socket: `ws://HOST:PORT/wf?view=base|hop`, open only while the tab is shown. It sends one
`{"type":"wf_meta", view, views, width, rate, db_min, db_max, fs, nfft, center_mhz,
channels[{slot,mhz}], bins_per_ch}` text frame, then binary rows (16-byte header
`<BBHId`: kind 0 base / 1 hop, 0, width, seq, t stream s; then `width` uint8, 0 = no data,
1..255 = db_min..db_max), and `{"type":"wf_stats", cpu_frac, dropped, ...}` once a second.

Measured cost (`host/tools/wf_demo.py --bench 10 [--follow]`): ~0.3 % of one core per
stream second for the row maker; ~1 % for the worker thread as reported in the UI.

Without the board: `cd host && .venv/bin/python tools/wf_demo.py --follow` (simulated
hopping tx, slot 33 silent) or `--sigmf /tmp/d8/centred_m2` (a recording), then open
`http://127.0.0.1:8765/#waterfall`.

## Help text and tooltips

Each tab opens with one line saying what it shows. Jargon labels (stats table rows, waterfall
`view` / `hold last visit`, the dB range and FFT CPU figures, hit-map cells, the connection
status) have a dotted underline and a `data-tip` attribute; `src/tooltip.ts` shows it in one
shared `role="tooltip"` bubble (positioned with `@floating-ui/dom`) on hover after 300 ms or on
keyboard focus, with `aria-describedby` on the trigger, and closes on Escape, blur or pointer
leave. The hit map is one tab stop; arrow keys move between cells. To add a tip, put
`data-tip="..."` (and `tabindex="0"` if the element is not focusable) on the element.
