from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .file_utils import copy_files_parallel, resolved_workers
from .internal_config import RUN_GMNS_READINESS_CHECK
from .readiness_check import run_gmns_readiness_check as run_period_readiness_check
from .reproducible_run import (
    DEFAULT_KERNEL_SOURCE,
    VALID_KERNEL_SOURCES,
    parse_convergence,
    preflight,
    run_dtalite,
    stage_inputs,
    verify_outputs,
    write_run_card,
)
from .dtab import demand_binary_path, inspect_dtab
from .settings.dtalite_settings_config import SUPPORTED_MODE_TYPES, demand_file_name
from .settings.generate_dtalite_settings import (
    configure_time_period_hours,
    generate_dtalite_input_files,
    normalize_period_key,
)

logger = logging.getLogger(__name__)

LEGACY_ASSIGNMENT_KEYS = {
    "dta_exe_name",
    "inplace",
    "length",
    "memory_blocks",
    "metric_system",
    "modes",
    "period_scale_factors",
    "route",
    "scenario_output_dir",
    "settings_overrides",
    "simu",
    "speed",
}

INTERNAL_ASSIGNMENT_KEYS = {
    "run_gmns_readiness_check",
}


@dataclass
class AssignmentConfig:
    network_path: Path
    scenario_name: str | None = None
    ue_converge: float = 0.1
    dtalite_run_mode: str = "assignment"
    time_periods: list[str] = field(default_factory=lambda: ["am", "md", "pm", "nt"])
    period_times: list[str] = field(default_factory=lambda: ["0600_0900", "0900_1500", "1500_1900", "1900_0600"])
    output_files: list[str] = field(default_factory=lambda: [
        "log.txt",
        "summary_log.txt",
        "link_performance.csv",
    ])
    dtalite_assignment: bool = False
    network_conversion: bool = False
    demand_conversion: bool = False
    conversion_workers: int = 4
    conversion_reserve_cores: int = 1
    network_chunks: int = 0
    demand_chunks: int = 0
    conversion_adaptive: bool = True
    conversion_cache: bool = True
    conversion_cache_dir: Path | None = None
    demand_output_format: str = "csv"
    work_dir: Path | None = None
    output_dir: Path | None = None
    iterations: int = 10
    processors: int = 8
    route_output: int = 0
    vehicle_output: int = 0
    period_start: int = 7
    period_end: int = 8
    unit_system: str = "metric"
    vdf_type: str = "bpr"
    label: str | None = None
    kernel_source: str = DEFAULT_KERNEL_SOURCE
    inplace: bool = True
    dry_run: bool = False
    no_rename_columns: bool = False
    scenario_input_dir: Path | None = None
    demand_dir: Path | None = None
    write_legacy_outputs: bool = False
    run_gmns_readiness_check: bool = field(default=RUN_GMNS_READINESS_CHECK, init=False)

    @classmethod
    def from_dict(cls, data: dict) -> "AssignmentConfig":
        parsed = data.copy()
        if "iteration" in parsed and "iterations" not in parsed:
            logger.warning("Using legacy assignment config key 'iteration' as 'iterations'.")
            parsed["iterations"] = parsed["iteration"]
        parsed.pop("iteration", None)

        if "metric_system" in parsed and "unit_system" not in parsed:
            logger.warning("Using legacy assignment config key 'metric_system' as 'unit_system'.")
            parsed["unit_system"] = "imperial" if parsed["metric_system"] == 1 else "metric"

        if "period_titles" in parsed and "time_periods" not in parsed:
            logger.warning("Using legacy assignment config key 'period_titles' as 'time_periods'.")
            parsed["time_periods"] = parsed["period_titles"]
        elif "period_titles" in parsed:
            logger.warning("Ignoring legacy assignment config key: period_titles")
        parsed.pop("period_titles", None)

        for legacy_key in LEGACY_ASSIGNMENT_KEYS:
            if legacy_key in parsed:
                logger.warning("Ignoring legacy assignment config key: %s", legacy_key)
                parsed.pop(legacy_key, None)

        for internal_key in INTERNAL_ASSIGNMENT_KEYS:
            if internal_key in parsed:
                logger.warning(
                    "Ignoring internal assignment config key: %s; controlled by src/dtalite4cube/internal_config.py",
                    internal_key,
                )
                parsed.pop(internal_key, None)

        known_fields = {field.name for field in dataclass_fields(cls)}
        unknown_keys = sorted(set(parsed) - known_fields)
        if unknown_keys:
            logger.warning("Ignoring unknown assignment config key(s): %s", ", ".join(unknown_keys))
            for key in unknown_keys:
                parsed.pop(key, None)

        parsed["network_path"] = Path(parsed["network_path"])
        for path_key in (
            "work_dir",
            "output_dir",
            "scenario_input_dir",
            "demand_dir",
            "conversion_cache_dir",
        ):
            if parsed.get(path_key) is not None:
                parsed[path_key] = Path(parsed[path_key])
        return cls(**parsed)

    def validate(self) -> None:
        if not self.network_path.exists():
            raise FileNotFoundError(f"Scenario folder does not exist: {self.network_path}")

        # TODO(NVTA package): remove this temporary restriction only after route
        # storage and vehicle output are redesigned and validated at regional scale.
        if self.route_output != 0 or self.vehicle_output != 0:
            logger.warning(
                "Temporary NVTA safety restriction overrides route_output=%s and "
                "vehicle_output=%s to 0.",
                self.route_output,
                self.vehicle_output,
            )
        self.route_output = 0
        self.vehicle_output = 0

        if self.dtalite_run_mode not in {"assignment", "simulation"}:
            raise ValueError("dtalite_run_mode must be 'assignment' or 'simulation'.")

        if self.dtalite_run_mode == "simulation":
            raise NotImplementedError("dtalite_run_mode='simulation' is reserved but not implemented in this workflow.")

        if self.unit_system not in {"imperial", "metric"}:
            raise ValueError("unit_system must be either 'imperial' for mile/mph or 'metric' for km/kph.")

        if self.route_output not in {0, 1}:
            raise ValueError("route_output must be 0 or 1.")

        if self.vehicle_output not in {0, 1}:
            raise ValueError("vehicle_output must be 0 or 1.")

        if self.vdf_type not in {"bpr", "qvdf"}:
            raise ValueError("vdf_type must be either 'bpr' or 'qvdf'.")

        if self.conversion_workers < 0:
            raise ValueError("conversion_workers must be zero (auto) or positive.")

        if self.conversion_reserve_cores < 0:
            raise ValueError("conversion_reserve_cores must be nonnegative.")

        if self.network_chunks < 0 or self.demand_chunks < 0:
            raise ValueError("network_chunks and demand_chunks must be zero (auto) or positive.")

        self.demand_output_format = self.demand_output_format.strip().lower()
        if self.demand_output_format not in {"csv", "binary", "both"}:
            raise ValueError("demand_output_format must be one of: csv, binary, both.")

        self.kernel_source = (self.kernel_source or DEFAULT_KERNEL_SOURCE).strip().lower()
        if self.kernel_source not in VALID_KERNEL_SOURCES:
            raise ValueError("kernel_source must be one of: " + ", ".join(sorted(VALID_KERNEL_SOURCES)))

        if len(self.active_time_periods) != len(self.period_times):
            raise ValueError("time_periods and period_times must have the same length.")

        if not self.active_time_periods:
            raise ValueError("time_periods cannot be empty.")

    @property
    def active_time_periods(self) -> list[str]:
        return [normalize_period_key(period) for period in self.time_periods]

    @property
    def length_unit(self) -> str:
        return "mile" if self.unit_system == "imperial" else "km"

    @property
    def speed_unit(self) -> str:
        return "mph" if self.unit_system == "imperial" else "kph"

    @property
    def metric_system(self) -> int:
        return 1 if self.unit_system == "imperial" else 0


