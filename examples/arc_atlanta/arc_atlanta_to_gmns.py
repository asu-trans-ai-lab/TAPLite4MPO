"""Convert the ARC Atlanta 2020 AM network (shapefiles) to GMNS for DTALite.

Inputs (arc-Shape/arc-Shape/):
    AMNode2020.shp  - 66,546 nodes; N <= 6031 are TAZ centroids (N == zone id)
    AMLink2020.shp  - 150,255 DIRECTED links (each record is one direction A->B)

Network coding (ARC / Cube):
    * Centroids are nodes 1..6031 -> node_id already equals zone_id (DTALite ok).
    * FACTYPE == 0  -> centroid connector (AMCAPACITY is 0 by design = unlimited).
    * AMCAPACITY > 0 -> AM-open road link; per-lane cap = AMCAPACITY / LANES.
    * AMCAPACITY == 0 & FACTYPE != 0 -> closed in AM -> dropped.
    * SPEED = free-flow mph, DISTANCE = miles, LANES = directional lanes.

Output: gmns/node.csv, gmns/link.csv, gmns/settings.csv, gmns/mode_type.csv
"""
import os
import numpy as np
import pandas as pd
import pyogrio

HERE = os.path.dirname(os.path.abspath(__file__))
SHP = os.path.join(HERE, "arc-Shape", "arc-Shape")
OUT = os.path.join(HERE, "gmns")

# PROVENANCE script — shows how gmns/ was built from the FULL ARC shapefiles
# (AMNode2020.shp + AMLink2020.shp WITH geometry, ~125 MB), which are NOT bundled.
# The gmns/ network is ALREADY provided, so you do NOT need to run this to use the example.
if not os.path.exists(os.path.join(SHP, "AMNode2020.shp")):
    raise SystemExit(
        "[provenance] AMNode2020.shp / full AMLink2020.shp not found (not bundled; ~125 MB,\n"
        "from ARC's published model). The gmns/ network is ALREADY provided here, so you do not\n"
        "need to run this. (The bundled arc-Shape/AMLink2020 is a trimmed teaching copy used\n"
        "only by arc_benchmark.py.)")

os.makedirs(OUT, exist_ok=True)
NZONES = 6031
MI2M = 1609.344
MPH2KMH = 1.609344

# ---------------- node.csv ----------------
nd = pyogrio.read_dataframe(os.path.join(SHP, "AMNode2020.shp"),
                            columns=["N", "X", "Y"], read_geometry=False)
nd["N"] = nd["N"].astype(int)
zone = np.where(nd["N"].to_numpy() <= NZONES, nd["N"].to_numpy(), 0)
node_df = pd.DataFrame({
    "node_id": nd["N"],
    "zone_id": zone.astype(int),
    "x_coord": nd["X"],
    "y_coord": nd["Y"],
}).drop_duplicates("node_id").sort_values("node_id")
node_df.to_csv(os.path.join(OUT, "node.csv"), index=False)
print("node.csv:", len(node_df), "nodes,", int((node_df.zone_id > 0).sum()), "centroids")

# ---------------- link.csv ----------------
lk = pyogrio.read_dataframe(
    os.path.join(SHP, "AMLink2020.shp"),
    columns=["A", "B", "LANES", "AMCAPACITY", "SPEED", "DISTANCE",
             "FACTYPE", "FCLASS", "NAME", "PROHIBIT", "TOLLAM", "TOLLID",
             "V_SOVAM", "V_HOV2AM", "V_HOV3AM", "WEAVEFLAG"], read_geometry=True)

A = lk["A"].astype(int).to_numpy()
B = lk["B"].astype(int).to_numpy()
cap = lk["AMCAPACITY"].to_numpy(dtype=float)
lanes_raw = lk["LANES"].to_numpy(dtype=float)
spd = lk["SPEED"].to_numpy(dtype=float)
dist = lk["DISTANCE"].to_numpy(dtype=float)
fac = lk["FACTYPE"].to_numpy(dtype=float)
weave = np.nan_to_num(lk["WEAVEFLAG"].to_numpy(dtype=float)) == 1

