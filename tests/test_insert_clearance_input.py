import importlib
import sys
import types
import unittest


class _Handler:
    def __init__(self, *args, **kwargs):
        pass


class _Cast:
    @staticmethod
    def cast(value):
        return value


class InsertClearanceInputTests(unittest.TestCase):
    def test_disabled_clearance_returns_zero_even_if_hidden_length_is_invalid(self):
        adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        fusion = types.ModuleType("adsk.fusion")
        core.CommandEventHandler = _Handler
        core.InputChangedEventHandler = _Handler
        core.CommandCreatedEventHandler = _Handler
        core.ValueCommandInput = _Cast
        core.BoolValueCommandInput = _Cast
        core.DropDownCommandInput = _Cast
        adsk.core = core
        adsk.fusion = fusion
        old_modules = {name: sys.modules.get(name) for name in ("adsk", "adsk.core", "adsk.fusion")}
        sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})
        try:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            module = importlib.import_module("FusionHeatInsertAddIn")
            values = {
                "add_insert_clearance": types.SimpleNamespace(value=False),
                "insert_clearance_depth": types.SimpleNamespace(value=-1.0),
            }
            inputs = types.SimpleNamespace(itemById=values.get)
            self.assertEqual(module._insert_clearance_depth_mm(inputs), 0.0)
        finally:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            for name, previous in old_modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous

    def test_missing_tolerance_input_uses_profile_value(self):
        adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        fusion = types.ModuleType("adsk.fusion")
        core.CommandEventHandler = _Handler
        core.InputChangedEventHandler = _Handler
        core.CommandCreatedEventHandler = _Handler
        core.ValueCommandInput = _Cast
        core.BoolValueCommandInput = _Cast
        core.DropDownCommandInput = _Cast
        adsk.core = core
        adsk.fusion = fusion
        old_modules = {name: sys.modules.get(name) for name in ("adsk", "adsk.core", "adsk.fusion")}
        sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})
        try:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            module = importlib.import_module("FusionHeatInsertAddIn")
            inputs = types.SimpleNamespace(itemById=lambda _input_id: None)
            self.assertEqual(module._selected_hole_diameter_tolerance_mm(inputs), 0.0)
        finally:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            for name, previous in old_modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous


if __name__ == "__main__":
    unittest.main()
