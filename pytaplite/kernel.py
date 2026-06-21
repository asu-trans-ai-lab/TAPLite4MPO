"""Drive the TAPLite C++ kernel from Python and load its results.

The kernel (DTALite.exe) is the solver; this module locates the binary, runs an assignment
in a scenario folder, and reads link_performance.csv back as Python objects. If the optional
native in-process binding (pytaplite._native, built from kernel/python/) is present it is
used automatically; otherwise the kernel is launched as a subprocess. Either way the C++
kernel does the assignment.
"""
import csv
import ctypes
import os
import platform
import shutil
import subprocess
import tempfile

__version__ = "0.1.0"

# --- in-process kernel via a C-ABI shared library (the Path4GMNS / DTALite pattern) ---------
# The kernel is built as DTALite.dll / libDTALite.so / libDTALite.dylib exporting the C symbol
# DTA_AssignmentAPI(); we load it with ctypes (stdlib) and call it in-process. Build it with
# kernel/python/build_shared.sh (or CMake `add_library(DTALite SHARED ...)`).
_LIBNAME = {"Windows": "DTALite.dll", "Linux": "libDTALite.so", "Darwin": "libDTALite.dylib"}


def _find_shared_lib(path=None):
    name = _LIBNAME.get(platform.system(), "DTALite.dll")
    cands = [path, os.environ.get("DTALITE_DLL")]
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.join(here, ".."), os.path.join(here, "..", ".."), os.getcwd()):
        cands += [os.path.join(base, name), os.path.join(base, "bin", name)]
    for c in cands:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return None


_lib = None          # cached ctypes handle (None = not tried, False = unavailable)


def _get_lib():
    global _lib
    if _lib is None:
        p = _find_shared_lib()
        try:
            _lib = ctypes.CDLL(p) if p else False
            if _lib:
                _lib.DTA_AssignmentAPI.restype = None
        except OSError:
            _lib = False
    return _lib or None


# optional pybind11 binding (alternative in-process path; kernel/python/build_native.sh)
try:
    from . import _native as _native_mod          # exposes run_in_dir(path) -> int
except Exception:
    _native_mod = None


def find_kernel(exe=None):
    """Locate the kernel binary. Order: explicit arg, $DTALITE_EXE, ./bin/DTALite.exe
    (and a few common spots), then DTALite[.exe] on PATH. Raises with guidance if absent."""
    cands = []
    if exe:
        cands.append(exe)
    if os.environ.get("DTALITE_EXE"):
        cands.append(os.environ["DTALITE_EXE"])
    names = ["DTALite.exe", "DTALite"]
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (os.getcwd(), os.path.join(here, ".."), os.path.join(here, "..", "..")):
        for n in names:
            cands.append(os.path.join(base, "bin", n))
            cands.append(os.path.join(base, n))
    for c in cands:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    onpath = shutil.which("DTALite") or shutil.which("DTALite.exe")
    if onpath:
        return onpath
    raise FileNotFoundError(
        "TAPLite C++ kernel not found. pytaplite drives the kernel — it does not solve.\n"
        "Build it (`bash build.sh` -> bin/DTALite.exe) and either pass exe=..., set\n"
        "$DTALITE_EXE, or run from a folder with bin/DTALite.exe. See docs/ARCHITECTURE.md.")


class Result:
    """Outcome of one assignment: the link_performance rows + run metadata."""
    def __init__(self, run_dir, returncode, log, links):
        self.run_dir = run_dir
        self.returncode = returncode
        self.log = log
        self.links = links            # list[dict]

    def __repr__(self):
        return f"<pytaplite.Result links={len(self.links)} rc={self.returncode} dir={self.run_dir!r}>"

    def _num(self, row, *keys):
        for k in keys:
            v = row.get(k)
            if v not in (None, ""):
                try:
                    return float(v)
                except ValueError:
                    pass
        return 0.0

    def summary(self):
        loaded = [r for r in self.links if self._num(r, "volume", "vehicle_volume") > 0]
        return {
            "links": len(self.links),
            "loaded_links": len(loaded),
            "total_VMT": round(sum(self._num(r, "VMT") for r in self.links), 1),
            "total_VHT": round(sum(self._num(r, "VHT") for r in self.links), 1),
            "returncode": self.returncode,
        }

    def to_pandas(self):
        import pandas as pd
        return pd.DataFrame(self.links)


def _read_links(run_dir):
    p = os.path.join(run_dir, "link_performance.csv")
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def assign(scenario, exe=None, in_place=True, work_dir=None, timeout=3600, capture=True,
           prefer_inproc=True):
    """Run a static assignment on a GMNS scenario folder with the C++ kernel.

    scenario : folder with node.csv, link.csv, demand*, settings.csv, mode_type.csv.
    exe      : kernel path (else auto-located; see find_kernel).
    in_place : run in `scenario` (kernel writes outputs there, its normal behaviour).
               If False, the scenario is copied to `work_dir` (or a temp dir) and run there,
               leaving the source untouched.
    Returns a Result; raises FileNotFoundError if the kernel or scenario is missing.
    """
    scenario = os.path.abspath(scenario)
    if not os.path.isdir(scenario):
        raise FileNotFoundError(f"scenario folder not found: {scenario}")

    if in_place:
        run_dir = scenario
    else:
        run_dir = work_dir or tempfile.mkdtemp(prefix="pytaplite_")
        if os.path.abspath(run_dir) != scenario:
            for fn in os.listdir(scenario):
                src = os.path.join(scenario, fn)
                if os.path.isfile(src):
                    shutil.copy(src, os.path.join(run_dir, fn))

    # Run the C++ solver. Prefer in-process: ctypes shared library (DTALite pattern) first,
    # then the pybind11 binding; otherwise launch the exe as a subprocess. All three call the
    # same kernel — the in-process paths skip the process-launch overhead.
    lib = _get_lib() if prefer_inproc else None
    if lib is not None or (prefer_inproc and _native_mod is not None):
        cwd = os.getcwd()
        try:
            os.chdir(run_dir)
            if lib is not None:
                lib.DTA_AssignmentAPI()          # reads CSVs in cwd, writes link_performance.csv
                rc, via = 0, "ctypes shared library (DTALite)"
            else:
                rc = int(_native_mod.run_in_dir(run_dir))
                via = "pybind11 binding (_native)"
        finally:
            os.chdir(cwd)
        log = f"(in-process: {via})"
    else:
        kernel = find_kernel(exe)            # subprocess path: the exe is needed here
        exe_local = os.path.join(run_dir, os.path.basename(kernel))
        if os.path.abspath(exe_local) != os.path.abspath(kernel):
            shutil.copy(kernel, exe_local)
        p = subprocess.run([exe_local], cwd=run_dir, timeout=timeout,
                           capture_output=capture, text=True)
        rc = p.returncode
        log = ((p.stdout or "") + (p.stderr or "")) if capture else "(subprocess)"

    return Result(run_dir, rc, log, _read_links(run_dir))
