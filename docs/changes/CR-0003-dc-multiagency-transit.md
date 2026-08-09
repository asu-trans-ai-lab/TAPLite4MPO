# CR-0003 — DC multi-agency transit dataset (T2): contracts, pipeline, manifests

status: MERGED (owner-authorized batch 2026-08-08: "1 and 2 and 3")
class:  FIXTURE
wp:     transit track T2 · training spine Parts 5–7
branch: cr-0003-dc-multiagency-transit
author: Claude (AI agent) · approver: Owner

## Motivation & scope
Adds `examples/dc_multiagency_transit/` (250 KB, curation-first): the full DC
pipeline scripts (calibrated doubly-constrained gravity + K-factors; builds
0.2→0.3b; compressed-schedule contract + reader), every build manifest, the
per-agency inventory, the 0.2b transfer contract table, and the WMATA compact
exemplar. Bulk outputs excluded and regenerable (README table). No kernel or
tooling files touched; the gtfs2gmns tool itself is external and unmodified.

## Evidence
- 0.3: all 20 feeds OK (5,984 AM trips, 209,997 visits), zero failures;
  compact stores round-trip lossless per feed.
- 0.2 rail golden preserved inside the combined build (138 certified trips).
- Gravity calibration: β=0.1022/km, mean trip length exact, cell R² 0.926,
  TLD coincidence 0.985, marginals preserved.
- demand_provenance = synthetic_gravity_dc_kfactor (owner D2, no agency-model
  attribution); vintages 2019–2021 declared per feed.

## Decision
Owner approved commit+merge in the 2026-08-08 batch directive.
