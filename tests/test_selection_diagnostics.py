import importlib
import sys
import types
import unittest


class _Handler:
    def __init__(self, *args, **kwargs):
        pass


class _Selection:
    selectionCount = 1

    def selection(self, index):
        return types.SimpleNamespace(
            entity=types.SimpleNamespace(objectType="adsk::fusion::BRepFaceProxy")
        )


class _EmptySelection:
    selectionCount = 1

    def selection(self, index):
        return types.SimpleNamespace(entity=None)


class SelectionDiagnosticsTests(unittest.TestCase):
    def test_face_type_error_identifies_the_input_and_fusion_type(self):
        adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        fusion = types.ModuleType("adsk.fusion")
        core.CommandEventHandler = _Handler
        core.InputChangedEventHandler = _Handler
        core.CommandCreatedEventHandler = _Handler
        core.SelectionCommandInput = types.SimpleNamespace(cast=lambda value: value)
        fusion.BRepFace = types.SimpleNamespace(cast=lambda value: None)
        adsk.core = core
        adsk.fusion = fusion
        old_modules = {
            name: sys.modules.get(name) for name in ("adsk", "adsk.core", "adsk.fusion")
        }
        sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})
        try:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            module = importlib.import_module("FusionHeatInsertAddIn")
            inputs = types.SimpleNamespace(itemById=lambda _input_id: _Selection())
            with self.assertRaisesRegex(
                ValueError,
                r"Screw Entry Face.*adsk::fusion::BRepFaceProxy.*native planar BRepFace",
            ):
                module._selected_entity(inputs, "screw_exit_face", fusion.BRepFace.cast)
        finally:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            for name, previous in old_modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous

    def test_invalidated_face_is_resolved_from_its_cached_entity_token(self):
        adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        fusion = types.ModuleType("adsk.fusion")
        core.CommandEventHandler = _Handler
        core.InputChangedEventHandler = _Handler
        core.CommandCreatedEventHandler = _Handler
        core.SelectionCommandInput = types.SimpleNamespace(cast=lambda value: value)
        replacement = types.SimpleNamespace(objectType="adsk::fusion::BRepFace")
        design = types.SimpleNamespace(findEntityByToken=lambda token: [replacement])
        fusion.Design = types.SimpleNamespace(cast=lambda value: design)
        fusion.BRepFace = types.SimpleNamespace(cast=lambda value: value)
        adsk.core = core
        adsk.fusion = fusion
        old_modules = {
            name: sys.modules.get(name) for name in ("adsk", "adsk.core", "adsk.fusion")
        }
        sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})
        try:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            module = importlib.import_module("FusionHeatInsertAddIn")
            module.APP = types.SimpleNamespace(activeProduct=object())
            inputs = types.SimpleNamespace(itemById=lambda _input_id: _EmptySelection())
            result = module._selected_entity(
                inputs,
                "screw_exit_face",
                fusion.BRepFace.cast,
                selection_cache={"screw_exit_face": {"token": "face-token"}},
            )
            self.assertIs(result, replacement)
        finally:
            if "module" in locals():
                module.APP = None
            sys.modules.pop("FusionHeatInsertAddIn", None)
            for name, previous in old_modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous


if __name__ == "__main__":
    unittest.main()
