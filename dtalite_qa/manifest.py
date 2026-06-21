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
    "speed": "mph (vdf_free_speed_mph, cutoff_speed); 'free_speed' is km/h unless overridden",
    "capacity": "veh/hour/lane",
    "travel_time_output": "minutes",
    "volume": "vehicles over the analysis period",
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
