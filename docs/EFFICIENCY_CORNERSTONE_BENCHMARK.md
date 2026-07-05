# The 4-network cornerstone efficiency benchmark — L1/L2/L3 warm-start ladder

**One consolidated benchmark of the warm-start ladder (L1 congested-times /
L2 flow-snapshot / L3 theta-share columns) across a size ladder of four
cornerstone networks.** It answers a single question for the TAPLite4MPO
rerun recipe: *when a planner reruns a model with edited demand, how much
compute does each warm-start level save, and where does each level's regime
end?*

Companion to `docs/KERNEL_FEATURE_CHANGES.md` ("L3 full" + same-gap sections)
and `github_taplite/docs/RERUN_RECIPE.md` (the canonical
`warm_start_columns` + `convergence_gap_pct,0.1` recipe). Kernel code is
unchanged; every number here is settings-only and reproducible from the
`release_v0.2.0/DTALite.exe` binary.

## Accounting rule (read this first)

Per the user rule, **all speedups are on COMPUTE seconds** — the
AoN / FW / GP-sweep / shortest-path work the kernel times from its post-parse
`start` anchor (the per-iteration `elapsed = X s` print). **SETUP** (network +
demand parse + allocations) and the one-time **DTAC column-file load** are
reported as their own columns and never folded into a speedup, because they
are common to every alternative and are addressed separately (the planned L4
mmap state snapshot). The kernel prints all three:
`phase timing: SETUP ... = X s`, `DTAC column load + pool build (SETUP) = X s`,
`column scatter ... (COMPUTE) = X s`, plus per-iteration `elapsed`.

## The four cornerstone networks (size ladder)

| # | network | nodes | links | zones | OD cells | classes | cold solve to its plateau (COMPUTE) |
|---|---|---:|---:|---:|---:|---:|---|
| 1 | Chicago Sketch    | 933    | 2,950   | 387    | 93,513  | 3 (1 populated) | 0.4 s @ 25 it → 0.10% |
| 2 | Chicago Regional  | 12,982 | 39,018  | 1,778  | 2.30 M  | 1 | 66.4 s @ 39 it → 0.69% (plateau > 0.1%) |
| 3 | ARC Atlanta       | 66,546 | 145,971 | 6,031  | 1.42 M  | 3 | 488.6 s @ 14 it → 0.159 % (0.10 % not reached; warm is) |
| 3b| ARC super-zone (subarea) | 67,977 | 158,033 | 1,431 | 564,882 | 3 | 164.6 s @ 14 it → 0.177 % (0.10 % not reached; warm L1/L2 are) |
| 4 | SCAG RTP24 AM     | 76,616 | 246,806 | 11,259 | 342,712 | 1 | 101.7 s @ 15 it → 0.10% |

*Basis note: rows 1, 2, 4 are unperturbed cold solves; rows 3 and 3b quote the
perturbed rerun-cold (the "to beat" run of the A/B protocol) — each section's
table states its own basis.*

- **Chicago Sketch** (`kernel/data_sets/03_chicago_sketch`) and **SCAG**
  (`private/SCAG/scag_daily/AM`) numbers are **reused** from the same-gap study
  already recorded in `KERNEL_FEATURE_CHANGES.md` (SCAG 139×@0.10%, etc.);
  their inputs are byte-identical to the runs there.
- **Chicago Regional** and **ARC Atlanta** are **new** full L1/L2/L3 runs done
  for this benchmark, plus an **ARC super-zone subarea** case.

"Plateau" matters: on the dense-demand regional networks (CR, and the
tighter ARC targets) plain Frank-Wolfe — cold **or** warm-started — does not
push below ~0.5–0.7% in any comparable budget. The 0.1% target is reachable
by FW only on the sketch-scale (CS) and long-path sparse-OD (SCAG) networks;
on CR the "cold solve" column shows the reachable plateau, and the tight
targets are a **GP-sweep-only** regime (documented per-network below).

## Rerun protocol (networks 2, 3, 3b)

1. **Baseline COLD** run with `flow_snapshot=1` + `column_output=2` +
   `link_output=2` → writes `link_performance.csv` (L1 source),
   `link_flows.bin` / DTLR (L2 source), `route_columns.bin` / DTAC v2 (L3
   source).
