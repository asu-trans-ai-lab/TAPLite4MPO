"""Run-config YAML driver: one file describes a whole assignment run.

A run-config is the analyst-facing counterpart of the Python API. ``taplite run
baseline.yml`` reads it, sets the solver settings, passes through the no-guessing
intake gate, runs the kernel via the API, writes the reproducibility manifest, and
(optionally) generates the fused HTML report. Nothing here bypasses the gate.

Schema (all keys optional except input.scenario_folder)::

    project_name: Chicago Sketch baseline
    input:
      scenario_folder: kernel/data_sets/03_chicago_sketch
    assignment:
      iterations: 20
      gap_tolerance: 0.01          # convergence_gap_pct (0 = run all iterations)
      processors: 8                # optional
      timeout: 3600                # optional kernel wall-clock limit, seconds (default 1800)
      warm_start_columns: ""       # optional path to a prior route_columns.bin
    output:
      folder: runs/chicago_baseline
      report: true                 # emit report.html next to the run
    exe: cmake_build_rel/DTALite_exe.exe   # optional; --exe overrides
    override: null                 # optional "who/why" to bypass a non-READY gate

Paths in the config are resolved relative to the config file's directory unless
absolute.
"""
import os

from . import api as _api

try:
    import yaml as _yaml
except Exception:                                     # pragma: no cover
    _yaml = None


def load(path):
    """Parse a run-config YAML into a dict (pyyaml if present, else a small parser)."""
    try:
        text = open(path, encoding="utf-8-sig").read()
    except UnicodeDecodeError as e:
        raise ValueError(
            f"{path}: not valid UTF-8 ({e}). Save the config as UTF-8 "
            f"(PowerShell: Out-File -Encoding utf8).") from None
    if _yaml is not None:
        cfg = _yaml.safe_load(text) or {}
    else:
        cfg = _parse_minimal(text)
    if not isinstance(cfg, dict):
        raise ValueError(f"{path}: run-config must be a mapping at top level")
    return cfg


def _resolve(base_dir, p):
    if not p:
        return p
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base_dir, p))


def run(config_path, exe=None, do_report=None):
    """Execute a run-config. Returns a dict:
        {result: api.Result, run_dir, report_html, config, wall_seconds}.

    ``exe`` (from --exe) overrides ``exe:`` in the config. ``do_report`` (True/False)
    overrides ``output.report``.
    """
    import time
    cfg = load(config_path)
    base = os.path.dirname(os.path.abspath(config_path))

    inp = cfg.get("input") or {}
    scenario_folder = _resolve(base, inp.get("scenario_folder"))
    if not scenario_folder or not os.path.isdir(scenario_folder):
        raise FileNotFoundError(
            f"input.scenario_folder not found: {inp.get('scenario_folder')!r} "
            f"(resolved to {scenario_folder})")

    asg = cfg.get("assignment") or {}
    settings = {}
    if "iterations" in asg:
        settings["number_of_iterations"] = asg["iterations"]
    if "gap_tolerance" in asg:
        settings["convergence_gap_pct"] = asg["gap_tolerance"]
    if "processors" in asg:
        settings["number_of_processors"] = asg["processors"]
    if asg.get("warm_start_columns"):
        # resolve relative to the config dir -- the kernel runs in a tempdir,
        # so an unresolved relative path silently cold-starts
        settings["warm_start_columns"] = _resolve(base, asg["warm_start_columns"])
    if "assignment_method" in asg:
        settings["assignment_method"] = asg["assignment_method"]

    out = cfg.get("output") or {}
    out_folder = _resolve(base, out.get("folder"))
    want_report = out.get("report", True) if do_report is None else do_report

    exe_path = exe or _resolve(base, cfg.get("exe")) or "cmake_build_rel/DTALite_exe.exe"
    if not os.path.exists(exe_path):
        raise FileNotFoundError(
            f"kernel exe not found: {exe_path!r}. Build it or pass --exe / set exe: in the config.")

    net = _api.Network.read_gmns(scenario_folder)
    scen = _api.Scenario(net, _api.Demand.from_network(net), settings=settings)

    t0 = time.time()
    kw = {"timeout": int(asg["timeout"])} if asg.get("timeout") else {}
    result = _api.AssignmentEngine().run(scen, exe=exe_path, override=cfg.get("override"), **kw)
    wall = time.time() - t0

    if out_folder:
        result.export(out_folder)

    report_html = None
    if want_report:
        from . import report_html as _rh
        report_html = os.path.join(result.run_dir, "report.html")
        _rh.build_report(result.run_dir, out_html=report_html,
                         project_name=cfg.get("project_name"))

    return {"result": result, "run_dir": result.run_dir, "report_html": report_html,
            "config": cfg, "wall_seconds": round(wall, 1)}


def _parse_minimal(text):
    """Fallback nested parser for a 2-level 'key:' / '  key: value' YAML subset.

    This is a deliberately small, HONEST subset -- it does NOT support YAML block
    lists (``- item``) and raises on encountering one rather than silently dropping
    it. Install pyyaml (``pip install taplite4mpo[runconfig]``) for full YAML.
    """
    root, cur, child_indent = {}, None, None
    for lineno, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.lstrip().startswith("- "):
            raise ValueError(
                f"line {lineno}: YAML block lists ('- item') are not supported by the "
                f"stdlib fallback parser. Install pyyaml (pip install taplite4mpo"
                f"[runconfig]) to use list values.")
        indent = len(raw) - len(raw.lstrip())
        line = _strip_comment(raw).rstrip()
        if ":" not in line:
            continue
        key, _, val = line.strip().partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith(("[", "{")):
            raise ValueError(
                f"line {lineno}: YAML flow collections ('[...]' / '{{...}}') are not "
                f"supported by the stdlib fallback parser. Install pyyaml (pip install "
                f"taplite4mpo[runconfig]) to use them.")
        val = val.strip('"').strip("'")
        if indent == 0:
            if val == "":
                root[key] = cur = {}
            else:
                root[key] = _coerce(val)
                cur = None
            child_indent = None
        elif cur is not None:
            if child_indent is None:
                child_indent = indent
            elif indent > child_indent:
                raise ValueError(
                    f"line {lineno}: nested mappings beyond 2 levels are not supported "
                    f"by the stdlib fallback parser. Install pyyaml (pip install "
                    f"taplite4mpo[runconfig]) to use deeper nesting.")
            cur[key] = _coerce(val)
    return root


def _strip_comment(raw):
    """Strip an inline '#' comment only when it is preceded by whitespace (or starts
    the value), so unquoted values containing '#' (e.g. a color '#ff0') are kept.
    Quoted values (value starts with a quote) are left untouched."""
    if raw.partition(":")[2].strip()[:1] in ('"', "'"):
        return raw
    out, prev_ws = [], True
    for ch in raw:
        if ch == "#" and prev_ws:
            break
        out.append(ch)
        prev_ws = ch in " \t"
    return "".join(out)


def _coerce(v):
    low = v.lower()
    if low in ("null", "none", "~", ""):
        return None
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v
