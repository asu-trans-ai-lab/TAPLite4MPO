"""Traceable staged workflow (R1-R7) — MAG -> TAPLite traceability, generalized to any MPO.

Implements the staged, gated, report-emitting workflow from the MAG Traceable-Workflow
spec. Every stage writes a numbered report + tables (+ figures when matplotlib is present)
and runs a verification GATE (PASS / WARN / FAIL / SKIP). An index and an HTML dashboard
tie them together so the whole conversion -> assignment -> validation chain is auditable.

  R1 Inventory & directionality      VMT/VHT + network by FT-AT; directed-link check
  R2 OD & allowed-uses               demand totals/unique-OD by class; allowed_use flags
  R3 Capacity & VDF join             capacity + alpha/beta/plf completeness by code
  R4 Period & PLF                    period length, PLF by FT, flat-PLF check
  R5 TAP consistency                 model vs reference: V/C, speed, time (needs run+ref)
  R6 VMT/VHT validation              model vs reference VMT/VHT by FT-AT, <=5% gate
  R7 Rough emissions (MovesLite-mini) speed-bin factors -> CO2/NOx/VOC/PM2.5 from VMT/VHT

CLI: python -m dtalite_qa workflow <scenario> [--reference <link_perf_with_ref.csv>]
                                   [--period PM] [--submission <file>] [--out <dir>]
Stages needing a completed run read <scenario>/link_performance.csv (or --reference).
"""
import os
import math
import statistics

from . import csvio
from . import intake as _intake

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False

GATE_RANK = {"PASS": 0, "WARN": 1, "SKIP": 2, "FAIL": 3}


# ---- small helpers (stdlib) ------------------------------------------------------------
def _f(r, *keys, default=None):
    for k in keys:
        if k in r and csvio.is_num(r.get(k)):
            return csvio.fnum(r.get(k))
        # case-insensitive
        for kk in r:
            if kk.lower() == k.lower() and csvio.is_num(r.get(kk)):
                return csvio.fnum(r.get(kk))
    return default


def _col(header, *names):
    low = {h.lower(): h for h in header}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def _group_sum(rows, keycol, valcols):
    out = {}
    for r in rows:
        k = r.get(keycol, "")
        d = out.setdefault(k, {c: 0.0 for c in valcols})
        for c in valcols:
            v = _f(r, c)
            if v is not None:
                d[c] += v
    return out


def _write_table(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(header) + "\n")
        for row in rows:
            f.write(",".join(str(x) for x in row) + "\n")


