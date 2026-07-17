"""ARC Superzone self-demo fixture builder + case-specific validation stages.

Builds the compact, redistributable ARC demonstration model from the public
ARC GMNS case bundled in this repository (examples/arc_atlanta/gmns): the
RECOGNIZABLE regional network is kept in full; computation is saved through
OD SUPERZONING (~150 origins instead of 6,031). Derived, reviewed public
data only -- no restricted agency files.

Superzone hierarchy (deterministic, reviewable -- NOT plain geographic
clustering):
  1. the top-N original zones by total demand (trip ends) become their OWN
     superzones -- this preserves downtown Atlanta, the airport, major
     employment clusters, and the high-volume external gateways;
  2. all remaining zones are grouped by a balanced quantile grid (spatial
     contiguity), giving ~K superzones total.
The mapping ships as zone_crosswalk.csv
(arc_zone_id,superzone_id,aggregation_weight,aggregation_method) and its hash
is pinned in the golden baseline.

Demand: the three vehicle classes (sov/hov2/hov3) are merged into ONE auto
class for the demo, then aggregated by the crosswalk. Conservation is
enforced to machine precision:  original_total == aggregated_total +
intrazonal_total.  INTRAZONAL demand created by aggregation is EXCLUDED from
network loading and RETAINED in the demand audit (declared, never silent).

Network: full ARC link set with connectors rewired to superzone centroids by
dtalite_qa.superzone_hier (bypass-and-delete construction; S=N corner-case
exact). Columns are trimmed (geometry/WKT dropped -- the dashboard map draws
from node coordinates) and floats rounded for package size.
"""
import csv
import hashlib
import json
import os
import shutil
import tempfile

from . import superzone_hier

K_TARGET = 150          # ~100-200 superzones per the demo design
TOP_DEMAND_OWN = 30     # highest-demand zones kept as their own superzones
KEEP_LINK_COLS = ["link_id", "from_node_id", "to_node_id", "link_type", "lanes",
                  "capacity", "free_speed", "vdf_free_speed_mph", "length",
                  "vdf_length_mi", "vdf_fftt", "vdf_type", "vdf_A", "vdf_alpha",
                  "vdf_beta", "vdf_plf", "allowed_use", "factype", "name"]
ROUND = {"capacity": 0, "free_speed": 2, "vdf_free_speed_mph": 1, "length": 1,
         "vdf_length_mi": 4, "vdf_fftt": 4, "vdf_A": 3, "vdf_alpha": 3,
         "vdf_beta": 2, "vdf_plf": 4}
CORRIDOR_NAMES = ["I-75", "I-85", "I-20", "I-285", "GA-400"]
DETERMINISTIC = {"number_of_iterations": 20, "number_of_processors": 1,
                 "assignment_method": 0, "convergence_gap_pct": 0.0,
                 "convergence_consecutive": 99, "route_output": 0,
                 "log_file": 0, "odme_mode": 0, "demand_format": 0,
                 "demand_period_starting_hours": 6,
                 "demand_period_ending_hours": 10}

SUBMISSION = """\
# ARC Superzone self-demo -- declaration (derived PUBLIC demonstration model)
agency: ARC Atlanta (superzoned demonstration derived from the public bundled GMNS case)
model_year: 2020 AM (demonstration)
contact: taplite4mpo maintainers
capacity_basis: per_lane
capacity_period: hourly
capacity_source_field: AMCAPACITY/lanes (inherited from the ARC conversion)
capacity_period_hours: 1
assignment_period: AM
period_start_hour: 6
period_end_hour: 10
peak_load_factor: 0.915
phi_hour_to_period: 3.66
plf_by_facility: none
length_unit: m
speed_unit: kmh
time_unit: min
demand_kind: vehicle_trips
demand_period_hours: 4
occupancy: 1
pce: 1
zone_id_basis: superzone ids 1..S; zone_crosswalk.csv maps original ARC TAZs
vot: 21.5
operating_cost_per_mi: 0.1729
toll_coding: none in this demonstration extract
vdf_type: 0
vdf_source: ARC Sec 7.1.2 per-FACTYPE modified BPR (inherited)
count_field: none (validated against the reviewed self-demo golden baseline)
restriction_coding: allowed_use inherited from the ARC conversion
# INTRAZONAL DECLARATION: demand whose origin and destination fall in the same
# superzone is EXCLUDED from network loading and RETAINED in the demand audit
# (see build_report.json). This is the standard superzone treatment; the audit
# reports its exact magnitude and share.
"""


