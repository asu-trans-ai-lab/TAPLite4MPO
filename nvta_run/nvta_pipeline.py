#!/usr/bin/env python3
"""NVTA subarea -- the stage-by-stage QA/QC pipeline (bring-your-own-data).

The NVTA dataset is agency-restricted and is NOT in this repository -- that is
EXPECTED, not an error. This pipeline reproduces the same gated process as the
public ARC flagship (examples/arc_atlanta/arc_pipeline.py) on YOUR copy of a
converted NVTA scenario, so the package is proven robust across MPOs:

    python nvta_pipeline.py check    --dir <scenario>              # audit, no run
    python nvta_pipeline.py declare  --dir <scenario> --period pm  # submission.yml
    python nvta_pipeline.py prepare  --dir <scenario> --period pm  # -> <dir>_qa_run
    python nvta_pipeline.py run      --out <dir>_qa_run            # gated, streamed
    python nvta_pipeline.py validate --out <dir>_qa_run            # vs Cube I4<P>VOL
    python nvta_pipeline.py all      --dir <scenario> --period pm  # stops before run

<scenario> is a period folder produced by the dtalite4cube workflow (node.csv,
link.csv, mode_type.csv, settings.csv, <mode>_<period>.csv demand). Point the
pipeline at it with --dir or the environment variable DTALITE_NVTA_SCENARIO.

The check stage encodes the NVTA-specific lessons as automatic findings:
  * flat vdf_plf=1 on a peaked period (agency phi table implies PLF=phi/L);
  * trk pce=1 (the validated NVTA convention is pce=2);
  * Cube reference volumes (I4<P>VOL) present but not wired into ref_volume;
  * zone ids far larger than the zone count (renumbering skipped -> kernel
    arrays scale with the LARGEST id; runs get much slower than needed);
  * capacity / VDF values outside the agency CAPCLASS / BPR tables.

`prepare` then applies the DECLARED conventions explicitly (never silently):
PLF=phi/L, trk pce=2, ref_volume wired from I4<P>VOL, solver printed line by
line -- network and demand are otherwise copied verbatim.
"""
import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
IS_WIN = sys.platform == "win32"
KERNEL_NAME = "DTALite.exe" if IS_WIN else "DTALite"

# --- NVTA (MWCOG-family Cube) conventions, as shipped in the dtalite4cube
# --- workflow's netconfig.py. Model parameters, not agency data.
PHI = {"am": 2.39776486, "md": 5.649424854, "pm": 3.401127052, "nt": 6.66626961}
PERIOD_HOURS = {"am": (6, 9), "md": (9, 15), "pm": (15, 19), "nt": (19, 30)}
CAPCLASS_VALUES = {3150, 1900, 2000, 600, 800, 960, 1100, 500, 700, 840, 900,
                   1200, 1400, 1600, 1000}
VDF_COMBOS = {(0.87, 5.0), (0.96, 2.3), (0.10, 2.0)}
MODES = ("sov", "hov2", "hov3", "com", "trk", "apv")
TRK_PCE = 2          # validated full-NVTA convention (nvta_run/mode_type.csv)

RESULTS = []


def _say(msg=""):
    print(msg, flush=True)


def _record(stage, status, detail=""):
    RESULTS.append((stage, status, detail))
    _say(f"[{status}] {stage}" + (f" -- {detail}" if detail else ""))


def _banner(title):
    _say("\n" + "=" * 72 + f"\n {title}\n" + "=" * 72)


