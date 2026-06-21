"""Hierarchical super-zone network construction (faithful, corner-case-exact).

Builds a new GMNS scenario where each ORIGINAL zone is demoted to a regular
THROUGH node and a smaller set of SUPER-ZONE centroids is prepended, each linked
to its member original zone nodes by zero-cost connectors. Demand is keyed to
super-zones.

Kernel facts this relies on (TAPLite.cpp):
  * a zone is a node with zone_id == node_id; no_zones = max(zone_id).
  * auto FirstThruNode (first_through_node_id = -1) = first node with zone_id==0.
  * a node is passable (through) iff seq >= FirstThruNode or it is the origin.

Node numbering (compact -> no_zones = S):
  super-zones : 1 .. S        (zone_id = node_id)   <- the only centroids
  original    : S+1 .. S+N    (zone_id = 0)         <- all become through nodes
With FirstThruNode auto = S+1, a trip routes super -> member-node -> network
(the member node, now through, may be traversed). One super-zone per original
zone reproduces the full assignment exactly.
"""
import bisect
import math
import os

from . import csvio


# zero-cost connector attributes (transparent: travel_time = fftt + alpha*... = 0)
_CONN = dict(length=0.0, vdf_length_mi=0.0, lanes=1, capacity=999999, free_speed=60,
             vdf_free_speed_mph=60, vdf_type=0, vdf_alpha=0, vdf_beta=1, vdf_plf=1,
             vdf_fftt=0.0, cutoff_speed=45, allowed_use="", link_type=9)


def cluster_grid(zone_xy, k_target):
    """{zone_id -> super_id(1..S)} via a balanced quantile grid; +super coords."""
    zones = list(zone_xy)
    g = max(1, int(round(math.sqrt(k_target))))
    xs = sorted(zone_xy[z][0] for z in zones)
    ys = sorted(zone_xy[z][1] for z in zones)
    edge = lambda v: [v[min(len(v) - 1, int(len(v) * i / g))] for i in range(1, g)]
    xe, ye = edge(xs), edge(ys)
    cell = {}
    for z in zones:
        x, y = zone_xy[z]
        cell.setdefault((bisect.bisect_right(xe, x), bisect.bisect_right(ye, y)), []).append(z)
    z2s, coords, sid = {}, {}, 0
    for members in cell.values():
        sid += 1
        coords[sid] = (sum(zone_xy[z][0] for z in members) / len(members),
                       sum(zone_xy[z][1] for z in members) / len(members))
        for z in members:
            z2s[z] = sid
    return z2s, coords


def identity_map(zone_xy):
    """One super-zone per original zone (the corner case)."""
    z2s, coords = {}, {}
    for i, z in enumerate(sorted(zone_xy), start=1):
        z2s[z] = i
        coords[i] = zone_xy[z]
    return z2s, coords


def _read_od(path):
    import csv
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.reader(f)
        h = next(r)
        oi, di, vi = (h.index("o_zone_id"), h.index("d_zone_id"), h.index("volume")) \
            if "o_zone_id" in h else (0, 1, 2)
        for row in r:
            try:
                yield int(float(row[oi])), int(float(row[di])), float(row[vi])
            except (IndexError, ValueError):
                continue


