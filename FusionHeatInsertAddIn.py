"""Threaded Insert Connections MVP add-in for Autodesk Fusion.

Creates a managed Connection Set consisting of:

* a blind insert pocket with a lead-in countersink,
* a through screw-clearance hole, and
* a head-clearance pocket positioned by a distance from a selected screw-body face.

All visible UI and generated names are intentionally English.
"""

from __future__ import annotations

import json
import importlib
import math
import os
import sys
import traceback
from typing import Any, Dict, Iterable, List, Optional, Tuple

import adsk.core
import adsk.fusion


ADDIN_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if ADDIN_DIRECTORY not in sys.path:
    sys.path.insert(0, ADDIN_DIRECTORY)

import hardware_library as _hardware_library  # noqa: E402

# Fusion keeps helper modules in its embedded Python cache when an add-in is
# stopped and run again. Refresh dependencies so the main script and the JSON
# schema can never be paired with an older parser from the previous run.
_hardware_library = importlib.reload(_hardware_library)

import connection_data as _connection_data  # noqa: E402

_connection_data = importlib.reload(_connection_data)

from connection_data import (  # noqa: E402
    decode_record,
    encode_record,
    make_record,
    new_connection_id,
    parameter_specs,
    record_label,
    update_record,
)
from hardware_library import HardwareLibrary, HardwareLibraryError  # noqa: E402


ADDIN_VERSION = "0.5.13"
LIBRARY_PATH = os.path.join(ADDIN_DIRECTORY, "hardware_library.json")
COMMAND_ID = "FusionHeatInsertConnectionSet"
LEGACY_COMMAND_IDS = (
    "FusionHeatInsertCreateConnectionSet",
    "FusionHeatInsertEditConnectionSet",
)
PANEL_ID = "SolidCreatePanel"
ATTRIBUTE_GROUP = "FusionHeatInsertConnections"
RECORD_PREFIX = "ConnectionSet."
OWNER_ATTRIBUTE = "ConnectionSetId"
ROLE_ATTRIBUTE = "ConnectionSetRole"
HEAD_SHAPES = {"Button Head": "button", "Cap Head": "cap"}
HEAD_SEAT_REFERENCES = {
    "From Screw Entry Face": "entry",
    "From Screw Exit Face": "exit",
}
HOLE_DIAMETER_TOLERANCES = {
    "Profile Value (+0.00 mm)": 0.0,
    "+0.05 mm": 0.05,
    "+0.10 mm": 0.10,
    "+0.15 mm": 0.15,
    "+0.20 mm": 0.20,
}
AUTO_INSERT_FACE_DEFAULT_GAP_MM = 0.2
AUTO_INSERT_FACE_MAX_GAP_MM = 100.0
POINT_FACE_TOLERANCE_CM = 1e-4
USER_SETTINGS_FILE = "FusionHeatInsertAddIn/settings.json"
GEOMETRY_TOLERANCE_CM = 1e-5
NORMAL_PARALLEL_TOLERANCE = 1e-5
HANDLERS: List[Any] = []
APP = None
UI = None


class ConnectionSetError(ValueError):
    """Expected user-correctable problem."""


def _log(message: str) -> None:
    line = "[HeatInsertConnections] {}".format(message)
    if APP:
        APP.log(line)
    try:
        palette = UI.palettes.itemById("TextCommands") if UI else None
        if palette:
            palette.writeText(line + "\n")
    except Exception:
        pass


def _library() -> HardwareLibrary:
    return HardwareLibrary.from_path(LIBRARY_PATH)


def _user_settings_path() -> str:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, USER_SETTINGS_FILE)
    return os.path.join(
        os.path.expanduser("~"), ".fusionheatinsertaddin", "settings.json"
    )


def _saved_auto_insert_face_tolerance_mm() -> float:
    try:
        with open(_user_settings_path(), "r", encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
        value = float(settings.get("autoInsertFaceToleranceMm"))
        if 0 < value <= AUTO_INSERT_FACE_MAX_GAP_MM and math.isfinite(value):
            return value
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return AUTO_INSERT_FACE_DEFAULT_GAP_MM


def _save_auto_insert_face_tolerance_mm(value: float) -> None:
    if not (0 < value <= AUTO_INSERT_FACE_MAX_GAP_MM and math.isfinite(value)):
        return
    path = _user_settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as settings_file:
            json.dump(
                {"autoInsertFaceToleranceMm": value},
                settings_file,
                indent=2,
            )
    except OSError:
        _log("Could not save user settings: {}".format(traceback.format_exc()))


def _active_design() -> adsk.fusion.Design:
    design = adsk.fusion.Design.cast(APP.activeProduct) if APP else None
    if not design:
        raise ConnectionSetError("Open a Fusion design before using this command.")
    if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
        raise ConnectionSetError(
            "Capture Design History must be enabled. Direct Modeling designs are not supported."
        )
    return design


def _remember_selection(selection_cache, key: str, entity) -> None:
    if selection_cache is None or not entity:
        return
    selection_cache[key] = {
        "entity": entity,
        "token": getattr(entity, "entityToken", "") or "",
    }


def _resolve_cached_selection(selection_cache, key: str, cast) -> Any:
    if not selection_cache:
        return None
    cached = selection_cache.get(key) or {}
    entity = cached.get("entity")
    if entity:
        try:
            if getattr(entity, "isValid", True):
                resolved = cast(entity)
                if resolved:
                    return resolved
        except Exception:
            pass
    token = cached.get("token")
    if not token or not APP:
        return None
    try:
        design = adsk.fusion.Design.cast(APP.activeProduct)
        matches = design.findEntityByToken(token) if design else []
        for match in matches:
            resolved = cast(match)
            if resolved:
                _remember_selection(selection_cache, key, resolved)
                return resolved
    except Exception:
        _log("Selection token resolution failed for {}: {}".format(key, traceback.format_exc()))
    return None


def _selected_entity(inputs, input_id: str, cast, selection_cache=None) -> Any:
    selection = adsk.core.SelectionCommandInput.cast(inputs.itemById(input_id))
    labels = {
        "insert_face": "Insert Entry Face (Manual)",
        "screw_exit_face": "Screw Entry Face",
    }
    label = labels.get(input_id, input_id)
    if not selection or selection.selectionCount != 1:
        if selection_cache is not None:
            selection_cache.pop(input_id, None)
        raise ConnectionSetError("Select exactly one {}.".format(label))
    selected = selection.selection(0)
    raw_entity = selected.entity if selected else None
    entity = cast(raw_entity)
    if entity and getattr(entity, "isValid", True):
        _remember_selection(selection_cache, input_id, entity)
        return entity
    entity = _resolve_cached_selection(selection_cache, input_id, cast)
    if entity:
        return entity
    if not entity:
        object_type = str(
            getattr(raw_entity, "objectType", type(raw_entity).__name__)
        )
        if raw_entity is None:
            guidance = (
                "Fusion returned no entity for this visible selection. Clear the "
                "field and select the native planar face again; if Preview is enabled, "
                "turn it off while reselecting."
            )
        elif "Proxy" in object_type or getattr(raw_entity, "assemblyContext", None):
            guidance = (
                "This is an occurrence/proxy entity. Activate the target component "
                "and select its native planar face, not a face through an occurrence."
            )
        else:
            guidance = (
                "Select the planar face itself, not an edge, body, component, or sketch."
            )
        raise ConnectionSetError(
            "{} returned '{}', but a native planar BRepFace is required. {}".format(
                label, object_type, guidance
            )
        )
    return entity


def _faces_represent_same_entity(first, second) -> bool:
    if not first or not second:
        return False
    if first is second or first == second:
        return True
    for left, right in ((first, second), (second, first)):
        is_same = getattr(left, "isSame", None)
        if callable(is_same):
            try:
                if is_same(right):
                    return True
            except Exception:
                pass
    first_native = getattr(first, "nativeObject", None) or first
    second_native = getattr(second, "nativeObject", None) or second
    if first_native is second_native or first_native == second_native:
        return True
    first_token = getattr(first_native, "entityToken", "") or ""
    second_token = getattr(second_native, "entityToken", "") or ""
    if first_token and first_token == second_token:
        return True
    first_temp_id = getattr(first_native, "tempId", None)
    second_temp_id = getattr(second_native, "tempId", None)
    first_body = getattr(first_native, "body", None)
    second_body = getattr(second_native, "body", None)
    return bool(
        first_temp_id
        and first_temp_id == second_temp_id
        and first_body
        and second_body
        and (first_body is second_body or first_body == second_body)
    )


def _selected_points(inputs, selection_cache=None) -> List[adsk.fusion.SketchPoint]:
    selection = adsk.core.SelectionCommandInput.cast(inputs.itemById("locations"))
    if not selection or selection.selectionCount < 1:
        if selection_cache is not None:
            for key in list(selection_cache):
                if key.startswith("locations:"):
                    selection_cache.pop(key, None)
        raise ConnectionSetError("Select at least one sketch point as a location.")
    points = []
    for index in range(selection.selectionCount):
        key = "locations:{}".format(index)
        selected = selection.selection(index)
        raw_entity = selected.entity if selected else None
        point = adsk.fusion.SketchPoint.cast(raw_entity)
        if point and getattr(point, "isValid", True):
            _remember_selection(selection_cache, key, point)
        else:
            point = _resolve_cached_selection(
                selection_cache, key, adsk.fusion.SketchPoint.cast
            )
        if not point:
            object_type = str(
                getattr(raw_entity, "objectType", type(raw_entity).__name__)
            )
            raise ConnectionSetError(
                "Locations must be SketchPoints; Fusion returned '{}'. Select a "
                "sketch point, not a vertex or edge.".format(object_type)
            )
        points.append(point)
    return points


def _selected_dropdown_id(dropdown, profiles: Iterable[Any]) -> str:
    item = dropdown.selectedItem if dropdown else None
    if not item:
        raise ConnectionSetError("Select a hardware profile.")
    for profile in profiles:
        if profile.display_name == item.name:
            return profile.id
    raise ConnectionSetError("The selected hardware profile is no longer in the library.")


def _select_dropdown_name(dropdown, display_name: str) -> None:
    if not dropdown:
        return
    for index in range(dropdown.listItems.count):
        item = dropdown.listItems.item(index)
        if item.name == display_name:
            item.isSelected = True
            return


def _selected_thread_size(inputs) -> str:
    dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById("thread_size"))
    item = dropdown.selectedItem if dropdown else None
    if not item:
        raise ConnectionSetError("Select a Thread Size.")
    return item.name


def _profiles_for_thread(profiles: Iterable[Any], thread_size: str) -> List[Any]:
    return [profile for profile in profiles if profile.thread_size == thread_size]


def _populate_profile_dropdown(dropdown, profiles, selected_id=None) -> None:
    dropdown.listItems.clear()
    for index, profile in enumerate(profiles):
        dropdown.listItems.add(
            profile.display_name,
            profile.id == selected_id if selected_id else index == 0,
        )


def _plane_from_face(face: adsk.fusion.BRepFace) -> adsk.core.Plane:
    plane = adsk.core.Plane.cast(face.geometry)
    if not plane:
        raise ConnectionSetError("Only planar faces are supported for this connection.")
    return plane


def _plane_from_sketch(sketch: adsk.fusion.Sketch) -> adsk.core.Plane:
    reference = sketch.referencePlane
    if not reference:
        raise ConnectionSetError("The location sketch does not expose a reference plane.")
    geometry = getattr(reference, "geometry", None)
    plane = adsk.core.Plane.cast(geometry)
    if not plane:
        raise ConnectionSetError("Location points must belong to a planar sketch.")
    return plane


