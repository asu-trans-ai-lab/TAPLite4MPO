"""Installed-wheel self-demo test.

A source-tree-only demo can pass while the published wheel is missing data
files or the native path. This test builds the wheel, installs it into a
FRESH virtual environment, changes to an unrelated empty directory, and runs

    python -m dtalite_qa self-demo --output selfdemo_artifacts

It is slow (wheel build + full Chicago Sketch run), so it is skipped unless
TAPLITE_WHEEL_TEST=1 -- CI and releases set it; fast local unittest runs skip.

Kernel note: wheels produced by cibuildwheel carry the compiled in-process
binding (pytaplite._native). A locally built pure wheel (no C++ toolchain for
the binding) falls back to the subprocess kernel, which this test supplies via
TAPLITE_EXE from the repo build -- proving the packaged DATA and gates while
CI's wheel jobs prove the packaged NATIVE path.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("TAPLITE_WHEEL_TEST") == "1",
                     "set TAPLITE_WHEEL_TEST=1 (slow; CI/releases run it)")
class InstalledWheelSelfDemoTest(unittest.TestCase):
    def test_wheel_selfdemo(self):
        with tempfile.TemporaryDirectory(prefix="taplite_wheel_") as td:
            td = Path(td)
            dist = td / "dist"
            subprocess.run([sys.executable, "-m", "pip", "wheel", str(REPO),
                            "--wheel-dir", str(dist), "--no-deps"],
                           check=True, capture_output=True, text=True)
            wheels = list(dist.glob("taplite4mpo-*.whl"))
            self.assertTrue(wheels, "wheel was not built")

            venv = td / "venv"
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
            vpy = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            subprocess.run([str(vpy), "-m", "pip", "install", "-q", str(wheels[0])],
                           check=True)

            empty = td / "empty"
            empty.mkdir()
            env = os.environ.copy()
            exe = REPO / "bin" / ("TAPLite.exe" if os.name == "nt" else "TAPLite")
            if exe.exists():
                env.setdefault("TAPLITE_EXE", str(exe))
            p = subprocess.run([str(vpy), "-m", "dtalite_qa", "self-demo",
                                "--output", "selfdemo_artifacts"],
                               cwd=empty, env=env, capture_output=True, text=True,
                               timeout=1800)
            self.assertEqual(p.returncode, 0,
                             f"installed-wheel self-demo failed:\n{p.stdout}\n{p.stderr}")
            art = empty / "selfdemo_artifacts"
            self.assertTrue((art / "selfdemo_dashboard.html").exists())
            self.assertTrue((art / "selfdemo_summary.json").exists())
            # never wrote inside site-packages
            site = venv / ("Lib/site-packages" if os.name == "nt"
                           else f"lib/python{sys.version_info.major}."
                                f"{sys.version_info.minor}/site-packages")
            leaked = list(Path(site, "dtalite_qa").rglob("taplite_selfdemo_output*"))
            self.assertFalse(leaked, f"wrote inside the installed package: {leaked}")


if __name__ == "__main__":
    unittest.main()
