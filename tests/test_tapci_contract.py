"""TAPCI Category-1/2 CONTRACT tests -- NO kernel required.

Exercises the API surface, the category contract, the Category-3 roadmap errors,
and the Category-2 observe/save logic against small canned fixtures (a fake run
folder), so the whole thing runs in CI in seconds without building or solving.

Run: python -m unittest tests.test_tapci_contract
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from dtalite_qa import api as _api          # noqa: E402
from dtalite_qa.tapci import TAPCI          # noqa: E402
from dtalite_qa import csvio                # noqa: E402

SKETCH = os.path.join(REPO, "kernel", "data_sets", "03_chicago_sketch")


def _write_csv(path, header, rows):
    csvio.write(path, header, rows)


class _FakeRun:
    """Build a temp folder with the canned kernel outputs TAPCI reads."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="tapci_fix_")
        _write_csv(os.path.join(self.dir, "link_performance.csv"),
                   ["link_id", "volume", "speed_mph", "doc", "VMT"],
                   [{"link_id": "1", "volume": "100", "speed_mph": "35", "doc": "0.5", "VMT": "50"},
                    {"link_id": "2", "volume": "0", "speed_mph": "60", "doc": "0", "VMT": "0"}])
        _write_csv(os.path.join(self.dir, "od_performance.csv"),
                   ["mode", "o_zone_id", "d_zone_id", "volume",
                    "total_distance_mile", "total_congestion_travel_time",
                    "total_free_flow_travel_time"],
                   [{"mode": "sov", "o_zone_id": "1", "d_zone_id": "2", "volume": "10",
                     "total_distance_mile": "3.0", "total_congestion_travel_time": "6",
                     "total_free_flow_travel_time": "4"}])
        _write_csv(os.path.join(self.dir, "system_performance.csv"),
                   ["mode_type", "total_volume", "PMT (VMT in miles)",
                    "PHT (VHT in hours)", "avg_speed_mph", "TTI"],
                   [{"mode_type": "sov", "total_volume": "10", "PMT (VMT in miles)": "50",
                     "PHT (VHT in hours)": "1.4", "avg_speed_mph": "35", "TTI": "1.2"}])
        _write_csv(os.path.join(self.dir, "route_assignment.csv"),
                   ["mode", "route_id", "o_zone_id", "d_zone_id", "prob",
                    "node_ids", "link_ids", "volume", "total_travel_time"],
                   [{"mode": "sov", "route_id": "1", "o_zone_id": "1", "d_zone_id": "2",
                     "prob": "0.7", "node_ids": "1;2;3", "link_ids": "1;2",
                     "volume": "7", "total_travel_time": "6"},
                    {"mode": "sov", "route_id": "2", "o_zone_id": "1", "d_zone_id": "2",
                     "prob": "0.3", "node_ids": "1;4;3", "link_ids": "3;4",
                     "volume": "3", "total_travel_time": "7"}])
        with open(os.path.join(self.dir, "route_columns.bin"), "wb") as f:
            f.write(b"DTAC-fixture")  # presence is all save_routing_policy checks


def _sim_with_fake_run():
    sim = TAPCI(_api.Network.read_gmns(SKETCH))
    sim._result = _api.Result(_FakeRun().dir)
    return sim


class CategoryContract(unittest.TestCase):
    def test_categories_wellformed(self):
        cats = TAPCI.categories()
        self.assertEqual(set(cats), {1, 2, 3})
        all_names = [m for names in cats.values() for m in names]
        self.assertEqual(len(all_names), len(set(all_names)), "duplicate method across categories")
        for m in all_names:
            self.assertTrue(hasattr(TAPCI, m), f"contract lists {m} but TAPCI has no such attr")

    def test_cat1_2_are_callable_attrs(self):
        for m in TAPCI.categories()[1] + TAPCI.categories()[2]:
            self.assertTrue(callable(getattr(TAPCI, m)))

    def test_cat3_methods_raise_roadmap(self):
        sim = TAPCI(_api.Network.read_gmns(SKETCH))
        for m in TAPCI.categories()[3]:
            with self.assertRaises(NotImplementedError, msg=f"{m} should be roadmap"):
                getattr(sim, m)()


class ObserveBeforeRun(unittest.TestCase):
    def test_observe_before_run_raises(self):
        sim = TAPCI(_api.Network.read_gmns(SKETCH))
        for call in (sim.observe_links, sim.observe_od, sim.observe_system, sim.moe):
            with self.assertRaises(RuntimeError):
                call()


class Category2IO(unittest.TestCase):
    def setUp(self):
        self.sim = _sim_with_fake_run()

    def test_observe_od_projection(self):
        rows = self.sim.observe_od(["volume", "travel_time", "distance"])
        self.assertEqual(rows[0]["volume"], "10")
        self.assertEqual(rows[0]["travel_time"], "6")     # -> total_congestion_travel_time
        self.assertEqual(rows[0]["distance"], "3.0")      # -> total_distance_mile

    def test_observe_system_projection(self):
        r = self.sim.observe_system(["vmt", "vht", "speed"])[0]
        self.assertEqual(r["vmt"], "50")                  # -> PMT (VMT in miles)
        self.assertEqual(r["speed"], "35")

    def test_query_paths_filters_od(self):
        rows = self.sim.query_paths(1, 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["prob"] for r in rows}, {"0.7", "0.3"})
        self.assertEqual(self.sim.query_paths(9, 9), [])

    def test_save_paths_json_roundtrip(self):
        out = os.path.join(tempfile.mkdtemp(), "paths.json")
        self.sim.save_paths(out)
        with open(out, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["format"], "tapci.paths.v1")
        self.assertEqual(doc["n"], 2)
        self.assertEqual(doc["paths"][0]["prob"], "0.7")   # routing policy preserved

    def test_save_routing_policy_needs_columns(self):
        out = os.path.join(tempfile.mkdtemp(), "policy.dtac")
        self.assertEqual(self.sim.save_routing_policy(out), out)
        self.assertTrue(os.path.exists(out))

    def test_load_routing_policy_sets_warm_start(self):
        out = os.path.join(tempfile.mkdtemp(), "policy.dtac")
        self.sim.save_routing_policy(out)
        sim2 = TAPCI(_api.Network.read_gmns(SKETCH)).load_routing_policy(out, adjust_sweeps=2)
        self.assertEqual(sim2._settings["warm_start_columns"], os.path.abspath(out))
        self.assertEqual(sim2._settings["column_adjust_sweeps"], 2)

    def test_set_time_period(self):
        sim = TAPCI(_api.Network.read_gmns(SKETCH)).set_time_period(7, 9)
        self.assertEqual(sim._settings["demand_period_starting_hours"], 7)
        self.assertEqual(sim._settings["demand_period_ending_hours"], 9)


if __name__ == "__main__":
    unittest.main()
