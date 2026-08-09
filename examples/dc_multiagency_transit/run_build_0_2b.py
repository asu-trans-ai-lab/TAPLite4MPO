"""Build 0.2b — the rail-bus TRANSFER CONTRACT + connected multimode graph.

0.2 finding: 0 name-matched rail-bus interchange stations (bus stops carry
street-corner names). Fix, as a declared contract:

  1. transfer_stop_match.csv — bus stops within RADIUS_M of a rail station
     platform (haversine on stops.txt coords), the proximity match table.
  2. Loader aliasing: matched bus stop names -> the rail station name, so the
     event graph's station-based transfer arcs connect the modes. Tool code
     remains untouched; the alias map is data, not code.
  3. Rebuild the graph; prove connectivity with an extracted rail->bus path
     (Gate-0 "Show Me the Path" evidence, transfer trip type).

Usage: python run_build_0_2b.py
"""
import heapq
import json
import os
import sys
from collections import Counter

import numpy as np
import pandas as pd

TOOL = r"C:\source_codes\0_source_code_new\transit_schedule_column_generation_assignment"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "build_0_2")
FEED = os.path.join(TOOL, "GTFS_DC", "1_WMATA_202004")
SERVICES = {"42", "65", "66", "67"}
W_S, W_E = 390, 540
RADIUS_M = 200.0

sys.path.insert(0, TOOL)
sys.path.insert(0, os.path.join(TOOL, "prototype"))
import event_graph
from config import BASE_CONFIG
from run_build_0_2 import load_trips_multimode


def hav_m(lon1, lat1, lon2, lat2):
    R = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = (np.sin((p2 - p1) / 2) ** 2
         + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2)
    return 2 * R * np.arcsin(np.sqrt(a))


def build_match_table():
    stops = pd.read_csv(os.path.join(FEED, "stops.txt"), dtype=str)
    stops["lat"] = stops.stop_lat.astype(float)
    stops["lon"] = stops.stop_lon.astype(float)
    routes = pd.read_csv(os.path.join(FEED, "routes.txt"), dtype=str)
    trips = pd.read_csv(os.path.join(FEED, "trips.txt"), dtype=str)
    st = pd.read_csv(os.path.join(FEED, "stop_times.txt"), dtype=str,
                     usecols=["trip_id", "stop_id"])
    rmode = dict(zip(routes.route_id, routes.route_type))
    trips["mode"] = trips.route_id.map(rmode)
    tmode = dict(zip(trips.trip_id, trips["mode"]))
    st["mode"] = st.trip_id.map(tmode)
    rail_ids = set(st[st["mode"] == "1"].stop_id)
    bus_ids = set(st[st["mode"] == "3"].stop_id)
    rail = stops[stops.stop_id.isin(rail_ids)]
    bus = stops[stops.stop_id.isin(bus_ids)]
    rows = []
    for _, rs in rail.iterrows():
        d = hav_m(bus.lon.to_numpy(), bus.lat.to_numpy(), rs.lon, rs.lat)
        near = bus[d <= RADIUS_M]
        for (_, bs), dist in zip(near.iterrows(), d[d <= RADIUS_M]):
            rows.append({"bus_stop_id": bs.stop_id,
                         "bus_stop_name": bs.stop_name,
                         "rail_station": rs.stop_name,
                         "distance_m": round(float(dist), 1)})
    m = (pd.DataFrame(rows).sort_values("distance_m")
         .drop_duplicates("bus_stop_id"))       # each bus stop -> nearest rail
    m.to_csv(os.path.join(OUT, "transfer_stop_match.csv"), index=False)
    return m


def dijkstra_path(g, src_nodes, dst_stations, trips, modes):
    dist = {u: 0.0 for u in src_nodes}
    prev = {}
    pq = [(0.0, u) for u in src_nodes]
    target = None
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, 1e18):
            continue
        kind, ti, k = g.node_info[u]
        if kind == "A" and trips[ti].stations[k] in dst_stations:
            target = u
            break
        for v, c, tag in g.adj[u]:
            nd = d + c
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                prev[v] = (u, tag)
                heapq.heappush(pq, (nd, v))
    if target is None:
        return None
    path = []
    u = target
    while u in prev:
        p, tag = prev[u]
        kind, ti, k = g.node_info[u]
        path.append((tag, kind, trips[ti].stations[k],
                     modes[ti], trips[ti].route_id))
        u = p
    return list(reversed(path))


def main():
    match = build_match_table()
    alias = dict(zip(match.bus_stop_name, match.rail_station))
    print(f"transfer contract: {len(match)} bus stops matched to "
          f"{match.rail_station.nunique()} rail stations (<= {RADIUS_M} m)")

    trips, modes = load_trips_multimode(FEED, SERVICES, W_S, W_E, ("1", "3"))
    # apply the alias map (data-level, tool untouched)
    trips = [event_graph.TripSched(
        t.trip_id, t.route_id, t.direction_id,
        tuple(alias.get(s, s) for s in t.stations), t.arr, t.dep)
        for t in trips]

    cfg = dict(BASE_CONFIG)
    cfg.update({"sched_start": W_S, "sched_end": W_E})
    g = event_graph.EventGraph(trips, cfg)
    tags = Counter(t for arcs in g.adj for (_v, _c, t) in arcs)
    rail_st = set(s for t, m in zip(trips, modes) if m == "1" for s in t.stations)
    bus_st = set(s for t, m in zip(trips, modes) if m == "3" for s in t.stations)
    shared = rail_st & bus_st

    # cross-mode transfer arcs: X of one mode -> W of other mode
    cross = 0
    for u, arcs in enumerate(g.adj):
        ku, tu, _ = g.node_info[u]
        for v, _c, tag in arcs:
            if tag == "transfer":
                kv, tv, _ = g.node_info[v]
                if modes[tu] != modes[tv]:
                    cross += 1

    # Gate-0 evidence: bus-only origin -> RAIL-ONLY destination, forcing a
    # bus -> rail transfer somewhere in the path.
    demo = None
    rail_only = rail_st - shared
    if rail_only:
        starts = [u for u, (k, ti, kk) in enumerate(g.node_info)
                  if k == "W" and modes[ti] == "3"
                  and trips[ti].stations[kk] not in shared][:2000]
        demo = dijkstra_path(g, starts, rail_only, trips, modes)

    man = {
        "build": "0.2b transfer contract + connected graph",
        "radius_m": RADIUS_M,
        "bus_stops_matched": int(len(match)),
        "rail_stations_with_bus_transfer": int(match.rail_station.nunique()),
        "shared_stations_after_contract": len(shared),
        "cross_mode_transfer_arcs": cross,
        "arcs_by_tag": dict(tags),
        "event_nodes": g.n_nodes,
        "gate0_demo_path_found": demo is not None,
        "gate0_demo_path": [f"{tag}@{station} [{ 'rail' if m=='1' else 'bus'}:{route}]"
                            for tag, kind, station, m, route in (demo or [])][:25],
    }
    with open(os.path.join(OUT, "build_0_2b_manifest.json"), "w") as f:
        json.dump(man, f, indent=2)
    print(json.dumps({k: man[k] for k in man if k != "gate0_demo_path"},
                     indent=1))
    if demo:
        print("Gate-0 demo path (first segments):")
        for line in man["gate0_demo_path"][:15]:
            print("  ", line)


if __name__ == "__main__":
    main()
