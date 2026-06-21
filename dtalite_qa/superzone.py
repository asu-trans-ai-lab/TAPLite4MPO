"""Super-zone aggregation for fast (approximate) static assignment.

The kernel skips zero-demand origins and zero OD pairs (TAPLite.cpp:1296,1323),
so AGGREGATING THE OD MATRIX to one representative centroid per super-zone -- with
node.csv and link.csv left UNCHANGED -- cuts both the shortest-path trees
(#origins) and the flow loading (#OD pairs) by the aggregation ratio. The full
road network and all link attributes are preserved; the only approximation is that
each super-zone's demand enters/exits the network at its representative zone's
centroid (and intra-super-zone trips are dropped).

Clustering: balanced quantile grid (~sqrt(K) bins per axis) on zone coordinates.
Representative = the member zone with the largest total demand (best connected).
"""
import bisect
import math

from . import csvio


def _zone_coords(scenario):
    _, nodes = csvio.read(csvio.path(scenario, "node.csv"))
    z = {}
    for r in nodes:
        zid = csvio.inum(r.get("zone_id"), 0)
        if zid > 0:
            z[zid] = (csvio.fnum(r.get("x_coord")), csvio.fnum(r.get("y_coord")))
    return z


def _read_od(path):
    """Yield (o, d, vol) from a demand CSV (ignores a leading empty column)."""
    import csv
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.reader(f)
        h = next(r)
        try:
            oi, di, vi = h.index("o_zone_id"), h.index("d_zone_id"), h.index("volume")
        except ValueError:
            oi, di, vi = 0, 1, 2
        for row in r:
            try:
                yield int(float(row[oi])), int(float(row[di])), float(row[vi])
            except (IndexError, ValueError):
                continue


def build_map(zone_xy, zone_demand, k_target):
    """Return {zone_id -> rep_zone_id} via a quantile grid; rep = max-demand member."""
    zones = list(zone_xy)
    g = max(1, int(round(math.sqrt(k_target))))
    xs = sorted(zone_xy[z][0] for z in zones)
    ys = sorted(zone_xy[z][1] for z in zones)

    def edges(vals):
        return [vals[min(len(vals) - 1, int(len(vals) * i / g))] for i in range(1, g)]

    xe, ye = edges(xs), edges(ys)
    cells = {}
    for z in zones:
        x, y = zone_xy[z]
        key = (bisect.bisect_right(xe, x), bisect.bisect_right(ye, y))
        cells.setdefault(key, []).append(z)
    zone2rep = {}
    reps = {}
    for key, members in cells.items():
        rep = max(members, key=lambda z: zone_demand.get(z, 0.0))
        reps[key] = rep
        for z in members:
            zone2rep[z] = rep
    return zone2rep, len(cells)


def aggregate_demand(in_csv, out_csv, zone2rep):
    """Aggregate one demand CSV to super-zone reps; drop intra-super-zone trips.
    Returns (n_pairs_in, n_pairs_out, vol_in, vol_out)."""
    agg = {}
    nin = 0
    vin = 0.0
    for o, d, v in _read_od(in_csv):
        nin += 1
        vin += v
        ro = zone2rep.get(o, o)
        rd = zone2rep.get(d, d)
        if ro == rd:
            continue            # intra-super-zone trip -> dropped
        agg[(ro, rd)] = agg.get((ro, rd), 0.0) + v
    import csv
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["o_zone_id", "d_zone_id", "volume"])
        for (o, d), v in agg.items():
            w.writerow([o, d, v])
    vout = sum(agg.values())
    return nin, len(agg), vin, vout
