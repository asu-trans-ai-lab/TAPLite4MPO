# ARC Atlanta — complete end-to-end MPO assignment example

This is the **flagship worked example**: reproducing an MPO's (the Atlanta Regional
Commission) static **AM highway assignment** with TAPLite4MPO, and **validating it
against ARC's own traffic-count benchmark** — region-wide %RMSE **23 %** (ARC target
~38 %), every volume group passing, assigned/observed total ≈ 1.00.

It shows the full chain an MPO run needs: per-facility VDF, hourly-capacity + peak-load-
factor period convention, generalized cost (VOT + operating cost + toll), managed-lane
restrictions, equilibrium convergence, and validation.

---

## 0. Read first — the ARC model documentation

Before running, read ARC's published Travel Demand Model documentation,
**[Section 7 — Trip Assignment](https://atlregional.github.io/ARC_Model/TripAssignment.html)**
(Atlanta Regional Commission). It defines the methodology this example reproduces:
bi-conjugate Frank–Wolfe, relative gap `< 1e-4` for 3 successive iterations, the
modified-BPR VDF, the generalized cost `time·VOT + toll + distance·op_cost` (passenger
VOT $21.50, truck $36.00), and the validation targets.

- ARC Travel Demand Model docs (Section 7 — Trip Assignment):
  <https://atlregional.github.io/ARC_Model/TripAssignment.html>
- ARC Transportation Assessment (The Atlanta Region's Plan):
  <https://documents.atlantaregional.com/The-Atlanta-Region-s-Plan/Transportation_Assessment.pdf>

- A faithful extraction of those requirements (with the FACTYPE/ATYPE tables and the
  exact kernel mapping) is in **[`ARC_DTALite_kernel_requirements.md`](ARC_DTALite_kernel_requirements.md)**.
- The cross-agency design rationale and the requirement→kernel conformance mapping are in
  **[`../../docs/mpo_spec/`](../../docs/mpo_spec/)** (unified spec + conformance matrix +
  per-agency reference values, covering ARC, SERPM, TRPA, MTC, SANDAG, MWCOG, VDOT, ODOT).
- The benchmark findings (guideline-table checks, the AMCAPACITY-is-hourly correction, the
  peak-load-factor derivation, the validation result) are in
  **[`ARC_BENCHMARK.md`](ARC_BENCHMARK.md)**.

---

## 1. ARC requirement → TAPLite4MPO mapping

| ARC requirement (Section 7) | TAPLite4MPO mechanism |
|---|---|
| Modified BPR `t0(1 + A·x + α·x^β)`, per-FACTYPE A/D/B | `vdf_type=0` + `vdf_A`, per-link `vdf_alpha/beta` |
| Hourly LOS-E capacity by FACTYPE×ATYPE | per-lane `capacity = AMCAPACITY/lanes` (hourly) |
| AM period factor φ=3.66 over a 4-h window | **`vdf_plf = φ/L = 3.66/4 = 0.915`**, `demand_period 6→10` |
| `cost = time·VOT + toll + distance·op_cost` | mode `vot`, `operating_cost`; link `toll_<mode>` |
| Passenger VOT $21.50 / truck $36.00 | mode_type `vot` |
| PROHIBIT → HOV/truck restrictions; tolls = cost | `allowed_use` + `toll_<mode>` |
| Rel-gap `< 1e-4`, 3 consecutive iters; bi-conjugate FW | `convergence_gap_pct`, `convergence_consecutive=3`, `assignment_method=2` |
| Validate vs counts (%RMSE by volume group) | `ref_volume` + `arc_validate_run.py` |

This is the "clean, specific mapping" — each ARC modeling choice maps to one kernel
column or setting; nothing is hidden in the engine.

---

## 2. What's included (and what's not)

**Included** (reproduces calibrate → run → validate):
- `gmns/` — the ARC AM GMNS network: `node.csv`, `link.csv` (with `factype`,
  `ref_volume`, hourly `capacity`, `allowed_use`), per-class demand
  (`demand_sov/hov2/hov3.csv`), `settings.csv`, `mode_type.csv`.
- `arc_am_ref_volume.csv` — ARC's own assigned AM auto volume per link
  (`V_SOVAM+V_HOV2AM+V_HOV3AM`) = the validation ground truth.
- **runnable scripts** (all inputs bundled): `arc_benchmark.py`, `arc_calibrate.py`,
  `arc_validate_run.py`.
- **provenance scripts** (show how `gmns/` was built — need the *full* ARC shapefiles /
  trip cores, which are **not** bundled): `arc_atlanta_to_gmns.py`, `arc_demand_to_csv.py`.
  You don't need them; the `gmns/` network + demand are already provided. Each prints a
  clear message if you run it without the full source data.

- `arc-Shape/arc-Shape/AMLink2020.*` — a **trimmed teaching shapefile** (~26 MB): the 25
  essential attributes (A/B, FACTYPE, ATYPE, lanes, AMCAPACITY, SPEED, restrictions, tolls,
  the AM class volumes) with **null geometry**, so `arc_benchmark.py` runs in-repo (Step 3a).

**Not included (size):** the *full* ARC shapefile (~125 MB DBF, with geometry + all ~130
attributes) and the run's `link_performance.csv` (~150 MB) exceed GitHub's 100 MB limit.
The full shapefile is available from **ARC's published model**; the trimmed one above
carries everything this example needs. `link_performance.csv` is produced when you run the
kernel (Step 3b).

---

## 3. Run it

```bash
# build the kernel once (from repo root)
bash build.sh

cd examples/arc_atlanta

# (0) intake audit: ARC's declaration (gmns/submission.yml) is the MODEL hand-off.
#     This gate is READY because every convention is declared (see MPO_ONBOARDING_GUIDE).
python -m dtalite_qa intake gmns          # -> GATE: READY (0 blockers)

# (a, optional) benchmark: check the network vs ARC's guideline tables (Table 7-1/7-2)
#               and (re)extract arc_am_ref_volume.csv from the trimmed shapefile
python arc_benchmark.py

# (a) calibrate: apply per-FACTYPE VDF + vdf_A, vdf_plf=0.915, AM 6-10, VOT 21.5, op_cost
python arc_calibrate.py                 # gmns/ -> gmns_calibrated/

# (b) run to equilibrium
cp ../../bin/DTALite.exe gmns_calibrated/
( cd gmns_calibrated && ./DTALite.exe )  # converges ~iter 10 (3-consecutive-gap stop)

# (c) validate against ARC's count benchmark
python arc_validate_run.py gmns_calibrated
```

**Expected result** — region-wide %RMSE ≈ **23 %**, all volume groups pass, assigned/ref
total ≈ 1.00. (Optional: set `assignment_method=2` in `gmns_calibrated/settings.csv` for
bi-conjugate FW.)

---

## 4. Discussion — why each step matters

- **Peak load factor (the #1 pitfall).** ARC's "period factor" is the load-factor memo's
  φ, so `PLF = φ/L = 0.915` (not flat). With hourly capacity + `vdf_plf=0.915`, the
  kernel's D/C equals ARC's period V/C exactly. Leaving `vdf_plf=1` over-states AM
  capacity ~9 % (and night ~2×). See `ARC_BENCHMARK.md §3b` and `docs/peak_load_factor.md`.
- **Modified BPR.** ARC's extra linear `A·(V/C)` term (absent from standard BPR) is the
  `vdf_A` column; without it arterials are under-timed near capacity.
- **Equilibrium.** The 3-consecutive-gap stop reproduces ARC's convergence rule;
  bi-conjugate FW closes the gap faster on this stiff regional network.
- **Validation.** The uncalibrated baseline scores 88 % %RMSE (high-volume links
  over-loaded); the calibrated run scores 23 % — the calibration tables *are* what close
  the gap, not solver tuning.

---

### Acceleration (optional)
The same network demonstrates **super-zone aggregation**: `dtalite_qa/superzone_hier.py`
+ `superzone_encoders.py` build a demand-weighted super-zone version that runs ~2× faster
and **still passes ARC validation** (see `docs/superzone_design_principles.md`).
