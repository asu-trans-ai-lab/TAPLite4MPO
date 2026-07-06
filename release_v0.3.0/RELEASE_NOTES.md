# TAPLite4MPO v0.3.0 — the MPO workflow product

v0.2.0 shipped the efficiency ladder inside the kernel; **v0.3.0 ships the
workflow around it**: a planner-facing product surface — Python API, `taplite`
CLI, run-config YAML, and a one-command HTML report — all inheriting the
no-guessing intake gate. Kernel unchanged from v0.2.0 (same solver, same
regression baselines).

**New in v0.3.0 — the four-layer surface**

| Layer | Entry point | What it does |
|---|---|---|
| Python API | `from dtalite_qa.api import Network, Demand, Scenario, AssignmentEngine, Result` | object model over the kernel: load a GMNS folder, compose demand, run, get MOEs — every run gate-checked + manifest-stamped |
| CLI | `taplite validate / run / report / compare` | the analyst front door; exit codes 0/1/2 (+3 = timeout) for scripting |
| Run-config YAML | `taplite run configs/chicago_sketch_baseline.yml` | one file = scenario + settings + outputs; works with PyYAML or a strict stdlib fallback parser |
| HTML report | `taplite report <run_dir>` | one self-contained file: summary, convergence, MOEs, V/C histogram, assignment map, count scatter, manifest |
| Notebooks | `notebooks/00–02` | quickstart / load-GMNS / baseline on Chicago Sketch |

**Benchmark**: `docs/EFFICIENCY_CORNERSTONE_BENCHMARK.md` — the L1/L2/L3
warm-start ladder measured on four cornerstone networks (Chicago Sketch,
Chicago Regional, ARC Atlanta + super-zone subarea, SCAG RTP24). Headline: ARC
rerun at the same ~0.09 % gap in **8.0× less compute** via the L3 θ-column
replay; the ladder is aggregation-invariant on the subarea case.

**Hardening in this release (post Fable-5 reviews)**
- intake gate: staleness now also watches per-mode demand files declared in
  `mode_type.csv` (+ `movement.csv`); the API settings-patch path re-checks the
  gate on the SOURCE scenario so a stale audit can never run silently; a
  bypassed gate is stamped `UNCHECKED` in the manifest, never null
- `Result.export` refuses to overwrite a folder that is not a prior run export
- assignment map renders at real MPO scale (fixed a JS spread-args limit that
  blanked the map above ~65 k links, e.g. TRMG2's 135,922)
- composed demand file lists are matched to `mode_type.csv` declarations by
  name — a reordered list can no longer silently swap demand between classes
- stale kernel outputs in a source folder are no longer copied into (and
  reported from) a new run; a nonzero kernel exit now marks the run not-ok
- run-config: `assignment.timeout` key; `warm_start_columns` resolved relative
  to the config file; BOM-tolerant; the stdlib fallback parser now *raises* on
  constructs it cannot represent (deep nesting, flow lists) instead of
  mis-parsing
- kernel subprocess output decoded `utf-8/replace` (no post-solve decode
  crashes); cp1252 fallback when reading agency CSVs
- wheels: cp39–cp314 (cibuildwheel v3.2), publish `skip-existing`, macOS
  best-effort as before; `__version__` single-sourced from package metadata

**Install**
```
pip install taplite4mpo          # wheels: win/linux cp39-cp314; macOS = sdist
```
Note for pip users: `taplite run` needs a kernel executable and a scenario on
disk — clone the repo (`bash build.sh` → `bin/DTALite.exe`, sample configs in
`configs/`) or point `assignment.exe`/`--exe` at your own kernel build. The
`configs/` folder and notebooks are repo-only by design (kept out of the sdist).

**Compatibility**: no breaking changes to `python -m dtalite_qa` or settings
keys; all v0.2.0 recipes (including `docs/RERUN_RECIPE.md`) run unchanged.
