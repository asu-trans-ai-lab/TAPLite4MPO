"""Per-mode accessibility / connectivity check.

For each mode, builds the directed graph of links that mode may use (respecting
allowed_use) and flags:
  - zones with no allowed OUTBOUND link  (cannot originate trips)
  - zones with no allowed INBOUND link   (cannot receive trips)
  - zones outside the largest strongly-connected component (mutually unreachable
    from the bulk of the network -> their OD pairs are infeasible)

Strongly-connected components are found with an iterative Kosaraju pass so the
check scales to large networks without recursion limits. This catches isolation
that the kernel would otherwise only reveal as silently dropped OD pairs.
"""
from . import csvio
from . import schema


def _load(scenario):
    _, nodes = csvio.read(csvio.path(scenario, "node.csv"))
    _, links = csvio.read(csvio.path(scenario, "link.csv"))
    node_ids = [csvio.inum(r["node_id"]) for r in nodes if csvio.is_num(r.get("node_id"))]
    zone_of = {csvio.inum(r["node_id"]): csvio.inum(r.get("zone_id"))
               for r in nodes if csvio.is_num(r.get("node_id"))}
    tokens = []
    if csvio.exists(scenario, "mode_type.csv"):
        _, mts = csvio.read(csvio.path(scenario, "mode_type.csv"))
        tokens = [r["mode_type"].strip() for r in mts if r.get("mode_type")]
    return node_ids, zone_of, links, tokens


def _scc(node_ids, edges):
    """Iterative Kosaraju. edges: list of (u, v). Returns {node: comp_id}."""
    idx = {n: i for i, n in enumerate(node_ids)}
    N = len(node_ids)
    g = [[] for _ in range(N)]
    gt = [[] for _ in range(N)]
    for u, v in edges:
        if u in idx and v in idx:
            g[idx[u]].append(idx[v])
            gt[idx[v]].append(idx[u])

    visited = [False] * N
    order = []
    for s in range(N):
        if visited[s]:
            continue
        stack = [(s, 0)]
        visited[s] = True
        while stack:
            node, i = stack[-1]
            if i < len(g[node]):
                stack[-1] = (node, i + 1)
                w = g[node][i]
                if not visited[w]:
                    visited[w] = True
                    stack.append((w, 0))
            else:
                order.append(node)
                stack.pop()

    comp = [-1] * N
    c = 0
    for s in reversed(order):
        if comp[s] != -1:
            continue
        stack = [s]
        comp[s] = c
        while stack:
            node = stack.pop()
            for w in gt[node]:
                if comp[w] == -1:
                    comp[w] = c
                    stack.append(w)
        c += 1
    return {n: comp[idx[n]] for n in node_ids}


def _demand_pairs(scenario, mode, single_mode):
    """Demanded (o_zone, d_zone) pairs with volume>0 for a mode."""
    df = "demand.csv"
    if not single_mode and csvio.exists(scenario, "mode_type.csv"):
        _, mts = csvio.read(csvio.path(scenario, "mode_type.csv"))
        for r in mts:
            if r.get("mode_type", "").strip() == mode:
                df = (r.get("demand_file") or "demand.csv").strip()
                break
    if not csvio.exists(scenario, df):
        return []
    _, rows = csvio.read(csvio.path(scenario, df))
    pairs = []
    for r in rows:
        if csvio.fnum(r.get("volume")) > 0:
            pairs.append((csvio.inum(r.get("o_zone_id")), csvio.inum(r.get("d_zone_id"))))
    return pairs


def _reachable_from(origin_comps, cedges):
    """BFS reachability in the SCC condensation from each origin component."""
    reach = {}
    for oc in origin_comps:
        seen = {oc}
        stack = [oc]
        while stack:
            c = stack.pop()
            for w in cedges.get(c, ()):  # forward edges in condensation
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        reach[oc] = seen
    return reach


def check(scenario):
    """Return {mode: result}. result: no_out/no_in (zones that originate/receive
    demand but have no allowed edge), infeasible_od (demanded OD that cannot be
    routed), and SCC stats. Demand-aware: a one-way corridor is fine as long as
    every demanded OD pair is reachable."""
    node_ids, zone_of, links, tokens = _load(scenario)
    zones = [n for n in node_ids if zone_of.get(n, 0) > 0]
    zone_to_node = {zone_of[n]: n for n in zones}  # zone_id -> a node id
    single = not tokens
    modes = tokens if tokens else ["(auto)"]
    results = {}
    for mode in modes:
        edges, out_deg, in_deg = [], {}, {}
        for r in links:
            au = (r.get("allowed_use") or "").strip()
            if not (single or schema.mode_allowed(au, mode)):
                continue
            u, v = csvio.inum(r.get("from_node_id")), csvio.inum(r.get("to_node_id"))
            edges.append((u, v))
            out_deg[u] = out_deg.get(u, 0) + 1
            in_deg[v] = in_deg.get(v, 0) + 1
        comp = _scc(node_ids, edges)

        # condensation edges (component -> set of components)
        cedges = {}
        for u, v in edges:
            cu, cv = comp.get(u), comp.get(v)
            if cu is not None and cv is not None and cu != cv:
                cedges.setdefault(cu, set()).add(cv)

        pairs = _demand_pairs(scenario, mode, single)
        origin_comps = {comp.get(zone_to_node.get(o)) for o, _ in pairs
                        if zone_to_node.get(o) is not None}
        origin_comps.discard(None)
        reach = _reachable_from(origin_comps, cedges)

        no_out, no_in, infeasible = [], [], []
        for o, d in pairs:
            on, dn = zone_to_node.get(o), zone_to_node.get(d)
            if on is None or dn is None:
                continue
            if out_deg.get(on, 0) == 0:
                no_out.append(o)
                continue
            if in_deg.get(dn, 0) == 0:
                no_in.append(d)
                continue
            if comp.get(dn) not in reach.get(comp.get(on), set()):
                infeasible.append((o, d))
        results[mode] = {
            "n_zones": len(zones), "n_demand": len(pairs),
            "no_out": sorted(set(no_out)), "no_in": sorted(set(no_in)),
            "infeasible_od": infeasible,
        }
    return results


def render(results):
    out = []
    worst = 0
    for mode, r in results.items():
        problems = len(r["no_out"]) + len(r["no_in"]) + len(r["infeasible_od"])
        worst = max(worst, problems)
        tag = "OK" if problems == 0 else "ISSUES"
        out.append(f"mode {mode:8} [{tag}] zones={r['n_zones']} demand_pairs={r['n_demand']}")

        def show(label, lst):
            if lst:
                head = ", ".join(str(z) for z in lst[:15])
                more = f" (+{len(lst) - 15})" if len(lst) > 15 else ""
                out.append(f"    {label}: {len(lst)} -> {head}{more}")
        show("origin zones w/ demand but NO allowed outbound", r["no_out"])
        show("dest zones w/ demand but NO allowed inbound", r["no_in"])
        show("demanded OD pairs UNREACHABLE (will be dropped)", r["infeasible_od"])
    return "\n".join(out), worst
