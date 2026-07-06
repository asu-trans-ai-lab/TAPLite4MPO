"""`taplite` -- the friendly analyst-facing front end (third-generation MPO workflow).

This is an ADDITIVE console entry over the existing `python -m dtalite_qa` verbs; it
does not replace them. Four commands, each wrapping pieces that already exist so the
no-guessing intake gate and the reproducibility manifest are inherited, never bypassed:

  taplite validate <scenario>          intake gate + validate/inventory/accessibility
  taplite run <config.yml>             run-config YAML -> gate -> kernel -> manifest -> report
  taplite report <run_dir>             fused self-contained HTML report of a finished run
  taplite compare <run_a> <run_b>      manifest diff + side-by-side MOE table

Everything under `python -m dtalite_qa ...` keeps working unchanged.
"""
import argparse
import json
import os
import subprocess
import sys

from . import control as _control
from . import validate as _validate
from . import inventory as _inventory
from . import accessibility as _accessibility
from . import manifest as _manifest


def _find_manifest(run_dir):
    """Accept either a run folder or a manifest.json path."""
    if os.path.isfile(run_dir) and run_dir.endswith(".json"):
        return run_dir
    p = os.path.join(run_dir, "manifest.json")
    return p if os.path.exists(p) else None


# ---------------------------------------------------------------------------
def cmd_validate(args):
    scenario = args.scenario
    if not os.path.isdir(scenario):
        print(f"scenario folder not found: {scenario}", file=sys.stderr)
        return 2
    print(f"== taplite validate {scenario} ==")
    # 1) the no-guessing intake gate (inherited, non-negotiable)
    ok, status, reason = _control.check_intake_gate(scenario)
    icon = "OK" if ok else "BLOCK"
    print(f"[{icon}] intake gate: {status}" + (f" -- {reason}" if reason else ""))
    if not ok:
        print("  This scenario has NOT declared its data conventions. Run:")
        print(f"    python -m dtalite_qa intake {scenario}")
        print("  fill submission.yml, and re-run. taplite refuses to guess.")
    # 2) schema validation (always shown; useful even when the gate blocks)
    rep = _validate.validate(scenario)
    for w in rep.warnings:
        print(f"  WARN  {w}")
    for e in rep.errors:
        print(f"  ERROR {e}")
    print(f"  schema: {'OK' if rep.ok else 'FAILED'} "
          f"({len(rep.errors)} error(s), {len(rep.warnings)} warning(s))")
    # 3) inventory + accessibility (only if schema is sane)
    worst = 0
    if rep.ok:
        _, worst = _accessibility.render(_accessibility.check(scenario))
        print(f"  accessibility: {'clean' if worst == 0 else 'PROBLEMS'}")
    # exit non-zero if the gate blocks OR schema fails
    return 0 if (ok and rep.ok and worst == 0) else 1


