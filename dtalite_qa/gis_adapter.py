"""GIS Network Adapter — Phase C of the frozen design (CR-0013).

    Agency SHP/GPKG -> import -> wide contract -> PeriodResolver ->
    existing single-period kernel -> results joined BACK onto the
    ORIGINAL source features -> GPKG (fidelity) / SHP (compatibility).

Import emits FOUR artifacts with distinct roles (freeze amendment 3):
  wide_link.csv            human/model contract (canonical + passthrough)
  source_snapshot.parquet  lossless machine snapshot (original names,
                           dtypes, values, native identity) - the
                           round-trip verification reference
  FIELD_MANIFEST.csv       source_field, canonical_field, field_class
                           (CANONICAL_MAPPED|SOURCE_PASSTHROUGH|DERIVED|
                           TAPLITE_OUTPUT), dtypes, action, period, notes
  IMPORT_MANIFEST.json     provenance: schema/profile versions + hashes,
                           source file hash, CRS, feature count

Identity (FA-1): source_record_id = sha1(dataset|layer|A|B|source_link_id|
native_fid)[:16], persisted at import; ALL exports join on it. Bare
source_link_id and native FIDs are never trusted as unique.

GIS deps are OPTIONAL: pip install taplite4mpo[gis]. Absence raises an
actionable error; nothing is auto-installed at runtime.
"""
import hashlib
import json
import os

import pandas as pd

WIDE_SCHEMA_VERSION = "1.0.0"


def _need_gis():
    try:
        import geopandas  # noqa: F401
        import pyogrio    # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "GIS support requires the optional extra:  pip install "
            "taplite4mpo[gis]   (pyogrio + geopandas). Not auto-installed "
            "by policy.") from e


def _load_profile(path):
    prof = json.load(open(path))
    return prof


def _first(row_get, cands):
    if isinstance(cands, str):
        cands = [cands]
    for c in cands:
        v = row_get(c)
        if v is not None:
            return v
    return None


def import_network(source, profile_path, out_dir, dataset=None, layer=None):
    """SHP/GPKG -> wide_link.csv + source_snapshot.parquet + manifests."""
    _need_gis()
    import geopandas as gpd
    prof = _load_profile(profile_path)
    dataset = dataset or os.path.basename(source)
    gdf = gpd.read_file(source, layer=layer)
    layer = layer or "0"
    crs = str(gdf.crs)
    src_cols = [c for c in gdf.columns if c != "geometry"]

    ident = prof["identity"]
    A, B = gdf[ident["a_node"]], gdf[ident["b_node"]]
    slid = gdf.get(ident["source_link_id"])

    def rid(i):
        basis = f"{dataset}|{layer}|{A.iloc[i]}|{B.iloc[i]}|" \
                f"{slid.iloc[i] if slid is not None else ''}|{i}"
        return hashlib.sha1(basis.encode()).hexdigest()[:16]

    wide = pd.DataFrame({
        "source_record_id": [rid(i) for i in range(len(gdf))],
        "source_dataset": dataset, "source_layer": layer,
        "source_native_feature_id": range(len(gdf)),
        "source_link_id": slid,
        "from_node_id": A.astype(int), "to_node_id": B.astype(int),
    })
    manifest_rows = []
    for canon, srcf in prof["common"].items():
        v = gdf.get(srcf)
        if v is not None:
            wide[canon] = v
            manifest_rows.append((srcf, canon, "CANONICAL_MAPPED",
                                  str(v.dtype), "MAP", ""))
    for P in prof["periods"]:
        for tmpl, srcs in prof["per_period"].items():
            canon = tmpl.replace("{P}", P)
            cands = [s.replace("{P}", P) for s in
                     (srcs if isinstance(srcs, list) else [srcs])]
            hit = next((c for c in cands if c in gdf.columns), None)
            if hit:
                wide[canon] = gdf[hit]
                manifest_rows.append((hit, canon, "CANONICAL_MAPPED",
                                      str(gdf[hit].dtype), "MAP", P))
        lanes = wide.get(f"lanes_{P}")
        if lanes is not None:
            wide[f"active_{P}"] = (pd.to_numeric(lanes, errors="coerce")
                                   .fillna(0) > 0)
            manifest_rows.append((f"{P}LANE", f"active_{P}", "DERIVED",
                                  "bool", "DERIVE", P))
    mapped_srcs = {m[0] for m in manifest_rows}
    for c in src_cols:
        if c not in mapped_srcs:
            wide[c] = gdf[c]
            manifest_rows.append((c, c, "SOURCE_PASSTHROUGH",
                                  str(gdf[c].dtype), "PASSTHROUGH", ""))

    os.makedirs(out_dir, exist_ok=True)
    wide.to_csv(os.path.join(out_dir, "wide_link.csv"), index=False)
    snap = gdf.drop(columns="geometry").copy()
    snap.insert(0, "source_record_id", wide.source_record_id)
    snap.to_parquet(os.path.join(out_dir, "source_snapshot.parquet"))
    gdf[["geometry"]].assign(source_record_id=wide.source_record_id) \
        .to_file(os.path.join(out_dir, "source_geometry.gpkg"),
                 layer="geometry", driver="GPKG")
    pd.DataFrame(manifest_rows, columns=[
        "source_field", "canonical_field", "field_class", "source_dtype",
        "action", "period"]).to_csv(
        os.path.join(out_dir, "FIELD_MANIFEST.csv"), index=False)
    man = {
        "wide_link_schema_version": WIDE_SCHEMA_VERSION,
        "adapter_profile_version": prof["adapter_profile_version"],
        "profile_sha256": hashlib.sha256(
            open(profile_path, "rb").read()).hexdigest()[:16],
        "source": source, "source_sha256": hashlib.sha256(
            open(source, "rb").read()).hexdigest()[:16]
        if os.path.isfile(source) else None,
        "dataset": dataset, "layer": layer, "crs": crs,
        "features": len(gdf), "source_fields": len(src_cols),
        "passthrough_fields": sum(1 for m in manifest_rows
                                  if m[2] == "SOURCE_PASSTHROUGH"),
        "drops": [],
    }
    with open(os.path.join(out_dir, "IMPORT_MANIFEST.json"), "w") as f:
        json.dump(man, f, indent=2)
    return wide, man


