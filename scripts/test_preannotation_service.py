import json
import tempfile
import unittest
from pathlib import Path

import preannotation_service
from preannotation_service import index_v2v_rows, nearest_v2v_rows, occ_label_target, parse_fusiondet_outputs, v2v_row_timestamp


class V2vTimestampTest(unittest.TestCase):
    def test_prefers_box_timestamp(self) -> None:
        row = {"frame_timestamp_ns": "100", "box_timestamp_ns": "200"}
        self.assertEqual(v2v_row_timestamp(row), 200)

    def test_selects_one_nearest_sample_per_vehicle(self) -> None:
        rows = [
            {"vehicle_id": "TRUCK007", "frame_timestamp_ns": "100", "box_timestamp_ns": "200", "x": "first"},
            {"vehicle_id": "TRUCK007", "frame_timestamp_ns": "100", "box_timestamp_ns": "300", "x": "second"},
            {"vehicle_id": "TRUCK007", "frame_timestamp_ns": "100", "box_timestamp_ns": "300", "x": "duplicate"},
            {"vehicle_id": "TRUCK025", "frame_timestamp_ns": "100", "box_timestamp_ns": "220", "x": "other"},
        ]
        index = index_v2v_rows(rows)

        matches = nearest_v2v_rows(index, 280, max_gap_ns=100)

        self.assertEqual(len(matches), 2)
        self.assertEqual([(item[0], item[1]) for item in matches], [("TRUCK007", 300), ("TRUCK025", 220)])
        self.assertEqual(matches[0][2]["x"], "second")

    def test_applies_gap_per_vehicle(self) -> None:
        rows = [
            {"vehicle_id": "near", "box_timestamp_ns": "900"},
            {"vehicle_id": "far", "box_timestamp_ns": "100"},
        ]
        matches = nearest_v2v_rows(index_v2v_rows(rows), 1000, max_gap_ns=200)
        self.assertEqual([item[0] for item in matches], ["near"])


class FusionDetOutputTest(unittest.TestCase):
    def test_occ_target_uses_clip_timestamp_layout(self) -> None:
        clip = Path("/data/all_test/7cam/clip")
        point = clip / "lidars/LIDAR_CAR/LIDAR_123.bin"
        self.assertEqual(
            occ_label_target(clip, point),
            clip / "anno/occ_labels/LIDAR_CAR/LIDAR_123.label",
        )

    def test_parses_detection_and_occ_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            old_work_root = preannotation_service.WORK_ROOT
            preannotation_service.WORK_ROOT = root
            try:
                output = root / "job_1" / "infer"
                (output / "det").mkdir(parents=True)
                (output / "occ").mkdir()
                (output / "det" / "42.json").write_text(json.dumps({"objects":[{
                    "category":"Car", "translation":[1,2,3], "size":[4,5,2], "yaw":0.25
                }]}), encoding="utf-8")
                (output / "occ" / "42.label").write_bytes(b"\x01\x02")
                predictions, occ = parse_fusiondet_outputs(output, [42])
                self.assertEqual(predictions["42"][0]["z"], 4.0)
                self.assertEqual(predictions["42"][0]["rotZ"], 0.25)
                self.assertEqual(occ["42"]["labelUrl"], "/preannotation-artifacts/job_1/infer/occ/42.label")
            finally:
                preannotation_service.WORK_ROOT = old_work_root


if __name__ == "__main__":
    unittest.main()
