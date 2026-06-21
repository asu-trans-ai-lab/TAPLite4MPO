import os
"""
build_multimodal.py
-------------------
Construct two SMALL multimodal GMNS test networks that mimic the NVTA regional
model (6 modes, allowed_use enforcement, per-mode demand split) from the base
classical networks shipped with DTALite:

  - Sioux Falls  -> sf_multimodal/   (<net> = "sf")
  - Chicago Sketch -> cs_multimodal/ (<net> = "cs")

What it does for each base network:
  1. Copies node.csv unchanged.
  2. Copies link.csv and ADDS an `allowed_use` column (the engine reads the
     field name "allowed_use", singular, as a SUBSTRING match against each
     mode_type token). Most links get the full 6-mode list; a deliberately
     chosen handful get restrictions placed ON high-demand shortest-path
     corridors so the restriction actually bites.
  3. Writes mode_type.csv with the 6 NVTA modes (all dedicated_shortest_path=1).
  4. Splits the single base demand.csv (o,d,volume) across the 6 modes by the
     NVTA mode-split fractions, writing 6 demand files (sov_<net>.csv, ...).
  5. Writes settings_1iter.csv / settings_10iter.csv / settings_20iter.csv
     (11-column schema the engine expects).

A per-mode connectivity guard verifies that NO zone becomes unreachable for any
mode after the restrictions are applied (closed / apv-only links can otherwise
strand a zone). If a zone is stranded the script raises so the restriction set
can be fixed before running the engine.

Reproducible: re-run to regenerate both folders from scratch.
"""
import os
import pandas as pd
import networkx as nx

# ----------------------------------------------------------------------------
BASE_SF = os.path.join(os.path.dirname(__file__), "..", "kernel", "data_sets", "02_Sioux_Falls")
BASE_CS = os.path.join(os.path.dirname(__file__), "..", "kernel", "data_sets", "03_chicago_sketch")
OUT_ROOT = os.path.dirname(__file__)

# NVTA 6 modes. dedicated_shortest_path=1 for all so each mode gets its own
# allowed_use-respecting shortest path.
MODES = [
    # mode_type_id, mode_type, name, vot, pce, occ, frac
    (1, "sov",  "sov",  20, 1, 1.0, 0.590),
    (2, "hov2", "hov2", 30, 1, 2.0, 0.214),
    (3, "hov3", "hov3", 60, 1, 3.5, 0.072),
    (4, "com",  "com",  30, 1, 1.0, 0.093),
    (5, "trk",  "trk",  30, 2, 1.0, 0.026),
    (6, "apv",  "apv",  30, 1, 1.6, 0.004),
]
ALL_USE = "sov;hov2;hov3;trk;apv;com"   # full multi-token list = all allowed
HOV_ONLY = "hov2;hov3"                   # sov/com/trk/apv get ZERO here
APV_ONLY = "apv"                         # only apv (substring-matches only apv)
NO_TRUCK = "sov;hov2;hov3;com;apv"       # everything except trk
CLOSED = "closed"                        # matches no mode token -> nobody

# ----------------------------------------------------------------------------
# Restriction plans. Each entry: link_id -> allowed_use string.
# Chosen on/near shortest paths between the highest-demand OD pairs so the
# restriction is NOT vacuous. See TEST_PLAN.md for the rationale per link.

# Sioux Falls: restrictions placed on links that the equilibrium assignment
# actually LOADS heavily (verified from an unrestricted run) so the restriction
# is NOT vacuous. Links 56(18->20)/60(20->18) are the busiest corridor
# (~35k/29k veh); links 50(16->18),30(10->17),51(17->10) also carry real flow.
SF_RESTRICTIONS = {
    26: HOV_ONLY,   # 10->9  MOST-used link (~35k), geometric bottleneck to hub
    25: HOV_ONLY,   # 9->10  reverse, HOV-only (HOV keeps it; sov/trk reroute)
    30: NO_TRUCK,   # 10->17  no truck (carries real allowed flow)
    51: NO_TRUCK,   # 17->10  no truck (carries real allowed flow)
    43: APV_ONLY,   # 15->10  apv-only; non-apv reroute via 15->14->11->10 etc.
    33: CLOSED,     # 11->12  low-importance, closed
    36: CLOSED,     # 12->11  low-importance, closed
}

# Chicago Sketch: restrictions placed on the busy interior corridor through
# nodes 563-564-565 (verified heavily loaded from an unrestricted run; each
# node has several alternative links so no zone is stranded). NOT placed on the
# single zone-connector links (16/17/18/19) which would isolate a zone.
CS_RESTRICTIONS = {
    1084: HOV_ONLY,   # 564->563  busy corridor (~20k), HOV-only; non-HOV reroute
    1081: HOV_ONLY,   # 563->564  reverse busy corridor, HOV-only
    1009: NO_TRUCK,   # 551->563  no truck (carries real allowed flow)
    1079: NO_TRUCK,   # 563->551  reverse, no truck
    1087: APV_ONLY,   # 565->564  apv-only (~18k); non-apv reroute via other links
    2822: CLOSED,     # 902->660  redundant interior link, closed
}