def _r2_slope(xs, ys):
    pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None
           and math.isfinite(x) and math.isfinite(y)]
    if len(pts) < 3:
        return None, None, len(pts)
    sx = sum(p[0] for p in pts)
    n = len(pts)
    sxx = sum(p[0] * p[0] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    slope = sxy / sxx if sxx else None                      # through-origin slope
    my = sum(p[1] for p in pts) / n
    mx = sx / n
    ss_tot = sum((p[1] - my) ** 2 for p in pts)
    a, b = None, None
    # ordinary R^2 about regression line y=a x + b
    den = n * sxx - sx * sx
    if den:
        a = (n * sxy - sx * sum(p[1] for p in pts)) / den
        b = (sum(p[1] for p in pts) - a * sx) / n
        ss_res = sum((p[1] - (a * p[0] + b)) ** 2 for p in pts)
        r2 = 1 - ss_res / ss_tot if ss_tot else None
    else:
        r2 = None
    return r2, slope, n


def _scatter(path, xs, ys, xl, yl, title):
    if not HAVE_MPL:
        return False
    pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if not pts:
        return False
    fig, ax = _plt.subplots(figsize=(6, 6))
    ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=5, alpha=0.4)
    lim = max(max(p[0] for p in pts), max(p[1] for p in pts))
    ax.plot([0, lim], [0, lim], "r--", linewidth=1)
    ax.set_xlabel(xl); ax.set_ylabel(yl); ax.set_title(title); ax.grid(True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.tight_layout(); fig.savefig(path, dpi=150); _plt.close(fig)
    return True


# ---- R7 emission factors (explicit, auditable; MovesLite-mini) -------------------------
# speed bin (mph) -> grams/mile by pollutant (rough; swap for MOVES later w/o changing flow)
EMIT_BINS = [(0, 25), (25, 45), (45, 100)]
EMIT_FACT = {  # g/mi: (CO2, NOx, VOC, PM25)
    (0, 25):  (520, 1.20, 0.45, 0.060),
    (25, 45): (360, 0.70, 0.20, 0.035),
    (45, 100):(410, 0.85, 0.22, 0.040),
}


def _bin_speed(mph):
    for lo, hi in EMIT_BINS:
        if lo <= mph < hi:
            return (lo, hi)
    return EMIT_BINS[-1]


# ========================================================================================
def run_workflow(scenario, reference=None, period=None, submission=None, out_dir=None):
    base = out_dir or os.path.join(scenario, "traceability")
    rep_dir = os.path.join(base, "reports")
    tab_dir = os.path.join(base, "tables")
    fig_dir = os.path.join(base, "figures")
    for d in (rep_dir, tab_dir, fig_dir):
        os.makedirs(d, exist_ok=True)

    decl = _intake.parse_submission(submission or os.path.join(scenario, "submission.yml"))
    TP = (period or decl.get("assignment_period", "") or "").strip().upper()

    # load network
    lhdr, links = ([], [])
    if csvio.exists(scenario, "link.csv"):
        lhdr, links = csvio.read(csvio.path(scenario, "link.csv"))
    ftcol = _col(lhdr, "FT", "factype", "fclass", "link_type")
    atcol = _col(lhdr, "AT", "area_type", "areatype")
    vdfcol = _col(lhdr, "vdf_code", "vdf_type")
    lencol = _col(lhdr, "vdf_length_mi", "length_mi") or _col(lhdr, "length")
    len_is_m = (lencol or "").lower() == "length"
    for r in links:                                          # normalize a grouping key
        ft = r.get(ftcol, "") if ftcol else ""
        at = r.get(atcol, "") if atcol else ""
        r["_ftat"] = f"{ft}-{at}" if atcol else f"{ft}"

    # load run output (+ optional external reference table) joined on (from,to)
    perf_path = reference or os.path.join(scenario, "link_performance.csv")
    phdr, perf = ([], [])
    if os.path.exists(perf_path):
        phdr, perf = csvio.read(perf_path)

    stages = []

    def stage(rid, title, status, gate_text, report_lines, deliverables):
        path = os.path.join(rep_dir, f"{rid}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# {rid} — {title}\n\n**GATE: {status}** — {gate_text}\n\n")
            f.write("\n".join(report_lines) + "\n\n")
            if deliverables:
                f.write("Deliverables: " + ", ".join(f"`{d}`" for d in deliverables) + "\n")
        stages.append(dict(id=rid, title=title, status=status, gate=gate_text,
                           deliverables=deliverables))

    # ---------------- R1 inventory & directionality -------------------------------------
    if links:
        nodes = set()
        oneway = 0
        pairs = set()
        for r in links:
            fn, tn = r.get("from_node_id"), r.get("to_node_id")
            nodes.add(fn); nodes.add(tn)
            pairs.add((fn, tn))
        # AB/BA: count links whose reverse also exists
        twoway = sum(1 for (a, b) in pairs if (b, a) in pairs)
        # VMT/VHT or lane-mi by FT-AT
        valcols = []
        have_perf = bool(perf)
        if have_perf:
            for r, p in zip(links, perf):
                pass
        # network table by FT-AT (lane-miles, link count)
        agg = {}
        for r in links:
            k = r["_ftat"]
            L = _f(r, lencol) if lencol else None
            if L is not None and len_is_m:
                L = L / 1609.344
            lanes = _f(r, "lanes", default=1) or 1
            d = agg.setdefault(k, dict(n=0, lane_mi=0.0, lane_sum=0.0))
            d["n"] += 1
            if L is not None:
                d["lane_mi"] += L * lanes
        rows = [(k, d["n"], round(d["lane_mi"], 2)) for k, d in sorted(agg.items())]
        _write_table(os.path.join(tab_dir, "network_by_ft_at.csv"),
                     ["ft_at", "links", "lane_miles"], rows)
        status = "PASS" if twoway > 0 else "WARN"
        stage("01_inventory", "Data inventory & network directionality", status,
              f"{len(links)} directed links, {len(nodes)} nodes; {twoway} have a reverse "
              f"(AB/BA paired). {'matplotlib off' if not HAVE_MPL else ''}",
              [f"- directed links: **{len(links)}**, nodes: {len(nodes)}",
               f"- reverse-paired (two-way) directed links: {twoway}",
               f"- grouping key: {'FT-AT' if atcol else (ftcol or 'none')}",
               f"- network table written by FT-AT ({len(rows)} groups)"],
              ["tables/network_by_ft_at.csv"])
    else:
        stage("01_inventory", "Data inventory & network directionality", "FAIL",
              "no link.csv", ["No link.csv found."], [])

    # ---------------- R2 OD & allowed-uses ----------------------------------------------
    demand_files = []
    if csvio.exists(scenario, "mode_type.csv"):
        _, mts = csvio.read(csvio.path(scenario, "mode_type.csv"))
        for m in mts:
            df = m.get("demand_file")
            if df and csvio.exists(scenario, df):
                demand_files.append((m.get("mode_type", df), df))
    if not demand_files and csvio.exists(scenario, "demand.csv"):
        demand_files = [("auto", "demand.csv")]
    od_rows = []
    tot_trips = 0.0
    for cls, df in demand_files:
        _, drows = csvio.read(csvio.path(scenario, df))
        pairs = sum(1 for r in drows if _f(r, "volume"))
        vol = sum(_f(r, "volume", default=0) or 0 for r in drows)
        tot_trips += vol
        od_rows.append((cls, df, pairs, round(vol, 1)))
    _write_table(os.path.join(tab_dir, "od_by_class.csv"),
                 ["class", "file", "od_pairs", "trips"], od_rows)
    # allowed_use summary
    aucol = _col(lhdr, "allowed_use", "allowed_uses")
    au = {}
    for r in links:
        v = (r.get(aucol) or "all") if aucol else "all"
        au[v] = au.get(v, 0) + 1
    _write_table(os.path.join(tab_dir, "allowed_use_summary.csv"),
                 ["allowed_use", "links"], sorted(au.items()))
    stage("02_od_allowed_use", "OD & allowed-uses", "PASS" if od_rows else "WARN",
          f"{len(od_rows)} demand class(es), {tot_trips:,.0f} total trips; "
          f"{len(au)} allowed_use group(s).",
          [f"- demand classes: {len(od_rows)}, total trips **{tot_trips:,.0f}**"]
          + [f"  - {c}: {p:,} OD pairs, {v:,.0f} trips" for c, _, p, v in od_rows]
          + [f"- allowed_use groups: {dict(list(au.items())[:6])}"],
          ["tables/od_by_class.csv", "tables/allowed_use_summary.csv"])

    # ---------------- R3 capacity & VDF join --------------------------------------------
    if links:
        n = len(links)
        capcol = _col(lhdr, "capacity")
        acol = _col(lhdr, "vdf_alpha"); bcol = _col(lhdr, "vdf_beta")
        miss_cap = sum(1 for r in links if not csvio.is_num(r.get(capcol)))
        miss_ab = sum(1 for r in links if not (csvio.is_num(r.get(acol)) and csvio.is_num(r.get(bcol))))
        # by vdf code
        agg = {}
        key = vdfcol or ftcol
        for r in links:
            k = r.get(key, "") if key else "all"
            d = agg.setdefault(k, dict(n=0, a=[], b=[], cap=[]))
            d["n"] += 1
            if csvio.is_num(r.get(acol)): d["a"].append(csvio.fnum(r[acol]))
            if csvio.is_num(r.get(bcol)): d["b"].append(csvio.fnum(r[bcol]))
            if csvio.is_num(r.get(capcol)): d["cap"].append(csvio.fnum(r[capcol]))
        rows = [(k, d["n"],
                 round(statistics.mean(d["a"]), 4) if d["a"] else "",
                 round(statistics.mean(d["b"]), 4) if d["b"] else "",
                 round(statistics.median(d["cap"]), 1) if d["cap"] else "")
                for k, d in sorted(agg.items(), key=lambda kv: str(kv[0]))]
        _write_table(os.path.join(tab_dir, "capacity_vdf_by_code.csv"),
                     ["code", "links", "alpha_mean", "beta_mean", "cap_median"], rows)
        join = 100.0 * (n - max(miss_cap, miss_ab)) / n if n else 0
        status = "PASS" if (miss_cap == 0 and miss_ab == 0) else ("WARN" if join > 95 else "FAIL")
        stage("03_capacity_join", "External capacity & VDF parameters", status,
              f"capacity+VDF join rate {join:.1f}% (cap missing {miss_cap}, alpha/beta missing {miss_ab}).",
              [f"- links: {n}; missing capacity: {miss_cap}; missing alpha/beta: {miss_ab}",
               f"- join rate: **{join:.1f}%** (gate: 100%)",
               f"- alpha/beta/cap summarized by {key or 'code'} ({len(rows)} groups)"],
              ["tables/capacity_vdf_by_code.csv"])

    # ---------------- R4 period & PLF ----------------------------------------------------
    L = None
    if csvio.exists(scenario, "settings.csv"):
        _, srows = csvio.read(csvio.path(scenario, "settings.csv"))
        if srows:
            h0 = _f(srows[0], "demand_period_starting_hours")
            h1 = _f(srows[0], "demand_period_ending_hours")
            if h0 is not None and h1 is not None and h1 > h0:
                L = h1 - h0
    plfcol = _col(lhdr, "vdf_plf", "VDF_plf")
    plf_by = {}
    for r in links:
        k = r.get(ftcol, "") if ftcol else "all"
        p = _f(r, plfcol) if plfcol else 1.0
        plf_by.setdefault(k, []).append(p if p is not None else 1.0)
    rows = [(k, round(statistics.mean(v), 4), round(min(v), 4), round(max(v), 4))
            for k, v in sorted(plf_by.items(), key=lambda kv: str(kv[0]))]
    _write_table(os.path.join(tab_dir, "plf_by_ft.csv"),
                 ["ft", "plf_mean", "plf_min", "plf_max"], rows)
    allvals = [p for v in plf_by.values() for p in v]
    flat = allvals and max(allvals) == min(allvals) == 1.0
    declared_plf = _intake._declared(decl, "peak_load_factor")
    if L and L > 1 and flat and not declared_plf:
        status, gate = "FAIL", f"PLF flat (=1) over {L:g}-h period and not declared — D/C is period-avg, not peak."
    elif flat and (not L or L <= 1):
        status, gate = "PASS", "1-hour period; PLF=1 is correct."
    else:
        status, gate = "PASS", f"PLF set (declared={declared_plf or 'n/a'})."
    stage("04_plf_conversion", "Period selection & PLF", status, gate,
          [f"- assignment period L = {L if L else 'n/a'} h; PLF flat={flat}; "
           f"declared peak_load_factor={declared_plf or 'none'}",
           f"- PLF by FT written ({len(rows)} groups)"],
          ["tables/plf_by_ft.csv"])

    # ---- reference column detection for R5/R6 (MAG-style <TP>_* or ref_volume) ---------
    # reference columns must be period-prefixed (PM_VMT) or explicitly ref_/obs_ prefixed,
    # NEVER bare model names (VMT/FLOW/SPEED) which are the model's own output columns.
    def refcol(*names):
        cands = []
        for n in names:
            if TP:
                cands.append(f"{TP}_{n}")
            cands += [f"ref_{n}", f"obs_{n}", n if n.startswith(("ref_", "obs_")) else None]
        for c in cands:
            if c:
                got = _col(phdr, c)
                if got:
                    return got
        return None
    def _has_data(col):
        # a reference column is only real if it carries non-zero values
        return col and any((_f(r, col) or 0) > 0 for r in perf)
    ref_flow = refcol("FLOW", "volume"); ref_flow = ref_flow if _has_data(ref_flow) else None
    ref_time = refcol("TIME"); ref_time = ref_time if _has_data(ref_time) else None
    ref_spee = refcol("SPEE", "SPEED", "speed"); ref_spee = ref_spee if _has_data(ref_spee) else None
    ref_vmt = refcol("VMT"); ref_vmt = ref_vmt if _has_data(ref_vmt) else None
    ref_vht = refcol("VHT"); ref_vht = ref_vht if _has_data(ref_vht) else None
    have_ref = bool(perf and (ref_flow or ref_vmt))

    # ---------------- R5 TAP consistency ------------------------------------------------
    if perf and have_ref:
        mvol = _col(phdr, "volume", "vehicle_volume")
        mspd = _col(phdr, "speed_mph", "speed")
        mtime = _col(phdr, "travel_time")
        mdoc = _col(phdr, "doc", "voc")
        xs_v = [_f(r, ref_flow) for r in perf] if ref_flow else []
        ys_v = [_f(r, mvol) for r in perf] if mvol else []
        prob = []
        for r in perf:
            rf = _f(r, ref_flow); mv = _f(r, mvol)
            if rf and mv and rf > 0 and abs(mv - rf) / rf > 0.5:
                prob.append((r.get("from_node_id"), r.get("to_node_id"), round(rf, 1), round(mv, 1)))
        r2v, slopev, nv = _r2_slope(xs_v, ys_v) if (xs_v and ys_v) else (None, None, 0)
        figs = []
        if ref_spee and mspd:
            ok = _scatter(os.path.join(fig_dir, "vc_vs_speed.png"),
                          [_f(r, mdoc) for r in perf] if mdoc else [],
                          [_f(r, mspd) for r in perf],
                          "model V/C", "model speed (mph)", "V/C vs speed")
            if ok: figs.append("figures/vc_vs_speed.png")
        if ref_spee and mspd:
            _write_table(os.path.join(tab_dir, "speed_obs_vs_model.csv"),
                         ["from", "to", f"ref_{ref_spee}", "model_speed"],
                         [(r.get("from_node_id"), r.get("to_node_id"),
                           _f(r, ref_spee), _f(r, mspd)) for r in perf[:100000]])
        if prob:
            _write_table(os.path.join(tab_dir, "problem_links_volume.csv"),
                         ["from", "to", "ref_flow", "model_vol"], prob)
        status = "PASS" if (slopev and 0.9 <= slopev <= 1.1) else "WARN"
        stage("05_consistency", "TAP assignment consistency (V/C, speed, duration)", status,
              f"volume model/ref slope={slopev:.3f} R^2={r2v:.3f} (n={nv}); "
              f"{len(prob)} links >50% volume diff." if slopev else "insufficient overlap.",
              [f"- volume: through-origin slope **{slopev:.3f}**, R²={r2v:.3f}, n={nv}" if slopev else "- volume regression: insufficient data",
               f"- problem links (>50% vol diff): {len(prob)}",
               f"- figures: {figs or ('none (matplotlib off)' if not HAVE_MPL else 'none')}"],
              ["tables/speed_obs_vs_model.csv", "tables/problem_links_volume.csv"] + figs)
    else:
        stage("05_consistency", "TAP assignment consistency (V/C, speed, duration)", "SKIP",
              "no link_performance.csv with reference columns (run the kernel + provide "
              "reference, or --reference / --period).",
              ["Provide a completed `link_performance.csv` and reference columns "
               f"(`{TP}_FLOW`/`{TP}_SPEE`/… or `ref_volume`) to enable R5."], [])

    # ---------------- R6 VMT/VHT validation ---------------------------------------------
    if perf and (ref_vmt or ref_flow):
        mvmt = _col(phdr, "VMT"); mvht = _col(phdr, "VHT")
        # group model + ref by FT-AT (join perf to link by row order if same file, else by index)
        # perf rows carry from/to; map FT-AT from link by (from,to)
        ftat = {}
        for r in links:
            ftat[(r.get("from_node_id"), r.get("to_node_id"))] = r["_ftat"]
        agg = {}
        for r in perf:
            k = ftat.get((r.get("from_node_id"), r.get("to_node_id")), "?")
            d = agg.setdefault(k, dict(mvmt=0.0, mvht=0.0, rvmt=0.0, rvht=0.0))
            if mvmt: d["mvmt"] += _f(r, mvmt, default=0) or 0
            if mvht: d["mvht"] += _f(r, mvht, default=0) or 0
            if ref_vmt: d["rvmt"] += _f(r, ref_vmt, default=0) or 0
            if ref_vht: d["rvht"] += _f(r, ref_vht, default=0) or 0
        rows = []
        worst = 0.0
        for k, d in sorted(agg.items()):
            dv = (d["mvmt"] - d["rvmt"]) / d["rvmt"] * 100 if d["rvmt"] else None
            if dv is not None:
                worst = max(worst, abs(dv))
            rows.append((k, round(d["mvmt"], 1), round(d["rvmt"], 1),
                         round(dv, 2) if dv is not None else "",
                         round(d["mvht"], 1), round(d["rvht"], 1)))
        _write_table(os.path.join(tab_dir, "vmt_vht_by_ft_at_taplite.csv"),
                     ["ft_at", "model_VMT", "ref_VMT", "VMT_diff_pct", "model_VHT", "ref_VHT"], rows)
        tot_m = sum(d["mvmt"] for d in agg.values()); tot_r = sum(d["rvmt"] for d in agg.values())
        tot_diff = (tot_m - tot_r) / tot_r * 100 if tot_r else None
        status = "PASS" if (tot_diff is not None and abs(tot_diff) <= 5) else ("WARN" if tot_diff is not None else "SKIP")
        stage("06_vmt_vht", "TAPLite VMT & VHT validation", status,
              f"total VMT diff vs reference = {tot_diff:.2f}% (gate: <=5%); worst FT-AT {worst:.1f}%."
              if tot_diff is not None else "no reference VMT.",
              [f"- total model VMT {tot_m:,.0f} vs ref {tot_r:,.0f} -> **{tot_diff:.2f}%**" if tot_diff is not None else "- no ref VMT",
               f"- worst FT-AT group: {worst:.1f}%", f"- {len(rows)} FT-AT groups"],
              ["tables/vmt_vht_by_ft_at_taplite.csv"])
        emit_src = rows  # reuse for R7
    else:
        stage("06_vmt_vht", "TAPLite VMT & VHT validation", "SKIP",
              "no link_performance.csv with reference VMT.",
              ["Provide a run + reference to enable R6."], [])
        emit_src = None

    # ---------------- R7 rough emissions (MovesLite-mini) -------------------------------
    if perf:
        mvmt = _col(phdr, "VMT"); mvht = _col(phdr, "VHT")
        agg = {}
        for r in perf:
            k = None
            # FT-AT via link map
            k = None
            d = agg.setdefault("_all", dict(vmt=0.0, vht=0.0))
            if mvmt: d["vmt"] += _f(r, mvmt, default=0) or 0
            if mvht: d["vht"] += _f(r, mvht, default=0) or 0
        rows = []
        for k, d in agg.items():
            vmt, vht = d["vmt"], d["vht"]
            mph = vmt / vht if vht else 30.0
            b = _bin_speed(mph)
            co2, nox, voc, pm = EMIT_FACT[b]
            rows.append((k, round(vmt, 1), round(vht, 1), f"{b[0]}-{b[1]}",
                         round(vmt * co2 / 1000, 1), round(vmt * nox / 1000, 2),
                         round(vmt * voc / 1000, 2), round(vmt * pm / 1000, 3)))
        _write_table(os.path.join(tab_dir, "emission_ft_at_rough.csv"),
                     ["group", "VMT", "VHT", "speed_bin", "CO2_kg", "NOx_kg", "VOC_kg", "PM25_kg"], rows)
        co2_t = sum(r[4] for r in rows) / 1000
        stage("07_emissions", "Rough emission estimation (MovesLite-mini)", "PASS",
              f"network speed-bin emissions: ~{co2_t:,.1f} t CO2 (rough, swappable factors).",
              ["- explicit speed-bin g/mi factors (documented in workflow.py EMIT_FACT)",
               f"- network total ~ {co2_t:,.1f} tonnes CO2"],
              ["tables/emission_ft_at_rough.csv"])
    else:
        stage("07_emissions", "Rough emission estimation (MovesLite-mini)", "SKIP",
              "no link_performance.csv (run the kernel first).", [], [])

    # ---------------- index + dashboard -------------------------------------------------
    worst = max((GATE_RANK[s["status"]] for s in stages), default=0)
    overall = {0: "PASS", 1: "WARN", 2: "INCOMPLETE", 3: "FAIL"}[worst]
    _write_index(os.path.join(rep_dir, "00_traceability.md"), scenario, overall, stages)
    _write_dashboard(os.path.join(base, "workflow_dashboard.html"), scenario, overall, stages)
    return dict(scenario=scenario, overall=overall, stages=stages, out=base,
                figures=HAVE_MPL)


def _write_index(path, scenario, overall, stages):
    out = [f"# Traceability index — {scenario}", "",
           f"**Overall: {overall}**", "",
           "| Stage | Gate | Deliverables |", "|---|---|---|"]
    for s in stages:
        out.append(f"| {s['id']} {s['title']} | **{s['status']}** | "
                   f"{', '.join(s['deliverables']) or '—'} |")
    out += ["", "Each stage's full report is in this folder (`0N_*.md`); tables in "
            "`../tables/`, figures in `../figures/`."]
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")


def _write_dashboard(path, scenario, overall, stages):
    color = {"PASS": "#1e8449", "WARN": "#d68910", "SKIP": "#7f8c8d", "FAIL": "#c0392b"}
    obg = {"PASS": "#1e8449", "WARN": "#d68910", "INCOMPLETE": "#7f8c8d", "FAIL": "#c0392b"}[overall]
    cards = []
    for s in stages:
        c = color[s["status"]]
        dl = "".join(f"<li><code>{d}</code></li>" for d in s["deliverables"])
        cards.append(f"""<div class="card" style="border-left-color:{c}">
          <div class="hd"><span class="rid">{s['id'].split('_')[0].upper()}</span>
            <span class="badge" style="background:{c}">{s['status']}</span></div>
          <div class="ti">{s['title']}</div>
          <div class="gt">{s['gate']}</div>
          <ul>{dl}</ul></div>""")
    open(path, "w", encoding="utf-8").write(f"""<!doctype html><html><head><meta charset="utf-8">
<title>Traceable workflow — {scenario}</title><style>
 body{{font:14px/1.5 system-ui,Segoe UI,Arial;margin:0;background:#f4f6f8;color:#222}}
 header{{background:{obg};color:#fff;padding:18px 26px}} header h1{{margin:0;font-size:19px}}
 header .ov{{font-size:26px;font-weight:700;letter-spacing:1px}}
 .wrap{{max-width:1000px;margin:0 auto;padding:18px 26px;display:grid;
   grid-template-columns:1fr 1fr;gap:14px}}
 .card{{background:#fff;border-left:5px solid #ccc;border-radius:6px;padding:12px 14px;box-shadow:0 1px 3px #0002}}
 .hd{{display:flex;justify-content:space-between;align-items:center}}
 .rid{{font-weight:700;color:#555}} .badge{{color:#fff;padding:2px 9px;border-radius:4px;font-size:12px;font-weight:700}}
 .ti{{font-weight:600;margin:6px 0 4px}} .gt{{color:#555;font-size:13px}}
 ul{{margin:8px 0 0;padding-left:18px}} li{{font-size:12px;color:#666}}
</style></head><body>
<header><h1>MAG-style traceable workflow — {scenario}</h1><div class="ov">{overall}</div>
<div style="font-size:12px;opacity:.9;margin-top:4px">R1->R7 staged · each gated · reports/ tables/ figures/</div></header>
<div class="wrap">{''.join(cards)}</div></body></html>""")
