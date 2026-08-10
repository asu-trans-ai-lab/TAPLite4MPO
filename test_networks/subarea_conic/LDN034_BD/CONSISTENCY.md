# LDN034_BD — public-source consistency verification (2026-08-09)

**Classification (owner ruling): Gold-LDN-RT-Public — adapter / identity /
field-manifest / GIS round-trip gold.** NOT a full numerical assignment
gold: the public source has no frozen narrow files, no expected assignment
outputs, no NB scenario, and no license file, so it cannot validate the
complete conversion→assignment→postprocessing chain by itself. The
per-class reproduction below is a CONSISTENCY check against references
embedded in this owner-authorized converted fixture — full-result
reproducibility claims await the private E2E gold (Gold-NVTA-E2E-Private).
The wide-contract teaching artifact for this dataset covers all FOUR
periods (AM/MD/PM/NT) per the source.

Verified against the PUBLIC source repository `Mmdabb/DTALite4Cube`
(`DTALite4Cube/LDN034_BD`): subarea shapefile + four period OMX matrices +
vdf-code parameter tables. No license file in that repo → per policy the
payload is NOT redistributed here; this fixture carries only the derived
28-link staging that already lived in this repo, now provenance-verified.

## Chain verified

1. **Demand**: fixture `demand.csv` total 6,324 == public `AM_SubArea.OMX`
   core `AM_SOVs` sum 6,324.1 (exact; SOV-only staging by design — the OMX
   also carries HV2/HV3/COM/TRK/APV cores for a future multiclass gold).
2. **Assignment** (frozen kernel `ab9bd2e`, 20 it, AM 6–9): SOV volumes vs
   `cube_ref_vol_sov` on all 28 links — **R² 0.9964, total +2.9%,
   82% within ±10%** (historical subarea criteria: R²≥0.95 ✓, band≥70% ✓).
3. **Identity finding (real-world FA-1 case)**: rows 32633/32634 are
   multi-segment chains sharing one Cube business LINKID → `link_id` is NOT
   unique in this fixture (28 rows / 24 unique). Do not merge on link_id;
   the wide-contract `source_record_id` design exists precisely for this.
4. **Staging debt**: vdf_type=1 links use the deprecated alpha/beta conic
   fallback (no explicit `conic_a/conic_b` columns) — flagged RS-1 by the
   strict resolver; migration to explicit columns is queued.

Comparison method note: row-aligned (kernel preserves input row order);
never merge this fixture on link_id.

## Multimodal upgrade + conic migration (2026-08-09, owner-authorized public release)

Owner decision: this SUBAREA is released as a public teaching example (full
configuration + TAPLite GMNS CSVs + converted demand); the full regional
model remains private.

- **Six demand classes** converted from the public OMX cores with the
  verified sorted-TAZ zone mapping: sov 6,324.1 / hov2 703.9 / hov3 343.0 /
  com 786.9 / trk 904.2 / apv 45.4. Regional-consistent mode_type (VOT
  24/40/60/30/30/30; occ 1/2/3.5/1/1/1.6; dedicated shortest paths).
- **Conic staging migrated to explicit `conic_a`/`conic_b` columns** on all
  four subarea fixtures (the deprecated alpha/beta fallback retired here);
  `vdf_alpha/vdf_beta` now carry BPR-family values only. Strict resolver:
  PASS (20 conical, 8 BPR, conic_fallback = 0).
- **Per-class reproduction vs Cube references** (frozen kernel, 19 it,
  AM 6–9): TOTAL R² 0.9963 ratio 1.028 (79% within ±10%) · sov 0.9971 ·
  hov2 0.9805 · hov3 0.9762 · com 0.9967 · trk 0.9976 · apv 0.9999.
