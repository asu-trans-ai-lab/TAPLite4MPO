# Conversion Error Catalog — every way an MPO hand-off goes wrong

**Audience: anyone converting an agency travel-demand model (vendor GIS / Cube / NeXTA /
shapefile) to a TAPLite/DTALite GMNS assignment.**

> **The one principle:** onboarding is *model-meaning* conversion, not file-format
> conversion. GMNS is only the container. The assignment is defined by **capacity, period,
> PLF, units, demand class, allowed-use, toll, and the validation target** — and **TAPLite
> never guesses these**. Every error below is a convention that was assumed instead of
> declared. When a run looks wrong, **suspect a convention mismatch, not the solver.**

This catalog is the Gate-2 ("Can I trust it?") reference for the
[Golden Path](GOLDEN_PATH_CHECKLIST.md) and [MPO Onboarding Guide](MPO_ONBOARDING_GUIDE.md).
Each entry is **symptom → cause → correct convention → seen in → how intake catches it**.

## How these are caught before they cost you a week

`python -m dtalite_qa intake <scenario>` classifies every issue by severity, and runs
**evidence cross-checks** (a declaration that disagrees with the data is flagged, not
trusted — e.g. `length_unit: mi` but median length 710 ⇒ contradiction):

| severity | meaning | blocks the gate? |
|---|---|---|
| **BLOCKER** | the run cannot be correct without it | **yes** |
| **DECISION** | a default exists but is risky; the MPO must choose | no, review |
| **MISSING** | absent; a safe default is applied and recorded | no |
| **INFO** | a detected fact or step | no |

The rule: **anything the MPO did not declare becomes a blocking issue that names the field
to provide and why it matters.** Declare it in `submission.yml`; then it is on the record,
reproducible, and reviewable.

---

## 1. Capacity — the #1 source of wrong answers

Capacity has **two independent axes**, and getting either wrong silently rescales V/C.

### 1a. Basis: per-lane vs per-link (total)
- **Symptom:** V/C 2–4× too low; freeways barely congest; speeds far too high; VHT far
  below the reference even though volumes look right.
- **Cause:** the kernel treats the `capacity` field as **per-lane** (`Lane_Capacity =
  capacity; Link_Capacity = lanes × capacity`). Commercial exports usually deliver **total**
  (all-lane) capacity. Writing the total into the per-lane field inflates `Link_Capacity`
  by the lane count.
- **Correct convention:** `capacity = total_hourly_capacity / lanes` (per-lane, per-hour).
- **Seen in:** **SCAG RTP24** — `AB_HRCAPAC` is total (freeway fac 10 = 7200 = 4 lanes ×
  1800; arterial fac 40 = 1500 = 2 × 750); the converter wrote it straight into the
  per-lane field, so V/C ran 4× low on freeways. Gentle default BPR *hid* it; the steep
  calibrated VDF (β=8) *exposed* it (freeway speeds ~69 mph vs reference ~42). Fix:
  `capacity = HRCAPAC / lanes`. Every agency model seen so far (GSATS, ARC) divides by lanes.
- **Detection:** compute per-lane capacity by facility and sanity-check (freeway ≈
  1800–2000, arterial ≈ 600–900). A freeway "per-lane" capacity of 7200 is the tell.

### 1b. Period: hourly vs period vs daily
- **Symptom:** daily-as-hourly ⇒ **median V/C ≈ 0.007** ("no congestion anywhere");
  hourly-as-period ⇒ over-congested.
- **Cause:** the DBF often carries several capacity columns that differ ~5× and nothing
  states which is the assignment capacity or its duration.
- **Correct convention:** declare `capacity_period` and the exact source column; convert to
  hourly per-lane `c_h`.
- **Seen in:** **GSATS** — `AB_CAP` (daily), `AB_CAP_PK` (peak), `AB_CAP_OFF` (off-peak).
  A first pass used `AB_CAP` and AM came out at V/C ≈ 0.007. The right response is **not**
  to quietly switch columns but to **block** and ask which column, what duration, what PLF.
