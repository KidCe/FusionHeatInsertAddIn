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


class _Vector:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def normalize(self):
        length = (self.x**2 + self.y**2 + self.z**2) ** 0.5
        if not length:
            return False
        self.x /= length
        self.y /= length
        self.z /= length
        return True

    def dotProduct(self, other):
        return self.x * other.x + self.y * other.y + self.z * other.z


class _Point:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def vectorTo(self, other):
        return _Vector(other.x - self.x, other.y - self.y, other.z - self.z)


class _Plane:
    def __init__(self):
        self.normal = _Vector(0, 0, 1)
        self.origin = _Point(0, 0, 1)


class _ConstructionPlane:
    def __init__(self):
        self.geometry = _Plane()


class _Face:
    def __init__(self):
        self.pointOnFace = _Point(0, 0, 0)
        self.normal = _Vector(0, 0, 1)
        self.evaluator = self

    def getNormalAtPoint(self, point):
        return True, _Vector(self.normal.x, self.normal.y, self.normal.z)


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

    def setOneSideToExtent(self, to_entity, match_shape, direction_hint):
        self.directions["headToFace"] = (to_entity, match_shape, direction_hint)
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
    def test_screw_clearance_goes_inward_but_head_pocket_goes_toward_outer_face(self):
        adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        fusion = types.ModuleType("adsk.fusion")
        core.CommandEventHandler = _Handler
        core.InputChangedEventHandler = _Handler
        core.CommandCreatedEventHandler = _Handler
        core.CustomEventHandler = _Handler
        core.ValueInput = _ValueInput
        core.Plane = types.SimpleNamespace(cast=lambda value: value)
        core.SurfaceEvaluator = types.SimpleNamespace(cast=lambda value: value)
        core.Vector3D = types.SimpleNamespace(
            create=lambda x, y, z: _Vector(x, y, z)
        )
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
            screw_face = _Face()
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
                head_seat_plane=_ConstructionPlane(),
                screw_face=screw_face,
            )

            directions = component.features.holeFeatures.directions
            self.assertEqual(directions["screwClearance"], "positive")
            self.assertNotIn("headClearance", directions)
            head_to_face = directions["headToFace"]
            self.assertIs(head_to_face[0], screw_face)
            self.assertFalse(head_to_face[1])
        finally:
            sys.modules.pop("FusionHeatInsertAddIn", None)
            for name, previous in old_modules.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous


if __name__ == "__main__":
    unittest.main()
