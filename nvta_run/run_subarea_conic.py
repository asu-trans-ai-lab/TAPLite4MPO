"""
Gate 4 (subarea-first): run our conic CMake kernel on the NVTA cordon subareas
(FFX134_BD/NB, LDN034_BD/NB), AM SOV, and compare per-link volume to the Cube
reference (cube_ref_vol_sov). Tight criteria: total +-0.5%, per-link R2>=0.95,
+-10% band >=70%, zero flow on allowed_use=closed links.

Staged GMNS carry conic in vdf_alpha/vdf_beta (vdf_type=1) + per-link vdf_plf.
"""
import csv, os, math, shutil, subprocess

from data_root import subarea
STAGED = subarea()
HERE = os.path.dirname(os.path.abspath(__file__))
KERNEL = os.path.join(HERE, "..", "bin", "DTALite.exe")
RUNROOT = os.path.join(HERE, "..", "test_networks", "subarea_conic")
SUBAREAS = ["FFX134_BD", "FFX134_NB", "LDN034_BD", "LDN034_NB"]

import sys
ITERS = int(sys.argv[1]) if len(sys.argv) > 1 else 1   # AON-only by default
SETTINGS_HDR = ("number_of_iterations,number_of_processors,demand_period_starting_hours,"
                "demand_period_ending_hours,first_through_node_id,base_demand_mode,route_output,"
                "vehicle_output,log_file,odme_mode,odme_vmt\n")
MODE_TYPE = ("mode_type_id,mode_type,name,vot,pce,occ,demand_file,dedicated_shortest_path\n"
             "1,sov,sov,10,1,1,demand.csv,1\n")

def r2(xs, ys):
    n = len(xs)
    mx, my = sum(xs)/n, sum(ys)/n
    sxx = sum((a-mx)**2 for a in xs); syy = sum((b-my)**2 for b in ys)
    sxy = sum((a-mx)*(b-my) for a, b in zip(xs, ys))
    return (sxy*sxy)/(sxx*syy) if sxx > 0 and syy > 0 else float("nan")

