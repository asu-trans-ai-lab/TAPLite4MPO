"""Forensics battery -- automatic convention detectors for incoming datasets.

Phase-1 of the NeXTA GMNS AI generation module (docs/NEXTA_AI_GENERATION_MODULE.md):
every data-conversion scar (lessons L1-L13 in docs/DATA_CONVERSION_STRATEGY.md)
packaged as a detector. Run BEFORE any conversion. Each finding carries a severity:

  BLOCK   -- will corrupt results or crash the kernel; must be fixed/declared.
  DECLARE -- a convention the agency/user must confirm (the AI may draft it,
             a human confirms; conversion must not proceed on a guess).
  INFO    -- noted for the conversion config / report.

Stdlib only; single streaming pass over link.csv; demand line-counts use fast
binary chunk counting (large files OK). Output is a JSON-able report dict.
"""
import csv
import glob
import os

from . import csvio

EXCEL_LIMIT_LINES = {1048574, 1048575, 1048576}   # wc -l of a sheet-truncated CSV
SENTINEL_CAPS = (99999.0, 299997.0, 599994.0)


def _find(fid, severity, title, evidence, rec):
    return {"id": fid, "severity": severity, "title": title,
            "evidence": evidence, "recommendation": rec}


def _count_lines(path, chunk=1 << 22):
    n = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            n += b.count(b"\n")
    return n


