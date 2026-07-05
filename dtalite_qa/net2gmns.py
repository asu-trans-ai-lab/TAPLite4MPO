"""Config-driven agency-network -> GMNS converter (WP-01 transcad2gmns +
WP-02 cube2gmns in one engine).

The tool never guesses: every convention comes from a JSON config (the machine-readable
twin of submission.yml). TransCAD exports are one-record-per-physical-link with AB_/BA_
directional fields + a DIR flag; Cube exports are usually already directed (A/B per
record). Both are the same conversion once the config declares which.

Requires pandas (+ geopandas/pyogrio and scipy only when reading shapefiles /
deriving endpoints from geometry). The stdlib control core of dtalite_qa does not
import this module.

Config keys (JSON; see github_taplite/docs/*EXPORT_GUIDE*.md for the export side):
{
  "directed": false,                  // false = TransCAD AB/BA+DIR, true = Cube-style
  "id_field": "ID",
  "dir_field": "DIR",                 // when directed=false
  "a_field": null, "b_field": null,   // node-id fields; null -> derive from geometry
  "length_field": "LENGTH", "length_unit": "mi",   // mi | km | m
  "speed_unit": "mph",                              // mph | kmh
  "capacity_basis": "total",          // total -> divide by lanes | per_lane
  "capacity_period_hours": 1,         // >1 -> divide to hourly
  "fields": {                         // GMNS <- source; ab/ba or single
    "lanes":     {"ab": "AB_LANES", "ba": "BA_LANES", "default": 1},
    "capacity":  {"ab": "AB_CAP_PK", "ba": "BA_CAP_PK", "default": 800},
    "speed":     {"ab": "AB_SPEED",  "ba": "BA_SPEED",  "default": 30},
    "fftt_min":  {"ab": "AB_TIME",   "ba": "BA_TIME"},    // optional
    "factype":   {"ab": "FCLASS"},
    "vdf_alpha": {"ab": "ALPHA", "default": 0.15},
    "vdf_beta":  {"ab": "BETA",  "default": 4}
  },
  "connector": {"field": "LINK_TYPE", "values": ["CC"]},   // or factype codes
  "zone_node_field": "ZONE"           // node table column marking centroids (>0)
}
"""
import json
import math
import os
import sys

import pandas as pd

MI2M = 1609.344
MPH2KMH = 1.609344


def _read_table(path):
    if path.lower().endswith((".shp", ".dbf")):
        import geopandas as gpd
        return gpd.read_file(path)
    return pd.read_csv(path)


def _endpoints_from_geometry(links, nodes, node_id_col):
    """Derive A/B node ids by snapping link endpoints to the node layer."""
    from scipy.spatial import cKDTree
    import numpy as np
    nx = nodes.geometry.x.to_numpy() if hasattr(nodes, "geometry") else nodes["x_coord"].to_numpy()
    ny = nodes.geometry.y.to_numpy() if hasattr(nodes, "geometry") else nodes["y_coord"].to_numpy()
    ids = nodes[node_id_col].to_numpy()
    tree = cKDTree(pd.DataFrame({"x": nx, "y": ny}).to_numpy())
    starts = pd.DataFrame([g.coords[0] for g in links.geometry]).to_numpy()
    ends = pd.DataFrame([g.coords[-1] for g in links.geometry]).to_numpy()
    ds, si = tree.query(starts)
    de, ei = tree.query(ends)
    tol = 1.0  # meters-ish; projected coordinates assumed
    bad = int((ds > tol).sum() + (de > tol).sum())
    return ids[si], ids[ei], bad


def _fld(cfg, row, name, direction):
    spec = cfg["fields"].get(name)
    if spec is None:
        return None
    col = spec.get(direction) or spec.get("ab")
    v = row.get(col) if col else None
    try:
        v = float(v)
        if math.isnan(v):
            v = None
    except (TypeError, ValueError):
        v = None
    return v if v is not None else spec.get("default")


def _fld_raw(cfg, row, name, direction):
    """Read a field as a STRING (categorical facility type / class codes).

    Numeric-coercing categorical labels (e.g. HCMType "Freeway") would silently
    drop them via _fld -> None -> default. Use this for factype and other
    non-numeric fields so agencies with string classes are preserved.
    """
    spec = cfg["fields"].get(name)
    if spec is None:
        return None
    col = spec.get(direction) or spec.get("ab")
    v = row.get(col) if col else None
    if v is None:
        return spec.get("default")
    try:
        if isinstance(v, float) and math.isnan(v):
            return spec.get("default")
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    # a numeric factype like 12.0 should print as "12", not "12.0"
    try:
        f = float(s)
        if f == int(f):
            s = str(int(f))
    except (TypeError, ValueError):
        pass
    return s if s != "" else spec.get("default")