def run_network_conversion(config: AssignmentConfig) -> dict:
    from .cube2gmns import get_gmns_from_cube

    scenario_output_dir = resolve_scenario_output_dir(config)
    logger.info("Running network conversion into period folders under %s", scenario_output_dir)
    result = get_gmns_from_cube(
        str(config.network_path),
        config.active_time_periods,
        length_unit=config.length_unit,
        speed_unit=config.speed_unit,
        district_id_assignment=True,
        capacity_adjustment=False,
        vdf_type=config.vdf_type,
        output_dir=str(scenario_output_dir),
        period_folder_output=True,
        conversion_workers=config.conversion_workers,
        reserve_cores=config.conversion_reserve_cores,
        chunks_per_period=config.network_chunks,
        adaptive=config.conversion_adaptive,
        conversion_cache=config.conversion_cache,
        cache_dir=config.conversion_cache_dir,
    )
    logger.info(
        "Network conversion finished in %.3fs with %s worker(s)",
        result["elapsed_sec"],
        result["worker_plan"]["workers"],
    )
    return result


def run_demand_conversion(config: AssignmentConfig) -> dict:
    from .omx2csv import get_gmns_demand_from_omx

    scenario_output_dir = resolve_scenario_output_dir(config)
    demand_dir = config.demand_dir or config.network_path
    logger.info("Running demand conversion into period folders under %s", scenario_output_dir)
    result = get_gmns_demand_from_omx(
        str(demand_dir),
        config.active_time_periods,
        output_base_dir=scenario_output_dir,
        period_folder_output=True,
        conversion_workers=config.conversion_workers,
        reserve_cores=config.conversion_reserve_cores,
        chunks_per_mode=config.demand_chunks,
        adaptive=config.conversion_adaptive,
        output_format=config.demand_output_format,
    )
    logger.info(
        "Demand conversion finished in %.3fs with %s worker(s)",
        result["elapsed_sec"],
        result["worker_plan"]["workers"],
    )
    return result