def _is_multisection_settings(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            head = [f.readline() for _ in range(40)]
        return any(ln.strip().strip(",").startswith("[") for ln in head)
    except OSError:
        return False


def _demand_files(scenario):
    """Demand files to check: declared (mode_type / NeXTA settings) else glob."""
    out = []
    if csvio.exists(scenario, "mode_type.csv"):
        _, mts = csvio.read(csvio.path(scenario, "mode_type.csv"))
        out += [m.get("demand_file") for m in mts if m.get("demand_file")]
    sp = csvio.path(scenario, "settings.csv")
    if os.path.exists(sp) and _is_multisection_settings(sp):
        try:
            from . import nexta
            out += [d["file"] for d in nexta.parse_settings(sp)["demand_files"]]
        except Exception:
            pass
    if csvio.exists(scenario, "demand.csv"):
        out.append("demand.csv")
    if not out:   # fallback: common period-demand naming
        for f in glob.glob(os.path.join(scenario, "*_[ap]m.csv")) + \
                 glob.glob(os.path.join(scenario, "*_md.csv")) + \
                 glob.glob(os.path.join(scenario, "*_nt.csv")):
            out.append(os.path.basename(f))
    seen, uniq = set(), []
    for f in out:
        if f and f.lower().endswith(".csv") and f not in seen:
            seen.add(f)
            uniq.append(f)
    return [f for f in uniq if os.path.exists(csvio.path(scenario, f))]


def _median(v):
    s = sorted(v)
    return s[len(s) // 2] if s else None


def run(scenario, quick=False, sample_rows=60000):
    """Run all detectors; returns the report dict."""
    F = []

    # ---------- settings / source family (L9, L11) ----------
    sp = csvio.path(scenario, "settings.csv")
    multisection = os.path.exists(sp) and _is_multisection_settings(sp)
    if multisection:
        F.append(_find("source_family", "INFO", "NeXTA / old-DTALite multi-section settings.csv",
                       "sections like [assignment]/[demand_file_list] present",
                       "convert with dtalite_qa.nexta.convert (per-period)"))
    elif not os.path.exists(sp):
        F.append(_find("settings_missing", "DECLARE", "no settings.csv",
                       "kernel will use defaults (20 iters, 7-8h period)",
                       "declare iterations / period hours / processors"))

    # ---------- node.csv checks (L5) ----------
    nid, zmismatch, zset = [], 0, set()
    if csvio.exists(scenario, "node.csv"):
        _, nrows = csvio.read(csvio.path(scenario, "node.csv"))
        for r in nrows:
            i = csvio.inum(r.get("node_id"))
            nid.append(i)
            z = csvio.inum(r.get("zone_id"), 0)
            if z > 0:
                zset.add(z)
                if z != i:
                    zmismatch += 1
        if any(nid[k] > nid[k + 1] for k in range(len(nid) - 1)):
            F.append(_find("node_order", "INFO", "node.csv is NOT sorted by node_id",
                           f"first ids: {nid[:3]}...; kernel numbers nodes by ROW order",
                           "links must be sorted by node.csv ROW position, not raw id "
                           "(emitters nexta/superzone_hier do this)"))
        if zmismatch:
            F.append(_find("zone_id_model", "BLOCK", "zones with zone_id != node_id",
                           f"{zmismatch} node(s) violate the kernel rule zone_id == node_id",
                           "renumber centroids so each zone is a node with zone_id==node_id"))
        if zset and max(zset) > 1.5 * len(zset):
            F.append(_find("zone_compact", "INFO", "zone ids are not compact",
                           f"max zone_id {max(zset):,} vs {len(zset):,} zones "
                           f"(kernel allocates by max id)",
                           "compact renumbering cuts memory and O(no_zones^2) loops"))
    else:
        F.append(_find("node_missing", "BLOCK", "node.csv not found", scenario, "provide node.csv"))

    # ---------- link.csv single streaming pass (L1,L2,L5,L6,L8) ----------
    lp = csvio.path(scenario, "link.csv")
    if os.path.exists(lp):
        with open(lp, newline="", encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            hdr = rd.fieldnames or []
            low = {c.lower(): c for c in hdr}
            fftt_col = low.get("vdf_fftt") or low.get("vdf_fftt1")
            capN = [low.get(f"vdf_cap{k}") for k in (1, 2, 3, 4)]
            multiperiod = all(capN)
            ln_ratio, spd, caps, capr = [], [], [], {2: [], 3: [], 4: []}
            abba = tot_id = 0
            from_seq, sent = [], 0
            nrow = 0
            nodepos = {v: k for k, v in enumerate(nid)} if nid else {}
            for r in rd:
                nrow += 1
                fs = csvio.fnum(r.get(low.get("free_speed", ""), ""), 0)
                L = csvio.fnum(r.get(low.get("length", ""), ""), 0)
                if fs:
                    spd.append(fs)
                if fftt_col and nrow <= sample_rows:
                    ff = csvio.fnum(r.get(fftt_col), 0)
                    if ff > 0 and fs > 0 and L > 0:
                        ln_ratio.append(L / (ff * fs / 60.0))
                c1 = csvio.fnum(r.get(capN[0]) if multiperiod else r.get(low.get("capacity", ""), ""), 0)
                if c1:
                    caps.append(c1)
                    if c1 in SENTINEL_CAPS:
                        sent += 1
                    if multiperiod and c1 > 0 and nrow <= sample_rows:
                        for k in (2, 3, 4):
                            ck = csvio.fnum(r.get(capN[k - 1]), 0)
                            if ck:
                                capr[k].append(ck / c1)
                li = (r.get(low.get("link_id", ""), "") or "").strip()
                if li:
                    tot_id += 1
                    if li[-2:].upper() in ("AB", "BA"):
                        abba += 1
                fr = csvio.inum(r.get(low.get("from_node_id", ""), ""), -1)
                if nodepos and nrow <= 200000:
                    from_seq.append(nodepos.get(fr, 1 << 30))

        # L1/L8 length units (unambiguous override columns win)
        has_mi = "vdf_length_mi" in low
        has_mph = "vdf_free_speed_mph" in low
        med = _median(ln_ratio)
        if med is not None:
            unit = ("miles" if 0.7 < med < 1.4 else
                    "kilometers" if 1.45 < med < 1.8 else
                    "METERS" if 1200 < med < 2000 else f"UNKNOWN (x{med:.2f})")
            if unit != "miles" and has_mi:
                F.append(_find("length_units", "INFO",
                               f"raw length column is {unit}, but vdf_length_mi override present",
                               f"median length/(fftt*speed/60) = {med:.3f}; kernel uses vdf_length_mi",
                               "keep vdf_length_mi authoritative"))
            else:
                sev = "INFO" if unit == "miles" else "BLOCK" if unit == "METERS" else "DECLARE"
                F.append(_find("length_units", sev, f"length column is in {unit}",
                               f"median length/(fftt*speed/60) = {med:.3f} over {len(ln_ratio):,} links",
                               "emit vdf_length_mi = fftt*speed/60 (unit-agnostic) or convert"))
        elif spd and not has_mi:
            F.append(_find("length_units", "DECLARE", "length units cannot be cross-checked",
                           "no fftt column to compare against", "declare length units (mi/km/m)"))
        # speed units
        if spd:
            mx = max(spd)
            if mx > 90 and has_mph:
                F.append(_find("speed_units", "INFO",
                               "raw free_speed odd, but vdf_free_speed_mph override present",
                               f"range {min(spd):.0f}-{mx:.0f}; kernel uses vdf_free_speed_mph",
                               "keep vdf_free_speed_mph authoritative"))
            else:
                F.append(_find("speed_units", "INFO" if mx <= 90 else "DECLARE",
                               f"free_speed looks like {'mph' if mx <= 90 else 'km/h or mixed'}",
                               f"range {min(spd):.0f}-{mx:.0f}", "set vdf_free_speed_mph explicitly"))
        # L9 multi-period
        if multiperiod:
            rats = {k: round(_median(v), 2) for k, v in capr.items() if v}
            F.append(_find("multiperiod_vdf", "DECLARE", "period-indexed VDF columns (VDF_cap1..4)",
                           f"median cap ratios vs period 1: {rats}",
                           "if ratios match your period-length ratios, VDF_cap is a PERIOD "
                           "capacity built FLAT (phi=L, PLF=1) -> recover hourly cap and set "
                           "real PLF (docs/peak_load_factor.md); pick a period via nexta.convert"))
        # L2 capacity convention (single-period)
        if caps and not multiperiod:
            mc = _median(caps)
            F.append(_find("capacity_convention", "DECLARE" if mc and mc > 2600 else "INFO",
                           f"capacity median {mc:,.0f}",
                           f"{'high for hourly per-lane -> may be period/daily/all-lane' if mc and mc > 2600 else 'consistent with hourly per-lane'}",
                           "declare: per-lane vs all-lane; hourly vs period vs daily"))
        if sent:
            F.append(_find("capacity_sentinels", "INFO", "sentinel (uncapped) capacities present",
                           f"{sent:,} link(s) at {sorted(set(SENTINEL_CAPS))}",
                           "intended as uncapped; keep, do not treat as data errors"))
        # L6 AB/BA ids
        if tot_id and abba / tot_id > 0.5:
            F.append(_find("abba_link_id", "INFO", "link_id carries AB/BA direction suffix",
                           f"{abba:,}/{tot_id:,} ids end in AB/BA",
                           "JOIN results on (from_node_id,to_node_id), never on link_id"))
        # L5 link sort vs node order
        if from_seq and any(from_seq[k] > from_seq[k + 1] for k in range(len(from_seq) - 1)):
            F.append(_find("link_sort", "BLOCK", "link.csv NOT sorted by node.csv row order",
                           "kernel CSR adjacency assumes it; unsorted links corrupt paths",
                           "sort links by the from-node's node.csv position (emitters do this)"))
    else:
        F.append(_find("link_missing", "BLOCK", "link.csv not found", scenario, "provide link.csv"))

    # ---------- demand checks (L4, L10) ----------
    dfs = _demand_files(scenario)
    if not dfs:
        F.append(_find("demand_missing", "DECLARE", "no demand files found",
                       "network-only dataset", "obtain OD tables, or generate a seed "
                       "(4-step-lite) clearly labeled synthetic"))
    if not quick:
        for df in dfs:
            path = csvio.path(scenario, df)
            n = _count_lines(path)
            if n in EXCEL_LIMIT_LINES:
                F.append(_find("excel_truncation", "BLOCK", f"{df}: Excel-truncated",
                               f"{n:,} lines == the 1,048,576-row sheet limit",
                               "recover the un-truncated source (never open/save demand in Excel)"))
        # zone coverage (sample first demand file)
        if dfs and zset:
            miss, seen = set(), 0
            with open(csvio.path(scenario, dfs[0]), newline="", encoding="utf-8-sig") as f:
                rd = csv.reader(f)
                h = next(rd, [])
                try:
                    oi, di = h.index("o_zone_id"), h.index("d_zone_id")
                except ValueError:
                    oi, di = 0, 1
                for row in rd:
                    seen += 1
                    if seen > 500000:
                        break
                    try:
                        o, d = int(float(row[oi])), int(float(row[di]))
                    except (IndexError, ValueError):
                        continue
                    if o not in zset:
                        miss.add(o)
                    if d not in zset:
                        miss.add(d)
            if miss:
                F.append(_find("demand_zone_coverage", "DECLARE",
                               f"{dfs[0]}: OD references zones absent from node.csv",
                               f"{len(miss)} unknown zone id(s) in first {seen:,} rows "
                               f"(e.g. {sorted(miss)[:5]})",
                               "map or filter (adapt --no-filter-demand keeps them); "
                               "document the dropped volume"))

    # ---------- PLF (L3) ----------
    if csvio.exists(scenario, "link.csv") and not multisection:
        try:
            from . import plf as _plf
            rep = _plf.check(scenario)
            if rep.get("flat") and rep.get("period_hours", 1) > 1:
                F.append(_find("plf_flat", "DECLARE", "flat PLF (=1) on a multi-hour period",
                               f"period {rep['period_hours']:.0f} h, all links PLF=1",
                               "under-states peak congestion; set PLF per "
                               "docs/peak_load_factor.md (bounds 0<PLF<=1, phi=L*PLF>=1)"))
        except Exception:
            pass

    order = {"BLOCK": 0, "DECLARE": 1, "INFO": 2}
    F.sort(key=lambda x: order[x["severity"]])
    counts = {s: sum(1 for x in F if x["severity"] == s) for s in ("BLOCK", "DECLARE", "INFO")}
    return {"scenario": scenario, "findings": F, "counts": counts,
            "verdict": "BLOCKED" if counts["BLOCK"] else
                       ("NEEDS DECLARATIONS" if counts["DECLARE"] else "CLEAN")}


def render(rep):
    L = [f"forensics: {rep['scenario']}",
         f"verdict: {rep['verdict']}  "
         f"(block {rep['counts']['BLOCK']}, declare {rep['counts']['DECLARE']}, info {rep['counts']['INFO']})", ""]
    for f in rep["findings"]:
        L.append(f"[{f['severity']:7}] {f['id']}: {f['title']}")
        L.append(f"          evidence: {f['evidence']}")
        L.append(f"          -> {f['recommendation']}")
    return "\n".join(L)
