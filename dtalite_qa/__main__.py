"""CLI:  python -m dtalite_qa <command> <scenario> [options]

commands:
  validate <scenario>                 validate inputs (errors/warnings)
  fill     <scenario> --out <dir>     write a normalized copy (defaults filled, links sorted)
  inventory <scenario>                allowed_use / network inventory
  accessibility <scenario>            per-mode connectivity check
  check    <scenario>                 validate + inventory + accessibility (no fill)
  run      <scenario> --exe <exe>     full QA gate then run the kernel on the normalized scenario
"""
import argparse
import json
import os
import sys

from . import validate as _validate
from . import fill as _fill
from . import inventory as _inventory
from . import accessibility as _accessibility
from . import control as _control
from . import manifest as _manifest
from . import report as _report
from . import demandbin as _demandbin
from . import adapt as _adapt
from . import plf as _plf
from . import intake as _intake
from . import workflow as _workflow
from . import guide as _guide


def _print_report(rep):
    for w in rep.warnings:
        print(f"  WARN  {w}")
    for e in rep.errors:
        print(f"  ERROR {e}")
    print(f"{'OK' if rep.ok else 'FAILED'}: {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dtalite_qa")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "inventory", "accessibility", "check"):
        sp = sub.add_parser(name)
        sp.add_argument("scenario")
    sp = sub.add_parser("fill")
    sp.add_argument("scenario")
    sp.add_argument("--out", required=True)
    sp = sub.add_parser("run")
    sp.add_argument("scenario")
    sp.add_argument("--exe", required=True)
    sp.add_argument("--out", default=None)
    sp.add_argument("--override", default=None, metavar="WHO_WHY",
                    help="bypass a non-READY intake gate; recorded in the run manifest")
    sp.add_argument("--no-gate", action="store_true",
                    help="skip the intake-gate check entirely (legacy behavior)")
    sp = sub.add_parser("diff")
    sp.add_argument("manifest_a", help="manifest.json of run A")
    sp.add_argument("manifest_b", help="manifest.json of run B")
    sp = sub.add_parser("schema")
    sp.add_argument("--out", default=None, help="write field schema JSON to this path")
    sp = sub.add_parser("manifest")
    sp.add_argument("scenario")
    sp.add_argument("--out", default=None, help="default: <scenario>/manifest.json")
    sp.add_argument("--kernel-version", default=None)
    sp = sub.add_parser("report")
    sp.add_argument("run_dir", help="folder with link_performance.csv (+ link.csv, summary log)")
    sp.add_argument("--out", default=None, help="path prefix; writes <prefix>.json and <prefix>.md")
    sp = sub.add_parser("report-html")
    sp.add_argument("run_dir", help="finished run folder (link_performance.csv + manifest.json)")
    sp.add_argument("--out", default=None, help="output .html (default: <run_dir>/report.html)")
    sp.add_argument("--name", default=None, help="project name in the report header")
    sp = sub.add_parser("plf")
    sp.add_argument("scenario", help="inventory VDF_plf and flag a flat PLF")
    sp.add_argument("--period", default=None, help="MAG period profile for recommendations: AM/MD/PM/NT")
    sp.add_argument("--hours", type=float, default=None, help="override period length (hours)")
    sp = sub.add_parser("columns")
    sp.add_argument("run_dir", help="folder with route_columns.bin (DTAC), link_performance.csv, mode_type.csv + demand CSVs")
    sp.add_argument("--dtac", default=None, help="explicit DTAC path (default: <run_dir>/route_columns.bin)")
    sp = sub.add_parser("resources")
    sp.add_argument("scenario", help="GMNS scenario to size for a memory-safe number_of_processors")
    sp.add_argument("--requested", type=int, default=None, help="cap the recommendation at this many processors")
    sp.add_argument("--columns", action="store_true", help="account for a column_output run (larger footprint)")
    sp = sub.add_parser("demand-bin")
    sp.add_argument("scenario", help="convert the scenario's demand CSVs to .bin (set demand_format=1)")
    sp = sub.add_parser("forensics")
    sp.add_argument("scenario", help="detect data conventions / issues before any conversion")
    sp.add_argument("--quick", action="store_true", help="skip large-file line counts")
    sp.add_argument("--out", default=None, help="also write the report JSON here")
    sp = sub.add_parser("tools")
    sp.add_argument("--out", default=None, help="write the agent tool manifest JSON here")
    sp = sub.add_parser("intake")
    sp.add_argument("scenario", help="GMNS scenario to run the MPO data-intake audit on")
    sp.add_argument("--submission", default=None, help="declaration file (default: <scenario>/submission.yml)")
    sp.add_argument("--out", default=None, help="output dir for intake_log.md / _issues.json / _dashboard.html")
    sp = sub.add_parser("guide")
    sp.add_argument("--out", default="onboarding_guide.html", help="output HTML path")
    sp = sub.add_parser("workflow")
    sp.add_argument("scenario", help="GMNS scenario to run the staged traceable workflow (R1-R7) on")
    sp.add_argument("--reference", default=None, help="link_performance/link CSV carrying reference columns (default: <scenario>/link_performance.csv)")
    sp.add_argument("--period", default=None, help="reference column period prefix, e.g. PM -> PM_FLOW/PM_VMT")
    sp.add_argument("--submission", default=None, help="declaration file (default: <scenario>/submission.yml)")
    sp.add_argument("--out", default=None, help="output dir (default: <scenario>/traceability)")
    sp = sub.add_parser("adapt")
    sp.add_argument("scenario", help="older/foreign GMNS scenario to convert to current format")
    sp.add_argument("--out", required=True)
    sp.add_argument("--free-speed", default="mph", choices=["mph", "kmph"])
    sp.add_argument("--length", default="mi", choices=["mi", "m"])
    sp.add_argument("--no-filter-demand", action="store_true",
                    help="keep OD pairs whose zones are absent from node.csv (default: drop them)")
    sp.add_argument("--mag-vdf-2015", action="store_true",
                    help="overwrite vdf_alpha/beta/free_speed with the calibrated MAG New-2015 table by vdf_code")
    args = ap.parse_args(argv)

    if args.cmd == "validate":
        rep = _validate.validate(args.scenario)
        print(f"== validate {args.scenario} ==")
        _print_report(rep)
        return 0 if rep.ok else 1

    if args.cmd == "fill":
        log = _fill.fill(args.scenario, args.out)
        print(f"== fill {args.scenario} -> {args.out} ==")
        for line in log:
            print(f"  {line}")
        print(f"normalized scenario written to {args.out} ({len(log)} change(s))")
        return 0

    if args.cmd == "inventory":
        print(f"== inventory {args.scenario} ==")
        print(_inventory.render(_inventory.build(args.scenario)))
        return 0

    if args.cmd == "accessibility":
        print(f"== accessibility {args.scenario} ==")
        text, worst = _accessibility.render(_accessibility.check(args.scenario))
        print(text)
        return 0 if worst == 0 else 1

    if args.cmd == "check":
        print(f"== check {args.scenario} ==")
        rep = _validate.validate(args.scenario)
        _print_report(rep)
        if not rep.ok:
            return 1
        print("\n-- inventory --")
        print(_inventory.render(_inventory.build(args.scenario)))
        print("\n-- accessibility --")
        text, worst = _accessibility.render(_accessibility.check(args.scenario))
        print(text)
        return 0 if worst == 0 else 1

    if args.cmd == "schema":
        text = json.dumps(_manifest.field_schema(), indent=2)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
            print(f"field schema written to {args.out}")
        else:
            print(text)
        return 0

    if args.cmd == "manifest":
        man = _manifest.build_manifest(args.scenario, kernel_version=args.kernel_version)
        out = args.out or os.path.join(args.scenario, "manifest.json")
        open(out, "w", encoding="utf-8").write(json.dumps(man, indent=2))
        print(f"manifest written to {out} ({len(man['files'])} files)")
        return 0

    if args.cmd == "plf":
        print(f"== plf {args.scenario} ==")
        phi = _plf.MAG_PHI.get((args.period or "").upper()) if args.period else None
        hours = args.hours or (_plf.PERIOD_HOURS.get((args.period or "").upper()) if args.period else None)
        rep = _plf.check(args.scenario, period_hours=hours, phi_profile=phi)
        print(_plf.render(rep))
        return 0 if not rep["flat"] else 1

    if args.cmd == "adapt":
        print(f"== adapt {args.scenario} -> {args.out} ==")
        rep = _adapt.adapt(args.scenario, args.out, args.free_speed, args.length,
                           do_filter_demand=not args.no_filter_demand,
                           mag_vdf_2015=args.mag_vdf_2015)
        for line in rep:
            print(f"  {line}")
        print(f"current-format scenario written to {args.out}; validate it with: "
              f"python -m dtalite_qa validate {args.out}")
        return 0

    if args.cmd == "columns":
        from . import columns as _columns
        print(f"== columns {args.run_dir} ==")
        rep = _columns.verify(args.run_dir, dtac_path=args.dtac)
        print(_columns.render(rep))
        return 0

    if args.cmd == "resources":
        from . import resources as _res
        txt, _n, _info = _res.report(args.scenario, requested=args.requested,
                                     with_columns=args.columns)
        print(txt)
        return 0

    if args.cmd == "demand-bin":
        print(f"== demand-bin {args.scenario} ==")
        for df, binp, n in _demandbin.convert_scenario(args.scenario):
            if binp is None:
                print(f"  {df}: {n}")
            else:
                print(f"  {df} -> {binp} ({n:,} pairs)")
        print("set demand_format=1 in settings.csv to read the .bin files")
        return 0

    if args.cmd == "forensics":
        from . import forensics as _forensics
        rep = _forensics.run(args.scenario, quick=args.quick)
        print(_forensics.render(rep))
        if args.out:
            open(args.out, "w", encoding="utf-8").write(json.dumps(rep, indent=2))
            print(f"\nreport JSON written to {args.out}")
        return 1 if rep["counts"]["BLOCK"] else 0

    if args.cmd == "tools":
        from . import agent_tools as _agent_tools
        text = _agent_tools.manifest()
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
            print(f"agent tool manifest written to {args.out}")
        else:
            print(text)
        return 0

    if args.cmd == "intake":
        print(f"== intake {args.scenario} ==")
        s = _intake.run_intake(args.scenario, submission=args.submission, out_dir=args.out)
        c = s["counts"]
        for i in s["issues"]:
            print(f"  {i['severity']:8} {i['field']:24} {i['message']}")
        od = args.out or args.scenario
        print(f"\nGATE: {s['gate']}  ({c['BLOCKER']} blocker, {c['DECISION']} decision, "
              f"{c['MISSING']} missing)")
        print(f"  -> {od}/intake_dashboard.html  (open it, fill submission.yml, re-run)")
        print(f"  -> {od}/intake_log.md   {od}/intake_issues.json")
        return 0 if s["gate"] == "READY" else 1

    if args.cmd == "guide":
        out = _guide.write(args.out)
        print(f"onboarding guide written to {out}")
        print("open it in a browser — the staged journey (GIS map -> declare -> convert -> "
              "intake -> quality -> run -> traceable workflow), each gated.")
        return 0

    if args.cmd == "workflow":
        print(f"== workflow {args.scenario} ==")
        s = _workflow.run_workflow(args.scenario, reference=args.reference, period=args.period,
                                   submission=args.submission, out_dir=args.out)
        for st in s["stages"]:
            print(f"  {st['status']:5} {st['id']:20} {st['gate']}")
        print(f"\nOVERALL: {s['overall']}   (figures: {'on' if s['figures'] else 'off (no matplotlib)'})")
        print(f"  -> {s['out']}/workflow_dashboard.html")
        print(f"  -> {s['out']}/reports/00_traceability.md")
        return 0 if s["overall"] in ("PASS", "WARN", "INCOMPLETE") else 1

    if args.cmd == "report":

        rep = _report.build(args.run_dir)
        prefix = args.out or os.path.join(args.run_dir, "run_report")
        open(prefix + ".json", "w", encoding="utf-8").write(json.dumps(rep, indent=2))
        open(prefix + ".md", "w", encoding="utf-8").write(_report.render_md(rep))
        print(f"report written to {prefix}.json and {prefix}.md")
        print(_report.render_md(rep))
        return 0

    if args.cmd == "run":
        print(f"== run {args.scenario} (QA gate -> kernel) ==")
        result = _control.run(args.scenario, exe=args.exe, out_dir=args.out,
                              override=args.override,
                              enforce_intake=not args.no_gate)
        if result.get("gate_refusal"):
            print(f"INTAKE GATE {result['intake_gate']}: {result['gate_refusal']}")
            print("  (use --override \"who/why\" to bypass -- it will be recorded, "
                  "or --no-gate for legacy behavior)")
            return 1
        if result.get("intake_gate") and result["intake_gate"] != "READY":
            print(f"INTAKE GATE {result['intake_gate']} -- OVERRIDDEN: {result['override']}")
        _print_report(result["validate"])
        if not result["ok"]:
            print("ABORTED: validation failed; kernel not run.")
            return 1
        for line in result["fill_log"]:
            print(f"  fill: {line}")
        text, worst = _accessibility.render(result["accessibility"])
        print(text)
        if result.get("ran"):
            # M1: emit the run manifest next to the outputs
            import datetime as _dt
            man = _manifest.build_run_manifest(
                result["normalized"], scenario=args.scenario, exe=args.exe,
                override=result.get("override"), intake_gate=result.get("intake_gate"),
                created=_dt.datetime.now().isoformat(timespec="seconds"))
            mp = os.path.join(result["normalized"], "manifest.json")
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(man, f, indent=1)
            print(f"kernel exit={result['returncode']}; outputs in {result['normalized']}")
            print(f"run manifest: {mp}")
            return 0 if result["returncode"] == 0 else 1
        return 1

    if args.cmd == "report-html":
        from . import report_html as _report_html
        out = _report_html.build_report(args.run_dir, out_html=args.out, project_name=args.name)
        print(f"self-contained HTML report -> {out}")
        return 0

    if args.cmd == "diff":
        a = json.load(open(args.manifest_a, encoding="utf-8"))
        b = json.load(open(args.manifest_b, encoding="utf-8"))
        d = _manifest.diff_manifests(a, b)
        print(json.dumps(d, indent=1))
        return 0 if d["identical"] else 2

    return 2


if __name__ == "__main__":
    sys.exit(main())
