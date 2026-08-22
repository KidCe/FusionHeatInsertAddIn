import importlib
import sys
import types
import unittest


class _Handler:
    def __init__(self, *args, **kwargs):
        pass


class AddInImportTests(unittest.TestCase):
    def test_module_imports_with_minimal_adsk_surface(self):
        adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        fusion = types.ModuleType("adsk.fusion")
        core.CommandEventHandler = _Handler
        core.InputChangedEventHandler = _Handler
        core.CommandCreatedEventHandler = _Handler
        adsk.core = core
        adsk.fusion = fusion

        old_modules = {
            name: sys.modules.get(name) for name in ("adsk", "adsk.core", "adsk.fusion")
        }
        sys.modules["adsk"] = adsk
        sys.modules["adsk.core"] = core
        sys.modules["adsk.fusion"] = fusion
        try:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            module = importlib.import_module("FusionHeatInsertAddIn")
            self.assertEqual(module.ADDIN_VERSION, "0.5.13")
            self.assertTrue(callable(module.run))
            self.assertTrue(callable(module.stop))
        finally:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            for name, previous in old_modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous


if __name__ == "__main__":
    unittest.main()
