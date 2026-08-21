import json
import tempfile
import unittest
from pathlib import Path

import hardware_library


ROOT = Path(__file__).resolve().parents[1]


class HardwareLibraryTests(unittest.TestCase):
    def test_starter_library_loads(self):
        library = hardware_library.HardwareLibrary.from_path(ROOT / "hardware_library.json")

        self.assertEqual(library.schema_version, 1)
        self.assertGreaterEqual(len(library.inserts), 3)
        self.assertGreaterEqual(len(library.screws), 3)

    def test_user_m3_values_are_preserved(self):
        library = hardware_library.HardwareLibrary.from_path(ROOT / "hardware_library.json")
        insert = library.insert("generic-m3-user-example")
        screw = library.screw("generic-m3-socket-head-user-example")

        self.assertEqual(insert.thread_size, "M3")
        self.assertAlmostEqual(insert.hole_diameter_mm, 4.05)
        self.assertAlmostEqual(insert.hole_depth_mm, 5.0)
        self.assertAlmostEqual(screw.clearance_diameter_mm, 3.5)
        self.assertAlmostEqual(screw.head_clearance_diameter_mm("cap"), 6.5)
        self.assertAlmostEqual(screw.head_clearance_diameter_mm("button"), 6.2)

    def test_approximate_m2_and_m4_examples_are_available(self):
        library = hardware_library.HardwareLibrary.from_path(ROOT / "hardware_library.json")
        self.assertEqual(library.insert("generic-m2-starter").thread_size, "M2")
        self.assertEqual(library.screw("generic-m2-screw-starter").thread_size, "M2")
        self.assertEqual(library.insert("generic-m4-starter").thread_size, "M4")

    def test_ruthex_profiles_and_researched_screw_profiles_are_available(self):
        library = hardware_library.HardwareLibrary.from_path(ROOT / "hardware_library.json")
        voron = library.insert("ruthex-rx-m3x5x4-voron")
        screw = library.screw("iso273-iso7380-iso4762-m6")

        self.assertAlmostEqual(voron.hole_diameter_mm, 4.4)
        self.assertAlmostEqual(voron.lead_in_diameter_mm, 5.0)
        self.assertAlmostEqual(screw.head_clearance_diameter_mm("button"), 10.9)
        self.assertAlmostEqual(screw.head_clearance_diameter_mm("cap"), 10.4)
        self.assertAlmostEqual(screw.head_clearance_allowance_mm, 0.4)

    def test_duplicate_profile_id_is_rejected(self):
        payload = json.loads((ROOT / "hardware_library.json").read_text(encoding="utf-8"))
        payload["insertProfiles"].append(dict(payload["insertProfiles"][0]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(hardware_library.HardwareLibraryError, "Duplicate insert profile id"):
                hardware_library.HardwareLibrary.from_path(path)

    def test_invalid_lead_in_is_rejected(self):
        payload = json.loads((ROOT / "hardware_library.json").read_text(encoding="utf-8"))
        payload["insertProfiles"][0]["leadInDiameterMm"] = payload["insertProfiles"][0]["holeDiameterMm"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(hardware_library.HardwareLibraryError, "must be larger"):
                hardware_library.HardwareLibrary.from_path(path)


if __name__ == "__main__":
    unittest.main()
