"""Automatic BPR coefficient calibration against observed/reference volumes.

THE function agencies ask for: given a runnable GMNS scenario and a reference-volume
column, find per-group vdf_alpha / vdf_beta that minimize the volume error, by running
the actual kernel in the loop (so congestion feedback and rerouting are fully honored --
no surrogate model, no closed-form shortcut).

Method: derivative-free COMPASS (pattern) SEARCH over the concatenated parameter vector
[ (alpha_g, beta_g) per calibration group ], with multiplicative steps for alpha and
additive for beta, box bounds alpha in [0.05, 1.5], beta in [1.5, 10]. Each evaluation
copies the scenario to a temp dir, patches link.csv, runs the kernel, scores
sqrt(mean((assigned - ref)^2)) over links with ref > 0 (optionally volume-weighted).
Groups default to the `link_type` column; pass --group-col factype etc. for agency codes.

PRECONDITION (see docs/CONVERSION_ERRORS_CATALOG.md): calibrate ONLY on a scenario whose
units / capacity basis / period+PLF conventions passed the intake gate -- otherwise you
are fitting alpha/beta to a units bug. The same loop extends to QVDF parameters
(vdf_cd / vdf_n with vdf_type=2) via --params.

Usage:
  python -m dtalite_qa.calibrate <scenario> --exe bin/DTALite.exe \
      [--ref-col ref_volume] [--group-col link_type] [--budget 40] [--weighted]
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import math

BOUNDS = {"vdf_alpha": (0.05, 1.5), "vdf_beta": (1.5, 10.0)}


def read_links(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames), list(r)


def scenario_groups(rows, group_col):
    groups = sorted({(r.get(group_col) or "").strip() for r in rows
                     if (r.get(group_col) or "").strip() not in ("", "100", "9")})
    return groups


def patch_and_run(scen, exe, rows, hdr, group_col, params, workdir):
    """Write link.csv with per-group alpha/beta from params, run kernel, return volumes."""
    out = os.path.join(workdir, "s")
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(scen, out, ignore=shutil.ignore_patterns(
        "link_performance*", "*.log", "od_performance*", "*accessibility*", "route_*"))
    with open(os.path.join(out, "link.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=hdr, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            g = (r.get(group_col) or "").strip()
            if g in params:
                r = dict(r)
                r["vdf_alpha"], r["vdf_beta"] = round(params[g][0], 4), round(params[g][1], 3)
            w.writerow(r)
    with open(os.path.join(out, "kernel.log"), "w") as log:
        rc = subprocess.run([os.path.abspath(exe)], cwd=out, stdout=log,
                            stderr=subprocess.STDOUT).returncode
    if rc != 0:
        return None
    vol = {}
    with open(os.path.join(out, "link_performance.csv"), newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                vol[r["link_id"]] = vol.get(r["link_id"], 0.0) + float(r["volume"])
            except (KeyError, ValueError):
                continue
    return vol


def score(vol, ref, weighted):
    se = 0.0
    wsum = 0.0
    for lid, rv in ref.items():
        v = vol.get(lid, 0.0)
        w = rv if weighted else 1.0
        se += w * (v - rv) ** 2
        wsum += w
    return math.sqrt(se / max(wsum, 1e-9))


def calibrate(scen, exe, ref_col="ref_volume", group_col="link_type", budget=12,
              weighted=False, verbose=True):
    hdr, rows = read_links(os.path.join(scen, "link.csv"))
    if ref_col not in hdr:
        sys.exit(f"link.csv has no '{ref_col}' column -- nothing to calibrate against")
    ref = {}
    for r in rows:
        try:
            rv = float(r.get(ref_col) or 0)
            if rv > 0:
                ref[r["link_id"]] = rv
        except ValueError:
            continue
    groups = scenario_groups(rows, group_col)
    if verbose:
        print(f"calibrating {len(groups)} group(s) {groups} against {len(ref):,} "
              f"ref links; budget {budget} kernel runs")
    # start from the scenario's current values (first row of each group)
    params = {}
    for g in groups:
        r0 = next(r for r in rows if (r.get(group_col) or "").strip() == g)
        params[g] = [float(r0.get("vdf_alpha") or 0.15), float(r0.get("vdf_beta") or 4)]

    workdir = tempfile.mkdtemp(prefix="dtalite_calib_")
    evals = [0]

    def f(p):
        evals[0] += 1
        vol = patch_and_run(scen, exe, rows, hdr, group_col, p, workdir)
        return float("inf") if vol is None else score(vol, ref, weighted)

    best = f(params)
    if verbose:
        print(f"  start RMSE = {best:,.1f}   params={ {g: tuple(v) for g, v in params.items()} }")
    # compass search: alpha multiplicative step, beta additive step
    step_a, step_b = 1.6, 1.5
    while evals[0] < budget and (step_a > 1.03 or step_b > 0.12):
        improved = False
        for g in groups:
            for dim, lo_hi, stp, mul in ((0, BOUNDS["vdf_alpha"], step_a, True),
                                         (1, BOUNDS["vdf_beta"], step_b, False)):
                if evals[0] >= budget:
                    break
                base = params[g][dim]
                cands = [base * stp, base / stp] if mul else [base + stp, base - stp]
                for c in cands:
                    c = min(max(c, lo_hi[0]), lo_hi[1])
                    if abs(c - base) < 1e-9 or evals[0] >= budget:
                        continue
                    trial = {k: list(v) for k, v in params.items()}
                    trial[g][dim] = c
                    s = f(trial)
                    if s < best - 1e-9:
                        best, params = s, trial
                        improved = True
                        if verbose:
                            print(f"  eval {evals[0]:>3}: RMSE {s:,.1f}  "
                                  f"{g}.{'alpha' if dim==0 else 'beta'} -> {c:.3f}")
                        break
        if not improved:
            step_a = math.sqrt(step_a)
            step_b = step_b / 2
    shutil.rmtree(workdir, ignore_errors=True)
    result = {g: {"vdf_alpha": round(v[0], 4), "vdf_beta": round(v[1], 3)} for g, v in params.items()}
    if verbose:
        print(f"DONE after {evals[0]} kernel runs: RMSE {best:,.1f}")
        for g, v in result.items():
            print(f"  group {g}: alpha={v['vdf_alpha']}  beta={v['vdf_beta']}")
    return result, best


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scenario")
    ap.add_argument("--exe", required=True)
    ap.add_argument("--ref-col", default="ref_volume")
    ap.add_argument("--group-col", default="link_type")
    ap.add_argument("--budget", type=int, default=12)
    ap.add_argument("--weighted", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="write calibrated alpha/beta back into the scenario's link.csv")
    a = ap.parse_args()
    result, rmse = calibrate(a.scenario, a.exe, a.ref_col, a.group_col, a.budget, a.weighted)
    if a.apply:
        hdr, rows = read_links(os.path.join(a.scenario, "link.csv"))
        for r in rows:
            g = (r.get(a.group_col) or "").strip()
            if g in result:
                r["vdf_alpha"] = result[g]["vdf_alpha"]
                r["vdf_beta"] = result[g]["vdf_beta"]
        with open(os.path.join(a.scenario, "link.csv"), "w", newline="", encoding="utf-8") as fo:
            w = csv.DictWriter(fo, fieldnames=hdr, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print("applied to link.csv")


if __name__ == "__main__":
    main()
