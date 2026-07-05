"""Orchestration: the QA gate that 'controls' a kernel run.

prepare()  validate -> (optionally) fill defaults -> inventory -> accessibility,
           returning a structured result and a normalized scenario folder.
run()      prepare(), and if it passes, run the kernel exe on the NORMALIZED
           scenario in an isolated copy so the assignment is reproducible.

This is the stable entry point for automated/batch use: a scenario that passes
prepare() has explicit defaults, sorted links, no dangling references, and a
known accessibility profile before a single iteration runs.
"""
import json
import os
import shutil
import subprocess
import tempfile

from . import validate as _validate
from . import fill as _fill
from . import inventory as _inventory
from . import accessibility as _accessibility

# input files whose modification invalidates a previous intake audit
_INTAKE_INPUTS = ("link.csv", "node.csv", "settings.csv", "mode_type.csv",
                  "demand.csv", "submission.yml")


def check_intake_gate(scenario, override=None):
    """WP-06: the intake gate is ENFORCED at the run boundary, not advisory.

    Returns (ok, status, reason). ok=False blocks the run unless `override`
    (a non-empty who/why string) is given — the override is reported back so the
    caller can record it in the run manifest.
      - no intake_issues.json  -> BLOCKED ('intake has not been run')
      - gate != READY          -> BLOCKED (undeclared conventions)
      - audit older than any input file -> STALE (re-run intake)
    """
    p = os.path.join(scenario, "intake_issues.json")
    if not os.path.exists(p):
        st = ("ABSENT", "intake has not been run: python -m dtalite_qa intake <scenario>")
    else:
        try:
            gate = json.load(open(p, encoding="utf-8")).get("gate", "BLOCKED")
        except (ValueError, OSError):
            gate = "BLOCKED"
        if gate != "READY":
            st = ("BLOCKED", "intake gate is not READY -- resolve the BLOCKER issues "
                             "(open intake_dashboard.html) and re-run intake")
        else:
            audit_t = os.path.getmtime(p)
            newer = [f for f in _INTAKE_INPUTS
                     if os.path.exists(os.path.join(scenario, f))
                     and os.path.getmtime(os.path.join(scenario, f)) > audit_t + 1]
            st = (("STALE", f"inputs changed after the intake audit ({', '.join(newer)}); "
                            "re-run intake") if newer else ("READY", ""))
    ok = st[0] == "READY" or bool(override)
    return ok, st[0], st[1]


def prepare(scenario, out_dir=None, do_fill=True):
    """Validate (+optionally fill) a scenario. Returns a dict result."""
    rep = _validate.validate(scenario)
    result = {"scenario": scenario, "validate": rep, "normalized": None,
              "fill_log": [], "inventory": None, "accessibility": None,
              "access_problems": 0, "ok": rep.ok}
    if not rep.ok:
        return result

    work = scenario
    if do_fill:
        out_dir = out_dir or tempfile.mkdtemp(prefix="dtalite_qa_")
        result["fill_log"] = _fill.fill(scenario, out_dir)
        result["normalized"] = out_dir
        work = out_dir

    result["inventory"] = _inventory.build(work)
    result["accessibility"] = _accessibility.check(work)
    _, worst = _accessibility.render(result["accessibility"])
    result["access_problems"] = worst
    return result


def run(scenario, exe, out_dir=None, timeout=1800, override=None, enforce_intake=True):
    """prepare() then run the kernel on the normalized scenario. Returns result
    with added keys: returncode, log, ran(bool), intake_gate, override.

    The intake gate is enforced (WP-06): an un-audited / BLOCKED / stale scenario
    refuses to run unless `override` (who/why string) is provided; the override is
    recorded in the result (and the run manifest)."""
    result = {"scenario": scenario, "ran": False, "ok": False}
    if enforce_intake:
        ok, status, reason = check_intake_gate(scenario, override=override)
        result["intake_gate"] = status
        result["override"] = override or None
        if not ok:
            result["gate_refusal"] = reason
            return result
    out_dir = out_dir or tempfile.mkdtemp(prefix="dtalite_run_")
    result.update(prepare(scenario, out_dir=out_dir, do_fill=True))
    result["ran"] = False
    if not result["ok"]:
        return result
    if not exe or not os.path.exists(exe):
        raise FileNotFoundError(
            f"C++ kernel not found: {exe!r}.\n"
            "dtalite_qa is the QA/orchestration layer — it does NOT solve the assignment; the\n"
            "C++ kernel (DTALite.exe) is the solver. Build it with `bash build.sh` (-> bin/\n"
            "DTALite.exe) and pass --exe bin/DTALite.exe.  See docs/ARCHITECTURE.md.")
    exe_local = os.path.join(out_dir, os.path.basename(exe))
    shutil.copy(exe, exe_local)
    p = subprocess.run([exe_local], cwd=out_dir, capture_output=True, text=True, timeout=timeout)
    result["returncode"] = p.returncode
    result["log"] = p.stdout + p.stderr
    result["ran"] = True
    return result
