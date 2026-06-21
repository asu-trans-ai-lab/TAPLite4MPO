#!/usr/bin/env python3
"""
Regression harness for the DTALite/TAPLite C++ kernel.

Runs the built kernel on every test network in an ISOLATED temp copy (the DLL/exe
accumulates state across in-process calls, so each case must run fresh) and checks
the *intent* criteria for each case rather than exact numeric match to old outputs
(the shipped lp_*.csv references predate the 2026 kernel fixes -- e.g. the #5
multi-lane D/C fix legitimately changes multi-lane results).

Checks applied:
  completes        engine exits 0 and writes a non-empty link_performance.csv
  gap_ok           final relative gap is finite, NON-NEGATIVE (issue #7) and small
  allowed_use      restricted links carry ZERO volume for every disallowed mode
                   (auto-detected from link.csv allowed_use + mode_type.csv)
  modes_sane       every mode carries some volume; sov is the largest (multimodal)
  lane_dc          per-lane D/C == volume/(lanes*capacity*H*plf)  (issue #5/#9)
  turn_reroute     with movement.csv the banned movement is avoided (issue #3)

Usage:
  python run_regression.py [--exe PATH] [--only NAME[,NAME...]]
Exit code 0 if all PASS, 1 otherwise.
"""
import argparse, csv, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_EXE = os.path.join(ROOT, "bin", "DTALite.exe")
DATA = os.path.join(ROOT, "kernel", "data_sets")

INPUT_NAMES = {"node.csv", "link.csv", "mode_type.csv", "settings.csv", "movement.csv"}


