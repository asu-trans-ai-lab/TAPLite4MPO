# DTALite + TAPLite — Design Guideline (PLF, V/C, allowed_use, toll, person/vehicle, validation)

Practical guidance for setting up and trusting a static assignment in the TAPLite kernel, focused
on the mechanics that most often go wrong. Every rule is grounded in `kernel/src/TAPLite.cpp`
(line refs) so it can be verified against the code.

---

## 0. The master V/C equation (read this first)

From `Link_Travel_Time` (TAPLite.cpp:4621, 4664) and `Link_QueueVDF` (4689-4690), **all** VDF
types use the same per-lane volume-to-capacity ratio:

```
                    Volume_pce(k)
IncomingDemand = ----------------------------------          (peak-hour, per-lane flow rate)
                 lanes · H · PLF

           IncomingDemand
V/C  =  ------------------------         (a.k.a. DOC = degree of congestion, reported as "doc")
          Lane_Capacity
```

where
- `Volume_pce(k)` = link volume over the period, **already PCE-weighted** (trucks count >1; §3),
- `lanes` = directional lanes,
- `H` = period duration in hours = `demand_period_ending_hours − demand_period_starting_hours`,
- `PLF` = `vdf_plf` (peak load factor; default 1) — §1,
- `Lane_Capacity` = **per-lane HOURLY** capacity (veh/h/lane) = `capacity` column.

Everything below is about getting each term right.

---

## 1. Peak load factor (PLF) — the thing to get right

`vdf_plf` (TAPLite.cpp:77, read :4025) appears in the denominator `lanes · H · PLF`. Its job is to
convert the **multi-hour period demand** into the **peak-hour-equivalent flow** that the hourly
capacity is defined against.

### The rule
```
H · PLF  =  "effective capacity-hours" in the period  =  agency period-to-hourly capacity factor
```
So **`vdf_plf = (agency period factor) / H`**.

### Why
Hourly capacity (e.g., 2000 veh/h/lane freeway) is a *one-hour* number. A 4-hour AM period does not
carry 4× that — peaking means the period behaves like ~3.66 capacity-hours (ARC AM factor, TripAssignment §7.1.1):
EA 1.25 · **AM 3.66** · MD 4.70 · PM 3.66 · EV 3.91. Loading the whole-period demand against the
hourly capacity requires spreading it over the *effective* hours, not the clock hours.

### ARC worked setting
- ARC `AMCAPACITY/LANES` ≈ 900 (arterial) … 2000+ (freeway) → these are **hourly** per-lane values
  (Table 7-2), so leave `capacity = AMCAPACITY/LANES`. (Verify: a freeway link should be ≈2000, not
  ≈7300; if ≈7300 the field is already period-capacity and PLF handling flips — see Pitfall below.)
- AM period 6–10 → set `demand_period_starting_hours=6, demand_period_ending_hours=10` (H=4).
- `vdf_plf = 3.66 / 4 = 0.915`.

> **Correction to our current ARC GMNS:** we used H=3 (6–9) and `vdf_plf=1` ⇒ H·PLF = 3.0, which
> **over-loads** vs ARC's 3.66 (V/C ~22% high). Fix: H=4 and `vdf_plf=0.915` (or per-period factors below).

### Per-period PLF (ARC, if capacity stays hourly)
| period | clock H | factor | vdf_plf = factor/H |
|--|--|--|--|
| EA | 3 | 1.25 | 0.417 |
| AM | 4 | 3.66 | 0.915 |
| MD | 5 | 4.70 | 0.940 |
| PM | 4 | 3.66 | 0.915 |
| EV | 8 | 3.91 | 0.489 |

### Pitfall
If a network's capacity field is **already period capacity** (hourly × factor), then set
`vdf_plf = 1` and `H` = the factor (or pre-divide). Decide once per agency and document it. The
single source of truth: `V/C must equal period_demand / period_capacity`. Check one freeway link by
hand against the agency's loaded V/C.

---

## 2. allowed_use — multiclass access

- Per-mode dedicated shortest path uses the link's `allowed_use` (TAPLite.cpp:445, 577; 14 refs).
  A mode `m` may traverse link `k` iff `mode_type[m]` token ∈ `allowed_use(k)`, or `allowed_use` is
  empty (= all modes).