def _normals_are_parallel(first: adsk.core.Plane, second: adsk.core.Plane) -> bool:
    a = first.normal
    b = second.normal
    if not a.normalize() or not b.normalize():
        return False
    return abs(abs(a.dotProduct(b)) - 1.0) <= 1e-5


def _face_normal(face: adsk.fusion.BRepFace) -> adsk.core.Vector3D:
    evaluator = adsk.core.SurfaceEvaluator.cast(face.evaluator)
    if not evaluator:
        raise ConnectionSetError("Fusion could not evaluate a selected planar face.")
    success, normal = evaluator.getNormalAtPoint(face.pointOnFace)
    if not success or not normal or not normal.normalize():
        raise ConnectionSetError("Fusion could not determine the direction of a selected face.")
    return normal


def _points_are_on_face(
    face: adsk.fusion.BRepFace,
    points: List[adsk.fusion.SketchPoint],
) -> bool:
    sketch_face = _screw_face_from_locations(points)
    if sketch_face and _faces_represent_same_entity(face, sketch_face):
        return True
    evaluator = adsk.core.SurfaceEvaluator.cast(face.evaluator)
    plane = _plane_from_face(face)
    normal = plane.normal
    if not normal.normalize() or not evaluator:
        return False
    for point in points:
        world_point = getattr(point, "worldGeometry", None)
        if not world_point:
            return False
        if face.isPointOnFace(world_point):
            continue
        offset = plane.origin.vectorTo(world_point).dotProduct(normal)
        if abs(offset) > POINT_FACE_TOLERANCE_CM:
            return False
        projected = adsk.core.Point3D.create(
            world_point.x - normal.x * offset,
            world_point.y - normal.y * offset,
            world_point.z - normal.z * offset,
        )
        success, parameter = evaluator.getParameterAtPoint(projected)
        if not success or not evaluator.isParameterOnFace(parameter):
            return False
    return True


def _points_project_inside_face(
    face: adsk.fusion.BRepFace,
    points: List[adsk.fusion.SketchPoint],
) -> bool:
    evaluator = adsk.core.SurfaceEvaluator.cast(face.evaluator)
    if not evaluator:
        return False
    try:
        plane = _plane_from_face(face)
        normal = plane.normal
        if not normal.normalize():
            return False
    except ConnectionSetError:
        return False
    for point in points:
        world_point = getattr(point, "worldGeometry", None)
        if not world_point:
            return False
        # A sketch point on the Screw Entry Face is intentionally separated
        # from the candidate Insert Entry Face by the small body gap. Project
        # it onto the candidate plane before asking Fusion for face parameters;
        # passing the original off-surface point is not reliable across Fusion
        # surface evaluators.
        offset = plane.origin.vectorTo(world_point).dotProduct(normal)
        projected = adsk.core.Point3D.create(
            world_point.x - normal.x * offset,
            world_point.y - normal.y * offset,
            world_point.z - normal.z * offset,
        )
        success, parameter = evaluator.getParameterAtPoint(projected)
        if not success or not evaluator.isParameterOnFace(parameter):
            return False
    return True


def _head_clearance_direction_hint(head_seat_plane, screw_face):
    plane = adsk.core.Plane.cast(head_seat_plane.geometry)
    if not plane:
        raise ConnectionSetError("Fusion could not determine the head-seat plane direction.")
    normal = plane.normal
    if not normal.normalize():
        raise ConnectionSetError("Fusion could not normalize the head-seat plane direction.")
    outward = _face_normal(screw_face)
    if normal.dotProduct(outward) < 0:
        normal = adsk.core.Vector3D.create(-normal.x, -normal.y, -normal.z)
    return normal


def _screw_body_exit_face(
    screw_face: adsk.fusion.BRepFace,
    points: List[adsk.fusion.SketchPoint],
) -> adsk.fusion.BRepFace:
    """Find the first planar face where the screw axis leaves the screw body."""
    screw_normal = _face_normal(screw_face)
    screw_plane = _plane_from_face(screw_face)
    inward = adsk.core.Vector3D.create(
        -screw_normal.x, -screw_normal.y, -screw_normal.z
    )
    exit_candidates = []
    screw_faces = screw_face.body.faces
    for face_index in range(screw_faces.count):
        exit_face = screw_faces.item(face_index)
        if not exit_face or _faces_represent_same_entity(exit_face, screw_face):
            continue
        try:
            exit_plane = _plane_from_face(exit_face)
            exit_normal = _face_normal(exit_face)
        except ConnectionSetError:
            continue
        if screw_normal.dotProduct(exit_normal) > -1.0 + NORMAL_PARALLEL_TOLERANCE:
            continue
        exit_distance_cm = screw_plane.origin.vectorTo(
            exit_plane.origin
        ).dotProduct(inward)
        if exit_distance_cm <= GEOMETRY_TOLERANCE_CM:
            continue
        if not _points_project_inside_face(exit_face, points):
            continue
        exit_candidates.append((exit_distance_cm, exit_face))
    if not exit_candidates:
        raise ConnectionSetError(
            "Automatic Insert Face detection could not find the next planar exit "
            "surface of the Screw body along the selected Screw Entry Face direction. "
            "Select the Screw Entry Face and locations on the outer screw surface."
        )
    exit_candidates.sort(key=lambda item: item[0])
    return exit_candidates[0][1]


def _head_seat_offset_expression(
    screw_face,
    parameter_name: str,
    reference: str = "entry",
    points: Optional[List[adsk.fusion.SketchPoint]] = None,
) -> str:
    """Return a signed offset from the selected face toward the screw body."""
    base_face = _head_seat_reference_face(screw_face, reference, points)

    face_plane = _plane_from_face(base_face)
    geometry_normal = face_plane.normal
    outward_normal = _face_normal(base_face)
    if not geometry_normal.normalize():
        raise ConnectionSetError("Fusion could not normalize the screw-entry face plane.")
    alignment = geometry_normal.dotProduct(outward_normal)
    if abs(alignment) <= NORMAL_PARALLEL_TOLERANCE:
            raise ConnectionSetError("Fusion could not determine the selected head-seat reference face orientation.")
    # setByOffset follows the geometric plane normal, which can be opposite
    # to the B-Rep face's outward normal. Move opposite the outward normal so
    # the seat plane stays inside the screw body in either case.
    return "{}{}".format("-" if alignment > 0 else "", parameter_name)


def _head_seat_reference_face(
    screw_face,
    reference: str,
    points: Optional[List[adsk.fusion.SketchPoint]] = None,
):
    if reference == "entry":
        return screw_face
    if reference == "exit":
        if not points:
            raise ConnectionSetError(
                "Locations are required to determine the Screw body's exit face."
            )
        return _screw_body_exit_face(screw_face, points)
    raise ConnectionSetError("Select a valid Head Seat Position Reference.")


def _auto_detect_insert_face(
    screw_face: adsk.fusion.BRepFace,
    points: List[adsk.fusion.SketchPoint],
    component: adsk.fusion.Component,
    max_gap_mm: float = AUTO_INSERT_FACE_DEFAULT_GAP_MM,
) -> adsk.fusion.BRepFace:
    if max_gap_mm <= 0:
        raise ConnectionSetError("Automatic Insert Face tolerance must be greater than 0 mm.")
    max_gap_cm = max_gap_mm / 10.0
    screw_body = screw_face.body
    screw_normal = _face_normal(screw_face)
    screw_plane = _plane_from_face(screw_face)
    inward = adsk.core.Vector3D.create(
        -screw_normal.x, -screw_normal.y, -screw_normal.z
    )

    # First find where the ray leaves the Screw body. The configured tolerance
    # applies only after this exit, not to the complete Screw body thickness.
    exit_candidates = []
    screw_faces = screw_body.faces
    for face_index in range(screw_faces.count):
        exit_face = screw_faces.item(face_index)
        if not exit_face or _faces_represent_same_entity(exit_face, screw_face):
            continue
        try:
            exit_plane = _plane_from_face(exit_face)
            exit_normal = _face_normal(exit_face)
        except ConnectionSetError:
            continue
        if screw_normal.dotProduct(exit_normal) > -1.0 + NORMAL_PARALLEL_TOLERANCE:
            continue
        exit_distance_cm = screw_plane.origin.vectorTo(
            exit_plane.origin
        ).dotProduct(inward)
        if exit_distance_cm <= GEOMETRY_TOLERANCE_CM:
            continue
        if not _points_project_inside_face(exit_face, points):
            continue
        exit_candidates.append((exit_distance_cm, exit_face))

    if not exit_candidates:
        raise ConnectionSetError(
            "Automatic Insert Face detection could not find the next planar exit "
            "face of the Screw body along the selected Screw Entry Face direction. "
            "Select the Screw Entry Face and locations on the outer screw surface."
        )
    exit_candidates.sort(key=lambda item: item[0])
    screw_exit_distance_cm, _screw_exit_face = exit_candidates[0]
    candidates = []

    bodies = component.bRepBodies
    for body_index in range(bodies.count):
        candidate_body = bodies.item(body_index)
        if (
            not candidate_body
            or candidate_body == screw_body
            or not candidate_body.isSolid
        ):
            continue
        faces = candidate_body.faces
        for face_index in range(faces.count):
            candidate = faces.item(face_index)
            if not candidate:
                continue
            try:
                _plane_from_face(candidate)
                candidate_normal = _face_normal(candidate)
            except ConnectionSetError:
                continue

            # The Insert Entry Face faces the Screw body. Its outward normal is
            # therefore parallel to the outward normal of the Screw Entry Face.
            if screw_normal.dotProduct(candidate_normal) < 1.0 - NORMAL_PARALLEL_TOLERANCE:
                continue

            candidate_plane = _plane_from_face(candidate)
            candidate_distance_cm = screw_plane.origin.vectorTo(
                candidate_plane.origin
            ).dotProduct(inward)
            if candidate_distance_cm < screw_exit_distance_cm - GEOMETRY_TOLERANCE_CM:
                continue
            gap_cm = max(0.0, candidate_distance_cm - screw_exit_distance_cm)
            if gap_cm > max_gap_cm + GEOMETRY_TOLERANCE_CM:
                continue
            if not _points_project_inside_face(candidate, points):
                continue
            candidates.append((max(0.0, gap_cm), candidate))

    if not candidates:
        raise ConnectionSetError(
            "Automatic Insert Face detection found the Screw body's exit about "
            "{:.3g} mm behind the Screw Entry Face, but no planar face on another "
            "body was found within {:.3g} mm after that exit that covers all selected "
            "locations. Disable Auto-detect Insert Face and select the Insert Entry "
            "Face manually."
            .format(screw_exit_distance_cm * 10.0, max_gap_mm)
        )

    candidates.sort(key=lambda item: item[0])
    best_gap, best_face = candidates[0]
    if len(candidates) > 1 and abs(candidates[1][0] - best_gap) <= GEOMETRY_TOLERANCE_CM:
        raise ConnectionSetError(
            "Automatic Insert Face detection found multiple equally close candidates. "
            "Disable Auto-detect Insert Face and select the Insert Entry Face manually."
        )
    return best_face


def _auto_detect_insert_face_enabled(inputs) -> bool:
    toggle = adsk.core.BoolValueCommandInput.cast(
        inputs.itemById("auto_detect_insert_face")
    )
    return bool(toggle and toggle.value)


def _selected_auto_insert_face_tolerance_mm(inputs) -> float:
    value_input = adsk.core.ValueCommandInput.cast(
        inputs.itemById("auto_insert_face_tolerance")
    )
    if not value_input:
        return AUTO_INSERT_FACE_DEFAULT_GAP_MM
    try:
        value = float(value_input.value) * 10.0
    except (AttributeError, TypeError, ValueError):
        raise ConnectionSetError("Enter a valid Auto-detect Gap Tolerance in mm.")
    if not (0 < value <= AUTO_INSERT_FACE_MAX_GAP_MM and math.isfinite(value)):
        raise ConnectionSetError(
            "Auto-detect Gap Tolerance must be greater than 0 and no more than {:.0f} mm.".format(
                AUTO_INSERT_FACE_MAX_GAP_MM
            )
        )
    return value


