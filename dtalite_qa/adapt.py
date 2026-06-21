"""Adapt an older / foreign GMNS scenario to the current kernel's column format.

Older TAPLite networks (e.g. the MAG regional model) use different column NAMES
(`VDF_alpha`, `allowed_uses`) and UNITS (`free_speed` in mph, `length` in miles)
than the current kernel reads (`vdf_alpha`, `allowed_use`; `free_speed` km/h or
`vdf_free_speed_mph`; `length` meters or `vdf_length_mi`). This writes a
current-format copy and a checklist of what it changed, so a foreign dataset can
be run without hand-editing 60 MB CSVs.

The column matcher is case-insensitive (so `VDF_alpha` -> `vdf_alpha` for free),
plus an explicit alias table. Unit handling is explicit (--free-speed / --length)
because mph-vs-kmh and mi-vs-m cannot be auto-detected reliably.
"""
import os
import shutil

from . import csvio
from . import mag_vdf

# lowercased source column -> canonical kernel column
ALIASES = {
    "allowed_uses": "allowed_use",
    "vdf_free_speed": "vdf_free_speed_mph",
    "vdf_cutoff_speed": "cutoff_speed",
    # reference columns preserved for validation/comparison against the kernel's
    # assigned results (ref_volume vs assigned volume, ref_time vs travel_time).
    "ref_cost": "ref_time",
}

# capacity defaults (veh/h/lane) used to repair lanes==0 / capacity==0 links,
# keyed by facility_type token; fallback applies otherwise.
FACILITY_CAP = {"motorway": 2000, "trunk": 1900, "primary": 1500,
                "secondary": 1200, "tertiary": 1000}
FALLBACK_CAP = 1000


def _canon(col):
    low = col.strip().lower()
    return ALIASES.get(low, low)


def adapt_links(scenario, out_dir, free_speed_unit="mph", length_unit="mi", report=None,
                mag_vdf_2015=False):
    header, rows = csvio.read(csvio.path(scenario, "link.csv"))
    # rename headers to canonical (case-insensitive + aliases); keep order, drop dup
    new_header, seen = [], set()
    rename = {}
    for c in header:
        cc = _canon(c)
        rename[c] = cc
        if cc not in seen:
            new_header.append(cc)
            seen.add(cc)
    # ensure derived unit columns exist
    for c in ("vdf_free_speed_mph", "vdf_length_mi"):
        if c not in new_header:
            new_header.append(c)
    if mag_vdf_2015:
        for c in ("vdf_alpha", "vdf_beta"):
            if c not in new_header:
                new_header.append(c)

    renamed = {src: dst for src, dst in rename.items() if src != dst}
    if renamed and report is not None:
        report.append(f"renamed columns: {renamed}")

    fixed_lc = 0
    out_rows = []
    for r in rows:
        nr = {}
        for src, val in r.items():
            nr[rename[src]] = val
        # units -> explicit mph / mi columns the kernel reads unambiguously
        if free_speed_unit == "mph" and not str(nr.get("vdf_free_speed_mph", "")).strip():
            nr["vdf_free_speed_mph"] = nr.get("free_speed", "")
        if length_unit == "mi" and not str(nr.get("vdf_length_mi", "")).strip():
            nr["vdf_length_mi"] = nr.get("length", "")
        # repair lanes==0 / capacity==0 (current kernel skips those -> disconnects)
        lanes = csvio.fnum(nr.get("lanes"))
        cap = csvio.fnum(nr.get("capacity"))
        if lanes <= 0 or cap <= 0:
            fixed_lc += 1
            if lanes <= 0:
                nr["lanes"] = 1
            if cap <= 0:
                ft = (nr.get("facility_type") or "").strip().lower()
                nr["capacity"] = FACILITY_CAP.get(ft, FALLBACK_CAP)
        out_rows.append(nr)

    # overwrite VDF alpha/beta/FFS with the calibrated MAG New-2015 values by vdf_code
    if mag_vdf_2015:
        n = mag_vdf.apply_to_rows(out_rows, set_free_speed=True)
        if report is not None:
            report.append(f"applied MAG New-2015 VDF (alpha/beta/free_speed) to {n} links by vdf_code")

    # sort ascending by from_node_id (CSR requirement)
    out_rows.sort(key=lambda r: (csvio.inum(r.get("from_node_id")), csvio.inum(r.get("to_node_id"))))
    csvio.write(csvio.path(out_dir, "link.csv"), new_header, out_rows)
    if report is not None:
        if free_speed_unit == "mph":
            report.append("added vdf_free_speed_mph = free_speed (free_speed is mph)")
        if length_unit == "mi":
            report.append("added vdf_length_mi = length (length is miles)")
        if fixed_lc:
            report.append(f"repaired {fixed_lc} links with lanes==0 or capacity==0 "
                          f"(set lanes>=1, capacity by facility_type)")
        report.append("sorted link.csv ascending by from_node_id")


def _node_zones(scenario):
    _, nodes = csvio.read(csvio.path(scenario, "node.csv"))
    z = set()
    for r in nodes:
        zz = r.get("zone_id")
        if csvio.is_num(zz) and csvio.inum(zz) > 0:
            z.add(csvio.inum(zz))
    return z


def _demand_targets(scenario):
    mt = csvio.path(scenario, "mode_type.csv")
    targets = []
    if os.path.exists(mt):
        _, rows = csvio.read(mt)
        targets = [(r.get("demand_file") or "").strip() for r in rows if r.get("demand_file")]
    if not targets and os.path.exists(csvio.path(scenario, "demand.csv")):
        targets = ["demand.csv"]
    return targets


def filter_demand(scenario, out_dir, report=None):
    """Drop OD pairs whose o/d zone is not present in node.csv (those pairs are
    unrouteable -> the kernel can't assign them). Returns total dropped."""
    zones = _node_zones(scenario)
    total_drop = 0
    for df in _demand_targets(scenario):
        src = csvio.path(scenario, df)
        if not os.path.exists(src):
            continue
        header, rows = csvio.read(src)
        keep, drop, dropvol = [], 0, 0.0
        for r in rows:
            o, d = csvio.inum(r.get("o_zone_id")), csvio.inum(r.get("d_zone_id"))
            if o in zones and d in zones:
                keep.append(r)
            else:
                drop += 1
                dropvol += csvio.fnum(r.get("volume"))
        csvio.write(csvio.path(out_dir, df), header, keep)
        total_drop += drop
        if drop and report is not None:
            report.append(f"{df}: dropped {drop:,} OD pairs ({dropvol:,.0f} vol) "
                          f"referencing zones absent from node.csv")
    return total_drop


def adapt(scenario, out_dir, free_speed_unit="mph", length_unit="mi", do_filter_demand=True,
          mag_vdf_2015=False):
    """Write a current-format copy of `scenario` into `out_dir`. Returns a report list."""
    os.makedirs(out_dir, exist_ok=True)
    report = []
    adapt_links(scenario, out_dir, free_speed_unit, length_unit, report, mag_vdf_2015=mag_vdf_2015)
    demand_files = set(_demand_targets(scenario)) if do_filter_demand else set()
    if do_filter_demand:
        filter_demand(scenario, out_dir, report)
    # pass remaining files (node / mode_type / settings / unfiltered) through
    for name in os.listdir(scenario):
        if name == "link.csv" or name in demand_files or not name.endswith(".csv"):
            continue
        src = csvio.path(scenario, name)
        if os.path.isfile(src):
            shutil.copy(src, csvio.path(out_dir, name))
    return report
