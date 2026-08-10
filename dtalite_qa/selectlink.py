"""Select-link analysis — CR-0011 (Select-Link Foundation).

Queries the path store of a finished run (route_assignment.csv,
route_output=1): which OD flows, modes and volumes use link X? Which use
the ordered pair (X, then Y)?

Method discipline (governing architecture, doc 09): UE link flows are
unique, route flows are NOT. Every output is stamped with
`path_flow_method`. Today only `raw_fw_columns` exists — valid for
diagnostics; NOT valid for official reporting. `proportional` /
`entropy_reconciled` reconstruction will register here when implemented,
and official regressions must use them.

CLI:
  python -m dtalite_qa.selectlink <run_dir> --link 986
  python -m dtalite_qa.selectlink <run_dir> --link 986 --then 994
  python -m dtalite_qa.selectlink <run_dir> --link 986 --top 25 --json out.json

Conservation check (always run): the sum of selected column volumes must
equal the link's assigned volume from link_performance.csv within
tolerance — the WP-05 acceptance test.
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict

METHOD = "raw_fw_columns"
OFFICIAL = False


def analyze(run_dir, link_id, then_link=None, top=20):
    ra = os.path.join(run_dir, "route_assignment.csv")
    if not os.path.exists(ra):
        raise SystemExit("route_assignment.csv not found — rerun the kernel "
                         "with route_output=1")
    want = str(int(link_id))
    want2 = str(int(then_link)) if then_link is not None else None
    total = 0.0
    by_mode = defaultdict(float)
    by_od = defaultdict(float)
    by_origin = defaultdict(float)
    by_dest = defaultdict(float)
    n_paths = 0
    with open(ra, newline="") as f:
        for r in csv.DictReader(f):
            links = r["link_ids"].split(";")
            if want not in links:
                continue
            if want2 is not None:
                i = links.index(want)
                if want2 not in links[i + 1:]:
                    continue
            v = float(r["volume"] or 0)
            if v <= 0:
                continue
            n_paths += 1
            total += v
            by_mode[r["mode"]] += v
            o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
            by_od[(o, d)] += v
            by_origin[o] += v
            by_dest[d] += v

    # conservation vs assigned link volume (single-link query only)
    conservation = None
    lp = os.path.join(run_dir, "link_performance.csv")
    if want2 is None and os.path.exists(lp):
        with open(lp, newline="") as f:
            for r in csv.DictReader(f):
                if str(int(float(r["link_id"]))) == want:
                    lv = float(r["volume"] or 0)
                    conservation = {
                        "link_volume": round(lv, 1),
                        "selected_paths_volume": round(total, 1),
                        "abs_gap": round(abs(lv - total), 2),
                        "rel_gap": round(abs(lv - total) / max(lv, 1e-9), 6),
                    }
                    break

    top_od = sorted(by_od.items(), key=lambda kv: -kv[1])[:top]
    return {
        "path_flow_method": METHOD,
        "official_reporting_valid": OFFICIAL,
        "note": "raw FW columns: route flows are algorithm history, not a "
                "unique behavioral decomposition; use for diagnostics",
        "selected_link": int(link_id),
        "then_link": int(then_link) if then_link is not None else None,
        "paths_using": n_paths,
        "total_flow": round(total, 1),
        "by_mode": {k: round(v, 1) for k, v in sorted(by_mode.items())},
        "top_od": [{"o": o, "d": d, "flow": round(v, 1)}
                   for (o, d), v in top_od],
        "distinct_origins": len(by_origin),
        "distinct_destinations": len(by_dest),
        "conservation": conservation,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--link", type=int, required=True)
    ap.add_argument("--then", type=int, default=None,
                    help="ordered second link (gate pair)")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    out = analyze(a.run_dir, a.link, a.then, a.top)
    text = json.dumps(out, indent=2)
    if a.json:
        open(a.json, "w").write(text)
    print(text)
    c = out["conservation"]
    if c and c["rel_gap"] > 0.01:
        print("WARNING: conservation gap %.2f%% — column store and link "
              "flows disagree" % (100 * c["rel_gap"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
