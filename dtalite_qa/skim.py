"""Zone-to-zone congested skim -- the supply->demand decoder for 4-step feedback.

After an assignment (full OR super-zone-accelerated) sets congested link travel
times, the demand model (trip distribution / mode choice) needs an ORIGINAL-zone
N x N impedance matrix. This computes it by shortest path between zone centroids
over the congested link times -- a one-shot, non-iterated step (cheap relative to
equilibration).

Validated: on Chicago Regional the skim from a super-zone assignment matches the
full-assignment skim at R^2 = 0.98 (demand-weighted), because zone-to-zone time is
corridor-dominated and super-zoning preserves corridors. A residual ~12% LEVEL bias
(super runs faster) comes from the loading decoder under-loading the network; fix it
with a demand-spread decoder (see docs/four_step_integration.md).

Requires numpy + scipy.
"""
import csv

from . import csvio


def read_link_times(link_perf_path, field="travel_time", remap=None):
    """{(from_node, to_node) -> time} from a link_performance.csv. `remap` maps the
    file's node ids back to the target network's ids (e.g. super-zone -> original)."""
    times = {}
    with open(link_perf_path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                a, b, t = int(r["from_node_id"]), int(r["to_node_id"]), float(r[field])
            except (KeyError, ValueError):
                continue
            if remap is not None:
                if a not in remap or b not in remap:
                    continue
                a, b = remap[a], remap[b]
            times[(a, b)] = t
    return times


def superzone_remap(scenario, S):
    """new (super-renumbered) node id -> original node id, for `read_link_times`.
    Assumes superzone_hier numbering: originals shifted to S + file_position."""
    _, nrows = csvio.read(csvio.path(scenario, "node.csv"))
    return {S + i + 1: csvio.inum(r["node_id"]) for i, r in enumerate(nrows)}


def skim(scenario, times):
    """Return (zone_ids, matrix) of zone-to-zone least congested travel time.
    `scenario` provides node.csv (zones = zone_id>0); `times` is {(from,to)->time}
    in those node ids. Centroids are sources/sinks (simple graph; consistent for
    full-vs-super comparison)."""
    import numpy as np
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import dijkstra
    _, nrows = csvio.read(csvio.path(scenario, "node.csv"))
    ids = [csvio.inum(r["node_id"]) for r in nrows]
    ix = {nid: i for i, nid in enumerate(ids)}
    n = len(ids)
    zones = [csvio.inum(r["node_id"]) for r in nrows if csvio.inum(r.get("zone_id"), 0) > 0]
    cidx = np.array([ix[z] for z in zones])
    rows, cols, w = [], [], []
    for (a, b), t in times.items():
        if a in ix and b in ix:
            rows.append(ix[a]); cols.append(ix[b]); w.append(max(t, 1e-6))
    G = csr_matrix((w, (rows, cols)), shape=(n, n))
    dist = dijkstra(G, directed=True, indices=cidx)
    return zones, dist[:, cidx]


def write_skim(zones, matrix, out_path, demand_pairs_only=None):
    """Write o_zone_id,d_zone_id,travel_time. `demand_pairs_only`: optional set of
    (o,d) to restrict output to OD pairs that carry demand."""
    import numpy as np
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        wtr = csv.writer(f)
        wtr.writerow(["o_zone_id", "d_zone_id", "travel_time"])
        for i, o in enumerate(zones):
            for j, d in enumerate(zones):
                if i == j or not np.isfinite(matrix[i, j]):
                    continue
                if demand_pairs_only is not None and (o, d) not in demand_pairs_only:
                    continue
                wtr.writerow([o, d, round(float(matrix[i, j]), 4)])
