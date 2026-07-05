# TransCAD → GMNS export guide
*For TransCAD modelers delivering a network + matrices to the TAPLite4MPO pipeline.
Battle-tested on two large TransCAD hand-offs (a 224k-link regional model and a
mid-size coastal MPO); every pitfall below actually happened.*

The goal: export everything, convert nothing silently, **declare** every convention in
`submission.yml`. The intake blocks on anything undeclared — that is a feature.

---

## 1. What to export

**Network (line layer).** From the map: *Tools ▸ Export* the line geographic file (.dbd)
to **shapefile** — but read the truncation warning below first. Export the node layer the
same way (or let the converter derive nodes from link endpoints + a node list).

> **⚠ DBF truncation — the #1 TransCAD hand-off killer.** Shapefile DBF caps at
> **255 fields** and **10-character field names**. A rich TransCAD line layer (one real
> model had 471 fields) silently loses columns and truncates names on export
> (`AB_FACILITYTYPE` → `AB_FACILIT`). One agency's tier-2 TAZ field was truncated away
> and blocked demand mapping for weeks (catalog §7b). **Do BOTH:**
> 1. Export the full attribute table separately: open the line layer's dataview ▸
>    *File ▸ Save As* ▸ CSV (no field limit), keyed by the link `ID`.
> 2. Ship a `working_network_fields.csv` mapping full names → truncated names.

**Matrices — export to OMX.** TransCAD 9+ reads/writes OMX natively: open each matrix ▸
*File ▸ Save As* ▸ **OMX** (or GISDK `CopyMatrix` with an OMX target). One file per
period × class, with the zone mapping embedded — this is the standard hand-off.
On older TransCAD without OMX: *File ▸ Save As* ▸ CSV plus the **zone ID vector**.
**Never round-trip through Excel**: Excel truncates at 1,048,575 rows and one statewide
model lost 85% of its origins that way (catalog §4c). Do NOT ship binary `.mtx` — the
pipeline deliberately does not read it.

**Lookup tables.** The FACTYPE×AREATYPE VDF table (α/β), the capacity table, and the
period definitions — usually in the model documentation or GISDK parameters, not the
line layer.

## 2. Field crosswalk (AB/BA → directed GMNS links)

TransCAD stores one record per physical link with `AB_`/`BA_` directional fields and a
`DIR` flag. GMNS wants **one row per direction**:

| `DIR` | emit |
|---|---|
| 0 | both: AB fields → forward row, BA fields → reverse row |
| 1 | AB row only |
| -1 | BA row only |

| GMNS link.csv | TransCAD | Conversion |
|---|---|---|
| `from_node_id`,`to_node_id` | endpoint node IDs (swap for BA) | |
| `lanes` | `AB_LANES` / period lanes (`AB_AMLANES`) | pick the assignment period's lane field |
| `capacity` | `AB_CAP*` / `AB_HRCAPAC` | **per-lane hourly**: check whether the field is total (divide by lanes — one regional model's `HRCAPAC` was total and cost a 4× V/C error, catalog §1a) and whether it is hourly/period/daily (a daily `AB_CAP` used as-is gave V/C ≈ 0.007, catalog §1b) |
| `free_speed` + `vdf_free_speed_mph` | `AB_SPEED`/`AB_FFSPEED` (mph) | emit both; declare the unit |
| `length` (m) + `vdf_length_mi` | `Length` (mi) | ×1609.344 / as-is |
| `vdf_fftt` | `AB_TIME`/`AB_FREETIM` (min) | if ≤0, fall back to `60·mi/mph` |
| `link_type` / `factype` | `AB_FACILIT` | keep the raw code + supply the VDF lookup |
| `vdf_alpha`,`vdf_beta` | FACTYPE×ATYPE table | from documentation, not the layer |
| `allowed_use` / `toll_<mode>` | HOV/toll flags | access ban ≠ toll cost (catalog §8) |
| `org_link_id` | `ID` | keep it — every validation join uses it |

Zones: centroid nodes must get `node_id == zone_id` (renumber compactly 1..Z, keep
originals in `org_node_id`/`org_zone_id`); sort links by `from_node_id` after renumbering.

## 3. TransCAD-specific pitfalls (all field-verified)

1. **Multiple capacity columns** that differ ~5× (`AB_CAP` daily / `AB_CAP_PK` peak /
   `AB_CAP_OFF`): do not guess — declare which one is the assignment capacity and its
   duration.
2. **Period capacities that scale exactly with period length** (3:6:3:12) mean the model
   was built with a flat PLF; get the real peak-load factor (see `peak_load_factor.md`).
3. **Tiered TAZ systems** (matrix keyed on a different TAZ level than the network
   carries): ship the correspondence CSV explicitly — do not rely on the truncated DBF.
4. **Connector coding** (`FACILIT` 100/200, lane-count sentinels like `AMLANES=9`):
   document the sentinel meanings.
5. **Turn penalty tables**: TAPLite currently supports hard bans only
   (`movement.csv` with `penalty ≥ 10`); graded seconds-per-turn tables do not apply yet.

## 4. Declare (`submission.yml`)

```yaml
network:
  length_unit: mi
  speed_unit: mph
  capacity_basis: per_lane        # or total — CHECK (catalog 1a)
  capacity_period: hourly         # or peak_period/daily — name the source column!
  capacity_source_field: AB_CAP_PK
  directionality: AB_BA_with_DIR
zones:
  zone_id_basis: "matrix label = centroid node ID -> compact 1..Z"
  correspondence: taz_correspondence.csv   # if tiered
demand:
  demand_kind: vehicle_trips      # or person_trips + occupancy per class
  periods: {AM: [6, 9]}
  peak_load_factor: 0.92          # the real PLF, not 1.0
vdf:
  vdf_source: "Model doc Table X: alpha/beta by FACTYPE x ATYPE"
validation:
  count_field: AADT_2019          # the observed-count column, or the loaded-network flow fields + their period
```

*See also:* [CONVERSION_ERRORS_CATALOG.md](CONVERSION_ERRORS_CATALOG.md) (§1, §4c, §7 are
the TransCAD sections) · [CUBE_EXPORT_RECIPE.md](CUBE_EXPORT_RECIPE.md) ·
[VISUM_TO_GMNS.md](VISUM_TO_GMNS.md) · [peak_load_factor.md](peak_load_factor.md)
