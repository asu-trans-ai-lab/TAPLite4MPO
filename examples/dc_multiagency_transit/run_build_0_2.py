"""Build 0.2 — NVTA_S1_WMATA_ALL: rail + bus, one weekday snapshot.

Drives the existing gtfs2gmns_pkg stages with route_types ("1","3") —
NO modification to the tool (P2: the frozen rail golden path is untouched;
the generalized trip loader lives HERE, additively).

Snapshot: WMATA 2020-04 feed, services active Wed 2020-04-15 = {42,65,66,67}
(COVID-reduced schedule — declared, not hidden), AM window 06:30-09:00.

Outputs -> build_0_2/: stageA/, stageB/, eventgraph manifest with arc counts,
rail-golden-preservation check, and rail-bus transfer-station evidence.
"""
import json
import os
import sys
from collections import Counter

import pandas as pd

TOOL = r"C:\source_codes\0_source_code_new\transit_schedule_column_generation_assignment"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "build_0_2")
FEED = os.path.join(TOOL, "GTFS_DC", "1_WMATA_202004")
SERVICES = {"42", "65", "66", "67"}
ROUTE_TYPES = ("1", "3")          # subway + bus
W_S, W_E = 390, 540               # minutes, 06:30-09:00

sys.path.insert(0, TOOL)
sys.path.insert(0, os.path.join(TOOL, "prototype"))
from gtfs2gmns_pkg.audit.inventory import audit_gtfs_supply
from gtfs2gmns_pkg.schedule.normalize import build_schedule_snapshot
import event_graph
from config import BASE_CONFIG


def load_trips_multimode(feed_path, service_ids, t0, t1, route_types):
    """Generalized (additive) version of event_graph.load_rail_trips:
    any route_type set, any service_id set. Returns (trips, trip_modes)."""
    routes = pd.read_csv(os.path.join(feed_path, "routes.txt"), dtype=str)
    keep_routes = routes[routes["route_type"].isin(route_types)]
    rmode = dict(zip(keep_routes["route_id"], keep_routes["route_type"]))
    trips = pd.read_csv(os.path.join(feed_path, "trips.txt"), dtype=str)
    trips = trips[trips["service_id"].isin(service_ids)
                  & trips["route_id"].isin(rmode)]
    stops = pd.read_csv(os.path.join(feed_path, "stops.txt"), dtype=str)
    name = dict(zip(stops["stop_id"], stops["stop_name"]))
    st = pd.read_csv(os.path.join(feed_path, "stop_times.txt"), dtype=str,
                     usecols=["trip_id", "arrival_time", "departure_time",
                              "stop_id", "stop_sequence"])
    st = st.merge(trips[["trip_id", "route_id", "direction_id"]], on="trip_id")
    st["stop_sequence"] = st["stop_sequence"].astype(int)
    st["arr_min"] = st["arrival_time"].map(event_graph._hms_to_min)
    st["dep_min"] = st["departure_time"].map(event_graph._hms_to_min)
    out, modes = [], []
    for trip_id, g in st.groupby("trip_id"):
        g = g.sort_values("stop_sequence")
        if g["dep_min"].min() > t1 or g["arr_min"].max() < t0:
            continue
        out.append(event_graph.TripSched(
            trip_id, g["route_id"].iloc[0], g["direction_id"].iloc[0],
            tuple(name[s] for s in g["stop_id"]),
            tuple(g["arr_min"]), tuple(g["dep_min"])))
        modes.append(rmode[g["route_id"].iloc[0]])
    order = sorted(range(len(out)), key=lambda i: out[i].dep[0])
    return [out[i] for i in order], [modes[i] for i in order]


def main():
    os.makedirs(OUT, exist_ok=True)

    print("== Stage A: audit (rail + bus) ==")
    manA = audit_gtfs_supply(
        os.path.join(TOOL, "GTFS_DC"), os.path.join(OUT, "stageA"),
        W_S, W_E, included_feeds=["1_WMATA_202004"],
        service_ids={"1_WMATA_202004": SERVICES},
        supported_route_types=ROUTE_TYPES)
    print(json.dumps({k: manA[k] for k in
                      ("raw_trips_total", "included_trips_total",
                       "gate_pass")}, indent=1))

    print("== Stage B: schedule snapshot ==")
    manB = build_schedule_snapshot(
        FEED, "wmata", os.path.join(OUT, "stageB"), SERVICES,
        ROUTE_TYPES, W_S * 60, W_E * 60)

    print("== Stage C/D: multimode event graph ==")
    trips, modes = load_trips_multimode(FEED, SERVICES, W_S, W_E, ROUTE_TYPES)
    n_rail = sum(1 for m in modes if m == "1")
    n_bus = sum(1 for m in modes if m == "3")
    cfg = dict(BASE_CONFIG)
    cfg.update({"sched_start": W_S, "sched_end": W_E})
    g = event_graph.EventGraph(trips, cfg)
    tags = Counter(t for arcs in g.adj for (_v, _c, t) in arcs)

    # rail-bus interchange evidence (name-matched stations, both modes)
    rail_st = set(s for t, m in zip(trips, modes) if m == "1"
                  for s in t.stations)
    bus_st = set(s for t, m in zip(trips, modes) if m == "3"
                 for s in t.stations)
    shared = rail_st & bus_st

    # P2 anchor: the rail-only subset inside this build must equal the golden
    golden_ok = (n_rail == 138)

    man = {
        "build": "0.2 NVTA_S1_WMATA_ALL",
        "snapshot": "WMATA 2020-04, services {42,65,66,67} (Wed 2020-04-15, "
                    "COVID-reduced schedule - declared), window 06:30-09:00",
        "route_types": list(ROUTE_TYPES),
        "trips": {"rail": n_rail, "bus": n_bus, "total": len(trips)},
        "stop_visits": sum(len(t.stations) for t in trips),
        "stations": len(g.stations),
        "event_nodes": g.n_nodes,
        "arcs_by_tag": dict(tags),
        "total_event_arcs": sum(tags.values()),
        "rail_golden_preserved": golden_ok,
        "rail_bus_shared_stations_name_matched": len(shared),
        "transfer_matching_limitation":
            "transfers connect visits at NAME-matched stations only; "
            "rail-bus interchange via distinct stop names (street-corner bus "
            "stops vs station names) is NOT captured -> proximity-based "
            "stop matching is the declared next step for the transfer "
            "contract (transit_stop_node / transfer_link tables)",
        "stageA_gate_pass": bool(manA["gate_pass"]),
    }
    with open(os.path.join(OUT, "build_0_2_manifest.json"), "w") as f:
        json.dump(man, f, indent=2)
    print(json.dumps(man, indent=1))


if __name__ == "__main__":
    main()
