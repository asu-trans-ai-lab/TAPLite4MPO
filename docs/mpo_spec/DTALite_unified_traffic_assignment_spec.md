# DTALite / TAPLite — Unified Traffic-Assignment Specification & Extension Plan

A single specification that **unifies the static-highway-assignment requirements of multiple
MPO/DOT models** (ARC, SERPM 8, TRPA, MTC, SANDAG, MWCOG, VDOT, ODOT; open-source reference
AequilibraE) into one GMNS-based engine spec, and states **exactly how the DTALite/TAPLite kernel
satisfies (or must be extended to satisfy) each requirement**.

- Companion conformance matrix: `agency_conformance_matrix.md` (+ `.csv`).
- Agency source docs archived offline under `agency_docs/`.
- Kernel grounded in `kernel/src/TAPLite.cpp` (line refs below) and the GMNS schema
  `schemas/gmns_dtalite_schema.json`.

Status legend: **[OK]** implemented in TAPLite · **[STAGED]** partially present/needs finishing ·
**[EXT]** extension required · **[CONV]** handled in the agency->GMNS converter (data, not kernel).

---

## 1. Unified data model (GMNS superset)

One schema covers all agencies; per-agency converters precompute facility/area-type lookups into it.

### node.csv
`node_id` (centroid: node_id==zone_id) **[OK]**, `zone_id`, `x_coord`, `y_coord`.

### link.csv (superset of fields needed across agencies)
| field | meaning | kernel | agencies needing it |
|--|--|--|--|
| from_node_id, to_node_id | directed topology (sorted by from_node) | [OK] | all |
| lanes | directional lanes | [OK] | all |
| capacity | **per-lane** veh/h/lane (period cap / lanes) | [OK] | all |
| free_speed / vdf_free_speed_mph | free-flow speed | [OK] | all |
| length / vdf_length_mi | length | [OK] | all |
| vdf_fftt | free-flow time (min) | [OK] | all |
| vdf_type | 0 BPR · 1 conical · 2 QVDF (extend: 3 BPR2, 4 INRETS, 5 Akcelik) | [OK]/[EXT] | see §2 |
| vdf_alpha, vdf_beta | BPR/conical coefficients (per facility) | [OK] | all |
| **vdf_A** | modified-BPR **linear term** `fftt*(1+A·x+α·x^β)` | **[OK]** (TAPLite.cpp:74) | ARC |
| vdf_plf | peak load factor | [OK] | — |
| vdf_cp,cd,n,s | QVDF queue params | [OK] | QVDF users |
| allowed_use | mode access (`hov2;hov3`, `trk`, empty=all) | [OK] (:14 refs) | ARC,SANDAG,MTC |
| toll / mode toll | per-mode toll cost | [OK] (mode_AdditionalCost) | ARC,SANDAG,MTC,MWCOG |
| ref_volume | calibration target (agency loaded volume) | [OK] (:9 refs) | all (validation) |
| (converter-only) FACTYPE, AREATYPE, WEAVEFLAG, TOLLID, GPID, PROHIBIT/HOV | source coding | [CONV] | all |

### demand_<class>.csv
`o_zone_id, d_zone_id, volume` — one file per user class. **[OK]**

### mode_type.csv  (multiclass)
`mode_type, vot, pce, occ, operating_cost, demand_file, dedicated_shortest_path`.
Kernel reads `pce`, `occ`, `operating_cost`, `demand_file` (TAPLite.cpp:3208-3210) and **`vot`**,
used to convert toll/operating-cost money into generalized-time minutes (TAPLite.cpp:4816). **[OK]**

### settings.csv
`number_of_iterations, number_of_processors, demand_period_*_hours, convergence_gap_pct,
convergence_consecutive, route_output, ...`. Relative-gap + consecutive-iteration stop are read
(TAPLite.cpp:3146-3147). **[OK]**

---

## 2. Unified VDF library

All agency VDF forms, the exact formula, the kernel mapping, and status. `x = v/c`.

