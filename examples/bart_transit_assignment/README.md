# Transit Dataset 1 — BART (T1 Observed-Demand Transit Gold)

**Tier:** T1 in the transit track (see `../planning/05_DATASET_CANDIDATES_TODO.md`).
**Built:** 2026-08-08 from `bart_core_v1_9.zip` (NSF LEAP-HI VoA project, SHA-256
manifests at source) + the project's multi-year ridership archive
(`ridership_change_2019-2025.gz`, 155 MB, already on disk — no external download).

## What this dataset is

A column-based BART loading model with **observed** hourly station-to-station
demand across **four service eras**, loaded onto the **fixed FY2025 timetable
supply** (capacity era 2025-01-13→2025-04-01; `period_capacity = num_trips ×
vehicle_capacity 750`). Because supply is held fixed while observed demand
varies by year, the result is a clean **counterfactual undersupply/oversupply
analysis**: could today's service carry yesterday's (or tomorrow's) riders?

Components: 50 stations (zones), 12 directed routes (6 lines × 2 directions),
362 ride links + 760 access/transfer arcs, 2,450 OD pairs with 1–2 enumerated
path columns each, hourly demand and hourly supply.

## The four-era result (average weekday, mid-period)

| Era | Riders/day | UNDERSUPPLY share | CROWDED | OVERSUPPLY | Peak V/C | Excess rider-link-hrs/day | Empty seat-hrs/day |
|-----|-----------:|---:|---:|---:|---:|---:|---:|
| **2019-10** (pre-COVID) | 432,783 | **6.45%** | 2.51% | 67.8% | **6.60** | **511,822** | 12.19M |
| **2021-10** (COVID trough) | 111,226 | 0.10% | 0.17% | **91.8%** | 1.42 | 1,497 | **14.18M** |
| **2023-10** (plateau) | 185,584 | 1.15% | 0.77% | 84.9% | 2.36 | 30,736 | 13.70M |
| **2025-02** (in-core data) | 178,006 | 0.98% | 0.74% | 85.7% | 2.20 | 26,996 | 13.75M |

States per served ride-link-hour: UNDERSUPPLY v/c≥1.0 · CROWDED 0.8–1.0 ·
BALANCED 0.2–0.8 · OVERSUPPLY <0.2 with service running.

**Reading it in transit-performance terms:**
- **Undersupply is a peak-direction, peak-hour phenomenon**, not a system one:
  even in 2019 only 6.5% of link-hours exceed capacity — but those are the
  transbay/core segments at 8:00 and 17:00–18:00, and the FY2025 timetable
  would strand ~512k rider-link-hours/day of 2019 demand (peak V/C 6.6 —
  today's service simply could not carry pre-COVID peaks).
- **Oversupply is the dominant modern state:** at 2021 trough, 92% of all
  served link-hours ran under 20% full; even in 2025, 86% do. Empty
  seat-hours barely move across eras (12.2M→14.2M) because supply is fixed —
  the difference between eras is who occupies the peak, not the base cost.
- **The recovery plateau:** 2023 and 2025 are statistically the same system
  (~180k riders/day, ~1% undersupply, peak V/C ≈ 2.2–2.4 on Red/Blue-S at
  8:00) — demand recovery stalled at ~42% of 2019.

## Files

| File | What |
|---|---|
| `source_core/` | unzipped `bart_core_v1_9.zip` (column_pool + partial GTFS) |
| `station_crosswalk.csv` | zone_id ↔ BART station code (49 via route-chain/GTFS alignment, 0 conflicts; zone 27 = MLBR inferred alphabetically, MCAR<MLBR<MLPT) |
| `bart_supply_demand.py` | the engine: crosswalk build, column loading, V/C classifier |
| `historical_od/weekday_{2019,2021,2023}-10.csv` | observed OD mapped to zones (3 matched mid-Oct weekdays each) |
| `analysis/<tag>_link_hour.csv` + `<tag>_summary.json` | per-era results |
| `gold/era_comparison.json` | the frozen four-era table above |

## Assumptions & Conventions register (the contract for this dataset)

Every number quoted from this dataset inherits these. Full cross-checks against
BART's own figures (CEE 598 module-4 decks, bart.gov values): [VERIFICATION.md](VERIFICATION.md).

| # | Assumption / Convention | Value & basis | Status |
|---|---|---|---|
| **A1** | **Capacity definition: 75 pax/car service capacity** — "all seats + light standing", NOT crush (~200/car, bart.gov). V/C=1.0 = comfort threshold; crush V/C ≈ 0.375 × reported. | decomposed from the capacity files: Yellow 6 tph × 750 (10-car×75); other lines 3 tph × 450 (6-car×75) | ✅ verified vs BART deck (seats 56–72/car, crush ~200) |
| **A2** | Per-line consists: Yellow 10-car, others 6-car | implied by the 750/450 decomposition; capacity era (2025-01-13→04-01) predates the Sept 29 2025 9-car extension | 🟡 plausible; exact in-era car counts = open item |
| **A3** | **Supply fixed at the FY2025 timetable for ALL demand eras** (counterfactual "can today's service carry that year's riders?", not historical reconstruction) | `period_capacity_td.csv` | deliberate framing |
| **A4** | **Loading: equal split across the OD's 1–2 enumerated path columns, uncapacitated** — V/C>1 is unmet-capacity diagnostic, not predicted physical loads | `bart_supply_demand.py` | convention |
| **A5** | V/C state thresholds: UNDERSUPPLY ≥1.0 · CROWDED 0.80–1.00 · BALANCED 0.20–0.80 · OVERSUPPLY <0.20 with service running | analysis choice (on A1's capacity basis) | convention |
| **A6** | Zone↔station crosswalk: 49/50 by route-chain/GTFS alignment (0 conflicts); zone 27 = MLBR inferred alphabetically (MCAR<MLBR<MLPT); zone ids = alphabetical station codes | `station_crosswalk.csv` | ✅ high confidence |
| **A7** | Demand provenance = **observed** BART fare-gate OD (core package 2024-10→2025-04; historical eras from `ridership_change_2019-2025.gz`); eras = 3 matched mid-October weekdays averaged | what makes this T1, not T2 | ✅ totals cross-check with BART reports (50.8% ⇔ "~50% of pre-COVID") |
| **A8** | Network era mismatch at edges: BERY/MLPT (opened 2020) carry zero 2019 demand; nothing fabricated | data as-is | documented |
| **A9** | `vehicle_capacity=750` label in `period_capacity_td.csv` is nominal; the `period_capacity` column is authoritative and used as-is | file quirk | documented |

## Honest-scope notes (read before quoting)

1. **Supply is FY2025 for every era** — deliberate counterfactual. 2019 riders
   on the 2019 timetable experienced far less crowding than the 6.6 V/C here;
   this measures today's timetable against each era's demand, which is the
   Value-of-Adaptability question, not a historical reconstruction.
2. **Loading = equal split across the OD's 1–2 enumerated columns, no capacity
   constraint.** V/C > 1 is a diagnostic of unmet capacity, not a prediction of
   physical loads (real riders would shift time/path/mode).
3. **Network era mismatch at the edges:** BERY/MLPT (2020) didn't exist in the
   2019 OD — those zones simply carry zero 2019 demand; conversely the 2019
   Oakland Airport connector demand maps fine. No fabricated data.
4. Demand files are **observed** (BART fare-gate OD via the project archive);
   `demand_provenance = observed` — this is what elevates BART to T1 above the
   synthetic-OD T2 tier.
5. **Capacity definition (verified vs BART sources — see VERIFICATION.md):**
   the dataset encodes **75 pax/car service capacity** (Yellow 6 tph × 750 =
   10-car; other lines 3 tph × 450 = 6-car), i.e. "all seats + light standing"
   — NOT crush (~200/car). V/C = 1.0 here is the comfort threshold; crush-based
   V/C ≈ 0.375 × reported. Frequencies match BART GTFS exactly (Yellow 6,
   Red 3 trains/hr). Ridership totals cross-check with BART reports: 2025 peak
   day 219,918 / our 2019 weekday 432,783 = 50.8% ⇔ BART's "~50% of pre-COVID".
