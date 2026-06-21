# DTALite / TAPLite kernel — User Guide

A single-file C++ traffic-assignment kernel (static user-equilibrium via
Frank–Wolfe) for GMNS-style networks. It reads CSV inputs from the current
working directory and writes CSV results back. This guide covers the input
schema, settings, volume-delay functions (BPR / conic / QVDF), multimodal and
turn-restriction features, outputs, and the validation/regression tooling.

> **Running an MPO/DOT model?** See **Volume 2 — [Static Highway Assignment for MPOs](USER_GUIDE_VOL2_MPO.md)**:
> the agency workflow, VDF selection, period-capacity / peak-load-factor convention,
> generalized cost & user classes, managed lanes, convergence (incl. bi-conjugate FW),
> validation targets, and per-agency recipes (ARC, SERPM, TRPA, MTC, SANDAG, MWCOG, VDOT, ODOT).

---

## 1. Build

```bash
bash build.sh          # -> bin/DTALite.exe  (mingw g++ + CMake/Ninja, OpenMP)
```
The standalone executable runs the kernel directly in the working directory.
(A shared library `DTALite` is also built for the Python `ctypes` wrapper.)

## 2. Run

Put the input CSVs in a folder and run the executable **from that folder**:

```bash
cd my_scenario/        # contains node.csv, link.csv, settings.csv, demand(s), mode_type.csv
/path/to/bin/DTALite.exe
```

Outputs are written next to the inputs. **Validate first** (section 8) to catch
schema problems before a run.

> Gotcha: the shared-library build accumulates link volume across repeated
> in-process `assignment()` calls. Run each scenario in a fresh process (the
> standalone exe always does).

---

## 3. Input files

### node.csv
| column | required | meaning |
|--------|:--------:|---------|
| `node_id` | yes | unique integer node id |
| `zone_id` | yes | zone/centroid id if this node is a zone, else 0 |
| `x_coord`, `y_coord` | yes | coordinates (lon/lat or projected) |

A node with `zone_id > 0` is an origin/destination centroid; demand is keyed by
zone id.

### link.csv
Links **must be sorted ascending by `from_node_id`** — the kernel builds CSR
adjacency assuming this; unsorted links silently corrupt the shortest path. The
validator enforces it.

| column | required | meaning |
|--------|:--------:|---------|
| `link_id` | recommended | external link id; preserved and echoed in all outputs. Without it, outputs fall back to the internal row index and movement.csv cannot reference links. |
| `from_node_id`, `to_node_id` | yes | endpoints (must exist in node.csv) |
| `lanes` | yes | number of lanes (> 0) |
| `capacity` | yes | **per-lane** capacity, veh/hour/lane |
| `free_speed` | yes | free-flow speed; treated as km/h then converted unless `vdf_free_speed_mph` is given |
| `vdf_free_speed_mph` | recommended | free-flow speed in mph (unambiguous; overrides `free_speed`) |
| `length` | yes | link length in **meters** (converted to miles internally) |
| `vdf_length_mi` | optional | length in miles; overrides `length` when ≥ 0 |
| `vdf_type` | optional | `0` = BPR (default), `1` = Spiess conic, `2` = QVDF |
| `vdf_alpha`, `vdf_beta` | optional | BPR/conic parameters (defaults 0.15, 4) |
| `vdf_A` | optional | modified-BPR **linear** term `A·(v/c)` (default 0 = standard BPR); see §4 |
| `vdf_plf` | optional | peak load factor (default 1; see §5) |
| `cutoff_speed` | optional | speed at capacity (mph); defaults to `0.75 × free_speed` |
| `vdf_cp`,`vdf_cd`,`vdf_n`,`vdf_s` | QVDF | QVDF queue parameters (used when `vdf_type=2`) |
| `allowed_use` | optional | mode access control (section 6) |
| `non_uturn_flag` | optional | `1` bans the immediate U-turn back along the reverse link |
| `ref_volume`, `obs_volume`, `geometry` | optional | reference/observed volume, WKT geometry |
| `toll_<mode>` (or `vdf_toll`) | optional | per-class toll in $ (`toll_sov`, …); falls back to link-level `vdf_toll`. Added to generalized cost as `toll/VOT·60` minutes |

