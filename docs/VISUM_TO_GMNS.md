# Visum → GMNS export guide
*For PTV Visum modelers delivering a network + demand to the TAPLite4MPO pipeline*

TAPLite4MPO consumes plain GMNS CSV files (`node.csv`, `link.csv`, demand OD tables) plus a `submission.yml` that **declares** your model's conventions. The intake step will block on anything undeclared, so the goal of this guide is: export everything, convert nothing silently, declare everything.

---

## 1. What to export from Visum

Two workable routes; the attribute-list route is preferred because it gives clean tabular CSV.

**A. Attribute lists (preferred).** Open the link list from the **Lists** menu (Lists > Network > Links in recent versions; exact wording varies — consult your version's manual), add the columns below via the list's attribute selection, then use the list toolbar's save/export function to write a `.att` / CSV file. Repeat for nodes, zones, and connectors. `.att` files are semicolon-delimited text with a header block — fine as-is, or re-save as CSV.

**B. Shapefile export.** Visum's GIS shapefile export (requires the GIS-interface add-on) splits the network into separate **node, link, zone, zone-centroid, and connector layers** — select all of them. The DBF tables carry the same attributes; you lose nothing except you must pick attributes in the export dialog.

Export these tables and fields:

| Table | Fields |
|---|---|
| **Links** | `No`, `FromNodeNo`, `ToNodeNo`, `TypeNo`, `NumLanes`, `CapPrT`, `V0PrT` [km/h], `Length` [km], `TSysSet` |
| **Nodes** | `No`, `XCoord`, `YCoord` |
| **Zones** | `No`, `XCoord`, `YCoord` |
| **Connectors** | `ZoneNo`, `NodeNo`, direction (origin/destination), `T0` (and length/speed if used) |
| **OD matrices** | One matrix per transport system (or demand segment) **per assignment period** |

**⚠ `CapPrT` — check before you export.** In Visum the capacity basis is **not universal**: the *link-type* `CapPrT` is conventionally per-lane, while the *link-level* `CapPrT` is usually the **total directed-link capacity across all lanes** (this is how e.g. the Aimsun importer interprets it). It may also be coded per assignment period rather than per hour, depending on how your model was built. **Open your model, check which one you have, and write it into `submission.yml`** (Section 4). Do not let the pipeline guess.

**Matrices.** Use the **OMX Export add-in** (shipped with Visum since 14.00-08; callable from the menu or a procedure sequence) — OMX is the cleanest handoff and preserves zone numbering. Alternatively, save each matrix from the **matrix editor** to a text/CSV matrix format, or dump via COM. One file per transport system per period; name them so the mapping is obvious (`odme_AM_car.omx`, etc.). Also export the zone-number vector so the matrix row/column order is unambiguous.

---

## 2. Field crosswalk: Visum → GMNS

**node.csv**

| GMNS | Visum | Notes |
|---|---|---|
| `node_id` | Node `No` | |
| `x_coord`, `y_coord` | `XCoord`, `YCoord` | Note the projection/EPSG in submission.yml |
| `zone_id` | Zone `No` (on the zone-centroid node) | Centroids become nodes; see connectors below |

**link.csv**

| GMNS | Visum | Conversion |
|---|---|---|
| `from_node_id` | `FromNodeNo` | |
| `to_node_id` | `ToNodeNo` | |
| `lanes` | `NumLanes` | |
| `capacity` | `CapPrT` | **GMNS/TAPLite wants PER-LANE, PER-HOUR.** If your `CapPrT` is total-link: divide by `NumLanes`. If per-period: divide by period hours or declare a PLF |
| `free_speed` | `V0PrT` | keep native units but declare them; also fill `vdf_free_speed_mph` = km/h × 0.621371 |
| `length` | `Length` | GMNS length in **meters** = km × 1000; also fill `vdf_length_mi` = km × 0.621371 |
| `link_type` | `TypeNo` | Keep the raw number; supply a TypeNo → VDF lookup (Section 3) |
| `allowed_use` | `TSysSet` | e.g. `"C,H"` → `allowed_use = 'C;H'` mapped to the pipeline's per-class access codes (car/truck/HOV…) |
| `vdf_alpha`, `vdf_beta`, `vdf_type` | from the model's VDF settings per LinkType | Not a per-link Visum attribute — see Section 3 |

**Connectors** → ordinary GMNS links: centroid node → `NodeNo` (and reverse for destination connectors), `free_speed`/`length` consistent with the exported `T0`, high capacity, `link_type` reserved for connectors.

---

## 3. Visum-specific pitfalls

- **Units are metric.** Visum models are typically km and km/h (the model's unit setting is configurable — verify it in your network settings before exporting). Declare the units; never assume the pipeline knows. A silent km→mi mix-up inflates every VDF travel time by 60%.
- **`CapPrT` basis varies by model** (per-lane vs total, hourly vs period). Check, then declare. This is the single most common intake failure across agencies.
- **Connectors are real network objects in Visum.** Export them and convert them; do **not** let the downstream pipeline regenerate connectors from zone centroids — you would change accessibility and loading points.
- **VDF parameters live on the Volume-Delay function settings, not on links.** Visum assigns a BPR-like function (with parameters a, b, c…) per LinkType. Export or transcribe that TypeNo → (function form, parameters) table from your procedure/assignment settings. The TAPLite kernel supports vdf_type 0–8 (BPR, conical, QVDF, BPR2, INRETS, Akçelik, SANDAG, SCAG piecewise, SCAG ramp-meter), so most Visum functions map directly; anything exotic needs a conversation with the pipeline team.
- **One-way links are separate directed objects.** Visum links are directed (a two-way street is two link objects, and a closed direction has `TSysSet` empty or 0 lanes). So there is **no AB/BA column split** to undo — just drop links that are closed to all relevant transport systems (lanes = 0 or empty `TSysSet`).
- **Zone numbering is often non-contiguous.** The kernel wants compact zone ids; renumber 1…N but keep the original Visum zone `No` in an `org_zone_id` column and remap the matrices consistently (OMX mappings make this easy).

---

## 4. The declare step: `submission.yml`

The intake dashboard blocks until these are declared. From a Visum export you must state:

```yaml
units:
  length: km          # Visum native; pipeline converts
  speed: kmh
capacity:
  basis: total_link   # or per_lane — CHECK your CapPrT (Section 1)
  period: hourly      # or e.g. "AM_3hr" if CapPrT is period capacity
peak_load_factor: 1.0 # PLF if demand is period trips assigned against hourly capacity
demand:
  kind: vehicles      # or persons — per transport system! Car matrices are often
                      # person trips pre-occupancy; truck matrices vehicles
  periods: [AM, MD, PM]
  matrix_per_tsys: {C: car_AM.omx, H: hgv_AM.omx}
network:
  crs: "EPSG:xxxxx"
  count_field: ""     # link attribute holding observed counts, if delivered (often a UDA like AADT)
vdf:
  lookup: linktype_vdf.csv   # TypeNo -> vdf_type, alpha, beta (Section 3)
```

Rule of thumb: if you had to look it up inside your `.ver` file, the pipeline can't know it — declare it.

---

**Sources:** [PTV Visum Import/Export knowledge base](https://support.ptvgroup.com/en-US/knowledgebase/category/?id=CAT-01033) · [Shapefile export via COM](https://support.ptvgroup.com/en-us/knowledgebase/article/KA-05021) · [OMX wiki — VISUM add-ins](https://github.com/osPlanning/omx/wiki/VISUM) · [PTV Visum matrix editor KB](https://support.ptvgroup.com/en-US/knowledgebase/category/?id=CAT-01040) · [Aimsun Visum importer (CapPrT interpretation)](https://docs.aimsun.com/next/22.0.1/UsersManual/VisumImporter.html) · [ODOT PTV Vision network setup guide](https://www.oregon.gov/ODOT/Planning/Documents/APMv2_App8B.pdf)

*See also:* [CONVERSION_ERRORS_CATALOG.md](CONVERSION_ERRORS_CATALOG.md) · [TRANSCAD_EXPORT_GUIDE.md](TRANSCAD_EXPORT_GUIDE.md) · [CUBE_EXPORT_RECIPE.md](CUBE_EXPORT_RECIPE.md) · [MPO_ONBOARDING_GUIDE.md](MPO_ONBOARDING_GUIDE.md)
