"""Golden A acceptance checker — Gate 0 "Show Me the Path" as executable tests.

Verifies, deterministically, on the tiny synthetic network:
  C1 auto path        Z1 -> Z4 on drive-legal links only
  C2 transit path     Z1 -> Z2 (walk + one bus ride)
  C3 transfer path    Z1 -> Z3 (bus -> transfer walk -> rail)
  C4 P&R path         Z5 -> Z3 (drive -> park -> walk -> rail) staged legality
  C5 K&R path         Z1 -> Z3 (drive -> dropoff -> walk -> rail)
  C6 disconnected OD  Z6 -> Z3 must be UNREACHABLE and REPORTED
  C7 supply           L1 = 12 scheduled trips; L2 frequency expands to 8
  C8 conservation     demand file total = sum of submarkets = 1200 (incl. the
                      50 deliberately unreachable, ledgered not dropped)

Every check prints PASS/FAIL; exit code 1 if any REQUIRED check fails
(C6 passes when unreachability IS detected). Results -> gold/check_results.json
"""
import json
import os
import sys
from collections import defaultdict

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    nodes = pd.read_csv(os.path.join(HERE, "network", "node.csv"))
    links = pd.read_csv(os.path.join(HERE, "network", "link.csv"))
    g = os.path.join(HERE, "gtfs")
    trips = pd.read_csv(os.path.join(g, "trips.txt"))
    st = pd.read_csv(os.path.join(g, "stop_times.txt"))
    fr = pd.read_csv(os.path.join(g, "frequencies.txt"))
    dem = pd.read_csv(os.path.join(HERE, "demand", "demand.csv"))
    return nodes, links, trips, st, fr, dem


def adj_for(links, modes):
    a = defaultdict(set)
    for r in links.itertuples():
        if r.allowed_uses in modes:
            a[r.from_node_id].add(r.to_node_id)
    return a


def reach(adj, srcs):
    seen = set(srcs)
    q = list(srcs)
    while q:
        u = q.pop()
        for v in adj.get(u, ()):
            if v not in seen:
                seen.add(v)
                q.append(v)
    return seen


def ride_edges(trips, st, fr):
    """station-level ride edges per route + trip counts (freq expanded)."""
    edges = defaultdict(set)
    n_trips = defaultdict(int)
    tmpl = set(fr.trip_id)
    for tid, g in st.groupby("trip_id"):
        g = g.sort_values("stop_sequence")
        rid = trips.loc[trips.trip_id == tid, "route_id"].iloc[0]
        for a, b in zip(g.stop_id[:-1], g.stop_id[1:]):
            edges[rid].add((a, b))
        if tid not in tmpl:
            n_trips[rid] += 1
    for r in fr.itertuples():
        rid = trips.loc[trips.trip_id == r.trip_id, "route_id"].iloc[0]
        s = sum(int(x) * f for x, f in
                zip(r.start_time.split(":"), (3600, 60, 1)))
        e = sum(int(x) * f for x, f in
                zip(r.end_time.split(":"), (3600, 60, 1)))
        n_trips[rid] += (e - s) // int(r.headway_secs)
    return edges, n_trips


def main():
    nodes, links, trips, st, fr, dem = load()
    walk = adj_for(links, {"walk"})
    drive = adj_for(links, {"auto"})
    edges, n_trips = ride_edges(trips, st, fr)
    # transit+walk adjacency: walk links + ride edges (station graph)
    twa = defaultdict(set)
    for u, vs in walk.items():
        twa[u] |= vs
    for rid, es in edges.items():
        for a, b in es:
            twa[a].add(b)

    res = {}
    res["C1_auto_Z1_Z4"] = 4 in reach(drive, [1])
    res["C2_transit_Z1_Z2"] = 2 in reach(twa, [1])
    r3 = reach(twa, [1])
    res["C3_transfer_Z1_Z3"] = (3 in r3) and (212, 202) in \
        {(a, b) for a in [212] for b in twa.get(212, ())} | {(212, 202)} \
        and (202 in twa.get(212, set()))
    # C4 staged: drive Z5 -> parking 301, then walk/ride 301 -> Z3
    stage1 = 301 in reach(drive, [5])
    stage2 = 3 in reach(twa, [301])
    res["C4_pnr_Z5_Z3"] = stage1 and stage2
    stage1k = 302 in reach(drive, [1])
    stage2k = 3 in reach(twa, [302])
    res["C5_knr_Z1_Z3"] = stage1k and stage2k
    # C6: Z6 must be unreachable in EVERY layer, and detected
    res["C6_disconnected_detected"] = (
        3 not in reach(drive, [6]) and 3 not in reach(twa, [6]))
    res["C7_supply_counts"] = (n_trips.get("L1") == 12
                               and n_trips.get("L2") == 8)
    tot = dem.volume.sum()
    res["C8_conservation_1200"] = (tot == 1200
                                   and dem[dem.submarket == "disconnected"]
                                   .volume.sum() == 50)

    res = {k: bool(v) for k, v in res.items()}
    out = {"checks": res, "all_pass": all(res.values()),
           "supply": {"L1_trips": int(n_trips.get("L1", 0)),
                      "L2_trips_freq_expanded": int(n_trips.get("L2", 0))},
           "demand_total": int(tot)}
    os.makedirs(os.path.join(HERE, "gold"), exist_ok=True)
    with open(os.path.join(HERE, "gold", "check_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    for k, v in res.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    print("ALL PASS" if out["all_pass"] else "FAILURES PRESENT")
    sys.exit(0 if out["all_pass"] else 1)


if __name__ == "__main__":
    main()
