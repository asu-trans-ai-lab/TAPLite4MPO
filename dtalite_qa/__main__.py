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
    sp = sub.add_parser("schema")
    sp.add_argument("--out", default=None, help="write field schema JSON to this path")
    sp = sub.add_parser("manifest")
    sp.add_argument("scenario")
    sp.add_argument("--out", default=None, help="default: <scenario>/manifest.json")
    sp.add_argument("--kernel-version", default=None)
    sp = sub.add_parser("report")
    sp.add_argument("run_dir", help="folder with link_performance.csv (+ link.csv, summary log)")
    sp.add_argument("--out", default=None, help="path prefix; writes <prefix>.json and <prefix>.md")
    sp = sub.add_parser("plf")
    sp.add_argument("scenario", help="inventory VDF_plf and flag a flat PLF")
    sp.add_argument("--period", default=None, help="MAG period profile for recommendations: AM/MD/PM/NT")
    sp.add_argument("--hours", type=float, default=None, help="override period length (hours)")
    sp = sub.add_parser("demand-bin")
    sp.add_argument("scenario", help="convert the scenario's demand CSVs to .bin (set demand_format=1)")
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
        import os
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

    if args.cmd == "demand-bin":
        print(f"== demand-bin {args.scenario} ==")
        for df, binp, n in _demandbin.convert_scenario(args.scenario):
            if binp is None:
                print(f"  {df}: {n}")
            else:
                print(f"  {df} -> {binp} ({n:,} pairs)")
        print("set demand_format=1 in settings.csv to read the .bin files")
        return 0

    if args.cmd == "report":
        import os
        rep = _report.build(args.run_dir)
        prefix = args.out or os.path.join(args.run_dir, "run_report")
        open(prefix + ".json", "w", encoding="utf-8").write(json.dumps(rep, indent=2))
        open(prefix + ".md", "w", encoding="utf-8").write(_report.render_md(rep))
        print(f"report written to {prefix}.json and {prefix}.md")
        print(_report.render_md(rep))
        return 0

    if args.cmd == "run":
        print(f"== run {args.scenario} (QA gate -> kernel) ==")
        result = _control.run(args.scenario, exe=args.exe, out_dir=args.out)
        _print_report(result["validate"])
        if not result["ok"]:
            print("ABORTED: validation failed; kernel not run.")
            return 1
        for line in result["fill_log"]:
            print(f"  fill: {line}")
        text, worst = _accessibility.render(result["accessibility"])
        print(text)
        if result.get("ran"):
            print(f"kernel exit={result['returncode']}; outputs in {result['normalized']}")
            return 0 if result["returncode"] == 0 else 1
        return 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
