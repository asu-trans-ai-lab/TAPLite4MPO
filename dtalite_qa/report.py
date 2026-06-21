"""Post-run report: turn a kernel run folder into a structured summary.

Reads link_performance.csv (+ link.csv for facility type / allowed_use, +
summary_log_file.txt for the gap trajectory) and produces a run_report.json and a
human-readable run_report.md: gap convergence, system VMT/VHT/PMT/PHT, per-mode
link-volume totals, VMT by facility type, and an allowed_use enforcement check.

This is the artifact you hand an analyst or attach to a deliverable -- it answers
'did it converge, how much travel, by whom, on what facilities, and were the
network restrictions respected'.
"""
import os
import re

from . import csvio
from . import schema


def parse_gap(run_dir):
    """Per-iteration gap trajectory from summary_log_file.txt (or *.log)."""
    text = ""
    for name in ("summary_log_file.txt", "nvta_qa_run.log", "run.log"):
        p = os.path.join(run_dir, name)
        if os.path.exists(p):
            text += open(p, encoding="utf-8", errors="ignore").read()
    traj = []
    for m in re.finditer(
        r"iter No = (\d+).*?g_System_VMT = ([\d.eE+-]+).*?sys\. TT =\s*([\d.eE+-]+).*?"
        r"least TT =\s*([\d.eE+-]+).*?gap = ([\d.eE+-]+)", text):
        traj.append({"iter": int(m.group(1)), "system_vmt": float(m.group(2)),
                     "system_tt": float(m.group(3)), "least_tt": float(m.group(4)),
                     "gap_pct": float(m.group(5))})
    return traj


def _mode_tokens(run_dir):
    p = os.path.join(run_dir, "mode_type.csv")
    if not os.path.exists(p):
        return []
    _, rows = csvio.read(p)
    return [r["mode_type"].strip() for r in rows if r.get("mode_type")]


def build(run_dir):
    lp_path = os.path.join(run_dir, "link_performance.csv")
    if not os.path.exists(lp_path):
        return {"error": "no link_performance.csv in run folder"}
    _, lp = csvio.read(lp_path)
    tokens = _mode_tokens(run_dir)

    totals = {k: 0.0 for k in ("volume", "VMT", "VHT", "PMT", "PHT")}
    per_mode = {t: 0.0 for t in tokens}
    for r in lp:
        for k in totals:
            totals[k] += csvio.fnum(r.get(k))
        for t in tokens:
            per_mode[t] += csvio.fnum(r.get(f"mod_vol_{t}"))

    # join to link.csv (on external link_id) for facility type + allowed_use
    link = {}
    lk_path = os.path.join(run_dir, "link.csv")
    # Key links on (from_node_id, to_node_id), NOT link_id: link_id can be
    # resequenced or carry a non-numeric direction suffix (e.g. MPO "194AB"),
    # which makes link_id joins unreliable. (from,to) is unambiguous per directed link.
    def key(r):
        return (csvio.inum(r.get("from_node_id")), csvio.inum(r.get("to_node_id")))
    if os.path.exists(lk_path):
        _, lk = csvio.read(lk_path)
        for r in lk:
            link[key(r)] = r

    vmt_by_ft, enforce_fail, n_restricted = {}, [], 0
    for r in lp:
        lk = link.get(key(r))
        vmt = csvio.fnum(r.get("VMT"))
        ft = (lk.get("link_type") if lk else None) or "?"
        vmt_by_ft[ft] = vmt_by_ft.get(ft, 0.0) + vmt
        if lk and tokens:
            au = (lk.get("allowed_use") or "").strip()
            denied = [t for t in tokens if not schema.mode_allowed(au, t)]
            if denied:
                n_restricted += 1
                for t in denied:
                    if csvio.fnum(r.get(f"mod_vol_{t}")) > 0.01:
                        enforce_fail.append({"link_id": r.get("link_id"), "mode": t,
                                             "volume": csvio.fnum(r.get(f"mod_vol_{t}"))})

    # reference comparison: assigned volume vs ref_volume, travel_time vs ref_time
    # (ref_volume/ref_time come from the input link.csv, joined on link_id). Only
    # links with a positive reference are included.
    vol_a, vol_r, tim_a, tim_r = [], [], [], []
    for r in lp:
        lk = link.get(key(r))
        if not lk:
            continue
        rv = csvio.fnum(lk.get("ref_volume"))
        if rv > 0:
            # compare PURE vehicle volume (sum of per-mode mod_vol_*) to ref_volume,
            # NOT the PCE-weighted 'volume' column -- ref_volume is vehicle counts,
            # so PCE (trucks pce>1) would inflate the assigned side.
            if tokens:
                assigned_veh = sum(csvio.fnum(r.get(f"mod_vol_{t}")) for t in tokens)
            else:
                assigned_veh = csvio.fnum(r.get("volume"))
            vol_a.append(assigned_veh)
            vol_r.append(rv)
        rt = csvio.fnum(lk.get("ref_time", lk.get("ref_cost")))
        if rt > 0:
            tim_a.append(csvio.fnum(r.get("travel_time")))
            tim_r.append(rt)
    reference = {}
    if vol_r:
        reference["volume_vs_ref_volume"] = _compare(vol_a, vol_r)
    if tim_r:
        reference["traveltime_vs_ref_time"] = _compare(tim_a, tim_r)

    gap = parse_gap(run_dir)
    return {
        "run_dir": os.path.abspath(run_dir), "n_links": len(lp),
        "totals": totals, "per_mode_volume": per_mode,
        "vmt_by_facility_type": vmt_by_ft,
        "restricted_links": n_restricted,
        "enforcement_failures": enforce_fail,
        "reference_comparison": reference,
        "gap_trajectory": gap,
        "final_gap_pct": gap[-1]["gap_pct"] if gap else None,
    }