def _auto_fill_screw_face_enabled(inputs) -> bool:
    toggle = adsk.core.BoolValueCommandInput.cast(
        inputs.itemById("auto_fill_screw_face")
    )
    return bool(toggle and toggle.value)


def _screw_face_from_locations(
    points: List[adsk.fusion.SketchPoint],
) -> Optional[adsk.fusion.BRepFace]:
    """Return the native planar face hosting the locations sketch, if available."""
    if not points:
        return None
    sketch = getattr(points[0], "parentSketch", None)
    if not sketch:
        return None
    if any(getattr(point, "parentSketch", None) != sketch for point in points):
        return None
    reference = getattr(sketch, "referencePlane", None)
    face = adsk.fusion.BRepFace.cast(reference)
    if not face or getattr(face, "assemblyContext", None):
        return None
    return face


def _try_auto_fill_screw_face(inputs, points, selection_cache=None) -> bool:
    if not _auto_fill_screw_face_enabled(inputs):
        return False
    screw_face = adsk.core.SelectionCommandInput.cast(
        inputs.itemById("screw_exit_face")
    )
    if not screw_face or screw_face.selectionCount:
        return False
    face = _screw_face_from_locations(points)
    if not face:
        return False
    try:
        screw_face.addSelection(face)
    except Exception:
        _log("Could not auto-fill Screw Entry Face: {}".format(traceback.format_exc()))
        return False
    _remember_selection(selection_cache, "screw_exit_face", face)
    return True


def _refresh_auto_detected_insert_face(inputs, points, selection_cache=None) -> bool:
    """Recompute and persist the hidden Insert Entry Face selection.

    Fusion does not automatically refresh a SelectionCommandInput when a
    dependent value changes. Keeping the detected face in the input also makes
    the preview state and the final validation use the same current result.
    """
    if not _auto_detect_insert_face_enabled(inputs) or not points:
        return False
    if selection_cache is not None:
        # A face-/location-/tolerance change invalidates the previous
        # detection. Keep the visible selection until a replacement is found,
        # but do not let validation reuse the stale cached entity.
        selection_cache.pop("insert_face", None)
    insert_selection = adsk.core.SelectionCommandInput.cast(
        inputs.itemById("insert_face")
    )
    if not insert_selection:
        return False
    screw_selection = adsk.core.SelectionCommandInput.cast(
        inputs.itemById("screw_exit_face")
    )
    if screw_selection and screw_selection.selectionCount:
        screw_face = _selected_entity(
            inputs, "screw_exit_face", adsk.fusion.BRepFace.cast, selection_cache
        )
    elif _auto_fill_screw_face_enabled(inputs):
        screw_face = _screw_face_from_locations(points)
    else:
        return False
    component = getattr(getattr(screw_face, "body", None), "parentComponent", None)
    if not component:
        return False
    candidate = _auto_detect_insert_face(
        screw_face,
        points,
        component,
        max_gap_mm=_selected_auto_insert_face_tolerance_mm(inputs),
    )
    insert_selection.clearSelection()
    insert_selection.addSelection(candidate)
    _remember_selection(selection_cache, "insert_face", candidate)
    return True


def _selected_create_faces(
    inputs,
    points: List[adsk.fusion.SketchPoint],
    selection_cache=None,
) -> Tuple[adsk.fusion.BRepFace, adsk.fusion.BRepFace, bool]:
    screw_selection = adsk.core.SelectionCommandInput.cast(
        inputs.itemById("screw_exit_face")
    )
    if (
        _auto_fill_screw_face_enabled(inputs)
        and screw_selection
        and screw_selection.selectionCount == 0
    ):
        screw_face = _screw_face_from_locations(points)
        if not screw_face:
            raise ConnectionSetError(
                "Auto-fill Screw Entry Face could not find a native planar face "
                "for the selected sketch. Disable Auto-fill and select the Screw "
                "Entry Face manually, or select points from a sketch based on a face."
            )
    else:
        screw_face = _selected_entity(
            inputs, "screw_exit_face", adsk.fusion.BRepFace.cast, selection_cache
        )
    auto_detect = _auto_detect_insert_face_enabled(inputs)
    if auto_detect:
        component = getattr(getattr(screw_face, "body", None), "parentComponent", None)
        if not component:
            raise ConnectionSetError(
                "The selected Screw Entry Face does not belong to a component."
            )
        insert_face = _resolve_cached_selection(
            selection_cache, "insert_face", adsk.fusion.BRepFace.cast
        )
        if not insert_face:
            insert_face = _auto_detect_insert_face(
                screw_face,
                points,
                component,
                max_gap_mm=_selected_auto_insert_face_tolerance_mm(inputs),
            )
            _remember_selection(selection_cache, "insert_face", insert_face)
    else:
        insert_face = _selected_entity(
            inputs, "insert_face", adsk.fusion.BRepFace.cast, selection_cache
        )
    return insert_face, screw_face, auto_detect


def _validate_geometry(
    insert_face: adsk.fusion.BRepFace,
    screw_face: adsk.fusion.BRepFace,
    points: List[adsk.fusion.SketchPoint],
    auto_detect_insert_face: bool = False,
) -> Tuple[adsk.fusion.Component, adsk.fusion.BRepBody, adsk.fusion.BRepBody]:
    if getattr(insert_face, "assemblyContext", None) or getattr(
        screw_face, "assemblyContext", None
    ):
        raise ConnectionSetError(
            "The MVP supports native bodies in one component, not assembly occurrence proxies."
        )
    insert_body = insert_face.body
    screw_body = screw_face.body
    if not insert_body or not screw_body or insert_body == screw_body:
        raise ConnectionSetError("Insert Entry and Screw-to-Insert faces must belong to two different solid bodies.")
    if not insert_body.isSolid or not screw_body.isSolid:
        raise ConnectionSetError("Both selected faces must belong to solid BRep bodies.")
    component = insert_body.parentComponent
    if not component or screw_body.parentComponent != component:
        raise ConnectionSetError("Both target bodies must belong to the same component in this MVP.")

    insert_plane = _plane_from_face(insert_face)
    screw_plane = _plane_from_face(screw_face)
    if not _normals_are_parallel(insert_plane, screw_plane):
        raise ConnectionSetError("Insert Entry and Screw-to-Insert faces must be parallel.")
    if not _points_are_on_face(screw_face, points):
        raise ConnectionSetError(
            "Fusion accepted the Locations as SketchPoints, but at least one point "
            "does not lie on the selected Screw Entry Face. Select the face hosting "
            "the location sketch, or choose the matching face manually."
        )

    source_sketch = points[0].parentSketch
    if not source_sketch or source_sketch.parentComponent != component:
        raise ConnectionSetError("Location sketch points must belong to the target component.")
    for point in points:
        if point.parentSketch != source_sketch:
            raise ConnectionSetError("All locations must belong to the same sketch.")
    if not _normals_are_parallel(insert_plane, _plane_from_sketch(source_sketch)):
        raise ConnectionSetError("The location sketch must be parallel to the selected faces.")
    return component, insert_body, screw_body


def _object_collection(items: Iterable[Any]) -> adsk.core.ObjectCollection:
    collection = adsk.core.ObjectCollection.create()
    for item in items:
        collection.add(item)
    return collection


def _project_points(
    component: adsk.fusion.Component,
    plane_or_face: Any,
    source_points: List[adsk.fusion.SketchPoint],
    name: str,
) -> Tuple[adsk.fusion.Sketch, adsk.core.ObjectCollection]:
    sketch = component.sketches.add(plane_or_face)
    sketch.name = name
    projected = sketch.project2(source_points, True)
    points = [adsk.fusion.SketchPoint.cast(entity) for entity in projected]
    points = [point for point in points if point]
    if len(points) != len(source_points):
        sketch.deleteMe()
        raise ConnectionSetError(
            "Fusion could not project every location onto {}.".format(name)
        )
    return sketch, _object_collection(points)


def _value(expression: str) -> adsk.core.ValueInput:
    return adsk.core.ValueInput.createByString(expression)


def _add_user_parameters(
    design: adsk.fusion.Design,
    specs: Dict[str, Dict[str, str]],
    connection_id: str,
    created: List[Any],
) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for key, spec in specs.items():
        if design.userParameters.itemByName(spec["name"]):
            raise ConnectionSetError("Parameter name already exists: {}".format(spec["name"]))
        parameter = design.userParameters.add(
            spec["name"],
            _value(spec["expression"]),
            spec["units"],
            "Threaded Insert Connection {}".format(connection_id),
        )
        if not parameter:
            raise RuntimeError("Fusion could not create parameter {}.".format(spec["name"]))
        _tag(parameter, connection_id, "parameter.{}".format(key))
        created.append(parameter)
        names[key] = parameter.name
    return names


def _tag(entity: Any, connection_id: str, role: str) -> None:
    attributes = getattr(entity, "attributes", None)
    if attributes:
        attributes.add(ATTRIBUTE_GROUP, OWNER_ATTRIBUTE, connection_id)
        attributes.add(ATTRIBUTE_GROUP, ROLE_ATTRIBUTE, role)


def _token(entity: Any) -> str:
    return getattr(entity, "entityToken", "") or ""


def _delete_if_valid(entity: Any) -> bool:
    try:
        if entity and getattr(entity, "isValid", False):
            return bool(entity.deleteMe())
    except Exception:
        _log("Cleanup failed for {}: {}".format(type(entity).__name__, traceback.format_exc()))
    return False


def _cleanup(created: List[Any]) -> bool:
    complete = True
    for entity in reversed(created):
        if getattr(entity, "isValid", False) and not _delete_if_valid(entity):
            complete = False
    return complete


def _create_holes(
    component: adsk.fusion.Component,
    insert_body: adsk.fusion.BRepBody,
    screw_body: adsk.fusion.BRepBody,
    insert_points: adsk.core.ObjectCollection,
    screw_points: adsk.core.ObjectCollection,
    seat_points: adsk.core.ObjectCollection,
    names: Dict[str, str],
    connection_id: str,
    created: List[Any],
    head_seat_plane: Any = None,
    screw_face: Any = None,
) -> Dict[str, Any]:
    holes = component.features.holeFeatures

    insert_input = holes.createCountersinkInput(
        _value(names["insertHoleDiameter"]),
        _value(names["insertLeadInDiameter"]),
        _value(names["insertLeadInAngle"]),
    )
    insert_input.tipAngle = _value(names["insertTipAngle"])
    if not insert_input.setDistanceExtent(_value(names["insertHoleDepth"])):
        raise RuntimeError("Fusion rejected the insert-hole depth.")
    if not insert_input.setPositionBySketchPoints(insert_points):
        raise RuntimeError("Fusion rejected the insert locations.")
    insert_input.participantBodies = [insert_body]
    insert_hole = holes.add(insert_input)
    if not insert_hole:
        raise RuntimeError("Fusion could not create the insert pocket.")
    insert_hole.name = "HIC {} Insert Pocket".format(connection_id)
    _tag(insert_hole, connection_id, "feature.insertPocket")
    created.append(insert_hole)

    clearance_input = holes.createSimpleInput(_value(names["screwClearanceDiameter"]))
    if not clearance_input.setAllExtent(
        adsk.fusion.ExtentDirections.PositiveExtentDirection
    ):
        raise RuntimeError("Fusion rejected the screw through-all extent.")
    if not clearance_input.setPositionBySketchPoints(screw_points):
        raise RuntimeError("Fusion rejected the screw locations.")
    clearance_input.participantBodies = [screw_body]
    screw_hole = holes.add(clearance_input)
    if not screw_hole:
        raise RuntimeError("Fusion could not create the screw clearance hole.")
    screw_hole.name = "HIC {} Screw Clearance".format(connection_id)
    _tag(screw_hole, connection_id, "feature.screwClearance")
    created.append(screw_hole)

    head_input = holes.createSimpleInput(_value(names["headClearanceDiameter"]))
    if not head_input.setPositionBySketchPoints(seat_points):
        raise RuntimeError("Fusion rejected the head-seat locations.")
    if not head_seat_plane or not screw_face:
        raise RuntimeError("Fusion could not determine the head-clearance target face.")
    if not head_input.setOneSideToExtent(
        screw_face,
        False,
        _head_clearance_direction_hint(head_seat_plane, screw_face),
    ):
        raise RuntimeError("Fusion rejected the head-clearance extent to the Screw Entry Face.")
    head_input.participantBodies = [screw_body]
    head_hole = holes.add(head_input)
    if not head_hole:
        raise RuntimeError("Fusion could not create the head-clearance pocket.")
    head_hole.name = "HIC {} Head Clearance".format(connection_id)
    _tag(head_hole, connection_id, "feature.headClearance")
    created.append(head_hole)

    return {
        "insertPocket": insert_hole,
        "screwClearance": screw_hole,
        "headClearance": head_hole,
    }


