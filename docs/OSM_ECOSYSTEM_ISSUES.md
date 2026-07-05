# OSM→GMNS ecosystem — issue list for student fixes

## Dataset & code (everything you need)

| What | Path |
|---|---|
| **Dataset** (OSM extract, Tempe AZ, 4 MB) | `test_networks/data_Tempe_network/tempe.osm.pbf` |
| Pipeline step 1: OSM → GMNS macro | `test_networks/data_Tempe_network/step1_osm2gmns.py` |
| Pipeline step 2: zones + connectors + demand → runnable | `test_networks/data_Tempe_network/step2_zones_demand_run.py` |
| Pipeline step 3: meso movement-link assignment (**the acceptance test** — blocked on N-issues below) | `test_networks/data_Tempe_network/step3_meso_assignment.py` |
| Runnable scenario + outputs + HTML map | `test_networks/data_Tempe_network/gmns_run/` |
| **net2cell minimal repro** (300-link subset where meso WORKS) | `test_networks/data_Tempe_network/tiny/` + `tiny_out/` |
| Kernel exe | `cmake_build_rel/DTALite_exe.exe` (build: `cmake --build cmake_build_rel --target DTALite_exe`) |
| Package sources to fix (site-packages) | `osm2gmns 1.0.1` · `gmns_ready 0.1.1` · `net2cell 0.1.3` (fork the GitHub repos; file:line refs below) |

Found while building the small-MPO turnkey path **osm2gmns → gmns-ready → TAPLite →
net2cell** on the Tempe test network (`test_networks/data_Tempe_network/`,
`tempe.osm.pbf`, 10,661 nodes / 22,296 links). Every issue below was hit in a real run;
each has the exact location, root cause, suggested fix, and difficulty. Versions:
**osm2gmns 1.0.1 · gmns-ready 0.1.1 · net2cell 0.1.3 · pandas 3.0.2 · geopandas (current)**.

Reproduce everything from `test_networks/data_Tempe_network/`:
`step1_osm2gmns.py` → `step2_zones_demand_run.py` → kernel run → `dtalite_qa/vizmap.py`.

---

## osm2gmns 1.0.1

**O1. `outputNetToCSV` does not create the output folder, and the failure is silent.** — EASY
- Symptom: `E... io.cpp:96] Cannot open file ".../gmns_macro/node.csv"`; the Python call
  returns normally, exit code 0, no exception — the pipeline continues with no files.
- Root cause: the C++ io layer (`io.cpp:91-96`) logs with glog and returns; the Python
  wrapper never checks or raises, and never `os.makedirs(output_folder)`.
- Fix: in the Python wrapper, `os.makedirs(output_folder, exist_ok=True)` before the
  native call, and raise `IOError` when the native writer reports failure.

**O2. `zone_id` is written as a float string (`37.0`) in node.csv.** — EASY
- Symptom: downstream parsers doing `int(zone_id)` crash (see N2 below); GMNS consumers
  expect integer zone ids.
- Root cause: activity/zone info stored as float and serialized without int cast.
- Fix: cast to int (or empty) on output.

**O3. Convention trap: `capacity` is TOTAL link capacity, not per-lane.** — EASY (doc) / MEDIUM (flag)
- Symptom: feeding osm2gmns capacity straight into a kernel that treats `capacity` as
  per-lane (TAPLite: `Link_Capacity = lanes × capacity`) inflates capacity by the lane
  count — the same class of error as CONVERSION_ERRORS_CATALOG §1a.
- Fix: state the basis in the docs/column comment, and/or add
  `outputNetToCSV(..., capacity_basis='per_lane'|'total')`.

## gmns-ready 0.1.1

*(`quick_check` and the validators worked well throughout — these issues are all in
`build_network`.)*

**G1. pandas-3 incompatible WKT detection: `dtype == object`.** — EASY→MEDIUM (the key fix)
- Symptom: `TypeError: Input must be valid geometry objects: POINT (-111.97 33.31)` from
  `geopandas _ensure_geometry`, for both the zone table and the link table.
- Root cause: `build_network.py:82,87,92` guard WKT parsing with
  `if df["geometry"].dtype == object:`. In pandas 3.0 string columns default to the new
  `str` dtype, so the guard is False and `wkt.loads` is never applied; the raw strings
  then hit the GeoDataFrame constructor.
- Fix: use `pandas.api.types.is_string_dtype(...) or is_object_dtype(...)`, or simply
  try-parse when the first element is a `str`. Add a pandas-3 environment to CI.

**G2. Connector geometry written as WKT strings into a geometry column.** — EASY
- Symptom: `TypeError: Value should be either a BaseGeometry or None, got POINT (...)`
  (geopandas `array.py __setitem__`) during connector generation.
- Root cause: new connector rows build `geometry` as f-string WKT and assign into an
  existing GeoDataFrame geometry column.
- Fix: construct `shapely.geometry.Point/LineString` objects instead of strings.

**G3. `zone.csv` input schema is undocumented and unvalidated.** — EASY
- Symptom: `KeyError: 'node_id'` (`build_network.py:21`), then `KeyError: 'geometry'` —
  no message says what the zone table must contain.
