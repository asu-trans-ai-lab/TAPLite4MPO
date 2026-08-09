"""Build 0.2c — first end-to-end DC multimodal loading (closes the 0.2 chain
Network -> Connection -> Path -> Assignment).

Static AM-period frequency-based loading, BART-style and equally honest:

  graph   : zones --walk access (<=800 m)--> stations --board (wait =
            min(headway/2, 20 min))--> pattern-stop layer --ride (scheduled
            ivt)--> ... --alight (0)--> stations --walk egress--> zones.
            Transfers arise naturally (alight then board), rail-bus via the
            0.2b transfer contract (aliased interchange stations).
  demand  : the calibrated doubly-constrained gravity OD (synthetic, D2),
            AM 06:30-09:00, loaded ALL-OR-NOTHING on min generalized time
            (walk + wait + in-vehicle); uncapacitated -> V/C is a diagnostic.
  supply  : trips per pattern in-window from the compact store;
            vehicle capacity DECLARED per mode: rail 600 (8-car x 75
            service std), bus 60. Period capacity = n_trips x veh_cap.
  states  : UNDERSUPPLY >=1.0 | CROWDED 0.8-1.0 | BALANCED 0.2-0.8 |
            OVERSUPPLY <0.2 (same thresholds as the BART gold).

Unserved demand (no access within 800 m, or unreachable) is LEDGERED, not
dropped silently. Outputs -> build_0_2/loading/.
"""
import heapq
import json
import os
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = r"C:\source_codes\0_source_code_new\transit_schedule_column_generation_assignment"
FEED = os.path.join(TOOL, "GTFS_DC", "1_WMATA_202004")
NODE = r"C:\source_codes\nvta_gmns_testbeds\Transit\transit_network_17agencies\node.csv"
COMPACT = os.path.join(HERE, "build_0_2", "compact")
OUT = os.path.join(HERE, "build_0_2", "loading")
os.makedirs(OUT, exist_ok=True)

WALK_M = 800.0
WALK_MIN_PER_KM = 12.0
MAX_WAIT = 20.0
WINDOW_MIN = 150.0          # 06:30-09:00
CAP = {"1": 600.0, "3": 60.0}   # DECLARED service capacity per vehicle
W_S, W_E = 390 * 60, 540 * 60

from compact_reader import load_trips


def hav_m(lon1, lat1, lon2, lat2):
    R = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = (np.sin((p2 - p1) / 2) ** 2
         + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2)
    return 2 * R * np.arcsin(np.sqrt(a))


