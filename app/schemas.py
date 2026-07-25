from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import AirlineCode, BookingStatus, CheckinStatus, EventSeverity, EventType


class BookingCreate(BaseModel):
    telegram_id: int = Field(gt=0)
    airline: AirlineCode
    pnr: str | None = Field(default=None, min_length=5, max_length=8)
    last_name: str | None = Field(default=None, min_length=2, max_length=80)
    ticket_number: str | None = Field(default=None, min_length=10, max_length=15)
    source_url: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def require_identifier(self) -> "BookingCreate":
        has_locator = self.pnr and self.last_name
        has_ticket = self.ticket_number and self.last_name
        if not (has_locator or has_ticket or self.source_url):
            raise ValueError("provide pnr+last_name, ticket_number+last_name, or source_url")
        return self


class SegmentRead(BaseModel):
    id: UUID
    flight_number: str
    departure_airport: str
    arrival_airport: str
    scheduled_departure: datetime
    estimated_departure: datetime | None = None
    operational_status: str
    gate: str | None = None
    terminal: str | None = None
    seat: str | None = None
    boarding_group: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CheckinPolicyRead(BaseModel):
    enabled: bool
    consent_version: str
    passenger_scope: list[str]
    seat_policy: str
    never_purchase_extras: bool
    require_confirmation: bool
    consented_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentSummaryRead(BaseModel):
    amount: float
    currency: str
    method: str | None = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class BookingRead(BaseModel):
    id: UUID
    telegram_id: int
    airline: AirlineCode
    status: BookingStatus
    checkin_status: CheckinStatus
    monitoring_enabled: bool
    passenger_names: list[str]
    payment_summary: PaymentSummaryRead | None = None
    segments: list[SegmentRead]
    checkin_policy: CheckinPolicyRead | None = None
    created_at: datetime
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CheckinConsentCreate(BaseModel):
    passenger_scope: list[str] = Field(min_length=1)
    consent_version: str = Field(default="2026-07-24", min_length=1, max_length=32)
    seat_policy: str = "free_only"
    require_confirmation: bool = True
    never_purchase_extras: bool = True

    @model_validator(mode="after")
    def enforce_safe_policy(self) -> "CheckinConsentCreate":
        if self.seat_policy != "free_only" or not self.never_purchase_extras:
            raise ValueError("check-in consent only supports free seats and no extras")
        return self


class FlightEventRead(BaseModel):
    id: UUID
    segment_id: UUID
    event_type: EventType
    severity: EventSeverity
    previous_value: str | None
    new_value: str | None
    dedupe_key: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecheckRead(BaseModel):
    booking: BookingRead
    events: list[FlightEventRead]
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BoardingPassRead(BaseModel):
    id: UUID
    booking_id: UUID
    download_url: str
    expires_at: datetime
    revoked_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SegmentRecheckRead(BaseModel):
    booking: BookingRead
    segment_index: int
    events: list[FlightEventRead]
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SegmentDeleteRead(BaseModel):
    booking_id: UUID
    deleted_segment: SegmentRead
    booking_deleted: bool
