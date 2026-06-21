"""Convert a NeXTA / old-DTALite multi-period scenario (e.g. the AZTDM statewide
model) to the current kernel's single-period GMNS format.

NeXTA differences handled:
  - settings.csv is a multi-SECTION file ([assignment]/[agent_type]/[link_type]/
    [demand_period]/[demand_file_list]); we emit a single-row settings.csv + a
    mode_type.csv for one chosen period.
  - link.csv carries PERIOD-INDEXED VDF columns (VDF_cap{N}, VDF_alpha{N},
    VDF_beta{N}, VDF_fftt{N}, VDF_allowed_uses{N}); we select period N and map to
    capacity / vdf_alpha / vdf_beta / vdf_fftt / allowed_use. free_speed is mph and
    length is miles (-> vdf_free_speed_mph / vdf_length_mi). FT -> facility_type.
  - VDF_cap{N} is the (all-lane) PERIOD capacity. AZTDM builds it as c_h*L (phi=L,
    i.e. a FLAT load factor PLF=1). Per the ADOT Load-Factor memo (Belezamo/Zhou,
    Sep 2022): c_period = phi*c_h, phi = L*PLF, and peak hourly demand D =
    v_period/(L*PLF), so the kernel's DOC = (V/lanes/H/plf)/lane_cap must be fed
    lane_cap = hourly c_h, vdf_plf = PLF (the real load factor), H = L -> DOC = D/c_h.
    We therefore set lane_cap = VDF_cap/(lanes*L) (recover hourly capacity) and
    vdf_plf = PLF from MEMO_PLF (NOT 1/H, which would hard-code the flat PLF=1 case
    the memo warns against). PLF<1 raises D/C by 1/PLF (~6% AM, ~2.5x NT).
  - demand CSVs have a leading empty column; we convert them to binary (.bin),
    which reads o_zone_id/d_zone_id/volume by NAME, and set demand_format=1.
"""
import os

from . import csvio
from . import demandbin
from . import plf as _plf

# Back-calculated load factor (ADOT Load-Factor memo, Sep 2022, Sec 6 — MAG ref).
# PLF = avg-hourly/peak-hourly volume in (0,1]; 1 = flat. phi = L*PLF. The "arterial"
# row is the more-peaked major-arterial (x06) class. Used as: lane_cap = VDF_cap/(lanes*L),
# vdf_plf = PLF.  Override per scenario if AZTDM-specific factors are available.
MEMO_PLF = {"AM": 0.94, "MD": 0.96, "PM": 0.98, "NT": 0.40}
MEMO_PLF_ARTERIAL = {"AM": 0.83, "MD": 0.93, "PM": 0.91, "NT": 0.39}
ARTERIAL_LINK_TYPES = {"2"}  # AZTDM link_type 2 = Major Arterial (memo x06 analogue)


def _hours(time_period):
    """'0600_0900' -> (6.0, 9.0); wraps past midnight ('1800_0600' -> (18, 30))."""
    a, b = time_period.split("_")
    sh = int(a[:2]) + int(a[2:]) / 60.0
    eh = int(b[:2]) + int(b[2:]) / 60.0
    if eh <= sh:
        eh += 24
    return sh, eh


def parse_settings(path):
    """Parse the NeXTA multi-section settings.csv."""
    agent_types, periods, demand_files = {}, {}, []
    iters = 1
    section = None
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csvio_reader(f):
            cell0 = row[0].strip() if row else ""
            if cell0.startswith("["):
                section = cell0.strip("[]")
                continue
            cells = [c.strip() for c in row]
            if section == "assignment" and len(cells) > 3 and cells[2] in ("ue", "dta", "odme"):
                iters = csvio.inum(cells[3], 1)
            elif section == "agent_type" and len(cells) > 6 and cells[1] and cells[1] != "agent_type":
                agent_types[cells[1]] = {"vot": csvio.fnum(cells[4], 10), "pce": csvio.fnum(cells[6], 1)}
            elif section == "demand_period":
                # rows are right-shifted per period; id is a bare int, name is the
                # next non-empty cell, time_period is the next cell containing '_'.
                for i, c in enumerate(cells):
                    if c.isdigit():
                        nm = next((cells[j] for j in range(i + 1, len(cells)) if cells[j]), "")
                        tp = next((cells[j] for j in range(i + 1, len(cells)) if "_" in cells[j]), "")
                        if tp:
                            periods[c] = {"name": nm, "time_period": tp}
                        break
            elif section == "demand_file_list" and len(cells) > 6 and cells[1].isdigit():
                demand_files.append({"file": cells[2], "period": cells[5], "agent": cells[6]})
    return {"iterations": iters, "agent_types": agent_types, "periods": periods,
            "demand_files": demand_files}


def csvio_reader(f):
    import csv
    return csv.reader(f)


