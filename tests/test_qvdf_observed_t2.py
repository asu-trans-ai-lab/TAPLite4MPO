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


def _rewrite_optional_link_column(path, column, values):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if column not in fields:
        fields.append(column)
    for row, value in zip(rows, values):
        row[column] = value
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _set_setting(path, column, value):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if column not in fields:
        fields.append(column)
    for row in rows:
        row[column] = value
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
    profile_modes=None,
    qvdf_volume_threshold=None,
    start_speeds=None,
    end_speeds=None,
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
    if profile_modes is not None:
        _rewrite_optional_link_column(
            scenario / "link.csv", "qvdf_profile_mode", profile_modes
        )
    if start_speeds is not None:
        _rewrite_optional_link_column(
            scenario / "link.csv", "qvdf_start_speed_mph", start_speeds
        )
    if end_speeds is not None:
        _rewrite_optional_link_column(
            scenario / "link.csv", "qvdf_end_speed_mph", end_speeds
        )
    if qvdf_volume_threshold is not None:
        _set_setting(
            scenario / "settings.csv",
            "qvdf_volume_threshold",
            qvdf_volume_threshold,
        )
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
    @staticmethod
    def _speed_columns(row):
        return [name for name in row if name.startswith("spd_mph_")]

    @staticmethod
    def _decimal_hour(column):
        clock = column.removeprefix("spd_mph_")
        hour, minute = map(int, clock.split(":"))
        return hour + minute / 60.0

    def _assert_smoothed_boundary_fallback(
        self, row, start_speed, end_speed
    ):
        speed_columns = self._speed_columns(row)
        last_index = len(speed_columns) - 1
        for index, column in enumerate(speed_columns):
            factor = index / last_index if last_index else 0.0
            smooth = factor * factor * (3.0 - 2.0 * factor)
            expected = (
                (1.0 - smooth) * start_speed + smooth * end_speed
            )
            self.assertAlmostEqual(
                float(row[column]), expected, delta=0.0011, msg=column
            )

    def test_missing_profile_mode_preserves_legacy_activation(self):
        for label, profile_modes in (("missing", None), ("blank", ["", ""])):
            with self.subTest(label):
                temporary, result, rows = _run_variant(
                    profile_modes=profile_modes
                )
                self.addCleanup(temporary.cleanup)
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                for row in rows.values():
                    self.assertEqual(
                        row["qvdf_profile_status"],
                        "generated_legacy_link_type",
                    )

    def test_disabled_mode_writes_unambiguous_flat_fallback(self):
        temporary, result, rows = _run_variant(profile_modes=["0", "0"])
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        for row in rows.values():
            period_speed = float(row["speed_mph"])
            self.assertEqual(row["qvdf_profile_status"], "flat_disabled")
            self.assertEqual(float(row["P"]), 0.0)
            self.assertAlmostEqual(
                float(row["vt2_mph"]), period_speed, delta=0.0001
            )
            self.assertAlmostEqual(
                float(row["congestion_ref_speed_mph"]),
                period_speed,
                delta=0.0001,
            )
            self.assertAlmostEqual(
                float(row["avg_queue_speed_mph"]),
                period_speed,
                delta=0.0001,
            )
            self.assertAlmostEqual(
                float(row["avg_QVDF_period_speed_mph"]),
                period_speed,
                delta=0.0001,
            )
            self.assertAlmostEqual(
                float(row["avg_QVDF_period_travel_time"]),
                float(row["travel_time"]),
                delta=0.0001,
            )
            self.assertAlmostEqual(
                float(row["VHT_QVDF"]),
                float(row["VHT"]),
                delta=0.000001,
            )
            for column, value in row.items():
                if column.startswith("spd_mph_"):
                    self.assertAlmostEqual(
                        float(value), period_speed, delta=0.0011
                    )

    def test_model_mode_selects_alternative_link_types_and_midpoint(self):
        temporary, result, rows = _run_variant(
            values=["", ""],
            link_types=["403", "405"],
            profile_modes=["1", "1"],
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for row in rows.values():
            self.assertEqual(row["qvdf_profile_status"], "generated_model")
            self.assertAlmostEqual(float(row["t2"]), 7.5, places=6)
            self.assertGreater(float(row["P"]), 0.0)

    def test_observed_mode_is_gated_by_valid_t2(self):
        temporary, result, rows = _run_variant(
            values=["7.0", ""],
            link_types=["403", "405"],
            profile_modes=["2", "2"],
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        generated, flat = rows["101"], rows["102"]
        self.assertEqual(generated["qvdf_profile_status"], "generated_observed")
        self.assertAlmostEqual(float(generated["t2"]), 7.0, places=6)
        self.assertEqual(flat["qvdf_profile_status"], "flat_missing_observation")
        self.assertEqual(float(flat["P"]), 0.0)
        self.assertGreater(float(flat["avg_QVDF_period_speed_mph"]), 0.0)

    def test_ineligible_observed_mode_smooths_either_boundary_anchor(self):
        temporary, result, rows = _run_variant(
            values=["", ""],
            link_types=["403", "405"],
            profile_modes=["2", "2"],
            start_speeds=["42", ""],
            end_speeds=["", "35"],
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        start_only, end_only = rows["101"], rows["102"]
        for row in (start_only, end_only):
            self.assertEqual(
                row["qvdf_profile_status"],
                "smoothed_boundary_missing_observation",
            )
            self.assertEqual(float(row["P"]), 0.0)
            period_speed = float(row["speed_mph"])
            self.assertAlmostEqual(
                float(row["vt2_mph"]), period_speed, delta=0.0001
            )
            self.assertAlmostEqual(
                float(row["avg_QVDF_period_speed_mph"]),
                period_speed,
                delta=0.0001,
            )
            self.assertAlmostEqual(
                float(row["avg_QVDF_period_travel_time"]),
                float(row["travel_time"]),
                delta=0.0001,
            )

        self._assert_smoothed_boundary_fallback(
            start_only, 42.0, float(start_only["speed_mph"])
        )
        self._assert_smoothed_boundary_fallback(
            end_only, float(end_only["speed_mph"]), 35.0
        )

    def test_other_ineligible_reasons_use_boundary_smoothing(self):
        temporary, result, rows = _run_variant(
            values=["", ""],
            link_types=["403", "405"],
            start_speeds=["44", ""],
            end_speeds=["", "36"],
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for row in rows.values():
            self.assertEqual(
                row["qvdf_profile_status"],
                "smoothed_boundary_legacy_not_selected",
            )

        temporary, result, rows = _run_variant(
            profile_modes=["1", "1"],
            qvdf_volume_threshold="1000000000",
            start_speeds=["44", ""],
            end_speeds=["", "36"],
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for row in rows.values():
            self.assertEqual(
                row["qvdf_profile_status"],
                "smoothed_boundary_below_volume_threshold",
            )

    def test_legacy_nonselected_and_volume_threshold_reasons(self):
        temporary, result, rows = _run_variant(
            values=["", ""],
            link_types=["403", "405"],
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for row in rows.values():
            self.assertEqual(
                row["qvdf_profile_status"], "flat_legacy_not_selected"
            )

        temporary, result, rows = _run_variant(
            profile_modes=["1", "1"],
            qvdf_volume_threshold="1000000000",
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for row in rows.values():
            self.assertEqual(
                row["qvdf_profile_status"], "flat_below_volume_threshold"
            )
            self.assertGreater(float(row["avg_QVDF_period_speed_mph"]), 0.0)

    def test_invalid_profile_modes_warn_and_use_legacy_auto(self):
        temporary, result, rows = _run_variant(
            profile_modes=["invalid", "3"]
        )
        self.addCleanup(temporary.cleanup)
        log = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, log)
        self.assertIn(
            "link_id=101 has invalid qvdf_profile_mode='invalid'", log
        )
        self.assertIn("link_id=102 has invalid qvdf_profile_mode='3'", log)
        for row in rows.values():
            self.assertEqual(
                row["qvdf_profile_status"], "generated_legacy_link_type"
            )

    def test_observed_boundary_speeds_anchor_first_and_last_samples(self):
        temporary, result, rows = _run_variant(
            start_speeds=["42", ""],
            end_speeds=["50", "35"],
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        first_columns = self._speed_columns(rows["101"])
        second_columns = self._speed_columns(rows["102"])
        self.assertAlmostEqual(float(rows["101"][first_columns[0]]), 42.0)
        self.assertAlmostEqual(float(rows["101"][first_columns[-1]]), 50.0)
        self.assertAlmostEqual(float(rows["102"][second_columns[-1]]), 35.0)

        temporary, result, baseline = _run_variant()
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            rows["102"][second_columns[0]], baseline["102"][second_columns[0]]
        )

    def test_boundary_blend_is_smooth_and_preserves_trough_and_scalars(self):
        temporary, result, baseline = _run_variant()
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        temporary, result, anchored = _run_variant(
            start_speeds=["55", "55"],
            end_speeds=["52", "52"],
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        unchanged = (
            "P",
            "t0",
            "t2",
            "t3",
            "vt2_mph",
            "avg_queue_speed_mph",
            "avg_QVDF_period_speed_mph",
            "avg_QVDF_period_travel_time",
        )
        for link_id, row in anchored.items():
            raw = baseline[link_id]
            for column in unchanged:
                self.assertEqual(row[column], raw[column], column)

            speed_columns = self._speed_columns(row)
            profile_start = self._decimal_hour(speed_columns[0])
            profile_last = self._decimal_hour(speed_columns[-1])
            pivot = float(row["t2"])
            for column in speed_columns:
                t = self._decimal_hour(column)
                raw_speed = float(raw[column])
                if t <= pivot:
                    factor = (t - profile_start) / (pivot - profile_start)
                    smooth = factor * factor * (3.0 - 2.0 * factor)
                    expected = (1.0 - smooth) * 55.0 + smooth * raw_speed
                else:
                    factor = (t - pivot) / (profile_last - pivot)
                    smooth = factor * factor * (3.0 - 2.0 * factor)
                    expected = (1.0 - smooth) * raw_speed + smooth * 52.0
                self.assertAlmostEqual(
                    float(row[column]), expected, delta=0.0011, msg=column
                )

            trough_column = min(
                speed_columns,
                key=lambda name: abs(self._decimal_hour(name) - pivot),
            )
            self.assertEqual(row[trough_column], raw[trough_column])

    def test_boundary_anchors_work_when_queue_window_touches_period_edges(self):
        temporary, result, rows = _run_variant(
            values=["6.25", "8.75"],
            start_speeds=["38", ""],
            end_speeds=["", "41"],
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        first_columns = self._speed_columns(rows["101"])
        second_columns = self._speed_columns(rows["102"])
        self.assertEqual(float(rows["101"]["t0"]), 6.0)
        self.assertEqual(float(rows["102"]["t3"]), 9.0)
        self.assertAlmostEqual(float(rows["101"][first_columns[0]]), 38.0)
        self.assertAlmostEqual(float(rows["102"][second_columns[-1]]), 41.0)

    def test_invalid_boundary_speeds_warn_and_fall_back_independently(self):
        temporary, result, baseline = _run_variant()
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        temporary, result, rows = _run_variant(
            start_speeds=["not-a-speed", "-1"],
            end_speeds=["", "nan"],
        )
        self.addCleanup(temporary.cleanup)
        log = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, log)
        self.assertIn(
            "link_id=101 has invalid qvdf_start_speed_mph='not-a-speed'", log
        )
        self.assertIn(
            "link_id=102 has invalid qvdf_start_speed_mph='-1'", log
        )
        self.assertIn("link_id=102 has invalid qvdf_end_speed_mph='nan'", log)
        for link_id, row in rows.items():
            for column in self._speed_columns(row):
                self.assertEqual(row[column], baseline[link_id][column])

    def test_disabled_mode_remains_flat_when_boundary_speeds_are_present(self):
        temporary, result, rows = _run_variant(
            profile_modes=["0", "0"],
            start_speeds=["20", "25"],
            end_speeds=["30", "35"],
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for row in rows.values():
            profile = [float(row[name]) for name in self._speed_columns(row)]
            self.assertEqual(row["qvdf_profile_status"], "flat_disabled")
            self.assertLess(max(profile) - min(profile), 0.0011)

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
