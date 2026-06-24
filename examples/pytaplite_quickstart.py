"""Quickstart — call the TAPLite C++ kernel from Python via `pytaplite`.

Runs a static assignment on an open benchmark network and inspects the result. The C++
kernel does the solving; pytaplite locates the binary, runs it (in-process via the ctypes
shared library / pybind11 binding if built, else subprocess), and loads link_performance.

Prereqs:
    bash build.sh            # -> bin/DTALite.exe   (the solver)
    pip install .            # installs pytaplite (+ optional native binding)

Run:
    python examples/pytaplite_quickstart.py
    python examples/pytaplite_quickstart.py kernel/data_sets/03_chicago_sketch
"""
import os
import sys

# allow running from a source checkout without installing
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytaplite

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "kernel/data_sets/02_Sioux_Falls")
    exe = os.path.join(REPO, "bin", "DTALite.exe")          # built by build.sh
    exe = exe if os.path.exists(exe) else None              # else pytaplite auto-locates / errors

    print(f"scenario : {scenario}")
    print(f"pytaplite: {pytaplite.__version__}   "
          f"native binding: {'yes' if pytaplite.kernel._native_mod else 'no'}   "
          f"shared lib: {'yes' if pytaplite.kernel._find_shared_lib() else 'no'}")

    # --- the one call: run the assignment (copy to a temp dir so the benchmark isn't mutated)
    r = pytaplite.assign(scenario, exe=exe, in_place=False)
    print(f"\nran via {r.log.strip()}  (returncode {r.returncode})")

    # --- inspect the result -------------------------------------------------------------
    s = r.summary()
    print(f"links {s['links']:,}  loaded {s['loaded_links']:,}  "
          f"VMT {s['total_VMT']:,.0f}  VHT {s['total_VHT']:,.0f}")

    def voc(row):
        try:
            return float(row.get("doc") or row.get("voc") or 0)
        except ValueError:
            return 0.0
    top = sorted(r.links, key=voc, reverse=True)[:5]
    print("\ntop 5 links by V/C:")
    print(f"  {'from':>8} {'to':>8} {'volume':>10} {'V/C':>6} {'speed':>7}")
    for row in top:
        print(f"  {row.get('from_node_id',''):>8} {row.get('to_node_id',''):>8} "
              f"{float(row.get('volume') or 0):>10.0f} {voc(row):>6.2f} "
              f"{float(row.get('speed_mph') or 0):>7.1f}")

    # --- optional: as a DataFrame (pip install taplite4mpo[data]) ------------------------
    try:
        df = r.to_pandas()
        print(f"\nas a DataFrame: {df.shape[0]:,} rows x {df.shape[1]} cols  ->  r.to_pandas()")
    except ImportError:
        print("\n(install pandas for r.to_pandas(): pip install taplite4mpo[data])")

    print("\nDone. The C++ kernel solved; pytaplite ran it and returned the results.")


if __name__ == "__main__":
    main()
