# CR-0017 — Origin-rooted tree column pool (route_output level 4), EXPERIMENTAL

**Status:** COMMITTED (local branch), feature marked EXPERIMENTAL · 2026-08-10
**Kernel change:** YES (new output path; assignment numerics untouched)
**Spine order followed:** analytical selftests → kernel writer → network
comparison. Format spec: `docs/TREE_POOL_BINARY_FORMAT.md`.

## What was added

`route_output = 4` writes `tree_pool.bin`: one PRUNED shortest-path tree per
(predecessor-tree x origin x iteration), plus per-(mode, destination) demand
records. Link volumes are recovered by a single bottom-up sweep of the arc
slice (arcs stored farther-to-root = valid post-order); individual OD paths
are recovered lazily by following policy links to the root.

Design choices proven necessary by measurement (see below):
- **Pruning**: only arcs on a path to a destination with positive demand are
  stored. Unpruned trees were 4.7x larger for no benefit.
- **Shared trees**: modes with the same predecessor tree (`dedicated_shortest_path=0`
  or the same `g_rep_mode`) share ONE snapshot; per-mode demand rides on the
  OD records. 3x fewer snapshots on a 3-mode network.
- **PCE on the consumer side**: OD records carry pure demand plus the mode;
  the bottom-up sweep applies `pce` to reproduce `link_performance` volumes.

## Verification

**Analytical selftests (25 new assertions, total 315/0).** Hand-computed
tree 1 -L10-> 2 -L20-> 3, 2 -L30-> 4 with demand {3:100, 4:50}: the sweep
must give L30=50, L20=100, L10=150 (trunk = total demand — the conservation
identity at the root); theta scaling linear; two snapshots with thetas
summing to 1 reproduce x exactly; binary round trip preserves arc order,
theta, volumes; and four corruption classes must FAIL loudly — arc slice
past the pool end, dangling snapshot_idx, missing file, unknown link in the
arc pool.

**End-to-end, kernel-internal identity check.** After writing, the kernel
re-reads the pool and re-derives every link volume by the bottom-up sweep,
comparing against `MainVolume`:

| network | snapshots | arcs | OD records | identity max abs |
|---|---|---|---|---|
| 4-node, 20 iters | 20 | 60 | 20 | **0.000e+00** |
| Chicago Sketch, 20 iters, 3 modes | 7,720 | 4,568,329 | 1,862,700 | **7.64e-11** |

Independent cross-check: an external tree-pool prototype reports 4,567,587
arcs for the same network — our independent pruned implementation lands
within 0.016% (742 arcs), and its 1,862,700 recovered paths match exactly.

Network regression suite: ALL PASS. Selftest: 315/0.

## Honest storage finding (contradicts the naive projection)

On Chicago Sketch, against OUR production explicit pool:

| pool | size | records |
|---|---|---|
| `route_pool.bin` (level 3, full coverage) | **22.25 MB** | 255,006 |
| `tree_pool.bin` (level 4, pruned, shared) | 77.78 MB | 7,720 snapshots + 1.86M OD |

**The tree pool is 3.5x LARGER here, not smaller.** The reason is that our
explicit writer deduplicates paths by route_key across iterations
(1,862,700 OD-iteration paths collapse to 255,006 unique records, 7.3x),
while the tree pool currently repeats the OD block once per snapshot even
though demand does not change between FW iterations. The external
benchmark's 5.6x structural advantage was measured against a
NON-deduplicated explicit form.

What remains genuinely better and was reproduced: **load/store CPU**
(3.5x-6.9x measured on two machines) and lazy path expansion.

Next optimization (schema v2): key the OD block on (mode, root) instead of
(snapshot) — demand is iteration-invariant, so 1.86M records collapse to
93,135 x modes, taking the pool to roughly 39 MB. Only after that does a
storage comparison against the deduplicated explicit pool become fair.

## Scope

EXPERIMENTAL. Not wired into any downstream contract. Still open, as the
external package also states: multi-mode dedicated-tree cases beyond
`g_rep_mode` sharing, turn restrictions (link-state trees are not node
trees), OpenMP merge cost of the `tree_pool` critical section, and a
regional end-to-end comparison.
