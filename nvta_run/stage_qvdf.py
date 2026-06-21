"""
Gate C (QVDF): stage the regional _internal/link.csv with calibrated QVDF params
(per-FT PM-period averages from NVTA_qvdf_dict) and vdf_type=2 so the kernel's
QVDF period-average travel time drives the assignment.

Kernel reads: vdf_alpha/vdf_beta (queue-speed), vdf_cp/vdf_cd/vdf_n/vdf_s (P & vt2),
vdf_plf (QVDF's own PLF), Cutoff_Speed=free_speed*0.75 (kernel default).

Calibration coverage: FT1/FT2/FT5 directly; FT3/FT4/FT6 use the 'all' global avg;
FT0 centroal connectors stay BPR (vdf_type=0). Base = renumbered+sorted link.csv.
"""
import csv, os, shutil

from data_root import internal
INTERNAL = internal()
# per-FT PM-period QVDF params (averaged from NVTA_qvdf_dict): alpha,beta,cp,cd,n,s,plf
QV = {
    "1": dict(alpha=0.1632, beta=4.5725, cp=0.1602, cd=0.9897, n=1.1941, s=4, plf=0.7379),
    "2": dict(alpha=0.2068, beta=4.1252, cp=0.1248, cd=1.0134, n=1.2158, s=4, plf=0.5650),
    "5": dict(alpha=0.1311, beta=4.6887, cp=0.1692, cd=1.0000, n=1.2102, s=4, plf=0.6803),
}
ALLP = dict(alpha=0.1762, beta=4.4204, cp=0.1482, cd=0.9993, n=1.2035, s=4, plf=0.6552)  # 'all' global avg

link = os.path.join(INTERNAL, "link.csv")
base = os.path.join(INTERNAL, "link.csv.preconic")   # renumbered+sorted base (pre-VDF-staging)
src = base if os.path.exists(base) else link
bak = os.path.join(INTERNAL, "link.csv.preqvdf")
if not os.path.exists(bak):
    shutil.copy2(link, bak)

rows = list(csv.DictReader(open(src, newline="", encoding="utf-8-sig")))
cols = [c for c in rows[0].keys()]
for c in ("vdf_type", "vdf_cp", "vdf_cd", "vdf_n", "vdf_s"):
    if c not in cols:
        # insert before geometry if present
        if "geometry" in cols: cols.insert(cols.index("geometry"), c)
        else: cols.append(c)
from collections import Counter
cnt = Counter()
for r in rows:
    ft = str(r.get("FTYPE", "")).strip().split(".")[0]
    if ft == "0":   # centroid connector -> BPR, uncongested
        r["vdf_type"] = 0; cnt[("0", "BPR")] += 1
        r.setdefault("vdf_cp", 0); r.setdefault("vdf_cd", 1); r.setdefault("vdf_n", 1); r.setdefault("vdf_s", 4)
        continue
    p = QV.get(ft, ALLP)
    r["vdf_type"] = 2
    r["vdf_alpha"] = p["alpha"]; r["vdf_beta"] = p["beta"]
    r["vdf_cp"] = p["cp"]; r["vdf_cd"] = p["cd"]; r["vdf_n"] = p["n"]; r["vdf_s"] = p["s"]
    r["vdf_plf"] = p["plf"]
    cnt[(ft, "QVDF" + ("(cal)" if ft in QV else "(all)"))] += 1
with open(link, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
print("staged QVDF link.csv (vdf_type=2 + calibrated params). FT -> kind counts:")
for kk, n in sorted(cnt.items()): print(f"  FT={kk[0]} {kk[1]}: {n}")
