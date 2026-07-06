"""TAPCIEnv -- an assignment-based RL / agentic-AI environment over TAPCI.

TAPCI is the ENVIRONMENT, not the RL algorithm (the agent lives outside). The
environment is *assignment-based*, not vehicle-level:

    state  = system MOEs (+ optional link/skim summaries)
    action = a next-run scenario edit (closure / capacity / toll / OD multiplier)
    reward = KPI improvement (default: VHT reduction vs the previous step)
    step   = apply edit -> run one-period assignment -> observe

Everything is OFFLINE and one-period: each step accumulates the edit onto the
scenario, reruns a full static assignment from the base network, and hands back
observations. This is the disciplined DP/RL framing (explicit state/action/
reward), NOT live per-vehicle control -- that needs the resident kernel (roadmap).

    from dtalite_qa.tapci_env import TAPCIEnv
    env = TAPCIEnv("project.yml", exe="bin/DTALite.exe", reward="vht")
    obs = env.reset()
    obs, reward, done, info = env.step({"type": "link_closure", "link_ids": [1071]})
"""
from .tapci import TAPCI

_ACTIONS = ("noop", "link_closure", "link_capacity", "toll", "od_multiplier")
_REWARDS = ("vht", "delay", "vmt", "mean_speed")


class TAPCIEnv:
    """One-period assignment environment. Edits accumulate across steps (episodic);
    call :meth:`reset` to return to the base network."""

    def __init__(self, project, exe=None, reward="vht", max_iter=20, gap=0.001,
                 override="tapci-env", run_kwargs=None):
        if reward not in _REWARDS:
            raise ValueError(f"reward must be one of {_REWARDS}, got {reward!r}")
        self.sim = TAPCI.open(project, exe=exe)
        self.reward_kind = reward
        self._run = dict(max_iter=max_iter, gap=gap, override=override, **(run_kwargs or {}))
        self._base = None      # baseline MOE (after reset)
        self._prev = None      # previous-step MOE
        self._steps = 0

    # -- gym-like API -------------------------------------------------------
    def reset(self):
        """Clear all edits, run the base assignment, return the initial observation."""
        self.sim.clear_edits()
        self.sim.run_until_converged(**self._run)
        self._base = self.sim.moe()
        self._prev = self._base
        self._steps = 0
        return self._observe()

    def step(self, action):
        """Apply ``action`` (a dict, see :meth:`action_space`), rerun, return
        ``(observation, reward, done, info)``. ``done`` is always False (continuing
        task); the agent decides when to stop."""
        self._apply(action)
        self.sim.run_until_converged(**self._run)
        moe = self.sim.moe()
        reward = self._reward(moe)
        info = {"action": action, "moe": moe, "step": self._steps + 1,
                "vs_base": {k: moe.get(k, 0) - self._base.get(k, 0)
                            for k in ("vmt", "vht")}}
        self._prev = moe
        self._steps += 1
        return self._observe(), reward, False, info

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

    def _reward(self, moe):
        """Default: improvement (reduction) vs the previous step. Lower VHT/VMT/delay
        is better -> positive reward; higher mean speed is better."""
        prev, kind = self._prev, self.reward_kind
        if kind == "mean_speed":
            return moe.get("mean_speed_mph", 0) - prev.get("mean_speed_mph", 0)
        if kind == "delay":
            # delay proxy = VHT - VHT_at_free_flow is not in moe; use VHT reduction
            kind = "vht"
        return prev.get(kind, 0) - moe.get(kind, 0)

    def _observe(self):
        moe = self.sim.moe()
        return {"vmt": moe.get("vmt"), "vht": moe.get("vht"),
                "mean_speed_mph": moe.get("mean_speed_mph"),
                "loaded_links": moe.get("loaded_links"), "step": self._steps}

    def close(self):
        self.sim.close()
