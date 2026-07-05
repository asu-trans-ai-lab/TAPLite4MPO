# TAPLite4MPO — work packages from the MPO review panel

Source: [MPO_REVIEW_PANEL.md](MPO_REVIEW_PANEL.md) (all findings accepted). Each WP has a
fix scope, a **test that gates completion**, and a size. Statuses: ☐ open · ◐ started ·
✅ done. After the P0 set lands, re-run the independent reviewer panel on the refined
package (WP-13).

> Standing rule for every WP (the convention rule): a feature is only done when it
> respects the declared **capacity basis / period+PLF / units** conventions and is
> exercised on a scenario that passed the intake gate — never calibrate or validate
> against a units bug (CONVERSION_ERRORS_CATALOG.md).

## P0 — blocks adoption

**WP-01 · ◐ TransCAD converter (one engine: `dtalite_qa/net2gmns.py`)** — core DONE 2026-07-04
Config-driven (JSON = machine-readable submission.yml twin): AB_/BA_ field pairs + DIR
split, geometry-endpoint A/B derivation, units, capacity basis/period → per-lane hourly,
connector codes, zone-field centroid renumbering (with exclusion values), emits
`conversion_log.json` for intake.
*Verified:* **GSATS equivalence test — 10,264 directed links, 5,362 org links, 0
attribute mismatches** vs the hand-written converter (capacity/fftt/lanes/length per
direction). **FFB `.BIN`+`.DCB` reader DONE** (`dtalite_qa/transcad_bin.py`): reads
TransCAD fixed-format binary attribute tables (int/short/real/float/char + null
sentinels) → CSV; *verified on Cleveland TN* — links 1,127×50 fields (speeds, facility
types, per-direction lanes/caps, AADT2018 counts), nodes 812 (centroid flags), and the
turn-penalty table. All public TransCAD repos' attributes (TRMG2 83 MB, Oahu 8.6 MB) are
now recoverable without TransCAD. (Provenance: independent implementation from the
self-describing text `.DCB` dictionary only — same interoperability posture as the
open-source `wsp-sag/tcadr` package; note in the module docstring.)
**STANDARD HAND-OFF (decision 2026-07): ask planners for a network SHAPEFILE + OMX
matrices** — that is the whole request, for all three tools. The FFB reader stays as a
convenience for public GitHub repos only; the `.dln/.pts` geometry-sidecar reader is
DESCOPED (unnecessary under the shapefile ask); binary `.mtx`/`.mat` are out of scope.
Remaining: SCAG config re-validation.

**WP-02 · ◐ Cube converter (same engine, `"directed": true`)** — M
Cube's directed A/B exports are the same conversion minus the DIR split — covered by
net2gmns config. Remaining: the PROHIBIT-style access-code table preset
(`allowed_use`/`toll_*` mapping) + ARC re-derivation byte-compare; ARC validation gate
= **22% RMSE** (re-baselined 2026-07 from 23% after the Dijkstra/gap kernel updates).

**WP-03 · ◐ Matrix interchange (`dtalite_qa/matrixio.py`)** — core DONE 2026-07-04
Wide/square CSV + long CSV import (stdlib), OMX import/export (guarded optional dep),
zone-coverage + **Excel-truncation fingerprint** checks (catalog §4c) run on every
import; `--scenario` checks matrix zones against node.csv; BLOCKS on failures.
*Verified:* wide↔long round-trip exact; origin-coverage cut caught; truncation
fingerprint caught. Remaining: binary `.mtx` reader (test target: Cleveland's 17 KB
`BY_2018_EETRIPS.mtx`) — Cube `.mat` stays out of scope (export CSV per WP-04 recipe).

**WP-04 · ✅ Per-tool export how-tos** — DONE 2026-07-04
[TRANSCAD_EXPORT_GUIDE.md](TRANSCAD_EXPORT_GUIDE.md) (DBF-truncation defense, AB/BA/DIR
crosswalk, multi-capacity-column declaration), [CUBE_EXPORT_RECIPE.md](CUBE_EXPORT_RECIPE.md)
(ARC-anchored: period factor ≠ period length, PROHIBIT access-vs-toll split),
[VISUM_TO_GMNS.md](VISUM_TO_GMNS.md) (attribute lists/OMX, CapPrT basis check, TSysSet →
allowed_use; web-sourced menu paths). Remaining nice-to-have: annotated ARC submission.yml
inline in the onboarding guide.

