import unittest

from preannotation_service import index_v2v_rows, nearest_v2v_rows, v2v_row_timestamp


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


if __name__ == "__main__":
    unittest.main()
