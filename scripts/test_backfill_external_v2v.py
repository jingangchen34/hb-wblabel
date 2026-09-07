import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backfill_external_v2v import generate_sql

TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / ".tmp"


class V2vBackfillTest(unittest.TestCase):
    def test_generates_idempotent_link_update_without_reimporting_frames(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v2v-backfill-", dir=TEST_TEMP_ROOT) as temp_dir:
            root = Path(temp_dir)
            clip = root / "all_test" / "7cam" / "clip-1"
            lidar = clip / "lidars" / "LIDAR_CAR"
            v2v = clip / "v2v"
            lidar.mkdir(parents=True)
            v2v.mkdir()
            (clip / "pose.json").write_text("{}", encoding="utf-8")
            (lidar / "LIDAR_1234567890123456.bin").write_bytes(b"pcd")
            (v2v / "V2V.csv").write_text("frame_timestamp_ns\n", encoding="utf-8")
            args = SimpleNamespace(
                root=str(root),
                scan_root=str(root / "all_test" / "7cam"),
                dataset_id=194,
                output=str(root / "repair.sql"),
                bucket_name="external-data",
                user_id=1,
                scene_name_from="basename",
            )
            sql, count = generate_sql(args)
            self.assertEqual(count, 1)
            self.assertIn("`dataset_id`=194", sql)
            self.assertIn("`name`='clip-1'", sql)
            self.assertIn("JSON_SEARCH(`content`, 'one', 'V2V.csv') IS NULL", sql)
            self.assertIn("all_test/7cam/clip-1/v2v/V2V.csv", sql)
            self.assertNotIn("INSERT INTO `data`", sql)


if __name__ == "__main__":
    unittest.main()
