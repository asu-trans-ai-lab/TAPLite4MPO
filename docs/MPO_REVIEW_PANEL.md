# TAPLite4MPO — simulated MPO reviewer panel

**Method:** six independent reviewer personas — a TransCAD-shop senior modeler, a
Cube/Voyager-shop modeler, a PTV Visum-shop modeler, a small-MPO planner (OSM, no
commercial license), a state-DOT QA/validation manager, and a visualization/NeXTA
specialist — each reviewed the package's public documentation and examples cold, then a
panel chair deduplicated and prioritized the findings. Persona attributions are kept
(e.g. [TransCAD, QA]).

**Companion hands-on evidence (small-MPO path):** the Tempe OSM pipeline test
(`test_networks/data_Tempe_network/`) exercised osm2gmns 1.0.1 -> gmns-ready 0.1.1 ->
TAPLite -> net2cell 0.1.3 end-to-end; findings from that run are folded into the QA
section (notably: gmns-ready `quick_check`/validators work well as the iterative external
verifier, but `build_network` is pandas-3-incompatible — `dtype == object` WKT checks
miss the new `str` dtype and WKT strings are written into geometry columns).

## What the panel agrees works

- **The intake/no-guessing discipline is the package's crown jewel.** All six personas endorse the declare→block→ask posture: BLOCKER/DECISION/MISSING taxonomy, evidence cross-checks (declared "mi" vs median length 710), and the GSATS "block and ask which capacity column" example [TransCAD, Cube, Visum, SmallMPO, QA, Viz].
- **CONVERSION_ERRORS_CATALOG.md is the most-cited asset in the review** — symptom → cause → convention → "which agency hit it" is called "the debugging bible" [TransCAD], "the most useful document for a converter" [Cube], "a genuinely reusable knowledge base" [Visum], "replaces the senior modeler we don't have" [SmallMPO], and "the strongest document in the package" [QA].
- **The ARC Atlanta flagship is a credible, honest reproduction, not a demo**: requirement→kernel mapping table, the 14-code PROHIBIT→allowed_use table, 0 SOV leakage on 820 HOV-only links, uncalibrated 88% vs calibrated 23% RMSE shown openly against ARC's own 38% target [TransCAD, Cube, Visum, SmallMPO, QA].
- **The kernel's VDF library and convergence semantics meet multi-vendor practice**: BPR/conical/BPR2/INRETS/Akcelik/SANDAG plus SCAG piecewise and ramp-meter, cost-based line search (no per-VDF solver hacks), standardized relative gap + consecutive-iteration stopping [TransCAD, Cube, Visum].
- **PLF methodology is rigorous and enforced, not just described** — phi = L·PLF with numeric bounds in dtalite_qa/plf.py, the "flat-PLF red flag" diagnostic [TransCAD, Cube, Visum, QA].
- **allowed_use vs toll (access ≠ cost) is handled correctly and verified** [TransCAD, Cube, Visum].
- **stdlib-only dtalite_qa CLI + the R1–R6 gated workflow are audit-grade and IT-friendly** — copy-paste commands, numbered per-stage PASS/WARN/FAIL reports, dashboards with no external dependencies [TransCAD, SmallMPO, QA, Viz].
- **Golden Path three-gate framing and the Dataset Ladder are the right onboarding scaffold** [TransCAD, Cube, SmallMPO], and **WKT geometry pass-through into link_performance.csv means the raw material for maps already exists** [SmallMPO, Viz].
- **KERNEL_FEATURE_CHANGES.md is a model engine-change document** — adversarially verified, honest about schema-vs-kernel default deltas [QA, Cube].

## Findings by theme

### 1. Documentation gaps

