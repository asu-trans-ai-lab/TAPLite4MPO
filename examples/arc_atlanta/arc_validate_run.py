#!/usr/bin/env python3
"""Validate a kernel run against the ARC reference benchmark (Section 7.1.4).
Joins link_performance.csv (assigned `volume`) to arc_am_ref_volume.csv
(`ref_auto_vol`) by (from,to); reports %RMSE and volume/count ratio by ARC volume
group vs the acceptance thresholds.  Usage: python arc_validate_run.py <run_dir>"""
import csv, math, collections, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "gmns_calibrated")

GROUPS = [(0,2500,1.00),(2500,5000,0.55),(5000,10000,0.45),(10000,25000,0.30),
          (25000,50000,0.25),(50000,75000,0.19),(75000,1e9,0.19)]


def grp(v):
    for lo, hi, t in GROUPS:
        if lo <= v < hi:
            return (lo, hi, t)
    return GROUPS[-1]


def main():
    ref = {}
    for r in csv.DictReader(open(os.path.join(HERE, "arc_am_ref_volume.csv"), encoding="utf-8-sig")):
        ref[(r["from_node_id"], r["to_node_id"])] = (float(r["ref_auto_vol"]), int(float(r["factype"])))
    asg = {}
    for r in csv.DictReader(open(os.path.join(RUN, "link_performance.csv"), encoding="utf-8-sig")):
        try:
            asg[(r["from_node_id"], r["to_node_id"])] = float(r["volume"])
        except (KeyError, ValueError):
            pass
    keys = [k for k in ref if k in asg and ref[k][1] != 0]   # exclude connectors
    b = collections.defaultdict(lambda: [0, 0.0, 0.0, 0.0])  # n, sumref, sse, sumasg
    for k in keys:
        rv = ref[k][0]; av = asg.get(k, 0)
        bk = b[grp(rv)]
        bk[0] += 1; bk[1] += rv; bk[2] += (av-rv)**2; bk[3] += av
    print(f"== {os.path.basename(RUN)} vs ARC AM reference ==  links {len(keys):,}")
    print(f"{'volume group':14}{'n':>8}{'%RMSE':>8}{'target':>8}{'asg/ref':>9}{'pass':>6}")
    tn = ts = tr = 0
    for lo, hi, t in GROUPS:
        bk = b[(lo, hi, t)]
        if bk[0] == 0:
            continue
        mean = bk[1]/bk[0]; rmse = math.sqrt(bk[2]/bk[0]); pct = 100*rmse/mean if mean else 0
        tn += bk[0]; ts += bk[2]; tr += bk[1]
        lbl = f"{lo//1000}k-{'+' if hi > 1e8 else str(int(hi)//1000)+'k'}"
        print(f"{lbl:14}{bk[0]:>8,}{pct:>7.0f}%{t*100:>7.0f}%{bk[3]/bk[1]:>9.2f}{'Y' if pct <= t*100 else 'n':>6}")
    gm = tr/tn; print(f"\nregion-wide %RMSE = {100*math.sqrt(ts/tn)/gm:.0f}% (target ~38%); "
                      f"assigned/ref total = {sum(asg.get(k,0) for k in keys)/sum(ref[k][0] for k in keys):.2f}")


if __name__ == "__main__":
    main()