2. **Perturb demand**: deterministic +5 % on ~2 % of positive OD cells (seeded
   md5 hash of `(o,d)` — identical selection every run, file-order-independent;
   `scratchpad/bench/perturb.py`). This is the "planner rerun" case. (One
   honest footnote: the rewrite formats every cell with `%.6g`, so unperturbed
   cells with >6 significant digits are micro-truncated too; A/B fairness holds
   because the cold rerun reads the identical file, and the total-volume delta
   matches the design intent, ≈ +0.10 %.)
3. **Four reruns** of the perturbed demand to `convergence_gap_pct=0.1`
   (capped iterations), timing each:
   - **COLD** (baseline to beat),
   - **L1** `warm_start_times = <baseline link_performance>`,
   - **L2** `warm_start_flows = <baseline link_flows.bin>`,
   - **L3** `warm_start_columns = <baseline route_columns.bin>`,
     `column_adjust_sweeps=0`.

L2's demand fingerprint is deliberately flipped by the perturbation → the
kernel demotes L2 to L1-behavior (times-only seed). Reporting that demotion is
a **valid interface test** and is called out per network.

---

## Network 2 — Chicago Regional (NEW)

12,982 nodes / 39,018 links / 1,778 zones / **2.30 M positive OD cells**
(near-dense), single class, plain FW. Perturbation touched **46,170 cells
(2.01 %)** ×1.05.

**A/B rerun table** (perturbed demand; target 0.1 %, 25-iteration cap; COMPUTE
seconds are the speedup basis, SETUP + DTAC-load shown separately):

| rerun | SETUP | DTAC load | COMPUTE | iters | TRUE gap | note |
|---|---:|---:|---:|---:|---:|---|
| baseline COLD (full, writes snapshot+cols) | 4.71 s | — | 66.4 s | 39 | 0.687 % | writes `route_columns.bin` = **5.60 GB** |
| rerun COLD           | 4.04 s | — | **22.9 s** | 24 | 1.481 % | to beat |
| rerun L1 (times)     | 4.58 s | — | 23.6 s | 24 | **0.617 %** | same compute, **2.4× lower gap** |
| rerun L2 (flows→L1)  | 3.89 s | — | 22.8 s | 24 | **0.573 %** | fingerprint flipped → demoted to L1 (verified) |
| rerun L3 (cols, 0 sweeps) | 4.10 s | 17.5 s | 31.7 s | 24 | **0.634 %** (restricted 0.498 %) | load-dominated at 2.3 M ODs |

**Regime finding (CR): equal-compute, not equal-gap.** At CR's near-dense
demand, plain FW plateaus around 0.5–0.7 %; **neither cold nor any warm level
reaches 0.1 % in 25 iterations**. So the win shows up as *gap at equal
compute*: for the same ~23 s of FW, the L1/L2 warm start lands at 0.57–0.62 %
where cold is still at 1.48 % — a **2.4–2.6× lower gap** for free. L2's
fingerprint flips (perturbed demand) and it correctly demotes to the L1
times-only seed — that is why L1 and L2 land within 0.044 % of each other.

**L3 at CR is load-dominated.** The DTAC v2 store is **5.60 GB** (2.30 M ODs,
~11 paths/OD → ~1.34 B link entries — the file is demand-proportional, not
network-proportional). Its 17.5 s load is SETUP, and with 0 sweeps the replay
lands at the same plateau as cold-restart (true 0.634 %). L3's payoff on CR is
**not** the 0-sweep replay — it is the GP sweeps, which are the only mechanism
that breaks the plateau (crossing table below).

**Same-gap crossing table (CR).**
All runs on the perturbed demand; COMPUTE excludes SETUP and the DTAC load
(warm elapsed clocks include the load, so it is subtracted out). Cold FW ran to
a 60-iteration budget (59 executed), warm replay+FW to 30 (29 executed), and
the GP points are freeze/replay runs (`number_of_iterations=0`) at
`column_adjust_sweeps = k`:

