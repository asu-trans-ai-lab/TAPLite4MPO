# CR-0002 — Add BART transit-assignment example dataset (T1 observed-demand gold)

status: MERQUEST — committed on branch, awaiting owner merge
class:  FIXTURE
wp:     transit track T1 (planning package 05_DATASET_CANDIDATES_TODO.md)
branch: cr-0002-transit-assignment-bart (stacked on cr-0001-freeze-baseline —
        cut before CR-0001 merged so the ledger folder exists; merge after it)
author: Claude (AI agent) · reviewer: pending · approver: Owner (commit
        requested by owner 2026-08-08: "commit to the data set for TAPLite")

## Motivation

TAPLite's dataset program needs a transit-side gold. `examples/
bart_transit_assignment/` adds the T1 observed-demand case: a column-based
BART loading model with four eras of observed hourly OD (2019/2021/2023/2025)
on the fixed FY2025 timetable — a clean undersupply/oversupply counterfactual
with every assumption in a register (README A1–A9) and capacity/ridership
values verified against BART's published figures (VERIFICATION.md).

## Scope of change

Additive only: new folder `examples/bart_transit_assignment/` (23 files,
10.7 MB) + this record. No kernel, tooling, or existing-example changes.
Touches NOTHING on the protected kernel list.

## Contract impact

None on existing contracts. Introduces the transit-loading conventions for
this example only (documented in its README register): 75 pax/car service
capacity, V/C state thresholds, uncapacitated equal-split column loading,
observed-demand provenance.

## Evidence

- Deterministic engine outputs committed (`analysis/`, `gold/era_comparison.json`);
  rerunning `bart_supply_demand.py` on the committed inputs reproduces them.
- Era table: 2019 433k riders/day, 6.5% link-hours undersupplied, peak V/C 6.6
  (service-capacity basis; ≈2.5 at crush) · 2021 111k, 92% oversupply ·
  2023 186k · 2025 178k (~42–50% recovery, matches BART's "~50%" report:
  219,918 peak day / 432,783 = 50.8%).
- Frequencies cross-checked vs BART GTFS (Yellow 6 tph, Red 3 tph — exact).
- 84 MB `demand_td.csv` intentionally not committed (DATA_SOURCES.md pointer +
  SHA-256 manifest reference); 2019/21/23 eras fully reproducible from
  committed files alone.
- Kernel regression: not run — no kernel-adjacent files touched (additive
  example folder only).

## Decision

Owner directed the commit (2026-08-08). Merge order: after CR-0001.
