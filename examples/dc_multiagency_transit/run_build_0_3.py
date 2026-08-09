"""Build 0.3 — NVTA_S1_FULL_MULTIAGENCY: all GTFS_DC feeds, one AM snapshot.

Per feed:
  1. resolve a canonical WEDNESDAY service set (calendar.txt wednesday=1 valid
     at the span midpoint; else the calendar_dates Wednesday with most active
     services) — never guessed from filenames;
  2. if frequencies.txt exists, PRE-EXPAND it additively into a temp feed copy
     (exact_times=1 -> gtfs_frequency_exact trips; exact_times=0 -> synthetic
     instances labeled gtfs_frequency_synthetic; template trips whose id is
     referenced by frequencies are replaced by their instances) — the tool's
     Stage B is untouched and consumes plain stop_times;
  3. Stage B snapshot (route types 0/1/2/3), window 06:30-09:00;
  4. compact store (lossless-verified factorization).

Aggregate manifest: per-agency vintage/service/trips/patterns/frequency
provenance/compression table -> build_0_3/multiagency_manifest.json
"""
import json
import os
import re
import shutil
import sys
import tempfile

import pandas as pd

TOOL = r"C:\source_codes\0_source_code_new\transit_schedule_column_generation_assignment"
ROOT = os.path.join(TOOL, "GTFS_DC")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "build_0_3")
SCRATCH = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()),
                       "dc_0_3_expanded")
W_S, W_E = 390 * 60, 540 * 60
ROUTE_TYPES = ("0", "1", "2", "3")

sys.path.insert(0, TOOL)
sys.path.insert(0, HERE)
from gtfs2gmns_pkg.schedule.normalize import build_schedule_snapshot
import compact_store


