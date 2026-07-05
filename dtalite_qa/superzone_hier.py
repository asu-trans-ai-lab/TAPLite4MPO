"""Hierarchical super-zone network construction (faithful, corner-case-exact).

Builds a new GMNS scenario where each ORIGINAL zone centroid is REMOVED and its
connector links are REWIRED -- with their original attributes (length, fftt,
capacity, ...) -- to a smaller set of SUPER-ZONE centroids prepended at ids 1..S.
Demand is keyed to super-zones. A super-zone therefore attaches to the network at
exactly the union of its member zones' attachment nodes, at the member
connectors' original costs.

Why bypass-and-delete (NOT demote-to-through): an earlier construction demoted
original centroids to regular through nodes and linked supers to them with
zero-cost connectors. That opens PHANTOM SHORTCUTS -- paths cutting through a
former centroid via two of its connectors -- on any network whose centroid
connectors can shortcut the streets. Chicago's topology masked this; a dense
147k-node grid network failed the S=N corner case badly (VMT -12%, slope 4.6).
With rewiring, S=N is exact BY CONSTRUCTION on every topology: the network is
identical up to renaming each centroid to its own super-zone.

Kernel facts this relies on (TAPLite.cpp):
  * a zone is a node with zone_id == node_id; no_zones = max(zone_id).
  * auto FirstThruNode (first_through_node_id = -1) = first node with zone_id==0.
  * a node is passable (through) iff seq >= FirstThruNode or it is the origin.
  * parallel links between the same node pair are legal (adjacency scans all
    outgoing links), so overlapping member connectors need no merging.

Node numbering (compact -> no_zones = S):
  super-zones                 : 1 .. S   (zone_id = node_id)  <- the only centroids
  original non-centroid nodes : S+1 ..   (zone_id = 0)        <- through, unchanged
"""
import bisect
import math
import os

from . import csvio


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
    # originals EXCLUDING centroids shift after supers; centroids are deleted
    order_nc = [nid for nid in order if nid not in zone_xy]
    old2new = {old: S + i + 1 for i, old in enumerate(order_nc)}
    rep.append(f"zones {len(zone_xy)} -> super-zones {S} (centroids rewired+removed); "
               f"nodes {len(order)} -> {S + len(order_nc)}; FirstThruNode auto = {S+1}")

    # --- node.csv: super-zones (1..S) then non-centroid originals (S+1..) ---
    out_nrows = []
    for s in range(1, S + 1):
        x, y = scoords[s]
        out_nrows.append({"node_id": s, "zone_id": s, "x_coord": x, "y_coord": y})
    nx_by_id = {csvio.inum(r.get("node_id")): r for r in nrows}
    for old in order_nc:
        r = nx_by_id[old]
        out_nrows.append({"node_id": old2new[old], "zone_id": 0,
                          "x_coord": r.get("x_coord"), "y_coord": r.get("y_coord")})
    csvio.write(csvio.path(out_dir, "node.csv"),
                ["node_id", "zone_id", "x_coord", "y_coord"], out_nrows)

    # --- link.csv: remap; links touching a centroid are REWIRED to its super ---
    # Pass ALL original columns through (datasets differ in case/naming); only the
    # endpoints change. Connector attributes (length/fftt/capacity/...) are KEPT,
    # so entering the network via a super-zone costs exactly what the member
    # zone's own connector cost. Self-loops (both ends in the same super) drop.
    lhdr, lrows = csvio.read(csvio.path(scenario, "link.csv"))
    if "link_id" not in lhdr:
        lhdr = ["link_id"] + lhdr
    out_lrows = []
    nrewired = nself = 0
    for r in lrows:
        f = csvio.inum(r.get("from_node_id")); t = csvio.inum(r.get("to_node_id"))
        fc = f in zone_xy; tc = t in zone_xy
        nf = zone2super[f] if fc else old2new.get(f)
        nt = zone2super[t] if tc else old2new.get(t)
        if nf is None or nt is None:
            continue                            # endpoint absent from node.csv
        if nf == nt:
            nself += 1; continue                # collapsed into one super: drop
        if fc or tc:
            nrewired += 1
        o = {c: r.get(c, "") for c in lhdr}
        o["from_node_id"] = nf
        o["to_node_id"] = nt
        out_lrows.append(o)
    # sort by from-node internal seq (= node.csv order = new id order)
    out_lrows.sort(key=lambda r: (csvio.inum(r["from_node_id"]), csvio.inum(r["to_node_id"])))
    csvio.write(csvio.path(out_dir, "link.csv"), lhdr, out_lrows)
    rep.append(f"links {len(lrows)} -> {len(out_lrows)} ({nrewired:,} connector links "
               f"rewired to supers, {nself:,} intra-super self-loops dropped)")

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