# allowed_use from ARC's PROHIBIT field (authoritative; the model's own path builder
# uses it). Toll is a COST not an ACCESS restriction, so managed-lane codes that merely
# toll SOV/HOV still allow them. Only 2/6/11 restrict autos; 4/10 are truck-only.
#   0 GP | 1 no-trk | 2 HOV2+ | 3 ML SOV-toll | 4 trk-only | 5 I285 bypass | 6 HOV3+
#   7/8/9 ML toll variants (autos allowed) | 10 trk-only-toll | 11 ML no-SOV (HOV only)
#   12/13 ML all-autos tolled
P = np.nan_to_num(lk["PROHIBIT"].to_numpy(dtype=float)).astype(int)
allowed = np.full(len(P), "", dtype=object)
allowed[np.isin(P, [2, 11])] = "hov2;hov3"   # no SOV
allowed[P == 6] = "hov3"                       # HOV3 only
allowed[np.isin(P, [4, 10])] = "trk"           # truck-only -> closed to our auto modes
# toll_flag: managed-lane codes that price a vehicle, or any coded toll link.
toll_codes = np.isin(P, [3, 7, 8, 9, 11, 12, 13])
tolled = toll_codes | (lk["TOLLAM"].to_numpy(dtype=float) > 0) | (lk["TOLLID"].to_numpy(dtype=float) > 0)
# ref_volume: ARC's modeled AM auto volume (SOV+HOV2+HOV3), matches our demand classes.
ref_vol = (lk["V_SOVAM"].to_numpy(dtype=float)
           + lk["V_HOV2AM"].to_numpy(dtype=float)
           + lk["V_HOV3AM"].to_numpy(dtype=float))

# ARC modified-BPR VDF coefficients by facility type (TripAssignment Table 7-3 / ARC_ABM_*.s
# lines 2680-2698):  Tc = T0*(1 + A*(V/C) + D*(V/C)^B).  GMNS map: vdf_A=A, vdf_alpha=D, vdf_beta=B.
fA = np.full(len(fac), 0.10)
fD = np.full(len(fac), 0.45)   # default = arterial/collector (FACTYPE 10-14)
fB = np.full(len(fac), 4.0)


def _setft(mask, a, d, b):
    fA[mask] = a
    fD[mask] = d
    fB[mask] = b


_setft(np.isin(fac, [1, 4, 5, 6]), 0.10, 0.60, 6.0)   # freeway / freeway-HOV / freeway-truck
_setft(np.isin(fac, [7, 8, 9]),    0.10, 1.00, 4.0)    # ramps (sys-sys, exit, entrance)
_setft(fac == 2,                   0.00, 1.00, 4.0)    # expressway
_setft(fac == 3,                   0.00, 1.25, 4.0)    # parkway
_setft(fac == 0,                   0.00, 0.15, 4.0)    # centroid connector (uncongested, cap huge)
_setft(weave & np.isin(fac, [1, 4, 5, 6]), 0.20, 1.25, 5.5)   # freeway weave override

# Weave capacity reduction (ARC): cap *= 0.98^(lanes-1) when WEAVEFLAG=1 and lanes>4
wmask = weave & (lanes_raw > 4)
cap = np.where(wmask, cap * np.power(0.98, np.maximum(lanes_raw - 1.0, 0.0)), cap)

is_conn = fac == 0
keep = is_conn | (cap > 0)          # connectors + AM-open roads; drop closed-in-AM
print("links total:", len(lk), "| connectors:", int(is_conn.sum()),
      "| AM-open roads kept:", int(((cap > 0) & ~is_conn).sum()),
      "| dropped (closed in AM):", int((~keep).sum()))

idx = np.where(keep)[0]
length_mi = np.maximum(dist[idx], 0.005)               # floor tiny lengths
speed_mph = np.where(spd[idx] > 0, spd[idx], 25.0)     # floor missing speed
lanes = np.where(is_conn[idx], 1, np.maximum(np.round(lanes_raw[idx]), 1)).astype(int)
cap_pl = np.where(is_conn[idx], 99999.0, cap[idx] / lanes)
fftt = 60.0 * length_mi / speed_mph