| # | VDF | formula | used by | kernel status |
|--|--|--|--|--|
| 0 | Standard BPR | `t0(1+α·x^β)` | TRPA, ODOT, VDOT, MTC(base) | **[OK]** |
| 0a | **Modified BPR + linear** | `t0(1+A·x+α·x^β)` | **ARC** | **[OK]** `vdf_A` |
| 0b | MTC capacity-shift BPR | `t0(1+0.20·(4/3·x)^6)` | MTC | **[OK]** via x-prescale in converter, or set α=0.20,β=6 with [CONV] 4/3 |
| 1 | Conical (Spiess) | `t0(2+√(α²(1−x)²+β²)−α(1−x)−β)` | MWCOG, VDOT | **[OK]** `vdf_type=1`, `conic_a/b` (verified vs formula 5e-5) |
| 2 | QVDF (queue-based) | DTALite queue VDF (cp,cd,n,s) | DTALite-native | **[OK]** |
| 3 | BPR2 (exponent doubles >cap) | `x≤1: t0(1+α·x^β); x>1: t0(1+α·x^{2β})` | AequilibraE | **[OK]** `vdf_type=3` |
| 4 | INRETS | `x≤1: t0(1.1−α·x)/(1.1−x); x>1: t0((1.1−α)/0.1)·x²` | AequilibraE | **[OK]** `vdf_type=4` |
| 5 | Akcelik | `t0+α(z+√(z²+β·x)), z=x−1` | VDOT-allowed, AequilibraE | **[OK]** `vdf_type=5` |
| 6 | BPR + intersection delay | BPR + Webster delay (`cycle_length`,`green_ratio`) | SANDAG | **[OK]** `vdf_type=6` |

**Note:** the FW line search is a bisection on the **cost-based** directional derivative
(`OF_LinksDirectionalDerivative`→`Link_GenCost`, TAPLite.cpp:5000), so it is **exact for any
monotone VDF cost** — no per-VDF integral/derivative needed. (The legacy BPR `Link_Travel_Time_Der`
is unused by the line search.)

Per-facility coefficient tables (to be written into link.csv by converters) are in
`MPO_assignment_kernel_references.md` §2 & §8 (ARC, TRPA, SANDAG, MTC, MWCOG values).

---

## 3. Equilibrium solver & convergence

- **Static user equilibrium** (Wardrop I) — universal. **[OK]**
- Solver: TAPLite uses **Frank-Wolfe with Armijo line search** + path-proportion update
  (TAPLite.cpp:1565-1907, computeTheta:1528). **[OK]** for FW.
  - **[OK]** Conjugate FW (`assignment_method=1`) and **Bi-conjugate FW** (`=2`, Mitradjieva-Lindberg)
    via the cost-derivative Hessian + convex-combination auxiliaries (feasible, falls back to FW).
    Verified faster gap closure to the SAME UE: Chicago Regional iter-24 gap FW 1.43% -> BFW 0.59%
    (R^2 0.999 vs FW), negligible overhead. SANDAG-style SOLA (path-based) still optional.
- **Relative-gap stop, N consecutive iterations**: `convergence_gap_pct` + `convergence_consecutive`,
  `gap_below_count` (TAPLite.cpp:315-319, 3403, 3542-3546). Set `convergence_gap_pct=0.0001,
  convergence_consecutive=3` to match **ARC & SERPM**. **[OK]**
- **[EXT]** *Progressive* gap that tightens across speed-feedback loops (MWCOG: 1e-2 -> 1e-3 ->
  1e-4) — add a per-feedback-iteration gap schedule.
- Relative-gap definition (AequilibraE): `RelGap = (Σ Vₐ·Cₐ − Σ Vₐ^AoN·Cₐ)/(Σ Vₐ·Cₐ)`.
  **[OK]** TAPLite default normalizes by the AoN total (`/system_least`); set
  `relative_gap_standard=1` to normalize by the **current** total (`/system_wide`, the
  AequilibraE form) so a `1e-4` target is agency-comparable (TAPLite.cpp:3474).

---

## 4. Generalized cost & multiclass

Unified link cost (per mode): `cost = travel_time + mode_AdditionalCost[mode]` where
AdditionalCost carries toll + distance operating cost (TAPLite.cpp:445,542,577; `op_cost`:230).
PCE applied in volume aggregation (TAPLite.cpp:1411,672); occupancy in PMT/PHT (3704). **[OK]**

