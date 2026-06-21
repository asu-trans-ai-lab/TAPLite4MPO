"""ARC Atlanta — recover the ORIGINAL-resolution zone-to-zone travel-time skim from a run.

The key advantage of super-zones: the assignment uses few origins, but the FULL link network
is solved, so the congested link travel times are full-resolution. From them we recover the
complete 6,031 x 6,031 zone-to-zone skim — at compressed-assignment speed. The skim is the
supply->demand decoder that 4-step / activity models feed back on.

Requires numpy + scipy.

Usage (after the runs in arc_superzone.py / the main README):
    python arc_skim.py full     # skim from the full run        -> arc_skim_full.csv
    python arc_skim.py sz       # skim from the super-zone run   -> arc_skim_from_superzone.csv
                                #   (remaps super-zone node ids back to the original network)
    python arc_skim.py compare  # full vs super-zone skim: R^2 + error (proves equivalence)
"""
import os, sys, csv, math

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from dtalite_qa import skim as sk
from dtalite_qa import csvio

HERE = os.path.dirname(os.path.abspath(__file__))
FULL = os.path.join(HERE, "gmns_calibrated")        # ORIGINAL 6,031-zone network + full run
SZ = os.path.join(HERE, "gmns_superzone")           # super-zone run (remapped node ids)
SKIM_FULL = os.path.join(HERE, "arc_skim_full.csv")
SKIM_SZ = os.path.join(HERE, "arc_skim_from_superzone.csv")


def _S(sz_dir):
    _, nr = csvio.read(csvio.path(sz_dir, "node.csv"))
    return max(csvio.inum(r.get("zone_id"), 0) for r in nr)     # # of super-zones


def _demand_pairs():
    """OD pairs that carry SOV demand (keeps the skim output sparse / usable)."""
    pairs = set()
    p = csvio.path(FULL, "demand_sov.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            try:
                pairs.add((int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))))
            except (KeyError, ValueError):
                pass
    return pairs or None


def make(which):
    if which == "sz":
        if not os.path.exists(csvio.path(SZ, "link_performance.csv")):
            raise SystemExit("Run the super-zone scenario first (see arc_superzone.py).")
        S = _S(SZ)
        remap = sk.superzone_remap(FULL, S)            # new super-zone node id -> original id
        times = sk.read_link_times(csvio.path(SZ, "link_performance.csv"), "travel_time", remap=remap)
        out, label = SKIM_SZ, f"super-zone run (S={S}) -> original network"
    else:
        if not os.path.exists(csvio.path(FULL, "link_performance.csv")):
            raise SystemExit("Run the full scenario first (gmns_calibrated/).")
        times = sk.read_link_times(csvio.path(FULL, "link_performance.csv"), "travel_time")
        out, label = SKIM_FULL, "full run"
    print(f"skimming original 6,031-zone network from {label} ({len(times):,} link times)...")
    zones, M = sk.skim(FULL, times)                    # Dijkstra over the ORIGINAL network
    sk.write_skim(zones, M, out, demand_pairs_only=_demand_pairs())
    print(f"-> {os.path.basename(out)}  ({len(zones):,} zones; o_zone_id,d_zone_id,travel_time on demand pairs)")


def compare():
    def load(p):
        d = {}
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            d[(r["o_zone_id"], r["d_zone_id"])] = float(r["travel_time"])
        return d
    if not (os.path.exists(SKIM_FULL) and os.path.exists(SKIM_SZ)):
        raise SystemExit("Build both skims first: python arc_skim.py full  &&  python arc_skim.py sz")
    a, b = load(SKIM_FULL), load(SKIM_SZ)
    keys = [k for k in a if k in b]
    n = len(keys)
    mean = sum(a[k] for k in keys) / n
    ss_res = sum((a[k] - b[k]) ** 2 for k in keys)
    ss_tot = sum((a[k] - mean) ** 2 for k in keys)
    mae = sum(abs(a[k] - b[k]) for k in keys) / n
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    print(f"== full vs super-zone skim ==  {n:,} common OD pairs")
    print(f"  R^2 = {r2:.4f}   mean |Δtime| = {mae:.3f} min   (full mean {mean:.2f} min)")
    print("  -> the super-zone run reproduces the full-resolution zone-to-zone skim" if r2 > 0.95
          else "  -> skims diverge; raise K or check the remap")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sz"
    compare() if cmd == "compare" else make(cmd)
