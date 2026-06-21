# TAPLite4MPO Golden Path — from agency files to a trusted assignment

**Read this first.** It is the front door, before any of the detailed manuals. Follow it in
order; only reach for the reference docs when a stage tells you to.

> A shapefile and an OD matrix are **not yet an assignment model.** They carry geometry and
> demand, but they do not tell us the capacity convention, period definition, peak-load
> factor, VDF formula, user classes, toll rules, or validation targets. **TAPLite will not
> guess those.** Onboarding makes them explicit, converts them to GMNS, runs the
> assignment, and validates the result.

GMNS is the *container*. The assignment model is defined by **capacity, period, PLF, VDF,
demand class, allowed-use, toll, and validation target.** A scenario is not done until it
runs, produces volumes/VMT/VHT/speed/V·C, and passes validation.

---

## The three questions (the whole guide in one frame)

| Gate | Question | What it covers |
|---|---|---|
| **1. Can I run?** | blockers only | missing files, schema, topology, missing zones, undeclared conventions |
| **2. Can I trust it?** | is the answer right? | capacity convention, period & PLF, VDF, demand unit, allowed-use, toll, validation target |
| **3. Can I improve it?** | go further | QVDF duration, path output, binary demand, super-zones, skims, dashboards |

Don't touch gate 3 until gate 2 is green. Don't argue gate 2 until gate 1 runs.

---

## The dataset ladder (start small)

Climb in order — each rung teaches one new thing. See **[DATASET_LADDER.md](DATASET_LADDER.md)**.

1. **Chicago Sketch** — minimum runnable assignment (BPR, one period). *Start here.*
2. **Chicago Regional** — scale, binary demand, convergence, super-zones.
3. **ARC Atlanta** — full agency reproduction (field mapping, modified BPR, PLF, classes, validation).
4. **Chicago Downtown OSM** — public-data quick start (OSM → GMNS). *(planned)*

---

## Stage 0 — Collect the agency package
Ask the agency for five things. **Do not start coding until capacity convention, period
definition, and demand unit are known.**

1. **Network** — shapefile / CUBE / Visum / DBF.
2. **Demand** — OD matrices by period and user class.
3. **Lookup tables** — facility type, area type, speed, capacity, VDF coefficients.
4. **Assignment documentation** — VDF formula, time periods, period factors, VOT, PCE, toll & HOV rules.
5. **Validation targets** — loaded volumes, counts, screenlines, VMT/VHT, or the agency validation report.

## Stage 1 — Map agency fields to GMNS
Convert the raw fields into the five inputs: `node.csv`, `link.csv`, `demand_<class>.csv`,
`mode_type.csv`, `settings.csv`. Most-important fields:

**link** `from_node_id` · `to_node_id` · `lanes` · `capacity` · `free_speed` /
`vdf_free_speed_mph` · `length` / `vdf_length_mi` · `vdf_type` · `vdf_alpha` · `vdf_beta` ·
`vdf_A` · `vdf_plf` · `allowed_use` · `toll_<mode>` · `ref_volume`

**mode_type** `mode_type` · `demand_file` · `vot` · `pce` · `occ` · `operating_cost` ·
`dedicated_shortest_path`

**settings** `demand_period_starting_hours` · `demand_period_ending_hours`

The ARC example is the worked mapping — see `examples/arc_atlanta/README.md`.

## Stage 2 — Define the assignment model (the part that's not a file)
Before running, answer:
1. Is capacity **hourly, period, or daily**?
2. Is capacity **per-lane or per-link**?
3. What is the **period length H**?
4. What is the **PLF** (or agency period factor φ)?
5. Which **VDF** — BPR, modified BPR, conic, QVDF, …?
6. Are demands **vehicle** or **person** trips?
7. What **user classes** are loaded?
8. Which links are **HOV-only / truck-only / closed / tolled**?
9. Which column is the **validation `ref_volume`**?