| TRUE-gap target | cold FW | warm replay+FW | warm+GP sweeps | speedup (cold / best warm) |
|---|---|---|---|---|
| 0.60 % | 43.9 s @ 42 it | **7.1 s @ 2 it** (0.590 %) | overshoots (1 sweep → 0.155 %) | **6.2×** |
| ~0.50 % (FW floor) | 58.1 s @ 53 it (0.492 %, then plateaus 0.502 %) | 46.0 s @ 29 it (0.498 %) | 139.3 s @ 1 sweep → 0.155 % | 1.3× (both at the floor) |
| 0.10 % | **not reached** (59 it → 0.502 %) | **not reached** (29 it → 0.498 %) | **190.7 s @ 2 sweeps → 0.068 %** | GP only |
| 0.05 % | not reached | not reached | **239.9 s @ 5 sweeps → 0.032 %** | GP only |
| 0.02 % / 0.01 % | not reached | not reached | **not reached** (8 sweeps / 364.8 s → 0.0223 %) | — |

Two CR-specific corrections to the general narrative: (1) the warm start's
loose-target win is real here too — at 0.60 % the replay+FW is **6.2×** faster
than cold; (2) the GP sweeps break the ~0.50 % FW floor decisively (2 sweeps →
0.068 %) **but grind slowly after that** — on this near-dense demand 8 sweeps
still sit at 0.0223 %, so CR does *not* pass 0.01 % in the captured budget
(unlike SCAG/Sketch). Sweep-1 costs **115–135 s** and later sweeps 26–55 s
(measured across the five sweep runs).

Figure: [`docs/l3_tradeoff_cr.png`](l3_tradeoff_cr.png).

---

## Network 3 — ARC Atlanta (NEW, 3-class calibrated)

66,546 nodes / 145,971 links / 6,031 zones / **1.42 M OD cells** across 3
classes (SOV / HOV2 / HOV3), agency-calibrated AM. Perturbation +5 % on ~2 %
of cells in each class file.

**A/B rerun table** (perturbed demand; target 0.1 %, capped iterations; COMPUTE
seconds are the speedup basis, SETUP parse + DTAC-load shown separately):

| rerun | SETUP | DTAC load | COMPUTE | iters | TRUE gap | note |
|---|---:|---:|---:|---:|---:|---|
| baseline COLD (full, writes snapshot+cols) | 9.61 s | — | 649.4 s | 19 | 0.164 % | writes `route_columns.bin` = **2.51 GB** (3.6 M paths) |
| rerun COLD           | 10.20 s | — | **488.6 s** | 14 | 0.159 % | to beat (**0.10 % not reached** in 14 it) |
| rerun L1 (times)     | 9.26 s | — | 294.4 s | 8 | **0.093 %** | 14 → 8 iters → target met, **1.66×** |
| rerun L2 (flows→L1)  | 14.80 s | — | 308.0 s | 8 | **0.094 %** | fingerprint flipped → demoted to L1 (L1≈L2 within 0.001 %) |
| rerun L3 (cols, 0 sweeps) | 10.87 s | 9.81 s | **60.8 s** | 1 | **0.092 %** | scatter 1.62 s + 1 FW iter → **8.0×**, *tighter than cold* |

**Regime finding (ARC): the clean warm-start win — faster AND tighter.** All
three warm levels reach **~0.09 %**, below the 0.10 % target that cold FW does
**not** hit in 14 iterations (it plateaus at 0.159 %). L1/L2 cut the iteration
count from 14 to 8 for a **1.66×** compute gain at a better gap. **L3 is the
headline: the θ-column scatter lands at 0.092 % after a *single* Frank-Wolfe
iteration — 60.8 s of compute versus cold's 488.6 s = 8.0× on compute, at a
tighter gap.** L2's demand fingerprint is flipped by the perturbation and it
correctly demotes to the L1 times-only seed (that is why L1 and L2 land within
0.001 % of each other — the interface test passes). Unlike Chicago Regional,
ARC's 3-class 1.42 M-OD demand is sparse *per class*, so the 0-sweep replay
already clears the target — **no GP sweeps needed** here. The 2.51 GB DTAC store
loads in **9.81 s** (SETUP, not folded into the speedup).

**Same-gap crossing (ARC)** — a full per-iteration trace was not captured for
ARC, so the crossing is stated from the rerun **endpoints** (target 0.10 %):

