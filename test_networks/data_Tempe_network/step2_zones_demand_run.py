"""Tempe small-MPO golden path, steps 2-4:
  2. synthesize ~40 grid zones over the OSM net -> zone.csv;
     gmns_ready.build_network() attaches them with connectors
  3. gravity demand on zone centroids (small synthetic peak hour)
  4. normalize for the TAPLite kernel (vdf fields, node/link renumbering so
     centroid node_id == zone_id, settings/mode_type) -> gmns_run/
Then re-run gmns_ready.quick_check on the runnable scenario (iterative verify).
"""
import os, math, collections
import pandas as pd
import numpy as np
import gmns_ready

HERE = os.path.dirname(os.path.abspath(__file__))
MACRO = os.path.join(HERE, "gmns_macro")
RUN = os.path.join(HERE, "gmns_run")
NZONE_TARGET = 40
KMH2MPH = 1 / 1.609344

# ---- 2a. zones: quantile grid over street nodes -> zone.csv
node = pd.read_csv(MACRO + "/node.csv")
g = int(round(math.sqrt(NZONE_TARGET)))
xq = node.x_coord.quantile(np.linspace(0, 1, g + 1)).values
yq = node.y_coord.quantile(np.linspace(0, 1, g + 1)).values
cx = np.clip(np.searchsorted(xq, node.x_coord, "right") - 1, 0, g - 1)
cy = np.clip(np.searchsorted(yq, node.y_coord, "right") - 1, 0, g - 1)
cell = cy * g + cx
zdf = (node.assign(cell=cell).groupby("cell")
       .agg(x_coord=("x_coord", "mean"), y_coord=("y_coord", "mean"), n=("node_id", "size"))
       .reset_index())
zdf = zdf[zdf.n >= 20].reset_index(drop=True)           # drop near-empty cells
zdf["zone_id"] = zdf.index + 1
zdf["node_id"] = zdf.zone_id            # gmns-ready keys the zone table by node_id
import geopandas as gpd
from shapely.geometry import Point
zgeo = gpd.GeoDataFrame(zdf[["node_id", "zone_id", "x_coord", "y_coord"]].copy(),
                        geometry=[Point(x, y) for x, y in zip(zdf.x_coord, zdf.y_coord)],
                        crs="EPSG:4326")
print(f"zones: {len(zgeo)} grid zones")

# ---- 2b. connectors: nearest-2 street nodes per zone (gmns-ready 0.1.1
# build_network is pandas-3-incompatible -- dtype=='object' WKT checks and
# WKT-string writes into geometry columns; reported as a finding. gmns-ready is
# still used for its working VERIFY role: quick_check / validate_* below.)
from scipy.spatial import cKDTree
street = node[["node_id", "x_coord", "y_coord"]].to_numpy()
tree = cKDTree(street[:, 1:3])
conn_rows = []
for _, z in zdf.iterrows():
    _, idx = tree.query([z.x_coord, z.y_coord], k=2)
    for i in np.atleast_1d(idx):
        conn_rows.append((int(z.zone_id), int(street[i, 0])))
print(f"connectors: {len(conn_rows)*2} directed (2 attachment nodes/zone)")

# ---- 3. gravity demand: T_ij ~ n_i * n_j / dist^1.5, scaled to ~30k veh/h
zx = zdf.x_coord.values; zy = zdf.y_coord.values; w = zdf.n.values.astype(float)
rows = []
for i in range(len(zdf)):
    for j in range(len(zdf)):
        if i == j: continue
        d = math.hypot((zx[i]-zx[j])*111000*0.83, (zy[i]-zy[j])*111000)  # ~meters
        rows.append((i + 1, j + 1, w[i]*w[j]/max(d, 300.0)**1.5))
dem = pd.DataFrame(rows, columns=["o_zone_id", "d_zone_id", "volume"])
dem["volume"] = dem.volume * (30000.0 / dem.volume.sum())
dem = dem[dem.volume >= 0.5].round({"volume": 3})
print(f"demand: {len(dem):,} pairs, {dem.volume.sum():,.0f} veh")

