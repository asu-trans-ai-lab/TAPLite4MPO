#!/usr/bin/env python3
"""ARC benchmark builder/checker.

Reads the authoritative ARC link database (arc-Shape/AMLink2020.dbf) and:
  1. derives the empirical FACTYPE x ATYPE free-flow SPEED and hourly CAPACITY and
     checks them against the guideline tables (Sec 7 Table 7-1 / 7-2);
  2. supplies the ARC modified-BPR A/D/B by FACTYPE (Sec 7.1.2) for the kernel's
     vdf_A / vdf_alpha / vdf_beta;
  3. extracts ARC's own AM assigned volumes (V_SOVAM+V_HOV2AM+V_HOV3AM) as the
     reference-volume benchmark, keyed by (A,B), for assignment validation.

Run from private/ARC_Atlanta/.  Requires pyshp.
"""
import collections, csv, os, statistics, sys
import shapefile

HERE = os.path.dirname(os.path.abspath(__file__))
DBF = os.path.join(HERE, "arc-Shape", "arc-Shape", "AMLink2020")

# --- Guideline tables (from ARC_DTALite_kernel_requirements.md) ---------------
# Table 7-1 free-flow speed (mph) by FACTYPE x ATYPE(1..7)
FFSPEED = {
    0:[7,11,11,11,11,14,14], 1:[62,63,63,63,64,65,66], 2:[43,46,49,52,55,58,61],
    3:[43,46,49,52,55,58,61], 4:[64,65,65,65,66,67,68], 5:[64,65,65,65,66,67,68],
    6:[62,63,63,63,64,65,66], 7:[50,50,50,55,55,55,55], 8:[35]*7, 9:[35]*7,
    10:[23,26,31,35,41,48,53], 11:[21,26,29,33,38,43,48], 12:[21,26,29,33,38,43,48],
    13:[21,26,29,33,38,43,48], 14:[17,23,24,26,30,35,45],
}
# Sec 7.1.2 modified BPR: Tc = T0*(1 + A*(V/C) + D*(V/C)^B); (A, D, B) by FACTYPE
VDF_ADB = {
    1:(0.10,0.60,6.0), 4:(0.10,0.60,6.0), 5:(0.10,0.60,6.0), 6:(0.10,0.60,6.0),
    2:(0.00,1.00,4.0), 3:(0.00,1.25,4.0),
    7:(0.10,1.00,4.0), 8:(0.10,1.00,4.0), 9:(0.10,1.00,4.0),
    10:(0.10,0.45,4.0), 11:(0.10,0.45,4.0), 12:(0.10,0.45,4.0), 13:(0.10,0.45,4.0),
    14:(0.10,0.45,4.0), 0:(0.0,0.0,1.0),   # connector: ~uncongested
}
WEAVE_ADB = (0.20, 1.25, 5.5)
AM_PERIOD_FACTOR = 3.66   # Sec 1.7: period cap = hourly cap * factor (AM)
FT_NAME = {0:"connector",1:"interstate",2:"expressway",3:"parkway",4:"fwyHOVbuf",
           5:"fwyHOVbar",6:"fwytruck",7:"sysramp",8:"exitramp",9:"entramp",
           10:"princart",11:"minorart",12:"artHOV",13:"arttruck",14:"collector"}


