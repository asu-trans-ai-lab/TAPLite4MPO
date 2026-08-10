# LDN034_BD — public-source consistency verification (2026-08-09)

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