- **Detection:** intake reports `BLOCKER capacity_period: undeclared`; median V/C far from
  ~0.6–0.9 for a peak period is the symptom.

---

## 2. Period & Peak Load Factor (PLF)

### 2a. Flat PLF on a multi-hour period
- **Symptom:** peak-hour congestion under-stated — ~6% at AM, but **~2.5× at night**
  (NT PLF ≈ 0.40).
- **Cause:** a static run loads a whole *period* of demand but the VDF congests by the
  *hour*. Setting `vdf_plf = 1` (flat) — or, equivalently, using the **period** capacity
  with `vdf_plf = 1/H` — hard-codes PLF = 1.
- **Correct convention:** `c_period = φ·c_h` with **φ = L·PLF**; in the kernel keep
  `capacity = c_h` (hourly per-lane), `H` = period length, `vdf_plf = the real PLF`.
  Then `DOC = (V/lanes/H/PLF)/c_h`. See [peak_load_factor.md](peak_load_factor.md).
  **Red flag:** if `VDF_cap` scales *exactly* with period length (e.g. 3:6:3:12 across
  AM:MD:PM:NT) it was built flat (φ = L) and needs the real PLF.
- **Seen in:** **ARC** AM period is 4 h (6–10) with φ = 3.66 ⇒ PLF = 3.66/4 = 0.915
  (an early GMNS used H = 3 and no PLF, under-stating AM ~9%). **AZTDM** old NeXTA carried
  `VDF_cap` built flat; corrected to memo PLF (0.94–0.98 day, 0.40 night). **MAG** declares
  per-facility `vdf_plf` (PHF→PLF, e.g. 0.9075/0.975/1.0). **SCAG/AZTDM** ship flat PLF=1.
- **Detection:** intake `DECISION vdf_plf flat across an H-hour period`; PLF bounds enforced
  by `dtalite_qa/plf.py` (`0 < PLF ≤ 1`, and `φ = L·PLF ≥ 1`).

### 2b. Comparing an assigned period to a daily-loaded reference
- **Symptom:** a clean, high-R² count regression with a **slope far below 1** (e.g. β≈0.18
  overall, freeway β≈0.18) that looks like massive under-assignment.
- **Cause:** assigning one period (AM) and comparing to a **daily** reference. The slope is
  the period/daily fraction, not a routing error.
- **Correct convention:** compare **like to like**. Either (1) assign all periods and sum to
  daily, or (2) use the reference's *period-specific* fields. **Do not** scale a daily
  reference by one factor — the period share varies by facility (freeways peak harder than
  collectors), so a single scalar injects false residuals.
- **Seen in:** **SCAG** — AM-vs-daily gave freeway β=0.18; the trace `β(0.177) ≈
  AM-veh/daily-veh(0.186)` proved it was pure period scaling. Summing all 5 periods →
  daily lifted freeway β to **0.94 (R²=0.91)**; and using the reference's AM-specific
  `VMT_LM_AM/LENGTH` gave freeway **count β=1.10 (R²=0.90)** — 1:1, no bias.
- **Detection:** if β is roughly constant across facilities and equals your
  period/daily demand fraction, it's a basis mismatch, not the network.

---

## 3. Units

### 3a. Length — metres/km labeled as miles
- **Symptom:** distance-based cost inflated ~**1609×** (metres) or ~1.6× (km).
- **Correct convention:** GMNS `length` in metres; emit a separate `vdf_length_mi` (miles)
  for the VDF free-flow time. Declare `length_unit`.
- **Detection:** intake cross-check — median length ~710 while declared `mi` ⇒ contradiction.

### 3b. Speed — km/h labeled as mph
- **Symptom:** free-flow time cost off by **1.6×**.
- **Correct convention:** emit both `free_speed` (km/h, GMNS) and `vdf_free_speed_mph`
  (mph, for the VDF). MAG/ARC/GSATS/SCAG all emit `vdf_free_speed_mph` explicitly so the
  kernel cannot misread the unit.