def resolve_scenario_input_dir(config: AssignmentConfig) -> Path:
    return config.scenario_input_dir or config.network_path


def resolve_scenario_output_dir(config: AssignmentConfig) -> Path:
    configured = config.output_dir
    if configured is not None:
        return configured if configured.is_absolute() else config.network_path / configured
    return config.network_path


def resolve_run_folder(config: AssignmentConfig, time_period: str | None = None) -> Path:
    configured_path = config.work_dir
    if configured_path is not None:
        base = configured_path if configured_path.is_absolute() else config.network_path / configured_path
    else:
        base = config.network_path / "dtalite_runs" / "latest"

    if time_period is not None:
        return base / time_period
    return base


def prepare_dtalite_period_folders(
    scenario_input_dir: Path,
    scenario_output_dir: Path,
    time_periods: list[str],
    *,
    demand_dir: Path | None = None,
    settings_overrides: dict | None = None,
    copy_workers: int = 1,
) -> dict[str, Path]:
    scenario_input_dir = Path(scenario_input_dir)
    scenario_output_dir = Path(scenario_output_dir)
    demand_source_dir = Path(demand_dir) if demand_dir is not None else scenario_input_dir
    binary_demand = bool((settings_overrides or {}).get("demand_format", 0))

    prepared_folders: dict[str, Path] = {}
    for raw_period in time_periods:
        period_key = normalize_period_key(raw_period)
        period_folder = scenario_output_dir / period_key
        period_folder.mkdir(parents=True, exist_ok=True)
        copy_pairs: list[tuple[Path, Path]] = []
        period_binary_paths: list[Path] = []

        period_node = period_folder / "node.csv"
        if not period_node.is_file():
            node_source = scenario_input_dir / "node.csv"
            if not node_source.is_file():
                raise FileNotFoundError(
                    f"Missing node.csv for {period_key}. Expected {period_node} "
                    f"or legacy source {node_source}"
                )
            copy_pairs.append((node_source, period_node))

        period_link = period_folder / "link.csv"
        if not period_link.is_file():
            link_source = scenario_input_dir / f"link_{period_key}.csv"
            direct_link_source = scenario_input_dir / period_key / "link.csv"
            if direct_link_source.is_file():
                link_source = direct_link_source
            elif not link_source.is_file():
                raise FileNotFoundError(
                    f"Missing period link file for {period_key}. Expected {period_link}, "
                    f"{direct_link_source}, or legacy source {link_source}"
                )
            copy_pairs.append((link_source, period_link))

        for mode in SUPPORTED_MODE_TYPES:
            demand_name = demand_file_name(mode, period_key)
            period_demand = period_folder / demand_name
            if binary_demand:
                period_binary = demand_binary_path(period_demand)
                if not period_binary.is_file():
                    direct_binary_source = demand_binary_path(
                        demand_source_dir / period_key / demand_name
                    )
                    root_binary_source = demand_binary_path(demand_source_dir / demand_name)
                    if direct_binary_source.is_file():
                        binary_source = direct_binary_source
                    elif root_binary_source.is_file():
                        binary_source = root_binary_source
                    else:
                        raise FileNotFoundError(
                            f"Missing binary demand for {period_key}: expected {period_binary}, "
                            f"{direct_binary_source}, or {root_binary_source}"
                        )
                    copy_pairs.append((binary_source, period_binary))
                period_binary_paths.append(period_binary)
            elif not period_demand.is_file():
                demand_source = demand_source_dir / demand_name
                direct_demand_source = demand_source_dir / period_key / demand_name
                if direct_demand_source.is_file():
                    demand_source = direct_demand_source
                elif not demand_source.is_file():
                    raise FileNotFoundError(
                        f"Missing demand file for {period_key}: expected {period_demand}, "
                        f"{direct_demand_source}, or legacy source {demand_source}"
                    )
                copy_pairs.append((demand_source, period_demand))

        copied = copy_files_parallel(
            copy_pairs,
            workers=copy_workers,
            preserve_metadata=True,
        )
        for source, target in copied:
            logger.info("Copied %s -> %s", source, target)
        if copied:
            logger.info(
                "Prepared %s period input copies with %s worker(s)",
                len(copied),
                resolved_workers(copy_workers, len(copy_pairs)),
            )
        for period_binary in period_binary_paths:
            inspect_dtab(period_binary)

        generate_dtalite_input_files(period_folder, period_key, overrides=settings_overrides)
        _validate_period_folder(period_folder)
        prepared_folders[period_key] = period_folder
        logger.info("Prepared DTALite period folder for %s: %s", period_key, period_folder)

    return prepared_folders


