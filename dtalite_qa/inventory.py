"""Network + allowed_use data inventory.

Summarizes how mode access control is used across the network: how many links
each mode may use, the restriction classes (HOV-only / no-truck / single-mode /
closed / custom), and the explicit list of restricted links. Run this before an
assignment to understand what the network actually permits.
"""
from . import csvio
from . import schema


def _classify(allowed_use, tokens):
    if schema.is_all_allowed(allowed_use):
        return "all"
    if schema.is_closed(allowed_use):
        return "closed"
    allowed = [t for t in tokens if schema.mode_allowed(allowed_use, t)]
    denied = [t for t in tokens if t not in allowed]
    if not denied:           # explicit list that still permits every mode == all
        return "all"
    if len(allowed) == 1:
        return f"only:{allowed[0]}"
    if len(denied) == 1:
        return f"no:{denied[0]}"
    return "custom"


def build(scenario):
    """Return an inventory dict for a scenario."""
    _, links = csvio.read(csvio.path(scenario, "link.csv"))
    tokens = []
    if csvio.exists(scenario, "mode_type.csv"):
        _, mts = csvio.read(csvio.path(scenario, "mode_type.csv"))
        tokens = [r["mode_type"].strip() for r in mts if r.get("mode_type")]

    n_links = len(links)
    per_mode_allowed = {t: 0 for t in tokens}
    classes = {}
    restricted = []
    for r in links:
        au = (r.get("allowed_use") or "").strip()
        cls = _classify(au, tokens) if tokens else ("all" if schema.is_all_allowed(au) else "custom")
        classes[cls] = classes.get(cls, 0) + 1
        for t in tokens:
            if schema.mode_allowed(au, t):
                per_mode_allowed[t] += 1
        if cls not in ("all",):
            restricted.append({
                "link_id": r.get("link_id", "?"),
                "from": r.get("from_node_id"), "to": r.get("to_node_id"),
                "allowed_use": au, "class": cls,
            })
    return {
        "n_links": n_links, "modes": tokens,
        "per_mode_allowed": per_mode_allowed, "classes": classes,
        "restricted": restricted,
    }


def render(inv):
    out = []
    out.append(f"links: {inv['n_links']}    modes: {inv['modes'] or '(single/auto)'}")
    if inv["modes"]:
        out.append("links each mode may use:")
        for t in inv["modes"]:
            a = inv["per_mode_allowed"][t]
            out.append(f"  {t:8} {a:>6} / {inv['n_links']} "
                       f"({100.0 * a / max(inv['n_links'], 1):5.1f}%)")
    out.append("restriction classes:")
    for cls, n in sorted(inv["classes"].items(), key=lambda kv: -kv[1]):
        out.append(f"  {cls:14} {n}")
    if inv["restricted"]:
        out.append(f"restricted links ({len(inv['restricted'])}):")
        for r in inv["restricted"][:200]:
            out.append(f"  link {r['link_id']:>6} {r['from']}->{r['to']:<6} "
                       f"[{r['class']}] allowed_use={r['allowed_use']!r}")
        if len(inv["restricted"]) > 200:
            out.append(f"  ... and {len(inv['restricted']) - 200} more")
    return "\n".join(out)
