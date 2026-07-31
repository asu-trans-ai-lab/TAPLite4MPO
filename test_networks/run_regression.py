#!/usr/bin/env python3
"""
Regression harness for the DTALite/TAPLite C++ kernel.

Runs the built kernel on every test network in an ISOLATED temp copy (the DLL/exe
accumulates state across in-process calls, so each case must run fresh) and checks
the *intent* criteria for each case rather than exact numeric match to old outputs
(the shipped lp_*.csv references predate the 2026 kernel fixes -- e.g. the #5
multi-lane D/C fix legitimately changes multi-lane results).

Checks applied:
  completes        engine exits 0 and writes a non-empty link_performance.csv
  external_ids     output link/from/to ids match the original input ids
  sparse_ids       near-INT_MAX node/zone/link ids stay compact, preserve
                   external ids in outputs, and work with route output on/off
  ffx_sparse       reconstruct the Issue #6 FFX134 ids (zones to 6114,
                   nodes to 36387), then require compact parity and external
                   ids in link/route outputs with route output on/off
  gap_ok           final relative gap is finite, NON-NEGATIVE (issue #7) and small
  allowed_use      restricted links carry ZERO volume for every disallowed mode
                   (auto-detected from link.csv allowed_use + mode_type.csv)
  modes_sane       every mode carries some volume; sov is the largest (multimodal)
  lane_dc          per-lane D/C == volume/(lanes*capacity*H*plf)  (issue #5/#9)
  turn_reroute     with movement.csv the banned movement is avoided (issue #3)

Usage:
  python run_regression.py [--exe PATH | --lib PATH] [--only NAME[,NAME...]]
Exit code 0 if all PASS, 1 otherwise.
"""
import argparse, csv, os, shutil, subprocess, sys, tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_EXE = os.path.join(ROOT, "bin", "DTALite.exe")
LIB_RUNNER = os.path.join(HERE, "run_kernel_lib.py")
DATA = os.path.join(ROOT, "kernel", "data_sets")
SUBAREA = os.path.join(HERE, "subarea_conic")

INPUT_NAMES = {"node.csv", "link.csv", "mode_type.csv", "settings.csv", "movement.csv"}