def remove_root_period_duplicates(scenario_output_dir: Path, time_periods: list[str]) -> list[Path]:
    scenario_output_dir = Path(scenario_output_dir)
    removed: list[Path] = []

    for file_name in ("link.csv", "demand.csv", "settings.csv", "mode_type.csv"):
        path = scenario_output_dir / file_name
        if path.is_file():
            path.unlink()
            removed.append(path)
    root_demand_binary = scenario_output_dir / "demand.bin"
    if root_demand_binary.is_file():
        root_demand_binary.unlink()
        removed.append(root_demand_binary)

    node_path = scenario_output_dir / "node.csv"
    if node_path.is_file() and all((scenario_output_dir / period / "node.csv").is_file() for period in time_periods):
        node_path.unlink()
        removed.append(node_path)

    for period in time_periods:
        period_folder = scenario_output_dir / period
        period_file_pairs = {
            f"link_{period}.csv": period_folder / "link.csv",
            f"settings_{period}.csv": period_folder / "settings.csv",
            f"mode_type_{period}.csv": period_folder / "mode_type.csv",
            f"demand_{period}.csv": period_folder / "demand.csv",
        }
        for mode in SUPPORTED_MODE_TYPES:
            demand_name = demand_file_name(mode, period)
            period_file_pairs[demand_name] = period_folder / demand_name
            period_file_pairs[demand_binary_path(demand_name).name] = demand_binary_path(
                period_folder / demand_name
            )

        for root_name, period_path in period_file_pairs.items():
            root_path = scenario_output_dir / root_name
            if root_path.is_file() and period_path.is_file():
                root_path.unlink()
                removed.append(root_path)

    for path in removed:
        logger.info("Removed root-level generated duplicate: %s", path)

    return removed


