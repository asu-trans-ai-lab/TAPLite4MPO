"""City Brain -- a multi-region orchestrator over TAPLite4MPO agents.

The City Brain is the CENTER of the choice graph: it holds the flow tensor
x[o,d,m,c,tau,s] and the mode/activity choice + RL policy (that logic lives in the
caller). It does NOT own any network. Each REGION is a TAPLite4MPO agent -- a TAPCI
instance holding that region's multimodal network + its reusable theta routing
policy -- and answers one question fast: given a demand slice + scenario state,
return skims / link summary / routing policy / KPIs.

    stage: Brain slices the tensor -> fans (demand + scenario s) to N agents in
    PARALLEL, each warm-started from its own prior theta -> agents run one-period
    assignment -> return skims + KPIs -> Brain folds skims back into the tensor,
    updates choice EXTERNALLY, advances tau. That is "enhanced four-step, online",
    with step 4 (assignment) distributed to the agents.

Wire contract (plain JSON-able dicts, so the in-process boundary here can be
swapped for processes / MCP tools / hosts-per-city later WITHOUT changing callers):

    request  = {"region", "period"?: (start,end), "od_multiplier"?: float,
                "tolls"?: [[link, toll], ...], "closures"?: [link, ...],
                "capacity"?: [[link, factor], ...], "warm"?: bool}
    response = {"region", "skim_summary": {"n", "mean_skim_time_min"},
                "kpis": {...10 KPIs...}, "moe": {...}, "policy": <theta path>,
                "compute_s": float}

Full skims stay on the agent (agent.query_skim(o,d) / agent.sim.observe_skims())
so a stage response is small; only summaries + KPIs cross the boundary.
"""
import os
import tempfile

from . import kpi as _kpi
from .tapci import TAPCI


class RegionAgent:
    """One region = one TAPLite4MPO agent (a TAPCI + a persistent theta policy).

    theta is ALWAYS captured after each run (available for reuse / inspection).
    ``keep_warm`` controls whether the NEXT run WARM-STARTS from the prior theta --
    the 10-30x efficiency lever. It defaults to False because of a known kernel
    limitation: on a warm replay whose routing does not change, the kernel currently
    emits an EMPTY od_performance.csv, so the skim service (observe_skims/query_skim)
    can come back empty. Since a City Brain stage usually needs skims for the choice
    loop, reliable skims are the default; set ``keep_warm=True`` when you want the
    speedup and only need link/KPI outputs (not per-stage skims). Fixing the kernel's
    warm-replay OD writer is the follow-up that lets you have both.
    """

    def __init__(self, name, project, exe=None, keep_warm=False,
                 run_kwargs=None, kpi_kwargs=None):
        self.name = name
        self.sim = TAPCI.open(project, exe=exe)
        self.keep_warm = keep_warm
        self._policy = None                        # last theta file
        self._run = dict(max_iter=20, gap=0.001, override="citybrain")
        self._run.update(run_kwargs or {})
        self._kpi = kpi_kwargs or {}

    def run_stage(self, request):
        """Apply the request's scenario edits, run (warm-started), return the response
        dict. The request/response are the wire contract (see module docstring)."""
        s = self.sim
        s.clear_edits()
        if request.get("period"):
            s.set_time_period(*request["period"])
        if request.get("od_multiplier"):
            s.set_od_multiplier(float(request["od_multiplier"]))
        for link, toll in request.get("tolls", []):
            s.set_toll([link], toll)
        if request.get("closures"):
            s.set_link_closure(request["closures"])
        for link, factor in request.get("capacity", []):
            s.set_link_capacity([link], factor=factor)
        s.set_setting(column_output=2)             # always capture theta
        warm = request.get("warm", self.keep_warm)
        if warm and self._policy:                  # opt-in speedup (see class docstring)
            s.load_routing_policy(self._policy)
        s.run_until_converged(**self._run)
        run_dir = s._result.run_dir
        self._policy = s.save_routing_policy(       # ALWAYS save (reuse/inspection)
            os.path.join(tempfile.mkdtemp(prefix="cb_pol_"), f"{self.name}.dtac"))
        skims = s.observe_skims()
        mean_t = (round(sum(x["skim_time"] for x in skims if x["skim_time"]) /
                        max(1, sum(1 for x in skims if x["skim_time"])), 3)
                  if skims else None)
        resp = {
            "region": self.name,
            "skim_summary": {"n": len(skims), "mean_skim_time_min": mean_t},
            "kpis": _kpi.compute(run_dir, **self._kpi),
            "moe": s.moe(),
            "policy": self._policy,
            "compute_s": None,                     # filled by the Brain (timed there)
        }
        if not skims:                              # never hand back empty skims silently
            resp["warning"] = ("empty od_performance: the skim service returned 0 rows "
                               "this stage (rerun the region; see parallel caveat)")
        return resp

    def query_skim(self, o_zone, d_zone, mode=None):
        """Point skim query for the Choice Graph (full skims stay on the agent)."""
        return self.sim.query_skim(o_zone, d_zone, mode=mode)

    def close(self):
        self.sim.close()


class CityBrain:
    """Orchestrates a stage across all region agents (parallel fan-out) and folds the
    responses into a central store. The choice/RL logic sits ON TOP of ``step``."""

    def __init__(self, agents):
        self.agents = {a.name: a for a in (agents.values() if isinstance(agents, dict)
                                           else agents)}
        self.stage = 0
        self.history = []                          # list of {region: response}

    def reset(self):
        """Baseline stage (no scenario edits) for every region."""
        self.stage = 0
        self.history = []
        return self.step({})

    def step(self, scenario_by_region=None, parallel=False):
        """Fan a per-region scenario dict out to all agents, collect responses.

        ``scenario_by_region`` maps region name -> request fields (period/od_multiplier/
        tolls/closures/capacity/warm); missing regions run their baseline. Returns
        ``{region: response}``.

        ``parallel`` (default False) is an EXPERIMENTAL opt-in: it runs the region
        kernels concurrently, but each kernel is already OpenMP-multithreaded, so N
        concurrent regions oversubscribe the CPU and a transient empty-output was
        observed. Serial is the reliable default; the theta-reuse speedup (the real
        lever) is independent of fan-out parallelism. A region that returns empty
        skims is flagged with a ``warning`` key, never silently zeroed.
        """
        scenario_by_region = scenario_by_region or {}
        names = list(self.agents)
        reqs = {n: dict(region=n, **scenario_by_region.get(n, {})) for n in names}

        def _one(n):
            return self.agents[n].run_stage(reqs[n])

        if parallel and len(names) > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(names)) as ex:
                results = list(ex.map(_one, names))
        else:
            results = [_one(n) for n in names]
        out = {r["region"]: r for r in results}
        self.stage += 1
        self.history.append(out)
        return out

    def kpi_totals(self, stage=-1):
        """System-of-systems KPIs across all regions for a stage. Extensive KPIs
        (VMT/VHT/delay) sum; intensive ones (max V/C, speed, skim) are combined by
        kind (see :func:`dtalite_qa.kpi.aggregate`) -- never a raw sum of speeds."""
        return _kpi.aggregate([r["kpis"] for r in self.history[stage].values()])

    def close(self):
        for a in self.agents.values():
            a.close()
