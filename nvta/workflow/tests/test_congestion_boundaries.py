from __future__ import annotations

import csv
import shutil
import sys
import unittest
from pathlib import Path
from uuid import uuid4

import numpy as np


WORKFLOW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKFLOW_ROOT))

from src.dtalite4cube.cube2gmns.congestion_boundaries import (
    apply_congestion_boundaries,
)
from src.dtalite4cube.cube2gmns.funclib import _outputLink
from src.dtalite4cube.cube2gmns.netclass import Link, Network, Node
from src.dtalite4cube.resources.congestion_t_node_pair_lookup.load_node_pair_boundaries import (
    BOUNDARY_FIELDS,
    lookup,
)


LOOKUP_DTYPE = np.dtype(
    [
        ("packed_key", "<u8"),
        ("from_node_id", "<u4"),
        ("to_node_id", "<u4"),
        ("t0_hour", "<f4"),
        ("t2_hour", "<f4"),
        ("t3_hour", "<f4"),
    ]
)


def _make_link(link_id: int, from_node_id: int, to_node_id: int) -> Link:
    link = Link(link_id)
    link.from_node = Node(from_node_id)
    link.to_node = Node(to_node_id)
    return link


class CongestionBoundaryMappingTests(unittest.TestCase):
    def setUp(self):
        self.root = WORKFLOW_ROOT / ".test-artifacts" / str(uuid4())
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root)

    def _write_lookup(self):
        table = np.array(
            [
                (
                    (np.uint64(10) << np.uint64(32)) | np.uint64(20),
                    10,
                    20,
                    6.25,
                    7.5,
                    8.75,
                )
            ],
            dtype=LOOKUP_DTYPE,
        )
        np.save(self.root / "am_node_pair_boundaries.npy", table, allow_pickle=False)

    def test_conversion_output_contains_period_boundaries_for_matched_pair(self):
        self._write_lookup()
        network = Network()
        network.link_dict = {
            1: _make_link(1, 10, 20),
            2: _make_link(2, 20, 30),
        }

        stats = apply_congestion_boundaries(network, "AM", self.root)
        _outputLink(network, self.root, "am")

        with (self.root / "link_am.csv").open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))

        self.assertEqual(stats["matched"], 1)
        self.assertEqual(stats["unmatched"], 1)
        self.assertTrue(set(BOUNDARY_FIELDS).issubset(rows[0]))
        self.assertEqual(
            [rows[0][field] for field in BOUNDARY_FIELDS],
            ["6.25", "7.5", "8.75"],
        )
        self.assertEqual([rows[1][field] for field in BOUNDARY_FIELDS], ["", "", ""])

    def test_period_without_lookup_keeps_stable_blank_columns(self):
        network = Network()
        network.link_dict = {1: _make_link(1, 10, 20)}

        stats = apply_congestion_boundaries(network, "nt", self.root)
        _outputLink(network, self.root, "nt")

        with (self.root / "link_nt.csv").open(newline="", encoding="utf-8") as stream:
            row = next(csv.DictReader(stream))

        self.assertFalse(stats["available"])
        self.assertEqual([row[field] for field in BOUNDARY_FIELDS], ["", "", ""])

    def test_empty_lookup_returns_unmatched_instead_of_indexing_error(self):
        empty = np.empty(0, dtype=LOOKUP_DTYPE)

        values, found = lookup(empty, np.array([10]), np.array([20]))

        self.assertEqual(values.shape, (1, len(BOUNDARY_FIELDS)))
        self.assertTrue(np.isnan(values).all())
        self.assertFalse(found.any())


if __name__ == "__main__":
    unittest.main()
