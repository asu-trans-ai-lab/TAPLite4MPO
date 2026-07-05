# TAPLite4MPO — Onboarding & Handoff

**Written for Henan and the MAG staff, and for anyone onboarding a new agency model.**
This folder is the *front door* for a new engineer. It doesn't repeat the reference docs —
it gives you the **order to read them, the runs to reproduce, and the issues to understand**
so that when an agency hand-off (shapefile + matrix + "alpha/beta") lands on your desk you
can turn it into a *trustworthy* assignment and know why every number is what it is.

> **The one principle** (from the [Conversion Error Catalog](../docs/CONVERSION_ERRORS_CATALOG.md)):
> onboarding is **model-meaning** conversion, not file-format conversion. GMNS is only the
> container. The assignment is defined by **capacity, period, PLF, units, demand class,
> allowed-use, toll, and the validation target** — and **TAPLite never guesses these.**
> When a run looks wrong, **suspect a convention mismatch, not the solver.**

---

## 0. The three gates (the whole job, in three questions)

1. **Can I run it?** — the kernel builds, the network loads, all zones connect, it converges.
2. **Can I trust it?** — units/capacity/period/PLF/demand/zone-mapping/VDF are *declared*,
   not assumed; it validates against the agency's own count benchmark.
3. **Can I improve it?** — calibrate the VDF, then accelerate (super-zones) without losing
   the corridors that matter.

Everything below is in service of walking a hand-off through those three gates.

---

## 1. Reading path (read in this order)

| # | Read | Why |
|---|---|---|
| 1 | [`docs/GOLDEN_PATH_CHECKLIST.md`](../docs/GOLDEN_PATH_CHECKLIST.md) | the 6-stage path, framed by the 3 gates — the map. |
| 2 | [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) | **the C++ kernel solves; Python only orchestrates.** Know what runs the assignment before you debug one. |
| 3 | [`docs/MPO_ONBOARDING_GUIDE.md`](../docs/MPO_ONBOARDING_GUIDE.md) | the process: declare → convert → **intake audit** → resolve → validate. The intake blocks on anything undeclared. |
| 4 | [`docs/CONVERSION_ERRORS_CATALOG.md`](../docs/CONVERSION_ERRORS_CATALOG.md) | ⭐ **the error-source document.** Every way a hand-off goes wrong (capacity, PLF, units, demand, zones, VDF, truncation, allowed-use, count basis, build) — symptom → cause → fix → *seen in which agency*. |
| 5 | [`BPR_AND_VDF_CONFIG_RULES.md`](BPR_AND_VDF_CONFIG_RULES.md) | **this folder** — the BPR/VDF/PLF/capacity **configuration rules & conditions card**: which `vdf_type`, which α/β, when PLF is flat, per-lane vs total capacity. The rules you apply on every model. |
| 6 | [`USER_GUIDE_VOL2_MPO.md`](../USER_GUIDE_VOL2_MPO.md) | the kernel mechanics for MPOs: VDF library (§3), period capacity/PLF (§4), generalized cost (§5), convergence (§7), per-agency quick reference (§10). |
| 7 | [`docs/peak_load_factor.md`](../docs/peak_load_factor.md) | the φ = L·PLF derivation — the single most misapplied convention. |
| 8 | [`docs/superzone_design_principles.md`](../docs/superzone_design_principles.md) | P0–P10 rules for compressing the assignment (the *response*, not the data). |
| 9 | [`docs/mpo_spec/`](../docs/mpo_spec/) | the design spec + the **multi-agency conformance matrix** (ARC, SERPM, TRPA, MTC, SANDAG, MWCOG, VDOT, ODOT): requirement → kernel feature → how to verify. |

## 2. Reproduction path (run these, in this order)

Build the kernel once (`bash build.sh` → `bin/DTALite.exe`), then:

| # | Run | What it teaches |
|---|---|---|
| 1 | `kernel/data_sets/02_Sioux_Falls` (copy the exe in, `./DTALite.exe`) | the kernel loads node/link/demand/settings and writes `link_performance.csv`. The smallest complete loop. |
| 2 | `python test_networks/run_regression.py` | BPR / conical / QVDF, multiclass, turn restrictions all produce the reference outputs — proves your build is sound. |
| 3 | [`examples/arc_atlanta/`](../examples/arc_atlanta/) — `README.md` then `arc_calibrate.py` → run → `arc_validate_run.py` | **the flagship.** A real MPO hand-off end-to-end: intake → calibrate the VDF → run → validate against ARC's own counts (region %RMSE ≈ 23%). This is the whole job in one folder. |
| 4 | [`examples/arc_atlanta/SUPERZONE.md`](../examples/arc_atlanta/SUPERZONE.md) — `arc_superzone.py 1500` → run → `validate`; then `arc_superzone.py identity` | **super-zones**: ~2× faster, corridors preserved, and the `S=N` corner case that *must* reproduce full exactly. Plus the full-resolution skim (`arc_skim.py`, R²=0.9985). |
| 5 | [`REPRODUCE_THE_ISSUES.md`](REPRODUCE_THE_ISSUES.md) — **this folder** | a hands-on **lab**: deliberately trip each classic failure (capacity basis, period-vs-daily, flat PLF, VDF defaults) on the open networks and watch `intake` catch it. See the symptom, apply the fix. |