- Tokens must match `mode_type.mode_type` exactly (`sov`, `hov2`, `hov3`, `trk`, …).
- Patterns: HOV-only → `hov2;hov3`; HOV3-only → `hov3`; truck-only → `trk` (closes it to autos);
  general purpose / connectors → empty.
- Set `dedicated_shortest_path=1` in `mode_type.csv` so each class respects its own access.
- **Access ≠ toll.** A managed lane that *charges* SOV is still *open* to SOV — keep `allowed_use`
  empty and price it via toll (§4). Only ban a mode when it physically cannot use the lane
  (ARC PROHIBIT 2/6/11; truck-only 4/10). Verify: a 1-iteration run must show **SOV volume = 0** on
  `hov2;hov3` links (we confirmed this).

---

## 3. Person ↔ vehicle ↔ PCE conversions (keep the three separate)

| quantity | unit | where used | kernel |
|--|--|--|--|
| **demand** | **vehicle trips** per class | input `demand_<class>.csv` | sum of vehicle-trip cores |
| **congestion loading** | **PCU (PCE-weighted)** | V/C, VDF | `Volume += RouteFlow · pce` (1411); LTT uses it (672) |
| **person metrics** | **persons** | PMT/PHT reporting | `× occ` (3704-3705) |

Rules:
- **Input demand is in vehicles**, one matrix per class (we built SOV/HOV2/HOV3 by summing the
  vehicle-trip cores — already vehicles, do **not** divide by occupancy).
- **`pce`** (mode_type) = passenger-car-equivalents per vehicle → drives V/C. Autos 1.0; ARC trucks
  MTK 1.5 / HTK 2.0; SANDAG 1.3/1.5/2.5. (We have no truck class yet, so pce=1.)
- **`occ`** (mode_type) = persons per vehicle → only for person-miles/hours reporting (PMT/PHT). It
  does **not** change routing or V/C. SOV occ=1, HOV2 occ=2, HOV3 occ≈3.3.
- If a matrix is in **person trips**, the converter must divide by occupancy *before* writing
  `demand_<class>.csv` (vehicles = persons / occ). ARC's assignment cores are already vehicles.

---

## 4. Toll & generalized cost (VOT converts money → time)

Per-mode link cost (TAPLite.cpp:4057-4060, 4816), in **minutes**:
```
cost(k,m) = Travel_time(k)  +  (mode_Toll[k,m] + op_cost[m] · length_mi) / VOT[m] · 60
```
- `mode_Toll` = toll in dollars for that mode/link; `op_cost` = $/mile (mode_type `operating_cost`,
  default 0); `VOT` = `mode_type.vot` in **$/hour**. So money is converted to equivalent minutes by
  `/VOT·60`. (This is algebraically equivalent to ARC's "time·VOT + toll + dist·opcost".)
- Set per class: ARC auto VOT $21.50, truck $36, op_cost $0.1729/mi (auto), $0.5360 (truck);
  SERPM $15 peak/$12 off-peak, no op_cost; TRPA/ODOT time-only (toll=op_cost=0).
- **Toll input**: agency toll codes (ARC TOLLID→TOLLS{yr}.DBF rate in cents, distance-based when
  FIXED=0; SANDAG TOLL{period} cents/mile) → converter computes `mode_Toll` $ per link per class
  (only for toll-eligible classes). Non-toll-eligible classes get a separate demand file and may be
  barred from priced lanes or simply see the toll.
- **Toll-eligibility split**: model as separate classes (ARC SOV_NT vs SOV_TR, SANDAG `_NT`/`_TR`),
  not a binary choice inside assignment. Non-toll class either can't pay (give it a prohibitive toll
  or restrict) or just routes on the toll-free network.

---

## 5. V/C handling & reporting

