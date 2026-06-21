"""Combine the ARC AM vehicle-trip cores into a DTALite demand.csv.

Inputs (TODAM20_asgn/TODAM20_asgn/): wide 6031x6031 OD matrices, one per core:
    SOVF, SOVT, HOV2F, HOV2T, HOV3F, HOV3T   (F = non-toll, T = toll segment)
Each file: first row = "<core>,1,2,...,6031"; each row = origin, then dest values.

Output: gmns/demand.csv  ->  o_zone_id, d_zone_id, volume   (zeros dropped)
        (single auto class = sum of all 6 vehicle-trip cores)
Also writes per-core long files if --per-core is passed (for multiclass later).
"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "TODAM20_asgn", "TODAM20_asgn")
OUT = os.path.join(HERE, "gmns")

# PROVENANCE script — rebuilds gmns/demand_*.csv from the ARC AM trip cores (TODAM20_asgn/),
# which are NOT bundled. The demand_sov / demand_hov2 / demand_hov3 CSVs are ALREADY provided
# in gmns/, so you do NOT need to run this to use the example.
if not os.path.isdir(SRC):
    raise SystemExit(
        "[provenance] TODAM20_asgn/ trip cores not found (not bundled). The per-class "
        "demand_*.csv are ALREADY provided in gmns/; you do not need to run this.")

os.makedirs(OUT, exist_ok=True)

# Three access classes; F (non-toll) + T (toll VOT segment) combined per class.
CLASSES = {
    "sov":  ["SOVF", "SOVT"],
    "hov2": ["HOV2F", "HOV2T"],
    "hov3": ["HOV3F", "HOV3T"],
}


def read_core(name):
    df = pd.read_csv(os.path.join(SRC, name + ".csv"), index_col=0)
    return df.index.to_numpy().astype(int), \
        df.columns.to_numpy().astype(int), \
        np.nan_to_num(df.to_numpy(dtype=np.float32))


grand = 0.0
for mode, cores in CLASSES.items():
    total = None
    o_ids = d_ids = None
    for c in cores:
        o, d, M = read_core(c)
        if total is None:
            total, o_ids, d_ids = np.zeros_like(M), o, d
        total += M
    oi, di = np.nonzero(total > 0)
    dem = pd.DataFrame({"o_zone_id": o_ids[oi], "d_zone_id": d_ids[di],
                        "volume": total[oi, di]})
    dem.to_csv(os.path.join(OUT, f"demand_{mode}.csv"), index=False)
    grand += dem.volume.sum()
    print(f"demand_{mode}.csv: {len(dem):,} OD pairs, volume {dem.volume.sum():,.0f}")
print(f"total auto volume across classes: {grand:,.0f}")
