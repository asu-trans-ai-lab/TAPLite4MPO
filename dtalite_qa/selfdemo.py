"""taplite self-demo -- prove the INSTALLED package end-to-end, in one command.

    taplite self-demo                    # full: bundled Chicago Sketch, all gates
    taplite self-demo --quick            # smallest native smoke (Sioux Falls)
    taplite self-demo --output DIR       # artifact directory (default below)
    taplite self-demo --keep             # keep an existing output directory
    taplite self-demo --json             # machine-readable final summary on stdout
    taplite self-demo --record-baseline  # MAINTAINER ONLY: propose a new golden
                                         # baseline (never happens automatically)

What a normal run proves, in order:
  1. the bundled public Chicago Sketch dataset ships inside the package;
  2. it copies to a writable run directory (never writes in site-packages);
  3. the no-guessing intake gate passes on the declared conventions;
  4. the NATIVE C++ TAPLite kernel actually executes (in-process binding,
     shared library, or subprocess exe -- whatever the install provides);
  5. outputs are schema-valid, finite, and physically sensible;
  6. a reproducibility manifest + HTML report/dashboard are generated;
  7. the metrics match the checked-in golden baseline within tolerances.
Exit code 0 only when every gate passes. Drift or breakage is nonzero.

The golden run is DETERMINISTIC on purpose: standard Frank-Wolfe
(assignment_method=0), one processor, a fixed iteration count and no early
stop -- parallel reduction order and conjugate directions vary across
platforms. This configuration is for regression testing only; it does not
replace the normal high-performance options.

A normal run NEVER writes the baseline. --record-baseline is the explicit
maintainer action, and it announces loudly that repository contents changed.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sys
import time

CASES = {"chicago_sketch": "Chicago Sketch (min. runnable MPO assignment)",
         "sioux_falls": "Sioux Falls (fast kernel smoke)",
         "arc_superzone": "ARC Superzone (MPO-scale workflow demonstration)"}
# per-case golden baseline location (sketch kept at the root for compatibility)
BASELINE_PATH = {"chicago_sketch": "golden_baseline.json",
                 "arc_superzone": "arc_superzone/golden_baseline.json"}
INPUT_FILES = ("node.csv", "link.csv", "demand.csv", "settings.csv",
               "mode_type.csv", "submission.yml", "zone_crosswalk.csv")
# Deterministic golden configuration (see module docstring).
DETERMINISTIC = {"assignment_method": 0, "number_of_processors": 1,
                 "number_of_iterations": 20, "convergence_gap_pct": 0.0,
                 "convergence_consecutive": 99, "route_output": 0,
                 "log_file": 0, "odme_mode": 0}
QUICK_OVERRIDES = dict(DETERMINISTIC, number_of_iterations=5)
BASELINE_NAME = "golden_baseline.json"
GATES = []
CURRENT_CORRIDORS = None   # set per-run for the ARC corridor comparison


def _say(msg=""):
    print(msg, flush=True)


def _gate(name, ok, detail):
    GATES.append({"gate": name, "pass": bool(ok), "detail": detail})
    _say(f"[{'PASS' if ok else 'FAIL'}] {name} -- {detail}")
    return bool(ok)


def _data_root():
    """Package data root, wheel-safe (importlib.resources)."""
    try:
        from importlib.resources import files
        return files("dtalite_qa") / "selfdemo_data"
    except Exception:                      # very old Python: source tree only
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "selfdemo_data")


def _copy_case(case, dest):
    """Copy the bundled scenario out of the package (which may be zipped or
    read-only) into a plain writable directory."""
    os.makedirs(dest, exist_ok=True)
    root = _data_root()
    src = root / case if not isinstance(root, str) else os.path.join(root, case)
    names = []
    if isinstance(root, str):
        names = os.listdir(src)
        for n in names:
            shutil.copy(os.path.join(src, n), os.path.join(dest, n))
    else:
        for entry in src.iterdir():
            names.append(entry.name)
            with entry.open("rb") as f:
                data = f.read()
            with open(os.path.join(dest, entry.name), "wb") as out:
                out.write(data)
    return sorted(names)


def _read_baseline(case="chicago_sketch"):
    root = _data_root()
    parts = BASELINE_PATH.get(case, BASELINE_NAME).split("/")
    try:
        if isinstance(root, str):
            with open(os.path.join(root, *parts), encoding="utf-8") as f:
                return json.load(f)
        node = root
        for part in parts:
            node = node / part
        with node.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _num(v, default=float("nan")):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _structure(run_dir):
    nodes = _rows(os.path.join(run_dir, "node.csv"))
    links = _rows(os.path.join(run_dir, "link.csv"))
    demand = _rows(os.path.join(run_dir, "demand.csv"))
    return {
        "nodes": len(nodes),
        "links": len(links),
        "zones": sum(1 for r in nodes if _num(r.get("zone_id"), 0) >= 1),
        "od_records": len(demand),
        "total_demand": round(sum(_num(r.get("volume"), 0) for r in demand), 6),
    }


def _metrics(run_dir):
    perf = _rows(os.path.join(run_dir, "link_performance.csv"))
    vmt = sum(_num(r.get("VMT"), 0) for r in perf)
    vht = sum(_num(r.get("VHT"), 0) for r in perf)
    vol = sum(_num(r.get("volume"), 0) for r in perf)
    from . import report as _report
    traj = _report.parse_gap(run_dir)
    gap = traj[-1]["gap_pct"] if traj else None
    volumes = {}
    for r in perf:
        lid = r.get("link_id") or f"{r.get('from_node_id')}-{r.get('to_node_id')}"
        volumes[str(lid)] = round(_num(r.get("volume"), 0), 4)
    return {"vmt": round(vmt, 2), "vht": round(vht, 2),
            "total_link_volume": round(vol, 2),
            "final_gap_pct": None if gap is None else round(float(gap), 6),
            "output_links": len(perf)}, volumes, perf


def _check_outputs(run_dir, structure, perf):
    """Gate B: kernel outputs are present, complete, finite, and physical."""
    if not perf:
        return _gate("output checks", False, "link_performance.csv missing or empty")
    problems = []
    if len(perf) != structure["links"]:
        problems.append(f"row count {len(perf)} != links {structure['links']}")
    need = ("volume", "travel_time", "speed_mph", "VMT", "VHT", "doc")
    missing = [c for c in need if c not in perf[0]]
    if missing:
        problems.append("missing columns: " + ",".join(missing))
    bad = fast = 0
    for r in perf:
        v, t, s = _num(r.get("volume")), _num(r.get("travel_time")), _num(r.get("speed_mph"))
        if not (math.isfinite(v) and math.isfinite(t) and math.isfinite(s)):
            bad += 1
        elif v < 0 or t < 0 or s < 0 or s > 500:   # >500 mph = unit blunder
            bad += 1
        elif s > 200:                              # benchmark gateway links: note only
            fast += 1
    if bad:
        problems.append(f"{bad} rows non-finite or physically invalid")
    note = (f"; {fast} gateway links >200 mph (benchmark data artifact, informational)"
            if fast else "")
    return _gate("output checks", not problems,
                 "; ".join(problems) if problems else
                 f"{len(perf)} rows, all required fields finite and physical{note}")


def _compare_golden(baseline, structure, metrics, volumes, input_hashes):
    """Gate C: exact structural checks + tolerance-based numerical checks."""
    if baseline is None:
        return _gate("golden regression", False,
                     "no golden_baseline.json bundled -- a maintainer must run "
                     "`taplite self-demo --record-baseline` and commit it")
    tol = baseline.get("tolerances", {})
    fails, notes = [], []

    for k, want in baseline.get("structure", {}).items():
        got = structure.get(k, metrics.get(k))
        if got != want and not (isinstance(want, float) and
                                abs(_num(got) - want) <= 1e-9 * max(1.0, abs(want))):
            fails.append(f"structure.{k}: {got} != {want}")
    for name, sha in baseline.get("input_sha256", {}).items():
        if input_hashes.get(name) != sha:
            fails.append(f"input {name} hash changed (dataset drift)")

    def rel(name, got, want, t):
        if want in (None, 0):
            return
        d = abs(got - want) / abs(want)
        (fails if d > t else notes).append(f"{name}: {got:g} vs {want:g} "
                                           f"(rel {d:.2e}, tol {t:g})")

    m = baseline.get("metrics", {})
    rel("VMT", metrics["vmt"], m.get("vmt"), tol.get("vmt_relative", 0.001))
    rel("VHT", metrics["vht"], m.get("vht"), tol.get("vht_relative", 0.001))
    rel("total link volume", metrics["total_link_volume"],
        m.get("total_link_volume"), tol.get("total_link_volume_relative", 0.001))
    gap_gate = m.get("final_gap_pct")
    if gap_gate is not None and metrics["final_gap_pct"] is not None:
        worst = max(gap_gate * 1.5, gap_gate + 0.05)
        if metrics["final_gap_pct"] > worst:
            fails.append(f"final gap {metrics['final_gap_pct']}% worse than "
                         f"baseline {gap_gate}% (limit {worst:.3f}%)")

    bt = tol.get("benchmark_link_relative", 0.005)
    for lid, want in baseline.get("benchmark_links", {}).items():
        got = volumes.get(str(lid))
        if got is None:
            fails.append(f"benchmark link {lid} absent from output")
        elif want and abs(got - want) / abs(want) > bt and abs(got - want) > 1.0:
            fails.append(f"benchmark link {lid}: {got:g} vs {want:g}")

    ct = tol.get("corridor_volume_relative", 0.01)
    for cname, want in baseline.get("corridor_volumes", {}).items():
        got = (CURRENT_CORRIDORS or {}).get(cname)
        if got is None:
            fails.append(f"corridor {cname} not extracted")
        elif want and abs(got - want) / abs(want) > ct:
            fails.append(f"corridor {cname}: {got:,.0f} vs {want:,.0f}")

    base_vol = baseline.get("link_volumes", {})
    if base_vol:
        tot = sum(abs(v) for v in base_vol.values()) or 1.0
        l1 = sum(abs(volumes.get(k, 0.0) - v) for k, v in base_vol.items()) / tot
        if l1 > tol.get("normalized_l1_volume", 0.001):
            fails.append(f"normalized L1 volume error {l1:.2e} > "
                         f"{tol.get('normalized_l1_volume', 0.001):g}")
        else:
            notes.append(f"normalized L1 volume error {l1:.2e}")

    detail = "; ".join(fails) if fails else \
        f"all structural + numerical checks within tolerance ({'; '.join(notes[:3])})"
    return _gate("golden regression", not fails, detail)


def _dashboard(outdir, case, structure, metrics, baseline, run_seconds,
               kernel_via, extra_html=""):
    """One self-contained HTML: Run / Trust / Reproduce panels + gate table."""
    rows = "".join(
        f"<tr class={'p' if g['pass'] else 'f'}><td>{g['gate']}</td>"
        f"<td>{'PASS' if g['pass'] else 'FAIL'}</td><td>{g['detail']}</td></tr>"
        for g in GATES)
    bm = (baseline or {}).get("metrics", {})

    def mrow(name, got, want):
        return (f"<tr><td>{name}</td><td>{got}</td><td>{want if want is not None else '-'}"
                f"</td></tr>")
    mtab = "".join([mrow("VMT", metrics["vmt"], bm.get("vmt")),
                    mrow("VHT", metrics["vht"], bm.get("vht")),
                    mrow("total link volume", metrics["total_link_volume"],
                         bm.get("total_link_volume")),
                    mrow("final gap %", metrics["final_gap_pct"],
                         bm.get("final_gap_pct"))])
    ok = all(g["pass"] for g in GATES)
    html = f"""<meta charset="utf-8"><title>TAPLite4MPO self-demo</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;max-width:960px}}
