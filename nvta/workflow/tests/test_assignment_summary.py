from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

import pandas as pd

from src.dtalite_postprocessing.pipeline import (
    SUMMARY_INPUT_COLUMNS,
    SUMMARY_INPUT_FILENAME,
)
from src.dtalite_postprocessing.runner import run_assignment_summary_outputs


WORKFLOW_ROOT = Path(__file__).resolve().parents[1]


class AssignmentSummaryTests(unittest.TestCase):
    def setUp(self):
        self.root = WORKFLOW_ROOT / ".test-artifacts" / str(uuid4())
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root)

    def _write_period_outputs(self, period: str, link_id: int) -> None:
        period_dir = self.root / period
        period_dir.mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "link_id": link_id,
                    "from_node_id": link_id,
                    "to_node_id": link_id + 1,
                    "link_type": 1,
                    "free_speed": 60.0,
                    "length": 1.5,
                    "length_in_mile": 1.5,
                    "TAZ": 1500,
                    "district_id": 3,
                    "FT": 1,
                    "TOLLGRP": 0,
                    f"{period.upper()}LIMIT": 0,
                    "geometry": "LINESTRING (0 0, 1 1)",
                }
            ]
        ).to_csv(period_dir / "link.csv", index=False)
        pd.DataFrame(
            [
                {
                    "link_id": link_id,
                    "volume": 100.0,
                    "speed_mph": 45.0,
                    "mod_vol_trk": 10.0,
                    "Severe_Congestion_P": 0.25,
                    "legacy_extra_column": "must not enter compact output",
                }
            ]
        ).to_csv(period_dir / "link_performance.csv", index=False)

    def test_assignment_writes_period_and_daily_compact_summaries(self):
        self._write_period_outputs("am", 1)
        self._write_period_outputs("md", 2)

        manifest = run_assignment_summary_outputs(
            scenario_output_dir=self.root,
            time_periods=["am", "md"],
            period_range_list=["0600_0900", "0900_1500"],
        )

        for label in ("am", "md", "daily"):
            output_dir = self.root / "summary" / label
            self.assertTrue((output_dir / SUMMARY_INPUT_FILENAME).is_file())
            self.assertTrue((output_dir / "statistics_data.csv").is_file())

        daily = pd.read_csv(
            self.root / "summary" / "daily" / SUMMARY_INPUT_FILENAME
        )
        self.assertEqual(list(daily.columns), SUMMARY_INPUT_COLUMNS)
        self.assertEqual(len(daily), 2)
        self.assertNotIn("legacy_extra_column", daily.columns)
        self.assertNotIn("link_id", daily.columns)
        self.assertNotIn("geometry", daily.columns)

        manifest_path = self.root / "summary" / "SUMMARY_MANIFEST.json"
        self.assertTrue(manifest_path.is_file())
        saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(saved_manifest["periods"], ["am", "md"])
        self.assertEqual(saved_manifest["daily_rows"], 2)
        self.assertEqual(manifest["daily_columns"], SUMMARY_INPUT_COLUMNS)

        self.assertFalse(
            (self.root / "link_performance_combined_processed.csv").exists(),
            "The automatic assignment path must not write the legacy wide aggregate.",
        )


if __name__ == "__main__":
    unittest.main()
