# Super-zone acceleration on ARC Atlanta — an MPO guide

**This is a Stage-5 "advanced" step.** Do it only **after** the full-resolution ARC run is
trusted (you've done `intake → calibrate → run → validate` and seen region-wide %RMSE ≈ 23%).
Super-zones make the model *faster*, not *better* — use them for scenario sweeps and sketch
planning, never as the model of record.

---

## 1. The idea — compress the response, not the data

A static assignment solves one shortest-path tree **per origin zone, per class, per
iteration**. ARC has 6,031 zones × 3 classes, so most of the run time is those trees. If two
neighbouring zones send traffic onto essentially the **same corridors**, the assignment
doesn't need them as separate origins — it needs their *combined response on the network*.

Super-zones **merge zones that respond alike** into ~K representatives. The **full link
network is kept** (every one of ARC's 145,971 links stays), so link volumes, V/C, VMT/VHT
are still produced at full resolution — only the *origins* are fewer.

> Goal: preserve the **link-flow response** `v = H·d`, not reconstruct the OD matrix.
> See [`../../docs/superzone_design_principles.md`](../../docs/superzone_design_principles.md).

## 2. Run it (after `arc_calibrate.py`)

```bash
python arc_superzone.py 1500          # gmns_calibrated/ -> gmns_superzone/  (~1,431 super-zones)
cp ../../bin/DTALite.exe gmns_superzone/
( cd gmns_superzone && ./DTALite.exe )       # fewer origins => faster
python arc_superzone.py validate gmns_superzone   # %RMSE vs ARC reference (auto-remaps node ids)
```

`K` is the target super-zone count. Smaller K → faster but more approximation; larger K →
closer to full. Build output on ARC at K=1500:

```
zones 6,031 -> super-zones 1,431          (4.2x fewer origins)
links 145,971 + 12,062 super-connectors    (full network preserved)
demand_sov 978,538 -> 356,746 pairs; vol 2,599,725 -> 2,265,000
```

## 3. The trade-off you must understand

Aggregating origins **drops intra-super-zone trips** — trips whose origin and destination
fall in the *same* super-zone no longer load the network (≈13% of SOV volume at K=1500).
That is the price of speed.

**Measured ARC result (K=1,431, AM, 3 classes):**

| | full | super-zone | |
|---|---|---|---|
| origins | 6,031 | 1,431 | 4.2× fewer |
| wall time | 376 s | **192 s** | **~2× faster** |
| region-wide %RMSE vs ARC ref | 22% | 40% | — |

But the region-wide number hides the real behaviour — **super-zones preserve the response
where it matters and trade local detail:**

| ARC volume group | %RMSE | assigned/ref |
|---|---|---|
| 25k–50k (major freeways) | **9%** | 1.08 |
| 10k–25k | **10%** | 1.03 |
| 5k–10k | 21% | 0.91 |
| 2k–5k | 34% | 0.82 |
| 0k–2k (local streets) | 65% | **0.76** |

The **high-volume corridors are still right** (9–10% %RMSE, ratio ≈ 1.0) — those carry most
of the VMT and drive most planning conclusions. The loss is concentrated on **low-volume
local links** (ratio 0.76), exactly where the ~13% dropped intra-super-zone trips would have
loaded. So super-zones are excellent for **corridor-level scenario screening** and poor for
**local-street detail.**

**Tuning:** raise `K` (e.g. 3,000) to cut the intra-zonal loss and lift the low groups, at
less speed-up; or use the demand-aware encoder (§6) so clustered zones genuinely respond
alike. **Always report the dropped intra-zonal share** — never let a compressed run be read
as full-resolution.

## 4. The key advantage — the full-resolution zone-to-zone skim

This is *why* super-zones are worth it. The compressed run uses few origins, but it solves
the **full link network**, so the congested **link travel times are full-resolution**. From
them you recover the complete **original 6,031 × 6,031 zone-to-zone travel-time skim** — the
matrix that 4-step / activity-based models feed back on. **You get the original-resolution
skim at compressed-assignment speed.**

```bash
python arc_skim.py sz        # skim the ORIGINAL network using the super-zone run's link times
                             #   -> arc_skim_from_superzone.csv  (o_zone_id,d_zone_id,travel_time)
python arc_skim.py full      # the same skim from the full run   -> arc_skim_full.csv
python arc_skim.py compare   # full vs super-zone skim: R^2 + mean |Δtime|
```
`arc_skim.py` remaps the super-zone run's node ids back to the original network
(`skim.superzone_remap`) and runs Dijkstra over all 6,031 original centroids
(`dtalite_qa/skim.py`; needs numpy + scipy).

**Measured (ARC AM):** the skim recovered from the **2× faster** super-zone run closely
reproduces the full-run skim over the SOV demand pairs — run `python arc_skim.py compare` to
see the R² and mean |Δtime| on your data.
The zone-to-zone *travel times* hold up far better than the local *link volumes* (§3),
because the major-corridor times — which dominate inter-zonal paths — are preserved. This is
the decoder for loop-integrated demand↔supply feedback (see
[`../../docs/four_step_integration.md`](../../docs/four_step_integration.md)).

## 5. The trust check — the `S = N` corner case

Before believing any compressed run, prove the machinery is exact when it should be:

```bash
python arc_superzone.py identity      # S = N (every zone is its own super-zone)
cp ../../bin/DTALite.exe gmns_identity/ && ( cd gmns_identity && ./DTALite.exe )
python arc_superzone.py validate gmns_identity
```
With one super-zone per zone, **nothing is aggregated**, so the result must reproduce the
full run **exactly** (link-volume R² = 1.000, identical %RMSE). If it doesn't, the
aggregation is broken — stop and fix it before trusting any K. *(Note: `identity` has 6,031
super-zones, so this run costs about the same as the full run — it's a correctness proof,
not a speed-up.)*

## 6. When to use / not use

**Use** for: scenario sweeps (many futures), sketch planning, large regional networks where a
full run is too slow, demand sensitivity. **Don't use** for: the validated model of record,
final agency reporting, small networks (Chicago Sketch doesn't need it), or any result where
the intra-zonal trips matter (very local analyses).

## 7. Going further
- `dtalite_qa/superzone_encoders.py` — smarter clustering than geography (`demand_kmeans`
  groups zones by *demand* similarity; needs numpy + scikit-learn).
- `dtalite_qa/skim.py` — recover a full-resolution zone-to-zone skim from the compressed run
  (the supply→demand decoder for 4-step feedback).
- [`../../docs/superzone_design_principles.md`](../../docs/superzone_design_principles.md) — the P0–P10 design rules.
