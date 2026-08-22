import importlib
import sys
import types
import unittest


class _Handler:
    def __init__(self, *args, **kwargs):
        pass


class DialogStatusTests(unittest.TestCase):
    def setUp(self):
        adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        fusion = types.ModuleType("adsk.fusion")
        core.CommandEventHandler = _Handler
        core.InputChangedEventHandler = _Handler
        core.CommandCreatedEventHandler = _Handler
        core.CustomEventHandler = _Handler
        adsk.core = core
        adsk.fusion = fusion
        self.old_modules = {
            name: sys.modules.get(name) for name in ("adsk", "adsk.core", "adsk.fusion")
        }
        sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})
        sys.modules.pop("FusionHeatInsertAddIn", None)
        self.module = importlib.import_module("FusionHeatInsertAddIn")

    def tearDown(self):
        sys.modules.pop("FusionHeatInsertAddIn", None)
        for name, previous in self.old_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    def test_valid_create_state_shows_confirmation_instead_of_workflow_instructions(self):
        self.assertTrue(
            self.module._dialog_status_text(None, "create").startswith("Confirmed —")
        )

    def test_invalid_state_shows_only_the_specific_problem(self):
        self.assertEqual(
            self.module._dialog_status_text("Select Locations.", "create"),
            "Not ready — Select Locations.",
        )

    def test_preview_signature_changes_for_real_parameter_changes(self):
        values = {
            "head_seat_offset": types.SimpleNamespace(value=0.3),
            "head_seat_reference": types.SimpleNamespace(
                selectedItem=types.SimpleNamespace(name="From Screw Exit Face")
            ),
        }
        inputs = types.SimpleNamespace(itemById=values.get)

        first = self.module._preview_signature(inputs, {})
        values["head_seat_offset"].value = 0.4
        second = self.module._preview_signature(inputs, {})

        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