def build(scenario, out_dir, k_target=None, zone2super=None):
    os.makedirs(out_dir, exist_ok=True)
    rep = []
    nhdr, nrows = csvio.read(csvio.path(scenario, "node.csv"))
    zone_xy = {}
    order = []                                  # original node ids in file order
    for r in nrows:
        nid = csvio.inum(r.get("node_id"))
        order.append(nid)
        if csvio.inum(r.get("zone_id"), 0) > 0:
            zone_xy[nid] = (csvio.fnum(r.get("x_coord")), csvio.fnum(r.get("y_coord")))

    if zone2super is None:
        zone2super, scoords = (identity_map(zone_xy) if not k_target
                               else cluster_grid(zone_xy, k_target))
    else:
        scoords = {s: zone_xy[next(z for z in zone2super if zone2super[z] == s)]
                   for s in set(zone2super.values())}
    S = max(zone2super.values())
    old2new = {old: S + i + 1 for i, old in enumerate(order)}   # originals shift after supers
    rep.append(f"zones {len(zone_xy)} -> super-zones {S}; nodes {len(order)} -> {S+len(order)}; FirstThruNode auto = {S+1}")

    # --- node.csv: super-zones (1..S) then originals (S+1..) ---
    out_nrows = []
    for s in range(1, S + 1):
        x, y = scoords[s]
        out_nrows.append({"node_id": s, "zone_id": s, "x_coord": x, "y_coord": y})
    nx_by_id = {csvio.inum(r.get("node_id")): r for r in nrows}
    for old in order:
        r = nx_by_id[old]
        out_nrows.append({"node_id": old2new[old], "zone_id": 0,
                          "x_coord": r.get("x_coord"), "y_coord": r.get("y_coord")})
    csvio.write(csvio.path(out_dir, "node.csv"),
                ["node_id", "zone_id", "x_coord", "y_coord"], out_nrows)

    # --- link.csv: remapped originals + super->member connectors ---
    # Pass ALL original columns through (datasets differ in case/naming, e.g. VDF_plf
    # vs vdf_plf); only remap from/to. Connector attributes are written into whatever
    # columns exist, matched case-insensitively.
    lhdr, lrows = csvio.read(csvio.path(scenario, "link.csv"))
    if "link_id" not in lhdr:
        lhdr = ["link_id"] + lhdr
    lower2col = {c.lower(): c for c in lhdr}
    out_lrows = []
    for r in lrows:
        o = {c: r.get(c, "") for c in lhdr}
        o["from_node_id"] = old2new[csvio.inum(r.get("from_node_id"))]
        o["to_node_id"] = old2new[csvio.inum(r.get("to_node_id"))]
        out_lrows.append(o)
    cid = 900000000
    nconn = 0
    for z, s in zone2super.items():
        for a, b in ((s, old2new[z]), (old2new[z], s)):     # bidirectional, zero cost
            row = {c: "" for c in lhdr}
            row["link_id"], row["from_node_id"], row["to_node_id"] = cid, a, b
            for k, v in _CONN.items():
                col = lower2col.get(k)
                if col:
                    row[col] = v
            out_lrows.append(row); cid += 1; nconn += 1
    # sort by from-node internal seq (= node.csv order = new id order)
    out_lrows.sort(key=lambda r: (csvio.inum(r["from_node_id"]), csvio.inum(r["to_node_id"])))
    csvio.write(csvio.path(out_dir, "link.csv"), lhdr, out_lrows)
    rep.append(f"links {len(lrows)} + {nconn} super-connectors = {len(out_lrows)}")

    # --- demand: key to super-zones, drop intra-super ---
    _, mts = csvio.read(csvio.path(scenario, "mode_type.csv")) if csvio.exists(scenario, "mode_type.csv") else (None, [])
    dfiles = [m.get("demand_file") for m in mts if m.get("demand_file")] or ["demand.csv"]
    import csv as _csv
    for df in dfiles:
        src = csvio.path(scenario, df)
        if not os.path.exists(src):
            continue
        agg = {}
        nin = vin = 0
        for o, d, v in _read_od(src):
            nin += 1; vin += v
            so, sd = zone2super.get(o), zone2super.get(d)
            if so is None or sd is None or so == sd:
                continue
            agg[(so, sd)] = agg.get((so, sd), 0.0) + v
        with open(csvio.path(out_dir, df), "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f); w.writerow(["o_zone_id", "d_zone_id", "volume"])
            for (o, d), v in agg.items():
                w.writerow([o, d, v])
        rep.append(f"{df}: {nin:,} -> {len(agg):,} pairs; vol {vin:,.0f} -> {sum(agg.values()):,.0f}")

    # --- settings + mode_type passthrough (force auto FirstThruNode) ---
    shdr, srows = csvio.read(csvio.path(scenario, "settings.csv"))
    s = dict(srows[0]) if srows else {}
    s["first_through_node_id"] = -1
    s["demand_format"] = 0                 # aggregated demand is written as CSV
    for col in ("first_through_node_id", "demand_format"):
        if col not in shdr:
            shdr = shdr + [col]
    csvio.write(csvio.path(out_dir, "settings.csv"), shdr, [s])
    if mts:
        mhdr, _m = csvio.read(csvio.path(scenario, "mode_type.csv"))
        csvio.write(csvio.path(out_dir, "mode_type.csv"), mhdr, mts)
    return rep
