# ARC benchmark & guideline checks

Built by `arc_benchmark.py` from the authoritative ARC link database
`arc-Shape/arc-Shape/AMLink2020.dbf` (150,255 records; 118,893 auto links,
FACTYPE 0-14) + the converted `gmns/` network. Validates the conversion against
the Section-7 guideline tables and extracts the reference-volume benchmark.

## 1. Guideline compliance (data vs Section-7 tables)
- **Free-flow SPEED vs Table 7-1 (FACTYPE x ATYPE): 64/69 cells within 2 mph.**
  The shapefile `SPEED` field follows the lookup (a few interstate cells read 70 vs
  62-66 where NPMRDS observed speeds were substituted, as the spec allows).
- **Hourly per-lane CAPACITY vs Table 7-2: 11/11 FACTYPEs match** (interstate
  1900-2100, expressway 1300-1450, collector 750-900, ...).

## 2. KEY FINDING — `AMCAPACITY` is HOURLY, not period
`AMCAPACITY/lanes` ~= Table 7-2 hourly LOS-E (interstate ~1900/lane), so
**`AMCAPACITY` is the hourly directional capacity**, NOT the period capacity.
The requirements note "(AMCAPACITY already = period cap)" is **wrong**. For
assignment: kernel per-lane `capacity = AMCAPACITY/lanes` (hourly) with the
period handled via `vdf_plf`/period-hours, OR period cap = `AMCAPACITY * 3.66`
(AM period factor). [Correct the GMNS conversion accordingly.]

## 3. VDF table for the new `vdf_A` feature (Section 7.1.2, by FACTYPE)
`Tc = T0*(1 + A*(V/C) + D*(V/C)^B)` -> kernel `vdf_A=A, vdf_alpha=D, vdf_beta=B`:

| FACTYPE | vdf_A | vdf_alpha | vdf_beta |
|---|--:|--:|--:|
| 1,4,5,6 freeway | 0.10 | 0.60 | 6.0 |
| 2 expressway | 0.00 | 1.00 | 4.0 |
| 3 parkway | 0.00 | 1.25 | 4.0 |
| 7,8,9 ramp | 0.10 | 1.00 | 4.0 |
| 10-14 arterial/collector | 0.10 | 0.45 | 4.0 |
| weave (WEAVEFLAG) | 0.20 | 1.25 | 5.5 |

The current GMNS uses a **flat 0.15/4** -> must be replaced by this per-FACTYPE
table (and set `vdf_A`). `arc_am_ref_volume.csv` carries `weaveflag` for the weave rows.

## 3b. PEAK LOAD FACTOR — ARC's period factor IS the memo's phi
ARC's "period factor" (Sec 1.7) is exactly the hour->period capacity expansion
`phi` from the load-factor memo: `phi = L * PLF`, so **PLF = phi / L**:

| period | window | L | phi | PLF = phi/L |
|---|---|--:|--:|--:|
| EA | 03-06 | 3 | 1.25 | 0.417 |
| AM | 06-10 | 4 | 3.66 | **0.915** |
| MD | 10-15 | 5 | 4.70 | 0.940 |
| PM | 15-19 | 4 | 3.66 | 0.915 |
| EV | 19-03 | 8 | 3.91 | 0.489 |

All pass the memo bounds (0<PLF<=1, phi>=1); profile mirrors MAG (daytime ~0.9-0.94,
off-peak ~0.4-0.5). **AM PLF = 0.915, NOT flat.** In `plf.py`: `ARC_PHI`,
`ARC_PERIOD_HOURS`, `arc_plf(period)`.

Kernel mapping (memo-correct, with AMCAPACITY=hourly from sec 2):
`capacity = AMCAPACITY/lanes` (hourly per-lane) · `vdf_plf = phi/L` (AM 0.915) ·
`demand_period = window` (AM 6-10, H=4) -> `DOC = V/(3.66*AMCAP) = V/period_cap`.

**Current GMNS gets PLF wrong twice:** uses H=6-9 (should be 6-10) AND no vdf_plf
(flat PLF=1). Flat over-states AM period cap by 4/3.66=1.09x (~9% under-congestion);
EV by 8/3.91=2.05x (severe). Fix: set vdf_plf=phi/L and the correct period hours.

## 4. Reference-volume benchmark
`arc_am_ref_volume.csv` (118,893 links): `from_node_id,to_node_id,factype,atype,
ref_auto_vol (=V_SOVAM+V_HOV2AM+V_HOV3AM), ref_total_vol (=V_TOTAM), weaveflag`.
This is ARC's own AM assigned volume = the calibration ground truth.

## 5. Validation framework (assigned vs reference, Section 7.1.4 targets)
%RMSE by volume group vs ARC thresholds (<2.5k:100% · 5-10k:45% · 10-25k:30% ·
25-50k:25% · >=50k:19%). Region-wide target ~38%.

**Uncalibrated baseline** (the bundled 1-iter run, flat VDF, VOT=15, no period cap):
- 0-2.5k 56%(PASS) · 2.5-5k 51%(PASS) · 5-10k 37%(PASS) · 10-25k 47%(FAIL) ·
  25-50k 63%(FAIL). Region-wide 88%; **assigned/ref total = 1.01** (aggregate VMT
  is right, but high-volume links are over-loaded).
- Diagnosis: 1-iteration all-or-nothing (no equilibration) + flat VDF pile flow on
  shortest paths. Closing the gap needs: (a) the per-FACTYPE VDF table + `vdf_A`,
  (b) hourly cap x3.66 period convention, (c) VOT 21.50 (+ op_cost), (d) multiple
  FW iterations to equilibrium (+ the 3-consecutive-gap stop). All now available.

## 6. CALIBRATED RUN — validation PASSED
`arc_calibrate.py` applies the benchmark tables to `gmns/` -> `gmns_calibrated/`:
per-FACTYPE VDF + `vdf_A` (replaces flat 0.15/4), `vdf_plf = phi/L = 0.915`, AM
window 6-10 (H=4), VOT $21.50 + `operating_cost` 0.1729. Run converged via the
3-consecutive-gap stop at **iter 10 (gap 0.24% < 0.5% x3)**, 7 min, 3 modes.

`arc_validate_run.py gmns_calibrated` vs the ARC reference (118,687 non-connector links):

| volume group | baseline %RMSE | calibrated %RMSE | ARC target | pass |
|---|--:|--:|--:|:--:|
| 0-2.5k | 56 | **22** | 100 | Y |
| 2.5-5k | 51 | **14** | 55 | Y |
| 5-10k | 37 | **11** | 45 | Y |
| 10-25k | 47 | **12** | 30 | Y |
| 25-50k | 63 | **14** | 25 | Y |
| region-wide | 88 | **23** | ~38 | Y |

**All groups pass; region-wide 23% beats the ~38% target; assigned/ref total = 1.00;**
per-group ratios 0.97-1.13. Validates every kernel change end-to-end on a real MPO
network against the agency's own benchmark.

## Reproduce
```
cd private/ARC_Atlanta
python arc_benchmark.py                       # checks + writes arc_am_ref_volume.csv
python arc_calibrate.py                       # gmns/ -> gmns_calibrated/ (apply tables)
(cd gmns_calibrated && ./DTALite.exe)         # equilibrium AM assignment
python arc_validate_run.py gmns_calibrated    # score vs ARC reference
```