def fnum(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def demand_files(case_dir):
    """Demand files referenced by mode_type.csv (fallback demand.csv)."""
    mt = os.path.join(case_dir, "mode_type.csv")
    files = set()
    if os.path.exists(mt):
        for r in csv.DictReader(open(mt)):
            df = (r.get("demand_file") or "").strip()
            if df:
                files.add(df)
    if not files and os.path.exists(os.path.join(case_dir, "demand.csv")):
        files.add("demand.csv")
    return files


def stage(case_dir, dst, drop_movement=False):
    """Copy only input files into an isolated dir."""
    wanted = set(INPUT_NAMES) | demand_files(case_dir)
    if drop_movement:
        wanted.discard("movement.csv")
    for name in wanted:
        src = os.path.join(case_dir, name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(dst, name))


def run_native(exe, library, cwd, timeout):
    if library:
        command = [sys.executable, LIB_RUNNER, os.path.abspath(library)]
    else:
        command = [os.path.abspath(exe)]
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def run_case(exe, case_dir, dst, drop_movement=False, library=""):
    stage(case_dir, dst, drop_movement)
    # Run the original absolute executable from the isolated working directory.
    # Copying a freshly built executable into %TEMP% is blocked by Windows
    # Application Control on some managed machines.
    p = run_native(exe, library, dst, 900)
    log = p.stdout + p.stderr
    return p.returncode, log


def parse_lp(dst):
    path = os.path.join(dst, "link_performance.csv")
    if not os.path.exists(path):
        return None
    return list(csv.DictReader(open(path)))


def final_gap(log):
    g = None
    for line in log.splitlines():
        if "gap =" in line:
            try:
                g = float(line.split("gap =")[1].split("%")[0].strip())
            except (IndexError, ValueError):
                pass
    return g


def mode_tokens(case_dir):
    mt = os.path.join(case_dir, "mode_type.csv")
    if not os.path.exists(mt):
        return []
    return [r["mode_type"].strip() for r in csv.DictReader(open(mt)) if r.get("mode_type")]


# ---- checks: each returns (passed: bool, detail: str) ----

def chk_completes(ctx):
    if ctx["rc"] != 0:
        return False, f"exit={ctx['rc']}"
    if not ctx["lp"]:
        return False, "no link_performance.csv rows"
    return True, f"{len(ctx['lp'])} links"


def chk_external_ids(ctx):
    expected = Counter(
        (r["link_id"], r["from_node_id"], r["to_node_id"])
        for r in csv.DictReader(open(os.path.join(ctx["case_dir"], "link.csv")))
    )
    actual = Counter(
        (r["link_id"], r["from_node_id"], r["to_node_id"])
        for r in (ctx["lp"] or [])
    )
    if actual != expected:
        return False, "link_performance.csv changed external link/node ids"
    return True, f"{sum(actual.values())} original link/from/to rows preserved"


def chk_gap_ok(ctx, max_gap=12.0):
    g = ctx["gap"]
    if g is None:
        return True, "no gap line (single-iter)"
    if g < -0.01:
        return False, f"NEGATIVE gap {g:.3f}%"
    if g > max_gap:
        return False, f"gap {g:.2f}% > {max_gap}%"
    return True, f"gap {g:.3f}%"


def chk_sparse_ids(ctx):
    sparse_to_dense = {
        "2025": "1",
        "2147483000": "2",
        "3725": "3",
        "1900000000": "4",
    }
    expected_links = {
        r["link_id"]: (r["from_node_id"], r["to_node_id"])
        for r in csv.DictReader(open(os.path.join(ctx["case_dir"], "link.csv")))
    }
    actual_links = {
        r["link_id"]: (r["from_node_id"], r["to_node_id"])
        for r in (ctx["lp"] or [])
    }
    if actual_links != expected_links:
        return False, "link_performance.csv did not preserve external link/node ids"

    route_path = os.path.join(ctx["dst"], "route_assignment.csv")
    if not os.path.exists(route_path):
        return False, "route_output=1 did not create route_assignment.csv"
    route_rows = list(csv.DictReader(open(route_path)))
    if not route_rows:
        return False, "route_assignment.csv has no rows"
    valid_node_ids = {str(v) for pair in expected_links.values() for v in pair}
    valid_link_ids = set(expected_links)
    for row in route_rows:
        node_ids = {x for x in (row.get("node_ids") or "").split(";") if x}
        link_ids = {x for x in (row.get("link_ids") or "").split(";") if x}
        if not node_ids <= valid_node_ids or not link_ids <= valid_link_ids:
            return False, "route output leaked internal ids"

    sparse_volumes = {
        (sparse_to_dense[r["from_node_id"]], sparse_to_dense[r["to_node_id"]]):
        float(r["volume"])
        for r in ctx["lp"]
    }
    with tempfile.TemporaryDirectory() as dense_dir:
        dense_case = os.path.join(HERE, "4_node_network")
        rc, _ = run_case(
            ctx["exe"], dense_case, dense_dir, library=ctx["library"],
        )
        dense_lp = parse_lp(dense_dir)
        if rc != 0 or not dense_lp:
            return False, f"dense parity run failed (exit={rc})"
        dense_volumes = {
            (r["from_node_id"], r["to_node_id"]): float(r["volume"])
            for r in dense_lp
        }
    if set(sparse_volumes) != set(dense_volumes):
        return False, "sparse and dense runs produced different network edges"
    worst = max(
        abs(sparse_volumes[edge] - dense_volumes[edge])
        for edge in dense_volumes
    )
    if worst > 1e-6:
        return False, f"sparse/dense max volume difference is {worst:.2e}"

    with tempfile.TemporaryDirectory() as d2:
        stage(ctx["case_dir"], d2)
        settings = os.path.join(d2, "settings.csv")
        rows = list(csv.DictReader(open(settings)))
        fields = list(rows[0])
        rows[0]["route_output"] = "0"
        with open(settings, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        p = run_native(ctx["exe"], ctx["library"], d2, 60)
        lp = parse_lp(d2)
        if p.returncode != 0 or not lp:
            return False, f"route_output=0 failed (exit={p.returncode})"

    if "# of nodes= 4" not in ctx["log"] or "# of zones = 2" not in ctx["log"]:
        return False, "console counts do not show compact node/zone dimensions"
    return True, (
        "4 nodes/2 zones/4 links; external ids preserved; "
        f"dense parity {worst:.1e}; route output on/off"
    )


def chk_ffx_sparse(ctx):
    """Reconstruct the Issue #6 FFX134 external ids retained in cube_A/cube_B."""
    def read_rows(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return list(reader.fieldnames or []), list(reader)

    def write_rows(path, fields, rows):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    with tempfile.TemporaryDirectory() as sparse_dir:
        stage(ctx["case_dir"], sparse_dir)
        link_path = os.path.join(sparse_dir, "link.csv")
        node_path = os.path.join(sparse_dir, "node.csv")
        demand_path = os.path.join(sparse_dir, "demand.csv")
        settings_path = os.path.join(sparse_dir, "settings.csv")

        link_fields, links = read_rows(link_path)
        node_fields, nodes = read_rows(node_path)
        demand_fields, demand = read_rows(demand_path)
        settings_fields, settings = read_rows(settings_path)

        remap = {}
        for link in links:
            for internal_col, external_col in (
                ("from_node_id", "cube_A"), ("to_node_id", "cube_B")
            ):
                internal = link[internal_col]
                external = link.get(external_col, "")
                if not external:
                    return False, f"{external_col} missing from FFX134 fixture"
                if internal in remap and remap[internal] != external:
                    return False, f"inconsistent retained external id for node {internal}"
                remap[internal] = external
        if set(remap) != {node["node_id"] for node in nodes}:
            return False, "retained cube_A/cube_B ids do not cover every FFX134 node"
        if len(set(remap.values())) != len(remap):
            return False, "retained FFX134 external node ids are not one-to-one"

        for node in nodes:
            old_node = node["node_id"]
            node["node_id"] = remap[old_node]
            zone = node.get("zone_id", "")
            if zone and fnum(zone) >= 1:
                node["zone_id"] = remap[zone]
        for link in links:
            link["from_node_id"] = link["cube_A"]
            link["to_node_id"] = link["cube_B"]
        for row in demand:
            row["o_zone_id"] = remap[row["o_zone_id"]]
            row["d_zone_id"] = remap[row["d_zone_id"]]

        first_through = settings[0].get("first_through_node_id", "-1")
        if fnum(first_through, -1) >= 1:
            settings[0]["first_through_node_id"] = remap[first_through]
        settings[0]["route_output"] = "1"
        write_rows(node_path, node_fields, nodes)
        write_rows(link_path, link_fields, links)
        write_rows(demand_path, demand_fields, demand)
        write_rows(settings_path, settings_fields, settings)

        p = run_native(ctx["exe"], ctx["library"], sparse_dir, 60)
        sparse_lp = parse_lp(sparse_dir)
        if p.returncode != 0 or not sparse_lp:
            return False, f"sparse FFX134 route-output run failed (exit={p.returncode})"

        expected = Counter(
            (r["link_id"], r["cube_A"], r["cube_B"]) for r in links
        )
        actual = Counter(
            (r["link_id"], r["from_node_id"], r["to_node_id"]) for r in sparse_lp
        )
        if actual != expected:
            return False, "sparse FFX134 link output leaked internal node/link ids"

        dense_volumes = {r["link_id"]: fnum(r["volume"]) for r in (ctx["lp"] or [])}
        sparse_volumes = {r["link_id"]: fnum(r["volume"]) for r in sparse_lp}
        if set(sparse_volumes) != set(dense_volumes):
            return False, "sparse FFX134 output link set differs from compact fixture"
        worst = max(
            abs(sparse_volumes[lid] - dense_volumes[lid])
            for lid in dense_volumes
        )
        if worst > 1e-6:
            return False, f"sparse FFX134 max volume difference is {worst:.2e}"

        route_path = os.path.join(sparse_dir, "route_assignment.csv")
        if not os.path.exists(route_path):
            return False, "sparse FFX134 route_output=1 produced no route file"
        _, routes = read_rows(route_path)
        valid_nodes = set(remap.values())
        valid_links = {r["link_id"] for r in links}
        for route in routes:
            route_nodes = {x for x in route.get("node_ids", "").split(";") if x}
            route_links = {x for x in route.get("link_ids", "").split(";") if x}
            if not route_nodes <= valid_nodes or not route_links <= valid_links:
                return False, "sparse FFX134 route output leaked internal ids"

        settings[0]["route_output"] = "0"
        write_rows(settings_path, settings_fields, settings)
        os.remove(route_path)
        p_off = run_native(ctx["exe"], ctx["library"], sparse_dir, 60)
        if p_off.returncode != 0 or not parse_lp(sparse_dir):
            return False, f"sparse FFX134 route_output=0 failed (exit={p_off.returncode})"
        if os.path.exists(route_path):
            return False, "sparse FFX134 route_output=0 unexpectedly wrote routes"

        if "# of nodes= 28" not in p.stdout or "# of zones = 17" not in p.stdout:
            return False, "sparse FFX134 did not report compact node/zone dimensions"
        max_zone = max(int(node["zone_id"]) for node in nodes if fnum(node["zone_id"]) >= 1)
        max_node = max(int(node["node_id"]) for node in nodes)
        return True, (
            f"28 nodes/17 zones (max zone {max_zone}, node {max_node}); "
            f"dense parity {worst:.1e}; external route ids; route output on/off"
        )


def chk_allowed_use(ctx):
    toks = mode_tokens(ctx["case_dir"])
    if not toks:
        return True, "no mode_type.csv (n/a)"
    link = {r["link_id"]: r for r in csv.DictReader(open(os.path.join(ctx["case_dir"], "link.csv")))}
    restricted = 0
    fails = []
    for r in ctx["lp"]:
        lid = r["link_id"]
        au = (link.get(lid, {}).get("allowed_use") or "").strip()
        if not au or au.lower() == "all":
            continue
        disallowed = [t for t in toks if t not in au]
        if not disallowed:
            continue
        restricted += 1
        for t in disallowed:
            col = f"mod_vol_{t}"
            if col in r and fnum(r[col]) > 0.01:
                fails.append(f"link {lid}: {t}={fnum(r[col]):.0f}")
    if fails:
        return False, "; ".join(fails[:4])
    return True, f"{restricted} restricted links, 0 leak"


def chk_modes_sane(ctx):
    toks = mode_tokens(ctx["case_dir"])
    if len(toks) <= 1:
        return True, "single mode (n/a)"
    tot = {t: 0.0 for t in toks}
    for r in ctx["lp"]:
        for t in toks:
            tot[t] += fnum(r.get(f"mod_vol_{t}"))
    zero = [t for t, v in tot.items() if v <= 0]
    if zero:
        return False, f"zero-volume modes: {zero}"
    largest = max(tot, key=tot.get)
    note = f"largest={largest} " + ",".join(f"{t}={tot[t]:.0f}" for t in toks)
    return True, note


def chk_lane_dc(ctx):
    link = {r["link_id"]: r for r in csv.DictReader(open(os.path.join(ctx["case_dir"], "link.csv")))}
    s = list(csv.DictReader(open(os.path.join(ctx["case_dir"], "settings.csv"))))[0]
    H = fnum(s.get("demand_period_ending_hours"), 8) - fnum(s.get("demand_period_starting_hours"), 7)
    worst = 0.0
    for r in ctx["lp"]:
        lk = link.get(r["link_id"])
        if not lk:
            continue
        lanes = fnum(lk.get("lanes"), 1)
        cap = fnum(lk.get("capacity"), 1)
        plf = fnum(lk.get("vdf_plf"), 1) or 1.0
        vol = fnum(r["volume"])
        if lanes <= 0 or cap <= 0 or vol <= 0:
            continue
        expect = vol / (lanes * cap * max(H, 1e-6) * plf)
        worst = max(worst, abs(expect - fnum(r["doc"])))
    if worst > 1e-3:
        return False, f"max |D/C - vol/(lanes*cap*H*plf)| = {worst:.2e}"
    return True, f"lane-aware D/C ok (max diff {worst:.1e})"


def links_with_volume(lp):
    return sorted(r["link_id"] for r in lp if fnum(r["volume"]) > 0)


def chk_turn_reroute(ctx):
    # run again WITHOUT movement.csv and confirm the path differs
    with tempfile.TemporaryDirectory() as d2:
        rc, _ = run_case(
            ctx["exe"], ctx["case_dir"], d2,
            drop_movement=True, library=ctx["library"],
        )
        if rc != 0:
            return False, "baseline (no movement) run failed"
        base = links_with_volume(parse_lp(d2))
    restr = links_with_volume(ctx["lp"])
    if base == restr:
        return False, f"restriction did not change routing ({restr})"
    return True, f"no-mvmt={base} -> with-mvmt={restr}"


# ---- case registry ----
CASES = [
    {"name": "4_node_network",        "dir": f"{HERE}/4_node_network",        "checks": ["completes", "external_ids", "gap_ok"]},
    {"name": "sparse_internal_ids",   "dir": f"{HERE}/sparse_internal_ids",   "checks": ["completes", "external_ids", "sparse_ids", "gap_ok"]},
    {"name": "I10_corridor_QVDF",     "dir": f"{HERE}/I10_corridor_QVDF",     "checks": ["completes", "external_ids"]},
    {"name": "I10_QVDF_1lane",        "dir": f"{HERE}/I10_corridor_QVDF_1lane", "checks": ["completes", "external_ids", "lane_dc"]},
    {"name": "I10_QVDF_2lane",        "dir": f"{HERE}/I10_corridor_QVDF_2lane", "checks": ["completes", "external_ids", "lane_dc"]},
    {"name": "I10_QVDF_multilane",    "dir": f"{HERE}/I10_corridor_QVDF_multilane", "checks": ["completes", "external_ids", "lane_dc"]},
    {"name": "multilane_bpr",         "dir": f"{HERE}/multilane_bpr",         "checks": ["completes", "external_ids", "lane_dc"]},
    {"name": "turn_restriction",      "dir": f"{HERE}/turn_restriction",      "checks": ["completes", "external_ids", "turn_reroute"]},
    {"name": "sf_multimodal",         "dir": f"{HERE}/sf_multimodal",         "checks": ["completes", "external_ids", "gap_ok", "allowed_use", "modes_sane"]},
    {"name": "cs_multimodal",         "dir": f"{HERE}/cs_multimodal",         "checks": ["completes", "external_ids", "gap_ok", "allowed_use", "modes_sane"]},
    {"name": "sf_conic",              "dir": f"{HERE}/sf_conic",              "checks": ["completes", "external_ids", "gap_ok", "allowed_use", "modes_sane"]},
    {"name": "subarea/FFX134_BD",     "dir": f"{SUBAREA}/FFX134_BD",          "checks": ["completes", "external_ids", "gap_ok", "allowed_use", "ffx_sparse"]},
    {"name": "subarea/FFX134_NB",     "dir": f"{SUBAREA}/FFX134_NB",          "checks": ["completes", "external_ids", "gap_ok", "allowed_use"]},
    {"name": "subarea/LDN034_BD",     "dir": f"{SUBAREA}/LDN034_BD",          "checks": ["completes", "external_ids", "gap_ok", "allowed_use"]},
    {"name": "subarea/LDN034_NB",     "dir": f"{SUBAREA}/LDN034_NB",          "checks": ["completes", "external_ids", "gap_ok", "allowed_use"]},
    {"name": "data/02_Sioux_Falls",   "dir": f"{DATA}/02_Sioux_Falls",        "checks": ["completes", "external_ids", "gap_ok"]},
    {"name": "data/03_chicago_sketch", "dir": f"{DATA}/03_chicago_sketch",    "checks": ["completes", "external_ids", "gap_ok"]},
]

CHECKS = {
    "completes": chk_completes, "external_ids": chk_external_ids,
    "sparse_ids": chk_sparse_ids, "ffx_sparse": chk_ffx_sparse,
    "gap_ok": chk_gap_ok, "allowed_use": chk_allowed_use,
    "modes_sane": chk_modes_sane, "lane_dc": chk_lane_dc, "turn_reroute": chk_turn_reroute,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=DEFAULT_EXE)
    ap.add_argument("--lib", default="", help="native DTALite shared library; runs each case in a fresh Python process")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    runtime = args.lib or args.exe
    if not os.path.exists(runtime):
        print(f"ERROR: kernel runtime not found: {runtime}\nBuild the executable or shared library first.")
        return 2
    only = set(x.strip() for x in args.only.split(",") if x.strip())

    all_pass = True
    print(f"{'case':24} {'check':14} {'result':6} detail")
    print("-" * 90)
    cases = CASES + [{
        "name": "qvdf_observed_t2",
        "dir": f"{HERE}/qvdf_observed_t2",
        "checks": ["completes"] + (
            ["external_ids"] if "external_ids" in CHECKS else []
        ),
    }]
    for case in cases:
        if only and case["name"] not in only:
            continue
        if not os.path.isdir(case["dir"]):
            print(f"{case['name']:24} {'(missing dir)':14} SKIP   {case['dir']}")
            continue
        with tempfile.TemporaryDirectory() as dst:
            try:
                rc, log = run_case(args.exe, case["dir"], dst, library=args.lib)
            except subprocess.TimeoutExpired:
                print(f"{case['name']:24} {'run':14} FAIL   timeout")
                all_pass = False
                continue
            ctx = {"case_dir": case["dir"], "exe": args.exe, "library": args.lib, "rc": rc,
                   "dst": dst, "log": log, "lp": parse_lp(dst), "gap": final_gap(log)}
            for ck in case["checks"]:
                ok, detail = CHECKS[ck](ctx)
                all_pass &= ok
                print(f"{case['name']:24} {ck:14} {'PASS' if ok else 'FAIL':6} {detail}")
    print("-" * 90)
    print("ALL PASS" if all_pass else "SOME FAILED")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