- **No tool-specific export/conversion guide exists for any source platform.** Golden Path Stage 0 name-drops "shapefile / CUBE / Visum / DBF" but the actual click paths and scripts (GISDK export, Voyager NETWORK/MATO, Visum list exports, osm2gmns invocation) are documented nowhere; the knowledge lives only as war stories in CONVERSION_ERRORS_CATALOG.md and inside bespoke scripts like arc_atlanta_to_gmns.py [TransCAD, Cube, Visum, SmallMPO, QA]. Each persona asks for its own guide: TRANSCAD_EXPORT_GUIDE.md, CUBE_EXPORT_RECIPE.md, VISUM_TO_GMNS.md, OSM_QUICKSTART.md.
- **submission.yml — the centerpiece of intake — is never shown filled-in.** Two template paths exist (dtalite_qa/templates/ and examples/), zero rendered examples; the template only shows single-value vot/vdf_type/PLF where real models are per-class and per-facility [TransCAD, Cube]. The ARC submission.yml should appear annotated in MPO_ONBOARDING_GUIDE.md.
- **Broken/private references for the external audience**: USER_GUIDE_VOL2_MPO.md cites private/ARC_Atlanta/ and private/kernel_references/ paths external readers cannot see [TransCAD, Cube]; peak_load_factor.md's canonical derivation is a private memo [QA]; KERNEL_FEATURE_CHANGES.md itself lives outside the deliverable repo [QA].
- **VDF documentation drift**: VOL2 lists types 0–6 while the kernel ships 7/8; manifest.py and schema.py comments are stale; no crosswalk telling Visum users that types 1/3/4/5 are their Conical/BPR2/INRETS/Akcelik built-ins [QA, Visum]. Generate the table from schema.py.
- **Multi-period operation gets one paragraph** — no worked 5-period example, no daily-assembly recipe, no doc closing the catalog §2b period-vs-daily validation trap it itself flags [TransCAD, Cube].
- **movement.csv soft-penalty trap is undocumented**: values <10 are read and silently ignored (TAPLite.cpp ~4249); a Cube/Visum modeler exporting turn times gets no effect with no warning [Visum, Cube].
- **No front-door scope statement** ("static highway assignment; no PuT, no blocking-back/ICA; QVDF duration is the queue analog") [Visum], and **zone/centroid/connector mechanics are explained only through agency examples** [Visum, SmallMPO].
- **Demand schema is not at the front door** (o/d/volume long form), and the "never round-trip through Excel" warning gives no positive alternative for .mtx/.mat holders [TransCAD, SmallMPO].
- **Install docs contradict reality**: Golden Path references bin/DTALite.exe that no fresh clone contains; wheels exist only "on a version tag" [SmallMPO].
- **DATASET_LADDER.md Rung 4 (OSM public quick start) is advertised but unbuilt** — flagged independently by four personas [TransCAD, Visum, SmallMPO, QA].
- **Toll story inconsistent in the flagship**: README advertises toll_<mode> wiring but toll_flag is future-layer only and SOVF/SOVT segments are collapsed [Cube].
- **Acceptance criteria are scattered** across docs/mpo_spec/ instead of one sign-off page, and no doc tells analysts to set relative_gap_standard=1 for comparable gap claims [QA]; count-validation wiring (mapping agency loaded-volume fields to ref_volume for R5/R6) is left as an exercise [TransCAD].

### 2. Commercial-tool connections (TransCAD / Cube / Visum how-tos)

The panel converges on a common recipe shape — export, field crosswalk, convention declaration, ID/topology fixes, VDF recovery, turn tables, demand matrices, round-trip validation — that must be written once per tool:

- **TransCAD** [TransCAD, QA]: .dbd → attribute CSV (not shapefile — DBF 255-field/10-char truncation, catalog §7b); DIR 0/1/-1 + AB_/BA_ pair mapping worksheet; which of AB_CAP/AB_CAP_PK/AB_CAP_OFF is assignment capacity and total-vs-per-lane (§1a/1b); .mtx export never via Excel (§4c); centroid renumbering + tiered-TAZ correspondence (§5a/5b); VDF recovery from GISDK scripts; loaded-volume fields → ref_volume like-for-like (§2b SCAG slope-0.18 trap).
- **Cube** [Cube]: Voyager NETWORK/MATO export scripts; A/B/CAPACITY/FT-AT crosswalk; HIGHWAY .s constructs → submission.yml (CAPFAC/phi → peak_load_factor, PATHLOAD toll classes → vot); generalize the ARC PROHIBIT 14-code table into a fill-in template; FACTYPE×ATYPE VDF/PLF lookups as CSV config, not the hard-coded VDF_ADB dict in arc_calibrate.py; catalog → 5 scenario folders + daily assembly; results/skims back to .net/OMX; GAP↔relative_gap_standard parity.
- **Visum** [Visum]: list exports via .att/CSV (link TSYSSET/CAPPRT/V0PRT, nodes, zones, connectors, turns, per-DSeg matrices); TSYSSET → allowed_use; connectors → centroid links with node_id==zone_id and an honest "connector shares are lost" statement; CapPrT per-link total ÷ lanes; **hourly-matrix models correctly use vdf_plf=1 — the guide must say when the PLF doctrine does NOT apply**; VDF crosswalk incl. unsupported forms (TMODEL/Lohse); turn bans map, turn times are dropped.
- **OSM (reverse problem)** [SmallMPO, QA]: attributes that don't exist rather than exports that truncate — link_type default tables recorded as intake MISSING/DECISION entries, TAZ centroid+connector creation from scratch, DOT AADT counts joined for ref_volume, and an explicit "teaching scenario, not agency-validated" label.
- **Cross-cutting** [QA, Viz]: per-tool declaration crosswalks ending in submission.yml blocks (model-semantics translation, not file translation); the two silent-truncation traps (DBF fields, Excel rows) stated up front; geometry CRS declared at export because state-plane vs WGS84 breaks every downstream map.

