# NVTA TAPLite Client Package — July 29, 2026

This package contains the NVTA base inputs, the assignment workflow, and the
Windows TAPLite engine. No separate DLL or DTALite installation is required.

## Package folders

- `nvta-base-run-07-29-2026/` — NVTA network and demand inputs
- `workflow/` — setup, assignment, and postprocessing tools
- `wheels/` — bundled Python 3.11 Windows engine

## First-time setup

Use 64-bit Windows. Open PowerShell in the `workflow` folder and run:

```powershell
.\setup_environment.bat
conda activate dtalite_pipeline
```

Setup creates the required Python 3.11 environment and installs the bundled
engine without downloading it from PyPI.

## Run the NVTA assignment

From the `workflow` folder:

```powershell
python run_assignment.py "..\nvta-base-run-07-29-2026" `
  --iterations 20 `
  --processors 8 `
  --time-periods am md pm nt `
  --period-times 0600_0900 0900_1500 1500_1900 1900_0600
```

Results are written to the workflow's normal scenario output folders. See
`workflow/README.md` for additional options and troubleshooting.