def num(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def main():
    r = shapefile.Reader(DBF)
    fields = [f[0] for f in r.fields[1:]]
    fi = {f: i for i, f in enumerate(fields)}
    def g(rec, name): return rec[fi[name]] if name in fi else None

    n = 0
    spd = collections.defaultdict(list)        # (ft,at) -> [SPEED]
    capph = collections.defaultdict(list)      # (ft,at) -> [hourly per-lane cap]
    ref_rows = []
    ft_counts = collections.Counter()
    for rec in r.iterRecords():
        ft = int(num(g(rec, "FACTYPE")) or -1)
        if ft < 0 or ft >= 50:                 # exclude transit (50-99)
            continue
        n += 1
        at = int(num(g(rec, "ATYPE")) or 0)
        ft_counts[ft] += 1
        s = num(g(rec, "SPEED"))
        if s and 1 <= at <= 7 and ft != 0:
            spd[(ft, at)].append(s)
        lanes_am = num(g(rec, "LANESAM")) or num(g(rec, "LANES")) or 0
        amcap = num(g(rec, "AMCAPACITY")) or 0
        # FINDING: AMCAPACITY/lanes ~= Table 7-2 hourly LOS-E (e.g. interstate ~1900),
        # so AMCAPACITY is the HOURLY directional capacity, NOT period (the spec note
        # that "AMCAPACITY = period cap" is wrong). Period cap = AMCAPACITY * 3.66.
        if ft != 0 and lanes_am > 0 and 0 < amcap < 90000 and 1 <= at <= 7:
            capph[(ft, at)].append(amcap / lanes_am)
        a, b = g(rec, "A"), g(rec, "B")
        auto = sum(num(g(rec, c)) or 0 for c in ("V_SOVAM", "V_HOV2AM", "V_HOV3AM"))
        ref_rows.append({"from_node_id": int(a), "to_node_id": int(b), "factype": ft,
                         "atype": at, "ref_auto_vol": round(auto, 1),
                         "ref_total_vol": round(num(g(rec, "V_TOTAM")) or 0, 1),
                         "weaveflag": int(num(g(rec, "WEAVEFLAG")) or 0)})

    print(f"ARC auto links (FACTYPE 0-14): {n:,}")
    print(f"FACTYPE counts: {dict(sorted(ft_counts.items()))}\n")

    # 1. SPEED check vs Table 7-1
    print("== free-flow SPEED: data median vs Table 7-1 (FACTYPE x ATYPE) ==")
    sp_ok = sp_tot = 0
    for ft in range(1, 15):
        cells = []
        for at in range(1, 8):
            obs = spd.get((ft, at))
            if obs:
                m = statistics.median(obs); ref = FFSPEED[ft][at-1]
                cells.append(f"{m:.0f}/{ref}")
                sp_tot += 1; sp_ok += (abs(m-ref) <= 2)
            else:
                cells.append("  -")
        print(f"  FT{ft:2} {FT_NAME[ft]:10} " + " ".join(f"{c:>7}" for c in cells))
    print(f"  -> within 2 mph of Table 7-1: {sp_ok}/{sp_tot}\n")

    # 2. CAPACITY check: AMCAPACITY/lanes (= hourly per-lane) vs Table 7-2 range
    CAP72 = {1:(1900,2100),2:(1200,1450),3:(1150,1400),4:(1900,2100),5:(1900,2100),
             6:(1900,2100),7:(1300,1700),8:(800,900),9:(900,1100),10:(1000,1300),
             11:(900,1100),12:(1000,1300),13:(900,1100),14:(750,900)}
    print("== hourly per-lane CAPACITY: AMCAP/lanes (data) vs Table 7-2 range ==")
    cap_ok = cap_tot = 0
    for ft in range(1, 15):
        vals = [statistics.median(capph[(ft, at)]) for at in range(1, 8) if capph.get((ft, at))]
        if vals:
            lo, hi = CAP72[ft]; dlo, dhi = min(vals), max(vals)
            ok = (lo*0.9 <= dlo) and (dhi <= hi*1.1)
            cap_tot += 1; cap_ok += ok
            print(f"  FT{ft:2} {FT_NAME[ft]:10} data {dlo:.0f}..{dhi:.0f}  | Table7-2 {lo}..{hi}  {'OK' if ok else 'CHECK'}")
    print(f"  -> AMCAPACITY/lanes matches Table 7-2 hourly: {cap_ok}/{cap_tot}  "
          f"(confirms AMCAPACITY is HOURLY directional; period cap = x{AM_PERIOD_FACTOR})\n")

    # 3. VDF table for the kernel
    print("== ARC modified-BPR A/D/B -> kernel vdf_A / vdf_alpha / vdf_beta (by FACTYPE) ==")
    for ft in range(0, 15):
        A, D, B = VDF_ADB[ft]
        print(f"  FT{ft:2} {FT_NAME[ft]:10} vdf_A={A:>4}  vdf_alpha={D:>4}  vdf_beta={B:>3}")
    print(f"  (weave: A/D/B = {WEAVE_ADB}; current GMNS uses FLAT 0.15/4 -> needs this table)\n")

    # 4. write the reference-volume benchmark
    out = os.path.join(HERE, "arc_am_ref_volume.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["from_node_id","to_node_id","factype","atype",
                                          "ref_auto_vol","ref_total_vol","weaveflag"])
        w.writeheader(); w.writerows(ref_rows)
    tot = sum(x["ref_auto_vol"] for x in ref_rows)
    print(f"reference benchmark written: {out}")
    print(f"  {len(ref_rows):,} links; total ARC AM auto volume (sov+hov2+hov3) = {tot:,.0f}")


if __name__ == "__main__":
    main()
