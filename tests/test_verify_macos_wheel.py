"""Platform-independent tests for the macOS wheel verifier's parsing rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


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
            "taplite4mpo-0.3.0-cp312-cp312-macosx_11_0_arm64.whl"
        )
        self.assertEqual(
            verify_macos_wheel._macos_platform_tag(wheel),
            ("macosx_11_0_arm64", "11.0", "arm64"),
        )

    def test_multi_platform_tag_is_rejected(self):
        wheel = Path(
            "taplite4mpo-0.3.0-cp312-cp312-"
            "macosx_11_0_arm64.macosx_11_0_x86_64.whl"
        )
        with self.assertRaisesRegex(RuntimeError, "multi-platform"):
            verify_macos_wheel._macos_platform_tag(wheel)

    def test_unsupported_platform_tag_is_rejected(self):
        wheel = Path("taplite4mpo-0.3.0-cp312-cp312-any.whl")
        with self.assertRaisesRegex(RuntimeError, "unsupported macOS platform"):
            verify_macos_wheel._macos_platform_tag(wheel)


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


if __name__ == "__main__":
    unittest.main()
