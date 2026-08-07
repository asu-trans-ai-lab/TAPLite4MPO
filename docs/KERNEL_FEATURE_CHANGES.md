# TAPLite kernel — feature change list

**The definitive list of engine features and runtime controls.** Compiled from the
code (`kernel/src/TAPLite.cpp`) and adversarially verified against it (51/53 entries
confirmed line-by-line; the 2 findings are folded in below). Defaults shown are the
kernel's own; `dtalite_qa/schema.py` fill-defaults deltas are flagged at the end.

**Headline change: the shortest-path engine is binary-heap Dijkstra (label-setting) by
default** (`sp_algorithm=1`) with pre-allocated per-thread scratch — measured ~20×
faster than the legacy D'Esopo–Pape label-correcting search on 77k-node networks,
identical costs. Verified stable: 13-network regression suite (30 checks ALL PASS),
ARC Atlanta calibrated reproduction (region %RMSE 22, assigned/ref 1.00).


## Shortest-path & solver engine

| Feature | Key | Default | Status | Purpose |
|---|---|---|---|---|
| **Accessibility-only mode (skims without assignment)** | `number_of_iterations = 0` | off | opt-in | Runs only free-flow OD skims/accessibility: v1 in-memory for <10,000 zones, v2 streaming writer above; then exits before any assignment allocation. |
| **Assignment iterations** | `number_of_iterations` | 20 | always-on | Number of Frank-Wolfe iterations; setting 0 switches the kernel to accessibility-only mode (skims/od_performance.csv without assignment). |
| **Assignment method: FW / conjugate FW / bi-conjugate FW** | `assignment_method` | 0 (plain Frank-Wolfe) | opt-in | 1 = conjugate FW, 2 = bi-conjugate FW (Mitradjieva-Lindberg): search direction rewritten using one/two prior auxiliary points with a forward-difference diagonal Hessian (valid for any VDF), convexity and descent guards fall back to plain FW when unsafe. Faster gap closure to the same UE. |
| **Cost-based bisection line search** | `—` | on | always-on | Step size found by bisection on the directional derivative computed from link generalized COSTS at the trial volume (not a closed-form BPR integral), so any monotone VDF (conic, QVDF, INRETS, Akcelik, SCAG piecewise...) is solved exactly with no per-VDF solver calibration. |
| **First-through-node control** | `first_through_node_id` | -1 (auto-detect) | default-on | Centroid gating in shortest path: -1 auto-identifies the first non-zone node from node.csv; 0 makes every node a through node; >=1 sets an explicit external node id. Paths never traverse a centroid except at the origin. |
| **OpenMP parallelism** | `number_of_processors` | 4 (kernel; schema.py fills 8) | always-on | Thread count for parallel shortest-path/assignment; origin zones are bucketed per processor. |
| **Per-link U-turn ban (non_uturn_flag)** | `link.csv non_uturn_flag` | 0 (off) | opt-in | non_uturn_flag=1 on a link forbids the immediate U-turn back along any reverse link; folded into the same movement-restriction mechanism so it is handled exactly by the link-state search. |
| **Pre-allocated per-thread SP scratch (InitSPScratch)** | `—` | on | always-on | Per-thread reusable buffers (Pape queue, predecessor-link array, Dijkstra heap) sized once after network read and indexed by omp_get_thread_num(), eliminating per-call malloc/free in every shortest-path computation. |
| **Shortest-path algorithm: binary-heap Dijkstra (label-setting)** | `sp_algorithm` | 1 (Dijkstra = DEFAULT) | default-on | sp_algorithm=1 uses binary-heap Dijkstra with lazy deletion on pre-allocated scratch, ~20-50x faster on large networks, correct because all VDF costs are non-negative; sp_algorithm=0 falls back to the legacy D'Esopo-Pape deque label-correcting search. Same FirstThruNode/mode/turn-restriction rules either way. |
| **Turn restrictions via movement.csv (exact link-state search)** | `—` | auto (active only when movement.csv rows with penalty>=10 exist) | opt-in | movement.csv ib_link_id/ob_link_id (external link ids, translated to internal indices) with penalty>=10 hard-ban a movement; the kernel then switches from node-based Minpath to the exact link-state Minpath_TR with a link-predecessor back-trace. Zero cost when no restrictions are present. |

## Convergence & gap

| Feature | Key | Default | Status | Purpose |
|---|---|---|---|---|
| **Consecutive-iteration convergence (ARC rule)** | `convergence_consecutive` | 1 | default-on | Require the gap to stay below convergence_gap_pct for N successive iterations before stopping (ARC: gap<1e-4 for 3 iters); default 1 preserves prior stop-on-first behavior. |
| **GPS trace map-matching API** | `(separate mapmatchingAPI entry; reads trace.csv)` | not run by AssignmentAPI/main | opt-in | mapmatchingAPI grids the network, matches trace.csv GPS points (agent_id, x/y, road_order, allowed/blocked link types) to routes via shortest path, and writes route_assignment.csv. |
| **Relative-gap stopping criterion** | `convergence_gap_pct` | 0 (off - run all iterations) | opt-in | Stop Frank-Wolfe once the relative gap (%) falls below this threshold. |
| **Standardized relative-gap denominator** | `relative_gap_standard` | 0 (legacy AoN denominator) | opt-in | 0 normalizes the gap by the all-or-nothing total (legacy TAPLite); 1 normalizes by the CURRENT system total - the AequilibraE/agency-standard relative gap so a 1e-4 target means the same across agencies. |
| **Toll-consistent gap (generalized-cost system total)** | `—` | on | always-on | System-wide travel time includes pce-weighted per-mode additional (toll/operating) cost so it matches the shortest-path benchmark; prevents negative relative gaps on tolled networks; byte-for-byte unchanged on toll-free networks. |

