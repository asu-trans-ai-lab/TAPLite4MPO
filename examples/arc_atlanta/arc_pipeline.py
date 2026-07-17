#!/usr/bin/env python3
"""ARC Atlanta -- the stage-by-stage pipeline (the ONE front door).

Every stage is a subcommand you can run alone; `all` chains them SERIALLY and
never launches the big kernel run unless you say so explicitly:

    python arc_pipeline.py check            # seconds: deps, kernel, data, intake, VDF/PLF
                                            #   (alias: doctor)
    python arc_pipeline.py inspect          # scenario summary: zones, links, VDF, modes
    python arc_pipeline.py convert          # PATH B only: full raw ARC data -> gmns/
    python arc_pipeline.py convert --source-root D:/ARC_Model   # find raw files anywhere
    python arc_pipeline.py build            # explicit kernel build (build.sh, else CMake)
    python arc_pipeline.py prepare          # verify + copy gmns/ -> gmns_run/, set solver
    python arc_pipeline.py run --quick      # 1-iteration smoke run (~1-2 min, live output)
    python arc_pipeline.py run              # FULL 6,031-zone equilibrium (~5-6 min)
    python arc_pipeline.py validate         # %RMSE vs ARC's own AM counts (+ JSON)
    python arc_pipeline.py all              # check+prepare, then PRINTS the run command
    python arc_pipeline.py all --quick      # ... + smoke run + approximate validation
    python arc_pipeline.py all --full       # ... + full run + validation (the real thing)

Design rules (learned the hard way):
  * The in-repo gmns/ scenario ALREADY encodes ARC's calibration (per-FACTYPE
    modified-BPR vdf_A/alpha/beta, weave overrides, vdf_plf = 3.66/4 = 0.915).
    `prepare` VERIFIES that encoding and copies it verbatim -- it never rewrites
    network files (arc_calibrate.py is a legacy/repair tool, not part of this flow).
  * Solver parameters are set EXPLICITLY in one place (`prepare`), printed in full.
  * Stages run strictly serially: one demand period (AM 6-10), one kernel process.
  * The kernel's first ~minute is quiet (reading 26M OD pairs, building the first
    paths). `run` streams every kernel line with an elapsed clock and prints a
    heartbeat while the kernel is silent, so "no output" never looks like a hang.
  * If the full raw ARC data (~125 MB, unbundled) is absent, that is EXPECTED --
    the bundled gmns/ case is complete (PATH A). `convert` only applies to PATH B.
  * Console output is pure ASCII (Windows legacy codepages crash on fancy dashes).

Measured on the reference machine (8 threads): build ~1 min; smoke run ~2 min;
full run ~5 min (converges at iteration ~8, gap<0.5% x3); validation: region-wide
%RMSE 22% vs ARC's ~38% target, assigned/ref = 1.00.
"""
import argparse
import glob
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
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
GMNS = os.path.join(HERE, "gmns")
RUN_FULL_DIR = os.path.join(HERE, "gmns_run")
RUN_QUICK_DIR = os.path.join(HERE, "gmns_run_quick")
RAW_SHP = os.path.join(HERE, "arc-Shape", "arc-Shape")            # full shapefiles (unbundled)
RAW_DEMAND = os.path.join(HERE, "TODAM20_asgn", "TODAM20_asgn")   # trip cores (unbundled)

IS_WIN = sys.platform == "win32"
KERNEL_NAME = "DTALite.exe" if IS_WIN else "DTALite"

# ARC Section 7.1.2 modified-BPR (A, alpha, beta) by FACTYPE -- the authoritative
# table gmns/link.csv must already encode. Weave links (WEAVEFLAG=1) may carry the
# WEAVE triple on any factype. Connectors (FACTYPE 0) are uncapacitated by design
# and are not checked.
VDF_ADB = {1: (0.10, 0.60, 6.0), 4: (0.10, 0.60, 6.0), 5: (0.10, 0.60, 6.0),
           6: (0.10, 0.60, 6.0), 2: (0.00, 1.00, 4.0), 3: (0.00, 1.25, 4.0),
           7: (0.10, 1.00, 4.0), 8: (0.10, 1.00, 4.0), 9: (0.10, 1.00, 4.0),
           10: (0.10, 0.45, 4.0), 11: (0.10, 0.45, 4.0), 12: (0.10, 0.45, 4.0),
           13: (0.10, 0.45, 4.0), 14: (0.10, 0.45, 4.0)}