**Capacity is per lane.** The kernel forms `Link_Capacity = lanes × capacity`
and the V/C ratio uses the **per-lane** demand vs the **per-lane** capacity, so
a corridor's D/C reflects its lane count correctly.

### demand.csv (and per-mode demand files)
| column | required | meaning |
|--------|:--------:|---------|
| `o_zone_id`, `d_zone_id` | yes | origin/destination zone ids (must exist as node `zone_id`s) |
| `volume` | yes | demand (≥ 0) for the analysis period |

In multimodal runs each mode has its own demand file (see mode_type.csv). A
missing demand file is skipped (that mode gets zero demand) and the run
continues with the remaining modes.

### mode_type.csv
| column | meaning |
|--------|---------|
| `mode_type_id` | mode index |
| `mode_type` | short token used in `allowed_use` (e.g. `sov`, `hov2`, `trk`) |
| `name` | display name |
| `vot` | value of time (used to convert tolls & distance cost to time) |
| `operating_cost` | $/mile distance cost added to generalized cost (default 0; ARC auto 0.1729, truck 0.5360) |
| `pce` | passenger-car equivalent (truck > 1) — link volume is pce-weighted |
| `occ` | occupancy (for person-miles/hours reporting) |
| `demand_file` | this mode's demand CSV |
| `dedicated_shortest_path` | `1` = compute this mode's own `allowed_use`-respecting path |

Single-mode runs may omit mode_type.csv; the kernel defaults to one `auto` mode
reading `demand.csv`.

### settings.csv (single data row) — the control/config surface
`settings.csv` **is** the kernel's configuration file. New parameters are added as
columns; the kernel reads each by name and falls back to a default if the column
is absent, so you never need a separate config file and old files keep working.
```
number_of_iterations,number_of_processors,demand_period_starting_hours,
demand_period_ending_hours,first_through_node_id,base_demand_mode,route_output,
vehicle_output,log_file,odme_mode,odme_vmt,demand_format
```
| column | meaning |
|--------|---------|
| `number_of_iterations` | Frank–Wolfe iterations |
| `number_of_processors` | OpenMP threads (origins partitioned across them) |
| `demand_period_starting_hours` / `ending_hours` | analysis period (hours); `H = end − start` |
| `first_through_node_id` | first node usable as a through node (`-1` auto) |
| `base_demand_mode` | enable base/background demand handling |
| `route_output` | `1` writes `route_assignment.csv` |
| `vehicle_output` | `1` writes `vehicle.csv` |
| `log_file` | `1` writes the verbose `TAP_log.csv` |
| `odme_mode`, `odme_vmt` | origin-destination matrix estimation toggles |
| `demand_format` | `0` = read demand CSV (default), `1` = read binary `.bin` (fast; see below) |
| `convergence_gap_pct` | stop Frank–Wolfe when relative gap% < this (`0` = run all iterations) |
| `convergence_consecutive` | require the gap below the target for this many **consecutive** iterations before stopping (default `1`; ARC uses `3`) |
| `relative_gap_standard` | `0` = gap normalized by the all-or-nothing total (legacy); `1` = by the current total (AequilibraE-standard relative gap) |
| `assignment_method` | `0` = Frank–Wolfe (default); `1` = conjugate FW; `2` = **bi-conjugate FW** (faster gap closure on stiff/congested networks, same UE) |

### Fast demand loading (binary format)
On large regional models, parsing millions of OD rows from CSV dominates startup.
Convert the demand files once to a packed binary and tell the kernel to read it:
```bash
python -m dtalite_qa demand-bin my_scenario/     # writes <demand_file>.bin next to each CSV
# then set demand_format=1 in settings.csv
```
The kernel reads `<demand_file>.bin` (falling back to CSV if absent). Results are
identical; only the load is faster. On Chicago Regional (2.3M OD pairs) total wall
time dropped ~1.5x (the CSV-parse cost is removed). Binary format (little-endian):
header `"DTAB"`, int32 version, int64 count; records `int32 o, int32 d, double vol`.