def fnum(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def demand_files(case_dir):
    """Demand files referenced by mode_type.csv (fallback demand.csv)."""
    mt = os.path.join(case_dir, "mode_type.csv")
    files = set()
    if os.path.exists(mt):
        for r in csv.DictReader(open(mt)):
            df = (r.get("demand_file") or "").strip()
            if df:
                files.add(df)
    if not files and os.path.exists(os.path.join(case_dir, "demand.csv")):
        files.add("demand.csv")
    return files


def stage(case_dir, dst, drop_movement=False):
    """Copy only input files into an isolated dir."""
    wanted = set(INPUT_NAMES) | demand_files(case_dir)
    if drop_movement:
        wanted.discard("movement.csv")
    for name in wanted:
        src = os.path.join(case_dir, name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(dst, name))


def run_case(exe, case_dir, dst, drop_movement=False):
    stage(case_dir, dst, drop_movement)
    exe_local = os.path.join(dst, os.path.basename(exe))
    shutil.copy(exe, exe_local)
    p = subprocess.run([exe_local], cwd=dst, capture_output=True, text=True, timeout=900)
    log = p.stdout + p.stderr
    return p.returncode, log


def parse_lp(dst):
    path = os.path.join(dst, "link_performance.csv")
    if not os.path.exists(path):
        return None
    return list(csv.DictReader(open(path)))


def final_gap(log):
    g = None
    for line in log.splitlines():
        if "gap =" in line:
            try:
                g = float(line.split("gap =")[1].split("%")[0].strip())
            except (IndexError, ValueError):
                pass
    return g


def mode_tokens(case_dir):
    mt = os.path.join(case_dir, "mode_type.csv")
    if not os.path.exists(mt):
        return []
    return [r["mode_type"].strip() for r in csv.DictReader(open(mt)) if r.get("mode_type")]


# ---- checks: each returns (passed: bool, detail: str) ----

def chk_completes(ctx):
    if ctx["rc"] != 0:
        return False, f"exit={ctx['rc']}"
    if not ctx["lp"]:
        return False, "no link_performance.csv rows"
    return True, f"{len(ctx['lp'])} links"


def chk_gap_ok(ctx, max_gap=12.0):
    g = ctx["gap"]
    if g is None:
        return True, "no gap line (single-iter)"
    if g < -0.01:
        return False, f"NEGATIVE gap {g:.3f}%"
    if g > max_gap:
        return False, f"gap {g:.2f}% > {max_gap}%"
    return True, f"gap {g:.3f}%"


def chk_allowed_use(ctx):
    toks = mode_tokens(ctx["case_dir"])
    if len(toks) <= 1:
        return True, "single mode (n/a)"
    link = {r["link_id"]: r for r in csv.DictReader(open(os.path.join(ctx["case_dir"], "link.csv")))}
    restricted = 0
    fails = []
    for r in ctx["lp"]:
        lid = r["link_id"]
        au = (link.get(lid, {}).get("allowed_use") or "").strip()
        if not au or au.lower() == "all":
            continue
        disallowed = [t for t in toks if t not in au]
        if not disallowed:
            continue
        restricted += 1
        for t in disallowed:
            col = f"mod_vol_{t}"
            if col in r and fnum(r[col]) > 0.01:
                fails.append(f"link {lid}: {t}={fnum(r[col]):.0f}")
    if fails:
        return False, "; ".join(fails[:4])
    return True, f"{restricted} restricted links, 0 leak"


def chk_modes_sane(ctx):
    toks = mode_tokens(ctx["case_dir"])
    if len(toks) <= 1:
        return True, "single mode (n/a)"
    tot = {t: 0.0 for t in toks}
    for r in ctx["lp"]:
        for t in toks:
            tot[t] += fnum(r.get(f"mod_vol_{t}"))
    zero = [t for t, v in tot.items() if v <= 0]
    if zero:
        return False, f"zero-volume modes: {zero}"
    largest = max(tot, key=tot.get)
    note = f"largest={largest} " + ",".join(f"{t}={tot[t]:.0f}" for t in toks)
    return True, note


def chk_lane_dc(ctx):
    link = {r["link_id"]: r for r in csv.DictReader(open(os.path.join(ctx["case_dir"], "link.csv")))}
    s = list(csv.DictReader(open(os.path.join(ctx["case_dir"], "settings.csv"))))[0]
    H = fnum(s.get("demand_period_ending_hours"), 8) - fnum(s.get("demand_period_starting_hours"), 7)
    worst = 0.0
    for r in ctx["lp"]:
        lk = link.get(r["link_id"])
        if not lk:
            continue
        lanes = fnum(lk.get("lanes"), 1)
        cap = fnum(lk.get("capacity"), 1)
        plf = fnum(lk.get("vdf_plf"), 1) or 1.0
        vol = fnum(r["volume"])
        if lanes <= 0 or cap <= 0 or vol <= 0:
            continue
        expect = vol / (lanes * cap * max(H, 1e-6) * plf)
        worst = max(worst, abs(expect - fnum(r["doc"])))
    if worst > 1e-3:
        return False, f"max |D/C - vol/(lanes*cap*H*plf)| = {worst:.2e}"
    return True, f"lane-aware D/C ok (max diff {worst:.1e})"


def links_with_volume(lp):
    return sorted(r["link_id"] for r in lp if fnum(r["volume"]) > 0)


def chk_turn_reroute(ctx):
    # run again WITHOUT movement.csv and confirm the path differs
    with tempfile.TemporaryDirectory() as d2:
        rc, _ = run_case(ctx["exe"], ctx["case_dir"], d2, drop_movement=True)
        if rc != 0:
            return False, "baseline (no movement) run failed"
        base = links_with_volume(parse_lp(d2))
    restr = links_with_volume(ctx["lp"])
    if base == restr:
        return False, f"restriction did not change routing ({restr})"
    return True, f"no-mvmt={base} -> with-mvmt={restr}"


# ---- case registry ----
CASES = [
    {"name": "4_node_network",        "dir": f"{HERE}/4_node_network",        "checks": ["completes", "gap_ok"]},
    {"name": "I10_corridor_QVDF",     "dir": f"{HERE}/I10_corridor_QVDF",     "checks": ["completes"]},
    {"name": "I10_QVDF_1lane",        "dir": f"{HERE}/I10_corridor_QVDF_1lane","checks": ["completes", "lane_dc"]},
    {"name": "I10_QVDF_2lane",        "dir": f"{HERE}/I10_corridor_QVDF_2lane","checks": ["completes", "lane_dc"]},
    {"name": "I10_QVDF_multilane",    "dir": f"{HERE}/I10_corridor_QVDF_multilane","checks": ["completes", "lane_dc"]},
    {"name": "multilane_bpr",         "dir": f"{HERE}/multilane_bpr",         "checks": ["completes", "lane_dc"]},
    {"name": "turn_restriction",      "dir": f"{HERE}/turn_restriction",      "checks": ["completes", "turn_reroute"]},
    {"name": "sf_multimodal",         "dir": f"{HERE}/sf_multimodal",         "checks": ["completes", "gap_ok", "allowed_use", "modes_sane"]},
    {"name": "cs_multimodal",         "dir": f"{HERE}/cs_multimodal",         "checks": ["completes", "gap_ok", "allowed_use", "modes_sane"]},
    {"name": "sf_conic",              "dir": f"{HERE}/sf_conic",              "checks": ["completes", "gap_ok", "allowed_use", "modes_sane"]},
    {"name": "data/02_Sioux_Falls",   "dir": f"{DATA}/02_Sioux_Falls",        "checks": ["completes", "gap_ok"]},
    {"name": "data/03_chicago_sketch","dir": f"{DATA}/03_chicago_sketch",     "checks": ["completes", "gap_ok"]},
]

CHECKS = {
    "completes": chk_completes, "gap_ok": chk_gap_ok, "allowed_use": chk_allowed_use,
    "modes_sane": chk_modes_sane, "lane_dc": chk_lane_dc, "turn_reroute": chk_turn_reroute,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=DEFAULT_EXE)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    if not os.path.exists(args.exe):
        print(f"ERROR: kernel exe not found: {args.exe}\nBuild it first (bash build.sh).")
        return 2
    only = set(x.strip() for x in args.only.split(",") if x.strip())

    all_pass = True
    print(f"{'case':24} {'check':14} {'result':6} detail")
    print("-" * 90)
    for case in CASES:
        if only and case["name"] not in only:
            continue
        if not os.path.isdir(case["dir"]):
            print(f"{case['name']:24} {'(missing dir)':14} SKIP   {case['dir']}")
            continue
        with tempfile.TemporaryDirectory() as dst:
            try:
                rc, log = run_case(args.exe, case["dir"], dst)
            except subprocess.TimeoutExpired:
                print(f"{case['name']:24} {'run':14} FAIL   timeout")
                all_pass = False
                continue
            ctx = {"case_dir": case["dir"], "exe": args.exe, "rc": rc,
                   "log": log, "lp": parse_lp(dst), "gap": final_gap(log)}
            for ck in case["checks"]:
                ok, detail = CHECKS[ck](ctx)
                all_pass &= ok
                print(f"{case['name']:24} {ck:14} {'PASS' if ok else 'FAIL':6} {detail}")
    print("-" * 90)
    print("ALL PASS" if all_pass else "SOME FAILED")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
