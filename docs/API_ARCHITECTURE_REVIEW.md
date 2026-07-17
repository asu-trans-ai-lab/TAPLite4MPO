# taplite4mpo PyPI package — API architecture review

*2026-07. A design review of the package surface (`pytaplite` + `dtalite_qa` +
the C++ kernel), triggered by the NVTA cross-MPO robustness exercise. Each
issue states the design rule it violated and how it is now resolved.*

## The layering rule

```
User space (external ids, agency conventions)
   pytaplite  — thin driver API: assign / accessibility / superzone /
                demand_to_binary; loads results back
   dtalite_qa — QA & orchestration: intake gate, checks, converters,
                super-zones, skims, workflow, dashboards
--------------------------------------------------------------- id boundary
Kernel space (dense internal ids — invisible to users)
   TAPLite.exe / DTALite shared lib — the solver. Renumbers sparse
   node/zone ids internally at read time; every output file reports the
   ORIGINAL external ids.
```

**Rule: id-space translation happens exactly once, at the kernel boundary,
inside the kernel.** No Python layer, notebook, or agency workflow should
renumber ids or back-map outputs.

## Issues identified and resolved

### 1. Id-space responsibility was in the wrong layer (the NVTA crash)
The kernel required dense ids with `zone_id == node_id`; every caller with
sparse agency ids (NVTA subareas) had to renumber in user space and back-map
outputs (the dtalite4cube `_internal/` + backmap steps). Callers that didn't
know this crashed the kernel (18 GB / silent death — issue #6).
**Resolved:** the kernel renumbers internally (zones-first dense 1..Z),
translates zone-id inputs (demand CSV/binary, stored column pools, GPS
origins) at read time, and reports all outputs in original external ids.
User-space renumbering is now optional everywhere.

### 2. Product naming: the kernel is TAPLite, not DTALite
The static-assignment kernel was built and shipped as `DTALite.exe`, the name
of the sibling dynamic-assignment product — confusing for users of both.
**Resolved:** the canonical binary is **`bin/TAPLite.exe`** (`bin/TAPLite` on
macOS/Linux). `build.sh` also writes a `DTALite`-named compatibility copy, and
every lookup (`pytaplite.find_kernel`, the ARC/NVTA pipelines, `$TAPLITE_EXE`
with `$DTALITE_EXE` still honored) accepts both names. Internal C symbols
(`DTA_AssignmentAPI`) are a stable C ABI and stay unchanged.

### 3. Kernel capabilities not surfaced in the package API
Super-zones, binary demand, compact path columns, and accessibility all
existed but only as example scripts, CLI subcommands, or undocumented settings
columns — invisible to a `pip install taplite4mpo` user.
**Resolved — one obvious call each in `pytaplite`:**
```python
import pytaplite

r = pytaplite.assign(scenario)                       # equilibrium assignment
a = pytaplite.accessibility(scenario)                # kernel-internal, no assignment
pytaplite.superzone(scenario, "sz/", k_target=1500)  # demand-side compression
pytaplite.demand_to_binary(scenario)                 # packed .bin OD for large tables
r = pytaplite.assign(scenario, settings_overrides={
        "demand_format": 1,      # read the .bin demand (large problems)
        "column_output": 1,      # compact DTAC path store instead of wide CSV
        "route_output": 0})      # skip the 5D route store (lean runs)
```
All of these operate on external ids; the kernel keeps id concerns internal
(super-zoned scenarios feed straight into `assign()` the same way).

### 4. Accessibility: internal kernel call vs the access4gmns package
Accessibility was computed by the kernel (`number_of_iterations = 0` →
accessibility-only mode writing `od_performance.csv`,
`origin/destination_accessibility.csv`) but was undocumented and unreachable
from Python. **Resolved:** `pytaplite.accessibility(scenario)` runs the
kernel-internal computation and returns the three tables as an
`AccessibilityResult` (`.od`, `.origins`, `.destinations`, `.to_pandas()`).

**Division of labor with `access4gmns`** (kept deliberately):
- `taplite4mpo` — auto/highway accessibility with assignment-grade path logic,
  at kernel speed, plus congested times as a by-product of assignment.
- `access4gmns` — multimodal and cross-modal measures (walk/bike/transit,
  cumulative-opportunity, gravity, dual access), which can re-impedance its
  network from this kernel's `link_performance.csv` for congested access.
This split is already encoded in access4gmns's `taplite_bridge` ("this module
reads kernel OUTPUT; it never runs the kernel").

### 5. Options for large problems are settings columns, not API magic
Binary demand (`demand_format=1`), compact columns (`column_output=1`), and
route-store control (`route_output`) are deliberate settings.csv columns —
the settings file remains the single record of what a run did. The package
exposes them through `settings_overrides` (which writes settings.csv, never a
hidden side channel), so a run folder is always self-describing and
reproducible by re-running the kernel in it.

### 6. Entry-point fragmentation (the original complaint)
Scattered scripts made every example look different. **Resolved:** each
worked example has ONE stage-by-stage pipeline with the same gate names
(`check → declare/convert → prepare → run → validate`):
`examples/arc_atlanta/arc_pipeline.py` (public data, notebook
`ARC_END_TO_END.ipynb`) and `nvta_run/nvta_pipeline.py` (bring-your-own
private data, notebook `NVTA_END_TO_END.ipynb`). Full runs are never launched
without an explicit flag.

## Remaining design debts (tracked, not yet resolved)

- **Wheel parity:** the PyPI wheels bundle the in-process binding but not the
  standalone `TAPLite.exe`; a pip-only user still needs `build.sh` for the
  subprocess path. A `taplite4mpo-kernel` binary wheel (or bundling the exe as
  package data per platform) would close it.
- **One assignment per process** (kernel global state) — documented in
  ARCHITECTURE.md; a re-entrant kernel is a larger refactor.
- **Matrix interchange** (OMX in/out) and **select-link** remain the top
  adoption asks from the review panel (docs/MPO_REVIEW_PANEL.md P0 list).