def cmd_run(args):
    from . import runconfig as _runconfig
    cfg_path = args.config
    if not os.path.exists(cfg_path):
        print(f"run-config not found: {cfg_path}", file=sys.stderr)
        return 2
    print(f"== taplite run {cfg_path} ==")
    try:
        res = _runconfig.run(cfg_path, exe=args.exe,
                             do_report=(False if args.no_report else None))
    except FileNotFoundError as e:
        # missing scenario_folder or kernel exe -> not-found, match sibling verbs (exit 2)
        print(f"not found: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        # gate refusal or validation failure surfaces here
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired as e:
        print(f"kernel timed out after {e.timeout}s -- raise assignment.timeout "
              f"in the config", file=sys.stderr)
        return 3
    r = res["result"]
    if r.returncode == "timeout":
        print("kernel timed out -- raise assignment.timeout in the config",
              file=sys.stderr)
        return 3
    gap = r.final_gap_pct()
    spd = (r.moe() or {}).get("mean_speed_mph")
    print(f"  gate: {r.manifest.get('intake_gate')}   iterations: "
          f"{r.manifest.get('convergence', {}).get('iterations')}   "
          f"final gap: {f'{gap}%' if gap is not None else 'n/a'}")
    moe = r.moe() or {}
    print(f"  VMT {moe.get('vmt', 0):,.0f}  VHT {moe.get('vht', 0):,.0f}  "
          f"mean speed {f'{spd} mph' if spd is not None else 'n/a'}  "
          f"loaded {moe.get('loaded_links', 0):,}/{moe.get('links', 0):,}")
    print(f"  run folder : {res['run_dir']}")
    print(f"  manifest   : {os.path.join(res['run_dir'], 'manifest.json')}")
    if res["report_html"]:
        print(f"  report     : {res['report_html']}")
    print(f"  wall time  : {res['wall_seconds']}s")
    return 0 if r.ok else 1


def cmd_report(args):
    from . import report_html as _rh
    run_dir = args.run_dir
    if not os.path.exists(os.path.join(run_dir, "link_performance.csv")):
        print(f"no link_performance.csv in {run_dir} (not a finished run folder)",
              file=sys.stderr)
        return 2
    out = args.out or os.path.join(run_dir, "report.html")
    try:
        path = _rh.build_report(run_dir, out_html=out, project_name=args.name)
    except FileNotFoundError as e:
        print(f"not found: {e}", file=sys.stderr)
        return 2
    print(f"== taplite report {run_dir} ==")
    print(f"  self-contained HTML report -> {path}")
    return 0


def cmd_compare(args):
    ma, mb = _find_manifest(args.run_a), _find_manifest(args.run_b)
    if not ma or not mb:
        miss = args.run_a if not ma else args.run_b
        print(f"no manifest.json for {miss} (run it through `taplite run` first)",
              file=sys.stderr)
        return 2
    try:
        bad = ma
        a = json.load(open(ma, encoding="utf-8"))
        bad = mb
        b = json.load(open(mb, encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"corrupt manifest {bad}: {e}", file=sys.stderr)
        return 2
    d = _manifest.diff_manifests(a, b)
    print(f"== taplite compare ==")
    print(f"  A: {ma}")
    print(f"  B: {mb}")
    print(f"  identical: {d['identical']}")

    # side-by-side MOE table
    ma_moe, mb_moe = a.get("moe") or {}, b.get("moe") or {}
    keys = ["vmt", "vht", "mean_speed_mph", "loaded_links", "links"]
    print("\n  MOE                A               B            delta %")
    print("  " + "-" * 58)
    for k in keys:
        va, vb = ma_moe.get(k), mb_moe.get(k)
        pct = ""
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va:
            pct = f"{(vb - va) / va * 100:+.2f}%"
        fa = f"{va:,.1f}" if isinstance(va, (int, float)) else ("n/a" if va is None else str(va))
        fb = f"{vb:,.1f}" if isinstance(vb, (int, float)) else ("n/a" if vb is None else str(vb))
        print(f"  {k:16} {fa:>14}  {fb:>14}   {pct:>8}")

    # convergence + changed inputs/settings
    ca, cb = a.get("convergence") or {}, b.get("convergence") or {}
    print(f"\n  final gap %      {ca.get('final_gap_pct')} vs {cb.get('final_gap_pct')}")
    print(f"  iterations       {ca.get('iterations')} vs {cb.get('iterations')}")
    if d["files"]:
        print("\n  changed inputs:")
        for n, what in d["files"].items():
            print(f"    {n}: {what}")
    if d["settings"]:
        print("\n  changed settings:")
        for k, v in d["settings"].items():
            print(f"    {k}: {v['a']} -> {v['b']}")
    if not d["files"] and not d["settings"]:
        print("\n  (inputs and settings identical)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="taplite",
        description="TAPLite4MPO workflow front end (validate / run / report / compare). "
                    "Every command inherits the no-guessing intake gate.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("validate", help="intake gate + schema/accessibility check")
    sp.add_argument("scenario")

    sp = sub.add_parser("run", help="run a run-config YAML end-to-end (gate -> kernel -> report)")
    sp.add_argument("config", help="run-config .yml (see configs/*.yml)")
    sp.add_argument("--exe", default=None, help="kernel exe (overrides exe: in the config)")
    sp.add_argument("--no-report", action="store_true", help="skip the HTML report")

    sp = sub.add_parser("report", help="fused self-contained HTML report of a finished run")
    sp.add_argument("run_dir")
    sp.add_argument("--out", default=None, help="output .html (default: <run_dir>/report.html)")
    sp.add_argument("--name", default=None, help="project name shown in the report header")

    sp = sub.add_parser("compare", help="manifest diff + side-by-side MOE of two runs")
    sp.add_argument("run_a", help="run folder or manifest.json")
    sp.add_argument("run_b", help="run folder or manifest.json")

    args = ap.parse_args(argv)
    return {
        "validate": cmd_validate, "run": cmd_run,
        "report": cmd_report, "compare": cmd_compare,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