def _feature_problem(features: Iterable[Any]) -> Optional[str]:
    errors = []
    warnings = []
    for feature in features:
        state = feature.healthState
        message = feature.errorOrWarningMessage or feature.name
        if state == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
            errors.append(message)
        elif state == adsk.fusion.FeatureHealthStates.WarningFeatureHealthState:
            warnings.append(message)
    if warnings:
        _log("Feature warnings: {}".format(" | ".join(warnings)))
    return " | ".join(errors) if errors else None


def _add_timeline_group(
    design: adsk.fusion.Design, start_index: int, name: str
) -> Optional[adsk.fusion.TimelineGroup]:
    end_index = design.timeline.count - 1
    if end_index < start_index:
        return None
    group = design.timeline.timelineGroups.add(start_index, end_index)
    if group:
        group.name = name
        group.isCollapsed = True
    return group


def _record_attribute_name(connection_id: str) -> str:
    return RECORD_PREFIX + connection_id


def _save_record(design: adsk.fusion.Design, record: Dict[str, Any]) -> None:
    attribute = design.attributes.add(
        ATTRIBUTE_GROUP, _record_attribute_name(record["id"]), encode_record(record)
    )
    if not attribute:
        raise RuntimeError("Fusion could not persist the Connection Set metadata.")


def _load_records(design: adsk.fusion.Design) -> List[Dict[str, Any]]:
    records = []
    attributes = design.attributes
    for index in range(attributes.count):
        attribute = attributes.item(index)
        if (
            attribute.groupName == ATTRIBUTE_GROUP
            and attribute.name.startswith(RECORD_PREFIX)
        ):
            try:
                record = decode_record(attribute.value)
                group = _timeline_group_by_name(
                    design, record.get("timelineGroupName", "")
                )
                feature_tokens = record.get("featureTokens", {}).values()
                features_are_live = all(
                    (entity := _resolve_one(design, token))
                    and getattr(entity, "isValid", False)
                    for token in feature_tokens
                )
                if group and features_are_live:
                    records.append(record)
                else:
                    _log(
                        "Ignored orphaned Connection Set {} because its timeline group or managed features are missing."
                        .format(record.get("id", "unknown"))
                    )
            except (ValueError, json.JSONDecodeError) as error:
                _log("Ignored invalid Connection Set metadata: {}".format(error))
    return sorted(records, key=lambda item: item.get("createdAt", ""))


def _resolve_one(design: adsk.fusion.Design, token: str) -> Any:
    if not token:
        return None
    result = design.findEntityByToken(token)
    if result is None:
        return None
    if isinstance(result, (list, tuple)):
        return result[0] if result else None
    try:
        return result[0] if len(result) else None
    except (TypeError, AttributeError):
        return result


def _format_group_name(connection_id: str, thread_size: str, count: int) -> str:
    return "HIC {} — {} — {} location{}".format(
        connection_id, thread_size, count, "" if count == 1 else "s"
    )


def _seat_offset_mm(inputs) -> float:
    value_input = adsk.core.ValueCommandInput.cast(inputs.itemById("head_seat_offset"))
    if not value_input or value_input.value <= 0:
        raise ConnectionSetError(
            "Head Seat Distance must be greater than zero."
        )
    return value_input.value * 10.0


def _insert_clearance_depth_mm(inputs) -> float:
    enabled = adsk.core.BoolValueCommandInput.cast(
        inputs.itemById("add_insert_clearance")
    )
    if not enabled or not enabled.value:
        return 0.0
    value_input = adsk.core.ValueCommandInput.cast(
        inputs.itemById("insert_clearance_depth")
    )
    if not value_input or value_input.value <= 0:
        raise ConnectionSetError(
            "Additional Insert Clearance Depth must be greater than zero when enabled."
        )
    return value_input.value * 10.0


def _selected_hole_diameter_tolerance_mm(inputs) -> float:
    dropdown = adsk.core.DropDownCommandInput.cast(
        inputs.itemById("hole_diameter_tolerance")
    )
    item = dropdown.selectedItem if dropdown else None
    if not item:
        # Keep older or partially loaded dialogs usable. The profile value is
        # the safe default when the optional tolerance input is unavailable.
        return 0.0
    if item.name not in HOLE_DIAMETER_TOLERANCES:
        raise ConnectionSetError("Select an Insert Hole Diameter Tolerance.")
    return HOLE_DIAMETER_TOLERANCES[item.name]


def _select_hole_diameter_tolerance(dropdown, tolerance_mm: float) -> None:
    closest = min(
        HOLE_DIAMETER_TOLERANCES.items(),
        key=lambda item: abs(item[1] - tolerance_mm),
    )[0]
    _select_dropdown_name(dropdown, closest)


def _selected_head_shape(inputs) -> str:
    dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById("head_shape"))
    item = dropdown.selectedItem if dropdown else None
    if not item or item.name not in HEAD_SHAPES:
        raise ConnectionSetError("Select Button Head or Cap Head.")
    return HEAD_SHAPES[item.name]


def _select_head_shape(dropdown, head_shape: str) -> None:
    display_name = next(
        (name for name, value in HEAD_SHAPES.items() if value == head_shape), "Cap Head"
    )
    _select_dropdown_name(dropdown, display_name)


def _selected_head_seat_reference(inputs) -> str:
    dropdown = adsk.core.DropDownCommandInput.cast(
        inputs.itemById("head_seat_reference")
    )
    item = dropdown.selectedItem if dropdown else None
    if not item or item.name not in HEAD_SEAT_REFERENCES:
        raise ConnectionSetError("Select a Head Seat Position Reference.")
    return HEAD_SEAT_REFERENCES[item.name]


def _select_head_seat_reference(dropdown, reference: str) -> None:
    display_name = next(
        (name for name, value in HEAD_SEAT_REFERENCES.items() if value == reference),
        "From Screw Entry Face",
    )
    _select_dropdown_name(dropdown, display_name)


def _create_connection_set(inputs, selection_cache=None) -> Dict[str, Any]:
    design = _active_design()
    library = _library()
    source_points = _selected_points(inputs, selection_cache)
    insert_face, screw_face, auto_detect_insert_face = _selected_create_faces(
        inputs, source_points, selection_cache
    )
    component, insert_body, screw_body = _validate_geometry(
        insert_face,
        screw_face,
        source_points,
        auto_detect_insert_face=auto_detect_insert_face,
    )
    insert_dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById("insert_profile"))
    screw_dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById("screw_profile"))
    insert = library.insert(_selected_dropdown_id(insert_dropdown, library.inserts))
    screw = library.screw(_selected_dropdown_id(screw_dropdown, library.screws))
    head_seat_offset_mm = _seat_offset_mm(inputs)
    head_seat_reference = _selected_head_seat_reference(inputs)
    insert_clearance_depth_mm = _insert_clearance_depth_mm(inputs)
    hole_diameter_tolerance_mm = _selected_hole_diameter_tolerance_mm(inputs)
    head_shape = _selected_head_shape(inputs)
    if insert.thread_size != screw.thread_size:
        raise ConnectionSetError("Insert and screw thread sizes must match in the MVP.")

    connection_id = new_connection_id()
    # Capture source references before any feature can split or replace the
    # selected B-Rep faces in Fusion's timeline.
    insert_face_token = _token(insert_face)
    screw_exit_face_token = _token(screw_face)
    source_point_tokens = [_token(point) for point in source_points]
    specs = parameter_specs(
        connection_id,
        insert,
        screw,
        head_seat_offset_mm,
        head_shape,
        insert_clearance_depth_mm,
        hole_diameter_tolerance_mm,
    )
    start_index = design.timeline.count
    created: List[Any] = []
    timeline_group = None
    try:
        parameter_names = _add_user_parameters(design, specs, connection_id, created)

        insert_sketch, insert_points = _project_points(
            component,
            insert_face,
            source_points,
            "HIC {} — 01 Insert Locations".format(connection_id),
        )
        _tag(insert_sketch, connection_id, "helper.insertLocations")
        created.append(insert_sketch)

        screw_sketch, screw_points = _project_points(
            component,
            screw_face,
            source_points,
            "HIC {} — 02 Screw-to-Insert Locations".format(connection_id),
        )
        _tag(screw_sketch, connection_id, "helper.screwExitLocations")
        created.append(screw_sketch)

        plane_input = component.constructionPlanes.createInput()
        if not plane_input.setByOffset(
            _head_seat_reference_face(screw_face, head_seat_reference, source_points),
            _value(
                _head_seat_offset_expression(
                    screw_face,
                    parameter_names["headSeatOffset"],
                    head_seat_reference,
                    source_points,
                )
            ),
        ):
            raise RuntimeError("Fusion rejected the head-seat offset plane.")
        seat_plane = component.constructionPlanes.add(plane_input)
        if not seat_plane:
            raise RuntimeError("Fusion could not create the head-seat offset plane.")
        seat_plane.name = "HIC {} Head Seat Plane".format(connection_id)
        _tag(seat_plane, connection_id, "helper.headSeatPlane")
        created.append(seat_plane)

        seat_sketch, seat_points = _project_points(
            component,
            seat_plane,
            source_points,
            "HIC {} — 03 Head Seat Locations".format(connection_id),
        )
        _tag(seat_sketch, connection_id, "helper.headSeatLocations")
        created.append(seat_sketch)

        features = _create_holes(
            component,
            insert_body,
            screw_body,
            insert_points,
            screw_points,
            seat_points,
            parameter_names,
            connection_id,
            created,
            head_seat_plane=seat_plane,
            screw_face=screw_face,
        )
        insert_sketch.isVisible = False
        screw_sketch.isVisible = False
        seat_sketch.isVisible = False
        seat_plane.isLightBulbOn = False

        if not design.computeAll():
            raise RuntimeError("Fusion did not complete Compute All.")
        problem = _feature_problem(features.values())
        if problem:
            raise RuntimeError("Created feature error: {}".format(problem))

        group_name = _format_group_name(connection_id, insert.thread_size, len(source_points))
        timeline_group = _add_timeline_group(design, start_index, group_name)
        feature_tokens = {key: _token(value) for key, value in features.items()}
        helper_tokens = {
            "insertSketch": _token(insert_sketch),
            "screwSketch": _token(screw_sketch),
            "seatPlane": _token(seat_plane),
            "seatSketch": _token(seat_sketch),
        }
        record = make_record(
            connection_id=connection_id,
            addin_version=ADDIN_VERSION,
            insert=insert,
            screw=screw,
            head_seat_offset_mm=head_seat_offset_mm,
            head_seat_reference=head_seat_reference,
            head_shape=head_shape,
            insert_clearance_depth_mm=insert_clearance_depth_mm,
            hole_diameter_tolerance_mm=hole_diameter_tolerance_mm,
            location_count=len(source_points),
            parameter_names=parameter_names,
            feature_tokens=feature_tokens,
            helper_tokens=helper_tokens,
            insert_face_token=insert_face_token,
            screw_exit_face_token=screw_exit_face_token,
            source_point_tokens=source_point_tokens,
            timeline_group_name=group_name,
        )
        _save_record(design, record)
        return record
    except Exception:
        if timeline_group and timeline_group.isValid:
            try:
                timeline_group.deleteMe(False)
            except Exception:
                pass
        cleanup_complete = _cleanup(created)
        if not cleanup_complete:
            _log("Automatic cleanup was incomplete; use Undo once.")
        raise


