# Capacity & Ridership Verification — against CEE 598 Module 4 BART decks

**Sources checked (2026-08-08):** `BART_Teaching_Case_Presentation.pptx` (based on
BART's Sept 29 2025 train-length announcement; capacity values sourced
bart.gov/about/history/cars) and `BART_Funding_Slides.pptx` (fiscal/ridership
context). Method: text extraction + targeted search of both decks, then
decomposition of the dataset's capacity files.

## 1. What the dataset actually encodes (decomposed, not assumed)

`period_capacity = num_trips × per-train capacity`, and the per-train values
resolve exactly by line:

| Line | Trains/hr (hour 8) | Per-train capacity | Implied consist |
|---|---:|---:|---|
| Yellow N/S | 6 | **750** | 10 cars × 75 pax/car |
| Orange, Green, Red, Blue (N/S) | 3 | **450** | 6 cars × 75 pax/car |
| Beige (OAK connector) | 9–10 | 450 | as-given |

**Frequency cross-check vs deck GTFS results (WOAK, 7–8 AM): EXACT MATCH** —
deck reports Yellow-N 6 trains/hr, Red-N 3 trains/hr; the dataset's
`trips_per_hour.csv` gives the same.

## 2. Capacity definition — the critical assumption, now explicit

Deck (slide 12, from bart.gov) distinguishes:
- **Seating capacity:** A/B cars 72 · C/C2 cars 64 · new Fleet-of-the-Future 56
  (deck worked example uses 70 seats/car)
- **Crush capacity:** legacy ~200 pax/car, new fleet >200

The dataset's **75 pax/car** therefore = **"all seats full plus light
standing"** (≈ 1.05–1.35× seats depending on fleet mix) — a *service-standard*
capacity, **NOT crush**. Consequences:

- **V/C = 1.0 in our analysis means every seat taken + a few standees**, i.e.
  the comfort threshold, not physical impossibility.
- **Crush-based V/C ≈ 0.375 × reported V/C** (75/200). The 2019 peak V/C of
  6.6 becomes ≈ 2.5 against crush — still >2× physically impossible, which
  confirms the counterfactual reading: the FY2025 timetable genuinely cannot
  carry 2019 peaks; 2019 BART ran more and longer trains.
- The oversupply threshold (<20% of 750) equals <7.5% of crush — "oversupply"
  in our tables is conservative.

## 3. Ridership totals — dataset vs deck reports

| Quantity | Deck (BART reports) | This dataset | Verdict |
|---|---|---|---|
| Pre-COVID weekday | baseline for "~50%" claim | 432,783/day (Oct 2019 avg of 3 weekdays) | consistent with BART's reported ~405–440k Oct-2019 weekdays |
| 2025 highest day | **219,918** (Sept 10, 2025) | — | 219,918 / 432,783 = **50.8%** ⇒ deck's "~50% of pre-COVID" reproduced almost exactly |
| 2025 typical weekday | +10% YoY growth (Aug 2025) | 178,006/day (Feb 2025 avg) | 178,006/432,783 = 41.1%; Feb value + ~10% growth through the year ≈ 196k avg, peak day 220k — coherent |
| Recovery framing | "2× ridership needed to close gap"; FY27 deficit $376M | plateau at ~42–50% | same story from two independent sources |

## 4. Assumption register (complete list)

| # | Assumption | Status |
|---|---|---|
| A1 | 75 pax/car service capacity (not crush 200) | **verified as the dataset's encoding**; must be stated with every V/C |
| A2 | Yellow 10-car, other lines 6-car consists | implied by 750/450 decomposition; deck confirms 8→9-car extensions only from Sept 29 2025, AFTER the dataset's capacity era (Jan 13–Apr 1 2025) — so shorter consists in-era are plausible, but exact per-line car counts not independently confirmed → open item |
| A3 | Supply fixed at FY2025 timetable for all demand eras | deliberate counterfactual (README note 1) |
| A4 | Equal split across 1–2 path columns, uncapacitated | convention (README note 2) |
| A5 | Zone 27 = MLBR by alphabetical inference | high confidence (MCAR < MLBR < MLPT); verifiable against any BART station list |
| A6 | vehicle_capacity 750 applied uniformly in `period_capacity_td.csv` even where per-train resolves to 450 | the td file's own `period_capacity` column is authoritative (used as-is); its `vehicle_capacity` label is nominal → documented quirk |

## 5. Open verification items

1. Confirm per-line consist lengths for the Jan–Apr 2025 era (BART service
   bulletins / Fleet-of-the-Future deployment reports).
2. Re-express the era-comparison table at crush capacity (×0.375 on V/C) as a
   sensitivity row, so both capacity definitions are visible side-by-side —
   the deck's warning ("always specify which capacity definition you are
   using") applied to our own gold.
3. Sept 29 2025 timetable (9-car Yellow, +4 peak trains) postdates the
   dataset; a "post-extension supply" scenario would quantify how much of the
   residual peak undersupply the announced changes absorb (+12.5%/train).
