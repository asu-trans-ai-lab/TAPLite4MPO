"""pytaplite — a Python interface to the TAPLite C++ assignment kernel.

The C++ kernel (TAPLite.exe; the legacy DTALite name is still accepted) is the
solver; this package drives it:

    import pytaplite
    r = pytaplite.assign("examples/arc_atlanta/gmns_calibrated")   # runs the C++ kernel
    print(r.summary())          # {'links': ..., 'total_VMT': ..., ...}
    df = r.to_pandas()          # link_performance as a DataFrame (needs pandas)

    a = pytaplite.accessibility(scenario)      # kernel-internal accessibility (no assignment)
    pytaplite.superzone(scenario, "sz/", 1500) # compress zones for large regional runs
    pytaplite.demand_to_binary(scenario)       # packed .bin demand for large OD tables
    r = pytaplite.assign(scenario, settings_overrides={"demand_format": 1,
                                                       "column_output": 1})

Sparse agency node/zone ids are renumbered INSIDE the kernel and every output
is reported in the original external ids — callers never manage id spaces.
It uses the native in-process binding (pytaplite._native) if built, else a subprocess.
See docs/ARCHITECTURE.md — Python orchestrates, the C++ kernel assigns.
"""
from .kernel import (
    AccessibilityResult,
    Result,
    __version__,
    accessibility,
    assign,
    demand_to_binary,
    find_kernel,
    superzone,
)

__all__ = ["assign", "accessibility", "superzone", "demand_to_binary",
           "find_kernel", "Result", "AccessibilityResult", "__version__"]
