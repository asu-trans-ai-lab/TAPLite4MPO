#!/usr/bin/env python3
"""Apply the ARC benchmark calibration to the gmns/ network -> gmns_calibrated/.

Fixes the gaps arc_benchmark.py found in the base conversion:
  - per-FACTYPE modified-BPR VDF (vdf_A / vdf_alpha / vdf_beta) + weave override
    (replaces the flat 0.15/4);
  - peak load factor vdf_plf = phi/L = 3.66/4 = 0.915 (AM) -- capacity stays the
    HOURLY per-lane AMCAPACITY/lanes the base conversion already wrote;
  - settings: AM window 6->10 (H=4), multi-iteration UE with the 3-consecutive
    relative-gap stop;
  - mode_type: VOT $21.50, operating_cost $0.1729/mi (auto).
"""
import os, shutil
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "gmns")
OUT = os.path.join(HERE, "gmns_calibrated")
os.makedirs(OUT, exist_ok=True)

VDF_ADB = {1:(.10,.60,6.0),4:(.10,.60,6.0),5:(.10,.60,6.0),6:(.10,.60,6.0),
           2:(.00,1.00,4.0),3:(.00,1.25,4.0),7:(.10,1.00,4.0),8:(.10,1.00,4.0),
           9:(.10,1.00,4.0),10:(.10,.45,4.0),11:(.10,.45,4.0),12:(.10,.45,4.0),
           13:(.10,.45,4.0),14:(.10,.45,4.0),0:(.0,.0,1.0)}
WEAVE_ADB = (0.20, 1.25, 5.5)
AM_PLF = 3.66 / 4.0   # phi / L

lk = pd.read_csv(os.path.join(SRC, "link.csv"))
ref = pd.read_csv(os.path.join(HERE, "arc_am_ref_volume.csv"))
weave = ref.set_index(["from_node_id", "to_node_id"])["weaveflag"].to_dict()

ft = lk["factype"].fillna(0).astype(int)
lk["vdf_A"]     = ft.map(lambda f: VDF_ADB.get(f, (.1,.45,4.0))[0])
lk["vdf_alpha"] = ft.map(lambda f: VDF_ADB.get(f, (.1,.45,4.0))[1])
lk["vdf_beta"]  = ft.map(lambda f: VDF_ADB.get(f, (.1,.45,4.0))[2])
# weave override (where ARC WEAVEFLAG=1)
wmask = lk.apply(lambda r: weave.get((r["from_node_id"], r["to_node_id"]), 0) == 1, axis=1)
lk.loc[wmask, ["vdf_A", "vdf_alpha", "vdf_beta"]] = WEAVE_ADB
lk["vdf_plf"] = AM_PLF
print(f"links {len(lk):,}; weave links overridden: {int(wmask.sum()):,}")
print("VDF by factype set; flat 0.15/4 ->", lk.groupby(ft)[["vdf_A","vdf_alpha","vdf_beta"]].first().to_dict("index"))

lk.to_csv(os.path.join(OUT, "link.csv"), index=False)
shutil.copy(os.path.join(SRC, "node.csv"), os.path.join(OUT, "node.csv"))
for d in ("demand_sov.csv", "demand_hov2.csv", "demand_hov3.csv"):
    shutil.copy(os.path.join(SRC, d), os.path.join(OUT, d))

# settings: AM 6-10 (H=4), 30 iters, relative-gap 0.5% x3 consecutive
pd.DataFrame([{
    "number_of_iterations": 30, "number_of_processors": 8,
    "demand_period_starting_hours": 6, "demand_period_ending_hours": 10,
    "base_demand_mode": 0, "route_output": 0, "log_file": 0,
    "odme_mode": 0, "odme_vmt": 0, "demand_format": 0,
    "convergence_gap_pct": 0.5, "convergence_consecutive": 3,
}]).to_csv(os.path.join(OUT, "settings.csv"), index=False)

# mode_type: ARC VOT $21.50, auto operating_cost $0.1729/mi
pd.DataFrame([
    {"mode_type_id":1,"mode_type":"sov","name":"SOV","vot":21.5,"pce":1,"occ":1,
     "operating_cost":0.1729,"demand_file":"demand_sov.csv","dedicated_shortest_path":1},
    {"mode_type_id":2,"mode_type":"hov2","name":"HOV2","vot":21.5,"pce":1,"occ":2,
     "operating_cost":0.1729,"demand_file":"demand_hov2.csv","dedicated_shortest_path":1},
    {"mode_type_id":3,"mode_type":"hov3","name":"HOV3","vot":21.5,"pce":1,"occ":3,
     "operating_cost":0.1729,"demand_file":"demand_hov3.csv","dedicated_shortest_path":1},
]).to_csv(os.path.join(OUT, "mode_type.csv"), index=False)
print(f"calibrated scenario -> {OUT}  (vdf_plf={AM_PLF:.3f}, AM 6-10 H=4, VOT 21.5, op_cost 0.1729)")
