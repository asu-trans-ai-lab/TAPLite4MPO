"""TAPCIEnv -- an assignment-based RL / agentic-AI environment over TAPCI.

TAPCI is the ENVIRONMENT, not the RL algorithm (the agent lives outside). The
environment is *assignment-based*, not vehicle-level:

    state  = system MOEs + the KPI4MPO/NPO vector
    action = a next-run scenario edit (closure / capacity / toll / OD multiplier)
    reward = KPI improvement (default: VHT reduction; or a KPI-weighted objective)
    step   = apply edit -> run one-period assignment -> observe

Everything is OFFLINE and one-period: each step accumulates the edit onto the
scenario, reruns a full static assignment from the base network, and hands back
observations. This is the disciplined DP/RL framing (explicit state/action/
reward), NOT live per-vehicle control -- that needs the resident kernel (roadmap).

The reward can be:
  - a STRING shortcut on system MOEs: "vht" | "vmt" | "delay" | "mean_speed"
    (reward = reduction since the previous step; speed = increase).
  - a KPI-WEIGHT DICT over KPI4MPO/NPO KPIs, e.g. {"vht_hours": -1.0,
    "co2_proxy_kg": -0.001}: reward = the step-change in the weighted objective
    (objective_now - objective_prev). Sign the weights so "good" KPIs are positive
    and costs to MINIMIZE are negative -- then a good action gives positive reward.
  - a CALLABLE(prev_kpis, now_kpis) -> float for full control.

    from dtalite_qa.tapci_env import TAPCIEnv
    env = TAPCIEnv("project.yml", exe="bin/DTALite.exe",
                   reward={"vht_hours": -1.0, "total_delay_hours": -0.5})
    obs = env.reset()
    obs, reward, done, info = env.step({"type": "link_closure", "link_ids": [1071]})
"""
from . import kpi as _kpi
from .tapci import TAPCI

_ACTIONS = ("noop", "link_closure", "link_capacity", "toll", "od_multiplier")
_STR_REWARDS = ("vht", "vmt", "delay", "mean_speed")


class TAPCIEnv:
    """One-period assignment environment. Edits accumulate across steps (episodic);
    call :meth:`reset` to return to the base network."""

    def __init__(self, project, exe=None, reward="vht", max_iter=20, gap=0.001,
                 override="tapci-env", run_kwargs=None,
                 co2_kg_per_mile=None, occupancy=None):
        self.reward_spec = self._validate_reward(reward)
        self.sim = TAPCI.open(project, exe=exe)
        self._run = dict(max_iter=max_iter, gap=gap, override=override, **(run_kwargs or {}))
        self._kpi_kw = {"co2_kg_per_mile": co2_kg_per_mile, "occupancy": occupancy}
        self._base = None          # baseline MOE (after reset)
        self._prev = None          # previous-step MOE
        self._prev_kpis = None     # previous-step KPI vector
        self._steps = 0

    @staticmethod
    def _validate_reward(reward):
        if callable(reward):
            return reward
        if isinstance(reward, str):
            if reward not in _STR_REWARDS:
                raise ValueError(f"string reward must be one of {_STR_REWARDS}, got {reward!r}")
            return reward
        if isinstance(reward, dict):
            if not reward:
                raise ValueError("KPI-weight reward dict must be non-empty")
            bad = [k for k in reward if k not in _kpi.MVP_KPIS]
            if bad:
                raise ValueError(f"unknown KPI(s) in reward weights: {bad}; "
                                 f"valid: {sorted(_kpi.MVP_KPIS)}")
            return dict(reward)
        raise TypeError("reward must be a str, a KPI-weight dict, or a callable")

    # -- gym-like API -------------------------------------------------------
    def reset(self):
        """Clear all edits, run the base assignment, return the initial observation."""
        self.sim.clear_edits()
        self.sim.run_until_converged(**self._run)
        self._base = self.sim.moe()
        self._prev = self._base
        self._prev_kpis = self._kpis()
        self._steps = 0
        return self._observe(self._prev_kpis)

    def step(self, action):
        """Apply ``action`` (a dict, see :meth:`action_space`), rerun, return
        ``(observation, reward, done, info)``. ``done`` is always False (continuing
        task); the agent decides when to stop."""
        self._apply(action)
        self.sim.run_until_converged(**self._run)
        moe = self.sim.moe()
        kpis = self._kpis()
        reward = self._reward(moe, kpis)
        info = {"action": action, "moe": moe, "kpis": kpis, "step": self._steps + 1,
                "vs_base": {k: moe.get(k, 0) - self._base.get(k, 0)
                            for k in ("vmt", "vht")}}
        self._prev, self._prev_kpis = moe, kpis
        self._steps += 1
        return self._observe(kpis), reward, False, info

    @staticmethod
    def action_space():
        """The (offline, next-run) action schema this environment accepts."""
        return {
            "noop": {},
            "link_closure": {"link_ids": "list[int]"},
            "link_capacity": {"link_ids": "list[int]", "factor": "float (or value=float)"},
            "toll": {"link_ids": "list[int]", "toll": "float"},
            "od_multiplier": {"factor": "float", "o_zones": "list?|None", "d_zones": "list?|None"},
        }

    # -- internals ----------------------------------------------------------
    def _apply(self, action):
        t = (action or {}).get("type")
        if t not in _ACTIONS:
            raise ValueError(f"action type must be one of {_ACTIONS}, got {t!r}")
        if t == "noop":
            return
        if t == "link_closure":
            self.sim.set_link_closure(action["link_ids"])
        elif t == "link_capacity":
            self.sim.set_link_capacity(action["link_ids"],
                                       factor=action.get("factor"),
                                       value=action.get("value"))
        elif t == "toll":
            self.sim.set_toll(action["link_ids"], action["toll"])
        elif t == "od_multiplier":
            self.sim.set_od_multiplier(action["factor"],
                                       o_zones=action.get("o_zones"),
                                       d_zones=action.get("d_zones"))

    def _kpis(self):
        return _kpi.compute(self.sim._result.run_dir, **self._kpi_kw)

    def _reward(self, moe, kpis):
        spec = self.reward_spec
        if callable(spec):
            return float(spec(self._prev_kpis, kpis))
        if isinstance(spec, dict):
            # step-change in the weighted objective; sign weights so good = positive
            return _kpi.objective(kpis, spec) - _kpi.objective(self._prev_kpis, spec)
        # string MOE shortcut: reduction since previous step (speed = increase)
        prev = self._prev
        if spec == "mean_speed":
            return moe.get("mean_speed_mph", 0) - prev.get("mean_speed_mph", 0)
        if spec == "delay":
            spec = "vht"          # no delay in moe; VHT reduction is the proxy
        return prev.get(spec, 0) - moe.get(spec, 0)

    def _observe(self, kpis):
        moe = self.sim.moe()
        return {"vmt": moe.get("vmt"), "vht": moe.get("vht"),
                "mean_speed_mph": moe.get("mean_speed_mph"),
                "loaded_links": moe.get("loaded_links"),
                "kpis": kpis, "step": self._steps}

    def close(self):
        self.sim.close()
