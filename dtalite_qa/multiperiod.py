"""Multi-period runner + daily accumulation (WP-11).

Runs each period scenario (one folder per period, e.g. root/EA, root/AM, ...) through
the kernel, then SUMS link volumes/VMT across periods into a daily table -- so a
single-period assignment is never compared against a daily reference again
(CONVERSION_ERRORS_CATALOG section 2b: the period-vs-daily basis trap).

Layout convention (what the SCAG pipeline uses):
    root/
      EA/  AM/  MD/  PM/  EV/     each a complete runnable scenario, SAME network
                                  (same link_id space), period demand + period H
Each period keeps its OWN congestion (BPR is period-specific); daily = sum of the
period equilibria, matching how agencies build daily loaded networks.

API:
  run_periods(root, periods, exe)          -> {period: returncode}
  accumulate(root, periods, out_csv=None)  -> daily rows + invariant checks
CLI:
  python -m dtalite_qa.multiperiod <root> --periods EA,AM,MD,PM,EV --exe <exe> [--run]
"""
import argparse
import csv
import os
import subprocess
import sys


def run_periods(root, periods, exe, log_name="run.log"):
    """Run the kernel in each period folder sequentially. Returns {period: rc}."""
    rcs = {}
    for p in periods:
        scen = os.path.join(root, p)
        if not os.path.isdir(scen):
            rcs[p] = None
            print(f"  {p}: MISSING folder {scen}")
            continue
        with open(os.path.join(scen, log_name), "w") as log:
            rc = subprocess.run([os.path.abspath(exe)], cwd=scen,
                                stdout=log, stderr=subprocess.STDOUT).returncode
        rcs[p] = rc
        print(f"  {p}: kernel exit {rc}")
    return rcs


def accumulate(root, periods, out_csv=None):
    """Sum link volume/VMT across the periods' link_performance.csv into a daily
    table keyed by link_id (+ from/to for traceability). Also returns invariant
    checks: daily totals must equal the sum of period totals exactly."""
    daily = {}          # link_id -> dict
    per_totals = {}
    for p in periods:
        f = os.path.join(root, p, "link_performance.csv")
        if not os.path.exists(f):
            raise FileNotFoundError(f"{f} not found -- run the {p} period first")
        vol_t = vmt_t = 0.0
        with open(f, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                lid = r.get("link_id")
                try:
                    v = float(r.get("volume") or 0)
                    vm = float(r.get("VMT") or 0)
                except ValueError:
                    continue
                d = daily.setdefault(lid, {"link_id": lid,
                                           "from_node_id": r.get("from_node_id"),
                                           "to_node_id": r.get("to_node_id"),
                                           "daily_volume": 0.0, "daily_vmt": 0.0})
                d["daily_volume"] += v
                d["daily_vmt"] += vm
                d[f"vol_{p}"] = round(v, 2)
                vol_t += v
                vmt_t += vm
        per_totals[p] = {"volume": vol_t, "vmt": vmt_t}
    # invariants
    sum_v = sum(t["volume"] for t in per_totals.values())
    day_v = sum(d["daily_volume"] for d in daily.values())
    ok = abs(sum_v - day_v) <= max(1e-6 * sum_v, 1e-3)
    rows = sorted(daily.values(), key=lambda d: float(d["link_id"]))
    if out_csv:
        hdr = ["link_id", "from_node_id", "to_node_id", "daily_volume", "daily_vmt"] + \
              [f"vol_{p}" for p in periods]
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=hdr, extrasaction="ignore")
            w.writeheader()
            for d in rows:
                d["daily_volume"] = round(d["daily_volume"], 2)
                d["daily_vmt"] = round(d["daily_vmt"], 2)
                w.writerow(d)
    return {"links": len(rows), "period_totals": per_totals,
            "daily_volume": day_v, "conserved": ok, "out_csv": out_csv}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", help="folder containing one scenario subfolder per period")
    ap.add_argument("--periods", default="EA,AM,MD,PM,EV")
    ap.add_argument("--exe", default=None)
    ap.add_argument("--run", action="store_true", help="run the kernel per period first")
    ap.add_argument("--out", default=None, help="daily CSV (default <root>/daily_link_performance.csv)")
    a = ap.parse_args(argv)
    periods = [p.strip() for p in a.periods.split(",") if p.strip()]
    if a.run:
        if not a.exe:
            sys.exit("--run requires --exe")
        run_periods(a.root, periods, a.exe)
    out = a.out or os.path.join(a.root, "daily_link_performance.csv")
    res = accumulate(a.root, periods, out_csv=out)
    print(f"daily accumulation: {res['links']:,} links; conserved={res['conserved']}")
    for p, t in res["period_totals"].items():
        print(f"  {p}: volume {t['volume']:,.0f}  VMT {t['vmt']:,.0f}")
    print(f"  DAILY volume {res['daily_volume']:,.0f} -> {res['out_csv']}")
    return 0 if res["conserved"] else 1


if __name__ == "__main__":
    sys.exit(main())
