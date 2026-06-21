# ARC Atlanta -> DTALite/TAPLite kernel requirements

Specification extracted from the ARC ABM documentation (Section 6 Model Inputs,
Section 7 Trip Assignment) and the ARC Cube assignment script `ARC_ABM_*.s`, written so the
DTALite C++ kernel can **replicate ARC's static highway assignment**. Each requirement notes
the source and the gap (if any) vs. the current kernel / our GMNS conversion.

Sources:
- `ARC_clone/docs/ModelInputs.html` (S6.3 network coding, S6.3.6 prohibitions)
- `ARC_clone/docs/TripAssignment.html` (S7 assignment method, VDF, validation)
- `ARC_clone/ARC_ABM_10-1-19_M7.s` (authoritative parameters; line refs below)

Legend: **[MATCH]** kernel already does it · **[ADD]** kernel change needed ·
**[DATA]** handled in GMNS conversion (link.csv/settings).

---

## 1. Network coding

### 1.1 Topology & centroids
- Directed links: each record is one direction `A`->`B` (two-way roads = two records). **[DATA]**
- Centroids = nodes `1..NZ` (NZ=6031 incl. externals; 5,922 internal TAZs). DTALite needs
  `node_id == zone_id` for centroids — ARC numbering already satisfies this. **[DATA]/[MATCH]**
- Connectors = `FACTYPE 0`; coded capacity 0 = "unlimited" (kernel must treat as uncongested,
  very high capacity). **[DATA]**
- `link.csv` must be sorted ascending by `from_node_id` (CSR adjacency). **[DATA]**

### 1.2 Facility type (FACTYPE) — auto types 0-14, transit 50-99 (EXCLUDE transit)
0 connector · 1 interstate/freeway · 2 expressway · 3 parkway · 4 freeway HOV buffer ·
5 freeway HOV barrier · 6 freeway truck-only · 7 sys-to-sys/CD/ramp · 8 exit ramp ·
9 entrance ramp · 10 principal arterial · 11 minor arterial · 12 arterial HOV ·
13 arterial truck-only · 14 collector/local · **50/51/52/53/55/98/99 = transit (not auto)**. **[DATA]**

### 1.3 Area type (ATYPE) drives speed & capacity lookups
1 CBD · 2 urban commercial · 3 urban residential · 4 suburban commercial ·
5 suburban residential · 6 exurban · 7 rural. (`ATYPE` is a link attribute.) **[DATA]**

### 1.4 Lanes (LANES = through + aux, ONE direction)
- Period override: `LANES{EA,AM,MD,PM,EV}` replaces `LANES` only when > 0, else use `LANES`. **[DATA]**
- Reversible lanes handled by period lane fields (AB gets +1 AM, BA gets +1 PM, etc.).

### 1.5 Free-flow speed lookup (Table 7-1, mph by FACTYPE x ATYPE)
| FT | name | A1 | A2 | A3 | A4 | A5 | A6 | A7 |
|--|--|--|--|--|--|--|--|--|
|0|connector|7|11|11|11|11|14|14|
|1|interstate|62|63|63|63|64|65|66|
|2|expressway|43|46|49|52|55|58|61|
|3|parkway|43|46|49|52|55|58|61|
|4|freeway HOV buffer|64|65|65|65|66|67|68|
|5|freeway HOV barrier|64|65|65|65|66|67|68|
|6|freeway truck|62|63|63|63|64|65|66|
|7|sys-sys ramp|50|50|50|55|55|55|55|
|8|exit ramp|35|35|35|35|35|35|35|
|9|entrance ramp|35|35|35|35|35|35|35|
|10|principal art|23|26|31|35|41|48|53|
|11|minor art|21|26|29|33|38|43|48|
|12|arterial HOV|21|26|29|33|38|43|48|
|13|arterial truck|21|26|29|33|38|43|48|
|14|collector/local|17|23|24|26|30|35|45|

Extra rules: loop ramps -> 35 mph (`RAMPFLAG`); principal-arterial CBD speed varies by lanes;
links with observed NPMRDS speed -> FFS = avg(observed EA speed, lookup). **[DATA]** (our
conversion takes the link `SPEED` field, which already embeds these rules.)

### 1.6 Hourly capacity lookup (Table 7-2, LOS-E veh/h/lane by FACTYPE x ATYPE)
connector 10,000 all ATYPE · interstate 1900/1900/2000/2000/2050/2100/2100 ·
expressway 1200..1450 · parkway 1150..1400 · freeway HOV (4,5) = interstate · freeway truck (6)
= interstate · sys ramp(7) 1300..1700 · exit ramp(8) 800..900 · entrance ramp(9) 900..1100 ·
principal art(10) 1000..1300 · minor art(11) 900..1100 · arterial HOV(12) 1000..1300 ·
arterial truck(13) 900..1100 · collector(14) 750..900. **[DATA]**

