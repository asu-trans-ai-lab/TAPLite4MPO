# Computational efficiency — industry panel study

Synthesis of five expert contributions (Caliper-class vendor, PTV/Visum-class vendor, open-source AequilibraE-class lead, Bar-Gera-tradition academic, HPC/systems engineer) on accelerating the TAPLite kernel. Ground truth: `kernel/src/TAPLite.cpp`, `KERNEL_FEATURE_CHANGES.md`, `shortest_path_benchmark.md`.

## Warm-start ladder

All five experts converged on a four-level ladder, one settings key `warm_start_level` (0=off), each level with a network fingerprint (n_links + hash of external link ids/capacity) and loud fallback logging to `summary_log_file.txt`. Universal rule: **reset CFW/BFW direction history (`g_cfw_nstored`) on any warm start** — conjugate directions from another problem are poison.

### L1 — Congested TIMES preload (all 5 endorse; ship first)
- **File**: existing `DTLP` (`link_output=3` `link_performance.bin`), bumped to v2 with external_link_id + network checksum; match by id, never row order.
- **Kernel**: after `InitLinks()` (~line 4463), overwrite `Link[k].Travel_time` before the first `FindMinCostRoutes`; call `UpdateLinkAdditionalCost()` so tolled networks seed correct generalized cost. Do NOT touch `MainVolume` — feasibility untouched; first AoN direction improves, nothing else changes.
- **Gain**: kills the free-flow iteration-1 disaster; 25–50% fewer iterations on congested reruns (SCAG 33 min → ~18–22 min). Zero risk — worst case a mediocre seed. **Effort: S** (~60 lines).
- Settings: `warm_start_level=1`, `warm_start_file=link_performance.bin`.

### L2 — FLOWS restart (Caliper, academic, HPC endorse with conditions; open-source dissents — see Dissents)
- **File**: new `DTLR`/`DTLF` binary — magic, version, checksum, n_links, n_modes; per link: external_link_id, from/to, `MainVolume`, per-mode volume, congested time. Writer `restart_output=1` at end of `AssignmentAPI()`.
- **Kernel**: load into `MainVolume`/`mode_MainVolume` in `InitLinks()`; `UpdateLinkCost()`; skip iteration-0 AoN. **Only valid when demand is identical (enforce via demand hash) OR paired with difference assignment** — the existing `base_demand_mode=1` + `DiffODtable` plumbing (line ~3619, `<demand>_base.csv`) is exactly this contract; generalize it from link.csv text columns to the binary file. Any deleted link carrying baseline flow auto-demotes to L1 (log loudly).
- **Gain**: identical-demand reruns (VDF recalibration, toll tweaks, gap-tightening continuation): 2–4x. Demand deltas 5–15% with diff assignment: ~1/3 the iterations. **Effort: M.**
- Docs note (panel consensus): `base_demand_mode` as shipped is pivot-point/incremental assignment on observed counts, not an equilibrium warm start — position it honestly.

### L3 — Binary COLUMN store + demand-delta adjustment (all 5: "the strategic asset")
- **File**: `DTAC`/`DTPC` — magic, version, checksum, n_modes, n_zones, n_paths; sparse CSR over positive-demand OD pairs only: `od_ptr` → per-path (`theta` float32, n_links) → concatenated int32 link stream. SCAG estimate ~1–3 GB. Settings: `column_output=1` (or `route_output=3`), `warm_start_level=3` + `column_input`.
- **Kernel**: (a) replace the 5D nested `linkIndices` vector (line 1330) with this CSR pool in memory — fixes the known route_output memory hazard, 10–50x smaller; all consumers (`OutputRouteDetails` 2229, `OutputVehicleDetails` 2463, `OutputODPerformance` 2687, aggregation 2878, ODME walks 1716–2086) convert mechanically; theta becomes per-OD, not global. (b) Loader: drop paths touching deleted/banned links (renormalize theta), rescale `theta * newOD` per pair, parallel scatter to `MainVolume`, resume FW.
- **Why gold standard** (unanimous): theta over a path set is a demand-INVARIANT routing policy — replay against any new OD table is exactly feasible per OD pair, which neither times nor raw flows can promise. This is the user's "routing policies waiting for demand changes," made rigorous.
- **Fixed-policy flow adjustment** (`column_adjust_sweeps`, default 3 at L3): gradient-projection sweeps over stored columns using `Link_GenCostDer` (~5061) — shift theta from costlier to cheapest path, no SP calls; then FW's first AoN acts as the pricing step. Report "restricted gap" vs "full gap" separately in the summary log — never let restricted masquerade as UE.
- **Gain**: demand-only deltas start at ~1e-2..1e-3 gap; 3–8 polish iterations replace 20–40 cold (4–8x, SCAG 33 → 5–6 min). Free bonuses: select-link, exact path skims, vehicle_output without rerun. Academic adds: GP polish on columns breaks the BFW 1e-4 plateau → 1e-6 in ~10–20 sweeps. **Effort: L** (touches every linkIndices consumer; 13-network regression + route CSV byte-diff required).
- **Freeze mode** (`policy_replay=1` / `warm_start_columns=2`): zero FW iterations, pure replay — 30–50x for scenario screening; error second-order in demand perturbation; mandatory fresh-SP gap report attached.

