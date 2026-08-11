# CR-0014 — Output-Contract Integrity: QVDF reporting lineage + TAP_log schema

**Status:** COMMITTED (local branch) · **Date:** 2026-08-09
**Source:** external static review (verified line-by-line; audit record in
planning doc 13, findings K-1..K-5) · **Kernel change:** YES (output layer
only — assignment numerics untouched, regression ALL PASS)

## Problem

1. **K-1** — Analytical QVDF reporting profiles (P, vt2, queue speeds, 5-min
   profile) were generated for NON-QVDF assignments: default
   `qvdf_profile_mode=-1` triggered on freeway `link_type` alone. One output
   row mixed two models (assignment speed 41 mph beside the run's own 5-min
   profile at 10 mph).
2. **K-2** — Missing QVDF parameters silently fell back to plausible ctor
   defaults (`Q_cd=Q_n=1` ⇒ `P=DOC`), producing congestion durations of tens
   of hours or `P=0` at `D/C>1` depending on eligibility — both patterns
   confirmed at scale in the 12-tmc anomaly audit (2,496 rows D/C>1.2 with
   P=0; 1,701 rows P > period duration).
3. **K-3** — `Link_QueueVDF` consumed `VDF_Alpha/VDF_Beta` unconditionally;
   for a conical run staged via the deprecated alias columns those hold conic
   a/b, silently interpreted as BPR α/β.
4. **K-4** — `TAP_log.csv` header (12 named columns) did not match either
   writer: iteration-0 wrote 13 values plus an un-headered per-mode
   Obs_volume block; later iterations put `Lane_Capacity` under the
   `obs_volume` header. Same column ≠ same quantity across iterations.
5. **K-5** — `TAP_log`'s "doc" (`V/Link_Capacity`, no H, no PLF) differed
   from the assignment DOC (`V/lanes/H/PLF/Lane_Capacity`) by several ×,
   unlabeled.

## Change

- New `DecideQvdfProfile()` (file-scope, testable): QVDF assignments
  (`vdf_type==2`) keep legacy-auto exactly; non-QVDF assignments generate an
  analytical profile only with calibrated `vdf_cd`/`vdf_n` AND (explicit
  mode 1/2 request OR observed t2). New refusal statuses:
  `flat_non_qvdf_assignment`, `flat_missing_parameters`. Observation-based
  boundary fallback unchanged.
- New `link_record.qvdf_params_provided` set only when link.csv supplies
  `vdf_cd`/`vdf_n`.
- `Link_QueueVDF`: internal BPR-style reference model uses standard 0.15/4
  when the assignment VDF is neither BPR nor QVDF (alias-lineage guard).
- `TAP_log.csv`: single 14-column fixed schema emitted identically by both
  writer sites (`...,obs_volume,background_volume,lane_capacity_hourly,`
  `link_capacity_hourly,vol_over_link_capacity_hourly,fftt,travel_time,delay`
  + per-mode blocks matching the header). The D/C column is basis-stamped in
  its name.

## Behavior change (intended, documented)

Freeway links in BPR/conical runs without calibrated QVDF parameters now
report `qvdf_profile_status=flat_non_qvdf_assignment` and flat
assignment-consistent scalars instead of fabricated analytical QVDF fields.
Assignment volumes/travel times are bit-identical (verified).
`TAP_log.csv` consumers: audit found ZERO in-repo parsers (only
filename-level cleanup in fill.py/scenario.py/run_agency.py) — no downstream
migration needed; external scripts that ever parsed TAP_log must re-review
(they were reading misaligned columns).

## Verification

- selftest: 281 PASS / 0 FAIL (13 new decision-contract assertions covering
  every mode × calibration × vdf_type branch, incl. legacy-preservation for
  vdf_type==2).
- twin differential: 240/240 (untouched by this CR — VDF math unchanged).
- Network regression (`test_networks/run_regression.py`): ALL PASS.
- `tests/test_qvdf_observed_t2.py`: 25 passed + 18 subtests.

## Deferred (tracked)

- Basis-stamping of link_performance.csv D/C columns → N1 (capacity_basis).
- 4-link dynamic forensic trace on the agency network → P1 (private root).
- Pricing/managed-lane allocation investigation → separate stream.
