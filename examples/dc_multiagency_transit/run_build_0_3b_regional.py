"""Build 0.3b — cross-agency transfer contract + REGIONAL multimodal loading.

Extends 0.2c from WMATA-only to all 20 feeds:
  1. Gather every stop used by any in-window profile across the 20 per-feed
     compact stores; proximity-cluster stops (union-find, <=200 m, grid-hashed)
     ACROSS agencies -> interchange clusters = the regional transfer contract.
     Written to regional_transfer_clusters.csv.
  2. Build the station-cluster/pattern-stop graph (board wait = min(headway/2,
     20'), scheduled ivt rides, alight free) over ALL agencies.
  3. Zone walk access <=800 m; AON loading of the calibrated gravity OD.
  4. Compare served share vs the 0.2c WMATA-only baseline (35.3%).

Vehicle capacity DECLARED by route_type: tram 120, metro 600, commuter rail
600, bus 60. Outputs -> build_0_3/regional/.
"""
import heapq
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

TOOL = r"C:\source_codes\0_source_code_new\transit_schedule_column_generation_assignment"
ROOT = os.path.join(TOOL, "GTFS_DC")
HERE = os.path.dirname(os.path.abspath(__file__))
B3 = os.path.join(HERE, "build_0_3")
OUT = os.path.join(B3, "regional")
NODE = r"C:\source_codes\nvta_gmns_testbeds\Transit\transit_network_17agencies\node.csv"
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, HERE)
from compact_reader import load_trips

RADIUS_M = 200.0
WALK_M = 800.0
WALK_MIN_PER_KM = 12.0
MAX_WAIT = 20.0
WINDOW_MIN = 150.0
W_S, W_E = 390 * 60, 540 * 60
CAP = {"0": 120.0, "1": 600.0, "2": 600.0, "3": 60.0}


def hav_m(lon1, lat1, lon2, lat2):
    R = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = (np.sin((p2 - p1) / 2) ** 2
         + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2)
    return 2 * R * np.arcsin(np.sqrt(a))


