# The standard rerun recipe — L3 column warm start to a 0.1% gap

**Policy decision (2026-07): rerunning ANY model = L3 warm start with a 0.1%
relative-gap target.** This is the canonical recipe for every rerun — demand
edits, scenario screening, toll/VDF tweaks, gap-tightening continuations.
Kernel **cold-start defaults are unchanged**; this recipe is settings-only and
entirely opt-in.

## The recipe

**Step 0 (once per model): make the baseline run write its columns.**

```
column_output,2
```

The run writes `route_columns.bin` (DTAC v2: per-OD path sets with
theta shares — a demand-invariant routing policy). `column_output` is
leveled: `0` = off, `1` = DTAC v1 (last-iteration path only — light, fine for
route_assignment parity checks but a poor warm start: a v1 replay on Chicago
Sketch lands at a 9.1% TRUE gap where v2 lands at 0.13%, because one path per
OD cannot represent the FW blend), **`2` = DTAC v2 theta-share columns
(recommended for this recipe)**, `3+` = reserved for a future per-iteration
trace (currently warns and acts as 2).

**Step 1 (every rerun): warm-start from the columns, stop at 0.1%.**

```
warm_start_columns,route_columns.bin
convergence_gap_pct,0.1
column_adjust_sweeps,0
```

That is the whole recipe. The column scatter replays theta x the **current**
OD table onto the links, skips the iteration-0 all-or-nothing, and FW
continues; replay + FW reaches the 0.1% TRUE gap in **~1 iteration** on
SCAG-scale models (5 iterations / 0.15 s on Chicago Sketch — verified).
Leave `number_of_iterations` at its normal value — the gap target stops the
run.

The kernel always prints **both** gaps after a column warm start: the
RESTRICTED gap (stored paths only — not an equilibrium claim) and the TRUE
relative gap (fresh shortest paths, full route space). The 0.1% target is
judged on the TRUE gap.

## Why 0.1% — the SCAG same-gap evidence

SCAG RTP24 AM (246,806 links, 342,712 positive OD cells, perturbed demand
+5% x 1,000 OD cells), COMPUTE seconds to reach a TRUE-gap target
(cold FW run to 80 iterations; warm replay+FW to 40; GP points = final TRUE
gap of separate `column_adjust_sweeps=k` replay runs):

| target | cold FW | warm replay + FW | warm + GP sweeps | speedup (cold / best warm) |
|---|---|---|---|---|
| 0.10% | 101.7 s @ 15 it | 8.6 s @ 1 it | 0.7 s @ scatter | **139x** |
| 0.05% | 183.4 s @ 26 it | 28.5 s @ 6 it | 21.9 s @ 1 sweep | **8.4x** |
| 0.02% | not reached (80 it -> 0.036%) | not reached (40 it -> 0.033%) | 21.9 s @ 1 sweep | **only GP reaches it** |
| 0.01% | not reached | not reached | 21.9 s @ 1 sweep | **only GP reaches it** |

Figures (kernel repo): [`docs/l3_tradeoff_scag.png`](../../docs/l3_tradeoff_scag.png)
and [`docs/l3_tradeoff_sketch.png`](../../docs/l3_tradeoff_sketch.png)
(Chicago Sketch: 0.10% -> 4.8x, 0.05% -> 2.4x, 0.02%/0.01% -> GP only, 2-3
sweeps). The regime split is the headline of both: **plain FW — cold OR
warm-started — plateaus above ~0.03%** on these networks, while GP sweeps
over the stored columns pass 0.01% in 1-3 sweeps and keep going (SCAG
8 sweeps -> 7.6e-4%). At 0.1% the scatter alone is already below target, so
sweeps buy nothing there — hence `column_adjust_sweeps=0` in the standard
recipe.

## When to add sweeps

Only when the target is tighter than plain FW's plateau (~0.03-0.05%):

| target | setting |
|---|---|
| 0.1% (the standard) | `column_adjust_sweeps,0` |
| 0.05% | `column_adjust_sweeps,1` |
| 0.02% / 0.01% and below | `column_adjust_sweeps,1` (SCAG) to `3` (Sketch); FW cannot get there at all |

Sweeps are fixed-policy gradient-projection over the stored columns (no
shortest-path calls), Gauss-Seidel and serial by design; per-sweep cost
scales with the OD count (~23 s first sweep on SCAG's 343k ODs, ~60 s on
Chicago Regional's 2.3M). The per-sweep RESTRICTED gap is printed
before -> after each sweep.

## Accounting rule: setup vs compute

All numbers above are **COMPUTE seconds only**: AoN/FW/sweeps/shortest-path
work. SETUP — network + demand parse plus the one-time DTAC file load
(~4 s for SCAG's 1.21 GB store) — is excluded, because it is common to every
alternative and is addressed separately by the L4 DTST state snapshot (mmap,
planned). When you time your own reruns, use the kernel's phase-timing lines
(`phase timing: SETUP ... / DTAC column load ... / column scatter ...`) and
compare compute to compute.

## Guards (what happens when inputs drift)

- **Demand MAY differ from the stored fingerprint — that is the point.**
  Theta over a path set is a demand-invariant routing policy; the kernel
  prints both fingerprints and the OD/trip coverage %, then rescales
  theta x the current OD table.
- **Network edits**: paths crossing deleted links, links now banned for the
  mode, broken node chains, or now-banned movements are DROPPED (counted +
  warned) with theta renormalized over the survivors. OD pairs left with no
  usable column fall back to a one-shot AoN on the warm times (self-healing).
- **Bad file** (unreadable / wrong magic / mode-count mismatch / 0 usable
  paths): loud warning, cold start — a production run is never aborted by a
  warm-start hint. `warm_start_columns` takes precedence over
  `warm_start_flows`.
- CFW/BFW: the theta cascade is exact for plain FW; under CFW/BFW it is the
  same approximation `route_assignment.csv` already makes (loud warning).
  Direction history is reset on any warm start.

## Provenance

Measured results and methodology: `docs/KERNEL_FEATURE_CHANGES.md` (kernel
repo, "L3 full" + same-gap sections); generator `scripts/l3_tradeoff.py`;
panel design in [EFFICIENCY_STUDY.md](EFFICIENCY_STUDY.md). Regression: 30/30
checks pass, defaults-off outputs byte-identical to the pre-change kernel.
