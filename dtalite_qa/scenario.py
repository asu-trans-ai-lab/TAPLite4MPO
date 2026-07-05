"""Scenario copilot engine -- plain language -> network edits -> build/no-build ->
measure differencing (Phase 2 of docs/NEXTA_AI_GENERATION_MODULE.md; the ADOT AI
Scenario Manager core).

Division of labor (AI proposes, deterministic code disposes):
  * the AI turns "widen US 15-501 to three lanes each way" into a structured
    EDIT SPEC (selector + actions) -- it never touches the CSVs;
  * this module deterministically locates links, applies edits, emits the build
    scenario with a scenario_manifest.json (provenance), and differences the
    standardized performance measures between runs (ADOT Task 1/2 templates).

Edit spec (JSON-able) -- the vocabulary covers the real SPR-790 scenario types
(widen by milepost range, directional lanes, ramp metering, HOV direct connectors,
NEW ramp/flyover construction, off-ramp replacement, interchange conversion):
  [{"select": {...selector...},
    "set":   {"lanes": 3, "link_type": 8, "allowed_use": "hov2;hov3"},  # absolutes
    "add":   {"lanes": 1},          # increments
    "scale": {"capacity": 1.5},     # multipliers
    "close": false,                 # allowed_use="closed"
    "remove": false},               # DELETE matched links (replacement scenarios)
   {"add_nodes": [{"node_id": 900001, "x_coord": ..., "y_coord": ...}],
    "add_links": [{"link_id": "NEW1", "from_node_id": 900001, "to_node_id": 442,
                   "lanes": 1, "capacity": 1800, "free_speed": 45, "length": 0.3,
                   "allowed_use": "", ...}]},                    # CONSTRUCTION
   {"add_movements": [{"node_id": 442, "ib_link_id": "NEW1",
                       "ob_link_id": "17", "penalty": 10}]}]     # turn bans (interchange form)
After topology edits the emitter RE-SORTS links by node.csv row order (kernel CSR
contract) and appends new nodes as through nodes (zone_id=0).

Selector fields (AND-combined; all optional):
  link_ids: [..]                    explicit external ids
  from_to:  [[f,t], ...]            explicit (from_node_id,to_node_id) pairs
  name_contains: "15-501"           searched in any name/road/route column
  route: {"col": "AZ_STATERT", "value": "I-17", "contains": true}   route column match
  mp_range: {"col": "milepost", "lo": 298, "hi": 314}               milepost window
            (or {"from_col": "MP_FROM", "to_col": "MP_TO"} overlap form)
  direction: "AB"|"BA"|"SB"...      link_id suffix (AB/BA) or a dir column value
  link_types: [1,2] / facility_types: [..]
  min_lanes / max_lanes
  corridor: {"a": [x,y], "b": [x,y], "buffer": 0.02}   both endpoints within
            `buffer` (coord units) of segment a-b
  run_dir + min_doc / top_volume_n  congestion-based selection from a prior
            run's link_performance.csv (joined on from,to)
"""
import json
import math
import os
import shutil

from . import csvio

# ---- standardized performance measures (ADOT Task 1.1 deliverable) ----------
MEASURES = {
    "VMT":        {"units": "veh-miles",  "better": "lower",
                   "what": "total vehicle miles traveled (exposure/usage)"},
    "VHT":        {"units": "veh-hours",  "better": "lower",
                   "what": "total vehicle hours traveled"},
    "avg_speed":  {"units": "mph",        "better": "higher",
                   "what": "network average speed = VMT/VHT"},
    "delay":      {"units": "veh-hours",  "better": "lower",
                   "what": "sum of volume x (congested - free-flow time)"},
    "congested_lane_miles": {"units": "lane-miles", "better": "lower",
                   "what": "lane-miles operating at D/C > 0.9"},
}
_OUTPUT_FILES = {"link_performance.csv", "od_performance.csv", "system_performance.csv",
                 "tap_log.csv", "route_assignment.csv", "vehicle.csv", "summary_log.csv",
                 "zone_accessibility.csv", "origin_accessibility.csv", "run_report.json",
                 "destination_accessibility.csv", "inaccessible_od.csv", "run_report.md",
                 "google_maps_od_distance.csv", "forensics.json", "scenario_manifest.json"}


