# Teaching Guide — Understanding an Agency Model Through One Dataset

**Dataset:** LDN034_BD, a 28-link / 7-zone directional subarea extracted from
a real regional travel model. Small enough to open every file in Excel;
complete enough to contain every concept of the full agency workflow.

**Who this is for:** a student or new team member who must understand what a
travel-model handoff actually contains BEFORE writing any code.

**The one rule this guide teaches:** *a model is defined by its conventions
(capacity basis, periods, classes, restrictions, functional forms, identity),
not by its file formats. "The program ran" never means "the model is right."*

---

## 0. Scope — what you can and cannot learn here

| In scope (this dataset demonstrates it) | Out of scope (needs the regional model) |
|---|---|
| Source GIS → open network conversion | Regional runtimes/memory behavior |
| Directional links, node identity, zones | Screenline/corridor count validation |
| Multi-period supply (AM/MD/PM/NT fields) | Multi-period assignment sequencing |
| Six demand classes with class VOT | Toll/managed-lane policy analysis |
| Conical + BPR volume-delay functions | QVDF calibration |
| Reference-volume verification (per class) | Observed-count validation |
| Round-trip identity (the LINKID trap) | — |

## 1. Inventory first — never run anything yet (Day 1)

Open each file and answer the questions in writing:

| File | What it is | You must be able to answer |
|---|---|---|
| `SubArea_NTWK_LDN034_LL.shp/.dbf` (public source repo) | the agency GIS network, 28 features × 112 attributes | Which fields are identity? Which are per-period? Which do you NOT understand? (List them — do not guess.) |
| `AM/MD/PM/NT_SubArea.OMX` (source repo) | period demand matrices, 6 class cores each | What are the six classes? What does each core sum to? |
| `link_bpr.csv` / `link_qvdf.csv` (source repo) | VDF parameter tables keyed by `vdf_code` × period | Why are there FOUR plf/alpha/beta columns per row? |
| `link.csv` (this folder) | the converted TAPLite network | Which columns came from the source, which were derived, which are TAPLite outputs? |
| `demand_*.csv` (this folder) | converted per-class demand | Does each file's total match its OMX core? (It must — verify, don't trust.) |
| `mode_type.csv` | the class contract | Why does hov3 have VOT $60 and occupancy 3.5? |
| `configuration.yml` | the run contract | What period is active? What is claimed about the VDF family? |

**Checkpoint Q1:** the shapefile has 112 fields; the converted link.csv has
fewer canonical fields plus passthrough. Name three fields that were
*mapped*, three that were *derived*, and three that were *passed through*.

## 2. The identity lesson — the LINKID trap (Day 1)

Count rows and unique IDs in link.csv: **28 rows, 24 unique `link_id`s.**
Cube LINKIDs 32633/32634 are each split across three segments sharing one
business ID.

**Exercise:** merge `link.csv` with `link_performance.csv` on `link_id` and
sum volumes. Then do it row-aligned. Explain why the answers differ.
**Lesson:** business identifiers are not record identifiers. Every join in
this workflow uses a persistent record identity, never the agency's link
number. (This is why the adapter creates `source_record_id`.)

## 3. The capacity lesson — three numbers that look alike (Day 2)

The source carries, per period: hourly PER-LANE capacity, hourly LINK
capacity (= lanes × per-lane), and a period V/C. Verify with a calculator on
one freeway link:

- `capacity_hourly_link_P == lanes_P × capacity_hourly_per_lane_P` — does it
  hold?
- `source_vc_P ≈ source_volume_P / capacity_hourly_link_P`? **It does NOT.**
  Compute the multiplier that makes it hold, per period.

**Checkpoint Q2:** you should find period multipliers near AM≈2.4, MD≈5.7,
PM≈3.4, NT≈6.7. What do these numbers mean physically? (Answer: effective
capacity-hours of the period — period duration × a peaking factor. The
`link_bpr.csv` table's `VDF_plf1 = 0.417 = 1/2.4` is the same fact from the
other direction.) **Lesson: never assume period capacity = duration ×
hourly capacity.**

