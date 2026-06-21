"""Default-value filler / normalizer.

Produces an explicit, kernel-stable copy of a scenario: every optional column
the kernel reads is present and populated with the kernel's own default, links
are sorted ascending by from_node_id (CSR requirement), and a settings.csv /
cutoff_speed are materialized when absent. The result runs identically to the
kernel's implicit behavior but leaves nothing to chance -- which is what makes
batch/automated runs reproducible.
"""
import os
import shutil

from . import csvio
from . import schema


def _fill_links(scenario, out, log):
    header, rows = csvio.read(csvio.path(scenario, "link.csv"))
    # ensure every default column exists in the header (append missing)
    for col in schema.LINK_DEFAULTS:
        if col not in header:
            header.append(col)
    if "cutoff_speed" not in header:
        header.append("cutoff_speed")

    added = {c: 0 for c in list(schema.LINK_DEFAULTS) + ["cutoff_speed"]}
    for r in rows:
        for col, default in schema.LINK_DEFAULTS.items():
            if not str(r.get(col, "")).strip():
                r[col] = default
                added[col] += 1
        # cutoff_speed default = 0.75 * free_speed (kernel's fallback), made explicit
        if not str(r.get("cutoff_speed", "")).strip():
            fs = csvio.fnum(r.get("vdf_free_speed_mph")) or (csvio.fnum(r.get("free_speed")) / 1.609)
            r["cutoff_speed"] = round(0.75 * fs, 4)
            added["cutoff_speed"] += 1

    # sort ascending by (from_node_id, to_node_id) -- CSR adjacency requirement
    before = [csvio.inum(r["from_node_id"]) for r in rows]
    rows.sort(key=lambda r: (csvio.inum(r["from_node_id"]), csvio.inum(r["to_node_id"])))
    if before != [csvio.inum(r["from_node_id"]) for r in rows]:
        log.append("link.csv: re-sorted ascending by from_node_id (CSR requirement)")

    csvio.write(csvio.path(out, "link.csv"), header, rows)
    for c, n in added.items():
        if n:
            log.append(f"link.csv: filled {n} '{c}' cells with default")


def _fill_nodes(scenario, out, log):
    header, rows = csvio.read(csvio.path(scenario, "node.csv"))
    if "zone_id" not in header:
        header.append("zone_id")
    n = 0
    for r in rows:
        if not str(r.get("zone_id", "")).strip():
            r["zone_id"] = schema.NODE_DEFAULTS["zone_id"]
            n += 1
    csvio.write(csvio.path(out, "node.csv"), header, rows)
    if n:
        log.append(f"node.csv: filled {n} 'zone_id' cells with 0")


def _fill_settings(scenario, out, log):
    path_in = csvio.path(scenario, "settings.csv")
    if not os.path.exists(path_in):
        csvio.write(csvio.path(out, "settings.csv"), schema.SETTINGS_COLUMNS,
                    [dict(schema.SETTINGS_DEFAULTS)])
        log.append("settings.csv: created with kernel defaults")
        return
    header, rows = csvio.read(path_in)
    row = rows[0] if rows else {}
    for col in schema.SETTINGS_COLUMNS:
        if col not in header:
            header.append(col)
        if not str(row.get(col, "")).strip():
            row[col] = schema.SETTINGS_DEFAULTS[col]
            log.append(f"settings.csv: filled '{col}' = {schema.SETTINGS_DEFAULTS[col]}")
    csvio.write(csvio.path(out, "settings.csv"), header, [row])


def _fill_mode_type(scenario, out, log):
    path_in = csvio.path(scenario, "mode_type.csv")
    if not os.path.exists(path_in):
        return
    header, rows = csvio.read(path_in)
    for col in schema.MODE_DEFAULTS:
        if col not in header:
            header.append(col)
    for r in rows:
        for col, default in schema.MODE_DEFAULTS.items():
            if not str(r.get(col, "")).strip():
                r[col] = default
    csvio.write(csvio.path(out, "mode_type.csv"), header, rows)


def fill(scenario, out_dir):
    """Write a normalized copy of `scenario` into `out_dir`. Returns a log list."""
    os.makedirs(out_dir, exist_ok=True)
    log = []
    _fill_nodes(scenario, out_dir, log)
    _fill_links(scenario, out_dir, log)
    _fill_settings(scenario, out_dir, log)
    _fill_mode_type(scenario, out_dir, log)
    # copy demand + movement files through unchanged
    for name in os.listdir(scenario):
        if name in ("node.csv", "link.csv", "settings.csv", "mode_type.csv"):
            continue
        if name.endswith(".csv"):
            src = csvio.path(scenario, name)
            if os.path.isfile(src):
                shutil.copy(src, csvio.path(out_dir, name))
    return log
