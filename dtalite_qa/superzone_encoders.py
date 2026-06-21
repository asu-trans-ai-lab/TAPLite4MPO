"""Encoder constructions for super-zone aggregation -- the choice of the zone->
super-zone map S (the fold Q^T = (S (x) S)^T). Each returns {zone_id -> super_id}
(contiguous 1..K) for `superzone_hier.build(scenario, out, zone2super=...)`.

Judged by response distortion e_v = H(I-U Q^T)d (link-flow error vs the full run),
NOT by OD reconstruction. On Chicago Regional (K=178) the ranking was:
  demand_kmeans (best, corridor R^2 0.97) > odsvd_embedding > geo_kmeans ~ grid.
The demand matrix is rank ~32 (99% energy), so the encoder rank is abundant; pick S
to put resolution where demand (the dominant gravity mode) concentrates.

Requires numpy + scikit-learn (unlike the stdlib core).  See
docs/od_compression_operators.tex for the linear-operator framework.
"""
import csv

from . import csvio


def _zones_and_od(scenario):
    import numpy as np
    _, nrows = csvio.read(csvio.path(scenario, "node.csv"))
    zid, xy = [], []
    for r in nrows:
        z = csvio.inum(r.get("zone_id"), 0)
        if z > 0:
            zid.append(z)
            xy.append((csvio.fnum(r.get("x_coord")), csvio.fnum(r.get("y_coord"))))
    zid = np.array(zid)
    xy = np.array(xy, float)
    idx = {int(z): i for i, z in enumerate(zid)}
    # OD matrix from the (first) demand file
    _, mts = csvio.read(csvio.path(scenario, "mode_type.csv")) if csvio.exists(scenario, "mode_type.csv") else (None, [])
    df = next((m.get("demand_file") for m in mts if m.get("demand_file")), "demand.csv")
    D = np.zeros((len(zid), len(zid)))
    with open(csvio.path(scenario, df), newline="", encoding="utf-8-sig") as f:
        r = csv.reader(f)
        h = next(r)
        oi, di, vi = (h.index("o_zone_id"), h.index("d_zone_id"), h.index("volume")) if "o_zone_id" in h else (0, 1, 2)
        for row in r:
            try:
                o, d = int(float(row[oi])), int(float(row[di]))
            except (IndexError, ValueError):
                continue
            if o in idx and d in idx:
                D[idx[o], idx[d]] += float(row[vi])
    return zid, xy, D


def _relabel(zid, labels):
    uniq = {v: i + 1 for i, v in enumerate(sorted(set(int(l) for l in labels)))}
    return {int(zid[i]): uniq[int(labels[i])] for i in range(len(zid))}


def geo_kmeans(scenario, K, seed=0):
    from sklearn.cluster import KMeans
    zid, xy, _ = _zones_and_od(scenario)
    return _relabel(zid, KMeans(K, n_init=4, random_state=seed).fit_predict(xy))


def demand_kmeans(scenario, K, seed=0):
    """RECOMMENDED. Weight zone centroids by total (origin+destination) demand so
    super-zone resolution concentrates where the response is largest."""
    from sklearn.cluster import KMeans
    zid, xy, D = _zones_and_od(scenario)
    w = D.sum(1) + D.sum(0) + 1e-6
    return _relabel(zid, KMeans(K, n_init=4, random_state=seed).fit_predict(xy, sample_weight=w))


def odsvd_embedding(scenario, K, rank=24, seed=0):
    """Response-aware: cluster origins by the top-`rank` left singular vectors of the
    OD matrix (the dominant destination-pattern modes). Beats demand-weighting when
    corridors are not aligned with demand density."""
    import numpy as np
    from sklearn.cluster import KMeans
    zid, xy, D = _zones_and_od(scenario)
    U, S, _ = np.linalg.svd(D, full_matrices=False)
    emb = U[:, :rank] * S[:rank]
    emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    return _relabel(zid, KMeans(K, n_init=4, random_state=seed).fit_predict(emb))


def od_rank_energy(scenario):
    """Effective rank of the OD matrix: ranks holding 50/90/99% of the SVD energy."""
    import numpy as np
    _, _, D = _zones_and_od(scenario)
    s = np.linalg.svd(D, compute_uv=False)
    e = np.cumsum(s ** 2) / np.sum(s ** 2)
    return {p: int(np.searchsorted(e, p / 100.0)) + 1 for p in (50, 90, 99)}
