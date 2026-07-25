from datetime import UTC, datetime
from uuid import UUID

from app.connectors.live_web import LIVE_CONNECTORS as CONNECTORS
from app.domain.diff import build_snapshot, diff_snapshots
from app.domain.models import (
    BoardingPass,
    Booking,
    BookingStatus,
    CheckinPolicy,
    CheckinStatus,
    FlightEvent,
    FlightSegment,
    PaymentSummary,
)
from app.repositories.sqlite import SQLiteStore, store_sqlite
from app.schemas import BookingCreate, CheckinConsentCreate, RecheckRead
from app.security.crypto import encrypt_for_storage
from app.security.url_safety import sanitize_official_url


class BookingService:
    def __init__(self, repository: SQLiteStore) -> None:
        self.repository = repository

    async def create_booking(self, payload: BookingCreate) -> Booking:
        source_url = sanitize_official_url(payload.source_url, payload.airline) if payload.source_url else None
        connector = CONNECTORS[payload.airline]
        validation = await connector.validate_input(
            payload.pnr, payload.last_name, payload.ticket_number, source_url
        )
        if validation.get("valid") is not True:
            raise ValueError(validation.get("reason", "invalid_booking_input"))

        booking_ref = str(validation["booking_ref"])
        retrieved = await connector.retrieve_booking(booking_ref, payload.last_name)
        if retrieved.get("error") is True:
            raise ValueError(str(retrieved.get("reason", "NOT_FOUND_ON_AIRLINE")))
        segments = [FlightSegment(**segment) for segment in retrieved["segments"]]
        booking = Booking(
            telegram_id=payload.telegram_id,
            airline=payload.airline,
            encrypted_locator=encrypt_for_storage(payload.pnr),
            encrypted_last_name=encrypt_for_storage(payload.last_name),
            encrypted_ticket_number=encrypt_for_storage(payload.ticket_number),
            source_type="url" if source_url else "manual",
            segments=segments,
            passenger_names=[
                str(passenger.get("display_name"))
                for passenger in retrieved.get("passengers", [])
                if passenger.get("display_name")
            ],
            payment_summary=_payment_summary(retrieved.get("payment_summary")),
        )
        self.repository.bookings[booking.id] = booking
        for segment in booking.segments:
            snapshot = build_snapshot(segment.id, _segment_payload(segment, booking.checkin_status.value))
            self.repository.snapshots[segment.id] = snapshot
        self.repository.save()
        return booking

    def get_booking(self, booking_id: UUID, telegram_id: int) -> Booking | None:
        booking = self.repository.bookings.get(booking_id)
        if not booking or booking.telegram_id != telegram_id or booking.deleted_at is not None:
            return None
        return booking

    def list_bookings(self, telegram_id: int) -> list[Booking]:
        return [
            booking
            for booking in self.repository.bookings.values()
            if booking.telegram_id == telegram_id and booking.deleted_at is None
        ]

    async def recheck_booking(self, booking_id: UUID, telegram_id: int) -> RecheckRead | None:
        booking = self.get_booking(booking_id, telegram_id)
        if booking is None:
            return None
        status = await CONNECTORS[booking.airline].fetch_flight_status(booking.encrypted_locator or "URL_IMPORT")
        events: list[FlightEvent] = []
        for segment, new_segment in zip(booking.segments, status["segments"], strict=False):
            _update_segment(segment, new_segment)
            booking.checkin_status = CheckinStatus(status.get("checkin_status", booking.checkin_status.value))
            current = build_snapshot(segment.id, _segment_payload(segment, booking.checkin_status.value))
            previous = self.repository.snapshots.get(segment.id)
            for event in diff_snapshots(previous, current):
                if event.dedupe_key in self.repository.event_keys:
                    continue
                self.repository.event_keys.add(event.dedupe_key)
                self.repository.events.setdefault(booking.id, []).append(event)
                events.append(event)
            self.repository.snapshots[segment.id] = current
        self.repository.save()
        return RecheckRead(booking=booking, events=events)

    def grant_checkin_consent(
        self, booking_id: UUID, telegram_id: int, payload: CheckinConsentCreate
    ) -> Booking | None:
        booking = self.get_booking(booking_id, telegram_id)
        if booking is None:
            return None
        booking.checkin_policy = CheckinPolicy(
            passenger_scope=payload.passenger_scope,
            consent_version=payload.consent_version,
            seat_policy=payload.seat_policy,
            never_purchase_extras=payload.never_purchase_extras,
            require_confirmation=payload.require_confirmation,
        )
        booking.checkin_status = CheckinStatus.CHECKIN_SCHEDULED
        self.repository.save()
        return booking

    async def process_auto_checkin(self, booking_id: UUID, telegram_id: int) -> tuple[Booking, list[BoardingPass]] | None:
        booking = self.get_booking(booking_id, telegram_id)
        if booking is None or not booking.checkin_policy or not booking.checkin_policy.enabled:
            return None

        connector = CONNECTORS[booking.airline]
        policy_dict = {
            "seat_policy": booking.checkin_policy.seat_policy,
            "never_purchase_extras": booking.checkin_policy.never_purchase_extras,
            "passenger_scope": booking.checkin_policy.passenger_scope,
        }
        res = await connector.perform_checkin(
            str(booking.id)[:8].upper(),
            booking.checkin_policy.passenger_scope,
            policy_dict,
        )
        if res.get("success") is True or res.get("status") in ("SUCCESS", "BOARDING_PASS_READY"):
            booking.checkin_status = CheckinStatus.BOARDING_PASS_READY
            passes = []
            for item in res.get("boarding_passes", []):
                bp = BoardingPass(
                    booking_id=booking.id,
                    download_url=item["download_url"],
                    expires_at=item["expires_at"],
                )
                passes.append(bp)
            self.repository.boarding_passes[booking.id] = passes
            self.repository.save()
            return booking, passes
        return None

    def list_events(self, booking_id: UUID, telegram_id: int) -> list[FlightEvent] | None:
        if self.get_booking(booking_id, telegram_id) is None:
            return None
        return self.repository.events.get(booking_id, [])

    def list_boarding_passes(self, booking_id: UUID, telegram_id: int) -> list[BoardingPass] | None:
        if self.get_booking(booking_id, telegram_id) is None:
            return None
        return self.repository.boarding_passes.get(booking_id, [])

    def delete_booking(self, booking_id: UUID, telegram_id: int) -> bool:
        booking = self.get_booking(booking_id, telegram_id)
        if booking is None:
            return False
        booking.status = BookingStatus.DELETED
        booking.monitoring_enabled = False
        booking.deleted_at = datetime.now(UTC)
        for boarding_pass in self.repository.boarding_passes.get(booking_id, []):
            boarding_pass.revoked_at = booking.deleted_at
        self.repository.save()
        return True


def _segment_payload(segment: FlightSegment, checkin_status: str) -> dict[str, object]:
    return {
        "flight_number": segment.flight_number,
        "departure_airport": segment.departure_airport,
        "arrival_airport": segment.arrival_airport,
        "scheduled_departure": segment.scheduled_departure,
        "estimated_departure": segment.estimated_departure,
        "operational_status": segment.operational_status,
        "gate": segment.gate,
        "terminal": segment.terminal,
        "seat": segment.seat,
        "checkin_status": checkin_status,
    }


def _update_segment(segment: FlightSegment, payload: dict[str, object]) -> None:
    for field in _segment_payload(segment, "").keys() - {"checkin_status"}:
        if field in payload:
            setattr(segment, field, payload[field])


def _payment_summary(payload: object) -> PaymentSummary | None:
    if not isinstance(payload, dict):
        return None
    return PaymentSummary(
        amount=float(payload["amount"]),
        currency=str(payload["currency"]),
        method=None if payload.get("method") is None else str(payload["method"]),
        status=str(payload.get("status", "PAID")),
    )


booking_service = BookingService(store_sqlite)
