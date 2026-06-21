# Multimodal TAPLite/DTALite Validation Test Plan

Small, reproducible MULTIMODAL test networks that mimic the NVTA regional model,
used to validate a TAPLite/DTALite C++ kernel (per-mode link volume, link travel
time, `allowed_use` enforcement, Frank-Wolfe convergence) on SMALL networks
BEFORE running the 49k-link NVTA model.

Location: `test_networks/` (this folder)

- `sf_multimodal/` — multimodal Sioux Falls (24 zones, 76 links)
- `cs_multimodal/` — multimodal Chicago Sketch (387 zones, 2950 links)
- `build_multimodal.py` — regenerates both from the base DTALite networks
- `test_harness.py` — runs 1/10/20 iterations and checks all criteria
- `TEST_PLAN.md` — this file

Base networks (schemas matched exactly, only `allowed_use` added + demand split):
- SF: `.../DTALite_release-main/data_sets/02_Sioux_Falls/`
- CS: `.../DTALite_release-main/data_sets/03_chicago_sketch/`

## 1. What mimics NVTA

### 6 modes (`mode_type.csv`)
| id | mode_type | vot | pce | occ | demand_file | dedicated_shortest_path | split |
|----|-----------|-----|-----|-----|-------------|--------------------------|-------|
| 1 | sov  | 20 | 1 | 1.0 | sov_<net>.csv  | 1 | 59.0% |
| 2 | hov2 | 30 | 1 | 2.0 | hov2_<net>.csv | 1 | 21.4% |
| 3 | hov3 | 60 | 1 | 3.5 | hov3_<net>.csv | 1 | 7.2% |
| 4 | com  | 30 | 1 | 1.0 | com_<net>.csv  | 1 | 9.3% |
| 5 | trk  | 30 | 1 | 1.0 | trk_<net>.csv  | 1 | 2.6% |
| 6 | apv  | 30 | 1 | 1.6 | apv_<net>.csv  | 1 | 0.4% |

All `dedicated_shortest_path=1`: each mode computes its own `allowed_use`-respecting
shortest path. `<net>` = `sf` / `cs`.

### Demand split
The single base `demand.csv` (o,d,volume) is split across the 6 modes by the NVTA
fractions above, producing 6 demand files per network with header
`o_zone_id,d_zone_id,volume`.

### `allowed_use` semantics (engine-verified)
The C++ engine reads the link field **`allowed_use`** (singular) and matches each
mode token as a **substring** (`TAPLite.cpp:3705,3724,3728`). Therefore:
- A BARE single token like `sov` would substring-match nothing else but is fragile;
  always use the full multi-token list `sov;hov2;hov3;trk;apv;com` for "all allowed".
- `"closed"` matches no mode token => no mode may use the link.
- `"apv"` matches only the `apv` token (no other mode name contains "apv").
- Empty string or `"all"` is treated by the engine as all-modes-allowed.

## 2. Restricted links (the test cases)

Restrictions were placed on links that the equilibrium assignment actually loads
(verified against an unrestricted baseline run) so each restriction is NON-VACUOUS:
the link's volume measurably changes vs. baseline (the harness flags this as
`[BITES]`).

### Sioux Falls (`sf_multimodal/link.csv`)
| input link_id | from->to | allowed_use | class | rationale |
|---------------|----------|-------------|-------|-----------|
| 26 | 10->9  | `hov2;hov3` | HOV-only | most-used link (~21.9k baseline); excluding sov/com/trk/apv displaces all of it |
| 25 | 9->10  | `hov2;hov3` | HOV-only | reverse of the busiest hub link (~21.7k baseline) |
| 30 | 10->17 | `sov;hov2;hov3;com;apv` | no-truck | hub corridor carrying real flow; truck must detour |
| 51 | 17->10 | `sov;hov2;hov3;com;apv` | no-truck | reverse; absorbs displaced flow (8.4k->13.4k) |
| 43 | 15->10 | `apv` | apv-only | high-demand link (~23.4k baseline); only apv may use it |
| 33 | 11->12 | `closed` | closed | low-importance link, parallels exist |
| 36 | 12->11 | `closed` | closed | reverse, closed |

### Chicago Sketch (`cs_multimodal/link.csv`)
| input link_id | from->to | allowed_use | class | rationale |
|---------------|----------|-------------|-------|-----------|
| 1084 | 564->563 | `hov2;hov3` | HOV-only | busy interior corridor (~20.1k baseline) |
| 1081 | 563->564 | `hov2;hov3` | HOV-only | reverse busy corridor (~18.7k baseline) |
| 1009 | 551->563 | `sov;hov2;hov3;com;apv` | no-truck | carries ~19.5k allowed flow; truck excluded |
| 1079 | 563->551 | `sov;hov2;hov3;com;apv` | no-truck | reverse, no-truck |
| 1087 | 565->564 | `apv` | apv-only | ~18.8k baseline; only apv may use it |
| 2822 | 902->660 | `closed` | closed | redundant interior link |

NOTE: in CS, each zone connects to the network through a single connector link
(e.g. zone 5 -> node 551). Those connectors are NEVER restricted (it would isolate
the zone). All restrictions are on INTERIOR links that have parallel alternatives.
`build_multimodal.py` runs a per-mode connectivity guard that aborts if any zone
loses all allowed in/out edges for any mode.

## 3. settings.csv (11-column schema the engine expects)

`number_of_iterations,number_of_processors,demand_period_starting_hours,`
`demand_period_ending_hours,first_through_node_id,base_demand_mode,route_output,`
`vehicle_output,log_file,odme_mode,odme_vmt`