### 1.7 Capacity adjustments — kernel-relevant
- **Period capacity** = hourly cap x **period factor** (not x hours):
  EA 1.25 · **AM 3.66** · MD 4.70 · PM 3.66 · EV 3.91. **[DATA]** (our `AMCAPACITY` already = period cap.)
- **Weave sections** (`WEAVEFLAG=1`, lanes > 4): `cap = base_cap * 0.98^(lanes-1)`. **[DATA/ADD]**
- DTALite `capacity` is PER-LANE: `capacity = period_directional_cap / lanes`. **[DATA]**

---

## 2. Demand types (vehicle classes)

ARC assigns **10 classes per period** (S7.1):
SOV non-toll · HOV2 non-toll · HOV3+ non-toll · SOV toll · HOV2 toll · HOV3+ toll ·
commercial vehicle · medium truck · heavy truck (I-285 bypass) · heavy truck (remaining).

- "non-toll / toll eligible" = value-of-time segmentation for **managed-lane choice**, not lane
  access. **[ADD]** (multiclass + per-class VOT; see generalized cost below.)
- **PCE** in VDF: medium truck = **1.5**, heavy truck = **2.0**, autos = 1.0 (`.s` line 2705). **[ADD]**
- Our current GMNS uses 3 auto classes (sov/hov2/hov3 = F+T combined, no trucks). Full ARC
  replication needs the truck classes + the toll-eligible split. **[DATA/ADD]**

---

## 3. Restrictions -> allowed_use (PROHIBIT field, authoritative)

`PROHIBIT` is what ARC's path builder uses (`.s` ADDTOGROUP, lines 1364-1376). Toll = cost,
NOT access, so managed-lane codes still ALLOW the tolled vehicle. Mapping to GMNS `allowed_use`
for auto modes {sov,hov2,hov3}:

| PROHIBIT | meaning | allowed_use |
|--|--|--|
|0|general purpose|*(all)*|
|1|no trucks|*(all)* for autos|
|2|HOV 2+|`hov2;hov3`|
|3|ML: SOV toll, HOV2+ free|*(all)*, SOV tolled|
|4|truck only|closed to autos (`trk`)|
|5|I-285 bypass (truck routing)|*(all)* for autos|
|6|HOV 3+|`hov3`|
|7|ML: SOV+HOV2 toll, HOV3 free|*(all)*, SOV+HOV2 tolled|
|8|ML: SOV+truck toll, HOV2+ free|*(all)*|
|9|ML: SOV+HOV2+truck toll, HOV3 free|*(all)*|
|10|truck only toll|closed to autos (`trk`)|
|11|ML: HOV2 toll, HOV3 free, no SOV|`hov2;hov3`|
|12|ML: SOV+HOV2+ toll, no trucks|*(all)*, autos tolled|
|13|ML: all autos, tolled|*(all)*, tolled|

Only **2/6/11** restrict autos; **4/10** are truck-only. **[DATA]** Kernel must honor
per-mode `allowed_use` with dedicated shortest paths (`dedicated_shortest_path=1`). **[MATCH]**

---

## 4. Traffic assignment method

- **Algorithm**: user equilibrium via **bi-conjugate Frank-Wolfe** (`.s` 2540
  `COMBINE=EQUI, ENHANCE=2, SMOOTH=0`). **[CHECK]** kernel currently does MSA/FW — confirm
  bi-conjugate FW is available/selected for parity.
- **Convergence**: `RELATIVEGAP = 1e-4`, met for **3 successive iterations** (`.s` 2539, 2727).
  `MAXITERS = 20`. **[ADD]** kernel needs the "3 consecutive iters below gap" stop rule (we used
  `number_of_iterations`; add a relative-gap target — schema has `convergence_gap_pct`). **[CHECK]**
- **Multithread** assignment (`MULTITHREAD`). **[MATCH]** (`number_of_processors`).

