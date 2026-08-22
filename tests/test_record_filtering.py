import importlib
import json
import sys
import types
import unittest


class _Handler:
    def __init__(self, *args, **kwargs):
        pass


class _Collection:
    def __init__(self, items):
        self.items = items
        self.count = len(items)

    def item(self, index):
        return self.items[index]


class RecordFilteringTests(unittest.TestCase):
    def test_record_without_its_timeline_group_is_not_offered_for_editing(self):
        adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        fusion = types.ModuleType("adsk.fusion")
        core.CommandEventHandler = _Handler
        core.InputChangedEventHandler = _Handler
        core.CommandCreatedEventHandler = _Handler
        core.CustomEventHandler = _Handler
        adsk.core = core
        adsk.fusion = fusion
        old_modules = {name: sys.modules.get(name) for name in ("adsk", "adsk.core", "adsk.fusion")}
        sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})
        try:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            module = importlib.import_module("FusionHeatInsertAddIn")
            record = {
                "schemaVersion": 1,
                "id": "orphan",
                "insertPresetId": "insert",
                "screwPresetId": "screw",
                "parameterNames": {},
                "featureTokens": {"insertPocket": "feature"},
                "locationCount": 1,
                "timelineGroupName": "deleted group",
            }
            attribute = types.SimpleNamespace(
                groupName=module.ATTRIBUTE_GROUP,
                name=module.RECORD_PREFIX + "orphan",
                value=json.dumps(record),
            )
            design = types.SimpleNamespace(
                attributes=_Collection([attribute]),
                timeline=types.SimpleNamespace(timelineGroups=_Collection([])),
                findEntityByToken=lambda _token: [types.SimpleNamespace(isValid=True)],
            )
            self.assertEqual(module._load_records(design), [])
        finally:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            for name, previous in old_modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous


if __name__ == "__main__":
    unittest.main()
