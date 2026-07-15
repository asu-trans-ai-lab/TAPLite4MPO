"""Native OpenMP diagnostics and processor-configuration regressions."""

from __future__ import annotations

import ctypes
import csv
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
NETWORK = REPO / "kernel" / "data_sets" / "01_4_node_network"
STATUS_FIELDS = {
    "compiled",
    "openmp_version",
    "max_threads",
    "num_procs",
    "dynamic",
    "requested_threads",
    "probe_team_size",
}

try:
    from pytaplite import _native
except ImportError:
    _native = None


def _write_scenario(directory: Path, processors: int, iterations: int = 2) -> None:
    for name in ("node.csv", "link.csv", "demand.csv"):
        shutil.copy2(NETWORK / name, directory / name)

    fields = [
        "number_of_iterations",
        "number_of_processors",
        "demand_period_starting_hours",
        "demand_period_ending_hours",
        "first_through_node_id",
        "base_demand_mode",
        "route_output",
        "vehicle_output",
        "log_file",
        "odme_mode",
        "odme_vmt",
        "link_output",
        "accessibility_output",
    ]
    values = [iterations, processors, 7, 8, -1, 0, 0, 0, 0, 0, 0, 1, 0]
    with (directory / "settings.csv").open("w", newline="", encoding="ascii") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerow(values)


def _run_native(directory: Path) -> tuple[int, subprocess.CompletedProcess[str]]:
    code = (
        "from pytaplite import _native; import sys; "
        "print('__KERNEL_RC__=' + str(_native.run_in_dir(sys.argv[1])))"
    )
    environment = os.environ.copy()
    pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(REPO) + (
        os.pathsep + pythonpath if pythonpath else ""
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(directory)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
    )
    match = re.search(r"__KERNEL_RC__=(\d+)", result.stdout)
    if result.returncode != 0 or match is None:
        raise AssertionError(
            f"native subprocess failed ({result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return int(match.group(1)), result


def _assignment_rows(processors: int) -> list[dict[str, str]]:
    with tempfile.TemporaryDirectory(prefix=f"taplite-p{processors}-") as directory:
        scenario = Path(directory)
        _write_scenario(scenario, processors, iterations=3)
        return_code, _ = _run_native(scenario)
        if return_code != 0:
            raise AssertionError(f"assignment returned {return_code}")
        with (scenario / "link_performance.csv").open(
            newline="", encoding="utf-8-sig"
        ) as stream:
            return list(csv.DictReader(stream))


@unittest.skipIf(_native is None, "pytaplite._native is not built")
class OpenMPStatusTests(unittest.TestCase):
    def test_native_import_and_status_fields(self):
        status = _native.openmp_status()
        self.assertEqual(set(status), STATUS_FIELDS)
        self.assertIsInstance(status["compiled"], bool)
        self.assertGreaterEqual(status["max_threads"], 1)
        self.assertGreaterEqual(status["num_procs"], 1)
        self.assertGreaterEqual(status["probe_team_size"], 1)
        if os.environ.get("TAPLITE_REQUIRE_OPENMP") == "1":
            self.assertTrue(status["compiled"])

    def test_requested_probe_does_not_change_openmp_default(self):
        before = _native.openmp_status(0)
        probe = _native.openmp_status(2)
        after = _native.openmp_status(0)

        self.assertEqual(probe["requested_threads"], 2)
        self.assertGreaterEqual(probe["probe_team_size"], 1)
        self.assertLessEqual(probe["probe_team_size"], 2)
        self.assertEqual(after["max_threads"], before["max_threads"])
        self.assertEqual(after["dynamic"], before["dynamic"])

        if before["compiled"] and before["num_procs"] >= 2:
            if probe["probe_team_size"] < 2:
                self.skipTest("external OpenMP runtime limits prevented a two-thread team")
            self.assertEqual(probe["probe_team_size"], 2)

    def test_negative_requested_threads_are_rejected(self):
        with self.assertRaises(ValueError):
            _native.openmp_status(-1)


@unittest.skipIf(_native is None, "pytaplite._native is not built")
class ProcessorConfigurationTests(unittest.TestCase):
    def test_processor_validation_boundaries(self):
        for processors in (1, 2, 17, 64, 4096):
            with self.subTest(processors=processors):
                self.assertEqual(
                    _native._processor_count_validation_status(processors), 0
                )
        for processors in (0, -3, 4097):
            with self.subTest(processors=processors):
                self.assertEqual(
                    _native._processor_count_validation_status(processors), 2
                )

    def test_invalid_processor_counts_are_rejected(self):
        for processors in (0, -3, 4097):
            with self.subTest(processors=processors):
                with tempfile.TemporaryDirectory(prefix="taplite-invalid-") as directory:
                    scenario = Path(directory)
                    _write_scenario(scenario, processors)
                    return_code, result = _run_native(scenario)
                    self.assertEqual(return_code, 2)
                    summary = (scenario / "summary_log_file.txt").read_text(
                        encoding="utf-8"
                    )
                    expected = (
                        f"number_of_processors={processors} is outside the accepted "
                        "range [1, 4096]"
                    )
                    self.assertIn(expected, summary)
                    self.assertIn(expected, result.stderr)

    def test_processor_counts_17_and_above_50(self):
        for processors in (17, 64):
            with self.subTest(processors=processors):
                with tempfile.TemporaryDirectory(
                    prefix=f"taplite-p{processors}-"
                ) as directory:
                    scenario = Path(directory)
                    _write_scenario(scenario, processors, iterations=1)
                    return_code, _ = _run_native(scenario)
                    self.assertEqual(return_code, 0)
                    self.assertTrue((scenario / "link_performance.csv").is_file())

                    summary = (scenario / "summary_log_file.txt").read_text(
                        encoding="utf-8"
                    )
                    self.assertIn("exceeds the 2 assignable origin zones", summary)

    def test_one_and_two_processor_link_results_are_equivalent(self):
        one_thread = _assignment_rows(1)
        two_threads = _assignment_rows(2)
        self.assertEqual(len(one_thread), len(two_threads))
        for first, second in zip(one_thread, two_threads):
            self.assertEqual(first["link_id"], second["link_id"])
            for field in ("volume", "doc", "travel_time", "speed_mph", "VMT"):
                self.assertTrue(
                    math.isclose(
                        float(first[field]),
                        float(second[field]),
                        rel_tol=1e-8,
                        abs_tol=1e-6,
                    ),
                    f"{field} differs for link {first['link_id']}",
                )


class SharedLibraryExportTests(unittest.TestCase):
    def test_legacy_and_status_c_abi_symbols_are_exported(self):
        if os.name == "nt":
            library_name = "DTALite.dll"
        elif sys.platform == "darwin":
            library_name = "libDTALite.dylib"
        else:
            library_name = "libDTALite.so"
        library_path = REPO / "pytaplite" / library_name
        if not library_path.is_file():
            self.skipTest("the optional C-ABI shared library is not built")

        library = ctypes.CDLL(str(library_path))
        for symbol in (
            "DTA_AssignmentAPI",
            "DTA_AssignmentAPIWithStatus",
            "DTA_SimulationAPI",
            "DTA_SimulationAPIWithStatus",
        ):
            with self.subTest(symbol=symbol):
                self.assertIsNotNone(getattr(library, symbol))


if __name__ == "__main__":
    unittest.main()