def convert(scenario, out_dir, period_name="AM", iterations=None, processors=8,
            to_binary=True, report=None, plf=None, plf_arterial=None):
    os.makedirs(out_dir, exist_ok=True)
    rep = report if report is not None else []
    nx = parse_settings(csvio.path(scenario, "settings.csv"))
    period_name = period_name.upper()

    # period hours
    H = 1.0
    for p in nx["periods"].values():
        if p["name"].upper() == period_name:
            sh, eh = _hours(p["time_period"])
            H = eh - sh
            start_h, end_h = sh, eh
            break
    else:
        start_h, end_h = 6.0, 9.0
        H = 3.0
    rep.append(f"period {period_name}: {start_h}-{end_h} h (H={H})")

    # period index N (VDF_*{N}) from the demand_period id
    pid = next((k for k, v in nx["periods"].items() if v["name"].upper() == period_name), "1")
    N = pid

    # demand files for this period
    dfs = [d for d in nx["demand_files"] if d["period"].upper() == period_name]
    # Fallback: the demand_file_list often only configures one period (AM). For
    # other periods, infer modes from files present on disk by the {prefix}_{period}
    # naming convention (da=sov, sr2=hov2, sr3=hov3, sut=sut, mut=mut).
    if not dfs:
        prefix_agent = [("da", "sov"), ("sr2", "hov2"), ("sr3", "hov3"),
                        ("sut", "sut"), ("mut", "mut")]
        for pre, agent in prefix_agent:
            fn = f"{pre}_{period_name.lower()}.csv"
            if os.path.exists(csvio.path(scenario, fn)):
                dfs.append({"file": fn, "period": period_name, "agent": agent})
        rep.append(f"demand_file_list had no {period_name} entry; inferred from disk: "
                   f"{[d['file'] for d in dfs]}")

    # mode_type.csv
    mt_rows = []
    for d in dfs:
        at = nx["agent_types"].get(d["agent"], {"vot": 10, "pce": 1})
        mt_rows.append({"mode_type": d["agent"], "name": d["agent"],
                        "vot": at["vot"], "pce": at["pce"], "occ": 1,
                        "demand_file": d["file"],  # kernel swaps .csv->.bin when demand_format=1
                        "dedicated_shortest_path": 1})
    csvio.write(csvio.path(out_dir, "mode_type.csv"),
                ["mode_type", "name", "vot", "pce", "occ", "demand_file", "dedicated_shortest_path"],
                mt_rows)
    rep.append(f"mode_type.csv: {len(mt_rows)} modes {[d['agent'] for d in dfs]}")

    # settings.csv (current single-row)
    csvio.write(csvio.path(out_dir, "settings.csv"),
                ["number_of_iterations", "number_of_processors", "demand_period_starting_hours",
                 "demand_period_ending_hours", "first_through_node_id", "base_demand_mode",
                 "route_output", "vehicle_output", "log_file", "odme_mode", "odme_vmt",
                 "demand_format", "added_delay_per_mile", "convergence_gap_pct"],
                [{"number_of_iterations": iterations or nx["iterations"], "number_of_processors": processors,
                  "demand_period_starting_hours": start_h, "demand_period_ending_hours": end_h,
                  "first_through_node_id": -1, "base_demand_mode": 0, "route_output": 0,
                  "vehicle_output": 0, "log_file": 0, "odme_mode": 0, "odme_vmt": 0,
                  "demand_format": 1 if to_binary else 0, "added_delay_per_mile": 0,
                  "convergence_gap_pct": 0}])

    plf_val = plf if plf is not None else MEMO_PLF.get(period_name, 1.0)
    plf_art = plf_arterial if plf_arterial is not None else MEMO_PLF_ARTERIAL.get(period_name, plf_val)
    # Enforce the memo PLF bounds: 0 < PLF <= 1 and phi = L*PLF >= 1.
    plf_val, note1 = _plf.bound_plf(plf_val, H)
    plf_art, note2 = _plf.bound_plf(plf_art, H)
    for note in (note1, note2):
        if note:
            rep.append(f"PLF bound: {note}")
    rep.append(f"load factor PLF: {plf_val} (arterial {plf_art}); phi=L*PLF={round(plf_val*H,3)}; "
               f"lane_cap = VDF_cap/(lanes*L), L={H}")
    _convert_links(scenario, out_dir, N, H, plf_val, plf_art, rep)
    # node.csv passthrough (has node_id, zone_id, x_coord, y_coord)
    import shutil
    shutil.copy(csvio.path(scenario, "node.csv"), csvio.path(out_dir, "node.csv"))

    # demand -> binary (handles the leading empty column via name-based read)
    if to_binary:
        for d in dfs:
            src = csvio.path(scenario, d["file"])
            if os.path.exists(src):
                n, binp = demandbin.convert_file(src, csvio.path(out_dir, d["file"][:-4] + ".bin"))
                rep.append(f"{d['file']} -> {os.path.basename(binp)} ({n:,} pairs)")
    else:
        for d in dfs:
            src = csvio.path(scenario, d["file"])
            if os.path.exists(src):
                shutil.copy(src, csvio.path(out_dir, d["file"]))

    # emit a converter step-log that `intake` ingests
    from . import convlog as _convlog
    cl = _convlog.ConversionLog("nexta", source=os.path.join(scenario, "link.csv"))
    cl.input("link.csv", "NeXTA period-indexed VDF columns")
    cl.step(f"selected period {period_name} (hours {sh}-{eh}, L={H})")
    cl.map("vdf_length_mi", "vdf_fftt * vdf_free_speed_mph / 60", "unit-agnostic length")
    cl.map("capacity", f"VDF_cap{period_name}/(lanes*L)", "hourly per-lane")
    cl.map("vdf_plf", f"MEMO_PLF[{period_name}]={plf_val} (arterial {plf_art})", "real load factor PLF=phi/L")
    cl.assume("capacity_period", "hourly", "lane_cap = VDF_cap/(lanes*L)")
    cl.assume("length_unit", "mi", "vdf_length_mi derived in miles")
    cl.assume("peak_load_factor", str(plf_val), "MEMO_PLF; confirm vs agency period factors")
    cl.assume("demand_period_hours", str(H), f"period {period_name} = {sh}-{eh}")
    cl.output("link.csv", "current-format GMNS with period VDF")
    cl.write(out_dir)
    rep.append("conversion_log.json written (intake will ingest it)")
    return rep


