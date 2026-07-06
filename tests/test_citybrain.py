"""City Brain orchestrator tests.

Two layers:
  - ORCHESTRATION (no kernel): fake region agents exercise fan-out, per-region
    scenario routing, KPI aggregation, history, reset, close -- fast, deterministic.
  - KERNEL (needs a built DTALite): a real 2-region City Brain reset + a scenario
    step with theta reuse and a cross-region KPI total.

Run: python -m unittest tests.test_citybrain
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from dtalite_qa.citybrain import CityBrain    # noqa: E402
from dtalite_qa import kpi                     # noqa: E402

SKETCH = os.path.join(REPO, "kernel", "data_sets", "03_chicago_sketch")


def _kpis(vmt, vht, delay=10.0, speed=25.0, vc=1.2, skim=6.0):
    return {"vmt_miles": vmt, "vht_hours": vht, "total_delay_hours": delay,
            "avg_speed_mph": speed, "max_vc": vc, "od_skim_time_min": skim,
            "co2_proxy_kg": None, "person_delay_hours": None,
            "bottleneck_duration_hours": None, "accessibility_to_jobs": None}


class _FakeAgent:
    """A region agent with no kernel -- echoes the request and returns canned KPIs."""

    def __init__(self, name, kpis_dict):
        self.name = name
        self._k = kpis_dict
        self.closed = False
        self.last_request = None

    def run_stage(self, request):
        self.last_request = request
        return {"region": self.name, "skim_summary": {"n": 2, "mean_skim_time_min": 5.0},
                "kpis": self._k, "moe": {"vmt": self._k["vmt_miles"]},
                "policy": None, "compute_s": None}

    def close(self):
        self.closed = True


class Orchestration(unittest.TestCase):
    def setUp(self):
        self.a = _FakeAgent("region_A", _kpis(100.0, 4.0))
        self.b = _FakeAgent("region_B", _kpis(300.0, 4.0, speed=75.0, vc=2.0, skim=10.0))
        self.brain = CityBrain([self.a, self.b])

    def test_reset_runs_all_regions_baseline(self):
        out = self.brain.reset()
        self.assertEqual(set(out), {"region_A", "region_B"})
        self.assertEqual(self.brain.stage, 1)
        self.assertEqual(len(self.brain.history), 1)
        # baseline: no scenario fields beyond region
        self.assertEqual(self.a.last_request, {"region": "region_A"})

    def test_scenario_routed_per_region(self):
        self.brain.reset()
        self.brain.step({"region_A": {"tolls": [[1071, 8.0]], "od_multiplier": 1.05}},
                        parallel=False)
        self.assertEqual(self.a.last_request["tolls"], [[1071, 8.0]])
        self.assertEqual(self.a.last_request["od_multiplier"], 1.05)
        self.assertEqual(self.b.last_request, {"region": "region_B"})   # untouched

    def test_kpi_totals_aggregate_by_kind(self):
        self.brain.reset()
        agg = self.brain.kpi_totals()
        self.assertEqual(agg["vmt_miles"], 400.0)          # extensive: sum
        self.assertEqual(agg["vht_hours"], 8.0)
        self.assertEqual(agg["avg_speed_mph"], 50.0)       # 400/8, NOT (25+75)
        self.assertEqual(agg["max_vc"], 2.0)               # max, not sum
        self.assertEqual(agg["od_skim_time_min"], 8.0)     # mean of 6,10

    def test_close_closes_agents(self):
        self.brain.close()
        self.assertTrue(self.a.closed and self.b.closed)


class KpiAggregateUnit(unittest.TestCase):
    def test_intensive_kpis_not_summed(self):
        agg = kpi.aggregate([_kpis(100, 4, speed=25, vc=1.2, skim=6),
                             _kpis(300, 4, speed=75, vc=2.0, skim=10)])
        self.assertEqual(agg["vmt_miles"], 400)
        self.assertEqual(agg["avg_speed_mph"], 50.0)
        self.assertEqual(agg["max_vc"], 2.0)
        self.assertIsNone(agg["co2_proxy_kg"])             # all-None stays None


def _find_exe():
    for c in (os.environ.get("DTALITE_EXE"),
              os.path.join(REPO, "bin", "DTALite.exe"),
              os.path.join(REPO, "release_v0.2.0", "DTALite.exe")):
        if c and os.path.exists(c):
            return c
    return None


EXE = _find_exe()


@unittest.skipIf(EXE is None, "no DTALite kernel found (set $DTALITE_EXE)")
class KernelCityBrain(unittest.TestCase):
    def test_two_region_fanout_and_totals(self):
        from dtalite_qa.citybrain import RegionAgent
        brain = CityBrain([
            RegionAgent("A", SKETCH, exe=EXE, run_kwargs=dict(max_iter=10)),
            RegionAgent("B", SKETCH, exe=EXE, run_kwargs=dict(max_iter=10))])
        base = brain.reset()
        self.assertEqual(set(base), {"A", "B"})
        for r in base.values():
            self.assertGreater(r["skim_summary"]["n"], 0)
            self.assertGreater(r["kpis"]["vmt_miles"], 0)
            self.assertIsNotNone(r["policy"])              # theta captured for reuse
        totals = brain.kpi_totals()
        one = base["A"]["kpis"]["vmt_miles"]
        self.assertAlmostEqual(totals["vmt_miles"], 2 * one, delta=one * 0.02)
        # a scenario step on one region only, warm-started
        s1 = brain.step({"A": {"tolls": [[1071, 8.0]]}})
        self.assertEqual(set(s1), {"A", "B"})
        self.assertGreater(brain.agents["A"].query_skim(1, 2)["skim_time"], 0)
        brain.close()


if __name__ == "__main__":
    unittest.main()
