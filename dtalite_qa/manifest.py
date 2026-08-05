"""GMNS field schema (machine-readable) + per-scenario manifest generation.

`field_schema()` returns a JSON-serializable description of every input file's
columns (type / required / default / units / description) -- a formal spec other
tools (and reviewers) can rely on, derived from `schema.py` so it never drifts
from the validator/filler.

`build_manifest()` produces a provenance manifest for a scenario: each file's
sha256, row count, and column list, plus the declared units, the schema version,
and (optionally) the kernel version. This is what makes an MPO assignment run
auditable and reproducible -- you can prove which exact inputs produced a result.
"""
import hashlib
import os

from . import csvio
from . import schema

SCHEMA_VERSION = "gmns-dtalite-1.0"

UNITS = {
    "length_input": "meters (link.csv 'length'); or miles via 'vdf_length_mi'",
    "speed": "mph (vdf_free_speed_mph, cutoff_speed, qvdf_start_speed_mph, qvdf_end_speed_mph); 'free_speed' is km/h unless overridden",
    "capacity": "veh/hour/lane",
    "travel_time_output": "minutes",
    "volume": "vehicles over the analysis period",
    "time_of_day": "decimal hour (link.csv 't0_hour', 't2_hour', 't3_hour')",
}

# Column documentation (merged with required/default info from schema.py).
_FIELD_DOC = {
    "link.csv": {
        "from_node_id": ("int", "origin node (must exist in node.csv)"),
        "to_node_id": ("int", "destination node (must exist in node.csv)"),
        "link_id": ("int", "external link id; preserved in all outputs"),
        "lanes": ("number", "lane count (> 0)"),
        "capacity": ("number", "PER-LANE capacity, veh/hour/lane"),
        "free_speed": ("number", "free-flow speed (km/h unless vdf_free_speed_mph given)"),
        "vdf_free_speed_mph": ("number", "free-flow speed in mph (unambiguous)"),
        "length": ("number", "length in meters (converted to miles internally)"),
        "vdf_length_mi": ("number", "length in miles; overrides 'length' when >= 0"),
        "vdf_type": ("int", "0 BPR, 1 conic, 2 QVDF"),
        "vdf_alpha": ("number", "BPR/conic alpha"),
        "vdf_beta": ("number", "BPR/conic beta"),
        "vdf_plf": ("number", "peak load factor"),
        "cutoff_speed": ("number", "speed at capacity, mph (default 0.75*free_speed)"),
        "vdf_cp": ("number", "QVDF queue parameter"),
        "vdf_cd": ("number", "QVDF queue parameter"),
        "vdf_n": ("number", "QVDF queue parameter"),
        "vdf_s": ("number", "QVDF queue parameter"),
        schema.LINK_QVDF_PROFILE_MODE_COL: (
            "int",
            "QVDF reporting profile mode: blank/absent legacy auto, 0 disabled, "
            "1 model-generated, 2 observed-t2 gated",
        ),
        schema.LINK_QVDF_T0_COL: (
            "number",
            "optional observed QVDF episode start as decimal hour-of-day; "
            "used with t2_hour and t3_hour to position the analytical duration",
        ),
        schema.LINK_QVDF_T2_COL: (
            "number",
            "observed QVDF trough time as decimal hour-of-day; link- and "
            "period-specific; blank/absent uses the assignment-period midpoint",
        ),
        schema.LINK_QVDF_T3_COL: (
            "number",
            "optional observed QVDF episode end as decimal hour-of-day; "
            "used with t0_hour and t2_hour to position the analytical duration",
        ),
        schema.LINK_QVDF_START_SPEED_COL: (
            "number",
            "optional observed speed in mph anchoring the first emitted QVDF "
            "profile sample",
        ),
        schema.LINK_QVDF_END_SPEED_COL: (
            "number",
            "optional observed speed in mph anchoring the last emitted QVDF "
            "profile sample",
        ),
        "allowed_use": ("string", "mode access control (empty/all, 'closed', or ';'-list)"),
        "non_uturn_flag": ("int", "1 bans the immediate U-turn"),
    },
    "node.csv": {
        "node_id": ("int", "unique node id"),
        "zone_id": ("int", "zone id if this node is a centroid, else 0"),
        "x_coord": ("number", "x / longitude"),
        "y_coord": ("number", "y / latitude"),
    },
    "demand.csv": {
        "o_zone_id": ("int", "origin zone id"),
        "d_zone_id": ("int", "destination zone id"),
        "volume": ("number", "demand for the analysis period (>= 0)"),
    },
    "settings.csv": {c: ("number", "") for c in schema.SETTINGS_COLUMNS},
    "mode_type.csv": {
        "mode_type": ("string", "short token used in allowed_use"),
        "vot": ("number", "value of time"),
        "pce": ("number", "passenger-car equivalent"),
        "occ": ("number", "occupancy"),
        "demand_file": ("string", "this mode's demand CSV"),
        "dedicated_shortest_path": ("int", "1 = per-mode allowed_use shortest path"),
    },
    "movement.csv": {
        "node_id": ("int", "intersection node"),
        "ib_link_id": ("int", "inbound link (external id)"),
        "ob_link_id": ("int", "outbound link (external id)"),
        "penalty": ("number", f"forbidden when >= {schema.MOVEMENT_BAN_PENALTY}"),
    },
}

