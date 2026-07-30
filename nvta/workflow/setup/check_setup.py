from __future__ import annotations

import importlib
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path


DEFAULT_CONFIG = Path("configs/project_assignment.json")

REQUIRED_PACKAGES = [
    "taplite4mpo",
    "pytaplite",
    "dtalite_qa",
    "pandas",
    "numpy",
    "openmatrix",
    "tqdm",
    "geopandas",
    "shapely",
]


def selected_config_path() -> Path:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return Path(sys.argv[1])
    return DEFAULT_CONFIG


def read_config(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def scenario_dirs_from_config(config: dict) -> tuple[Path, list[Path]]:
    scenario_base_dir = Path(config.get("scenario_base_dir", "scenarios"))

    raw_paths = config.get("scenario_paths")
    if raw_paths:
        scenario_dirs = [
            path if (path := Path(raw_path)).is_absolute() else scenario_base_dir / path
            for raw_path in raw_paths
        ]
        return scenario_base_dir, scenario_dirs

    scenario_names = config.get("scenario_names", [])
    scenario_dirs = [scenario_base_dir / name for name in scenario_names]
    return scenario_base_dir, scenario_dirs


def kernel_source_from_config(config: dict) -> str:
    assignment = config.get("assignment", {})
    return str(assignment.get("kernel_source", "wheel")).strip().lower() or "wheel"


def bundled_wheels() -> list[Path]:
    wheel_dir = Path(__file__).resolve().parents[2] / "wheels"
    return sorted(wheel_dir.glob("taplite4mpo-*.whl"))


def wheel_version(wheel_path: Path) -> str:
    prefix = "taplite4mpo-"
    remainder = wheel_path.name[len(prefix):]
    return remainder.split("-cp", 1)[0]


def check_wheel_kernel_loads(expected_version: str) -> tuple[bool, str]:
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            taplite4mpo = importlib.import_module("taplite4mpo")
            pytaplite = importlib.import_module("pytaplite")
            native = importlib.import_module("pytaplite._native")
        if not callable(getattr(pytaplite, "assign", None)):
            return False, "pytaplite.assign is not available"
        version = getattr(taplite4mpo, "__version__", "(unknown)")
        if version != expected_version:
            return False, (
                f"installed taplite4mpo version {version} does not match "
                f"the bundled wheel version {expected_version}"
            )
        status = native.openmp_status(2)
        if not status.get("compiled"):
            return False, "the wheel's pytaplite native extension does not have OpenMP enabled"
        expected_team_size = min(2, int(status.get("num_procs", 1)))
        if int(status.get("probe_team_size", 0)) < expected_team_size:
            return False, f"OpenMP worker probe failed: {status}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, (
        f"taplite4mpo {version}, pytaplite.assign, and the OpenMP native "
        f"extension loaded from {native.__file__}"
    )


def main() -> int:
    print("=" * 60)
    print("DTALite Pipeline Setup Check")
    print("=" * 60)

    failed = False
    config_path = selected_config_path()
    explicit_config = len(sys.argv) > 1 and sys.argv[1].strip()

    print(f"\nSelected config: {config_path}")

    print("\nChecking required project files/folders:")
    required_paths = [
        Path("run_assignment.py"),
        Path("run_postprocessing.py"),
        Path("src"),
        Path("setup"),
        Path("setup/environment.yml"),
    ]

    for path in required_paths:
        if path.exists():
            print(f"[OK] {path}")
        else:
            print(f"[MISSING] {path}")
            failed = True

    config = {}
    scenario_base_dir = Path("scenarios")
    scenario_dirs: list[Path] = []
    if config_path.exists():
        try:
            config = read_config(config_path)
            scenario_base_dir, scenario_dirs = scenario_dirs_from_config(config)
        except Exception as exc:
            print(f"[ERROR] Could not read selected config: {exc}")
            failed = True
    elif explicit_config:
        print(f"[MISSING] Selected config does not exist: {config_path}")
        failed = True
    else:
        print(f"[SKIP] Default config not found; scenario checks will be skipped: {config_path}")

    print(f"\nScenario base directory: {scenario_base_dir}")
    print(f"Scenario folders checked: {len(scenario_dirs)}")

    kernel_source = kernel_source_from_config(config)
    print("\nChecking Python packages:")
    for pkg in REQUIRED_PACKAGES:
        try:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                importlib.import_module(pkg)
            print(f"[OK] {pkg}")
        except ImportError:
            print(f"[MISSING] {pkg}")
            failed = True

    print("\nChecking scenario folders:")
    if not scenario_dirs:
        if config_path.exists() or explicit_config:
            print("[MISSING] No scenario folders listed in selected config.")
            failed = True
        else:
            print("[SKIP] No config was provided.")
    for scenario_dir in scenario_dirs:
        if scenario_dir.exists():
            print(f"[OK] {scenario_dir}")
        else:
            print(f"[MISSING] {scenario_dir}")
            failed = True

    print("\nChecking DTALite kernel source:")
    if kernel_source == "wheel":
        wheel_paths = bundled_wheels()
        if len(wheel_paths) == 1:
            wheel_path = wheel_paths[0]
            print(f"[OK] Bundled engine wheel: {wheel_path}")
            wheel_ok, wheel_message = check_wheel_kernel_loads(
                wheel_version(wheel_path)
            )
            if wheel_ok:
                print(f"[OK] {wheel_message}")
            else:
                print(f"[ERROR] Wheel kernel could not load: {wheel_message}")
                failed = True
        else:
            print(
                "[ERROR] Expected exactly one bundled taplite4mpo wheel under "
                f"{Path(__file__).resolve().parents[2] / 'wheels'}; "
                f"found {len(wheel_paths)}"
            )
            failed = True
    else:
        print(f"[ERROR] Unknown kernel_source: {kernel_source}")
        failed = True

    print("\nExternal DTALite executable is not used.")
    print(f"Current workflow uses kernel_source={kernel_source}.")

    print("\n" + "=" * 60)
    if failed:
        print("Setup check completed with issues.")
        print("Please review the messages above.")
        return 1

    print("Setup check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
