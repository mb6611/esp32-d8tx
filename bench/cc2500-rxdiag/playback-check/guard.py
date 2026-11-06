"""Keyed-burst envelope guard for pbcheck.py (no I/O; importable offline).

Bound used: keyed_us (firmware, esp_timer before key() .. after unkey()) =
    key/unkey overhead + engine poll, and the poll is hard-capped in firmware by tmo (CPU cycles).
Worst observed overhead (K 0): 291 us on the first keyed slot after boot (A 290.8, B 291.2, pilot2 243);
later slots 117-130 us. The overhead is NOT hard-bounded by firmware; the margin below is empirical.
"""

LIMIT_US = 444            # bench rule, key to unkey
ABORT_US = 400            # stop the session at any keyed_us above this (stricter than the rule)
OVERHEAD_WORST_US = 291   # worst observed key()+unkey() overhead, first key after boot, K 0
MARGIN_US = 40            # headroom over the worst observed overhead
COUNT_DEFAULT = 6143      # 6144 samples @80 MS/s = 76.8 us
TMO_DEFAULT = 100         # firmware poll cap, us (engine needs 76.8)


class Abort(Exception):
    pass


def engine_us(count):
    return (count + 1) / 80.0


def preflight(count, tmo, km, pwr):
    """Refuse a configuration whose worst case (observed overhead + tmo cap) is not inside the rule."""
    if km != 0:
        raise Abort(f"K {km}: overhead only characterised for K 0")
    if pwr not in (0, 127):
        raise Abort(f"pwr {pwr} not 0/127")
    if engine_us(count) > tmo:
        raise Abort(f"engine {engine_us(count):.1f} us > tmo {tmo} us (would time out)")
    worst = OVERHEAD_WORST_US + tmo
    if worst + MARGIN_US > LIMIT_US:
        raise Abort(f"worst case {worst} us + margin {MARGIN_US} > {LIMIT_US}")
    return worst


def check_keyed(rec):
    """Call after every keyed T. Raises Abort (end session, no further keying) on anything unexpected."""
    if rec.get("hang"):
        raise Abort(f"slot {rec.get('i')}: hang during keyed T")
    k = rec.get("keyed_us")
    if k is None or k <= 0:
        raise Abort(f"slot {rec.get('i')}: no keyed_us reported")
    if k > ABORT_US:
        raise Abort(f"slot {rec.get('i')}: keyed_us {k} > {ABORT_US}")
    if rec.get("ndone") != 1:
        raise Abort(f"slot {rec.get('i')}: engine did not finish (ndone {rec.get('ndone')})")
    if rec.get("pb51") not in (0, 127):
        raise Abort(f"slot {rec.get('i')}: pb51 {rec.get('pb51')} not 0/127")
