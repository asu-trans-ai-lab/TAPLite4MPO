"""Build the optional in-process TAPLite kernel extension.

Metadata lives in pyproject.toml. Normal source installs may fall back to the
subprocess kernel when a native toolchain is unavailable. Wheel CI sets
TAPLITE_REQUIRE_OPENMP=1 so a missing native OpenMP extension is a hard error.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from setuptools import setup
from setuptools.command.build_ext import build_ext


REQUIRE_OPENMP = os.environ.get("TAPLITE_REQUIRE_OPENMP", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

try:
    from pybind11.setup_helpers import Pybind11Extension

    _HAVE_PYBIND11 = True
except Exception:  # pybind11 not importable at setup time
    Pybind11Extension = None
    _HAVE_PYBIND11 = False


def _ext_modules():
    if not _HAVE_PYBIND11:
        if REQUIRE_OPENMP:
            raise RuntimeError(
                "TAPLITE_REQUIRE_OPENMP=1, but pybind11 is unavailable; "
                "pytaplite._native cannot be built."
            )
        return []
    return [
        Pybind11Extension(
            "pytaplite._native",
            sources=["kernel/python/binding.cpp", "kernel/src/TAPLite.cpp"],
            include_dirs=["kernel/src"],
            cxx_std=17,
            # TAPLite.cpp's main() is excluded automatically (BUILD_EXE not defined).
        )
    ]


def _compiler_command(compiler):
    for attribute in ("compiler_cxx", "compiler", "cc"):
        command = getattr(compiler, attribute, None)
        if isinstance(command, (list, tuple)) and command:
            return list(command)
        if isinstance(command, str) and command:
            return [command]
    return []


def _compiler_version(compiler):
    command = _compiler_command(compiler)
    if not command:
        return ""
    try:
        result = subprocess.run(
            [command[0], "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return f"{result.stdout}\n{result.stderr}".strip()


def _is_apple_clang(compiler):
    if sys.platform != "darwin":
        return False
    version = _compiler_version(compiler)
    if "Apple clang" in version:
        return True
    if version and ("clang" in version.lower() or "gcc" in version.lower()):
        return False
    command = _compiler_command(compiler)
    name = Path(command[0]).name.lower() if command else ""
    return "clang" in name or not name


def _libomp_layout(prefix):
    prefix_path = Path(prefix).expanduser().resolve()
    include_dir = prefix_path / "include"
    library_dir = prefix_path / "lib"
    library = library_dir / "libomp.dylib"
    if (include_dir / "omp.h").is_file() and library.is_file():
        return prefix_path, include_dir, library_dir
    return None


def _find_macos_libomp():
    configured = os.environ.get("LIBOMP_PREFIX")
    if configured:
        layout = _libomp_layout(configured)
        if layout:
            return layout
        sys.stderr.write(
            f"[taplite4mpo] LIBOMP_PREFIX={configured!r} does not contain "
            "include/omp.h and lib/libomp.dylib.\n"
        )

    brew = shutil.which("brew")
    if brew:
        try:
            prefix = subprocess.run(
                [brew, "--prefix", "libomp"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.strip()
            layout = _libomp_layout(prefix)
            if layout:
                return layout
        except (OSError, subprocess.SubprocessError):
            pass

    return None


def _missing_libomp_message():
    return (
        "Apple Clang requires LLVM libomp, but a usable installation was not found.\n"
        "Install and select it with:\n"
        "  brew install libomp\n"
        "  export LIBOMP_PREFIX=\"$(brew --prefix libomp)\""
    )


def _probe_openmp(
    compiler,
    compile_args,
    link_args,
    include_dirs,
    library_dirs,
    libraries,
):
    source = """\
