# Design note — Issue #3: exact turn restrictions in shortest path

Status: IMPLEMENTED + verified (link-state Minpath_TR, gated). See
test_networks/turn_restriction/. The notes below are the original design; the
shipped implementation follows Option A with the "restrictions exist" dispatch.

## 1. Problem

`Minpath()` (kernel/src/TAPLite.cpp) keeps **one label per node**
(`CostTo[node]`, `PredLink[node]`, `PrevLink[node]`). Turn restrictions are
checked at relaxation time with

```cpp
if (PrevLink[now] != INVALID && Link[PrevLink[now]].b_withmovement_restrictions)
    if (IsMovementRestricted(PrevLink[now], k)) continue;
```

With a single label per node, `PrevLink[now]` records only the **one** incoming
link on the current best path to `now`. But with turn restrictions the true
state is the pair **(node, incoming link)**: the set of allowed outgoing
movements depends on *how you arrived*. One label per node cannot represent that.

### Concrete failure
Node V reached by link A (cost 10) or link B (cost 11). Movement A→C is
restricted; B→C is allowed. C is only reachable from V.
- Correct answer: arrive at V via B (cost 11), then B→C.
- Current code: settles V with the cheaper label (via A), so `PrevLink[V]=A`;
  when it tries V→C it sees A→C restricted and skips C entirely. C becomes
  unreachable even though a valid path exists.

The reverse error also occurs (a turn is allowed because the remembered
incoming link happens to permit it, while the path actually used a different,
restricted incoming link after a later label update).

## 2. Secondary bug found while scoping (must fix together)

Movement restrictions are stored and looked up by **external** link id, but used
in `Minpath` as **internal** indices:

- `Load_Movement_Restrictions()` reads `ib_link_id`/`ob_link_id` (external ids
  from movement.csv) and calls `InsertMovementRestriction(ib_link_id, ob_link_id)`
  and `Link[ib_link_id].b_withmovement_restrictions = true` — indexing `Link[]`
  with an external id.
- `Minpath` calls `IsMovementRestricted(PrevLink[now], k)` with **internal**
  link indices.

These agree only when external link_id == internal index for every link. After
the issue #2 fix (external id preserved, internal id = row index), and whenever
link.csv ids are non-sequential or any link is skipped, they diverge. The
restriction subsystem then silently mis-keys. Fix: translate external→internal
once at load time via a `map<external_link_id,int>` and store everything by
internal index.

## 3. Options

| Option | Exact? | Invasiveness | Memory |
|--------|--------|--------------|--------|
| A. Link-based labeling (label per directed link / line graph) | Yes | Localized to Minpath + pred-tree semantics | O(#links) labels |
| B. Physical node expansion (split each node per incoming link) | Yes | Network-wide structural change | grows node/link arrays |
| C. Expand only restricted nodes | Yes | Medium; two code paths | O(#links near restrictions) |

**Recommended: Option A — link-based labeling.** It is exact, the extra memory
is O(#links) (same order as today's O(#nodes)), and the change is contained to
the routing layer. Option B touches the whole network build; Option C adds a
second code path with little benefit over A.

## 4. Design (Option A)

State = a directed link `k` (equivalently, "arrived at `head(k)` via `k`").
- `label[k]` = least cost to be at `head(k)` having just traversed `k`.
- `pred_link[k]` = the link traversed immediately before `k` (INVALID at origin).
- Transition `k -> k'` allowed iff `head(k) == tail(k')` and
  `!IsMovementRestricted(k, k')` (internal ids).
- Origin seed: for each outgoing link `k` of the origin node, `label[k] =
  cost(k)`, `pred_link[k] = INVALID`.
- Cost of stepping onto `k'`: `label[k] + Travel_time[k'] + AdditionalCost[k']`
  (same per-link cost terms as today).
- Destination zone `d`: `CostTo[d] = min over links k entering head==d of label[k]`;
  remember the arg-min link `best_in_link[d]`.

Label-correcting queue (deque) identical in spirit to the current implementation,
but indexed by link instead of node. FirstThruNode / origin-node gating is applied
on `tail(k')` exactly as the node version gates on `now`.

### Predecessor tree / downstream impact
Today `MinPathPredLink[m][Orig][node]` (node-indexed) feeds the back-trace in
`All_or_Nothing_Assign` and the route builders. New representation:
- Store `pred_link[k]` (link-indexed) for the tree, plus `best_in_link[node]`.
- Back-trace from destination `d`: `k = best_in_link[d]`; emit `k`; `k =
  pred_link[k]`; repeat until INVALID. This yields the same link sequence the
  current back-trace produces, so `All_or_Nothing_Assign`, `OutputRouteDetails`,
  and `OutputVehicleDetails` need only the trace-loop adjusted, not their logic.

Touched functions: `Minpath`, `FindMinCostRoutes` (alloc + call),
`All_or_Nothing_Assign` (back-trace), `MinPathPredLink` allocation/free, and the
restriction loader (id mapping). `AddLinkSequence`/route builders unchanged if we
keep returning a node/link sequence.

### When there are no restrictions
If `global_movement_restrictions` is empty, results must be byte-identical to the
node-based algorithm. Plan: keep the existing node-based `Minpath` as the default
fast path and dispatch to the link-based version only when restrictions exist
(`!global_movement_restrictions.empty()`). This bounds risk and preserves the
verified Sioux/Chicago behavior.

## 5. Memory / performance
- Labels/queues: O(#links) vs O(#nodes) — typically 2-4x nodes, still small.
- Per-zone predecessor storage grows from #nodes to #links per (mode,zone).
  For large multi-zone networks this is the main cost; only allocate the
  link-indexed tree when restrictions exist.
- Run-time: same label-correcting complexity; constant factor a bit higher.

## 6. Test plan
1. **Tiny restricted net** (build under `test_networks/turn_restriction/`):
   the §1 example (A/B into V, A→C restricted) with a hand-computed answer.
   Assert the path uses B→C and that C is reachable.
2. **No-restriction regression**: Sioux Falls + Chicago Sketch must reproduce the
   current gap trajectory exactly (we already have the upstream reference).
3. **U-turn case**: a node where the U-turn movement is penalized; confirm the
   path avoids it.
4. **External-id mapping**: a net with non-sequential link ids + a movement
   restriction; confirm the restriction binds the intended movement.

## 7. Rollout
1. Fix the external→internal id mapping in `Load_Movement_Restrictions` (small,
   independently testable).
2. Add link-based `Minpath` behind the "restrictions exist" dispatch.
3. Adapt the back-trace + predecessor allocation.
4. Add the test networks; verify exactness + no-restriction regression.

Estimated blast radius: ~4 functions + 1 new test dir. The dispatch keeps the
default (no-restriction) path untouched.
