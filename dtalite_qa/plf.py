"""Peak Load Factor (PLF) inventory + check.

In a static period assignment the kernel converts period demand to peak-hour
(queued) demand via  D = V_period / (L * PLF)  (L = period hours). PLF=1 means
"perfectly flat" demand across the whole period, which UNDER-states peak-hour
congestion -- the classic error. The correct PLF comes from the MPO's hourly->
period capacity **expansion factor** phi:  PLF = phi / L.

This step inventories VDF_plf in a network and FLAGS a flat (all-1) PLF on a
multi-hour period, with the recommended PLF per facility type when an expansion-
factor profile is supplied. A built-in MAG PM profile (from the "Capacity from
Hourly to Period" table) is included as an example.

BOUNDS (ADOT Load-Factor memo, ADOT VDF calibration project, 2022 -- the canonical reference):
  * hard:      0 < PLF <= 1     (memo Sec 5: "LF between 0 and 1; 1 = flat").
  * physical:  phi = L*PLF >= 1 (a multi-hour period cannot carry LESS capacity
               than a single hour)  =>  PLF >= 1/L.
  * advisory:  PLF >= 0.25       (Lan-Abia LF = 0.25 + alpha*(V/C)^beta floor).
`bound_plf()` enforces these; `check()` flags any link/value that violates them.

Reference: docs/peak_load_factor.md  (derivation: phi = L*PLF, D = V/(L*PLF)).
"""
from . import csvio

# --- PLF bounds (ADOT Load-Factor memo) -------------------------------------
PLF_HARD_MAX = 1.0           # memo: LF in (0, 1]; 1 == perfectly flat demand
PLF_ADVISORY_FLOOR = 0.25    # Lan-Abia LF = 0.25 + alpha*(V/C)^beta (memo App.1)

# Back-calculated MAG load factor by VDF_TYPE class and period (memo Sec 6 table,
# "serve as internal references only"). Most VDF types follow `default`; the
# major-arterial (x06) class is more peaked in the daytime.
MEMO_LOAD_FACTOR = {
    "default":        {"AM": 0.94, "MD": 0.96, "PM": 0.98, "NT": 0.40},
    "major_arterial": {"AM": 0.83, "MD": 0.93, "PM": 0.91, "NT": 0.39},
}


def phi_of(plf, L):
    """Hour->period capacity expansion factor phi = L * PLF (memo Eq.13)."""
    return float(plf) * float(L)


def bound_plf(plf, L=None):
    """Clamp a PLF to the memo bounds. Returns (plf_bounded, note_or_None).

    Enforces 0 < PLF <= 1 and (when L given) phi = L*PLF >= 1 (PLF >= 1/L).
    Flags (does not hard-clamp) values below the 0.25 advisory floor."""
    if plf is None:
        return 1.0, None
    p = float(plf)
    notes = []
    if p <= 0:
        return PLF_ADVISORY_FLOOR, f"PLF {p} <= 0 invalid -> floor {PLF_ADVISORY_FLOOR}"
    if p > PLF_HARD_MAX:
        notes.append(f"PLF {p} > 1 (memo: LF in (0,1]) -> clamped to 1.0")
        p = PLF_HARD_MAX
    if L and L > 0 and p < 1.0 / L:
        notes.append(f"PLF {p} -> phi=L*PLF<1 (period cap < hourly) -> raised to 1/L={1.0/L:.3f}")
        p = 1.0 / L
    if p < PLF_ADVISORY_FLOOR:
        notes.append(f"PLF {p} below advisory floor {PLF_ADVISORY_FLOOR}")
    return p, ("; ".join(notes) if notes else None)


