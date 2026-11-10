#!/usr/bin/env python3
"""Offline classification of telemetry trigger slots in tlm_listen.py link runs (no hardware).

For every capture of a run: energy burst detection (reply present? where in the window?), the
stock decode (tlm_listen.decode_capture), decoder margins on caught replies (sync errors, soft-bit
eye, sign errors against the CRC-valid bits) and, for uncaught captures with energy, a relaxed decode
(fine carrier grid, more sync errors, single-bit CRC fix).

Classes per capture (b/c are split by a known-bits template correlation into "reply under the energy"
and "interference only"; a with a template hit would be a reply too weak to show as a burst):
  hit  CRC-valid telemetry frame (stock decoder)
  a    no reply energy (no burst >= MIN_BURST_MS at >= THRESH_DB over the capture's quiet floor)
  b    burst inside the window but no CRC-valid frame
  c    burst touching the window start or end and shorter than a full reply (cut off)

    python tlm_misses.py experiments/09-telemetry/data/<run> [<run> ...] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tlm_listen  # noqa: E402
from tlm_listen import d8  # noqa: E402

BLOCK_S = 100e-6
THRESH_DB = 10.0
MIN_BURST_MS = 0.5
AIR_MS = d8.AIR_BITS / d8.BAUD * 1e3  # full reply on air (preamble .. CRC), ~6.70 ms
EDGE_S = 2 * BLOCK_S
TXID_B = tlm_listen.TXID
CORR_PRESENT = 0.25  # max 0.12 over the 124 no-reply captures of 212358/212508/212744; replies >= 0.75


def load(run: str, rec: dict) -> np.ndarray:
    """Capture as complex, scaled back to the firmware's int16 sums (int8 stream: << sh)."""
    raw = open(os.path.join(run, rec["file"]), "rb").read()
    bits = rec.get("bits", 16)
    iq = tlm_listen.load_iq(raw, rec["n"], bits)
    return iq * (1 << rec.get("sh", 0)) if bits == 8 else iq


def floor_power(iq: np.ndarray, fs: float) -> float:
    """Quiet level of one capture: 10th percentile of the block powers."""
    x = iq - iq.mean()
    blk = max(1, int(round(fs * BLOCK_S)))
    nb = len(x) // blk
    return float(np.percentile((np.abs(x[: nb * blk]) ** 2).reshape(nb, blk).mean(1), 10))


def bursts(iq: np.ndarray, fs: float, floor: float | None = None) -> tuple[list[tuple[float, float, float]], float, np.ndarray]:
    """Energy bursts as (start_s, end_s, level_db_over_floor), floor rms, block power (dB).
    floor: reference power (the run's receiver noise floor); default this capture's quiet level, which
    hides energy that fills the whole window."""
    x = iq - iq.mean()
    blk = max(1, int(round(fs * BLOCK_S)))
    nb = len(x) // blk
    p = (np.abs(x[: nb * blk]) ** 2).reshape(nb, blk).mean(1)
    if floor is None:
        floor = float(np.percentile(p, 10))
    floor = floor or 1e-12
    db = 10 * np.log10(np.maximum(p, 1e-12) / floor)
    on = db >= THRESH_DB
    out = []
    i = 0
    while i < nb:
        if not on[i]:
            i += 1
            continue
        j = i
        while j < nb and on[j]:
            j += 1
        if (j - i) * BLOCK_S * 1e3 >= MIN_BURST_MS:
            out.append((i * blk / fs, j * blk / fs, float(np.median(db[i:j]))))
        i = j
    return out, float(np.sqrt(floor)), db


def classify(burst_list, dur_s: float, caught: bool) -> str:
    if caught:
        return "hit"
    if not burst_list:
        return "a"
    s, e, _ = max(burst_list, key=lambda b: b[1] - b[0])
    cut = (s <= EDGE_S or e >= dur_s - EDGE_S) and (e - s) * 1e3 < AIR_MS - 0.3
    return "c" if cut else "b"