| target | cold FW | warm L1 | warm L3 | speedup (cold / best warm) |
|---|---|---|---|---|
| 0.10 % | **not reached** (14 it / 488.6 s → 0.159 %) | 294.4 s @ 8 it → 0.093 % | **60.8 s @ 1 it → 0.092 %** | cold never reaches it in-budget; L3 gets there **≥ 8.0×** faster than cold's 488.6 s plateau |

*(No `l3_tradeoff_arc.png` — the ARC per-iteration trace runs were not executed;
the endpoint crossing above is the honest ARC result. CR, Sketch, and SCAG
figures exist.)*

### Network 3b — ARC subarea (super-zone aggregation)

The **subarea performance case** uses ARC's own super-zone aggregation
(`examples/arc_atlanta/arc_superzone.py`, K≈1,431): the **full 145,971-link
network is preserved** (+ super-connectors → 158,033 links) while origins are
compressed 6,031 → **1,431 super-zones** (4.2× fewer SP trees). This documents
that L1/L2/L3 work unchanged on aggregated / subarea networks — the warm-start
artifacts key on external link ids and a demand-invariant routing policy, both
of which survive origin aggregation. (A geographic window cut was available but
the super-zone build already existed and exercises the same code path with a
cleaner apples-to-apples full-network link set.)

**A/B rerun table** (super-zone-aggregated demand, 564,882 OD cells; perturbed
+5 % on ~2 % of cells per class; target 0.1 %):

| rerun | SETUP | DTAC load | COMPUTE | iters | TRUE gap | note |
|---|---:|---:|---:|---:|---:|---|
| baseline COLD (writes snapshot+cols) | 3.73 s | — | 186.9 s | 19 | 0.152 % | `route_columns.bin` = **1.13 GB** |
| rerun COLD           | 3.81 s | — | **164.6 s** | 14 | 0.177 % | to beat (0.10 % not reached in 14 it) |
| rerun L1 (times)     | 3.77 s | — | 76.5 s | 7 | **0.098 %** | 14 → 7 iters → target met, **2.15×** |
| rerun L2 (flows→L1)  | 5.30 s | — | 67.4 s | 7 | **0.098 %** | fingerprint flipped → demoted to L1 (L1≈L2) |
| rerun L3 (cols, 0 sweeps) | 3.63 s | 2.96 s | **29.2 s** | 3 | 0.105 % (restricted 0.084 %) | scatter + 3 FW → **5.6×**, *just above* target |