## VDF library (vdf_type 0-8)

| Feature | Key | Default | Status | Purpose |
|---|---|---|---|---|
| **QVDF profile activation and volume threshold** | `link.csv qvdf_profile_mode`; `settings.csv qvdf_volume_threshold` | mode blank/absent = legacy auto; threshold 0 | default-on | FULL output profile selection is explicit and independent of assignment `vdf_type`: legacy auto preserves link type `1`, Cube-style `*01`, or observed `t2`; `0` disables; `1` model-generates on any link; `2` requires observed `t2`. Positive assigned volume and the threshold remain hard guards. Zero-volume links ignore anchors and emit a reason-coded flat numeric compatibility profile. Other skipped links retain assigned QVDF speed/time scalars; outside mode `0`, either valid boundary anchor produces an observed-only smooth fallback, otherwise the samples remain flat. |
| **Queue-based vehicle simulation API** | `(separate SimulationAPI entry; reads vehicle.csv agents)` | not run by AssignmentAPI/main | opt-in | SimulationAPI loads agents (agent_id, departure_time, link_ids, o/d zone) from vehicle.csv, runs a queue-based link simulation with optional signal timing arcs, and writes trajectory.csv plus sim debug logs. Exported as DTA_SimulationAPI. |
| **VDF type 0: BPR (+ ARC modified-BPR linear term vdf_A)** | `link.csv vdf_type=0 (default), vdf_alpha, vdf_beta, vdf_A` | vdf_type=0, alpha=0.15, beta=4, A=0 | default-on | t = fftt*(1 + A*x + alpha*x^beta) with x = per-lane V/C (per-lane fix: divides by Lane_Capacity, not lanes*capacity). vdf_A=0 recovers standard BPR exactly; ARC uses the linear term. |
| **VDF type 1: Spiess conical** | `link.csv vdf_type=1, conic_a, conic_b` | conic_a/b=0 -> fall back to vdf_alpha/vdf_beta; b derived as (2a-1)/(2a-2) if absent | opt-in | t = t0*(2 + sqrt(a^2(1-x)^2 + b^2) - a(1-x) - b), asymptotically linear (MWCOG/VDOT style). Prefers explicit conic_a/conic_b columns; staged convention stores a/b in vdf_alpha/vdf_beta. |
| **VDF type 2: QVDF (queue VDF) as assignment cost** | `link.csv vdf_type=2, vdf_cp, vdf_cd, vdf_n, vdf_s, cutoff_speed` | Q_cp=0.28125, Q_cd=1.0, Q_n=1.0, Q_s=4; cutoff_speed=0.75*free_speed | opt-in | Period-average congested travel time from the DTALite queue speed model (congestion duration P = cd*DOC^n, queue speed blend with cutoff speed); monotone in D/C so valid as a link cost. The time-sliced queue profile stays in Link_QueueVDF for reporting. |
| **VDF type 3: BPR2 (AequilibraE)** | `link.csv vdf_type=3` | off (per-link opt-in) | opt-in | BPR whose exponent DOUBLES above capacity: e = beta if x<=1 else 2*beta - steeper over-saturation penalty. |
| **VDF type 4: INRETS (AequilibraE)** | `link.csv vdf_type=4` | off (per-link opt-in) | opt-in | x<=1: t0*(1.1 - a*x)/(1.1 - x); x>1: t0*((1.1-a)/0.1)*x^2, with vdf_alpha the uncongested ratio (~0.9-1.0). |
| **VDF type 5: Akcelik time-dependent (VDOT-allowed)** | `link.csv vdf_type=5` | off (per-link opt-in) | opt-in | t = t0 + alpha*(z + sqrt(z^2 + beta*x)), z = x-1, alpha in minutes. |
| **VDF type 6: SANDAG BPR + Webster signal delay** | `link.csv vdf_type=6, green_ratio` | green_ratio=0.45; cycle_length fixed at struct default 60 s (NOT read from link.csv) | opt-in | BPR running time plus Webster uniform delay d = 0.5*C*(1-g/C)^2/(1 - min(1,x)*g/C); g/C clamped to [0.05,0.95]. Note: cycle_length has a hard-coded 60 s default and no CSV reader. |
| **VDF type 7: SCAG piecewise BPR** | `link.csv vdf_type=7` | off; uncongested exponent fixed at SCAG_UNCONGESTED_BETA=4.0 (constant, not a setting) | opt-in | Exponent 4.0 below capacity, calibrated per-link vdf_beta (5/6/8 by facility) at/above capacity; branches meet continuously at x=1 (both give t0*(1+alpha)). SCAG Validation Report Table 16-2. |
| **VDF type 8: SCAG freeway on-ramp meter delay** | `link.csv vdf_type=8` | off (per-link opt-in) | opt-in | t = fftt + [(PLPHx/120)*5.0*(1+x)^8]/60*60 min - metered-queue delay growing with the 8th power of (1+x); SCAG facility 82/84. |

## Period, capacity & PLF

| Feature | Key | Default | Status | Purpose |
|---|---|---|---|---|
| **Demand period window** | `demand_period_starting_hours / demand_period_ending_hours` | 7 / 8 | always-on | Assignment period bounds; period length H enters the per-lane hourly demand D = V/lanes/H/plf used by every VDF, and the 5-min speed-profile output range. |
| **Peak load factor (per-link vdf_plf)** | `link.csv vdf_plf` | 1 | default-on | Period->peak-hour bridge: per-lane hourly demand D = V/lanes/H/plf feeds every VDF; PLF = phi/L per agency convention (ARC AM 0.915, MAG AM 0.94). The #1 MPO onboarding pitfall (USER_GUIDE_VOL2_MPO.md section 4). |

