import json
import sqlite3
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


class SQLiteStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = Path(db_path or settings.data_file.replace(".json", ".db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.bookings: dict[UUID, Booking] = {}
        self.snapshots: dict[UUID, FlightSnapshot] = {}
        self.events: dict[UUID, list[FlightEvent]] = {}
        self.event_keys: set[str] = set()
        self.boarding_passes: dict[UUID, list[BoardingPass]] = {}
        self.user_languages: dict[int, str] = {}
        self.user_notifications: dict[int, bool] = {}
        self._init_db()
        self.load()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS bookings (
                    id TEXT PRIMARY KEY,
                    telegram_id INTEGER,
                    airline TEXT,
                    encrypted_locator TEXT,
                    encrypted_last_name TEXT,
                    encrypted_ticket_number TEXT,
                    source_type TEXT,
                    status TEXT,
                    checkin_status TEXT,
                    monitoring_enabled INTEGER,
                    segments_json TEXT,
                    passenger_names_json TEXT,
                    payment_summary_json TEXT,
                    checkin_policy_json TEXT,
                    created_at TEXT,
                    deleted_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    segment_id TEXT PRIMARY KEY,
                    snapshot_id TEXT,
                    payload_hash TEXT,
                    normalized_payload_json TEXT,
                    captured_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    booking_id TEXT,
                    segment_id TEXT,
                    event_type TEXT,
                    severity TEXT,
                    previous_value TEXT,
                    new_value TEXT,
                    dedupe_key TEXT UNIQUE,
                    created_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS boarding_passes (
                    id TEXT PRIMARY KEY,
                    booking_id TEXT,
                    download_url TEXT,
                    expires_at TEXT,
                    revoked_at TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    telegram_id INTEGER PRIMARY KEY,
                    language TEXT DEFAULT 'ES',
                    notifications_enabled INTEGER DEFAULT 1
                )
                """
            )
            conn.commit()

    def save(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for booking in self.bookings.values():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO bookings (
                        id, telegram_id, airline, encrypted_locator, encrypted_last_name,
                        encrypted_ticket_number, source_type, status, checkin_status,
                        monitoring_enabled, segments_json, passenger_names_json,
                        payment_summary_json, checkin_policy_json, created_at, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(booking.id),
                        booking.telegram_id,
                        booking.airline.value,
                        booking.encrypted_locator,
                        booking.encrypted_last_name,
                        booking.encrypted_ticket_number,
                        booking.source_type,
                        booking.status.value,
                        booking.checkin_status.value,
                        1 if booking.monitoring_enabled else 0,
                        json.dumps([_encode(seg) for seg in booking.segments]),
                        json.dumps(booking.passenger_names),
                        json.dumps(_encode(booking.payment_summary)) if booking.payment_summary else None,
                        json.dumps(_encode(booking.checkin_policy)) if booking.checkin_policy else None,
                        booking.created_at.isoformat(),
                        booking.deleted_at.isoformat() if booking.deleted_at else None,
                    ),
                )

            for snapshot in self.snapshots.values():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO snapshots (
                        segment_id, snapshot_id, payload_hash, normalized_payload_json, captured_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(snapshot.segment_id),
                        str(snapshot.id),
                        snapshot.payload_hash,
                        json.dumps(snapshot.normalized_payload),
                        snapshot.captured_at.isoformat(),
                    ),
                )

            for booking_id, events_list in self.events.items():
                for event in events_list:
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO events (
                            id, booking_id, segment_id, event_type, severity,
                            previous_value, new_value, dedupe_key, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(event.id),
                            str(booking_id),
                            str(event.segment_id),
                            event.event_type.value,
                            event.severity.value,
                            event.previous_value,
                            event.new_value,
                            event.dedupe_key,
                            event.created_at.isoformat(),
                        ),
                    )

            for booking_id, passes in self.boarding_passes.items():
                for pass_item in passes:
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO boarding_passes (
                            id, booking_id, download_url, expires_at, revoked_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            str(pass_item.id),
                            str(booking_id),
                            pass_item.download_url,
                            pass_item.expires_at.isoformat(),
                            pass_item.revoked_at.isoformat() if pass_item.revoked_at else None,
                        ),
                    )

            for telegram_id, lang in self.user_languages.items():
                notif = 1 if self.user_notifications.get(telegram_id, True) else 0
                cursor.execute(
                    "INSERT OR REPLACE INTO user_preferences (telegram_id, language, notifications_enabled) VALUES (?, ?, ?)",
                    (telegram_id, lang, notif),
                )
            conn.commit()

    def load(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bookings")
            for row in cursor.fetchall():
                segments = [_decode_segment(item) for item in json.loads(row["segments_json"])]
                pass_names = json.loads(row["passenger_names_json"]) if row["passenger_names_json"] else []
                payment = _decode_payment_summary(json.loads(row["payment_summary_json"])) if row["payment_summary_json"] else None
                policy = _decode_policy(json.loads(row["checkin_policy_json"])) if row["checkin_policy_json"] else None
                b = Booking(
                    id=UUID(row["id"]),
                    telegram_id=row["telegram_id"],
                    airline=AirlineCode(row["airline"]),
                    encrypted_locator=row["encrypted_locator"],
                    encrypted_last_name=row["encrypted_last_name"],
                    encrypted_ticket_number=row["encrypted_ticket_number"],
                    source_type=row["source_type"],
                    status=BookingStatus(row["status"]),
                    checkin_status=CheckinStatus(row["checkin_status"]),
                    monitoring_enabled=bool(row["monitoring_enabled"]),
                    segments=segments,
                    passenger_names=pass_names,
                    payment_summary=payment,
                    checkin_policy=policy,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    deleted_at=_dt(row["deleted_at"]),
                )
                self.bookings[b.id] = b

            cursor.execute("SELECT * FROM snapshots")
            for row in cursor.fetchall():
                s = FlightSnapshot(
                    id=UUID(row["snapshot_id"]),
                    segment_id=UUID(row["segment_id"]),
                    payload_hash=row["payload_hash"],
                    normalized_payload=json.loads(row["normalized_payload_json"]),
                    captured_at=datetime.fromisoformat(row["captured_at"]),
                )
                self.snapshots[s.segment_id] = s

            cursor.execute("SELECT * FROM events")
            for row in cursor.fetchall():
                e = FlightEvent(
                    id=UUID(row["id"]),
                    segment_id=UUID(row["segment_id"]),
                    event_type=EventType(row["event_type"]),
                    severity=EventSeverity(row["severity"]),
                    previous_value=row["previous_value"],
                    new_value=row["new_value"],
                    dedupe_key=row["dedupe_key"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                booking_id = UUID(row["booking_id"])
                self.events.setdefault(booking_id, []).append(e)
                self.event_keys.add(e.dedupe_key)

            cursor.execute("SELECT * FROM boarding_passes")
            for row in cursor.fetchall():
                bp = BoardingPass(
                    id=UUID(row["id"]),
                    booking_id=UUID(row["booking_id"]),
                    download_url=row["download_url"],
                    expires_at=datetime.fromisoformat(row["expires_at"]),
                    revoked_at=_dt(row["revoked_at"]),
                )
                self.boarding_passes.setdefault(bp.booking_id, []).append(bp)

            cursor.execute("SELECT * FROM user_preferences")
            for row in cursor.fetchall():
                self.user_languages[row["telegram_id"]] = row["language"]
                self.user_notifications[row["telegram_id"]] = bool(row.get("notifications_enabled", 1))


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


store_sqlite = SQLiteStore()
