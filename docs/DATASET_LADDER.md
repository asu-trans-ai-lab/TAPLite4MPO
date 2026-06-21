# Dataset ladder — which example to start with

Four examples of increasing realism. Climb in order: each rung adds **one** new idea. Do not
jump to ARC Atlanta or super-zones before a minimum run works.

| Rung | Example | Teaches | Status / location |
|---|---|---|---|
| **1** | **Chicago Sketch — minimum runnable** | GMNS inputs, BPR, capacity×lanes, period settings, `link_performance.csv`, VMT/VHT/V·C, basic validation | ✅ `kernel/data_sets/03_chicago_sketch` |
| **2** | **Chicago Regional — scale** | large OD loading, binary demand, convergence/performance, super-zones, skims, scenario workflow | ✅ `kernel/data_sets/04_chicago_regional` |
| **3** | **ARC Atlanta — agency reproduction** | agency field mapping, lookup tables, modified BPR (`vdf_A`), capacity convention, PLF, user classes, `allowed_use`, toll/generalized cost, validation vs agency volumes | ✅ `examples/arc_atlanta/` |
| **4** | **Chicago Downtown OSM — public quick start** | OSM→GMNS (osm2gmns / gmns-ready), zones, connectors, link-type defaults, simple demand, BPR; *teaching scenario, not agency-validated* | ⏳ planned |

---

### Rung 1 — Chicago Sketch (start here)
The smallest thing that runs. Use it to learn the five input files and to read a
`link_performance.csv`. **Don't** add QVDF, super-zones, tolls, or multi-class here.
```bash
cd kernel/data_sets/03_chicago_sketch && cp ../../../bin/DTALite.exe . && ./DTALite.exe
```
*Avoids the mistake:* "I don't know what a runnable scenario even looks like."

### Rung 2 — Chicago Regional (scale)
Same model form, real size. Learn binary demand, convergence/gap, and **super-zone
aggregation** (compress the response, not the data — verify the `S=N` corner case first).
```bash
cd kernel/data_sets/04_chicago_regional && cp ../../../bin/DTALite.exe . && ./DTALite.exe
```
*Avoids the mistake:* "it worked small, then fell over / went slow at scale."

### Rung 3 — ARC Atlanta (the agency gold standard)
A real MPO conversion: **model semantics, not just a shapefile** — capacity convention, PLF,
modified BPR, user classes, allowed-use, tolls, and validation against ARC's own counts
(region %RMSE 23%). This is where the Golden Path's Stages 1–4 are fully worked.
```bash
cd examples/arc_atlanta
python -m dtalite_qa intake gmns            # GATE: READY (declarations complete)
python arc_calibrate.py && ( cd gmns_calibrated && ./DTALite.exe )
python arc_validate_run.py gmns_calibrated
```
*Avoids the mistake:* "I converted the shapefile but the conventions were guessed."

### Rung 4 — Chicago Downtown OSM (planned)
Public-data onboarding via osm2gmns + gmns-ready, then a TAPLite-ready teaching scenario.
**This is a demo, not an agency-validated model** unless observed counts and lookup tables
are added. *(Not built yet — see the missing-items list in the Golden Path.)*

---

**Rule of thumb:** Atlanta teaches full agency reproduction; Chicago teaches minimum and
scale; Chicago Downtown OSM teaches public-data onboarding. New analyst → Rung 1. New
agency model → Rung 3.
