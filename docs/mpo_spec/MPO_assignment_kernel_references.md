# MPO / DOT assignment references for the DTALite / TAPLite kernel

Cross-agency synthesis of public travel-model documentation, extracted to guide the
DTALite/TAPLite static-assignment kernel (VDF plugin, equilibrium solver, generalized cost,
multiclass, validation). Companion to `../ARC_Atlanta/ARC_DTALite_kernel_requirements.md`.

Each fact is attributed to the agency doc it came from. Where a doc did not state a value, it
is marked "not stated" — **do not substitute generic textbook values for a specific agency.**
Numeric lookup tables that live in external spreadsheets/PDFs that could not be machine-read are
flagged as gaps at the end.

Agencies covered: **ARC** (Atlanta, our base), **SERPM 8** (SE Florida), **TRPA** (Tahoe),
**MTC Travel Model One** (Bay Area), **SANDAG ABM3** (San Diego), **MWCOG/TPB** (Washington DC),
**VDOT** (Virginia policy), **ODOT** (Oregon APM), plus **AequilibraE** (open-source architecture).

---

## 1. Cross-agency comparison matrix

| Agency | Solver | Convergence target | TOD periods | # classes | VDF form | Generalized cost |
|--|--|--|--|--|--|--|
| ARC | bi-conjugate FW | rgap < 1e-4, **3 consec iters**, max 20 | 5 (EA/AM/MD/PM/EV) | 10 | **modified BPR + linear term** | time·VOT + toll + dist·opcost |
| SERPM 8 | Frank-Wolfe | rgap = 1e-4, **3 consec iters** | 5 | 8 (+2 AV) | modified BPR (by FTC2) | time + toll only |
| TRPA | MSA capacity-restraint (vendor GIS platform) | avg link-vol change < 1e-4, ~50 iters | 4 (AM/MD/PM/LN) | 2 (DA, SR) | standard BPR | time only |
| MTC TM1 | not stated (Cube) | not stated | 5 (EA/AM/MD/PM/EV) | 10 (5×pay/no-pay) | **modified BPR, 4/3 factor** | not stated (toll via classes) |
| SANDAG ABM3 | **SOLA** (Emme, path-based) | rgap = **5e-4** | 5 (EA/AM/MD/PM/EV) | 15 (3 income × SOV/HOV + trucks) | modified BPR + intersection delay | time·VOT + toll + opcost per class |
| MWCOG/TPB | bi-conjugate FW | **progressive** 1e-2→1e-4 over feedback; backup ≥1000 UE iters | 4 (AM/MD/PM/NT) | 6 | **conical** | time + cost (min/$ by class) |
| VDOT (policy) | bi-conjugate FW (recommended) | rgap = 1e-4 (recommended) | Daily/AM/PM/MD/NT | — | BPR / conical / Akcelik allowed | — |
| ODOT (APM) | UE / capacity-restrained (Visum) | not stated | daily + PM (JEMnR); 5-bin ABM | 1 (OSUM) | BPR (signalized vs not) | time |
| AequilibraE | AoN/MSA/FW/CFW/**BFW** | rgap target + max_iter | n/a | multi (TrafficClass) | BPR/BPR2/Conical/INRETS/Akcelik | time·VOT + fixed cost |

**Takeaways for the kernel:** static UE is universal; **bi-conjugate Frank-Wolfe** is the
modal solver (ARC, MWCOG, VDOT-recommended, AequilibraE); **relative gap ≈ 1e-4** is the modal
target (SANDAG 5e-4; MWCOG progressive). VDF form is the biggest divergence — see §2.

---

## 2. VDF library (the key kernel artifact)

Implement these as selectable VDF types; all are analytically differentiable (needed for
CFW/BFW line search — AequilibraE explicitly requires differentiable VDFs). Notation: `t`
congested time, `t0` free-flow time, `x = v/c` volume/capacity.

### 2.1 Standard BPR
`t = t0 · (1 + α·x^β)` — AequilibraE defaults α=0.15, β=4. Used by TRPA, ODOT, MTC (variant),
allowed by VDOT (α∈[0,2], β∈[1,10]). **This is the kernel's current `vdf_type=0`.**

### 2.2 Modified BPR — extra linear term (ARC)
`t = t0 · (1 + A·x + D·x^β)` — ARC's calibrated form (NOT standard BPR). Per-facility (A, D, β):
freeway (0.10, 0.60, 6); weave (0.20, 1.25, 5.5); ramps (0.10, 1.0, 4); expressway (0, 1.0, 4);
parkway (0, 1.25, 4); arterials/collector (0.10, 0.45, 4). **[kernel ADD: linear term].**

### 2.3 Modified BPR — capacity-shift factor (MTC TM1)
`t = t0 · (1 + 0.20·(4/3·x)^6)` — the 4/3 factor shifts delay onset (delay = 0.2 at x=0.75).
i.e. α=0.20, β=6 with v/c pre-scaled by 4/3.

### 2.4 BPR2 — exponent doubles past capacity (AequilibraE)
`x ≤ 1: t = t0(1 + α·x^β)`; `x > 1: t = t0(1 + α·x^(2β))`. Defaults α=0.15, β=4.

### 2.5 Conical (Spiess) — MWCOG, VDOT-allowed
`t = t0 · (2 + √(α²·(1−x)² + β²) − α·(1−x) − β)`. AequilibraE defaults α=0.15, β=4.
(MWCOG's calibrated α/β are in its separate 2012 calibration report — not in the user guide.)

### 2.6 INRETS (AequilibraE)
`x ≤ 1: t = t0·(1.1 − α·x)/(1.1 − x)`; `x > 1: t = t0·((1.1−α)/0.1)·x²`. α ≤ 1.0 (default 1.0).

### 2.7 Akcelik — VDOT-allowed, AequilibraE
`t = t0 + α·(z + √(z² + τ·x/c))`, `z = x − 1`. AequilibraE defaults α=0.25, τ=0.8.
**Convention warning:** AequilibraE folds the literature factor-of-8 into τ (literature τ=0.1 →
set τ=0.8). Document which convention the kernel uses.

### 2.8 Modified BPR + explicit intersection delay (SANDAG)
Uses mid-block capacity, intersection approach capacity, cycle length, and green/cycle ratio.
Per-fd coefficients: freeways fd10 α=0.24 β=5.5; arterials fd20–23 α=4.5 β=2; metered ramps fd24
α=6.0 β=2; freeway nodes fd25 α=0.6 β=4. **Plain BPR will diverge on arterials** unless the
intersection-delay term is added or capacities pre-adjusted.

### 2.9 Per-link BPR coefficient tables (ready to map into link.csv)
**TRPA** (α, β keyed by area type × speed limit × lanes) — e.g. Rural 60mph 2+ (0.09, 6);
Suburban 45mph (0.42, 5); Urban 35mph (1.00, 5); rural <2 lanes (0.34, 4). [full table in §8 TRPA card]

> **Kernel implication:** VDF parameters are almost always **per-link / per-facility-type**, not
> global. The kernel should read α/β (and A, τ) from link.csv columns; the agency2gmns converters
> precompute them from each agency's facility-type × area-type lookup.

---

## 3. Equilibrium solver & convergence

- **Relative gap** (portable definition, AequilibraE):
  `RelGap = (Σ Vₐ·Cₐ − Σ Vₐ^AoN·Cₐ) / (Σ Vₐ·Cₐ)`, Vₐ current equilibrium flow, Vₐ^AoN the
  all-or-nothing flow on current shortest paths, Cₐ link cost. Dual stop: `rgap_target` + `max_iter`.
- **Solver families to support:** AoN, MSA, FW, Conjugate FW (CFW), **Bi-conjugate FW (BFW)**.
  CFW/BFW need differentiable VDFs (provide closed-form dt/dv per §2). AequilibraE benchmark: BFW
  hits 1e-4 in <200 iters, 1e-5 in ~700; plain FW ~800 for 1e-4; MSA ~3.5e-4 after 1000.
- **Targets seen:** ARC & SERPM 1e-4 sustained 3 consecutive iterations; SANDAG 5e-4 (SOLA);
  MWCOG progressive (1e-2 → 1e-3 → 1e-4 across speed-feedback loops, backup ≥1000 UE iters);
  VDOT recommends 1e-4 + BFW; TRPA MSA avg-volume-change 1e-4 (~50 iters).
- **[kernel ADD]** "gap below target for N consecutive iterations" stop rule (ARC/SERPM use 3);
  and a progressive/tightening gap across feedback loops (MWCOG pattern).

---

## 4. Generalized cost & multiclass

| Agency | Cost formula | VOT | Operating / toll cost | PCE |
|--|--|--|--|--|
| ARC | time·VOT + toll + dist·opcost | auto $21.50/hr, truck $36/hr | auto $0.1729/mi, truck $0.5360/mi | MTK 1.5, HTK 2.0 |
| SERPM 8 | time + toll only | $15/hr peak, $12/hr off-peak (occupancy-independent) | no distance term | not stated |
| SANDAG | time·VOT + toll + opcost, **per class** | $0.0881–0.85/min by income; trucks $0.67–0.89/min | per-link fixed cost by class | LT 1.3, MT 1.5, HT 2.5 |
| MWCOG | time + cost via min/$ factor by class & period | min/$ table (Table 89) | yes | not stated |
| MTC | toll via paired pay/no-pay classes | not stated | not stated | not stated |
| AequilibraE | time·VOT + fixed_cost field | `set_vot` per class | `set_fixed_cost(field)` | `set_pce` per class |

**[kernel ADD]** per-class generalized cost = `time·VOT_class + toll_class + distance·opcost_class`,
with per-class VOT/opcost/PCE and toll restricted to toll-eligible classes. Toll-eligibility is
modeled by **splitting demand into toll/non-toll classes** (ARC, SANDAG `_TR`/`_NT`, MTC `T`),
not a binary toll-choice inside assignment.

---

## 5. Network coding patterns (for the agency2gmns converters)

- **Facility type × area type** drives capacity and free-flow speed lookups in *every* model
  (ARC, SERPM FTC2×lanes, MTC CAPCLASS=f(AT,FT,TOS,SIGCOR), SANDAG fd by FC, MWCOG, ODOT).
  Converters must precompute per-link capacity & FFS from these lookups and write them into link.csv.
- **Per-lane capacity** (veh/h/lane) is the universal unit. Sample freeway values: ARC 1900–2100,
  MTC 2050–2150 (CBD empirically ~1420–1780), MWCOG 1900–2000, ODOT 1900, TRPA principal-art 1100.
  Centroid connectors: ARC 10000, TRPA 9999, MTC "infinite", ODOT 9999.
- **Directional lanes** by TOD with period overrides (ARC LANES{period}, SANDAG ABLN{period}).
- **HOV / managed lanes / toll:** SANDAG HOV field {1 GP, 2 HOV2+, 3 HOV3+, 4 toll}, TOLL{period}
  cents/mile, "HOT if toll>0"; MTC USE/TOLLCLASS + FT8 managed freeway; ARC PROHIBIT codes (see
  ARC doc). Map to GMNS `allowed_use` + a toll/cost field.
- **Period capacity factor** (hourly→period): ARC EA 1.25 / AM 3.66 / MD 4.70 / PM 3.66 / EV 3.91.
- **Weave / interchange** capacity reduction: ARC `cap·0.98^(lanes−1)` for WEAVEFLAG, lanes>4.

---

## 6. Validation standards (most concrete = VDOT)

**VDOT (quotable, policy-level):**
- Volume-vs-count R²: **0.90 large regions, 0.92 small**.
- %RMSE by volume group: <5k 100% · 5–10k 45% · 10–15k 35% · 15–20k 30% · 20–30k 27% ·
  30–50k 25% · 50–60k 20% · >60k 19% · areawide daily 40%.
- %RMSE by facility type: freeway 20% · principal art 35% · minor art 45% · collector 100%.
- VMT by functional class: freeways ±7% · principal ±7–15% · minor ±10–15% · collector ±15–25% ·
  all links ±2–5%. By area type ±10% (Ohio) / ±25% accept / ±15% prefer (FDOT).
- Screenline/cordon: <54k ±10%; ≥250k ±5%; mid-range per a deviation curve. Coverage ≥5–10% of
  non-centroid links. Speed: congested-vs-uncongested check; >5 mph deviation triggers review.
- Caveat: guidelines are **not pass/fail tests**.

**ODOT:** R² ≥ 0.9 desired (slope ≈ 1.0); screenline model/count within ~10%; VMT by FC vs HPMS
as reasonableness. **TRPA:** %RMSE < 40% (got 30.7%), correlation ≥ 0.88 (got 0.93), ≥75% links
within RTP-deviation (got 82.4%). **ARC:** region %RMSE ~38%, V/C ~0.91, arterial-and-above VMT
within ~6% (see ARC doc for full tables). **SERPM:** feedback target = demand-weighted %RMSE of
AM&PM drive-alone travel time < 1%.

**[kernel outputs needed]** link `volume`, per-class `mod_vol_*`, `ref_volume`, VMT/VHT, speed,
v/c (`doc`) — already emitted in `link_performance.csv`; add screenline/cutline aggregation and
%RMSE-by-volume-group reporting to a validation plugin.

---

## 7. Kernel design pattern (target)

```
agency model docs  ->  <agency>2gmns converter  ->  standard node.csv / link.csv / demand_<class>.csv / settings
   ->  TAPLite static UE (AoN/MSA/FW/CFW/BFW)  +  VDF plugin (BPR | BPR2 | conical | INRETS | Akcelik | modified-BPR±linear)
   ->  validation plugin (counts / VMT / speed / screenline / %RMSE)
```
Converters to build (each maps facility-type×area-type lookups + restrictions into GMNS):
`arc2gmns.py` (done), `serpm2gmns.py`, `trpa2gmns.py`, `mtc2gmns.py`, `sandag2gmns.py`.

---

## 8. Per-agency reference cards (condensed, grounded)

### SERPM 8 (SE Florida) — sites.google.com/site/serpm8reference
Multi-class **static UE, Frank-Wolfe, rgap 1e-4 over 3 consecutive iters**. Cost = **time + toll
only** (no distance term); VOT **$15 peak / $12 off-peak**, occupancy-independent. **8 classes**
(DA free/pay, SR free/pay, TNC-alone, TNC-shared, large trucks, externals) +2 optional AV. VDF =
**modified BPR by FTC2**; capacity from FTC2×lanes lookup; FFS from POSTSPD×FTC2. Key fields FTC2,
NUM_LANES (uni-directional, excludes turn/merge, incl aux), POSTSPD, SIGLOC (signal). Speed
feedback via **MSA**; feedback target demand-weighted %RMSE AM&PM DA time **<1%**. *Gaps:* all
numeric lookup tables + TOD hour ranges live in external Google Sheets (not machine-readable).

### TRPA (Tahoe) — trpa-agency.github.io/travel_demand_model
**Vendor-GIS MSA capacity-restraint**, AoN inner step; converge at avg link-vol change **1e-4**,
~**50 iters**. Paths by **time only**. **4 periods** AM 7–10, MD 10–16, PM 16–19, LN 19–7.
**2 classes** (drive-alone, shared-auto). **Standard BPR**; full α/β table by area-type×speed×lanes
(Rural/Suburban/Urban; e.g. Rural60 2+ →0.09/6, Urban35 →1.00/5). Per-lane cap: principal 1100,
minor 800, collector 500, centroid 9999. Area type from density (WP<600 rural, <7500 suburban,
else urban). Validation: %RMSE<40% (30.7%), corr≥0.88 (0.93), ≥75% links within deviation (82.4%).

### MTC Travel Model One (Bay Area) — github.com/BayAreaMetro
**5 periods** EA 3–6, AM 6–10, MD 10–15, PM 15–19, EV 19–3. **10 classes** = {DA, S2, S3, SM, HV}
× {no-pay, pay-HOT}. VDF = **modified BPR `t0·(1+0.20·(4/3·x)^6)`**. Freeway cap 2050–2150 vphpl by
area type (CBD empirically ~1420–1780), FFS 55–65 (PeMS suggests uniform ~67). Network: FT, AT,
CAPCLASS=f(AT,FT,TOS,SIGCOR)→CAP/FFS/CritSpd, FFT=dist/FFS·60, TOLLCLASS, USE, BRT. *Gaps:* solver,
rgap, VOT, PCE live in Cube scripts / params_*.properties (not in wiki).

### SANDAG ABM3 (San Diego) — sandag.github.io/ABM (Emme)
**SOLA path-based UE, rgap 5e-4**. **15 classes** (3 income × {SOV_NT, SOV_TR, HOV2, HOV3} + 3
trucks). VOT $0.0881–0.85/min by income, trucks $0.67–0.89; **PCE LT1.3/MT1.5/HT2.5**; transit
preload in PCE. VDF **modified BPR + intersection delay** (cycle length, g/C): fd10 freeway
0.24/5.5; fd20–23 arterials 4.5/2; fd24 metered ramp 6.0/2; fd25 freeway node 0.6/4. FC 1–12;
HOV field {1 GP,2 HOV2+,3 HOV3+,4 toll}; TOLL{period} cents/mi ("HOT if >0"); truck restriction
{1..7, 7=truck-only}; intersection control codes; connectors FC=10. Skims via fixed-flow 0-iter
reassignment. *Gaps:* TOD hours, validation targets, TNED schema not public.

### MWCOG / TPB (Washington DC) — user guide v2.3.78
**Multi-class UE, bi-conjugate Frank-Wolfe.** Convergence **progressive** (pump-prime/SFB≤2: 1e-2;
iter3: 1e-3; iter4: 1e-4), backup ≥1000 UE iters. **4 periods** AM 6–9, MD 9–15, PM 15–19, NT
19–6. **6 classes** (SOV, HOV2, HOV3+, med/heavy trucks, commercial, airport autos); two-step AM/PM
split → 6 assignments/feedback. VDF = **conical** (`hwy_assign_Conical_VDF.s`; coefficients in the
separate 2012 calibration report). Free-flow cap (vphpl by AT 1–6): freeways 1900–2000, expressways
1100–1600, major art 600–1100, minor 500–900, collectors 500–800, ramps 1000–2000. FFS: freeways
55–65, major art 35–50, minor 35–45, collectors 30–35, expressways 45–55, ramps 20–50. *Gaps:*
numeric validation criteria in separate calibration reports.

### VDOT (Virginia policy) — TDM Policies & Procedures v3.0
State-of-practice **static equilibrium (Wardrop)**; recommends **bi-conjugate FW to rgap 1e-4**.
VDFs **BPR / conical / Akcelik** all acceptable (BPR α∈[0,2], β∈[1,10]). Best source of **concrete
validation standards** (see §6). Explicit caveat: guidelines are not pass/fail.

### ODOT (Oregon APM Ch.17) — Visum
Methods: capacity-restrained / UE / AoN. **BPR**, applied differently for signalized vs unsignalized
links; peak vs daily have unique VDFs. Default per-lane cap (FC×area CBD/Fringe/Urban/Rural):
freeway 1900; principal 700–950; minor 575–760; collector 450–650; local 400–625; ramps 700–1000;
connectors 9999. Validation: R²≥0.9 desired, screenline model/count within ~10%, VMT-by-FC vs HPMS.

### AequilibraE (open-source architecture) — aequilibrae.com
Reference implementation of the VDF library (§2.1,2.4,2.5,2.6,2.7) and solver set (AoN/MSA/FW/CFW/
BFW) with the relative-gap definition in §3. Multiclass via `TrafficClass` + `set_pce`/`set_vot`/
`set_fixed_cost`. Good template for the kernel's VDF-plugin interface (string-keyed VDF + per-link
parameter arrays + required closed-form derivative for line search).

---

## 9. Gaps / where the missing numbers live

- **SERPM 8:** capacity/FFS/BPR tables and TOD hours are in external Google Sheets data dictionaries.
- **MTC:** solver, rgap, VOT, PCE in Cube assignment scripts + `params_*.properties`; validation in
  per-version Calibration reports (Box links from the Development wiki).
- **MWCOG:** conical α/β and validation acceptance criteria in the 2012 Calibration Report (separate).
- **SANDAG:** TOD hour ranges, validation targets, full TNED schema not public.
- **TRPA:** exact VDF/MSA equations only as page images; VOT/toll not stated.
- To fill these, fetch the Cube/GISDK/Emme scripts and the calibration/validation PDFs directly
  (browser, not plain HTTP) per agency.