### 3c. free-flow time vs speed vs length inconsistency
- **Symptom:** fftt disagrees with length/speed; congested speeds implausible.
- **Correct convention:** derive fftt from a consistent pair and guard degenerate inputs:
  if `AB_TIME ≤ 0`, fall back to `60·length_mi/speed_mph`. (GSATS uses `AB_TIME`; SCAG uses
  `AB_FREETIM` with a speed fallback.)

---

## 4. Demand — vehicles vs persons, occupancy, class, truncation

### 4a. Person trips loaded as vehicles
- **Symptom:** network over-loaded by the occupancy factor.
- **Correct convention:** declare `demand_kind` (vehicle vs person) and `occupancy`. Convert
  persons→vehicles by occupancy **per class**.
- **Seen in:** **SCAG** CT-RAMP disaggregate trips split by `tripMode` into SOV (×1),
  HOV2 (×0.5), HOV3 (×0.303 = 1/3.3); non-auto (`tripMode ≥ 7`) **dropped** (~17%). ARC/
  GSATS ship vehicle trips already (occupancy 1).

### 4b. PCE ≠ occupancy
- **Cause:** trucks convert to vehicles by occupancy=1 but load the network at **PCE > 1**.
  Keep the two separate in `mode_type.csv`.
- **Seen in:** **AZTDM** 5 classes (sov/hov2/hov3/sut/mut) with per-mode PCE.

### 4c. Demand file silently truncated
- **Symptom:** last origin zones missing; totals low; a period "can't be run faithfully."
- **Cause:** a matrix exported through **Excel** is capped at **1,048,575 rows**.
- **Seen in:** **AZTDM** AM passenger files each hit exactly 1,048,575 rows (~85% of origins
  dropped). **Fix:** obtain the untruncated file or stream from the source (never round-trip
  a large matrix through Excel).
- **Detection:** row count == 1,048,575, or max origin id ≪ zone count.

---

## 5. Zone-ID mapping — scrambles the whole OD table

### 5a. Centroid node id ≠ zone id
- **Cause:** the kernel treats a node as a zone **iff `zone_id == node_id`**. Agency
  centroid ids (e.g. 2390673) must be renumbered so the centroid node id equals its zone id.
- **Seen in:** **GSATS** — 721 centroids renumbered to zone 1..721. Declare `zone_id_basis`.

### 5b. Matrix labels ↔ zone ids (multi-tier TAZ)
- **Symptom:** demand zones don't map to network centroids; huge unmatched demand.
- **Cause:** the demand matrix keys on a *different* TAZ system than the network carries.
- **Seen in:** **SCAG** — trips key on **tier-2** TAZ (~11,259) but the network only kept
  **tier-1** (1–4,109) after field truncation (§7). Fixed with a tier-2↔tier-1
  correspondence + spatial join of tier-2 boundaries to centroids (100%).

### 5c. Node/link ordering
- **Symptom:** kernel warns "link.csv is NOT sorted by from_node"; adjacency wrong.
- **Correct convention:** after renumbering, **sort links by `from_node_id`** (the kernel's
  CSR adjacency assumes it). For NeXTA, map to `node.csv` row order first, then sort.
- **Seen in:** AZTDM (node.csv was descending), SCAG, ARC all sort by `from_node_id`.

---

## 6. VDF — default curve vs the agency's calibrated curve

- **Symptom:** high-volume links over/under-loaded; %RMSE dominated by the top volume group;
  results not reproducible against the agency.
- **Cause:** using BPR defaults `α=0.15, β=4` for all facilities instead of the agency's
  **per-facility** (× area type × posted speed) coefficients and VDF *form*.
- **Correct convention:** take α/β (and the form) from the agency's assignment
  documentation; pick the matching `vdf_type` (the kernel ships BPR, conical, BPR2, INRETS,
  Akcelik, SANDAG-signal, and **SCAG piecewise + ramp-meter**). Declare `vdf_source`.
