# DC Multi-Agency Transit — T2 interoperability dataset (contracts + pipeline)

**Tier T2:** real 20-feed DC-region supply + DECLARED synthetic demand
(`demand_provenance = synthetic_gravity_dc_kfactor`). Training role: Parts 5–7
of the ModelOps spine. **Read [TODO.md](TODO.md) first** — decisions D1–D3 and
all findings are ledgered there upfront.

## What is committed here (250 KB) vs regenerated

| Committed | Regenerate with |
|---|---|
| All pipeline scripts (gravity calibration, builds 0.2/0.2b/0.2c/0.3/0.3b, compact store + reader) | — |
| `calibration_report.json`, `k_factors.csv` | `python gravity_calibrate.py` |
| `manifests/` — every build manifest + per-agency inventory + the 0.2b transfer contract table | the corresponding `run_build_*.py` |
| `compact_exemplar/` — the WMATA compressed-schedule store (run_profiles / frequency_blocks / exceptions, round-trip lossless) | `python compact_store.py` |
| NOT committed: `synthetic_od_am.csv` (12.5 MB) | `python gravity_calibrate.py` (deterministic) |
| NOT committed: stage outputs / expanded / loading CSVs | the build scripts, in order |

External inputs (paths declared at the top of each script): the `GTFS_DC` feed
collection and the legacy zone-centroid file — see TODO.md D1/I-2. Feeds span
2019–2021 vintages; never present the merged snapshot as one date.

## Headline results (full detail in TODO.md and manifests/)

- 0.2: WMATA rail+bus supply, rail golden preserved inside the combined build.
- 0.2b: proximity transfer contract (423 bus stops ↔ 69 stations) → 3,078
  cross-mode arcs; forced bus→Orange-Line Gate-0 path demonstrated.
- 0.2c: gravity OD on WMATA-only supply → **35.3% servable** (the number that
  motivates multi-agency).
- 0.3: **all 20 feeds** built on per-feed Wednesday snapshots; 260 frequency
  trips instantiated; per-feed compact stores lossless (~3×; ~30× vs raw CSV
  with parquet-zstd).
- 0.3b: regional cross-agency clustering + loading (see
  `manifests/regional_manifest.json` when present).

## The compressed-schedule contract

Factorize repeats (453 run profiles, 214 frequency blocks), keep exceptions
explicit, prove the round-trip (encoder AND reader both verify), and ship the
decoder with the format (`compact_reader.py` emits the TAPLite column-pool
schemas). Never lossy, never silent.
