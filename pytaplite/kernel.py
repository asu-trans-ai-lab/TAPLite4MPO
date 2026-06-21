"""Drive the TAPLite C++ kernel from Python and load its results.

The kernel (DTALite.exe) is the solver; this module locates the binary, runs an assignment
in a scenario folder, and reads link_performance.csv back as Python objects. If the optional
native in-process binding (pytaplite._native, built from kernel/python/) is present it is
used automatically; otherwise the kernel is launched as a subprocess. Either way the C++
kernel does the assignment.
"""
import csv
import os
import shutil
import subprocess
import tempfile

__version__ = "0.1.0"

# optional in-process binding (built separately from kernel/python/)
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


def assign(scenario, exe=None, in_place=True, work_dir=None, timeout=3600, capture=True):
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
    kernel = find_kernel(exe)

    if in_place:
        run_dir = scenario
    else:
        run_dir = work_dir or tempfile.mkdtemp(prefix="pytaplite_")
        if os.path.abspath(run_dir) != scenario:
            for fn in os.listdir(scenario):
                src = os.path.join(scenario, fn)
                if os.path.isfile(src):
                    shutil.copy(src, os.path.join(run_dir, fn))

    # native in-process call if available, else subprocess (both run the C++ solver)
    if _native_mod is not None:
        cwd = os.getcwd()
        try:
            os.chdir(run_dir)
            rc = int(_native_mod.run_in_dir(run_dir))
            log = "(native binding: pytaplite._native.run_in_dir)"
        finally:
            os.chdir(cwd)
    else:
        exe_local = os.path.join(run_dir, os.path.basename(kernel))
        if os.path.abspath(exe_local) != os.path.abspath(kernel):
            shutil.copy(kernel, exe_local)
        p = subprocess.run([exe_local], cwd=run_dir, timeout=timeout,
                           capture_output=capture, text=True)
        rc = p.returncode
        log = (p.stdout or "") + (p.stderr or "") if capture else ""

    return Result(run_dir, rc, log, _read_links(run_dir))
