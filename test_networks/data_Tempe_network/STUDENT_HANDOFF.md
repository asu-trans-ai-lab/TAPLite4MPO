# Student handoff — debug the OSM→GMNS ecosystem on the Tempe dataset

**Mission:** three open-source packages (osm2gmns, gmns-ready, net2cell) must work
together to take an OpenStreetMap extract all the way to a traffic assignment. Today
they break each other in 11 diagnosed places. Your job: fix them, prove it with the
acceptance tests, and send the fixes upstream.

## 0. What's in this folder

| File | Role |
|---|---|
| `tempe.osm.pbf` | THE dataset — 4 MB OSM extract, Tempe AZ (public) |
| `step1_osm2gmns.py` | OSM → GMNS macro net (10,661 nodes / 22,296 links) |
| `step2_zones_demand_run.py` | 36 grid zones + connectors + 30k gravity demand → `gmns_run/` |
| `step3_meso_assignment.py` | **acceptance test** — meso movement-link assignment (blocked by the net2cell bugs) |
| `gmns_run/` | working scenario + `assignment_map.html` (the target state) |
| `tiny/`, `tiny_out/` | 300-link minimal repro where net2cell meso already works |
| `movement.csv`, `UTDF.csv` | signal/movement data for the meso track |

## 1. Environment

```
pip install osm2gmns==1.0.1 gmns-ready==0.1.1 net2cell==0.1.3 pandas geopandas scipy
```
Kernel exe: `cmake --build cmake_build_rel --target DTALite_exe` from the repo root
(do NOT build with plain g++ — broken exe). Note: **pandas 3.x is deliberate** — two of
the bugs only appear under pandas 3's `str` dtype.

## 2. First hour — run the working loop before touching anything

```
python step1_osm2gmns.py          # (creates gmns_macro/; note bug O1 if the dir is missing)
python step2_zones_demand_run.py
cd gmns_run && ../../../cmake_build_rel/DTALite_exe.exe && cd ..
python ../../dtalite_qa/vizmap.py gmns_run     # open assignment_map.html
python -c "import gmns_ready; gmns_ready.quick_check()"   # run inside gmns_run/
```
Expected: gap ≈ 0.0005% in ~0.5 s; 0 rows in `inaccessible_od.csv`; a colored V/C map.

## 3. The bug list

**`../../docs/OSM_ECOSYSTEM_ISSUES.md`** — 11 issues, each with symptom → file:line →
root cause → suggested fix → difficulty. Fix order: **N2+O2** (one afternoon, int('37.0')
crashes) → **G1+G2** (the real pandas-3 work in gmns-ready build_network) → N1/N3/G3/G4
(polish) → O1 (silent-failure wrapper) → N4 (logging). Fork the GitHub repos; the
file:line references match the pip versions above.

## 4. Acceptance tests (what "done" means)

1. `step3_meso_assignment.py` runs end-to-end: net2cell builds the full 22k-link meso
   net, the kernel assigns it, and movement links (`mvmt_txt_id`) carry turn volumes.
2. `step2` runs **without** the workarounds marked in its comments (gmns-ready
   `build_network` usable directly under pandas 3).
3. The joint smoke test passes: pbf → osm2gmns → gmns-ready `quick_check` → assignment →
   net2cell meso, asserting each stage's outputs exist. (Write it as `test_tempe_loop.py`
   — it becomes the CI guard that keeps the three packages compatible; seed it from
   steps 1-3.)
4. Each fix lands as an upstream PR with the Tempe repro attached.

## 5. Architecture fact you need (and a common confusion)

**gmns-ready contains NO assignment engine.** Its `validate_accessibility` /
`validate_assignment` do `import DTALite` (the DTALite **pypi package**) and run a real
assignment through it to check connectivity — everything else in gmns-ready is pure
file/topology checking. So: osm2gmns *builds*, gmns-ready *checks*, DTALite/TAPLite
*solves*, net2cell *refines resolution*. Keep the roles separate in your fixes — do not
add solving logic to a checker or checking logic to the builder.

## 6. Who to ask
Conventions & catalog: `github_taplite/docs/CONVERSION_ERRORS_CATALOG.md`. Kernel
behavior: `docs/KERNEL_FEATURE_CHANGES.md`. Upstream owners: osm2gmns (asu-trans-ai-lab),
gmns_ready (hhhhhenanZ), net2cell (asu-trans-ai-lab).
