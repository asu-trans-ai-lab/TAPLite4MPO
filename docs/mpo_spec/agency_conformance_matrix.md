# Agency requirements -> DTALite/TAPLite conformance matrix

How the DTALite/TAPLite kernel satisfies each MPO/DOT assignment requirement, and **how to verify
it**. Grounded in `kernel/src/TAPLite.cpp`, `schemas/gmns_dtalite_schema.json`, and the agency docs
in `agency_docs/`. See `DTALite_unified_traffic_assignment_spec.md` for the full spec and
`MPO_assignment_kernel_references.md` for sourced agency values.

Status: ✅ implemented · 🟡 staged/partial/convention-dependent · 🔴 extension needed ·
🟦 handled in agency->GMNS converter (data, not kernel).

---

## A. Cross-agency requirement matrix (what each model requires)

| Requirement | ARC | SERPM8 | TRPA | MTC | SANDAG | MWCOG | VDOT | ODOT |
|--|--|--|--|--|--|--|--|--|
| Equilibrium | UE | UE | MSA cap-restraint | UE | UE (SOLA) | UE | UE | UE/cap-restr |
| Solver | bi-conj FW | FW | MSA | (Cube) | SOLA | bi-conj FW | bi-conj FW (rec) | Visum |
| Rel-gap target | 1e-4 ×3 | 1e-4 ×3 | 1e-4 avg Δvol | n/s | 5e-4 | 1e-2→1e-4 | 1e-4 (rec) | n/s |
| VDF | mod-BPR+linear | mod-BPR | BPR | BPR(4/3) | BPR+int.delay | conical | BPR/conical/Akcelik | BPR |
| TOD periods | 5 | 5 | 4 | 5 | 5 | 4 | ≤4 | daily+PM |
| User classes | 10 | 8 | 2 | 10 | 15 | 6 | — | 1 |
| Generalized cost | t·VOT+toll+dist | t+toll | t | toll-classes | t·VOT+toll+op | t+cost | — | t |
| VOT | $21.5/$36 | $15/$12 | n/s | n/s | income $/min | min/$ | — | n/s |
| PCE | MTK1.5/HTK2.0 | n/s | n/s | n/s | 1.3/1.5/2.5 | n/s | — | n/s |
| Managed/HOV | PROHIBIT | yes | n/s | USE/FT8 | HOV+TOLL | yes | — | n/s |
| Validation R² | — | — | corr≥0.88 | — | — | — | 0.90/0.92 | ≥0.9 |

(n/s = not stated in fetched docs; see gaps in references doc.)

---

## B. Conformance: requirement -> DTALite status -> verification

### B1. Network coding
| # | Requirement | Required by | Status | Evidence | How to verify |
|--|--|--|--|--|--|
|N1| Directed links, sorted by from_node_id | all | ✅ | CSR build | `arc_atlanta_to_gmns.py` sorts; run -> no "NOT sorted" warning |
|N2| Centroid node_id==zone_id | all (DTALite hard req) | ✅ | loader check | run -> no "zone_id should be the same" error |
|N3| Per-lane capacity (period cap/lanes) | all | ✅ | link.csv `capacity` | inspect capacity≈900–2150; product lanes·cap = directional cap |
|N4| Facility×area-type capacity & speed lookups | all | 🟦 | converter | precomputed into link.csv (SPEED/AMCAPACITY) |
|N5| Period lanes/capacity factors (AM 3.66 etc.) | ARC,MWCOG | 🟦 | converter | AMCAPACITY already = period cap |
|N6| Weave capacity 0.98^(lanes-1) | ARC | 🟦 | converter | apply when WEAVEFLAG=1 & lanes>4 |

### B2. Volume-delay functions
| # | Requirement | Required by | Status | Evidence | How to verify |
|--|--|--|--|--|--|
|V1| Standard BPR | TRPA,ODOT,VDOT,MTC | ✅ | TAPLite.cpp BPR | set vdf_alpha/beta; Tc=t0(1+α·x^β) on test link |
|V2| Modified BPR + **linear term** | ARC | ✅ | `VDF_A` TAPLite.cpp:74, read :4024 | set vdf_A>0; Tc=t0(1+A·x+α·x^β) |
|V3| QVDF | DTALite-native | ✅ | QVDF code (:2333) | vdf_type=2 + cp/cd/n/s |
|V4| Conical (Spiess) | MWCOG,VDOT | 🟡 | `Conic_a/b` :79-80 (staged) | **finish**, wire vdf_type=1, test vs formula |
|V5| MTC 4/3-shift BPR | MTC | ✅/🟦 | α=0.20,β=6 + 4/3 prescale | converter pre-scales x, or kernel flag |
|V6| BPR2 / INRETS / Akcelik | AequilibraE/VDOT-opt | 🔴 | absent | **add** VDF types 3/4/5 + derivatives |
|V7| Per-facility VDF coefficients | ARC,TRPA,SANDAG,MTC | ✅/🟦 | per-link vdf_alpha/beta/A | converter writes from lookup tables |
|V8| Differentiable VDF for CFW/BFW | (solver) | 🔴 | n/a (no BFW) | provide dt/dv with V6 |