#include <omp.h>
int main() {
    int workers = 0;
#pragma omp parallel reduction(+:workers)
    workers += omp_get_thread_num() >= 0 ? 1 : 0;
    return (workers < 1 || omp_get_max_threads() < 1) ? 1 : 0;
}
"""
    try:
        with tempfile.TemporaryDirectory(prefix="taplite-openmp-") as directory:
            source_path = Path(directory) / "openmp_probe.cpp"
            source_path.write_text(source, encoding="ascii")
            objects = compiler.compile(
                [str(source_path)],
                output_dir=directory,
                include_dirs=[str(path) for path in include_dirs],
                extra_postargs=compile_args,
            )
            executable = compiler.executable_filename(
                "openmp_probe", output_dir=directory
            )
            compiler.link_executable(
                objects,
                executable,
                libraries=libraries,
                library_dirs=[str(path) for path in library_dirs],
                extra_postargs=link_args,
                target_lang="c++",
            )
            subprocess.run(
                [executable],
                check=True,
                capture_output=True,
                timeout=30,
            )
    except Exception as exc:
        return False, str(exc)
    return True, ""


class OptionalBuildExt(build_ext):
    """Configure and verify OpenMP, with an optional source-install fallback."""

    def _configure_openmp(self, extension):
        compiler_type = self.compiler.compiler_type
        include_dirs = []
        library_dirs = []
        libraries = []
        link_args = []

        if compiler_type == "msvc":
            compile_args = ["/openmp"]
        elif _is_apple_clang(self.compiler):
            layout = _find_macos_libomp()
            if layout is None:
                return False, _missing_libomp_message()
            prefix, include_dir, library_dir = layout
            compile_args = ["-Xpreprocessor", "-fopenmp"]
            include_dirs = [include_dir]
            library_dirs = [library_dir]
            libraries = ["omp"]
            link_args = [
                f"-Wl,-rpath,{library_dir}",
                "-Wl,-headerpad_max_install_names",
            ]
            sys.stderr.write(
                f"[taplite4mpo] Using Apple Clang OpenMP runtime at {prefix}.\n"
            )
        else:
            compile_args = ["-fopenmp"]
            link_args = ["-fopenmp"]

        supported, error = _probe_openmp(
            self.compiler,
            compile_args,
            link_args,
            include_dirs,
            library_dirs,
            libraries,
        )
        if not supported:
            return False, f"OpenMP compile/link/runtime probe failed: {error}"

        extension.extra_compile_args.extend(compile_args)
        extension.extra_link_args.extend(link_args)
        extension.include_dirs.extend(str(path) for path in include_dirs)
        extension.library_dirs.extend(str(path) for path in library_dirs)
        extension.libraries.extend(libraries)
        sys.stderr.write(
            "[taplite4mpo] OpenMP compile/link/runtime probe succeeded "
            f"with compiler type {compiler_type}.\n"
        )
        return True, ""

    def build_extensions(self):
        compiler_type = self.compiler.compiler_type
        if REQUIRE_OPENMP:
            self.force = True
        for extension in self.extensions:
            extension.extra_compile_args.append(
                "/O2" if compiler_type == "msvc" else "-O2"
            )
            configured, error = self._configure_openmp(extension)
            if not configured:
                if REQUIRE_OPENMP:
                    raise RuntimeError(
                        "TAPLITE_REQUIRE_OPENMP=1, so the native build cannot "
                        f"continue. {error}"
                    )
                sys.stderr.write(
                    "\n[taplite4mpo] WARNING: OpenMP is unavailable; building a "
                    f"serial native extension. {error}\n\n"
                )

            if sys.platform == "win32" and compiler_type != "msvc":
                extension.extra_link_args.extend(
                    ["-static", "-static-libgcc", "-static-libstdc++"]
                )

        try:
            super().build_extensions()
        except Exception as exc:
            if REQUIRE_OPENMP:
                raise
            sys.stderr.write(
                "\n[taplite4mpo] WARNING: could not build the native kernel extension "
                f"(pytaplite._native): {exc}\n"
                "The package still installs; pytaplite will run the kernel via subprocess.\n"
                "Build the kernel executable with `bash build.sh` (-> bin/DTALite.exe). "
                "See docs/ARCHITECTURE.md.\n\n"
            )


setup(
    ext_modules=_ext_modules(),
    cmdclass={"build_ext": OptionalBuildExt},
)