def _num(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _pt_seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def locate(scenario, select):
    """Deterministically resolve a selector to link rows.
    Returns (matched_row_indices, link_header, all_rows, evidence_dict)."""
    hdr, rows = csvio.read(csvio.path(scenario, "link.csv"))
    low = {c.lower(): c for c in hdr}
    ev = {}

    node_xy = {}
    if select.get("corridor") and csvio.exists(scenario, "node.csv"):
        _, nrows = csvio.read(csvio.path(scenario, "node.csv"))
        for r in nrows:
            node_xy[csvio.inum(r.get("node_id"))] = (_num(r.get("x_coord"), 0), _num(r.get("y_coord"), 0))

    perf = {}
    if select.get("run_dir"):
        import csv as _csv
        with open(os.path.join(select["run_dir"], "link_performance.csv"),
                  newline="", encoding="utf-8-sig") as f:
            for r in _csv.DictReader(f):
                try:
                    perf[(int(r["from_node_id"]), int(r["to_node_id"]))] = \
                        (float(r.get("volume") or 0), float(r.get("doc") or 0))
                except (KeyError, ValueError):
                    continue

    name_cols = [c for c in hdr if any(k in c.lower() for k in
                 ("name", "road", "route", "corridor", "way"))]
    want_ids = set(str(x) for x in select.get("link_ids", []))
    want_ft = set(str(x) for x in (select.get("from_to") or []) and
                  [f"{f}_{t}" for f, t in select["from_to"]] or [])
    q = (select.get("name_contains") or "").lower()
    lts = set(str(x) for x in select.get("link_types", []))
    fts = set(str(x) for x in select.get("facility_types", []))
    cor = select.get("corridor")

    # external LRS reference table (appendix sidecar; the GMNS network stays
    # pristine): {"lrs": {"table": path, "route_id": "I-17", "mp_lo": 298,
    # "mp_hi": 314, "mp_dir": -1}} -> link_id allow-set joined at select time.
    if select.get("lrs"):
        import csv as _csv
        L = select["lrs"]
        allow = set()
        with open(L["table"], newline="", encoding="utf-8-sig") as f:
            for r in _csv.DictReader(f):
                if L.get("route_id") and r.get("route_id") != L["route_id"]:
                    continue
                if L.get("mp_dir") is not None and str(r.get("mp_dir")) != str(L["mp_dir"]):
                    continue
                try:
                    b, e = float(r["mp_begin"]), float(r["mp_end"])
                except (KeyError, ValueError):
                    continue
                if L.get("mp_lo") is not None and max(b, e) < L["mp_lo"]:
                    continue
                if L.get("mp_hi") is not None and min(b, e) > L["mp_hi"]:
                    continue
                allow.add(str(r["link_id"]).strip())
        want_ids = (want_ids & allow) if want_ids else allow

    route = select.get("route")
    mp = select.get("mp_range")
    direction = (select.get("direction") or "").upper()
    dir_col = low.get("dir") or low.get("direction") or low.get("dir_flag")

    matched = []
    for i, r in enumerate(rows):
        if want_ids and str(r.get(low.get("link_id", ""), "")).strip() not in want_ids:
            continue
        f, t = csvio.inum(r.get(low.get("from_node_id", ""))), csvio.inum(r.get(low.get("to_node_id", "")))
        if want_ft and f"{f}_{t}" not in want_ft:
            continue
        if q and not any(q in str(r.get(c, "")).lower() for c in name_cols):
            continue
        if route:
            col = low.get(route["col"].lower(), route["col"])
            val = str(r.get(col, "") or "")
            want = str(route["value"])
            if (want.lower() not in val.lower()) if route.get("contains", True) else (val != want):
                continue
        if mp:
            if "col" in mp:
                v = _num(r.get(low.get(mp["col"].lower(), mp["col"])), None)
                if v is None or not (mp["lo"] <= v <= mp["hi"]):
                    continue
            else:  # (from_col,to_col) overlap form
                a = _num(r.get(low.get(mp["from_col"].lower(), mp["from_col"])), None)
                b = _num(r.get(low.get(mp["to_col"].lower(), mp["to_col"])), None)
                if a is None or b is None or max(a, b) < mp["lo"] or min(a, b) > mp["hi"]:
                    continue
        if direction:
            li = str(r.get(low.get("link_id", ""), "") or "")
            dv = str(r.get(dir_col, "") or "") if dir_col else ""
            if not (li.upper().endswith(direction) or dv.upper() == direction):
                continue
        if lts and str(csvio.inum(r.get(low.get("link_type", ""), ""), -1)) not in lts:
            continue
        if fts and str(csvio.inum(r.get(low.get("facility_type", ""), ""), -1)) not in fts:
            continue
        ln = _num(r.get(low.get("lanes", ""), ""), 0)
        if select.get("min_lanes") is not None and ln < select["min_lanes"]:
            continue
        if select.get("max_lanes") is not None and ln > select["max_lanes"]:
            continue
        if cor:
            pa, pb = node_xy.get(f), node_xy.get(t)
            if not pa or not pb:
                continue
            buf = cor.get("buffer", 0.02)
            if (_pt_seg_dist(pa, cor["a"], cor["b"]) > buf or
                    _pt_seg_dist(pb, cor["a"], cor["b"]) > buf):
                continue
        if select.get("min_doc") is not None:
            v = perf.get((f, t))
            if not v or v[1] < select["min_doc"]:
                continue
        matched.append(i)

    if select.get("top_volume_n") and perf:
        matched.sort(key=lambda i: -perf.get(
            (csvio.inum(rows[i].get(low.get("from_node_id", ""))),
             csvio.inum(rows[i].get(low.get("to_node_id", "")))), (0, 0))[0])
        matched = matched[: select["top_volume_n"]]
    ev["n_matched"] = len(matched)
    ev["name_columns_searched"] = name_cols
    return matched, hdr, rows, ev


def build(scenario, out_dir, edits, description=""):
    """Emit the BUILD scenario: copy inputs, apply edits (attribute changes, link
    removal, NEW node/link construction, movement/turn edits), re-sort links by
    node order (kernel CSR contract), write provenance. Returns the manifest."""
    os.makedirs(out_dir, exist_ok=True)
    hdr, rows = csvio.read(csvio.path(scenario, "link.csv"))
    low = {c.lower(): c for c in hdr}
    nhdr, nrows = csvio.read(csvio.path(scenario, "node.csv"))
    log = []
    removed = set()
    topo_changed = False
    new_movements = []
    for k, ed in enumerate(edits):
        entry = {"edit": k, "select": ed.get("select", {}),
                 "actions": {a: ed[a] for a in
                             ("set", "add", "scale", "close", "remove",
                              "add_nodes", "add_links", "add_movements") if ed.get(a)}}
        before = []
        n_matched = 0
        if ed.get("select") is not None and any(ed.get(a) for a in
                                                ("set", "add", "scale", "close", "remove")):
            idx, _, _, ev = locate(scenario, ed.get("select", {}))
            n_matched = ev["n_matched"]
            for i in idx:
                r = rows[i]
                rec = {"link_id": r.get(low.get("link_id", ""), ""),
                       "from": r.get(low.get("from_node_id", "")), "to": r.get(low.get("to_node_id", ""))}
                for col, val in (ed.get("set") or {}).items():
                    c = low.get(col.lower(), col)
                    if c not in hdr:
                        hdr.append(c)
                        low[c.lower()] = c
                    rec[f"{col}:before"] = r.get(c)
                    r[c] = val
                for col, inc in (ed.get("add") or {}).items():
                    c = low.get(col.lower(), col)
                    rec[f"{col}:before"] = r.get(c)
                    r[c] = (_num(r.get(c), 0) or 0) + inc
                for col, fac in (ed.get("scale") or {}).items():
                    c = low.get(col.lower(), col)
                    rec[f"{col}:before"] = r.get(c)
                    r[c] = round((_num(r.get(c), 0) or 0) * fac, 4)
                if ed.get("close"):
                    c = low.get("allowed_use", "allowed_use")
                    if c not in hdr:
                        hdr.append(c)
                        low[c.lower()] = c
                    rec["allowed_use:before"] = r.get(c, "")
                    r[c] = "closed"
                if ed.get("remove"):
                    rec["removed"] = True
                    removed.add(i)
                    topo_changed = True
                before.append(rec)
        # construction: new through nodes + new links (any column; missing cols added)
        for nn in ed.get("add_nodes") or []:
            rec = dict(nn)
            rec.setdefault("zone_id", 0)               # through node
            nrows.append({c: rec.get(c, "") for c in nhdr})
            topo_changed = True
        for nl in ed.get("add_links") or []:
            for c in nl:
                cc = low.get(c.lower())
                if cc is None:
                    hdr.append(c)
                    low[c.lower()] = c
            rows.append({low.get(c.lower(), c): v for c, v in nl.items()})
            topo_changed = True
        for mv in ed.get("add_movements") or []:
            new_movements.append(mv)
        entry["n_matched"] = n_matched
        entry["links"] = before[:50]
        log.append(entry)

    rows = [r for i, r in enumerate(rows) if i not in removed]
    # kernel CSR contract: links sorted by the from-node's node.csv row position
    if topo_changed:
        pos = {csvio.inum(r.get("node_id")): i for i, r in enumerate(nrows)}
        big = len(pos) + 1
        rows.sort(key=lambda r: (pos.get(csvio.inum(r.get(low.get("from_node_id", "from_node_id"))), big),
                                 pos.get(csvio.inum(r.get(low.get("to_node_id", "to_node_id"))), big)))

    # copy inputs (skip outputs), then write edited files
    for name in os.listdir(scenario):
        src = os.path.join(scenario, name)
        if (os.path.isfile(src) and name.lower() not in _OUTPUT_FILES
                and not name.lower().startswith(("summary_log", "tap_log", "log"))):
            shutil.copy(src, os.path.join(out_dir, name))
    csvio.write(csvio.path(out_dir, "link.csv"), hdr, [{c: r.get(c, "") for c in hdr} for r in rows])
    if topo_changed:
        csvio.write(csvio.path(out_dir, "node.csv"), nhdr, nrows)
    if new_movements:
        mpath = csvio.path(out_dir, "movement.csv")
        mhdr = ["mvmt_id", "node_id", "ib_link_id", "ob_link_id", "penalty"]
        mrows = []
        if csvio.exists(scenario, "movement.csv"):
            mhdr, mrows = csvio.read(csvio.path(scenario, "movement.csv"))
        base = len(mrows)
        for j, mv in enumerate(new_movements):
            row = {c: "" for c in mhdr}
            row.update({"mvmt_id": mv.get("mvmt_id", base + j + 1), **mv})
            mrows.append(row)
        csvio.write(mpath, mhdr, mrows)
    manifest = {"description": description, "base_scenario": os.path.abspath(scenario),
                "edits": log, "total_links_edited": sum(e["n_matched"] for e in log),
                "links_removed": len(removed),
                "links_added": sum(len(e.get("add_links") or []) for e in edits),
                "nodes_added": sum(len(e.get("add_nodes") or []) for e in edits),
                "movements_added": len(new_movements)}
    open(os.path.join(out_dir, "scenario_manifest.json"), "w", encoding="utf-8").write(
        json.dumps(manifest, indent=2, default=str))
    return manifest


def measures(run_dir, corridor_keys=None):
    """Standardized measures from a run's link_performance.csv. corridor_keys:
    optional set of (from,to) for corridor-level aggregation alongside region."""
    import csv as _csv
    reg = dict(VMT=0.0, VHT=0.0, delay=0.0, congested_lane_miles=0.0)
    cor = dict(VMT=0.0, VHT=0.0, delay=0.0, volume=0.0) if corridor_keys else None
    with open(os.path.join(run_dir, "link_performance.csv"), newline="", encoding="utf-8-sig") as f:
        for r in _csv.DictReader(f):
            vol = _num(r.get("volume"), 0) or 0
            vmt = _num(r.get("VMT"), 0) or 0
            vht = _num(r.get("VHT"), 0) or 0
            tt = _num(r.get("travel_time"), 0) or 0
            ff = _num(r.get("vdf_fftt"), 0) or 0
            doc = _num(r.get("doc"), 0) or 0
            lanes = _num(r.get("lanes"), 1) or 1
            reg["VMT"] += vmt
            reg["VHT"] += vht
            reg["delay"] += vol * max(0.0, tt - ff) / 60.0
            if doc > 0.9 and vol > 0:
                reg["congested_lane_miles"] += lanes * (vmt / vol)
            if cor is not None:
                try:
                    key = (int(r["from_node_id"]), int(r["to_node_id"]))
                except (KeyError, ValueError):
                    key = None
                if key in corridor_keys:
                    cor["VMT"] += vmt
                    cor["VHT"] += vht
                    cor["volume"] += vol
                    cor["delay"] += vol * max(0.0, tt - ff) / 60.0
    reg["avg_speed"] = reg["VMT"] / reg["VHT"] if reg["VHT"] else 0.0
    out = {"region": reg}
    if cor is not None:
        cor["avg_speed"] = cor["VMT"] / cor["VHT"] if cor["VHT"] else 0.0
        out["corridor"] = cor
    return out


def diff(nobuild_run, build_run, corridor_keys=None, description=""):
    """Difference the standardized measures between two runs (the Task 1/2 record)."""
    a = measures(nobuild_run, corridor_keys)
    b = measures(build_run, corridor_keys)
    rep = {"description": description, "nobuild": nobuild_run, "build": build_run, "rows": []}
    for scope in [s for s in ("region", "corridor") if s in a]:
        for m in ("VMT", "VHT", "avg_speed", "delay", "congested_lane_miles"):
            if m not in a[scope]:
                continue
            va, vb = a[scope][m], b[scope][m]
            spec = MEASURES[m]
            improved = (vb < va) if spec["better"] == "lower" else (vb > va)
            rep["rows"].append({"scope": scope, "measure": m, "units": spec["units"],
                                "better": spec["better"], "nobuild": round(va, 1),
                                "build": round(vb, 1), "delta": round(vb - va, 1),
                                "pct": round(100 * (vb - va) / va, 2) if va else None,
                                "improved": bool(improved)})
    return rep


def render_diff(rep):
    L = [f"scenario comparison: {rep.get('description') or '(no description)'}",
         f"  no-build: {rep['nobuild']}",
         f"  build:    {rep['build']}", "",
         f"  {'scope':9} {'measure':22} {'units':11} {'no-build':>12} {'build':>12} "
         f"{'delta':>10} {'%':>7}  verdict"]
    for r in rep["rows"]:
        v = "IMPROVED" if r["improved"] else ("worse" if r["delta"] != 0 else "-")
        L.append(f"  {r['scope']:9} {r['measure']:22} {r['units']:11} {r['nobuild']:>12,.1f} "
                 f"{r['build']:>12,.1f} {r['delta']:>10,.1f} "
                 f"{(str(r['pct']) + '%') if r['pct'] is not None else '-':>7}  {v}")
    return "\n".join(L)