def resolve_wednesday_services(feed):
    cal = os.path.join(feed, "calendar.txt")
    cds = os.path.join(feed, "calendar_dates.txt")
    if os.path.exists(cal):
        c = pd.read_csv(cal, dtype=str)
        if "wednesday" in c.columns and len(c):
            c = c[c.wednesday == "1"]
            if len(c):
                mid = str(int((c.start_date.astype(int).min()
                               + c.end_date.astype(int).max()) // 2))
                ok = c[(c.start_date <= mid) & (c.end_date >= mid)]
                base = set((ok if len(ok) else c).service_id)
                return base, "calendar.txt wednesday=1"
    if os.path.exists(cds):
        cd = pd.read_csv(cds, dtype=str)
        cd["dt"] = pd.to_datetime(cd.date, format="%Y%m%d", errors="coerce")
        wed = cd[(cd.dt.dt.dayofweek == 2) & (cd.exception_type == "1")]
        if len(wed):
            best = wed.groupby("date").service_id.nunique().idxmax()
            return set(wed[wed.date == best].service_id), \
                f"calendar_dates {best}"
    return None, "NO SERVICE RESOLUTION"


def clean_feed(feed, dst):
    """Copy feed with GTFS-standard time interpolation: non-timepoint rows
    (blank arrival/departure) are linearly interpolated between timepoints;
    trips with unusable endpoints are dropped (counted). stop_sequence made
    integer. Returns (n_interpolated_rows, n_dropped_trips)."""
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(feed):
        src_f = os.path.join(feed, f)
        if f != "stop_times.txt" and os.path.isfile(src_f):
            try:
                shutil.copy2(src_f, os.path.join(dst, f))
            except OSError:
                pass    # non-essential sidecar; GTFS core is read explicitly
    st = pd.read_csv(os.path.join(feed, "stop_times.txt"), dtype=str)

    def sec(t):
        try:
            h, m, s = str(t).split(":")
            return int(h) * 3600 + int(m) * 60 + int(s)
        except Exception:
            return None

    def hms(x):
        x = int(round(x))
        return "%02d:%02d:%02d" % (x // 3600, (x % 3600) // 60, x % 60)

    st["seq"] = pd.to_numeric(st.stop_sequence, errors="coerce")
    st = st[st.seq.notna()].copy()
    st["seq"] = st.seq.astype(int)
    st["a"] = st.arrival_time.map(sec)
    st["d"] = st.departure_time.map(sec)
    st["a"] = st.a.fillna(st.d)
    st["d"] = st.d.fillna(st.a)
    n_interp, drop_trips = 0, []
    out = []
    for tid, g in st.groupby("trip_id", sort=False):
        g = g.sort_values("seq").copy()
        if pd.isna(g.a.iloc[0]) or pd.isna(g.a.iloc[-1]):
            drop_trips.append(tid)
            continue
        if g.a.isna().any():
            n_interp += int(g.a.isna().sum())
            g["a"] = g.a.astype(float).interpolate()
            g["d"] = g.d.astype(float).interpolate()
        g["arrival_time"] = g.a.map(hms)
        g["departure_time"] = g.d.map(hms)
        g["stop_sequence"] = g.seq
        out.append(g)
    res = pd.concat(out) if out else st.iloc[0:0]
    res.drop(columns=["seq", "a", "d"]).to_csv(
        os.path.join(dst, "stop_times.txt"), index=False)
    if drop_trips:
        tr = pd.read_csv(os.path.join(dst, "trips.txt"), dtype=str)
        tr[~tr.trip_id.isin(drop_trips)].to_csv(
            os.path.join(dst, "trips.txt"), index=False)
    return n_interp, len(drop_trips)


def expand_frequencies(feed, dst):
    """Copy feed to dst, instantiating frequencies.txt trips."""
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(feed):
        if f != "frequencies.txt":
            shutil.copy2(os.path.join(feed, f), os.path.join(dst, f))
    fr = pd.read_csv(os.path.join(feed, "frequencies.txt"), dtype=str)
    trips = pd.read_csv(os.path.join(feed, "trips.txt"), dtype=str)
    st = pd.read_csv(os.path.join(feed, "stop_times.txt"), dtype=str)

    def sec(t):
        try:
            h, m, s = str(t).split(":")
            return int(h) * 3600 + int(m) * 60 + int(s)
        except Exception:
            return None

    def hms(x):
        return "%02d:%02d:%02d" % (x // 3600, (x % 3600) // 60, x % 60)

    tmpl_ids = set(fr.trip_id)
    new_trips, new_st = [], []
    n_exact = n_synth = 0
    st = st.assign(_seq=pd.to_numeric(st.stop_sequence, errors="coerce"))
    st_by_trip = {t: g.sort_values("_seq")
                  for t, g in st[st.trip_id.isin(tmpl_ids)].groupby("trip_id")}
    for r in fr.itertuples():
        g = st_by_trip.get(r.trip_id)
        if g is None:
            continue
        base = trips[trips.trip_id == r.trip_id]
        if base.empty:
            continue
        base = base.iloc[0]
        g = g.copy()
        g["dep_s"] = g.departure_time.map(sec)
        g["arr_s"] = g.arrival_time.map(sec)
        t0 = g.dep_s.iloc[0]
        s, e, h = sec(r.start_time), sec(r.end_time), int(r.headway_secs)
        exact = getattr(r, "exact_times", "0") == "1"
        k = 0
        t = s
        while t < e:
            tid = f"{r.trip_id}#f{k}"
            row = base.to_dict()
            row["trip_id"] = tid
            new_trips.append(row)
            for _, v in g.iterrows():
                new_st.append({**{c: v[c] for c in st.columns
                                  if c in v.index},
                               "trip_id": tid,
                               "arrival_time": hms(int(v.arr_s - t0 + t)),
                               "departure_time": hms(int(v.dep_s - t0 + t))})
            n_exact += int(exact)
            n_synth += int(not exact)
            k += 1
            t += h
    keep_trips = trips[~trips.trip_id.isin(tmpl_ids)]
    keep_st = st[~st.trip_id.isin(tmpl_ids)]
    pd.concat([keep_trips, pd.DataFrame(new_trips)]).to_csv(
        os.path.join(dst, "trips.txt"), index=False)
    pd.concat([keep_st, pd.DataFrame(new_st)]).to_csv(
        os.path.join(dst, "stop_times.txt"), index=False)
    return n_exact, n_synth


def vintage_of(name):
    m = re.search(r"(20\d{2})[_-]?(\d{2})?", name)
    return (m.group(1) + ("-" + m.group(2) if m.group(2) else "")) if m \
        else "unknown"


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for i, feed_name in enumerate(sorted(os.listdir(ROOT))):
        feed = os.path.join(ROOT, feed_name)
        if not os.path.isdir(feed):
            continue
        row = {"feed": feed_name, "vintage": vintage_of(feed_name)}
        try:
            svcs, how = resolve_wednesday_services(feed)
            row["service_resolution"] = how
            if svcs is None:
                row["status"] = "SKIPPED - no service resolution"
                rows.append(row)
                continue
            clean_dst = os.path.join(SCRATCH, "clean_" + feed_name)
            ni, nd = clean_feed(feed, clean_dst)
            row["times_interpolated"], row["trips_dropped_no_times"] = ni, nd
            src = clean_dst
            row["freq_exact_trips"] = row["freq_synth_trips"] = 0
            fpath = os.path.join(feed, "frequencies.txt")
            if os.path.exists(fpath) and len(
                    pd.read_csv(fpath, dtype=str)) > 0:
                dst = os.path.join(SCRATCH, feed_name)
                ne, ns = expand_frequencies(clean_dst, dst)
                row["freq_exact_trips"], row["freq_synth_trips"] = ne, ns
                src = dst
            ns_tag = f"f{i:02d}"
            bdir = os.path.join(OUT, f"stageB_{i:02d}")
            man = build_schedule_snapshot(src, ns_tag, bdir, svcs,
                                          ROUTE_TYPES, W_S, W_E)
            row.update({"n_trips": man["n_trips"],
                        "n_stop_visits": man["n_stop_visits"],
                        "n_patterns": man["n_service_patterns"],
                        "n_excluded": man["n_excluded"]})
            if man["n_trips"] > 0:
                rep = compact_store.main(bdir, os.path.join(
                    OUT, f"compact_{i:02d}"))
                row["compact_ratio"] = rep["ratio"]
                row["freq_blocks"] = rep["frequency_blocks"]
            row["status"] = "OK"
        except Exception as e:
            row["status"] = f"FAILED: {type(e).__name__}: {e}"
        rows.append(row)
        print(row)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, "agency_inventory.csv"), index=False)
    ok = df[df.status == "OK"]
    man = {
        "build": "0.3 NVTA_S1_FULL_MULTIAGENCY (stage B + compact per feed)",
        "window": "06:30-09:00 Wednesday-service snapshot per feed",
        "feeds_total": int(len(df)), "feeds_ok": int(len(ok)),
        "trips_total": int(ok.n_trips.sum()) if len(ok) else 0,
        "stop_visits_total": int(ok.n_stop_visits.sum()) if len(ok) else 0,
        "frequency_trips_instantiated":
            int(ok.freq_exact_trips.sum() + ok.freq_synth_trips.sum())
            if len(ok) else 0,
        "vintage_warning": "feeds span 2019-2021+; NEVER present the merged "
                           "snapshot as a single coherent date "
                           "(TODO.md I-1); per-feed vintages in "
                           "agency_inventory.csv",
        "failures": df[df.status.str.startswith("FAILED")].feed.tolist(),
        "skipped": df[df.status.str.startswith("SKIPPED")].feed.tolist(),
    }
    with open(os.path.join(OUT, "multiagency_manifest.json"), "w") as f:
        json.dump(man, f, indent=2)
    print(json.dumps(man, indent=1))


if __name__ == "__main__":
    main()
