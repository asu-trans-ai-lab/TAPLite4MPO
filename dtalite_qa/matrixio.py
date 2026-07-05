"""Matrix interchange (WP-03): agency OD matrices <-> kernel long-form demand.

Import: wide/square CSV (zone ids in header+first column, TransCAD/Cube export style),
long CSV (o,d,value), and OMX (optional dependency, guarded). Every import runs the
COVERAGE CHECKS from the conversion-error catalog section 4c:
  - Excel truncation fingerprint (exactly 1,048,575 data rows)
  - origin coverage vs the zone list (a sorted export cut mid-file loses the tail)
Export: long-form demand or a skim back to wide CSV / OMX.

Stdlib + csv only for the CSV paths; `openmatrix` (or h5py) only if OMX is used.
"""
import csv
import os
import sys

EXCEL_ROW_LIMIT = 1_048_575


class MatrixReport(dict):
    @property
    def ok(self):
        return not self.get("errors")


def _check(report, zones, origins, dests, n_rows):
    report["rows"] = n_rows
    report["origins"] = len(origins)
    report["destinations"] = len(dests)
    report["errors"] = []
    report["warnings"] = []
    if n_rows in (EXCEL_ROW_LIMIT, EXCEL_ROW_LIMIT + 1):
        report["errors"].append(
            f"EXCEL TRUNCATION fingerprint: {n_rows:,} rows == the Excel sheet limit -- "
            "the file was almost certainly cut (catalog 4c). Obtain the untruncated source.")
    if zones:
        cov_o = len(origins & set(zones)) / len(zones)
        cov_d = len(dests & set(zones)) / len(zones)
        report["origin_coverage"] = round(cov_o, 4)
        report["destination_coverage"] = round(cov_d, 4)
        if cov_o < 0.9:
            report["errors"].append(
                f"only {cov_o:.0%} of zones appear as ORIGINS -- truncated or mis-mapped "
                "(a sorted export cut mid-file loses the high-numbered origins)")
        elif cov_o < 0.99:
            report["warnings"].append(f"origin coverage {cov_o:.0%} (<99%)")
        unknown = (origins | dests) - set(zones)
        if unknown:
            report["errors"].append(
                f"{len(unknown):,} matrix zone ids not in the network zone list "
                f"(sample: {sorted(unknown)[:5]}) -- zone-id basis mismatch (catalog 5b)")
    return report


def read_long(path, zones=None, o_col=0, d_col=1, v_col=2):
    """Long-form o,d,value -> dict[(o,d)] = value, with coverage checks."""
    od = {}
    origins, dests = set(), set()
    n = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.reader(f)
        header = next(r)
        for row in r:
            n += 1
            try:
                o, d, v = int(float(row[o_col])), int(float(row[d_col])), float(row[v_col])
            except (ValueError, IndexError):
                continue
            if v:
                od[(o, d)] = od.get((o, d), 0.0) + v
                origins.add(o)
                dests.add(d)
    rep = _check(MatrixReport(kind="long", path=path), zones, origins, dests, n)
    return od, rep


def read_wide(path, zones=None):
    """Square CSV: header = ,z1,z2,... ; rows = zi,v,v,... -> dict[(o,d)]=v."""
    od = {}
    origins, dests = set(), set()
    n = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.reader(f)
        header = next(r)
        cols = []
        for c in header[1:]:
            try:
                cols.append(int(float(c)))
            except ValueError:
                cols.append(None)
        dests = {c for c in cols if c is not None}
        for row in r:
            n += 1
            try:
                o = int(float(row[0]))
            except (ValueError, IndexError):
                continue
            origins.add(o)
            for j, c in enumerate(cols, start=1):
                if c is None or j >= len(row):
                    continue
                try:
                    v = float(row[j])
                except ValueError:
                    continue
                if v:
                    od[(o, c)] = v
    rep = _check(MatrixReport(kind="wide", path=path), zones, origins, dests, n)
    return od, rep


def read_omx(path, table=None, zones=None):
    """OMX matrix (optional dep). Returns dict[(o,d)]=v using the zone mapping."""
    try:
        import openmatrix as omx
    except ImportError:
        sys.exit("OMX support needs `pip install openmatrix`")
    f = omx.open_file(path)
    try:
        name = table or f.list_matrices()[0]
        m = f[name][:]
        maps = f.list_mappings()
        ids = list(f.mapping(maps[0]).keys()) if maps else list(range(1, m.shape[0] + 1))
        od = {}
        origins = set()
        for i, o in enumerate(ids):
            row = m[i]
            for j, d in enumerate(ids):
                v = float(row[j])
                if v:
                    od[(int(o), int(d))] = v
                    origins.add(int(o))
        rep = _check(MatrixReport(kind="omx", path=path, table=name), zones,
                     origins, {int(z) for z in ids}, m.shape[0])
        return od, rep
    finally:
        f.close()


def write_long(od, path, header=("o_zone_id", "d_zone_id", "volume")):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for (o, d), v in sorted(od.items()):
            w.writerow([o, d, round(v, 4)])


def zones_of_scenario(scenario):
    """Zone id list from node.csv (zone_id == node_id convention)."""
    zones = []
    with open(os.path.join(scenario, "node.csv"), newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                z = int(float(r.get("zone_id") or 0))
            except ValueError:
                continue
            if z > 0:
                zones.append(z)
    return zones


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description="matrix -> kernel demand.csv with coverage checks")
    ap.add_argument("matrix", help="wide CSV / long CSV / .omx")
    ap.add_argument("--kind", choices=["auto", "wide", "long", "omx"], default="auto")
    ap.add_argument("--scenario", default=None, help="check coverage vs this scenario's zones")
    ap.add_argument("--out", default=None, help="write long-form demand.csv here")
    ap.add_argument("--table", default=None, help="OMX table name")
    a = ap.parse_args()
    zones = zones_of_scenario(a.scenario) if a.scenario else None
    kind = a.kind
    if kind == "auto":
        kind = ("omx" if a.matrix.lower().endswith(".omx") else "long")
        if kind == "long":       # sniff: wide files have >4 columns
            with open(a.matrix, newline="", encoding="utf-8-sig") as f:
                kind = "wide" if len(next(csv.reader(f))) > 4 else "long"
    od, rep = {"wide": read_wide, "long": read_long, "omx": read_omx}[kind](a.matrix, zones=zones)
    print(json.dumps(rep, indent=1))
    if rep["errors"]:
        print("BLOCKED: fix the matrix issues above before assignment.")
        return 1
    if a.out:
        write_long(od, a.out)
        print(f"wrote {a.out} ({len(od):,} OD pairs, {sum(od.values()):,.0f} total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
