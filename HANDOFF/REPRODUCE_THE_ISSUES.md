# Reproduce the issues — a hands-on lab

**Goal:** don't just *read* the [Conversion Error Catalog](../docs/CONVERSION_ERRORS_CATALOG.md)
— **trip each classic failure yourself** on the open benchmark networks, watch the symptom
appear, and watch `intake` catch it. After this lab the symptoms are muscle memory: you'll
recognize "V/C ≈ 0.007" or "slope 0.18, high R²" in one glance.

**Prereqs:** `bash build.sh` (→ `bin/DTALite.exe`) and `pip install -e .`. Everything here uses
the **open** networks (`kernel/data_sets/`, `examples/arc_atlanta/`) — no agency data needed.
Work on **copies** so you never edit the reference inputs.

> Each lab = **break it → observe → fix → confirm**. The observation column is what you're
> training your eye on.

---

## Lab 0 — the intake audit is the safety net (do this first)

```bash
python -m dtalite_qa intake kernel/data_sets/02_Sioux_Falls
```
Read the issue report. Note the severity ladder — **BLOCKER** (run can't be correct),
**DECISION** (risky default, you must choose), **MISSING** (safe default applied), **INFO**.
The whole philosophy: *anything undeclared becomes a blocking issue that names the field.*
Every lab below is a thing intake is built to flag before it costs you a week.

## Lab 1 — capacity basis (total written as per-lane) → Catalog §1a

The #1 source of wrong answers. The kernel reads `capacity` as **per-lane**.

1. Copy a scenario: `cp -r kernel/data_sets/03_chicago_sketch /tmp/cap_lab`.
2. In `/tmp/cap_lab/link.csv`, **multiply `capacity` by `lanes`** (simulating a total-capacity
   field written straight into the per-lane column).
3. Run both: `( cd /tmp/cap_lab && cp <repo>/bin/DTALite.exe . && ./DTALite.exe )` and the
   original.
4. **Observe:** in `link_performance.csv`, median **V/C collapses** and free-flow-ish speeds
   rise; freeways "never congest." That is the exact SCAG signature (per-lane 7200 on a
   freeway).
5. **Fix & confirm:** `capacity = total / lanes`; V/C returns to a sane 0.6–0.9 at the peak.

**Eye-training:** freeway per-lane capacity should be **1800–2000**. Anything ≫2000 per lane
is a total masquerading as per-lane.

## Lab 2 — capacity period (daily used as hourly) → Catalog §1b

1. In another copy, **multiply `capacity` by ~5** (daily ≈ 5× the peak hour).
2. Run. **Observe:** median **V/C ≈ 0.007** — "no congestion anywhere."
3. The right response is **not** to quietly rescale — it's to **block and ask** which column,
   what duration, what PLF (the GSATS lesson: `AB_CAP` daily vs `AB_CAP_PK` peak).

## Lab 3 — Peak Load Factor (flat vs real) → Catalog §2a, `peak_load_factor.md`

1. Inventory the PLF the kernel would use:
   `python -m dtalite_qa plf examples/arc_atlanta/gmns_calibrated --period AM`
   (φ/L for ARC AM = 3.66/4 = **0.915**).
2. In a copy, set every `vdf_plf = 1` (flat).
3. Run and compare `link_performance.csv`. **Observe:** peak congestion **under-states** — mild
   at AM, and it would be **~2.5× off at night** (NT PLF ≈ 0.40). Flat PLF hides the peak.
4. **Fix:** `vdf_plf = φ/L`. **Red-flag drill:** if `VDF_cap` scales exactly as period length
   (3:6:3:12 for AM:MD:PM:NT), it was built flat — it needs the real PLF.

## Lab 4 — VDF defaults vs the agency curve → Catalog §6

This is the ARC flagship's whole point — run it and read the numbers.

```bash
cd examples/arc_atlanta
# (a) the calibrated per-FACTYPE modified-BPR run (the reference recipe)
python arc_calibrate.py && cp ../../bin/DTALite.exe gmns_calibrated/ && ( cd gmns_calibrated && ./DTALite.exe )
python arc_validate_run.py           # region %RMSE ~23%
```
**Observe:** the calibrated VDF lands at ~**23%** %RMSE vs ARC counts. Now imagine (or edit a
copy to) flat `0.15/4` — the catalog records that as **88%**, dominated by the top volume
group. **Lesson:** the VDF *form and per-facility α/β* are the model, not a default.
**Stiffness drill:** with a steep β (≥6), check `system_performance.csv` gap — if it's loose
at 20 iters, set `assignment_method = 2` and raise iterations to ≥40 (SCAG needed this).

## Lab 5 — period vs daily reference (the slope-0.18 trap) → Catalog §2b

You can't fully reproduce this without an agency reference, but you can **see the mechanism**:
1. Assign **one period** (AM) and regress link volume against a **daily** reference column.
2. **Observe:** a clean, **high-R²** fit with **slope ≈ the AM/daily fraction** (SCAG freeway
   β=0.18). It *looks* like 5× under-assignment; it's pure period scaling.
3. **Fix:** compare like-to-like — sum all periods to daily (SCAG freeway β → **0.94, R²=0.91**),
   or use the reference's period-specific field. **Never** rescale a daily reference by one
   scalar (the period share differs by facility).

## Lab 6 — super-zone correctness gate (`S = N` must be exact) → `superzone_design_principles.md` P6

Before trusting *any* compressed run, prove the machinery:
```bash
cd examples/arc_atlanta
python arc_superzone.py identity          # S = N: every zone is its own super-zone
cp ../../bin/DTALite.exe gmns_identity/ && ( cd gmns_identity && ./DTALite.exe )
python arc_superzone.py validate gmns_identity
```
**Observe:** with nothing aggregated, the compressed result must reproduce the full run
**exactly** (link-volume R² = **1.000**, identical %RMSE). If it doesn't, the aggregation is
broken (a through-node or connector-cost bug) — fix it before believing any `K`.
Then run a real compression (`arc_superzone.py 1500`) and confirm the corridors hold (9–10%
%RMSE on 25k+ links) while local streets degrade — *and always report the dropped intra-zonal
share.*

## Lab 7 — zone-ID mapping (centroid id ≠ zone id) → Catalog §5

1. **Observe the rule:** the kernel treats a node as a zone **iff `zone_id == node_id`**, and
   sizes arrays by `max(zone_id)`. In a copy, give a centroid a `zone_id` ≠ its `node_id`.
2. **Observe:** that OD row silently fails to load / mismaps. Fix: renumber centroids so
   `node_id == zone_id` (GSATS: 1..721). Multi-tier TAZ (SCAG tier-2 vs tier-1) needs the
   agency correspondence — see [`private/SCAG/`](../private/README.md).

---

## What you should now recognize on sight

| you see… | it's almost certainly… | go to |
|---|---|---|
| median V/C ≈ 0.007 | daily capacity used as hourly | Lab 2 / §1b |
| freeways never congest, speeds too high, VHT low | total capacity in the per-lane field | Lab 1 / §1a |
| high R², slope ≈ 0.2 | one period vs a daily reference | Lab 5 / §2b |
| congestion fine by day, ~2.5× off at night | flat PLF | Lab 3 / §2a |
| top volume group dominates %RMSE | default BPR instead of the agency curve | Lab 4 / §6 |
| loose gap after 20 iters, over-diversion | stiff β needs bi-conjugate FW + ≥40 iters | Lab 4 / §6 |
| compressed run ≠ full at S=N | broken aggregation (through-node/connector) | Lab 6 / P6 |
| big block of demand unmapped | centroid id ≠ zone id, or multi-tier TAZ | Lab 7 / §5 |

**Next:** apply the whole flow to a real hand-off with
[`docs/MPO_ONBOARDING_GUIDE.md`](../docs/MPO_ONBOARDING_GUIDE.md), and keep
[`BPR_AND_VDF_CONFIG_RULES.md`](BPR_AND_VDF_CONFIG_RULES.md) beside you.