print(f"{'subarea':<12}{'n':>5}{'engine':>10}{'cube':>10}{'ratio':>8}{'bias%':>8}{'R2':>8}{'+-10%':>7}{'closed=0':>9}")
for s in SUBAREAS:
    src = os.path.join(STAGED, f"{s}_am_sov_conic")
    if not os.path.exists(os.path.join(src, "link.csv")):
        print(f"{s:<12} (staged folder missing)"); continue
    run = os.path.join(RUNROOT, s); os.makedirs(run, exist_ok=True)
    # --- RENUMBER zones-first contiguous (1..Z zones, then network nodes) so the
    #     kernel's zone arrays / First-Through-Node detection work (sparse real-
    #     world ids otherwise yield zero assignment, as on regional pm/). ---
    nodes = list(csv.DictReader(open(os.path.join(src, "node.csv"), newline="", encoding="utf-8-sig")))
    def has_zone(r):
        z = (r.get("zone_id") or "").strip()
        return z not in ("", "0", "0.0")
    zone_nodes = [r for r in nodes if has_zone(r)]
    net_nodes  = [r for r in nodes if not has_zone(r)]
    remap = {}
    seq = 1
    zone_remap = {}
    for r in zone_nodes:
        remap[r["node_id"]] = seq
        zone_remap[str(int(float(r["zone_id"])))] = seq
        seq += 1
    for r in net_nodes:
        remap[r["node_id"]] = seq; seq += 1
    # write node.csv (node_id + zone_id remapped, zones first)
    with open(os.path.join(run, "node.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["node_id", "zone_id", "x_coord", "y_coord"])
        for r in zone_nodes + net_nodes:
            nid = remap[r["node_id"]]
            zid = remap[r["node_id"]] if has_zone(r) else 0
            w.writerow([nid, zid, r.get("x_coord", ""), r.get("y_coord", "")])
    # write link.csv (from/to remapped, keep all other cols incl conic + cube_ref)
    lrows = list(csv.DictReader(open(os.path.join(src, "link.csv"), newline="", encoding="utf-8-sig")))
    lfn = list(lrows[0].keys())
    for r in lrows:
        r["from_node_id"] = remap.get(r["from_node_id"], r["from_node_id"])
        r["to_node_id"] = remap.get(r["to_node_id"], r["to_node_id"])
    # CRITICAL: the kernel builds CSR adjacency (FirstLinkFrom/LastLinkFrom)
    # assuming links are sorted by from_node (its sort-error check is disabled).
    # Unsorted links -> wrong adjacency -> corrupted SP tree / pred cycles.
    lrows.sort(key=lambda r: (int(r["from_node_id"]), int(r["to_node_id"])))
    with open(os.path.join(run, "link.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=lfn); w.writeheader()
        for r in lrows:
            w.writerow(r)
    # write demand.csv (o/d zone remapped)
    drows = list(csv.DictReader(open(os.path.join(src, "demand.csv"), newline="")))
    with open(os.path.join(run, "demand.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["o_zone_id", "d_zone_id", "volume"])
        for r in drows:
            o = zone_remap.get(str(int(float(r["o_zone_id"]))))
            d = zone_remap.get(str(int(float(r["d_zone_id"]))))
            if o and d: w.writerow([o, d, r["volume"]])
    # DYNAMIC First Through Node = (#zones)+1 (zones renumbered first 1..Z)
    ftn = len(zone_nodes) + 1
    open(os.path.join(run, "settings.csv"), "w").write(
        SETTINGS_HDR + f"{ITERS},8,6,9,{ftn},0,0,0,0,0,0\n")
    open(os.path.join(run, "mode_type.csv"), "w").write(MODE_TYPE)
    shutil.copy(KERNEL, os.path.join(run, "DTALite.exe"))
    for f in ("link_performance.csv",):
        p = os.path.join(run, f)
        if os.path.exists(p):
            try: os.remove(p)
            except OSError: pass
    try:
        subprocess.run([os.path.join(run, "DTALite.exe")], cwd=run,
                       capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        print(f"{s:<12} TIMEOUT/HANG (zones={len(zone_nodes)}, ftn={ftn}, iters={ITERS})")
        continue
    if not os.path.exists(os.path.join(run, "link_performance.csv")):
        print(f"{s:<12} no link_performance (zones={len(zone_nodes)}, ftn={ftn})"); continue
    # reference + allowed_use by (from,to)
    ref = {}; closed = set()
    for x in csv.DictReader(open(os.path.join(run, "link.csv"), newline="", encoding="utf-8-sig")):
        k = (x["from_node_id"], x["to_node_id"])
        ref[k] = float(x.get("cube_ref_vol_sov", 0) or 0)
        if x.get("allowed_use", "").strip() == "closed": closed.add(k)
    vol = {}
    for x in csv.DictReader(open(os.path.join(run, "link_performance.csv"), newline="")):
        vol[(x["from_node_id"], x["to_node_id"])] = float(x.get("volume", 0) or 0)
    pairs = [(ref[k], vol.get(k, 0.0)) for k in ref if ref[k] > 0]
    xs = [p[0] for p in pairs]; ys = [p[1] for p in pairs]
    eng, cube = sum(ys), sum(xs)
    within10 = 100*sum(1 for a, b in pairs if abs(b-a) <= 0.10*max(a, 1)) / len(pairs)
    closed_leak = sum(vol.get(k, 0.0) for k in closed)
    print(f"{s:<12}{len(pairs):>5}{eng:>10.0f}{cube:>10.0f}{eng/cube:>8.3f}"
          f"{100*(eng-cube)/cube:>7.2f}%{r2(xs,ys):>8.4f}{within10:>6.0f}%"
          f"{('PASS' if closed_leak<1e-6 else f'{closed_leak:.0f}'):>9}")
