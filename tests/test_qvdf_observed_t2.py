"""Kernel regression tests for link-specific observed QVDF episode timing."""

import csv
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "test_networks" / "qvdf_observed_t2"


def _find_executable():
    configured = os.environ.get("DTALITE_EXE")
    candidates = [
        Path(configured) if configured else None,
        REPO / "bin" / "DTALite.exe",
        REPO / "bin" / "DTALite",
    ]
    return next((path for path in candidates if path and path.is_file()), None)


def _find_shared_library():
    configured = os.environ.get("DTALITE_DLL")
    if sys.platform == "win32":
        names = ["DTALite.dll"]
    elif sys.platform == "darwin":
        names = ["libDTALite.dylib"]
    else:
        names = ["libDTALite.so"]
    candidates = [Path(configured) if configured else None]
    for name in names:
        candidates.extend(
            [
                REPO / "pytaplite" / name,
                REPO / "bin" / name,
                REPO / "cmake_build_rel" / "Release" / name,
                REPO / "cmake_build_rel" / name,
            ]
        )
    return next((path for path in candidates if path and path.is_file()), None)


EXE = _find_executable()
DLL = _find_shared_library()


def _rewrite_t2(path, values=None, remove_column=False):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if remove_column:
        fields.remove("t2_hour")
        for row in rows:
            row.pop("t2_hour", None)
    elif values is not None:
        for row, value in zip(rows, values):
            row["t2_hour"] = value
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _rewrite_episode_endpoints(
    path,
    t0_values=None,
    t3_values=None,
    remove_columns=False,
):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if remove_columns:
        for column in ("t0_hour", "t3_hour"):
            fields.remove(column)
            for row in rows:
                row.pop(column, None)
    else:
        if t0_values is not None:
            for row, value in zip(rows, t0_values):
                row["t0_hour"] = value
        if t3_values is not None:
            for row, value in zip(rows, t3_values):
                row["t3_hour"] = value
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _rewrite_link_types(path, values):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for row, value in zip(rows, values):
        row["link_type"] = value
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _run_variant(
    values=None,
    remove_column=False,
    link_types=None,
    t0_values=None,
    t3_values=None,
    remove_endpoint_columns=False,
):
    temporary = tempfile.TemporaryDirectory(prefix="qvdf_t2_")
    scenario = Path(temporary.name) / "scenario"
    shutil.copytree(FIXTURE, scenario)
    if values is not None or remove_column:
        _rewrite_t2(scenario / "link.csv", values, remove_column)
    if (
        t0_values is not None
        or t3_values is not None
        or remove_endpoint_columns
    ):
        _rewrite_episode_endpoints(
            scenario / "link.csv",
            t0_values=t0_values,
            t3_values=t3_values,
            remove_columns=remove_endpoint_columns,
        )
    if link_types is not None:
        _rewrite_link_types(scenario / "link.csv", link_types)
    if DLL is not None:
        environment = os.environ.copy()
        environment["DTALITE_DLL"] = str(DLL)
        command = [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.path.insert(0, sys.argv[1]); "
                "import pytaplite; "
                "result = pytaplite.assign(sys.argv[2], prefer_inproc=True); "
                "print(result.log); "
                "raise SystemExit(result.returncode)"
            ),
            str(REPO),
            str(scenario),
        ]
    else:
        environment = None
        command = [str(EXE)]
    result = subprocess.run(
        command,
        cwd=scenario,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    with (scenario / "link_performance.csv").open(
        newline="", encoding="utf-8-sig"
    ) as stream:
        rows = {row["link_id"]: row for row in csv.DictReader(stream)}
    return temporary, result, rows


@unittest.skipIf(
    DLL is None and EXE is None,
    "no DTALite kernel found (set DTALITE_DLL or DTALITE_EXE)",
)
class ObservedQvdfT2Tests(unittest.TestCase):
    def test_outside_queue_window_uses_cubic_smoothstep(self):
        temporary, result, rows = _run_variant()
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        period_start = 6.0
        period_end = 9.0

        def decimal_hour(column):
            clock = column.removeprefix("spd_mph_")
            hour, minute = map(int, clock.split(":"))
            return hour + minute / 60.0

        for link_id, row in rows.items():
            free_speed = float(row["free_speed_mph"])
            boundary_speed = max(
                float(row["congestion_ref_speed_mph"]),
                float(row["avg_queue_speed_mph"]),
            )
            t0 = float(row["t0"])
            t3 = float(row["t3"])
            speed_columns = [
                column for column in row if column.startswith("spd_mph_")
            ]

            transitions = (
                (
                    "before",
                    [
                        column
                        for column in speed_columns
                        if period_start < decimal_hour(column) < t0
                    ],
                    (period_start + t0) / 2.0,
                ),
                (
                    "after",
                    [
                        column
                        for column in speed_columns
                        if t3 < decimal_hour(column) < period_end
                    ],
                    (t3 + period_end) / 2.0,
                ),
            )
            for label, candidates, midpoint in transitions:
                with self.subTest(link_id=link_id, transition=label):
                    self.assertTrue(candidates)
                    column = min(
                        candidates,
                        key=lambda name: abs(decimal_hour(name) - midpoint),
                    )
                    t = decimal_hour(column)
                    if label == "before":
                        factor = (t - period_start) / max(
                            0.001, t0 - period_start
                        )
                        linear_speed = (
                            (1.0 - factor) * free_speed
                            + factor * boundary_speed
                        )
                        start_speed, end_speed = free_speed, boundary_speed
                    else:
                        factor = (t - t3) / max(0.001, period_end - t3)
                        linear_speed = (
                            (1.0 - factor) * boundary_speed
                            + factor * free_speed
                        )
                        start_speed, end_speed = boundary_speed, free_speed

                    factor = min(1.0, max(0.0, factor))
                    smooth_factor = factor * factor * (3.0 - 2.0 * factor)
                    expected_speed = (
                        (1.0 - smooth_factor) * start_speed
                        + smooth_factor * end_speed
                    )
                    actual_speed = float(row[column])

                    self.assertAlmostEqual(
                        actual_speed, expected_speed, delta=0.0011
                    )
                    self.assertGreater(
                        abs(actual_speed - linear_speed),
                        0.05,
                    )
                    self.assertGreaterEqual(
                        actual_speed,
                        min(free_speed, boundary_speed) - 0.0011,
                    )
                    self.assertLessEqual(
                        actual_speed,
                        max(free_speed, boundary_speed) + 0.0011,
                    )

    def test_observed_t2_shifts_only_the_time_profile(self):
        temporary, result, rows = _run_variant()
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        first, second = rows["101"], rows["102"]

        self.assertAlmostEqual(float(first["t2"]), 7.0, places=6)
        self.assertAlmostEqual(float(second["t2"]), 8.0, places=6)
        expected_left_fraction = {"101": 0.25, "102": 0.75}
        for link_id, row in rows.items():
            left_fraction = expected_left_fraction[link_id]
            self.assertAlmostEqual(
                float(row["t0"]),
                max(
                    6.0,
                    float(row["t2"]) - left_fraction * float(row["P"]),
                ),
                places=6,
            )
            self.assertAlmostEqual(
                float(row["t3"]),
                min(
                    9.0,
                    float(row["t2"])
                    + (1.0 - left_fraction) * float(row["P"]),
                ),
                places=6,
            )

        unchanged = [
            "doc",
            "P",
            "vt2_mph",
            "avg_QVDF_period_speed_mph",
            "avg_QVDF_period_travel_time",
            "travel_time",
        ]
        for column in unchanged:
            self.assertAlmostEqual(
                float(first[column]), float(second[column]), places=6, msg=column
            )

        speed_columns = [name for name in first if name.startswith("spd_mph_")]
        first_min = min(speed_columns, key=lambda name: float(first[name]))
        second_min = min(speed_columns, key=lambda name: float(second[name]))
        self.assertEqual(first_min, "spd_mph_07:00")
        self.assertEqual(second_min, "spd_mph_08:00")

    def test_observed_endpoint_fraction_is_limited(self):
        temporary, result, rows = _run_variant(
            values=["7.5", "7.5"],
            t0_values=["7.49", "6.51"],
            t3_values=["8.49", "7.51"],
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        expected_left_fraction = {"101": 0.05, "102": 0.95}
        for link_id, row in rows.items():
            left_fraction = expected_left_fraction[link_id]
            P = float(row["P"])
            self.assertAlmostEqual(
                float(row["t0"]),
                float(row["t2"]) - left_fraction * P,
                places=6,
            )
            self.assertAlmostEqual(
                float(row["t3"]),
                float(row["t2"]) + (1.0 - left_fraction) * P,
                places=6,
            )

    def test_unusable_endpoints_silently_use_symmetric_split(self):
        variants = (
            ("missing columns", {"remove_endpoint_columns": True}),
            (
                "blank cells",
                {"t0_values": ["", ""], "t3_values": ["", ""]},
            ),
            (
                "partial episode",
                {"t0_values": ["6.5", "6.5"], "t3_values": ["", ""]},
            ),
            (
                "unordered episode",
                {"t0_values": ["7.0", "8.0"], "t3_values": ["8.5", "8.5"]},
            ),
        )
        for label, arguments in variants:
            with self.subTest(label):
                temporary, result, rows = _run_variant(**arguments)
                self.addCleanup(temporary.cleanup)
                log = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, log)
                self.assertNotIn("invalid t0_hour", log)
                self.assertNotIn("invalid t3_hour", log)
                for row in rows.values():
                    P = float(row["P"])
                    self.assertAlmostEqual(
                        float(row["t0"]),
                        max(6.0, float(row["t2"]) - P / 2),
                        places=6,
                    )
                    self.assertAlmostEqual(
                        float(row["t3"]),
                        min(9.0, float(row["t2"]) + P / 2),
                        places=6,
                    )

    def test_observed_t2_requests_profile_on_composite_nonfreeway_type(self):
        temporary, result, rows = _run_variant(link_types=["403", "201"])
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        first = rows["101"]
        self.assertAlmostEqual(float(first["t2"]), 7.0, places=6)
        self.assertEqual(
            min(
                (name for name in first if name.startswith("spd_mph_")),
                key=lambda name: float(first[name]),
            ),
            "spd_mph_07:00",
        )

    def test_issue_10_profile_acceptance_and_period_edge_clamping(self):
        temporary, result, rows = _run_variant(values=["6.25", "8.75"])
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        for row in rows.values():
            t0, t2, t3 = map(float, (row["t0"], row["t2"], row["t3"]))
            vt2 = float(row["vt2_mph"])
            cutoff = float(row["cutoff_speed_mph"])
            free_speed = 60.0
            profile = [
                float(value)
                for column, value in row.items()
                if column.startswith("spd_mph_")
            ]

            self.assertLessEqual(t0, t2)
            self.assertLessEqual(t2, t3)
            self.assertGreaterEqual(t0, 6.0)
            self.assertLessEqual(t3, 9.0)
            self.assertLessEqual(vt2, cutoff)
            # Profile cells are serialized to three decimals, so allow one
            # thousandth around the full-precision scalar outputs.
            self.assertGreaterEqual(min(profile), vt2 - 0.0011)
            self.assertLessEqual(max(profile), free_speed + 0.0011)
            self.assertAlmostEqual(min(profile), vt2, delta=0.0011)

        self.assertAlmostEqual(float(rows["101"]["t0"]), 6.0, places=6)
        self.assertAlmostEqual(float(rows["102"]["t3"]), 9.0, places=6)
        self.assertEqual(
            min(
                (name for name in rows["101"] if name.startswith("spd_mph_")),
                key=lambda name: float(rows["101"][name]),
            ),
            "spd_mph_06:15",
        )
        self.assertEqual(
            min(
                (name for name in rows["102"] if name.startswith("spd_mph_")),
                key=lambda name: float(rows["102"][name]),
            ),
            "spd_mph_08:45",
        )

    def test_missing_column_or_blank_cells_use_historical_midpoint(self):
        variants = (
            ("missing column", {"remove_column": True}),
            ("blank cells", {"values": ["", ""]}),
        )
        for label, arguments in variants:
            with self.subTest(label):
                temporary, result, rows = _run_variant(**arguments)
                self.addCleanup(temporary.cleanup)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for row in rows.values():
                    self.assertAlmostEqual(float(row["t2"]), 7.5, places=6)
                    self.assertAlmostEqual(
                        float(row["t0"]),
                        max(6.0, 7.5 - float(row["P"]) / 2),
                        places=6,
                    )
                    self.assertAlmostEqual(
                        float(row["t3"]),
                        min(9.0, 7.5 + float(row["P"]) / 2),
                        places=6,
                    )

    def test_invalid_values_report_link_and_use_midpoint(self):
        temporary, result, rows = _run_variant(values=["not-a-time", "9.5"])
        self.addCleanup(temporary.cleanup)
        log = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, log)
        self.assertIn("link_id=101 has invalid t2_hour='not-a-time'", log)
        self.assertIn("link_id=102 has invalid t2_hour='9.5'", log)
        for row in rows.values():
            self.assertAlmostEqual(float(row["t2"]), 7.5, places=6)


if __name__ == "__main__":
    unittest.main()
