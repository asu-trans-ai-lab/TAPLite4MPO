# NVTA run (bring-your-own-data)

Run-configs and scripts to reproduce the **NVTA PM 6-mode** assignment (sov, hov2,
hov3, com, trk, apv) with the TAPLite kernel against the renumbered NVTA dataset.

> **The NVTA data is agency-restricted and is NOT in this repository.** Your
> instructor shares the `_internal/` data folder separately (e.g. via Dropbox). The
> rest of the repo reproduces fully without it — see the open networks in
> `kernel/data_sets/` and the top-level README.

## 1. Get the data
Download the `_internal/` folder your instructor shared (it already contains
`node.csv`, `link.csv`, the per-mode demand `*.csv`/`.bin`, and the CUBE reference
columns). Renumbered, contiguous ids → small memory footprint (~6–8 GB).

## 2. Point the scripts at it (choose ONE)
```bash
# A) environment variable (per shell)
export DTALITE_NVTA_INTERNAL=/path/to/_internal          # Windows: set DTALITE_NVTA_INTERNAL=C:\path\to\_internal

# B) a local config file (git-ignored)
echo '{"internal": "/path/to/_internal"}' > nvta_run/local_config.json

# C) drop the folder into the repo at  data/nvta_internal/   (also git-ignored)
```
If none is set, the runner prints a clear "NVTA data not configured" message.

## 3. Build the kernel (once)
```bash
bash build.sh        # from the repo root -> bin/DTALite.exe
```

## 4. Run
```bash
cd nvta_run
python run_nvta.py 1     # all-or-nothing baseline (fast sanity check)
python run_nvta.py 10    # Frank-Wolfe, 10 iterations
python run_nvta.py 20    # Frank-Wolfe, 20 iterations (most converged)
```
`run_nvta.py` stages this folder's config + `bin/DTALite.exe` into the data folder,
runs the assignment, copies `link_performance.csv` to `results/link_perf_iter<N>.csv`,
then checks per-mode link volume against the CUBE reference (`I4PM*`, joined on
`(from_node, to_node)`) and verifies `allowed_use` (HOV/managed lanes).

## Files here
- `mode_type.csv` — 6 modes, `dedicated_shortest_path=1`; PCE: trk=2, others=1;
  occ: hov2=2, hov3=3.5, apv=1.6.
- `settings_1iter.csv` / `_10iter.csv` / `_20iter.csv` — FW, 8 processors, PM 15–19h,
  `first_through_node_id=-1`, `route_output=0`, ODME off.
- `data_root.py` — resolves the data path (§2). `prep_network.py`, `stage_conic.py`,
  `stage_plf.py`, `stage_qvdf.py` — optional staging for conic / PLF / QVDF variants.
- `results/` — derived outputs (git-ignored).
