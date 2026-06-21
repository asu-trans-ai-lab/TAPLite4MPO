"""
Gate 5: set per-link PM Peak Load Factor on the (conic-staged) regional
_internal/link.csv, back-extracted from CUBE:
    PLF = I4PMVOL / (L * IPMHRLKCAP * I4PMVC),  L = 4h (PM 15-19),
default 0.8503 (documented PM PLF) where columns are missing/zero.
The kernel uses vdf_plf as: IncomingDemand = Volume/lanes/L/vdf_plf -> DOC.
Backs up link.csv -> link.csv.preplf.
"""
import csv, os, shutil

from data_root import internal
INTERNAL = internal()
L = 4.0
PM_PLF_DEFAULT = 0.8503
link = os.path.join(INTERNAL, "link.csv")
bak = os.path.join(INTERNAL, "link.csv.preplf")
if not os.path.exists(bak):
    shutil.copy2(link, bak)

rows = list(csv.DictReader(open(bak, newline="", encoding="utf-8-sig")))
fn = list(rows[0].keys())
n_bx = 0
for r in rows:
    vol = float(r.get("I4PMVOL", 0) or 0); cap = float(r.get("IPMHRLKCAP", 0) or 0); vc = float(r.get("I4PMVC", 0) or 0)
    if vol > 0 and cap > 0 and vc > 0:
        plf = vol / (L * cap * vc)
        if plf < 0.3 or plf > 1.5:   # clamp outliers to the period default
            plf = PM_PLF_DEFAULT
        else:
            n_bx += 1
    else:
        plf = PM_PLF_DEFAULT
    r["vdf_plf"] = round(plf, 6)

with open(link, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fn); w.writeheader(); w.writerows(rows)
print(f"set per-link PM PLF on {len(rows)} links ({n_bx} back-extracted, rest default {PM_PLF_DEFAULT}); backup link.csv.preplf")