geoms = lk.geometry.values[idx]
link_df = pd.DataFrame({
    "link_id": np.arange(1, len(idx) + 1),
    "from_node_id": A[idx],
    "to_node_id": B[idx],
    "link_type": np.where(is_conn[idx], 1, 2),
    "lanes": lanes,
    "capacity": np.round(cap_pl, 3),
    "free_speed": np.round(speed_mph * MPH2KMH, 3),
    "vdf_free_speed_mph": np.round(speed_mph, 3),
    "length": np.round(length_mi * MI2M, 3),
    "vdf_length_mi": np.round(length_mi, 6),
    "vdf_fftt": np.round(fftt, 6),
    "vdf_type": 0,
    "vdf_A": np.round(fA[idx], 3),          # ARC modified-BPR linear term
    "vdf_alpha": np.round(fD[idx], 3),      # ARC D coefficient
    "vdf_beta": np.round(fB[idx], 2),       # ARC B exponent
    "vdf_plf": 0.915,                       # AM peak load factor = 3.66 / 4 (H*plf = period factor)
    "allowed_use": allowed[idx],
    "ref_volume": np.round(ref_vol[idx], 2),
    "toll_flag": tolled[idx].astype(int),
    "prohibit": P[idx],
    "factype": fac[idx].astype(int),
    "fclass": lk["FCLASS"].to_numpy()[idx],
    "name": lk["NAME"].to_numpy()[idx],
    "geometry": [g.wkt if g is not None else "" for g in geoms],
})
# DTALite CSR adjacency needs links sorted by from_node_id
link_df = link_df.sort_values("from_node_id", kind="stable").reset_index(drop=True)
link_df["link_id"] = np.arange(1, len(link_df) + 1)
link_df.to_csv(os.path.join(OUT, "link.csv"), index=False)
print("link.csv:", len(link_df), "directed links")

# ---------------- settings.csv + mode_type.csv ----------------
# Converged AM run reproducing ARC's loading: period 6-10 (H=4) with vdf_plf=0.915 so
# H*plf = 3.66 (ARC AM capacity factor); stop at relative gap < 1e-4 for 3 consecutive iters.
pd.DataFrame([{
    "number_of_iterations": 20, "number_of_processors": 8,
    "demand_period_starting_hours": 6, "demand_period_ending_hours": 10,
    "convergence_gap_pct": 0.0001, "convergence_consecutive": 3,
    "base_demand_mode": 0, "route_output": 0, "log_file": 0,
    "odme_mode": 0, "odme_vmt": 0, "demand_format": 0,
}]).to_csv(os.path.join(OUT, "settings.csv"), index=False)
# 3 access classes; tokens MUST match allowed_use ("hov2;hov3"). ARC auto VOT $21.50/hr.
pd.DataFrame([
    {"mode_type_id": 1, "mode_type": "sov",  "name": "SOV",  "vot": 21.5, "pce": 1,
     "occ": 1, "operating_cost": 0.1729, "demand_file": "demand_sov.csv",  "dedicated_shortest_path": 1},
    {"mode_type_id": 2, "mode_type": "hov2", "name": "HOV2", "vot": 21.5, "pce": 1,
     "occ": 2, "operating_cost": 0.1729, "demand_file": "demand_hov2.csv", "dedicated_shortest_path": 1},
    {"mode_type_id": 3, "mode_type": "hov3", "name": "HOV3", "vot": 21.5, "pce": 1,
     "occ": 3.3, "operating_cost": 0.1729, "demand_file": "demand_hov3.csv", "dedicated_shortest_path": 1},
]).to_csv(os.path.join(OUT, "mode_type.csv"), index=False)

# allowed_use inventory
au = link_df["allowed_use"].replace("", "(all)").value_counts().to_dict()
print("allowed_use inventory:", au)
print("HOV-only links:", int((link_df.allowed_use == "hov2;hov3").sum()),
      "| tolled (HOT) links:", int((link_df.toll_flag == 1).sum()),
      "| ref_volume>0 on:", int((link_df.ref_volume > 0).sum()), "links")
print("wrote ->", OUT)
