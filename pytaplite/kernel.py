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

try:  # single-source: the installed distribution version (pyproject.toml)
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("taplite4mpo")
except Exception:  # repo checkout without install
    __version__ = "0.3.0"

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
    """Locate the kernel binary. The canonical name is TAPLite.exe (this is the
    TAPLite static-assignment kernel; DTALite is the sibling DTA product) — the
    legacy DTALite name is still accepted everywhere for compatibility.
    Order: explicit arg, $TAPLITE_EXE, $DTALITE_EXE, ./bin/TAPLite[.exe] then
    ./bin/DTALite[.exe] (and a few common spots), then PATH."""
    cands = []
    if exe:
        cands.append(exe)
    for env in ("TAPLITE_EXE", "DTALITE_EXE"):
        if os.environ.get(env):
            cands.append(os.environ[env])
    names = ["TAPLite.exe", "TAPLite", "DTALite.exe", "DTALite"]
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (os.getcwd(), os.path.join(here, ".."), os.path.join(here, "..", "..")):
        for n in names:
            cands.append(os.path.join(base, "bin", n))
            cands.append(os.path.join(base, n))
    for c in cands:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    for n in names:
        onpath = shutil.which(n)
        if onpath:
            return onpath
    raise FileNotFoundError(
        "TAPLite C++ kernel not found. pytaplite drives the kernel — it does not solve.\n"
        "Build it (`bash build.sh` -> bin/TAPLite.exe) and either pass exe=..., set\n"
        "$TAPLITE_EXE, or run from a folder with bin/TAPLite.exe. See docs/ARCHITECTURE.md.")


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

    def dashboard(self, out=None):
        """Generate an interactive network dashboard for this run via the
        optional gui4gmns package (same *4gmns family): pan/zoom map, volume
        tiers, desire lines, QC layers, OSM basemap for lon/lat networks.
        `pip install gui4gmns` to enable. Returns the HTML path."""
        try:
            import gui4gmns
        except ImportError:
            raise ImportError("pip install gui4gmns to generate interactive "
                              "network dashboards from run folders")
        out = out or os.path.join(self.run_dir, "network_dashboard.html")
        gui4gmns.generate(self.run_dir, out=out)
        return out


def _read_links(run_dir):
    p = os.path.join(run_dir, "link_performance.csv")
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _apply_settings_overrides(run_dir, overrides):
    """Rewrite settings.csv in run_dir with the given column overrides (adding
    columns that are absent). Single-row settings files only — the kernel's format."""
    path = os.path.join(run_dir, "settings.csv")
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    row = rows[0] if rows else {}
    for k, v in overrides.items():
        row[k] = v
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        w.writeheader()
        w.writerow(row)


