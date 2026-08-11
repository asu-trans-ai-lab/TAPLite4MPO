# CR-0021 — `route_output = 4` stops allocating the explicit route store

**Date:** 2026-08-10 · **Status:** implemented, selftest green (351/0)
**Files:** `kernel/src/TAPLite.cpp`

## Why

At `route_output = 4` the kernel wrote the compact origin-rooted tree pool
**and** still built the 5D explicit route store in memory. The tree pool is
lossless, so the explicit store was pure duplication — and it was the
peak-memory term.

Measured on a regional single-mode PM run:

| | peak memory |
|---|---|
| before | **33.7 GB** (6.3 GB free of 63.5, 10.9 GB paged) |
| after | **14.0 GB** (38 GB free) |

The earlier attempts died in exactly this phase.

## What changed

```cpp
bool tree_only = (shortest_path_log_flag >= 4) && (g_ODME_mode == 0) &&
    !(g_ODME_obs_VMT > 0);
if (shortest_path_log_flag >= 4 && !tree_only)
    printf("NOTE: route_output=4 with ODME active keeps the explicit route "
           "store (ODME walks it); peak memory will match level 3.\n");
if (shortest_path_log_flag >= 1 && !tree_only) { /* allocate linkIndices */ }
```

**ODME walks the explicit store.** Rather than silently changing ODME's basis,
the store is retained when ODME is active and the run says so.

Levels 1–3 are untouched. Level 4 already wrote only `tree_pool.bin` — the
writer is an `if`/`else if` — so no output changes; only the allocation does.

## Known limitation — do not quote the old size target

`CaptureTreeSnapshot(Assignment_iteration_no, ...)` stores a snapshot set **per
Frank-Wolfe iteration**. A 20-iteration run over 7,716 origins produces
~154,000 snapshots, not 7,716.

| | projected | measured |
|---|---|---|
| modes | 6 | **1** |
| `tree_pool.bin` | 0.98 GiB | **10.29 GB** |

Roughly 10× larger on one sixth of the modes. The compression argument — modes
sharing one predecessor tree per origin — is still correct; it was applied to
the wrong denominator, because iterations were never in the arithmetic.

**Consequence:** the read-back self-test does not terminate at that scale. It
rebuilds link volumes bottom-up through `std::map` lookups per snapshot per
link; at ~154,000 × 49,329 it ran 20+ minutes at 27 GB resident with no
progress, and never reached `link_performance.csv`.

### Before level 4 can be used at regional scale

1. Decide what the pool is *for*. If it is the converged routing policy, store
   the **final iteration only** plus FW weights. If the full history is wanted,
   make that a separate declared level with its own size budget.
2. Re-derive the size target **with the iteration count in it**, and state that
   count next to the number.
3. Make the self-test scale — vector indexing instead of per-snapshot map
   lookups, or sample-verify at a declared and logged rate rather than
   silently checking everything.

Until then, level 4 is correct but only practical on small networks, and the
memory win above applies to the assignment phase.
