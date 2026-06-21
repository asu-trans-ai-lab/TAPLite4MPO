"""Input validation for a DTALite/TAPLite scenario folder.

Returns a Report with ERRORS (will break/corrupt the run) and WARNINGS
(tolerated). See README for the full list. Designed to be called both as a
library (returns the Report) and from the CLI.
"""
import os

from . import csvio
from . import schema


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def err(self, m):
        self.errors.append(m)

    def warn(self, m):
        self.warnings.append(m)

    @property
    def ok(self):
        return not self.errors


def _mode_tokens(scenario):
    if not csvio.exists(scenario, "mode_type.csv"):
        return []
    _, rows = csvio.read(csvio.path(scenario, "mode_type.csv"))
    return [r["mode_type"].strip() for r in rows if r.get("mode_type")]


def validate(scenario):
    rep = Report()
    for n in ("node.csv", "link.csv"):
        if not csvio.exists(scenario, n):
            rep.err(f"missing required file: {n}")
    if rep.errors:
        return rep
    if not csvio.exists(scenario, "settings.csv"):
        rep.warn("settings.csv not found; the kernel will use default settings")

    # node.csv
    _, nodes = csvio.read(csvio.path(scenario, "node.csv"))
    node_ids, zone_ids = set(), set()
    nhdr = set(nodes[0].keys()) if nodes else set()
    miss = [c for c in schema.NODE_REQUIRED if c not in nhdr and c != "zone_id"]
    if not nodes:
        rep.err("node.csv: empty")
    if miss:
        rep.err(f"node.csv: missing required columns {miss}")
    for i, r in enumerate(nodes, 2):
        if not csvio.is_num(r.get("node_id")):
            rep.err(f"node.csv line {i}: non-numeric node_id {r.get('node_id')!r}")
            continue
        nid = csvio.inum(r["node_id"])
        if nid in node_ids:
            rep.err(f"node.csv: duplicate node_id {nid}")
        node_ids.add(nid)
        z = r.get("zone_id")
        if csvio.is_num(z) and float(z) > 0:
            zone_ids.add(csvio.inum(z))

    # link.csv
    _, links = csvio.read(csvio.path(scenario, "link.csv"))
    tokens = _mode_tokens(scenario)
    link_ids = set()
    if not links:
        rep.err("link.csv: empty")
    else:
        lhdr = set(links[0].keys())
        miss = [c for c in schema.LINK_REQUIRED if c not in lhdr]
        if miss:
            rep.err(f"link.csv: missing required columns {miss}")
        has_link_id = "link_id" in lhdr
        if not has_link_id:
            rep.warn("link.csv: no link_id column; outputs use row index and movement.csv "
                     "cannot reference links")
        prev_from, unsorted = -10**9, False
        for i, r in enumerate(links, 2):
            fn, tn = r.get("from_node_id"), r.get("to_node_id")
            if not (csvio.is_num(fn) and csvio.is_num(tn)):
                rep.err(f"link.csv line {i}: non-numeric from/to node id")
                continue
            fn, tn = csvio.inum(fn), csvio.inum(tn)
            if fn not in node_ids:
                rep.err(f"link.csv line {i}: from_node_id {fn} not in node.csv")
            if tn not in node_ids:
                rep.err(f"link.csv line {i}: to_node_id {tn} not in node.csv")
            if fn < prev_from and not unsorted:
                rep.err(f"link.csv line {i}: links NOT sorted ascending by from_node_id "
                        f"(from {fn} after {prev_from}); the kernel's CSR adjacency will be "
                        f"corrupted. Sort link.csv by from_node_id (dtalite_qa fill does this).")
                unsorted = True
            prev_from = max(prev_from, fn)
            for c in ("lanes", "capacity", "free_speed"):
                if not csvio.is_num(r.get(c)) or csvio.fnum(r.get(c)) <= 0:
                    rep.err(f"link.csv line {i}: {c}={r.get(c)!r} must be > 0")
            if has_link_id and csvio.is_num(r.get("link_id")):
                lid = csvio.inum(r["link_id"])
                if lid in link_ids:
                    rep.err(f"link.csv: duplicate link_id {lid}")
                link_ids.add(lid)
            if str(r.get("vdf_type", "0")).strip() == "2":
                for c in schema.LINK_QVDF_COLS:
                    if not csvio.is_num(r.get(c)):
                        rep.warn(f"link.csv line {i}: vdf_type=2 but {c} missing -> kernel default used")
            au = (r.get("allowed_use") or "").strip()
            if au and not schema.is_all_allowed(au) and not schema.is_closed(au) and tokens:
                toks = [t for t in au.replace(",", ";").split(";") if t]
                unknown = [t for t in toks if t not in tokens]
                if unknown:
                    rep.warn(f"link.csv line {i}: allowed_use tokens {unknown} not in "
                             f"mode_type.csv {sorted(tokens)}")

    # settings.csv
    period_hours = None
    if csvio.exists(scenario, "settings.csv"):
        _, srows = csvio.read(csvio.path(scenario, "settings.csv"))
        if srows:
            s = srows[0]
            h0, h1 = s.get("demand_period_starting_hours"), s.get("demand_period_ending_hours")
            if csvio.is_num(h0) and csvio.is_num(h1):
                if float(h1) <= float(h0):
                    rep.err(f"settings.csv: demand_period_ending_hours ({h1}) must be > starting ({h0})")
                else:
                    period_hours = float(h1) - float(h0)

    # PLF check: a flat VDF_plf (=1) on a multi-hour period under-states peak-hour
    # congestion (D = V_period/(L*PLF)). The right PLF = phi/L from the MPO's
    # hourly->period expansion factors. See `dtalite_qa plf` for the inventory.
    if links and period_hours and period_hours > 1.0:
        plf_vals = set()
        for r in links:
            plf_vals.add(round(csvio.fnum(r.get("vdf_plf", r.get("VDF_plf")), 1.0), 4))
        if plf_vals == {1.0}:
            rep.warn(f"VDF_plf is flat (=1) on a {period_hours:.0f}-hour period -> under-states "
                     f"peak-hour congestion. Set PLF=phi/L by facility type (see `dtalite_qa plf`).")

    # mode_type + demand files
    targets = []
    if csvio.exists(scenario, "mode_type.csv"):
        _, mts = csvio.read(csvio.path(scenario, "mode_type.csv"))
        for r in mts:
            df = (r.get("demand_file") or "").strip()
            if df:
                targets.append(df)
                if not csvio.exists(scenario, df):
                    rep.warn(f"mode_type.csv: demand_file {df!r} not found (mode gets zero demand)")
    if not targets and csvio.exists(scenario, "demand.csv"):
        targets = ["demand.csv"]
    for df in targets:
        if not csvio.exists(scenario, df):
            continue
        if df.lower().endswith(".bin"):
            continue   # binary demand (demand_format=1); validated at conversion time
        _, rows = csvio.read(csvio.path(scenario, df))
        if rows:
            for c in schema.DEMAND_REQUIRED:
                if c not in rows[0]:
                    rep.err(f"{df}: missing column {c}")
        bad = 0
        for r in rows:
            for c in ("o_zone_id", "d_zone_id"):
                z = r.get(c)
                if csvio.is_num(z) and csvio.inum(z) > 0 and csvio.inum(z) not in zone_ids:
                    bad += 1
            if csvio.is_num(r.get("volume")) and float(r["volume"]) < 0:
                rep.err(f"{df}: negative volume {r['volume']}")
        if bad:
            rep.warn(f"{df}: {bad} entries reference zone ids with no matching node zone_id (skipped)")

    # movement.csv
    if csvio.exists(scenario, "movement.csv"):
        _, rows = csvio.read(csvio.path(scenario, "movement.csv"))
        for i, r in enumerate(rows, 2):
            for c in ("ib_link_id", "ob_link_id"):
                v = r.get(c)
                if csvio.is_num(v) and link_ids and csvio.inum(v) not in link_ids:
                    rep.err(f"movement.csv line {i}: {c} {v} not a link_id in link.csv")
    return rep
