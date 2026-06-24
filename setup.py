"""Build the TAPLite kernel into pytaplite._native (an in-process pybind11 extension).

Metadata lives in pyproject.toml; this file only declares the C++ extension and makes it
OPTIONAL — if there is no C++ compiler / OpenMP, the build still succeeds and pytaplite falls
back to launching the kernel as a subprocess (you then build DTALite.exe with build.sh).
"""
import sys

from setuptools import setup
from setuptools.command.build_ext import build_ext

try:
    from pybind11.setup_helpers import Pybind11Extension
    _HAVE_PYBIND11 = True
except Exception:                       # pybind11 not importable at setup time
    Pybind11Extension = None
    _HAVE_PYBIND11 = False


def _ext_modules():
    if not _HAVE_PYBIND11:
        return []
    ext = Pybind11Extension(
        "pytaplite._native",
        sources=["kernel/python/binding.cpp", "kernel/src/TAPLite.cpp"],
        include_dirs=["kernel/src"],
        cxx_std=17,
        # NOTE: TAPLite.cpp's main() is excluded automatically (BUILD_EXE not defined).
    )
    return [ext]


def _compiler_supports(compiler, flag):
    """True if the C++ compiler accepts `flag` (used to make OpenMP optional)."""
    import os
    import tempfile
    d = tempfile.mkdtemp()
    src = os.path.join(d, "t.cpp")
    open(src, "w").write("int main(){return 0;}\n")
    try:
        compiler.compile([src], output_dir=d, extra_postargs=[flag])
        return True
    except Exception:
        return False


class OptionalBuildExt(build_ext):
    """Add OpenMP (when available) + per-compiler flags; never fail the whole install if the
    C++ build breaks — the package still installs and pytaplite falls back to subprocess."""

    def build_extensions(self):
        ct = self.compiler.compiler_type
        for e in self.extensions:
            if ct == "msvc":
                e.extra_compile_args += ["/O2"]
                if _compiler_supports(self.compiler, "/openmp"):
                    e.extra_compile_args += ["/openmp"]
            else:                       # gcc / clang / mingw
                e.extra_compile_args += ["-O2"]
                if _compiler_supports(self.compiler, "-fopenmp"):   # absent on stock macOS clang
                    e.extra_compile_args += ["-fopenmp"]
                    e.extra_link_args += ["-fopenmp"]
                if sys.platform == "win32":     # mingw: bundle the runtime into the .pyd
                    e.extra_link_args += ["-static", "-static-libgcc", "-static-libstdc++"]
        try:
            super().build_extensions()
        except Exception as exc:        # optional extension: keep the pure-Python install
            sys.stderr.write(
                "\n[taplite4mpo] WARNING: could not build the native kernel extension "
                f"(pytaplite._native): {exc}\n"
                "The package still installs; pytaplite will run the kernel via subprocess.\n"
                "Build the kernel exe with `bash build.sh` (-> bin/DTALite.exe). "
                "See docs/ARCHITECTURE.md.\n\n")


setup(
    ext_modules=_ext_modules(),
    cmdclass={"build_ext": OptionalBuildExt},
)
