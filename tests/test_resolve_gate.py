"""PR-3 (CR-0008): strict model-resolution gate tests.

1. NEGATIVE: the synthetic bad-configuration fixture MUST fail strict
   resolution with RS-3 + RS-4 (a PASS here is a gate regression).
2. POSITIVE: the public conical fixture (explicit conic_a) passes strict.
3. POSITIVE: Chicago Sketch passes non-strict as plain BPR with zero
   conic-fallback links.
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from dtalite_qa import resolve  # noqa: E402


def test_negative_fixture_fails_strict():
    cfg = os.path.join(REPO, "test_networks", "bad_vdf_config",
                       "configuration.yml")
    man = resolve.resolve(cfg, strict=True)
    ids = {f["id"] for f in man["findings"]}
    assert man["verdict"] == "FAIL"
    assert "RS-3" in ids and "RS-4" in ids
    assert man["performance_resolution"] == {"bpr": 6}


def test_conic_fixture_passes_strict():
    tmp = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(REPO, "test_networks", "sf_conic",
                                 "link.csv"), tmp)
        cfg = os.path.join(tmp, "configuration.yml")
        with open(cfg, "w") as f:
            f.write("scenario: sf_conic_audit\n"
                    "network: {link: link.csv}\n"
                    "run:\n  active_period: {id: 1, name: AM, "
                    "start: \"07:00\", end: \"08:00\"}\n"
                    "claims: {replication_family: conical}\n")
        man = resolve.resolve(cfg, strict=True)
        assert man["verdict"] == "PASS", man["findings"]
        assert man["conic_fallback_links"] == 0
        assert man["performance_resolution"].get("conical_spiess", 0) > 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_chicago_sketch_bpr_audit():
    tmp = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(REPO, "kernel", "data_sets",
                                 "03_chicago_sketch", "link.csv"), tmp)
        cfg = os.path.join(tmp, "configuration.yml")
        with open(cfg, "w") as f:
            f.write("scenario: chicago_sketch_audit\n"
                    "network: {link: link.csv}\n"
                    "run:\n  active_period: {id: 1, name: AM, "
                    "start: \"07:00\", end: \"08:00\"}\n")
        man = resolve.resolve(cfg, strict=False)
        assert man["verdict"] in ("PASS", "WARN")
        assert man["conic_fallback_links"] == 0
        assert man["performance_resolution"].get("bpr", 0) > 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_negative_fixture_fails_strict()
    print("negative fixture: FAILS strict as required")
    test_conic_fixture_passes_strict()
    print("conic fixture: PASSES strict (explicit columns)")
    test_chicago_sketch_bpr_audit()
    print("chicago sketch: BPR audit clean")
    print("ALL RESOLVE-GATE TESTS PASS")
