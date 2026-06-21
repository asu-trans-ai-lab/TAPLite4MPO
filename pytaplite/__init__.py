"""pytaplite — a Python interface to the TAPLite C++ assignment kernel.

The C++ kernel (DTALite.exe) is the solver; this package drives it:

    import pytaplite
    r = pytaplite.assign("examples/arc_atlanta/gmns_calibrated")   # runs the C++ kernel
    print(r.summary())          # {'links': ..., 'total_VMT': ..., ...}
    df = r.to_pandas()          # link_performance as a DataFrame (needs pandas)

It uses the native in-process binding (pytaplite._native) if built, else a subprocess.
See docs/ARCHITECTURE.md — Python orchestrates, the C++ kernel assigns.
"""
from .kernel import assign, find_kernel, Result, __version__

__all__ = ["assign", "find_kernel", "Result", "__version__"]
