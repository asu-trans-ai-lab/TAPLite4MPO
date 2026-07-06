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


class SkimService(unittest.TestCase):
    def setUp(self):
        self.sim = _sim_with_fake_run()

    def test_observe_skims(self):
        rows = self.sim.observe_skims()
        self.assertEqual(rows[0]["skim_time"], 6.0)          # congested tt
        self.assertEqual(rows[0]["skim_distance"], 3.0)
        self.assertTrue(rows[0]["path_available"])

    def test_query_skim_found_and_missing(self):
        self.assertTrue(self.sim.query_skim(1, 2)["path_available"])
        miss = self.sim.query_skim(9, 9)
        self.assertFalse(miss["path_available"])
        self.assertIsNone(miss["skim_time"])

    def test_save_skims_json(self):
        out = os.path.join(tempfile.mkdtemp(), "skims.json")
        self.sim.save_skims(out)
        with open(out, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["format"], "tapci.skims.v1")
        self.assertGreater(doc["n"], 0)


class ScenarioEditLogic(unittest.TestCase):
    """The edit MECHANICS, exercised without a kernel by applying edits to a
    fixture link.csv and reading the result back."""

    def _link_fixture(self):
        d = tempfile.mkdtemp(prefix="tapci_link_")
        _write_csv(os.path.join(d, "link.csv"),
                   ["link_id", "capacity", "vdf_toll", "allowed_uses"],
                   [{"link_id": "10", "capacity": "1000", "vdf_toll": "0", "allowed_uses": "all"},
                    {"link_id": "20", "capacity": "2000", "vdf_toll": "0", "allowed_uses": "all"}])
        return d

    def test_set_methods_record_edits(self):
        sim = TAPCI(_api.Network.read_gmns(SKETCH))
        sim.set_link_closure([10]).set_link_capacity([20], factor=0.5)
        sim.set_toll([30], 2.5).set_od_multiplier(1.1, o_zones=[1])
        ops = {e["op"] for e in sim._edits}
        self.assertEqual(ops, {"closure", "capacity", "toll", "od_mult"})
        self.assertEqual(len(sim.clear_edits()._edits), 0)

    def test_capacity_needs_exactly_one_of(self):
        sim = TAPCI(_api.Network.read_gmns(SKETCH))
        with self.assertRaises(ValueError):
            sim.set_link_capacity([1])                       # neither
        with self.assertRaises(ValueError):
            sim.set_link_capacity([1], factor=2, value=5)    # both

    def test_apply_link_edits_writes_expected_columns(self):
        d = self._link_fixture()
        ops = [{"op": "closure", "links": {"10"}},
               {"op": "capacity", "links": {"20"}, "factor": 0.5, "value": None},
               {"op": "toll", "links": {"20"}, "toll": 3.0}]
        TAPCI._apply_link_edits(d, ops)
        _, rows = csvio.read(os.path.join(d, "link.csv"))
        by_id = {r["link_id"]: r for r in rows}
        # closure writes the singular allowed_use the kernel reads
        self.assertEqual(by_id["10"]["allowed_use"], "closed")
        self.assertEqual(float(by_id["20"]["capacity"]), 1000.0)   # 2000 * 0.5
        self.assertEqual(float(by_id["20"]["vdf_toll"]), 3.0)


class EnvContract(unittest.TestCase):
    def test_env_import_and_action_validation(self):
        from dtalite_qa.tapci_env import TAPCIEnv
        env = TAPCIEnv(SKETCH)                     # open reads the network; no solve
        self.assertEqual(set(env.action_space()),
                         {"noop", "link_closure", "link_capacity", "toll", "od_multiplier"})
        with self.assertRaises(ValueError):
            env._apply({"type": "bogus"})
        with self.assertRaises(ValueError):
            TAPCIEnv(SKETCH, reward="nonsense")


if __name__ == "__main__":
    unittest.main()
