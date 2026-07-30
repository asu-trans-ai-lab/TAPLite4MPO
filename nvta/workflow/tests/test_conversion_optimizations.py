from __future__ import annotations

import csv
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

import numpy as np

from src.dtalite4cube.dtab import (
    demand_binary_path,
    inspect_dtab,
    read_dtab_records,
    write_dtab_file,
)
from src.dtalite4cube.file_utils import copy_files_parallel
from src.dtalite4cube.network_cache import (
    load_network_cache,
    network_source_fingerprint,
    save_network_cache,
)
from src.dtalite4cube.omx2csv import (
    _close_worker_omx_files,
    _worker_omx_file,
)
from src.dtalite4cube.reproducible_run import preflight
from src.dtalite4cube.reproducible_run import _build_dtalite_command
from src.dtalite4cube.runner import (
    AssignmentConfig,
    build_arg_parser as build_internal_arg_parser,
)
from src.dtalite4cube.settings.generate_dtalite_settings import (
    generate_dtalite_input_files,
)
from run_assignment import build_arg_parser as build_public_arg_parser


WORKFLOW_ROOT = Path(__file__).resolve().parents[1]


class WorkspaceArtifactTestCase(unittest.TestCase):
    def setUp(self):
        self.root = WORKFLOW_ROOT / ".test-artifacts" / str(uuid4())
        self.root.mkdir(parents=True)

    def tearDown(self):
        _close_worker_omx_files()
        shutil.rmtree(self.root)


class ParallelPackageDefaultTests(unittest.TestCase):
    def test_config_and_both_clis_use_csv_cache_and_four_workers(self):
        config = AssignmentConfig(network_path=WORKFLOW_ROOT)
        self.assertEqual(config.conversion_workers, 4)
        self.assertTrue(config.conversion_cache)
        self.assertEqual(config.demand_output_format, "csv")
        self.assertEqual(config.kernel_source, "wheel")

        public = build_public_arg_parser().parse_args([str(WORKFLOW_ROOT)])
        self.assertEqual(public.conversion_workers, 4)
        self.assertTrue(public.conversion_cache)
        self.assertEqual(public.demand_output_format, "csv")
        self.assertEqual(public.kernel_source, "wheel")

        internal = build_internal_arg_parser().parse_args(
            ["--network-path", str(WORKFLOW_ROOT)]
        )
        self.assertEqual(internal.conversion_workers, 4)
        self.assertTrue(internal.conversion_cache)
        self.assertEqual(internal.demand_output_format, "csv")
        self.assertEqual(internal.kernel_source, "wheel")

    def test_wheel_command_uses_pytaplite_in_a_child_process(self):
        command = _build_dtalite_command("wheel")
        command_text = command[-1]

        self.assertIn("import taplite4mpo", command_text)
        self.assertIn("import pytaplite", command_text)
        self.assertIn("from pytaplite import _native", command_text)
        self.assertIn("pytaplite.assign(os.getcwd(), in_place=True)", command_text)
        self.assertNotIn("ctypes", command_text)
        self.assertNotIn("DTALite.dll", command_text)

    def test_nvta_package_forces_route_and_vehicle_outputs_off(self):
        config = AssignmentConfig(
            network_path=WORKFLOW_ROOT,
            route_output=1,
            vehicle_output=1,
        )
        config.validate()
        self.assertEqual(config.route_output, 0)
        self.assertEqual(config.vehicle_output, 0)

        public = build_public_arg_parser().parse_args(
            [str(WORKFLOW_ROOT), "--route-output", "1", "--vehicle-output", "1"]
        )
        config = AssignmentConfig(
            network_path=WORKFLOW_ROOT,
            route_output=public.route_output,
            vehicle_output=public.vehicle_output,
        )
        config.validate()
        self.assertEqual(config.route_output, 0)
        self.assertEqual(config.vehicle_output, 0)

    def test_obsolete_id_translation_controls_are_removed(self):
        config = AssignmentConfig(network_path=WORKFLOW_ROOT)
        self.assertFalse(hasattr(config, "use_sequential_ids_for_dtalite"))
        self.assertFalse(hasattr(config, "renumber_link_ids_if_needed"))
        self.assertFalse(hasattr(config, "backmap_dtalite_outputs"))