def reply_template(tid: int, rssi: int = 0x45, a1: int = 0, a2: int = 0) -> bytes:
    """The reply frame this drone sends with telemetry off (hub count 0): only RSSI/A1/A2 vary."""
    body = bytes([0x11, *TXID_B, a1, a2, rssi, 0, tid & 0x1F]) + bytes(10)
    c = d8.crc16(body)
    return body + bytes([c >> 8, c & 0xFF])


def template_corr(iq: np.ndarray, fs: float, tid: int, shift_hz: float = -35e3) -> tuple[float, float]:
    """Presence test with ~190 known bits: normalised correlation of the discriminator output with the
    expected preamble+sync+frame (RSSI byte and CRC excluded, so the value does not need to be known).
    ~0.8 for a clean reply, <= 0.12 measured on noise-only captures. Returns (corr, t_s)."""
    dec = d8.StandardDecoder(fs, shift_hz=shift_hz, cutoff=75e3)
    d = d8.fm_demod(np.convolve(dec._prep(iq), dec.taps, "same"), fs)
    bits = d8.air_bits(reply_template(tid))
    sgn = 2.0 * bits - 1
    sps = fs / d8.BAUD
    known = np.ones(len(bits), bool)
    rb = d8.PRE_SYNC_BITS + 8 * 5  # RSSI byte (frame index 5)
    known[rb: rb + 8] = False
    known[-16:] = False  # CRC depends on RSSI
    n = int(np.ceil(len(bits) * sps))
    t = np.arange(n)
    k = np.minimum((t / sps).astype(int), len(bits) - 1)
    tpl = np.where(known[k], sgn[k], 0.0)
    # remove the carrier: moving mean over one frame
    dm = d - np.convolve(d, np.ones(n) / n, "same")
    if len(dm) < n:
        return 0.0, 0.0
    num = np.correlate(dm, tpl, "valid")
    e = np.convolve(dm ** 2, (tpl != 0).astype(float), "valid")
    c = num / np.sqrt(np.maximum(e, 1e-12) * np.sum(tpl != 0))
    i = int(np.argmax(c))
    return float(c[i]), i / fs


def band_fraction(seg: np.ndarray, fs: float, cfo_hz: float = -35e3, half_bw: float = 70e3) -> float:
    """Share of a segment's power within +-half_bw of the reply carrier: ~0.9+ for the D8 reply,
    ~2*half_bw/fs (0.28 at 500 kS/s) for wideband (WiFi/BLE-like) interference."""
    if len(seg) < 32:
        return 0.0
    sp = np.abs(np.fft.fft((seg - seg.mean()) * np.hanning(len(seg)))) ** 2
    f = np.fft.fftfreq(len(seg), 1 / fs)
    return float(sp[np.abs(f - cfo_hz) <= half_bw].sum() / sp.sum())


def soft_margin(iq: np.ndarray, fs: float, shift_hz: float, t_s: float, raw: bytes, cutoff: float = 75e3) -> dict:
    """Integrate-and-dump soft bits of a decoded frame on its own bit grid (best of +-1 sample),
    normalised by the deviation: eye = min over bits of sign-corrected value, sign errors vs the
    CRC-valid air bits (0 by construction for the stock path, >0 means the margin is negative)."""
    dec = d8.StandardDecoder(fs, shift_hz=shift_hz, cutoff=cutoff)
    d = d8.fm_demod(np.convolve(dec._prep(iq), dec.taps, "same"), fs)
    t0, c, _ = dec._refine(d, t_s * fs)
    ref = d8.air_bits(bytes(raw[: d8.PACKET_BYTES]))
    sgn = 2.0 * ref - 1
    sps = fs / d8.BAUD
    cs = np.concatenate([[0.0], np.cumsum(d)])
    n = np.arange(len(ref))
    a = np.interp(t0 + (n + 0.2) * sps + 0.5, np.arange(len(cs)), cs)
    b = np.interp(t0 + (n + 0.8) * sps + 0.5, np.arange(len(cs)), cs)
    v = ((b - a) / (0.6 * sps) - c) / d8.DEVIATION * sgn
    return {"eye_min": round(float(v.min()), 3), "eye_mean": round(float(v.mean()), 3),
            "eye_p1": round(float(np.percentile(v, 1)), 3), "sign_errors": int(np.sum(v <= 0)), "cfo_hz": c + shift_hz}


