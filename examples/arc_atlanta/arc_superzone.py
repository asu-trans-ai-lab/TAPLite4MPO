"""ARC Atlanta super-zone acceleration — build, run, and validate a compressed scenario.

Super-zones merge origin/destination zones that respond alike, so the assignment solves far
fewer shortest-path trees while the FULL link network (and its flows) is preserved. This is
the "compress the response, not the data" idea (docs/superzone_design_principles.md).

Usage (run arc_calibrate.py first, so gmns_calibrated/ exists):
    python arc_superzone.py            # build gmns_superzone/  (~K super-zones, default 1500)
    python arc_superzone.py 1000       # choose K
    python arc_superzone.py identity   # build gmns_identity/  (S=N corner case: must equal full)
    python arc_superzone.py validate gmns_superzone   # %RMSE vs ARC reference (remaps node ids)

Then run the kernel on the built folder and time it:
    cp ../../bin/DTALite.exe gmns_superzone/ && ( cd gmns_superzone && ./DTALite.exe )
"""
import os, sys, csv, math, collections

# make the in-repo dtalite_qa importable when run from this folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from dtalite_qa import superzone_hier as sz

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "gmns_calibrated")     # super-zone the CALIBRATED network
REF = os.path.join(HERE, "arc_am_ref_volume.csv")


def _nodes(path):
    """original node ids in file order, and the originals (zone_id==0) in file order."""
    ids, originals = [], []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        nid = int(float(r["node_id"])); ids.append(nid)
        if int(float(r.get("zone_id") or 0)) == 0:
            originals.append(nid)
    return ids, originals


def new2old(out_dir):
    """Map super-zone-network node ids back to original ARC node ids.
    build() lists super-zones (1..S) then the ORIGINAL nodes in the SAME order as the source
    node.csv, so the k-th zone_id==0 row here pairs with the k-th source node."""
    src_ids, _ = _nodes(os.path.join(SRC, "node.csv"))
    _, sz_orig = _nodes(os.path.join(out_dir, "node.csv"))
    return dict(zip(sz_orig, src_ids))      # sz_orig are in source order; pair to src_ids


def build(k_target, out_name):
    out = os.path.join(HERE, out_name)
    if not os.path.exists(os.path.join(SRC, "node.csv")):
        raise SystemExit("Run arc_calibrate.py first — gmns_calibrated/ not found.")
    rep = sz.build(SRC, out, k_target=k_target)
    for line in rep:
        print("  " + line)
    print(f"-> {out_name}/  (run the kernel here; fewer origins => faster)")
    return out


def validate(out_dir):
    m = new2old(out_dir)
    ref = {}
    for r in csv.DictReader(open(REF, encoding="utf-8-sig")):
        ref[(int(float(r["from_node_id"])), int(float(r["to_node_id"])))] = \
            (float(r["ref_auto_vol"]), int(float(r["factype"])))
    lp = os.path.join(out_dir, "link_performance.csv")
    if not os.path.exists(lp):
        raise SystemExit(f"No link_performance.csv in {out_dir} — run the kernel there first.")
    asg = {}
    for r in csv.DictReader(open(lp, encoding="utf-8-sig")):
        fn, tn = int(float(r["from_node_id"])), int(float(r["to_node_id"]))
        a, b = m.get(fn), m.get(tn)                 # remap super-zone-net ids -> original
        if a and b and r.get("volume"):
            asg[(a, b)] = float(r["volume"])
    keys = [k for k in ref if k in asg and ref[k][1] != 0]
    groups = [(0, 2000), (2000, 5000), (5000, 10000), (10000, 25000), (25000, 1e9)]
    print(f"== {os.path.basename(out_dir)} vs ARC AM reference ==  matched links {len(keys):,}")
    ts = tn_ = tr = 0.0
    for lo, hi in groups:
        gk = [k for k in keys if lo <= ref[k][0] < hi]
        if not gk:
            continue
        sse = sum((asg[k] - ref[k][0]) ** 2 for k in gk)
        sr = sum(ref[k][0] for k in gk); sa = sum(asg[k] for k in gk)
        rmse = 100 * math.sqrt(sse / len(gk)) / (sr / len(gk))
        print(f"  {lo//1000}k-{int(hi//1000)}k  n={len(gk):>7,}  %RMSE={rmse:4.0f}%  asg/ref={sa/sr:.2f}")
        ts += sse; tn_ += len(gk); tr += sr
    if tn_:
        print(f"  region-wide %RMSE = {100*math.sqrt(ts/tn_)/(tr/tn_):.0f}%  (full-resolution target ~38%)")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "1500"
    if a == "identity":
        build(None, "gmns_identity")          # S = N: must reproduce the full run exactly
    elif a == "validate":
        validate(os.path.join(HERE, sys.argv[2] if len(sys.argv) > 2 else "gmns_superzone"))
    else:
        build(int(a), "gmns_superzone")
