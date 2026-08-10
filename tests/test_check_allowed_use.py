"""Gate tests: allowed_use vs a reference assignment, and the HOT invariant.

The central property under test: a class with zero volume is only a lost
restriction when its EXPECTED volume was large. Airport vans permitted
network-wide with little demand must NOT be flagged.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dtalite_qa.check_allowed_use import (check_allowed_use,
                                          check_toll_consistency)

VOL = {"sov": "v_sov", "hov3": "v_hov3", "apv": "v_apv"}
TOLL = {"sov": "toll_sov", "hov2": "toll_hov2", "hov3": "toll_hov3"}


def _links(rows):
    return pd.DataFrame(rows, columns=["facility_id", "allowed_use",
                                       "v_sov", "v_hov3", "v_apv"])


def _gp(n=5, sov=200000.0, hov3=20000.0, apv=6000.0):
    """General-purpose context: how the classes behave elsewhere. The gate
    needs this — the expectation is learned leave-one-out."""
    return _links([("GP", "sov;hov3;apv", sov, hov3, apv)] * n)


def test_hov_only_facility_with_sov_permitted_is_a_blocker():
    # busy facility, SOV expected in quantity from its behaviour elsewhere,
    # reference assigns none here, yet allowed_use permits sov
    df = pd.concat([_gp(),
                    _links([("HOV_SB", "sov;hov3;apv", 0.0, 50000.0, 3000.0)] * 5)],
                   ignore_index=True)
    v = check_allowed_use(df, class_volume_cols=VOL)
    row = v.detail.query("facility == 'HOV_SB' and cls == 'sov'").iloc[0]
    assert row.verdict == "RESTRICTION_LOST"
    assert row.action == "REMOVE from allowed_use"
    assert not v.ok
    with pytest.raises(RuntimeError):
        v.require()


def test_single_facility_cannot_support_a_restriction_verdict():
    """Design property: with no other facility to learn the class share
    from, a zero is uninformative and MUST NOT be called a restriction."""
    df = _links([("ONLY", "sov;hov3;apv", 0.0, 50000.0, 3000.0)] * 5)
    v = check_allowed_use(df, class_volume_cols=VOL)
    assert (v.detail.query("cls == 'sov'").iloc[0].verdict
            == "INSUFFICIENT_EVIDENCE")
    assert v.ok


def test_airport_vans_with_no_demand_are_NOT_flagged():
    # apv is permitted network-wide and carries a small share; a facility
    # with no apv volume is absence of demand, not a restriction
    df = pd.concat([
        _links([("BUSY", "sov;hov3;apv", 90000.0, 9000.0, 900.0)] * 5),
        _links([("QUIET", "sov;hov3;apv", 300.0, 20.0, 0.0)] * 2),
    ], ignore_index=True)
    v = check_allowed_use(df, class_volume_cols=VOL)
    row = v.detail.query("facility == 'QUIET' and cls == 'apv'").iloc[0]
    assert row.verdict == "INSUFFICIENT_EVIDENCE"
    assert row.action == ""
    assert v.ok, "a low-demand zero must not block the gate"


def test_used_but_forbidden_is_a_blocker():
    df = _links([("F1", "sov;hov3", 1000.0, 500.0, 400.0)] * 3)
    v = check_allowed_use(df, class_volume_cols=VOL)
    row = v.detail.query("facility == 'F1' and cls == 'apv'").iloc[0]
    assert row.verdict == "RESTRICTION_TOO_TIGHT"
    assert row.action == "ADD to allowed_use"
    assert not v.ok


def test_closed_facility_with_zero_volume_is_consistent():
    df = _links([("REV_NB", "closed", 0.0, 0.0, 0.0)] * 4)
    v = check_allowed_use(df, class_volume_cols=VOL)
    assert set(v.detail.verdict) == {"CONSISTENT_EXCLUDED"}
    assert v.ok


def test_closed_facility_carrying_volume_is_a_blocker():
    df = _links([("REV_NB", "closed", 0.0, 800.0, 0.0)] * 4)
    v = check_allowed_use(df, class_volume_cols=VOL)
    row = v.detail.query("cls == 'hov3'").iloc[0]
    assert row.verdict == "RESTRICTION_TOO_TIGHT"
    assert not v.ok


def test_facility_level_not_link_level():
    # one zero link inside an otherwise-used facility is a routing outcome
    df = _links([("F1", "sov;hov3;apv", 5000.0, 5000.0, 5000.0),
                 ("F1", "sov;hov3;apv", 0.0, 5000.0, 5000.0),
                 ("F1", "sov;hov3;apv", 5000.0, 5000.0, 5000.0)])
    v = check_allowed_use(df, class_volume_cols=VOL)
    assert v.detail.query("cls == 'sov'").iloc[0].verdict == "CONSISTENT_USED"
    assert v.ok


def test_expected_volume_drives_the_verdict_not_the_raw_zero():
    # identical zero on two facilities, same network context: only the one
    # where SOV was expected in quantity is called a restriction
    df = pd.concat([
        _gp(),
        _links([("BIG", "sov;hov3;apv", 0.0, 100000.0, 100000.0)] * 3),
        _links([("SMALL", "sov;hov3;apv", 0.0, 10.0, 10.0)] * 3),
    ], ignore_index=True)
    v = check_allowed_use(df, class_volume_cols=VOL)
    assert (v.detail.query("facility == 'BIG' and cls == 'sov'").iloc[0]
            .verdict == "RESTRICTION_LOST")
    assert (v.detail.query("facility == 'SMALL' and cls == 'sov'").iloc[0]
            .verdict == "INSUFFICIENT_EVIDENCE")


def test_hot_without_hov_differential_is_flagged():
    df = pd.DataFrame(dict(facility_id=["HOT1"] * 3,
                           toll_sov=[1.42] * 3, toll_hov2=[1.42] * 3,
                           toll_hov3=[1.42] * 3))
    v = check_toll_consistency(df, toll_cols=TOLL)
    assert not v.ok
    assert v.detail.iloc[0].verdict == "NO_HOV_DIFFERENTIAL"
    assert "toll_hov3 = 0" in v.detail.iloc[0].action


def test_hot_with_free_hov3_passes():
    df = pd.DataFrame(dict(facility_id=["HOT1"] * 3,
                           toll_sov=[1.42] * 3, toll_hov2=[0.71] * 3,
                           toll_hov3=[0.0] * 3))
    v = check_toll_consistency(df, toll_cols=TOLL)
    assert v.ok and v.detail.iloc[0].verdict == "OK_HOT"


def test_untolled_facility_is_not_examined_for_differential():
    df = pd.DataFrame(dict(facility_id=["GP"] * 3, toll_sov=[0.0] * 3,
                           toll_hov2=[0.0] * 3, toll_hov3=[0.0] * 3))
    v = check_toll_consistency(df, toll_cols=TOLL)
    assert v.ok and v.detail.empty


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for f in fns:
        try:
            f()
            print(f"PASS {f.__name__}")
        except Exception:
            bad += 1
            print(f"FAIL {f.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns)-bad}/{len(fns)} passed")