def _with_crc(hex18: str) -> bytes:
    b = bytes.fromhex(hex18)[:18]
    c = d8.crc16(b)
    return b + bytes([c >> 8, c & 0xFF])


def relaxed_decode(iq: np.ndarray, fs: float) -> list[dict]:
    """Wider net for uncaught captures: 5 kHz carrier grid, 4 sync errors, all cutoffs, 1-bit CRC fix."""
    x = iq - iq.mean()
    hits = []
    for s in np.arange(-100e3, 60e3 + 1, 5e3):
        if abs(s) + 40e3 > fs / 2:
            continue
        for trk in (16, 32, 64):
            dec = d8.StandardDecoder(fs, shift_hz=float(s), max_sync_errors=4)
            for r in dec.decode(x, fix1=True, track_bits=trk):
                p = r.packet
                if p.crc_ok and p.tx_id == tlm_listen.TXID and p.raw[0] == 0x11:
                    hits.append({"t_ms": round(r.t * 1e3, 3), "shift_hz": float(s), "track": trk,
                                 "cfo_hz": round(float(r.cfo) + float(s)), "sync_errors": r.sync_errors,
                                 "fixed_bit": r.fixed_bit, "hex": p.raw.hex()})
        if hits:
            break
    return hits


def analyse_run(run: str, relaxed: bool = True) -> dict:
    recs = []
    names = sorted(n for n in os.listdir(run) if n.startswith("cap") and n.endswith(".json"))
    floors = []
    for name in names:
        rec = json.load(open(os.path.join(run, name)))
        if rec.get("crc_ok", True):
            floors.append(floor_power(load(run, rec), rec["fs"]))
    run_floor = float(np.median(floors)) if floors else None
    for name in names:
        rec = json.load(open(os.path.join(run, name)))
        if not rec.get("crc_ok", True):
            recs.append({"cap": name, "k": rec.get("k"), "cls": "uart_bad"})
            continue
        iq = load(run, rec)
        fs = rec["fs"]
        dur = len(iq) / fs
        frames = tlm_listen.decode_capture(iq, fs)
        tel = [h for h in frames if h["telemetry"]]
        bl, floor_rms, _ = bursts(iq, fs, run_floor)
        cls = classify(bl, dur, bool(tel))
        corr, tc = template_corr(iq, fs, rec.get("tid") or 0)
        x = iq - iq.mean()
        turn = rec.get("turn_ns", 0) / 1e9
        o = {"cap": name, "k": rec["k"], "ch": rec["ch"], "tid": rec.get("tid"), "sh": rec.get("sh"),
             "g": rec.get("g0"), "turn_us": round(turn * 1e6, 1), "dur_ms": round(dur * 1e3, 3), "cls": cls,
             "floor_rms": round(float(np.sqrt(floor_power(iq, fs))), 1), "run_floor_rms": round(floor_rms, 1),
             "tpl_corr": round(corr, 3), "reply_present": bool(corr >= CORR_PRESENT), "tpl_t_ms": round(tc * 1e3, 3), "peak_i_q": float(max(np.abs(iq.real).max(), np.abs(iq.imag).max())),
             "bursts": [(round(s * 1e3, 2), round(e * 1e3, 2), round(l, 1)) for s, e, l in bl]}
        if bl:
            s, e, lvl = max(bl, key=lambda b: b[1] - b[0])
            seg = x[int(s * fs): int(e * fs)]
            o["burst_rms"] = round(float(np.sqrt(np.mean(np.abs(seg) ** 2))), 1)
            o["band_frac"] = round(band_fraction(seg, fs), 3)
            a_ = np.abs(seg)
            o["env_cv"] = round(float(a_.std() / max(a_.mean(), 1e-9)), 3)  # constant-envelope GFSK ~0.05; clipping/interference higher
            o["snr_db"] = round(lvl, 1)
            o["start_after_unkey_ms"] = round((s + turn) * 1e3, 3)
            o["tail_room_ms"] = round((dur - e) * 1e3, 3)
        if tel:
            h = tel[0]
            o.update(t_ms=h["t_ms"], cfo_hz=h["cfo_hz"], sync_errors=h["sync_errors"], shift_hz=h["shift_hz"])
            o["reply_after_unkey_ms"] = round(h["t_ms"] + turn * 1e3, 3)
            o["margin"] = soft_margin(iq, fs, h["shift_hz"], h["t_ms"] / 1e3, _with_crc(h["hex"]))
        elif relaxed and cls in ("b", "c"):
            o["relaxed"] = relaxed_decode(iq, fs)
        recs.append(o)
    return {"run": os.path.basename(os.path.normpath(run)), "caps": recs}


