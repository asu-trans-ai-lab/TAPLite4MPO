"""Memory-aware resourcing tests -- NO kernel required.

Covers memory_status, network_size, the footprint estimate, and the
recommend_processors decision (including the oversized-network warning and the
memory-limited cap), plus the auto-resolution helper in control.

Run: python -m unittest tests.test_resources
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from dtalite_qa import resources as R    # noqa: E402
from dtalite_qa import csvio             # noqa: E402

SKETCH = os.path.join(REPO, "kernel", "data_sets", "03_chicago_sketch")
BIG = {"nodes": 76616, "links": 246806, "zones": 11259, "od_cells": 342712, "modes": 1}


class MemoryStatus(unittest.TestCase):
    def test_status_shape(self):
        s = R.memory_status()
        self.assertIn("cpu_count", s)
        self.assertGreaterEqual(s["cpu_count"], 1)
        # on a known platform total/available are floats and available <= total
        if s["available_gb"] is not None:
            self.assertLessEqual(s["available_gb"], s["total_gb"] + 1e-6)
            self.assertGreater(s["total_gb"], 0)


class NetworkSize(unittest.TestCase):
    def test_sketch_size(self):
        sz = R.network_size(SKETCH)
        self.assertEqual(sz["nodes"], 933)
        self.assertEqual(sz["links"], 2950)
        self.assertGreater(sz["zones"], 300)
        self.assertGreater(sz["od_cells"], 0)


class Footprint(unittest.TestCase):
    def test_monotonic_in_processors(self):
        _, per, t4 = R.estimate_footprint_gb(BIG, 4)
        _, _, t16 = R.estimate_footprint_gb(BIG, 16)
        self.assertGreater(t16, t4)              # more processors -> more memory
        self.assertGreater(per, 0)

    def test_columns_add_footprint(self):
        _, _, without = R.estimate_footprint_gb(BIG, 8, with_columns=False)
        _, _, with_c = R.estimate_footprint_gb(BIG, 8, with_columns=True)
        self.assertGreater(with_c, without)


class Recommend(unittest.TestCase):
    def test_ample_memory_uses_all_cores(self):
        n, info = R.recommend_processors(size=BIG, available_gb=256.0)
        self.assertEqual(n, min(info["cpu_count"], info["cpu_count"]))
        self.assertFalse(info["oversized"])

    def test_requested_caps(self):
        n, _ = R.recommend_processors(size=BIG, available_gb=256.0, requested=2)
        self.assertEqual(n, 2)

    def test_oversized_network_warns_and_returns_one(self):
        n, info = R.recommend_processors(size=BIG, available_gb=3.0, with_columns=True)
        self.assertEqual(n, 1)
        self.assertTrue(info["oversized"])
        self.assertIn("super-zone", info["reason"])   # honest fix, not "fewer threads"

    def test_unknown_memory_does_not_guess_down(self):
        n, info = R.recommend_processors(size=BIG, available_gb=None, requested=8)
        self.assertEqual(n, 8)                    # no memory cap applied
        self.assertFalse(info["oversized"])


class AutoResolve(unittest.TestCase):
    def test_control_resolves_auto_in_settings(self):
        from dtalite_qa import control
        d = tempfile.mkdtemp(prefix="autoproc_")
        # a tiny scenario copy with number_of_processors=auto
        for f in ("node.csv", "link.csv", "mode_type.csv", "demand.csv"):
            src = os.path.join(SKETCH, f)
            if os.path.exists(src):
                csvio.write(os.path.join(d, f), *csvio.read(src))
        csvio.write(os.path.join(d, "settings.csv"),
                    ["number_of_iterations", "number_of_processors", "column_output"],
                    [{"number_of_iterations": "5", "number_of_processors": "auto",
                      "column_output": "0"}])
        note = control._resolve_auto_processors(d)
        self.assertIsNotNone(note)
        _, rows = csvio.read(os.path.join(d, "settings.csv"))
        self.assertTrue(rows[0]["number_of_processors"].isdigit())   # auto -> concrete int
        self.assertGreaterEqual(int(rows[0]["number_of_processors"]), 1)

    def test_non_auto_untouched(self):
        from dtalite_qa import control
        d = tempfile.mkdtemp(prefix="autoproc2_")
        csvio.write(os.path.join(d, "settings.csv"),
                    ["number_of_processors"], [{"number_of_processors": "6"}])
        self.assertIsNone(control._resolve_auto_processors(d))
        _, rows = csvio.read(os.path.join(d, "settings.csv"))
        self.assertEqual(rows[0]["number_of_processors"], "6")


class Tracer(unittest.TestCase):
    def test_tracer_summary_shape(self):
        with R.MemoryTracer(interval=0.05) as t:
            _ = [i * i for i in range(10000)]
        s = t.summary()
        self.assertIn("peak_used_gb", s)
        self.assertIn("baseline_avail_gb", s)


if __name__ == "__main__":
    unittest.main()