def _read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hierarchy_mapping(gmns, k_target=K_TARGET, top_own=TOP_DEMAND_OWN):
    """Deterministic demand-aware superzone mapping. Returns (z2s, method_by_zone)."""
    nodes = _read_rows(os.path.join(gmns, "node.csv"))
    zone_xy = {int(float(r["node_id"])): (float(r["x_coord"]), float(r["y_coord"]))
               for r in nodes if float(r.get("zone_id") or 0) >= 1}
    ends = dict.fromkeys(zone_xy, 0.0)                 # trip ends per zone
    for df in ("demand_sov.csv", "demand_hov2.csv", "demand_hov3.csv", "demand.csv"):
        p = os.path.join(gmns, df)
        if not os.path.exists(p):
            continue
        with open(p, newline="", encoding="utf-8-sig") as f:
            rd = csv.reader(f)
            next(rd)
            for row in rd:
                try:
                    o, d, v = int(float(row[0])), int(float(row[1])), float(row[2])
                except (IndexError, ValueError):
                    continue
                if o in ends:
                    ends[o] += v
                if d in ends:
                    ends[d] += v

    own = sorted(sorted(ends, key=lambda z: (-ends[z], z))[:top_own])
    z2s, method = {}, {}
    for i, z in enumerate(own, start=1):               # activity centers/gateways
        z2s[z] = i
        method[z] = "own_superzone_top_demand"
    rest_xy = {z: xy for z, xy in zone_xy.items() if z not in z2s}
    grid, _ = superzone_hier.cluster_grid(rest_xy, max(1, k_target - len(own)))
    for z, s in grid.items():
        z2s[z] = len(own) + s
        method[z] = "grid_cluster_contiguous"
    return z2s, method