class UF:
    def __init__(self, n):
        self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def main():
    feeds = sorted(os.listdir(ROOT))
    # per-feed assets
    feed_stops, profiles, prof_trips, prof_mode = {}, [], {}, {}
    for i, fname in enumerate(feeds):
        fdir = os.path.join(ROOT, fname)
        if not os.path.isdir(fdir):
            continue
        cdir = os.path.join(B3, f"compact_{i:02d}")
        bdir = os.path.join(B3, f"stageB_{i:02d}")
        if not os.path.isdir(cdir):
            continue
        st = pd.read_csv(os.path.join(fdir, "stops.txt"), dtype=str)
        feed_stops[i] = {r.stop_id: (float(r.stop_lon), float(r.stop_lat),
                                     r.stop_name)
                         for r in st.itertuples()
                         if pd.notna(r.stop_lon)}
        rp = pd.read_parquet(os.path.join(cdir, "run_profiles.parquet"))
        trips = load_trips(cdir)
        inwin = trips[(trips.t0_s < W_E) & (trips.t0_s >= W_S - 3600)]
        tph = inwin.groupby("profile_id").size()
        routes = pd.read_csv(os.path.join(fdir, "routes.txt"), dtype=str)
        rtype = dict(zip(routes.route_id, routes.route_type))
        pats = pd.read_parquet(os.path.join(bdir, "service_patterns.parquet"))
        pat_rt = dict(zip(pats.service_pattern_id,
                          pats.route_id.map(rtype)))
        for p in rp.itertuples():
            n = int(tph.get(p.profile_id, 0))
            if n == 0:
                continue
            profiles.append((i, p))
            prof_trips[(i, p.profile_id)] = n
            prof_mode[(i, p.profile_id)] = pat_rt.get(p.pattern_id, "3")

    # ---- regional stop clustering (union-find, grid hash) ----
    stop_list = []       # (feed, stop_id, lon, lat)
    seen = set()
    for i, p in profiles:
        for s in p.stops:
            sid = s.split(":")[-1]
            if (i, sid) in seen:
                continue
            seen.add((i, sid))
            if sid in feed_stops.get(i, {}):
                lon, lat, _ = feed_stops[i][sid]
                stop_list.append((i, sid, lon, lat))
    n = len(stop_list)
    uf = UF(n)
    cell = defaultdict(list)
    SZ = 0.0025          # ~ 250 m grid
    for k, (_i, _s, lon, lat) in enumerate(stop_list):
        cell[(int(lon / SZ), int(lat / SZ))].append(k)
    for (cx, cy), members in cell.items():
        cand = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cand.extend(cell.get((cx + dx, cy + dy), ()))
        for a in members:
            la, oa = stop_list[a][3], stop_list[a][2]
            for b in cand:
                if b <= a:
                    continue
                if hav_m(oa, la, stop_list[b][2], stop_list[b][3]) <= RADIUS_M:
                    uf.union(a, b)
    cluster_of = {}
    for k, (i, sid, lon, lat) in enumerate(stop_list):
        cluster_of[(i, sid)] = uf.find(k)
    clusters = defaultdict(list)
    for k, (i, sid, lon, lat) in enumerate(stop_list):
        clusters[uf.find(k)].append((i, sid, lon, lat))
    cross_agency_clusters = sum(
        1 for m in clusters.values() if len({x[0] for x in m}) > 1)
    pd.DataFrame([{"cluster": c, "feed_idx": i, "stop_id": s,
                   "lon": lon, "lat": lat}
                  for c, mem in clusters.items()
                  for (i, s, lon, lat) in mem]).to_csv(
        os.path.join(OUT, "regional_transfer_clusters.csv"), index=False)
    print(f"stops {n:,} -> clusters {len(clusters):,} "
          f"({cross_agency_clusters:,} span >1 agency)")

    # ---- graph ----
    node_id = {}
    def nid(key):
        if key not in node_id:
            node_id[key] = len(node_id)
        return node_id[key]
    adj = defaultdict(list)
    seg_meta = {}
    for i, p in profiles:
        key = (i, p.profile_id)
        nt = prof_trips[key]
        wait = min(MAX_WAIT, WINDOW_MIN / nt / 2.0)
        sids = [s.split(":")[-1] for s in p.stops]
        cl = [cluster_of.get((i, s)) for s in sids]
        for k, c in enumerate(cl):
            if c is None:
                continue
            pk = nid(("P", i, p.profile_id, k))
            sk = nid(("S", c))
            adj[sk].append((pk, wait, None))
            adj[pk].append((sk, 0.0, None))
            if k + 1 < len(cl) and cl[k + 1] is not None:
                ivt = (p.dep_off[k + 1] - p.dep_off[k]) / 60.0
                pk2 = nid(("P", i, p.profile_id, k + 1))
                seg = (i, p.profile_id, k)
                adj[pk].append((pk2, max(ivt, 0.3), seg))
                seg_meta[seg] = {
                    "feed_idx": i, "profile_id": int(p.profile_id),
                    "from_cluster": int(c), "to_cluster": int(cl[k + 1]),
                    "n_trips": nt, "mode": prof_mode[key]}

    # zone access
    cent = pd.read_csv(NODE, low_memory=False,
                       usecols=["zone_id", "x_coord", "y_coord"])
    cent = (cent[cent.zone_id.notna() & (cent.zone_id > 0)]
            .groupby("zone_id")[["x_coord", "y_coord"]].first())
    ccoord = {}
    for c, mem in clusters.items():
        ccoord[c] = (np.mean([m[2] for m in mem]),
                     np.mean([m[3] for m in mem]))
    cids = list(ccoord)
    clon = np.array([ccoord[c][0] for c in cids])
    clat = np.array([ccoord[c][1] for c in cids])
    zone_access = {}
    for z, r in cent.iterrows():
        d = hav_m(clon, clat, r.x_coord, r.y_coord)
        near = np.where(d <= WALK_M)[0]
        if len(near) == 0:
            continue
        zn = nid(("Z", z))
        zone_access[z] = zn
        for ix in near:
            w = d[ix] / 1000.0 * WALK_MIN_PER_KM
            sk = nid(("S", cids[ix]))
            adj[zn].append((sk, w, None))
            adj[sk].append((zn, w, None))
    N = len(node_id)
    print(f"graph {N:,} nodes | zones with access "
          f"{len(zone_access):,} of {len(cent):,}")

    # ---- AON loading ----
    od = pd.read_csv(os.path.join(HERE, "synthetic_od_am.csv"))
    total = od.volume.sum()
    m = od.o_zone_id.isin(zone_access) & od.d_zone_id.isin(zone_access)
    unserved_access = od[~m].volume.sum()
    od = od[m]
    arcs_flat, adj_c = [], {}
    for u, lst in adj.items():
        row = []
        for (v, c, seg) in lst:
            ai = len(arcs_flat)
            arcs_flat.append((u, v, seg))
            row.append((v, c, ai))
        adj_c[u] = row
    seg_vol = defaultdict(float)
    unreachable = 0.0
    dist = np.full(N, 1e18)
    prev_arc = np.full(N, -1, dtype=np.int64)
    for oz, g in od.groupby("o_zone_id"):
        src = zone_access[oz]
        dist.fill(1e18); prev_arc.fill(-1)
        dist[src] = 0.0
        pq = [(0.0, src)]
        targets = {zone_access[dz] for dz in g.d_zone_id
                   if dz in zone_access}
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
            if tz is None or dist[tz] >= 1e17:
                unreachable += r.volume
                continue
            u = tz
            while prev_arc[u] >= 0:
                pu, _v, seg = arcs_flat[prev_arc[u]]
                if seg is not None:
                    seg_vol[seg] += r.volume
                u = pu

    rows = []
    for seg, meta in seg_meta.items():
        v = seg_vol.get(seg, 0.0)
        cap = meta["n_trips"] * CAP.get(meta["mode"], 60.0)
        rows.append({**meta, "volume": round(v, 1),
                     "period_capacity": cap, "vc": v / cap})
    segdf = pd.DataFrame(rows)
    segdf["state"] = np.select(
        [segdf.vc >= 1.0, segdf.vc >= 0.8, segdf.vc >= 0.2],
        ["UNDERSUPPLY", "CROWDED", "BALANCED"], default="OVERSUPPLY")
    segdf.sort_values("vc", ascending=False).to_csv(
        os.path.join(OUT, "regional_segment_loading.csv"), index=False)
    served = total - unserved_access - unreachable
    states = segdf.state.value_counts().to_dict()
    man = {
        "build": "0.3b regional multi-agency loading",
        "feeds_in_graph": len({i for i, _ in profiles}),
        "stops": n, "clusters": len(clusters),
        "cross_agency_clusters": cross_agency_clusters,
        "demand_total_am": round(float(total), 0),
        "served": round(float(served), 0),
        "served_share": round(float(served / total), 4),
        "served_share_WMATA_only_baseline": 0.3529,
        "unserved_no_walk_access_800m": round(float(unserved_access), 0),
        "unserved_unreachable": round(float(unreachable), 0),
        "segments": int(len(segdf)),
        "state_shares": {k: round(v / len(segdf), 4)
                         for k, v in states.items()},
        "peak_vc": round(float(segdf.vc.max()), 2),
        "assumptions": "walk 800 m @12 min/km; wait min(headway/2,20'); AON "
                       "uncapacitated; veh caps by route_type tram 120 / "
                       "metro 600 / commuter 600 / bus 60; feeds span "
                       "2019-2021 vintages (declared, not one date)",
    }
    with open(os.path.join(OUT, "regional_manifest.json"), "w") as f:
        json.dump(man, f, indent=2)
    print(json.dumps(man, indent=1))


if __name__ == "__main__":
    main()
