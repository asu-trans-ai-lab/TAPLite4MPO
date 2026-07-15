"""Fail when a repaired macOS wheel lacks a portable native OpenMP runtime."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


ALLOWED_ABSOLUTE_PREFIXES = ("/usr/lib/", "/System/Library/")
BUILD_MACHINE_PREFIXES = ("/opt/homebrew/", "/usr/local/", "/home/linuxbrew/", "/Cellar/")


def _run(*command: str) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _dependencies(binary: Path) -> tuple[str, list[str]]:
    output = _run("otool", "-L", str(binary))
    dependencies = []
    for line in output.splitlines()[1:]:
        stripped = line.strip()
        if stripped:
            dependencies.append(stripped.split(" ", 1)[0])
    return output, dependencies


def _install_id(binary: Path) -> str | None:
    if binary.suffix != ".dylib":
        return None
    lines = [line.strip() for line in _run("otool", "-D", str(binary)).splitlines()]
    return lines[1] if len(lines) > 1 else None


def _minimum_macos_version(binary: Path) -> str | None:
    output = _run("otool", "-l", str(binary))
    load_command = ""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("cmd LC_"):
            load_command = stripped.removeprefix("cmd ")
        elif load_command == "LC_BUILD_VERSION" and stripped.startswith("minos "):
            return stripped.split()[1]
        elif (
            load_command == "LC_VERSION_MIN_MACOSX"
            and stripped.startswith("version ")
        ):
            return stripped.split()[1]
    return None


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def _verify_binary(binary: Path, architecture: str, deployment_target: str) -> None:
    linked_libraries, dependencies = _dependencies(binary)
    mach_o_commands = _run("otool", "-l", str(binary))
    for prefix in BUILD_MACHINE_PREFIXES:
        if prefix in linked_libraries or prefix in mach_o_commands:
            raise RuntimeError(f"{binary.name} retains build-machine path {prefix}")

    install_id = _install_id(binary)
    for dependency in dependencies:
        if dependency == install_id:
            continue
        if dependency.startswith("/") and not dependency.startswith(ALLOWED_ABSOLUTE_PREFIXES):
            raise RuntimeError(
                f"{binary.name} has non-portable absolute dependency {dependency}"
            )

    architectures = _run("lipo", "-archs", str(binary)).split()
    if architecture not in architectures:
        raise RuntimeError(
            f"{binary.name} has architectures {architectures}, expected {architecture}"
        )

    minimum = _minimum_macos_version(binary)
    if minimum is None:
        raise RuntimeError(f"Could not determine the macOS minimum version for {binary.name}")
    if _version_tuple(minimum) > _version_tuple(deployment_target):
        raise RuntimeError(
            f"{binary.name} requires macOS {minimum}, but the wheel targets "
            f"macOS {deployment_target}"
        )


def verify_wheel(
    wheel: Path,
    architecture: str,
    deployment_target: str,
) -> None:
    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
        native_members = [
            name
            for name in members
            if Path(name).name.startswith("_native") and name.endswith(".so")
        ]
        libomp_members = [
            name
            for name in members
            if "libomp" in Path(name).name.lower() and name.endswith(".dylib")
        ]
        if not native_members:
            raise RuntimeError(f"{wheel.name} does not contain pytaplite._native")
        if not libomp_members:
            raise RuntimeError(f"{wheel.name} does not contain a bundled libomp dylib")

        with tempfile.TemporaryDirectory(prefix="taplite-wheel-") as directory:
            archive.extractall(directory)
            root = Path(directory)
            native_binaries = [root / name for name in native_members]
            libomp_binaries = [root / name for name in libomp_members]
            for binary in native_binaries + libomp_binaries:
                _verify_binary(binary, architecture, deployment_target)

            for native in native_binaries:
                _, dependencies = _dependencies(native)
                libomp_dependencies = [
                    dependency
                    for dependency in dependencies
                    if "libomp" in dependency.lower()
                ]
                if not libomp_dependencies:
                    raise RuntimeError(f"{native.name} is not linked to the bundled libomp")
                if not all(
                    dependency.startswith("@loader_path/")
                    for dependency in libomp_dependencies
                ):
                    raise RuntimeError(
                        f"{native.name} does not load libomp relative to the wheel: "
                        f"{libomp_dependencies}"
                    )

    print(
        f"verified {wheel.name}: native extension, bundled libomp, {architecture}, "
        f"macOS <= {deployment_target}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheels", nargs="+", type=Path)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--deployment-target", default="11.0")
    args = parser.parse_args()

    for wheel in args.wheels:
        verify_wheel(wheel, args.architecture, args.deployment_target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
