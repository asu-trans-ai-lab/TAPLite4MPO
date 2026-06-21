# pytaplite — Python interface to the TAPLite C++ kernel

`pytaplite` drives the **C++ assignment kernel** from Python: locate the binary, run an
assignment on a GMNS scenario, and load `link_performance.csv` back as Python objects. **The
C++ kernel is the solver; this package only orchestrates it** (see
[`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)).

```python
import pytaplite

r = pytaplite.assign("examples/arc_atlanta/gmns_calibrated")  # runs the C++ kernel
print(r.summary())        # {'links': 145971, 'loaded_links': ..., 'total_VMT': ..., 'returncode': 0}
df = r.to_pandas()        # link_performance as a DataFrame (pip install taplite4mpo[data])
```

## Install
```bash
pip install -e .          # from the repo root (installs dtalite_qa + pytaplite)
bash build.sh             # build the kernel first -> bin/DTALite.exe  (REQUIRED)
```

## API
- `assign(scenario, exe=None, in_place=True, work_dir=None, timeout=3600) -> Result`
  - `exe`: kernel path; if omitted, auto-located (`$DTALITE_EXE`, `./bin/DTALite.exe`, PATH).
  - `in_place=True` runs in the scenario folder (kernel writes outputs there — its normal
    behaviour). `in_place=False` copies the scenario to a temp/`work_dir` and runs there,
    leaving the source untouched.
- `find_kernel(exe=None) -> path` — locate the binary (raises with guidance if missing).
- `Result` — `.links` (list of dicts), `.summary()`, `.to_pandas()`, `.log`, `.returncode`, `.run_dir`.

## How it runs the kernel (three paths, same solver)
`pytaplite` picks the fastest available, in order:

1. **ctypes shared library** — `DTALite.dll` / `libDTALite.so` / `libDTALite.dylib`, loaded
   with `ctypes` (Python stdlib) and called via the C-ABI `DTA_AssignmentAPI()` **in-process**.
   This is the **Path4GMNS / DTALite package pattern** ([jdlph/Path4GMNS](https://github.com/jdlph/Path4GMNS)).
   Build it once: `bash kernel/python/build_shared.sh`.
2. **pybind11 binding** `pytaplite._native` — an alternative in-process path
   (`bash kernel/python/build_native.sh`).
3. **subprocess** — launch `DTALite.exe` (always works; needs no library build).

Either way **the C++ kernel does the assignment.** The two in-process paths share the
kernel's global state, so they run **one assignment per process** (pytaplite uses a fresh
`work_dir`; for many runs in a loop, prefer subprocess or `multiprocessing`). Pass
`prefer_inproc=False` to force the subprocess path.

> `pytaplite` is the runnable bridge; `dtalite_qa` is the QA/validation/workflow layer. Use
> `dtalite_qa intake/check` to get a scenario READY, then `pytaplite.assign` to run it.