- V/C (=DOC) is **per-lane** for every VDF type (BPR/conical/QVDF) — a prior bug that used total
  link capacity (understating D/C by #lanes) is fixed (TAPLite.cpp:4659-4663). So always provide a
  correct **per-lane** `capacity`.
- Reported in `link_performance.csv` as `doc` = `MainVolume / Link_Capacity` for the headline column
  (total-capacity basis, 3494/3599) **and** the VDF uses the per-lane `IncomingDemand/Lane_Capacity`
  internally — be aware the headline `doc` and the VDF's internal V/C differ by the H·PLF and lane
  normalization. For congestion interpretation use the VDF V/C (peak-hour, per-lane).
- Sustained V/C > ~1 with high `vdf_beta` (ARC freeway β=6) makes travel time explode — this is
  intended (the S-curve, §7). Check that capacity, lanes, H, and PLF are all right before trusting
  a V/C > 1.5.

---

## 6. Validation (how to trust the result)

- `ref_volume` (TAPLite.cpp:9 refs) = the agency's loaded link volume target. We set it to ARC's
  `V_SOVAM+V_HOV2AM+V_HOV3AM` (auto, matches our demand).
- Outputs already present: link `volume`, per-class `mod_vol_*`, `ref_volume`, VMT, VHT, speed, doc.
- Targets (VDOT, most concrete): R² 0.90 (large)/0.92 (small); %RMSE by volume group (<5k 100% …
  >60k 19%) and facility type (freeway 20%, principal 35%, minor 45%); VMT by FC ±7–25%; screenline
  ±5–10%; speed deviation > 5 mph flagged. ARC region %RMSE ~38%, V/C ~0.91.
- Procedure: (1) 1-iteration run → connectivity + allowed_use inventory (0 inaccessible OD, SOV=0 on
  HOV-only). (2) Converged run (gap 1e-4 ×3) → compare `volume` vs `ref_volume`: R², %RMSE by volume
  group/FT, VMT by FC, screenlines. (3) Adjust capacity/PLF/VDF, not demand, to close gaps.

---

## 7. The S-curve (speed–flow / VDF shape)

See the rendered chart (`vdf_speed_scurve`). Two views of the same physics:
- **VDF (travel-time ratio Tc/T0 vs V/C)** — convex/J-shaped; ARC freeway (β=6) is nearly flat to
  V/C≈0.8 then rises steeply. The linear `A·x` term lifts it slightly at low V/C.
- **Speed vs V/C** — the **S-curve**: ~free-flow until V/C≈0.75 (cutoff), a steep drop through
  capacity (V/C=1), then a low congested branch. QVDF reproduces the S explicitly via the queue
  speed model (cutoff_speed, Q_cd/Q_n) — TAPLite.cpp:4646-4655. BPR's speed = free_speed/(1+A·x+α·x^β)
  is a smooth approximation of the same S.

Use the S-curve to sanity-check coefficients: the knee should sit near V/C≈0.8–1.0 and the congested
branch should not collapse to absurd speeds at moderate V/C (a sign of β too high or capacity too low).

---

## 8. Settings cheat-sheet (per agency, AM example)

| setting | ARC | SERPM | TRPA |
|--|--|--|--|
| capacity (link.csv) | AMCAPACITY/LANES (hourly per-lane) | FTC2×lanes lookup | per-FC (1100/800/500) |
| demand_period hours | 6–10 (H=4) | period | 7–10 |
| vdf_plf | 0.915 (=3.66/4) | period factor/H | per coding |
| vdf_type / coeffs | 0 + vdf_A by facility | 0 (modified BPR) | 0, α/β table |
| mode_type vot / pce / occ | 21.5(auto)/36(trk); pce 1/1.5/2; occ 1/2/3.3 | 15/12; — ; — | — |
| convergence_gap_pct / consecutive | 0.0001 / 3 | 0.0001 / 3 | (MSA n/a) |

---

## 9. Quick checklist before trusting a run
1. capacity is **per-lane hourly** (verify a freeway link ≈ 1900–2100).
2. `H · vdf_plf` = the agency period factor (ARC AM 3.66).
3. demand is **vehicles**; pce set for trucks; occ only affects PMT/PHT.
4. allowed_use: SOV=0 on HOV-only (1-iter check); toll lanes left open + priced.
5. vot/op_cost/toll set per class (money→minutes via /vot·60).
6. gap 1e-4 for 3 consecutive iters.
7. compare `volume` vs `ref_volume` (R², %RMSE by group/FT); fix supply, not demand.
