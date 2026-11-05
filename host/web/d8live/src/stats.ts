// Text readouts for the stats tab tables (packets, hop follow, stream). Stats arrive
// once a second; packet fields are written from the animation frame, at most
// once per frame, never per packet.
import type { PacketMsg, StatsMsg } from "./types";

const $ = (id: string) => document.getElementById(id)!;
const set = (id: string, text: string) => { const e = $(id); if (e.textContent !== text) e.textContent = text; };

/** Colour a value element by state using the theme's ok / warn / bad tokens. */
function tone(id: string, t: "ok" | "warn" | "bad" | null) {
  const e = $(id);
  e.classList.toggle("text-ok", t === "ok");
  e.classList.toggle("text-warn", t === "warn");
  e.classList.toggle("text-bad", t === "bad");
}

export function setConnected(on: boolean) {
  set("conn", on ? "connected" : "disconnected");
  tone("conn", on ? "ok" : "bad");
}

export function showPacket(p: PacketMsg) {
  set("tx", `${p.tx_id[0]},${p.tx_id[1]} (0x${((p.tx_id[0] << 8) | p.tx_id[1]).toString(16).padStart(4, "0")})`);
  set("ctr", String(p.counter));
}

export function showAge(age: number | null) {
  set("age", age == null ? "–" : `${age.toFixed(1)} s ago`);
  tone("age", age != null && age > 1.5 ? "bad" : null);
}

export function showStats(s: StatsMsg) {
  const f = s.follow;
  $("follow").hidden = !f;
  if (f) {
    set("f-state", s.mode);
    tone("f-state", s.mode === "locked" ? "ok" : "warn");
    set("f-pps", s.packets_per_s.toFixed(1));
    set("f-slot", `${f.slot_pct.toFixed(1)}% (${f.ok_locked}/${f.hops})`);
    set("f-hops", String(f.hops));
    set("f-loss", String(f.losses));
    const r = f.reacq_s;
    set("f-reacq", r.length ? `${r[r.length - 1].toFixed(2)} s` : "–");
    set("f-first", f.first_lock_s == null ? "–" : `${f.first_lock_s.toFixed(1)} s`);
    set("f-sched", String(f.schedules));
    set("f-mis", `${f.slot_mismatch} / ${f.counter_mismatch}`);
  }
  set("rate", `${s.packets_per_s.toFixed(2)}/s`);
  set("crc", s.crc_rate == null ? "–" : `${(s.crc_rate * 100).toFixed(0)}%`);
  set("mode", `${s.mode}${s.mode === "locked" ? ` (${s.period_ms.toFixed(1)} ms)` : ""}`);
  set("s-center", `${s.center_mhz} MHz`);
  set("s-gain", `${s.gain} (frame idx ${s.gain_index ?? "?"})`);
  set("s-up", `${s.uptime.toFixed(0)} s`);
  set("s-ok", `${s.n_ok} / ${s.n_all}`);
  set("s-frames", String(s.frames));
  set("s-lost", `${s.lost_samples} (${(s.loss_frac * 100).toFixed(3)}%)`);
  tone("s-lost", s.lost_samples ? "warn" : null);
  set("s-bad", `${s.bad_crc} / ${s.short_frames}`);
  set("s-dec", `${(s.decode_frac * 100).toFixed(1)}% of samples`);
  set("s-lat", `${s.latency_ms ?? "–"} ms`);
}