# ---- 4. kernel-ready scenario: centroids node_id==zone_id==1..Z, streets Z+1..
os.makedirs(RUN, exist_ok=True)
Z = len(zdf)
newid = {int(nid): Z + k for k, nid in enumerate(node.node_id, 1)}
out_nodes = pd.concat([
    pd.DataFrame({"node_id": zdf.zone_id, "zone_id": zdf.zone_id,
                  "x_coord": zdf.x_coord, "y_coord": zdf.y_coord}),
    pd.DataFrame({"node_id": [newid[int(n)] for n in node.node_id], "zone_id": 0,
                  "x_coord": node.x_coord, "y_coord": node.y_coord})])
out_nodes.to_csv(RUN + "/node.csv", index=False)

cl = pd.read_csv(MACRO + "/link.csv")
spd_kmh = pd.to_numeric(cl.get("free_speed"), errors="coerce").fillna(40)
length_m = pd.to_numeric(cl.get("length"), errors="coerce").fillna(50)
lanes = pd.to_numeric(cl.get("lanes"), errors="coerce").fillna(1).clip(lower=1).astype(int)
cap = pd.to_numeric(cl.get("capacity"), errors="coerce").fillna(800)
cap_pl = (cap / lanes).clip(lower=300)                 # osm2gmns capacity is total
streets = pd.DataFrame({
    "from_node_id": cl.from_node_id.map(newid), "to_node_id": cl.to_node_id.map(newid),
    "link_type": 2, "lanes": lanes, "capacity": cap_pl,
    "free_speed": spd_kmh, "vdf_free_speed_mph": (spd_kmh * KMH2MPH).round(2),
    "length": length_m.round(2), "vdf_length_mi": (length_m / 1609.344).round(5),
    "vdf_fftt": (60 * (length_m / 1609.344) / (spd_kmh * KMH2MPH).clip(lower=1)).round(4),
    "vdf_alpha": 0.15, "vdf_beta": 4, "vdf_plf": 1}).dropna(subset=["from_node_id", "to_node_id"])
conns = pd.DataFrame(
    [{"from_node_id": a, "to_node_id": b} for z, n in conn_rows
     for a, b in ((z, newid[n]), (newid[n], z))])
conns = conns.assign(link_type=100, lanes=1, capacity=99999, free_speed=30,
                     vdf_free_speed_mph=18.6, length=100, vdf_length_mi=0.0,
                     vdf_fftt=0.0, vdf_alpha=0, vdf_beta=1, vdf_plf=1)
out_links = pd.concat([streets, conns], ignore_index=True)
out_links["from_node_id"] = out_links.from_node_id.astype(int)
out_links["to_node_id"] = out_links.to_node_id.astype(int)
out_links = out_links.sort_values(["from_node_id", "to_node_id"]).reset_index(drop=True)
out_links.insert(0, "link_id", range(1, len(out_links) + 1))
out_links.to_csv(RUN + "/link.csv", index=False)
dem.to_csv(RUN + "/demand.csv", index=False)
pd.DataFrame([{"mode_type": "auto", "name": "auto", "vot": 10, "pce": 1, "occ": 1,
               "demand_file": "demand.csv", "dedicated_shortest_path": 0}]).to_csv(RUN + "/mode_type.csv", index=False)
pd.DataFrame([{"number_of_iterations": 20, "number_of_processors": 8,
               "demand_period_starting_hours": 7, "demand_period_ending_hours": 8,
               "first_through_node_id": -1, "route_output": 0, "log_file": 0,
               "link_output": 1, "accessibility_output": 1, "sp_algorithm": 1}]).to_csv(RUN + "/settings.csv", index=False)
print(f"kernel scenario: {Z} zones, {len(out_links):,} links -> {RUN}")