### L4 — Full binary state snapshot (HPC; others neutral)
- **File**: `DTST` — mmap-able, 64-byte-aligned, section table (tag, offset, length, crc32): [NETW] forward-star CSR + SoA link fields, [DMND] embedded DTAB, [VOLS], [TIME], [COLS]=DTAC, [META] settings+demand hashes + iteration/gap. Settings: `state_file`, `state_mode=0/1/2`.
- **Kernel**: on hash match, bypass `ReadLinks`/`Read_ODtable` entirely — pointer-cast arrays from the mapping. Kills the input phase: minutes of CSV parse → ~100 ms.
- **Gain**: 1.5–2x on short runs and Python-driven sweeps (pytaplite re-parses per run today); substrate for L1–L3. **Effort: M** (~600 lines; Windows file-mapping lifetime care).

**Resolution order at startup**: valid DTAC → L3; else valid DTLR → L2; else valid DTLP → L1; else free-flow. Every decision + id-match rate logged.

## Multi-class engineering

**Decision rule (unanimous, exact — not heuristic)**: two classes need separate SP trees **iff** their `mode_allowed_use[m][k]` masks or per-link `mode_AdditionalCost[m][k]` vectors differ anywhere. PCE and occupancy NEVER force a dedicated tree — they enter loading and gap weighting only. Since AdditionalCost = (toll + length·operating_cost)/VOT, VOT without a money term is a routing no-op: untolled sov/hov2/hov3 collapse to one tree automatically.

- **Auto-preset detection**: after `read_mode_type_file()`/`UpdateLinkAdditionalCost()`, hash per mode (allowed_use bitset, AdditionalCost array); equal hash → exact byte-compare → same group. Settings: `sp_tree_dedup` / `sp_preset=auto|manual` (default = honor user flags until regression re-baseline). Must compare the full AdditionalCost vector — one HOT-lane `toll_sov` entry legitimately splits SOV from HOV; column-presence heuristics corrupt class flows silently.
- **Generalize the existing hook**: `dedicated_shortest_path=0` currently hardcodes "reuse mode 1" (`FindMinCostRoutes` ~770, `All_or_Nothing_Assign` mpred ~1482/1503). Replace `MinPathPredLink[1]` with `MinPathPredLink[rep_mode[m]]` / `share_with_mode`. `dedicated_shortest_path=1` stays as manual opt-out.
- **Batching**: flatten to one dynamically-scheduled OpenMP loop over (group, origin); consume the shared tree for all group members while hot in per-thread `InitSPScratch` cache. HPC adds: ONE back-trace walk per shared tree accumulating all member modes' OD flows (PCE applied at the accumulate step) instead of M walks.
- **PCE aggregation**: unchanged — per-class volumes, PCE weighting, per-class tolls in the gap denominator stay exact; sharing trees must never blur class accounting.
- **Always log the grouping** ("sov/hov2/hov3 share tree of sov; trk dedicated — allowed_use differs on 2,895 links") — silent cleverness loses MPO trust (all 5 experts said this).
- **Gain**: SP cost scales with GROUPS not classes; the agency 6 modes → 2–3 groups → SP phase 2–3x, bit-identical results. **Effort: S–M.**

## Other high-value techniques