- **Seen in:** **ARC** — flat 0.15/4 gave region %RMSE 88%; the per-FACTYPE Section-7 table
  (freeway 0.60/6.0, etc.) brought it to 23%. **SCAG** — Validation Report Table 16-2 is a
  *piecewise* BPR (β=4 below capacity, calibrated β=5/6/8 above, by facility × posted speed
  × area type; α=1.0 freeway / 0.8 others) plus a separate freeway on-ramp meter function
  (fac 82/84). Implemented as kernel `vdf_type=7`/`8`; the steep β=8 correctly diverts
  freeway→arterial (arterial R² jumped MajArt 0.68→0.84, MinArt 0.51→0.72).
- **Note (convergence):** steep VDFs (β=8) are **stiff** — plain Frank-Wolfe left a ~6% gap
  at 20 iters. Use `assignment_method=2` (bi-conjugate FW) and ≥40 iterations. A loose gap
  reads as *over-diversion*, which is easy to mistake for a routing error.

---

## 7. Directionality & field-name truncation

### 7a. Two-way vs one-way split
- **Correct convention:** vendor AB/BA records carry a `DIR` field — `0` ⇒ emit both
  directions, `1` ⇒ AB only, `-1` ⇒ BA only. (SCAG: 124,076 records → 224,288 directed.)
  Already-directed networks (ARC) instead need closed-in-period links (`AMCAPACITY=0`)
  dropped.

### 7b. DBF 255-field / 10-char truncation
- **Symptom:** a critical join/zone field is simply **absent** from the shapefile.
- **Cause:** shapefile DBF caps at **255 fields** and **10-char** names; a rich agency
  table (SCAG had 471 fields) loses columns on export.
- **Seen in:** **SCAG** — the tier-2 zone field (`T2TAZ`/`ccportzone`) was truncated away,
  which *was* the demand-mapping blocker (§5b). **Fix:** ask the agency for the dropped
  field as a separate CSV, or a `working_network_fields.csv` mapping full→truncated names.

---

## 8. Allowed-use vs toll — access is not cost

- **Symptom:** SOVs routed on HOV-only lanes, or trucks on prohibited links; or a managed
  lane treated as closed when it's actually just tolled.
- **Cause:** conflating an **access restriction** (route feasibility) with a **toll**
  (a generalized-cost penalty). They are different fields.
- **Correct convention:** `allowed_use` = which classes may use the link (HOV-only,
  truck-only); `toll_<mode>` → `mode_AdditionalCost = toll/VOT×60` = cost penalty, link
  still open. Getting the toll penalty needs the **VOT** (find it, don't assume — SCAG's
  CT-RAMP list carries per-trip `valueOfTime`; per-class means SOV $20.9/HOV2 $18.5/
  HOV3 $11.6).
- **Seen in:** **ARC** `PROHIBIT` code (0=GP, 2/11=HOV2/3+, 4/10=truck-only,
  3/7-9/12-13=tolled managed) — HOV codes → `allowed_use`, tolled codes → `toll_*`.

---

## 9. Reference / count basis — validating against the wrong thing

- **Symptom:** "validated" against a field that isn't an observed volume, or a scenario/
  period that doesn't match the run.
- **Causes & fixes:**
  - **A code, not a count.** SCAG's `AB_OBSERVE`/`BA_OBSERVE` is a small-integer flag
    (median 1, max 178), **not** an observed volume — do not regress against it.
  - **Scenario mismatch.** Comparing a **2050 Plan** assignment to a **2050 Baseline**
    loaded network mixes scenarios. Match the scenario.
  - **Period mismatch.** See §2b — use the reference's period-specific fields
    (`VMT_LM_AM`, `AB_TIME_AM`) when judging a single-period run.
  - **Undeclared count field.** Intake flags `MISSING count_field`; a run is not
    "validated" without an observed/reference volume. Declare `count_field`.
