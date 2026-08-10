# CR-0012/0013 - Network Adapter: wide contract locked + GIS round trip

status: COMMITTED (local; NOT pushed)
class:  TOOLING + CONTRACT
author: Claude (AI agent) / approver: Owner (frozen design 2026-08-09)

## CR-0012 - wide contract + resolver locks (Gold-Resolver stage 1)
adapters/cube_wide_periodic.json: the generic Cube wide-periodic profile
with EMPIRICALLY LOCKED derivations (100% x 3 periods x 49k links, run in
the private root): lanes={P}LANE; capacity=per-lane hourly ({P}HRLNCAP,
provably NOT link-total); length=DISTANCE miles; free speed=I4{P}FFSPD;
drop rule = lanes<=0 (limit-9 rows with lanes>0 are KEPT - restriction
lives in allowed_use). VDF staging recorded as DEVIATION-BY-CORRECTION:
the published narrow files carry hand-set alpha/beta + flat plf matching
NO public table (the period table's plf1=0.4170 equals the independently
computed AM inverse factor); authoritative-table confirmation pending.
ref_volume provenance unknown (5-7% vs I4{P}VOL) - flagged.

## CR-0013 - GIS round trip (gates PASS)
dtalite_qa/gis_adapter.py: import emits wide_link.csv +
source_snapshot.parquet + FIELD_MANIFEST.csv + IMPORT_MANIFEST.json;
source_record_id = sha1(dataset|layer|A|B|source_link_id|fid) persisted,
ALL exports join on it; GPKG = self-contained fidelity package (links +
taplite_run_metadata + taplite_field_manifest tables); SHP =
compatibility bundle (+SHAPE_FIELD_MAP.csv + manifest sidecars);
round_trip_gate = semantic (IDs + geometry tolerance + CRS), never byte.
Evidence (public Gold-LDN-RT case, 28 features x 112 fields, 68
passthrough, EPSG:4269): GPKG gate PASS, SHP gate PASS, geometry offset
0.0. GIS deps via pip install taplite4mpo[gis]; no runtime install.