## Multi-class, tolls & access

| Feature | Key | Default | Status | Purpose |
|---|---|---|---|---|
| **ARC generalized cost: distance operating cost** | `mode_type.csv operating_cost` | 0 ($/mile, off) | opt-in | Generalized cost (min) = time + (toll + length*op_cost)/VOT*60; op_cost=0 turns the distance term off so only ARC-style setups pay it. |
| **Base-demand warm start / incremental assignment** | `base_demand_mode (+ link.csv base_demand_volume, base_vol_<mode>; demand file <name>_base.csv)` | 1 (kernel; schema.py default 0) | default-on | Loads observed base link volumes as the starting MainVolume and assigns only the OD difference D^c - D^b (from <demand>_base.csv), enabling warm-started/incremental assignment on top of a baseline. |
| **Mode-restricted links (allowed_use)** | `link.csv allowed_use` | empty = all modes | default-on | Substring mode-token match determines mode_allowed_use[m] per link; shortest path skips disallowed links per mode. Empty or 'all' allows every mode. |
| **Multi-mode assignment (mode_type.csv)** | `mode_type.csv (mode_type, vot, pce, occ, demand_file, dedicated_shortest_path)` | single 'auto' mode, vot=10, pce=1, occ=1, demand.csv | default-on | Up to MAX_MODE_TYPES user classes each with own demand file, VOT, PCE, occupancy; dedicated_shortest_path=0 lets a mode reuse the main mode's paths (skips its own SP tree). |
| **ODME (origin-destination matrix estimation)** | `odme_mode, odme_vmt (+ link.csv obs_volume / obs_volume_<mode>, <demand>_target.csv)` | odme_mode=0 (off), odme_vmt=-1 | opt-in | After assignment, gradient descent with Armijo line search adjusts OD flows to match observed link volumes (w=0.1), target OD (w=0.01) and an observed VMT total (w=1e-6); logs to ODME_log.txt. |
| **Observed volume columns for validation/ODME** | `link.csv obs_volume / obs_volume_<mode>, ref_volume` | obs_volume=-1 (absent), ref_volume=0 | opt-in | Per-mode observed counts feed the ODME objective and are echoed in link_performance/TAP_log for validation against agency counts; ref_volume is carried through to output. |
| **Per-class tolls with vdf_toll fallback** | `link.csv toll / toll_<mode> / vdf_toll` | 0 | opt-in | Per-mode toll columns (toll for single mode, toll_<mode> multi-mode); the designed vdf_toll single-class column is the fallback when a per-class field is absent. Converted to minutes via VOT into mode_AdditionalCost. |

## Demand formats

| Feature | Key | Default | Status | Purpose |
|---|---|---|---|---|
| **Binary demand input (DTAB .bin)** | `demand_format` | 0 (CSV) | opt-in | demand_format=1 reads <demand>.bin (magic 'DTAB', int32 version=1, int64 n, packed 16-byte o/d/volume records) with bulk 64K-record freads - 2.5-3x faster OD load on regional models; silently falls back to CSV if the .bin is missing/invalid. Written by 'python -m dtalite_qa demand-bin'. |
| **Skip-Seed OD optimization** | `—` | auto | always-on | The seed OD copy (seed_MDODflow) is populated only when ODME, VMT target, or route output actually consume it - a third fewer OD writes on plain assignment runs. |

## Outputs & post-processing

| Feature | Key | Default | Status | Purpose |
|---|---|---|---|---|
| **Accessibility / OD performance post-processing** | `accessibility_output` | 1 (on) | default-on | Writes od_performance.csv (OutputODPerformance) and the aggregated accessibility suite (system_performance.csv, origin_accessibility.csv, destination_accessibility.csv, inaccessible_od.csv, od/origin/destination accessibility CSVs (zone_accessibility.csv belongs to accessibility-only mode), google_maps_od_distance.csv). Set 0 to skip - the dominant post-processing cost on large networks. |
| **Debug iteration log (TAP_log.csv)** | `log_file` | 0 (off) | opt-in | g_tap_log_file=1 writes per-iteration per-link volumes/costs/search-direction detail to TAP_log.csv, plus link node-mapping echo during read. |
| **Route (path) output** | `route_output` | 0 (off) | opt-in | Writes route_assignment.csv with per-OD path link sequences and FW flow proportions theta; also gates allocation of the 5D route-policy store - when off, linkIndices stays empty giving fast low-memory FW with correct per-mode volumes. |
| **Run summary log** | `—` | on | always-on | summary_log_file.txt always records per-iteration gap/lambda/VMT, convergence events, turn-restriction counts, demand totals and CPU time. |
| **Vehicle-level output** | `vehicle_output` | 0 (off) | opt-in | Expands routes into individual vehicle records (vehicle.csv, using occupancy) - requires route_output=1 since it consumes the stored paths. |
| **link_performance output detail levels 0/1/2/3** | `link_output` | 2 (full CSV) | default-on | 2 = full CSV with QVDF queue model (P, t0/t2/t3, vt2, mu, Q_gamma) plus per-5-min speed profile; 1 = compact CSV (link_id/from/to/volume/doc/travel_time/speed/VMT); 3 = binary link_performance.bin (header 'DTLP', int32 version, int32 n_links; same compact fields, fastest); 0 = none. Compact/binary skip the per-link queue simulation entirely. |

## Calibration / ODME