def _env():
    env = os.environ.copy()
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _capture(cmd, cwd=HERE, tail=12):
    p = subprocess.run(cmd, cwd=cwd, env=_env(), capture_output=True, text=True,
                       errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    for ln in out.strip().splitlines()[-tail:]:
        _say("  " + ln)
    return p.returncode, out


def resolve_dir(explicit):
    d = explicit or os.environ.get("DTALITE_NVTA_SCENARIO")
    if not d:
        _record("data", "SKIP",
                "NVTA data not configured -- EXPECTED (agency-restricted, not in "
                "this repo). Pass --dir <converted scenario> or set "
                "DTALITE_NVTA_SCENARIO. The public ARC example exercises the same "
                "process end-to-end without any private data.")
        return None
    d = os.path.abspath(os.path.expanduser(d))
    if not os.path.isdir(d):
        _record("data", "FAIL", f"{d} is not a directory")
        return None
    return d


def _period_of(d):
    """Infer the period from the demand file names (sov_pm.csv -> pm)."""
    for p in PERIOD_HOURS:
        if os.path.exists(os.path.join(d, f"sov_{p}.csv")):
            return p
    return None


def kernel_path():
    cands = [os.path.join(REPO, "bin", KERNEL_NAME)]
    if IS_WIN:
        cands.append(os.path.join(REPO, "release_v0.2.0", "DTALite.exe"))
    for c in cands:
        if os.path.exists(c):
            return c
    return None


# ------------------------------------------------------------------ stage: check
def stage_check(scenario):
    import pandas as pd
    d = resolve_dir(scenario)
    if d is None:
        return True                      # not configured is not a failure
    period = _period_of(d)
    _banner(f"CHECK 1/3 -- files + kernel ({os.path.basename(d)}, period: {period})")
    need = ["node.csv", "link.csv", "mode_type.csv", "settings.csv"] + \
           ([f"{m}_{period}.csv" for m in MODES] if period else [])
    missing = [f for f in need if not os.path.exists(os.path.join(d, f))]
    if missing:
        _record("files", "FAIL", "missing: " + ", ".join(missing))
        return False
    _record("files", "OK", f"{len(need)} required files present")
    exe = kernel_path()
    _record("kernel", "OK" if exe else "WARN",
            os.path.relpath(exe, REPO) if exe else "not built -- bash build.sh")

    _banner("CHECK 2/3 -- intake gate (declared conventions)")
    rc, out = _capture([sys.executable, "-m", "dtalite_qa", "intake", d], cwd=REPO)
    ready = rc == 0 and "GATE: READY" in out
    _record("intake gate", "READY" if ready else "BLOCKED",
            "0 blockers" if ready else
            f"run `python nvta_pipeline.py declare --dir {d}` to write the "
            "NVTA declaration, then re-check")

    _banner("CHECK 3/3 -- NVTA convention findings (the encoded lessons)")
    lk = pd.read_csv(os.path.join(d, "link.csv"), low_memory=False)
    nd = pd.read_csv(os.path.join(d, "node.csv"), usecols=["node_id", "zone_id"])
    findings = 0

    plf = sorted(lk["vdf_plf"].dropna().round(4).unique().tolist())
    want = round(PHI[period] / (PERIOD_HOURS[period][1] - PERIOD_HOURS[period][0]), 4) \
        if period else None
    if period and plf == [1.0]:
        findings += 1
        _record("PLF", "WARN", f"flat vdf_plf=1.0 on the {period.upper()} period; "
                f"agency phi={PHI[period]:.4f} implies PLF={want} -- capacity is "
                "overstated in the VDF. `prepare` applies the declared PLF.")
    else:
        _record("PLF", "OK", f"vdf_plf {plf}")

    mt = pd.read_csv(os.path.join(d, "mode_type.csv"))
    trk = mt.loc[mt["mode_type"] == "trk", "pce"]
    if len(trk) and float(trk.iloc[0]) != TRK_PCE:
        findings += 1
        _record("truck PCE", "WARN", f"trk pce={float(trk.iloc[0]):g}; the validated "
                f"NVTA convention is pce={TRK_PCE}. `prepare` applies it.")
    else:
        _record("truck PCE", "OK", f"pce={TRK_PCE}")

    refcol = f"I4{period.upper()}VOL" if period else None
    if refcol and refcol in lk.columns:
        wired = int((lk.get("ref_volume", 0) > 0).sum())
        if wired == 0:
            findings += 1
            _record("reference", "WARN", f"Cube {refcol} present but ref_volume is 0 "
                    "on every link -- validation is not wired. `prepare` wires it.")
        else:
            _record("reference", "OK", f"ref_volume wired on {wired:,} links")
    else:
        _record("reference", "WARN", "no Cube I4<P>VOL columns found -- validation "
                "will need an observed-count source")

    nz = int((nd["zone_id"].fillna(0) > 0).sum())
    zmax = int(nd["zone_id"].fillna(0).max())
    if zmax > 10 * max(nz, 1):
        _record("renumbering", "INFO", f"{nz} zones with sparse ids (max {zmax}). "
                "The current kernel renumbers internally (zones-first, dense 1..Z) and "
                "reports outputs in the ORIGINAL ids, so this folder is directly "
                "runnable. Kernels older than 2026-07 crash on sparse ids (issue #6); "
                "the dtalite4cube runner's _internal/ renumbering covers those.")
    else:
        _record("renumbering", "OK", f"{nz} zones, max id {zmax}")

    road = lk[lk.get("FTYPE", 0) > 0] if "FTYPE" in lk.columns else lk
    badcap = sorted(set(road["capacity"].dropna().astype(int)) - CAPCLASS_VALUES)
    _record("capacity table", "OK" if not badcap else "WARN",
            "all per-lane hourly capacities are CAPCLASS values" if not badcap
            else f"values outside the CAPCLASS table: {badcap[:8]}")
    combos = set(zip(road["vdf_alpha"].round(2), road["vdf_beta"].round(1)))
    badvdf = combos - VDF_COMBOS
    _record("VDF table", "OK" if not badvdf else "WARN",
            "per-FTYPE BPR matches the NVTA table" if not badvdf
            else f"unknown (alpha,beta) combos: {sorted(badvdf)[:6]}")

    _say(f"\n  convention findings: {findings} "
         f"({'`prepare` fixes the fixable ones explicitly' if findings else 'clean'})")
    return True


# ---------------------------------------------------------------- stage: declare
DECLARATION = """\
# NVTA subarea submission declaration (generated by nvta_pipeline.py declare)
agency: NVTA (Northern Virginia / MWCOG-family Cube model) subarea
model_year: declared-by-user
contact: declared-by-user
capacity_basis: per_lane
capacity_period: hourly
capacity_source_field: CAPCLASS -> dtalite4cube netconfig.capacity_class_dict
capacity_period_hours: 1
assignment_period: {P}
period_start_hour: {h0}
period_end_hour: {h1}
peak_load_factor: {plf}          # phi/L; phi from the agency period-hour table
phi_hour_to_period: {phi}
plf_by_facility: none
length_unit: km
speed_unit: kmh
time_unit: min
demand_kind: vehicle_trips
demand_period_hours: {H}
occupancy: sov=1 hov2=2 hov3=3.5 com=1 trk=1 apv=1.6
pce: trk={pce}
zone_id_basis: matrix label = centroid zone id (dtalite4cube workflow)
vot: sov=20 hov2=30 hov3=60 com=30 trk=30 apv=30
operating_cost_per_mi: 0
toll_coding: per-mode toll_<mode> columns
vdf_type: 0
vdf_source: per-FTYPE BPR from dtalite4cube netconfig (fwy .87/5, art .96/2.3)
count_field: I4{P}VOL (Cube loaded volume; wired into ref_volume by `prepare`)
restriction_coding: {P}LIMIT codes 0-9 -> allowed_use (netconfig.allowed_uses_dict)
"""


def stage_declare(scenario, period=None):
    d = resolve_dir(scenario)
    if d is None:
        return True
    period = period or _period_of(d)
    if not period:
        _record("declare", "FAIL", "could not infer the period; pass --period")
        return False
    h0, h1 = PERIOD_HOURS[period]
    text = DECLARATION.format(P=period.upper(), h0=h0, h1=h1, H=h1 - h0,
                              phi=round(PHI[period], 6),
                              plf=round(PHI[period] / (h1 - h0), 4), pce=TRK_PCE)
    with open(os.path.join(d, "submission.yml"), "w", encoding="utf-8") as f:
        f.write(text)
    _record("declare", "OK", f"submission.yml written ({period.upper()}, "
            f"PLF={round(PHI[period]/(h1-h0), 4)}) -- re-run `check`")
    return True


# ---------------------------------------------------------------- stage: prepare
def stage_prepare(scenario, period=None, out=None, iterations=10, processors=8):
    import pandas as pd
    d = resolve_dir(scenario)
    if d is None:
        return True
    period = period or _period_of(d)
    out = out or (d.rstrip("/\\") + "_qa_run")
    os.makedirs(out, exist_ok=True)

    # Ids are staged VERBATIM: since 2026-07 the kernel renumbers sparse
    # node/zone ids internally (zones first, dense 1..Z) and writes all outputs
    # back in the ORIGINAL ids -- no user-space renumber/backmap step needed.
    # (Older kernels crash on sparse ids; see GitHub issue #6.)
    shutil.copy(os.path.join(d, "node.csv"), os.path.join(out, "node.csv"))
    for m in MODES:
        shutil.copy(os.path.join(d, f"{m}_{period}.csv"),
                    os.path.join(out, f"{m}_{period}.csv"))
    _say(f"  node + {len(MODES)} demand files staged verbatim "
         "(kernel renumbers sparse ids internally)")

    lk = pd.read_csv(os.path.join(d, "link.csv"), low_memory=False)
    h0, h1 = PERIOD_HOURS[period]
    plf = PHI[period] / (h1 - h0)
    lk["vdf_plf"] = round(plf, 6)
    refcol = f"I4{period.upper()}VOL"
    wired = 0
    if refcol in lk.columns:
        lk["ref_volume"] = lk[refcol].fillna(0)
        wired = int((lk["ref_volume"] > 0).sum())
    lk.to_csv(os.path.join(out, "link.csv"), index=False)
    _say(f"  link.csv: vdf_plf {1.0} -> {plf:.4f} (phi={PHI[period]:.4f}/L={h1-h0}); "
         f"ref_volume wired from {refcol} on {wired:,} links")

    mt = pd.read_csv(os.path.join(d, "mode_type.csv"))
    if "trk" in set(mt["mode_type"]):
        mt.loc[mt["mode_type"] == "trk", "pce"] = TRK_PCE
    mt.to_csv(os.path.join(out, "mode_type.csv"), index=False)
    _say(f"  mode_type.csv: trk pce -> {TRK_PCE} (validated NVTA convention)")

    st = pd.read_csv(os.path.join(d, "settings.csv")).iloc[0].to_dict()
    st.update({"number_of_iterations": iterations,
               "number_of_processors": processors,
               "demand_period_starting_hours": h0,
               "demand_period_ending_hours": h1,
               # route/vehicle output OFF for validation runs: the 5D route store
               # is sized by the LARGEST zone id -- on non-renumbered scenarios it
               # can eat tens of GB even on tiny subareas. Link volumes are
               # unaffected; re-enable deliberately for select-link work.
               "route_output": 0, "vehicle_output": 0})
    pd.DataFrame([st]).to_csv(os.path.join(out, "settings.csv"), index=False)
    _say("  solver parameters (settings.csv) -- explicit, nowhere else:")
    for k, v in st.items():
        _say(f"    {k:32} = {v}")
    if os.path.exists(os.path.join(d, "submission.yml")):
        shutil.copy(os.path.join(d, "submission.yml"),
                    os.path.join(out, "submission.yml"))
    _say("  one period, strictly serial; one kernel process at a time.")
    _record("prepare", "OK", f"{os.path.basename(out)}/ ready "
            f"(declared conventions applied EXPLICITLY, printed above)")
    return True


# -------------------------------------------------------------------- stage: run
def stage_run(out, timeout=7200):
    if not out or not os.path.exists(os.path.join(out, "settings.csv")):
        _record("run", "FAIL", "run folder not prepared -- run `prepare` first")
        return False
    exe = kernel_path()
    if not exe:
        _record("run", "FAIL", f"no {KERNEL_NAME} -- bash build.sh at the repo root")
        return False
    shutil.copy(exe, os.path.join(out, KERNEL_NAME))
    _say(f"  running the kernel in {os.path.basename(out)}/ (streamed; quiet start "
         "is normal; non-renumbered ids make this slower than the link count suggests)")
    t0 = time.time()
    logp = os.path.join(out, "kernel_console.log")
    proc = subprocess.Popen([os.path.join(out, KERNEL_NAME)], cwd=out, env=_env(),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace", bufsize=1)
    q = queue.Queue()

    def _reader():
        for line in proc.stdout:
            q.put(line.rstrip())
        q.put(None)

    threading.Thread(target=_reader, daemon=True).start()
    last = time.time()
    with open(logp, "w", encoding="utf-8") as log:
        while True:
            if timeout and time.time() - t0 > timeout:
                proc.kill()
                _record("run", "FAIL", f"timed out after {timeout} s")
                return False
            try:
                item = q.get(timeout=1.0)
            except queue.Empty:
                if time.time() - last >= 30:
                    el = int(time.time() - t0)
                    _say(f"  [{el//60:02d}:{el%60:02d}] ... kernel busy, still running")
                    last = time.time()
                continue
            if item is None:
                break
            el = int(time.time() - t0)
            _say(f"  [{el//60:02d}:{el%60:02d}] {item}")
            log.write(item + "\n")
            last = time.time()
    rc = proc.wait()
    ok = rc == 0 and os.path.getsize(os.path.join(out, "link_performance.csv")) > 0
    _record("run", "OK" if ok else "FAIL",
            f"{(time.time()-t0)/60:.1f} min" if ok else f"kernel exit {rc}; see {logp}")
    return ok


# --------------------------------------------------------------- stage: validate
def stage_validate(out):
    import math
    import pandas as pd
    perf = os.path.join(out, "link_performance.csv")
    if not os.path.exists(perf):
        _record("validate", "FAIL", "no link_performance.csv -- run `run` first")
        return False
    lk = pd.read_csv(os.path.join(out, "link.csv"), low_memory=False)
    lp = pd.read_csv(perf, encoding="utf-8-sig", low_memory=False)
    m = lk.merge(lp[["from_node_id", "to_node_id", "volume"]],
                 on=["from_node_id", "to_node_id"], how="inner")
    if "FTYPE" in m.columns:
        m = m[m["FTYPE"] > 0]
    m = m[m["ref_volume"] > 0]
    if not len(m):
        _record("validate", "FAIL", "no links with ref_volume > 0")
        return False
    rv, av = m["ref_volume"], m["volume"]
    rmse = math.sqrt(((av - rv) ** 2).mean())
    pct = 100 * rmse / rv.mean()
    r2 = 1 - ((av - rv) ** 2).sum() / max(((rv - rv.mean()) ** 2).sum(), 1e-9)
    ratio = av.sum() / rv.sum()
    with open(os.path.join(out, "nvta_validation.json"), "w", encoding="utf-8") as f:
        json.dump({"links": int(len(m)), "rmse_pct": pct, "r2": r2,
                   "assigned_ref_ratio": ratio}, f, indent=2)
    _record("validate", "OK", f"{len(m)} road links vs Cube reference: "
            f"%RMSE {pct:.1f}%, R^2 {r2:.3f}, assigned/ref {ratio:.3f} "
            "(nvta_validation.json written)")
    return True


def summary():
    _banner("SUMMARY")
    width = max((len(s) for s, _, _ in RESULTS), default=10) + 2
    for stage, status, detail in RESULTS:
        _say(f" {stage:<{width}}{status:<8}{detail}")
    bad = [s for s, st, _ in RESULTS if st == "FAIL"]
    _say("=" * 72)
    _say(" RESULT: " + ("FAILED at: " + ", ".join(bad) if bad
                        else "all executed stages passed."))
    return not bad


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nvta_pipeline.py",
                                 description="NVTA subarea QA/QC pipeline "
                                             "(bring-your-own-data; see docstring)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, hlp in (("check", "audit files, intake gate, NVTA conventions"),
                      ("declare", "write the NVTA submission.yml declaration"),
                      ("all", "check + declare + prepare; prints the run command")):
        sp = sub.add_parser(name, help=hlp)
        sp.add_argument("--dir", default=None, help="converted scenario folder "
                        "(or set DTALITE_NVTA_SCENARIO)")
        sp.add_argument("--period", choices=sorted(PERIOD_HOURS), default=None)
    sp = sub.add_parser("prepare", help="apply declared conventions -> <dir>_qa_run")
    sp.add_argument("--dir", default=None)
    sp.add_argument("--period", choices=sorted(PERIOD_HOURS), default=None)
    sp.add_argument("--out", default=None)
    sp.add_argument("--iterations", type=int, default=10)
    sp.add_argument("--processors", type=int, default=8)
    sp = sub.add_parser("run", help="run the kernel in the prepared folder (gated)")
    sp.add_argument("--out", required=True)
    sp.add_argument("--timeout", type=int, default=7200)
    sp = sub.add_parser("validate", help="score vs the wired Cube reference")
    sp.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "check":
        ok = stage_check(a.dir)
    elif a.cmd == "declare":
        ok = stage_declare(a.dir, a.period)
    elif a.cmd == "prepare":
        ok = stage_prepare(a.dir, a.period, a.out, a.iterations, a.processors)
    elif a.cmd == "run":
        ok = stage_run(a.out, a.timeout)
    elif a.cmd == "validate":
        ok = stage_validate(a.out)
    else:                                     # all
        ok = stage_check(a.dir)
        if ok and resolve_dir(a.dir):
            d = resolve_dir(a.dir)
            if not os.path.exists(os.path.join(d, "submission.yml")):
                ok = stage_declare(a.dir, a.period) and ok
            ok = stage_prepare(a.dir, a.period) and ok
            if ok:
                qa_run = d.rstrip("/\\") + "_qa_run"
                _say("\n  Prepared but NOT run (never launched without your say-so):")
                _say(f"    python nvta_pipeline.py run --out {qa_run}")
                _say(f"    python nvta_pipeline.py validate --out {qa_run}")
    return summary() and ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
