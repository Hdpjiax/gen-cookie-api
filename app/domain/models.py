from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4


class AirlineCode(StrEnum):
    VIVA = "VIVA"
    VOLARIS = "VOLARIS"
    AEROMEXICO = "AEROMEXICO"
    UNITED = "UNITED"


class BookingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    DELETED = "DELETED"


class CheckinStatus(StrEnum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    CHECKIN_SCHEDULED = "CHECKIN_SCHEDULED"
    CHECKIN_WINDOW_OPEN = "CHECKIN_WINDOW_OPEN"
    CHECKIN_RUNNING = "CHECKIN_RUNNING"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    CHECKED_IN = "CHECKED_IN"
    BOARDING_PASS_READY = "BOARDING_PASS_READY"
    CHECKIN_FAILED = "CHECKIN_FAILED"
    CHECKIN_EXPIRED = "CHECKIN_EXPIRED"


class EventType(StrEnum):
    DELAY = "DELAY"
    EARLY = "EARLY"
    CANCELLATION = "CANCELLATION"
    GATE = "GATE"
    TERMINAL = "TERMINAL"
    SEAT = "SEAT"
    ITINERARY = "ITINERARY"
    CHECKIN = "CHECKIN"


class EventSeverity(StrEnum):
    INFO = "INFO"
    ATTENTION = "ATTENTION"
    CRITICAL = "CRITICAL"


@dataclass(slots=True)
class FlightSegment:
    flight_number: str
    departure_airport: str
    arrival_airport: str
    scheduled_departure: datetime
    estimated_departure: datetime | None = None
    operational_status: str = "SCHEDULED"
    gate: str | None = None
    terminal: str | None = None
    seat: str | None = None
    boarding_group: str | None = None
    id: UUID = field(default_factory=uuid4)


@dataclass(slots=True)
class CheckinPolicy:
    passenger_scope: list[str]
    consent_version: str
    seat_policy: str = "free_only"
    never_purchase_extras: bool = True
    require_confirmation: bool = True
    enabled: bool = True
    consented_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class PaymentSummary:
    amount: float
    currency: str
    method: str | None = None
    status: str = "PAID"


@dataclass(slots=True)
class Booking:
    telegram_id: int
    airline: AirlineCode
    encrypted_locator: str | None
    encrypted_last_name: str | None
    encrypted_ticket_number: str | None
    source_type: str
    segments: list[FlightSegment]
    passenger_names: list[str] = field(default_factory=list)
    payment_summary: PaymentSummary | None = None
    id: UUID = field(default_factory=uuid4)
    status: BookingStatus = BookingStatus.ACTIVE
    checkin_status: CheckinStatus = CheckinStatus.NOT_ELIGIBLE
    monitoring_enabled: bool = True
    checkin_policy: CheckinPolicy | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None


@dataclass(slots=True)
class FlightSnapshot:
    segment_id: UUID
    payload_hash: str
    normalized_payload: dict[str, object]
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID = field(default_factory=uuid4)


@dataclass(slots=True)
class FlightEvent:
    segment_id: UUID
    event_type: EventType
    previous_value: str | None
    new_value: str | None
    dedupe_key: str
    severity: EventSeverity
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class BoardingPass:
    booking_id: UUID
    download_url: str
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=15))
    revoked_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
