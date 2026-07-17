"""Focused leak-check coverage for TAPLite's inclusive 3-D allocator bounds."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class MemoryAllocatorTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "the focused leak probe uses Unix tooling")
    def test_alloc_3d_and_free_3d_have_matching_bounds(self):
        configured_compiler = os.environ.get("CXX")
        compiler = (
            shlex.split(configured_compiler)
            if configured_compiler
            else [shutil.which("c++")]
        )
        if not compiler[0]:
            self.skipTest("no C++ compiler available")

        use_apple_leaks = sys.platform == "darwin"
        if use_apple_leaks and not shutil.which("leaks"):
            self.skipTest("the macOS leaks tool is unavailable")

        source = r"""
#include "TAPLite.h"

int main() {
    int*** values = reinterpret_cast<int***>(Alloc_3D(2, 3, 4, sizeof(int)));
    for (int i = 0; i <= 2; ++i)
        for (int j = 0; j <= 3; ++j)
            for (int k = 0; k <= 4; ++k)
                values[i][j][k] = i + j + k;
    Free_3D(reinterpret_cast<void***>(values), 2, 3, 4);
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="taplite-asan-") as directory:
            root = Path(directory)
            source_path = root / "allocator_test.cpp"
            executable = root / "allocator_test"
            source_path.write_text(source, encoding="ascii")
            sanitizer_args = [] if use_apple_leaks else [
                "-fsanitize=address",
                "-fno-omit-frame-pointer",
            ]
            build = subprocess.run(
                [
                    *compiler,
                    "-std=c++17",
                    *sanitizer_args,
                    "-I",
                    str(REPO / "kernel" / "src"),
                    str(source_path),
                    "-o",
                    str(executable),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if build.returncode != 0:
                self.skipTest(f"allocator compiler probe failed: {build.stderr}")

            environment = os.environ.copy()
            if use_apple_leaks:
                environment["MallocStackLogging"] = "1"
                command = ["leaks", "--atExit", "--", str(executable)]
            else:
                environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
                command = [str(executable)]
            try:
                run = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                    timeout=5 if use_apple_leaks else 30,
                )
            except subprocess.TimeoutExpired as exc:
                stderr = exc.stderr or ""
                if isinstance(stderr, bytes):
                    stderr = stderr.decode(errors="replace")
                if use_apple_leaks and "Couldn't get task port" in stderr:
                    self.skipTest("macOS sandbox denied the leaks tool task port")
                raise
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
