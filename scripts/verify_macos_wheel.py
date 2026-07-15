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
NATIVE_EXTENSION_PATTERN = re.compile(r"^pytaplite/_native[^/]*\.so$")
MACOS_PLATFORM_PATTERN = re.compile(
    r"^macosx_(?P<major>\d+)_(?P<minor>\d+)_(?P<architecture>arm64|x86_64)$"
)


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


def _minimum_macos_version(mach_o_commands: str) -> str | None:
    load_command = ""
    for line in mach_o_commands.splitlines():
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
    parts = [int(part) for part in re.findall(r"\d+", version)]
    return tuple((parts + [0, 0, 0])[:3])


def _normalize_wheel_member(member: str) -> str:
    normalized = member.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _native_extension_members(members: list[str]) -> list[str]:
    native_members = []
    misplaced_members = []
    for member in members:
        normalized = _normalize_wheel_member(member)
        filename = normalized.rsplit("/", 1)[-1]
        if not (filename.startswith("_native") and filename.endswith(".so")):
            continue
        if NATIVE_EXTENSION_PATTERN.fullmatch(normalized):
            native_members.append(member)
        else:
            misplaced_members.append(normalized)

    if misplaced_members:
        raise RuntimeError(
            "native extension is outside pytaplite/: "
            + ", ".join(sorted(misplaced_members))
        )
    return native_members


def _macos_platform_tag(wheel: Path) -> tuple[str, str, str]:
    if wheel.suffix != ".whl":
        raise RuntimeError(f"{wheel.name} is not a wheel filename")
    filename_parts = wheel.stem.rsplit("-", 3)
    if len(filename_parts) != 4:
        raise RuntimeError(f"Could not parse the platform tag from {wheel.name}")

    platform_tag = filename_parts[-1]
    if "." in platform_tag:
        raise RuntimeError(
            f"{wheel.name} has an ambiguous multi-platform tag: {platform_tag}"
        )
    match = MACOS_PLATFORM_PATTERN.fullmatch(platform_tag)
    if match is None:
        raise RuntimeError(
            f"{wheel.name} has an unsupported macOS platform tag: {platform_tag}"
        )
    version = f"{match.group('major')}.{match.group('minor')}"
    return platform_tag, version, match.group("architecture")


def _runtime_search_paths(mach_o_commands: str) -> list[str]:
    load_command = ""
    paths = []
    for line in mach_o_commands.splitlines():
        stripped = line.strip()
        if stripped.startswith("cmd LC_"):
            load_command = stripped.removeprefix("cmd ")
        elif load_command == "LC_RPATH" and stripped.startswith("path "):
            path = stripped.removeprefix("path ").rsplit(" (offset ", 1)[0]
            paths.append(path)
    return paths


def _verify_runtime_search_paths(binary: Path, paths: list[str]) -> None:
    for path in paths:
        if path.startswith("/") and not _is_allowed_absolute_path(path):
            raise RuntimeError(
                f"{binary.name} has non-portable absolute LC_RPATH {path}"
            )


def _is_allowed_absolute_path(path: str) -> bool:
    return any(
        path == prefix.rstrip("/") or path.startswith(prefix)
        for prefix in ALLOWED_ABSOLUTE_PREFIXES
    )


def _verify_binary(
    binary: Path,
    architecture: str,
    deployment_target: str,
    wheel_target: str,
) -> None:
    linked_libraries, dependencies = _dependencies(binary)
    mach_o_commands = _run("otool", "-l", str(binary))
    for prefix in BUILD_MACHINE_PREFIXES:
        if prefix in linked_libraries or prefix in mach_o_commands:
            raise RuntimeError(f"{binary.name} retains build-machine path {prefix}")

    _verify_runtime_search_paths(binary, _runtime_search_paths(mach_o_commands))

    install_id = _install_id(binary)
    for dependency in dependencies:
        if dependency == install_id:
            continue
        if dependency.startswith("/") and not _is_allowed_absolute_path(dependency):
            raise RuntimeError(
                f"{binary.name} has non-portable absolute dependency {dependency}"
            )

    architectures = _run("lipo", "-archs", str(binary)).split()
    if architecture not in architectures:
        raise RuntimeError(
            f"{binary.name} has architectures {architectures}, expected {architecture}"
        )

    minimum = _minimum_macos_version(mach_o_commands)
    if minimum is None:
        raise RuntimeError(f"Could not determine the macOS minimum version for {binary.name}")
    if _version_tuple(minimum) > _version_tuple(deployment_target):
        raise RuntimeError(
            f"{binary.name} requires macOS {minimum}, but the wheel targets "
            f"macOS {deployment_target}"
        )
    if _version_tuple(minimum) > _version_tuple(wheel_target):
        raise RuntimeError(
            f"{binary.name} requires macOS {minimum}, but the wheel platform tag "
            f"declares macOS {wheel_target}"
        )


def verify_wheel(
    wheel: Path,
    architecture: str,
    deployment_target: str,
) -> None:
    platform_tag, wheel_target, wheel_architecture = _macos_platform_tag(wheel)
    if wheel_architecture != architecture:
        raise RuntimeError(
            f"{wheel.name} declares architecture {wheel_architecture}, expected {architecture}"
        )
    if _version_tuple(wheel_target) > _version_tuple(deployment_target):
        raise RuntimeError(
            f"{wheel.name} declares macOS {wheel_target}, newer than the configured "
            f"deployment target {deployment_target}"
        )

    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
        native_members = _native_extension_members(members)
        libomp_members = [
            name
            for name in members
            if "libomp" in Path(_normalize_wheel_member(name)).name.lower()
            and _normalize_wheel_member(name).endswith(".dylib")
        ]
        binary_members = [
            name
            for name in members
            if _normalize_wheel_member(name).endswith((".so", ".dylib"))
        ]
        if not native_members:
            raise RuntimeError(f"{wheel.name} does not contain pytaplite._native")
        if not libomp_members:
            raise RuntimeError(f"{wheel.name} does not contain a bundled libomp dylib")

        with tempfile.TemporaryDirectory(prefix="taplite-wheel-") as directory:
            archive.extractall(directory)
            root = Path(directory)
            native_binaries = [root / name for name in native_members]
            for binary in (root / name for name in binary_members):
                _verify_binary(
                    binary,
                    architecture,
                    deployment_target,
                    wheel_target,
                )

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
        f"{platform_tag}, macOS <= {deployment_target}"
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