### B3. Solver & convergence
| # | Requirement | Required by | Status | Evidence | How to verify |
|--|--|--|--|--|--|
|S1| Static UE, Frank-Wolfe | most | ✅ | FW+Armijo :1565-1907 | run, gap decreases monotonically |
|S2| Relative-gap stop, **N consecutive iters** | ARC,SERPM | ✅ | `convergence_gap_pct`,`convergence_consecutive` :315-319,3542 | settings 1e-4/3 -> stops after 3 sub-gap iters |
|S3| Bi-conjugate FW | ARC,MWCOG,VDOT | ✅ | `assignment_method` 0/1/2 (FW/CFW/BFW), cost-deriv Hessian + convex auxiliaries | set =2; CR iter-24 gap FW 1.43%->BFW 0.59%, same UE (R² 0.999) |
|S4| Progressive gap across feedback | MWCOG | 🔴 | single target | **add** per-feedback gap schedule |
|S5| Standard rel-gap definition | all | 🟡 | confirm formula | compare kernel gap to (ΣVC−ΣV^AoN·C)/ΣVC |

### B4. Generalized cost & multiclass
| # | Requirement | Required by | Status | Evidence | How to verify |
|--|--|--|--|--|--|
|C1| Per-mode toll / additional cost | ARC,SANDAG,MTC,MWCOG | ✅ | `mode_AdditionalCost` :445,577 | set per-mode toll; path avoids/uses by cost |
|C2| Distance operating cost | ARC,SANDAG | ✅ | `op_cost` :230 | set op_cost; longer paths cost more |
|C3| Per-class PCE | ARC,SANDAG | ✅ | `pce` :1411,3208 | truck pce=2 -> doubles v/c contribution |
|C4| Occupancy (person metrics) | all | ✅ | `occ` :3704 | PMT/PHT in link_performance |
|C5| Per-class VOT in generalized cost | ARC,SERPM,SANDAG | ✅ | `/vot*60` money→time (TAPLite.cpp:4816,4057-4060) | set mode vot; toll/op_cost convert to minutes |
|C6| Toll-eligible class split (NT/TR) | ARC,SANDAG,MTC | 🟦 | separate demand classes | converter emits demand_sov_nt/_tr |
|C7| Per-mode allowed_use, dedicated paths | ARC,SANDAG,MTC | ✅ | allowed_use :14 refs | 1-iter: SOV vol=0 on hov-only (verified) |

### B5. Time-of-day & restrictions
| # | Requirement | Required by | Status | Evidence | How to verify |
|--|--|--|--|--|--|
|T1| Per-period assignment (4–5 TOD) | all | 🟦 | settings periods | run EA/AM/MD/PM/EV folders |
|T2| Managed-lane/HOV access from coding | ARC,SANDAG,MTC | 🟦/✅ | PROHIBIT/HOV->allowed_use | converter map (ARC done) |

### B6. Validation & I/O
| # | Requirement | Required by | Status | Evidence | How to verify |
|--|--|--|--|--|--|
|O1| ref_volume target on links | all | ✅ | `ref_volume` :9 | set; compare in link_performance |
|O2| link volume/speed/VMT/VHT/vc outputs | all | ✅ | link_performance.csv | columns present |
|O3| R² / %RMSE by volume group & FT | VDOT,ODOT,ARC | 🔴 | no plugin | **add** validation plugin |
|O4| VMT by functional class | VDOT,ARC | 🔴 | manual now | **add** to validation plugin |
|O5| Screenline/cutline ratios | VDOT | 🔴 | none | **add** screenline aggregation |
|O6| ODME | (ARC binary) | 🔴 (TAPLite) | settings odme_mode | present in DTALite.exe, not TAPLite.cpp |

---

## C. Summary — how we ensure conformance

1. **Converter responsibility (🟦):** each `agency2gmns` precomputes facility×area-type capacity,
   free-flow speed, per-facility VDF coefficients (α/β/A), period capacities, lanes, and maps
   restrictions (PROHIBIT/HOV/managed) into GMNS `allowed_use` + toll. Verified by re-deriving
   agency loaded volumes (`ref_volume`).
2. **Kernel core already conformant (✅):** modified-BPR+linear, QVDF, multiclass PCE/occ, per-mode
   toll + distance op-cost, allowed_use dedicated paths, relative-gap×N-consecutive stop.
3. **Extensions to reach full multi-agency conformance (🔴/🟡):** explicit per-class VOT (C5),
   finish conical (V4), add BPR2/INRETS/Akcelik (V6), bi-conjugate FW (S3), progressive gap (S4),
   validation plugin (O3–O5), ODME in TAPLite (O6).
4. **Verification harness:** the `How to verify` column is the test checklist — each row is a
   unit/integration check on a small network (e.g., `test_networks/`) plus the agency
   1-iteration inventory (connectivity + allowed_use) and N-iteration calibration-vs-ref_volume run.

See `agency_conformance_matrix.csv` for the machine-readable checklist.