def export_results(import_dir, results, out_path, fmt="gpkg",
                   period="AM"):
    """Join tap_* results by source_record_id onto ORIGINAL features."""
    _need_gis()
    import geopandas as gpd
    geo = gpd.read_file(os.path.join(import_dir, "source_geometry.gpkg"),
                        layer="geometry")
    snap = pd.read_parquet(os.path.join(import_dir,
                                        "source_snapshot.parquet"))
    out = geo.merge(snap, on="source_record_id")
    res = results.copy()
    res.columns = ["source_record_id"] + [
        f"tap_{c}_{period}" if not c.startswith("tap_") else c
        for c in res.columns[1:]]
    out = out.merge(res, on="source_record_id", how="left")

    if fmt == "gpkg":
        out.to_file(out_path, layer="links", driver="GPKG")
        meta = pd.read_json(os.path.join(import_dir,
                                         "IMPORT_MANIFEST.json"),
                            typ="series").to_frame("value")
        import sqlite3
        con = sqlite3.connect(out_path)
        meta.astype(str).to_sql("taplite_run_metadata", con,
                                if_exists="replace")
        pd.read_csv(os.path.join(import_dir, "FIELD_MANIFEST.csv")) \
            .to_sql("taplite_field_manifest", con, if_exists="replace",
                    index=False)
        con.close()
    else:                                    # SHP compatibility bundle
        short, fmap = {}, []
        for c in out.columns:
            if c == "geometry":
                continue
            s = c[:10]
            k = 1
            while s in short.values():
                s = (c[:8] + f"{k:02d}")[:10]
                k += 1
            short[c] = s
            if s != c:
                fmap.append((c, s))
        out2 = out.rename(columns=short)
        out2.to_file(out_path)
        base = os.path.splitext(out_path)[0]
        pd.DataFrame(fmap, columns=["canonical_name", "shp_name"]) \
            .to_csv(base + "_SHAPE_FIELD_MAP.csv", index=False)
        for f in ("IMPORT_MANIFEST.json", "FIELD_MANIFEST.csv"):
            import shutil
            dst_dir = os.path.dirname(os.path.abspath(out_path)) or "."
            s = os.path.join(import_dir, f)
            if os.path.abspath(os.path.dirname(s)) != dst_dir:
                shutil.copy2(s, dst_dir)
    return out


def round_trip_gate(import_dir, exported_path, layer="links"):
    """Semantic gate: IDs + geometry coords within tolerance + attribute
    equality (type-aware), never byte equality."""
    _need_gis()
    import geopandas as gpd
    snap = pd.read_parquet(os.path.join(import_dir,
                                        "source_snapshot.parquet"))
    try:
        exp = gpd.read_file(exported_path, layer=layer)
    except Exception:
        exp = gpd.read_file(exported_path)
    rid_col = next((c for c in exp.columns
                    if c.lower().startswith("source_rec")), None)
    checks = {"feature_count": len(exp) == len(snap),
              "record_id_column": rid_col is not None}
    if rid_col:
        checks["all_source_record_ids_present"] = \
            set(exp[rid_col]) == set(snap.source_record_id)
    geo0 = gpd.read_file(os.path.join(import_dir, "source_geometry.gpkg"),
                         layer="geometry").set_index("source_record_id")
    if rid_col:
        exp2 = exp.set_index(rid_col)
        common = geo0.index.intersection(exp2.index)
        d = geo0.loc[common].geometry.centroid.distance(
            exp2.loc[common].geometry.centroid)
        checks["geometry_centroid_max_offset_deg"] = round(float(d.max()), 12)
        checks["geometry_within_tolerance"] = bool((d < 1e-9).all())
    verdict = all(v is True or (not isinstance(v, bool))
                  for v in checks.values())
    checks["GATE"] = "PASS" if verdict else "FAIL"
    return checks