class NetworkCacheTests(WorkspaceArtifactTestCase):
    def test_cache_hit_and_source_content_invalidation(self):
        source = self.root / "network"
        source.mkdir()
        (source / "DTALiteNetworkInput.shp").write_bytes(b"shape-v1")
        (source / "DTALiteNetworkInput.dbf").write_bytes(b"attributes-v1")
        fingerprint_v1, files_v1 = network_source_fingerprint(
            source,
            target_crs="EPSG:4326",
        )

        node_csv = self.root / "node.csv"
        node_csv.write_text(
            "node_id,zone_id,x_coord,y_coord\n1,1,0,0\n",
            encoding="utf-8",
        )
        cache_dir = self.root / "cache"
        save_network_cache(
            cache_dir,
            fingerprint=fingerprint_v1,
            source_files=files_v1,
            target_crs="EPSG:4326",
            payload={"prepared": [1, 2, 3]},
            node_csv_source=node_csv,
        )

        payload, cached_node = load_network_cache(
            cache_dir,
            expected_fingerprint=fingerprint_v1,
        )
        self.assertEqual(payload, {"prepared": [1, 2, 3]})
        self.assertEqual(cached_node.read_bytes(), node_csv.read_bytes())

        (source / "DTALiteNetworkInput.dbf").write_bytes(b"attributes-v2")
        fingerprint_v2, _ = network_source_fingerprint(
            source,
            target_crs="EPSG:4326",
        )
        self.assertNotEqual(fingerprint_v1, fingerprint_v2)
        payload, cached_node = load_network_cache(
            cache_dir,
            expected_fingerprint=fingerprint_v2,
        )
        self.assertIsNone(payload)
        self.assertIsNone(cached_node)


class OMXWorkerCacheTests(WorkspaceArtifactTestCase):
    def test_worker_reuses_open_omx_handle(self):
        import openmatrix as omx

        matrix_path = self.root / "tiny.omx"
        with omx.open_file(str(matrix_path), "w") as matrix_file:
            matrix_file["AM_SOVs"] = np.eye(3)

        first = _worker_omx_file(str(matrix_path))
        second = _worker_omx_file(str(matrix_path))
        self.assertIs(first, second)
        self.assertEqual(np.asarray(first["AM_SOVs"]).shape, (3, 3))


