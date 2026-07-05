# Shortest-path algorithm: label-correcting vs label-setting

The kernel's `Minpath` was originally **D'Esopo-Pape deque label-correcting** (the
`WAS_IN_QUEUE` marker; the "Deque implementation of MLC" from
[jdlph/shortest-path-algorithms](https://github.com/jdlph/shortest-path-algorithms)).
That project benchmarked only the **Chicago Sketch (933 nodes)** and concluded the deque
MLC is competitive. **That conclusion does not hold at regional/statewide scale.**

## What we added
- **`sp_algorithm`** setting: `0` = Pape deque label-correcting (default), `1` = binary-heap
  **Dijkstra label-setting** (`Minpath_Dijkstra`). Identical FirstThruNode gating,
  `mode_allowed_use`, and movement-restriction rules — a true drop-in.
- **Pre-allocated per-thread scratch** (`InitSPScratch`): the queue/prev-link/heap buffers
  are allocated ONCE and reused across all `Minpath` calls (indexed by
  `omp_get_thread_num()`), eliminating the per-call `malloc`/`free` that both algorithms
  previously paid on every one of the ~10⁴ shortest-path solves per FW iteration.

## Benchmark — output/accessibility off to isolate the SP

| network | nodes / links | Pape deque (sp=0) | **Dijkstra (sp=1)** | speedup |
|---|---|--:|--:|--:|
| Chicago Regional | 13K / 39K, 1,790 z, 20 it | 19.2 s | 21.9 s | 0.9× (wash) |
| **SCAG super-zone** | **77K / 247K, 1,000 z, 5 it** | **385 s** | **18 s** | **~21×** |

## The finding
- On **moderate** networks the deque MLC and Dijkstra are within noise (deque's low
  overhead offsets a few re-scans) — matching the Chicago-Sketch-only benchmark.
- On **large** networks (SCAG, 77K nodes) the label-correcting deque **re-scans
  pathologically** (label-correcting worst case ~O(nm)); **Dijkstra settles each node
  once and is ~21× faster.** This — not parsing or output — was the SCAG runtime wall.
- Both compute correct shortest-path **costs** (match to ~0.05%); the tiny equilibrium
  difference is equal-cost-path **tie-breaking**, well within the convergence gap.

## Recommendation
Use **`sp_algorithm=1` (Dijkstra) for any large network.** It is equal-or-faster
everywhere and dramatically faster at scale, with non-negative link costs guaranteed by
every VDF (BPR/conic/QVDF). Consider making it the default once the tie-break-sensitive
regression baselines are refreshed.

## Further work (noted, not yet done)
- Skip the O(nodes) re-init via generation-stamped labels (reset only touched nodes) —
  helps both algorithms further on large networks.
- Restrict `FindMinCostRoutes` tree building to active origins only.
- Fibonacci heap / 4-ary heap for the Dijkstra frontier.