**WP-05 · Select-link / turning-movement query tool** — M ⚡ (path data exists)
Query `route_assignment.csv`: which OD/flows use link X; turn volumes at node Y
(movement-link volumes once the meso path lands).
*Test:* Chicago Sketch — select-link flows sum exactly to the link's assigned volume.

**WP-06 · ✅ Enforceable intake gate** — DONE 2026-07-04
`dtalite_qa run` now refuses ABSENT / BLOCKED / STALE intake (`control.check_intake_gate`;
staleness = audit older than any input file); `--override "who/why"` bypasses and is
recorded in the run manifest; `--no-gate` = explicit legacy mode.
*Verified:* un-audited Chicago Sketch refuses with the exact remediation message;
override runs and the manifest carries `intake_gate: ABSENT, override: who/why`.

**WP-07 · ◐ No-compiler release + Dataset Ladder Rung 4 (OSM)** — S/M — STARTED
Rung 4 = Tempe is now live in DATASET_LADDER/Golden Path (scripts in
`test_networks/data_Tempe_network/`, macro path verified end-to-end); remaining: cut the
tagged wheel/exe release, fold the Tempe scripts into the deliverable repo, and the
[OSM_ECOSYSTEM_ISSUES](../../docs/OSM_ECOSYSTEM_ISSUES.md) student fixes (O1-O3, G1-G4,
N1-N5) for the meso track.
*Test:* fresh machine, `pip install` + download pbf → assignment map in ≤ 30 min.

## P1 — high value

**WP-08 · ✅ BPR calibration (keep it SIMPLE)** — DONE this session, right-sized
The default recommendation is **not a search**: it is the VDF **ladder** — (L1) BPR
defaults → (L2) + real PLF → (L3) the agency's published α/β lookup table by
facility × area type (ARC Table Section-7, SCAG Table 16-2 style) — one kernel run per
layer, pick the layer that meets the validation gate. Most agencies already HAVE the
table; calibration = transcribing it correctly (WP-04 guides), not fitting.
`dtalite_qa/calibrate.py` exists as the OPTIONAL last resort when no table exists:
small-budget (default 12 kernel runs) per-group refinement with `--apply`. Same loop
covers **QVDF** params. Precondition either way: intake gate green (never fit a units
bug). Gradient/CG calibration stays a research track (roadmap M5) — not a deliverable.
*Test:* `test_networks/test_calibrate_recovery.py` (truth recovery on Chicago Sketch).

**WP-09 · ✅ HTML assignment map (`dtalite_qa/vizmap.py`)** — DONE this session
Self-contained canvas map (V/C / volume / speed, connector toggle, no CDN).
*Next increments:* GeoJSON export with CRS; scenario-difference map; NeXTA project file.

**WP-10 · ✅ Run manifest + `dtalite_qa diff`** — DONE 2026-07-04 (= roadmap M1)
Every `dtalite_qa run` now emits `manifest.json`: SHA-256 of every CSV + the exe,
effective settings, convergence trace (final gap/VMT), MOE (VMT/VHT/mean speed/loaded
links), intake-gate status + any override. `dtalite_qa diff a b` reports changed
files/settings + MOE %-deltas (exit 2 if different).
*Verified:* two identical Chicago Sketch runs ⇒ MOE deltas 0.00% (deterministic kernel).

**WP-11 · ✅ Multi-period runner + daily accumulation** — DONE 2026-07-04
`dtalite_qa/multiperiod.py`: `--run` executes each period folder, then sums link
volume/VMT to `daily_link_performance.csv` (per-period columns kept) with a volume-
conservation invariant. Prevents the period-vs-daily validation trap (catalog §2b).
*Verified:* SCAG 5-period suite → 246,806 links accumulated, conserved=True, per-period
VMT matches the original kernel logs exactly.

**WP-12 · Per-class congested skims + soft turn penalties** — M/L
Mode-aware skims (allowed_use + class generalized cost) in OMX [Visum]; graded turn
penalties (today `penalty<10` is silently ignored — document immediately, then
implement additive penalties in the movement path).
*Test:* HOV skim ≠ SOV skim on a toll network fixture; a 30-second left-turn penalty
shifts flow in a 4-node fixture by the analytic amount.

## Accepted from the panel, not yet scheduled (traceability)

