"""D2: calibrated doubly-constrained gravity model with K-factors.

Synthesizes the DC transit AM OD matrix from a documented model:

    T_ij = K(d(i),d(j)) * a_i * b_j * P_i * A_j * exp(-beta * c_ij)

- Target = COMBINED transit AM (the four mode-availability segments summed
  per OD pair -- they overlap heavily and are one travel market).
- P_i, A_j       : reference marginals (row/col sums)
- c_ij           : haversine km between zone centroids (documented impedance)
- beta           : calibrated by bisection so the doubly-constrained model
                   reproduces the reference demand-weighted mean trip length
- K(d,d')        : district-level factors (quantile-grid districts),
                   K = observed/modeled district flow ratio, capped, then
                   re-balanced (Furness) so marginals still hold
- provenance     : demand_provenance = synthetic_gravity_dc_kfactor

Outputs: synthetic_od_am.csv, k_factors.csv, calibration_report.json
"""
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REF = r"C:\source_codes\0_source_code_new\transit_schedule_column_generation_assignment"
NODE = r"C:\source_codes\nvta_gmns_testbeds\Transit\transit_network_17agencies\node.csv"
SEGMENTS = ["d_bus_only_am", "d_metro_only_am", "d_bus_metro_am", "d_rail_only_am"]
GRID = 6            # quantile grid -> up to GRID*GRID districts per axis pairing
K_CAP = (0.25, 4.0)
MIN_WRITE = 0.01


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def furness(seed, P, A, iters=100, tol=1e-6):
    T = seed.copy()
    for _ in range(iters):
        r = P / np.maximum(T.sum(1), 1e-12)
        T *= r[:, None]
        c = A / np.maximum(T.sum(0), 1e-12)
        T *= c[None, :]
        if abs(T.sum(1) - P).max() < tol and abs(T.sum(0) - A).max() < tol:
            break
    return T


def main():
    # reference = combined transit AM market
    ref = None
    for s in SEGMENTS:
        d = pd.read_csv(os.path.join(REF, s + ".csv"))
        d.columns = ["o", "d", "v"]
        ref = d if ref is None else pd.concat([ref, d])
    ref = ref.groupby(["o", "d"], as_index=False).v.sum()

    nodes = pd.read_csv(NODE, low_memory=False,
                        usecols=["zone_id", "x_coord", "y_coord"])
    cent = (nodes[nodes.zone_id.notna() & (nodes.zone_id > 0)]
            .groupby("zone_id")[["x_coord", "y_coord"]].first())

    zones = sorted(set(ref.o) | set(ref.d))
    have = [z for z in zones if z in cent.index]
    dropped = ref[~(ref.o.isin(have) & ref.d.isin(have))].v.sum()
    ref = ref[ref.o.isin(have) & ref.d.isin(have)]
    idx = {z: i for i, z in enumerate(have)}
    n = len(have)
    lon = cent.loc[have, "x_coord"].to_numpy()
    lat = cent.loc[have, "y_coord"].to_numpy()

    T_obs = np.zeros((n, n))
    T_obs[ref.o.map(idx), ref.d.map(idx)] = ref.v
    total = T_obs.sum()
    P, A = T_obs.sum(1), T_obs.sum(0)

    C = haversine_km(lon[:, None], lat[:, None], lon[None, :], lat[None, :])
    np.fill_diagonal(C, 0.5)   # nominal intrazonal impedance (km)
    mtl_obs = (T_obs * C).sum() / total

    def model(beta):
        return furness(np.exp(-beta * C), P, A)

    lo, hi = 1e-4, 2.0
    for _ in range(40):
        beta = 0.5 * (lo + hi)
        mtl = (model(beta) * C).sum() / total
        if mtl > mtl_obs:
            lo = beta
        else:
            hi = beta
    T_grav = model(beta)

    # district K-factors on a quantile grid
    qx = np.quantile(lon, np.linspace(0, 1, GRID + 1))
    qy = np.quantile(lat, np.linspace(0, 1, GRID + 1))
    dx = np.clip(np.searchsorted(qx, lon, "right") - 1, 0, GRID - 1)
    dy = np.clip(np.searchsorted(qy, lat, "right") - 1, 0, GRID - 1)
    dist_id = dx * GRID + dy
    nd = GRID * GRID
    M = np.zeros((n, nd)); M[np.arange(n), dist_id] = 1.0
    obs_dd = M.T @ T_obs @ M
    mod_dd = M.T @ T_grav @ M
    with np.errstate(divide="ignore", invalid="ignore"):
        K_dd = np.where(mod_dd > 1.0, obs_dd / np.maximum(mod_dd, 1e-12), 1.0)
    K_dd = np.clip(K_dd, *K_CAP)
    K_cells = K_dd[dist_id[:, None], dist_id[None, :]]
    T_k = furness(np.exp(-beta * C) * K_cells, P, A)

    def stats(T):
        mtl = (T * C).sum() / total
        mod_d = M.T @ T @ M
        ss_res = ((obs_dd - mod_d) ** 2).sum()
        ss_tot = ((obs_dd - obs_dd.mean()) ** 2).sum()
        r2_dist = 1 - ss_res / ss_tot
        mask = (T_obs > 0) | (T > MIN_WRITE)
        a, b = T_obs[mask], T[mask]
        r2_cell = np.corrcoef(a, b)[0, 1] ** 2 if a.size > 1 else None
        bins = np.arange(0, 80, 2.5)
        h_o, _ = np.histogram(C.ravel(), bins, weights=T_obs.ravel())
        h_m, _ = np.histogram(C.ravel(), bins, weights=T.ravel())
        coincidence = np.minimum(h_o / total, h_m / total).sum()
        return dict(mean_trip_km=round(float(mtl), 3),
                    district_R2=round(float(r2_dist), 4),
                    cell_R2=round(float(r2_cell), 4),
                    TLD_coincidence=round(float(coincidence), 4))

    rep = {
        "provenance": "synthetic_gravity_dc_kfactor",
        "model": "T_ij = K(d_i,d_j) a_i b_j P_i A_j exp(-beta c_ij), doubly constrained (Furness)",
        "target": "combined transit AM (4 overlapping mode segments summed)",
        "zones": n, "dropped_ref_volume_no_centroid": round(float(dropped), 1),
        "total_demand": round(float(total), 1),
        "impedance": "haversine km between zone centroids; intrazonal 0.5 km",
        "beta_per_km": round(float(beta), 5),
        "observed_mean_trip_km": round(float(mtl_obs), 3),
        "districts": f"{GRID}x{GRID} lon/lat quantile grid",
        "K_cap": K_CAP,
        "gravity_only": stats(T_grav),
        "gravity_plus_K": stats(T_k),
        "marginals_preserved": bool(abs(T_k.sum(1) - P).max() < 1e-3
                                    and abs(T_k.sum(0) - A).max() < 1e-3),
    }

    oi, di = np.nonzero(T_k >= MIN_WRITE)
    out = pd.DataFrame({"o_zone_id": np.array(have)[oi],
                        "d_zone_id": np.array(have)[di],
                        "volume": T_k[oi, di].round(4)})
    out.to_csv(os.path.join(HERE, "synthetic_od_am.csv"), index=False)
    kf = pd.DataFrame([(a, b, K_dd[a, b]) for a in range(nd) for b in range(nd)
                       if K_dd[a, b] != 1.0],
                      columns=["o_district", "d_district", "K"])
    kf.to_csv(os.path.join(HERE, "k_factors.csv"), index=False)
    with open(os.path.join(HERE, "calibration_report.json"), "w") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
