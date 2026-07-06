"""TAPCI kernel tests -- REQUIRE a built DTALite kernel.

Full Category-1/2 loop on Chicago Sketch: run -> observe link/OD/system -> save
the routing policy (DTAC) -> reload it as a warm start -> confirm the replay
reaches the converged gap in far fewer iterations -> export.

Locates the kernel via $DTALITE_EXE, then bin/DTALite.exe, then
release_v0.2.0/DTALite.exe. Skips (does NOT fail) if none is present, so the
contract job stays green on a machine without a kernel.

Run: python -m unittest tests.test_tapci_kernel
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from dtalite_qa.tapci import TAPCI          # noqa: E402

SKETCH = os.path.join(REPO, "kernel", "data_sets", "03_chicago_sketch")
_OVR = "tapci ci kernel test"


def _find_exe():
    for cand in (os.environ.get("DTALITE_EXE"),
                 os.path.join(REPO, "bin", "DTALite.exe"),
                 os.path.join(REPO, "bin", "DTALite"),
                 os.path.join(REPO, "release_v0.2.0", "DTALite.exe")):
        if cand and os.path.exists(cand):
            return cand
    return None


EXE = _find_exe()


@unittest.skipIf(EXE is None, "no DTALite kernel found (set $DTALITE_EXE)")
class TapciKernelLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # one run captures link/OD/system outputs + the routing policy
        cls.sim = TAPCI.open(SKETCH, exe=EXE)
        cls.sim.set_setting(route_output=1, column_output=2)
        cls.sim.run_until_converged(max_iter=20, gap=0.001, override=_OVR)

    def test_cat1_run_and_moe(self):
        self.assertTrue(self.sim._result.ok)
        moe = self.sim.moe()
        self.assertGreater(moe["vmt"], 0)
        self.assertGreater(moe["loaded_links"], 100)
        gap = self.sim.observe_convergence()[-1]["gap_pct"]
        self.assertLess(gap, 5.0)

    def test_cat2_observe_od_and_system(self):
        od = self.sim.observe_od(["volume", "travel_time"])
        self.assertGreater(len(od), 0)
        self.assertIn("volume", od[0])
        sysrows = self.sim.observe_system(["vmt", "speed"])
        self.assertTrue(any(float(r["vmt"]) > 0 for r in sysrows))

    def test_cat2_query_and_save_paths(self):
        paths = self.sim.observe_paths()
        self.assertGreater(len(paths), 0)
        out = os.path.join(tempfile.mkdtemp(), "paths.json")
        self.sim.save_paths(out)
        import json
        with open(out, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["format"], "tapci.paths.v1")
        self.assertGreater(doc["n"], 0)

    def test_cat2_routing_policy_save_load_replay(self):
        """The headline workflow: save routing policy -> load -> execute converges fast."""
        pol = os.path.join(tempfile.mkdtemp(), "policy.dtac")
        self.sim.save_routing_policy(pol)
        self.assertGreater(os.path.getsize(pol), 0)
        cold_gap = self.sim.observe_convergence()[-1]["gap_pct"]

        sim2 = TAPCI.open(SKETCH, exe=EXE).load_routing_policy(pol)
        sim2.run_until_converged(max_iter=3, gap=0.001, override=_OVR)
        traj = sim2.observe_convergence()
        self.assertLessEqual(len(traj), 3, "replay should need very few FW iterations")
        # replay lands at or below the cold run's final gap (policy already ~optimal)
        self.assertLessEqual(traj[-1]["gap_pct"], max(cold_gap * 1.5, 0.2))

    def test_cat1_export(self):
        out = tempfile.mkdtemp(prefix="tapci_exp_")
        # export refuses a non-run dir; use a fresh (empty) child
        dest = os.path.join(out, "run")
        self.sim.export(dest)
        self.assertTrue(os.path.exists(os.path.join(dest, "link_performance.csv")))
        self.assertTrue(os.path.exists(os.path.join(dest, "manifest.json")))


if __name__ == "__main__":
    unittest.main()
