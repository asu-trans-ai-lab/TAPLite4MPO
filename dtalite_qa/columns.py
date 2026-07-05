"""DTAC column-store reader + verifier (P2: increments 1 and 2 / L3 full).

The kernel (settings ``column_output=1``) writes ``route_columns.bin`` (DTAC).
Two on-disk versions exist; this module reads BOTH:

v1 (increment 1, single path per OD -- the last-iteration AoN direction):

    header: int32 magic 0x43415444 ('DTAC'), int32 version=1,
            int32 n_modes, int32 n_zones
    then for each mode m=1..n_modes, origin O=1..n_zones (row-major,
    every (m, O) present) one block:
      int32 n_dest
      int32 dest_zone_id[n_dest]
      int32 offsets[n_dest+1]            (offsets[0] == 0)
      int32 external_link_ids[offsets[n_dest]]   (origin -> destination order)

v2 (increment 2 / L3 full: the FULL path set with theta shares, the exact
Frank-Wolfe lambda cascade, duplicate paths merged; shares per (mode, O, D)
sum to 1):

    header: int32 magic, int32 version=2, int32 n_modes, int32 n_zones
    float32 demand_fingerprint[4]   (total, positive cells, min/max zone id)
    then per (mode, origin) block:
      int32 n_dest
      int32 dest_zone_id[n_dest]
      int32 path_offsets[n_dest+1]       (path_offsets[0] == 0)
      float32 theta[n_paths]             (n_paths = path_offsets[n_dest])
      int32 link_offsets[n_paths+1]
      int32 external_link_ids[link_offsets[n_paths]]

The verifier pushes each OD volume (PCE-weighted, as the kernel accumulates
MainVolume) down its stored path(s) -- weighted by theta for v2 -- sums per
link and compares against the run's link_performance volume. For v1 this is
NOT expected to match (link_performance is the FW blend of all iterations,
v1 stores only the final AoN direction; the R^2 quantifies that distance).
For v2 the push-down reconstructs the blend by construction, so R^2 should
be ~1 (residuals: float32 theta rounding, dropped <1e-7 shares, and any OD
demand the kernel itself could not route).

Everything is stdlib-only, consistent with the rest of dtalite_qa.
"""
import csv
import os
import struct

DTAC_MAGIC = 0x43415444
DTLR_MAGIC = 0x524C5444


# ----------------------------------------------------------------------------
# readers
# ----------------------------------------------------------------------------

def read_dtac(path):
    """Read a DTAC file (v1 or v2). Returns dict:
      {"version", "n_modes", "n_zones",
       "fingerprint": (total, cells, min_zone, max_zone) or None (v1),
       "columns": {(mode, orig): [(dest, [(theta, [link_ids...]), ...]), ...]}}
    v1 files appear as one path per dest with theta=1.0.
    Only (mode, origin) blocks with n_dest > 0 appear in "columns".
    """
    with open(path, "rb") as f:
        hdr = f.read(16)
        if len(hdr) < 16:
            raise ValueError(f"{path}: truncated DTAC header")
        magic, version, n_modes, n_zones = struct.unpack("<4i", hdr)
        if magic != DTAC_MAGIC:
            raise ValueError(f"{path}: not a DTAC file (magic 0x{magic:08X})")
        if version not in (1, 2):
            raise ValueError(f"{path}: unknown DTAC version {version}")
        fingerprint = None
        if version >= 2:
            fingerprint = struct.unpack("<4f", f.read(16))
        columns = {}
        for m in range(1, n_modes + 1):
            for orig in range(1, n_zones + 1):
                raw = f.read(4)
                if len(raw) < 4:
                    raise ValueError(f"{path}: truncated at (mode {m}, origin {orig})")
                (n_dest,) = struct.unpack("<i", raw)
                if n_dest == 0:
                    continue
                dests = struct.unpack(f"<{n_dest}i", f.read(4 * n_dest))
                if version == 1:
                    offsets = struct.unpack(f"<{n_dest + 1}i", f.read(4 * (n_dest + 1)))
                    links = struct.unpack(f"<{offsets[-1]}i", f.read(4 * offsets[-1]))
                    entry = [(dest,
                              [(1.0, list(links[offsets[j]:offsets[j + 1]]))])
                             for j, dest in enumerate(dests)]
                else:
                    poff = struct.unpack(f"<{n_dest + 1}i", f.read(4 * (n_dest + 1)))
                    n_paths = poff[-1]
                    thetas = struct.unpack(f"<{n_paths}f", f.read(4 * n_paths)) if n_paths else ()
                    loff = struct.unpack(f"<{n_paths + 1}i", f.read(4 * (n_paths + 1)))
                    links = struct.unpack(f"<{loff[-1]}i", f.read(4 * loff[-1]))
                    entry = []
                    for j, dest in enumerate(dests):
                        paths = [(thetas[p], list(links[loff[p]:loff[p + 1]]))
                                 for p in range(poff[j], poff[j + 1])]
                        entry.append((dest, paths))
                columns[(m, orig)] = entry
    return {"version": version, "n_modes": n_modes, "n_zones": n_zones,
            "fingerprint": fingerprint, "columns": columns}


