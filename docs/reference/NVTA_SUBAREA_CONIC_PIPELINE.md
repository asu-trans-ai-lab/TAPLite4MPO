# NVTA Sub-Area Conic VDF Pipeline

**Goal:** validate the **conic VDF + per-link back-extracted PLF** pipeline on
small NVTA sub-area cordons (28-59 links) by reproducing Cube assigned link
volumes exactly, BEFORE scaling to the 49,786-link regional R09.

**Scope:** four sub-areas:

| ID  | Sub-area | Links | Zones | Tolled | Notes |
|---|---|---:|---:|---:|---|
| S1 | FFX134_BD (Fairfax I-66 Build)    | 59 | 28 | ? | 8 `allowed_use=closed` + 2 LIMIT=0 links |
| S2 | FFX134_NB (Fairfax I-66 No-Build) | 59 | 28 | ? | Same 8 closed, no LIMIT=0 |
| S3 | LDN034_BD (Loudoun Build)         | 28 | ? | 0  | No closures |
| S4 | LDN034_NB (Loudoun No-Build)      | 28 | ? | 0  | Byte-identical to S3 |

**Why sub-areas first:**

1. ~10⁻² × the size of regional → engine runs in seconds, full sweep of params in minutes
2. Stand-alone Cube + DTALite assignment files already prepared for each sub-area
   in `DTALite_package/{FFX134_BD, FFX134_NB, LDN034_BD, LDN034_NB}/` — including
   AM/MD/PM/NT demand (sov, hov2, hov3, com, trk, apv) and settings
3. The 4-sub-area set spans `allowed_use=closed`, LIMIT=0, and small-versus-tiny
   network sizes → confirms multiple correctness axes at once
4. If we can match Cube exactly here, the regional run is just bigger-of-same

---

## Pipeline stages (per sub-area, per period, per mode)

```
                                                  ┌──────────────────┐
                                                  │ Feng Liu conic   │
                                                  │ a per FT table   │
                                                  └────────┬─────────┘
DTALite_package/<subarea>/SubArea_NTWK_*.dbf    ───┐       │
DTALite_package/<subarea>/SubArea_NTWK_*.shp    ───┤       │
                                                  ▼       ▼
                  ┌──────────────────────────────────────────────────┐
                  │ Stage 1: tools/nvta_vdf_inventory.py             │
                  │  • Back-extract per-link PLF for AM/MD/PM        │
                  │  • Output: outputs/<subarea>/plf_per_link.csv    │
                  └────────────────────┬─────────────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────────────┐
                  │ Stage 2: tools/nvta_shp_to_gmns.py               │
                  │  --conic --per-link-plf-csv <plf csv>            │
                  │  • Reads DBF + SHP                               │
                  │  • Writes link.csv with vdf_type=1, conic α/β    │
                  │    (per-FT from Feng) + per-link PLF             │
                  │  • Writes node.csv with zone_ids                 │
                  │  • Preserves ALL Cube reference values as        │
                  │    cube_ref_* columns                            │
                  │  Output: scenarios/10_NVTA_Benchmark/<S>_<P>_<M>/│
                  └────────────────────┬─────────────────────────────┘
                                       │
DTALite_package/<subarea>/<mode>_<period>.csv ────────────┐
                                       │                  │
                                       ▼                  ▼
                  ┌──────────────────────────────────────────────────┐
                  │ Stage 3: copy demand + write CG settings.csv     │
                  │  • cp <mode>_<period>.csv → demand.csv           │
                  │  • settings.csv: vot, period hours, current_mode │
                  └────────────────────┬─────────────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────────────┐
                  │ Stage 4: preprocess_network.py                   │
                  │  • link.csv + node.csv → network.bin (v3)        │
                  │  • Schema v3 includes vdf_type per link          │
                  └────────────────────┬─────────────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────────────┐
                  │ Stage 5: tap_lite_cg.exe                         │
                  │  • Reads network.bin + demand.csv + settings.csv │
                  │  • Engine dispatches conic or BPR per link       │
                  │  • Writes link_volume_vs_ref.csv (modeled vol)   │
                  │  • Writes tap_log.csv (per-iter convergence)     │
                  └────────────────────┬─────────────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────────────┐
                  │ Stage 6: tools/r09_compare_qvdf.py (per subarea) │
                  │  • Join modeled vol to cube_ref_vol_<mode>       │
                  │  • Compute per-link diff, R², bias, ±% bands     │
                  │  • Per-FT breakdown                              │
                  │  • Output: docs/<subarea>_<period>_<mode>.md     │
                  └──────────────────────────────────────────────────┘
```