### 4.1 Generalized cost (S7.1) — kernel-relevant
`cost = time*VOT + toll + distance*operating_cost`
- Passenger-car **VOT = $21.50/hr**; truck VOT = $36.00/hr. **[ADD]** (per-mode `vot`.)
- Auto **operating cost = $0.1729/mi**; truck = $0.5360/mi. **[ADD]** (distance term in cost — the
  kernel's pure time-based shortest path must add `distance*op_cost` and `toll`.) **[CHECK/ADD]**
- Toll term: from `TOLLID` -> `TOLLS{yr}.DBF` rate (cents); `FIXED=0` => distance-based
  (rate x miles), `FIXED=1` => flat. Managed-lane toll varies by which class is tolled (table S3).
  **[ADD]** (toll cost layer per class.)

### 4.2 Time-of-day periods (run 5 separate assignments)
EA 3-6 · **AM 6-10** · MD 10-3 · PM 3-7 · EV 7-3. Each period has its own demand, lanes,
capacity factor, and tolls. **[DATA]** (we built AM; replicate per period.)

---

## 5. Volume Delay Function (modified BPR) — exact

`.s` lines 2680-2698. **General form (NOT standard BPR — has an extra linear term):**

```
Tc = T0 * ( 1 + A*(V/C) + D*(V/C)^B )
```

| Facility | FACTYPE | A | D | B |
|--|--|--|--|--|
| Freeway basic | 1 | 0.10 | 0.60 | 6.0 |
| Freeway HOV concurrent | 4 | 0.10 | 0.60 | 6.0 |
| Freeway HOV barrier | 5 | 0.10 | 0.60 | 6.0 |
| Freeway truck | 6 | 0.10 | 0.60 | 6.0 |
| Freeway **weave** (`WEAVEFLAG`) | — | 0.20 | 1.25 | 5.5 |
| Sys-sys / exit / entrance ramp | 7,8,9 | 0.10 | 1.00 | 4.0 |
| Expressway | 2 | 0.00 | 1.00 | 4.0 |
| Parkway | 3 | 0.00 | 1.25 | 4.0 |
| Principal / Minor / Arterial-HOV / Arterial-truck | 10,11,12,13 | 0.10 | 0.45 | 4.0 |
| Collector / local | 14 | 0.10 | 0.45 | 4.0 |

**Kernel gap [ADD]:** DTALite standard BPR is `fftt*(1 + alpha*(v/c)^beta)`. ARC adds a
**linear `A*(V/C)` term**. To match ARC exactly the kernel needs a VDF variant
`fftt*(1 + A*(v/c) + alpha*(v/c)^beta)` (alpha=D, beta=B). If only standard BPR is available,
approximate with `vdf_alpha=D, vdf_beta=B` and **drop A** (error is small at low V/C, grows near
capacity). Our GMNS currently sets a flat `alpha=0.15, beta=4` — **[DATA] change to per-FACTYPE
D/B from this table**, and add the `A` term column if the kernel supports it.

PCE applied inside V (V = sum class_vol * PCE) — see §2. **[ADD]**

---

## 6. Inputs the kernel/conversion must consume (calibrated)

- `CAPACITY.DBF` (Table 7-2 hourly cap by FT x ATYPE) + period factors (§1.7).
- `FFSPEED.DBF` (Table 7-1 free-flow speed by FT x ATYPE) + AMSPEED.DBF (1st feedback congested).
- `AUXLANE.DBF` (aux-lane capacity by FT).
- `TOLLS{yr}.DBF` (toll rate by TOLLID/period, cents, FIXED flag).
- Network attributes: `A,B,FACTYPE,ATYPE,LANES,LANES{period},DISTANCE,SPEED,PROHIBIT,TOLLID,GPID,
  WEAVEFLAG,RAMPFLAG,AMCAPACITY,...` (full list in ModelInputs Tables 6-4/6-5).
- Demand: per-class period OD matrices (we have AM cores SOVF/SOVT/HOV2F/HOV2T/HOV3F/HOV3T).

## 7. Outputs & calibration targets (validation parity)

ARC validates assignment against (S7.1.3-7.1.4):
- **VMT by functional class** vs GDOT AADT->AWDT (factors: 13-cty interstate 1.03, non-int 1.07;
  8-cty interstate 1.003, non-int 1.065). Target: arterial-and-above within ~6%.
- **Counts at 5,000+ GDOT locations**: RMSE, %RMSE, volume/count ratio by volume group / FACTYPE /
  ATYPE. Region-wide %RMSE ~38%; V/C ratio ~0.91. Acceptable %RMSE thresholds by volume group:
  <2.5k:100% · 5-10k:45% · 10-25k:30% · 25-50k:25% · 50-75k:19% · >=100k:19%.
- Kernel outputs to support this: link `volume`, `ref_volume` (we set = V_SOVAM+V_HOV2AM+V_HOV3AM),
  per-class `mod_vol_*`, VMT/VHT, speed, v/c (`doc`). **[MATCH]** (link_performance.csv already has these.)

---

## 8. Kernel checklist (what to verify in the C++ code)

1. [CHECK] Bi-conjugate Frank-Wolfe available & selected (vs MSA) — for ARC parity.
2. [CHECK] Stop rule = relative gap < 1e-4 for 3 consecutive iterations (not just iter count).
3. [ADD] VDF with linear term: `fftt*(1 + A*(v/c) + alpha*(v/c)^beta)`; per-FACTYPE A/D/B.
4. [ADD] Generalized cost = time*VOT + toll + distance*op_cost (per-class VOT & op cost).
5. [ADD] Toll cost layer (TOLLID->rate, distance-based when FIXED=0; class-specific tolling).
6. [ADD] PCE in loaded volume (MTK 1.5, HTK 2.0).
7. [MATCH] Per-mode allowed_use w/ dedicated shortest paths (verified: SOV=0 on HOV-only).
8. [DATA] Per-period runs (EA/AM/MD/PM/EV) with period lanes, capacity factors, tolls.
9. [DATA] Weave capacity reduction (0.98^(lanes-1)) for WEAVEFLAG, lanes>4.
10. [MATCH] node_id==zone_id centroids; link.csv sorted by from_node_id.