def _parameter_expressions(
    record: Dict[str, Any], insert, screw, seat_offset_mm: float, head_shape: str,
    insert_clearance_depth_mm: float, hole_diameter_tolerance_mm: float = 0.0,
) -> Dict[str, str]:
    specs = parameter_specs(
        record["id"], insert, screw, seat_offset_mm, head_shape,
        insert_clearance_depth_mm,
        hole_diameter_tolerance_mm,
    )
    return {key: spec["expression"] for key, spec in specs.items()}


def _timeline_group_by_name(
    design: adsk.fusion.Design, name: str
) -> Optional[adsk.fusion.TimelineGroup]:
    groups = design.timeline.timelineGroups
    for index in range(groups.count):
        group = groups.item(index)
        if group.name == name:
            return group
    return None


def _update_connection_set(
    record: Dict[str, Any], insert, screw, seat_offset_mm: float, head_shape: str,
    insert_clearance_depth_mm: float, hole_diameter_tolerance_mm: float = 0.0,
    head_seat_reference: str = "entry",
) -> Dict[str, Any]:
    design = _active_design()
    if insert.thread_size != screw.thread_size:
        raise ConnectionSetError("Insert and screw thread sizes must match in the MVP.")
    names = record["parameterNames"]
    expressions = _parameter_expressions(
        record, insert, screw, seat_offset_mm, head_shape,
        insert_clearance_depth_mm,
        hole_diameter_tolerance_mm,
    )
    parameters: Dict[str, Any] = {}
    old_expressions: Dict[str, str] = {}
    for key, name in names.items():
        parameter = design.userParameters.itemByName(name)
        if not parameter:
            raise ConnectionSetError(
                "Connection Set {} is missing parameter {}.".format(record["id"], name)
            )
        parameters[key] = parameter
        old_expressions[key] = parameter.expression

    features: Dict[str, Any] = {}
    for role, token in record["featureTokens"].items():
        feature = _resolve_one(design, token)
        if not feature or not getattr(feature, "isValid", False):
            raise ConnectionSetError(
                "Connection Set {} is missing managed feature {}.".format(record["id"], role)
            )
        features[role] = feature

    source_screw_face = adsk.fusion.BRepFace.cast(
        _resolve_one(design, record.get("screwExitFaceToken", ""))
    )
    source_points = [
        adsk.fusion.SketchPoint.cast(_resolve_one(design, token))
        for token in record.get("sourcePointTokens", [])
    ]
    source_points = [point for point in source_points if point]
    if not source_screw_face or not source_points:
        raise ConnectionSetError(
            "Connection Set {} is missing the native Screw Entry Face or locations needed to position the head seat.".format(
                record["id"]
            )
        )
    seat_plane = _resolve_one(
        design, record.get("helperTokens", {}).get("seatPlane", "")
    )
    if not seat_plane or not getattr(seat_plane, "isValid", False):
        raise ConnectionSetError(
            "Connection Set {} is missing its managed Head Seat Plane.".format(
                record["id"]
            )
        )
    offset_expression = _head_seat_offset_expression(
        source_screw_face,
        names["headSeatOffset"],
        head_seat_reference,
        source_points,
    )
    definition = adsk.fusion.ConstructionPlaneOffsetDefinition.cast(
        seat_plane.definition
    )
    if not definition:
        raise ConnectionSetError(
            "Connection Set {} has an unsupported Head Seat Plane definition.".format(
                record["id"]
            )
        )
    old_planar_entity = definition.planarEntity
    old_offset_expression = definition.offset.expression

    try:
        for key, expression in expressions.items():
            parameters[key].expression = expression
        if not definition or not definition.redefine(
            _value(offset_expression),
            _head_seat_reference_face(
                source_screw_face, head_seat_reference, source_points
            ),
        ):
            raise RuntimeError("Fusion could not redefine the Head Seat Plane reference.")
        if not design.computeAll():
            raise RuntimeError("Fusion did not complete Compute All.")
        problem = _feature_problem(features.values())
        if problem:
            raise RuntimeError("Updated feature error: {}".format(problem))
    except Exception:
        for key, expression in old_expressions.items():
            try:
                parameters[key].expression = expression
            except Exception:
                pass
        try:
            definition.redefine(_value(old_offset_expression), old_planar_entity)
        except Exception:
            _log(
                "Could not restore the previous Head Seat Plane definition: {}".format(
                    traceback.format_exc()
                )
            )
        design.computeAll()
        raise

    feature_names = {
        "insertPocket": "HIC {} Insert Pocket".format(record["id"]),
        "screwClearance": "HIC {} Screw Clearance".format(record["id"]),
        "headClearance": "HIC {} Head Clearance".format(record["id"]),
    }
    for role, feature in features.items():
        if role in feature_names:
            feature.name = feature_names[role]

    new_group_name = _format_group_name(
        record["id"], insert.thread_size, record["locationCount"]
    )
    group = _timeline_group_by_name(design, record.get("timelineGroupName", ""))
    if group:
        group.name = new_group_name
    updated = update_record(
        record,
        addin_version=ADDIN_VERSION,
        insert=insert,
        screw=screw,
        head_seat_offset_mm=seat_offset_mm,
        head_seat_reference=head_seat_reference,
        head_shape=head_shape,
        insert_clearance_depth_mm=insert_clearance_depth_mm,
        hole_diameter_tolerance_mm=hole_diameter_tolerance_mm,
        timeline_group_name=new_group_name,
    )
    _save_record(design, updated)
    return updated


"""Legacy separate Create/Edit handlers were replaced by the unified dialog below."""