### 3. Missing features

- **No reusable, config-driven converters** — every agency so far got a bespoke private script; transcad2gmns / cube2gmns / visum2gmns / an osm adapter (field-map YAML + lookup CSVs + access-code table) is the single biggest self-service blocker [TransCAD, Cube, Visum, SmallMPO]. Existing dtalite_qa adapt/nexta.py and the ARC/SCAG scripts are patterns to generalize, not solutions.
- **No matrix interchange**: nothing reads .mtx/.mat/OMX or writes OMX skims; demand must be hand-exported wide CSV and skims can't round-trip into any demand model [TransCAD, Cube, Visum].
- **No select-link or turning-movement outputs** despite route_assignment.csv already storing paths — "non-negotiable MPO deliverables that block adoption outright" [TransCAD, Cube, Viz].
- **No multi-period orchestration/daily-assembly command** — closes catalog §2b by construction [TransCAD, Cube].
- **Turn penalties are hard-bans only** (penalty ≥10), no soft penalties, no per-mode movement restrictions, no per-link cycle_length for vdf_type=6 [TransCAD, Cube, Visum].
- **No per-class congested skim pipeline**: skim.py is single-class (ignores allowed_use/tolls/VOT — a truck skim routes through truck-prohibited links); the mode-aware alternative needs the memory-heavy route store [Visum].
- **No GeoJSON/shapefile export, no result dashboard, no scenario diff** — PRODUCTIONIZATION items 5/6 and roadmap M1/M3 all acknowledged but unbuilt [TransCAD, SmallMPO, Viz, Cube, QA].
- **No run-level manifest** (manifest.py hashes inputs only — no kernel build hash, effective settings, convergence trace, output hashes) and **no intake enforcement at run** (control.py gates only on validate.ok; a BLOCKED scenario runs anyway) [QA].
- **No generic gated validate-run command or screenline module** (conformance matrix row O5 = "none/add"); ARC's %RMSE gate is a one-off script and is not in CI; regression baselines are intent-checks with no numeric tolerances or re-baseline policy [QA, TransCAD].
- **No verified no-compiler distribution** (no bin/, wheels tag-only) [SmallMPO]; **no zone/connector generator or first-demand (gravity/growth-factor) helper** for public-data networks [SmallMPO]; **no toll-segmentation workflow** for SOVF/SOVT-style classes [Cube, TransCAD].

### 4. Visualization & NeXTA

- **The geometry is there; the map is not.** WKT pass-through is verified working, yet the entire pipeline produces exactly one figure (optional vc_vs_speed.png); nothing renders volume/V-C/speed maps, and roadmap M3's dashboard spec — which the Viz reviewer endorses as the right content — is unbuilt [Viz, SmallMPO, TransCAD].
- **NeXTA is asserted "GMNS in/out compatible" but has zero how-to** — no open-the-run steps, no write-back packaging of a finished run; dtalite_qa/nexta.py only converts inputs inward [Viz, SmallMPO].
- **CRS is never declared or handled**: submission.yml has no crs field, geometry echoes source projection, and origin_accessibility.csv's google_maps_link pastes state-plane feet as lat/lon (verified broken on ARC) [Viz].
- **No output column dictionary**: link_performance.csv's 100+ columns (QVDF internals, 48 five-minute speed slices) and od_performance.csv's population preconditions (header-only file in the flagship) are undocumented [Viz, Visum].
- **The flagship produces no board-ready graphics** — the 23%-RMSE headline has no validation scatter, no loaded-network map, no convergence chart despite the gap trajectory already being parsed in report.py [Viz].
- **Interim path exists today and just needs writing down**: QGIS Add-Delimited-Text→WKT→graduated symbology recipe, period-vs-daily map labeling (the map version of catalog §2b), and a mid-level output cut between 148 MB full and geometry-less compact [Viz, SmallMPO].

### 5. QA / verification

