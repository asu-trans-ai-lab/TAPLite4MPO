# Gate plan (revised): VDF progression toward CUBE — conic → capacity/PLF → QVDF → path

Source of truth for the setup: ADOT `docs/NVTA_SUBAREA_CONIC_PIPELINE.md`,
`FFX134_BD_VDF_INVENTORY.md`, and `cube2gmns/{vdf_lookup_tables,
NVTA_qvdf_calibration_results_dict}.py`. Path-based assignment moved to Gate 7.

## Precise setup (as used in the previous NVTA Cube run)

### VDF code = Area Type (AT) × Functional Type (FT)
VDF code digits: hundreds = AT (1..6), units = FT (1..6). e.g. 101 = AT1·FT1,
201 = AT2·FT1, 305 = AT3·FT5. `BPR_VDF_DICT` / `QVDF_VDF_DICT` hold 86 codes,
4 periods each (AM/MD/PM/NT). Each NVTA link carries a per-period code
(`I4{AM,MD,PM,NT}VDF`). FTYPE column in regional link.csv:

| FT | Name | n_links (regional) | conic a | conic b | (fitted BPR α / β) |
|---:|------|---:|---:|---:|---|
| 0 | Centroid connector | 15,986 | — | — | (uncongested) |
| 1 | Freeway | 2,888 | 15.0 | 1.0357 | 1.000 / 10.0 |
| 2 | Major Arterial | 6,842 | 7.0 | 1.0833 | 1.050 / 6.0 |
| 3 | Minor Arterial | 11,534 | 5.5 | 1.1111 | 1.000 / 5.0 |
| 4 | Collector | 10,489 | 3.0 | 1.2500 | 1.000 / 3.0 |
| 5 | Expressway | 787 | 8.0 | 1.0714 | 1.000 / 7.0 |
| 6 | Ramps | 803 | 15.0 | 1.0357 | 1.000 / 10.0 |
Source: Feng Liu 2024-03-21 conic VDF table (canonical NVTA FT mapping).

### Conic (Spiess) functional form
`t = t0 · [ 2 + sqrt( a²(1−x)² + b² ) − a(1−x) − b ]`, with `x = V/C`,
`a` per FT (above), `b` per FT. Asymptotically linear (unlike BPR power).
Engine selects conic vs BPR per link via `vdf_type` (conic = vdf_type 1).

### Period capacity from hourly capacity (Gate 5)
- Hourly PER-LANE capacity columns: `I{AM}HRLNCAP`, `MDHRLNCAP`, `IPMHRLNCAP`,
  `NTHRLNCAP`; per-LINK: `*HRLKCAP`. Convention used: per-lane × lanes.
- Period length L: AM=3 h, MD=6 h, PM=4 h (PM window 15–19h).
- **Peak Load Factor** back-extracted per link from the DBF:
  `PLF = V_period / (L · C_hourly · (V/C))`.
  Period-level PLF (confirmed): **AM=0.7994, MD=0.9416, PM=0.8503**.
- Period capacity (effective) = `C_hourly · L · PLF` (PLF concentrates the peak).

### QVDF calibrated parameters (Gate 6)
`NVTA_qvdf_calibration_results_dict.py` (`NVTA_qvdf_dict`): per vdf_code QVDF
params calibrated from prior-year runs (`link_qvdf.csv`): per period
`QVDF_plf, qdf, n, s, cp, cd, alpha, beta` (e.g. code 101 PM: plf=0.6415,
qdf=0.3897, n=1.1685, s=4, cp=0.1385, cd=0.9730, alpha=0.1965, beta=4.394).
Our DTALite kernel already implements QVDF (`Link_QueueVDF`).

## Engine note (decision needed — see below)
- The previous conic runs used a DIFFERENT engine: `tap_lite_cg.exe` (CG kernel
  v2, `network.bin` v3 schema, `vdf_type` dispatch) at `C:/t/cg_kernel_v2/Release`
  and in `ADOT/.../cg_kernel/`.
