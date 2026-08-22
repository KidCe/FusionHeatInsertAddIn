import importlib
import sys
import types
import unittest


class _Handler:
    def __init__(self, *args, **kwargs):
        pass


class _Vector:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def dotProduct(self, other):
        return self.x * other.x + self.y * other.y + self.z * other.z

    def normalize(self):
        length = (self.x**2 + self.y**2 + self.z**2) ** 0.5
        if not length:
            return False
        self.x /= length
        self.y /= length
        self.z /= length
        return True


class _Point:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def vectorTo(self, other):
        return _Vector(other.x - self.x, other.y - self.y, other.z - self.z)


class _Plane:
    def __init__(self, normal, origin):
        self.normal = normal
        self.origin = origin


class _Evaluator:
    def __init__(self, face):
        self.face = face

    def getNormalAtPoint(self, point):
        return True, _Vector(
            self.face.normal.x, self.face.normal.y, self.face.normal.z
        )

    def getParameterAtPoint(self, point):
        if abs(point.z - self.face.pointOnFace.z) > 1e-7:
            return False, None
        return True, point

    def isParameterOnFace(self, point):
        return self.face.contains(point)


class _Face:
    def __init__(self, body, z, normal, bounds=(0, 2, 0, 2)):
        self.body = body
        self.pointOnFace = _Point(0.5, 0.5, z)
        self.normal = _Vector(*normal)
        self.geometry = _Plane(_Vector(*normal), _Point(0.0, 0.0, z))
        self.evaluator = _Evaluator(self)
        self.bounds = bounds

    def contains(self, point):
        min_x, max_x, min_y, max_y = self.bounds
        return min_x <= point.x <= max_x and min_y <= point.y <= max_y

    def isPointOnFace(self, point):
        return abs(point.z - self.pointOnFace.z) <= 1e-7 and self.contains(point)


class _Collection:
    def __init__(self, items):
        self.items = list(items)
        self.count = len(self.items)

    def item(self, index):
        return self.items[index]


class _Body:
    def __init__(self, component):
        self.parentComponent = component
        self.isSolid = True
        self.faces = _Collection([])


class AutoFaceDetectionTests(unittest.TestCase):
    def setUp(self):
        adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        fusion = types.ModuleType("adsk.fusion")
        core.CommandEventHandler = _Handler
        core.InputChangedEventHandler = _Handler
        core.CommandCreatedEventHandler = _Handler
        core.SurfaceEvaluator = types.SimpleNamespace(cast=lambda evaluator: evaluator)
        core.Plane = types.SimpleNamespace(cast=lambda geometry: geometry)
        core.Point3D = types.SimpleNamespace(
            create=lambda x, y, z: _Point(x, y, z)
        )
        fusion.BRepFace = types.SimpleNamespace(cast=lambda face: face)
        adsk.core = core
        adsk.fusion = fusion
        self.old_modules = {
            name: sys.modules.get(name) for name in ("adsk", "adsk.core", "adsk.fusion")
        }
        sys.modules["adsk"] = adsk
        sys.modules["adsk.core"] = core
        sys.modules["adsk.fusion"] = fusion
        sys.modules.pop("FusionHeatInsertAddIn", None)
        self.module = importlib.import_module("FusionHeatInsertAddIn")

    def tearDown(self):
        sys.modules.pop("FusionHeatInsertAddIn", None)
        for name, previous in self.old_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    def _geometry(self, candidates):
        component = types.SimpleNamespace(bRepBodies=None)
        screw_body = _Body(component)
        insert_bodies = [_Body(component) for _ in candidates]
        screw_face = _Face(screw_body, 0.0, (0, 0, 1))
        screw_body.faces = _Collection([screw_face])
        for body, candidate in zip(insert_bodies, candidates):
            body.faces = _Collection([_Face(body, candidate, (0, 0, -1))])
        component.bRepBodies = _Collection([screw_body] + insert_bodies)
        points = [
            types.SimpleNamespace(worldGeometry=_Point(0.5, 0.5, 0.0)),
            types.SimpleNamespace(worldGeometry=_Point(1.5, 1.5, 0.0)),
        ]
        return component, screw_face, points, insert_bodies

    def test_selects_unique_opposing_face_within_point_two_mm(self):
        component, screw_face, points, insert_bodies = self._geometry([0.015, 0.03])

        result = self.module._auto_detect_insert_face(screw_face, points, component)

        self.assertIs(result.body, insert_bodies[0])

    def test_rejects_ambiguous_equally_close_faces(self):
        component, screw_face, points, _ = self._geometry([0.015, 0.015])

        with self.assertRaisesRegex(ValueError, "multiple equally close"):
            self.module._auto_detect_insert_face(screw_face, points, component)

    def test_rejects_faces_beyond_point_two_mm(self):
        component, screw_face, points, _ = self._geometry([0.021])

        with self.assertRaisesRegex(ValueError, "within 0.2 mm"):
            self.module._auto_detect_insert_face(screw_face, points, component)


if __name__ == "__main__":
    unittest.main()
