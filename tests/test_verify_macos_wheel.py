"""Platform-independent tests for the macOS wheel verifier's parsing rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
VERIFIER_PATH = REPO / "scripts" / "verify_macos_wheel.py"
SPEC = importlib.util.spec_from_file_location("verify_macos_wheel", VERIFIER_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import machinery failure
    raise RuntimeError(f"Could not load {VERIFIER_PATH}")
verify_macos_wheel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_macos_wheel)


class WheelMemberTests(unittest.TestCase):
    def test_native_extension_must_be_directly_in_pytaplite(self):
        expected = "pytaplite/_native.cpython-312-darwin.so"
        self.assertEqual(
            verify_macos_wheel._native_extension_members([expected]),
            [expected],
        )
        with self.assertRaisesRegex(RuntimeError, "outside pytaplite"):
            verify_macos_wheel._native_extension_members(
                ["other/_native.cpython-312-darwin.so"]
            )

    def test_wheel_member_paths_are_normalized_before_matching(self):
        member = r"pytaplite\_native.cpython-312-darwin.so"
        self.assertEqual(
            verify_macos_wheel._native_extension_members([member]),
            [member],
        )


class PlatformTagTests(unittest.TestCase):
    def test_single_macos_platform_tag_is_parsed(self):
        wheel = Path(
            "taplite4mpo-0.3.0-cp312-cp312-macosx_13_0_arm64.whl"
        )
        self.assertEqual(
            verify_macos_wheel._macos_platform_tag(wheel),
            ("macosx_13_0_arm64", "13.0", "arm64"),
        )

    def test_x86_64_macos_platform_tag_is_parsed(self):
        wheel = Path(
            "taplite4mpo-0.3.0-cp312-cp312-macosx_13_0_x86_64.whl"
        )
        self.assertEqual(
            verify_macos_wheel._macos_platform_tag(wheel),
            ("macosx_13_0_x86_64", "13.0", "x86_64"),
        )

    def test_multi_platform_tag_is_rejected(self):
        wheel = Path(
            "taplite4mpo-0.3.0-cp312-cp312-"
            "macosx_13_0_arm64.macosx_13_0_x86_64.whl"
        )
        with self.assertRaisesRegex(RuntimeError, "multi-platform"):
            verify_macos_wheel._macos_platform_tag(wheel)

    def test_unsupported_platform_tag_is_rejected(self):
        wheel = Path("taplite4mpo-0.3.0-cp312-cp312-any.whl")
        with self.assertRaisesRegex(RuntimeError, "unsupported macOS platform"):
            verify_macos_wheel._macos_platform_tag(wheel)

    def test_wheel_tag_must_match_configured_deployment_target(self):
        wheel = Path(
            "taplite4mpo-0.3.0-cp312-cp312-macosx_11_0_arm64.whl"
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "declares macOS 11.0, expected the configured deployment target 13.0",
        ):
            verify_macos_wheel.verify_wheel(wheel, "arm64", "13.0")


class RuntimeSearchPathTests(unittest.TestCase):
    LOAD_COMMANDS = """\
Load command 1
          cmd LC_RPATH
      cmdsize 48
         path @loader_path/../.dylibs (offset 12)
Load command 2
          cmd LC_RPATH
      cmdsize 40
         path /opt/homebrew/lib (offset 12)
"""

    def test_all_runtime_search_paths_are_parsed(self):
        self.assertEqual(
            verify_macos_wheel._runtime_search_paths(self.LOAD_COMMANDS),
            ["@loader_path/../.dylibs", "/opt/homebrew/lib"],
        )

    def test_relative_and_apple_system_paths_are_allowed(self):
        verify_macos_wheel._verify_runtime_search_paths(
            Path("_native.so"),
            [
                "@loader_path/../.dylibs",
                "@rpath",
                "/usr/lib",
                "/System/Library/Frameworks",
            ],
        )

    def test_build_machine_absolute_rpath_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "absolute LC_RPATH"):
            verify_macos_wheel._verify_runtime_search_paths(
                Path("_native.so"), ["/private/tmp/wheel-build"]
            )


class BinaryCompatibilityTests(unittest.TestCase):
    LOAD_COMMANDS_14 = """\
Load command 1
          cmd LC_BUILD_VERSION
      cmdsize 32
     platform MACOS
        minos 14.0
"""

    def test_binary_newer_than_deployment_target_is_rejected(self):
        def command_output(*command):
            if command[:2] == ("otool", "-l"):
                return self.LOAD_COMMANDS_14
            if command[:2] == ("lipo", "-archs"):
                return "arm64\n"
            if command[:3] == ("xcrun", "vtool", "-show-build"):
                return self.LOAD_COMMANDS_14
            raise AssertionError(f"unexpected command: {command}")

        dependencies_patch = mock.patch.object(
            verify_macos_wheel, "_dependencies", return_value=("", [])
        )
        install_id_patch = mock.patch.object(
            verify_macos_wheel, "_install_id", return_value=None
        )
        run_patch = mock.patch.object(
            verify_macos_wheel, "_run", side_effect=command_output
        )
        error = self.assertRaisesRegex(
            RuntimeError,
            "requires macOS 14.0, but the wheel targets macOS 13.0",
        )
        with dependencies_patch, install_id_patch, run_patch, error:
            verify_macos_wheel._verify_binary(
                Path("libomp.dylib"), "arm64", "13.0", "13.0"
            )

    def test_absolute_runtime_install_id_is_rejected(self):
        dependencies_patch = mock.patch.object(
            verify_macos_wheel, "_dependencies", return_value=("", [])
        )
        install_id_patch = mock.patch.object(
            verify_macos_wheel,
            "_install_id",
            return_value="/Users/runner/lib/libomp.dylib",
        )
        run_patch = mock.patch.object(
            verify_macos_wheel, "_run", return_value=""
        )
        error = self.assertRaisesRegex(RuntimeError, "absolute install ID")
        with dependencies_patch, install_id_patch, run_patch, error:
            verify_macos_wheel._verify_binary(
                Path("libomp.dylib"), "arm64", "13.0", "13.0"
            )

    def test_delocate_install_id_namespace_is_allowed(self):
        self.assertTrue(
            verify_macos_wheel._is_allowed_install_id(
                "/DLC/taplite4mpo/.dylibs/libomp.dylib"
            )
        )


class RuntimeValidationModeTests(unittest.TestCase):
    def test_runtime_validation_uses_deployment_target_as_binary_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "libomp.dylib"
            runtime.touch()
            with mock.patch.object(
                verify_macos_wheel,
                "_verify_binary",
                return_value="11.0",
            ) as verify_binary:
                verify_macos_wheel.verify_runtime(runtime, "arm64", "13.0")

        verify_binary.assert_called_once_with(
            runtime, "arm64", "13.0", "13.0"
        )

    def test_runtime_cli_defaults_to_macos_13(self):
        runtime = Path("libomp.dylib")
        with mock.patch.object(
            verify_macos_wheel, "verify_runtime"
        ) as verify_runtime:
            result = verify_macos_wheel.main(
                [
                    "--verify-runtime",
                    str(runtime),
                    "--architecture",
                    "arm64",
                ]
            )

        self.assertEqual(result, 0)
        verify_runtime.assert_called_once_with(runtime, "arm64", "13.0")


if __name__ == "__main__":
    unittest.main()