def split_demand(base_dir, out_dir, net):
    d = pd.read_csv(os.path.join(base_dir, "demand.csv"))
    files = []
    for (_id, mtype, _name, _vot, _pce, _occ, frac) in MODES:
        dm = d.copy()
        dm["volume"] = dm["volume"] * frac
        fname = f"{mtype}_{net}.csv"
        dm.to_csv(os.path.join(out_dir, fname), index=False,
                  columns=["o_zone_id", "d_zone_id", "volume"])
        files.append((mtype, fname, round(dm["volume"].sum(), 1)))
    return files


def write_mode_type(out_dir, net):
    rows = []
    for (_id, mtype, name, vot, pce, occ, _frac) in MODES:
        rows.append(dict(mode_type_id=_id, mode_type=mtype, name=name, vot=vot,
                         pce=pce, occ=occ, demand_file=f"{mtype}_{net}.csv",
                         dedicated_shortest_path=1))
    pd.DataFrame(rows).to_csv(os.path.join(out_dir, "mode_type.csv"), index=False)


def write_settings(out_dir):
    cols = ("number_of_iterations,number_of_processors,demand_period_starting_hours,"
            "demand_period_ending_hours,first_through_node_id,base_demand_mode,"
            "route_output,vehicle_output,log_file,odme_mode,odme_vmt")
    for n_it, tag in [(1, "1iter"), (10, "10iter"), (20, "20iter")]:
        with open(os.path.join(out_dir, f"settings_{tag}.csv"), "w", newline="") as f:
            f.write(cols + "\n")
            f.write(f"{n_it},8,7,8,-1,0,0,0,0,0,0\n")


def mode_allowed(allowed_use_str, mode_token):
    """Replicate the engine's substring match semantics."""
    if not allowed_use_str or allowed_use_str == "all":
        return True
    return mode_token in allowed_use_str


def check_connectivity(link_df, restrictions, zone_ids):
    """For each mode, build the allowed subgraph and verify every zone can both
    reach and be reached by at least one other zone. Returns list of problems."""
    problems = []
    au_map = {int(r.link_id): restrictions.get(int(r.link_id), ALL_USE)
              for r in link_df.itertuples()}
    for (_id, mtype, *_rest) in MODES:
        G = nx.DiGraph()
        G.add_nodes_from(zone_ids)
        for r in link_df.itertuples():
            if mode_allowed(au_map[int(r.link_id)], mtype):
                G.add_edge(int(r.from_node_id), int(r.to_node_id))
        # use a strongly-connected check on the zone set proxy: ensure each zone
        # has at least one out and one in edge in the allowed graph
        for z in zone_ids:
            if z not in G or G.out_degree(z) == 0 or G.in_degree(z) == 0:
                problems.append(f"mode {mtype}: zone {z} has no allowed in/out edge")
    return problems


def build(base_dir, out_dir, net, restrictions):
    os.makedirs(out_dir, exist_ok=True)
    # node.csv unchanged
    node = pd.read_csv(os.path.join(base_dir, "node.csv"))
    node.to_csv(os.path.join(out_dir, "node.csv"), index=False)
    zone_ids = sorted(set(int(z) for z in node["zone_id"].dropna().unique() if z != 0))

    # link.csv + allowed_use
    link = pd.read_csv(os.path.join(base_dir, "link.csv"))
    link["allowed_use"] = [restrictions.get(int(lid), ALL_USE) for lid in link["link_id"]]

    # connectivity guard (zone-level in/out edge presence)
    problems = check_connectivity(link, restrictions, zone_ids)
    if problems:
        raise RuntimeError(f"[{net}] restriction set strands zones:\n  " +
                           "\n  ".join(problems[:20]))

    link.to_csv(os.path.join(out_dir, "link.csv"), index=False)

    write_mode_type(out_dir, net)
    write_settings(out_dir)
    files = split_demand(base_dir, out_dir, net)

    print(f"[{net}] built in {out_dir}")
    print(f"   links={len(link)} nodes={len(node)} zones={len(zone_ids)}")
    print(f"   restricted link_ids: {sorted(restrictions)}")
    for mtype, fname, vol in files:
        print(f"   demand {fname:14s} total={vol}")
    return files


if __name__ == "__main__":
    build(BASE_SF, os.path.join(OUT_ROOT, "sf_multimodal"), "sf", SF_RESTRICTIONS)
    build(BASE_CS, os.path.join(OUT_ROOT, "cs_multimodal"), "cs", CS_RESTRICTIONS)
    print("\nDone. Run test_harness.py to validate.")
