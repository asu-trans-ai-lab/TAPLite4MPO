"""
Run the NVTA 6-mode Frank-Wolfe assignment with the consolidated CMake kernel
against the RENUMBERED, small-footprint _internal/ dataset, then verify per-mode
link volume vs CUBE (I4PM* columns, joined on (from,to)) and check allowed_use.

Config (mode_type.csv with dedicated+trk pce=2, settings_<N>iter.csv) lives HERE;
the large node/link/demand data stays in _internal/ and is run against in place.

Usage:  python run_nvta.py [iters]      # iters in {1,10,20}, default 1
"""
import csv, math, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KERNEL = os.path.join(HERE, "..", "bin", "DTALite.exe")
from data_root import internal
INTERNAL = internal()
RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

CUBECOL = {"TOTAL": "I4PMVOL", "sov": "I4PMSOV", "hov2": "I4PMHV2",
           "hov3": "I4PMHV3", "trk": "I4PMTRK", "com": "I4PMCV", "apv": "I4PMAPX"}
MODES = ["sov", "hov2", "hov3", "com", "trk", "apv"]

def prep_and_run(iters):
    # back up the original _internal config once
    for f in ("mode_type.csv", "settings.csv"):
        orig = os.path.join(INTERNAL, f); bak = orig + ".orig"
        if os.path.exists(orig) and not os.path.exists(bak):
            shutil.copy2(orig, bak)
    shutil.copy(os.path.join(HERE, "mode_type.csv"), os.path.join(INTERNAL, "mode_type.csv"))
    shutil.copy(os.path.join(HERE, f"settings_{iters}iter.csv"), os.path.join(INTERNAL, "settings.csv"))
    exe = os.path.join(INTERNAL, "DTALite.exe")
    shutil.copy(KERNEL, exe)
    for f in ("link_performance.csv", "summary_log_file.txt", "TAP_log.csv"):
        p = os.path.join(INTERNAL, f)
        if os.path.exists(p):
            try: os.remove(p)
            except OSError: pass
    print(f"[run] NVTA _internal FW {iters} iter (route_output=0, trk pce=2) ...", flush=True)
    import time; t0 = time.time()
    r = subprocess.run([exe], cwd=INTERNAL)
    print(f"[run] exit={r.returncode} elapsed={time.time()-t0:.0f}s", flush=True)
    lp = os.path.join(INTERNAL, "link_performance.csv")
    if os.path.exists(lp):
        out = os.path.join(RESULTS, f"link_perf_iter{iters}.csv")
        shutil.copy(lp, out)
        return out
    return None

def verify(perf_csv):
    link = os.path.join(INTERNAL, "link.csv")
    cube = {}; allowed = {}
    for x in csv.DictReader(open(link, newline="", encoding="utf-8-sig")):
        k = (x["from_node_id"], x["to_node_id"])
        cube[k] = {c: float(x.get(col, 0) or 0) for c, col in CUBECOL.items()}
        allowed[k] = x["allowed_use"].strip()
    tap = {}
    rdr = csv.DictReader(open(perf_csv, newline="")); cols = rdr.fieldnames
    for x in rdr:
        k = (x["from_node_id"], x["to_node_id"])
        d = {"TOTAL": float(x.get("volume", 0) or 0)}
        for m in MODES:
            c = "mod_vol_" + m
            d[m] = float(x.get(c, 0) or 0) if (cols and c in cols) else 0.0
        tap[k] = d

    def stats(pairs):
        n = len(pairs)
        if n < 2: return None
        X = [p[0] for p in pairs]; Y = [p[1] for p in pairs]
        mx = sum(X)/n; my = sum(Y)/n
        sxx = sum((a-mx)**2 for a in X); syy = sum((b-my)**2 for b in Y); sxy = sum((a-mx)*(b-my) for a, b in zip(X, Y))
        r2 = (sxy*sxy)/(sxx*syy) if sxx > 0 and syy > 0 else float("nan")
        rmse = math.sqrt(sum((a-b)**2 for a, b in zip(X, Y))/n)
        return n, r2, rmse, sum(X), sum(Y)

    print(f"\n=== TAPLite vs CUBE (join on from/to) ===")
    print(f"{'class':<7}{'n':>7}{'R2':>9}{'RMSE':>10}{'CUBE_tot':>14}{'TAP_tot':>14}{'ratio':>8}")
    for c in ["TOTAL"] + MODES:
        pairs = [(cube[k][c], tap[k][c]) for k in tap if k in cube and cube[k][c] > 0]
        s = stats(pairs)
        if s:
            n, r2, rmse, ct, tt = s
            print(f"{c:<7}{n:>7}{r2:>9.4f}{rmse:>10.1f}{ct:>14,.0f}{tt:>14,.0f}{(tt/ct if ct else 0):>8.3f}")

    # allowed_use enforcement
    print("  --- allowed_use enforcement ---")
    all6 = set(MODES); ok = True
    classes = {}
    for k, au in allowed.items():
        if au == "sov;hov2;hov3;trk;apv;com": continue
        classes.setdefault(au, []).append(k)
    for au, ks in sorted(classes.items()):
        allowset = set() if au == "closed" else set(t.strip() for t in au.split(";"))
        dis = all6 - allowset
        leak = sum(tap[k][m] for k in ks if k in tap for m in dis)
        if leak >= 1e-6: ok = False
        print(f"     {au:<32} links={len(ks):<5} -> {'PASS' if leak < 1e-6 else f'LEAK {leak:.1f}'}")
    print(f"  allowed_use OVERALL: {'PASS' if ok else 'FAIL'}")

if __name__ == "__main__":
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    out = prep_and_run(iters)
    if out:
        verify(out)
    else:
        print("NO link_performance.csv produced — run failed.")