def _compare(assigned, ref):
    """Validation stats for paired (assigned, reference) values."""
    n = len(assigned)
    mean_r = sum(ref) / n if n else 0.0
    rmse = (sum((a - r) ** 2 for a, r in zip(assigned, ref)) / n) ** 0.5 if n else None
    # Pearson r^2
    r2 = None
    if n >= 2:
        ma = sum(assigned) / n
        mr = sum(ref) / n
        sxy = sum((a - ma) * (r - mr) for a, r in zip(assigned, ref))
        sxx = sum((a - ma) ** 2 for a in assigned)
        syy = sum((r - mr) ** 2 for r in ref)
        if sxx > 0 and syy > 0:
            corr = sxy / (sxx ** 0.5 * syy ** 0.5)
            r2 = corr * corr
    return {"n": n, "r2": r2, "rmse": rmse,
            "pct_rmse": (100.0 * rmse / mean_r if (rmse is not None and mean_r > 0) else None),
            "sum_assigned": sum(assigned), "sum_ref": sum(ref)}


def render_md(rep):
    if "error" in rep:
        return f"# Run report\n\n**ERROR:** {rep['error']}\n"
    L = ["# DTALite run report", "", f"- run folder: `{rep['run_dir']}`",
         f"- links: {rep['n_links']}",
         f"- final relative gap: "
         f"{rep['final_gap_pct'] if rep['final_gap_pct'] is not None else 'n/a'}%", ""]
    t = rep["totals"]
    L += ["## System totals",
          f"| VMT | VHT | PMT | PHT | total volume |",
          f"|---:|---:|---:|---:|---:|",
          f"| {t['VMT']:,.0f} | {t['VHT']:,.0f} | {t['PMT']:,.0f} | {t['PHT']:,.0f} | {t['volume']:,.0f} |", ""]
    if rep["per_mode_volume"]:
        L += ["## Per-mode link volume", "| mode | volume |", "|---|---:|"]
        for m, v in rep["per_mode_volume"].items():
            L.append(f"| {m} | {v:,.0f} |")
        L.append("")
    if rep["vmt_by_facility_type"]:
        L += ["## VMT by facility type (link_type)", "| link_type | VMT |", "|---|---:|"]
        for ft, v in sorted(rep["vmt_by_facility_type"].items(),
                            key=lambda kv: -kv[1]):
            L.append(f"| {ft} | {v:,.0f} |")
        L.append("")
    L += ["## allowed_use enforcement",
          f"- restricted links: {rep['restricted_links']}",
          f"- enforcement failures (disallowed-mode volume): "
          f"**{len(rep['enforcement_failures'])}**"
          + ("  (clean)" if not rep["enforcement_failures"] else "")]
    for f in rep["enforcement_failures"][:20]:
        L.append(f"  - link {f['link_id']} mode {f['mode']} = {f['volume']:.1f}")
    if rep.get("reference_comparison"):
        L += ["", "## Comparison vs reference (ref_volume / ref_time)",
              "| metric | n links | R^2 | RMSE | %RMSE | sum assigned | sum ref |",
              "|---|---:|---:|---:|---:|---:|---:|"]
        for name, c in rep["reference_comparison"].items():
            r2 = f"{c['r2']:.4f}" if c['r2'] is not None else "n/a"
            pr = f"{c['pct_rmse']:.1f}%" if c['pct_rmse'] is not None else "n/a"
            L.append(f"| {name} | {c['n']:,} | {r2} | {c['rmse']:,.1f} | {pr} "
                     f"| {c['sum_assigned']:,.0f} | {c['sum_ref']:,.0f} |")
        L.append("")
    if rep["gap_trajectory"]:
        L += ["", "## Gap trajectory", "| iter | system VMT | system TT | least TT | gap % |",
              "|---:|---:|---:|---:|---:|"]
        for g in rep["gap_trajectory"]:
            L.append(f"| {g['iter']} | {g['system_vmt']:,.0f} | {g['system_tt']:,.0f} "
                     f"| {g['least_tt']:,.0f} | {g['gap_pct']:.3f} |")
    return "\n".join(L) + "\n"