def assign(scenario, exe=None, in_place=True, work_dir=None, timeout=3600, capture=True,
           prefer_inproc=True, settings_overrides=None):
    """Run a static assignment on a GMNS scenario folder with the C++ kernel.

    scenario : folder with node.csv, link.csv, demand*, settings.csv, mode_type.csv.
    exe      : kernel path (else auto-located; see find_kernel).
    in_place : run in `scenario` (kernel writes outputs there, its normal behaviour).
               If False, the scenario is copied to `work_dir` (or a temp dir) and run there,
               leaving the source untouched.
    settings_overrides : dict of settings.csv columns to set for this run, e.g.
               {"demand_format": 1}   — read demand from binary .bin files
                                        (see demand_to_binary) for large problems;
               {"column_output": 1}  — write the compact DTAC path store instead of
                                        the wide route CSV;
               {"route_output": 0}   — skip the 5D route store (fast/lean runs).
               With in_place=True the scenario's settings.csv IS modified (that is
               the record of what ran); use in_place=False to leave the source
               untouched.
    Sparse agency node/zone ids are handled INSIDE the kernel (renumbered
    internally, all outputs reported in the original external ids) — no
    pre-processing needed.
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

    if settings_overrides:
        _apply_settings_overrides(run_dir, settings_overrides)

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


# --------------------------------------------------------------------------- extras
class AccessibilityResult:
    """Outcome of an accessibility-only kernel run (no equilibrium iterations).

    All node/zone ids are the ORIGINAL external ids — the kernel renumbers
    internally and maps everything back on output."""

    def __init__(self, run_dir, returncode, log):
        self.run_dir = run_dir
        self.returncode = returncode
        self.log = log

    def _read(self, name):
        p = os.path.join(self.run_dir, name)
        if not os.path.exists(p):
            return []
        with open(p, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    @property
    def od(self):
        """od_performance.csv rows: zone-to-zone distance / free-flow time skim."""
        return self._read("od_performance.csv")

    @property
    def origins(self):
        """origin_accessibility.csv rows: per-origin-zone reach statistics."""
        return self._read("origin_accessibility.csv")

    @property
    def destinations(self):
        """destination_accessibility.csv rows: per-destination-zone statistics.
        Volume-weighted fields are populated by assignment runs; in
        accessibility-only mode prefer `zones`."""
        return self._read("destination_accessibility.csv")

    @property
    def zones(self):
        """zone_accessibility.csv rows: per-zone reach counts and average
        distance / free-flow / congested times — the accessibility-only
        mode's primary per-zone table."""
        return self._read("zone_accessibility.csv")

    def to_pandas(self, table="zones"):
        import pandas as pd
        return pd.DataFrame(getattr(self, table))

    def __repr__(self):
        return (f"<pytaplite.AccessibilityResult zones={len(self.zones)} "
                f"od={len(self.od)} rc={self.returncode} dir={self.run_dir!r}>")


def accessibility(scenario, exe=None, in_place=True, work_dir=None, timeout=3600,
                  capture=True):
    """Zone-to-zone accessibility via an INTERNAL kernel call (no assignment).

    Runs the C++ kernel in accessibility-only mode (number_of_iterations = 0):
    it builds shortest-path trees for every origin zone and writes
    od_performance.csv, origin_accessibility.csv and destination_accessibility.csv
    — auto/highway accessibility with assignment-grade path logic, at kernel
    speed, with all ids reported in the ORIGINAL external numbering.

    For multimodal / transit / cross-modal accessibility measures (cumulative,
    gravity, dual access on walk+bike+transit networks), use the sibling
    `access4gmns` package — it can also re-impedance its network from this
    kernel's link_performance.csv for congested accessibility.
    """
    result = assign(scenario, exe=exe, in_place=in_place, work_dir=work_dir,
                    timeout=timeout, capture=capture,
                    settings_overrides={"number_of_iterations": 0})
    return AccessibilityResult(result.run_dir, result.returncode, result.log)


def superzone(scenario, out_dir, k_target=None, zone2super=None):
    """Compress a scenario's zones into super-zones (fewer origins, full link
    network preserved) — the demand-side acceleration for large regional runs.

    Wraps dtalite_qa.superzone_hier.build (ships in the same taplite4mpo
    distribution). The compressed scenario in `out_dir` uses well-formed dense
    super-zone ids, so it feeds straight into pytaplite.assign(); the kernel's
    internal renumbering keeps every id concern at the kernel level. Recover
    the original-resolution zone-to-zone skim afterwards with dtalite_qa.skim.
    """
    from dtalite_qa import superzone_hier
    return superzone_hier.build(scenario, out_dir, k_target=k_target,
                                zone2super=zone2super)


def demand_to_binary(scenario):
    """Convert a scenario's demand CSVs to the kernel's packed .bin format
    (fast bulk reads for large OD tables). Then run with
    assign(scenario, settings_overrides={"demand_format": 1}).

    Wraps dtalite_qa.demandbin.convert_scenario."""
    from dtalite_qa import demandbin
    return demandbin.convert_scenario(scenario)