## 4. The functional-form lesson (Day 2)

This network runs the **Spiess conical** VDF on 20 links (explicit
`conic_a`/`conic_b` columns, by facility type) and BPR on 8 connectors.

- Plot t(x) for conic a=15 (freeway) and a=3 (collector) against BPR
  α=0.15/β=4 for x ∈ [0, 2]. Where do they differ most?
- Verify by hand: conic at x=1 gives exactly t = 2·t₀ for ANY a. Check one
  link's numbers.
- **History lesson (read `CONSISTENCY.md`):** this fixture once stored conic
  parameters in the BPR columns (`vdf_alpha/vdf_beta`) with only `vdf_type`
  to disambiguate. Explain how that convention can silently produce a
  ZERO-travel-time link. (This really happened; the strict resolver's RS-1
  finding exists because of it.)

## 5. Run it — and know what you claimed (Day 3)

```bash
python -m dtalite_qa.resolve configuration.yml --strict   # the claim gate
./TAPLite.exe                                             # the assignment
```

The resolver prints the MODEL RESOLUTION AUDIT: 20 conical + 8 BPR,
`conic_fallback = 0`. If you cannot explain every line of that audit, stop.

**Checkpoint Q3:** what would the audit say if `vdf_type` were missing?
(Try it on a COPY: delete the column, rerun with `--strict`, read finding
RS-3. Restore the copy.) That failure mode, at regional scale, once cost
weeks.

## 6. Verify against the reference — per class, correctly keyed (Day 3)

The link file embeds the agency model's own assigned volumes per class
(`cube_ref_vol_sov` … `cube_ref_vol_apx`). Compare your run:

- Row-aligned (lesson 2!), per class, links with reference > 0.
- Expected results (frozen kernel, 20 iterations): total R² ≈ 0.996;
  per-class R²: sov 0.997, hov2 0.981, hov3 0.976, com 0.997, trk 0.998,
  apv 0.9999; total volume within ~3%.
- **Checkpoint Q4:** if you compared your (multiclass) total against ONLY
  the SOV reference — or vice versa — what ratio would you see, and why is
  it meaningless? (The earlier SOV-only version of this fixture made
  exactly that mistake possible.)

## 7. The round trip — give the analyst their shapefile back (Day 4)

```python
from dtalite_qa import gis_adapter as ga
wide, man = ga.import_network("SubArea_NTWK_LDN034_LL.shp",
                              "adapters/cube_wide_periodic.json", "out/")
# ... run ... then:
ga.export_results("out/", results, "out/results.gpkg")
ga.round_trip_gate("out/", "out/results.gpkg")   # must PASS
```

Open the GPKG in QGIS/ArcGIS: the ORIGINAL 112 agency fields are intact,
your `tap_*` results sit beside them, and two extra tables carry the run
metadata and the field manifest. **Checkpoint Q5:** find, in
`FIELD_MANIFEST.csv`, one field of each class: CANONICAL_MAPPED /
SOURCE_PASSTHROUGH / DERIVED. Why must unmapped agency fields survive?

## 8. Write the memo (Day 4)

One page, addressed to a planner who has never seen TAPLite: what model did
you run (period, classes, VDF family, capacity basis), what did it reproduce
(the per-class table), what is NOT validated by this exercise (see the scope
table — no observed counts, one period), and what you would need for the
regional version. Every number labeled *reference-supplied* or
*derived-by-you*.

---

## The traps in this dataset, deliberately kept

1. **Shared business LINKID** (rows 32633/32634) — the identity trap.
2. **Three capacity numbers** that differ by lane basis and period factor —
   the conventions trap.
3. **The conic/BPR column history** — the parameter-aliasing trap
   (documented in CONSISTENCY.md; the strict resolver now refuses it).

A student who can explain all three, with numbers, understands more about
agency-model interoperability than most tool users ever will.

## Where this leads

The same eight steps, at 49,000 links with four periods, tolls, and
period-conditional links (a reversible parkway whose links exist only in
some periods), are the regional workflow. Nothing conceptually new is added
— only scale, and the discipline this guide just taught.
