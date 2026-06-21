# TAPLite4MPO — open C++ static traffic assignment for MPOs

[![build-and-test](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A single-file, reproducible **C++ (CMake) static user-equilibrium traffic-assignment
kernel** (Frank–Wolfe) for GMNS networks — with the VDF library, generalized cost,
peak-load-factor, and solver options that **MPO/DOT static highway assignments** need —
plus a Python QA/automation package, open benchmark networks, and a two-volume user
guide. Built for teaching and for reproducing agency assignments (ARC, SERPM, TRPA,
MTC, SANDAG, MWCOG, VDOT, ODOT).

**Features**
- Frank–Wolfe with an exact cost-based line search; **conjugate / bi-conjugate FW**
  (`assignment_method`) for faster convergence on congested networks.
- **VDF library:** BPR, modified-BPR (linear term), conical (Spiess), QVDF (queue),
  BPR2, INRETS, Akcelik, SANDAG signal-delay (`vdf_type` 0–6).
- **QVDF congestion duration** — a D/C-consistent queue output (`P`, severe-congestion
  duration, queue speeds), calibrated from corridor speeds by the **CBI sister project**.
- Multiclass: per-mode demand, **VOT**, **PCE**, occupancy, per-mode toll + distance
  operating cost (generalized cost), `allowed_use` (HOV/truck/managed lanes).
- **Peak-Load-Factor / period-capacity** convention (`vdf_plf = φ/L`).
- Relative-gap stop (N consecutive iters), binary demand fast-load, OpenMP parallel.

> **Start with the flagship example → [`examples/arc_atlanta/`](examples/arc_atlanta/):**
> a complete end-to-end MPO run — reproduce the Atlanta Regional Commission's AM highway
> assignment and **validate it against ARC's own count benchmark** (region %RMSE 23 %,
> target ~38 %). It shows every MPO feature wired up, with a clean ARC-requirement →
> kernel-setting mapping. Background: [`docs/mpo_spec/`](docs/mpo_spec/) (the design spec
> + multi-agency survey).

---

## 1. Build

```bash
bash build.sh          # -> bin/DTALite.exe   (CMake + g++/MinGW, OpenMP, Release)
```
Requires CMake, a C++17 compiler (g++/clang/MSVC), and OpenMP. Output: `bin/DTALite.exe`.

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
- `dtalite_qa/` — Python package: `validate`, `fill`, `inventory`, `accessibility`,
  `report`, `demand-bin`, `plf`, `adapt`, `run` (see `python -m dtalite_qa -h`).

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