Three variants per network: `settings_1iter.csv`, `settings_10iter.csv`,
`settings_20iter.csv`. Common values: processors=8, period 7-8h,
`first_through_node_id=-1` (auto), `base_demand_mode=0`, `route_output=0`,
`vehicle_output=0`, `log_file=0`, `odme_mode=0`, `odme_vmt=0`.

## 4. How to run

```python
import os, DTALite
os.chdir(r"<network folder>")   # node/link/settings/mode_type + 6 demand files
DTALite.assignment()            # writes link_performance.csv into the folder
```

IMPORTANT runtime gotchas (both encoded in `test_harness.py`):
1. **Output `link_id` is RESEQUENCED** to contiguous 1..N internal order and does
   NOT match the input `link_id`. ALWAYS join `link_performance.csv` back to the
   input `link.csv` on `(from_node_id, to_node_id)`.
2. **State persists across `assignment()` calls in the SAME Python process** — the
   DLL accumulates link volume, so repeated calls inflate volumes (confirmed:
   call1=1.07M, call2=2.25M). Run each assignment in a FRESH subprocess. The
   harness does this via `subprocess.run([sys.executable, "-c", ...])`.

`link_performance.csv` key columns: `link_id` (reseq), `from_node_id`,
`to_node_id`, `volume` (total), per-mode `mod_vol_sov..mod_vol_apv`,
`travel_time`, `vdf_fftt`, `speed_mph`, `VMT`.

## 5. Pass / fail criteria

1. **Engine runs** to completion on both networks at 1/10/20 iterations. PASS.
2. **`allowed_use` enforced** — every restricted link carries EXACTLY ZERO volume
   for each disallowed mode (joined on (from,to)). Closed links carry zero for all
   modes. PASS = no disallowed-mode volume on any restricted link.
3. **Restrictions non-vacuous** — each restricted link's total volume differs from
   the unrestricted baseline by > 1% (the harness `[BITES]` flag). Demonstrates the
   restriction actually changes routing.
4. **Per-mode volumes sane** — all 6 modes carry nonzero total link volume and the
   per-mode totals track the demand split (sov largest ~59%, apv smallest ~0.4%).
5. **Congestion builds** — link travel_time on loaded links increases from the
   1-iter (near free-flow) loading as iterations add congestion.
6. **FW converges by 20 iter** — max per-link |dVolume| from 10->20 iter is much
   smaller than from 1->10 iter; total VMT stabilizes (|VMT20-VMT10|/VMT10 small).

## 6. Latest harness results (pypi DTALite 0.8.1)

### Sioux Falls
- Per-mode total link volume (20 iter): sov 638,375; hov2 231,546; hov3 77,903;
  com 100,625; trk 28,477; apv 4,328 (total 1,081,255).
- allowed_use: 7 restricted links, **0 FAIL**, **7/7 BITE**.
  - link 25/26 (HOV-only): 21.7k/21.9k baseline -> 0 (all displaced).
  - link 43 (apv-only): 23.4k baseline -> 0 for non-apv.
  - link 30/51 (no-truck): retain 8.3k/13.4k allowed flow, ZERO truck.
  - link 33/36 (closed): 8.5k baseline -> 0 for all.
- Congestion: link 30 travel_time 8.0 -> 11.9 -> 17.3 across 1/10/20 iter.
- FW convergence: max |dVol| 1->10 = 19,694 vs 10->20 = 3,070; |VMT20-VMT10|/VMT10 = 3.86%.

### Chicago Sketch
- Per-mode total link volume (20 iter): sov 4,267,629; hov2 1,547,920; hov3 520,795;
  com 672,694; trk 188,595; apv 28,933 (total 7,226,565).
- allowed_use: 6 restricted links, **0 FAIL**, **6/6 BITE**.
  - link 1081/1084 (HOV-only): 18.7k/20.1k baseline -> 0.
  - link 1087 (apv-only): 18.8k baseline -> 0 for non-apv.
  - link 1009/1079 (no-truck): retain 17.8k/7.1k allowed flow, ZERO truck.
  - link 2822 (closed): 4.3k baseline -> 0.
- FW convergence: max |dVol| 1->10 = 20,533 vs 10->20 = 0.0 (fully converged);
  |VMT20-VMT10|/VMT10 = 0.00%.

**OVERALL: allowed_use enforcement ALL PASS; all restrictions non-vacuous (bite).**

## 7. Checklist the C++ CMake kernel MUST pass on SF and CS before NVTA

Run the same SF and CS folders through the freshly built C++ kernel and confirm:

- [ ] Engine reads node/link/mode_type/settings + 6 per-mode demand files and runs
      1/10/20 iterations without crashing.
- [ ] `link_performance.csv` is written with per-mode `mod_vol_*` columns for all 6
      modes.
- [ ] Joining output to input `link.csv` on (from_node_id,to_node_id): every
      HOV-only link has sov=com=trk=apv=0; every no-truck link has trk=0; every
      apv-only link has sov=hov2=hov3=com=trk=0; every closed link has total=0.
- [ ] Each restricted link's volume differs from an unrestricted baseline run
      (restriction bites).
- [ ] All 6 modes have nonzero total link volume; per-mode totals follow the
      59/21.4/7.2/9.3/2.6/0.4 split ordering.
- [ ] Loaded-link travel_time rises from 1-iter toward 20-iter (congestion builds).
- [ ] FW converges: max per-link |dVolume| 10->20 << 1->10; total VMT stabilizes.
- [ ] C++ per-mode volumes and link travel_times match the pypi DTALite reference
      (within FW solver tolerance) on BOTH SF and CS.

Only after ALL boxes are checked on SF and CS should the kernel be run on the full
49k-link NVTA network.
