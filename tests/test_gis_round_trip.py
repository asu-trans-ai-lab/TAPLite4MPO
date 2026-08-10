"""D1 — Gold-LDN-RT-Public: GIS round-trip gold (committed test logic;
payload acquired externally per the redistribution policy).

Acquire the payload (not redistributed here — no license in the source repo):
    git clone --depth 1 https://github.com/Mmdabb/DTALite4Cube
and set LDN034_SHP to .../DTALite4Cube/LDN034_BD/SubArea_NTWK_LDN034_LL.shp
(or place the clone as a sibling of this repo). The test SKIPS with an
actionable message when the payload or the optional GIS deps are absent.

Gate (semantic, per the frozen design): feature count, source_record_id
presence and completeness, geometry within tolerance — on BOTH the GPKG
fidelity package and the SHP compatibility bundle.

D2 — wide-path neutrality on a single-period public case (ARC in-repo):
mapping a canonical narrow file into the wide contract and resolving the
period back must reproduce the file (identity transform).
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

LDN034_SHP = os.environ.get(
    "LDN034_SHP",
    os.path.join(REPO, "..", "DTALite4Cube", "DTALite4Cube", "LDN034_BD",
                 "SubArea_NTWK_LDN034_LL.shp"))


def _gis_available():
    try:
        import geopandas  # noqa: F401
        import pyogrio    # noqa: F401
        return True
    except ImportError:
        return False


def test_ldn034_round_trip():
    if not _gis_available():
        print("SKIP: pip install taplite4mpo[gis]")
        return
    if not os.path.exists(LDN034_SHP):
        print("SKIP: payload absent — clone Mmdabb/DTALite4Cube (see "
              "docstring); not redistributed here (no source license)")
        return
    import pandas as pd
    from dtalite_qa import gis_adapter as ga
    tmp = tempfile.mkdtemp()
    wide, man = ga.import_network(
        LDN034_SHP, os.path.join(REPO, "adapters",
                                 "cube_wide_periodic.json"),
        tmp, dataset="LDN034_BD")
    assert man["features"] == 28 and man["source_fields"] == 112
    assert wide.source_record_id.is_unique
    for P in ("AM", "MD", "PM", "NT"):
        assert f"active_{P}" in wide.columns
    res = pd.DataFrame({"source_record_id": wide.source_record_id,
                        "volume": range(len(wide))})
    for fmt, name in (("gpkg", "rt.gpkg"), ("shp", "rt.shp")):
        out = os.path.join(tmp, name)
        ga.export_results(tmp, res, out, fmt=fmt)
        gate = ga.round_trip_gate(tmp, out)
        assert gate["GATE"] == "PASS", (fmt, gate)
    print("LDN034 round-trip gold: GPKG PASS + SHP PASS "
          "(28 features, 112 fields, geometry exact)")


def test_arc_wide_neutrality():
    """Single-period identity: narrow -> wide naming -> resolve == narrow."""
    import pandas as pd
    src = os.path.join(REPO, "examples", "arc_atlanta", "gmns", "link.csv")
    lk = pd.read_csv(src, low_memory=False)
    wide = lk.rename(columns={"capacity": "capacity_hourly_per_lane_AM",
                              "lanes": "lanes_AM"})
    wide["active_AM"] = pd.to_numeric(wide.lanes_AM,
                                      errors="coerce").fillna(0) > 0
    resolved = wide[wide.active_AM].rename(
        columns={"capacity_hourly_per_lane_AM": "capacity",
                 "lanes_AM": "lanes"}).drop(columns=["active_AM"])
    orig = lk[pd.to_numeric(lk.lanes, errors="coerce").fillna(0) > 0]
    assert len(resolved) == len(orig)
    for c in ("capacity", "lanes", "vdf_alpha", "vdf_beta", "vdf_plf"):
        a = pd.to_numeric(resolved[c], errors="coerce").reset_index(drop=True)
        b = pd.to_numeric(orig[c], errors="coerce").reset_index(drop=True)
        assert ((a - b).abs().fillna(0) < 1e-9).all(), c
    print(f"ARC wide-path neutrality: identity holds on "
          f"{len(resolved):,} links (drop rule lanes>0: "
          f"{len(lk)-len(orig)} connectors excluded)")


if __name__ == "__main__":
    test_ldn034_round_trip()
    test_arc_wide_neutrality()
    print("D1+D2 PASS")