def _read_modes(run_dir):
    """mode order (1-based, kernel read order) -> {"name", "pce", "demand_file"}."""
    mt = os.path.join(run_dir, "mode_type.csv")
    modes = {}
    if os.path.exists(mt):
        with open(mt, newline="", encoding="utf-8-sig") as f:
            for i, row in enumerate(csv.DictReader(f), start=1):
                modes[i] = {
                    "name": (row.get("mode_type") or f"mode{i}").strip(),
                    "pce": float(row.get("pce") or 1),
                    "demand_file": (row.get("demand_file") or "demand.csv").strip(),
                }
    if not modes:
        modes[1] = {"name": "auto", "pce": 1.0, "demand_file": "demand.csv"}
    return modes


def _read_demand(path):
    """demand CSV -> {(o_zone, d_zone): volume} (duplicates summed)."""
    od = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                o = int(float(row["o_zone_id"]))
                d = int(float(row["d_zone_id"]))
                v = float(row["volume"])
            except (KeyError, TypeError, ValueError):
                continue
            if v > 0 and o != d:
                od[(o, d)] = od.get((o, d), 0.0) + v
    return od


def _read_link_volume(path):
    """link_performance CSV -> {external link_id: volume} (compact or full)."""
    vol = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                vol[int(float(row["link_id"]))] = float(row["volume"])
            except (KeyError, TypeError, ValueError):
                continue
    return vol


# ----------------------------------------------------------------------------
# verifier
# ----------------------------------------------------------------------------

def verify(run_dir, dtac_path=None):
    """Push demand down the stored DTAC paths (theta-weighted for v2) and
    compare per-link sums to the run's link_performance volumes."""
    dtac_path = dtac_path or os.path.join(run_dir, "route_columns.bin")
    lp_path = os.path.join(run_dir, "link_performance.csv")
    store = read_dtac(dtac_path)
    modes = _read_modes(run_dir)
    lp_vol = _read_link_volume(lp_path)

    demand = {}
    demand_missing = []
    for m in range(1, store["n_modes"] + 1):
        info = modes.get(m, {"name": f"mode{m}", "pce": 1.0, "demand_file": "demand.csv"})
        dpath = os.path.join(run_dir, info["demand_file"])
        if os.path.exists(dpath) and dpath.lower().endswith(".csv"):
            demand[m] = _read_demand(dpath)
        else:
            demand[m] = {}
            demand_missing.append(info["demand_file"])

    pushed = {}           # link_id -> pushed volume
    total_ods = 0
    total_paths = 0
    total_link_entries = 0
    demand_pushed = 0.0
    demand_unstored = 0.0  # OD volume with no stored path
    theta_sum_min, theta_sum_max = float("inf"), float("-inf")
    for (m, orig), entry in store["columns"].items():
        pce = modes.get(m, {}).get("pce", 1.0)
        od = demand.get(m, {})
        stored_dests = set()
        for dest, paths in entry:
            stored_dests.add(dest)
            total_ods += 1
            total_paths += len(paths)
            total_link_entries += sum(len(seg) for _, seg in paths)
            v = od.get((orig, dest), 0.0) * pce
            if v <= 0:
                continue
            tsum = sum(t for t, _ in paths)
            theta_sum_min = min(theta_sum_min, tsum)
            theta_sum_max = max(theta_sum_max, tsum)
            demand_pushed += v
            for theta, seg in paths:
                w = v * theta
                if w <= 0:
                    continue
                for lid in seg:
                    pushed[lid] = pushed.get(lid, 0.0) + w
        for (o, d), v in od.items():
            if o == orig and d not in stored_dests:
                demand_unstored += v * pce
    # demand for (m, orig) pairs absent from the store entirely
    for m, od in demand.items():
        stored_origs = {o for (mm, o) in store["columns"] if mm == m}
        for (o, d), v in od.items():
            if o not in stored_origs:
                demand_unstored += v * modes.get(m, {}).get("pce", 1.0)

    # compare on the union of links (link_performance is the reference)
    n = 0
    ss_res = 0.0
    sum_y = 0.0
    sum_y2 = 0.0
    max_diff = 0.0
    max_diff_link = None
    for lid, y in lp_vol.items():
        x = pushed.get(lid, 0.0)
        d = x - y
        n += 1
        ss_res += d * d
        sum_y += y
        sum_y2 += y * y
        if abs(d) > max_diff:
            max_diff = abs(d)
            max_diff_link = lid
    phantom = [lid for lid in pushed if lid not in lp_vol]
    r2 = float("nan")
    if n > 1:
        ss_tot = sum_y2 - sum_y * sum_y / n
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    ra_path = os.path.join(run_dir, "route_assignment.csv")
    return {
        "dtac": dtac_path,
        "version": store["version"],
        "n_modes": store["n_modes"],
        "n_zones": store["n_zones"],
        "fingerprint": store["fingerprint"],
        "total_ods": total_ods,
        "total_paths": total_paths,
        "total_link_entries": total_link_entries,
        "theta_sum_min": None if theta_sum_min == float("inf") else theta_sum_min,
        "theta_sum_max": None if theta_sum_max == float("-inf") else theta_sum_max,
        "n_links_compared": n,
        "r2": r2,
        "max_diff": max_diff,
        "max_diff_link": max_diff_link,
        "demand_pushed": demand_pushed,
        "demand_unstored": demand_unstored,
        "lp_total_volume_sum": sum_y,
        "phantom_links": len(phantom),
        "dtac_bytes": os.path.getsize(dtac_path),
        "route_assignment_bytes": os.path.getsize(ra_path) if os.path.exists(ra_path) else None,
        "demand_missing": demand_missing,
    }