- Root cause: `process_node_data` requires `node_id`, `zone_id`, `geometry` columns but
  nothing validates or documents this (the docstring only says "zone.csv (from
  extract_zones)").
- Fix: validate inputs up front with a clear error listing required columns; document the
  schema in the docstring/README.

**G4. `build_network` mutates the caller's dataframes.** — EASY
- Symptom: side effects on user data; under pandas copy-on-write, in-place column
  assignments on passed frames are unreliable (part of why G1 bites twice).
- Fix: `df = df.copy()` at function entry for every input frame.

## net2cell 0.1.3

**N1. `loadNetFromCSV(folder=...)` doesn't resolve default file names.** — EASY
- Symptom: `ERROR: node_file is not specified` even though `folder` contains
  node.csv/link.csv.
- Root cause: `loadNetFromCSV` (load_from_csv.py:515) only uses explicit
  `node_file`/`link_file` paths; the `folder` parameter is never joined with defaults.
- Fix: `node_file = node_file or os.path.join(folder, "node.csv")` (same for the others).

**N2. `int(zone_id)` crashes on float-formatted ids.** — EASY (first student exercise)
- Symptom: `ValueError: invalid literal for int() with base 10: '37.0'`
  (`load_from_csv.py:70`, `_loadNodes`).
- Root cause: `int(zone_id)` on the raw string; osm2gmns writes `37.0` (see O2 — fix both
  sides).
- Fix: `int(float(zone_id))` with a try/except that warns and skips.

**N3. `buildMultiResolutionNets` returns `None` (mutates in place, undocumented) and
`outputNetToCSV` gives an opaque crash when handed the wrong object.** — EASY
- Symptom: the natural usage `mr = buildMultiResolutionNets(net); outputNetToCSV(mr, ...)`
  crashes with `AttributeError: 'NoneType' object has no attribute 'node_dict'`
  (`writefile.py:23`) — *after* partially writing files (non-atomic).
- Root cause: `buildMultiResolutionNets` mutates `net` in place (attaching
  `net.mesonet` / `net.micronet`) and returns `None`; nothing documents this, and the
  writer does not validate its `network` argument.
- Correct usage (verified working on Tempe): call `buildMultiResolutionNets(net, ...)`,
  then `outputNetToCSV(net, output_folder)` — this writes `mesonet/` (and `macronet/`,
  `movement.csv`).
- Fix: `return network` from `buildMultiResolutionNets` (keeping in-place behavior);
  raise a clear `TypeError("expected the macro network object")` in `outputNetToCSV`;
  write to a temp folder and move on success (atomic output); document the meso/micro
  attachment in the docstring.

**N5. `buildMultiResolutionNets` crashes on an internally-generated EMPTY Point during
lat-lon back-transform on the full Tempe net.** — MEDIUM (good debugging exercise)
- Symptom: `IndexError: list index out of range` at `util_geo.py:136`
  (`_transform` → `Point` branch: `list(map(func, shape.coords))[0]` with empty coords).
  Works on a 300-link subset; fails on the full 22,296-link net.
- Verified NOT the input: 0 degenerate link geometries, 0 NaN node coords in the CSVs.
  The empty `Point()` is created inside the meso build itself.
- Hypotheses ruled out already: intersection consolidation (rebuilt the macro net
  WITHOUT `consolidateComplexIntersections` — same crash), degenerate input geometry,
  NaN coordinates. So the trigger is some node/link configuration in the full net that
  the 300-link subset lacks (boundary nodes? dead-end stubs? a specific movement
  pattern?).
- Student task: BISECT the link set to isolate the offending configuration (binary
  search on link subsets reproduces in ~15 runs); guard `_transform` against empty
  geometries with a clear error naming the node/link; fix the geometry construction at
  the source. Acceptance: `step3_meso_assignment.py` then runs the TAPLite assignment on
  the movement-link meso network end-to-end.

**N4. No progress or error surface on large inputs.** — MEDIUM
- Symptom: on the full 22k-link Tempe net the process dies with no output at all when
  run non-interactively (the N2 crash was only diagnosable after shrinking to a
  300-link subset).
- Fix: logging with flush per stage (load / movement gen / meso / micro / write), and let
  exceptions propagate to the caller instead of printing-and-exiting.

---

## Cross-cutting assignment for the team

1. **Fix order:** N2+O2 (one afternoon) → G1+G2 (the real pandas-3 work) → N1/N3/G3/G4
   (polish) → O1 (wrapper) → N4 (logging).
2. **Add a joint CI smoke test**: the 4 MB `tempe.osm.pbf` through
   osm2gmns → gmns-ready `quick_check` → a TAPLite assignment → net2cell meso, asserting
   each stage's outputs exist and `quick_check` passes — so the three packages stop
   breaking each other's assumptions. The scripts in `test_networks/data_Tempe_network/`
   are the seed.
3. **Convention rule** (from CONVERSION_ERRORS_CATALOG.md): every tool must state its
   capacity basis (per-lane vs total) and id types (int) at the file boundary.

Working reference: the completed Tempe loop (osm2gmns → zones/connectors → 30k-veh
gravity demand → TAPLite gap 0.0005% in 0.5 s → gmns-ready re-check with 0 inaccessible
OD → `assignment_map.html` via `dtalite_qa/vizmap.py`).