# MAG hourly->period expansion factors phi by facility_type code, per period.
# (from the MAG "Capacity from Hourly to Period" table). PLF = phi / period_hours.
MAG_PHI = {
    # period: {facility_type: phi}
    "AM": {1: 2.83, 2: 2.48, 3: 2.48, 4: 2.48, 6: 2.48, 7: 2.83, 8: 2.83, 9: 2.83, 0: 2.83, 10: 2.48, 11: 2.48},
    "MD": {1: 4.79, 2: 4.64, 3: 4.64, 4: 4.64, 6: 4.64, 7: 4.79, 8: 4.79, 9: 4.79, 0: 4.79, 10: 4.64, 11: 4.64},
    "PM": {1: 3.90, 2: 3.63, 3: 3.63, 4: 3.63, 6: 3.63, 7: 3.90, 8: 3.90, 9: 3.90, 0: 3.90, 10: 3.63, 11: 3.63},
    "NT": {1: 4.80, 2: 4.68, 3: 4.68, 4: 4.68, 6: 4.68, 7: 4.80, 8: 4.80, 9: 4.80, 0: 4.80, 10: 4.68, 11: 4.68},
}
PERIOD_HOURS = {"AM": 3.0, "MD": 5.0, "PM": 4.0, "NT": 12.0}

# ARC Atlanta: hour->period capacity expansion factor phi (req Sec 1.7) is uniform
# across facility types; period windows from Sec 4.2. PLF = phi / L. AMCAPACITY is
# HOURLY (confirmed by arc_benchmark.py vs Table 7-2), so feed the kernel:
#   capacity = AMCAPACITY/lanes,  vdf_plf = phi/L,  demand_period = the window.
ARC_PHI = {"EA": 1.25, "AM": 3.66, "MD": 4.70, "PM": 3.66, "EV": 3.91}
ARC_PERIOD_HOURS = {"EA": 3.0, "AM": 4.0, "MD": 5.0, "PM": 4.0, "EV": 8.0}


def arc_plf(period):
    """ARC peak load factor PLF = phi / L for a period (EA/AM/MD/PM/EV)."""
    p = period.upper()
    return ARC_PHI[p] / ARC_PERIOD_HOURS[p]


def _settings_period_hours(scenario):
    p = csvio.path(scenario, "settings.csv")
    if not csvio.exists(scenario, "settings.csv"):
        return None
    _, rows = csvio.read(p)
    if not rows:
        return None
    s = rows[0]
    h0, h1 = csvio.fnum(s.get("demand_period_starting_hours")), csvio.fnum(s.get("demand_period_ending_hours"))
    return (h1 - h0) if h1 > h0 else None


def check(scenario, period_hours=None, phi_profile=None):
    """Inventory VDF_plf and flag a flat PLF. phi_profile: {facility_type:int -> phi}."""
    import collections
    _, links = csvio.read(csvio.path(scenario, "link.csv"))
    H = period_hours or _settings_period_hours(scenario) or 1.0

    plf_vals = collections.Counter()
    by_ft = collections.defaultdict(list)
    for r in links:
        p = csvio.fnum(r.get("vdf_plf", r.get("VDF_plf")), 1.0)
        plf_vals[round(p, 4)] += 1
        ft = csvio.inum(r.get("facility_type"), -1)
        by_ft[ft].append(p)

    distinct = list(plf_vals)
    flat = (len(distinct) == 1 and abs(distinct[0] - 1.0) < 1e-6)
    warnings, recs = [], []

    # --- bounds enforcement (memo): 0 < PLF <= 1 and phi = L*PLF >= 1 ---------
    n_gt1 = sum(c for p, c in plf_vals.items() if p > PLF_HARD_MAX + 1e-9)
    n_le0 = sum(c for p, c in plf_vals.items() if p <= 0)
    n_subphi = sum(c for p, c in plf_vals.items() if H > 1.0 and 0 < p < 1.0 / H - 1e-9)
    n_floor = sum(c for p, c in plf_vals.items() if 0 < p < PLF_ADVISORY_FLOOR)
    if n_gt1:
        warnings.append(f"{n_gt1} link(s) have PLF > 1 -- violates the memo bound LF in (0,1] "
                        f"(1 = flat). Clamp to 1.0.")
    if n_le0:
        warnings.append(f"{n_le0} link(s) have PLF <= 0 -- invalid; assignment D=V/(L*PLF) diverges.")
    if n_subphi:
        warnings.append(f"{n_subphi} link(s) have PLF < 1/L = {1.0/H:.3f} -> phi=L*PLF < 1 "
                        f"(period capacity below hourly capacity), non-physical. Raise to >= 1/L.")
    if n_floor:
        warnings.append(f"{n_floor} link(s) have PLF < {PLF_ADVISORY_FLOOR} advisory floor "
                        f"(more peaked than Lan-Abia LF=0.25+a*(V/C)^b); verify.")
    pvals = [p for p in plf_vals if p > 0]
    bounds = {"min": min(pvals) if pvals else None, "max": max(pvals) if pvals else None,
              "phi_min": (min(pvals) * H) if pvals else None, "one_over_L": round(1.0 / H, 4),
              "n_gt1": n_gt1, "n_le0": n_le0, "n_subphi": n_subphi, "n_below_floor": n_floor}

    if H > 1.0 and flat:
        warnings.append(
            f"VDF_plf is flat (=1) on a {H:.0f}-hour period: this assumes uniform demand "
            f"across the whole period and UNDER-states peak-hour congestion. "
            f"Set PLF = phi/L from the hourly->period expansion factors by facility type.")
    elif H > 1.0 and len(distinct) == 1:
        warnings.append(f"VDF_plf is constant ({distinct[0]}) across all links on a {H:.0f}-hour period; "
                        f"verify it reflects facility-specific peaking.")

    if phi_profile:
        for ft in sorted(by_ft):
            phi = phi_profile.get(ft)
            if phi:
                cur = sum(by_ft[ft]) / len(by_ft[ft])
                recs.append({"facility_type": ft, "n": len(by_ft[ft]),
                             "current_plf": round(cur, 3), "phi": phi,
                             "recommended_plf": round(phi / H, 3)})
    return {"period_hours": H, "plf_distribution": dict(plf_vals), "flat": flat,
            "warnings": warnings, "recommendations": recs, "bounds": bounds}