def _convert_links(scenario, out_dir, N, H, plf_val, plf_art, rep):
    # The kernel assigns internal node seq numbers in node.csv ROW ORDER and builds
    # CSR adjacency on that; links must be sorted by the from-node's node.csv position
    # (NOT raw node_id, since node.csv here is not id-sorted).
    nseq = {}
    nhdr, nrows = csvio.read(csvio.path(scenario, "node.csv"))
    for i, nr in enumerate(nrows):
        nseq[csvio.inum(nr.get("node_id"))] = i
    header, rows = csvio.read(csvio.path(scenario, "link.csv"))
    out_hdr = ["link_id", "from_node_id", "to_node_id", "facility_type", "link_type",
               "lanes", "capacity", "free_speed", "vdf_free_speed_mph", "length",
               "vdf_length_mi", "vdf_type", "vdf_alpha", "vdf_beta", "vdf_plf",
               "vdf_fftt", "cutoff_speed", "allowed_use", "geometry"]
    out_rows = []
    L = H if H > 0 else 1.0   # period length (hours)
    for r in rows:
        lanes = csvio.fnum(r.get("lanes"), 1) or 1
        vcap = csvio.fnum(r.get(f"VDF_cap{N}"))
        fs = csvio.fnum(r.get("free_speed"), 0)
        ff = csvio.fnum(r.get(f"VDF_fftt{N}"))
        # Derive length (miles) from the period free-flow time and free_speed. This is
        # unit-agnostic (the raw `length` column is meters in some AZTDM folders, miles
        # in others) and stays consistent with vdf_fftt -> correct VMT and travel time.
        length_mi = (ff * fs / 60.0) if (ff and fs) else csvio.fnum(r.get("length"))
        # Memo-correct: recover HOURLY per-lane capacity c_h = VDF_cap/(lanes*L) and
        # carry the real load factor PLF in vdf_plf -> DOC = D/c_h, D = V/(L*PLF).
        lane_cap = (vcap / (lanes * L)) if vcap else 1000
        plf = plf_art if (r.get("link_type") in ARTERIAL_LINK_TYPES) else plf_val
        out_rows.append({
            "link_id": r.get("link_id"), "from_node_id": r.get("from_node_id"),
            "to_node_id": r.get("to_node_id"), "facility_type": r.get("FT"),
            "link_type": r.get("link_type"), "lanes": lanes,
            "capacity": round(lane_cap, 3),                # HOURLY per-lane capacity c_h
            "free_speed": fs, "vdf_free_speed_mph": fs,
            "length": round(length_mi, 6), "vdf_length_mi": round(length_mi, 6),
            "vdf_type": 0,
            "vdf_alpha": r.get(f"VDF_alpha{N}"), "vdf_beta": r.get(f"VDF_beta{N}"),
            "vdf_plf": plf,                                 # real load factor (memo)
            "vdf_fftt": r.get(f"VDF_fftt{N}"),
            "cutoff_speed": round(fs * 0.75, 3) if fs else "",
            "allowed_use": r.get(f"VDF_allowed_uses{N}", ""), "geometry": r.get("geometry", ""),
        })
    big = len(nseq) + 1
    out_rows.sort(key=lambda r: (nseq.get(csvio.inum(r["from_node_id"]), big),
                                 nseq.get(csvio.inum(r["to_node_id"]), big)))
    csvio.write(csvio.path(out_dir, "link.csv"), out_hdr, out_rows)
    rep.append(f"link.csv: {len(out_rows)} links, period {N} (capacity=VDF_cap{N}/(lanes*L), "
               f"vdf_plf=PLF); sorted by node.csv seq order")
