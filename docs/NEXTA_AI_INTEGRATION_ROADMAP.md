# TAPLite4MPO × NeXTA-AI — integration roadmap

**Goal:** close the loop for MPOs — *assignment result → dashboard → adjust → re-run* —
so an agency can creatively use assignment results through scenario management,
version control, and (most importantly) **automatic parameter configuration and
calibration**, with the AI layer driving the iteration instead of a modeler
hand-editing CSVs.

```
   agency data ──▶ intake (declare, audit) ──▶ TAPLite kernel (Dijkstra engine)
                                                       │
        ┌── scenario manager (configs, versions) ◀─────┤ manifest.json per run
        │                                              ▼
   NeXTA / dashboards ◀── MOE + validation ◀── link_performance / skims
        │                                              │
        └────────── AI calibration loop (CG gradients) ┘
```

---

## 1. What already exists (the assets to connect)

| Asset | Where | What it gives the loop |
|---|---|---|
| **TAPLite kernel** | `kernel/src/TAPLite.cpp` | the solver: Dijkstra SP engine (default), VDF library (types 0–8 incl. agency-calibrated forms), FW/CFW/BFW, compact/binary outputs — see `KERNEL_FEATURE_CHANGES.md` |
| **dtalite_qa** | `dtalite_qa/` | declare→convert→intake→resolve→validate control; R1–R6 traceable workflow; PLF tooling; super-zone builders; skim recovery |
| **Conversion-error catalog** | `docs/CONVERSION_ERRORS_CATALOG.md` | the Gate-2 knowledge base the AI layer must enforce before any calibration |
| **TAP-line Scenario Manager** | `ADOT_AI_Scenario_Manager/` (sister repo) | JSON-manifest CLI contract (`run_tapline.py`), **4-layer adaptation pipeline** (`adapt_pipeline.py`: default BPR → +PLF → agency-calibrated → conic, MOE per FT×AT×period×mode), scenario staging, 1,200-line CHANGELOG discipline, per-network acceptance tests |
| **CompressedTAP CG kernel** | `ADOT_AI_Scenario_Manager/CompressedTAP-feature-core` | **the computational-graph foundation**: compressed traffic assignment with augmented Lagrangian; explicit gradients `∇_y L_c`, `∇_z L_c` via chain rule on `v = v₀ + B₁'y + Dz` — i.e., a *differentiable* assignment |
| **Super-zone encoder–decoder** | `docs/od_compression_operators.tex`, `superzone_design_principles.md` | the compression operators (encoder Qᵀ, decoder U) that make large-region calibration tractable |
| **NeXTA** | `Nexta_source_code` | the GUI front-end; GMNS in/out already compatible |

The pieces exist. What's missing is the **contract between them** — that is this roadmap.

---

## 2. Milestones

### M1 — Run manifest & scenario management (the contract)
Every kernel run emits a `manifest.json`: input file hashes, full effective settings
(after defaults), kernel version + feature flags, convergence trace (gap per iteration),
runtime, and MOE summary (VMT/VHT/speed by facility; β/R² vs the declared count field).
- A *scenario* = GMNS folder + `submission.yml` + `manifest.json` history.
- Scenario diff = diff of two manifests → "what changed and what it did to the MOEs."
- This generalizes the TAP-line `run_tapline.py` JSON contract to the TAPLite4MPO kernel.

### M2 — Version control & stability gates
- `docs/KERNEL_FEATURE_CHANGES.md` is the running feature list (every settings key,
  default, status); the TAP-line CHANGELOG discipline (date + files + rationale +
  verification) applies to every kernel change.
- **Gate:** `test_networks/run_regression.py` (13 networks, 30 checks) must pass on every
  kernel change; agency scenarios (ARC calibrated, SCAG super-zone) are the second ring.
- Baselines are versioned; a change that shifts a baseline must say why (e.g. the
  Dijkstra tie-breaking re-baseline).