'''LEGACY_HANDLERS_REMOVED
class CreateSummaryHandler(adsk.core.InputChangedEventHandler):
    def __init__(self, library: HardwareLibrary):
        super().__init__()
        self.library = library

    def notify(self, args):
        try:
            inputs = args.inputs
            insert_dd = adsk.core.DropDownCommandInput.cast(inputs.itemById("insert_profile"))
            screw_dd = adsk.core.DropDownCommandInput.cast(inputs.itemById("screw_profile"))
            insert = self.library.insert(_selected_dropdown_id(insert_dd, self.library.inserts))
            screw = self.library.screw(_selected_dropdown_id(screw_dd, self.library.screws))
            status = adsk.core.TextBoxCommandInput.cast(inputs.itemById("profile_status"))
            compatibility = (
                "Compatible pair."
                if insert.thread_size == screw.thread_size
                else "Thread-size mismatch: choose matching Insert and Screw profiles."
            )
            status.text = (
                "{} Insert: Ø{:.3g} x {:.3g} mm, lead-in Ø{:.3g} mm. "
                "Screw: Ø{:.3g} mm, head clearance Ø{:.3g} mm."
            ).format(
                compatibility,
                insert.hole_diameter_mm,
                insert.hole_depth_mm,
                insert.lead_in_diameter_mm,
                screw.clearance_diameter_mm,
                screw.head_clearance_diameter_mm,
            )
        except Exception:
            _log("Create summary update failed: {}".format(traceback.format_exc()))


class CreateExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            record = _create_connection_set(args.command.commandInputs)
            _log("Created {}".format(record_label(record)))
            UI.messageBox(
                "Connection Set created successfully.\n\n{}\n\n"
                "Starter library dimensions must be verified against the actual hardware before manufacturing."
                .format(record_label(record)),
                "Threaded Insert Connections",
            )
        except (ConnectionSetError, HardwareLibraryError, ValueError) as error:
            _log("Create validation error: {}".format(error))
            UI.messageBox(
                "Connection Set was not created.\n\n{}".format(error),
                "Threaded Insert Connections",
            )
        except Exception:
            _log("Create failed: {}".format(traceback.format_exc()))
            UI.messageBox(
                "Connection Set creation failed.\n\n{}\n\nIf geometry remains, use Undo once."
                .format(traceback.format_exc()),
                "Threaded Insert Connections",
            )


class CreateCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            library = _library()
            command = args.command
            inputs = command.commandInputs
            inputs.addTextBoxCommandInput(
                "intro",
                "",
                "Select outward planar faces on two different bodies. Locations must be sketch points in one parallel sketch. The head-seat plane is offset inward from the Screw Exit Face.",
                3,
                True,
            )
            insert_face = inputs.addSelectionInput(
                "insert_face", "Insert Entry Face", "Select the outward insert entry face."
            )
            insert_face.addSelectionFilter("PlanarFaces")
            insert_face.setSelectionLimits(1, 1)
            screw_face = inputs.addSelectionInput(
                "screw_exit_face",
                "Screw Exit Face",
                "Select the outward face where the screw exits toward the insert body.",
            )
            screw_face.addSelectionFilter("PlanarFaces")
            screw_face.setSelectionLimits(1, 1)
            locations = inputs.addSelectionInput(
                "locations", "Locations", "Select one or more sketch points."
            )
            locations.addSelectionFilter("SketchPoints")
            locations.setSelectionLimits(1, 0)

            thread_dd = inputs.addDropDownCommandInput(
                "thread_size", "Thread Size", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            thread_sizes = sorted(
                {
                    profile.thread_size
                    for profile in tuple(library.inserts) + tuple(library.screws)
                }
            )
            for index, thread_size in enumerate(thread_sizes):
                thread_dd.listItems.add(thread_size, index == 0)
            initial_thread = thread_sizes[0]

            insert_dd = inputs.addDropDownCommandInput(
                "insert_profile", "Threaded Insert Profile", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for index, profile in enumerate(
                _profiles_for_thread(library.inserts, initial_thread)
            ):
                insert_dd.listItems.add(profile.display_name, index == 0)
            tolerance_dd = inputs.addDropDownCommandInput(
                "hole_diameter_tolerance",
                "Insert Hole Diameter Tolerance",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            for index, label in enumerate(HOLE_DIAMETER_TOLERANCES):
                tolerance_dd.listItems.add(label, index == 0)
            screw_dd = inputs.addDropDownCommandInput(
                "screw_profile", "Screw Profile", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for index, profile in enumerate(
                _profiles_for_thread(library.screws, initial_thread)
            ):
                screw_dd.listItems.add(profile.display_name, index == 0)
            inputs.addValueInput(
                "head_seat_offset",
                "Head Seat Offset from Exit Face",
                "mm",
                adsk.core.ValueInput.createByString("3 mm"),
            )
            inputs.addValueInput(
                "insert_clearance_depth",
                "Additional Insert Clearance Depth",
                "mm",
                adsk.core.ValueInput.createByString("0 mm"),
            )
            inputs.addTextBoxCommandInput(
                "profile_status",
                "",
                "Starter dimensions are loaded from hardware_library.json.",
                3,
                True,
            )
            summary_handler = CreateSummaryHandler(library)
            command.inputChanged.add(summary_handler)
            execute_handler = CreateExecuteHandler()
            command.execute.add(execute_handler)
            HANDLERS.extend((summary_handler, execute_handler))
        except Exception:
            _log("Create command setup failed: {}".format(traceback.format_exc()))
            UI.messageBox(
                "Threaded Insert Connections could not open.\n\n{}".format(
                    traceback.format_exc()
                )
            )


class EditInputHandler(adsk.core.InputChangedEventHandler):
    def __init__(
        self,
        records_by_label: Dict[str, Dict[str, Any]],
        library: HardwareLibrary,
    ):
        super().__init__()
        self.records_by_label = records_by_label
        self.library = library
        self.syncing = False

    def sync(self, inputs) -> None:
        if self.syncing:
            return
        self.syncing = True
        try:
            set_dd = adsk.core.DropDownCommandInput.cast(inputs.itemById("connection_set"))
            if not set_dd or not set_dd.selectedItem:
                return
            record = self.records_by_label.get(set_dd.selectedItem.name)
            if not record:
                return
            try:
                insert = self.library.insert(record["insertPresetId"])
                _select_dropdown_name(
                    adsk.core.DropDownCommandInput.cast(inputs.itemById("insert_profile")),
                    insert.display_name,
                )
            except HardwareLibraryError:
                pass
            try:
                screw = self.library.screw(record["screwPresetId"])
                _select_dropdown_name(
                    adsk.core.DropDownCommandInput.cast(inputs.itemById("screw_profile")),
                    screw.display_name,
                )
            except HardwareLibraryError:
                pass
            offset = adsk.core.ValueCommandInput.cast(inputs.itemById("head_seat_offset"))
            offset.value = float(record.get("headSeatOffsetMm", 3.0)) / 10.0
            info = adsk.core.TextBoxCommandInput.cast(inputs.itemById("edit_status"))
            info.text = (
                "Updates the managed dimensions at all {} locations. Faces and points are reused."
            ).format(record.get("locationCount", 0))
        finally:
            self.syncing = False

    def notify(self, args):
        try:
            if args.input.id == "connection_set":
                self.sync(args.inputs)
        except Exception:
            _log("Edit input synchronization failed: {}".format(traceback.format_exc()))


class EditExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(
        self,
        records_by_label: Dict[str, Dict[str, Any]],
        library: HardwareLibrary,
    ):
        super().__init__()
        self.records_by_label = records_by_label
        self.library = library

    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            set_dd = adsk.core.DropDownCommandInput.cast(inputs.itemById("connection_set"))
            if not set_dd or not set_dd.selectedItem:
                raise ConnectionSetError("This design does not contain a managed Connection Set.")
            record = self.records_by_label.get(set_dd.selectedItem.name)
            if not record:
                raise ConnectionSetError("The selected Connection Set metadata is unavailable.")
            insert_dd = adsk.core.DropDownCommandInput.cast(inputs.itemById("insert_profile"))
            screw_dd = adsk.core.DropDownCommandInput.cast(inputs.itemById("screw_profile"))
            insert = self.library.insert(_selected_dropdown_id(insert_dd, self.library.inserts))
            screw = self.library.screw(_selected_dropdown_id(screw_dd, self.library.screws))
            updated = _update_connection_set(record, insert, screw, _seat_offset_mm(inputs))
            _log("Updated {}".format(record_label(updated)))
            UI.messageBox(
                "Connection Set updated successfully.\n\n{}".format(record_label(updated)),
                "Threaded Insert Connections",
            )
        except (ConnectionSetError, HardwareLibraryError, ValueError) as error:
            _log("Edit validation error: {}".format(error))
            UI.messageBox(
                "Connection Set was not updated.\n\n{}".format(error),
                "Threaded Insert Connections",
            )
        except Exception:
            _log("Edit failed: {}".format(traceback.format_exc()))
            UI.messageBox(
                "Connection Set update failed. Previous parameter expressions were restored when possible.\n\n{}"
                .format(traceback.format_exc()),
                "Threaded Insert Connections",
            )


class EditCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            design = _active_design()
            library = _library()
            records = _load_records(design)
            command = args.command
            inputs = command.commandInputs
            inputs.addTextBoxCommandInput(
                "intro",
                "",
                "Change Insert and Screw profiles without selecting the target geometry again. Only supported recipe-compatible dimensions are updated.",
                3,
                True,
            )
            set_dd = inputs.addDropDownCommandInput(
                "connection_set",
                "Connection Set",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            records_by_label = {record_label(record): record for record in records}
            if records:
                for index, label in enumerate(records_by_label):
                    set_dd.listItems.add(label, index == 0)
            else:
                set_dd.listItems.add("No managed Connection Sets found", True)

            insert_dd = inputs.addDropDownCommandInput(
                "insert_profile", "Threaded Insert Profile", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for index, profile in enumerate(library.inserts):
                insert_dd.listItems.add(profile.display_name, index == 0)
            screw_dd = inputs.addDropDownCommandInput(
                "screw_profile", "Screw Profile", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for index, profile in enumerate(library.screws):
                screw_dd.listItems.add(profile.display_name, index == 0)
            inputs.addValueInput(
                "head_seat_offset",
                "Head Seat Offset from Exit Face",
                "mm",
                adsk.core.ValueInput.createByString("3 mm"),
            )
            inputs.addTextBoxCommandInput(
                "edit_status",
                "",
                "No geometry selections are required.",
                2,
                True,
            )
            input_handler = EditInputHandler(records_by_label, library)
            execute_handler = EditExecuteHandler(records_by_label, library)
            command.inputChanged.add(input_handler)
            command.execute.add(execute_handler)
            HANDLERS.extend((input_handler, execute_handler))
            input_handler.sync(inputs)
        except Exception:
            _log("Edit command setup failed: {}".format(traceback.format_exc()))
            UI.messageBox(
                "Threaded Insert Connections could not open Edit.\n\n{}".format(
                    traceback.format_exc()
                )
            )
'''


def _dialog_mode(inputs) -> str:
    dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById("dialog_mode"))
    item = dropdown.selectedItem if dropdown else None
    return "edit" if item and item.name == "Edit Existing" else "create"


def _dialog_validation_message(
    inputs, records_by_label, library, selection_cache=None
) -> Optional[str]:
    try:
        if _dialog_mode(inputs) == "edit":
            dropdown = adsk.core.DropDownCommandInput.cast(
                inputs.itemById("connection_set")
            )
            item = dropdown.selectedItem if dropdown else None
            if not item or item.name not in records_by_label:
                return "Select a managed Connection Set to edit."
        else:
            points = _selected_points(inputs, selection_cache)
            insert_face, screw_face, auto_detect = _selected_create_faces(
                inputs, points, selection_cache
            )
            _validate_geometry(
                insert_face,
                screw_face,
                points,
                auto_detect_insert_face=auto_detect,
            )

        insert_dropdown = adsk.core.DropDownCommandInput.cast(
            inputs.itemById("insert_profile")
        )
        screw_dropdown = adsk.core.DropDownCommandInput.cast(
            inputs.itemById("screw_profile")
        )
        library.insert(_selected_dropdown_id(insert_dropdown, library.inserts))
        library.screw(_selected_dropdown_id(screw_dropdown, library.screws))
        _seat_offset_mm(inputs)
        _selected_head_seat_reference(inputs)
        _insert_clearance_depth_mm(inputs)
        _selected_hole_diameter_tolerance_mm(inputs)
        _selected_head_shape(inputs)
        return None
    except (ConnectionSetError, HardwareLibraryError, ValueError) as error:
        return str(error)


def _set_dialog_status(inputs, message: str) -> None:
    status = adsk.core.TextBoxCommandInput.cast(inputs.itemById("dialog_status"))
    if status:
        status.text = message


def _dialog_status_text(validation_message: Optional[str], mode: str) -> str:
    if validation_message:
        return "Not ready — {}".format(validation_message)
    if mode == "edit":
        return "Confirmed — the selected Connection Set and options are valid. Click OK to update it."
    return "Confirmed — all required inputs are valid. Click OK to create the connection set."


