# CR-0005 — TAPLite → OpenDTA export (R-06): the CSV is the interface

status: MERGED (owner directive 2026-08-09: "commit and move to next task —
TAPLite for OpenDTA")
class:  TOOLING (+ CONTRACT: first implementation of the export interface)
wp:     R-06 (planning Phase 3) · spine Part 10
branch: committed on main (single additive script + this record)
author: Claude (AI agent) · approver: Owner

## Motivation & scope

`scripts/export_opendta.py`: emits, from one single-period TAPLite run with
`route_output=1`, the four CSVs OpenDTA's loader contracts
(openDTA/dev/doc/01_design_document.md §§2.1–2.4):
`demand_period.csv` · `link_period.csv` (μ = per-lane capacity × lanes,
units declared PCE/h total post-ratio per Q-1; MANDATORY provenance columns
capacity_source/tt_source; reference_tt = fftt until an observed layer is
supplied — never silently overwritten) · `columns.csv` (route/OD/agent/
period/volume/link_sequence/departure_profile_id) · `departure_profile.csv`
(period-level uniform template; OpenDTA's route→OD→corridor→period→uniform
hierarchy overrides downstream).

Kernel untouched. One run = one active period (frozen single-period
contract); multi-period = one export per run. The two codebases never
include each other's C++ — per OpenDTA's own design doc, the CSV IS the
interface.

## Evidence (Chicago Sketch, frozen kernel `ab9bd2e`, 40 iters, AM 07–08)

- 256,582 columns exported; **V1 conservation identity EXACT**:
  1,260,907.4 demand = 1,137,493.4 routed + 123,414.0 intrazonal
  (never routed, ledgered) + **0.0 unexplained**.
- V2: 0 unknown link_ids across all sequences.
- V3: column push-down onto links vs `link_performance.csv` volume
  **R² = 1.0000** (noted: approximate for plain-FW last-iteration paths in
  general; exact only for DTAC v2 θ-share stores).
- Export gate refuses to emit on V1/V2 failure (fail-closed).

## Decision
Owner-directed. Follow-ups: DTAC v2 θ-share source option (exact shares),
observed reference_tt layer hookup (INRIX) on the OpenDTA side, NVTA
corridor case as first real consumer (Gate 0–3 order per the OpenDTA plan).
