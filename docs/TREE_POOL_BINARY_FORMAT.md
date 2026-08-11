# tree_pool.bin — Origin-Rooted Tree Column Pool (v1 DESIGN)

**Status:** design + independently verified prototype (Chicago Sketch).
Companion to `ROUTE_POOL_BINARY_FORMAT.md` (explicit path pool). Same
discipline: fixed little-endian layout, streaming write, header patched at
close, mandatory read-back self-test.

## Why a tree pool

An explicit pool stores one record per (OD x mode x iteration) path — cost
O(#OD x path_length). A tree pool stores one shortest-path tree per
(origin x mode x iteration) — cost O(#origins x #reachable_nodes) — and
recovers every OD path lazily by walking policy links back to the root.
Measured (Chicago Sketch, 387 zones / 933 nodes / 93,135 OD pairs, 20 FW
iterations, independently reproduced on a second machine):

| quantity | explicit | tree | gain |
|---|---|---|---|
| structural entries | 24,248,780 | 4,567,587 | 5.31x |
| structural bytes | 230.1 MB | 40.9 MB | 5.63x |
| load/store CPU (vendor, EPYC pinned) | 0.3253 s | 0.0938 s | 3.47x |
| load/store CPU (independent, Windows) | 0.5140 s | 0.0750 s | 6.85x |
| FW/tree identity residual | — | 1.0e-10 | lossless |

Projection for a regional PM network (measured full-coverage pool: 57.3M paths,
4.08B link entries, avg 71.2 links/path, 17,754 nodes, 3,858 zones,
6 modes, 2 iterations):

| representation | size | note |
|---|---|---|
| explicit, full coverage | **16.9 GiB** | what a lossless CSV/route_pool costs today |
| explicit, 1.0-veh floor | 0.06 GiB | **lossy** — small-volume paths dropped to background_volume |
| tree pool (node,link arcs) | 6.1 GiB | 2.8x |
| tree pool compact (link-only) | **3.2 GiB** | 5.4x, still LOSSLESS |

The gain is smaller than Chicago Sketch's 5.6x on the arc form because the agency
paths average 71 links (vs ~13): long paths make the explicit form
relatively less wasteful. The decisive property is not the ratio — it is
that the tree form gives **full coverage without a volume floor**, so
`A·f = x` holds with no residual and no background_volume bookkeeping.

## Layout (v1)

    HEADER — 40 bytes
      0   u32  magic       = 0x54504154   ('TAPT' as LE u32)
      4   u32  version     = 1
      8   u32  orientation = 0 origin-rooted | 1 destination-rooted
      12  u32  flags       = bit0: arcs store node ids (0 = link-only compact)
      16  u64  n_snapshots
      24  u64  total_arcs
      32  u64  n_od_records

    SNAPSHOT DIRECTORY — n_snapshots x 32 bytes (random access)
      i32 iteration | i32 mode | i32 root_zone | i32 root_node
      u64 arc_begin | u32 arc_count | f32 pad/reserved
      f64 theta            (FW weight of this snapshot)

    ARC POOL — total_arcs entries, farther-to-root order
      flags bit0 = 1:  i32 node, i32 link      (8 B/arc, self-describing)
      flags bit0 = 0:  i32 link                (4 B/arc; node implied by the
                       snapshot's node bitmap, written after the arc pool)

    OD VOLUME BLOCK — n_od_records x 24 bytes
      u32 snapshot_idx | i32 dest_node | i32 dest_zone | f64 volume | u32 pad

## Reconstruction semantics

**Bottom-up loading (the fast path).** Arcs are stored farther-to-root,
which is simultaneously the routing policy and a valid post-order. Seed
`mass[dest] += volume` for each OD record of the snapshot, then sweep the
arc slice once in stored order: `flow = mass[arc.node];
link_volume[arc.link] += theta * flow; mass[parent] += flow`. One pass, no
path materialization. This is exactly what makes it 3-7x faster than
replaying explicit paths.

**Lazy path expansion (on demand).** For any (origin, destination): start at
the destination and follow policy links to the root; reverse. Cost O(path
length) per query, zero storage. Used for select-link, path reporting, and
the OD->path->link tensor when a specific OD is requested.

## Consumer checklist

1. Verify magic/version; reject unknown `orientation`/`flags` bits.
2. `Σ over snapshots arc_count == total_arcs`, else corrupt.
3. Rebuild link volumes bottom-up; cross-check against
   `link_performance.csv` — must match to 1e-9 (this is the A·f identity;
   the tree pool has no floor, so there is no permitted residual).
4. `Σ theta` over the iterations of one (mode, root) must equal 1.
5. Never renormalize theta or invent missing arcs — a violation is a
   producer bug.

## Relationship to the flow-through tensor (planning doc 15)

    tree_pool.bin --(bottom-up sweep)--> x           (link volumes)
                  --(lazy expansion)-->  A, B        (incidence + shares)
                  --(OD block)-------->  q           (OD demand)

`A` and `B` are materialized only for the ODs a study needs (a corridor, a
select-link set), instead of for all 57M paths. For OpenDTA the departure
profile applies to the OD block: `λ(t) = volume · g(t)`, `Σ_t g = 1`.

## Implementation status

- Prototype: `tree_route_pool` external package (C++17, experimental),
  independently built and reproduced; residual 1.0e-10, AON 8.8e-10.
- NOT yet in the production kernel. Blocking items before adoption:
  multi-mode integration, turn restrictions, OpenMP merge, and end-to-end
  production-kernel tests (the vendor states the same).
- Sequence per the verification spine: analytical selftest cases for the
  codec and the bottom-up identity FIRST, then the kernel writer, then a
  regional run compared bit-for-bit against the explicit pool.
