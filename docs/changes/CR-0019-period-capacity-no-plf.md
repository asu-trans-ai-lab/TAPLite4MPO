# CR-0019 — Static VDFs consume period capacity directly; PLF leaves the runtime

**Date:** 2026-08-10 · **Status:** implemented, selftest green (351/0 with CR-0020 and GOLD-001)
**Agency evidence:** the corridor-level tables behind this record are
agency-confidential and live in the private analysis repo; the engineering
content below is complete without them.

**Files:** `kernel/src/TAPLite.cpp`, `kernel/tests_cpp/selftest_main.cpp`

## Why

Three quantities were mediating between a period volume and a period
capacity that already agreed with each other: `lanes`, the period duration
`H`, and `vdf_plf`. Every basis defect in the agency audit trail — the D/C = 10
rows, the two different "doc" columns (K-5), the 1.92× `VDF_plf1` trap — came
from disagreement about which of those a given number had already been
divided by.

The fix is to remove the mediation. The static VDFs take one ratio:

```
x = V_period / C_period
```

Both sides are on the period basis by construction, so there is nothing left
to get wrong.

## What changed

**New column `capacity_period`** (veh/period, whole link) parsed in
`ReadLinks`, defaulting to 0 = not supplied. Negative values are clamped to 0.

**New file-scope helper** expressing the rule once:

```cpp
static inline double StaticLoadingRatio(int k, double volume)
{
	if (Link[k].capacity_period > 0.0)
		return volume / Link[k].capacity_period;
	double incoming = volume / fmax(0.01, Link[k].lanes)
		/ fmax(0.001, demand_period_ending_hours - demand_period_starting_hours)
		/ fmax(0.0001, Link[k].VDF_plf);
	return incoming / fmax(0.1, Link[k].Lane_Capacity);
}
```

`Link_Travel_Time` computes `IncomingDemand` so that
`IncomingDemand / Lane_Capacity == StaticLoadingRatio` holds in **both**
modes, which lets every existing per-form branch stay untouched.

## Scope — what is explicitly NOT changed

- **Hourly capacity is untouched.** `Lane_Capacity` / `capacity` remain
  per-lane hourly and are still what QVDF reads. The two capacities now
  coexist with distinct names and distinct consumers, which is the point.
- **QVDF is untouched.** It keeps its own DOC on the hourly basis.
- **The legacy path is untouched.** With no `capacity_period` column, every
  existing network produces bit-identical results.

## QVDF: `k_d` does PLF's job, but must not be derived from it

`k_d` maps a period volume to a demand rate — structurally **the same role
PLF played**:

```
D = k_d · (V / H)          veh/h, the rate the queue actually sees
x_D = D / C_hourly         the QVDF loading ratio
```

What changes is provenance and granularity: PLF is one declared constant per
period, applied to every link; `k_d` is per link, calibrated from observed
speed over the congested episode.

So `k_d ≈ 1/PLF` is not false — it is what you get when a link's demand
peaking happens to equal the regional peak-hour share. **Withdrawn as a
definition**, because whether they coincide on a given link is exactly what
QVDF calibration is meant to determine; assuming it makes the calibration
circular against its own target. They diverge most on precisely the links that
matter — the long-queue ones, where the episode's peaking has little to do
with a regional period factor.

`k_μ = μ/C_h` has no PLF counterpart at all: supply-side, from measured
discharge.

## Tests (8 new assertions, spine order — written before the kernel change)

| assertion | what it pins |
|---|---|
| BPR uses `V_period/C_period` | the ratio itself, hand-computed |
| PLF is inert | `vdf_plf` 1.0 → 0.4270 changes nothing, 1e-12 |
| lanes are inert | 1 → 7 changes nothing, 1e-12 |
| period hours are inert | H 4 → 3 changes nothing, 1e-12 |
| conical: PLF and lanes inert | same, through the conical branch |
| conical `t(x=1) = 2·t0` | Spiess identity survives the new path |
| legacy path unchanged | lanes/H/PLF arithmetic exact when column absent |
| `capacity_period = 0` falls back safely | never divides by zero |

Total: 351 pass, 0 fail (whole suite).

