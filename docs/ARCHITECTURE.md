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
| Super-zone encoders / skim recovery | Python + `numpy`, `scipy` (and `scikit-learn` for `demand_kmeans`) |
| Read agency shapefiles in the example converters | `pyshp` / `pyogrio` / `pandas` (provenance scripts only) |

CI (`.github/workflows/ci.yml`) builds the kernel with MSVC on `windows-latest` and runs the
regression — proof the C++ layer is the thing under test.

## "Can I call the C++ kernel *from* Python?"

Yes — that is exactly what the Python layer does today, by **subprocess**, not by a native
binding:
```python
from dtalite_qa import control
result = control.run("my_scenario", exe="bin/DTALite.exe")   # prepares, then runs DTALite.exe
print(result["returncode"], result["normalized"])            # outputs in the normalized folder
```
or the lowest level — just launch the binary yourself:
```python
import subprocess
subprocess.run(["bin/DTALite.exe"], cwd="my_scenario")       # the solver, in that folder
```

The kernel is a **self-contained binary**, deliberately: it stays fast and dependency-free,
and any language can drive it by writing the CSVs and launching it. A native **`pybind11`
in-process binding** (call the solver as a Python function, no file round-trip) is a sensible
future addition for tight demand↔supply feedback loops — it is **not** in the repo yet. If you
need it, open an issue; the kernel's entry points are structured to allow it.

## Where each part lives
- `kernel/src/TAPLite.cpp`, `kernel/CMakeLists.txt`, `build.sh` — **the solver**.
- `dtalite_qa/` — the Python controller (`control.py` is where it invokes the kernel).
- `examples/`, `test_networks/`, `kernel/data_sets/` — inputs the kernel reads.