def apply(scenario, out_dir, phi_profile, period_hours, default_plf=1.0):
    """Write a copy of the scenario with VDF_plf set to phi/period_hours by
    facility_type (links whose FT is not in the profile keep default_plf)."""
    import os, shutil
    os.makedirs(out_dir, exist_ok=True)
    header, rows = csvio.read(csvio.path(scenario, "link.csv"))
    col = "vdf_plf" if "vdf_plf" in header else ("VDF_plf" if "VDF_plf" in header else "vdf_plf")
    if col not in header:
        header.append(col)
    n = 0
    for r in rows:
        ft = csvio.inum(r.get("facility_type"), -1)
        phi = phi_profile.get(ft)
        if phi:
            bounded, _ = bound_plf(phi / period_hours, period_hours)
            r[col] = round(bounded, 4)
            n += 1
        elif not str(r.get(col, "")).strip():
            r[col] = default_plf
    csvio.write(csvio.path(out_dir, "link.csv"), header, rows)
    for name in os.listdir(scenario):
        if name == "link.csv" or not name.endswith(".csv"):
            continue
        src = csvio.path(scenario, name)
        if os.path.isfile(src):
            shutil.copy(src, csvio.path(out_dir, name))
    return n


def render(rep):
    L = [f"PLF inventory (period = {rep['period_hours']:.0f} h)",
         f"  VDF_plf distribution: {rep['plf_distribution']}"]
    b = rep.get("bounds")
    if b and b.get("min") is not None:
        L.append(f"  bounds: PLF in [{b['min']}, {b['max']}] (memo: (0,1]); "
                 f"phi=L*PLF >= 1 needs PLF >= 1/L = {b['one_over_L']}; "
                 f"min phi observed = {b['phi_min']:.2f}")
    for w in rep["warnings"]:
        L.append(f"  WARN: {w}")
    if rep["recommendations"]:
        L.append("  recommended PLF = phi / period_hours, by facility_type:")
        L.append(f"    {'FT':>4} {'n':>7} {'current':>8} {'phi':>6} {'recommended':>12}")
        for r in rep["recommendations"]:
            L.append(f"    {r['facility_type']:>4} {r['n']:>7} {r['current_plf']:>8} "
                     f"{r['phi']:>6} {r['recommended_plf']:>12}")
    if not rep["warnings"]:
        L.append("  OK: PLF varies / is not flat")
    return "\n".join(L)
