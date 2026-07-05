"""Truth-recovery test for dtalite_qa.calibrate (the BPR auto-calibration function).

Protocol (self-validating, no external counts needed):
  1. copy Chicago Sketch; set KNOWN 'truth' coefficients alpha=0.60, beta=6.0 on all
     roadway links; run the kernel once; write its volumes into link.csv ref_volume.
  2. reset coefficients to the BPR defaults (0.15, 4).
  3. run the auto-calibrator (budget 36 kernel runs).
  4. PASS iff calibrated RMSE <= 2% of mean ref volume (identifiability note: several
     (alpha,beta) pairs can fit flows almost equally well -- volume match is the
     acceptance criterion, coefficient closeness is reported for information).

Usage: python test_calibrate_recovery.py [--exe ../cmake_build_rel/DTALite_exe.exe]
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
from dtalite_qa.calibrate import calibrate, read_links  # noqa: E402

SRC = os.path.join(ROOT, "kernel", "data_sets", "03_chicago_sketch")
WORK = os.path.join(HERE, "_calib_recovery")
TRUTH = (0.60, 6.0)


def run_kernel(scen, exe):
    with open(os.path.join(scen, "kernel.log"), "w") as log:
        rc = subprocess.run([os.path.abspath(exe)], cwd=scen, stdout=log,
                            stderr=subprocess.STDOUT).returncode
    assert rc == 0, f"kernel failed in {scen}"
    vol = {}
    with open(os.path.join(scen, "link_performance.csv"), newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                vol[r["link_id"]] = vol.get(r["link_id"], 0.0) + float(r["volume"])
            except (KeyError, ValueError):
                continue
    return vol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.path.join(ROOT, "cmake_build_rel", "DTALite_exe.exe"))
    ap.add_argument("--budget", type=int, default=36)
    a = ap.parse_args()

    if os.path.exists(WORK):
        shutil.rmtree(WORK)
    shutil.copytree(SRC, WORK, ignore=shutil.ignore_patterns("link_performance*", "*.log"))

    # 1. plant the truth and generate synthetic counts
    hdr, rows = read_links(os.path.join(WORK, "link.csv"))
    for c in ("vdf_alpha", "vdf_beta", "ref_volume"):
        if c not in hdr:
            hdr.append(c)
    for r in rows:
        r["vdf_alpha"], r["vdf_beta"] = TRUTH
    with open(os.path.join(WORK, "link.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=hdr, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    truth_vol = run_kernel(WORK, a.exe)
    mean_ref = sum(truth_vol.values()) / max(len(truth_vol), 1)

    # 2. write counts, reset to defaults
    for r in rows:
        r["ref_volume"] = round(truth_vol.get(r["link_id"], 0.0), 2)
        r["vdf_alpha"], r["vdf_beta"] = 0.15, 4
    with open(os.path.join(WORK, "link.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=hdr, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    # 3. calibrate
    result, rmse = calibrate(WORK, a.exe, ref_col="ref_volume",
                             group_col="link_type", budget=a.budget)

    # 4. verdict
    tol = 0.02 * mean_ref
    print(f"\nTRUTH alpha={TRUTH[0]} beta={TRUTH[1]}; recovered: {result}")
    print(f"final RMSE {rmse:,.1f} vs tolerance {tol:,.1f} (2% of mean ref {mean_ref:,.0f})")
    if rmse <= tol:
        print("RECOVERY TEST: PASS")
    else:
        print("RECOVERY TEST: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