**Standard TAPLite convention:**
```
capacity = hourly per-lane capacity c_h
vdf_plf  = real PLF = phi / H
H        = assignment period length (hours)
DOC      = (period_volume / lanes / H / PLF) / c_h
```
ARC AM worked setting: `capacity = AMCAPACITY/LANES`, `H = 4` (6–10 AM), `vdf_plf = 3.66/4 = 0.915`.
See **[peak_load_factor.md](peak_load_factor.md)**. **Allowed-use ≠ toll:** HOV-only is an
*access restriction* (`allowed_use`); a toll is a *generalized-cost penalty* (`toll_<mode>`).

## Stage 3 — Run the minimum assignment
Get **one period** running before anything advanced.
```bash
python -m dtalite_qa intake <scenario>     # declare gaps -> resolve until READY
python -m dtalite_qa check  <scenario>     # schema, topology, accessibility
python -m dtalite_qa run    <scenario> --exe bin/DTALite.exe
```
A good first run: no missing critical fields, no connectivity failures, reasonable V/C,
correct allowed-use behavior, link volumes comparable to `ref_volume`, sane VMT/VHT by
facility type. Intake writes `intake_issues.json`, `intake_log.md`, `intake_dashboard.html`
— iterate until **blockers = 0**.

## Stage 4 — Validate **before** tuning
Never adjust demand first. If the result looks wrong, the first suspect is **a convention
mismatch, not the solver.** Diagnose in this order:

| Symptom | Usual cause |
|---|---|
| V/C too low everywhere | daily capacity used as hourly |
| V/C too high | PLF or period length wrong |
| HOV links carry SOV | `allowed_use` mapping wrong |
| toll links unused | VOT / toll units wrong |
| total volume off | demand period or class mismatch |
| VMT/VHT off by facility type | speed / capacity / VDF lookup wrong |

Order: units (length/speed/capacity) → period & PLF → VDF coeffs → demand unit & classes →
PCE/occupancy → allowed-use & toll → convergence → **only then** demand totals & OD pattern.
The traceable workflow does this for you, gated:
```bash
python -m dtalite_qa workflow <scenario> --period <PM>   # R1-R6, each with a gate
```

## Stage 5 — Add advanced modules (only after the baseline passes)
PLF back-calculation · BPR/conic/QVDF VDF gates · QVDF congestion duration · path/route
output · super-zone aggregation · skims / four-step feedback · dashboards. **Super-zones are
an accelerator** — introduce them only after the full-resolution model is trusted, and
always verify the `S=N` corner case first. See **[superzone_design_principles.md](superzone_design_principles.md)**
("compress the response, not the data") and **[qvdf_congestion_duration.md](qvdf_congestion_duration.md)**.

---

## What to inspect in `link_performance.csv`
`volume` / per-class `mod_vol_*` · `doc` (V/C) · `speed_mph` · `VMT` · `VHT` · the
`ref_volume` comparison · (QVDF) `P` congestion duration. Plus the accessibility report
(unreachable OD / bad allowed-use) and the summary log (gap / convergence).

## Common mistakes this guide prevents
capacity period/hour confusion · per-lane vs per-link · `vdf_plf=1` on a peaked period ·
daily capacity used hourly · persons loaded as vehicles · mph/kmh · m/mi/km · HOV≠toll ·
missing `dedicated_shortest_path` · broken centroid/zone ids · unsorted links · inaccessible
OD · validating against the wrong volume column · super-zones before a trusted baseline.

## Where to go next
- **[DATASET_LADDER.md](DATASET_LADDER.md)** — which example to start with
- `examples/arc_atlanta/` — the agency-reproduction worked example
- **[MPO_ONBOARDING_GUIDE.md](MPO_ONBOARDING_GUIDE.md)** — the detailed declare→…→workflow process
- **[USER_GUIDE_VOL2_MPO.md](../USER_GUIDE_VOL2_MPO.md)** — kernel mechanics & per-agency recipes
- `docs/onboarding_guide.html` — the visual, click-through version of this path