### movement.csv (optional — turn restrictions)
| column | meaning |
|--------|---------|
| `mvmt_id` | movement id |
| `node_id` | intersection node |
| `ib_link_id`, `ob_link_id` | inbound / outbound **external** link ids |
| `penalty` | `>= 10` ⇒ the movement `ib → ob` is **forbidden** |

When any restriction exists (movement.csv or `non_uturn_flag`), the kernel uses
an exact link-state shortest path that respects turn bans; otherwise it uses the
fast node-based path. See section 7.

---

## 4. Volume-delay functions (`vdf_type`)

- **`0` BPR** (default): `t = fftt · (1 + α·(d/c)^β)`, with `d` the per-lane demand
  rate and `c` the per-lane capacity. Set `vdf_A` for the **modified BPR**
  `t = fftt · (1 + A·(d/c) + α·(d/c)^β)` (an extra linear term, e.g. ARC Atlanta;
  `vdf_A=0` recovers standard BPR).
- **`1` Spiess conic**: asymptotically linear congestion function; uses
  `vdf_alpha`/`vdf_beta` (or explicit conic columns) and per-lane V/C.
- **`2` QVDF** (Queue VDF / fluid queue): period-average congested speed from the
  queue model calibrated by `cutoff_speed` and `vdf_cp/cd/n/s`. A transparent
  reference implementation and clean spreadsheet live in
  `test_networks/qvdf_reference/` (`qvdf_ref.py`, `QVDF_clean_reference.xlsx`).
- **`3` BPR2** (AequilibraE): BPR with the exponent doubled above capacity —
  `t0(1+α·x^β)` for x≤1, `t0(1+α·x^{2β})` for x>1 (steeper over-saturation).
- **`4` INRETS** (AequilibraE): `t0(1.1−α·x)/(1.1−x)` for x≤1, `t0·((1.1−α)/0.1)·x²`
  for x>1 (`vdf_alpha` ≈ 0.9–1.0).
- **`5` Akcelik**: `t0 + α·(z+√(z²+β·x))`, `z=x−1` — time-dependent delay form.
- **`6` SANDAG-signal**: BPR running time + Webster uniform signal delay from
  `cycle_length` (sec) and `green_ratio` (g/C, default 0.45).

All VDFs share the FW line search (a bisection on the cost-based directional
derivative), so any monotone VDF is handled exactly.

## 5. Peak Load Factor — hourly → period capacity (IMPORTANT)

Static assignment loads a whole **period** of demand at once, but capacity and the
VDF are defined per **hour**. The **Peak Load Factor (PLF)** bridges them, and it is
the single most common source of mis-stated congestion. Full derivation and
planning guidance: **[docs/peak_load_factor.md](docs/peak_load_factor.md)** (the
ADOT load-factor memo, ADOT VDF calibration project, 2022).

- **Identities:** peak hourly demand `D = V_period / (L·PLF)`; capacity expansion
  `φ = L·PLF`; period capacity `c_period = φ·c_h` (`L` = period length in hours).
- **Kernel mapping:** set `capacity` = **hourly** per-lane `c_h`, `vdf_plf` = the
  **real PLF**, period `H = L`. Then `DOC = (V/lanes/H/plf)/c_h = D/c_h`.
- **Do NOT** set `vdf_plf = 1` (flat) or feed *period* capacity with `vdf_plf = 1/H`
  — both hard-code PLF = 1 and under-load congestion by `1/PLF` (~6 % AM, ~2.5× NT).
  If `VDF_cap` scales exactly with period length it was built flat and needs PLF.
- **Bounds (enforced by `plf.bound_plf`):** `0 < PLF ≤ 1` (1 = flat);
  `φ = L·PLF ≥ 1` ⇒ `PLF ≥ 1/L`; advisory floor `PLF ≥ 0.25`.
- **Recommended (MAG back-calc):** most VDF types AM/MD/PM/NT = `0.94/0.96/0.98/0.40`;
  major arterials = `0.83/0.93/0.91/0.39`.
- **Tools:** `python -m dtalite_qa plf <scenario> --period AM` (inventory + bound
  check); `plf.apply()` or `nexta.convert(plf=…, plf_arterial=…)` to write a bounded
  PLF.

## 6. Mode access control (`allowed_use`)