### M3 — Result dashboards for MPOs (NeXTA-facing)
Extend the intake/workflow dashboards to **assignment-result dashboards**: per-run HTML
with the validation scatter (y = βx by facility), VMT/VHT vs reference, congestion/speed
maps, convergence trace — auto-generated from `manifest.json` + `link_performance.csv`,
viewable standalone or inside NeXTA. The MPO's "fit to their needs" loop starts by
*seeing* the result the same way every run.

### M4 — Automatic parameter configuration (search-based, near-term)
Generalize `adapt_pipeline.py`'s layer ladder into an **auto-configurator**:
given reference volumes, stage and run the candidate ladder (default BPR → +PLF →
agency table → conic/piecewise), score MOE per facility × area type × period × mode, and
**select the winning configuration per segment** — producing a `submission.yml` +
`link.csv` VDF patch automatically. This is derivative-free (grid/ladder search), robust,
and works today with the existing kernel.

### M5 — Gradient calibration via the computational graph (the destination)
Treat the assignment as a differentiable map **v(θ)** where θ = {vdf_alpha/beta per
facility class, capacity factors, PLF, OD scaling / compressed OD coordinates}:
- The CompressedTAP augmented-Lagrangian machinery already computes exact gradients
  through the flow map (`∇f` via the chain rule on `v = v₀ + B₁'y + Dz`).
- Calibration = minimize `Σ_links w·(v(θ) − v_obs)²` by gradient descent on θ — replacing
  manual VDF tuning entirely.
- The super-zone **encoder–decoder compression** keeps the design space small: calibrate
  in compressed coordinates (z), decode to full OD/parameters — the same operators
  validated on Chicago/AZTDM/SCAG (freeway R² 0.93–0.99).
- Deliverable: `calibrate` subcommand — inputs: scenario + counts; outputs: θ*, the
  manifest of the calibrated run, and the sensitivity report (∂MOE/∂θ — which parameter
  actually moves which corridor).

### M6 — The NeXTA-AI loop
NeXTA (or the AI Scenario Manager chat layer) drives: *load scenario → run → dashboard →
"the freeways are too fast in the north corridor" → the AI maps that to θ (capacity/VDF
of those facility classes) → M4/M5 adjusts → re-run → diff dashboards.* Every step is a
manifest, so the whole conversation is reproducible and versioned.

---

## 3. Sequencing & effort

| Milestone | Depends on | Effort | Risk |
|---|---|---|---|
| M1 manifest | — | small (kernel already logs most of it; wrap in dtalite_qa run) | low |
| M2 gates | M1 | small (regression exists; formalize CHANGELOG) | low |
| M3 dashboards | M1 | medium (reuse workflow_dashboard plumbing) | low |
| M4 auto-config | M1+M3 | medium (port adapt_pipeline to dtalite_qa) | low — proven on the agency |
| M5 CG calibration | M4 | large (integrate CompressedTAP gradients with the kernel's VDF library) | medium — research-grade, but the math + code exist |
| M6 NeXTA-AI loop | M3+M4 | medium (contract + UI wiring) | medium |

**Recommended order: M1 → M2 (immediately), M3 + M4 (next), M5 in parallel as the
research track, M6 once M3/M4 are stable.**

---

## 4. Principles (carried over from the pipelines)

1. **The kernel stays a solver; orchestration stays in Python** (`docs/ARCHITECTURE.md`).
2. **Never guess a convention** — the AI layer *enforces* the intake gate; calibration
   only starts on a GATE: READY scenario (otherwise you calibrate against a units bug —
   see `CONVERSION_ERRORS_CATALOG.md` §1a: a capacity-basis error looks exactly like a
   VDF that needs recalibrating).
3. **Validate before tuning; volumes before speeds; VMT/VHT alongside β/R²** — a
   calibration objective must include congestion measures, not just volume fit.
4. **Every run reproducible from its manifest** — the version-control unit is the
   scenario+manifest, not a loose folder of CSVs.
