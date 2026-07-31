from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.dtalite4cube.cube2gmns import funclib
from src.dtalite4cube.cube2gmns.vdf_lookup_tables import (
    QVDF_CSV_PATH,
    _load_qvdf_csv,
    get_vdf_dict,
)


class QvdfCsvSourceTests(unittest.TestCase):
    def test_runtime_qvdf_values_match_packaged_csv(self):
        with QVDF_CSV_PATH.open(newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))

        expected_codes = {row["vdf_code"] for row in rows}
        loaded = get_vdf_dict("qvdf")

        self.assertEqual(set(loaded), expected_codes)
        self.assertEqual(rows[-1]["vdf_code"], "all")
        self.assertEqual(list(loaded)[-1], "all")
        source_101 = next(row for row in rows if row["vdf_code"] == "101")
        self.assertEqual(
            loaded["101"]["QVDF_alpha1"],
            float(source_101["QVDF_alpha1"]),
        )
        self.assertEqual(
            loaded["101"]["QVDF_beta3"],
            float(source_101["QVDF_beta3"]),
        )

    def test_loader_reads_the_selected_csv_file(self):
        with tempfile.TemporaryDirectory(prefix="qvdf_csv_source_") as temp_dir:
            csv_path = Path(temp_dir) / "link_qvdf.csv"
            csv_path.write_text(
                "data_type,vdf_code,QVDF_alpha1,QVDF_beta1\n"
                "vdf_code,custom,0.321,4.567\n",
                encoding="utf-8",
            )

            loaded = _load_qvdf_csv(csv_path)

        self.assertEqual(
            loaded,
            {"custom": {"QVDF_alpha1": 0.321, "QVDF_beta1": 4.567}},
        )

    def test_known_link_type_uses_its_own_csv_row(self):
        loaded = get_vdf_dict("qvdf")

        selected_code = funclib._resolve_vdf_code(loaded, 101)

        self.assertEqual(selected_code, "101")
        self.assertIs(loaded[selected_code], loaded["101"])

    def test_unknown_link_type_uses_all_network_csv_row(self):
        loaded = get_vdf_dict("qvdf")

        selected_code = funclib._resolve_vdf_code(loaded, 999)

        self.assertEqual(selected_code, "all")
        self.assertIs(loaded[selected_code], loaded["all"])

    def test_legacy_nvta_dictionary_is_not_wired_into_funclib(self):
        self.assertFalse(hasattr(funclib, "NVTA_qvdf_dict"))


if __name__ == "__main__":
    unittest.main()