- **Zero-demand-origin skip** (3 experts; already in benchmark further-work): precompute `active[m][O]` from MDODflow row sums after `Read_ODtable`; skip SP for inactive origins; bucket only active origins with `schedule(dynamic)`. Exact; 10–30% on sparse statewide/superzone demand, 5–20x on delta-demand reruns. Gap accounting for skipped origins needs cached full-tree cost or periodic full-SP audit. Effort: S.
- **Generation-stamped label reset** (3 experts): `int32 gen[]` in `InitSPScratch` scratch; `CostTo[i]` valid iff `gen[i]==current` — kills the O(n) memset per Minpath call. 5–15% of SP wall on 77k-node nets; apply to `Minpath`, `Minpath_Dijkstra`, `Minpath_TR` alike. Effort: S; silent-wrong-cost risk → guard with cost cross-check + 13-network regression.
- **SoA generalized-cost arrays** (HPC): build flat `gencost_m[k]` + `link_to[k]` once per iteration in `UpdateLinkCost` instead of striding the fat `link_record` in the relax loop. 1.3–1.8x on the memory-bound SP phase. Effort: S.
- **Settled-zone early exit** (HPC): pop-terminate Dijkstra when all zone centroids are settled. 10–30% where zones << nodes. Effort: S.
- **Per-thread SP-tree reuse across iterations** (HPC): skip recompute for origins whose incident cost deltas < `sp_tree_reuse_eps`; late FW iterations skip 50–90% of solves. Ships default-off (changes iterates slightly). Effort: M.
- **Superzone two-stage seeding** (4 experts): Python-only given L1 — `superzone_hier.py` compact run (~15 iters, `link_output=3`), physical links identical so DTLP fingerprint matches by construction; full run starts at `warm_start_level=1` (connectors fall back to FFTT). SCAG 33 → ~12–18 min with the EXACT full answer. Expose as `dtalite_qa run --two-stage S=1000`. Column prolongation (splice connectors onto superzone paths → full DTAC) is the L version. Effort: S–M.

## Recommended sequence

Consensus first move: **L1 times preload + SP-equivalence auto-detection** — both small, both exact, both compound with everything later.

- **P0 (days, S)**: L1 DTLP preload; SP-tree dedup fingerprint + `rep_mode` generalization of the hardcoded mode-1 reuse; zero-demand-origin skip; generation stamps. All bit-exact or feasibility-safe.
- **P1 (1–2 weeks, M)**: L2 DTLR restart wired to the existing `base_demand_mode`/DiffODtable diff-assignment plumbing; superzone two-stage flag in `dtalite_qa`; SoA cost arrays + settled-zone exit.
- **P2 (multi-week, L)**: the DTAC CSR column store replacing 5D `linkIndices` (also fixes the route_output memory hazard) → L3 rescale-restore, fixed-policy flow adjustment / freeze mode, GP polish, select-link. P2 is the roadmap centerpiece — every expert independently called columns the strategic asset.
- **P3 (optional, M)**: DTST full-state mmap snapshot for input-phase elimination in pytaplite sweep workflows.

## Dissents

- **Link-flow warm start (L2)**: open-source expert rejects the rung outright for UE work ("breaks the convex-combination-of-AoN invariant; the gap can go negative; document base_demand_mode as not-a-warm-start"); Caliper/academic/HPC accept it strictly gated — identical-demand hash OR mandatory difference assignment, auto-demote on network edits. Resolution: ship gated, docs call `base_demand_mode` incremental/pivot-point assignment.
- **How much L1 buys**: academic is the skeptic ("FW's rate is governed by feasible-region geometry, expect 2–5 iterations, not a transformation") vs open-source/HPC ("halves iterations"). All still say ship it — the disagreement is magnitude, not direction.
- **Persisting SP trees/policies per se**: rejected by Caliper and HPC ("a tree is one cost snapshot per origin, strictly dominated by columns; goes stale after one cost update"). Columns-with-theta won unanimously as the persistence currency.
- **Bush-based rewrite (Algorithm B/TAPAS) vs FW+warm-start**: nobody advocated the rewrite. The academic explicitly positions GP polish on stored columns as "bush-method-class precision without becoming Algorithm B"; likewise bicriteria/VOT-parameterized SP for tree sharing across tolled classes was named and rejected as disproportionate for a single-file link-based FW kernel.
- **Parallelizing GP sweeps**: academic recommends serial sweeps (shared-link write hazards; one serial sweep beats five plateau FW iterations); Caliper/PTV sketch origin-parallel with per-thread accumulators. Start serial, parallelize if profiled as the bottleneck.
- **Freeze-mode positioning**: PTV/open-source insist on a mandatory fresh-SP gap report so replay output is never mistaken for equilibrium; HPC would drop pure policies-only replay entirely. Resolution: ship as a mode of L3 with the gap report non-optional.
