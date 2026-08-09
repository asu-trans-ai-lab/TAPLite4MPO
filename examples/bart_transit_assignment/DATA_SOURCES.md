# Data sources & what is NOT committed

| Committed here | Source |
|---|---|
| `core/column_pool/` (link, columns, period_capacity_td, trips_per_hour) + `core/GTFS/` | extracted from `bart_core_v1_9.zip` (NSF LEAP-HI Adaptive Transit VoA project; SHA-256 manifests `BART_CORE_ARCHIVE.sha256` / `BART_CORE_FILES.sha256` ship beside the zip) |
| `historical_od/weekday_{2019,2021,2023}-10.csv` | extracted from the VoA project's `ridership_change_2019-2025.gz` (observed BART fare-gate OD), mapped to zones via `station_crosswalk.csv` |
| `analysis/`, `gold/` | produced by `bart_supply_demand.py` on 2026-08-08 (see README for the era table) |

**NOT committed (size):** `demand_td.csv` (84 MB, hourly OD 2024-10-01→2025-04-01)
from the same `bart_core_v1_9.zip` — required only to reproduce the
`weekday_2025-02` era. Obtain the zip from the VoA project
(`adaptive-transit-voa-students/data/`), verify against its SHA-256 manifests,
and place the file at `core/column_pool/demand_td.csv`.

Reproduce any historical era without it:

```bash
python bart_supply_demand.py weekday_2019-10 2019-10-15 2019-10-16 2019-10-17 --demand historical_od/weekday_2019-10.csv
```

BART station-to-station ridership is public data (bart.gov ridership reports);
the VoA packaging is the checksummed distribution used here.
