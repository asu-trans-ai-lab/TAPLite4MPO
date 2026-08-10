# DTALite / TAPLite — User Guide, Volume 2: Static Highway Assignment for MPOs

**Volume 1** (`USER_GUIDE.md`) is the kernel reference: input schema, build/run, VDF
mechanics, outputs. **Volume 2** (this document) is the agency-facing guide: how to use
the same kernel to **reproduce an MPO/DOT static highway assignment** — the VDF choice,
the period-capacity / peak-load-factor convention, generalized cost and user classes,
managed lanes, convergence, validation, and per-agency recipes.

It unifies the requirements of ARC (Atlanta), SERPM 8, TRPA, MTC, SANDAG, MWCOG, VDOT,
and ODOT into one GMNS-based workflow. The kernel covers the common core directly; each
agency differs only in *data* (lookup tables) plus a few settings. Full conformance
detail: `private/kernel_references/` (`DTALite_unified_traffic_assignment_spec.md`,
`agency_conformance_matrix.md`).

---

## 1. The MPO assignment workflow

> **Onboarding a new agency model? Read [`docs/MPO_ONBOARDING_GUIDE.md`](docs/MPO_ONBOARDING_GUIDE.md) first.**
> A shapefile + matrix + "alpha/beta" can't state the capacity basis/period, peak-load
> factor, units, or trip kind — so the agency must supply a `submission.yml` declaration,
> and `python -m dtalite_qa intake <scenario>` audits it (issue report + conversion log +
> guided HTML dashboard) and **blocks rather than guessing** any undeclared convention.

```
 agency network (CUBE/Visum/shapefile + DBF lookups)
   └─ agency2gmns converter  (facility×area-type → capacity, speed, VDF coeffs;
   │                          restrictions → allowed_use; tolls; period factors)
   ▼
 GMNS inputs  (node.csv, link.csv, demand_<class>.csv, mode_type.csv, settings.csv)
   └─ python -m dtalite_qa validate / check        (schema + connectivity + allowed_use)
   ▼
 bin/DTALite.exe  (run from the scenario folder; one run per time period)
   ▼
 link_performance.csv  (volume, per-class mod_vol_*, speed, v/c, VMT/VHT, ref_volume)
   └─ validation vs counts / ref_volume  (R², %RMSE by volume-group & facility type)
```

The kernel is **one static-UE engine**; the agency identity lives in the converter
(data) and a handful of settings. The rest of this guide is what to put in those files.

---

## 2. Unified GMNS input (what every MPO provides)

Beyond the Volume 1 schema, MPO runs use these fields (all optional, sensible defaults):

| file | field | MPO meaning |
|---|---|---|
| link.csv | `capacity` | **hourly per-lane** capacity (`= agency hourly cap`); period handled by `vdf_plf` (see §4) |
| link.csv | `vdf_type` | `0` BPR · `1` conical · `2` QVDF · `3` BPR2 · `4` INRETS · `5` Akcelik · `6` SANDAG-signal · `7` SCAG piecewise-BPR · `8` SCAG ramp-meter |
| link.csv | `vdf_alpha,vdf_beta` | per-facility VDF coefficients (from the agency FACTYPE×ATYPE table) |
| link.csv | `vdf_A` | modified-BPR linear term (ARC) |
| link.csv | `vdf_plf` | **peak load factor** φ/L (the period-capacity convention — §4) |
| link.csv | `green_ratio` | signal g/C for `vdf_type=6` (SANDAG) |
| link.csv | `allowed_use` | mode access (`hov2;hov3`, `trk`, empty=all) — managed lanes/HOV |
| link.csv | `toll_<mode>` (or `vdf_toll`) | per-class toll in $ |
| link.csv | `ref_volume` | agency loaded volume = validation target |
| mode_type.csv | `vot` | value of time ($/hr) — converts toll & distance cost to time |
| mode_type.csv | `operating_cost` | $/mile distance cost (generalized cost) |
| mode_type.csv | `pce`,`occ` | passenger-car equivalent, occupancy |
| settings.csv | period, convergence, solver | §7 |

