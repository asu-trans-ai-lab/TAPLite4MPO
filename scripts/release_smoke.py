#!/usr/bin/env python3
"""Release smoke test -- ONE self-checking command that proves a build passes
every public-network QA/QC gate before it ships.

    python scripts/release_smoke.py            # quick (~5 min): gates G1-G7
    python scripts/release_smoke.py --full     # + the full ARC equilibrium
                                               #   (region %RMSE must be <= 38)

Gates (all on PUBLIC data -- no agency files needed):
  G1  kernel        bin/TAPLite.exe present (or legacy DTALite name)
  G2  regression    test_networks/run_regression.py -> ALL PASS
  G3  sparse ids    synthetic sparse relabel of the 4-node network fed to the
                    kernel DIRECTLY: must run, keep ORIGINAL ids in outputs,
                    and match the dense run's volumes (locks in issue #6)
  G4  ARC gates     arc_pipeline check: intake GATE READY + VDF/PLF verify OK
  G5  ARC smoke     arc_pipeline all --quick: 1-iteration run + validation
                    (--full instead runs the real equilibrium and ENFORCES
                    region %RMSE <= 38)
  G6  NVTA safety   nvta_pipeline check with NO data configured: must skip
                    cleanly with the "EXPECTED" message and exit 0
  G7  package API   pytaplite on Chicago Sketch: assign (quick), accessibility
                    (od skim non-empty), demand_to_binary + binary assign,
                    superzone build + assign on the compressed scenario

Exit code 0 only when every gate passes. ASCII-only output (CI/legacy consoles).
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
IS_WIN = sys.platform == "win32"
GATES = []


def record(gate, ok, detail):
    GATES.append((gate, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {gate} -- {detail}", flush=True)
    return ok


def run(cmd, cwd=REPO, timeout=1800):
    env = os.environ.copy()
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                       errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def kernel_path():
    names = ["TAPLite.exe", "TAPLite", "DTALite.exe", "DTALite"]
    for n in names:
        p = os.path.join(REPO, "bin", n)
        if os.path.exists(p):
            return p
    return None


# --------------------------------------------------------------------- gates
def g1_kernel():
    exe = kernel_path()
    if exe:
        return record("G1 kernel", True, os.path.relpath(exe, REPO))
    rc, _ = run(["bash", "build.sh"])
    exe = kernel_path()
    return record("G1 kernel", exe is not None,
                  os.path.relpath(exe, REPO) if exe else
                  "bash build.sh failed -- cmake + C++ compiler required")


def g2_regression():
    rc, out = run([sys.executable, os.path.join("test_networks", "run_regression.py")])
    ok = rc == 0 and "ALL PASS" in out
    fails = [ln.strip() for ln in out.splitlines() if "FAIL" in ln][:3]
    return record("G2 regression suite", ok,
                  "ALL PASS" if ok else ("; ".join(fails) or f"rc={rc}"))


def g3_sparse_ids(workdir):
    """Synthetic issue-#6 repro: relabel the 4-node network's ids to sparse
    values, feed the kernel DIRECTLY, require original ids + dense-run parity."""
    src = os.path.join(REPO, "kernel", "data_sets", "01_4_node_network")
    relabel = {1: 2025, 2: 3725, 3: 5098, 4: 6114}

    def read(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            r = csv.DictReader(f)
            return r.fieldnames, list(r)

    def write(path, hdr, rows):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=hdr)
            w.writeheader()
            w.writerows(rows)

    def stage(dest, mapping):
        os.makedirs(dest, exist_ok=True)
        hdr, rows = read(os.path.join(src, "node.csv"))
        for r in rows:
            r["node_id"] = mapping.get(int(r["node_id"]), r["node_id"])
            if r.get("zone_id") and int(float(r["zone_id"])) >= 1:
                r["zone_id"] = mapping.get(int(float(r["zone_id"])), r["zone_id"])
        write(os.path.join(dest, "node.csv"), hdr, rows)
        hdr, rows = read(os.path.join(src, "link.csv"))
        for r in rows:
            r["from_node_id"] = mapping.get(int(r["from_node_id"]), r["from_node_id"])
            r["to_node_id"] = mapping.get(int(r["to_node_id"]), r["to_node_id"])
        write(os.path.join(dest, "link.csv"), hdr, rows)
        hdr, rows = read(os.path.join(src, "demand.csv"))
        for r in rows:
            r["o_zone_id"] = mapping.get(int(r["o_zone_id"]), r["o_zone_id"])
            r["d_zone_id"] = mapping.get(int(r["d_zone_id"]), r["d_zone_id"])
        write(os.path.join(dest, "demand.csv"), hdr, rows)
        write(os.path.join(dest, "settings.csv"),
              ["number_of_iterations", "number_of_processors",
               "demand_period_starting_hours", "demand_period_ending_hours",
               "route_output", "log_file"],
              [{"number_of_iterations": 3, "number_of_processors": 2,
                "demand_period_starting_hours": 7, "demand_period_ending_hours": 8,
                "route_output": 0, "log_file": 0}])
        shutil.copy(kernel_path(), os.path.join(dest, os.path.basename(kernel_path())))

    dense = os.path.join(workdir, "g3_dense")
    sparse = os.path.join(workdir, "g3_sparse")
    stage(dense, {})
    stage(sparse, relabel)
    exe = os.path.basename(kernel_path())
    rc_d, _ = run([os.path.join(dense, exe)], cwd=dense, timeout=300)
    rc_s, out_s = run([os.path.join(sparse, exe)], cwd=sparse, timeout=300)
    if rc_d != 0 or rc_s != 0:
        return record("G3 sparse ids", False, f"kernel rc dense={rc_d} sparse={rc_s}")
    if "sparse zone ids detected" not in out_s:
        return record("G3 sparse ids", False, "renumbering NOTE not printed")

    def volumes(d, mapping):
        _, rows = read(os.path.join(d, "link_performance.csv"))
        return {(mapping.get(int(r["from_node_id"]), int(r["from_node_id"])),
                 mapping.get(int(r["to_node_id"]), int(r["to_node_id"]))):
                float(r["volume"]) for r in rows}

    vd = volumes(dense, relabel)          # dense keys mapped INTO sparse ids
    vs = volumes(sparse, {})              # sparse output should already be sparse ids
    if set(vs) != set(vd):
        return record("G3 sparse ids", False,
                      "output ids differ from the original external ids")
    worst = max(abs(vs[k] - vd[k]) for k in vs) if vs else 1e9
    return record("G3 sparse ids", worst <= 1e-6,
                  f"original ids kept; max volume diff vs dense run = {worst:.2e}")


def g4_arc_check():
    rc, out = run([sys.executable, "arc_pipeline.py", "check"],
                  cwd=os.path.join(REPO, "examples", "arc_atlanta"))
    ok = rc == 0 and "GATE: READY" in out and "[OK] VDF/PLF verify" in out
    return record("G4 ARC QA gates", ok,
                  "intake READY + VDF/PLF verified" if ok else f"rc={rc}; see arc check")


def g5_arc_run(full):
    arc = os.path.join(REPO, "examples", "arc_atlanta")
    mode = ["all", "--full"] if full else ["all", "--quick"]
    rc, out = run([sys.executable, "arc_pipeline.py"] + mode, cwd=arc, timeout=3600)
    m = re.search(r"region-wide %RMSE = (\d+)%", out)
    if full:
        ok = rc == 0 and m is not None and int(m.group(1)) <= 38
        return record("G5 ARC full equilibrium", ok,
                      f"region %RMSE {m.group(1)}% (gate <= 38%)" if m else f"rc={rc}")
    ok = rc == 0 and m is not None
    return record("G5 ARC smoke run", ok,
                  f"1-iteration run + validation parsed (%RMSE {m.group(1)}%, "
                  "informational)" if m else f"rc={rc}")


def g6_nvta_safety():
    env_backup = os.environ.pop("DTALITE_NVTA_SCENARIO", None)
    try:
        rc, out = run([sys.executable, "nvta_pipeline.py", "check"],
                      cwd=os.path.join(REPO, "nvta_run"))
    finally:
        if env_backup is not None:
            os.environ["DTALITE_NVTA_SCENARIO"] = env_backup
    ok = rc == 0 and "EXPECTED" in out
    return record("G6 NVTA public-safe path", ok,
                  "skips cleanly without agency data" if ok else f"rc={rc}")


def g7_package_api(workdir):
    sys.path.insert(0, REPO)
    import pytaplite
    sk = os.path.join(workdir, "g7_sketch")
    shutil.copytree(os.path.join(REPO, "kernel", "data_sets", "03_chicago_sketch"), sk)
    # prefer_inproc=False: this gate runs FOUR kernel calls in one process;
    # the in-process binding keeps global state (one assignment per process).
    r = pytaplite.assign(sk, prefer_inproc=False,
                         settings_overrides={"number_of_iterations": 3,
                                             "route_output": 0})
    if r.returncode != 0 or not r.links:
        return record("G7 package API", False, f"assign rc={r.returncode}")
    a = pytaplite.accessibility(sk, prefer_inproc=False)
    od_rows = len(a.od)          # capture now: later runs in sk rewrite the file
    if a.returncode != 0 or od_rows == 0:
        return record("G7 package API", False, "accessibility produced no od skim")
    pytaplite.demand_to_binary(sk)
    rb = pytaplite.assign(sk, prefer_inproc=False,
                          settings_overrides={"demand_format": 1,
                                              "number_of_iterations": 3})
    if rb.returncode != 0:
        return record("G7 package API", False, f"binary-demand assign rc={rb.returncode}")
    sz = sk + "_sz"
    pytaplite.superzone(sk, sz, k_target=100)
    rs = pytaplite.assign(sz, prefer_inproc=False,
                          settings_overrides={"number_of_iterations": 3,
                                              "route_output": 0})
    ok = rs.returncode == 0 and len(rs.links) > 0
    return record("G7 package API", ok,
                  f"assign + accessibility ({od_rows:,} od rows) + binary demand "
                  f"+ superzone->assign all rc 0" if ok else f"superzone assign rc={rs.returncode}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="release smoke test (public QA/QC gates)")
    ap.add_argument("--full", action="store_true",
                    help="run the FULL ARC equilibrium and enforce %RMSE <= 38")
    a = ap.parse_args(argv)
    workdir = tempfile.mkdtemp(prefix="taplite_release_smoke_")
    print(f"== TAPLite4MPO release smoke test ({'full' if a.full else 'quick'}) ==")
    print(f"repo: {REPO}\nwork: {workdir}\n")

    ok = g1_kernel()
    if ok:
        for gate in (g2_regression,
                     lambda: g3_sparse_ids(workdir),
                     g4_arc_check,
                     lambda: g5_arc_run(a.full),
                     g6_nvta_safety,
                     lambda: g7_package_api(workdir)):
            try:
                ok = gate() and ok
            except Exception as exc:                      # a gate crashing is a FAIL
                ok = record(getattr(gate, "__name__", "gate"), False,
                            f"exception: {exc}") and ok

    print("\n" + "=" * 72)
    for g, passed, detail in GATES:
        print(f" {g:26} {'PASS' if passed else 'FAIL':6} {detail}")
    print("=" * 72)
    print(" RELEASE GATE:", "PASS -- safe to ship" if ok else "FAIL -- do NOT release")
    shutil.rmtree(workdir, ignore_errors=True)
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