def build_fixture(gmns, out_dir, k_target=K_TARGET, top_own=TOP_DEMAND_OWN):
    """Build the redistributable ARC Superzone fixture. Returns build_report dict."""
    os.makedirs(out_dir, exist_ok=True)
    z2s, method = hierarchy_mapping(gmns, k_target, top_own)
    S = max(z2s.values())

    # crosswalk (deterministic, reviewable)
    xwalk = os.path.join(out_dir, "zone_crosswalk.csv")
    with open(xwalk, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["arc_zone_id", "superzone_id", "aggregation_weight",
                    "aggregation_method"])
        for z in sorted(z2s):
            w.writerow([z, z2s[z], 1.0, method[z]])

    # single merged auto class in a temp source scenario, then superzone it
    with tempfile.TemporaryDirectory(prefix="arc_szdemo_") as td:
        for f in ("node.csv", "link.csv", "settings.csv"):
            shutil.copy(os.path.join(gmns, f), os.path.join(td, f))
        total_in = 0.0
        pairs_in = 0
        merged = {}
        for df in ("demand_sov.csv", "demand_hov2.csv", "demand_hov3.csv"):
            with open(os.path.join(gmns, df), newline="", encoding="utf-8-sig") as f:
                rd = csv.reader(f)
                next(rd)
                for row in rd:
                    o, d, v = int(float(row[0])), int(float(row[1])), float(row[2])
                    pairs_in += 1
                    total_in += v
                    merged[(o, d)] = merged.get((o, d), 0.0) + v
        with open(os.path.join(td, "demand.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["o_zone_id", "d_zone_id", "volume"])
            for (o, d), v in sorted(merged.items()):
                w.writerow([o, d, round(v, 6)])
        with open(os.path.join(td, "mode_type.csv"), "w", newline="",
                  encoding="utf-8") as f:
            f.write("mode_type_id,mode_type,name,vot,pce,occ,operating_cost,"
                    "demand_file,dedicated_shortest_path\n"
                    "1,auto,AUTO,21.5,1,1,0.1729,demand.csv,1\n")
        intrazonal = sum(v for (o, d), v in merged.items()
                         if z2s.get(o) is not None and z2s.get(o) == z2s.get(d))
        superzone_hier.build(td, out_dir, zone2super=z2s)

    # trim + round the network for package size (geometry dropped: the map
    # draws from node coordinates)
    lp = os.path.join(out_dir, "link.csv")
    rows = _read_rows(lp)
    with open(lp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=KEEP_LINK_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            for c, nd in ROUND.items():
                if r.get(c) not in (None, ""):
                    try:
                        r[c] = round(float(r[c]), nd) if nd else int(float(r[c]))
                    except ValueError:
                        pass
            w.writerow(r)
    np_ = os.path.join(out_dir, "node.csv")
    nrows = _read_rows(np_)
    with open(np_, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["node_id", "zone_id", "x_coord", "y_coord"])
        w.writeheader()
        for r in nrows:
            r = {k: r.get(k, "") for k in ("node_id", "zone_id", "x_coord", "y_coord")}
            for c in ("x_coord", "y_coord"):
                try:
                    r[c] = round(float(r[c]), 5)
                except (TypeError, ValueError):
                    pass
            w.writerow(r)

    # deterministic settings + declaration
    with open(os.path.join(out_dir, "settings.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(DETERMINISTIC) +
                           ["first_through_node_id"])
        w.writeheader()
        w.writerow(dict(DETERMINISTIC, first_through_node_id=-1))
    with open(os.path.join(out_dir, "submission.yml"), "w", encoding="utf-8") as f:
        f.write(SUBMISSION)

    # aggregated totals + conservation
    agg_total = 0.0
    agg_pairs = 0
    with open(os.path.join(out_dir, "demand.csv"), newline="",
              encoding="utf-8-sig") as f:
        rd = csv.reader(f)
        next(rd)
        for row in rd:
            agg_pairs += 1
            agg_total += float(row[2])
    conserved = abs(total_in - (agg_total + intrazonal)) <= 1e-6 * max(1.0, total_in)

    # corridor candidates by stable link name -> top-capacity freeway link ids
    corridors = {}
    for r in rows:
        name = (r.get("name") or "").strip()
        for c in CORRIDOR_NAMES:
            if name.startswith(c) and int(float(r.get("factype") or 0)) in (1, 2, 3, 4, 5, 6):
                key = c
                cur = corridors.get(key)
                cap = float(r.get("capacity") or 0) * float(r.get("lanes") or 1)
                if cur is None or cap > cur[1]:
                    corridors[key] = (str(r.get("link_id")), cap)
    corridor_links = {k: v[0] for k, v in sorted(corridors.items())}
    with open(os.path.join(out_dir, "corridors.json"), "w", encoding="utf-8") as f:
        json.dump(corridor_links, f, indent=1, sort_keys=True)

    report = {
        "original_zones": len(z2s),
        "superzones": S,
        "compression_ratio": round(len(z2s) / S, 2),
        "top_demand_own_superzones": top_own,
        "original_od_pairs": pairs_in,
        "merged_od_pairs_one_class": len(merged),
        "aggregated_od_pairs": agg_pairs,
        "total_demand_original": round(total_in, 4),
        "total_demand_aggregated": round(agg_total, 4),
        "intrazonal_demand": round(intrazonal, 4),
        "intrazonal_share_pct": round(100 * intrazonal / total_in, 3),
        "intrazonal_treatment": "excluded from network loading, retained in this audit",
        "demand_conserved_machine_precision": conserved,
        "corridor_links": corridor_links,
        "crosswalk_sha256": _sha256(xwalk),
    }
    with open(os.path.join(out_dir, "build_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, sort_keys=True)
    return report


# --------------------------------------------------------------- demo stages
def validate_fixture(run_dir):
    """ARC-specific pre-kernel stages. Returns [(stage, ok, detail), ...]."""
    out = []
    rep_p = os.path.join(run_dir, "build_report.json")
    try:
        with open(rep_p, encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return [("superzone fixture", False, "build_report.json missing/invalid")]

    xw = os.path.join(run_dir, "zone_crosswalk.csv")
    sha = _sha256(xw) if os.path.exists(xw) else None
    out.append(("crosswalk", sha == rep.get("crosswalk_sha256"),
                f"deterministic mapping, sha256 {str(sha)[:12]}..., "
                f"{rep['original_zones']} zones -> {rep['superzones']} superzones "
                f"({rep['compression_ratio']}x)" if sha else "zone_crosswalk.csv missing"))

    # demand conservation, re-verified from the shipped files
    agg = 0.0
    intra_pairs = 0
    with open(os.path.join(run_dir, "demand.csv"), newline="",
              encoding="utf-8-sig") as f:
        rd = csv.reader(f)
        next(rd)
        for row in rd:
            agg += float(row[2])
            if row[0] == row[1]:
                intra_pairs += 1
    tot = rep["total_demand_original"]
    ok = (abs(agg - rep["total_demand_aggregated"]) <= 1e-6 * max(1.0, agg)
          and abs(tot - (agg + rep["intrazonal_demand"])) <= 1e-6 * tot
          and intra_pairs == 0)
    out.append(("demand conservation", ok,
                f"original {tot:,.0f} == aggregated {agg:,.0f} + intrazonal "
                f"{rep['intrazonal_demand']:,.0f} ({rep['intrazonal_share_pct']}%, "
                f"{rep['intrazonal_treatment']})"))

    # every superzone has network access, both directions
    zones = set()
    with open(os.path.join(run_dir, "node.csv"), newline="",
              encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if float(r.get("zone_id") or 0) >= 1:
                zones.add(int(float(r["node_id"])))
    outb = set()
    inb = set()
    with open(os.path.join(run_dir, "link.csv"), newline="",
              encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            fn, tn = int(float(r["from_node_id"])), int(float(r["to_node_id"]))
            if fn in zones:
                outb.add(fn)
            if tn in zones:
                inb.add(tn)
    dangling = sorted(zones - (outb & inb))
    out.append(("superzone connectivity", not dangling,
                f"all {len(zones)} superzones have outbound+inbound connectors"
                if not dangling else
                f"{len(dangling)} superzones lack connectors: {dangling[:5]}"))
    return out


def corridor_volumes(run_dir):
    """{corridor: volume} for the pinned stable link_ids (corridors.json)."""
    with open(os.path.join(run_dir, "corridors.json"), encoding="utf-8") as f:
        pins = json.load(f)
    vol_by_id = {}
    with open(os.path.join(run_dir, "link_performance.csv"), newline="",
              encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            vol_by_id[str(r.get("link_id"))] = float(r.get("volume") or 0)
    return {name: round(vol_by_id.get(lid, 0.0), 2) for name, lid in pins.items()}


def svg_map(run_dir, width=880, height=660):
    """Self-contained SVG of the recognizable ARC network: freeways/ramps by
    volume, superzone centroids as dots. Drawn from node coordinates."""
    xy = {}
    zones = []
    with open(os.path.join(run_dir, "node.csv"), newline="",
              encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            nid = int(float(r["node_id"]))
            xy[nid] = (float(r["x_coord"]), float(r["y_coord"]))
            if float(r.get("zone_id") or 0) >= 1:
                zones.append(nid)
    vol = {}
    try:
        with open(os.path.join(run_dir, "link_performance.csv"), newline="",
                  encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                vol[(int(float(r["from_node_id"])), int(float(r["to_node_id"])))] = \
                    float(r.get("volume") or 0)
    except OSError:
        pass
    segs = []
    with open(os.path.join(run_dir, "link.csv"), newline="",
              encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            ft = int(float(r.get("factype") or 0))
            if ft not in (1, 2, 3, 4, 5, 6, 7, 8, 9):     # freeways + ramps only
                continue
            fn, tn = int(float(r["from_node_id"])), int(float(r["to_node_id"]))
            if fn in xy and tn in xy:
                segs.append((xy[fn], xy[tn], vol.get((fn, tn), 0.0), ft))
    if not segs:
        return "<p>(no freeway links to draw)</p>"
    xs = [p[0] for s in segs for p in (s[0], s[1])]
    ys = [p[1] for s in segs for p in (s[0], s[1])]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx = (width - 20) / max(1e-9, x1 - x0)
    sy = (height - 20) / max(1e-9, y1 - y0)

    def px(p):
        return (10 + (p[0] - x0) * sx, height - 10 - (p[1] - y0) * sy)
    vmax = max((s[2] for s in segs), default=1.0) or 1.0
    parts = [f'<svg viewBox="0 0 {width} {height}" '
             'xmlns="http://www.w3.org/2000/svg" style="background:#fff">']
    for a, b, v, ft in segs:
        (ax, ay), (bx, by) = px(a), px(b)
        w = 0.4 + 2.6 * (v / vmax)
        col = "#c0392b" if v > 0.66 * vmax else ("#e67e22" if v > 0.33 * vmax
                                                 else "#2c3e50")
        parts.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" '
                     f'y2="{by:.1f}" stroke="{col}" stroke-width="{w:.2f}" '
                     'stroke-opacity="0.75"/>')
    for z in zones:
        zx, zy = px(xy[z])
        parts.append(f'<circle cx="{zx:.1f}" cy="{zy:.1f}" r="3" fill="#1e8449" '
                     'fill-opacity="0.85"/>')
    parts.append("</svg>")
    return "".join(parts)