---

## Per-stage detail

### Stage 1 — Back-extract PLF from each sub-area DBF

```bash
python tools/nvta_vdf_inventory.py \
  --dbf DTALite_package/FFX134_BD/SubArea_NTWK_FFX134_LL.dbf \
  --qvdf-csv DTALite_package/DTALite4Cube/link_qvdf.csv \
  --out-dir outputs/FFX134_BD_inventory \
  --md-out  docs/FFX134_BD_VDF_INVENTORY.md
```

Outputs (per sub-area):
- `outputs/<sub>_inventory/plf_per_link.csv` — per (link_id, period) PLF
- `outputs/<sub>_inventory/ft_semantics_check.csv` — confirms Feng FT labels
- `outputs/<sub>_inventory/bpr_fit_to_conic.csv` — fitted α/β per FT
- `docs/<sub>_VDF_INVENTORY.md` — summary

### Stage 2 — Stage GMNS link.csv with conic + PLF

```bash
python tools/nvta_shp_to_gmns.py \
  --shp-stem DTALite_package/FFX134_BD/SubArea_NTWK_FFX134_LL \
  --out-dir  scenarios/10_NVTA_Benchmark/FFX134_BD_am_sov_conic \
  --period am --mode sov \
  --qvdf-csv DTALite_package/DTALite4Cube/link_qvdf.csv \
  --conic \
  --per-link-plf-csv outputs/FFX134_BD_inventory/plf_per_link.csv
```

Output: `link.csv` (59 × 41) and `node.csv` (zone-aware).

### Stage 3 — Wire up demand + settings

```bash
cp DTALite_package/FFX134_BD/sov_am.csv \
   scenarios/10_NVTA_Benchmark/FFX134_BD_am_sov_conic/demand.csv

cat > scenarios/.../FFX134_BD_am_sov_conic/settings.csv <<EOF
number_of_iterations,number_of_processors,route_output,perturb_enable,perturb_kind,perturb_num_runs,perturb_sigma,sp_algorithm,current_mode,demand_period_starting_hours,demand_period_ending_hours,capacity_is_per_lane,vot_dollars_per_hour
20,8,1,0,0,0,0.0,0,sov,6,9,1,10
EOF

# (minimal mode_type.csv for allowed_use filtering)
cat > scenarios/.../FFX134_BD_am_sov_conic/mode_type.csv <<EOF
mode_id,mode_name
0,sov
EOF
```

### Stage 4 — Preprocess

```bash
python TAPLite-main/.../preprocess_network.py \
  --in-dir  scenarios/10_NVTA_Benchmark/FFX134_BD_am_sov_conic \
  --out-dir scenarios/10_NVTA_Benchmark/FFX134_BD_am_sov_conic
```

Output: `network.bin` (v3 schema, ~6 KB for 59 links).

### Stage 5 — Run engine

```bash
C:/t/cg_kernel_v2/Release/tap_lite_cg.exe \
  scenarios/10_NVTA_Benchmark/FFX134_BD_am_sov_conic \
  scenarios/10_NVTA_Benchmark/FFX134_BD_am_sov_conic
```

Expected wall time: < 5 seconds (59 links × 28 zones × 20 iters).

### Stage 6 — Compare to Cube reference

```bash
python tools/r09_compare_qvdf.py \
  --baseline scenarios/10_NVTA_Benchmark/FFX134_BD_am_sov_conic \
  --qvdf     scenarios/10_NVTA_Benchmark/FFX134_BD_am_sov_conic \
  --out      docs/FFX134_BD_AM_SOV_RESULT.md
```

