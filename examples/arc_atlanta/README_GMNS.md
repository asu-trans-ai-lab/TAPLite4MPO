# ARC Atlanta 2020 AM -> GMNS for DTALite (multiclass, allowed_use + ref_volume)

Engine: **`bin/DTALite.exe` (the TAPLite C++ kernel)** — not the pip `DTALite` package.

## Build

```
python arc_atlanta_to_gmns.py     # shapefiles -> node.csv, link.csv (+allowed_use,+ref_volume), settings.csv, mode_type.csv
python arc_demand_to_csv.py       # 6 cores -> demand_sov.csv, demand_hov2.csv, demand_hov3.csv
cd gmns && DTALite.exe            # 1-iteration connectivity + allowed_use inventory
```

## gmns/

| File | Contents |
|---|---|
| `node.csv` | 66,546 nodes; 6,031 centroids (node_id == zone_id) |
| `link.csv` | 145,971 directed links; adds `allowed_use`, `ref_volume`, `toll_flag` |
| `demand_sov.csv` | 978,538 OD pairs, 2,599,725 trips (SOVF+SOVT) |
| `demand_hov2.csv` | 275,946 OD pairs, 570,616 trips (HOV2F+HOV2T) |
| `demand_hov3.csv` | 169,550 OD pairs, 228,360 trips (HOV3F+HOV3T) |
| `settings.csv` | **1 iteration** (inventory) — raise to 20+ for a converged run |
| `mode_type.csv` | sov / hov2 / hov3, each with its own demand_file, dedicated_shortest_path=1 |

## allowed_use (demand types -> link access)

Three access classes (tokens match `mode_type.csv`): `sov`, `hov2`, `hov3`.

| allowed_use | links | meaning |
|---|---|---|
| *(empty = all)* | 145,151 | general purpose, connectors, ramps, arterials, and tolled managed lanes |
| `hov2;hov3` | 820 | **HOV-only** (PROHIBIT = 2, "HOV 2+") |

**Derived from ARC's `PROHIBIT` field** — the authoritative attribute the ARC model's own
path builder uses (per `ARC_ABM_*.s` and ModelInputs.html S6.3.6). A toll is a *cost*, not an
access ban, so managed-lane codes that merely toll SOV/HOV still allow them. Only PROHIBIT
2/6/11 restrict autos; 4/10 are truck-only. Full code map:

| PROHIBIT | meaning | sov | hov2 | hov3 | allowed_use |
|---|---|:--:|:--:|:--:|---|
| 0 | general purpose | y | y | y | *(all)* |
| 1 | no trucks | y | y | y | *(all)* |
| 2 | HOV 2+ | - | y | y | `hov2;hov3` |
| 3 | ML: SOV toll, HOV2+ free | y* | y | y | *(all)* |
| 4 | truck only | - | - | - | `trk` (closed) |
| 5 | I-285 bypass (truck routing) | y | y | y | *(all)* |
| 6 | HOV 3+ | - | - | y | `hov3` |
| 7 | ML: SOV+HOV2 toll, HOV3 free | y* | y* | y | *(all)* |
| 8 | ML: SOV+truck toll, HOV2+ free | y* | y | y | *(all)* |
| 9 | ML: SOV+HOV2+truck toll, HOV3 free | y* | y* | y | *(all)* |
| 10 | truck only toll | - | - | - | `trk` (closed) |
| 11 | ML: HOV2 toll, HOV3 free, no SOV | - | y* | y | `hov2;hov3` |
| 12 | ML: SOV+HOV2+ toll, no trucks | y* | y* | y* | *(all)* |
| 13 | ML: all autos, tolled | y* | y* | y* | *(all)* |

`y*` = allowed but tolled (toll-cost layer, not access). In *this* AM network only codes
0/2/5/7/12 are present; the 820 PROHIBIT=2 links validate cleanly (0% SOV in ARC's own run,
89% HOV-used). `toll_flag=1` marks the 559 managed/tolled links for the future toll layer.
Each link also carries its raw `prohibit` value for reference.

## ref_volume

`ref_volume = V_SOVAM + V_HOV2AM + V_HOV3AM` — ARC's modeled AM **auto** link volume
(matches the SOV+HOV2+HOV3 demand we assign; excludes ARC's truck/commercial volumes).
Populated on 143,811 links. Use it as the calibration/validation target vs DTALite volume.

## 1-iteration inventory result (AON, ~49 s, 3 modes)

- Connectivity: **0 zones without outbound links**, **0 inaccessible OD pairs** (all 3 modes
  reach every destination).
- allowed_use enforced: **SOV volume on the 820 HOV-only links = 0** (0 violations);
  HOV2/HOV3 use them (2.26M veh).

For a converged assignment, set `number_of_iterations` back to 20 in settings.csv.
