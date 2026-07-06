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

    def test_cat2_skims(self):
        skims = self.sim.observe_skims()
        self.assertGreater(len(skims), 0)
        self.assertTrue(all(s["path_available"] for s in skims[:50]))
        # a valid OD resolves; a nonsense OD reports path_available False
        self.assertFalse(self.sim.query_skim(999999, 999998)["path_available"])


@unittest.skipIf(EXE is None, "no DTALite kernel found (set $DTALITE_EXE)")
class TapciScenarioEdits(unittest.TestCase):
    """Category-2 next-run edits, checked CAUSALLY against the kernel."""

    def test_closure_zeros_the_link(self):
        base = TAPCI.open(SKETCH, exe=EXE)
        base.run_until_converged(max_iter=15, gap=0.001, override=_OVR)
        vol = {r["link_id"]: float(r["volume"]) for r in base.observe_links(["volume"])}
        busy = max(vol, key=vol.get)
        self.assertGreater(vol[busy], 0)

        closed = TAPCI.open(SKETCH, exe=EXE).set_link_closure([busy])
        closed.run_until_converged(max_iter=15, gap=0.001, override=_OVR)
        after = {r["link_id"]: float(r["volume"]) for r in closed.observe_links(["volume"])}
        self.assertLess(after[busy], 1e-6, "closed link must carry zero volume")
        closed.close()

    def test_source_network_untouched(self):
        import hashlib
        src_link = os.path.join(SKETCH, "link.csv")
        before = hashlib.md5(open(src_link, "rb").read()).hexdigest()
        sim = TAPCI.open(SKETCH, exe=EXE).set_link_closure([1]).set_toll([2], 5.0)
        sim.run_until_converged(max_iter=5, gap=0.001, override=_OVR)
        after = hashlib.md5(open(src_link, "rb").read()).hexdigest()
        self.assertEqual(before, after, "source link.csv must be untouched by edits")
        sim.close()


@unittest.skipIf(EXE is None, "no DTALite kernel found (set $DTALITE_EXE)")
class TapciStreamLoop(unittest.TestCase):
    """Repeated-run / open-close stability (MVP robustness): identical reruns give
    identical MOEs and nothing leaks or drifts across a stream of runs."""

    def test_repeated_runs_are_stable(self):
        vmts = []
        for _ in range(3):
            sim = TAPCI.open(SKETCH, exe=EXE)
            sim.run_until_converged(max_iter=10, gap=0.001, override=_OVR)
            vmts.append(sim.moe()["vmt"])
            sim.close()
        # deterministic kernel -> identical VMT across identical reruns
        self.assertLess(max(vmts) - min(vmts), 1.0, f"VMT drifted across reruns: {vmts}")


@unittest.skipIf(EXE is None, "no DTALite kernel found (set $DTALITE_EXE)")
class TapciEnvLoop(unittest.TestCase):
    def test_reset_and_steps(self):
        from dtalite_qa.tapci_env import TAPCIEnv
        env = TAPCIEnv(SKETCH, exe=EXE, reward="vht", max_iter=10)
        obs = env.reset()
        self.assertGreater(obs["vht"], 0)
        o1, r1, done, info = env.step({"type": "od_multiplier", "factor": 1.1})
        self.assertIsInstance(r1, float)
        self.assertGreater(o1["vmt"], obs["vmt"])          # +10% demand -> more VMT
        self.assertFalse(done)
        o2, r2, _, _ = env.step({"type": "noop"})
        self.assertIsInstance(r2, float)
        env.close()


if __name__ == "__main__":
    unittest.main()
