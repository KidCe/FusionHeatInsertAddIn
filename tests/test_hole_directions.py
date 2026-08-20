import importlib
import sys
import types
import unittest


class _Handler:
    def __init__(self, *args, **kwargs):
        pass


class _ValueInput:
    @staticmethod
    def createByString(expression):
        return expression


class _ExtentDirections:
    NegativeExtentDirection = "negative"
    PositiveExtentDirection = "positive"


class _FakeHoleInput:
    def __init__(self, role, directions):
        self.role = role
        self.directions = directions
        self.participantBodies = None
        self.tipAngle = None

    def setDistanceExtent(self, value):
        return True

    def setAllExtent(self, direction):
        self.directions[self.role] = direction
        return True

    def setPositionBySketchPoints(self, points):
        return True


class _FakeFeature:
    def __init__(self):
        self.name = ""


class _FakeHoleFeatures:
    def __init__(self):
        self.directions = {}
        self.simple_count = 0

    def createCountersinkInput(self, *args):
        return _FakeHoleInput("insert", self.directions)

    def createSimpleInput(self, *args):
        self.simple_count += 1
        role = "screwClearance" if self.simple_count == 1 else "headClearance"
        return _FakeHoleInput(role, self.directions)

    def add(self, input_value):
        return _FakeFeature()


class _FakeComponent:
    def __init__(self):
        self.features = types.SimpleNamespace(holeFeatures=_FakeHoleFeatures())


class HoleDirectionTests(unittest.TestCase):
    def test_both_screw_side_holes_use_the_flipped_positive_direction(self):
        adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        fusion = types.ModuleType("adsk.fusion")
        core.CommandEventHandler = _Handler
        core.InputChangedEventHandler = _Handler
        core.CommandCreatedEventHandler = _Handler
        core.ValueInput = _ValueInput
        fusion.ExtentDirections = _ExtentDirections
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
            component = _FakeComponent()
            module._create_holes(
                component=component,
                insert_body=object(),
                screw_body=object(),
                insert_points=object(),
                screw_points=object(),
                seat_points=object(),
                names={
                    "insertHoleDiameter": "insert_diameter",
                    "insertLeadInDiameter": "lead_in_diameter",
                    "insertLeadInAngle": "lead_in_angle",
                    "insertTipAngle": "tip_angle",
                    "insertHoleDepth": "insert_depth",
                    "screwClearanceDiameter": "screw_diameter",
                    "headClearanceDiameter": "head_diameter",
                },
                connection_id="test",
                created=[],
            )

            self.assertEqual(
                component.features.holeFeatures.directions,
                {"screwClearance": "positive", "headClearance": "positive"},
            )
        finally:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            for name, previous in old_modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous


if __name__ == "__main__":
    unittest.main()
