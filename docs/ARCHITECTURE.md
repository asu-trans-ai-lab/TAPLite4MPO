# Architecture — what actually solves the assignment

**Read this if you're unsure which part does the work.** TAPLite4MPO is **two layers**, and it
matters which one you're using:

```
   ┌──────────────────────────────────────────────────────────────────┐
   │  dtalite_qa  (Python package)  —  QA / orchestration ONLY         │
   │  validates inputs · fills defaults · intake audit · builds        │
   │  scenarios · runs the R1-R6 workflow · super-zones · skims        │
   │  >>> it does NOT solve the assignment <<<                         │
   └───────────────────────────────┬──────────────────────────────────┘
                                    │  prepares CSVs, then invokes ↓ (subprocess)
   ┌───────────────────────────────▼──────────────────────────────────┐
   │  THE KERNEL  (C++17, bin/DTALite.exe)  —  the SOLVER / engine     │
   │  reads node/link/demand/settings CSV → Frank-Wolfe / conjugate /  │
   │  bi-conjugate user equilibrium (OpenMP, scalable) → writes        │
   │  link_performance.csv (volumes, V/C, speed, VMT/VHT, QVDF)        │
   └──────────────────────────────────────────────────────────────────┘
```

**The C++ kernel is the engine.** All assignment math, the VDF library, the line search, the
parallelism, and the scale live in `kernel/src/TAPLite.cpp`. The Python package is a
*controller*: it never computes an equilibrium — it prepares the inputs the kernel reads and
then **shells out to `DTALite.exe`** (`dtalite_qa/control.py` → `subprocess.run`). If you run
only Python and never build the kernel, **nothing is assigned.** This is also why
`python -m dtalite_qa run` **requires `--exe`**, and why it now fails loudly with a pointer
here if the kernel binary is missing.

> Not the same as a pure-Python solver. Some traffic-assignment tools are entirely Python; this
> one is not. Python is the convenience/QA layer; the **C++ kernel does the assignment** and is
> what makes it scalable to a 145k-link / 6k-zone network in minutes.

---

## Two ways to run — and which environment each needs

| Path | What runs | You need |
|---|---|---|
| **A. Kernel directly** | the C++ solver only | a built `DTALite.exe`; nothing else |
| **B. Python-orchestrated** (recommended) | Python validates/builds, then calls the kernel | Python 3.8+ **and** a built `DTALite.exe` |

**A — run the kernel directly** (no Python at all):
```bash
cd kernel/data_sets/03_chicago_sketch
cp ../../../bin/DTALite.exe .
./DTALite.exe          # reads the CSVs here, writes link_performance.csv
```

**B — Python orchestrates the kernel** (QA gate first, then the same kernel):
```bash
pip install -e .
python -m dtalite_qa run <scenario> --exe bin/DTALite.exe
#   = validate inputs → fill defaults → invoke DTALite.exe → check outputs
```
Either way **the C++ kernel does the assignment.** Path B just wraps it with validation and
reporting.

## Environment requirements

| To do this | You need |
|---|---|
| **Build the kernel** (once) | a C++17 compiler (g++/clang/MSVC) + CMake + OpenMP — `bash build.sh` → `bin/DTALite.exe` |
| Run the kernel | the built `DTALite.exe` (Windows/Linux/macOS); no runtime deps |
| Use `dtalite_qa` (intake/check/run/workflow/guide) | Python 3.8+ (standard library only) |
| Drive the kernel from Python (`pytaplite`) | Python 3.8+ (+ `pandas` for `to_pandas`) + a built `DTALite.exe` |
| Build the **native in-process binding** (optional) | `pybind11` + the C++ toolchain — `bash kernel/python/build_native.sh` |
| Super-zone encoders / skim recovery | Python + `numpy`, `scipy` (and `scikit-learn` for `demand_kmeans`) |
| Read agency shapefiles in the example converters | `pyshp` / `pyogrio` / `pandas` (provenance scripts only) |

CI (`.github/workflows/ci.yml`) builds the kernel with MSVC on `windows-latest` and runs the
regression — proof the C++ layer is the thing under test.

## Calling the C++ kernel from Python — two ways, both shipped

**1. `pytaplite` — the clean Python interface (recommended).**
```python
import pytaplite
r = pytaplite.assign("examples/arc_atlanta/gmns_calibrated")   # runs the C++ kernel
print(r.summary())        # {'links': ..., 'total_VMT': ..., 'returncode': 0}
df = r.to_pandas()        # link_performance as a DataFrame
```
It locates the binary, runs the assignment, and loads `link_performance.csv` back. It picks
the fastest of three execution paths automatically (all call the same C++ kernel):

**2. ctypes shared library — the Path4GMNS / DTALite pattern (in-process, no pybind11).**
The kernel exports the C-ABI symbols `DTA_AssignmentAPI()` / `DTA_SimulationAPI()`
(`extern "C"` in `kernel/src/TAPLite.h`), so it builds as a shared library that Python loads
with stdlib **`ctypes`** — exactly how [Path4GMNS](https://github.com/jdlph/Path4GMNS) ships
the `DTALite` engine:
```bash
bash kernel/python/build_shared.sh    # -> pytaplite/DTALite.dll | libDTALite.so | libDTALite.dylib
```
`pytaplite.assign(...)` then loads it and calls `DTA_AssignmentAPI()` **in-process**. (CMake's
`add_library(DTALite SHARED ...)` target builds the same library.)

**3. pybind11 binding — `pytaplite._native` (alternative in-process; releases the GIL).**
`pip install pybind11 && bash kernel/python/build_native.sh`.

**Caveat (both in-process paths):** the kernel keeps global state, so run **one assignment
per process**; for many runs use a fresh `work_dir` per call, `multiprocessing`, or
`prefer_inproc=False` to use the subprocess path. The shared lib / native module are optional
and git-ignored; **subprocess works with no library build.**

Lowest level — just launch the binary yourself (any language can):
```python
import subprocess
subprocess.run(["bin/DTALite.exe"], cwd="my_scenario")        # the solver, in that folder
```

The kernel is a **self-contained binary**, deliberately: it stays fast and dependency-free,

## Where each part lives
- `kernel/src/TAPLite.cpp`, `kernel/CMakeLists.txt`, `build.sh` — **the solver**.
- `dtalite_qa/` — the Python controller (`control.py` is where it invokes the kernel).
- `examples/`, `test_networks/`, `kernel/data_sets/` — inputs the kernel reads.