Validate before every run: `python -m dtalite_qa check <scenario>`.

---

## 3. VDF library — pick the agency's volume-delay function

`x = v/c` (per-lane). All VDFs share the **cost-based** Frank-Wolfe line search, so any
monotone form is solved exactly (no per-VDF calibration of the solver).

| `vdf_type` | form | used by |
|---|---|---|
| **0** BPR | `t0(1 + α·x^β)` | TRPA, ODOT, VDOT, MTC |
| **0+`vdf_A`** modified BPR | `t0(1 + A·x + α·x^β)` | **ARC** |
| **1** conical (Spiess) | `t0(2 + √(a²(1−x)²+b²) − a(1−x) − b)` — parameters from the **explicit `conic_a`/`conic_b` columns** (per facility type; `b=(2a−1)/(2a−2)` derived when absent). A legacy fallback reads a/b from `vdf_alpha/vdf_beta`; it is deprecated and will be rejected in strict mode. | MWCOG, VDOT |
| **2** QVDF (queue) | DTALite queue VDF (`vdf_cp/cd/n/s`, `cutoff_speed`) | DTALite-native |
| **3** BPR2 | exponent doubles for x>1 | AequilibraE |
| **4** INRETS | `t0(1.1−α·x)/(1.1−x)`, quadratic for x>1 | AequilibraE |
| **5** Akcelik | `t0 + α(z+√(z²+β·x))`, z=x−1 | VDOT-allowed |
| **6** SANDAG-signal | BPR + Webster delay (`cycle_length`,`green_ratio`) | SANDAG |
| **7** SCAG piecewise-BPR | `t0(1 + α·x^e)`, `e=4` below capacity, per-link `β` (5/6/8) at/above; continuous at x=1 | SCAG |
| **8** SCAG ramp-meter | `t0 + (PLPH/120)·5·(1+x)^8 /60` hr→min metered-queue delay | SCAG (facility 82/84) |

Every form above is certified per release by `taplite_selftest`
(`kernel/tests_cpp/`) on hand-computed known values and property checks
(non-negativity, monotonicity, breakpoint continuity).

Per-facility α/β/A come from the agency's FACTYPE×ATYPE table and are written into
link.csv by the converter (not a global setting).

---

## 4. Period capacity & the Peak Load Factor — the #1 pitfall

MPO assignment loads a whole **period** of demand at once, but capacity and the VDF are
per **hour**. The bridge is the **Peak Load Factor (PLF)**. Getting it wrong silently
under-states congestion (worst at night). Full derivation: `docs/peak_load_factor.md`.

- **Identity:** peak hourly demand `D = V_period/(L·PLF)`; hour→period capacity
  expansion `φ = L·PLF`; period capacity `c_period = φ·c_h`. `L` = period length (hrs).
- **Agencies state φ, not PLF.** ARC's "period factor" (AM 3.66) *is* `φ`. So
  `PLF = φ/L` (ARC AM = 3.66/4 = **0.915** — not flat).
- **Kernel mapping (do this):**
  - `capacity` = **hourly** per-lane `c_h` (e.g. ARC `AMCAPACITY/lanes`),
  - `vdf_plf` = **PLF = φ/L**,
  - `demand_period_*_hours` = the period window.
  - ⇒ `DOC = (V/lanes/H/plf)/c_h = D/c_h` exactly.
- **Do NOT** leave `vdf_plf=1` (flat) or feed *period* capacity with `plf=1/H` — both
  hard-code PLF=1 and over-state capacity. **Bounds (enforced):** `0 < PLF ≤ 1`,
  `φ = L·PLF ≥ 1`, advisory floor `0.25`.

Reference factors (φ/L): ARC EA .417 / AM .915 / MD .94 / PM .915 / EV .489
(`dtalite_qa/plf.py:ARC_PHI`); MAG AM .94 / MD .96 / PM .98 / NT .40. Inventory a
network: `python -m dtalite_qa plf <scenario> --period AM`.

---

## 5. Generalized cost & user classes

