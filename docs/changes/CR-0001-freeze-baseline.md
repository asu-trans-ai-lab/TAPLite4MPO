# CR-0001 — Freeze single-period reference baseline + golden capture

status: APPROVED (owner, 2026-08-08) — execution in progress
class:  FIXTURE
wp:     R-01 (planning package, Phase 0)
branch: cr-0001-freeze-baseline
author: Claude (AI agent, Author role) · reviewer: pending · approver: Owner

## Motivation

TAPLite4MPO must carry a permanently protected single-period static-assignment
baseline (the "S0" contract) so that every future change — including QVDF edits,
multi-period features, and the OpenDTA export — can be checked against a frozen,
reviewed reference. Until this CR, golden baselines existed for the self-demo but
there was no release-blocking tag + golden set tied to one audited commit.

## Scope of change

- Annotated tag `release/taplite-reference` at `ab9bd2e` (main, 2026-08-06). No code
  is modified by this CR.
- New ledger: `docs/changes/` (this folder) with CR-INDEX.
- Golden capture (this file, §Goldens): S0a Chicago Sketch regression, S0b ARC AM
  full pipeline, S0c TRMG2 (public golds only — SCAG and the agency are private by owner
  decision 2026-08-08 and are never public gates).
- Protected kernel list declared (below). Touches NO file on that list.

## Protected kernel list (KERNEL-PROTECTED class applies from this CR forward)

Frank–Wolfe assignment · shortest-path generation · generalized cost · VDF/QVDF
evaluation · PCE loading · allowed-use filtering · dense internal ID mapping /
external ID restoration · VMT/VHT calculation · column/path output · convergence
calculation.

## Contract impact

None. No conventions change; this CR only freezes and records them.

## Goldens (captured on this machine, kernel built from source at `ab9bd2e`)

Build: MinGW g++ (WinLibs UCRT), CMake, Windows 11; Python 3.11.9, pandas 3.0.2,
numpy 2.4.6.

**S0a — kernel regression (`test_networks/run_regression.py`): ALL PASS, exit 0**
(captured 2026-08-08). Spot values: Chicago Sketch completes 2,950 links, gap
0.039%, external IDs preserved; Sioux Falls 76 links, gap 0.563%; subarea
fixtures 0 allowed-use leaks; qvdf_observed_t2 external IDs preserved.

**S0b — ARC AM full pipeline: PASS** (captured 2026-08-08, `arc_pipeline.py all
--full`, 5.5-min kernel run). Preflight: intake gate READY (0 blockers); VDF/PLF
verify OK — 11 facility types match ARC Sec 7.1.2, vdf_plf = 0.915 everywhere.
Network 66,546 nodes / 145,971 links; validation vs ARC AM reference over
118,687 links: **region-wide %RMSE = 22%** (ARC target ~38%), assigned/ref
total = 1.00, all five volume groups pass (0k–2k 23%, 2k–5k 14%, 5k–10k 12%,
10k–25k 11%, 25k–50k 11%). **VMT = 33.252M mi, VHT = 1.033M hr** (volume ×
length / travel_time over all links). Run manifest with per-file SHA-256:
`examples/arc_atlanta/gmns_run/manifest.json` (schema gmns-dtalite-1.0).

**S0c / R0 — TRMG2: CAPTURED** (2026-08-08; renamed R0 "Real-World Reference
Gold" per the planning package's S0/R0/A1/A2 hierarchy). Source:
`asu-trans-ai-lab/TRMG2_GMNS` (cloned sibling). GMNS network 33,963 nodes /
75,939 directed links / 3,247 zones; resident-HB demand rebuilt from TRMG2's
own tables (`make_od_4period.py` v1.5, no invented parameters); multiclass
SOV/HOV2/HOV3 demand files; kernel = THIS repo's `bin/TAPLite.exe` @ `ab9bd2e`.
Per-period results (gap = final relative gap):

| Period | veh (log) | VMT (mi) | VHT (hr) | VHD (hr) | avg mph | gap |
|--------|----------:|---------:|---------:|---------:|--------:|----:|
| AM | 466,633 | 3,084,153 | 65,079 | 250 | 47.39 | 0.001081% |
| MD | 870,780 | 5,700,859 | 121,449 | 74 | 46.94 | 0.000112% |
| PM | 708,818 | 4,677,875 | 99,546 | 503 | 46.99 | 0.000597% |
| NT | 743,439 | 4,813,042 | 102,479 | 120 | 46.97 | 0.000174% |
| Daily | — | 18,275,928 | 388,552 | 948 | 47.04 | — |

Total wall 728 s (demand build + 4 assignments). Count comparison (4,659 links,
2020 AWDT): captured share 0.307 overall, freeway −74.8% — the expected
missing-markets deficit (resident HB only; NHB/CV/university/airport/externals
labeled in the dataset inventory, not hidden). Full metrics + honesty notes:
`../../../../MPO_dataset_1_TRMG2/gold/assignment_metrics.json` (teaching
dataset scaffold, outside this repo).

**SCAG / the agency:** excluded from public goldens by owner decision 2026-08-08
(private mode); never a public release gate.

## Decision

Owner approved the freeze plan 2026-08-08 ("approve." on the six-step safest-path
plan). Reviewer verification of the golden numbers: pending first human review.