def _validate_period_folder(period_folder: Path) -> None:
    for required_file in ("node.csv", "link.csv", "settings.csv", "mode_type.csv"):
        path = period_folder / required_file
        if not path.is_file():
            raise FileNotFoundError(f"Prepared period folder is missing {required_file}: {period_folder}")

    with (period_folder / "settings.csv").open("r", newline="", encoding="utf-8") as f:
        settings_rows = list(csv.DictReader(f))
        if len(settings_rows) != 1:
            raise ValueError(f"settings.csv must have exactly 2 lines: {period_folder / 'settings.csv'}")
    binary_demand = int(float(settings_rows[0].get("demand_format") or 0)) == 1

    with (period_folder / "mode_type.csv").open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 6:
        raise ValueError(f"mode_type.csv must have exactly 6 mode rows: {period_folder / 'mode_type.csv'}")

    missing = []
    for row in rows:
        demand_path = period_folder / row["demand_file"]
        if binary_demand:
            binary_path = demand_binary_path(demand_path)
            if binary_path.is_file():
                inspect_dtab(binary_path)
                continue
        elif demand_path.is_file():
            continue
        missing.append(row["demand_file"])
    if missing:
        raise FileNotFoundError(
            f"mode_type.csv in {period_folder} references missing demand file(s): {', '.join(missing)}"
        )


def copy_route_assignment_to_columns(work_dir: Path) -> None:
    route_assignment = work_dir / "route_assignment.csv"
    columns = work_dir / "columns.csv"
    shutil.copy2(route_assignment, columns)
    logger.info("Copied %s to %s", route_assignment.name, columns.name)


def run_reproducible_dtalite(
    *,
    config: AssignmentConfig,
    source_network_path: Path,
    work_dir: Path,
    label: str,
    time_period: str | None = None,
) -> Path:
    logger.info("Starting reproducible DTALite run: source=%s work_dir=%s", source_network_path, work_dir)
    preflight_info = preflight(source_network_path)

    if config.dry_run:
        logger.info("DTALite dry_run=True; preflight passed and execution is skipped.")
        return work_dir

    stage_inputs(
        source_network_path,
        source_network_path if config.inplace else work_dir,
        iterations=config.iterations,
        processors=config.processors,
        route_output=config.route_output,
        vehicle_output=config.vehicle_output,
        period_start=config.period_start,
        period_end=config.period_end,
        metric_system=config.metric_system,
        copy_workers=config.conversion_workers,
    )
    run_folder = source_network_path if config.inplace else work_dir
    elapsed, log = run_dtalite(run_folder, kernel_source=config.kernel_source)
    verify_info = verify_outputs(run_folder, route_output=config.route_output)
    convergence = parse_convergence(log, run_folder)

    if config.route_output and not config.no_rename_columns:
        copy_route_assignment_to_columns(run_folder)

    args_used = {
        "iterations": config.iterations,
        "processors": config.processors,
        "route_output": config.route_output,
        "vehicle_output": config.vehicle_output,
        "period_start": config.period_start,
        "period_end": config.period_end,
        "unit_system": config.unit_system,
    }
    write_run_card(
        run_folder,
        source_network_path,
        label,
        preflight_info,
        elapsed,
        convergence,
        verify_info,
        args_used,
    )

    if time_period is not None and config.write_legacy_outputs:
        output_files = [
            *config.output_files,
            "od_performance.csv",
            "dtalite_run.log",
            "summary_log_file.txt",
            "RUN_CARD.md",
        ]
        if config.route_output:
            output_files.extend(["route_assignment.csv", "columns.csv"])

        save_period_outputs(
            network_path=config.network_path,
            source_dir=run_folder,
            time_period=time_period,
            output_files=output_files,
            extra_files=[],
            copy_workers=config.conversion_workers,
        )

    return run_folder


