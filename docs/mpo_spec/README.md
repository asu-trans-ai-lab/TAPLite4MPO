# MPO assignment — design spec & multi-agency survey

The design rationale behind TAPLite4MPO and a survey of how eight MPO/DOT static-highway-
assignment models map onto one GMNS engine. Read these alongside
**[USER_GUIDE_VOL2_MPO.md](../../USER_GUIDE_VOL2_MPO.md)** (the how-to) and the worked
**[ARC example](../../examples/arc_atlanta/)**.

| file | what it is |
|---|---|
| `DTALite_unified_traffic_assignment_spec.md` | the unified spec: one GMNS engine that satisfies ARC, SERPM 8, TRPA, MTC, SANDAG, MWCOG, VDOT, ODOT — with the exact kernel mapping and status for each requirement |
| `agency_conformance_matrix.md` (+ `.csv`) | requirement → kernel feature → **how to verify**, per agency (the clean, specific mapping) |
| `MPO_assignment_kernel_references.md` | sourced per-agency values: VDF coefficients, capacities, VOT, PCE, gap targets, periods |
| `DTALite_TAPLite_design_guideline.md` | kernel design principles and the GMNS data-model rationale |

Coverage at a glance: equilibrium (UE / FW / conjugate / bi-conjugate FW), the VDF library
(BPR, modified-BPR, conical, QVDF, BPR2, INRETS, Akcelik, SANDAG signal), generalized cost
(VOT + toll + operating cost), multiclass PCE/occupancy, managed-lane `allowed_use`,
period capacity + peak-load-factor, convergence, and validation targets.
