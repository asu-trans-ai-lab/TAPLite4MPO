# CR-0016 — All_or_Nothing_Assign route-store hot loop: remove omp critical + quadratic copy

**Status:** COMMITTED (local branch) · **Date:** 2026-08-10
**Source:** external tree-route-pool package patch
`0001_fix_legacy_route_hotloop.diff`, independently confirmed against our
own code and our own regional timing evidence.
**Kernel change:** YES (performance only — assignment numerics unchanged)

## Problem (two defects in the same 20 lines)

Inside the per-hop back-trace loop of `All_or_Nothing_Assign`:

1. **`#pragma omp critical` around a thread-local vector.**
   `currentLinkSequence` is declared inside the origin-parallel region and
   belongs to exactly one worker, yet every `push_back` took a global
   critical section — serializing all threads on every hop of every path.
2. **`AddLinkSequence()` called INSIDE the hop loop.** The complete path is
   only known after the loop; calling the store per hop re-copied the
   growing vector every time — quadratic in path length. On NVTA (avg 71
   links/path) that is ~2,500 int copies per path instead of 71.

Measured consequence before the fix (NVTA regional PM, 49,329 links /
3,858 zones / 6 modes, 16 cores): **~5.5 min per FW iteration with route
output on, vs ~15 s with it off** — a ~22x penalty that made full-iteration
regional path extraction impractical.

## Change

Push the link index without any critical section; call `AddLinkSequence`
exactly once, after the back-trace completes. Guard conditions unchanged
(`linkIndices.size() > 0 && (shortest_path_log_flag || iteration == 0)`).

## Verification — MEASURED

Regional NVTA PM, identical inputs/settings/exe-except-this-fix, 16 cores:

| metric | pre-fix (run3) | post-fix (run4) | gain |
|---|---|---|---|
| All-or-Nothing assignment | 5 min 04.9 s | **3.34 s** | **91x** |
| FW iteration 1 wall clock | 327.01 s | **19.81 s** | **16.5x** |
| system TT | 153,472,168.5 | 153,472,168.5 | identical |
| least TT | 81,081,805.4 | 81,081,805.4 | identical |
| gap | 89.280650 % | 89.280650 % | identical |

Numerics are bit-identical — only storage scheduling changed. The route
store is no longer the dominant cost: with the fix, route output adds a few
seconds per iteration instead of five minutes, so full-iteration regional
path extraction becomes routine.

- selftest 290/0 (unchanged — not a numerics change).
- `route_pool.bin` compared against the pre-fix pool (`route_pool_prefix.bin`).
- 4-node + network regression suite.

## Attribution

The defect was surfaced by the external `taplite_tree_route_pool` package
(Chicago Sketch benchmark, v0.1.0), whose "legacy repeated-growth copy lower
bound" measurement isolates exactly this pattern. Verified line-by-line in
our tree before adopting — the patch context matched our code exactly.
