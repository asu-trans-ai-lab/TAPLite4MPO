"""KPI4MPO/NPO tests -- NO kernel required.

Computes the 10 MVP KPIs from a canned run folder with known values and checks the
exact numbers, the proxy opt-in behavior, the two external-tool Nones, compare()
deltas, and objective(). KPI is independent of TAPCI (reads a run folder), so this
suite is self-contained.

Run: python -m unittest tests.test_kpi
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from dtalite_qa import kpi        # noqa: E402
from dtalite_qa import csvio      # noqa: E402


def _fixture_run(scale=1.0):
    """A run folder with two loaded links + one OD row, known values.
    vmt=160*scale, vht=4*scale, mean_speed=40, delay=10*scale hr, max_vc=1.5,
    od_skim=6 min."""
    d = tempfile.mkdtemp(prefix="kpi_fix_")
    csvio.write(os.path.join(d, "link_performance.csv"),
                ["link_id", "volume", "speed_mph", "doc", "travel_time", "vdf_fftt", "VMT"],
                [{"link_id": "1", "volume": str(100 * scale), "speed_mph": "30", "doc": "0.8",
                  "travel_time": "10", "vdf_fftt": "6", "VMT": str(60 * scale)},
                 {"link_id": "2", "volume": str(200 * scale), "speed_mph": "50", "doc": "1.5",
                  "travel_time": "8", "vdf_fftt": "7", "VMT": str(100 * scale)}])
    csvio.write(os.path.join(d, "od_performance.csv"),
                ["mode", "o_zone_id", "d_zone_id", "volume", "total_congestion_travel_time"],
                [{"mode": "sov", "o_zone_id": "1", "d_zone_id": "2", "volume": "10",
                  "total_congestion_travel_time": "6"}])
    return d


class KpiCompute(unittest.TestCase):
    def setUp(self):
        self.d = _fixture_run()

    def test_six_real_kpis(self):
        k = kpi.compute(self.d)
        self.assertAlmostEqual(k["vmt_miles"], 160.0, places=1)
        self.assertAlmostEqual(k["vht_hours"], 4.0, places=1)
        self.assertAlmostEqual(k["avg_speed_mph"], 40.0, places=1)
        self.assertAlmostEqual(k["total_delay_hours"], 10.0, places=1)  # (400+200)/60
        self.assertAlmostEqual(k["max_vc"], 1.5, places=3)
        self.assertAlmostEqual(k["od_skim_time_min"], 6.0, places=3)

    def test_proxies_are_opt_in(self):
        self.assertIsNone(kpi.compute(self.d)["co2_proxy_kg"])
        self.assertIsNone(kpi.compute(self.d)["person_delay_hours"])
        k = kpi.compute(self.d, co2_kg_per_mile=0.4, occupancy=1.5)
        self.assertAlmostEqual(k["co2_proxy_kg"], 64.0, places=1)      # 160 * 0.4
        self.assertAlmostEqual(k["person_delay_hours"], 15.0, places=1)  # 10 * 1.5

    def test_external_kpis_are_none(self):
        k = kpi.compute(self.d)
        self.assertIsNone(k["bottleneck_duration_hours"])
        self.assertIsNone(k["accessibility_to_jobs"])
        self.assertEqual(len(kpi.available(k)), 6)                     # 6 real, no proxies

    def test_metadata_matches_keys(self):
        self.assertEqual(set(kpi.MVP_KPIS), set(kpi.compute(self.d)))
        self.assertEqual(len(kpi.MVP_KPIS), 10)


class KpiCompareObjective(unittest.TestCase):
    def test_compare_deltas(self):
        base, build = _fixture_run(1.0), _fixture_run(1.1)   # +10% everything
        cmp = kpi.compare(base, build)
        self.assertAlmostEqual(cmp["vmt_miles"]["delta"], 16.0, places=1)   # 176-160
        self.assertAlmostEqual(cmp["vmt_miles"]["pct"], 10.0, places=1)
        # max_vc unchanged (doc same) -> delta 0
        self.assertAlmostEqual(cmp["max_vc"]["delta"], 0.0, places=3)
        # external KPI: both None -> delta None, no crash
        self.assertIsNone(cmp["accessibility_to_jobs"]["delta"])

    def test_objective_weighted_sum(self):
        k = kpi.compute(_fixture_run())
        obj = kpi.objective(k, {"vht_hours": 1.0, "total_delay_hours": 2.0})
        self.assertAlmostEqual(obj, 4.0 + 2.0 * 10.0, places=1)            # 24.0
        # None-valued KPIs are skipped, not crashed
        self.assertAlmostEqual(kpi.objective(k, {"accessibility_to_jobs": 5.0}), 0.0)


if __name__ == "__main__":
    unittest.main()
