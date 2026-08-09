"""External Python oracle — PR-2 (CR-0007). Cross-language independence.

Reimplements every VDF form from the specification in Python (no shared code
with either C++ implementation), reads the YAML case spec directly (NOT the
compiled .inc — so a case-compiler bug shows up as a three-way disagreement),
and compares against the values dumped by twin_differential.

Run:
  kernel/build/twin_differential vdf_values.csv     # dumps production+twin
  python external_reference/python/vdf_reference.py vdf_values.csv
"""
import csv
import math
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
YML = os.path.join(HERE, "..", "..", "test_cases", "analytical",
                   "vdf_grid.yml")

LAB = dict(lanes=1.0, H=1.0, plf=1.0, C=1000.0, t0=10.0,
           L=5.0, free=60.0, cutoff=45.0)


def voc(x):
    return x            # lab construction: incoming == x*C, voc == x


def ref_tt(c, x):
    a = c.get("alpha", 0.15)
    b = c.get("beta", 4.0)
    t0, L = LAB["t0"], LAB["L"]
    k = c["kernel_id"]
    if k == 1:
        ca = c.get("conic_a", 0.0)
        cb = c.get("conic_b", 0.0) or (2 * ca - 1) / (2 * ca - 2)
        om = 1.0 - x
        t = t0 * (2 + math.sqrt(ca * ca * om * om + cb * cb) - ca * om - cb)
    elif k == 2:
        doc = x
        cong = (1 - doc) * LAB["free"] + doc * LAB["cutoff"] if doc < 1 \
            else LAB["cutoff"]
        qs = cong / (1 + a * doc ** b)
        P = c.get("q_cd", 1.0) * doc ** c.get("q_n", 1.24)
        H = LAB["H"]
        ps = qs if P > H else (P / H) * qs + (1 - P / H) * (cong + LAB["free"]) / 2
        t = L / max(0.1, ps) * 60.0
    elif k == 3:
        e = b if x <= 1 else 2 * b
        t = t0 * (1 + a * x ** e)
    elif k == 4:
        t = (t0 * (1.1 - a * x) / max(0.05, 1.1 - x)) if x <= 1 \
            else t0 * ((1.1 - a) / 0.1) * x * x
    elif k == 5:
        z = x - 1
        t = t0 + a * (z + math.sqrt(z * z + b * x))
    elif k == 6:
        bpr = t0 * (1 + a * x ** b)
        g = min(0.95, max(0.05, c.get("green_ratio", 0.45)))
        C = max(0.0, c.get("cycle_length_s", 90.0))
        t = bpr + 0.5 * C * (1 - g) ** 2 / max(0.05, 1 - min(1.0, x) * g) / 60.0
    elif k == 7:
        e = 4.0 if x <= 1 else b
        t = t0 * (1 + a * x ** e)
    elif k == 8:
        plph = x * LAB["C"]
        t = t0 + (plph / 120.0) * 5.0 * (1 + x) ** 8
        # bracket is hours; convert then to minutes:
        t = t0 + ((plph / 120.0) * 5.0 * (1 + x) ** 8 / 60.0) * 60.0
    else:
        t = t0 * (1 + c.get("mbpr_A", 0.0) * x + a * x ** b)
    t += c.get("added_delay_per_mile", 0.0) * L
    return max(0.0, t)


def main():
    dump = sys.argv[1] if len(sys.argv) > 1 else "vdf_values.csv"
    spec = yaml.safe_load(open(YML))
    cases = {c["id"]: c for c in spec["cases"]}
    rel = float(spec["tolerances"]["rel"])
    n_ok = n_bad = 0
    bad = []
    for r in csv.DictReader(open(dump)):
        c = cases[r["case_id"]]
        x = float(r["x"])
        t_ref = ref_tt(c, x)
        for which in ("production_tt", "twin_tt"):
            t_c = float(r[which])
            if abs(t_c - t_ref) <= rel * (1 + abs(t_ref)) + 1e-9:
                n_ok += 1
            else:
                n_bad += 1
                bad.append(f"{r['case_id']} @x={x} {which}={t_c} "
                           f"python={t_ref}")
    print(f"external oracle: {n_ok} agreements, {n_bad} disagreements")
    for b in bad[:15]:
        print("  DISAGREE:", b)
    print("OVERALL:", "PASS" if n_bad == 0 else "BLOCKED")
    sys.exit(0 if n_bad == 0 else 1)


if __name__ == "__main__":
    main()
