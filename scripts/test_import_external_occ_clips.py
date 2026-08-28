import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from import_external_occ_clips import find_v2v_csv, generate_sql

TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / ".tmp"


class V2vImportTest(unittest.TestCase):
    def test_finds_real_csv_and_ignores_office_lock_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v2v-test-", dir=TEST_TEMP_ROOT) as temp_dir:
            clip = Path(temp_dir)
            v2v = clip / "v2v"
            v2v.mkdir()
            (v2v / ".~lock.V2V.csv#").write_text("lock", encoding="utf-8")
            expected = v2v / "V2V.csv"
            expected.write_text("frame_index\n", encoding="utf-8")

            self.assertEqual(find_v2v_csv(clip), expected)

    def test_registers_v2v_csv_in_frame_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v2v-test-", dir=TEST_TEMP_ROOT) as temp_dir:
            root = Path(temp_dir)
            clip = root / "all_test" / "7cam" / "ks" / "ks_qlc_result" / "clip-1"
            lidar_dir = clip / "lidars" / "LIDAR_CAR"
            v2v_dir = clip / "v2v"
            lidar_dir.mkdir(parents=True)
            v2v_dir.mkdir()
            (clip / "pose.json").write_text("{}", encoding="utf-8")
            (lidar_dir / "LIDAR_1783333787600171327.bin").write_bytes(b"\0" * 28)
            (v2v_dir / "V2V.csv").write_text(
                "frame_index,frame_timestamp_ns\n0,1783333787600171327\n",
                encoding="utf-8",
            )
            args = SimpleNamespace(
                root=str(root),
                scan_root=str(root / "all_test" / "7cam"),
                conch_data_layout=False,
                skip_obstacle_annotations=True,
                dataset_from="clip-parent",
                dataset_name=None,
                dataset_description="test",
                bucket_name="external-data",
                user_id=1,
            )

            sql, clip_count, frame_count = generate_sql(args)

            self.assertEqual((clip_count, frame_count), (1, 1))
            self.assertIn("all_test/7cam/ks/ks_qlc_result/clip-1/v2v/V2V.csv", sql)
            self.assertIn("JSON_OBJECT('name', 'v2v', 'type', 'directory'", sql)


if __name__ == "__main__":
    unittest.main()
