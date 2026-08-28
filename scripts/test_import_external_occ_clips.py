import unittest
from pathlib import Path

from import_external_occ_clips import make_clip_display_name


class MakeClipDisplayNameTest(unittest.TestCase):
    def test_collapses_redundant_qlc_result_directory_for_nested_dataset(self) -> None:
        root = Path("/home/user/cjg/conch_data")
        clip = root / "all_test" / "7cam" / "dz" / "dz_qlc_result" / "2026-07-09-16-18-28"

        self.assertEqual(
            make_clip_display_name(clip, root, "all_test/7cam"),
            "dz/2026-07-09-16-18-28.clip",
        )

    def test_preserves_existing_clip_parent_behavior(self) -> None:
        root = Path("/data")
        clip = root / "chizhou" / "cz_quliuc" / "2025-10-24-10-26"

        self.assertEqual(
            make_clip_display_name(clip, root, "chizhou/cz_quliuc"),
            "2025-10-24-10-26",
        )

    def test_preserves_full_relative_name_for_unrelated_fixed_dataset(self) -> None:
        root = Path("/data")
        clip = root / "site" / "group" / "2025-10-24-10-26"

        self.assertEqual(
            make_clip_display_name(clip, root, "fixed"),
            "site/group/2025-10-24-10-26",
        )


if __name__ == "__main__":
    unittest.main()