These panel P1 asks are **accepted** but have no WP yet — listed so nothing is silently
dropped: numeric golden baselines + ARC %RMSE gate in CI, with a written re-baseline
policy [QA] · gmns-ready as an external verifier inside intake [QA] · documentation-
hygiene sweep (mirror KERNEL_FEATURE_CHANGES into this repo with a kernel version;
regenerate the VDF table from schema.py) [QA, Visum] · VISUALIZATION_GUIDE + output
column dictionary [Viz, SmallMPO] · flagship graphics (validation scatter, convergence
chart) + toll/managed-lane story [Cube, Viz] · front-door scope statement (static highway
only) [Visum, SmallMPO].

*Sequencing note (2026-07):* this round completed two P1 quick-wins (WP-08 calibrate,
WP-09 vizmap) before Wave 1 — a deliberate deviation because both were direct user asks;
Wave 1 (WP-04/06/07) remains the next scheduled work.

## Kernel efficiency track (industry panel, 2026-07-04)

See **[EFFICIENCY_STUDY.md](EFFICIENCY_STUDY.md)** — 5-expert panel (Caliper-class /
PTV-class / open-source / academic / HPC). Warm-start ladder L1 times → L2 flows →
L3 **DTAC binary column store** (demand-invariant routing policy θ; rescale to new OD =
the "routing policy waits for demand change" mode) → L4 mmap state snapshot.
**✅ P0 SHIPPED (2026-07-04):** `warm_start_times` (L1: SCAG reaches cold's 20-iter gap
in ~11 iters, ends 1.9× tighter) + SP-equivalence auto-detect (6 modes → 4 trees,
byte-identical) + group-aware zero-demand-origin skip. Regression 30/30.
**✅ P1 SHIPPED:** `flow_snapshot`/`warm_start_flows` (DTLR binary + demand fingerprint
guard, mismatch demotes to L1): SCAG restart begins AT the prior final gap (0.072%);
9 warm iters = 1.7× tighter than 19 cold at 35 s vs 78 s.
**✅ P2 increment 1 SHIPPED:** `column_output` DTAC sparse-CSR path store (9.8× smaller
than route_assignment.csv) + `dtalite_qa/columns.py` push-down verifier (R² 0.966 vs the
FW blend — expected for last-iteration paths; exact on single-path nets).
**✅ L3 SHIPPED (2026-07):** DTAC v2 θ-share columns (push-down R² = 1.000000 exact),
`warm_start_columns` rescale-to-new-OD replay, fixed-policy GP sweeps
(`column_adjust_sweeps`), freeze/replay with the mandatory RESTRICTED + TRUE gap report.
**Same-gap evidence (SCAG RTP24 AM, perturbed demand, compute-only): 139× to a 0.10%
TRUE gap, 8.4× to 0.05%; 0.02%/0.01% reachable ONLY via GP sweeps** — plain FW (cold or
warm) plateaus ~0.03%, GP reaches 7.6e-4%. Standard rerun recipe (user decision):
**every rerun = `warm_start_columns` + `convergence_gap_pct=0.1` + 0 sweeps** —
[RERUN_RECIPE.md](RERUN_RECIPE.md). Regression 30/30, defaults-off byte-identity kept.
**Remaining:** per-origin parallel GP sweeps (serial sweeps dominate at ≥2M ODs) +
L4 DTST mmap state snapshot (kill the input-parse/DTAC-load setup phase).
Unanimously rejected: bush-based rewrite.

## Review loop

**WP-13 · ◐ Independent re-review after P0** — S — first pass DONE 2026-07-04
Two independent reviewers ran on the refined package: the replication verifier confirmed
every light claim in `soft/README.md` works as written (regression subset, Tempe map,
7/7 doc links, Beijing intake gate); the adoption reviewer's findings (22-vs-23 drift,
Rung-4 contradiction, vdf 0-6 staleness, unlinked front door, dropped-items traceability)
were all fixed same-day — this section is one of those fixes. Re-run after Wave 2.

## Suggested sequencing

1. Wave 1 (self-service): WP-04, WP-06, WP-07-release ⚡ small, immediate credibility
2. Wave 2 (converters): WP-01, WP-02, WP-03 — the adoption unlock
3. Wave 3 (production): WP-05, WP-10, WP-11
4. Wave 4 (depth): WP-12, calibrate-on-ARC, ecosystem student fixes → WP-07-Rung-4
5. WP-13 re-review, then repeat