`allowed_use` is matched against each mode token as a **substring**:
- empty or `all` → all modes allowed.
- `closed` → no mode may use the link (carries zero volume).
- a `;`-separated list (e.g. `sov;hov2;hov3`) → only those modes; others get zero
  volume on that link. Use full tokens to avoid accidental substring matches.

## 7. Turn restrictions

- `movement.csv` bans specific `(ib_link → ob_link)` movements (penalty ≥ 10).
- `non_uturn_flag=1` on a link bans the immediate U-turn back along its reverse.
- Restrictions are keyed by **external** link id and mapped to internal indices
  at load. With restrictions present the shortest path is solved exactly in
  link-state space (the state is the incoming link), so a banned turn can force a
  longer feasible detour without dropping the OD. With no restrictions the
  classic node-based path is used (identical results, zero overhead).

---

## 8. Outputs

| file | when | contents |
|------|------|----------|
| `link_performance.csv` | always | per-link volume, `D` (per-lane demand), `doc` (D/C), travel time, speed, VMT/VHT, per-mode `mod_vol_*`, QVDF queue profile |
| `od_performance.csv` | always | per-OD distance/time |
| `system_performance.csv` | always | system totals |
| `route_assignment.csv` | `route_output=1` | per-route node/link ids, distance, times, volume |
| `vehicle.csv` | `vehicle_output=1` | one row per generated vehicle with departure time, node/link path |
| `origin_/destination_accessibility.csv`, `inaccessible_od.csv` | always | zone accessibility |
| `summary_log_file.txt`, `TAP_log.csv` | always / `log_file=1` | run log, gap trajectory |

`link_id`, `node_ids`, and `link_ids` in the outputs are the **external** ids
from your input files. The summary log's per-iteration line reports the relative
gap `(system_total − shortest_path_benchmark) / benchmark`, in generalized cost,
which is non-negative at/with convergence (including toll networks).

---

## 9. QA / control package (`dtalite_qa`)

The `dtalite_qa` Python package (stdlib only) is the stable front end for the
kernel — validate, fill defaults, inventory access control, and check
reachability before running. See `dtalite_qa/README.md`.

```bash
python -m dtalite_qa validate      my_scenario/                 # errors + warnings
python -m dtalite_qa fill          my_scenario/ --out norm/     # normalize (fill defaults, sort links)
python -m dtalite_qa inventory     my_scenario/                 # allowed_use / network inventory
python -m dtalite_qa accessibility my_scenario/                 # demanded-OD reachability per mode
python -m dtalite_qa check         my_scenario/                 # validate + inventory + accessibility
python -m dtalite_qa run           my_scenario/ --exe bin/DTALite.exe   # gate, then run the kernel
```

- **validate** — ERRORS (missing node/link, links not sorted by `from_node_id`
  → CSR corruption, bad node/zone/link refs, non-positive lanes/capacity/speed,
  `end ≤ start` period); WARNINGS (missing settings → defaults, missing demand
  file, unknown `allowed_use` token, QVDF columns absent).
- **fill** — materializes every optional column with the kernel's own default and
  sorts links; the normalized scenario runs **byte-identically** but leaves
  nothing implicit (reproducible batch runs).
- **accessibility** — flags **demanded** OD pairs that cannot be routed under each
  mode's `allowed_use` (the OD the kernel would otherwise silently drop).

`python test_networks/validate_inputs.py my_scenario/` is a thin wrapper kept for
compatibility (delegates to the package).

## 10. Regression suite

```bash
python test_networks/run_regression.py
```
Runs every test network in an isolated copy and checks the intent criteria:
engine completes, gap is non-negative and converges, `allowed_use` is enforced
(zero disallowed-mode volume), per-lane D/C is correct, and turn restrictions
reroute as expected.

## 11. Test networks

`test_networks/` ships ready-to-run scenarios:
`4_node_network`, `I10_corridor_QVDF` (+ `_1lane`/`_2lane`/`_multilane`),
`multilane_bpr`, `turn_restriction`, `sf_multimodal`, `cs_multimodal`,
`sf_conic`, plus the QVDF reference in `qvdf_reference/`. Each multi-feature one
has its own README.
