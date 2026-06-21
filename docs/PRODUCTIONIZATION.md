# Productionization notes — toward an MPO-grade assignment package

This documents how the repo separates public vs private data, the machine-readable
schema/manifest, and a prioritized feature roadmap for professional MPO use.

## 1. Public vs private data (done)

| kind | location | tracked? |
|------|----------|:--------:|
| public datasets | `kernel/data_sets/` (4-node, Sioux Falls, Chicago Sketch/Regional) | yes |
| test networks | `test_networks/` | yes |
| **private / agency data** | **`private/<scenario>/`** | **no (git-ignored)** |
| external private data | anywhere on disk, referenced by config | n/a |

- `private/` is ignored except its README; drop NVTA / MPO / client networks there
  and run them exactly like public ones (`python -m dtalite_qa run private/<s> --exe ...`).
- `nvta_run/` scripts no longer hard-code agency paths — they resolve the data
  root from `DTALITE_NVTA_INTERNAL`, a git-ignored `nvta_run/local_config.json`,
  or `private/nvta_internal/` (see `nvta_run/data_root.py`).
- `.gitignore` now excludes `private/**`, `nvta_run/results/` (derived from private
  data), `local_config.json`, and generic kernel outputs that may carry private
  volumes — so you can publish everything else.

**To publish:** the kernel source, `bin/`, `dtalite_qa/`, `test_networks/`,
`kernel/data_sets/`, `schemas/`, and docs are all safe to upload; agency data
stays in `private/` and never leaves the machine.

## 2. Machine-readable schema + manifest (done)

- `schemas/gmns_dtalite_schema.json` — formal field spec for every input file
  (type / required / default / units / description), version `gmns-dtalite-1.0`.
  Regenerate with `python -m dtalite_qa schema --out schemas/gmns_dtalite_schema.json`.
- `python -m dtalite_qa manifest <scenario>` writes a provenance `manifest.json`:
  per-file sha256 + row count + columns, declared units, schema version, optional
  kernel version. This makes a run **auditable and reproducible** — you can prove
  which exact inputs produced a result, which agencies and reviewers expect.

A JSON schema/manifest is worth having: it pins units (the per-lane capacity and
mph/km-h conventions are the usual source of silent errors), gives other tools a
contract, and underpins reproducibility.

## 3. Feature roadmap (recommended, by priority)

### High value, low effort
1. **Run report** — after an assignment, emit `run_report.json`/`.md`: gap
   trajectory, total VMT/VHT/PMT, per-mode link-volume totals, restricted-link
   enforcement summary, wall-clock. (One pass over the log + link_performance.)
2. **Kernel version stamping** — embed a version string in the kernel and echo it
   into `summary_log_file.txt` and `manifest.json` (close the provenance loop).
3. **CI** — wire `python -m dtalite_qa check` + `test_networks/run_regression.py`
   into `kernel/.github/workflows/` so every PR re-validates and re-regresses.
4. **`scenario.json` config** — one file naming inputs, settings overrides, and
   outputs, so a run is fully declarative (good for batch / scenario managers).

### Medium
5. **Scenario diff** — compare two runs' `link_performance.csv` (volume/speed
   deltas, top movers) for before/after policy analysis.
6. **GeoJSON / shapefile export** of link_performance (geometry already present)
   for GIS dashboards.
7. **Deterministic vehicle generation** — seed the RNG so `vehicle.csv` is
   reproducible run-to-run.
8. **Unit auto-detection / conversion** — warn when `free_speed` looks like mph
   vs km/h; offer to normalize.

### Larger
9. **Sparse OD / demand-on-disk** for very large regional models (the dense
   `[modes][zones^2]` matrices dominate memory at MPO scale).
10. **Python wheel** packaging the kernel binary so MPO IT can `pip install`
    without a compiler; ship per-platform exes.
11. **Path/skim export** (OD travel-time skims) — a standard MPO deliverable.
12. **Convergence controls** — relative-gap stopping criterion and max wall-time,
    not just a fixed iteration count.

## 4. Performance — large-scale efficiency (Chicago Regional)

`kernel/data_sets/04_chicago_regional`: 12,982 nodes, ~25k links, 2.3M OD pairs,
single mode. 10 Frank-Wolfe iterations, 8 OpenMP threads:

| phase | time |
|-------|------|
| assignment loop (kernel "CPU running time", 10 iters) | ~8.6 s (~325 ms / AON) |
| total wall, **CSV** demand (`demand_format=0`) | ~28.8 s |
| total wall, **binary** demand (`demand_format=1`) | ~19.7 s (**1.46x**, identical gap) |

The assignment is already fast; startup (network + demand load + output) was the
rest, and the binary demand format removes the CSV-parse cost. Memory was also cut
earlier: the shortest-path `CostTo` scratch is now O(processors x nodes) instead of
O(zones x nodes) — 186 MB -> 0.8 MB on Chicago Regional (issue #9).

**Binary demand format (done).** `python -m dtalite_qa demand-bin <scenario>`
writes packed `.bin` files; `demand_format=1` in settings.csv makes the kernel read
them (falling back to CSV). Layout: header `"DTAB"`/int32 version/int64 count, then
`int32 o, int32 d, double vol` records. Results are bit-identical to CSV.

The speedup grows with demand size. On the **NVTA** regional model (PM, ~30M OD
pairs across 6 modes, 1-iter AON, 8 threads), total wall time:

| run | CSV | binary | speedup |
|-----|----:|-------:|--------:|
| single mode (sov, 10.2M ODs, 158 MB) | 68.7 s | 27.4 s | **2.5x** |
| all 6 modes (~30M ODs, ~455 MB) | 144.4 s | 46.6 s | **3.1x** (−98 s) |

Assignment CPU is identical both ways; the whole difference is demand loading. All
six modes' binary totals match the CSV totals to the cent. One-time conversion of
all 6 NVTA demand files: ~59 s.

**Demand-read tuning (done).** Beyond the binary format: the per-mode reads now run
in parallel (`#pragma omp parallel for` over modes — each writes its own `ODtable[m]`),
and the `Seed_ODtable` copy is skipped unless ODME or route output needs it (a third
fewer OD writes + one fewer matrix to populate on the common fast-run path). Results
are identical (sf_multimodal per-mode totals unchanged, regression green).

**Systematic binary I/O (next).** The same `"DTAB"` container generalizes to the
large *output* files we read back. `route_assignment.csv` / `vehicle.csv` have
variable-length `node_ids`/`link_ids`, so they use a **CSR layout**: a fixed
per-route header array `{mode, o, d, volume, n_links, link_offset}` + one flat
`link_ids[]` array (all routes concatenated) -> two bulk `fread`s, no parsing. This
enables warm-starting a path-based assignment from a prior route file. The kernel
keeps the lightweight custom binary (no deps); `dtalite_qa` is the bridge that can
also export Parquet/Feather for pandas/DuckDB/GIS interop.

**Config:** `settings.csv` is the single config surface — new parameters are added
as named columns and default when absent (e.g. `demand_format`); no separate config
file is needed, and older settings files keep working.

## 5. What "professional" buys the user here

The kernel already produces correct equilibria (all 9 issues fixed, regression
green). The package around it — validate → fill defaults → inventory → check
accessibility → manifest → run → report — is what turns a research kernel into a
tool an MPO can hand to staff and auditors: reproducible, self-documenting,
public-safe, and hard to misconfigure.
