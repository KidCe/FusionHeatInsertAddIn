"""Load and validate the editable heat-insert and screw geometry library."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List


class HardwareLibraryError(ValueError):
    """Raised when the hardware library is missing or invalid."""


@dataclass(frozen=True)
class InsertProfile:
    id: str
    display_name: str
    thread_size: str
    recipe: str
    hole_diameter_mm: float
    hole_depth_mm: float
    lead_in_diameter_mm: float
    lead_in_angle_deg: float
    tip_angle_deg: float
    notes: str = ""


@dataclass(frozen=True)
class ScrewProfile:
    id: str
    display_name: str
    thread_size: str
    recipe: str
    clearance_diameter_mm: float
    button_head_clearance_diameter_mm: float
    cap_head_clearance_diameter_mm: float
    notes: str = ""

    def head_clearance_diameter_mm(self, head_shape: str) -> float:
        if head_shape == "button":
            return self.button_head_clearance_diameter_mm
        if head_shape == "cap":
            return self.cap_head_clearance_diameter_mm
        raise HardwareLibraryError(f"Unsupported head shape: {head_shape}")


class HardwareLibrary:
    """Validated, read-only view of ``hardware_library.json``."""

    def __init__(
        self,
        schema_version: int,
        inserts: Iterable[InsertProfile],
        screws: Iterable[ScrewProfile],
    ) -> None:
        self.schema_version = schema_version
        self.inserts = tuple(inserts)
        self.screws = tuple(screws)
        self._inserts_by_id = _index_unique(self.inserts, "insert")
        self._screws_by_id = _index_unique(self.screws, "screw")
        if not self.inserts:
            raise HardwareLibraryError("The library must contain at least one insert profile.")
        if not self.screws:
            raise HardwareLibraryError("The library must contain at least one screw profile.")

    @classmethod
    def from_path(cls, path: str | Path) -> "HardwareLibrary":
        library_path = Path(path)
        try:
            payload = json.loads(library_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise HardwareLibraryError(f"Hardware library not found: {library_path}") from error
        except (OSError, json.JSONDecodeError) as error:
            raise HardwareLibraryError(f"Cannot read hardware library: {error}") from error

        if not isinstance(payload, dict):
            raise HardwareLibraryError("The hardware library root must be a JSON object.")
        if payload.get("schemaVersion") != 1:
            raise HardwareLibraryError("Unsupported hardware library schemaVersion; expected 1.")

        inserts_raw = _require_list(payload, "insertProfiles")
        screws_raw = _require_list(payload, "screwProfiles")
        inserts = [_parse_insert(item, index) for index, item in enumerate(inserts_raw)]
        screws = [_parse_screw(item, index) for index, item in enumerate(screws_raw)]
        return cls(1, inserts, screws)

    def insert(self, profile_id: str) -> InsertProfile:
        try:
            return self._inserts_by_id[profile_id]
        except KeyError as error:
            raise HardwareLibraryError(f"Unknown insert profile: {profile_id}") from error

    def screw(self, profile_id: str) -> ScrewProfile:
        try:
            return self._screws_by_id[profile_id]
        except KeyError as error:
            raise HardwareLibraryError(f"Unknown screw profile: {profile_id}") from error


def _index_unique(items: Iterable[Any], kind: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    display_names = set()
    for item in items:
        if item.id in result:
            raise HardwareLibraryError(f"Duplicate {kind} profile id: {item.id}")
        if item.display_name in display_names:
            raise HardwareLibraryError(f"Duplicate {kind} displayName: {item.display_name}")
        result[item.id] = item
        display_names.add(item.display_name)
    return result


def _require_list(payload: Dict[str, Any], name: str) -> List[Dict[str, Any]]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise HardwareLibraryError(f"{name} must be a JSON array.")
    if not all(isinstance(item, dict) for item in value):
        raise HardwareLibraryError(f"Every entry in {name} must be a JSON object.")
    return value


def _text(item: Dict[str, Any], name: str, context: str) -> str:
    value = item.get(name)
    if not isinstance(value, str) or not value.strip():
        raise HardwareLibraryError(f"{context}.{name} must be a non-empty string.")
    return value.strip()


def _positive_number(item: Dict[str, Any], name: str, context: str) -> float:
    value = item.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise HardwareLibraryError(f"{context}.{name} must be a positive number.")
    return float(value)


def _optional_text(item: Dict[str, Any], name: str, context: str) -> str:
    value = item.get(name, "")
    if not isinstance(value, str):
        raise HardwareLibraryError(f"{context}.{name} must be a string.")
    return value.strip()


def _parse_insert(item: Dict[str, Any], index: int) -> InsertProfile:
    context = f"insertProfiles[{index}]"
    profile = InsertProfile(
        id=_text(item, "id", context),
        display_name=_text(item, "displayName", context),
        thread_size=_text(item, "threadSize", context),
        recipe=_text(item, "recipe", context),
        hole_diameter_mm=_positive_number(item, "holeDiameterMm", context),
        hole_depth_mm=_positive_number(item, "holeDepthMm", context),
        lead_in_diameter_mm=_positive_number(item, "leadInDiameterMm", context),
        lead_in_angle_deg=_positive_number(item, "leadInAngleDeg", context),
        tip_angle_deg=_positive_number(item, "tipAngleDeg", context),
        notes=_optional_text(item, "notes", context),
    )
    if profile.recipe != "countersink_hole_v1":
        raise HardwareLibraryError(f"{context}.recipe is not supported by this MVP.")
    if profile.lead_in_diameter_mm <= profile.hole_diameter_mm:
        raise HardwareLibraryError(
            f"{context}.leadInDiameterMm must be larger than holeDiameterMm."
        )
    if not 0 < profile.lead_in_angle_deg < 180:
        raise HardwareLibraryError(f"{context}.leadInAngleDeg must be below 180 degrees.")
    if not 0 < profile.tip_angle_deg <= 180:
        raise HardwareLibraryError(f"{context}.tipAngleDeg must be at most 180 degrees.")
    return profile


def _parse_screw(item: Dict[str, Any], index: int) -> ScrewProfile:
    context = f"screwProfiles[{index}]"
    profile = ScrewProfile(
        id=_text(item, "id", context),
        display_name=_text(item, "displayName", context),
        thread_size=_text(item, "threadSize", context),
        recipe=_text(item, "recipe", context),
        clearance_diameter_mm=_positive_number(item, "clearanceDiameterMm", context),
        button_head_clearance_diameter_mm=_positive_number(
            item, "buttonHeadClearanceDiameterMm", context
        ),
        cap_head_clearance_diameter_mm=_positive_number(
            item, "capHeadClearanceDiameterMm", context
        ),
        notes=_optional_text(item, "notes", context),
    )
    if profile.recipe != "offset_head_seat_v1":
        raise HardwareLibraryError(f"{context}.recipe is not supported by this MVP.")
    for field_name, diameter in (
        ("buttonHeadClearanceDiameterMm", profile.button_head_clearance_diameter_mm),
        ("capHeadClearanceDiameterMm", profile.cap_head_clearance_diameter_mm),
    ):
        if diameter <= profile.clearance_diameter_mm:
            raise HardwareLibraryError(
                f"{context}.{field_name} must be larger than clearanceDiameterMm."
            )
    return profile