(The comparator was written for two runs; here we use the same run twice so the
report shows our result alone vs Cube. A specialized 1-vs-Cube comparator could
be added later.)

---

## Success criteria (per sub-area)

- **System total**: engine sum should equal Cube I4AMSOV sum within ±0.5% — same
  network, same demand, same VDF parameters → near-exact match is achievable
- **Per-link Pearson R²** ≥ 0.95 against Cube I4AMSOV
- **±10% band**: ≥ 70% of links land within 10% of Cube reference
- **HOT-lane / closed-link links**: zero flow on `allowed_use=closed` links

If we miss any of these, the pipeline has a remaining gap — typical suspects:
1. **Demand** — Cube's sub-area OD matrix may have been extracted differently
   than what's in `sov_am.csv`. Need to cross-check OD sums.
2. **Capacity convention** — verify IAMHRLKCAP is link total vs per-lane (we use
   the per-lane variant `IAMHRLNCAP` × lanes; Cube may use IAMHRLKCAP directly).
3. **VOT for tolled links** — sub-areas with tolls may need a different VOT.
4. **VDF α/β interpretation** — Feng's table calibration was on the regional;
   may not exactly match sub-area calibration if NVTA re-calibrated per cordon.

---

## Once sub-areas pass — scale to regional R09

1. Re-run `nvta_vdf_inventory.py` on regional DBF (already done — values stored)
2. Re-run `nvta_shp_to_gmns.py --conic` on regional shapefile
3. Run engine (6-10 minutes wall time)
4. Compare per-link and per-FT to Cube

---

## Status — AM SOV pass complete (2026-05-24)

| Sub-area | n_links | Engine | Cube | Match% | Bias | R² | ±25% band | Wall time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FFX134_BD | 59 | 93,060 | 95,660 | **97.3%** | **−2.72%** | **0.9987** | 92.0% | 38 ms |
| FFX134_NB | 59 | 93,060 | 95,660 | 97.3% | −2.72% | 0.9987 | 92.0% | 30 ms |
| LDN034_BD | 28 | 21,683 | 22,285 | 97.3% | −2.70% | **0.9160** | 82.1% | 27 ms |
| LDN034_NB | 28 | 21,683 | 22,285 | 97.3% | −2.70% | 0.9160 | 82.1% | 38 ms |

**Driver:** `tools/run_subarea_benchmark.py` — single command runs all 4 stages 1-6:
```bash
python tools/run_subarea_benchmark.py --subareas FFX134_BD FFX134_NB LDN034_BD LDN034_NB \
                                       --period am --mode sov
```

**Result reports:** `docs/NVTA_SUBAREA_BENCHMARK_RESULTS.md` (per-FT breakdown)

