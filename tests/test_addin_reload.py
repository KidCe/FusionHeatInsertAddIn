import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AddInReloadTests(unittest.TestCase):
    def test_reload_source_executes_for_fusion_main_module_without_spec(self):
        script = textwrap.dedent(
            """
            import importlib
            import sys
            import tempfile
            import types
            from pathlib import Path

            class Handler:
                def __init__(self, *args, **kwargs):
                    pass

            adsk = types.ModuleType("adsk")
            core = types.ModuleType("adsk.core")
            fusion = types.ModuleType("adsk.fusion")
            core.CommandEventHandler = Handler
            core.InputChangedEventHandler = Handler
            core.CommandCreatedEventHandler = Handler
            core.CustomEventHandler = Handler
            adsk.core = core
            adsk.fusion = fusion
            sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})

            addin = importlib.import_module("FusionHeatInsertAddIn")
            fusion_main = types.ModuleType("__main__C%3A%2Ffusion%2FFusionHeatInsertAddIn_py")
            fusion_main.__spec__ = None
            with tempfile.TemporaryDirectory() as temp_dir:
                source_path = Path(temp_dir) / "FusionHeatInsertAddIn.py"
                source_path.write_text("RELOADED_VALUE = 42\\n", encoding="utf-8")
                loaded = addin._execute_module_source(fusion_main, str(source_path))
                assert loaded is fusion_main
                assert loaded.RELOADED_VALUE == 42
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_import_refreshes_a_stale_cached_hardware_library(self):
        script = textwrap.dedent(
            """
            import importlib
            import sys
            import types

            class Handler:
                def __init__(self, *args, **kwargs):
                    pass

            adsk = types.ModuleType("adsk")
            core = types.ModuleType("adsk.core")
            fusion = types.ModuleType("adsk.fusion")
            core.CommandEventHandler = Handler
            core.InputChangedEventHandler = Handler
            core.CommandCreatedEventHandler = Handler
            core.CustomEventHandler = Handler
            adsk.core = core
            adsk.fusion = fusion
            sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})

            import hardware_library

            def stale_parser(_path):
                raise hardware_library.HardwareLibraryError(
                    "screwProfiles[0].headClearanceDiameterMm must be a positive number."
                )

            hardware_library.HardwareLibrary.from_path = stale_parser
            module = importlib.import_module("FusionHeatInsertAddIn")
            assert module._library().schema_version == 1
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reload_button_queues_fusion_custom_event(self):
        script = textwrap.dedent(
            """
            import importlib
            import sys
            import types

            class Handler:
                def __init__(self, *args, **kwargs):
                    pass

            adsk = types.ModuleType("adsk")
            core = types.ModuleType("adsk.core")
            fusion = types.ModuleType("adsk.fusion")
            core.CommandEventHandler = Handler
            core.InputChangedEventHandler = Handler
            core.CommandCreatedEventHandler = Handler
            core.CustomEventHandler = Handler
            adsk.core = core
            adsk.fusion = fusion
            sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})

            module = importlib.import_module("FusionHeatInsertAddIn")

            class FakeApplication:
                def __init__(self):
                    self.events = []

                def fireCustomEvent(self, event_id):
                    self.events.append(event_id)
                    return True

            class FakeUi:
                statusMessage = ""

            app = FakeApplication()
            module.APP = app
            module.UI = FakeUi()
            module.ReloadAddInCommandExecuteHandler().notify(None)
            assert app.events == [module.RELOAD_EVENT_ID]
            assert module.UI.statusMessage.startswith("Reloading")
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
