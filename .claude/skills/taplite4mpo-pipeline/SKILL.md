---
name: taplite4mpo-pipeline
description: >
  Use for any work on the TAPLite4MPO / DTALite / TAPLite static traffic-assignment
  pipeline: onboarding an agency or OSM network, GMNS conversion and field mapping,
  the intake audit, peak-load-factor / capacity conventions, VDF setup, allowed_use
  and tolls, running a static highway assignment, validating against agency volumes,
  the traceable R1-R6 workflow, super-zone aggregation, and recovering the
  zone-to-zone travel-time skim. Triggers on: TAPLite4MPO, ARC Atlanta example,
  Chicago Sketch/Regional, GMNS conversion, MPO model reproduction, capacity/PLF
  conventions, super-zone, skim, link_performance, or turning raw agency/OSM data
  into a trusted TAPLite assignment.
compatibility: >
  Designed for Claude Code in a local TAPLite4MPO repo (Python 3 + a C++17 compiler
  for the kernel). Reads/edits project files; runs python -m dtalite_qa and the kernel.
---

# TAPLite4MPO pipeline

## Organizing principle
> Onboarding is **model-meaning** conversion, not file-format conversion. GMNS is the
> container; the assignment model is defined by capacity, period, PLF, VDF, demand class,
> allowed-use, toll, and validation target. **TAPLite will not guess these — they must be
> declared.** A scenario is done only when it runs, produces volumes/V·C/VMT/VHT/speeds,
> and passes validation.

Read `docs/GOLDEN_PATH_CHECKLIST.md` first; it is the front door this skill operates.

## The three gates (frame every task this way)
1. **Can I run?** — blockers only: missing files, schema, topology, missing zones, undeclared conventions.
2. **Can I trust it?** — capacity convention, period & PLF, VDF, demand unit, allowed-use, toll, validation target.
3. **Can I improve it?** — QVDF duration, path output, binary demand, super-zones, skims, dashboards.
Don't touch gate 3 until gate 2 is green; don't argue gate 2 until gate 1 runs.

## The path (6 stages)
0. **Collect the agency package** — network, demand by period/class, lookup tables, assignment docs, validation targets.
1. **Map fields → GMNS** — `node.csv`, `link.csv`, `demand_<class>.csv`, `mode_type.csv`, `settings.csv` (see the ARC mapping table).
2. **Declare the model semantics** — fill `submission.yml`: capacity basis/period, PLF, units, trip kind, VOT, classes, restrictions, count field.
3. **Run the minimum assignment** — one period:
   ```
   python -m dtalite_qa intake <scenario>      # resolve until GATE: READY (0 blockers)
   python -m dtalite_qa check  <scenario>      # schema, topology, accessibility
   python -m dtalite_qa run    <scenario> --exe bin/DTALite.exe
   ```
4. **Validate before tuning** — units → period/PLF → VDF → demand unit/classes → PCE/occ → allowed-use/toll → convergence → *then* demand. If it looks wrong, suspect a **convention mismatch, not the solver.**
   ```
   python -m dtalite_qa workflow <scenario> --period <PM>   # gated R1-R6 traceability
   ```
5. **Advanced (only after the baseline passes)** — super-zones, skims, QVDF duration, path output, dashboards.

## Standard convention (the #1 thing to get right)
```
capacity = hourly per-lane capacity c_h
vdf_plf  = real PLF = phi / H
H        = assignment period length (hours)
DOC      = (period_volume / lanes / H / PLF) / c_h
```
ARC AM: `capacity = AMCAPACITY/LANES`, `H = 4` (6-10), `vdf_plf = 3.66/4 = 0.915`. See `docs/peak_load_factor.md`.
**allowed_use ≠ toll**: HOV-only is an access restriction; a toll is a generalized-cost penalty.

## Tooling (dtalite_qa)
`guide` (HTML onboarding) · `intake` (audit + dashboard, blocks on undeclared conventions) ·
`check` · `run` · `workflow` (R1-R6 traceability) · `plf` · `adapt` · `demand-bin`.
Converters emit a `conversion_log.json` (field mappings + assumptions) that `intake` ingests.

## Examples ladder (start small — `docs/DATASET_LADDER.md`)
1. `kernel/data_sets/03_chicago_sketch` — minimum runnable.
2. `kernel/data_sets/04_chicago_regional` — scale, super-zones.
3. `examples/arc_atlanta/` — **the flagship**: full agency reproduction, validated (region %RMSE 22%).
4. Chicago Downtown OSM — planned (don't build unless asked).

### ARC flagship — the complete loop
```
python -m dtalite_qa intake gmns          # READY
python arc_benchmark.py                    # vs ARC Table 7-1/7-2
python arc_calibrate.py                    # gmns_calibrated/
( cd gmns_calibrated && ./DTALite.exe )    # converges ~iter 8
python arc_validate_run.py gmns_calibrated # region %RMSE 22% (target ~38%)
python arc_superzone.py 1500               # 6,031->1,431 zones, ~2x faster
python arc_skim.py sz && python arc_skim.py compare   # original skim, R^2=0.9985
```
Super-zones preserve major-corridor flows + the zone-to-zone skim (R²=0.9985) at 2× speed,
trading local-link detail — `examples/arc_atlanta/SUPERZONE.md`.

## Common mistakes to catch
capacity period/hour confusion · per-lane vs per-link · `vdf_plf=1` on a peaked period ·
daily capacity used hourly · persons loaded as vehicles · mph/kmh · m/mi/km · HOV≠toll ·
missing `dedicated_shortest_path` · broken centroid/zone ids · unsorted links · inaccessible
OD · validating against the wrong volume column · super-zones before a trusted baseline.

## Rules
- Inspect before creating; prefer additive docs + small scripts over rewrites.
- Never hard-code private data paths; agency data lives in `private/` (git-ignored), public examples stay reproducible.
- Make every assumption explicit in `submission.yml` or the example README.
- Don't call any result "validated" without observed/reference volumes.

## Definition of done
A new user can answer: which example to start with · what files are needed · what commands to
run · what output to inspect · how to tell if it's wrong · what assumptions were made · where to go next.