WEAVE_ADB = (0.20, 1.25, 5.5)
AM_PLF = 3.66 / 4.0          # ARC AM period factor phi=3.66 over the 4-h window

# Solver defaults = the configuration that produced the validated 22% %RMSE run.
SOLVER_DEFAULTS = dict(number_of_iterations=30, number_of_processors=8,
                       demand_period_starting_hours=6, demand_period_ending_hours=10,
                       convergence_gap_pct=0.5, convergence_consecutive=3)

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


def _capture(cmd, cwd=HERE, tail=20):
    """Short-running helper subprocesses: capture, print the tail, return (rc, out)."""
    p = subprocess.run(cmd, cwd=cwd, env=_env(), capture_output=True, text=True,
                       errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    lines = out.strip().splitlines()
    if len(lines) > tail:
        _say(f"  ... ({len(lines) - tail} earlier lines omitted)")
    for ln in lines[-tail:]:
        _say("  " + ln)
    return p.returncode, out


def kernel_path():
    """Platform-aware kernel binary lookup (never builds; see stage_run)."""
    cands = [os.path.join(REPO, "bin", KERNEL_NAME)]
    if IS_WIN:
        cands.append(os.path.join(REPO, "release_v0.2.0", "DTALite.exe"))
    for c in cands:
        if os.path.exists(c):
            return c
    return None


# ------------------------------------------------------------------ stage: check
def stage_check():
    """Fast preflight (seconds). Never launches the kernel."""
    _banner("CHECK 1/4 -- Python dependencies + kernel binary")
    ok = True
    missing = []
    for mod in ("pandas", "numpy", "shapefile"):
        try:
            __import__(mod)
        except ImportError:
            missing.append("pyshp" if mod == "shapefile" else mod)
    if missing:
        _record("deps", "FAIL", "pip install " + " ".join(missing))
        return False
    _record("deps", "OK", f"python {sys.version.split()[0]}, pandas/numpy/pyshp present")

    exe = kernel_path()
    if exe:
        _record("kernel", "OK", os.path.relpath(exe, REPO))
    else:
        _record("kernel", "WARN",
                f"bin/{KERNEL_NAME} not found -- needed only for `run`; "
                "build it once with: bash build.sh   (repo root; "
                "macOS: brew install cmake libomp first)")

    _banner("CHECK 2/4 -- data audit: PATH A (in-repo) vs PATH B (full raw ARC)")
    path = data_path()
    if path is None:
        return False

    _banner("CHECK 3/4 -- intake gate (declared conventions in gmns/submission.yml)")
    rc, out = _capture([sys.executable, "-m", "dtalite_qa", "intake", "gmns"], tail=8)
    ready = rc == 0 and "GATE: READY" in out
    _record("intake gate", "READY" if ready else "FAIL",
            "0 blockers" if ready else "open gmns/intake_dashboard.html for the blocker list")
    ok = ok and ready

    _banner("CHECK 4/4 -- verify the encoded ARC VDF/PLF in gmns/link.csv")
    ok = verify_vdf() and ok
    return ok


def data_path(from_raw=False):
    have_raw = (os.path.exists(os.path.join(RAW_SHP, "AMNode2020.shp"))
                and os.path.isdir(RAW_DEMAND))
    have_gmns = all(os.path.exists(os.path.join(GMNS, f)) for f in
                    ("node.csv", "link.csv", "demand_sov.csv", "settings.csv",
                     "mode_type.csv"))
    _say(f"  full raw ARC data (shapefiles + trip cores) ... {'FOUND' if have_raw else 'absent'}")
    _say(f"  in-repo GMNS case (gmns/) ..................... {'FOUND' if have_gmns else 'MISSING'}")
    if from_raw and not have_raw:
        _record("data audit", "FAIL", "--from-raw requested but the ~125 MB raw ARC "
                "data is not present (see README section 2)")
        return None
    if from_raw or (have_raw and not have_gmns):
        _record("data audit", "PATH B", "raw ARC data -> `convert` will (re)build gmns/")
        return "B"
    if have_gmns:
        _record("data audit", "PATH A", "raw data absent is EXPECTED (not bundled, ~125 MB); "
                "the in-repo gmns/ case is complete")
        return "A"
    _record("data audit", "FAIL", "neither gmns/ nor raw ARC data found")
    return None


def verify_vdf():
    """Confirm gmns/link.csv already encodes ARC's calibration. Never rewrites."""
    import pandas as pd
    lk = pd.read_csv(os.path.join(GMNS, "link.csv"), low_memory=False,
                     usecols=["factype", "vdf_A", "vdf_alpha", "vdf_beta", "vdf_plf"])
    drift = []
    plf = sorted(lk["vdf_plf"].round(4).unique())
    if plf != [round(AM_PLF, 4)]:
        drift.append(f"vdf_plf {plf} != {AM_PLF:.3f}")
    for ft, grp in lk.groupby(lk["factype"].fillna(0).astype(int)):
        if ft == 0:
            continue                       # connectors: uncapacitated, not checked
        seen = set(zip(grp["vdf_A"].round(2), grp["vdf_alpha"].round(2),
                       grp["vdf_beta"].round(1)))
        allowed = {VDF_ADB[ft], WEAVE_ADB} if ft in VDF_ADB else {WEAVE_ADB}
        bad = seen - allowed
        if bad:
            drift.append(f"factype {ft}: {sorted(bad)} not in ARC table {sorted(allowed)}")
    n_ft = lk[lk['factype'] != 0]['factype'].nunique()
    if drift:
        _record("VDF/PLF verify", "FAIL", "; ".join(drift) +
                "  -- gmns/link.csv has drifted from the ARC tables; do NOT run blindly. "
                "arc_calibrate.py can re-derive it (legacy repair), or restore gmns/ from git.")
        return False
    _record("VDF/PLF verify", "OK",
            f"{n_ft} facility types match ARC Sec 7.1.2 (incl. weave overrides); "
            f"vdf_plf = {AM_PLF:.3f} everywhere (connectors uncapacitated, not checked)")
    return True


# ---------------------------------------------------------------- stage: convert
RAW_CORES = ("SOVF", "SOVT", "HOV2F", "HOV2T", "HOV3F", "HOV3T")


def _find_shallowest(root, pattern):
    hits = sorted(glob.glob(os.path.join(root, "**", pattern), recursive=True),
                  key=lambda p: (p.count(os.sep), p.lower()))
    return hits[0] if hits else None


def _collect_raw(source_root):
    """Find the raw ARC files anywhere below source_root and stage them into the
    layout the faithful provenance converters expect (arc-Shape/, TODAM20_asgn/)."""
    root = os.path.abspath(os.path.expanduser(source_root))
    if not os.path.isdir(root):
        _record("collect raw", "FAIL", f"--source-root {root} is not a directory")
        return False
    missing, plan = [], []
    for base in ("AMNode2020", "AMLink2020"):
        shp = _find_shallowest(root, base + ".shp")
        if not shp:
            missing.append(base + ".shp")
            continue
        for sidecar in glob.glob(os.path.splitext(shp)[0] + ".*"):
            plan.append((sidecar, os.path.join(RAW_SHP, os.path.basename(sidecar))))
    for core in RAW_CORES:
        p = _find_shallowest(root, core + ".csv")
        (plan.append((p, os.path.join(RAW_DEMAND, core + ".csv")))
         if p else missing.append(core + ".csv"))
    if missing:
        _record("collect raw", "FAIL",
                f"not found below {root}: " + ", ".join(missing))
        return False
    os.makedirs(RAW_SHP, exist_ok=True)
    os.makedirs(RAW_DEMAND, exist_ok=True)
    _say(f"  staging {len(plan)} raw files from {root}")
    _say("  NOTE: this replaces the bundled trimmed teaching shapefile in arc-Shape/ "
         "with the full one (restore it from git if you want the trimmed copy back).")
    for src, dst in plan:
        shutil.copy2(src, dst)
    _record("collect raw", "OK", f"{len(plan)} files staged for conversion")
    return True


def stage_convert(from_raw=False, source_root=None):
    """PATH B only: rebuild gmns/ from the full raw ARC data. Skips cleanly on PATH A."""
    if source_root and not _collect_raw(source_root):
        return False
    if source_root:
        from_raw = True
    path = data_path(from_raw=from_raw)
    if path is None:
        return False
    if path == "A":
        _record("convert", "SKIP", "PATH A -- gmns/ already provided; nothing to convert "
                "(this is the normal case)")
        return True
    _say("  converting network: arc_atlanta_to_gmns.py (full shapefiles -> gmns/)")
    rc1, _ = _capture([sys.executable, "arc_atlanta_to_gmns.py"])
    _say("  converting demand: arc_demand_to_csv.py (trip cores -> gmns/demand_*.csv)")
    rc2, _ = _capture([sys.executable, "arc_demand_to_csv.py"])
    ok = rc1 == 0 and rc2 == 0
    _record("convert", "OK" if ok else "FAIL",
            "gmns/ rebuilt from raw ARC data" if ok else "see messages above")
    return ok


# ---------------------------------------------------------------- stage: prepare
def stage_prepare(quick=False, **solver):
    """Verify the encoded calibration, copy gmns/ verbatim, set solver params explicitly."""
    if not verify_vdf():
        return False
    out = RUN_QUICK_DIR if quick else RUN_FULL_DIR
    params = dict(SOLVER_DEFAULTS)
    params.update({k: v for k, v in solver.items() if v is not None})
    if quick:
        params["number_of_iterations"] = 1

    os.makedirs(out, exist_ok=True)
    files = ["node.csv", "link.csv", "mode_type.csv",
             "demand_sov.csv", "demand_hov2.csv", "demand_hov3.csv"]
    for f in files:
        shutil.copy(os.path.join(GMNS, f), os.path.join(out, f))
    _say(f"  copied {len(files)} files verbatim from gmns/ (network + demand UNCHANGED)")

    import pandas as pd
    base = pd.read_csv(os.path.join(GMNS, "settings.csv")).iloc[0].to_dict()
    base.update(params)
    pd.DataFrame([base]).to_csv(os.path.join(out, "settings.csv"), index=False)
    _say("  solver parameters (settings.csv) -- set EXPLICITLY here, nowhere else:")
    for k, v in base.items():
        mark = "  <-- quick smoke" if (quick and k == "number_of_iterations") else ""
        _say(f"    {k:32} = {v}{mark}")
    _say("  single demand period (AM 6-10); stages run strictly serially, "
         "one kernel process at a time.")
    _record("prepare", "OK", f"{os.path.basename(out)}/ ready "
            f"({'1-iteration smoke' if quick else 'full equilibrium'} configuration)")
    return True


# ------------------------------------------------------------------ stage: build
def stage_build():
    """Explicit kernel build: bash build.sh when available, else direct CMake."""
    if shutil.which("bash") and os.path.exists(os.path.join(REPO, "build.sh")):
        rc, _ = _capture(["bash", "build.sh"], cwd=REPO, tail=6)
    elif shutil.which("cmake"):
        bdir = os.path.join(REPO, "cmake_build_rel")
        cfg = ["cmake", "-S", os.path.join(REPO, "kernel"), "-B", bdir,
               "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_DTALITE_EXE=ON"]
        if shutil.which("ninja"):
            cfg[1:1] = ["-G", "Ninja"]
        rc, _ = _capture(cfg, cwd=REPO, tail=4)
        if rc == 0:
            rc, _ = _capture(["cmake", "--build", bdir, "--target", "DTALite_exe",
                              "--config", "Release"], cwd=REPO, tail=4)
        if rc == 0:
            os.makedirs(os.path.join(REPO, "bin"), exist_ok=True)
            for name in ("DTALite_exe.exe", "Release/DTALite_exe.exe", "DTALite_exe"):
                built = os.path.join(bdir, name)
                if os.path.exists(built):
                    shutil.copy2(built, os.path.join(REPO, "bin", KERNEL_NAME))
                    break
    else:
        _record("build", "FAIL", "neither bash nor cmake found -- install CMake "
                "(macOS: brew install cmake libomp)")
        return False
    exe = kernel_path()
    ok = rc == 0 and exe is not None
    _record("build", "OK" if ok else "FAIL",
            os.path.relpath(exe, REPO) if ok else "see build output above")
    return ok


# ---------------------------------------------------------------- stage: inspect
def stage_inspect():
    """Scenario summary: what is actually coded in gmns/ (no files changed)."""
    import pandas as pd
    nodes = pd.read_csv(os.path.join(GMNS, "node.csv"), usecols=["node_id", "zone_id"])
    lk = pd.read_csv(os.path.join(GMNS, "link.csv"), low_memory=False)
    _say(f"  nodes       : {len(nodes):,}")
    _say(f"  zones       : {int((nodes['zone_id'].fillna(0) > 0).sum()):,}")
    _say(f"  links       : {len(lk):,}")
    if "ref_volume" in lk.columns:
        _say(f"  ref links   : {int((lk['ref_volume'].fillna(0) > 0).sum()):,}")
    if "allowed_use" in lk.columns:
        uses = lk["allowed_use"].fillna("(all)").replace("", "(all)").value_counts()
        _say("  allowed_use : " + ", ".join(f"{k}={v:,}" for k, v in uses.items()))
    _say(f"  vdf_plf     : {sorted(lk['vdf_plf'].dropna().round(4).unique().tolist())}")
    combos = lk[lk["factype"].fillna(0) != 0][["vdf_A", "vdf_alpha", "vdf_beta"]]
    _say(f"  VDF sets    : {len(combos.drop_duplicates())} distinct (road links)")
    _say("  settings.csv:")
    for k, v in pd.read_csv(os.path.join(GMNS, "settings.csv")).iloc[0].items():
        _say(f"    {k:32} = {v}")
    _say("  mode_type.csv:")
    mt = pd.read_csv(os.path.join(GMNS, "mode_type.csv"))
    for _, r in mt.iterrows():
        _say(f"    {r['mode_type']:6} vot={r['vot']} occ={r['occ']} "
             f"op_cost={r['operating_cost']} demand={r['demand_file']}")
    _record("inspect", "OK", f"{len(lk):,} links, {len(mt)} demand classes")
    return True


# -------------------------------------------------------------------- stage: run
def _ensure_kernel():
    exe = kernel_path()
    if exe:
        return exe
    _say(f"  {KERNEL_NAME} not found -- building it once (bash build.sh, ~1 min) ...")
    rc, _ = _capture(["bash", "build.sh"], cwd=REPO, tail=6)
    exe = kernel_path()
    if rc != 0 or not exe:
        _record("kernel build", "FAIL",
                "bash build.sh failed -- needs cmake + a C++ compiler"
                + ("; on macOS: brew install cmake libomp" if not IS_WIN else
                   " (MinGW/MSVC); see docs/ARCHITECTURE.md"))
        return None
    return exe


def stage_run(quick=False, run_dir=None, timeout=7200):
    """Run the kernel with LIVE streamed output + heartbeat. Strictly one process.
    The timeout fires even while the kernel is silent (checked every second)."""
    rd = run_dir or (RUN_QUICK_DIR if quick else RUN_FULL_DIR)
    if not os.path.exists(os.path.join(rd, "settings.csv")):
        _record("run", "FAIL", f"{os.path.basename(rd)}/ not prepared -- run "
                f"`python arc_pipeline.py prepare{' --quick' if quick else ''}` first")
        return False
    exe = _ensure_kernel()
    if not exe:
        return False
    shutil.copy(exe, os.path.join(rd, KERNEL_NAME))

    label = "1-iteration SMOKE run (~2 min)" if quick else \
            "FULL 6,031-zone equilibrium run (~5-6 min on 8 threads)"
    _say(f"  starting {label} in {os.path.basename(rd)}/")
    _say("  NOTE: the first ~minute is quiet -- the kernel is reading ~26M OD pairs and")
    _say("  building the first shortest-path trees. The clock below proves it is alive.")

    t0 = time.time()
    logp = os.path.join(rd, "kernel_console.log")
    proc = subprocess.Popen([os.path.join(rd, KERNEL_NAME)], cwd=rd, env=_env(),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace", bufsize=1)
    q = queue.Queue()

    def _reader():
        for line in proc.stdout:
            q.put(line.rstrip())
        q.put(None)

    threading.Thread(target=_reader, daemon=True).start()
    last_out = time.time()
    timed_out = False
    with open(logp, "w", encoding="utf-8") as log:
        while True:
            if timeout and time.time() - t0 > timeout:
                proc.kill()
                timed_out = True
                _say(f"  TIMEOUT: kernel exceeded {timeout} s -- killed "
                     f"(raise with --timeout; log: {os.path.relpath(logp, HERE)})")
                break
            try:
                item = q.get(timeout=1.0)
            except queue.Empty:
                if time.time() - last_out >= 30:
                    el = int(time.time() - t0)
                    _say(f"  [{el//60:02d}:{el%60:02d}] ... kernel busy (quiet is normal "
                         "while loading/assigning), still running")
                    last_out = time.time()
                continue
            if item is None:
                break
            el = int(time.time() - t0)
            _say(f"  [{el//60:02d}:{el%60:02d}] {item}")
            log.write(item + "\n")
            last_out = time.time()
    rc = proc.wait()
    if timed_out:
        _record("run", "FAIL", f"timed out after {timeout} s")
        return False
    dt = (time.time() - t0) / 60
    ok = rc == 0 and os.path.exists(os.path.join(rd, "link_performance.csv")) \
        and os.path.getsize(os.path.join(rd, "link_performance.csv")) > 0
    if ok:
        try:
            sys.path.insert(0, REPO)
            from dtalite_qa import manifest as _manifest, report_html as _report_html
            man = _manifest.build_run_manifest(rd, scenario=GMNS, exe=exe,
                                               intake_gate="READY")
            with open(os.path.join(rd, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(man, f, indent=1, default=str)
            _report_html.build_report(rd, out_html=os.path.join(rd, "report.html"),
                                      project_name="ARC Atlanta 2020 AM")
            _say("  reproducibility record: manifest.json + report.html written")
        except Exception as exc:
            _say(f"  note: run succeeded; manifest/report skipped ({exc})")
    _record("run", "OK" if ok else "FAIL",
            f"{dt:.1f} min, console log: {os.path.relpath(logp, HERE)}" if ok
            else f"kernel exit {rc}; see {os.path.relpath(logp, HERE)}")
    return ok


# --------------------------------------------------------------- stage: validate
def stage_validate(quick=False, run_dir=None):
    rd = run_dir or (RUN_QUICK_DIR if quick else RUN_FULL_DIR)
    if not os.path.exists(os.path.join(rd, "link_performance.csv")):
        _record("validate", "FAIL", f"no link_performance.csv in {os.path.basename(rd)}/ -- "
                f"run `python arc_pipeline.py run{' --quick' if quick else ''}` first")
        return False
    if not os.path.exists(os.path.join(HERE, "arc_am_ref_volume.csv")):
        _say("  extracting the ARC reference volumes first (arc_benchmark.py) ...")
        rc, _ = _capture([sys.executable, "arc_benchmark.py"], tail=5)
        if rc != 0:
            _record("validate", "FAIL", "arc_benchmark.py could not build the reference")
            return False
    rc, out = _capture([sys.executable, "arc_validate_run.py", rd], tail=15)
    m = re.search(r"region-wide %RMSE = (\d+)%", out)
    if rc != 0 or not m:
        _record("validate", "FAIL", "could not compute %RMSE")
        return False
    rmse = int(m.group(1))
    # machine-readable record next to the run (per-group rows parsed from the report)
    ratio_m = re.search(r"assigned/ref total = ([\d.]+)", out)
    rows = [dict(group=g[0], n=int(g[1].replace(",", "")), rmse_pct=int(g[2]),
                 target_pct=int(g[3]), assigned_ref_ratio=float(g[4]),
                 passed=g[5] == "Y")
            for g in re.findall(
                r"(\d+k-\S+)\s+([\d,]+)\s+(\d+)%\s+(\d+)%\s+([\d.]+)\s+(Y|n)", out)]
    with open(os.path.join(rd, "arc_validation.json"), "w", encoding="utf-8") as f:
        json.dump({"region_rmse_pct": rmse,
                   "assigned_ref_ratio": float(ratio_m.group(1)) if ratio_m else None,
                   "arc_target_pct": 38, "quick_smoke": bool(quick),
                   "groups": rows}, f, indent=2)
    if quick:
        _record("validate", "INFO", f"%RMSE {rmse}% after the 1-iteration smoke run -- "
                "NOT the converged number; run the full pipeline for the real ~22%")
        return True
    ok = rmse <= 38
    _record("validate", "PASS" if ok else "FAIL",
            f"region-wide %RMSE {rmse}% vs ARC target ~38% (expected ~22%)")
    return ok


# ----------------------------------------------------------------------- summary
def summary():
    _banner("SUMMARY")
    if not RESULTS:
        _say(" (nothing ran)")
        return True
    width = max(len(s) for s, _, _ in RESULTS) + 2
    for stage, status, detail in RESULTS:
        _say(f" {stage:<{width}}{status:<8}{detail}")
    bad = [s for s, st, _ in RESULTS if st == "FAIL"]
    _say("=" * 72)
    if bad:
        _say(" RESULT: FAILED at: " + ", ".join(bad))
        _say(" Fix the first failure above, then rerun that stage alone.")
    else:
        _say(" RESULT: all executed stages passed.")
    return not bad


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="arc_pipeline.py",
        description="ARC Atlanta stage-by-stage pipeline (see module docstring)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", aliases=["doctor"],
                   help="fast preflight: deps, kernel, data, intake, VDF/PLF")
    sub.add_parser("inspect", help="scenario summary: zones, links, VDF, modes, settings")
    sp = sub.add_parser("convert", help="PATH B only: raw ARC data -> gmns/")
    sp.add_argument("--from-raw", action="store_true",
                    help="fail loudly if the raw data is absent (default: skip cleanly)")
    sp.add_argument("--source-root", default=None,
                    help="folder to search recursively for the raw ARC files "
                         "(AMNode2020/AMLink2020 shapefiles + the six trip cores)")
    sub.add_parser("build", help="build the kernel (bash build.sh, else direct CMake)")
    sp = sub.add_parser("prepare", help="verify + copy gmns/ -> run folder, set solver")
    sp.add_argument("--quick", action="store_true", help="1-iteration smoke configuration")
    sp.add_argument("--iterations", type=int, dest="number_of_iterations")
    sp.add_argument("--gap", type=float, dest="convergence_gap_pct",
                    help="relative-gap stop, in percent (default 0.5)")
    sp.add_argument("--processors", type=int, dest="number_of_processors")
    sp = sub.add_parser("run", help="run the kernel (live output; --quick = smoke)")
    sp.add_argument("--quick", action="store_true")
    sp.add_argument("--dir", default=None, help="run folder (default gmns_run[/quick])")
    sp.add_argument("--timeout", type=int, default=7200,
                    help="kill the kernel after this many seconds (default 7200)")
    sp = sub.add_parser("validate", help="%RMSE vs the ARC count benchmark")
    sp.add_argument("--quick", action="store_true")
    sp.add_argument("--dir", default=None)
    sp = sub.add_parser("all", help="check+prepare; add --quick or --full to also run")
    sp.add_argument("--quick", action="store_true", help="append smoke run + validation")
    sp.add_argument("--full", action="store_true", help="append FULL run + validation")
    sp.add_argument("--from-raw", action="store_true")
    a = ap.parse_args(argv)

    ok = True
    if a.cmd in ("check", "doctor"):
        ok = stage_check()
    elif a.cmd == "inspect":
        ok = stage_inspect()
    elif a.cmd == "convert":
        ok = stage_convert(from_raw=a.from_raw, source_root=a.source_root)
    elif a.cmd == "build":
        ok = stage_build()
    elif a.cmd == "prepare":
        ok = stage_prepare(quick=a.quick,
                           number_of_iterations=a.number_of_iterations,
                           convergence_gap_pct=a.convergence_gap_pct,
                           number_of_processors=a.number_of_processors)
    elif a.cmd == "run":
        ok = stage_run(quick=a.quick, run_dir=a.dir, timeout=a.timeout)
    elif a.cmd == "validate":
        ok = stage_validate(quick=a.quick, run_dir=a.dir)
    elif a.cmd == "all":
        _banner("STAGE 1 -- check")
        ok = stage_check()
        if ok:
            _banner("STAGE 1b -- convert (PATH B only; skips on PATH A)")
            ok = stage_convert(from_raw=a.from_raw)
        if ok:
            _banner("STAGE 2 -- prepare")
            ok = stage_prepare(quick=a.quick)
        if ok and (a.quick or a.full):
            _banner("STAGE 3 -- run " + ("(smoke)" if a.quick else "(FULL)"))
            ok = stage_run(quick=a.quick)
            if ok:
                _banner("STAGE 4 -- validate")
                ok = stage_validate(quick=a.quick)
        elif ok:
            _say("\n  Prepared but NOT run (a full 6,031-zone run is never launched")
            _say("  without your say-so). Next, exactly one of:")
            _say("    python arc_pipeline.py run --quick   # ~2 min smoke test first")
            _say("    python arc_pipeline.py run           # the real ~5-6 min run")
            _say("  then:")
            _say("    python arc_pipeline.py validate")
    return summary() and ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
