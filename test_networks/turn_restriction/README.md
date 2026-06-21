# Turn-restriction test (issue #3)

Exercises exact turn restrictions in the shortest path (link-state `Minpath_TR`),
the `movement.csv` input, and the external→internal link-id mapping.

## Network
```
        102 (1->3, direct, cheap "A")
   (1) ───────────────────────► (3) ──104──► (4)
    │                            ▲
   101 (1->2)                   103 (2->3)
    └──────────► (2) ───────────┘
```
Link ids 101/102/103/104 are **non-sequential** vs the internal indices 1..4, so
the run also checks that movement.csv ids (external) are mapped to internal ones.

- All links: 1 mi @ 60 mph → ~1 min free-flow, high capacity (negligible congestion).
- Direct route 1→3→4 (102,104) costs ~2 min; detour 1→2→3→4 (101,103,104) costs ~3 min.

## movement.csv
```
mvmt_id,node_id,ib_link_id,ob_link_id,penalty
1,3,102,104,100        # forbid arriving via 102 then taking 104 (penalty>=10 = banned)
```

## Expected (verified)
| run | shortest path | links carrying volume |
|-----|---------------|-----------------------|
| **without** movement.csv | 1→3→4 | 102, 104 |
| **with** movement.csv | 1→2→3→4 | 101, 103, 104 |

The destination stays reachable under the restriction (the OD is not dropped) —
the one-label-per-node algorithm would have settled node 3 via the cheaper link
102, found 102→104 banned, and dropped the OD. The link-state search instead
reaches node 3 via link 103, which permits the turn to 104.

## Run
```
# copy node/link/demand/settings (+ movement.csv to enable restrictions) + DTALite.exe, then:
DTALite.exe
# log prints: "Turn restrictions active: 1 from movement.csv, 0 U-turn bans..."
```

When `movement.csv` is absent the kernel reports no restrictions and uses the
fast node-based `Minpath` unchanged (byte-identical to prior behavior).

`non_uturn_flag` in link.csv is also honored now (folded into the same
mechanism): set it to 1 on a link to forbid the immediate U-turn back along the
reverse link.