**The subarea result is the same regime as full ARC — the ladder is
aggregation-invariant.** Origin aggregation 6,031 → 1,431 super-zones makes the
*cold* solve ~3.0× cheaper (164.6 s vs full ARC's 488.6 s — fewer SP trees), but
every warm level keeps working with **no code or artifact change**: L1/L2 reach
the 0.10 % target in 7 iterations (**2.15–2.44×**), and **L3's θ-column replay
lands at TRUE gap 0.105 % after 3 Frank-Wolfe iterations — 29.2 s compute +
2.96 s DTAC load vs cold's 164.6 s = 5.6×.** By this document's TRUE-gap
standard L3 finishes *just above* the 0.10 % target (only its restricted gap,
0.084 %, is below) — the honest statement is that L1/L2 meet the target and L3
gets within 5 % of it at a third of their compute. L2's demand fingerprint flips
on the perturbed demand and it correctly demotes to L1 (7 it, within 0.001 %) —
the same interface test as full ARC, passing on the aggregated network. This is
the point of the subarea case: the warm-start artifacts key on **external link
ids** and a **demand-invariant routing policy**, both of which survive origin
aggregation, so subarea / super-zone models inherit the full ladder unchanged.
The DTAC store (1.13 GB) is proportional to the 0.56 M aggregated OD cells, not
to the preserved 158,033-link network — consistent with the
store-scales-with-OD law below.

---

## Network 1 — Chicago Sketch (REUSED)

387 zones / 2,950 links / 3 modes / 93,513 OD cells, plain FW. From
`KERNEL_FEATURE_CHANGES.md` "L3 full" evidence + the same-gap study
(`docs/l3_tradeoff_sketch.png`):

| quantity | value |
|---|---|
| DTAC v2 store | 18.0 MB (3.1× smaller than route_assignment.csv 55.1 MB) |
| replay push-down vs cold | R² = 1.000000, max |diff| 0.00 veh (exact by construction) |
| perturbed +5 %×1,000: cold 20-it | 0.7 s → gap 0.173 % |
| perturbed: warm (sweeps=5, 3 it)  | 1.0 s → TRUE gap **0.0028 %** (**62× tighter** at comparable wall) |
| same-gap 0.10 % | cold 0.4 s @ 25 it vs warm+FW 0.1 s @ 5 it → **4.8×** |
| same-gap 0.05 % | cold 0.6 s @ 35 it vs warm+FW 0.2 s @ 16 it → **2.4×** |
| same-gap 0.02 % / 0.01 % | FW (cold+warm) plateau ~0.028–0.030 %; **GP sweeps only** (2–3 sweeps, ~0.4 s) |

## Network 4 — SCAG RTP24 AM (REUSED)

76,616 nodes / 246,806 links / 11,259 zones / 342,712 OD cells, plain FW.
From `KERNEL_FEATURE_CHANGES.md` + `docs/l3_tradeoff_scag.png` (perturbed
demand +5 %×1,000; COMPUTE seconds; SETUP + DTAC load excluded):

| run | SETUP (parse + DTAC load) | COMPUTE | TRUE gap | R² vs cold-pert |
|---|---|---:|---:|---:|
| cold 20 iters | 2.7 s | **94.8 s** | 0.0778 % | — |
| warm, 0 sweeps + 3 it | 2.9 + 4.1 s | **16.3 s** | **0.0592 %** | 0.9998 |
| warm, 5 sweeps + 3 it | 2.8 + 4.1 s | **82.6 s** | **0.00107 %** | 0.9994 |

Same-gap crossing (`docs/l3_tradeoff_scag.png`):

| target | cold FW | warm replay+FW | warm+GP sweeps | speedup (cold / best warm) |
|---|---|---|---|---|
| 0.10 % | 101.7 s @ 15 it | 8.6 s @ 1 it | 0.7 s @ scatter | **139×** |
| 0.05 % | 183.4 s @ 26 it | 28.5 s @ 6 it | 21.9 s @ 1 sweep | **8.4×** |
| 0.02 % | not reached (80 it → 0.036 %) | not reached (40 it → 0.033 %) | 21.9 s @ 1 sweep | only GP reaches it |
| 0.01 % | not reached | not reached | 21.9 s @ 1 sweep | only GP reaches it |

---

## The honest regime finding (all four networks)

Two distinct regimes, both real, and the crossing tables make the boundary
explicit:

1. **Loose targets (≥ ~0.05 %) → warm replay dominates.** The column scatter
   (or even the L1/L2 times/flows seed) starts the rerun *at or below* the cold
   run's final gap. At 0.10 %, SCAG is **139×** faster on compute, ARC **8.0×**,
   and Chicago Sketch **4.8×**; the scatter alone is already below target so
   **sweeps buy nothing** — hence `column_adjust_sweeps,0` in the standard
   recipe. On the near-dense regional demand (Chicago Regional) FW cannot reach
   0.10 % at all, but the warm start still wins at reachable targets (**6.2×**
   at 0.60 %) and halves the gap at equal compute.

2. **Tight targets (≤ ~0.03 %) → GP columns reach what FW cannot.** Plain
   Frank-Wolfe — cold **or** warm-started — plateaus above ~0.03 % on every one
   of these networks. The fixed-policy gradient-projection sweeps over the
   stored columns (no new shortest-path calls) are the only mechanism that gets
   below: SCAG and Sketch pass 0.01 % in 1–3 sweeps and keep going (SCAG
   8 sweeps → 7.6e-4 %). On the **near-dense CR the sweeps grind slower** —
   2 sweeps break the FW floor decisively (0.068 %) but 8 sweeps still sit at
   0.0223 %, so 0.01 % is *not* reached there in the captured budget. Tight
   targets are unreachable by FW in any comparable budget; only the columns get
   there, and their per-sweep progress slows with demand density.

## Scale trend (Sketch → Regional → ARC → SCAG)

| effect | Sketch | Chicago Regional | ARC | SCAG |
|---|---|---|---|---|
| OD cells | 93 k | 2.30 M | 1.42 M | 343 k |
| DTAC v2 size | 18 MB | **5.60 GB** | 2.51 GB | 1.21 GB |
| DTAC load (SETUP) | <1 s | 17.5 s | 9.8 s | ~4 s |
| GP sweep cost (1st sweep) | ~0.1 s | ~130 s (later sweeps 26–55 s) | n/a (0-sweep clears target) | ~23 s |
| L3 same-gap speedup @0.10 % | 4.8× | GP-only (190.7 s @ 2 sweeps) | **≥ 8.0×** | 139× |

(File sizes are decimal GB/MB throughout.)

Two scaling laws fall out:

- **The DTAC store and the serial GP-sweep cost scale with OD-cell count, not
  network size.** Chicago Regional (2.30 M ODs) has the *biggest* store (5.6 GB)
  and the *most expensive* sweeps (~130 s for sweep 1) despite being ~6× smaller
  than SCAG in links — because its demand is near-dense (~11 paths/OD → 1.34 B
  stored link entries). SCAG's 343 k sparser (but longer-path) ODs give a 1.2 GB
  store and ~23 s sweeps. This is the dominant cost at ≥2 M ODs and is the next
  lever (parallelize the serial sweeps).
- **The warm-replay speedup grows with the cold cost.** The looser-target
  speedup is largest where the cold FW is most expensive per iteration and the
  scatter lands closest to the answer — SCAG's 139× vs ARC's 8.0× vs Sketch's
  4.8× at 0.10 %. On the near-dense CR the FW curve is so flat that "speedup at
  a fixed target" degenerates near the floor; the honest statements there are
  the 6.2× at the reachable 0.60 % target, the equal-compute gap reduction
  (2.4–2.6×), and GP-only access to tight gaps.

*(Note on the reused Sketch/SCAG ratios: 139×, 4.8×, 2.4× etc. are carried
verbatim from the same-gap study in `KERNEL_FEATURE_CHANGES.md`, computed from
its unrounded timings; recomputing from the rounded values printed in these
tables gives slightly different figures (e.g. 145×, 4.0×).)*

## Caveats

- **Perturbed-demand reruns are the "planner rerun" case** — a small
  deterministic demand edit, not a from-scratch build. The warm-start artifacts
  are keyed to the baseline network topology; large network edits fall back to
  self-healing (dropped paths + one-shot AoN), which is a different (and slower)
  case not measured here.
- **Demand provenance differs by network**: ARC and SCAG use agency demand;
  Chicago Regional uses its own bundled demand; the ARC subarea (3b) uses the
  super-zone-aggregated demand (564,882 OD cells) — intra-super-zone trips are
  dropped by aggregation, a property of the subarea method, not the warm start.
- **Compute vs setup accounting is stated on every number**: speedups are
  COMPUTE-only; SETUP and DTAC-load are separate columns. The DTAC-load cost is
  real and grows with OD count — L3's break-even shifts toward looser targets
  and bigger models where the FW it replaces is expensive enough to dwarf the
  load.
- **L2 fingerprint demotion is expected** on any perturbed rerun and is
  reported as a feature (loud warn → L1 behavior), not a failure.
- Regression suite unaffected: no kernel code touched (benchmark is
  settings-only + a script extension to `scripts/l3_tradeoff.py`).

## Reproduce

```
# per new network: baseline cold (snapshot+cols) -> perturb -> cold/L1/L2/L3 reruns
python scratchpad/bench/bench_network.py chicago_regional
python scratchpad/bench/bench_network.py arc_atlanta
python scratchpad/bench/bench_network.py arc_superzone
# same-gap trace runs + figure
python scratchpad/bench/trace_runs.py chicago_regional 60 30 1,2,3,5,8
L3_RUN_ROOT=scratchpad/bench/runs/chicago_regional/trace \
  L3_DOCS_DIR=docs python scripts/l3_tradeoff.py cr
```
(Harness lives in the session scratchpad; agency data stays local.)
