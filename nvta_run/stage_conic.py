"""
Stage the NVTA _internal/link.csv for CONIC VDF (Gate 4): add vdf_type/conic_a/
conic_b columns by FTYPE (Feng Liu 2024-03-21 per-FT conic table). Centroid
connectors (FT0) stay BPR (vdf_type=0). Backs up link.csv -> link.csv.preconic.

Spiess conic: t = t0*(2 + sqrt(a^2(1-x)^2 + b^2) - a(1-x) - b),  b=(2a-1)/(2a-2).
"""
import csv, os, shutil

from data_root import internal
INTERNAL = internal()
# FTYPE -> conic a  (Feng Liu canonical NVTA table)
FT_A = {"1": 15.0, "2": 7.0, "3": 5.5, "4": 3.0, "5": 8.0, "6": 15.0}
def conic_b(a): return (2*a-1)/(2*a-2)

link = os.path.join(INTERNAL, "link.csv")
bak = os.path.join(INTERNAL, "link.csv.preconic")
src = bak if os.path.exists(bak) else link
if not os.path.exists(bak):
    shutil.copy2(link, bak)   # preserve the BPR/original link.csv

rows = list(csv.DictReader(open(src, newline="", encoding="utf-8-sig")))
base = list(rows[0].keys())
for c in ("vdf_type", "conic_a", "conic_b"):
    if c in base: base.remove(c)
# insert conic cols right after vdf_plf if present else append before geometry
fn = [c for c in base if c != "geometry"] + ["vdf_type", "conic_a", "conic_b"] + (["geometry"] if "geometry" in base else [])
from collections import Counter
cnt = Counter()
w = csv.DictWriter(open(link, "w", newline=""), fieldnames=fn); w.writeheader()
for r in rows:
    ft = str(r.get("FTYPE", "")).strip().split(".")[0]
    if ft in FT_A:
        a = FT_A[ft]; r["vdf_type"] = 1; r["conic_a"] = a; r["conic_b"] = round(conic_b(a), 6)
    else:  # FT0 centroid connector (or unknown) -> keep BPR
        r["vdf_type"] = 0; r["conic_a"] = 0; r["conic_b"] = 0
    cnt[(ft, r["vdf_type"])] += 1
    w.writerow(r)
print("staged conic link.csv (backup link.csv.preconic). FT -> (vdf_type) counts:")
for (ft, vt), n in sorted(cnt.items()):
    aval = FT_A.get(ft, "BPR")
    print(f"  FT={ft or '(none)'}: vdf_type={vt} a={aval}  links={n}")