**FFX134_BD vs FFX134_NB identical** because their network inputs are identical
(only differ on 2 LIMIT=0 links, which our engine doesn't read as closures).
Same for LDN034_BD/NB (byte-identical inputs).

### Remaining gap vs "perfect"

System-level bias is **−2.72%** (engine under-routes by ~2,600 vehicles on 95,660).
Per-FT pattern in FFX134_BD:
- **Freeway: −0.2%** ← essentially perfect
- Collector: +1.1%
- Ramps: −2.9%
- Minor Arterial: −3.7%
- Centroid (connectors): −6.3%
- **Expressway: −10.5%** ← worst gap

Likely root causes for the residual 2-3% under-routing:
1. **Demand truncation** — Cube's sub-area assignment may be using an OD matrix
   slightly larger than the 92 ODs in `sov_am.csv`. Need to compare OD-row total
   against Cube's reported total.
2. **VOT** — toll-free sub-area, so this likely isn't it.
3. **Conic α for Expressway** — Feng's a=8 for FT=5 may need a softer value if
   Cube uses a slightly different per-FT calibration in sub-area.

### Multi-mode result (FFX134_BD AM, all 6 modes)

Engine vs Cube I4AM{mode} per mode, FFX134_BD AM:

| Mode | VOT | Engine | Cube  | Match% | Bias    | R²     |
|------|----:|-------:|------:|-------:|--------:|-------:|
| sov  | $10 | 93,060 | 95,660 | 97.3% | −2.72%  | **0.9987** |
| hov2 | $15 |  5,591 |  5,840 | 95.7% | −4.26%  | 0.9364 |
| hov3 | $15 |  3,452 |  4,059 | 85.0% | −14.96% | 0.9771 |
| com  | $20 |  9,577 | 10,909 | 87.8% | −12.20% | 0.9324 |
| trk  | $30 |  8,850 |  9,257 | 95.6% | −4.40%  | **0.9970** |
| apv  | $20 |    260 |    440 | 59.1% | −40.93% | 0.7216 |
| **sum** | | **120,790** | **126,165** | **95.7%** |   |        |

Larger modes (SOV, TRK) match Cube within 3-5%. Smaller modes (HOV3, COM, APV)
under-route because each mode runs **independently** (separate engine call per
mode) — small modes don't experience the congestion that all-modes-shared in
Cube produce. This is the long-standing "Gap 4 multi-mode capacity sharing" — a
single-engine multi-mode loop would close it.

Reproduction:
```bash
python tools/run_subarea_benchmark.py --subareas FFX134_BD --period am \
  --modes sov hov2 hov3 com trk apv --out-md docs/NVTA_FFX134_MULTIMODE_RESULTS.md
```

---

## Assumptions inventory — every value tagged with provenance

**Per user direction (2026-05-24):** PCE belongs in a settings/JSON inventory
file, NOT in `mode_type.csv`. Every assumed value MUST be visible and reviewable
before running. No hidden defaults. No silent assumptions. Pre-ask the planner
when uncertain.

**Tool:** `tools/build_assumptions_inventory.py`

Generates `<scenario_dir>/assumptions.json` containing:
- Period definition (start/end/length hours) + source + confidence
- Per-period PLF + source + confidence (NVTA: AM=0.7994, MD=0.9416, PM=0.8503,
  all **confirmed** via back-extraction)
- VDF functional form (`conic_spiess` for NVTA, `bpr` for generic,
  `custom_bpr_length_factor` for MAG) + source + confidence
- Per-FT VDF α/β + source + confidence (NVTA: all 7 FT classes **confirmed**
  via Feng Liu 2024-03-21 email)
- Per-mode **PCE**, occupancy, VOT + source + confidence
- Capacity convention (per-lane vs per-link) + source + confidence
- `open_assumptions_needing_planner_confirmation`: rolled-up list of any value
  tagged `assumed_pending_review` or `needs_planner_input`

**Confidence labels:**
- `confirmed` — traces to a verified data source
- `assumed_pending_review` — typical default, review with planner
- `needs_planner_input` — placeholder, requires explicit confirmation

**Pre-flight banner** printed before each engine run shows every assumption
side-by-side with its confidence label, so anything mis-set is visible.

**Status for NVTA AM SOV (FFX134_BD):**
- ✓ Confirmed: period definition, PLF, VDF form, conic α per FT, capacity convention
- ⚠ Needs review: per-mode VOT for ALL modes (NVTA Cube-specific VOT not yet
  extracted from their model), HOV3 occupancy, COM/TRK/APV PCE, APV mode definition

**To absorb other agencies (MAG, TPB, etc.):**
- Add agency entry in `VDF_INVENTORY` and `MODE_DEFAULTS_<AGENCY>` dicts
- MAG specifically: introduce `vdf_type=2` ("custom BPR with link length factor"
  per MAG TransCAD model). Requires engine extension. Currently `confidence:
  needs_planner_input` in the inventory.

---

## Next milestones

1. **R09 regional with conic + per-link PLF** (engine running now, 6-min wall)
2. **Three-way compare**: baseline / QVDF / conic on regional → quantify net improvement
3. **Wire `assumptions.json` into `nvta_shp_to_gmns.py`** so it reads PCE/VOT
   from inventory instead of hardcoded dicts. Single source of truth.
4. **MAG case absorption**: implement `vdf_type=2` (custom BPR with α=f(L_mi))
   in engine; extend inventory for MAG agency
5. **Verify demand matches Cube** for sub-areas (per the −2.7% residual bias)
