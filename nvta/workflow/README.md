# NVTA DTALite Workflow

This folder converts Cube network and demand inputs, runs TAPLite/DTALite, and
postprocesses the period results.

This packaged `workflow` copy is isolated from the production workflow. It adds
bounded process-based parallelism, a fingerprinted prepared-network cache, and
optional native DTAB binary demand files. The native kernel maps external node,
zone, and link IDs to compact in-memory indices during assignment, so prepared
period inputs and assignment outputs retain their original IDs.

During network conversion, the workflow also maps period-specific observed
congestion boundaries by directed `(from_node_id, to_node_id)` pair. AM, MD,
and PM `link.csv` files receive `t0_hour`, `t2_hour`, and `t3_hour` from the
bundled lookup tables. Unmatched pairs—and periods without a lookup table such
as NT—retain the same columns with blank values, which invokes the kernel's
analytical fallback.

Parallel-package conversion defaults are four workers, prepared-network cache
enabled, and CSV demand output. The bundled Python 3.11 Windows wheel is the
default engine.

The same bounded `--conversion-workers` limit also accelerates conversion and
assignment preparation without changing file formats or IDs:

- independent input and output files are copied with a bounded thread pool;
- network and demand conversion work is split into deterministic bounded
  chunks; and
- preflight streams CSV and DTAB demand records to verify that their original
  zone IDs exist before the kernel starts.

Serial and parallel conversion results are regression-tested for byte parity.
The workflow does not create an `_internal` assignment folder, `id_mapping.csv`,
renumbered inputs, or back-mapped output copies.

> **Temporary NVTA restriction:** route and vehicle outputs are always forced
> to `0`, even when a command or configuration requests `1`. A TODO is retained
> in the workflow code so this restriction can be revisited after regional-scale
> storage and output behavior are redesigned and validated.

> **Use the packaged Python 3.11 environment.** The engine is a CPython 3.11
> Windows x64 native extension and will not load under another Python ABI.

## Quick navigation

