"""Export the 0.3b regional loading as a GMNS folder + gui4gmns dashboard.

Nodes = transfer clusters (station groups); links = loaded ride segments with
volume / period_capacity / V/C; dashboard = self-contained HTML (Dashboard D
of the training spine: planning results view).

Run: python dc_dashboard_export.py
"""
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.join(HERE, "build_0_3", "regional")
GMNS = os.path.join(REG, "gmns_dashboard")
os.makedirs(GMNS, exist_ok=True)


def main():
    cl = pd.read_csv(os.path.join(REG, "regional_transfer_clusters.csv"))
    seg = pd.read_csv(os.path.join(REG, "regional_segment_loading.csv"))
    cent = cl.groupby("cluster")[["lon", "lat"]].mean()

    nodes = (cent.reset_index()
             .rename(columns={"cluster": "node_id", "lon": "x_coord",
                              "lat": "y_coord"}))
    nodes["node_id"] = nodes.node_id.astype(int)
    nodes.to_csv(os.path.join(GMNS, "node.csv"), index=False)

    seg = seg[(seg.from_cluster.isin(cent.index))
              & (seg.to_cluster.isin(cent.index))].copy()
    seg["link_id"] = range(1, len(seg) + 1)
    lk = seg.rename(columns={"from_cluster": "from_node_id",
                             "to_cluster": "to_node_id"})
    lk["from_node_id"] = lk.from_node_id.astype(int)
    lk["to_node_id"] = lk.to_node_id.astype(int)
    lk["capacity"] = lk.period_capacity
    lk[["link_id", "from_node_id", "to_node_id", "capacity",
        "mode", "n_trips"]].to_csv(os.path.join(GMNS, "link.csv"),
                                   index=False)
    perf = lk[["link_id", "from_node_id", "to_node_id", "volume",
               "period_capacity", "vc", "state"]].copy()
    perf["travel_time"] = 0.0
    perf.to_csv(os.path.join(GMNS, "link_performance.csv"), index=False)

    import gui4gmns
    out = os.path.join(REG, "dc_regional_dashboard.html")
    gui4gmns.generate(GMNS, out=out)
    print("dashboard:", out)
    print(f"nodes {len(nodes):,} | loaded segments {len(lk):,} | "
          f"undersupply segments {(seg.vc >= 1).sum():,}")


if __name__ == "__main__":
    main()
