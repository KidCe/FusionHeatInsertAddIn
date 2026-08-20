"""Heat Insert Connections MVP add-in for Autodesk Fusion.

Creates a managed Connection Set consisting of:

* a blind insert pocket with a lead-in countersink,
* a through screw-clearance hole, and
* a head-clearance pocket positioned by its distance from the Screw-to-Insert Face.

All visible UI and generated names are intentionally English.
"""

from __future__ import annotations

import json
import importlib
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


ADDIN_VERSION = "0.3.1"
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


def _active_design() -> adsk.fusion.Design:
    design = adsk.fusion.Design.cast(APP.activeProduct) if APP else None
    if not design:
        raise ConnectionSetError("Open a Fusion design before using this command.")
    if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
        raise ConnectionSetError(
            "Capture Design History must be enabled. Direct Modeling designs are not supported."
        )
    return design


def _selected_entity(inputs, input_id: str, cast) -> Any:
    selection = adsk.core.SelectionCommandInput.cast(inputs.itemById(input_id))
    if not selection or selection.selectionCount != 1:
        raise ConnectionSetError("Complete every required face selection.")
    entity = cast(selection.selection(0).entity)
    if not entity:
        raise ConnectionSetError("A selected entity has the wrong type.")
    return entity


def _selected_points(inputs) -> List[adsk.fusion.SketchPoint]:
    selection = adsk.core.SelectionCommandInput.cast(inputs.itemById("locations"))
    if not selection or selection.selectionCount < 1:
        raise ConnectionSetError("Select at least one sketch point as a location.")
    points = []
    for index in range(selection.selectionCount):
        point = adsk.fusion.SketchPoint.cast(selection.selection(index).entity)
        if not point:
            raise ConnectionSetError("Locations must be sketch points.")
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
        raise ConnectionSetError("Only planar Insert Entry and Screw-to-Insert faces are supported.")
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


