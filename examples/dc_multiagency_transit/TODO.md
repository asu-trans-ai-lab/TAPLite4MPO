# Transit Dataset 2 (DC / multi-agency) — DECISIONS & TODOs, upfront

**Tier:** T2 — real multi-agency supply + DECLARED synthetic demand
(interoperability gold). Training role: Parts 5–7 of the ModelOps spine.

## Decisions RESOLVED (owner, 2026-08-08)

| # | Decision | Resolution |
|---|---|---|
| D1 | Rebuild vs reproduce the 2021 pipeline | **REBUILD on current tooling: `gtfs2gmns_pkg`** (`C:\source_codes\0_source_code_new\transit_schedule_column_generation_assignment\`). Verified on this machine 2026-08-08: `python -m gtfs2gmns_pkg.tests.test_golden_rail` → **all 11 certified NVTA_S1_WMATA_RAIL counts + arc identities + DAG check PASS**. The 2021-era DTALite transit exes and the 1.2 GB legacy service networks in `nvta_gmns_testbeds` become provenance archives, not build inputs. |
| D2 | Demand provenance | **SYNTHETIC via CALIBRATED doubly-constrained gravity + K-factors** (owner refinement 2026-08-08) — `demand_provenance = synthetic_gravity_dc_kfactor`; no agency-model attribution. The archived 2022 `d_*` files serve ONLY as calibration targets (marginals, mean trip length, district K-factors), never as shipped demand. **BUILT & CALIBRATED same day** — see below. Acceptance = T2 rule: conservation, correct paths/costs, deterministic reproduction — never observed-ridership match. |
| D3 | G9 distribution of large service networks | **Three-layer scheme:** (1) contract = plain GMNS CSV, committed only as a teaching-sized corridor extract; (2) rebuild = GTFS feeds + gtfs2gmns_pkg scripts + SHA-256 checksums, committed; (3) cache = Parquet snapshots + stage manifests (the pkg's native pattern), NOT committed, zipped-CSV export on request. SQLite = optional viewer only, never the contract. Bulk/binary is cache, not the interoperability contract. |

## Build ladder (follows the package's own release plan)

| Stage | Scope | Status |
|---|---|---|
| 0.1 | WMATA rail golden (event graph, priced ride resources) | ✅ EXISTS & PASSES (stageA–E_rail outputs in `gtfs2gmns_pkg_out/`) |
| 0.2 | NVTA_S1_WMATA_ALL: + bus, rail–bus transfers | ◐ **SUPPLY BUILT 2026-08-08** (`run_build_0_2.py` → `build_0_2/`, zero tool modification): Stage A gate PASS (1,461 of 142,740 raw trips included, double-entry ledger); 138 rail + 1,323 bus trips, 61,509 stop visits, 5,501 stations, 240,192 event nodes, 347,241 arcs. **Rail golden preserved inside the ALL build (138 = certified count) — P2 anchor held.** WMATA 2020-04 has no frequencies.txt (that item moves to other agencies in 0.3). **FINDING: rail–bus name-matched interchange stations = 0** — the two mode layers are currently DISCONNECTED (transfers are name-matched; bus stops use street-corner names, rail uses station names). This is the Gate-0 "Show Me the Path" failure made visible: multimodal supply ≠ multimodal connectivity. **0.2b same day — TRANSFER CONTRACT BUILT, graph connected:** `run_build_0_2b.py` → `transfer_stop_match.csv` (423 bus stops ↔ 69 rail stations, ≤200 m proximity match; aliasing is data-level, tool untouched). Result: 67 shared interchange stations, **3,078 cross-mode transfer arcs** (was 0). **Gate-0 transfer trip type DEMONSTRATED with a forced bus→rail path** (destination restricted to rail-only stations): board bus 30N @ Pennsylvania Ave SE & E St SE → ride → alight @ Eastern Market → **transfer to Orange Line** → board → ride → Capitol South — every segment traceable (arc type, station, mode, route). First naive demo honestly noted: an unconstrained search found a direct-bus path to a shared station (connectivity ≠ transfer proof; the forced version is the real evidence). Remaining for full 0.2 closure: walk access/egress arcs from zones, P&R/K&R trip types (needs parking elements), and the committed corridor extract. |
| 0.3 | NVTA_S1_FULL_MULTIAGENCY | ✅ **BUILT 2026-08-08** (`run_build_0_3.py` → `build_0_3/`): **all 20 feeds OK, zero failures/skips** — 5,984 AM trips, 209,997 stop visits, per-feed Wednesday-service snapshots (resolution method recorded per feed, never guessed), route types 0/1/2/3 incl. VRE + Amtrak. Additive fixes en route (tool untouched): GTFS-standard time interpolation (38,674 non-timepoint rows on Prince George alone), frequency instantiation (260 synthetic trips — and the finding that 7 of 9 frequencies.txt files in the collection are header-only export artifacts; only Prince George + Annapolis carry real rows), empty-block + sidecar-file guards. Per-feed compact stores all round-trip lossless (~2.7–3.5×). Per-agency vintage table: `build_0_3/agency_inventory.csv` (feeds span 2019–2021 — never present the merge as one date). Next for 0.3: cross-agency transfer contract (proximity matching agency-pairwise) + regional loading rerun to lift the 35.3% served share. |
| — | Synthetic gravity OD (D2) | ✅ **BUILT 2026-08-08** — `gravity_calibrate.py` → `synthetic_od_am.csv` + `k_factors.csv` + `calibration_report.json`. Model: T_ij = K(d_i,d_j)·a_i·b_j·P_i·A_j·exp(−βc_ij), doubly constrained (Furness). Target = combined transit AM (the 4 overlapping mode segments summed — one travel market; overlaps quantified up to 142k shared OD pairs). 2,886 zones, 124,788 trips (4.3% dropped for missing centroids, logged); β = 0.1022/km; mean trip length matched exactly (22.48 km). Fit: district R² 0.9995, cell-level R² 0.926, TLD coincidence 0.985, marginals preserved. K-factors: 6×6 quantile-grid districts, capped [0.25, 4]. Feeds Stage E cohorts. |
| — | **0.2c END-TO-END LOADING DONE 2026-08-08** (`run_build_0_2c_loading.py` → `build_0_2/loading/`): calibrated gravity OD loaded AON on the connected rail+bus graph (walk ≤800 m access/egress, wait = min(headway/2, 20'), declared veh caps rail 600 / bus 60). **Finding 1 — regional demand vs WMATA-only supply: only 35.3% of the 121k AM trips are servable; 64.7% have no walk access within 800 m** → the quantitative motivation for 0.3 (17 agencies). **Finding 2 — AON artifact made visible:** top "undersupply" hotspots are single-trip feeder-bus segments carrying ~650 riders (peak V/C 11.65) — uncapacitated one-path loading concentrates flow unrealistically; states on frequent services are meaningful, single-trip-segment V/C is a loading-method diagnostic, not a crowding prediction. 20,389 segments: 88.2% oversupply / 5.1% undersupply / 1.2% crowded. The acceptance chain Network → Connection → Path → Assignment is CLOSED on WMATA. | ✅ (Gate-0 path demo in 0.2b; P&R/K&R still pending parking elements) |
| — | Teaching corridor extract (D3 layer 1) committed as plain CSV | ☐ choose corridor (candidate: one Metro line + feeder buses) |

## Compressed schedule contract (built 2026-08-08, owner request)

`compact_store.py` → `build_0_2/compact/`: the time-expanded schedule
factorized into **run_profiles** (453: pattern + stop sequence + offset
vectors) + **frequency_blocks** (214 blocks of equal-headway departures,
covering 966 of 1,461 trips; only 73 distinct headway values exist, dominated
by clean 15/20/30/60-min) + **exceptions** (495 irregular departures kept
EXPLICITLY — the COVID schedule is irregular; nothing is forced into a
frequency that isn't there). Reconstruction is regenerated, not stored:
**round-trip verified LOSSLESS against Stage B** (script fails otherwise).
Size: 2.8× smaller than the already-zstd stage B parquet (≈30× vs raw CSV
when combined with the 10.9× parquet-zstd factor). Rule: compression is a
CONTRACT — factorize repeats, keep exceptions explicit, prove the round-trip;
never lossy, never silent.

**Reader/expander ships WITH the format** (decoder-next-to-encoder rule):
`compact_reader.py` — API (`load_trips`, `expand_stop_times`,
`trips_per_hour`, `period_capacity`) + CLI that writes the TAPLite-consumable
files into `build_0_2/expanded/`. Verified 2026-08-08: expansion reproduces
Stage B exactly (61,509 visits, 1,461 trips); `trips_per_hour.csv` schema is
an EXACT match to the BART engine's input; `period_capacity_td.csv` is
per-route-hour here (joins to ride links on directed_route_id once the DC
ride-link table exists — the BART file's extra link_id column is produced by
that join). `vehicle_capacity` is a declared parameter (default 750 service
capacity — same A1-register semantics as BART, must be restated per fleet).

## Open items / risks (marked upfront)

- **I-1 Feed vintage:** GTFS feeds are 2019–2021 (mixed). Fine for an
  interoperability gold, but the vintage per agency must be listed in the
  inventory; never present the merged network as a coherent single-date system.
- **I-2 Two GTFS collections exist** (`nvta_gmns_testbeds\Transit\GTFS_dataset`
  ~17 agencies vs `transit_schedule_column_generation_assignment\GTFS_DC` incl.
  VRE/AMTRK). Pick ONE canonical collection (recommend GTFS_DC — it is what the
  verified tooling reads) and record checksums.
- **I-3 Stage F (routing/assignment) is the pkg's last gated stage** — not yet
  exercised here; the TAPLite-side question (column export compatibility with
  the BART-style loading engine) is open.
- **I-4 The legacy 2021 outputs** (WMATA_Service link_performance etc.) are NOT
  comparable to the rebuild (different network representation, unknown demand);
  use only as qualitative sanity references, never as goldens.