1. [Use the bundled engine wheel](#1-use-the-bundled-engine-wheel)
2. [Run assignment: simple](#2-run-assignment-simple)
3. [Run assignment: all options](#3-run-assignment-all-options)
4. [Run postprocessing](#4-run-postprocessing)
5. [Assignment option values](#5-assignment-option-values)
6. [Postprocessing option values](#6-postprocessing-option-values)
7. [Expected scenario layout](#7-expected-scenario-layout)

---

## 1. Use the bundled engine wheel

Run all commands from this `workflow` folder.

### Setup once

```powershell
.\setup_environment.bat
conda activate dtalite_pipeline
```

The setup creates a Python 3.11 environment and installs the bundled engine:

```text
../wheels/taplite4mpo-0.4.0rc2-cp311-cp311-win_amd64.whl
```

The wheel contains `taplite4mpo`, `pytaplite`, `dtalite_qa`, and the compiled
`pytaplite._native` OpenMP kernel. As in the earlier workflow, each period runs
`pytaplite.assign(...)` in a fresh Python child process. This keeps kernel state
isolated without a standalone DLL or DTALite executable. The only supported
kernel source is:

```text
--kernel-source wheel
```

`setup_environment.bat` requires exactly one `taplite4mpo-*.whl` under
`../wheels`, reinstalls that local wheel without contacting PyPI, and verifies
its version, `pytaplite.assign`, compiled extension, and OpenMP runtime.

---

## 2. Run assignment: simple

### Shortest command

This uses the bundled wheel and all default values:

```powershell
python run_assignment.py "C:\path\to\scenario"
```

### Recommended command with important options

```powershell
python run_assignment.py "C:\path\to\scenario" `
  --kernel-source wheel `
  --iterations 20 `
  --processors 8 `
  --time-periods am md pm nt `
  --period-times 0600_0900 0900_1500 1500_1900 1900_0600
```

### Run already-prepared period folders

Use this when `am`, `md`, `pm`, and `nt` already contain `node.csv`,
`link.csv`, and demand CSV or DTAB files:

```powershell
python run_assignment.py "C:\path\to\prepared_scenario" `
  --kernel-source wheel `
  --network-conversion false `
  --demand-conversion false `
  --iterations 20 `
  --processors 8
```

### Convert inputs without running assignment

```powershell
python run_assignment.py "C:\path\to\scenario" `
  --network-conversion true `
  --demand-conversion true `
  --dtalite-assignment false
```

For the fastest kernel input path, add:

```text
--demand-output-format binary
```

Use `both` when CSV demand exports are also needed. The default remains `csv`
for compatibility.

### Validate and stage inputs without starting the kernel

Add the flag below to an assignment command:

```text
--dry-run
```

---

## 3. Run assignment: all options

This example shows every value-taking assignment option:

```powershell
python run_assignment.py "C:\path\to\scenario" `
  --kernel-source wheel `
  --iterations 20 `
  --processors 8 `
  --route-output 0 `
  --vehicle-output 0 `
  --unit-system imperial `
  --vdf-type bpr `
  --dtalite-run-mode assignment `
  --network-conversion true `
  --demand-conversion true `
  --dtalite-assignment true `
  --conversion-workers 4 `
  --conversion-reserve-cores 1 `
  --conversion-adaptive true `
  --conversion-cache true `
  --demand-output-format csv `
  --time-periods am md pm nt `
  --period-times 0600_0900 0900_1500 1500_1900 1900_0600
```

`--dry-run` is the only option without a value. Add it only when the kernel
execution should be skipped.

---

## 4. Automatic and legacy postprocessing

After every successful multi-period assignment, the workflow now runs compact
aggregation and performance statistics automatically. Outputs are written next
to the period assignment folders:

```text
scenario_output/
  am/
  md/
  pm/
  nt/
  summary/
    am/
      link_performance_summary_input.csv
      statistics_data.csv
    md/
    pm/
    nt/
    daily/
      link_performance_summary_input.csv
      statistics_data.csv
    SUMMARY_MANIFEST.json
```

The compact input contains only fields consumed by `performance_summary`. The
legacy wide combined aggregator remains available through
`run_postprocessing.py` for compatibility and comparisons.

### Simple performance summary

```powershell
python run_postprocessing.py "C:\path\to\scenario" `
  --time-periods am md pm nt `
  --period-times 0600_0900 0900_1500 1500_1900 1900_0600
```

This creates the combined processed link-performance file and performance
statistics. Each five-minute speed column is taken from the period file that
owns its configured time range.

### Compare two scenarios

The first path is the catalog containing both scenario folders:

```powershell
python run_postprocessing.py "C:\path\to\scenario_catalog" `
  --scenario-a Base_Scenario `
  --scenario-b Build_Scenario `
  --performance-stats false `
  --link-performance-comparison true `
  --time-periods am md pm nt `
  --period-times 0600_0900 0900_1500 1500_1900 1900_0600
```

### Postprocessing with all options

```powershell
python run_postprocessing.py "C:\path\to\scenario_or_catalog" `
  --scenario-a Base_Scenario `
  --scenario-b Build_Scenario `
  --performance-stats false `
  --link-performance-comparison true `
  --bus-delay-analysis false `
  --time-periods am md pm nt `
  --period-times 0600_0900 0900_1500 1500_1900 1900_0600
```

`--scenario-a` and `--scenario-b` are required only when
`--link-performance-comparison true`.

---

## 5. Assignment option values

| Option | Default | Feasible values | Meaning |
|---|---:|---|---|
| `scenario_dir` | Current folder | Existing scenario folder | Positional path to Cube inputs or prepared period folders. Quote paths containing spaces. |
| `--kernel-source` | `wheel` | `wheel` | Bundled Python 3.11 Windows wheel using `pytaplite.assign` and its compiled `_native` OpenMP extension. |
| `--iterations` | `10` | Positive integer | Maximum assignment iterations. |
| `--processors` | `4` | Positive integer | Requested OpenMP processors. Do not exceed available logical processors. |
| `--route-output` | `0` | `0`, `1` accepted | Temporarily forced to `0`; user/configuration input is overridden. |
| `--vehicle-output` | `0` | `0`, `1` accepted | Temporarily forced to `0`; user/configuration input is overridden. |
| `--unit-system` | `metric` | `metric`, `imperial` | `metric` uses km/kph; `imperial` uses mile/mph. |
| `--vdf-type` | `bpr` | `bpr`, `qvdf` | Volume-delay function used during network conversion. |
| `--dtalite-run-mode` | `assignment` | `assignment` | `simulation` is reserved by the CLI but is not implemented. |
| `--network-conversion` | `true` | Boolean | Convert the Cube shapefile into period GMNS network files. |
| `--demand-conversion` | `true` | Boolean | Convert period OMX demand matrices into CSV files. |
| `--dtalite-assignment` | `true` | Boolean | Run or skip the assignment kernel after preparation. |
| `--conversion-workers` | `4` | `0` or positive integer | Bounded workflow worker limit for conversion and independent input/output copying. `0` selects a safe automatic limit; separate from OpenMP `--processors`. |
| `--conversion-reserve-cores` | `1` | Nonnegative integer | Physical cores kept free from conversion work. |
| `--network-chunks` | `0` | `0` or positive integer | Network chunks per period. `0` selects automatically. |
| `--demand-chunks` | `0` | `0` or positive integer | Matrix-row chunks per period and mode. `0` selects automatically. |
| `--conversion-adaptive` | `true` | Boolean | Reduce or disable parallel conversion when the machine is already busy. |
| `--conversion-cache` | `true` | Boolean | Reuse reprojected network data and the node template when the source fingerprint matches. |
| `--conversion-cache-dir` | Scenario cache | Folder path | Optional location for the prepared-network cache. |
| `--demand-output-format` | `csv` | `csv`, `binary`, `both` | Write compatible CSV, native DTAB binary, or both. Binary is selected in `settings.csv` automatically. |
| `--time-periods` | `am md pm nt` | One or more of `am`, `md`, `pm`, `nt` | Period names, in the same order as `--period-times`. |
| `--period-times` | See below | `HHMM_HHMM` values | One range for every selected time period. |
| `--dry-run` | Off | Flag present or absent | Perform preparation and preflight but skip kernel execution. |

When `--vdf-type qvdf` is selected, calibration parameters are read directly
from `src/dtalite4cube/resources/link_qvdf.csv`. If a network link type is not
listed, the workflow uses the final `vdf_code=all` row as the all-network fallback.

### Boolean values

Boolean options accept:

| True | False |
|---|---|
| `true`, `1`, `yes`, `y` | `false`, `0`, `no`, `n` |

### Default periods

| Period | Range | Current assignment behavior |
|---|---|---|
| `am` | `0600_0900` | 06:00 through 09:00 |
| `md` | `0900_1500` | 09:00 through 15:00 |
| `pm` | `1500_1900` | 15:00 through 19:00 |
| `nt` | `1900_0600` | Currently assigned as 19:00 through midnight; the post-midnight portion is not yet run by the kernel. |

The number of period names and time ranges must match.

---

## 6. Postprocessing option values

| Option | Default | Feasible values | Meaning |
|---|---:|---|---|
| `scenario_or_root_dir` | Required | Existing scenario or catalog folder | A single scenario for statistics, or a catalog for comparison. |
| `--scenario-a` | None | Scenario folder name | First scenario in a comparison. |
| `--scenario-b` | None | Scenario folder name | Second scenario in a comparison. |
| `--performance-stats` | `true` | Boolean | Create combined link performance and summary statistics. |
| `--link-performance-comparison` | `false` | Boolean | Compare `scenario-a` against `scenario-b`. |
| `--bus-delay-analysis` | `false` | `false` | The option is reserved, but this stage is not implemented. |
| `--time-periods` | `am md pm nt` | One or more of `am`, `md`, `pm`, `nt` | Periods to load and process. |
| `--period-times` | Default ranges above | `HHMM_HHMM` values | Defines period duration and ownership of five-minute speed columns. |

---

## 7. Expected scenario layout

### Cube inputs requiring conversion

```text
scenario/
├── network.shp
├── network.dbf
├── network.shx
├── network.prj
├── AM_*.OMX
├── MD_*.OMX
├── PM_*.OMX
└── NT_*.OMX
```

Keep one network shapefile in the scenario folder. Link geometry is written as
WKT with all source vertices retained. Network topology still uses only each
link's first and last nodes.

### Already-prepared inputs

```text
scenario/
├── am/
│   ├── node.csv
│   ├── link.csv
│   ├── settings.csv
│   ├── mode_type.csv
│   └── *_am.csv or *_am.bin
├── md/
├── pm/
└── nt/
```

### Useful help commands

```powershell
python run_assignment.py --help
python run_postprocessing.py --help
```

---

## Parallel conversion

The parallel copy uses one flat process pool for each conversion stage:

- Network tasks are `periods × network chunks`.
- Demand tasks are `periods × modes × demand row chunks`.
- The number of active processes is bounded independently of the number of
  queued tasks, so these dimensions never create nested pools.

Automatic scheduling uses physical-core capacity, reserves cores for the
operating system, applies minimum chunk sizes, and can sample current CPU load.
If fewer than two safe cores or too little work are available, conversion runs
serially.

### Automatic scheduling

```powershell
python run_assignment.py "C:\path\to\scenario" `
  --network-conversion true `
  --demand-conversion true `
  --dtalite-assignment false `
  --conversion-workers 0 `
  --conversion-reserve-cores 1 `
  --network-chunks 0 `
  --demand-chunks 0 `
  --conversion-adaptive true
```

### Reproducible fixed-worker test

Disable adaptive load sampling when comparing worker counts:

```powershell
python run_assignment.py "C:\path\to\scenario" `
  --network-conversion true `
  --demand-conversion true `
  --dtalite-assignment false `
  --conversion-workers 8 `
  --conversion-reserve-cores 1 `
  --network-chunks 0 `
  --demand-chunks 0 `
  --conversion-adaptive false `
  --output-dir "C:\path\to\converted-output"
```

`--processors` remains the OpenMP setting for assignment. It does not control
conversion workers.

Each conversion run writes `CONVERSION_PROFILE.json` to its output folder. To
profile multiple worker counts and verify output hashes against the one-worker
baseline:

```powershell
python profile_conversion.py `
  "C:\path\to\nvta_2025_base_network" `
  --workers 1,4,8
```

Profiling disables the prepared-network cache by default so worker comparisons
remain fair. Enable and locate it explicitly for cold/warm cache tests:

```powershell
python profile_conversion.py `
  "C:\path\to\nvta_2025_base_network" `
  --workers 1 `
  --conversion-cache `
  --conversion-cache-dir "C:\path\to\profile-cache" `
  --demand-output-format binary
```

To compare against an unchanged serial workflow without writing into the source
scenario, profile one worker and provide its folder:

```powershell
python profile_conversion.py `
  "C:\path\to\nvta_2025_base_network" `
  --workers 1 `
  --demand-output-format csv `
  --legacy-workflow-root "C:\path\to\workflow"
```

The profiler stages top-level scenario inputs as hard links when the source and
benchmark output are on the same volume, then runs the legacy workflow's normal
entry point with assignment disabled.

The cache is content-fingerprinted and rebuilt when any shapefile component or
the target CRS changes. Cache files are written atomically. Each period still
receives an independent `node.csv` copy because optional district assignment
may modify it.

DTAB is a versioned little-endian sparse record format read by the wheel's
native kernel (`demand_format=1`). During preflight, the workflow
streams DTAB records and verifies that their external zone IDs exist in
`node.csv`; the records are not rewritten. Invalid, truncated, or
referentially inconsistent DTAB files fail before the kernel starts.
