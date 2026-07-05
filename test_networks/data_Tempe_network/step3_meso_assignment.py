"""Tempe step 3: assignment on the net2cell MESO (movement-link) network.
Takes mrm_out/mesonet/, re-attaches the 36 grid zones via macro_node_id lineage
(same attachment nodes as the macro run), same gravity demand -> gmns_meso_run/.
Movement links (mvmt_txt_id) then carry TURN volumes in link_performance.csv.
Usage: python step3_meso_assignment.py
"""
import os
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MESO = os.path.join(HERE, "mrm_out", "mesonet")
RUN = os.path.join(HERE, "gmns_meso_run")
KMH2MPH = 1 / 1.609344

os.makedirs(RUN, exist_ok=True)
mn = pd.read_csv(MESO + "/node.csv")
ml = pd.read_csv(MESO + "/link.csv")
dem = pd.read_csv(os.path.join(HERE, "gmns_run", "demand.csv"))
# macro attachment nodes used by the macro run: zones 1..Z connect to street nodes;
# recover (zone -> macro street node) pairs from the macro run's connector links.
mrl = pd.read_csv(os.path.join(HERE, "gmns_run", "link.csv"))
mrn = pd.read_csv(os.path.join(HERE, "gmns_run", "node.csv"))
Z = int(mrn[mrn.zone_id > 0].zone_id.max())
conns = mrl[(mrl.link_type == 100) & (mrl.from_node_id <= Z)][["from_node_id", "to_node_id"]]
# macro-run street node -> original osm2gmns macro node_id (macro run shifted by Z)
# macro run newid = Z + row_index+1 over gmns_macro/node.csv order
gm = pd.read_csv(os.path.join(HERE, "gmns_macro", "node.csv"))
runid2macro = {Z + i + 1: int(nid) for i, nid in enumerate(gm.node_id)}
zone_attach = [(int(z), runid2macro[int(s)]) for z, s in conns.itertuples(index=False)]

# meso nodes that inherit those macro nodes (first meso node per macro node)
meso_of_macro = (mn.dropna(subset=["macro_node_id"])
                   .astype({"macro_node_id": "float"})
                   .groupby("macro_node_id").node_id.first().to_dict())
pairs = [(z, int(meso_of_macro[m])) for z, m in zone_attach if m in meso_of_macro]
print(f"zone attachments: {len(pairs)} of {len(zone_attach)} recovered on meso net")

# renumber: zones 1..Z, meso nodes Z+1..
newid = {int(nid): Z + k for k, nid in enumerate(mn.node_id, 1)}
zx = mrn[mrn.zone_id > 0].sort_values("zone_id")
nodes_out = pd.concat([
    pd.DataFrame({"node_id": zx.zone_id.astype(int), "zone_id": zx.zone_id.astype(int),
                  "x_coord": zx.x_coord, "y_coord": zx.y_coord}),
    pd.DataFrame({"node_id": [newid[int(n)] for n in mn.node_id], "zone_id": 0,
                  "x_coord": mn.x_coord, "y_coord": mn.y_coord})])
nodes_out.to_csv(RUN + "/node.csv", index=False)

spd = pd.to_numeric(ml.free_speed, errors="coerce").fillna(40)
lng = pd.to_numeric(ml.length, errors="coerce").fillna(20)
lanes = pd.to_numeric(ml.lanes, errors="coerce").fillna(1).clip(lower=1).astype(int)
cap = pd.to_numeric(ml.capacity, errors="coerce").fillna(800)
streets = pd.DataFrame({
    "from_node_id": ml.from_node_id.map(newid), "to_node_id": ml.to_node_id.map(newid),
    "link_type": 2, "lanes": lanes, "capacity": (cap / lanes).clip(lower=300),
    "free_speed": spd, "vdf_free_speed_mph": (spd * KMH2MPH).round(2),
    "length": lng.round(2), "vdf_length_mi": (lng / 1609.344).round(6),
    "vdf_fftt": (60 * (lng / 1609.344) / (spd * KMH2MPH).clip(lower=1)).round(4),
    "vdf_alpha": 0.15, "vdf_beta": 4, "vdf_plf": 1,
    "mvmt_txt_id": ml.get("mvmt_txt_id", ""), "macro_link_id": ml.get("macro_link_id", "")
}).dropna(subset=["from_node_id", "to_node_id"])
zc = pd.DataFrame([{"from_node_id": p[0] if d == 0 else newid[p[1]],
                    "to_node_id": newid[p[1]] if d == 0 else p[0]}
                   for p in pairs for d in (0, 1)])
zc = zc.assign(link_type=100, lanes=1, capacity=99999, free_speed=30,
               vdf_free_speed_mph=18.6, length=50, vdf_length_mi=0.0, vdf_fftt=0.0,
               vdf_alpha=0, vdf_beta=1, vdf_plf=1, mvmt_txt_id="", macro_link_id="")
links_out = pd.concat([streets, zc], ignore_index=True)
links_out["from_node_id"] = links_out.from_node_id.astype(int)
links_out["to_node_id"] = links_out.to_node_id.astype(int)
links_out = links_out.sort_values(["from_node_id", "to_node_id"]).reset_index(drop=True)
links_out.insert(0, "link_id", range(1, len(links_out) + 1))
links_out.to_csv(RUN + "/link.csv", index=False)
dem.to_csv(RUN + "/demand.csv", index=False)
for f, df in [("mode_type.csv", pd.DataFrame([{"mode_type": "auto", "name": "auto", "vot": 10,
                "pce": 1, "occ": 1, "demand_file": "demand.csv", "dedicated_shortest_path": 0}])),
              ("settings.csv", pd.DataFrame([{"number_of_iterations": 20, "number_of_processors": 8,
                "demand_period_starting_hours": 7, "demand_period_ending_hours": 8,
                "first_through_node_id": -1, "route_output": 0, "log_file": 0,
                "link_output": 1, "accessibility_output": 0, "sp_algorithm": 1}]))]:
    df.to_csv(os.path.join(RUN, f), index=False)
n_mv = int((links_out.mvmt_txt_id.astype(str) != "").sum() - len(zc))
print(f"meso scenario: {Z} zones, {len(links_out):,} links "
      f"({(links_out.mvmt_txt_id.astype(str).str.len() > 0).sum():,} movement links) -> {RUN}")