| requirement | agencies | kernel |
|--|--|--|
| time + toll + distance·opcost | ARC, SANDAG, MWCOG | **[OK]** |
| time + toll only (no distance) | SERPM 8 | **[OK]** (set op_cost=0) |
| time only | TRPA, ODOT | **[OK]** (toll=op_cost=0) |
| per-class PCE (truck 1.3–2.5) | ARC, SANDAG | **[OK]** `pce` |
| occupancy (person-trip metrics) | all | **[OK]** `occ` |
| per-class VOT in generalized cost | ARC ($21.5/$36), SERPM ($15/$12), SANDAG (income-based) | **[OK]** cost = time + (toll + op_cost·dist)/VOT·60 minutes (TAPLite.cpp:4816); VOT converts money→time (equivalent to ARC's time·VOT form) |
| **toll-eligible class split** (SOV_NT vs SOV_TR) | ARC, SANDAG, MTC | **[CONV]** create separate demand classes; restrict toll links via allowed_use/cost |

---

## 5. Restrictions / managed lanes

`allowed_use` (per-mode, dedicated shortest path) **[OK]**. Converter maps each agency's coding:
- ARC: PROHIBIT (2/6/11 -> hov-only; 4/10 -> truck-only) **[CONV]**
- SANDAG: HOV field {1 GP,2 HOV2+,3 HOV3+,4 toll} + TOLL{period}>0 -> HOT **[CONV]**
- MTC: USE / TOLLCLASS / FT8 managed freeway **[CONV]**
- Toll = cost layer (mode_AdditionalCost), not access ban, for managed lanes. **[OK]**

---

## 6. Time of day

Run one assignment per period; converter writes period lanes, period capacity (hourly·period
factor), and period tolls. Periods: ARC/MTC/SANDAG 5 (EA/AM/MD/PM/EV); MWCOG/VDOT 4; TRPA 4. **[CONV]**

---

## 7. Validation (unified targets the kernel must enable)

Kernel already emits link `volume`, per-class `mod_vol_*`, `ref_volume`, VMT/VHT, speed, v/c
(`link_performance.csv`). **[OK]** Add a **validation plugin** **[EXT]** computing, against `ref_volume`
/ counts:
- R² (target VDOT 0.90 large / 0.92 small; ODOT ≥0.9)
- %RMSE by volume group & facility type (VDOT table; ARC ~38% region)
- VMT by functional class (VDOT ±7–25%; ARC arterial+ within ~6%)
- screenline/cutline ratios (VDOT ±5–10%), speed deviation (>5 mph flag)

---

## 8. Extension roadmap for the TAPLite kernel (priority order)

1. **[DONE] Conical VDF** (`vdf_type=1`): verified vs formula (5e-5). Cost-based line search ⇒ exact, no integral needed.
2. **[DONE] Standardized relative gap** (`relative_gap_standard`) — `/system_wide` AequilibraE form.
3. **[DONE] VDF library: BPR2 (3), INRETS (4), Akcelik (5), SANDAG-signal (6)** — all verified vs formula; line search exact for any monotone VDF.
4. **[DONE/verify] ODME** — present in TAPLite.cpp (g_ODME_mode, gradient descent :1526); needs a validation run, not new code.
5. **[DONE] Bi-conjugate Frank-Wolfe** (`assignment_method` 0 FW / 1 CFW / 2 BFW). Cost-derivative
   Hessian + convex-combination auxiliaries (feasible); FW fallback on degeneracy/non-descent.
   Verified faster gap closure to the same UE; default FW byte-identical (regression PASS).
6. **[EXT, deferred — minor]** Progressive gap schedule across feedback loops (MWCOG).
7. **[EXT, deferred — minor]** Validation plugin (R²/%RMSE/VMT-by-FC/screenline) — the ARC
   `arc_validate_run.py` already covers this ad hoc.
9. **[CONV] Agency converters**: `serpm2gmns`, `trpa2gmns`, `mtc2gmns`, `sandag2gmns`
   (arc done) — each maps facility×area-type capacity/speed/VDF lookups + restrictions into the §1 schema.

> Net: the kernel already covers the ARC-style core (modified-BPR linear term, toll+opcost
> generalized cost, multiclass PCE/occ, relative-gap×N-consecutive stop). The main gaps for
> *full multi-agency* conformance are explicit VOT, the extra VDF forms (conical finish + BPR2/
> INRETS/Akcelik), bi-conjugate FW, and a validation plugin.
