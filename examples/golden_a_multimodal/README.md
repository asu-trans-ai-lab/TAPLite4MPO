# Golden A — the synthetic multimodal teaching network (T0)

**Purpose: deterministic teaching + regression, NOT realism.** Every class
participant should understand the entire network. This is the fixture named in
`../planning/06_TRAINING_MODELOPS_SPINE.md` (Golden A) and the T0 slot of the
transit track. Built & all checks passing 2026-08-08.

## The network on one screen

- **6 zones.** Z1–Z5 connected; **Z6 is a deliberate island** (no connectors —
  its 50 trips MUST be detected as unreachable, never silently dropped).
- **Road:** chain 101–102–103–104 with a signal at 102; centroid connectors
  for Z1, Z4, Z5.
- **Two transit lines:** L1 rail R1–R2–R3, **schedule-based** (12 explicit
  trips, 07:00–08:50 every 10 min); L2 bus B1–B2–B3, **frequency-based**
  (frequencies.txt, 15-min headway 07:00–09:00 → expands to 8 trips).
- **Transfer:** walk link B2↔R2 (the hub) — the only place modes touch.
- **Parking as network elements (P5):** P&R lot 301 (drive-in from 101, walk
  to R1) and K&R curb 302 (drive-in from 102, walk to R2). Not POIs — arcs.
- **Walk connectors:** Z1–B1, Z2–R2, Z3–R3, Z4–B3.

## The five trip types + the trap (demand/demand.csv, total 1,200)

| Submarket | OD | Volume | Teaches |
|---|---|---:|---|
| drive | Z1→Z4 | 600 | plain auto path |
| transit_walk | Z1→Z2 | 200 | walk–ride–walk legality |
| transit_transfer | Z1→Z3 | 150 | bus→walk-transfer→rail |
| park_and_ride | Z5→Z3 | 120 | staged legality: drive legal ONLY until the park node |
| kiss_and_ride | Z1→Z3 | 80 | dropoff variant |
| **disconnected** | **Z6→Z3** | **50** | **the intake gate must catch it** |

## Run the acceptance checks (Gate 0 as executable tests)

```bash
python golden_a_check.py
```

C1–C5 = the five "Show Me the Path" trip types as staged reachability over
mode-legal subgraphs; C6 = the island is unreachable AND reported; C7 = supply
counts exact (L1=12 scheduled, L2=8 frequency-expanded); C8 = demand
conservation incl. the ledgered unreachable 50. Exit 0 only if ALL pass.
Results: `gold/check_results.json`.

## Files

`network/node.csv` (18 nodes, typed: centroid/road/rail_station/bus_stop/
parking/dropoff, signal ctrl_type) · `network/link.csv` (30 directed links,
`allowed_uses` auto|walk; park_access/dropoff_access link types) ·
`gtfs/` (stops, routes, calendar, trips, stop_times, frequencies — a complete
minimal feed) · `demand/demand.csv` (submarket-labeled) ·
`golden_a_check.py` · `gold/check_results.json`.

## Teaching uses

1. **Gate-0 drill:** break one link (delete B2↔R2) and watch C3 fail — the
   difference between "supports multimodal" and a demonstrable path.
2. **Frequency vs schedule (transit layers L1/L2):** same network, two service
   representations; the compact-store factorization is visible by hand.
3. **The intake-gate lesson:** Z6's 50 trips are the permanent reminder that
   unreachable demand is ledgered, never dropped.
4. **Regression:** any converter/tooling change must keep C1–C8 green.