- **The gate is procedural, not technical**: `dtalite_qa run` does not read intake_issues.json; the panel's audit persona calls this the honor system at the run boundary and wants refusal on BLOCKED/absent/stale intake with a recorded --override [QA].
- **Independent verification is missing**: gmns-ready (the only external GMNS validator mentioned) appears solely in unbuilt Rung 4; schema conformance is currently self-certified by the same package that did the conversion. QA would require an external verifier run on every converted network with its report archived alongside intake artifacts; SmallMPO separately asks for a doc clarifying gmns-ready (generic GMNS conformance) vs dtalite_qa check (TAPLite runnability) [QA, SmallMPO].
- **Manifests**: input manifests exist (sha256/rows/columns via manifest.py) but the M1 run manifest — kernel version/build hash, effective settings after defaults, convergence trace, output hashes, run_id — is the missing contract that makes scenario+manifest the version-control unit and enables scenario diff [QA, Cube, Viz].
- **Regression rigor**: run_regression.py's own header admits shipped baselines predate the 2026 kernel fixes; no written re-baselining procedure or numeric tolerances; the ARC calibrated reproduction is not in CI, so an engine change degrading agency validation would pass [QA].
- **Convergence auditability**: per-iteration gap is free text; no machine-readable convergence certificate stating criterion, denominator convention (relative_gap_standard 0 vs 1), and achieved trace [QA].
- **Provenance drift**: KERNEL_FEATURE_CHANGES.md outside the deliverable, VDF table stale vs schema.py, PLF derivation behind a private memo — all fixable documentation-hygiene items [QA].

## Prioritized action list

**P0 — blocks adoption**

- Ship config-driven converters (transcad2gmns first, cube2gmns second: field-map YAML, DIR/AB-BA split, FACTYPE×ATYPE lookup CSVs, access-code table, emits the conversion log intake consumes) [TransCAD, Cube] — ⚡ quick-win seed: adapt.py/nexta.py plumbing + arc_atlanta_to_gmns.py/SCAG scripts as generalization targets.
- Add matrix interchange to dtalite_qa: .mtx/.mat/wide-CSV/OMX demand import with zone-index mapping + truncation/coverage checks, and OMX skim export [TransCAD, Cube, Visum].
- Write the per-tool export how-tos (TRANSCAD_EXPORT_GUIDE, CUBE_EXPORT_RECIPE, VISUM_TO_GMNS) with field crosswalks and an annotated filled-in ARC submission.yml, linked from Golden Path Stage 0/1 [TransCAD, Cube, Visum, QA] — ⚡ quick-win: content largely exists in CONVERSION_ERRORS_CATALOG.md + the ARC example; it needs assembly, not research.
- Build select-link and turning-movement post-processors on the already-stored route set (route_assignment.csv) [TransCAD, Cube, Viz] — ⚡ quick-win: the path data exists; this is a query tool.
- Publish the no-compiler distribution (tagged wheel / Releases exe) and fix the bin/DTALite.exe doc contradiction [SmallMPO] — ⚡ quick-win: cibuildwheel + RELEASE.md already exist; cut a tag.
- Make the intake gate technically enforceable: run/workflow refuse BLOCKED/absent/stale intake_issues.json, --override records who/why [QA] — ⚡ quick-win: gate artifact and control.py hook point both exist.
- Build Dataset Ladder Rung 4 for real (osm2gmns → gmns-ready → centroids/connectors → toy demand → run → map) or stop advertising it [SmallMPO, QA, Visum, TransCAD].

**P1 — high value**

- Implement the M1 run manifest (emitted by default from run) + `dtalite_qa diff` for scenario comparison [QA, Cube, Viz, SmallMPO] — ⚡ quick-win: manifest.py hashing + report.py gap parsing are the building blocks.
- Multi-period production runner: run EA/AM/MD/PM/EV, accumulate to daily, like-for-like R5/R6 per period and daily [TransCAD, Cube].
- One-command GeoJSON export with CRS declaration/reprojection + the M3 self-contained HTML result map; fix the google_maps_link projected-feet bug [Viz, SmallMPO, TransCAD] — ⚡ quick-win: WKT pass-through + intake/workflow dashboard plumbing already proven.
- Generic gated validate-run command + docs/ACCEPTANCE_CRITERIA.md + screenline aggregation module (conformance matrix O5) [QA, TransCAD] — ⚡ quick-win: generalize arc_validate_run.py.
- Mode-aware per-class congested skims (respect allowed_use + per-class generalized cost) with matrix output [Visum].
- Soft turn penalties + per-mode movement restrictions; immediately document that penalty<10 is silently ignored [Visum, Cube, TransCAD] — ⚡ doc half is a one-line quick-win.
- Documentation hygiene sweep: fix private/ references in VOL2, mirror KERNEL_FEATURE_CHANGES.md into the deliverable with a kernel version, regenerate the VDF table from schema.py (types 7/8 + Visum crosswalk), publish the PLF derivation [QA, Visum, TransCAD, Cube] — ⚡ quick-win: all content exists.
- Add gmns-ready as an external verifier inside intake with archived reports; numeric golden baselines + written re-baseline policy; ARC %RMSE gate into CI [QA].
- docs/VISUALIZATION_GUIDE.md as Golden Path Stage 4.5: NeXTA open-the-run steps, QGIS WKT recipe (works today), link_performance/od_performance column dictionary, period-vs-daily map labeling [Viz, SmallMPO] — ⚡ quick-win for the QGIS/NeXTA/dictionary portions.
- Finish the flagship toll/managed-lane story (populate toll_<mode>, keep SOVF/SOVT classes) and make the flagship produce graphics (validation scatter, convergence chart) [Cube, Viz] — ⚡ chart data already parsed in report.py.
- Front-door scope statement (static highway only; no PuT/blocking-back/ICA) + connectors/zones explainer + OSM/public-data branch at Golden Path Stage 0 [Visum, SmallMPO] — ⚡ quick-win: paragraphs, not features.