Per-mode link cost (in minutes): `cost = travel_time + (toll + distance·operating_cost)/VOT·60`.

| requirement | how |
|---|---|
| time + toll + distance·opcost (ARC, SANDAG, MWCOG) | set `vot`, `toll_<mode>`, `operating_cost` |
| time + toll only (SERPM) | `operating_cost=0` |
| time only (TRPA, ODOT) | `toll=operating_cost=0` |
| per-class PCE (truck 1.3–2.5) | `pce` (truck volume weighted into v/c) |
| occupancy / person metrics | `occ` (PMT/PHT in `link_performance.csv`) |
| per-class VOT (ARC $21.5/$36; SERPM $15/$12) | `vot` per mode |
| toll-eligible split (SOV_NT vs SOV_TR) | separate demand classes + toll on the tolled class |

One `demand_<class>.csv` + `mode_type.csv` row per user class.

---

## 6. Managed lanes, HOV, and restrictions

`allowed_use` is per-mode with dedicated shortest paths (`dedicated_shortest_path=1`):
empty/`all` = all modes; `hov2;hov3` = HOV-only; `trk` = truck-only/closed-to-autos.
**Tolling is a cost, not an access ban** — managed lanes still *allow* the tolled class
(via `toll_<mode>`), just at higher cost. The converter maps each agency's coding
(ARC `PROHIBIT` 2/6/11→HOV, 4/10→truck; SANDAG `HOV`+`TOLL`; MTC `USE`/`FT8`) into
`allowed_use` + toll.

**Turn restrictions (`movement.csv`) are bans-only:** a movement row with
`penalty >= 10` hard-bans that turn (exact link-state search); **`penalty < 10` is
currently IGNORED — there are no graded/soft turn penalties yet** (planned; see
WORK_PACKAGES WP-12). Don't encode vendor-style seconds-per-left-turn tables and
expect them to apply.

---

## 7. Convergence & the solver

| setting | meaning | agency targets |
|---|---|---|
| `number_of_iterations` | max FW iterations | — |
| `convergence_gap_pct` | stop when relative gap% < this | ARC/SERPM `0.01` (=1e-4) |
| `convergence_consecutive` | gap below target for N **consecutive** iters | ARC/SERPM `3` |
| `relative_gap_standard` | `0` legacy (/AoN total) · `1` AequilibraE (/current total) | use `1` for agency-comparable 1e-4 |
| `assignment_method` | `0` FW · `1` conjugate FW · `2` **bi-conjugate FW** | ARC/MWCOG/VDOT recommend BFW |
| `number_of_processors` | OpenMP threads | — |

**Bi-conjugate FW (`assignment_method=2`)** closes the gap faster on stiff/congested
regional networks (Chicago Regional: iter-24 gap FW 1.43% → BFW 0.59%, same UE) at no
extra wall-time — recommended for large MPO runs. It falls back to plain FW automatically
when a step would be infeasible, so it is always safe.

---

## 8. Time of day

Run **one assignment per period** (separate scenario folders), each with its own demand,
period lanes, period capacity factor (`vdf_plf=φ/L`), and tolls. Periods: ARC/MTC/SANDAG
5 (EA/AM/MD/PM/EV); MWCOG/VDOT/TRPA 4. Set `demand_period_starting_hours` /
`demand_period_ending_hours` to the window.

---

## 9. Validation against agency targets

`link_performance.csv` carries `volume`, per-class `mod_vol_*`, `ref_volume`, speed, v/c
(`doc`), VMT/VHT. Compare to counts / `ref_volume`:

- **%RMSE by volume group** vs the agency table (ARC: <2.5k 100% · 5–10k 45% · 10–25k 30%
  · 25–50k 25% · ≥50k 19%; region ~38%).
- **R²** (VDOT 0.90 large / 0.92 small; ODOT ≥0.90).
- **VMT by functional class** (VDOT ±7–25%; ARC arterial+ within ~6%).
- Screenline/cutline ratios (VDOT ±5–10%); speed deviation (>5 mph flag).

Example scorer: `private/ARC_Atlanta/arc_validate_run.py` (%RMSE by volume group vs the
agency reference) — generalize per agency.