def _pct(v, q=(0, 5, 50, 95, 100)):
    return [round(float(x), 2) for x in np.percentile(v, q)] if len(v) else []


def summarize(res: dict) -> dict:
    caps = res["caps"]
    cnt = {k: sum(c["cls"] == k for c in caps) for k in ("hit", "a", "b", "c", "uart_bad")}
    hits = [c for c in caps if c["cls"] == "hit"]
    rec = sum(bool(c.get("relaxed")) for c in caps)
    for k in ("a", "b", "c"):
        cnt[k + "_reply"] = sum(c["cls"] == k and c.get("reply_present", False) for c in caps)
    return {"run": res["run"], "n": len(caps), **cnt, "relaxed_recovered": rec,
            "hit_cfo_khz": _pct([c["cfo_hz"] / 1e3 for c in hits]),
            "hit_reply_after_unkey_ms": _pct([c["reply_after_unkey_ms"] for c in hits]),
            "hit_tail_room_ms": _pct([c["tail_room_ms"] for c in hits if "tail_room_ms" in c]),
            "hit_snr_db": _pct([c["snr_db"] for c in hits if "snr_db" in c]),
            "hit_burst_rms": _pct([c["burst_rms"] for c in hits if "burst_rms" in c]),
            "hit_peak_i_q": _pct([c["peak_i_q"] for c in hits]),
            "hit_sync_errors": {e: sum(c["sync_errors"] == e for c in hits) for e in (0, 1, 2)},
            "hit_eye_min": _pct([c["margin"]["eye_min"] for c in hits]),
            "hit_eye_mean": _pct([c["margin"]["eye_mean"] for c in hits]),
            "hit_sign_errors_max": max([c["margin"]["sign_errors"] for c in hits], default=None),
            "hit_env_cv": _pct([c["env_cv"] for c in hits if "env_cv" in c]),
            "hit_band_frac": _pct([c["band_frac"] for c in hits if "band_frac" in c]),
            "hit_tpl_corr": _pct([c["tpl_corr"] for c in hits]),
            "miss_tpl_corr": _pct([c["tpl_corr"] for c in caps if c["cls"] in ("a", "b", "c")]),
            "miss_floor_rms": _pct([c["floor_rms"] for c in caps if c["cls"] == "a"]),
            "miss_peak_i_q": _pct([c["peak_i_q"] for c in caps if c["cls"] == "a"])}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--json", default=None, help="write per-capture results here")
    ap.add_argument("--no-relaxed", action="store_true")
    a = ap.parse_args(argv)
    allres = []
    for run in a.runs:
        res = analyse_run(run, relaxed=not a.no_relaxed)
        allres.append(res)
        print(json.dumps(summarize(res)))
        for c in res["caps"]:
            if c["cls"] != "hit":
                print(f"  {c['cls']} k={c.get('k')} ch={c.get('ch')} tid={c.get('tid')} sh={c.get('sh')} "
                      f"floor={c.get('floor_rms')} corr={c.get('tpl_corr')}@{c.get('tpl_t_ms')} "
                      f"band={c.get('band_frac')} cv={c.get('env_cv')} peak={c.get('peak_i_q')} bursts={c.get('bursts')} "
                      f"relaxed={len(c.get('relaxed', []))}")
    if a.json:
        json.dump(allres, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