class ConnectionDialogInputHandler(adsk.core.InputChangedEventHandler):
    def __init__(
        self,
        records_by_label: Dict[str, Dict[str, Any]],
        library: HardwareLibrary,
        dialog_state: Dict[str, Any],
    ):
        super().__init__()
        self.records_by_label = records_by_label
        self.library = library
        self.dialog_state = dialog_state
        self.syncing = False
        self.refreshing_auto_insert_face = False

    def _selected_record(self, inputs) -> Optional[Dict[str, Any]]:
        dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById("connection_set"))
        item = dropdown.selectedItem if dropdown else None
        return self.records_by_label.get(item.name) if item else None

    def _set_visibility(self, inputs) -> None:
        editing = _dialog_mode(inputs) == "edit"
        inputs.itemById("connection_set").isVisible = editing
        auto_detect = adsk.core.BoolValueCommandInput.cast(
            inputs.itemById("auto_detect_insert_face")
        )
        auto_detect_tolerance = adsk.core.ValueCommandInput.cast(
            inputs.itemById("auto_insert_face_tolerance")
        )
        insert_face = adsk.core.SelectionCommandInput.cast(inputs.itemById("insert_face"))
        screw_face = adsk.core.SelectionCommandInput.cast(inputs.itemById("screw_exit_face"))
        locations = adsk.core.SelectionCommandInput.cast(inputs.itemById("locations"))
        auto_fill = adsk.core.BoolValueCommandInput.cast(
            inputs.itemById("auto_fill_screw_face")
        )
        if auto_detect:
            auto_detect.isVisible = not editing
        if auto_detect_tolerance:
            auto_detect_tolerance.isVisible = not editing and bool(
                auto_detect and auto_detect.value
            )
        if auto_fill:
            auto_fill.isVisible = not editing
        insert_face.isVisible = not editing and not bool(auto_detect and auto_detect.value)
        screw_face.isVisible = not editing
        locations.isVisible = not editing
        insert_face.setSelectionLimits(
            0 if editing or bool(auto_detect and auto_detect.value) else 1, 1
        )
        screw_face.setSelectionLimits(0, 1)
        locations.setSelectionLimits(0 if editing else 1, 0)
        enabled = adsk.core.BoolValueCommandInput.cast(
            inputs.itemById("add_insert_clearance")
        )
        inputs.itemById("insert_clearance_depth").isVisible = bool(
            enabled and enabled.value
        )

    def _load_record(self, inputs) -> None:
        record = self._selected_record(inputs)
        if not record:
            return
        _select_dropdown_name(
            adsk.core.DropDownCommandInput.cast(inputs.itemById("thread_size")),
            record.get("threadSize", "M3"),
        )
        self._filter_profiles(
            inputs,
            record.get("insertPresetId"),
            record.get("screwPresetId"),
        )
        try:
            insert = self.library.insert(record["insertPresetId"])
            _select_dropdown_name(
                adsk.core.DropDownCommandInput.cast(inputs.itemById("insert_profile")),
                insert.display_name,
            )
        except HardwareLibraryError:
            pass
        try:
            screw = self.library.screw(record["screwPresetId"])
            _select_dropdown_name(
                adsk.core.DropDownCommandInput.cast(inputs.itemById("screw_profile")),
                screw.display_name,
            )
        except HardwareLibraryError:
            pass
        _select_head_shape(
            adsk.core.DropDownCommandInput.cast(inputs.itemById("head_shape")),
            record.get("headShape", "cap"),
        )
        _select_head_seat_reference(
            adsk.core.DropDownCommandInput.cast(
                inputs.itemById("head_seat_reference")
            ),
            record.get("headSeatReference", "entry"),
        )
        _select_hole_diameter_tolerance(
            adsk.core.DropDownCommandInput.cast(
                inputs.itemById("hole_diameter_tolerance")
            ),
            float(record.get("holeDiameterToleranceMm", 0.0)),
        )
        offset = adsk.core.ValueCommandInput.cast(inputs.itemById("head_seat_offset"))
        offset.value = float(record.get("headSeatOffsetMm", 3.0)) / 10.0
        clearance = adsk.core.ValueCommandInput.cast(
            inputs.itemById("insert_clearance_depth")
        )
        clearance_mm = float(record.get("insertClearanceDepthMm", 0.0))
        enabled = adsk.core.BoolValueCommandInput.cast(
            inputs.itemById("add_insert_clearance")
        )
        enabled.value = clearance_mm > 0
        clearance.value = (clearance_mm if clearance_mm > 0 else 1.0) / 10.0

    def _filter_profiles(
        self, inputs, selected_insert_id=None, selected_screw_id=None
    ) -> None:
        thread_size = _selected_thread_size(inputs)
        inserts = _profiles_for_thread(self.library.inserts, thread_size)
        screws = _profiles_for_thread(self.library.screws, thread_size)
        if not inserts or not screws:
            raise ConnectionSetError(
                "The hardware library has no complete profile pair for {}."
                .format(thread_size)
            )
        _populate_profile_dropdown(
            adsk.core.DropDownCommandInput.cast(inputs.itemById("insert_profile")),
            inserts,
            selected_insert_id,
        )
        _populate_profile_dropdown(
            adsk.core.DropDownCommandInput.cast(inputs.itemById("screw_profile")),
            screws,
            selected_screw_id,
        )

    def sync(
        self, inputs, load_record: bool = False, filter_profiles: bool = False
    ) -> None:
        if self.syncing:
            return
        self.syncing = True
        try:
            self._set_visibility(inputs)
            if load_record and _dialog_mode(inputs) == "edit":
                self._load_record(inputs)
            elif load_record or filter_profiles:
                self._filter_profiles(inputs)
            message = _dialog_validation_message(
                inputs,
                self.records_by_label,
                self.library,
                self.dialog_state.get("selection_cache"),
            )
            _set_dialog_status(inputs, _dialog_status_text(message, _dialog_mode(inputs)))
        finally:
            self.syncing = False

    def notify(self, args):
        try:
            self.dialog_state["preview_error"] = None
            if args.input.id == "auto_insert_face_tolerance":
                try:
                    _save_auto_insert_face_tolerance_mm(
                        _selected_auto_insert_face_tolerance_mm(args.inputs)
                    )
                except ConnectionSetError:
                    pass
            if args.input.id == "screw_exit_face":
                screw_face = adsk.core.SelectionCommandInput.cast(
                    args.inputs.itemById("screw_exit_face")
                )
                auto_fill = adsk.core.BoolValueCommandInput.cast(
                    args.inputs.itemById("auto_fill_screw_face")
                )
                if screw_face and screw_face.selectionCount == 0 and auto_fill:
                    # Clearing the suggestion is the explicit gesture for switching
                    # to a manual face, so do not immediately add it again.
                    auto_fill.value = False
            if args.input.id in ("locations", "auto_fill_screw_face"):
                try:
                    points = _selected_points(
                        args.inputs, self.dialog_state.get("selection_cache")
                    )
                    _try_auto_fill_screw_face(
                        args.inputs,
                        points,
                        self.dialog_state.get("selection_cache"),
                    )
                except ConnectionSetError:
                    pass
            if args.input.id in (
                "locations",
                "auto_fill_screw_face",
                "screw_exit_face",
                "auto_detect_insert_face",
                "auto_insert_face_tolerance",
            ) and not self.refreshing_auto_insert_face:
                self.refreshing_auto_insert_face = True
                try:
                    try:
                        points = _selected_points(
                            args.inputs, self.dialog_state.get("selection_cache")
                        )
                        _refresh_auto_detected_insert_face(
                            args.inputs,
                            points,
                            self.dialog_state.get("selection_cache"),
                        )
                    except ConnectionSetError:
                        # The normal validation pass below reports the specific
                        # missing or invalid input in the dialog status area.
                        pass
                finally:
                    self.refreshing_auto_insert_face = False
            self.sync(
                args.inputs,
                load_record=args.input.id in ("dialog_mode", "connection_set"),
                filter_profiles=args.input.id == "thread_size",
            )
        except Exception:
            _log("Connection dialog update failed: {}".format(traceback.format_exc()))
            _set_dialog_status(
                args.inputs,
                "Not ready — Fusion could not validate the current inputs. Check the selections and try again.",
            )


class ConnectionDialogValidateInputsHandler(
    getattr(adsk.core, "ValidateInputsEventHandler", adsk.core.CommandEventHandler)
):
    def __init__(self, records_by_label, library, dialog_state):
        super().__init__()
        self.records_by_label = records_by_label
        self.library = library
        self.dialog_state = dialog_state

    def notify(self, args):
        inputs = args.inputs
        try:
            message = self.dialog_state.get("preview_error")
            if message:
                message = "Preview is not available — {} Correct the inputs before clicking OK.".format(
                    message
                )
            else:
                message = _dialog_validation_message(
                    inputs,
                    self.records_by_label,
                    self.library,
                    self.dialog_state.get("selection_cache"),
                )
        except Exception:
            message = "Fusion could not validate the current inputs. Check the selections and try again."
            _log("Connection dialog validation failed: {}".format(traceback.format_exc()))
        args.areInputsValid = not bool(message)
        _set_dialog_status(inputs, _dialog_status_text(message, _dialog_mode(inputs)))


def _run_dialog_operation(inputs, records_by_label, library, selection_cache=None):
    if _dialog_mode(inputs) == "create":
        return "created", _create_connection_set(inputs, selection_cache)
    set_dd = adsk.core.DropDownCommandInput.cast(inputs.itemById("connection_set"))
    item = set_dd.selectedItem if set_dd else None
    record = records_by_label.get(item.name) if item else None
    if not record:
        raise ConnectionSetError(
            "This design does not contain a managed Connection Set to edit."
        )
    insert_dd = adsk.core.DropDownCommandInput.cast(inputs.itemById("insert_profile"))
    screw_dd = adsk.core.DropDownCommandInput.cast(inputs.itemById("screw_profile"))
    insert = library.insert(_selected_dropdown_id(insert_dd, library.inserts))
    screw = library.screw(_selected_dropdown_id(screw_dd, library.screws))
    return "updated", _update_connection_set(
        record,
        insert,
        screw,
        _seat_offset_mm(inputs),
        _selected_head_shape(inputs),
        _insert_clearance_depth_mm(inputs),
        _selected_hole_diameter_tolerance_mm(inputs),
        _selected_head_seat_reference(inputs),
    )


def _preview_signature(inputs, selection_cache=None):
    """Return a stable snapshot so duplicate preview events can be skipped."""
    def selected_name(input_id):
        input_value = inputs.itemById(input_id)
        item = getattr(input_value, "selectedItem", None) if input_value else None
        return getattr(item, "name", None) if item else None

    def scalar(input_id):
        input_value = inputs.itemById(input_id)
        value = getattr(input_value, "value", None) if input_value else None
        if isinstance(value, bool) or value is None:
            return value
        try:
            return round(float(value), 12)
        except (TypeError, ValueError):
            return str(value)

    def cached_token(key):
        cached = (selection_cache or {}).get(key) or {}
        return cached.get("token") or getattr(cached.get("entity"), "entityToken", "")

    return (
        selected_name("dialog_mode"),
        selected_name("connection_set"),
        selected_name("thread_size"),
        selected_name("insert_profile"),
        selected_name("screw_profile"),
        selected_name("hole_diameter_tolerance"),
        selected_name("head_shape"),
        selected_name("head_seat_reference"),
        scalar("head_seat_offset"),
        scalar("insert_clearance_depth"),
        scalar("auto_insert_face_tolerance"),
        scalar("add_insert_clearance"),
        scalar("auto_detect_insert_face"),
        cached_token("screw_exit_face"),
        cached_token("insert_face"),
        tuple(
            cached_token("locations:{}".format(index))
            for index in range(64)
            if cached_token("locations:{}".format(index))
        ),
    )


class PreviewAppearance:
    def __init__(self, records_by_label, selection_cache=None):
        self.records_by_label = records_by_label
        self.selection_cache = selection_cache
        self.original_opacity: Dict[int, Tuple[Any, float]] = {}

    def _bodies(self, inputs) -> List[Any]:
        bodies = []
        if _dialog_mode(inputs) == "create":
            points = _selected_points(inputs, self.selection_cache)
            insert_face, screw_face, _ = _selected_create_faces(
                inputs, points, self.selection_cache
            )
            for face in (insert_face, screw_face):
                if face and face.body:
                    bodies.append(face.body)
        else:
            set_dd = adsk.core.DropDownCommandInput.cast(
                inputs.itemById("connection_set")
            )
            item = set_dd.selectedItem if set_dd else None
            record = self.records_by_label.get(item.name) if item else None
            if record:
                design = _active_design()
                for role in ("insertPocket", "screwClearance"):
                    feature = _resolve_one(
                        design, record.get("featureTokens", {}).get(role, "")
                    )
                    feature_bodies = getattr(feature, "bodies", None)
                    if feature_bodies:
                        for index in range(feature_bodies.count):
                            bodies.append(feature_bodies.item(index))
        unique = []
        seen = set()
        for body in bodies:
            key = id(body)
            if key not in seen:
                seen.add(key)
                unique.append(body)
        return unique

    def apply(self, inputs) -> None:
        self.restore()
        for body in self._bodies(inputs):
            if getattr(body, "isValid", False):
                self.original_opacity[id(body)] = (body, body.opacity)
                body.opacity = 0.35

    def restore(self) -> None:
        for body, opacity in self.original_opacity.values():
            try:
                if body.isValid:
                    body.opacity = opacity
            except Exception:
                pass
        self.original_opacity.clear()


class ConnectionDialogPreviewHandler(adsk.core.CommandEventHandler):
    def __init__(self, records_by_label, library, appearance, dialog_state):
        super().__init__()
        self.records_by_label = records_by_label
        self.library = library
        self.appearance = appearance
        self.dialog_state = dialog_state

    def notify(self, args):
        preview = adsk.core.BoolValueCommandInput.cast(
            args.command.commandInputs.itemById("preview")
        )
        if not preview or not preview.value:
            self.dialog_state["preview_error"] = None
            self.dialog_state["last_preview_signature"] = None
            self.appearance.restore()
            return
        signature = _preview_signature(
            args.command.commandInputs,
            self.dialog_state.get("selection_cache"),
        )
        if signature == self.dialog_state.get("last_preview_signature"):
            args.isValidResult = not bool(self.dialog_state.get("preview_error"))
            return
        self.dialog_state["last_preview_signature"] = signature
        try:
            self.appearance.apply(args.command.commandInputs)
            _run_dialog_operation(
                args.command.commandInputs,
                self.records_by_label,
                self.library,
                self.dialog_state.get("selection_cache"),
            )
            self.dialog_state["preview_error"] = None
            args.isValidResult = True
        except (ConnectionSetError, HardwareLibraryError, ValueError) as error:
            self.appearance.restore()
            self.dialog_state["preview_error"] = str(error)
            _set_dialog_status(
                args.command.commandInputs,
                "Preview unavailable — {} Correct the inputs before clicking OK.".format(
                    error
                ),
            )
            args.isValidResult = False
        except Exception:
            self.appearance.restore()
            self.dialog_state["preview_error"] = "Fusion could not generate the preview."
            _set_dialog_status(
                args.command.commandInputs,
                "Preview failed — Fusion could not generate the preview. Correct the inputs before clicking OK.",
            )
            args.isValidResult = False
            _log("Preview failed: {}".format(traceback.format_exc()))


class ConnectionDialogDestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self, appearance):
        super().__init__()
        self.appearance = appearance

    def notify(self, args):
        self.appearance.restore()


class ConnectionDialogExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, records_by_label, library, dialog_state):
        super().__init__()
        self.records_by_label = records_by_label
        self.library = library
        self.dialog_state = dialog_state

    def notify(self, args):
        try:
            validation_message = _dialog_validation_message(
                args.command.commandInputs,
                self.records_by_label,
                self.library,
                self.dialog_state.get("selection_cache"),
            )
            if validation_message:
                message = "Not ready — {}".format(validation_message)
                _set_dialog_status(args.command.commandInputs, message)
                UI.messageBox(
                    "Connection Set was not changed.\n\n{}".format(message),
                    "Threaded Insert Connections",
                )
                return
            action, record = _run_dialog_operation(
                args.command.commandInputs,
                self.records_by_label,
                self.library,
                self.dialog_state.get("selection_cache"),
            )
            _log("Connection Set {}: {}".format(action, record_label(record)))
            UI.messageBox(
                "Connection Set {} successfully.\n\n{}\n\n"
                "Approximate starter profiles must be replaced or verified before manufacturing."
                .format(action, record_label(record)),
                    "Threaded Insert Connections",
            )
        except (ConnectionSetError, HardwareLibraryError, ValueError) as error:
            _log("Connection dialog validation error: {}".format(error))
            UI.messageBox(
                "Connection Set was not changed.\n\n{}".format(error),
                    "Threaded Insert Connections",
            )
        except Exception:
            _log("Connection dialog failed: {}".format(traceback.format_exc()))
            UI.messageBox(
                "Connection Set operation failed.\n\n{}\n\nIf new geometry remains, use Undo once."
                .format(traceback.format_exc()),
                "Threaded Insert Connections",
            )


class ConnectionDialogCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            design = _active_design()
            library = _library()
            records = _load_records(design)
            records_by_label = {record_label(record): record for record in records}
            command = args.command
            inputs = command.commandInputs

            inputs.addTextBoxCommandInput(
                "intro",
                "",
                "Create or edit a paired threaded-insert connection. In Create mode, select Locations first. The sketch hosting those points can fill the Screw Entry Face automatically. The Screw Entry Face is the planar screw-side surface; the Insert Entry Face is the planar surface where the heat-set threaded insert is installed. Native faces from one active component are required; occurrence/proxy faces are not supported.",
                4,
                True,
            )
            inputs.addTextBoxCommandInput(
                "version_info",
                "",
                "FusionHeatInsertAddIn version {}. Preview is temporary and OK is disabled until the inputs are valid.".format(
                    ADDIN_VERSION
                ),
                2,
                True,
            )
            mode = inputs.addDropDownCommandInput(
                "dialog_mode", "Action", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            mode.listItems.add("Create New", True)
            mode.listItems.add("Edit Existing", False)

            set_dd = inputs.addDropDownCommandInput(
                "connection_set",
                "Connection Set",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            for index, label in enumerate(records_by_label):
                set_dd.listItems.add(label, index == 0)
            if not records_by_label:
                set_dd.listItems.add("No managed Connection Sets found", True)

            locations = inputs.addSelectionInput(
                "locations",
                "Locations",
                "Select one or more SketchPoints that define the screw axes. These points should be on the face where the screw is inserted.",
            )
            locations.addSelectionFilter("SketchPoints")
            locations.setSelectionLimits(1, 0)
            locations.tooltip = "Connection locations"
            locations.tooltipDescription = (
                "Sketch points that define the screw axes on the screw-entry surface."
            )
            auto_fill = inputs.addBoolValueInput(
                "auto_fill_screw_face",
                "Auto-fill Screw Entry Face from Sketch",
                True,
                "",
                True,
            )
            auto_fill.isVisible = True
            auto_fill.tooltip = "Use the location sketch face"
            auto_fill.tooltipDescription = (
                "Automatically use the native planar face hosting the selected sketch points as the Screw Entry Face."
            )
            screw_face = inputs.addSelectionInput(
                "screw_exit_face",
                "Screw Entry Face",
                "The planar face on the screw-side body from which the screw is inserted. It is filled from the Locations sketch when possible; clear it to choose another native planar face manually.",
            )
            screw_face.addSelectionFilter("PlanarFaces")
            screw_face.setSelectionLimits(0, 1)
            screw_face.tooltip = "Screw Entry Face"
            screw_face.tooltipDescription = (
                "The planar face on the screw-side body from which the screw is inserted."
            )
            auto_detect = inputs.addBoolValueInput(
                "auto_detect_insert_face", "Auto-detect Insert Face", True, "", True
            )
            auto_detect.isVisible = True
            auto_detect.tooltip = "Find the Insert Entry Face automatically"
            auto_detect.tooltipDescription = (
                "Search for a parallel planar face on another solid body after the Screw body's exit."
            )
            auto_detect_tolerance = inputs.addValueInput(
                "auto_insert_face_tolerance",
                "Auto-detect Gap Tolerance",
                "mm",
                adsk.core.ValueInput.createByString(
                    "{} mm".format(_saved_auto_insert_face_tolerance_mm())
                ),
            )
            auto_detect_tolerance.isVisible = True
            auto_detect_tolerance.tooltip = "Maximum gap after the Screw body"
            auto_detect_tolerance.tooltipDescription = (
                "The maximum distance from the Screw body's exit to the Insert Entry Face. The value is in millimetres."
            )
            insert_face = inputs.addSelectionInput(
                "insert_face",
                "Insert Entry Face (Manual)",
                "The planar face on the other body where the heat-set threaded insert is installed. The generated insert pocket opens from this face; select a native planar face, not an occurrence/proxy.",
            )
            insert_face.addSelectionFilter("PlanarFaces")
            insert_face.setSelectionLimits(0, 1)
            insert_face.tooltip = "Insert Entry Face"
            insert_face.tooltipDescription = (
                "The planar face on the other body where the heat-set threaded insert is installed."
            )

            thread_dd = inputs.addDropDownCommandInput(
                "thread_size", "Thread Size", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            thread_sizes = sorted(
                {
                    profile.thread_size
                    for profile in tuple(library.inserts) + tuple(library.screws)
                }
            )
            for index, thread_size in enumerate(thread_sizes):
                thread_dd.listItems.add(thread_size, index == 0)
            initial_thread = thread_sizes[0]

            insert_dd = inputs.addDropDownCommandInput(
                "insert_profile", "Threaded Insert Profile", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for index, profile in enumerate(
                _profiles_for_thread(library.inserts, initial_thread)
            ):
                insert_dd.listItems.add(profile.display_name, index == 0)
            tolerance_dd = inputs.addDropDownCommandInput(
                "hole_diameter_tolerance",
                "Insert Hole Diameter Tolerance",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            for index, label in enumerate(HOLE_DIAMETER_TOLERANCES):
                tolerance_dd.listItems.add(label, index == 0)
            screw_dd = inputs.addDropDownCommandInput(
                "screw_profile", "Screw Profile", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for index, profile in enumerate(
                _profiles_for_thread(library.screws, initial_thread)
            ):
                screw_dd.listItems.add(profile.display_name, index == 0)
            head_shape = inputs.addDropDownCommandInput(
                "head_shape", "Head Shape", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            head_shape.listItems.add("Button Head", False)
            head_shape.listItems.add("Cap Head", True)
            head_seat_reference = inputs.addDropDownCommandInput(
                "head_seat_reference",
                "Head Seat Position Reference",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            head_seat_reference.listItems.add("From Screw Entry Face", False)
            head_seat_reference.listItems.add("From Screw Exit Face", True)
            head_seat_reference.tooltip = "Choose the face from which the head-seat distance is measured"
            head_seat_reference.tooltipDescription = (
                "Entry Face measures from the outside screw-entry surface. Exit Face measures the material thickness between the screw head seat and the screw body's exit surface."
            )
            inputs.addValueInput(
                "head_seat_offset",
                "Head Seat Distance",
                "mm",
                adsk.core.ValueInput.createByString("3 mm"),
            )
            inputs.addBoolValueInput(
                "add_insert_clearance", "Add Insert Clearance", True, "", False
            )
            clearance_input = inputs.addValueInput(
                "insert_clearance_depth",
                "Additional Insert Clearance Depth",
                "mm",
                adsk.core.ValueInput.createByString("1 mm"),
            )
            clearance_input.isVisible = False
            inputs.addBoolValueInput("preview", "Preview", True, "", False)
            inputs.addTextBoxCommandInput(
                "dialog_status",
                "",
                "Approximate library values must be verified before manufacturing.",
                3,
                True,
            )

            dialog_state = {"preview_error": None, "selection_cache": {}}
            input_handler = ConnectionDialogInputHandler(
                records_by_label, library, dialog_state
            )
            preview_appearance = PreviewAppearance(
                records_by_label, dialog_state["selection_cache"]
            )
            preview_handler = ConnectionDialogPreviewHandler(
                records_by_label, library, preview_appearance, dialog_state
            )
            validate_handler = ConnectionDialogValidateInputsHandler(
                records_by_label, library, dialog_state
            )
            destroy_handler = ConnectionDialogDestroyHandler(preview_appearance)
            execute_handler = ConnectionDialogExecuteHandler(
                records_by_label, library, dialog_state
            )
            command.inputChanged.add(input_handler)
            command.executePreview.add(preview_handler)
            command.validateInputs.add(validate_handler)
            command.execute.add(execute_handler)
            command.destroy.add(destroy_handler)
            HANDLERS.extend(
                (
                    input_handler,
                    preview_handler,
                    validate_handler,
                    execute_handler,
                    destroy_handler,
                )
            )
            input_handler.sync(inputs)
        except Exception:
            _log("Connection dialog setup failed: {}".format(traceback.format_exc()))
            UI.messageBox(
                "Threaded Insert Connections could not open.\n\n{}".format(
                    traceback.format_exc()
                )
            )


def _remove_ui() -> None:
    if not UI:
        return
    for panel_id in (PANEL_ID, "SolidScriptsAddinsPanel", "UtilityPanel"):
        panel = UI.allToolbarPanels.itemById(panel_id)
        if not panel:
            continue
        for command_id in (COMMAND_ID,) + LEGACY_COMMAND_IDS:
            control = panel.controls.itemById(command_id)
            if control:
                control.deleteMe()
    for command_id in (COMMAND_ID,) + LEGACY_COMMAND_IDS:
        definition = UI.commandDefinitions.itemById(command_id)
        if definition:
            definition.deleteMe()


def _add_control(definition) -> None:
    panel = UI.allToolbarPanels.itemById(PANEL_ID)
    if not panel:
        raise RuntimeError("Fusion Solid > Create toolbar panel was not found.")
    control = panel.controls.addCommand(definition)
    if control:
        control.isPromotedByDefault = True


def run(context):
    global APP, UI
    try:
        APP = adsk.core.Application.get()
        UI = APP.userInterface
        _library()
        _remove_ui()

        definition = UI.commandDefinitions.addButtonDefinition(
            COMMAND_ID,
            "Insert Connection",
            "Create or edit paired heat-insert and screw geometry.",
        )
        handler = ConnectionDialogCreatedHandler()
        definition.commandCreated.add(handler)
        HANDLERS.append(handler)
        _add_control(definition)
        _log("Add-in {} started.".format(ADDIN_VERSION))
    except Exception:
        message = "Threaded Insert Connections failed to start.\n\n{}".format(
            traceback.format_exc()
        )
        _log(message)
        if UI:
            UI.messageBox(message)


def stop(context):
    try:
        _remove_ui()
    finally:
        HANDLERS[:] = []
        _log("Add-in stopped.")
