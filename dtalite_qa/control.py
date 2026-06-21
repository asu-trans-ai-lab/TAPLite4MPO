"""Orchestration: the QA gate that 'controls' a kernel run.

prepare()  validate -> (optionally) fill defaults -> inventory -> accessibility,
           returning a structured result and a normalized scenario folder.
run()      prepare(), and if it passes, run the kernel exe on the NORMALIZED
           scenario in an isolated copy so the assignment is reproducible.

This is the stable entry point for automated/batch use: a scenario that passes
prepare() has explicit defaults, sorted links, no dangling references, and a
known accessibility profile before a single iteration runs.
"""
import os
import shutil
import subprocess
import tempfile

from . import validate as _validate
from . import fill as _fill
from . import inventory as _inventory
from . import accessibility as _accessibility


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


def run(scenario, exe, out_dir=None, timeout=1800):
    """prepare() then run the kernel on the normalized scenario. Returns result
    with added keys: returncode, log, ran(bool)."""
    out_dir = out_dir or tempfile.mkdtemp(prefix="dtalite_run_")
    result = prepare(scenario, out_dir=out_dir, do_fill=True)
    result["ran"] = False
    if not result["ok"]:
        return result
    exe_local = os.path.join(out_dir, os.path.basename(exe))
    shutil.copy(exe, exe_local)
    p = subprocess.run([exe_local], cwd=out_dir, capture_output=True, text=True, timeout=timeout)
    result["returncode"] = p.returncode
    result["log"] = p.stdout + p.stderr
    result["ran"] = True
    return result