class DirectExternalIdPreflightTests(WorkspaceArtifactTestCase):
    def _write_period(self) -> Path:
        source = self.root / "am"
        source.mkdir()
        (source / "node.csv").write_text(
            "node_id,zone_id,x_coord,y_coord\n"
            "1000,5000,0,0\n"
            "9000,7000,1,1\n"
            "42000,,2,2\n",
            encoding="utf-8",
        )
        (source / "link.csv").write_text(
            "link_id,from_node_id,to_node_id\n"
            "70000,1000,42000\n"
            "90000,42000,9000\n",
            encoding="utf-8",
        )
        generate_dtalite_input_files(
            source,
            "am",
            overrides={"demand_format": 0},
        )
        (source / "mode_type.csv").write_text(
            "mode_type_id,mode_type,name,vot,pce,occ,demand_file\n"
            "1,sov,sov,20,1,1,sov_am.csv\n"
            "2,hov2,hov2,20,1,2,hov2_am.csv\n",
            encoding="utf-8",
        )
        (source / "sov_am.csv").write_text(
            "o_zone_id,d_zone_id,volume\n"
            "5000,7000,1.5\n"
            "7000,5000,2.5\n",
            encoding="utf-8",
        )
        (source / "hov2_am.csv").write_text(
            "o_zone_id,d_zone_id,volume\n"
            "5000,7000,3.5\n",
            encoding="utf-8",
        )
        return source

    def test_sparse_external_ids_are_validated_without_rewriting(self):
        source = self._write_period()
        original_files = {
            path.name: path.read_bytes()
            for path in source.iterdir()
            if path.is_file()
        }

        info = preflight(source)

        self.assertEqual(info["counts"]["node_ids"], 3)
        self.assertEqual(info["counts"]["zone_ids"], 2)
        self.assertEqual(info["counts"]["link_ids"], 2)
        self.assertEqual(info["counts"]["demand_rows"], 3)
        self.assertFalse((source / "_internal").exists())
        self.assertFalse((source / "id_mapping.csv").exists())
        self.assertEqual(
            original_files,
            {
                path.name: path.read_bytes()
                for path in source.iterdir()
                if path.is_file()
            },
        )

    def test_missing_link_endpoint_is_rejected(self):
        source = self._write_period()
        (source / "link.csv").write_text(
            "link_id,from_node_id,to_node_id\n"
            "70000,1000,999999\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "does not reference a node_id"):
            preflight(source)

    def test_missing_demand_zone_is_rejected(self):
        source = self._write_period()
        (source / "sov_am.csv").write_text(
            "o_zone_id,d_zone_id,volume\n"
            "5000,999999,1.5\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "positive zone_id"):
            preflight(source)


class ParallelFileCopyTests(WorkspaceArtifactTestCase):
    def test_parallel_copy_preserves_order_and_bytes(self):
        sources = self.root / "sources"
        targets = self.root / "targets"
        sources.mkdir()
        pairs = []
        for index in range(5):
            source = sources / f"source-{index}.bin"
            target = targets / f"target-{index}.bin"
            source.write_bytes(bytes([index]) * (index + 1) * 17)
            pairs.append((source, target))

        copied = copy_files_parallel(
            pairs,
            workers=3,
            preserve_metadata=False,
        )

        self.assertEqual(copied, pairs)
        for source, target in pairs:
            self.assertEqual(source.read_bytes(), target.read_bytes())


class BinaryDemandTests(WorkspaceArtifactTestCase):
    def _write_period_inputs(self, period_dir: Path) -> None:
        period_dir.mkdir(parents=True)
        with (period_dir / "node.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["node_id", "zone_id", "x_coord", "y_coord"])
            writer.writerows(
                [
                    [10, 10, 0, 0],
                    [20, 20, 1, 1],
                    [100, "", 2, 2],
                ]
            )
        with (period_dir / "link.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["link_id", "from_node_id", "to_node_id"])
            writer.writerows([[7, 10, 100], [8, 100, 20]])

        generate_dtalite_input_files(
            period_dir,
            "am",
            overrides={"demand_format": 1},
        )
        with (period_dir / "mode_type.csv").open(
            "w",
            newline="",
            encoding="utf-8",
        ) as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(
                ["mode_type_id", "mode_type", "name", "vot", "pce", "occ", "demand_file"]
            )
            writer.writerow([1, "sov", "sov", 20, 1, 1, "sov_am.csv"])

        write_dtab_file(
            period_dir / "sov_am.bin",
            np.array([10, 20], dtype=np.int32),
            np.array([20, 10], dtype=np.int32),
            np.array([1.25, 2.5], dtype=np.float64),
        )

    def test_binary_preflight_preserves_external_ids(self):
        source = self.root / "am"
        self._write_period_inputs(source)

        source_info = preflight(source)
        self.assertEqual(source_info["counts"]["demand_files"], 1)
        self.assertEqual(source_info["files"]["sov_am.bin"]["rows"], 2)
        self.assertEqual(source_info["counts"]["demand_rows"], 2)
        info = inspect_dtab(source / "sov_am.bin")
        records = read_dtab_records(source / "sov_am.bin")
        self.assertEqual(info["records"], 2)
        self.assertEqual(records["o_zone_id"].tolist(), [10, 20])
        self.assertEqual(records["d_zone_id"].tolist(), [20, 10])
        self.assertEqual(records["volume"].tolist(), [1.25, 2.5])
        self.assertFalse((source / "_internal").exists())
        self.assertFalse((source / "id_mapping.csv").exists())

    def test_binary_preflight_rejects_missing_zone(self):
        source = self.root / "am"
        self._write_period_inputs(source)
        write_dtab_file(
            source / "sov_am.bin",
            np.array([10], dtype=np.int32),
            np.array([999], dtype=np.int32),
            np.array([1.25], dtype=np.float64),
        )

        with self.assertRaisesRegex(ValueError, "absent from node.csv"):
            preflight(source)

    def test_binary_path_replaces_csv_suffix(self):
        self.assertEqual(
            demand_binary_path(self.root / "sov_am.csv"),
            self.root / "sov_am.bin",
        )


if __name__ == "__main__":
    unittest.main()
