import hashlib
import json
from datetime import datetime
from uuid import UUID

from app.domain.models import EventSeverity, EventType, FlightEvent, FlightSnapshot

WATCHED_FIELDS: dict[str, EventType] = {
    "operational_status": EventType.CANCELLATION,
    "estimated_departure": EventType.DELAY,
    "gate": EventType.GATE,
    "terminal": EventType.TERMINAL,
    "seat": EventType.SEAT,
    "checkin_status": EventType.CHECKIN,
}


def normalize_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in sorted(payload.items()):
        if isinstance(value, datetime):
            normalized[key] = value.astimezone().isoformat()
        elif isinstance(value, str):
            normalized[key] = value.strip().upper()
        else:
            normalized[key] = value
    return normalized


def payload_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(normalize_payload(payload), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_snapshot(segment_id: UUID, payload: dict[str, object]) -> FlightSnapshot:
    normalized = normalize_payload(payload)
    return FlightSnapshot(segment_id=segment_id, payload_hash=payload_hash(normalized), normalized_payload=normalized)


def diff_snapshots(previous: FlightSnapshot | None, current: FlightSnapshot) -> list[FlightEvent]:
    if previous is None or previous.payload_hash == current.payload_hash:
        return []

    events: list[FlightEvent] = []
    for field, event_type in WATCHED_FIELDS.items():
        old = previous.normalized_payload.get(field)
        new = current.normalized_payload.get(field)
        if old == new:
            continue
        severity = classify_severity(event_type, new)
        new_value = None if new is None else str(new)
        events.append(
            FlightEvent(
                segment_id=current.segment_id,
                event_type=event_type,
                previous_value=None if old is None else str(old),
                new_value=new_value,
                severity=severity,
                dedupe_key=make_dedupe_key(current.segment_id, event_type, new_value),
            )
        )
    return events


def make_dedupe_key(segment_id: UUID, event_type: EventType, new_value: str | None) -> str:
    raw = f"{segment_id}:{event_type}:{new_value or ''}".encode()
    return hashlib.blake2b(raw, digest_size=16).hexdigest()


def classify_severity(event_type: EventType, new_value: object) -> EventSeverity:
    if event_type is EventType.CANCELLATION or new_value == "CANCELLED":
        return EventSeverity.CRITICAL
    if event_type in {EventType.DELAY, EventType.ITINERARY, EventType.CHECKIN}:
        return EventSeverity.ATTENTION
    return EventSeverity.INFO
