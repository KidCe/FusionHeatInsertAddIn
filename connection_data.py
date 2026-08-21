"""Fusion-independent Connection Set metadata and parameter planning."""

from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict

from hardware_library import InsertProfile, ScrewProfile


SCHEMA_VERSION = 1


def new_connection_id() -> str:
    return uuid.uuid4().hex[:8]


def parameter_prefix(connection_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", connection_id)
    if not safe or safe[0].isdigit():
        safe = f"C_{safe}"
    return f"HIC_{safe}"


def parameter_specs(
    connection_id: str,
    insert: InsertProfile,
    screw: ScrewProfile,
    head_seat_offset_mm: float,
    head_shape: str = "cap",
    insert_clearance_depth_mm: float = 0.0,
) -> Dict[str, Dict[str, str]]:
    if insert.thread_size != screw.thread_size:
        raise ValueError("Insert and screw thread sizes must match in the MVP.")
    if head_seat_offset_mm <= 0:
        raise ValueError(
            "Head seat distance from the Screw Entry Face must be greater than zero."
        )
    if insert_clearance_depth_mm < 0:
        raise ValueError("Additional insert clearance depth cannot be negative.")
    prefix = parameter_prefix(connection_id)
    return {
        "insertHoleDiameter": _length(prefix, "InsertHoleDiameter", insert.hole_diameter_mm),
        "insertHoleDepth": _length(
            prefix,
            "InsertHoleDepth",
            insert.hole_depth_mm + insert_clearance_depth_mm,
        ),
        "insertLeadInDiameter": _length(
            prefix, "InsertLeadInDiameter", insert.lead_in_diameter_mm
        ),
        "insertLeadInAngle": _angle(prefix, "InsertLeadInAngle", insert.lead_in_angle_deg),
        "insertTipAngle": _angle(prefix, "InsertTipAngle", insert.tip_angle_deg),
        "screwClearanceDiameter": _length(
            prefix, "ScrewClearanceDiameter", screw.clearance_diameter_mm
        ),
        "headClearanceDiameter": _length(
            prefix, "HeadClearanceDiameter", screw.head_clearance_diameter_mm(head_shape)
        ),
        "headSeatOffset": _length(prefix, "HeadSeatOffset", head_seat_offset_mm),
    }


def make_record(
    *,
    connection_id: str,
    addin_version: str,
    insert: InsertProfile,
    screw: ScrewProfile,
    head_seat_offset_mm: float,
    head_shape: str,
    insert_clearance_depth_mm: float,
    location_count: int,
    parameter_names: Dict[str, str],
    feature_tokens: Dict[str, str],
    helper_tokens: Dict[str, str],
    insert_face_token: str,
    screw_exit_face_token: str,
    source_point_tokens: list[str],
    timeline_group_name: str,
) -> Dict[str, Any]:
    if location_count < 1:
        raise ValueError("A Connection Set must contain at least one location.")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": connection_id,
        "createdWithVersion": addin_version,
        "updatedWithVersion": addin_version,
        "createdAt": now,
        "updatedAt": now,
        "threadSize": insert.thread_size,
        "insertPresetId": insert.id,
        "screwPresetId": screw.id,
        "headShape": head_shape,
        "insertClearanceDepthMm": float(insert_clearance_depth_mm),
        "headSeatOffsetMm": float(head_seat_offset_mm),
        "locationCount": int(location_count),
        "parameterNames": dict(parameter_names),
        "featureTokens": dict(feature_tokens),
        "helperTokens": dict(helper_tokens),
        "insertFaceToken": insert_face_token,
        "screwExitFaceToken": screw_exit_face_token,
        "sourcePointTokens": list(source_point_tokens),
        "timelineGroupName": timeline_group_name,
    }


def update_record(
    record: Dict[str, Any],
    *,
    addin_version: str,
    insert: InsertProfile,
    screw: ScrewProfile,
    head_seat_offset_mm: float,
    head_shape: str,
    insert_clearance_depth_mm: float,
    timeline_group_name: str,
) -> Dict[str, Any]:
    result = deepcopy(record)
    result["updatedWithVersion"] = addin_version
    result["updatedAt"] = datetime.now(timezone.utc).isoformat()
    result["threadSize"] = insert.thread_size
    result["insertPresetId"] = insert.id
    result["screwPresetId"] = screw.id
    result["headShape"] = head_shape
    result["insertClearanceDepthMm"] = float(insert_clearance_depth_mm)
    result["headSeatOffsetMm"] = float(head_seat_offset_mm)
    result["timelineGroupName"] = timeline_group_name
    return result


def encode_record(record: Dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def decode_record(value: str) -> Dict[str, Any]:
    record = json.loads(value)
    if not isinstance(record, dict) or record.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("Unsupported Connection Set record.")
    required = (
        "id",
        "insertPresetId",
        "screwPresetId",
        "parameterNames",
        "featureTokens",
        "locationCount",
    )
    missing = [name for name in required if name not in record]
    if missing:
        raise ValueError(f"Connection Set record is missing: {', '.join(missing)}")
    return record


def record_label(record: Dict[str, Any]) -> str:
    return "HIC {} — {} — {} location{}".format(
        record["id"],
        record.get("threadSize", "Unknown"),
        record.get("locationCount", 0),
        "" if record.get("locationCount") == 1 else "s",
    )


def _length(prefix: str, suffix: str, value: float) -> Dict[str, str]:
    return {"name": f"{prefix}_{suffix}", "expression": f"{value:.8g} mm", "units": "mm"}


def _angle(prefix: str, suffix: str, value: float) -> Dict[str, str]:
    return {"name": f"{prefix}_{suffix}", "expression": f"{value:.8g} deg", "units": "deg"}
