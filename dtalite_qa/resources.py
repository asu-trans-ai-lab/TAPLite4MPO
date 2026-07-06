"""Memory-aware run resourcing: trace free memory and pick number_of_processors.

Two jobs:
  1. TRACE  -- report system memory (total / available / used) and, around a run,
     sample available memory to record the peak the run actually used.
  2. DECIDE -- recommend number_of_processors so the ESTIMATED footprint stays under a
     safe fraction of available memory, biased toward FEWER processors (an OOM is far
     worse than a slower run).

Honest model of where the kernel's memory goes (from kernel/src/TAPLite.cpp):
  - FIXED  (independent of processors): link arrays (per-mode fields), node arrays,
           the OD demand, and the per-origin shortest-path predecessor trees
           (modes x zones x nodes). This dominates on big networks -- so if it alone
           exceeds memory, MORE RAM / super-zones / binary demand is the fix, NOT
           fewer threads.
  - PER-PROCESSOR: the Dijkstra scratch CostTo (double) + PredLink (int), sized
           ~n_proc x scratch_rows x nodes. Small per thread, but it is the only term
           threads control -- so it is what this module trims when memory is tight.

Stdlib only (no psutil): Windows GlobalMemoryStatusEx via ctypes, Linux /proc/meminfo,
macOS sysctl+vm_stat, with a graceful "unknown" fallback.
"""
import os
import subprocess
import threading
import time

from . import csvio as _csvio

GB = 1024.0 ** 3

# --- footprint coefficients (bytes; conservative, tunable; the TRACE is authoritative)
_B_LINK_BASE = 120          # per link, mode-independent fields
_B_LINK_PER_MODE = 48       # per link, per mode (volume/toll/cost/allowed arrays)
_B_NODE = 64                # per node
_B_OD = 24                  # per positive OD cell (+ overhead)
_B_TREE = 4                 # per (mode, zone, node) predecessor-tree int
_SP_ROWS = 2                # CostTo scratch rows per processor (1 shared + repr)
_B_SCRATCH = 12             # per (processor, row, node): double CostTo + int PredLink
_B_COL_PER_OD = 9 * 6 * 8   # if column_output: ~9 paths/OD x ~6 links x 8B


# ============================================================================
# 1. memory status (cross-platform, stdlib)
# ============================================================================
def _win_mem():
    import ctypes
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS(); m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullTotalPhys / GB, m.ullAvailPhys / GB


def _linux_mem():
    total = avail = None
    with open("/proc/meminfo", encoding="ascii") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) * 1024 / GB
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1]) * 1024 / GB
    return total, avail


def _mac_mem():
    total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"])) / GB
    page = int(subprocess.check_output(["sysctl", "-n", "hw.pagesize"]))
    free = spec = 0
    for line in subprocess.check_output(["vm_stat"]).decode().splitlines():
        if "Pages free:" in line:
            free = int(line.split(":")[1].strip().rstrip("."))
        elif "Pages speculative:" in line:
            spec = int(line.split(":")[1].strip().rstrip("."))
    return total, (free + spec) * page / GB


def memory_status():
    """{total_gb, available_gb, used_gb, used_pct, cpu_count, source}. available_gb is
    None if the platform is unknown (callers must handle None)."""
    total = avail = None
    src = os.name
    try:
        if os.name == "nt":
            total, avail = _win_mem()
        elif os.uname().sysname == "Linux":            # noqa: attr on posix only
            total, avail = _linux_mem()
        elif os.uname().sysname == "Darwin":
            total, avail = _mac_mem()
    except Exception:
        total = avail = None
    used = (total - avail) if (total is not None and avail is not None) else None
    return {"total_gb": _r(total), "available_gb": _r(avail), "used_gb": _r(used),
            "used_pct": _r(100.0 * used / total, 1) if (used and total) else None,
            "cpu_count": os.cpu_count() or 1, "source": src}


def _r(x, n=2):
    return round(x, n) if isinstance(x, (int, float)) else x


# ============================================================================
# 2. network size + footprint estimate
# ============================================================================
def _count_rows(path):
    if not os.path.exists(path):
        return 0
    with open(path, "rb") as f:
        n = sum(1 for _ in f)
    return max(0, n - 1)                                # minus header


def network_size(scenario):
    """{nodes, links, zones, od_cells, modes} for a GMNS scenario folder."""
    nodes = _count_rows(os.path.join(scenario, "node.csv"))
    links = _count_rows(os.path.join(scenario, "link.csv"))
    # zones: distinct positive zone_id in node.csv
    zones = 0
    p = os.path.join(scenario, "node.csv")
    if os.path.exists(p):
        hdr, rows = _csvio.read(p)
        zc = next((c for c in hdr if c.lower() in ("zone_id", "zone")), None)
        if zc:
            zones = len({r[zc] for r in rows if (r.get(zc) or "0") not in ("", "0")})
    # demand files from mode_type.csv (fallback demand.csv), modes = mode rows
    modes, od = 1, 0
    mt = os.path.join(scenario, "mode_type.csv")
    dfiles = []
    if os.path.exists(mt):
        hdr, rows = _csvio.read(mt)
        modes = max(1, len(rows))
        df = next((c for c in hdr if c.lower() == "demand_file"), None)
        if df:
            dfiles = [r[df] for r in rows if r.get(df)]
    if not dfiles and os.path.exists(os.path.join(scenario, "demand.csv")):
        dfiles = ["demand.csv"]
    for d in dfiles:
        od += _count_rows(os.path.join(scenario, d))
    return {"nodes": nodes, "links": links, "zones": zones or 1,
            "od_cells": od, "modes": modes}