- **Judge overall loading with VMT/VHT/speed, not just β/R².** β can be ~1 (right volumes)
  while VHT is 48% of reference (speeds too high) — which immediately fingers the capacity
  or PLF convention. Region VMT within **±5%** of the reference is the gate (MAG audit ran
  −6.9%, just outside).

---

## 10. Build & environment (not a data error, but it wastes days)

- **Symptom:** the kernel **segfaults at runtime** on a network that another build runs fine.
- **Cause:** a from-scratch `g++` build (e.g. ucrt-posix target) mis-compiles the
  single-file kernel.
- **Fix:** build via the project's toolchain — `cmake --build cmake_build_rel --target
  DTALite_exe` (MinGW `x86_64-w64-mingw32-g++ -O2`). Windows consoles are cp1252 — keep
  console/log output ASCII.

---

## Master table

| # | Category | Scale | Symptom | Root cause | Fix |
|---|---|---|---|---|---|
| 1a | Capacity basis | Critical | V/C 2–4× low, speeds too high, VHT low | total written to per-lane field | `capacity = total/lanes` |
| 1b | Capacity period | Critical | V/C ≈0.007 or ≫1 | daily used as hourly | declare `capacity_period` + column |
| 2a | Flat PLF | Mod (NT 2.5×) | peak under-stated | `vdf_plf=1` on a peaked period | `φ=L·PLF`, real PLF |
| 2b | Period vs daily ref | High (looks like 5× bias) | slope ≪1, high R² | AM assigned vs daily ref | compare like-to-like |
| 3a | Length unit | Critical | distance cost ×1609 | metres labeled miles | emit `vdf_length_mi`, declare |
| 3b | Speed unit | Mod (1.6×) | fftt ×1.6 | km/h labeled mph | emit `vdf_free_speed_mph` |
| 4a | Person vs vehicle | High | over-loaded by occupancy | persons as vehicles | declare kind + occupancy/class |
| 4c | Demand truncation | Critical | ~85% origins dropped | Excel 1,048,575-row cap | untruncated / streamed source |
| 5a | Centroid id ≠ zone id | Critical | OD unmapped | ids not renumbered | node_id == zone_id for centroids |
| 5b | Multi-tier TAZ | Critical | demand unmapped | matrix TAZ ≠ network TAZ | correspondence + spatial join |
| 5c | Link ordering | High | adjacency corrupted | not sorted by from_node | sort by `from_node_id` |
| 6 | VDF defaults | Mod–High | wrong congestion shape | 0.15/4 vs agency table | per-facility α/β + form + BFW |
| 7b | DBF truncation | Critical | key field absent | 255-field / 10-char cap | request dropped field as CSV |
| 8 | allowed_use vs toll | High | SOV on HOV / wrong cost | access confused with toll | separate fields; find VOT |
| 9 | Wrong count field | Mod | can't validate | code-not-count / wrong scenario/period | declare + match `count_field` |
| 10 | Build | Blocking | runtime segfault | wrong g++ toolchain | cmake/ninja MinGW build |

---

## The order to check (when a run looks wrong)

1. **units** (length, speed) — cheapest, catches 1609× and 1.6×
2. **period & PLF** — is `H` right, is PLF flat, is the reference the same period?
3. **capacity** — per-lane? hourly? sane per-lane values by facility?
4. **demand** — vehicles vs persons, class split, not truncated?
5. **zone mapping** — centroid ids, matrix labels, link sort
6. **VDF** — agency curve, converged (BFW for stiff)
7. **allowed-use / toll** — access vs cost, VOT
8. **then** the count/reference basis — and only then suspect demand or the solver

**See also:** [MPO_ONBOARDING_GUIDE.md](MPO_ONBOARDING_GUIDE.md) (the declare→convert→intake→
resolve→validate process), [GOLDEN_PATH_CHECKLIST.md](GOLDEN_PATH_CHECKLIST.md) (the three
gates), [peak_load_factor.md](peak_load_factor.md) (φ = L·PLF), and
[USER_GUIDE_VOL2_MPO.md](../USER_GUIDE_VOL2_MPO.md) (kernel mechanics + VDF library).
