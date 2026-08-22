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


class _Face:
    objectType = "adsk::fusion::BRepFace"
    assemblyContext = None

    def __init__(self, token="face-token"):
        self.entityToken = token


class _ConstructionPlane:
    objectType = "adsk::fusion::ConstructionPlane"


class _Sketch:
    def __init__(self, reference):
        self.referencePlane = reference


class _Point:
    def __init__(self, sketch):
        self.parentSketch = sketch


class SketchFaceAutofillTests(unittest.TestCase):
    def setUp(self):
        adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        fusion = types.ModuleType("adsk.fusion")
        core.CommandEventHandler = _Handler
        core.InputChangedEventHandler = _Handler
        core.CommandCreatedEventHandler = _Handler
        core.CustomEventHandler = _Handler
        core.ValueCommandInput = _Cast
        core.BoolValueCommandInput = types.SimpleNamespace(cast=lambda value: value)
        core.SelectionCommandInput = types.SimpleNamespace(cast=lambda value: value)
        fusion.BRepFace = types.SimpleNamespace(
            cast=lambda value: value if isinstance(value, _Face) else None
        )
        fusion.SketchPoint = types.SimpleNamespace(
            cast=lambda value: value if isinstance(value, _Point) else None
        )
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

    def test_native_planar_reference_face_is_used(self):
        face = _Face()
        point = _Point(_Sketch(face))

        self.assertIs(self.module._screw_face_from_locations([point]), face)

    def test_construction_plane_requires_manual_face_selection(self):
        point = _Point(_Sketch(_ConstructionPlane()))

        self.assertIsNone(self.module._screw_face_from_locations([point]))

    def test_face_wrappers_with_the_same_fusion_token_are_recognized_as_one_face(self):
        selected_face = _Face("same-face-token")
        sketch_face = _Face("same-face-token")

        self.assertTrue(
            self.module._faces_represent_same_entity(selected_face, sketch_face)
        )

    def test_auto_fill_adds_the_suggested_face_only_when_the_field_is_empty(self):
        class _Bool:
            value = True

        class _Selection:
            selectionCount = 0

            def addSelection(self, face):
                self.face = face
                self.selectionCount = 1

        face = _Face()
        inputs_by_id = {
            "auto_fill_screw_face": _Bool(),
            "screw_exit_face": _Selection(),
        }
        inputs = types.SimpleNamespace(itemById=lambda input_id: inputs_by_id[input_id])

        self.assertTrue(
            self.module._try_auto_fill_screw_face(inputs, [_Point(_Sketch(face))])
        )
        self.assertIs(inputs_by_id["screw_exit_face"].face, face)
        self.assertFalse(
            self.module._try_auto_fill_screw_face(inputs, [_Point(_Sketch(_Face()))])
        )

    def test_tolerance_change_replaces_the_persisted_auto_detected_face(self):
        class _Bool:
            def __init__(self, value):
                self.value = value

        class _Selection:
            def __init__(self, face=None):
                self.selected = face
                self.selectionCount = 1 if face else 0

            def selection(self, _index):
                return types.SimpleNamespace(entity=self.selected)

            def clearSelection(self):
                self.selected = None
                self.selectionCount = 0

            def addSelection(self, face):
                self.selected = face
                self.selectionCount = 1

        component = types.SimpleNamespace()
        body = types.SimpleNamespace(parentComponent=component)
        screw_face = _Face("screw")
        screw_face.body = body
        candidate = _Face("candidate")
        candidate.body = types.SimpleNamespace(parentComponent=component)
        points = [_Point(_Sketch(screw_face))]
        values = {
            "auto_detect_insert_face": _Bool(True),
            "auto_fill_screw_face": _Bool(False),
            "auto_insert_face_tolerance": types.SimpleNamespace(value=0.05),
            "screw_exit_face": _Selection(screw_face),
            "insert_face": _Selection(),
        }
        inputs = types.SimpleNamespace(itemById=values.get)
        with unittest.mock.patch.object(
            self.module, "_auto_detect_insert_face", return_value=candidate
        ) as detect:
            self.assertTrue(
                self.module._refresh_auto_detected_insert_face(inputs, points)
            )

        detect.assert_called_once()
        self.assertIs(values["insert_face"].selected, candidate)
        self.assertEqual(detect.call_args.kwargs["max_gap_mm"], 0.5)

    def test_parameter_validation_reuses_the_cached_auto_detected_face(self):
        class _Bool:
            def __init__(self, value):
                self.value = value

        class _Selection:
            def __init__(self, face=None):
                self.selected = face
                self.selectionCount = 1 if face else 0

            def selection(self, _index):
                return types.SimpleNamespace(entity=self.selected)

        component = types.SimpleNamespace()
        screw_face = _Face("screw")
        screw_face.body = types.SimpleNamespace(parentComponent=component)
        candidate = _Face("candidate")
        candidate.body = types.SimpleNamespace(parentComponent=component)
        values = {
            "auto_detect_insert_face": _Bool(True),
            "auto_fill_screw_face": _Bool(False),
            "auto_insert_face_tolerance": types.SimpleNamespace(value=0.02),
            "screw_exit_face": _Selection(screw_face),
            "insert_face": _Selection(candidate),
        }
        inputs = types.SimpleNamespace(itemById=values.get)
        cache = {"insert_face": {"entity": candidate, "token": "candidate"}}
        with unittest.mock.patch.object(
            self.module,
            "_auto_detect_insert_face",
            side_effect=AssertionError("auto-detection should be cached"),
        ):
            insert_face, selected_screw_face, auto_detect = (
                self.module._selected_create_faces(inputs, [_Point(_Sketch(screw_face))], cache)
            )

        self.assertIs(insert_face, candidate)
        self.assertIs(selected_screw_face, screw_face)
        self.assertTrue(auto_detect)


if __name__ == "__main__":
    unittest.main()