def save_period_outputs(
    *,
    network_path: Path,
    source_dir: Path,
    time_period: str,
    output_files: Iterable[str],
    extra_files: Iterable[str],
    copy_workers: int = 1,
) -> None:
    output_dir = network_path / "Outputs" / "DTALite"
    output_dir.mkdir(parents=True, exist_ok=True)

    period_suffix = f"_{time_period}"

    copy_pairs: list[tuple[Path, Path]] = []
    for file_name in output_files:
        source_path = source_dir / file_name
        if not source_path.exists():
            logger.warning("Expected output file not found: %s", source_path)
            continue

        new_name = f"{source_path.stem}{period_suffix}{source_path.suffix}"
        target_path = output_dir / new_name
        copy_pairs.append((source_path, target_path))

    for file_name in extra_files:
        source_path = network_path / file_name
        if not source_path.exists():
            logger.warning("Extra file not found: %s", source_path)
            continue

        target_path = output_dir / source_path.name
        copy_pairs.append((source_path, target_path))

    copied = copy_files_parallel(
        copy_pairs,
        workers=copy_workers,
        preserve_metadata=False,
    )
    for _, target_path in copied:
        logger.info("Saved %s", target_path)
    if copied:
        logger.info(
            "Saved %s output files with %s copy worker(s)",
            len(copied),
            resolved_workers(copy_workers, len(copy_pairs)),
        )


