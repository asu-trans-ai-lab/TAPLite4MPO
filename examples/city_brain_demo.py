"""End-to-end capstone: City Brain -> TAPLite4MPO agents -> skims -> KPI -> reward.

Runs the whole API stack in one script so a reviewer (or the next developer) can see
the pieces work together:

  1. build a City Brain over TWO regions (each a TAPLite4MPO agent);
  2. reset() -> baseline assignment in every region (parallel), report system KPIs;
  3. run a few "days": each day apply an information-provision / scenario policy
     (toll a corridor, nudge demand), warm-started from each region's prior routing
     policy (the 10-30x efficiency lever), and report per-region + system-of-systems
     KPIs and a KPI-weighted reward;
  4. answer a Choice-Graph point skim query.

Everything is offline, one-period, planning-scale -- TAPCI is the ENVIRONMENT; the
policy / choice / RL logic is the tiny `policy()` function here (external, swappable).

Usage:
    python examples/city_brain_demo.py               # locates a kernel exe
    DTALITE_EXE=path/to/DTALite.exe python examples/city_brain_demo.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from dtalite_qa.citybrain import CityBrain, RegionAgent
from dtalite_qa import kpi

SKETCH = os.path.join(REPO, "kernel", "data_sets", "03_chicago_sketch")
CO2 = 0.4          # kg CO2 per mile (proxy factor)
# a KPI-weighted objective: minimize VHT + delay + a little CO2 (negative = cost)
REWARD_WEIGHTS = {"vht_hours": -1.0, "total_delay_hours": -0.5, "co2_proxy_kg": -1e-4}


def _find_exe():
    for c in (os.environ.get("DTALITE_EXE"),
              os.path.join(REPO, "bin", "DTALite.exe"),
              os.path.join(REPO, "bin", "DTALite"),
              os.path.join(REPO, "release_v0.2.0", "DTALite.exe")):
        if c and os.path.exists(c):
            return c
    sys.exit("no DTALite kernel found; build it (bash build.sh) or set $DTALITE_EXE")


def objective(totals):
    return kpi.objective(totals, REWARD_WEIGHTS)


def policy(day):
    """The EXTERNAL information-provision policy: from day 1, toll a busy corridor in
    region A and shift a little demand in region B. Returns a scenario-by-region dict."""
    if day == 0:
        return {}
    return {"A": {"tolls": [[1071, 4.0 * day]]},
            "B": {"od_multiplier": 1.0 + 0.03 * day}}


def main():
    exe = _find_exe()
    print(f"kernel: {exe}\n")
    # keep_warm=False (the default): reliable per-stage skims. The theta-reuse
    # speedup (keep_warm=True) is validated separately (docs/EFFICIENCY_CORNERSTONE_
    # BENCHMARK.md) -- it is NOT combined here because the kernel's warm-replay path
    # can emit an empty od_performance when routing is unchanged (see RegionAgent).
    brain = CityBrain([
        RegionAgent("A", SKETCH, exe=exe,
                    run_kwargs=dict(max_iter=15, override="city-brain-demo"),
                    kpi_kwargs=dict(co2_kg_per_mile=CO2)),
        RegionAgent("B", SKETCH, exe=exe,
                    run_kwargs=dict(max_iter=15, override="city-brain-demo"),
                    kpi_kwargs=dict(co2_kg_per_mile=CO2)),
    ])

    prev_obj = None
    for day in range(3):
        out = brain.reset() if day == 0 else brain.step(policy(day))
        totals = brain.kpi_totals()
        obj = objective(totals)
        reward = "" if prev_obj is None else f"  reward={obj - prev_obj:+.1f}"
        prev_obj = obj
        tag = "baseline" if day == 0 else f"policy day {day}"
        print(f"=== stage {day} ({tag}) ===")
        for region, r in out.items():
            k = r["kpis"]
            print(f"  region {region}: VHT={k['vht_hours']:>9.0f}  "
                  f"delay={k['total_delay_hours']:>7.0f}h  maxV/C={k['max_vc']:.2f}  "
                  f"skims={r['skim_summary']['n']}")
        print(f"  SYSTEM: VMT={totals['vmt_miles']:>11.0f}  VHT={totals['vht_hours']:>9.0f}  "
              f"speed={totals['avg_speed_mph']:.1f}mph  objective={obj:.1f}{reward}\n")

    # Choice-Graph point query (the ABM/skim interface)
    q = brain.agents["A"].query_skim(1, 5)
    print(f"choice-graph skim query region A, OD 1->5: "
          f"time={q['skim_time']} min, available={q['path_available']}")

    brain.close()
    print("\ndone. TAPCI is the environment; the policy() above is the only external "
          "logic -- swap it for an RL agent or an LLM/OpenTI orchestrator.")


if __name__ == "__main__":
    main()