h1{{font-size:22px}} .badge{{display:inline-block;padding:4px 14px;border-radius:6px;
color:#fff;background:{'#1e8449' if ok else '#c0392b'};font-weight:700}}
table{{border-collapse:collapse;margin:10px 0 22px}} td,th{{border:1px solid #ccc;
padding:4px 10px;font-size:14px}} tr.p td:nth-child(2){{color:#1e8449;font-weight:700}}
tr.f td:nth-child(2){{color:#c0392b;font-weight:700}} .k{{color:#666}}</style>
<h1>TAPLite4MPO self-demo <span class="badge">{'PASS' if ok else 'FAIL'}</span></h1>
<h2>Run</h2><table>
<tr><td class="k">dataset</td><td>{CASES.get(case, case)}</td></tr>
<tr><td class="k">kernel execution</td><td>{kernel_via}</td></tr>
<tr><td class="k">duration</td><td>{run_seconds:.1f} s (informational, never a gate)</td></tr>
<tr><td class="k">deterministic config</td><td>FW (assignment_method=0), 1 processor,
{DETERMINISTIC['number_of_iterations']} fixed iterations</td></tr></table>
<h2>Trust</h2><table>
<tr><td class="k">nodes / links / zones / OD</td><td>{structure['nodes']} /
{structure['links']} / {structure['zones']} / {structure['od_records']}</td></tr>
<tr><td class="k">total input demand</td><td>{structure['total_demand']}</td></tr></table>
<h2>Reproduce -- current vs golden</h2>
<table><tr><th>metric</th><th>this run</th><th>golden</th></tr>{mtab}</table>
<h2>Gates</h2><table><tr><th>gate</th><th>status</th><th>detail</th></tr>{rows}</table>
{extra_html}
<p>Deep run report: <a href="run/report.html">run/report.html</a> (convergence plot,
V/C and volume distributions, most-congested links) -- manifest:
<a href="run/manifest.json">run/manifest.json</a></p>"""
    p = os.path.join(outdir, "selfdemo_dashboard.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(html)
    return p


def run_selfdemo(case="chicago_sketch", output=None, keep=False, quick=False,
                 record_baseline=False, as_json=False, rebuild_superzones=False):
    del GATES[:]
    t0 = time.time()
    case = "sioux_falls" if quick else case
    if rebuild_superzones and case == "arc_superzone":
        src = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "examples", "arc_atlanta", "gmns")
        if not os.path.isdir(src):
            _say("--rebuild-superzones needs a repository checkout (the full "
                 "6,031-zone ARC source is not shipped in the wheel); using the "
                 "checked-in deterministic fixture instead.")
        else:
            from . import selfdemo_arc
            _say("rebuilding the superzone fixture from examples/arc_atlanta/gmns ...")
            selfdemo_arc.build_fixture(src, os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "selfdemo_data", "arc_superzone"))
    outdir = os.path.abspath(output or os.environ.get("TAPLITE_SELFDEMO_OUT")
                             or "taplite_selfdemo_output")
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.commonprefix([outdir, pkg_dir]) == pkg_dir:
        _say("refusing to write inside the installed package; choose --output")
        return 2
    if os.path.isdir(outdir) and not keep:
        shutil.rmtree(outdir)
    run_dir = os.path.join(outdir, "run")
    os.makedirs(run_dir, exist_ok=True)

    _say(f"== TAPLite4MPO self-demo: {CASES.get(case, case)} ==")
    _say(f"artifacts: {outdir}\n")

    # 1-2) bundled data -> writable input/ + run/ copies
    try:
        names = _copy_case(case, os.path.join(outdir, "input"))
        _copy_case(case, run_dir)
        _gate("bundled data", True, f"{len(names)} files from the installed package")
    except Exception as exc:
        _gate("bundled data", False, f"cannot locate/copy package data: {exc}")
        return _finish(outdir, case, t0, as_json)
    input_hashes = {n: _sha256(os.path.join(run_dir, n))
                    for n in INPUT_FILES if os.path.exists(os.path.join(run_dir, n))}

    # 3) the no-guessing intake gate (full case only; quick is a kernel smoke)
    if not quick:
        try:
            from . import intake as _intake
            s = _intake.run_intake(run_dir)
            ready = s["gate"] == "READY"
            _gate("intake gate", ready,
                  "GATE: READY (0 blockers)" if ready else
                  f"GATE: {s['gate']} -- see {run_dir}/intake_dashboard.html")
            if not ready:
                return _finish(outdir, case, t0, as_json)
        except Exception as exc:
            _gate("intake gate", False, f"intake crashed: {exc}")
            return _finish(outdir, case, t0, as_json)

    # 3b) ARC-specific fixture stages (crosswalk, conservation, connectivity)
    if case == "arc_superzone":
        from . import selfdemo_arc
        arc_ok = True
        for name, ok_, detail in selfdemo_arc.validate_fixture(run_dir):
            arc_ok = _gate(name, ok_, detail) and arc_ok
        if not arc_ok:
            return _finish(outdir, case, t0, as_json)

    # 4) the NATIVE kernel, deterministic configuration
    try:
        import pytaplite
        if case == "arc_superzone":
            from . import selfdemo_arc
            overrides = selfdemo_arc.DETERMINISTIC
        else:
            overrides = QUICK_OVERRIDES if quick else DETERMINISTIC
        r = pytaplite.assign(run_dir, settings_overrides=dict(overrides))
        via = ("in-process" if "in-process" in (r.log or "") else "subprocess exe")
        _gate("native assignment", r.returncode == 0,
              f"kernel rc={r.returncode} via {via}")
        if r.returncode != 0:
            return _finish(outdir, case, t0, as_json)
    except FileNotFoundError as exc:
        _gate("native assignment", False, str(exc).splitlines()[0])
        return _finish(outdir, case, t0, as_json)

    # 5) output gate + MOEs
    structure = _structure(run_dir)
    if case == "arc_superzone":
        try:
            with open(os.path.join(run_dir, "build_report.json"),
                      encoding="utf-8") as f:
                _brep = json.load(f)
            structure["superzones"] = _brep["superzones"]
            structure["original_zones"] = _brep["original_zones"]
        except (OSError, ValueError, KeyError):
            pass
    metrics, volumes, perf = _metrics(run_dir)
    if not _check_outputs(run_dir, structure, perf):
        return _finish(outdir, case, t0, as_json)

    # 6) manifest + deep report (reuse the existing layers)
    try:
        from . import manifest as _manifest, report_html as _report_html
        man = _manifest.build_run_manifest(run_dir, scenario=run_dir)
        man["selfdemo"] = {"case": case, "package_version": _pkg_version()}
        with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(man, f, indent=1, default=str)
        _report_html.build_report(run_dir, out_html=os.path.join(run_dir, "report.html"),
                                  project_name=f"self-demo {case}")
        _gate("manifest + report", True, "manifest.json + report.html written")
    except Exception as exc:
        _gate("manifest + report", False, f"{exc}")

    # 6b) corridor volumes (ARC case): stable link_id pins
    corridors = None
    if case == "arc_superzone":
        from . import selfdemo_arc
        try:
            corridors = selfdemo_arc.corridor_volumes(run_dir)
            _gate("corridor extraction", True,
                  "; ".join(f"{k}={v:,.0f}" for k, v in sorted(corridors.items())))
        except Exception as exc:
            _gate("corridor extraction", False, str(exc))

    # 7) golden regression (full case only) -- NEVER auto-recorded
    baseline = _read_baseline(case) if not quick else None
    if record_baseline:
        proposed = {
            "schema_version": 1, "case": case,
            "configuration": {k: DETERMINISTIC[k] for k in
                              ("assignment_method", "number_of_processors",
                               "number_of_iterations")},
            "structure": dict(structure, output_links=metrics["output_links"]),
            "metrics": {k: metrics[k] for k in
                        ("vmt", "vht", "total_link_volume", "final_gap_pct")},
            "benchmark_links": dict(sorted(volumes.items(),
                                           key=lambda kv: -kv[1])[:5]),
            "link_volumes": volumes,
            "tolerances": {"vmt_relative": 0.001, "vht_relative": 0.001,
                           "total_link_volume_relative": 0.001,
                           "benchmark_link_relative": 0.005,
                           "normalized_l1_volume": 0.001},
            "input_sha256": input_hashes,
            "package_version": _pkg_version(),
        }
        if corridors:
            proposed["corridor_volumes"] = corridors
            proposed["tolerances"].update({"corridor_volume_relative": 0.01,
                                           "vmt_relative": 0.0025,
                                           "vht_relative": 0.0025,
                                           "total_link_volume_relative": 0.0025,
                                           "normalized_l1_volume": 0.005})
            try:
                with open(os.path.join(run_dir, "build_report.json"),
                          encoding="utf-8") as f:
                    brep = json.load(f)
                proposed["structure"]["superzones"] = brep["superzones"]
                proposed["structure"]["original_zones"] = brep["original_zones"]
                proposed["crosswalk_sha256"] = brep["crosswalk_sha256"]
                proposed["intrazonal_demand"] = brep["intrazonal_demand"]
            except (OSError, ValueError, KeyError):
                pass
        target = os.path.join(pkg_dir, "selfdemo_data",
                              *BASELINE_PATH.get(case, BASELINE_NAME).split("/"))
        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(proposed, f, indent=1, sort_keys=True)
            _say("\n*** MAINTAINER ACTION: golden baseline WRITTEN to the package "
                 f"source tree:\n***   {target}\n*** Repository contents changed -- "
                 "review the metrics above and commit deliberately.")
        except OSError:
            alt = os.path.join(outdir, BASELINE_NAME)
            with open(alt, "w", encoding="utf-8") as f:
                json.dump(proposed, f, indent=1, sort_keys=True)
            _say(f"\n*** package dir is read-only; proposed baseline written to {alt}"
                 "\n*** copy it into dtalite_qa/selfdemo_data/ in the repo and commit.")
        _gate("golden regression", True, "baseline recorded (maintainer mode)")
    elif not quick:
        global CURRENT_CORRIDORS
        CURRENT_CORRIDORS = corridors
        _compare_golden(baseline, structure, metrics, volumes, input_hashes)

    return _finish(outdir, case, t0, as_json, structure, metrics,
                   baseline=baseline)


def _pkg_version():
    try:
        from importlib.metadata import version
        return version("taplite4mpo")
    except Exception:
        return "source-tree"


def _arc_extra_html(outdir):
    """Panel A (compression) + Panel B (superzone map) for the ARC case."""
    run_dir = os.path.join(outdir, "run")
    try:
        with open(os.path.join(run_dir, "build_report.json"), encoding="utf-8") as f:
            rep_ = json.load(f)
        from . import selfdemo_arc
        svg = selfdemo_arc.svg_map(run_dir)
        rows = "".join(
            f"<tr><td class=k>{k.replace('_', ' ')}</td><td>{v}</td></tr>"
            for k, v in (("original zones", rep_["original_zones"]),
                         ("superzones", rep_["superzones"]),
                         ("compression ratio", f"{rep_['compression_ratio']}x"),
                         ("original OD pairs", f"{rep_['original_od_pairs']:,}"),
                         ("aggregated OD pairs", f"{rep_['aggregated_od_pairs']:,}"),
                         ("total demand (original)",
                          f"{rep_['total_demand_original']:,.0f}"),
                         ("network-loaded demand",
                          f"{rep_['total_demand_aggregated']:,.0f}"),
                         ("intrazonal (audited, excluded)",
                          f"{rep_['intrazonal_demand']:,.0f} "
                          f"({rep_['intrazonal_share_pct']}%)"),
                         ("demand conserved",
                          rep_["demand_conserved_machine_precision"])))
        return (f"<h2>Model compression (superzoning)</h2><table>{rows}</table>"
                "<h2>Superzone map -- recognizable ARC freeway network</h2>"
                "<p class=k>Freeways/ramps colored and scaled by assigned volume; "
                "green dots are the superzone centroids. This superzone model is a "
                "computational demonstration and QA case, NOT a replacement for "
                "the production ARC model.</p>" + svg)
    except Exception as exc:
        return f"<p class=k>(ARC panels unavailable: {exc})</p>"


def _finish(outdir, case, t0, as_json, structure=None, metrics=None,
            baseline=None):
    ok = all(g["pass"] for g in GATES)
    try:
        extra = _arc_extra_html(outdir) if case == "arc_superzone" else ""
        _dashboard(outdir, case,
                   structure or {"nodes": "-", "links": "-", "zones": "-",
                                 "od_records": "-", "total_demand": "-"},
                   metrics or {"vmt": "-", "vht": "-", "total_link_volume": "-",
                               "final_gap_pct": "-"},
                   baseline, time.time() - t0, "native kernel", extra_html=extra)
    except Exception:
        pass
    summary = {"case": case, "pass": ok, "gates": GATES,
               "structure": structure, "metrics": metrics,
               "runtime_seconds": round(time.time() - t0, 1),
               "package_version": _pkg_version(),
               "artifacts": {"dashboard": os.path.join(outdir, "selfdemo_dashboard.html"),
                             "summary": os.path.join(outdir, "selfdemo_summary.json")}}
    try:
        with open(os.path.join(outdir, "selfdemo_summary.json"), "w",
                  encoding="utf-8") as f:
            json.dump(summary, f, indent=1)
        with open(os.path.join(outdir, "selfdemo_summary.md"), "w",
                  encoding="utf-8") as f:
            f.write(f"# TAPLite4MPO self-demo: {'PASS' if ok else 'FAIL'}\n\n" +
                    "".join(f"- {'PASS' if g['pass'] else 'FAIL'} {g['gate']} -- "
                            f"{g['detail']}\n" for g in GATES))
    except OSError:
        pass
    _say(f"\nTAPLite4MPO self-demo: {'PASS' if ok else 'FAIL'}")
    for g in GATES:
        _say(f"  {g['gate']}: {'PASS' if g['pass'] else 'FAIL'}")
    _say(f"\nArtifacts:\n  {summary['artifacts']['dashboard']}\n"
         f"  {summary['artifacts']['summary']}")
    if as_json:
        _say(json.dumps(summary))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="taplite self-demo",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--case", default="chicago-sketch",
                    choices=["chicago-sketch", "arc-superzone"],
                    help="chicago-sketch: fast deterministic regression (default); "
                         "arc-superzone: MPO-scale workflow demonstration")
    ap.add_argument("--output", default=None)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--record-baseline", action="store_true")
    ap.add_argument("--rebuild-superzones", action="store_true")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    return run_selfdemo(case=a.case.replace("-", "_"), output=a.output,
                        keep=a.keep, quick=a.quick,
                        record_baseline=a.record_baseline, as_json=a.as_json,
                        rebuild_superzones=a.rebuild_superzones)


if __name__ == "__main__":
    sys.exit(main())
