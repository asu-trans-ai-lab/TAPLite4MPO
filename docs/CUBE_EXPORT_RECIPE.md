# Cube → GMNS export recipe
*For Cube/Voyager modelers. The worked reference is the ARC Atlanta flagship
(`examples/arc_atlanta/` — a complete Cube-origin reproduction validated to 22% region
%RMSE against the agency's own counts); this recipe generalizes what that example did.*

---

## 1. What to export

**Network (.net).** Export the highway network to shapefile or DBF via *File ▸ Export* in
Cube (or NETWORK step `FILEO LINKO` to a DBF). Cube networks are usually **already
directed** (one record per direction, `A`/`B` node fields) — no AB/BA split needed; just
drop links closed in your assignment period (e.g. `AMCAPACITY = 0` on a real network
flagged period-closed links that must not enter the AM run).

**Matrices — export to OMX.** Cube 6.4+ reads/writes OMX (`FILEO MATO[1]=...omx` or the
matrix converter). One file per period × class (SOV/HOV2/HOV3/truck) with the zone
mapping embedded — this is the standard hand-off. Fallback on older Cube: MATRIX step
`FILEO MATO` to CSV plus the zone-ID vector. Avoid Excel round-trips (row cap —
catalog §4c); do NOT ship binary `.mat`.

**The assignment documentation.** Cube models keep the model *meaning* in the scripts
and the documentation, not the .net: the VDF form + per-FACTYPE α/β table, the **period
factor** (hours of effective capacity per period), VOT and operating cost, and the
access-code table. ARC publishes these as "Section 7 — Trip Assignment"; **every Cube
agency must ship its equivalent.**

## 2. Field crosswalk (ARC-style)

| GMNS link.csv | Cube field | Conversion |
|---|---|---|
| `from_node_id`,`to_node_id` | `A`,`B` | already directed |
| `lanes` | `LANES` / period lanes | |
| `capacity` | `AMCAPACITY`/`CAPACITY` | **check basis**: ARC's `AMCAPACITY/LANES` ≈ hourly LOS-E per-lane — divide by lanes if total; declare hourly vs period |
| `vdf_plf` | period factor / period hours | ARC: φ=3.66 over a 4-h period ⇒ `vdf_plf = 0.915` — **not** 1.0 (catalog §2a) |
| `free_speed`+`vdf_free_speed_mph` | `SPEED` (mph) | emit both |
| `length`+`vdf_length_mi` | `DISTANCE` (mi) | ×1609.344 / as-is |
| `vdf_alpha`,`vdf_beta`,`vdf_A` | per-FACTYPE table | ARC's modified BPR `t=t0(1+A·x+D·x^B)` maps to kernel `vdf_A` + `vdf_alpha/beta` (vdf_type 0); flat defaults gave 88% RMSE, the agency table 22% |
| `allowed_use` / `toll_<mode>` | `PROHIBIT`-style codes | code table → access vs toll: e.g. 2/11 = HOV-only → `allowed_use=hov2;hov3`; 4/10 = truck-only; 3/7-9/12-13 = tolled (open + `toll_*`), catalog §8 |
| capacity adjustments | `WEAVEFLAG` etc. | apply documented factors (ARC: cap ×0.98^(lanes−1) when lanes>4) |
| `org_link_id` | link `ID` | keep for validation joins |

Zones/centroids: FACTYPE 0 (or the agency's connector code) → `link_type=100`,
`capacity=99999`; centroid `node_id == zone_id`, compact 1..Z.

## 3. Cube-specific pitfalls

1. **The period factor is not the period length.** ARC's AM is 4 hours but φ=3.66; using
   H alone under-states peak congestion ~9% (catalog §2a).
2. **PROHIBIT-style codes mix access and cost** — split them; a tolled managed lane is
   *open* to SOV at a price, not closed (catalog §8).
3. **Validation columns live on the loaded network** (`V_SOVAM+V_HOV2AM+...`): declare
   the exact expression as `count_field`, and match the **period** of the run (never AM
   assignment vs daily counts — catalog §2b).
4. **Catalogs/alternatives**: Cube scenario catalogs have no GMNS equivalent yet — one
   scenario folder per alternative; the run-manifest + `diff` tooling compares them.

## 4. Declare (`submission.yml`)

The ARC example ships the model declaration: see
[`examples/arc_atlanta/gmns/submission.yml`](../examples/arc_atlanta/gmns/submission.yml)
— copy its structure. The must-declares: capacity basis+period (+source field), period
definition + **period factor** (⇒ `vdf_plf`), units, demand kind per class, VDF form +
table source, access-code table, `count_field` (+ its period).

*See also:* [CONVERSION_ERRORS_CATALOG.md](CONVERSION_ERRORS_CATALOG.md) ·
[TRANSCAD_EXPORT_GUIDE.md](TRANSCAD_EXPORT_GUIDE.md) · [VISUM_TO_GMNS.md](VISUM_TO_GMNS.md) ·
[peak_load_factor.md](peak_load_factor.md) · the flagship: `examples/arc_atlanta/README.md`
