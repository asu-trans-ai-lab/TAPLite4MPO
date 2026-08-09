"""BART T1 — hourly supply/demand loading and under/oversupply analysis.

Pipeline:
  1. Reconstruct zone -> BART station-code crosswalk (route ride-link chains
     aligned with GTFS stop sequences; zones tied to route nodes via boarding
     arcs). Writes station_crosswalk.csv.
  2. Load hourly OD demand for the selected dates onto the enumerated path
     columns (equal split across an OD's columns — documented convention),
     accumulate hourly ride-link volumes.
  3. Join hourly supply (period_capacity_td = num_trips x vehicle_capacity 750)
     -> V/C per ride link-hour; classify:
        UNDERSUPPLY  v/c >= 1.00        (demand exceeds offered capacity)
        CROWDED      0.80 <= v/c < 1.00
        BALANCED     0.20 <= v/c < 0.80
        OVERSUPPLY   v/c < 0.20 with service running (empty capacity)
  4. Write analysis/<tag>_link_hour.csv + <tag>_summary.json.

Usage: python bart_supply_demand.py <tag> <date> [<date> ...]
       (dates averaged -> "average day" for the tag, e.g. one weekday)
Demand file override: --demand <path> (same schema: date,hour,o,d,volume)
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BART = os.path.join(HERE, "core")   # repo layout: core/column_pool + core/GTFS
CP = os.path.join(BART, "column_pool")
OUT = os.path.join(HERE, "analysis")
os.makedirs(OUT, exist_ok=True)

VC_UNDER, VC_CROWD, VC_OVER = 1.00, 0.80, 0.20


def build_crosswalk(links):
    """zone_id -> station code, via per-route chain alignment with GTFS.

    directed_route_id '1.1' -> GTFS route_id 1 (int part). A route may carry
    several parallel service-pattern chains (own node ids each); every chain is
    aligned to a GTFS trip with the same stop count."""
    trips = pd.read_csv(os.path.join(BART, "GTFS", "trips.txt"))
    st = pd.read_csv(os.path.join(BART, "GTFS", "stop_times.txt"),
                     usecols=["trip_id", "stop_id", "stop_sequence"])
    st_by_trip = {t: g.sort_values("stop_sequence").stop_id.tolist()
                  for t, g in st.groupby("trip_id")}
    votes = defaultdict(lambda: defaultdict(int))
    for drid, grp in links[links.arc_type == "ride"].groupby("directed_route_id"):
        rid = int(float(drid))
        rtrips = trips[trips.route_id.astype(int) == rid].trip_id
        seqs = [st_by_trip[t] for t in rtrips if t in st_by_trip]
        if not seqs:
            continue
        succ = dict(zip(grp.from_node_id, grp.to_node_id))
        starts = sorted(set(grp.from_node_id) - set(grp.to_node_id))
        for s in starts:
            chain, seen = [s], {s}
            while chain[-1] in succ and succ[chain[-1]] not in seen:
                chain.append(succ[chain[-1]])
                seen.add(chain[-1])
            match = [q for q in seqs if len(q) == len(chain)]
            if not match:
                continue
            # majority stop-sequence among same-length trips
            key = max(set(map(tuple, match)), key=lambda k: match.count(list(k)))
            node2code = dict(zip(chain, key))
            board = links[(links.arc_type == "non_ride")
                          & links.to_node_id.isin(node2code)
                          & (links.from_node_id <= 50)]
            for _, r in board.iterrows():
                votes[int(r.from_node_id)][node2code[int(r.to_node_id)]] += 1
    rows = []
    for z in sorted(votes):
        code, n = max(votes[z].items(), key=lambda kv: kv[1])
        conflict = len(votes[z]) > 1
        rows.append({"zone_id": z, "station_code": code,
                     "conflict": conflict, "votes": dict(votes[z])})
    cw = pd.DataFrame(rows)
    cw[["zone_id", "station_code", "conflict"]].to_csv(
        os.path.join(HERE, "station_crosswalk.csv"), index=False)
    return cw


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tag, dates = args[0], args[1:]
    dem_path = os.path.join(CP, "demand_td.csv")
    if "--demand" in sys.argv:
        dem_path = sys.argv[sys.argv.index("--demand") + 1]

    links = pd.read_csv(os.path.join(CP, "link.csv"))
    cols = pd.read_csv(os.path.join(CP, "columns.csv"))
    cap = pd.read_csv(os.path.join(CP, "period_capacity_td.csv"))

    cw = build_crosswalk(links)
    n_conf = int(cw.conflict.sum()) if len(cw) else -1
    print(f"crosswalk: {len(cw)} zones mapped, {n_conf} conflicts")

    # columns -> per-OD path list with equal weights
    cols["links"] = cols.link_sequence.str.split(";")
    n_paths = cols.groupby(["o_zone_id", "d_zone_id"]).path_id.transform("count")
    cols["weight"] = 1.0 / n_paths

    dem = pd.read_csv(dem_path)
    dem = dem[dem.date.isin(dates)]
    if dem.empty:
        raise SystemExit(f"no demand rows for dates {dates}")
    n_days = dem.date.nunique()
    print(f"{tag}: {n_days} day(s), riders/day {dem.volume.sum()/n_days:,.0f}")
    hod = (dem.groupby(["hour", "o_zone_id", "d_zone_id"]).volume.sum()
           / n_days).reset_index()

    # loading: OD-hour volume x column weight onto every ride link of the path
    m = hod.merge(cols[["o_zone_id", "d_zone_id", "links", "weight"]],
                  on=["o_zone_id", "d_zone_id"], how="left")
    unmatched = m[m.weight.isna()].volume.sum()
    m = m.dropna(subset=["weight"])
    m["load"] = m.volume * m.weight
    e = m[["hour", "load", "links"]].explode("links")
    e["link_id"] = e.links.astype(int)
    linkvol = e.groupby(["link_id", "hour"], as_index=False).load.sum()

    ride = links[links.arc_type == "ride"][
        ["link_id", "directed_route_id", "route_short_name",
         "from_node_id", "to_node_id"]]
    lv = ride.merge(linkvol, on="link_id", how="left").fillna({"load": 0.0})
    lv = lv.merge(cap[["link_id", "hour", "num_trips", "period_capacity"]],
                  on=["link_id", "hour"], how="left")
    lv = lv.dropna(subset=["period_capacity"])
    served = lv[lv.num_trips > 0].copy()
    served["vc"] = served.load / served.period_capacity
    served["state"] = np.select(
        [served.vc >= VC_UNDER, served.vc >= VC_CROWD, served.vc >= VC_OVER],
        ["UNDERSUPPLY", "CROWDED", "BALANCED"], default="OVERSUPPLY")
    served["empty_seats"] = (served.period_capacity - served.load).clip(lower=0)
    served["excess_riders"] = (served.load - served.period_capacity).clip(lower=0)

    out_csv = os.path.join(OUT, f"{tag}_link_hour.csv")
    served.to_csv(out_csv, index=False)

    states = served.state.value_counts().to_dict()
    worst = served.nlargest(10, "vc")[
        ["route_short_name", "from_node_id", "to_node_id", "hour", "load",
         "period_capacity", "vc"]]
    summary = {
        "tag": tag, "dates": dates, "days_averaged": n_days,
        "riders_per_day": round(float(dem.volume.sum()) / n_days, 0),
        "unmatched_od_riders_per_day": round(float(unmatched) / n_days, 1),
        "link_hours_served": int(len(served)),
        "state_counts": states,
        "state_shares": {k: round(v / len(served), 4) for k, v in states.items()},
        "peak_vc": round(float(served.vc.max()), 3),
        "excess_riders_per_day": round(float(served.excess_riders.sum()), 0),
        "empty_seat_hours_per_day": round(float(served.empty_seats.sum()), 0),
        "capacity_note": "supply = period_capacity_td (FY2025 timetable era "
                         "2025-01-13..2025-04-01, vehicle_capacity 750/train); "
                         "historical demand years are loaded on THIS fixed "
                         "supply = counterfactual under/oversupply analysis",
        "loading_convention": "equal split across the OD's enumerated columns; "
                              "no capacity constraint (V/C diagnostic, not "
                              "capacitated assignment)",
    }
    with open(os.path.join(OUT, f"{tag}_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: summary[k] for k in
                      ("riders_per_day", "state_shares", "peak_vc",
                       "excess_riders_per_day", "empty_seat_hours_per_day")},
                     indent=1))
    print("worst link-hours:")
    print(worst.to_string(index=False))
    print(f"-> {out_csv}")


if __name__ == "__main__":
    main()