def render(rep):
    lines = []
    lines.append(f"DTAC file: {rep['dtac']} (v{rep['version']}, "
                 f"{rep['n_modes']} mode(s), {rep['n_zones']} zones)")
    if rep.get("fingerprint"):
        fp = rep["fingerprint"]
        lines.append(f"  demand fingerprint    : total={fp[0]:.6g} cells={fp[1]:.0f} "
                     f"zones=[{fp[2]:.0f}, {fp[3]:.0f}]")
    lines.append(f"  stored OD pairs       : {rep['total_ods']:,}")
    lines.append(f"  stored paths          : {rep['total_paths']:,}"
                 + (f" ({rep['total_paths'] / max(rep['total_ods'], 1):.2f} per OD)"
                    if rep['total_ods'] else ""))
    lines.append(f"  stored link entries   : {rep['total_link_entries']:,}")
    lines.append(f"  file size             : {rep['dtac_bytes']:,} bytes")
    if rep["route_assignment_bytes"]:
        ratio = rep["route_assignment_bytes"] / max(rep["dtac_bytes"], 1)
        lines.append(f"  route_assignment.csv  : {rep['route_assignment_bytes']:,} bytes "
                     f"({ratio:.1f}x larger than DTAC)")
    if rep.get("theta_sum_min") is not None:
        lines.append(f"  sum(theta) per OD     : min {rep['theta_sum_min']:.6f}, "
                     f"max {rep['theta_sum_max']:.6f} (should be ~1)")
    if rep["demand_missing"]:
        lines.append(f"  WARN demand files not read (missing or non-CSV): {rep['demand_missing']}")
    if rep["version"] >= 2:
        lines.append("push-down vs link_performance volume (v2 theta shares: expected "
                     "~exact; residuals = float32 theta + dropped <1e-7 shares "
                     "+ unroutable demand):")
    else:
        lines.append("push-down vs link_performance volume "
                     "(NOT expected exact: link_performance is the FW blend of all "
                     "iterations; v1 stores only the final AoN direction):")
    lines.append(f"  links compared        : {rep['n_links_compared']:,}")
    lines.append(f"  R^2                   : {rep['r2']:.6f}")
    lines.append(f"  max |diff|            : {rep['max_diff']:.2f} (link {rep['max_diff_link']})")
    lines.append(f"  demand pushed (pce)   : {rep['demand_pushed']:,.1f}")
    if rep["demand_unstored"] > 0:
        lines.append(f"  demand w/o stored path: {rep['demand_unstored']:,.1f} (pce)")
    if rep["phantom_links"]:
        lines.append(f"  WARN paths reference {rep['phantom_links']} link id(s) "
                     "absent from link_performance")
    return "\n".join(lines)
