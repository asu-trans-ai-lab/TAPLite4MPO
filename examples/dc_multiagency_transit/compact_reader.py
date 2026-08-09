"""Reader/expander for the compressed schedule contract — ships WITH the
format so the compact store is always consumable (decoder-next-to-encoder
rule; compression must never strand the data).

API
    trips  = load_trips(compact_dir)          # trip_ns_id, pattern, profile, t0_s
    visits = expand_stop_times(compact_dir)   # full per-trip stop times
    tph    = trips_per_hour(compact_dir)      # TAPLite column-pool schema
    cap    = period_capacity(compact_dir, vehicle_capacity=..., links=...)

CLI (writes the TAPLite-consumable files)
    python compact_reader.py build_0_2/compact --out build_0_2/expanded \
           --vehicle-capacity 750

Outputs (schemas match examples/bart_transit_assignment/core/column_pool):
    stop_times_expanded.csv   trip_ns_id, stop_ns_id, stop_sequence,
                              arrival_seconds, departure_seconds
    trips_per_hour.csv        directed_route_id, hour, num_trips
    period_capacity_td.csv    directed_route_id, hour, num_trips,
                              vehicle_capacity, period_capacity
                              (per-ROUTE here; joins to ride links on
                               directed_route_id exactly like the BART engine)
"""
import argparse
import json
import os

import pandas as pd

FILES = ("run_profiles.parquet", "frequency_blocks.parquet",
         "exceptions.parquet")


def _load(compact_dir):
    rp, fb, ex = (pd.read_parquet(os.path.join(compact_dir, f))
                  for f in FILES)
    return rp, fb, ex


def load_trips(compact_dir):
    rp, fb, ex = _load(compact_dir)
    rows = []
    for b in fb.itertuples():
        for k, tid in enumerate(b.trip_ids.split(";")):
            rows.append((tid, b.pattern_id, b.profile_id,
                         b.start_s + k * b.headway_s))
    for e in ex.itertuples():
        rows.append((e.trip_ns_id, e.pattern_id, e.profile_id, e.t0_s))
    return pd.DataFrame(rows, columns=["trip_ns_id", "pattern_id",
                                       "profile_id", "t0_s"])


def expand_stop_times(compact_dir):
    rp, _, _ = _load(compact_dir)
    trips = load_trips(compact_dir)
    pinfo = {r.profile_id: r for r in rp.itertuples()}
    rows = []
    for t in trips.itertuples():
        p = pinfo[t.profile_id]
        for seq, (s, d, a) in enumerate(zip(p.stops, p.dep_off, p.arr_off)):
            rows.append((t.trip_ns_id, s, seq,
                         t.t0_s + a, t.t0_s + d))
    return pd.DataFrame(rows, columns=["trip_ns_id", "stop_ns_id",
                                       "stop_sequence", "arrival_seconds",
                                       "departure_seconds"])


def _route_of_pattern(pattern_id):
    # pattern ids are namespaced "feed:pattern:N"; the route lives on the
    # profile's pattern via stageB trips table when present. Fallback: the
    # pattern id itself is the routing key (stable, join-safe).
    return pattern_id


def trips_per_hour(compact_dir, route_key=_route_of_pattern):
    trips = load_trips(compact_dir)
    trips["hour"] = (trips.t0_s // 3600).astype(int)
    trips["directed_route_id"] = trips.pattern_id.map(route_key)
    return (trips.groupby(["directed_route_id", "hour"], as_index=False)
            .size().rename(columns={"size": "num_trips"}))


def period_capacity(compact_dir, vehicle_capacity=750.0,
                    route_key=_route_of_pattern):
    tph = trips_per_hour(compact_dir, route_key)
    tph["vehicle_capacity"] = float(vehicle_capacity)
    tph["period_capacity"] = tph.num_trips * tph.vehicle_capacity
    return tph


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("compact_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--vehicle-capacity", type=float, default=750.0,
                    help="declared service capacity per vehicle "
                         "(ASSUMPTION - state it; see BART A1 register)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    visits = expand_stop_times(a.compact_dir)
    visits.to_csv(os.path.join(a.out, "stop_times_expanded.csv"), index=False)
    tph = trips_per_hour(a.compact_dir)
    tph.to_csv(os.path.join(a.out, "trips_per_hour.csv"), index=False)
    cap = period_capacity(a.compact_dir, a.vehicle_capacity)
    cap.to_csv(os.path.join(a.out, "period_capacity_td.csv"), index=False)

    man = {"expanded_stop_visits": int(len(visits)),
           "trips": int(visits.trip_ns_id.nunique()),
           "route_hour_rows": int(len(tph)),
           "vehicle_capacity_assumption": a.vehicle_capacity,
           "note": "period_capacity here is per pattern-route-hour; join to "
                   "ride links on directed_route_id as in the BART engine. "
                   "vehicle_capacity is a DECLARED assumption (service "
                   "capacity, not crush)."}
    with open(os.path.join(a.out, "expanded_manifest.json"), "w") as f:
        json.dump(man, f, indent=2)
    print(json.dumps(man, indent=1))


if __name__ == "__main__":
    main()