def run_assignment_pipeline(config: AssignmentConfig) -> bool:
    config.validate()
    configure_time_period_hours(config.active_time_periods, config.period_times)
    scenario_input_dir = resolve_scenario_input_dir(config)
    scenario_output_dir = resolve_scenario_output_dir(config)
    # logger.info("Running assignment pipeline for: %s", config.network_path)
    logger.info(
        "Running assignment pipeline for scenario=%s path=%s",
        config.scenario_name or "<unnamed>",
        config.network_path,
    )
    conversion_profile = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenario": config.scenario_name or config.network_path.name,
        "periods": config.active_time_periods,
        "conversion_workers": config.conversion_workers,
        "conversion_reserve_cores": config.conversion_reserve_cores,
        "network_chunks": config.network_chunks,
        "demand_chunks": config.demand_chunks,
        "demand_output_format": config.demand_output_format,
        "conversion_adaptive": config.conversion_adaptive,
        "conversion_cache": config.conversion_cache,
        "conversion_cache_dir": (
            str(config.conversion_cache_dir)
            if config.conversion_cache_dir is not None
            else None
        ),
        "stages": {},
    }

    if config.network_conversion:
        conversion_profile["stages"]["network"] = run_network_conversion(config)

    if config.demand_conversion:
        conversion_profile["stages"]["demand"] = run_demand_conversion(config)

    if conversion_profile["stages"]:
        scenario_output_dir.mkdir(parents=True, exist_ok=True)
        profile_path = scenario_output_dir / "CONVERSION_PROFILE.json"
        profile_path.write_text(json.dumps(conversion_profile, indent=2) + "\n", encoding="utf-8")
        logger.info("Conversion profile written: %s", profile_path)

    if not config.dtalite_assignment and not (
        config.network_conversion and config.demand_conversion
    ):
        logger.info(
            "Partial conversion complete; skipping DTALite period preparation because "
            "assignment is disabled."
        )
        return False

    prepared_period_folders = prepare_dtalite_period_folders(
        scenario_input_dir=scenario_input_dir,
        scenario_output_dir=scenario_output_dir,
        time_periods=config.active_time_periods,
        demand_dir=config.demand_dir,
        settings_overrides={
            "number_of_iterations": config.iterations,
            "number_of_processors": config.processors,
            "route_output": config.route_output,
            "vehicle_output": config.vehicle_output,
            "demand_format": 1 if config.demand_output_format in {"binary", "both"} else 0,
        },
        copy_workers=config.conversion_workers,
    )
    remove_root_period_duplicates(scenario_output_dir, config.active_time_periods)
    logger.info("conversion complete")

    if config.run_gmns_readiness_check:
        for period_source in prepared_period_folders.values():
            run_period_readiness_check(period_source)
        logger.info("readiness check complete")

    if not config.dtalite_assignment:
        logger.info("DTALite assignment is disabled for: %s", config.network_path)
        return False

    for time_period, period_source in prepared_period_folders.items():
        period_label = f"{config.label or config.scenario_name or 'scenario'}_{time_period}"
        run_reproducible_dtalite(
            config=config,
            source_network_path=period_source,
            work_dir=resolve_run_folder(config, time_period=time_period),
            label=period_label,
            time_period=time_period,
        )

    from src.dtalite_postprocessing.runner import run_assignment_summary_outputs

    summary_manifest = run_assignment_summary_outputs(
        scenario_output_dir=scenario_output_dir,
        time_periods=config.active_time_periods,
        period_range_list=config.period_times,
    )
    logger.info(
        "Post-assignment aggregation and summary statistics complete: %s",
        summary_manifest["summary_root"],
    )
    logger.info("Finished DTALite assignment pipeline for: %s", config.network_path)
    return True


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run DTALite4Cube assignment pipeline for a scenario."
    )

    parser.add_argument("--network-path", required=True, help="Scenario folder path")
    parser.add_argument("--dtalite-run-mode", choices=["assignment", "simulation"], default="assignment")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--scenario-input-dir", type=Path)
    parser.add_argument("--demand-dir", type=Path)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--processors", type=int, default=8)
    parser.add_argument("--route-output", type=int, choices=[0, 1], default=0)
    parser.add_argument("--vehicle-output", type=int, choices=[0, 1], default=0)
    parser.add_argument("--period-start", type=int, default=7)
    parser.add_argument("--period-end", type=int, default=8)
    parser.add_argument("--unit-system", choices=["imperial", "metric"], default="metric")
    parser.add_argument("--metric-system", type=int, choices=[0, 1], help="Legacy alias: 1=imperial, 0=metric.")
    parser.add_argument("--vdf-type", choices=["bpr", "qvdf"], default="bpr")
    parser.add_argument("--label")
    parser.add_argument("--kernel-source", choices=sorted(VALID_KERNEL_SOURCES), default=DEFAULT_KERNEL_SOURCE)

    parser.add_argument("--network-conversion", action="store_true")
    parser.add_argument("--demand-conversion", action="store_true")
    parser.add_argument("--dtalite-assignment", action="store_true")
    parser.add_argument("--conversion-workers", type=int, default=4)
    parser.add_argument("--conversion-reserve-cores", type=int, default=1)
    parser.add_argument("--network-chunks", type=int, default=0)
    parser.add_argument("--demand-chunks", type=int, default=0)
    parser.add_argument("--demand-output-format", choices=["csv", "binary", "both"], default="csv")
    parser.add_argument("--conversion-adaptive", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--conversion-cache", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--conversion-cache-dir", type=Path)
    parser.add_argument("--isolated-work-dir", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-rename-columns", action="store_true")
    parser.add_argument("--time-periods", nargs="+", default=["am", "md", "pm", "nt"])
    parser.add_argument(
        "--period-times",
        nargs="+",
        default=["0600_0900", "0900_1500", "1500_1900", "1900_0600"],
    )

    return parser


def main() -> None:
    install_root_log_capture("dtalite4cube_runner")
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    parser = build_arg_parser()
    args = parser.parse_args()

    config = AssignmentConfig(
        network_path=Path(args.network_path),
        dtalite_run_mode=args.dtalite_run_mode,
        time_periods=args.time_periods,
        period_times=args.period_times,
        dtalite_assignment=args.dtalite_assignment,
        network_conversion=args.network_conversion,
        demand_conversion=args.demand_conversion,
        conversion_workers=args.conversion_workers,
        conversion_reserve_cores=args.conversion_reserve_cores,
        network_chunks=args.network_chunks,
        demand_chunks=args.demand_chunks,
        demand_output_format=args.demand_output_format,
        conversion_adaptive=args.conversion_adaptive,
        conversion_cache=args.conversion_cache,
        conversion_cache_dir=args.conversion_cache_dir,
        work_dir=args.work_dir,
        output_dir=args.output_dir,
        scenario_input_dir=args.scenario_input_dir,
        demand_dir=args.demand_dir,
        iterations=args.iterations,
        processors=args.processors,
        route_output=args.route_output,
        vehicle_output=args.vehicle_output,
        period_start=args.period_start,
        period_end=args.period_end,
        unit_system=args.unit_system if args.metric_system is None else ("imperial" if args.metric_system == 1 else "metric"),
        vdf_type=args.vdf_type,
        label=args.label,
        kernel_source=args.kernel_source,
        inplace=not args.isolated_work_dir,
        dry_run=args.dry_run,
        no_rename_columns=args.no_rename_columns,
    )

    run_assignment_pipeline(config)


if __name__ == "__main__":
    main()