---

## 10. Per-agency quick reference

| agency | VDF | gap target | solver | gen. cost | VOT | PCE | periods |
|---|---|---|---|---|---|---|---|
| **ARC** | mod-BPR + `vdf_A` | 1e-4 ×3 | BFW | t+toll+dist | $21.5 / $36 | MTK 1.5 / HTK 2.0 | 5 |
| **SERPM 8** | mod-BPR | 1e-4 ×3 | FW | t+toll | $15 / $12 | — | 5 |
| **TRPA** | BPR | 1e-4 Δvol | (MSA cap-restraint) | time only | — | — | 4 |
| **MTC** | BPR (4/3-shift) | n/s | (Cube) | toll-classes | n/s | — | 5 |
| **SANDAG** | BPR + signal (`type 6`) | 5e-4 | (SOLA / FW) | t·VOT+toll+op | income-based | 1.3/1.5/2.5 | 5 |
| **MWCOG** | conical (`type 1`) | 1e-2→1e-4 | BFW | t + cost | min/$ | n/s | 4 |
| **VDOT** | BPR / conical / Akcelik | 1e-4 | BFW | — | — | — | ≤4 |
| **ODOT** | BPR | n/s | (Visum) | time only | n/s | — | daily+PM |

Set `vdf_type` + per-facility α/β/A in link.csv, `vdf_plf=φ/L`, the mode `vot/pce/occ/
operating_cost`, `allowed_use`/tolls, and the `convergence_*` / `assignment_method`
settings from this row.

---

## 11. Performance at scale

- **Binary demand** — `python -m dtalite_qa demand-bin <scenario>` + `demand_format=1`:
  removes CSV parse cost on million-OD regional matrices.
- **Bi-conjugate FW** (`assignment_method=2`) — fewer iterations to a tight gap on stiff
  networks (§7).
- **Super-zone aggregation** — `dtalite_qa/superzone_hier.py` + `superzone_encoders.py`:
  fast *approximate* runs (Chicago Regional 5× compression → 5× faster, R² 0.87; ARC
  1,500 super-zones → 2.2× faster and **still passes agency validation**). The N×N
  original-resolution **skim** for the 4-step feedback loop is recovered afterward with
  `dtalite_qa/skim.py`. See `docs/superzone_design_principles.md`,
  `docs/four_step_integration.md`.

---

## 12. Worked example — ARC Atlanta AM (validated)

The end-to-end recipe that reproduced ARC's AM assignment within the agency's own
validation tolerance:

1. **Convert** the ARC network → GMNS, writing per-FACTYPE VDF (`vdf_alpha/beta/vdf_A`),
   `capacity = AMCAPACITY/lanes` (hourly), `ref_volume = V_SOVAM+V_HOV2AM+V_HOV3AM`,
   `allowed_use` from `PROHIBIT`.
2. **Set the period/PLF/cost:** `demand_period 6→10` (H=4), **`vdf_plf = 3.66/4 = 0.915`**,
   `vot=21.5`, `operating_cost=0.1729`.
3. **Solve to equilibrium:** `convergence_gap_pct=0.5, convergence_consecutive=3`
   (or `assignment_method=2` for BFW). Converged at iter 10.
4. **Validate:** region-wide %RMSE **22%** (target ~38%), all volume groups pass,
   assigned/ref total = 1.00. *(Re-baselined 2026-07 from 23% after the Dijkstra-default
   and standardized-gap kernel updates.)*

Scripts: `examples/arc_atlanta/{arc_benchmark.py, arc_calibrate.py, arc_validate_run.py}`;
detail in `examples/arc_atlanta/ARC_BENCHMARK.md` / `README.md`.

---

### See also
- `USER_GUIDE.md` (Volume 1 — kernel reference & input schema)
- `docs/peak_load_factor.md` · `docs/compress_the_response.tex` ·
  `docs/superzone_design_principles.md` · `docs/four_step_integration.md`
- `private/kernel_references/` (multi-agency spec + conformance matrix)
