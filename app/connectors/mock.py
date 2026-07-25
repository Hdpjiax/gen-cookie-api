import hashlib
import logging
from datetime import UTC, datetime, timedelta

from app.domain.models import AirlineCode

logger = logging.getLogger(__name__)

AIRPORT_PAIRS = [
    ("MEX", "CUN"), ("TIJ", "MEX"), ("MEX", "GDL"), ("MTY", "CUN"),
    ("CJS", "MEX"), ("MEX", "ORD"), ("MEX", "LAX"), ("GDL", "TIJ"),
    ("SFO", "MEX"), ("CUN", "MTY"), ("MEX", "IAH"), ("MTY", "MEX"),
]

FIRST_NAMES = [
    "Jonathon", "Mariana", "Carlos", "Karina", "Alejandro",
    "Sofia", "Mateo", "Valentina", "Diego", "Isabella",
]


class MockAirlineConnector:
    def __init__(self, airline_code: AirlineCode) -> None:
        self.airline_code = airline_code.value
        self._recheck_count = 0

    async def validate_input(
        self,
        pnr: str | None,
        last_name: str | None,
        ticket_number: str | None,
        source_url: str | None,
    ) -> dict[str, object]:
        if not ((pnr and last_name) or (ticket_number and last_name) or source_url):
            return {"valid": False, "reason": "missing_identifier"}
        return {"valid": True, "booking_ref": (pnr or ticket_number or "URL_IMPORT").upper()}

    async def retrieve_booking(self, booking_ref: str, last_name: str | None = None) -> dict[str, object]:
        ref = booking_ref.upper()
        clean_last = last_name.strip().capitalize() if last_name else "Garcia"

        booking_data = _build_dynamic_booking(self.airline_code, ref, clean_last)
        if booking_data is None:
            logger.warning(f"Booking {ref} with last name {clean_last} not found in {self.airline_code} mock data")
            return {
                "error": True,
                "reason": "NOT_FOUND_ON_AIRLINE",
                "message": f"No se encontró la reserva {ref} ({clean_last}) en {self.airline_code}. Verifique el código y apellido.",
            }
        return booking_data

    async def fetch_flight_status(self, booking_ref: str, last_name: str | None = None) -> dict[str, object]:
        self._recheck_count += 1
        booking = await self.retrieve_booking(booking_ref, last_name)
        segments = booking.get("segments", [])
        if segments and self._recheck_count % 2 == 1:
            segments[0]["gate"] = "Gate 15"
        return {"segments": segments, "recheck_count": self._recheck_count, "checkin_status": "NOT_ELIGIBLE"}

    async def get_checkin_eligibility(self, booking_ref: str) -> dict[str, object]:
        return {
            "status": "CHECKIN_WINDOW_OPEN",
            "window_opens_at": datetime.now(UTC) - timedelta(hours=2),
            "window_closes_at": datetime.now(UTC) + timedelta(hours=24),
            "eligible_passengers": ["P1", "P2"],
        }

    async def perform_checkin(
        self, booking_ref: str, passenger_ids: list[str], policy: dict[str, object]
    ) -> dict[str, object]:
        skip_seat = policy.get("seat_policy") in ("skip_seat_selection", "free_only")
        no_extras = policy.get("never_purchase_extras") is True

        if not (skip_seat and no_extras):
            return {
                "success": False,
                "status": "ACTION_REQUIRED",
                "reason": "policy_violation_requires_free_seats_and_no_extras",
            }

        return {
            "success": True,
            "status": "BOARDING_PASS_READY",
            "assigned_seats": {pid: "Asignado por aerolínea (selección saltada)" for pid in passenger_ids},
            "boarding_passes": [
                {
                    "passenger_id": pid,
                    "download_url": f"https://official.airline.com/passes/{booking_ref[:8]}_boarding_pass.pdf",
                    "expires_at": datetime.now(UTC) + timedelta(days=2),
                }
                for pid in passenger_ids
            ],
        }

    async def retrieve_boarding_passes(self, booking_ref: str) -> list[dict[str, object]]:
        return [
            {
                "passenger_id": "P1",
                "download_url": f"https://official.airline.com/passes/{booking_ref[:8]}_boarding_pass.pdf",
                "expires_at": datetime.now(UTC) + timedelta(days=2),
            }
        ]


