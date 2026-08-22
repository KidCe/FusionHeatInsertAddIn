import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


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
        core.CustomEventHandler = _Handler
        core.SurfaceEvaluator = types.SimpleNamespace(cast=lambda evaluator: evaluator)
        core.Plane = types.SimpleNamespace(cast=lambda geometry: geometry)
        core.Point3D = types.SimpleNamespace(
            create=lambda x, y, z: _Point(x, y, z)
        )
        core.Vector3D = types.SimpleNamespace(
            create=lambda x, y, z: _Vector(x, y, z)
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
        screw_exit_face = _Face(screw_body, -0.5, (0, 0, -1))
        screw_body.faces = _Collection([screw_face, screw_exit_face])
        for body, candidate in zip(insert_bodies, candidates):
            body.faces = _Collection([_Face(body, candidate, (0, 0, 1))])
        component.bRepBodies = _Collection([screw_body] + insert_bodies)
        points = [
            types.SimpleNamespace(worldGeometry=_Point(0.5, 0.5, 0.0)),
            types.SimpleNamespace(worldGeometry=_Point(1.5, 1.5, 0.0)),
        ]
        return component, screw_face, points, insert_bodies

    def test_selects_unique_opposing_face_within_point_two_mm(self):
        component, screw_face, points, insert_bodies = self._geometry([-0.515, -0.53])

        result = self.module._auto_detect_insert_face(screw_face, points, component)

        self.assertIs(result.body, insert_bodies[0])

    def test_selects_unique_opposing_face_on_the_other_side_of_screw_face(self):
        component, screw_face, points, insert_bodies = self._geometry([-0.515, 0.515])

        result = self.module._auto_detect_insert_face(screw_face, points, component)

        self.assertIs(result.body, insert_bodies[0])

    def test_rejects_ambiguous_equally_close_faces(self):
        component, screw_face, points, _ = self._geometry([-0.515, -0.515])

        with self.assertRaisesRegex(ValueError, "multiple equally close"):
            self.module._auto_detect_insert_face(screw_face, points, component)

    def test_rejects_faces_beyond_point_two_mm(self):
        component, screw_face, points, _ = self._geometry([-0.521])

        with self.assertRaisesRegex(ValueError, "within 0.2 mm"):
            self.module._auto_detect_insert_face(screw_face, points, component)

    def test_ignores_a_candidate_on_the_outward_side_of_the_screw_face(self):
        component, screw_face, points, _ = self._geometry([0.015])

        with self.assertRaisesRegex(ValueError, "no planar face on another body"):
            self.module._auto_detect_insert_face(screw_face, points, component)

    def test_custom_gap_tolerance_can_include_a_larger_plane_distance(self):
        component, screw_face, points, insert_bodies = self._geometry([-0.53])

        result = self.module._auto_detect_insert_face(
            screw_face, points, component, max_gap_mm=0.4
        )

        self.assertIs(result.body, insert_bodies[0])

    def test_head_seat_offset_from_exit_face_uses_the_screw_body_exit(self):
        component, screw_face, points, _ = self._geometry([-0.515])

        result = self.module._head_seat_offset_expression(
            screw_face, "headSeatOffset", "exit", points
        )

        self.assertEqual(result, "-headSeatOffset")
        self.assertIs(
            self.module._head_seat_reference_face(screw_face, "exit", points),
            screw_face.body.faces.item(1),
        )

    def test_points_with_small_plane_rounding_offset_are_still_on_face(self):
        body = _Body(types.SimpleNamespace())
        face = _Face(body, 0.0, (0, 0, 1))
        points = [types.SimpleNamespace(worldGeometry=_Point(0.5, 0.5, 5e-5))]

        self.assertTrue(self.module._points_are_on_face(face, points))

    def test_auto_detect_tolerance_is_persisted_between_dialog_starts(self):
        with tempfile.TemporaryDirectory() as settings_root:
            with patch.dict(os.environ, {"APPDATA": settings_root}, clear=False):
                self.module._save_auto_insert_face_tolerance_mm(0.37)

                self.assertEqual(
                    self.module._saved_auto_insert_face_tolerance_mm(), 0.37
                )


if __name__ == "__main__":
    unittest.main()