| Feature | Key | Default | Status | Purpose |
|---|---|---|---|---|
| **Explicit calibrated cutoff speed** | `link.csv cutoff_speed` | 0.75 * free_speed when column absent | default-on | Speed at capacity for the QVDF queue model; an explicit calibrated column (e.g. 49 mph on I-10) overrides the 0.75*free_speed derivation and is never silently overridden. |
| **Observed QVDF boundary-speed anchors** | `link.csv qvdf_start_speed_mph, qvdf_end_speed_mph` | modeled/free-flow boundary independently on each generated side; assigned period-average speed on a missing fallback side | opt-in | Valid positive mph observations anchor the first and last emitted five-minute samples. With observed `t2`, an anchor at or below the Hermite margin connects directly to `vt2` by cubic smoothstep and reports `generated_low_anchor_connector`; an anchor clearly between `vt2` and the modeled boundary uses an independently selected monotone Hermite splice into the raw profile. Remaining generated sides retain the historical blend. All paths preserve analytical scalars. When QVDF generation is skipped outside explicit mode `0`, either valid anchor creates an observed-only cubic smoothstep connector and the assigned flat speed supplies a missing endpoint. Invalid supplied values warn and fall back independently. |

## Other

| Feature | Key | Default | Status | Purpose |
|---|---|---|---|---|
| **External link id preservation** | `link.csv link_id` | on | always-on | Original link.csv link_id is preserved as external_link_id while the kernel renumbers internally (row index k); movement.csv restrictions are translated external->internal so they work when ids do not coincide. |
| **Geometry pass-through** | `link.csv geometry` | empty | opt-in | WKT geometry column read and echoed into full link_performance.csv for direct GIS mapping. |
| **Library + optional executable packaging** | `(build flag BUILD_EXE)` | DLL/shared-library exports; exe only with -DBUILD_EXE | always-on | DTA_AssignmentAPI / DTA_SimulationAPI are the shared-library entry points (used by pytaplite/pybind11); a standalone main() that runs AssignmentAPI from the cwd is compiled only when BUILD_EXE is defined. |
| **Link validation on read** | `—` | on | always-on | Links with lanes<=0, capacity<0.0001 or free_speed<0.0001 are skipped with an error message rather than corrupting the VDF; unknown from/to node ids are also skipped. |
| **MAG additive per-mile delay** | `added_delay_per_mile` | 0.0 (off) | opt-in | Adds g_added_delay_per_mile * length(mi) minutes to the congested time of EVERY VDF type (MAG's '1.4*L + Tc' on all facility types); 0 leaves all other networks bit-identical. |
| **Metric-unit input conversion** | `(link.csv vdf_length_mi / vdf_free_speed_mph overrides)` | g_metric_system_flag = 1 (hard-coded) | always-on | length is read in meters (/1609 -> miles) and free_speed in km/h (/1.609 -> mph); explicit vdf_length_mi and vdf_free_speed_mph columns override the converted values for imperial-native agency data. |
| **Missing-demand fallback (unit OD)** | `—` | auto (single-mode only) | always-on | If the single mode's demand file cannot be opened, the kernel fills a 1.0-trip OD for every valid zone pair so connectivity/skim runs still work; multi-mode missing files leave that mode at zero. |
| **Zero-outbound-zone demand diagnostics** | `—` | on | always-on | After demand load, reports every zone with positive origin demand but no outbound link, and the share of total demand stranded - catches connector/zone-id mismatches early. |
| **dtalite_qa settings schema parity** | `(dtalite_qa/schema.py SETTINGS_COLUMNS/SETTINGS_DEFAULTS)` | mirrors kernel defaults | always-on | The Python control package's canonical schema lists all 19+2 settings keys (incl. relative_gap_standard and assignment_method in DEFAULTS) and all LINK_DEFAULTS, so validate/fill-defaults produces networks that run identically with nothing implicit. Note two intentional deltas: schema fills number_of_processors=8 (kernel internal default 4) and base_demand_mode=0 (kernel internal default 1). |


## Known deltas: dtalite_qa schema vs kernel defaults

Found by the verification pass — intentional but worth knowing:

1. **`route_output`**: schema.py fills `1` (paths written, route-policy store allocated —
   real memory/speed impact); kernel default is `0`. Set `route_output,0` explicitly for
   large networks unless you need paths/skims.
2. **`odme_vmt`**: schema fills `0` vs kernel `-1` — functionally identical (gated by
   `VMT_target > 1`).
3. schema.py `SETTINGS_COLUMNS` omits `relative_gap_standard` / `assignment_method`
   (present in `SETTINGS_DEFAULTS` only), and its `vdf_type` comment predates types 7/8.

## Stability evidence (this kernel build)

| Test | Result |
|---|---|
| `test_networks/run_regression.py` (13 networks, incl. Sioux Falls, Chicago Sketch, QVDF corridors, multimodal, turn restrictions, conic) | **30/30 checks PASS** |
| ARC Atlanta calibrated AM (118,687 links, 6,031 zones) | converges iter ~8; **region %RMSE 22% (target 38%), assigned/ref 1.00, all 5 volume groups pass** |
| SCAG RTP24 AM full-scale (76,616 nodes / 224,288 links / 11,259 zones) | converged gap 0.04% (40 iters BFW); freeway count β=1.03, R²=0.93 vs agency AM |
| 147k-node private test network (398k links, 2,023 zones) | converged gap 0.08%, 2m01s / 20 iters (Dijkstra) |

## P0 efficiency trio (2026-07, from github_taplite/docs/EFFICIENCY_STUDY.md)

All three are exact: outputs are bit-identical with the features off (L1) or on
(SP dedup / origin skip, which only remove redundant work). Verified by byte-diffing
`link_performance.csv` and the gap trajectory of the new exe vs the pre-change exe
on `cs_multimodal` (6 modes, grouping active) and by matching the SCAG AM cold gap
trajectory digit-for-digit against the pre-change prior run.

| Feature | Key | Default | Purpose / behavior | Kernel evidence (TAPLite.cpp) |
|---|---|---|---|---|
| **L1 warm start from congested times** | `warm_start_times` = path to a prior run's `link_performance` CSV (compact or full) or DTLP `link_performance.bin` (`link_output=3`) | `""` (off) | Preloads `Link[k].Travel_time` (+ `GenCost` recomposed as `mode_AdditionalCost[1] + tt`) by EXTERNAL link id after the initial `UpdateLinkCost` and before the first `FindMinCostRoutes`, so iteration-0 AoN routes on congested instead of free-flow times. Only the starting point changes; later iterations recompute costs from volumes, so the equilibrium is unchanged. Missing/unreadable file or 0 matches = loud warning, cold start (never fails the run). Logs the id-match rate. | `ApplyWarmStartTimes()` ~3644–3760; call site ~3869; settings read ~3344 |
| **SP-equivalence auto-detect (tree dedup)** | — (automatic) | always on | After input read, modes are grouped iff `mode_allowed_use` AND per-link `mode_AdditionalCost` are identical on every link (PCE/occ never split a group). Non-representative modes reuse the representative's `Minpath` tree/costs (`g_rep_mode`), skipping redundant identical SP solves; the legacy manual `dedicated_shortest_path=0` "reuse mode 1" path is untouched. Grouping is always logged, e.g. `SP tree groups: {sov,com} -> sov; {hov2,hov3} -> hov2; {trk} -> trk; {apv} -> apv;` (cs/sf_multimodal: 6 modes -> 4 trees). | `BuildSPModeGroups()` ~3505–3585; reuse in `FindMinCostRoutes` ~806–830; AoN `mpred` ~1543 |
| **Zero-demand-origin skip (per mode)** | — (automatic) | always on | The kernel already skipped whole origins with zero TOTAL demand (`TotalOFlow`, before Minpath). Completed to per-(mode, origin): `Minpath` is skipped when no mode in the SP group has demand out of the origin, and the `MDRouteCost` row is BIGM-filled directly — exactly what the full destination loop produces with a zero demand row, so results are identical. Logs active/total (mode, origin) pairs. | `BuildOriginActivity()` ~3589–3640; skip in `FindMinCostRoutes` ~808–840 |

Registered in `dtalite_qa/schema.py` (`SETTINGS_COLUMNS` + `SETTINGS_DEFAULTS["warm_start_times"]=""`).

**Evidence**: 30/30 regression checks PASS post-change. SCAG RTP24 AM (224,288 links,
plain FW, 20 iters): warm start from the prior run's `link_performance.csv` matched
224,288/246,806 links (connectors carry tt=0 and keep FFTT), iteration-1 gap 44.9%
vs 185.2% cold; the warm run reaches the cold run's final gap (0.0755% @ iter 19)
by iteration ~11, and ends at 0.0407% @ iter 19 (~1.9x tighter, ~2x fewer iterations
to equal gap).

## P1/P2 increments (2026-07, from github_taplite/docs/EFFICIENCY_STUDY.md)

P0 conventions carried forward: EXACT results with the features off (default-off keys;
byte-diff-verified `link_performance.csv` + gap trajectory vs the pre-change exe on
Chicago Sketch), loud-warn-and-continue on every bad input, 30/30 regression checks
PASS with no re-baselining.

| Feature | Key | Default | Purpose / behavior | Kernel evidence (TAPLite.cpp) |
|---|---|---|---|---|
| **DTLR flow snapshot** | `flow_snapshot` = 1 (also auto-written when `link_output=3`) | 0 (off) | Writes `link_flows.bin` at the end of the run: header `'DTLR'` (0x524C5444), int32 version=1, n_links, n_modes, then a 16-byte demand fingerprint (4 floats: OD total, positive-cell count, min/max zone id touched — deterministic fixed-order double accumulation, `ComputeDemandFingerprint`); per link {int32 external_link_id; double MainVolume; per-mode double volumes}. Input format for `warm_start_flows`. | `ComputeDemandFingerprint()` + `WriteFlowSnapshotDTLR()`; call site after the link_performance loop |
| **L2 warm start from FLOWS** | `warm_start_flows` = path to a DTLR `link_flows.bin` | `""` (off) | When the snapshot's demand fingerprint matches the CURRENT OD table exactly (and mode counts agree), restores `MainVolume` + per-mode `mode_MainVolume` by EXTERNAL link id, skips the iteration-0 all-or-nothing entirely, `UpdateLinkCost` recomputes times from the restored volumes, and FW continues from iteration 1 — the restored point is a convex combination of AoN assignments of the same demand, so a valid FW iterate. **Guard**: on fingerprint mismatch (or mode-count mismatch / unreadable / wrong magic) it warns LOUDLY (both fingerprints printed) and demotes to L1 behavior — the snapshot flows only seed congested TIMES (`Link_Travel_Time` at snapshot volumes), then a normal cold AoN start; never a silent restart from incompatible flows. Unmatched links (network edits) are counted and warned; volumes on snapshot-only links are dropped with a warning. With `route_output=1` a warning notes route_assignment prob shares cover post-warm-start iterations only. | `ApplyWarmStartFlows()`; restore/skip branch around the iteration-0 `FindMinCostRoutes`/`All_or_Nothing_Assign` in `AssignmentAPI` |
| **DTAC column store (increment 1: write + verify; NOW LEVEL 1 of the leveled setting — see L3 full)** | `column_output` = 1 | 0 (off) | Writes `route_columns.bin`: per (mode, origin, destination) with positive demand and a feasible route, the **last-iteration shortest path** — the FINAL all-or-nothing direction whose FW step produced the reported volumes — as an external-link-id sequence, back-traced from `MinPathPredLink` exactly like `All_or_Nothing_Assign`/`route_assignment.csv` (same `mpred`/`g_rep_mode` sharing, same link-state walk under turn restrictions, same hop-cap guards). Binary sparse-CSR: header `'DTAC'` (0x43415444), int32 version=1, n_modes, n_zones; then per (mode, origin) row-major block {int32 n_dest; int32 dest_zone_id[n_dest]; int32 offsets[n_dest+1]; int32 external_link_ids[...] origin→destination order}. **Increment 1 is route_assignment PARITY only** — the last-iteration single path per OD, NOT the full multi-path column set with theta shares (that is increment 2 / the L3 warm start). | `WriteColumnsDTAC()`; call site after route output in `AssignmentAPI` (uses the trees of the LAST `FindMinCostRoutes`) |
| **DTAC verifier** | `python -m dtalite_qa columns <run_dir>` | — | Reads the DTAC file, pushes each OD volume (PCE-weighted) down its stored path, sums per link and compares to the run's link_performance volume: R², max diff, stored paths/links, DTAC vs route_assignment.csv size. NOT expected exact — link_performance is the FW blend of all iterations while increment 1 stores only the final AoN direction; the R² quantifies that distance. | `dtalite_qa/columns.py` (stdlib-only reader `read_dtac` + `verify`/`render`) |

Registered in `dtalite_qa/schema.py`: `warm_start_flows=""`, `flow_snapshot=0`,
`column_output=0` (SETTINGS_COLUMNS + SETTINGS_DEFAULTS).

**Evidence (P1)**: SCAG RTP24 AM scenario (`private/SCAG/scag_daily/AM`, 246,806 links,
plain FW). Run A cold 20 iters + `flow_snapshot=1`: gap 185.23% → 0.0755% @ iter 19
(FW time 1m18s). Run B `warm_start_flows` from A, 10 iters: restored 246,806/246,806
links, iteration-1 gap **0.0724%** (i.e. starts AT run A's final gap — measured after
A's last FW step) and ends 0.0453% @ iter 9 (35s). Fingerprint guard verified on
Chicago Sketch: a 10% perturbation of ONE OD cell flips the fingerprint
([1.26091e6,…] vs [1.26093e6,…]), triggers the loud demotion, and the run proceeds
as an L1 times-only warm start (iter-1 gap 2.78% vs 510.78% cold, 0.13% flow-restore).

**Evidence (P2 increment 1)**: Chicago Sketch (`kernel/data_sets/03_chicago_sketch`,
20 iters, 3 modes, 387 zones): DTAC = 93,135 paths / 1,211,261 link entries /
5.6 MB vs route_assignment.csv 55.1 MB (**9.8x smaller**). Verifier push-down vs
link_performance volume: **R² 0.9657**, max |diff| 8,051 veh (link 805) — honest gap:
the final AoN direction vs the 20-iteration FW blend; exactness arrives with
increment 2 theta shares. Turn-restriction case: stored path avoids the banned
movement (101,103,104), push-down R² = 1.0 (single-path net).

**Remaining for full L3** (increment 2): store ALL iterations' paths per OD with
theta shares (route_assignment already accumulates these — the CSR pool should then
REPLACE the 5D `linkIndices` store), the `warm_start_level=3` loader (drop paths on
deleted/banned links + renormalize, rescale theta×newOD, scatter to MainVolume), and
the fixed-policy gradient-projection adjustment sweeps with a separate
restricted-gap vs full-gap report. → Done below (L3 full); the pool was built as a
PARALLEL mechanism, the 5D `linkIndices` store is untouched (replacement deferred).

## L3 full: theta-share columns + warm start + fixed-policy adjustment (2026-07, P2 increment 2)

Same house rules: default-off keys, EXACT-or-clearly-reported, loud-warn-never-fail
on any bad input, 30/30 regression checks PASS with no re-baselining, defaults-off
`link_performance.csv` AND `route_assignment.csv` byte-identical to `bin/DTALite.exe`
on Chicago Sketch.

| Feature | Key | Default | Purpose / behavior | Kernel evidence (TAPLite.cpp) |
|---|---|---|---|---|
| **DTAC v2 theta-share column store** | `column_output` = 2 (LEVELED: 0 = off; 1 = DTAC v1 last-iteration path, light; 2 = DTAC v2 theta-share columns, RECOMMENDED for the rerun recipe; 3+ = reserved, warns and acts as 2) | 0 (off) | An in-memory pool (sparse per-(mode,origin) rows of growable per-OD path sets — NOT the 5D `linkIndices` route store, which is untouched) accumulates the path SET across FW iterations: after each line search the stored shares are scaled by (1−λ) via a global multiplier and the iteration's AoN paths enter with share λ (the exact `computeTheta` cascade route_assignment.csv uses), duplicate paths merged by summing. Written at end of run as DTAC **v2**: header {magic 'DTAC', version=2, n_modes, n_zones} + 16-byte demand fingerprint; per (m,O) block {n_dest; dest ids; path_offsets[n_dest+1]; float theta[n_paths] (per-OD sum = 1, renormalized at write, drift reported); link_offsets[n_paths+1]; external link ids}. Warned as plain-FW-exact only under CFW/BFW, and share-deficit-warned after an L2 flow warm start. | `ColPath/ColOD/g_col_pool`, `ColumnPoolUpdate()`, `WriteColumnsDTACv2()`; hooks after iteration-0 AoN and after `LinksSDLineSearch` |
| **L3 warm start from COLUMNS (rescale mode)** | `warm_start_columns` = path to a DTAC file (v1 or v2) | `""` (off) | Loads the columns into the pool and scatters theta × **CURRENT** OD volume to `MainVolume`/`mode_MainVolume`. Demand MAY differ from the stored fingerprint — that is the point: theta over a path set is a demand-invariant routing policy; both fingerprints and the OD/trip coverage % are printed. Paths crossing deleted links, links now banned for the mode, broken node chains, or now-banned movements are DROPPED (counted + warned) with theta renormalized over survivors. OD pairs with demand but no usable stored column fall back to a one-shot AoN on the warm times implied by the scattered flows (those paths join the pool, theta=1). Iteration-0 AoN is skipped and FW continues from iteration 1 (self-healing). Unreadable/wrong-magic/mode-count-mismatch/0-usable-paths ⇒ loud warn + cold start; takes precedence over `warm_start_flows`. | `ApplyWarmStartColumns()`; call site before `ApplyWarmStartFlows` in `AssignmentAPI` |
| **Fixed-policy adjustment sweeps** | `column_adjust_sweeps` = N | 0 (off) | After loading columns: N gradient-projection sweeps shifting share from costlier stored paths to the CHEAPEST stored path per (m,O,D) under current costs — NO new shortest-path calls. Newton step = min(movable flow, cost diff / Σ exact link-cost derivative over non-shared links); the derivative is a forward difference on the ACTUAL VDF (any vdf_type). Sweeps are **Gauss-Seidel** (touched links' travel times re-evaluated after each OD) — a frozen-cost simultaneous sweep was tested and DIVERGES. Serial by design (panel dissent; parallelize only if profiled). Per-sweep the RESTRICTED gap (stored paths only) is printed before→after. | `RunColumnAdjustSweeps()`, `ColLinkTTDer()`, `ColRestrictedGap()` |
| **Mandatory TRUE-gap report** | — (automatic with warm_start_columns) | always | After the scatter (+ sweeps), the kernel ALWAYS runs one fresh `FindMinCostRoutes` and prints BOTH clearly-labeled gaps: `RESTRICTED gap (STORED paths only, NOT an equilibrium claim)` and `TRUE relative gap (fresh shortest paths, full route space)` — freeze mode can never masquerade as equilibrium. | true-gap block after the warm-start branch in `AssignmentAPI` |
| **Freeze/replay mode** | `number_of_iterations=0` + `warm_start_columns` | — | `number_of_iterations=0` normally means accessibility-only; with `warm_start_columns` set it is PURE REPLAY: scatter + optional sweeps + both-gap report + all normal outputs (link_performance, accessibility uses the fresh-SP `MDRouteCost`). `odme_mode=1`/`route_output=1` in this mode warn that the route store covers post-warm iterations only and proceed. | override in `read_settings_file()` |

Registered in `dtalite_qa/schema.py` (`warm_start_columns=""`, `column_adjust_sweeps=0`).
`dtalite_qa/columns.py` reads BOTH DTAC versions; the v2 push-down weights each path by
theta and reports per-OD theta-sum min/max plus the stored fingerprint.

**Evidence (Chicago Sketch**, 387 zones, 3 modes, 20 iters, plain FW): theta push-down
R² = **1.000000**, max |diff| **0.00** veh (v1 was 0.9657 / 8,051 veh) — exact by
construction. DTAC v2 18.0 MB vs route_assignment.csv 55.1 MB (3.1x smaller; v1 was
5.6 MB). Freeze/replay reproduces the cold solution to max |vol diff| 1e-4 veh and
prints restricted 0.1268% / true 0.1268%. Perturbed demand (+5% on 1,000 random OD
cells): warm(`sweeps=5`, 3 iters) = 1.0 s, TRUE gap **0.0028%** vs cold 20-iter 0.7 s,
gap 0.173% — **62x tighter gap** at comparable wall; solutions agree at R² 0.9993
(residual is the cold run's own non-convergence). GP sweeps: restricted
0.127→0.0026% in 5 sweeps — the columns break the FW plateau exactly as predicted.
Turn-restriction case: stored path respects the ban; deleting its link makes the OD
infeasible (banned movement blocks the alternative) — replay warns, drops, completes.

**Evidence (Chicago Regional**, 12,982 nodes / 1,778 zones / 39,018 links, 2.30M
positive OD cells, 20 iters): column accumulation adds ~36 s to a 29 s cold run
(65 s total); DTAC v2 = **4.48 GB** (21.4M paths, 9.3/OD, 1.07B link entries) —
near-dense demand makes the store big; the file is demand-proportional, not
network-proportional. Replay: 32 s, push-down R² **1.00000000**, max diff 0.000 veh.
Perturbed +5%×1000: cold 20-iter 28.7 s → gap 1.685%; warm(`sweeps=0`, 3 iters)
28.2 s → 1.60% (restart parity, load-dominated); warm(`sweeps=5`, 3 iters) 348 s →
TRUE gap **0.064%** (26x tighter than cold-20; unreachable by plain FW in comparable
time — but the serial sweeps at ~60 s each ARE the bottleneck at 2.3M ODs). Warm vs
cold solutions R² 0.9981.

**Evidence (SCAG RTP24 AM**, `private/SCAG/scag_daily/AM`, 246,806 links / 11,259
zones, 342,712 positive OD cells, plain FW; phase timing separates SETUP = network+
demand parse + DTAC file load from COMPUTE = AoN/FW/sweeps/SP): cold 20-iter +
`column_output` at the v2 level (the benchmark runs predate the 2026-07 leveling, when v2 wrote under `=1`; it is `=2` now): 116 s wall, DTAC v2 **1.21 GB** (2.70M paths, 7.9/OD), gap 0.0755%.
Perturbed demand (+5% × 1,000 OD cells), all runs on it:

| run | SETUP (parse + DTAC load) | COMPUTE | TRUE gap | R² vs cold-pert |
|---|---|---|---|---|
| cold 20 iters | 2.7 s | **94.8 s** | 0.0778% | — |
| warm, 0 sweeps + 3 iters | 2.9 + 4.1 s | **16.3 s** (scatter 0.8 + gap-SP + 3 FW) | **0.0592%** | 0.9998 |
| warm, 5 sweeps + 3 iters | 2.8 + 4.1 s | **82.6 s** (sweeps 67.5) | **0.00107%** | 0.9994 |

- **Equal accuracy (compute-only)**: the scatter alone already lands at TRUE gap
  0.0725% — below the cold 20-iter final — after ~5.7 s of compute (0.8 s scatter +
  one fresh-SP gap audit), a **~17x** compute speedup; the conservative full-(b)
  number is 16.3 s vs 94.8 s = **5.8x** with a better gap (0.0592% vs 0.0778%).
- **Equal time**: at ~13% LESS compute than the cold run (82.6 vs 94.8 s), the
  5-sweep warm run reaches 0.00107% — **73x tighter** than cold-20, a level plain FW
  does not reach in any comparable budget (restricted gap 0.0717→0.00058% in 5 sweeps).
- Sweep cost: 23.5 s first sweep (2.35M shifts), ~11 s per later sweep — ~5.5x
  cheaper than Chicago Regional's ~60 s (342k vs 2.3M ODs; SCAG paths are longer),
  in line with the OD-count scaling expectation.
- The 0-sweep run's R² vs the cold reference is HIGHER than the 5-sweep run's
  (0.9998 vs 0.9994) because the sweeps move the solution PAST the non-converged
  cold reference toward equilibrium — the residual is the reference's own error.

Phase timing is print-only instrumentation (`phase timing: SETUP ... / DTAC column
load ... / column scatter ...` lines + per-sweep seconds + per-iteration
`elapsed = X s` on the gap lines), regression 30/30 and byte-identity re-verified
after adding it.

**Same-gap trade-off study** (figures `docs/l3_tradeoff_scag.png`,
`docs/l3_tradeoff_sketch.png`; generator `scripts/l3_tradeoff.py`; perturbed demand,
COMPUTE seconds only, setup + DTAC load excluded; crossings at discrete
iteration/sweep boundaries — no interpolation inside an atomic sweep/iteration;
cold FW run to 80 iterations, warm replay+FW to 40, GP points = final TRUE gap of
separate `column_adjust_sweeps=k` replay runs, k ∈ {1,2,3,5,8}):

SCAG RTP24 AM — compute seconds to reach a TRUE-gap target:

| target | cold FW | warm replay + FW | warm + GP sweeps | speedup (cold / best warm) |
|---|---|---|---|---|
| 0.10% | 101.7 s @ 15 it | 8.6 s @ 1 it | 0.7 s @ scatter | **139x** |
| 0.05% | 183.4 s @ 26 it | 28.5 s @ 6 it | 21.9 s @ 1 sweep | **8.4x** |
| 0.02% | not reached (80 it → 0.036%) | not reached (40 it → 0.033%) | 21.9 s @ 1 sweep | only GP reaches it |
| 0.01% | not reached | not reached | 21.9 s @ 1 sweep | only GP reaches it |

Chicago Sketch: 0.10% → cold 0.4 s @ 25 it vs warm+FW 0.1 s @ 5 it (4.8x);
0.05% → 0.6 s @ 35 it vs 0.2 s @ 16 it (2.4x); 0.02%/0.01% → cold and warm+FW
never reach them (80/40-iteration plateaus at ~0.028/0.030%), GP sweeps reach
0.02% at 2 sweeps and 0.01% at 3 sweeps (~0.4 s). The headline of both figures:
plain FW (cold OR warm-started) plateaus above 0.03% on these networks, while
GP sweeps over the stored columns pass 0.01% in 1–3 sweeps and keep going
(SCAG 8 sweeps → 7.6e-4%) — the sweeps are not just faster to a fixed target,
they reach targets FW cannot. Curve semantics documented in the figure caption:
FW curves are per-iteration TRUE gap; GP points are the final TRUE gap of each
sweeps=k run (per-sweep restricted gaps track them closely: 0.0717→0.00058% over
5 sweeps vs TRUE 0.0725→0.00107%).

**Honest caveats**: (1) theta cascade is exact for plain FW; under CFW/BFW it is the
same approximation route_assignment.csv already makes (loud warning). (2) The
stdlib-only Python verifier materializes the whole file — fine at Chicago-Sketch
scale, not at 4.5 GB; at that scale verify via freeze/replay R² (native push-down).
(3) GP sweeps are serial; parallelizing per-origin with volume reconciliation is the
next lever if sweeps are profiled as dominant (they are, at ≥2M ODs). (4) The 5D
`linkIndices` store is NOT yet replaced by the pool (deferred; route_output memory
hazard unchanged). (5) `base_demand_mode` diff-assignment + columns is loudly
unsupported (scatter uses the FULL OD table).
