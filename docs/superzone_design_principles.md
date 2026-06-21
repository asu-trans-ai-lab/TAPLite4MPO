# Super-zone aggregation — design principles

Companion to **[compress_the_response.tex](compress_the_response.tex)** (the
conceptual essay: *Compress the Response, Not the Data*) and the empirical results
in `private/aztdm_statewide/SUPERZONE_RESULTS.md`. The essay states the *why*; this
page states the *engineering rules* for doing it correctly inside the
DTALite/TAPLite kernel. Implementations: `dtalite_qa/superzone_hier.py` (faithful)
and `dtalite_qa/superzone.py` (rep-centroid, cruder/faster).

---

## P0 — Compress the response, not the data

We never require the OD table `d` to be reconstructed. We require the **link flow**
`v = H d` to be preserved, where `H = Bᵀ R` is the OD→link response (assignment +
incidence). Formally the aggregation is a fold/unfold `d → Qᵀ d → U Qᵀ d`, and the
goal is

```
H d  ≈  H U Qᵀ d     on the dominant (corridor) modes.
```

Everything below is in service of this one equation.

## P1 — Merge zones that *respond* alike, not just zones that are near

Two zones should be aggregated when their demand routes onto the **same corridors**
(their columns of `H` are nearly parallel — the equalizer picture), not merely when
they are geographically adjacent. Empirically this is why **freeway/corridor flow is
preserved (R² ≈ 0.93) while local roads are not (R² 0.2–0.35)**: corridors are the
dominant response modes; local access is the high-frequency detail that aggregation
discards. Spatial proximity is only a cheap *proxy* for response-similarity; replace
it with an `H`-aware clustering when accuracy on a specific corridor matters.

## P2 — Respect the kernel's network invariants (or results are silently wrong)

The kernel (`TAPLite.cpp`) fixes the data model; the builder must honor it:

1. **A zone is a node with `zone_id == node_id`** (the kernel errors otherwise).
2. **`no_zones = max(zone_id)`** — arrays are sized by the *largest* zone id, not the
   active count. ⇒ **use compact super-zone ids `1..S`**, or you pay full allocation
   and `O(no_zones²)` loops even with few active zones.
3. **Links must be sorted by node.csv row order** (CSR adjacency).
4. **Auto FirstThruNode** (`first_through_node_id = -1`) = the first node.csv row with
   `zone_id == 0`. A node is traversable (through) iff `seq ≥ FirstThruNode` or it is
   the origin; **centroids cannot be passed through**.

## P3 — Hierarchical construction: super-zones are the only centroids

- **Prepend** super-zone nodes as ids `1..S` with `zone_id = node_id` → the only
  centroids.
- **Demote every original zone** to a through node: `zone_id = 0`, renumbered to
  `S+1 … S+N`.
- **Zero-cost connectors** `super ↔ member-zone-node`.
- Demand is keyed to super-zones.

This makes a trip route `super → member-zone-node → real network`.

## P4 — Handle the first-through-node case by *ordering*, not by hand

Because super-zones come first, the auto rule sets `FirstThruNode = S+1` for free.
That single fact does the work: **all original nodes (including the old centroids)
become through**, so `super → member → network` is a legal path. No manual
`first_through_node_id`, no per-node flags. (Set `first_through_node_id = -1`.)

## P5 — Transparent plumbing: the connectors must not change paths

Super-connectors carry zero generalized cost (`vdf_fftt = 0`, `vdf_alpha = 0`,
`length ≈ 0`) and effectively infinite capacity, so they add no travel time, no VMT,
and no congestion. They are pure relabeling, not new infrastructure.

## P6 — The correctness gate is the corner case `S = N`

**One super-zone per original zone (1:1) must reproduce the full assignment exactly.**
This is the unit test for *any* aggregation scheme. Validated on Chicago Sketch (40
iters): full and 1:1-super are identical to every decimal (VMT, TT, gap). If your
corner case is not exact, the construction is wrong (usually a through-node or
connector-cost bug) — fix it before trusting any compressed run.

## P7 — The accuracy cost is intra-super demand; it extends an existing kernel rule

Aggregation drops **intra-super-zone** trips. This is not a new approximation — the
kernel already skips intrazonal trips (`Dest == Orig → continue`); aggregation just
applies the same "no self-loading" rule over larger groups. The dropped fraction
(≈30–50% at 15× compression) is the dominant error and falls as `S` rises. **Choose
`S` to bound the intra-super share on the corridors you care about.**

