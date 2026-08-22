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
        core.BoolValueCommandInput = types.SimpleNamespace(cast=lambda value: value)
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

    def test_repeated_preview_rebuilds_after_fusion_aborts_previous_transaction(self):
        class FakeAppearance:
            def __init__(self):
                self.geometry_present = False
                self.apply_count = 0

            def apply(self, inputs):
                self.apply_count += 1
                self.geometry_present = True

            def restore(self):
                self.geometry_present = False

        class FakeInputs:
            def __init__(self):
                self.preview = types.SimpleNamespace(value=True)

            def itemById(self, input_id):
                return self.preview if input_id == "preview" else None

        inputs = FakeInputs()
        command = types.SimpleNamespace(commandInputs=inputs)
        args = types.SimpleNamespace(command=command, isValidResult=False)
        appearance = FakeAppearance()
        original_operation = self.module._run_dialog_operation
        self.module._run_dialog_operation = lambda *args, **kwargs: None
        try:
            handler = self.module.ConnectionDialogPreviewHandler(
                {}, None, appearance, {"selection_cache": {}}
            )
            handler.notify(args)
            appearance.geometry_present = False  # Fusion aborts the prior preview transaction.
            handler.notify(args)
            self.assertTrue(appearance.geometry_present)
            self.assertEqual(appearance.apply_count, 2)
        finally:
            self.module._run_dialog_operation = original_operation

    def test_preview_appearance_does_not_toggle_opacity_on_rebuild(self):
        class FakeBody:
            isValid = True

            def __init__(self):
                self._opacity = 1.0
                self.opacity_changes = []

            @property
            def opacity(self):
                return self._opacity

            @opacity.setter
            def opacity(self, value):
                self.opacity_changes.append(value)
                self._opacity = value

        body = FakeBody()
        appearance = self.module.PreviewAppearance({}, {})
        appearance._bodies = lambda inputs: [body]
        appearance.apply(None)
        appearance.apply(None)
        self.assertEqual(body.opacity_changes, [0.35])


if __name__ == "__main__":
    unittest.main()
