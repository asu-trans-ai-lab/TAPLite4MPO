"""KPI4MPO/NPO -- the starter evaluation layer.

"The kernels compute. KPI4MPO/NPO decides what the computations mean." This module
turns a finished assignment run (any kernel run folder -- it does NOT depend on
TAPCI) into decision-ready KPIs, KPI deltas for base/build comparison, and a
weighted objective usable as an optimization goal or an RL reward.

MVP = 10 core KPIs. SIX are produced directly from a TAPLite run's output files
today; TWO are offered as clearly-labeled proxies (only when you pass the factor);
TWO need an external tool and return None with a stated source. Nothing is faked.

    from dtalite_qa import kpi
    k = kpi.compute(run_dir)                       # dict of the 10 KPIs
    d = kpi.compare(base_dir, build_dir)           # per-KPI base/build/delta/pct
    r = kpi.objective(k, {"vht_hours": 1.0})       # scalar (min VHT) reward/objective
"""
import csv as _csv
import os

from . import manifest as _manifest

# name -> (unit, source, available_today)
MVP_KPIS = {
    "vmt_miles":              ("veh-miles",  "link_performance",   True),
    "vht_hours":              ("veh-hours",  "link_performance",   True),
    "total_delay_hours":      ("veh-hours",  "link_performance",   True),
    "avg_speed_mph":          ("mph",        "link_performance",   True),
    "max_vc":                 ("ratio",      "link_performance",   True),
    "od_skim_time_min":       ("min (vol-wt)", "od_performance",   True),
    "co2_proxy_kg":           ("kg (proxy)", "VMT x factor",       "proxy"),
    "person_delay_hours":     ("person-hrs (proxy)", "delay x occ", "proxy"),
    "bottleneck_duration_hours": ("hours",   "DRC/QVDF (external)", False),
    "accessibility_to_jobs":  ("jobs",       "GTFS/accessibility (external)", False),
}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _link_kpis(run_dir):
    """(total_delay_hours, max_vc) from link_performance in one pass."""
    p = os.path.join(run_dir, "link_performance.csv")
    if not os.path.exists(p):
        return None, None
    delay_veh_min = 0.0
    max_vc = 0.0
    with open(p, newline="", encoding="utf-8-sig") as f:
        for r in _csv.DictReader(f):
            vol = _f(r.get("volume")) or 0.0
            tt = _f(r.get("travel_time"))
            fftt = _f(r.get("vdf_fftt"))
            if vol > 0 and tt is not None and fftt is not None and tt > fftt:
                delay_veh_min += vol * (tt - fftt)
            vc = _f(r.get("doc"))
            if vol > 0.5 and vc is not None and vc > max_vc:
                max_vc = vc
    return round(delay_veh_min / 60.0, 1), round(max_vc, 4)


def _od_skim_mean(run_dir):
    """Volume-weighted mean congested OD travel time (minutes)."""
    p = os.path.join(run_dir, "od_performance.csv")
    if not os.path.exists(p):
        return None
    num = den = 0.0
    with open(p, newline="", encoding="utf-8-sig") as f:
        for r in _csv.DictReader(f):
            vol = _f(r.get("volume")) or 0.0
            tt = _f(r.get("total_congestion_travel_time"))
            if vol > 0 and tt is not None:
                num += vol * tt
                den += vol
    return round(num / den, 4) if den > 0 else None


def compute(run_dir, co2_kg_per_mile=None, occupancy=None):
    """Compute the 10 MVP KPIs for a finished run folder.

    ``co2_kg_per_mile`` and ``occupancy`` unlock the two PROXY KPIs (co2_proxy_kg,
    person_delay_hours); left None they stay None (honest -- a proxy is opt-in). The
    two external KPIs are always None here (source noted in :data:`MVP_KPIS`).
    """
    moe = _manifest._moe_from_link_performance(run_dir) or {}
    delay, max_vc = _link_kpis(run_dir)
    vmt = moe.get("vmt")
    k = {
        "vmt_miles": vmt,
        "vht_hours": moe.get("vht"),
        "total_delay_hours": delay,
        "avg_speed_mph": moe.get("mean_speed_mph"),
        "max_vc": max_vc,
        "od_skim_time_min": _od_skim_mean(run_dir),
        "co2_proxy_kg": round(vmt * co2_kg_per_mile, 1)
        if (vmt is not None and co2_kg_per_mile) else None,
        "person_delay_hours": round(delay * occupancy, 1)
        if (delay is not None and occupancy) else None,
        "bottleneck_duration_hours": None,   # external: DRC/QVDF
        "accessibility_to_jobs": None,       # external: GTFS/accessibility
    }
    return k


def compare(base_run, build_run, **kw):
    """Per-KPI base/build/delta/pct between two run folders. Only KPIs numeric in
    BOTH runs get a delta; others report the available values with delta=None."""
    b, c = compute(base_run, **kw), compute(build_run, **kw)
    out = {}
    for name in MVP_KPIS:
        bv, cv = b.get(name), c.get(name)
        rec = {"base": bv, "build": cv, "delta": None, "pct": None}
        if isinstance(bv, (int, float)) and isinstance(cv, (int, float)):
            rec["delta"] = round(cv - bv, 4)
            rec["pct"] = round((cv - bv) / bv * 100.0, 3) if bv else None
        out[name] = rec
    return out


def objective(kpis, weights):
    """Weighted sum over the KPIs named in ``weights`` (skips None values).

    Use as an optimization objective or an RL reward. Convention: positive weight =
    the KPI counts positively; to MINIMIZE VHT use a positive weight and negate/rank
    accordingly, or pass a negative weight to reward reductions. Returns a float.
    """
    total = 0.0
    for name, w in weights.items():
        v = kpis.get(name)
        if isinstance(v, (int, float)):
            total += w * v
    return round(total, 4)


def available(kpis):
    """The subset of KPIs actually produced (non-None) -- for reporting coverage."""
    return {k: v for k, v in kpis.items() if v is not None}


# KPIs that ADD across regions (extensive); the rest are intensive and must NOT sum.
EXTENSIVE = ("vmt_miles", "vht_hours", "total_delay_hours",
             "co2_proxy_kg", "person_delay_hours")


def aggregate(kpi_dicts):
    """Combine per-region KPIs into system-of-systems KPIs, correctly by KIND:

    extensive KPIs (VMT/VHT/delay/CO2/person-delay) SUM; ``max_vc`` is the MAX;
    ``avg_speed_mph`` is recomputed as total VMT / total VHT (you cannot average
    average speeds); ``od_skim_time_min`` is a simple mean of the available regions;
    the two external KPIs stay None. Missing values are skipped, not zeroed.
    """
    ks = list(kpi_dicts)
    agg = {}
    for name in EXTENSIVE:
        vals = [d.get(name) for d in ks if isinstance(d.get(name), (int, float))]
        agg[name] = round(sum(vals), 4) if vals else None
    vcs = [d.get("max_vc") for d in ks if isinstance(d.get("max_vc"), (int, float))]
    agg["max_vc"] = max(vcs) if vcs else None
    vmt, vht = agg.get("vmt_miles"), agg.get("vht_hours")
    agg["avg_speed_mph"] = round(vmt / vht, 2) if (vmt and vht) else None
    sk = [d.get("od_skim_time_min") for d in ks
          if isinstance(d.get("od_skim_time_min"), (int, float))]
    agg["od_skim_time_min"] = round(sum(sk) / len(sk), 4) if sk else None
    agg["bottleneck_duration_hours"] = None
    agg["accessibility_to_jobs"] = None
    return agg