def _access_for(cfg, row):
    """Map an agency access/prohibit code to (allowed_use, toll_flag) via the
    config's reusable access_code_map preset (Cube PROHIBIT / TransCAD access
    tables). Config block:
        "access_code_map": {
          "field": "PROHIBIT",
          "codes": {"2": {"allowed_use": "hov2;hov3"}, "6": {"allowed_use": "hov3", ...}},
          "toll_field": "TOLLAM", "toll_id_field": "TOLLID"   // optional numeric->toll
        }
    Returns (allowed_use_str, toll_flag_int). No block -> ("", 0)."""
    acm = cfg.get("access_code_map")
    if not acm:
        return "", 0
    fld = acm.get("field")
    raw = row.get(fld) if fld else None
    code = None
    try:
        code = str(int(float(raw)))
    except (TypeError, ValueError):
        code = None
    entry = (acm.get("codes") or {}).get(code) if code is not None else None
    allowed = (entry or {}).get("allowed_use", "")
    toll = 1 if (entry or {}).get("toll") else 0
    for tf in (acm.get("toll_field"), acm.get("toll_id_field")):
        if tf:
            try:
                if float(row.get(tf) or 0) > 0:
                    toll = 1
            except (TypeError, ValueError):
                pass
    return allowed, toll


def convert(links_path, config_path, out_dir, nodes_path=None):
    cfg = json.load(open(config_path, encoding="utf-8"))
    os.makedirs(out_dir, exist_ok=True)
    log = {"config": os.path.abspath(config_path), "links": os.path.abspath(links_path),
           "steps": [], "assumptions": []}
    links = _read_table(links_path)
    nodes = _read_table(nodes_path) if nodes_path else None
    log["steps"].append(f"read {len(links):,} link records" +
                        (f", {len(nodes):,} node records" if nodes is not None else ""))

    # optional row filter: keep only rows where <field> CONTAINS a token (e.g. drive
    # links have DTWB containing "D"; walk/bike/transit-only geometry is excluded).
    #   "row_filter": {"field": "DTWB", "contains": "D"}
    rf = cfg.get("row_filter")
    if rf and rf.get("field") in links.columns:
        tok = str(rf.get("contains", ""))
        mask = links[rf["field"]].astype(str).str.contains(tok, na=False, regex=False)
        kept = int(mask.sum())
        log["steps"].append(
            f"row_filter {rf['field']} contains {tok!r}: kept {kept:,} of {len(links):,}")
        links = links[mask].reset_index(drop=True)

    node_id_col = cfg.get("node_id_field", "ID")
    if cfg.get("a_field") and cfg.get("b_field"):
        A = links[cfg["a_field"]].astype(int).to_numpy()
        B = links[cfg["b_field"]].astype(int).to_numpy()
    else:
        if nodes is None:
            sys.exit("no a_field/b_field in config and no node layer to derive endpoints from")
        A, B, bad = _endpoints_from_geometry(links, nodes, node_id_col)
        log["steps"].append(f"derived A/B from geometry endpoints ({bad} beyond snap tolerance)")

    # zones: nodes with zone_node_field > 0 become centroids, renumbered 1..Z first
    zfield = cfg.get("zone_node_field")
    zone_ids = {}
    if nodes is not None and zfield and zfield in nodes.columns:
        zv = pd.to_numeric(nodes[zfield], errors="coerce").fillna(0)
        excl = set(cfg.get("zone_exclude_values", []))
        zn = nodes[(zv > 0) & ~zv.isin(excl)]
        for k, (_, r) in enumerate(zn.sort_values(zfield).iterrows(), 1):
            zone_ids[int(r[node_id_col])] = k
    Z = len(zone_ids)
    newid = dict(zone_ids)
    nxt = Z + 1
    all_ids = nodes[node_id_col].astype(int) if nodes is not None else pd.Series(sorted(set(A) | set(B)))
    for nid in all_ids:
        if int(nid) not in newid:
            newid[int(nid)] = nxt
            nxt += 1
    log["steps"].append(f"zones: {Z} centroids (node_id==zone_id==1..{Z}); "
                        f"{nxt - Z - 1:,} regular nodes")

    # nodes out
    if nodes is not None:
        gx = nodes.geometry.x if hasattr(nodes, "geometry") else nodes["x_coord"]
        gy = nodes.geometry.y if hasattr(nodes, "geometry") else nodes["y_coord"]
        nd = pd.DataFrame({"org_node_id": nodes[node_id_col].astype(int),
                           "x_coord": gx.to_numpy(), "y_coord": gy.to_numpy()})
        nd["node_id"] = nd.org_node_id.map(newid)
        nd["zone_id"] = nd.org_node_id.map(lambda i: zone_ids.get(int(i), 0))
        nd.sort_values("node_id")[["node_id", "zone_id", "x_coord", "y_coord", "org_node_id"]] \
          .to_csv(os.path.join(out_dir, "node.csv"), index=False)

    # links out (directed)
    lu = {"mi": 1.0, "km": 0.621371, "m": 0.000621371}[cfg.get("length_unit", "mi")]
    spd_mph = (lambda s: s) if cfg.get("speed_unit", "mph") == "mph" else (lambda s: s / MPH2KMH)
    cap_hourly = float(cfg.get("capacity_period_hours", 1) or 1)
    conn = cfg.get("connector") or {}
    dirf = cfg.get("dir_field")
    rows = []
    lid = 0
    n_rev = 0

    has_access = bool(cfg.get("access_code_map"))

    def emit(r, fn, tn, d):
        nonlocal lid
        lid += 1
        length_mi = float(r.get(cfg.get("length_field", "LENGTH")) or 0) * lu
        is_conn = conn and str(r.get(conn.get("field"))) in [str(v) for v in conn.get("values", [])]
        lanes = max(1, int(round(_fld(cfg, r, "lanes", d) or 1)))
        cap = _fld(cfg, r, "capacity", d) or 800
        cap = cap / cap_hourly
        cap_pl = 99999.0 if is_conn else (cap / lanes if cfg.get("capacity_basis", "total") == "total" else cap)
        v = _fld(cfg, r, "speed", d) or 30
        mph = spd_mph(float(v))
        fftt = _fld(cfg, r, "fftt_min", d)
        if not fftt or fftt <= 0:
            fftt = 60.0 * length_mi / max(mph, 1e-6)
        rec = {
            "link_id": lid, "from_node_id": newid[int(fn)], "to_node_id": newid[int(tn)],
            "link_type": 100 if is_conn else 2,
            "lanes": 1 if is_conn else lanes,
            "capacity": round(cap_pl, 3),
            "free_speed": round(mph * MPH2KMH, 3), "vdf_free_speed_mph": round(mph, 3),
            "length": round(length_mi * MI2M, 3), "vdf_length_mi": round(length_mi, 6),
            "vdf_fftt": round(float(fftt), 6), "vdf_type": 0,
            "vdf_alpha": _fld(cfg, r, "vdf_alpha", d) or 0.15,
            "vdf_beta": _fld(cfg, r, "vdf_beta", d) or 4,
            "vdf_plf": 1,
            "factype": _fld_raw(cfg, r, "factype", d) or "",
            "org_link_id": r.get(cfg.get("id_field", "ID")),
        }
        if has_access:
            au, toll = _access_for(cfg, r)
            rec["allowed_use"] = au
            rec["toll_flag"] = toll
        rows.append(rec)

    for i, (_, r) in enumerate(links.iterrows()):
        fn, tn = A[i], B[i]
        if cfg.get("directed", False):
            emit(r, fn, tn, "ab")
            continue
        dv = int(float(r.get(dirf) or 0)) if dirf else 0
        if dv >= 0:
            emit(r, fn, tn, "ab")
        if dv <= 0:
            emit(r, tn, fn, "ba")
            n_rev += 1
    out = pd.DataFrame(rows).sort_values(["from_node_id", "to_node_id"])
    out["link_id"] = range(1, len(out) + 1)
    out.to_csv(os.path.join(out_dir, "link.csv"), index=False)
    log["steps"].append(f"emitted {len(out):,} directed links ({n_rev:,} reverse-direction)")
    log["assumptions"] += [
        f"capacity_basis={cfg.get('capacity_basis','total')} (per-lane written)",
        f"capacity_period_hours={cap_hourly} (hourly written)",
        f"length_unit={cfg.get('length_unit','mi')}, speed_unit={cfg.get('speed_unit','mph')}",
    ]
    with open(os.path.join(out_dir, "conversion_log.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, indent=1)
    print("\n".join(log["steps"]))
    print(f"wrote {out_dir} (+ conversion_log.json). Next: declare submission.yml, "
          f"then python -m dtalite_qa intake {out_dir}")
    return log


def main():
    import argparse
    ap = argparse.ArgumentParser(description="agency network -> GMNS (config-driven)")
    ap.add_argument("links", help="links shapefile/DBF/CSV (the WP-04 export)")
    ap.add_argument("--nodes", default=None)
    ap.add_argument("--config", required=True, help="JSON field-map/convention config")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    convert(a.links, a.config, a.out, nodes_path=a.nodes)


if __name__ == "__main__":
    main()