def main():
    rp = pd.read_parquet(os.path.join(COMPACT, "run_profiles.parquet"))
    trips = load_trips(COMPACT)
    inwin = trips[(trips.t0_s < W_E) & (trips.t0_s >= W_S - 3600)]
    tph = inwin.groupby("profile_id").size()          # trips per profile, AM

    stops = pd.read_csv(os.path.join(FEED, "stops.txt"), dtype=str)
    stops["lat"] = stops.stop_lat.astype(float)
    stops["lon"] = stops.stop_lon.astype(float)
    sname = dict(zip(stops.stop_id, stops.stop_name))
    scoord = {}
    for _, r in stops.iterrows():
        scoord.setdefault(r.stop_name, (r.lon, r.lat))
    # transfer contract aliasing (bus stop name -> rail station name)
    match = pd.read_csv(os.path.join(HERE, "build_0_2",
                                     "transfer_stop_match.csv"))
    alias = dict(zip(match.bus_stop_name, match.rail_station))

    routes = pd.read_csv(os.path.join(FEED, "routes.txt"), dtype=str)
    rmode = dict(zip(routes.route_id, routes.route_type))

    # ---- graph ----
    node_id = {}
    def nid(key):
        if key not in node_id:
            node_id[key] = len(node_id)
        return node_id[key]

    adj = defaultdict(list)
    seg_of_arc = {}
    seg_meta = {}
    n_prof_used = 0
    for p in rp.itertuples():
        n = tph.get(p.profile_id, 0)
        if n == 0:
            continue
        n_prof_used += 1
        # stop_ns_id 'wmata:stop:<id>' -> name -> alias
        names = [alias.get(sname.get(s.split(":")[-1], s),
                 sname.get(s.split(":")[-1], s)) for s in p.stops]
        names = [alias.get(x, x) for x in names]
        rid = p.pattern_id            # stable route key
        wait = min(MAX_WAIT, WINDOW_MIN / n / 2.0)
        for k, st in enumerate(names):
            pk = nid(("P", p.profile_id, k))
            sk = nid(("S", st))
            adj[sk].append((pk, wait, None))            # board
            adj[pk].append((sk, 0.0, None))             # alight
            if k + 1 < len(names):
                ivt = (p.dep_off[k + 1] - p.dep_off[k]) / 60.0
                pk2 = nid(("P", p.profile_id, k + 1))
                seg = (p.profile_id, k)
                arc = (pk, pk2)
                adj[pk].append((pk2, max(ivt, 0.3), seg))
                seg_meta[seg] = {"profile_id": int(p.profile_id),
                                 "pattern_id": p.pattern_id,
                                 "from": st, "to": names[k + 1],
                                 "n_trips": int(n),
                                 "ivt_min": round(max(ivt, 0.3), 2)}

    # zone access/egress
    cent = pd.read_csv(NODE, low_memory=False,
                       usecols=["zone_id", "x_coord", "y_coord"])
    cent = (cent[cent.zone_id.notna() & (cent.zone_id > 0)]
            .groupby("zone_id")[["x_coord", "y_coord"]].first())
    st_names = [k[1] for k in node_id if k[0] == "S"]
    st_lon = np.array([scoord.get(s, (np.nan, np.nan))[0] for s in st_names])
    st_lat = np.array([scoord.get(s, (np.nan, np.nan))[1] for s in st_names])
    ok = ~np.isnan(st_lon)
    st_names = [s for s, o in zip(st_names, ok) if o]
    st_lon, st_lat = st_lon[ok], st_lat[ok]

    zone_access = {}
    for z, r in cent.iterrows():
        d = hav_m(st_lon, st_lat, r.x_coord, r.y_coord)
        near = np.where(d <= WALK_M)[0]
        if len(near) == 0:
            continue
        zn = nid(("Z", z))
        zone_access[z] = zn
        for i in near:
            w = d[i] / 1000.0 * WALK_MIN_PER_KM
            sk = nid(("S", st_names[i]))
            adj[zn].append((sk, w, None))
            adj[sk].append((zn, w, None))

    N = len(node_id)
    print(f"graph: {N:,} nodes | profiles used {n_prof_used} | "
          f"zones with access {len(zone_access):,} of {len(cent):,}")

    # ---- demand + AON loading ----
    od = pd.read_csv(os.path.join(HERE, "synthetic_od_am.csv"))
    total = od.volume.sum()
    served_mask = od.o_zone_id.isin(zone_access) & od.d_zone_id.isin(zone_access)
    unserved_access = od[~served_mask].volume.sum()
    od = od[served_mask]

    seg_vol = defaultdict(float)
    unreachable = 0.0
    INF = 1e18
    dist = np.full(N, INF)
    prev_arc = np.full(N, -1, dtype=np.int64)
    arcs_flat = []
    arc_index = {}
    adj_c = {}
    for u, lst in adj.items():
        row = []
        for (v, c, seg) in lst:
            ai = len(arcs_flat)
            arcs_flat.append((u, v, seg))
            row.append((v, c, ai))
        adj_c[u] = row

    for oz, g in od.groupby("o_zone_id"):
        src = zone_access[oz]
        dist.fill(INF); prev_arc.fill(-1)
        dist[src] = 0.0
        pq = [(0.0, src)]
        targets = {zone_access[dz]: dz for dz in g.d_zone_id if dz in zone_access}
        found = 0
        while pq and found < len(targets):
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            if u in targets:
                found += 1
            for v, c, ai in adj_c.get(u, ()):
                nd = d + c
                if nd < dist[v] - 1e-9:
                    dist[v] = nd
                    prev_arc[v] = ai
                    heapq.heappush(pq, (nd, v))
        for r in g.itertuples():
            tz = zone_access.get(r.d_zone_id)
            if tz is None or dist[tz] >= INF:
                unreachable += r.volume
                continue
            u = tz
            while prev_arc[u] >= 0:
                pu, _v, seg = arcs_flat[prev_arc[u]]
                if seg is not None:
                    seg_vol[seg] += r.volume
                u = pu

    # ---- V/C states ----
    rows = []
    for seg, meta in seg_meta.items():
        pid = meta["pattern_id"]
        # mode from pattern namespace route: profile patterns are
        # 'wmata:pattern:N' -> recover mode via any trip? keep via route_type
        # embedded at build: patterns built per route; look up by first stop's
        # membership is unreliable -> carry mode by profile via trips table.
        rows.append({**meta, "segment": f"{meta['from']} -> {meta['to']}",
                     "volume": round(seg_vol.get(seg, 0.0), 1)})
    segdf = pd.DataFrame(rows)
    # mode per profile from the trips/pattern namespace: rail patterns run on
    # rail routes; recover from stageB trips table.
    tr = pd.read_parquet(os.path.join(HERE, "build_0_2", "stageB",
                                      "trips.parquet"))
    tr["route_id"] = tr.route_ns_id.str.split(":").str[-1]
    tr["mode"] = tr.route_id.map(rmode)
    pat_mode = tr.drop_duplicates("service_pattern_id").set_index(
        "service_pattern_id")["mode"]
    segdf["mode"] = segdf.pattern_id.map(pat_mode).fillna("3")
    segdf["veh_cap"] = segdf["mode"].map(CAP)
    segdf["period_capacity"] = segdf.n_trips * segdf.veh_cap
    segdf["vc"] = segdf.volume / segdf.period_capacity
    segdf["state"] = np.select(
        [segdf.vc >= 1.0, segdf.vc >= 0.8, segdf.vc >= 0.2],
        ["UNDERSUPPLY", "CROWDED", "BALANCED"], default="OVERSUPPLY")
    segdf.sort_values("vc", ascending=False).to_csv(
        os.path.join(OUT, "segment_loading.csv"), index=False)

    served = total - unserved_access - unreachable
    states = segdf.state.value_counts().to_dict()
    man = {
        "build": "0.2c end-to-end multimodal loading (AON, static AM)",
        "demand_provenance": "synthetic_gravity_dc_kfactor",
        "demand_total_am": round(float(total), 0),
        "served": round(float(served), 0),
        "unserved_no_walk_access_800m": round(float(unserved_access), 0),
        "unserved_unreachable": round(float(unreachable), 0),
        "served_share": round(float(served / total), 4),
        "segments": int(len(segdf)),
        "state_counts": states,
        "state_shares": {k: round(v / len(segdf), 4)
                         for k, v in states.items()},
        "peak_vc": round(float(segdf.vc.max()), 2),
        "assumptions": {
            "walk": "800 m access/egress, 12 min/km",
            "wait": "min(headway/2, 20 min), headway from in-window trips",
            "veh_capacity": {"rail": 600, "bus": 60,
                             "basis": "declared service capacity (A1-style)"},
            "loading": "all-or-nothing on min generalized time, "
                       "uncapacitated -> V/C diagnostic",
            "period": "single AM 06:30-09:00 (COVID-reduced snapshot)"},
    }
    with open(os.path.join(OUT, "loading_manifest.json"), "w") as f:
        json.dump(man, f, indent=2)
    print(json.dumps(man, indent=1))
    print("\ntop 8 segments by V/C:")
    print(segdf.nlargest(8, "vc")[["segment", "mode", "n_trips", "volume",
                                   "period_capacity", "vc", "state"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