_REQUIRED = {
    "link.csv": set(schema.LINK_REQUIRED),
    "node.csv": set(schema.NODE_REQUIRED) - {"zone_id"},
    "demand.csv": set(schema.DEMAND_REQUIRED),
    "settings.csv": set(),
    "mode_type.csv": {"mode_type"},
    "movement.csv": {"ib_link_id", "ob_link_id"},
}
_DEFAULTS = {
    "link.csv": dict(schema.LINK_DEFAULTS),
    "node.csv": dict(schema.NODE_DEFAULTS),
    "settings.csv": dict(schema.SETTINGS_DEFAULTS),
    "mode_type.csv": {k: v for k, v in schema.MODE_DEFAULTS.items()},
}


def field_schema():
    out = {"schema_version": SCHEMA_VERSION, "units": UNITS, "files": {}}
    for fname, cols in _FIELD_DOC.items():
        fields = []
        for col, (typ, desc) in cols.items():
            fields.append({
                "name": col, "type": typ,
                "required": col in _REQUIRED.get(fname, set()),
                "default": _DEFAULTS.get(fname, {}).get(col, None),
                "description": desc,
            })
        out["files"][fname] = {"fields": fields}
    return out


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(scenario, kernel_version=None, created=None):
    files = {}
    for name in sorted(os.listdir(scenario)):
        if not name.endswith(".csv"):
            continue
        p = os.path.join(scenario, name)
        if not os.path.isfile(p):
            continue
        header, rows = csvio.read(p)
        files[name] = {
            "sha256": _sha256(p),
            "rows": len(rows),
            "columns": header,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario": os.path.basename(os.path.abspath(scenario)),
        "created": created,            # pass an ISO timestamp from the caller if desired
        "kernel_version": kernel_version,
        "units": UNITS,
        "files": files,
    }


# ---------------------------------------------------------------------------
# M1 (NeXTA-AI roadmap): per-RUN manifest + diff -- the contract that makes a
# run reproducible and two runs comparable. build_run_manifest() is called after
# a kernel run on the run folder; diff_manifests() names what changed and what
# it did to the MOEs.
# ---------------------------------------------------------------------------

def _moe_from_link_performance(run_dir):
    import csv as _csv
    p = os.path.join(run_dir, "link_performance.csv")
    if not os.path.exists(p):
        return None
    vmt = vht = 0.0
    n = loaded = 0
    with open(p, newline="", encoding="utf-8-sig") as f:
        for r in _csv.DictReader(f):
            try:
                v = float(r.get("volume") or 0)
                vm = float(r.get("VMT") or 0)
                sp = float(r.get("speed_mph") or r.get("speed") or 0)
            except ValueError:
                continue
            n += 1
            if v > 0.5:
                loaded += 1
            vmt += vm
            if sp > 0:
                vht += vm / sp
    return {"links": n, "loaded_links": loaded, "vmt": round(vmt, 1),
            "vht": round(vht, 1),
            "mean_speed_mph": round(vmt / vht, 2) if vht > 0 else None}


def build_run_manifest(run_dir, scenario=None, exe=None, override=None,
                       intake_gate=None, created=None):
    """Everything needed to reproduce and compare this run."""
    from . import report as _report
    scenario = scenario or run_dir
    man = build_manifest(run_dir, created=created)
    man["kind"] = "run"
    man["source_scenario"] = os.path.abspath(scenario)
    if exe and os.path.exists(exe):
        man["exe"] = {"path": os.path.abspath(exe), "sha256": _sha256(exe),
                      "bytes": os.path.getsize(exe)}
    # effective settings (single row)
    sp = os.path.join(run_dir, "settings.csv")
    if os.path.exists(sp):
        hdr, rows = csvio.read(sp)
        man["effective_settings"] = dict(rows[0]) if rows else {}
    traj = _report.parse_gap(run_dir)
    man["convergence"] = {"iterations": len(traj),
                          "final_gap_pct": traj[-1]["gap_pct"] if traj else None,
                          "final_vmt": traj[-1]["system_vmt"] if traj else None,
                          "trace": traj[-8:]}
    man["moe"] = _moe_from_link_performance(run_dir)
    man["intake_gate"] = intake_gate
    man["override"] = override
    return man


def diff_manifests(a, b):
    """Compare two (run) manifests: changed inputs, changed settings, MOE deltas."""
    out = {"files": {}, "settings": {}, "moe": {}, "convergence": {}}
    fa, fb = a.get("files", {}), b.get("files", {})
    for name in sorted(set(fa) | set(fb)):
        ha = fa.get(name, {}).get("sha256")
        hb = fb.get(name, {}).get("sha256")
        if ha != hb:
            out["files"][name] = ("added" if ha is None else
                                  "removed" if hb is None else "changed")
    sa, sb = a.get("effective_settings", {}) or {}, b.get("effective_settings", {}) or {}
    for k in sorted(set(sa) | set(sb)):
        if sa.get(k) != sb.get(k):
            out["settings"][k] = {"a": sa.get(k), "b": sb.get(k)}
    ma, mb = a.get("moe") or {}, b.get("moe") or {}
    for k in sorted(set(ma) | set(mb)):
        va, vb = ma.get(k), mb.get(k)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va:
            out["moe"][k] = {"a": va, "b": vb, "pct": round((vb - va) / va * 100, 2)}
        elif va != vb:
            out["moe"][k] = {"a": va, "b": vb}
    ca, cb = a.get("convergence") or {}, b.get("convergence") or {}
    for k in ("final_gap_pct", "final_vmt", "iterations"):
        if ca.get(k) != cb.get(k):
            out["convergence"][k] = {"a": ca.get(k), "b": cb.get(k)}
    out["identical"] = not (out["files"] or out["settings"] or out["moe"] or out["convergence"])
    return out