def _validate_geometry(
    insert_face: adsk.fusion.BRepFace,
    screw_face: adsk.fusion.BRepFace,
    points: List[adsk.fusion.SketchPoint],
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
            "Heat Insert Connection {}".format(connection_id),
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
    if not head_input.setAllExtent(adsk.fusion.ExtentDirections.PositiveExtentDirection):
        raise RuntimeError("Fusion rejected the head-clearance extent.")
    if not head_input.setPositionBySketchPoints(seat_points):
        raise RuntimeError("Fusion rejected the head-seat locations.")
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
            "Head Seat Distance from Screw-to-Insert Face must be greater than zero."
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


def _create_connection_set(inputs) -> Dict[str, Any]:
    design = _active_design()
    library = _library()
    insert_face = _selected_entity(inputs, "insert_face", adsk.fusion.BRepFace.cast)
    screw_face = _selected_entity(inputs, "screw_exit_face", adsk.fusion.BRepFace.cast)
    source_points = _selected_points(inputs)
    component, insert_body, screw_body = _validate_geometry(
        insert_face, screw_face, source_points
    )
    insert_dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById("insert_profile"))
    screw_dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById("screw_profile"))
    insert = library.insert(_selected_dropdown_id(insert_dropdown, library.inserts))
    screw = library.screw(_selected_dropdown_id(screw_dropdown, library.screws))
    head_seat_offset_mm = _seat_offset_mm(inputs)
    insert_clearance_depth_mm = _insert_clearance_depth_mm(inputs)
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
            screw_face, _value("-{}".format(parameter_names["headSeatOffset"]))
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
            head_shape=head_shape,
            insert_clearance_depth_mm=insert_clearance_depth_mm,
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
    insert_clearance_depth_mm: float,
) -> Dict[str, str]:
    specs = parameter_specs(
        record["id"], insert, screw, seat_offset_mm, head_shape,
        insert_clearance_depth_mm,
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
    insert_clearance_depth_mm: float,
) -> Dict[str, Any]:
    design = _active_design()
    if insert.thread_size != screw.thread_size:
        raise ConnectionSetError("Insert and screw thread sizes must match in the MVP.")
    names = record["parameterNames"]
    expressions = _parameter_expressions(
        record, insert, screw, seat_offset_mm, head_shape,
        insert_clearance_depth_mm,
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

    try:
        for key, expression in expressions.items():
            parameters[key].expression = expression
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
        head_shape=head_shape,
        insert_clearance_depth_mm=insert_clearance_depth_mm,
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
                "Heat Insert Connections",
            )
        except (ConnectionSetError, HardwareLibraryError, ValueError) as error:
            _log("Create validation error: {}".format(error))
            UI.messageBox(
                "Connection Set was not created.\n\n{}".format(error),
                "Heat Insert Connections",
            )
        except Exception:
            _log("Create failed: {}".format(traceback.format_exc()))
            UI.messageBox(
                "Connection Set creation failed.\n\n{}\n\nIf geometry remains, use Undo once."
                .format(traceback.format_exc()),
                "Heat Insert Connections",
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
                "insert_profile", "Insert Profile", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for index, profile in enumerate(
                _profiles_for_thread(library.inserts, initial_thread)
            ):
                insert_dd.listItems.add(profile.display_name, index == 0)
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
                "Heat Insert Connections could not open.\n\n{}".format(
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
                "Heat Insert Connections",
            )
        except (ConnectionSetError, HardwareLibraryError, ValueError) as error:
            _log("Edit validation error: {}".format(error))
            UI.messageBox(
                "Connection Set was not updated.\n\n{}".format(error),
                "Heat Insert Connections",
            )
        except Exception:
            _log("Edit failed: {}".format(traceback.format_exc()))
            UI.messageBox(
                "Connection Set update failed. Previous parameter expressions were restored when possible.\n\n{}"
                .format(traceback.format_exc()),
                "Heat Insert Connections",
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
                "insert_profile", "Insert Profile", adsk.core.DropDownStyles.TextListDropDownStyle
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
                "Heat Insert Connections could not open Edit.\n\n{}".format(
                    traceback.format_exc()
                )
            )
'''


def _dialog_mode(inputs) -> str:
    dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById("dialog_mode"))
    item = dropdown.selectedItem if dropdown else None
    return "edit" if item and item.name == "Edit Existing" else "create"


class ConnectionDialogInputHandler(adsk.core.InputChangedEventHandler):
    def __init__(
        self,
        records_by_label: Dict[str, Dict[str, Any]],
        library: HardwareLibrary,
    ):
        super().__init__()
        self.records_by_label = records_by_label
        self.library = library
        self.syncing = False

    def _selected_record(self, inputs) -> Optional[Dict[str, Any]]:
        dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById("connection_set"))
        item = dropdown.selectedItem if dropdown else None
        return self.records_by_label.get(item.name) if item else None

    def _set_visibility(self, inputs) -> None:
        editing = _dialog_mode(inputs) == "edit"
        inputs.itemById("connection_set").isVisible = editing
        insert_face = adsk.core.SelectionCommandInput.cast(inputs.itemById("insert_face"))
        screw_face = adsk.core.SelectionCommandInput.cast(inputs.itemById("screw_exit_face"))
        locations = adsk.core.SelectionCommandInput.cast(inputs.itemById("locations"))
        for selection in (insert_face, screw_face, locations):
            selection.isVisible = not editing
        insert_face.setSelectionLimits(0 if editing else 1, 1)
        screw_face.setSelectionLimits(0 if editing else 1, 1)
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

    def _update_summary(self, inputs) -> None:
        status = adsk.core.TextBoxCommandInput.cast(inputs.itemById("dialog_status"))
        if _dialog_mode(inputs) == "edit" and not self._selected_record(inputs):
            status.text = "No managed Connection Set is available in this design."
            return
        insert_dd = adsk.core.DropDownCommandInput.cast(inputs.itemById("insert_profile"))
        screw_dd = adsk.core.DropDownCommandInput.cast(inputs.itemById("screw_profile"))
        insert = self.library.insert(_selected_dropdown_id(insert_dd, self.library.inserts))
        screw = self.library.screw(_selected_dropdown_id(screw_dd, self.library.screws))
        head_shape = _selected_head_shape(inputs)
        action = "Existing faces and points will be reused." if _dialog_mode(inputs) == "edit" else "Select the three geometry inputs above."
        status.text = (
            "{} Insert Ø{:.3g} x {:.3g} mm plus {:.3g} mm additional clearance; screw Ø{:.3g} mm; {} clearance Ø{:.3g} mm."
        ).format(
            action,
            insert.hole_diameter_mm,
            insert.hole_depth_mm,
            _insert_clearance_depth_mm(inputs),
            screw.clearance_diameter_mm,
            "button-head" if head_shape == "button" else "cap-head",
            screw.head_clearance_diameter_mm(head_shape),
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
            self._update_summary(inputs)
        finally:
            self.syncing = False

    def notify(self, args):
        try:
            self.sync(
                args.inputs,
                load_record=args.input.id in ("dialog_mode", "connection_set"),
                filter_profiles=args.input.id == "thread_size",
            )
        except Exception:
            _log("Connection dialog update failed: {}".format(traceback.format_exc()))


def _run_dialog_operation(inputs, records_by_label, library):
    if _dialog_mode(inputs) == "create":
        return "created", _create_connection_set(inputs)
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
    )


class PreviewAppearance:
    def __init__(self, records_by_label):
        self.records_by_label = records_by_label
        self.original_opacity: Dict[int, Tuple[Any, float]] = {}

    def _bodies(self, inputs) -> List[Any]:
        bodies = []
        if _dialog_mode(inputs) == "create":
            for input_id in ("insert_face", "screw_exit_face"):
                selection = adsk.core.SelectionCommandInput.cast(
                    inputs.itemById(input_id)
                )
                if selection and selection.selectionCount:
                    face = adsk.fusion.BRepFace.cast(selection.selection(0).entity)
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
    def __init__(self, records_by_label, library, appearance):
        super().__init__()
        self.records_by_label = records_by_label
        self.library = library
        self.appearance = appearance

    def notify(self, args):
        preview = adsk.core.BoolValueCommandInput.cast(
            args.command.commandInputs.itemById("preview")
        )
        if not preview or not preview.value:
            self.appearance.restore()
            return
        try:
            self.appearance.apply(args.command.commandInputs)
            _run_dialog_operation(
                args.command.commandInputs, self.records_by_label, self.library
            )
            args.isValidResult = True
        except (ConnectionSetError, HardwareLibraryError, ValueError):
            self.appearance.restore()
            args.isValidResult = False
        except Exception:
            self.appearance.restore()
            args.isValidResult = False
            _log("Preview failed: {}".format(traceback.format_exc()))


class ConnectionDialogDestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self, appearance):
        super().__init__()
        self.appearance = appearance

    def notify(self, args):
        self.appearance.restore()


class ConnectionDialogExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, records_by_label, library):
        super().__init__()
        self.records_by_label = records_by_label
        self.library = library

    def notify(self, args):
        try:
            action, record = _run_dialog_operation(
                args.command.commandInputs, self.records_by_label, self.library
            )
            _log("Connection Set {}: {}".format(action, record_label(record)))
            UI.messageBox(
                "Connection Set {} successfully.\n\n{}\n\n"
                "Approximate starter profiles must be replaced or verified before manufacturing."
                .format(action, record_label(record)),
                "Heat Insert Connections",
            )
        except (ConnectionSetError, HardwareLibraryError, ValueError) as error:
            _log("Connection dialog validation error: {}".format(error))
            UI.messageBox(
                "Connection Set was not changed.\n\n{}".format(error),
                "Heat Insert Connections",
            )
        except Exception:
            _log("Connection dialog failed: {}".format(traceback.format_exc()))
            UI.messageBox(
                "Connection Set operation failed.\n\n{}\n\nIf new geometry remains, use Undo once."
                .format(traceback.format_exc()),
                "Heat Insert Connections",
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
                "Create or edit a paired insert connection. Screw-to-Insert Face is the face where the screw leaves its body and enters the insert body. Head Seat Distance is measured from that face back through the screw-side body.",
                4,
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

            insert_face = inputs.addSelectionInput(
                "insert_face", "Insert Entry Face", "Select the outward insert entry face."
            )
            insert_face.addSelectionFilter("PlanarFaces")
            insert_face.setSelectionLimits(1, 1)
            screw_face = inputs.addSelectionInput(
                "screw_exit_face",
                "Screw-to-Insert Face",
                "Select the face where the screw leaves this body and enters the insert body.",
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
                "insert_profile", "Insert Profile", adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for index, profile in enumerate(
                _profiles_for_thread(library.inserts, initial_thread)
            ):
                insert_dd.listItems.add(profile.display_name, index == 0)
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
            inputs.addValueInput(
                "head_seat_offset",
                "Head Seat Distance from Screw-to-Insert Face",
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

            input_handler = ConnectionDialogInputHandler(records_by_label, library)
            preview_appearance = PreviewAppearance(records_by_label)
            preview_handler = ConnectionDialogPreviewHandler(
                records_by_label, library, preview_appearance
            )
            destroy_handler = ConnectionDialogDestroyHandler(preview_appearance)
            execute_handler = ConnectionDialogExecuteHandler(records_by_label, library)
            command.inputChanged.add(input_handler)
            command.executePreview.add(preview_handler)
            command.execute.add(execute_handler)
            command.destroy.add(destroy_handler)
            HANDLERS.extend(
                (input_handler, preview_handler, execute_handler, destroy_handler)
            )
            input_handler.sync(inputs)
        except Exception:
            _log("Connection dialog setup failed: {}".format(traceback.format_exc()))
            UI.messageBox(
                "Heat Insert Connections could not open.\n\n{}".format(
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
        message = "Heat Insert Connections failed to start.\n\n{}".format(
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
