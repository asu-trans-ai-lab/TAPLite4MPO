"""Contract tests for `taplite self-demo` -- fast, no kernel execution."""
import json
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dtalite_qa import selfdemo                                    # noqa: E402


class SelfDemoContractTests(unittest.TestCase):
    def test_bundled_resources_discoverable(self):
        root = selfdemo._data_root()
        for case in ("chicago_sketch", "sioux_falls"):
            src = root / case if not isinstance(root, str) else os.path.join(root, case)
            names = ([e.name for e in src.iterdir()] if not isinstance(root, str)
                     else os.listdir(src))
            for required in ("node.csv", "link.csv", "demand.csv",
                             "settings.csv", "mode_type.csv"):
                self.assertIn(required, names, f"{case} missing {required}")
        self.assertIn("submission.yml",
                      [e.name for e in (root / "chicago_sketch").iterdir()]
                      if not isinstance(root, str)
                      else os.listdir(os.path.join(root, "chicago_sketch")))

    def test_baseline_valid_and_complete(self):
        b = selfdemo._read_baseline()
        self.assertIsNotNone(b, "golden_baseline.json missing or invalid")
        self.assertEqual(b["schema_version"], 1)
        self.assertEqual(b["case"], "chicago_sketch")
        self.assertEqual(b["configuration"]["assignment_method"], 0)
        self.assertEqual(b["configuration"]["number_of_processors"], 1)
        for section, keys in (("structure", ("nodes", "links", "zones",
                                             "od_records", "total_demand")),
                              ("metrics", ("vmt", "vht", "total_link_volume",
                                           "final_gap_pct")),
                              ("tolerances", ("vmt_relative", "vht_relative",
                                              "total_link_volume_relative",
                                              "benchmark_link_relative",
                                              "normalized_l1_volume"))):
            for k in keys:
                self.assertIn(k, b[section], f"baseline missing {section}.{k}")
        self.assertTrue(b["benchmark_links"])
        self.assertTrue(b["input_sha256"])
        self.assertGreater(len(b.get("link_volumes", {})), 1000)

    def test_baseline_has_no_absolute_paths(self):
        raw = json.dumps(selfdemo._read_baseline())
        for marker in (":\\\\", "C:/", "/home/", "/Users/"):
            self.assertNotIn(marker, raw,
                             f"baseline contains absolute path marker {marker!r}")

    def test_cli_exposes_selfdemo(self):
        from dtalite_qa import taplite_cli
        with self.assertRaises(SystemExit):
            taplite_cli.main(["self-demo", "--help"])

    def test_normal_mode_cannot_touch_baseline(self):
        """run_selfdemo without --record-baseline must not write the baseline."""
        target = os.path.join(os.path.dirname(selfdemo.__file__),
                              "selfdemo_data", selfdemo.BASELINE_NAME)
        before = os.path.getmtime(target)
        # refuse-inside-package guard exercises the earliest exit path without
        # running the kernel; the baseline file must remain untouched.
        rc = selfdemo.run_selfdemo(output=os.path.join(
            os.path.dirname(selfdemo.__file__), "nested_out"))
        self.assertEqual(rc, 2)
        self.assertEqual(os.path.getmtime(target), before)

    def test_arc_superzone_baseline_and_fixture(self):
        b = selfdemo._read_baseline("arc_superzone")
        self.assertIsNotNone(b, "arc_superzone golden_baseline.json missing")
        self.assertEqual(b["case"], "arc_superzone")
        self.assertEqual(b["structure"]["superzones"], 151)
        self.assertEqual(b["structure"]["original_zones"], 6031)
        self.assertIn("crosswalk_sha256", b)
        self.assertEqual(len(b["corridor_volumes"]), 5)
        for c in ("I-75", "I-85", "I-20", "I-285", "GA-400"):
            self.assertIn(c, b["corridor_volumes"])
        root = selfdemo._data_root()
        arc = root / "arc_superzone" if not isinstance(root, str) else None
        names = [e.name for e in arc.iterdir()] if arc else []
        for req in ("zone_crosswalk.csv", "build_report.json", "corridors.json",
                    "demand.csv", "link.csv", "node.csv", "submission.yml"):
            self.assertIn(req, names)

    def test_output_path_guard(self):
        pkg = os.path.dirname(os.path.abspath(selfdemo.__file__))
        self.assertEqual(selfdemo.run_selfdemo(output=os.path.join(pkg, "x")), 2)


if __name__ == "__main__":
    unittest.main()