**A false pass was caught during authoring.** The first version declared
`double v[2] = {0.0, 4000.0}` while `Link_Travel_Time(0, v)` reads `v[0]`, so
every call ran at zero volume and the three "inert" assertions passed
vacuously. Two other assertions failed loudly, which is what exposed it.
Noted because an inertness test that passes for the wrong reason is worse
than no test.

## Field evidence — the period factor is a constant

Inverting the source model's own V/C on 31,416 links of a regional agency PM network:

```
f = (SRC_PM_VOLUME / SRC_PM_VC) / SRC_PM_HOURLY_LINK_CAP
    mean 3.4014   std 0.0001   range [3.4005, 3.4022]
```

No per-link structure; the spread is the source model's rounding of `SRC_PM_VC` to five
decimals. 3.4014 / 4 h = 0.85035, matching the 0.8503 derived independently
from the published regional peak-hour shares. So `capacity_period = SRC_PM_HOURLY_LINK_CAP × 3.4014`
uses only a supply field and one global constant — **not circular**, unlike
the per-link back-extraction it replaces.

## Pre-assignment verification gate

```
source_vc_P  ≈  source_volume_P / capacity_period_P
```

Result on that network: 31,416 links, max rel err 0.026 %, p95 0.005 %, 100 % inside 0.5 % —
**PASS**. A failure here means the capacity is on the wrong basis and no
downstream assignment number is interpretable.

## Field verification — PLF inertness control (same network, 49,329 links)

Two full regional runs, byte-identical inputs except `vdf_plf`
(0.4270 vs 0.8503). 106 numeric output columns compared:

| result | columns |
|---|---|
| **bit-identical** | **103** — including `volume`, `speed_mph`, `travel_time` |
| differ | 3 — `vdf_plf` (the echoed input), `D`, `doc` |

**The assignment is provably PLF-free.** Every equilibrium quantity is
unchanged to the last bit under a 2× perturbation of PLF.

### OPEN — CR-0019b: the reporting layer still uses the old basis

`D` and `doc` in `link_performance.csv` are still written as
`V/lanes/H/plf` and `D/C_hourly`. Under the new contract that is a column
which moves when a provably inert input changes — the K-5 two-definitions
defect, displaced from the assignment into the report.

Fix (deferred, needs care): when `capacity_period > 0`, the reported `doc`
for a static-VDF link must be `V / capacity_period`, and every emitted D/C
column must be basis-stamped. **QVDF's internal DOC must stay on the hourly
basis** — it is a genuinely different quantity, not the same one on a
different basis, so this cannot be a blanket substitution.

Until then: `doc` in a `capacity_period` run is **not** the ratio the static
VDF actually used. Read `volume / capacity_period` instead.

## Run ledger (corridor set, 2,812 links, vs the source model)

| run | model | R² | slope | WAPE | bias | spd MAE | FW gap |
|---|---|---|---|---|---|---|---|
| A | BPR + plf 1.0 (delivered) | 0.9426 | 1.0116 | 10.81 % | −1.61 % | 2.94 | 1.70 % |
| B | conical + plf 0.8503 flat | 0.9966 | 1.0051 | 3.02 % | +0.76 % | 1.07 | 3.42 % |
| C | conical + per-link plf | 0.9967 | 1.0034 | 2.93 % | +0.64 % | 1.05 | 3.38 % |
| **D** | **conical + capacity_period, no PLF** | **0.9966** | 1.0040 | 2.98 % | +0.69 % | 1.08 | 3.19 % |

Corridors with R² ≥ 0.9: **64 of 70** under D, 41 under A.
managed-lane corridor A −4.26 → **0.9335**; managed-lane corridor B −4.19 → **0.9843**.

**C is reverse-engineering evidence only** and must not be cited as
validation — it fits per-link capacity to the comparison target. It earns its
place by having *measured* that the factor is a constant (§3b), which is what
made D constructible without circularity.

**Freeze D.** B and D agree to 4 decimals; D is the one with no PLF in it.

Two notes on interpretation:
- **A is the most converged run and the worst fit.** The conical runs sit at
  a ~3.2–3.4 % gap versus A's 1.70 % and still fit far better, so the
  improvement is not a convergence artifact.
- **D and B are not the same model** (denominators differ by a uniform
  1.00006, and the runs land on different FW iterates), so link-level scatter
  between them is equilibrium indeterminacy at a 3 % gap, not a PLF effect.
  The inertness control above is the clean test; D-vs-B is not.