## P8 — Know the speed model, then pick the lever

Per-iteration cost scales with **#active origins** (shortest-path trees) and
**#OD pairs** (flow loading), and the one-time cost with demand read + output. Compact
ids (P2.2) shrink allocation and the destination loops. Measured:

| network | full | compressed | speedup | overall R² | corridor R² |
|---|--:|--:|--:|--:|--:|
| Chicago Sketch (387→92 z) | 17.0 s | 1.44 s | 11.8× | 0.49 | freeway 0.41* |
| **Chicago Regional (1790→350 z)** | 25.3 s | 4.8 s | **5.3×** | **0.87** | **freeway 0.91** |
| Chicago Regional (1790→178 z) | 25.3 s | 2.8 s | 9.0× | 0.81 | freeway 0.89 |
| Chicago Regional (1790→93 z) | 25.3 s | 1.8 s | 14.1× | 0.72 | freeway 0.84 |
| AZTDM AM (6,090→396 z) | 459 s | 95 s | 4.8× | 0.76 | freeway 0.93 |
| **ARC Atlanta (6,031→1,500 z)** | 7 min | 3.1 min | **2.2×** | **0.97** | passes agency val.\*\* |
| ARC Atlanta (6,031→600 z) | 7 min | 1.2 min | 5.7× | 0.93 | groups pass |

\*Chicago **Sketch** is a coarse network (few large zones, short trips) — a poor
aggregation candidate (R² 0.49 at only 4×). Regional **fine-zone** models are the
real use case: at 5× compression Chicago Regional keeps overall R² 0.87 / freeway
0.91. **Corner case `S=N` verified exact (R²=1.000, 0% RMSE) on both Sketch and
Regional.** Corridor (freeway) R² stays 0.84–0.93 even at heavy compression — the
"compress the response" thesis in numbers.

\*\***ARC Atlanta is the production proof:** measured against the agency's own count
benchmark (not just self-consistency), super-zone at 1,500 (4× compression, 2.2×
faster) lands at **region-wide %RMSE 38% = the ARC acceptance target, all volume
groups pass** — i.e. you can accelerate the assignment and still meet agency
validation. (Encoder = `demand_kmeans`; calibrated network with the modified-BPR
VDF + `vdf_plf=φ/L`.)

## P9 — Super-zone is the interpretable cousin of SVD

SVD gives the *optimal* low-rank fold/unfold of `H` and tells you **how many response
modes are real** (the rank floor). Super-zones give those modes **names** (geographic
groups). Use the SVD spectrum of `H` to choose `S` (enough super-zones to span the
dominant corridor modes); use the geographic map to keep the result interpretable and
loadable by the kernel.

## P10 — Aggregation is a linear encoder–decoder; pick the encoder by *response*

Formally `d → Qᵀd → U Qᵀd` with `Q = S⊗S`; the only error is
`e_v = H(I−UQᵀ)d` (response, not OD reconstruction). Full framework + derivations:
**[od_compression_operators.tex](od_compression_operators.tex)**.

**Which encoder `S`?** Measured at K=178 on Chicago Regional (response distortion vs
full):

| encoder (`dtalite_qa/superzone_encoders.py`) | link R² | corridor R² |
|---|--:|--:|
| **`demand_kmeans` (recommended)** | **0.85** | **0.97** |
| `odsvd_embedding` (response-aware) | 0.84 | 0.95 |
| `geo_kmeans` | 0.80 | 0.95 |
| quantile grid (`cluster_grid`) | 0.81 | 0.89 |

- **Use `demand_kmeans`** — weight zone centroids by total demand. It wins because
  the OD matrix's rank-1 mode (50% energy) *is* the gravity/size pattern.
- The **OD matrix is rank ≈ 32** (99% energy) — so at any usable K the **encoder rank
  is abundant; the decoder `U` is the bottleneck** (intra-super demand it drops +
  single-representative loading). The highest-value improvement is a *demand-spread*
  decoder, not a cleverer encoder.

---

### Checklist for a new aggregation
- [ ] compact super-zone ids `1..S` (P2.2)
- [ ] super-zones first, originals demoted to through (P3, P4)
- [ ] zero-cost connectors (P5)
- [ ] links re-sorted by node order (P2.3)
- [ ] **corner case `S=N` reproduces full exactly** (P6)
- [ ] intra-super share reported and bounded (P7)
- [ ] speedup and corridor R² measured vs full (P8)
