# START HERE — one page, no prior reading required

TAPLite4MPO reproduces an MPO's static highway assignment on open GMNS data: a C++
equilibrium solver (**the kernel — required**) plus Python QA tooling. The flagship proof:
the **Atlanta Regional Commission (ARC) AM assignment**, validated against ARC's own
counts at **region-wide %RMSE ≈ 22 %** (ARC's target is ~38 %).

## 1. Install (once, ~2 minutes)

```bash
pip install pandas numpy pyshp
bash build.sh        # builds the solver -> bin/DTALite.exe (Windows) / bin/DTALite (macOS, Linux)
```
macOS first: `brew install cmake libomp` (without libomp it still builds — serial, slower).
Windows: any MinGW/MSVC + CMake. Python alone assigns **nothing**; the kernel is the solver.

## 2. Run the ARC example — three sizes, your choice

```bash
cd examples/arc_atlanta
python arc_pipeline.py check        # seconds — is everything in place? (never launches a run)
python arc_pipeline.py all --quick  # ~1–2 min: 1-iteration smoke run, live output
python arc_pipeline.py all --full   # ~5–6 min: real equilibrium -> %RMSE ~22 %
```

Prefer a notebook? Open **`examples/arc_atlanta/ARC_END_TO_END.ipynb`** — *Run All* is
safe: it does the quick smoke by default; the full-scale run only starts if you set
`RUN_MODE = "full"` yourself.

Each stage also runs alone (`convert` / `prepare` / `run` / `validate`) — if something
fails, the summary names the stage; rerun just that one. Stages are strictly serial:
one demand period (AM 6–10), one kernel process, never a silent full-scale launch.

## The two data paths (the #1 confusion, settled)

| | PATH A — in-repo (default) | PATH B — full raw ARC data |
|---|---|---|
| Input | `gmns/` — bundled, complete | full shapefiles + trip cores (**~125 MB, NOT bundled**) |
| Works offline? | **Yes — this is the normal case** | only if you download ARC's published model |
| Extra step | none | `python arc_pipeline.py convert` (auto-detected) |

If `check` says the raw data is *absent*, **that is expected, not an error.**

`gmns/link.csv` already encodes ARC's calibration (per-facility-type modified BPR, peak
load factor 0.915); the pipeline **verifies and copies** it — nothing rewrites your inputs,
and solver parameters are set explicitly (and printed) in the `prepare` stage only.

## What success looks like

`gmns_run/link_performance.csv` (assigned volumes/times) and a validation table where every
volume group passes and the last line reads `region-wide %RMSE = 22% … assigned/ref = 1.00`.
Kernel console output is echoed live with an elapsed clock (the first ~30 s are quiet —
that's the OD load, not a hang) and saved to `gmns_run*/kernel_console.log`.

## If something fails

- The **first FAIL line in the summary** is the stage to fix; rerun that stage alone.
- Intake gate BLOCKED → open `examples/arc_atlanta/gmns/intake_dashboard.html`.
- No kernel → `bash build.sh` at the repo root (macOS: `brew install cmake libomp` first).

## Next steps

- Why each convention matters (PLF, modified BPR, VOT): `examples/arc_atlanta/README.md`
- Brand-new to the tool? Smallest runnable case: `kernel/data_sets/03_chicago_sketch` via `notebooks/00–02`
- The same process on private agency data (bring-your-own): `nvta_run/NVTA_END_TO_END.ipynb`
- The package API (`pytaplite.assign / accessibility / superzone / demand_to_binary`):
  `docs/API_ARCHITECTURE_REVIEW.md`
- Onboard **your** agency's model: `docs/MPO_ONBOARDING_GUIDE.md` + `docs/GOLDEN_PATH_CHECKLIST.md`
- 2× faster scenario runs + original-resolution skims: `examples/arc_atlanta/SUPERZONE.md`
