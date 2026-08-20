import unittest
from pathlib import Path

from connection_data import (
    decode_record,
    encode_record,
    make_record,
    parameter_prefix,
    parameter_specs,
    record_label,
    update_record,
)
from hardware_library import HardwareLibrary


ROOT = Path(__file__).resolve().parents[1]


class ConnectionDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = HardwareLibrary.from_path(ROOT / "hardware_library.json")
        cls.insert = cls.library.insert("generic-m3-user-example")
        cls.screw = cls.library.screw("generic-m3-socket-head-user-example")

    def test_parameter_specs_are_namespaced_and_dimensioned(self):
        specs = parameter_specs(
            "1a-2b", self.insert, self.screw, 3.25, "button", 2.0
        )

        self.assertEqual(parameter_prefix("1a-2b"), "HIC_C_1a_2b")
        self.assertEqual(specs["insertHoleDiameter"]["expression"], "4.05 mm")
        self.assertEqual(specs["screwClearanceDiameter"]["expression"], "3.5 mm")
        self.assertEqual(specs["headSeatOffset"]["expression"], "3.25 mm")
        self.assertEqual(specs["headClearanceDiameter"]["expression"], "6.2 mm")
        self.assertEqual(specs["insertHoleDepth"]["expression"], "7 mm")

    def test_mismatched_thread_sizes_are_rejected(self):
        m4_screw = self.library.screw("generic-m4-socket-head-starter")
        with self.assertRaisesRegex(ValueError, "thread sizes must match"):
            parameter_specs("abc", self.insert, m4_screw, 3.0)

    def test_negative_additional_insert_clearance_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            parameter_specs("abc", self.insert, self.screw, 3.0, "cap", -0.1)

    def test_record_round_trip_and_update(self):
        specs = parameter_specs("abc123", self.insert, self.screw, 3.0)
        names = {key: spec["name"] for key, spec in specs.items()}
        record = make_record(
            connection_id="abc123",
            addin_version="0.1.0",
            insert=self.insert,
            screw=self.screw,
            head_seat_offset_mm=3.0,
            head_shape="cap",
            insert_clearance_depth_mm=0.0,
            location_count=3,
            parameter_names=names,
            feature_tokens={"insertPocket": "feature-token"},
            helper_tokens={"seatPlane": "plane-token"},
            insert_face_token="insert-face",
            screw_exit_face_token="screw-face",
            source_point_tokens=["p1", "p2", "p3"],
            timeline_group_name="HIC abc123 — M3 — 3 locations",
        )

        decoded = decode_record(encode_record(record))
        self.assertEqual(decoded["locationCount"], 3)
        self.assertEqual(record_label(decoded), "HIC abc123 — M3 — 3 locations")

        m4_insert = self.library.insert("generic-m4-starter")
        m4_screw = self.library.screw("generic-m4-socket-head-starter")
        updated = update_record(
            decoded,
            addin_version="0.1.1",
            insert=m4_insert,
            screw=m4_screw,
            head_seat_offset_mm=4.0,
            head_shape="button",
            insert_clearance_depth_mm=2.5,
            timeline_group_name="HIC abc123 — M4 — 3 locations",
        )
        self.assertEqual(updated["threadSize"], "M4")
        self.assertEqual(updated["headSeatOffsetMm"], 4.0)
        self.assertEqual(updated["headShape"], "button")
        self.assertEqual(updated["insertClearanceDepthMm"], 2.5)
        self.assertEqual(decoded["threadSize"], "M3")


if __name__ == "__main__":
    unittest.main()