def estimate_footprint_gb(size, n_proc, with_columns=False):
    """Return (fixed_gb, per_proc_gb, total_gb) for a run with n_proc processors.

    fixed = links + nodes + demand + per-origin SP trees (+ columns if written);
    per_proc scales with processors. total = fixed + per_proc * n_proc.
    """
    n, l, z = size["nodes"], size["links"], size["zones"]
    od, m = size["od_cells"], size["modes"]
    fixed = (l * (_B_LINK_BASE + _B_LINK_PER_MODE * m) + n * _B_NODE + od * _B_OD
             + m * z * n * _B_TREE)
    if with_columns:
        fixed += od * _B_COL_PER_OD
    per_proc = _SP_ROWS * n * _B_SCRATCH
    return _r(fixed / GB), _r(per_proc / GB, 4), _r((fixed + per_proc * n_proc) / GB)


# ============================================================================
# 3. the recommendation
# ============================================================================
def recommend_processors(scenario=None, size=None, requested=None, available_gb=None,
                         reserve_gb=2.0, safety=0.85, with_columns=False):
    """Pick a safe number_of_processors. Returns (n_proc, info).

    Budget = available_gb * safety - reserve_gb. If the FIXED footprint alone exceeds
    the budget, no thread count fits -> recommend 1 and flag `oversized` (the honest
    signal that RAM / super-zones / binary demand is the real fix). Otherwise choose the
    largest n <= cpu_count whose total fits, capped by `requested` if given.
    """
    size = size or network_size(scenario)
    cpu = os.cpu_count() or 1
    cap = min(cpu, int(requested)) if requested else cpu
    if available_gb is None:
        available_gb = memory_status()["available_gb"]

    info = {"size": size, "cpu_count": cpu, "requested": requested,
            "available_gb": _r(available_gb), "reserve_gb": reserve_gb, "safety": safety}
    fixed, per_proc, _ = estimate_footprint_gb(size, cap, with_columns)
    info.update({"fixed_gb": fixed, "per_proc_gb": per_proc})

    if available_gb is None:                            # unknown memory -> don't guess down
        info["reason"] = "memory status unavailable; using requested/cpu without a memory cap"
        info["oversized"] = False
        return cap, info

    budget = available_gb * safety - reserve_gb
    info["budget_gb"] = _r(budget)
    if fixed > budget:
        info["oversized"] = True
        info["reason"] = (f"fixed footprint {fixed} GB exceeds budget {round(budget,2)} GB "
                          f"(avail {round(available_gb,2)}); threads cannot fix this -- "
                          f"use super-zones, binary demand, or a bigger machine")
        return 1, info

    n_max = int((budget - fixed) / per_proc) if per_proc > 0 else cap
    n = max(1, min(cap, n_max))
    info["oversized"] = False
    info["mem_limited"] = n < cap
    _, _, total = estimate_footprint_gb(size, n, with_columns)
    info["est_total_gb"] = total
    info["reason"] = (f"{n} of {cap} processors -> est {total} GB fits budget "
                      f"{round(budget,2)} GB" + (" (memory-limited)" if n < cap else ""))
    return n, info


# ============================================================================
# 4. live trace during a run
# ============================================================================
class MemoryTracer:
    """Background sampler of system available memory. Use around a kernel run to
    record the peak the run actually consumed:

        with MemoryTracer() as t:
            ... run the kernel ...
        print(t.summary())     # {baseline_avail_gb, min_avail_gb, peak_used_gb, samples}
    """

    def __init__(self, interval=0.5):
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self.baseline = None
        self.min_avail = None
        self.samples = 0

    def _run(self):
        s = memory_status()
        self.baseline = s["available_gb"]
        self.min_avail = s["available_gb"]
        while not self._stop.wait(self.interval):
            a = memory_status()["available_gb"]
            self.samples += 1
            if a is not None and (self.min_avail is None or a < self.min_avail):
                self.min_avail = a

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def summary(self):
        peak = (self.baseline - self.min_avail) if (self.baseline is not None
                and self.min_avail is not None) else None
        return {"baseline_avail_gb": _r(self.baseline), "min_avail_gb": _r(self.min_avail),
                "peak_used_gb": _r(peak), "samples": self.samples}


# ============================================================================
# 5. report (CLI)
# ============================================================================
def report(scenario, requested=None, with_columns=False):
    """Human-readable memory + processor recommendation for a scenario (ASCII)."""
    ms = memory_status()
    n, info = recommend_processors(scenario, requested=requested, with_columns=with_columns)
    sz = info["size"]
    lines = [
        "memory status:",
        f"  total {ms['total_gb']} GB | available {ms['available_gb']} GB | "
        f"used {ms['used_gb']} GB ({ms['used_pct']}%) | cores {ms['cpu_count']}",
        f"network: {sz['nodes']} nodes / {sz['links']} links / {sz['zones']} zones / "
        f"{sz['od_cells']} OD / {sz['modes']} modes",
        f"footprint: fixed {info['fixed_gb']} GB + {info['per_proc_gb']} GB/processor"
        + (f" | budget {info.get('budget_gb')} GB" if 'budget_gb' in info else ""),
        f"RECOMMEND number_of_processors = {n}",
        f"  reason: {info['reason']}",
    ]
    if info.get("oversized"):
        lines.append("  WARNING: this network may not fit in available memory at any "
                     "thread count.")
    return "\n".join(lines), n, info