## 3. The issues to understand (and the agencies where we hit them)

Read these as the catalog's [Master table](../docs/CONVERSION_ERRORS_CATALOG.md#master-table);
here is the "which agency taught us this" index so you recognize a symptom fast:

| Issue | Where it bit us | One-line rule |
|---|---|---|
| **Capacity basis** — total written to a per-lane field | **SCAG** (`AB_HRCAPAC` is all-lane) | `capacity = total_hourly / lanes`. |
| **Capacity period** — daily used as hourly | **GSATS** (`AB_CAP` daily → V/C ≈ 0.007) | declare `capacity_period` + the exact column. |
| **Flat PLF** on a multi-hour period | **ARC, AZTDM** | `φ = L·PLF`; use the *real* PLF, not 1. |
| **Period vs daily reference** — slope ≪ 1 that looks like 5× under-assignment | **SCAG** (freeway β=0.18 = the AM/daily fraction) | compare like-to-like; sum periods or use period-specific reference fields. |
| **Units** — metres-as-miles (×1609), km/h-as-mph (×1.6) | all | emit `vdf_length_mi`, `vdf_free_speed_mph`; declare units. |
| **Person vs vehicle** demand + occupancy/mode split | **SCAG** (CT-RAMP person trips; drop non-auto) | declare `demand_kind` + per-class occupancy. |
| **Demand truncation** (Excel 1,048,575-row cap) | **AZTDM** (~85% origins dropped) | stream from source; never round-trip a big matrix through Excel. |
| **Zone-ID mapping** — centroid id ≠ zone id; multi-tier TAZ | **GSATS** (renumber 1..721), **SCAG** (tier-2 vs tier-1) | `node_id == zone_id` for centroids; build the TAZ correspondence. |
| **DBF 255-field / 10-char truncation** dropped the join field | **SCAG** (`T2TAZ`/`ccportzone` truncated away — *this was the demand blocker*) | ask the agency for the dropped field as a companion CSV. |
| **VDF defaults** vs the agency's calibrated curve | **ARC** (0.15/4 → 88% RMSE; per-FACTYPE → 23%), **SCAG** (piecewise β=5/6/8) | take α/β *and the form* from agency docs; steep β needs bi-conjugate FW + ≥40 iters. |
| **allowed-use vs toll** — access is not cost | **ARC** (`PROHIBIT` codes) | separate `allowed_use` (feasibility) from `toll_*` (generalized cost); find the VOT. |
| **Wrong count field** — a code, not a count; wrong scenario/period | **SCAG** (`AB_OBSERVE` is a flag; 2050PL vs 2050BL) | declare + match `count_field`; judge with VMT/VHT/speed, not just β/R². |
| **Build** — wrong g++ toolchain segfaults | all | build via the project cmake/MinGW toolchain; keep console output ASCII. |

**The worked real-world case study is the SCAG model** — the full narrative (network built, tier-2
zone correspondence resolved, VDF cleared, and the *open* "missing volume" question) lives in
[`private/SCAG/README.md`](../private/README.md) (agency data is not in the public repo — see §5).

## 4. The order to check when a run looks wrong

1. **units** (length, speed) — cheapest, catches 1609× and 1.6×.
2. **period & PLF** — is `H` right, is PLF flat, is the reference the same period?
3. **capacity** — per-lane? hourly? sane per-lane values by facility (freeway ≈ 1800–2000)?
4. **demand** — vehicles vs persons, class split, not truncated?
5. **zone mapping** — centroid ids, matrix labels, link sort.
6. **VDF** — agency curve, converged (bi-conjugate FW for stiff β)?
7. **allowed-use / toll** — access vs cost, VOT.
8. **then** the count/reference basis — and only then suspect demand or the solver.

## 5. Where agency data lives (private)

Real agency networks and matrices are **restricted** and are **never committed**. The repo's
`.gitignore` keeps everything under `private/` and `private_docs/` out of Git (only their
`README.md` is tracked). Each agency model gets its own **private subfolder** with a
case-study `README.md` documenting exactly which conventions it used and which issues it
raised — e.g. [`private/SCAG/`](../private/README.md). Reproduce those runs by pointing the
scripts at your own copy of the data (same pattern as `nvta_run/`, README §6).

---

**Start at §1 row 1, keep the [error catalog](../docs/CONVERSION_ERRORS_CATALOG.md) open in a
second tab, and run the ARC example (§2 row 3) as soon as your kernel builds.**