**P2 — nice to have**

- Simple demand bootstrap (gravity/growth-factor from zonal totals) and surfaced unit-OD smoke test [SmallMPO].
- TAZ-polygon → centroid/connector generator [SmallMPO].
- Per-link cycle_length input for vdf_type=6 and any junction/ICA-adjacent modeling [Visum].
- Machine-readable convergence certificate artifact [QA].
- Raw-DBF pre-scan before conversion (detect AB_/BA_ pairs, multiple capacity columns, truncated names) [TransCAD].
- Mid-level link_output cut (geometry + key MOEs) sized for web maps/NeXTA joins [Viz].
- Per-period/dynamic toll schedules and VOT distributions beyond manual class splits [TransCAD].
- Cube-catalog-style scenario-family management beyond folder conventions [Cube].

## Dissents & tensions

- **Flat PLF: red flag or correct answer?** The PLF doctrine (and the R4 "PLF-not-flat" workflow gate) treats vdf_plf=1 as a suspect default, which TransCAD and QA endorse — but the Visum reviewer notes that for classic 1-hour European matrices vdf_plf=1 is *correct*, and the doctrine as written would mislead a Visum shop. The docs need a "when PLF does not apply" clause, and the R4 gate may need a declared exemption [Visum vs TransCAD, QA].
- **route_output=1: enabler or footgun?** TransCAD, Cube, and Viz want path output on for select-link, turn volumes, and path visualization; Visum flags the 5D route-store memory warning as making it unusable at regional scale, and QA flags the schema-vs-kernel default mismatch (1 vs 0). A select-link build should not assume full path storage is affordable [TransCAD, Cube, Viz vs Visum, QA].
- **What to build first**: the commercial-shop personas rank converters + matrix I/O + select-link as the adoption blockers; the small MPO ranks the OSM quick-start, prebuilt exe, and a map; the QA manager would sequence enforcement, manifests, and external verification *before* new features ("I cannot currently prove two identical runs used the same engine"); the Viz specialist ranks the result dashboard first. The P0 list above spans all four, but the panel does not agree on a single top item [TransCAD, Cube vs SmallMPO vs QA vs Viz].
- **Self-service defaults vs the no-guessing doctrine.** The small MPO wants sane defaults filled automatically (OSM capacity/speed by link_type, default submission.yml, no Python authoring); the QA manager insists every default be a recorded DECISION/MISSING entry and OSM builds be labeled "teaching, not agency-validated." The proposed osm adapter must log provenance rather than silently apply defaults — convenience and auditability pull in opposite directions [SmallMPO vs QA].
- **Gate strictness vs runnability.** QA wants run to hard-refuse BLOCKED scenarios; the small-MPO teaching path (and Rung 1 "just run the exe" ethos praised by the same persona) depends on being able to run imperfect data. Resolution likely a --teaching/--override mode with recorded justification, but the tension is real [QA vs SmallMPO].
- **NeXTA vs web-native visualization.** The roadmap treats NeXTA as the GUI front-end; the Viz specialist wants self-contained HTML/GeoJSON (Kepler.gl/QGIS) as the primary path and NeXTA as one viewer among several — the M3 dashboard and the NeXTA write-back are partially competing investments [Viz vs NEXTA_AI_INTEGRATION_ROADMAP framing].
- **Output richness vs usability.** The same 148 MB, 100+-column link_performance.csv is praised as "MOE-rich for storytelling" and criticized as having no consumable middle tier — the fix (a mid-level cut) is uncontroversial but the panel implicitly disagrees on whether full output should remain the default [Viz, internally; SmallMPO].
