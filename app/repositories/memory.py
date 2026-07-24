import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.config import settings
from app.domain.models import (
    AirlineCode,
    BoardingPass,
    Booking,
    BookingStatus,
    CheckinPolicy,
    CheckinStatus,
    EventSeverity,
    EventType,
    FlightEvent,
    FlightSegment,
    FlightSnapshot,
    PaymentSummary,
)


class InMemoryStore:
    def __init__(self) -> None:
        self.bookings: dict[UUID, Booking] = {}
        self.snapshots: dict[UUID, FlightSnapshot] = {}
        self.events: dict[UUID, list[FlightEvent]] = {}
        self.event_keys: set[str] = set()
        self.boarding_passes: dict[UUID, list[BoardingPass]] = {}
        self.load()

    def save(self) -> None:
        path = Path(settings.data_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "bookings": [_encode(booking) for booking in self.bookings.values()],
            "snapshots": [_encode(snapshot) for snapshot in self.snapshots.values()],
            "events": [
                {"booking_id": str(booking_id), "events": [_encode(event) for event in events]}
                for booking_id, events in self.events.items()
            ],
            "event_keys": sorted(self.event_keys),
            "boarding_passes": [
                {"booking_id": str(booking_id), "passes": [_encode(item) for item in items]}
                for booking_id, items in self.boarding_passes.items()
            ],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> None:
        path = Path(settings.data_file)
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.bookings = {
            booking.id: booking for booking in (_decode_booking(item) for item in payload.get("bookings", []))
        }
        self.snapshots = {
            snapshot.segment_id: snapshot
            for snapshot in (_decode_snapshot(item) for item in payload.get("snapshots", []))
        }
        self.events = {
            UUID(item["booking_id"]): [_decode_event(event) for event in item["events"]]
            for item in payload.get("events", [])
        }
        self.event_keys = set(payload.get("event_keys", []))
        self.boarding_passes = {
            UUID(item["booking_id"]): [_decode_boarding_pass(pass_item) for pass_item in item["passes"]]
            for item in payload.get("boarding_passes", [])
        }


def _encode(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _encode(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value


def _dt(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _decode_segment(item: dict[str, Any]) -> FlightSegment:
    return FlightSegment(
        id=UUID(item["id"]),
        flight_number=item["flight_number"],
        departure_airport=item["departure_airport"],
        arrival_airport=item["arrival_airport"],
        scheduled_departure=_dt(item["scheduled_departure"]),
        estimated_departure=_dt(item["estimated_departure"]),
        operational_status=item["operational_status"],
        gate=item["gate"],
        terminal=item["terminal"],
        seat=item["seat"],
        boarding_group=item["boarding_group"],
    )


def _decode_policy(item: dict[str, Any] | None) -> CheckinPolicy | None:
    if item is None:
        return None
    return CheckinPolicy(
        enabled=item["enabled"],
        consent_version=item["consent_version"],
        passenger_scope=item["passenger_scope"],
        seat_policy=item["seat_policy"],
        never_purchase_extras=item["never_purchase_extras"],
        require_confirmation=item["require_confirmation"],
        consented_at=_dt(item["consented_at"]),
    )


def _decode_payment_summary(item: dict[str, Any] | None) -> PaymentSummary | None:
    if item is None:
        return None
    return PaymentSummary(
        amount=float(item["amount"]),
        currency=item["currency"],
        method=item["method"],
        status=item["status"],
    )


def _decode_booking(item: dict[str, Any]) -> Booking:
    return Booking(
        id=UUID(item["id"]),
        telegram_id=item["telegram_id"],
        airline=AirlineCode(item["airline"]),
        encrypted_locator=item["encrypted_locator"],
        encrypted_last_name=item["encrypted_last_name"],
        encrypted_ticket_number=item["encrypted_ticket_number"],
        source_type=item["source_type"],
        status=BookingStatus(item["status"]),
        checkin_status=CheckinStatus(item["checkin_status"]),
        monitoring_enabled=item["monitoring_enabled"],
        segments=[_decode_segment(segment) for segment in item["segments"]],
        passenger_names=item.get("passenger_names", []),
        payment_summary=_decode_payment_summary(item.get("payment_summary")),
        checkin_policy=_decode_policy(item["checkin_policy"]),
        created_at=_dt(item["created_at"]),
        deleted_at=_dt(item["deleted_at"]),
    )


def _decode_snapshot(item: dict[str, Any]) -> FlightSnapshot:
    return FlightSnapshot(
        id=UUID(item["id"]),
        segment_id=UUID(item["segment_id"]),
        payload_hash=item["payload_hash"],
        normalized_payload=item["normalized_payload"],
        captured_at=_dt(item["captured_at"]),
    )


def _decode_event(item: dict[str, Any]) -> FlightEvent:
    return FlightEvent(
        id=UUID(item["id"]),
        segment_id=UUID(item["segment_id"]),
        event_type=EventType(item["event_type"]),
        severity=EventSeverity(item["severity"]),
        previous_value=item["previous_value"],
        new_value=item["new_value"],
        dedupe_key=item["dedupe_key"],
        created_at=_dt(item["created_at"]),
    )


def _decode_boarding_pass(item: dict[str, Any]) -> BoardingPass:
    return BoardingPass(
        id=UUID(item["id"]),
        booking_id=UUID(item["booking_id"]),
        download_url=item["download_url"],
        expires_at=_dt(item["expires_at"]),
        revoked_at=_dt(item["revoked_at"]),
    )


store = InMemoryStore()
