"""Agent tool manifest -- the programmatic surface of the AI generation module.

Phase 1 of docs/NEXTA_AI_GENERATION_MODULE.md: every capability an agent needs for
the INSPECT -> DECLARE -> GENERATE -> VERIFY -> REPORT loop, exposed as named tools
with JSON-able args/results. An LLM agent (or an MCP server wrapping this) calls
`call(name, **kwargs)`; `manifest()` returns the tool schemas.

Design rule: the AI proposes, deterministic code disposes -- these tools ARE the
deterministic code. The agent orchestrates; it never fabricates data.
"""
import importlib
import json

TOOLS = [
    # ---- INSPECT ----
    dict(name="forensics", phase="inspect",
         desc="Run the convention-detector battery on a dataset folder (units, "
              "capacity/PLF conventions, Excel truncation, AB/BA ids, sort order, "
              "zone model, demand coverage). Returns findings with severities "
              "BLOCK / DECLARE / INFO.",
         args={"scenario": "path", "quick": "bool (skip big-file line counts)"},
         impl="dtalite_qa.forensics:run"),
    dict(name="inventory", phase="inspect",
         desc="Network inventory: allowed_use tokens, link types, modes.",
         args={"scenario": "path"}, impl="dtalite_qa.inventory:build"),
    # ---- VERIFY (contract) ----
    dict(name="validate", phase="verify",
         desc="Kernel input-contract validation (errors/warnings).",
         args={"scenario": "path"}, impl="dtalite_qa.validate:validate"),
    dict(name="accessibility", phase="verify",
         desc="Per-mode zone connectivity check (SCC-based).",
         args={"scenario": "path"}, impl="dtalite_qa.accessibility:check"),
    dict(name="plf_check", phase="verify",
         desc="PLF inventory with memo bounds (0<PLF<=1, phi=L*PLF>=1); flags flat PLF.",
         args={"scenario": "path", "period_hours": "float?", "phi_profile": "dict?"},
         impl="dtalite_qa.plf:check"),
    # ---- GENERATE (deterministic emitters) ----
    dict(name="adapt", phase="generate",
         desc="Convert an older/foreign GMNS scenario (old-TAPLite style: caps VDF_*, "
              "mph/mi units, lanes=0 repair, missing-zone demand filter) to current format.",
         args={"scenario": "path", "out_dir": "path", "free_speed": "mph|kmph",
               "length": "mi|m", "do_filter_demand": "bool", "mag_vdf_2015": "bool"},
         impl="dtalite_qa.adapt:adapt"),
    dict(name="nexta_convert", phase="generate",
         desc="Convert a NeXTA/old-DTALite multi-period scenario to current single-period "
              "GMNS (period VDF selection, hourly cap + real PLF, node.csv-order sort, "
              "binary demand).",
         args={"scenario": "path", "out_dir": "path", "period_name": "AM|MD|PM|NT",
               "iterations": "int?", "plf": "float?", "plf_arterial": "float?"},
         impl="dtalite_qa.nexta:convert"),
    dict(name="demand_bin", phase="generate",
         desc="Convert demand CSVs to fast binary .bin (set demand_format=1).",
         args={"scenario": "path"}, impl="dtalite_qa.demandbin:convert_scenario"),
    dict(name="fill_defaults", phase="generate",
         desc="Write a normalized copy: kernel defaults filled, links sorted.",
         args={"scenario": "path", "out_dir": "path"}, impl="dtalite_qa.fill:fill"),
    dict(name="superzone_build", phase="generate",
         desc="Hierarchical super-zone network (compression): super-zones as the only "
              "centroids, originals demoted to through nodes, zero-cost connectors. "
              "Corner-case-exact at 1:1. zone2super from superzone_encoders.",
         args={"scenario": "path", "out_dir": "path", "k_target": "int?",
               "zone2super": "dict?"},
         impl="dtalite_qa.superzone_hier:build"),
    dict(name="encoder_demand_kmeans", phase="generate",
         desc="Recommended super-zone encoder: demand-weighted k-means zone map.",
         args={"scenario": "path", "K": "int"},
         impl="dtalite_qa.superzone_encoders:demand_kmeans"),
    # ---- SCENARIO (Phase 2: plain language -> build/no-build) ----
    dict(name="locate_links", phase="generate",
         desc="Deterministically resolve a structured selector (name_contains, "
              "link_types, corridor geometry, min_doc/top_volume from a prior run, "
              "link_ids/from_to) to network links. The AI drafts the selector from "
              "plain language; this resolves it with evidence.",
         args={"scenario": "path", "select": "selector dict"},
         impl="dtalite_qa.scenario:locate"),
    dict(name="scenario_build", phase="generate",
         desc="Emit a BUILD scenario: copy inputs, apply structured edits "
              "(set/add/scale lanes, capacity, free_speed; close), write "
              "scenario_manifest.json provenance.",
         args={"scenario": "path", "out_dir": "path", "edits": "list of edit specs",
               "description": "str"},
         impl="dtalite_qa.scenario:build"),
    dict(name="scenario_diff", phase="report",
         desc="Difference the standardized performance measures (VMT/VHT/avg_speed/"
              "delay/congested_lane_miles, region + corridor scope, with units and "
              "direction-of-preference) between a no-build and build run.",
         args={"nobuild_run": "path", "build_run": "path",
               "corridor_keys": "set of (from,to)?", "description": "str"},
         impl="dtalite_qa.scenario:diff"),
    # ---- LRS conflation (WP_LRS2GMNS) ----
    dict(name="azgeo_fetch", phase="inspect",
         desc="Download an AZGeo REST layer (atis_roads PolylineM m=milepost, "
              "mileposts points) with pagination + disk cache. Milepost highway "
              "filter uses ONROAD (padded '  I 017' convention), RETIRED=0.",
         args={"layer": "atis_roads|mileposts|url", "where": "SQL", "cache_dir": "path"},
         impl="dtalite_qa.lrs2gmns:fetch_azgeo"),
    dict(name="lrs_tier0", phase="generate",
         desc="Harvest route ids + name-decoded milepost anchors from a link table "
              "(ADOT convention '008100E' = route 008, MP 100, dir E; free text "
              "'WB US60 EX 176A ON'). Returns (anchors, stats). Validated 16/16 vs "
              "hand-coded TIP mileposts.",
         args={"rows": "list of link dicts", "name_col": "str"},
         impl="dtalite_qa.lrs2gmns:tier0"),
    # ---- RUN / EVIDENCE ----
    dict(name="run_kernel", phase="verify",
         desc="QA gate then run the assignment kernel on the normalized scenario.",
         args={"scenario": "path", "exe": "path", "out_dir": "path?"},
         impl="dtalite_qa.control:run"),
    dict(name="report", phase="report",
         desc="Run report incl. reference comparison (joins on from/to; R^2, %RMSE) "
              "when ref_volume/ref_time are present.",
         args={"run_dir": "path"}, impl="dtalite_qa.report:build"),
    dict(name="skim_build", phase="report",
         desc="Original-resolution NxN congested skim from a run's link times "
              "(the supply->demand decoder for 4-step feedback).",
         args={"scenario": "path", "times": "dict[(from,to)->minutes]"},
         impl="dtalite_qa.skim:skim"),
]


def manifest(as_json=True):
    m = [{k: v for k, v in t.items() if k != "impl"} for t in TOOLS]
    return json.dumps(m, indent=2) if as_json else m


def call(name, **kwargs):
    """Dispatch a tool call to its deterministic implementation."""
    for t in TOOLS:
        if t["name"] == name:
            mod, fn = t["impl"].split(":")
            return getattr(importlib.import_module(mod), fn)(**kwargs)
    raise KeyError(f"unknown tool {name!r}; available: {[t['name'] for t in TOOLS]}")
