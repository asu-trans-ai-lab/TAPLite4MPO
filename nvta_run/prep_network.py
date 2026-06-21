"""
PREPROCESSING (run ONCE, before any assignment gate: BPR / conic / QVDF).

Takes the renumbered, link-sorted GMNS _internal/link.csv and bakes in the
network attributes that are independent of the VDF form, so every gate runs on
the SAME corrected network:

  1. Conic params per functional type (Feng Liu table): conic_a, conic_b,
     and vdf_type=1 for FT1..6 (FT0 centroid connectors stay BPR vdf_type=0).
  2. Per-link PM Peak Load Factor, back-extracted from CUBE:
       vdf_plf = I4PMVOL / (L * IPMHRLKCAP * I4PMVC),  L=4h (PM 15-19),
     default 0.8503 (documented PM PLF) where columns are missing/zero;
     outliers (<0.3 or >1.5) clamped to the default.
  3. Period capacity: already correct (capacity col == IPMHRLNCAP = PM hourly
     per-lane; kernel uses lanes*capacity*L*plf as effective period capacity).

The per-gate runner only flips vdf_type (0=BPR, 1=conic) or swaps to QVDF params;
PLF + capacity are fixed here so BPR and conic are compared on equal footing.

Output: rewrites _internal/link.csv (backup link.csv.prePrep on first run).
"""
import csv, os, shutil

from data_root import internal
INTERNAL = internal()
FT_A = {"1": 15.0, "2": 7.0, "3": 5.5, "4": 3.0, "5": 8.0, "6": 15.0}   # Feng Liu conic a per FT
def conic_b(a): return (2*a - 1) / (2*a - 2)
L = 4.0            # PM period hours (15-19)
PM_PLF = 0.8503    # documented PM peak load factor (back-extraction default)

link = os.path.join(INTERNAL, "link.csv")
bak = os.path.join(INTERNAL, "link.csv.prePrep")
src = bak if os.path.exists(bak) else link
if not os.path.exists(bak):
    shutil.copy2(link, bak)

rows = list(csv.DictReader(open(src, newline="", encoding="utf-8-sig")))
base = [c for c in rows[0].keys() if c not in ("vdf_type", "conic_a", "conic_b")]
fn = [c for c in base if c != "geometry"] + ["vdf_type", "conic_a", "conic_b"] + (["geometry"] if "geometry" in base else [])
n_conic = n_plf_bx = 0
for r in rows:
    # (1) conic params by FT
    ft = str(r.get("FTYPE", "")).strip().split(".")[0]
    if ft in FT_A:
        a = FT_A[ft]; r["vdf_type"] = 1; r["conic_a"] = a; r["conic_b"] = round(conic_b(a), 6); n_conic += 1
    else:
        r["vdf_type"] = 0; r["conic_a"] = 0; r["conic_b"] = 0
    # (2) per-link PM PLF back-extracted from CUBE
    vol = float(r.get("I4PMVOL", 0) or 0); cap = float(r.get("IPMHRLKCAP", 0) or 0); vc = float(r.get("I4PMVC", 0) or 0)
    if vol > 0 and cap > 0 and vc > 0:
        plf = vol / (L * cap * vc)
        if 0.3 <= plf <= 1.5: n_plf_bx += 1
        else: plf = PM_PLF
    else:
        plf = PM_PLF
    r["vdf_plf"] = round(plf, 6)

with open(link, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fn); w.writeheader(); w.writerows(rows)
print(f"[prep] {len(rows)} links: conic on {n_conic} (FT1-6), per-link PLF back-extracted on {n_plf_bx} "
      f"(rest default {PM_PLF}). Backup: link.csv.prePrep")
print("[prep] network ready for ALL gates (BPR vdf_type=0 / conic vdf_type=1 / QVDF). PLF + capacity fixed.")