- Our consolidated DTALite CMake kernel has **BPR + QVDF, NOT conic**.
- Our kernel runs all 6 modes JOINTLY (shared congestion) → already closes the
  old pipeline's "Gap 4" (their per-mode independent runs under-routed small
  modes: hov3 −15%, apv −41%). Our Gate 3 had ALL modes within ±4%.

## Revised structure (PLF is PREPROCESSING, not a post-conic gate)

PREPROCESSING (run once, before ANY assignment gate — `nvta_run/prep_network.py`):
  1. Renumber zones-first + SORT links by from_node (kernel CSR adjacency
     requires sorted links — unsorted silently corrupts the SP tree).
  2. Conic params per FT (Feng table) → conic_a/conic_b, vdf_type.
  3. **Peak Load Factor → the existing `vdf_plf` field.** PLF was always part of
     link.csv as `vdf_plf`; the dtalite4cube `BPR_VDF_DICT` placeholder-set it to
     1.0. Repopulate per-link from CUBE: `vdf_plf = I4PMVOL/(L·IPMHRLKCAP·I4PMVC)`,
     median = 0.8503 PM (matches doc). Period capacity = `lanes·capacity·L·vdf_plf`
     (capacity col == IPMHRLNCAP, PM hourly per-lane; L = 4h).
  → BPR and conic gates then run on the SAME PLF-corrected network.

GATES (each just flips vdf_type / swaps VDF params; PLF + capacity fixed above):
- **Gate A — BPR** (vdf_type=0): regional FW10 R²=0.873 (PLF) — baseline form.
- **Gate B — Conic** (vdf_type=1, Spiess): subarea R²=0.9987 / regional R²=0.989
  (PLF). Conic ≫ BPR (CUBE used conic). DONE.
- **Gate C — QVDF** from prior-year calibration (`NVTA_qvdf_dict`; uses its own
  per-code `QVDF_plf` 0.69/1.04/0.64, distinct from the BPR/conic period PLF).
  Three-way compare BPR vs conic vs QVDF on per-mode volume + travel time.
Success (conic, per doc): subarea total ±0.5%, per-link R²≥0.95, zero on closed — MET (0.9987).

## Path-based + simulation stages (D–G) — future
Link-based FW (A/B/C) reproduces volume; D–G build the path/route layer.
Two STANDING RULES for D–G (memory/time + validation discipline):
  • **Store/output ONLY the SOV (main-mode) path columns.** All 6 modes' link
    VOLUMES are still computed (allowed_use + congestion), but the 5D route store
    (`linkIndices`) is allocated for ONE mode (SOV) only — the dominant memory/time
    cost. Other modes contribute aggregated per-link volume, not stored paths.
  • **Always validate on SF + CS multimodal first, then NVTA** (small-network-first).

- **Gate D — Static path-based**: route_output on, SOV path columns only; reproduce
  link volume via per-OD SOV paths (column generation). SF/CS → NVTA.
- **Gate E — Time-dependent path-based**: per-departure-time SOV path flows over the
  period (uses the QVDF queue / td-speed profile).
- **Gate F — FW → average flow**: link-based FW average flows as the convergence /
  consistency anchor for D & E.
- **Gate G — Time-dependent path tree → routing policies**: export per-time SOV path
  trees as routing policies to drive the meso/micro traffic SIMULATION.

## Open decision (resolved)
Gate B/conic engine: added to our CMake kernel (vdf_type=1). Either: (kept for record)

## Open decision
Gate 4 needs a conic engine. Either:
(A) ADD Spiess conic (`vdf_type=1`) to our DTALite CMake kernel (one bounded edit
    in the VDF function + read conic a/b per link), keeping ONE consolidated
    debuggable kernel; OR
(B) Use the existing `tap_lite_cg.exe` conic engine (works today, but separate
    codebase + `network.bin` format).
Recommendation: (A) — consistent with the consolidated-kernel goal and our
multi-mode FW advantage.
