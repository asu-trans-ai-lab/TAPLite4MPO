# TAPLite4MPO — open C++ static traffic assignment for MPOs

[![build-and-test](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **New here? One entry:** open
> **[notebooks/03_arc_atlanta_end_to_end.ipynb](notebooks/03_arc_atlanta_end_to_end.ipynb)**
> — it walks you into the flagship ARC Atlanta reproduction (validated, %RMSE 22 %).
> Prefer text? The same one page is [START_HERE.md](START_HERE.md).

A single-file, reproducible **C++ (CMake) static user-equilibrium traffic-assignment
kernel** (Frank–Wolfe) for GMNS networks — with the VDF library, generalized cost,
peak-load-factor, and solver options that **MPO/DOT static highway assignments** need —
plus a Python QA/automation package, open benchmark networks, and a two-volume user
guide. Built for teaching and for reproducing agency assignments (ARC, SERPM, TRPA,
MTC, SANDAG, MWCOG, VDOT, ODOT).

![TAPLite4MPO at a glance — the Golden Path (collect → GMNS → declare → run → validate → advanced), the three gates (can I run / trust / improve), why a shapefile is not yet a model, the dataset ladder (Sketch → Regional → ARC Atlanta → OSM), super-zone compression (~2× faster), and recovering the original-resolution zone-to-zone skim (R²=0.99).](workflow_diagram.png)

> The whole pipeline at a glance. Start with **[docs/GOLDEN_PATH_CHECKLIST.md](docs/GOLDEN_PATH_CHECKLIST.md)**.
> (Figure generated from `docs/IMAGE_PROMPTS.md`.)

> ### ⚙️ Which part solves the assignment?
> The **C++ kernel** (`bin/DTALite.exe`, `kernel/src/TAPLite.cpp`) is the **solver** —
> Frank–Wolfe equilibrium, the VDF library, OpenMP, the scale. The **`dtalite_qa` Python
> package is QA/orchestration only**: it validates inputs, builds scenarios, and *invokes* the
> kernel — **it does not compute the assignment.** So you **must build the kernel**
> (`bash build.sh`); running only Python assigns nothing. This is not a pure-Python solver.
> Full explanation, environment matrix, and how to call the kernel from Python:
> **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

**Features**
- Frank–Wolfe with an exact cost-based line search; **conjugate / bi-conjugate FW**
  (`assignment_method`) for faster convergence on congested networks.
- **VDF library:** BPR, modified-BPR (linear term), conical (Spiess), QVDF (queue),
  BPR2, INRETS, Akcelik, SANDAG signal-delay, SCAG piecewise-BPR, SCAG ramp-meter
  (`vdf_type` 0–8).
- **QVDF congestion duration** — a D/C-consistent queue output (`P`, severe-congestion
  duration, queue speeds), calibrated from corridor speeds by the **CBI sister project**.
- Multiclass: per-mode demand, **VOT**, **PCE**, occupancy, per-mode toll + distance
  operating cost (generalized cost), `allowed_use` (HOV/truck/managed lanes).
- **Peak-Load-Factor / period-capacity** convention (`vdf_plf = φ/L`).
- Relative-gap stop (N consecutive iters), binary demand fast-load, OpenMP parallel.

> **Start with the flagship example → [`examples/arc_atlanta/`](examples/arc_atlanta/):**
> a complete end-to-end MPO run — reproduce the Atlanta Regional Commission's AM highway
> assignment and **validate it against ARC's own count benchmark** (region %RMSE 22 %,
> target ~38 %; re-baselined 2026-07 from 23 % after the Dijkstra-default and gap-metric
> kernel updates). It shows every MPO feature wired up, with a clean ARC-requirement →
> kernel-setting mapping. Background: [`docs/mpo_spec/`](docs/mpo_spec/) (the design spec
> + multi-agency survey).
>
> **One front door runs all of it:** `cd examples/arc_atlanta && python arc_pipeline.py all --full`
> (auto-detects raw-ARC vs in-repo data, verifies the encoded calibration, builds the kernel
> if needed, live-streams the run, ends with a PASS/FAIL summary; `check` and `all --quick`
> are the seconds/minutes-sized versions) — or open the one-click notebook
> [`examples/arc_atlanta/ARC_END_TO_END.ipynb`](examples/arc_atlanta/ARC_END_TO_END.ipynb).

---

## Self-demonstrating installation

Verify that the installed package, bundled public data, native assignment
kernel, validation gate, reporting pipeline, and regression baseline all work:

```bash
pip install taplite4mpo
taplite self-demo
```

The command copies the bundled Chicago Sketch scenario to a writable run
folder, validates its model declarations through the no-guessing intake gate,
executes the native TAPLite kernel (deterministic Frank-Wolfe, one processor),
generates an HTML dashboard, and compares VMT, VHT, convergence, and link
volumes with the reviewed golden baseline. A successful run exits with code 0;
numerical or packaging drift exits nonzero — the same check gates every
release. Variants: `taplite self-demo --quick` (Sioux Falls kernel smoke),
`--output my_demo`, `--json`. The baseline is never rewritten by a normal run
(`--record-baseline` is an explicit maintainer action).

Optional visualization: `pip install gui4gmns` (the same `*4gmns` family) and every
self-demo / pipeline run additionally produces an **interactive network dashboard**
(`network_dashboard.html`: pan/zoom map with an OSM basemap on lon/lat networks,
volume-tiered links, OD desire lines, and QC layers). Also available per run as
`pytaplite.assign(...).dashboard()`. Purely additive — nothing requires it.

Two complementary cases:

| Case | Command | Purpose |
|---|---|---|
| Chicago Sketch (default) | `taplite self-demo` | fast deterministic kernel + packaging regression — every PR and release |
| ARC Superzone | `taplite self-demo --case arc-superzone` (alias `taplite demo arc-superzone`) | MPO-scale workflow demonstration: 6,031 ARC zones superzoned to 151 (demand conserved, intrazonal audited), the full recognizable regional freeway network, corridor checks on I-75/I-85/I-20/I-285/GA-400, a superzone map in the dashboard — scheduled CI and user validation (~1–3 min) |

## 1. Build the kernel (the solver — required)

`bin/DTALite.exe` is the C++ engine that actually runs the assignment; the Python tools just
drive it. Build it first:
```bash
bash build.sh          # -> bin/DTALite.exe   (CMake + g++/MinGW, OpenMP, Release)
```
Requires CMake, a C++17 compiler (g++/clang/MSVC), and OpenMP. Output: `bin/DTALite.exe`.
(See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for why this is mandatory.)

### Install the Python packages
```bash
pip install .            # installs dtalite_qa + pytaplite; compiles the in-process kernel binding
```
This builds `pytaplite._native` from the bundled kernel source (falls back to subprocess if no
compiler). Multi-platform PyPI wheels (`pip install taplite4mpo`) are produced by cibuildwheel
on a version tag — see **[RELEASE.md](RELEASE.md)**.

Then call the kernel from Python:
```python
import pytaplite
r = pytaplite.assign("kernel/data_sets/02_Sioux_Falls")   # runs the C++ kernel
print(r.summary())                                         # links, VMT, VHT, returncode
```
Runnable demo: **[`examples/pytaplite_quickstart.py`](examples/pytaplite_quickstart.py)**
(`python examples/pytaplite_quickstart.py`).

### The two front doors for a QA-gated run

Installing the package also gives you two ways to drive a **gated, manifested** run
(both go through the no-guessing intake gate and write a reproducibility manifest —
neither can bypass the gate):

- **Python API** (developer):
  ```python
  from dtalite_qa.api import Network, Scenario, AssignmentEngine
  net  = Network.read_gmns("kernel/data_sets/03_chicago_sketch")
  res  = AssignmentEngine().run(Scenario(net, settings={"iterations": 20}),
                                exe="bin/DTALite.exe")
  print(res.moe())
  ```
- **TAPCI** (preview) — a stable, tiered "build-on-top" surface for GMNS
  assignment, so tools and AI workflows call the kernel instead of forking it.
  `TAPCI.categories()` returns the three tiers:
  ```python
  from taplite4mpo import TAPCI
  sim = TAPCI.open("project.yml", exe="bin/DTALite.exe")
  sim.set_time_period(7, 9).set_setting(route_output=1, column_output=2)
  sim.run_until_converged(max_iter=50, gap=0.001)
  sim.observe_links(["volume", "speed", "vc"])   # + observe_od / observe_system
  sim.query_paths(o_zone=12, d_zone=87)          # Path4GMNS-style external query
  sim.save_routing_policy("policy.dtac")         # the theta-share routing policy
  # ...later: reuse that policy on new demand and execute in ~1 iteration
  TAPCI.open("project.yml", exe="...").load_routing_policy("policy.dtac").run_until_converged()
  ```
  **Category 1** (core run/observe/export) and **Category 2** — the one-period
  *environment*: time period, OD/system/path performance, **OD skims** for a
  Choice-Graph/ABM caller (`observe_skims` / `query_skim`), save & reload the
  routing policy, and **next-run scenario edits** (`set_link_closure` /
  `set_link_capacity` / `set_toll` / `set_od_multiplier`, applied to a working
  copy — the source network is never touched) — are real and backed by the
  audited API + kernel. There's also an offline day-to-day / information-provision
  loop (`run_day_to_day`, driven by an external policy function) and an
  assignment-based RL environment (`dtalite_qa.tapci_env.TAPCIEnv`,
  `reset`/`step`; `reward=` accepts a MOE shortcut string, a **KPI-weighted
  objective dict** e.g. `{"vht_hours": -1.0, "co2_proxy_kg": -1e-4}`, or a
  callable). A separate, kernel-independent **KPI4MPO/NPO** layer
  (`dtalite_qa.kpi`) turns any run into decision KPIs (VMT, VHT, delay, speed,
  max V/C, OD-skim time, + CO2/person-delay proxies), KPI deltas, and a weighted
  objective/reward. **Category 3**
  (step-style `run_iteration`, live mid-solve control, external `load_paths`,
  `run_day_to_day` / information provision) raises a clear roadmap error rather
  than faking a no-op. Auto-tested in CI (`.github/workflows/tapci-ci.yml`:
  a no-kernel contract job + a kernel-loop job).
- **`taplite` CLI** (analyst) — installed as a console script; four verbs:
  ```bash
  taplite validate <scenario>                 # intake gate + schema/accessibility
  taplite run      configs/chicago_sketch_baseline.yml   # gate -> kernel -> manifest -> report
  taplite report   <run_dir>                  # fused self-contained HTML report
  taplite compare  <run_a> <run_b>            # manifest diff + side-by-side MOE
  ```
  If the `taplite` script is not on your PATH (e.g. a `--user` install), run it as
  `python -m dtalite_qa.taplite_cli <verb> ...`.

  > **pip users**: the examples above assume a repo clone — `configs/`, the
  > sample networks, and the kernel exe (`bash build.sh` -> `bin/DTALite.exe`)
  > live in the repo, not in the wheel. With only `pip install taplite4mpo`,
  > point `taplite run` at your own scenario + config and set `assignment.exe`
  > (or `--exe`) to your kernel build.

## 2. Reproduce a run (open benchmark networks — no extra data needed)

```bash
cd kernel/data_sets/02_Sioux_Falls       # or 03_chicago_sketch, 04_chicago_regional
cp ../../../bin/DTALite.exe .
./DTALite.exe                            # reads node/link/demand/settings, writes link_performance.csv
```

Or via the Python QA wrapper (validates inputs first, then runs):
```bash
pip install -e .
python -m dtalite_qa run kernel/data_sets/02_Sioux_Falls --exe bin/DTALite.exe
```

## 3. Regression / self-test

```bash
python test_networks/run_regression.py   # builds & checks BPR/conic/QVDF, multimodal, turn restrictions
```

---

## 4. Documentation
- **[HANDOFF/](HANDOFF/)** — ⭐ **new engineer? start here.** The onboarding & handoff folder:
  the ordered reading path, the runs to reproduce, the "which agency taught us this" issue
  index, a **[BPR/VDF/PLF config-rules card](HANDOFF/BPR_AND_VDF_CONFIG_RULES.md)**, and a
  **[hands-on lab](HANDOFF/REPRODUCE_THE_ISSUES.md)** that trips each classic conversion error
  on the open networks so you learn to recognize it.
- **[docs/CONVERSION_ERRORS_CATALOG.md](docs/CONVERSION_ERRORS_CATALOG.md)** — the
  **lessons-learned / error-source** reference: every way an MPO hand-off goes wrong
  (capacity, PLF, units, demand, zones, VDF, truncation, allowed-use, count basis, build),
  symptom → cause → fix → *which agency*.
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — **the C++ kernel solves; the Python
  package orchestrates.** Which part runs what, the environment matrix, and how to call the
  kernel from Python. Read it if you're unsure what's doing the assignment.
- **[docs/GOLDEN_PATH_CHECKLIST.md](docs/GOLDEN_PATH_CHECKLIST.md)** — ⭐ **READ THIS FIRST.**
  The Golden Path: from agency files to a trusted assignment, in 6 stages, framed by three
  questions — *can I run? can I trust it? can I improve it?* Simple first, advanced later.
- **[docs/DATASET_LADDER.md](docs/DATASET_LADDER.md)** — which example to start with
  (Chicago Sketch → Chicago Regional → ARC Atlanta → OSM quick start).
- **[docs/onboarding_guide.html](docs/onboarding_guide.html)** — **the visual onboarding guide**:
  open in a browser for the staged journey (GIS field-map → declare → convert → intake →
  quality → run → traceable workflow), each with its gate and a progress tracker. Generate
  it anytime with `python -m dtalite_qa guide`.
- **[docs/MPO_ONBOARDING_GUIDE.md](docs/MPO_ONBOARDING_GUIDE.md)** — **start here for a new
  agency model.** The process to turn a raw hand-off (shapefile + matrix + "alpha/beta")
  into a trustworthy run: declare → convert → **intake audit** → resolve → validate. The
  intake (`dtalite_qa intake`) never guesses a convention — it blocks on anything the MPO
  didn't declare (capacity basis/period, PLF, units, trip kind) and produces an issue
  report + conversion log + a guided HTML dashboard. The MPO fills
  [`submission.yml`](dtalite_qa/templates/mpo_submission_template.yml) (the README for the
  data; ARC's is in `examples/arc_atlanta/gmns/`).
- **[USER_GUIDE.md](USER_GUIDE.md)** — Volume 1: kernel reference (input schema, settings,
  VDFs, outputs).
- **[USER_GUIDE_VOL2_MPO.md](USER_GUIDE_VOL2_MPO.md)** — Volume 2: static highway assignment
  for MPOs (period capacity / PLF, generalized cost, convergence/solver, validation,
  per-agency recipes).
- `examples/arc_atlanta/` — **complete worked MPO example** (ARC AM assignment, calibrate
  → run → validate vs the agency benchmark) with the ARC→kernel mapping.
- `docs/mpo_spec/` — design spec + **multi-agency survey/conformance** (ARC, SERPM, TRPA,
  MTC, SANDAG, MWCOG, VDOT, ODOT): requirement → kernel feature → how to verify.
- `docs/qvdf_congestion_duration.md` — QVDF as the D/C-consistent congestion-**duration**
  output, and the **CBI sister-project pipeline** (corridor speeds → QVDF params → kernel).
- `docs/` — methodology notes (peak load factor, super-zone aggregation, 4-step
  integration, OD-compression operators).
- `docs/IMAGE_PROMPTS.md` — copy-paste prompts for GPT image tools to generate the
  easy-to-follow figures (Golden Path, the 3 gates, super-zones, the skim advantage).
- `.claude/skills/taplite4mpo-pipeline/` — a Claude Code **skill** encoding the whole
  pipeline (gates, stages, conventions, the ARC loop) for agent-assisted work in this repo.
- `dtalite_qa/` — Python package: `guide`, `intake`, `workflow`, `validate`, `fill`, `inventory`,
  `accessibility`, `report`, `demand-bin`, `plf`, `adapt`, `run` (see `python -m dtalite_qa -h`).
- **[`pytaplite/`](pytaplite/)** — Python interface that **drives the C++ kernel**:
  `pytaplite.assign(scenario)` → runs `DTALite.exe`, returns `link_performance` (subprocess, or
  the in-process `_native` binding from [`kernel/python/`](kernel/python/) if built).

## 5. Folder map
```
TAPLite4MPO/
├── kernel/            C++ kernel (src/TAPLite.cpp, CMakeLists.txt) + open data_sets/
├── examples/
│   └── arc_atlanta/   complete end-to-end MPO example (ARC AM, validated)
├── dtalite_qa/        Python QA / control package
├── test_networks/     open test/benchmark networks + regression harness
├── schemas/           GMNS field schema (JSON)
├── docs/              methodology docs
│   └── mpo_spec/      design spec + multi-agency survey & conformance mapping
├── nvta_run/          NVTA run-configs + helper scripts (bring-your-own-data, §6)
├── USER_GUIDE.md      Volume 1 (kernel)
├── USER_GUIDE_VOL2_MPO.md   Volume 2 (MPOs)
└── build.sh
```

## 6. NVTA reproduction (bring-your-own-data)

The **NVTA dataset is agency-restricted and is NOT included** in this repository.
`nvta_run/` ships the run-configs and helper scripts (network prep, settings, conic/QVDF
staging). To run it, point the scripts at your own copy of the data:

```bash
# option A: environment variable
export DTALITE_NVTA_INTERNAL=/path/to/nvta/_internal
# option B: nvta_run/local_config.json -> {"internal": "...", "subarea": "..."}
# option C: place the data in  data/nvta_internal/
python nvta_run/run_nvta.py
```
If unconfigured, the runner prints a clear message. **All of §2–§3 reproduces fully
without it** using the open benchmark networks.

> Course note: instructors distribute the NVTA data to students through a separate
> channel (not this public repo); students set one of the options above.

---

## Continuous integration
`.github/workflows/ci.yml` builds the kernel (CMake + MSVC on `windows-latest`) and runs
the full regression suite on every push / pull request.

## License & citation
**MIT** — see `LICENSE`. If you use this kernel in research or coursework, please cite the
DTALite / TAPLite project. (Some `docs/` notes reference internal companion files that are
not part of this public release.)