def _build_dynamic_booking(airline_code: str, ref: str, clean_last: str) -> dict[str, object] | None:
    """
    Build booking data. Returns real data ONLY for known test bookings.
    For unknown bookings, returns None so the system uses live connectors.
    """
    hash_digest = hashlib.md5(f"{ref}:{clean_last}:{airline_code}".encode()).hexdigest()
    seed = int(hash_digest[:8], 16)

    # Known test bookings with REAL data from tests
    known_bookings = {
        ("VOLARIS", "LCYD6C"): {
            "passengers": [
                {"id": "P1", "display_name": "Max Nino Ortega"},
                {"id": "P2", "display_name": f"Karina {clean_last}"},
            ],
            "payment_summary": {"amount": 14287.00, "currency": "MXN", "method": "Tarjeta", "status": "PAID"},
            "segments": [
                {
                    "flight_number": "Y4 700",
                    "departure_airport": "MEX",
                    "arrival_airport": "ORD",
                    "scheduled_departure": datetime(2026, 7, 30, 6, 50, tzinfo=UTC),
                    "estimated_departure": datetime(2026, 7, 30, 6, 50, tzinfo=UTC),
                    "operational_status": "SCHEDULED",
                    "gate": "A12",
                    "terminal": "T1",
                    "seat": "Sin asignar",
                    "boarding_group": "Grupo B",
                }
            ],
        },
        ("VOLARIS", "XY895L"): {
            "passengers": [
                {"id": "P1", "display_name": f"Jonathon {clean_last}" if clean_last != "Garcia" else "Jonathon Martinez"},
                {"id": "P2", "display_name": "Brenda Montoya"},
            ],
            "payment_summary": {"amount": 3850.00, "currency": "MXN", "method": "Tarjeta", "status": "PAID"},
            "segments": [
                {
                    "flight_number": "Y4 895",
                    "departure_airport": "TIJ",
                    "arrival_airport": "MEX",
                    "scheduled_departure": datetime(2026, 7, 31, 9, 30, tzinfo=UTC),
                    "estimated_departure": datetime(2026, 7, 31, 9, 30, tzinfo=UTC),
                    "operational_status": "SCHEDULED",
                    "gate": "A14",
                    "terminal": "T1",
                    "seat": "Sin asignar",
                    "boarding_group": "Grupo B",
                }
            ],
        },
        ("VOLARIS", "IFS2JW"): {
            "passengers": [
                {"id": "P1", "display_name": f"Antonio {clean_last}"},
            ],
            "payment_summary": {"amount": 4250.00, "currency": "MXN", "method": "Tarjeta", "status": "PAID"},
            "segments": [
                {
                    "flight_number": "Y4 1234",
                    "departure_airport": "MEX",
                    "arrival_airport": "CUN",
                    "scheduled_departure": datetime(2026, 8, 15, 10, 30, tzinfo=UTC),
                    "estimated_departure": datetime(2026, 8, 15, 10, 30, tzinfo=UTC),
                    "operational_status": "SCHEDULED",
                    "gate": "A8",
                    "terminal": "T1",
                    "seat": "Sin asignar",
                    "boarding_group": "Grupo A",
                }
            ],
        },
        ("AEROMEXICO", "HUIITL"): {
            "passengers": [{"id": "P1", "display_name": f"Mariana {clean_last}"}],
            "payment_summary": {"amount": 5420.00, "currency": "MXN", "method": "Tarjeta (Visa)", "status": "PAID"},
            "segments": [
                {
                    "flight_number": "AM 116",
                    "departure_airport": "CJS",
                    "arrival_airport": "MEX",
                    "scheduled_departure": datetime.now(UTC) + timedelta(hours=12),
                    "estimated_departure": datetime.now(UTC) + timedelta(hours=12),
                    "operational_status": "SCHEDULED",
                    "gate": "24",
                    "terminal": "T2",
                    "seat": "Aleatorio (Sin selección previa)",
                    "boarding_group": "Grupo 2",
                },
                {
                    "flight_number": "AM 115",
                    "departure_airport": "MEX",
                    "arrival_airport": "CJS",
                    "scheduled_departure": datetime.now(UTC) + timedelta(days=4),
                    "estimated_departure": datetime.now(UTC) + timedelta(days=4),
                    "operational_status": "SCHEDULED",
                    "gate": "62",
                    "terminal": "T2",
                    "seat": "Aleatorio (Sin selección previa)",
                    "boarding_group": "Grupo 2",
                },
            ],
        },
        ("AEROMEXICO", "AM452"): {
            "passengers": [{"id": "P1", "display_name": f"Mariana {clean_last}"}],
            "payment_summary": {"amount": 5420.00, "currency": "MXN", "method": "Tarjeta (Visa)", "status": "PAID"},
            "segments": [
                {
                    "flight_number": "AM 452",
                    "departure_airport": "MEX",
                    "arrival_airport": "GDL",
                    "scheduled_departure": datetime.now(UTC) + timedelta(hours=12),
                    "estimated_departure": datetime.now(UTC) + timedelta(hours=12),
                    "operational_status": "SCHEDULED",
                    "gate": "24",
                    "terminal": "T2",
                    "seat": "Aleatorio (Sin selección previa)",
                    "boarding_group": "Grupo 2",
                }
            ],
        },
        ("VIVA", "VIV123"): {
            "passengers": [{"id": "P1", "display_name": f"Carlos {clean_last}"}],
            "payment_summary": {"amount": 2450.00, "currency": "MXN", "method": "Tarjeta (Mastercard)", "status": "PAID"},
            "segments": [
                {
                    "flight_number": "VB 1124",
                    "departure_airport": "MTY",
                    "arrival_airport": "CUN",
                    "scheduled_departure": datetime(2026, 8, 5, 14, 20, tzinfo=UTC),
                    "estimated_departure": datetime(2026, 8, 5, 14, 20, tzinfo=UTC),
                    "operational_status": "SCHEDULED",
                    "gate": "A4",
                    "terminal": "T1",
                    "seat": "Aleatorio (Sin selección previa)",
                    "boarding_group": "Grupo C",
                },
                {
                    "flight_number": "VB 1125",
                    "departure_airport": "CUN",
                    "arrival_airport": "MTY",
                    "scheduled_departure": datetime(2026, 8, 12, 17, 45, tzinfo=UTC),
                    "estimated_departure": datetime(2026, 8, 12, 17, 45, tzinfo=UTC),
                    "operational_status": "SCHEDULED",
                    "gate": "B8",
                    "terminal": "T2",
                    "seat": "Aleatorio (Sin selección previa)",
                    "boarding_group": "Grupo C",
                },
            ],
        },
    }

    key = (airline_code, ref)
    if key in known_bookings:
        return known_bookings[key]

    # Return None for unknown bookings - this forces the system to use live connectors
    # which will try to fetch REAL data from airline systems
    return None


CONNECTORS: dict[str, MockAirlineConnector] = {
    AirlineCode.VOLARIS.value: MockAirlineConnector(AirlineCode.VOLARIS),
    AirlineCode.VIVA.value: MockAirlineConnector(AirlineCode.VIVA),
    AirlineCode.AEROMEXICO.value: MockAirlineConnector(AirlineCode.AEROMEXICO),
    AirlineCode.UNITED.value: MockAirlineConnector(AirlineCode.UNITED),
}