from datetime import UTC, datetime, timedelta

from app.domain.models import AirlineCode


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

        if self.airline_code == AirlineCode.VOLARIS.value:
            num = "".join(filter(str.isdigit, ref))
            flight_1 = "Y4 700" if ref == "LCYD6C" else (f"Y4 {num}" if num else f"Y4 {ref[:6]}")
            passenger_name = f"Karina {clean_last}" if ref == "LCYD6C" else f"Pasajero {clean_last}"
            return {
                "passengers": [
                    {"id": "P1", "display_name": passenger_name},
                ],
                "payment_summary": {
                    "amount": 14287.00 if ref == "LCYD6C" else 3850.00,
                    "currency": "MXN",
                    "method": "Tarjeta",
                    "status": "PAID",
                },
                "segments": [
                    {
                        "flight_number": flight_1,
                        "departure_airport": "MEX",
                        "arrival_airport": "ORD" if ref == "LCYD6C" else "TIJ",
                        "scheduled_departure": datetime(2026, 7, 30, 6, 50, tzinfo=UTC),
                        "estimated_departure": datetime(2026, 7, 30, 6, 50, tzinfo=UTC),
                        "operational_status": "SCHEDULED",
                        "gate": "A12",
                        "terminal": "T1",
                        "seat": "Sin asignar",
                        "boarding_group": "Grupo B",
                    }
                ],
            }

        if self.airline_code == AirlineCode.AEROMEXICO.value:
            flight_1 = "AM 452" if "452" in ref else ("AM " + ref[2:] if ref.startswith("AM") and ref[2:].isdigit() else "AM 116")
            flight_2 = "AM 453" if "452" in ref else "AM 115"
            dep_1, arr_1 = ("MEX", "GDL") if "452" in ref or "GDL" in ref else ("CJS", "MEX")
            dep_2, arr_2 = ("GDL", "MEX") if "452" in ref or "GDL" in ref else ("MEX", "CJS")
            return {
                "passengers": [
                    {"id": "P1", "display_name": f"Mariana {clean_last}"}
                ],
                "payment_summary": {
                    "amount": 5420.00,
                    "currency": "MXN",
                    "method": "Tarjeta (Visa)",
                    "status": "PAID",
                },
                "segments": [
                    {
                        "flight_number": flight_1,
                        "departure_airport": dep_1,
                        "arrival_airport": arr_1,
                        "scheduled_departure": datetime(2026, 7, 27, 9, 57, tzinfo=UTC),
                        "estimated_departure": datetime(2026, 7, 27, 9, 57, tzinfo=UTC),
                        "operational_status": "SCHEDULED",
                        "gate": "24",
                        "terminal": "T2",
                        "seat": "Aleatorio (Sin selección previa)",
                        "boarding_group": "Grupo 2",
                    },
                    {
                        "flight_number": flight_2,
                        "departure_airport": dep_2,
                        "arrival_airport": arr_2,
                        "scheduled_departure": datetime(2026, 7, 31, 10, 30, tzinfo=UTC),
                        "estimated_departure": datetime(2026, 7, 31, 10, 30, tzinfo=UTC),
                        "operational_status": "SCHEDULED",
                        "gate": "62",
                        "terminal": "T2",
                        "seat": "Aleatorio (Sin selección previa)",
                        "boarding_group": "Grupo 2",
                    },
                ],
            }

        if self.airline_code == AirlineCode.VIVA.value:
            flight_1 = "VB 452" if "452" in ref else ("VB " + ref[2:] if ref.startswith("VB") and ref[2:].isdigit() else "VB 1124")
            flight_2 = "VB 453" if "452" in ref else "VB 1125"
            return {
                "passengers": [
                    {"id": "P1", "display_name": f"Carlos {clean_last}"}
                ],
                "payment_summary": {
                    "amount": 2450.00,
                    "currency": "MXN",
                    "method": "Tarjeta (Mastercard)",
                    "status": "PAID",
                },
                "segments": [
                    {
                        "flight_number": flight_1,
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
            }

        if self.airline_code == AirlineCode.UNITED.value:
            flight_1 = "UA 452" if "452" in ref else ("UA " + ref[2:] if ref.startswith("UA") and ref[2:].isdigit() else "UA 452")
            return {
                "passengers": [
                    {"id": "P1", "display_name": f"Alex {clean_last}"}
                ],
                "payment_summary": {
                    "amount": 6800.00,
                    "currency": "MXN",
                    "method": "Tarjeta (Amex)",
                    "status": "PAID",
                },
                "segments": [
                    {
                        "flight_number": flight_1,
                        "departure_airport": "MEX",
                        "arrival_airport": "IAH",
                        "scheduled_departure": datetime(2026, 8, 1, 15, 30, tzinfo=UTC),
                        "estimated_departure": datetime(2026, 8, 1, 15, 30, tzinfo=UTC),
                        "operational_status": "SCHEDULED",
                        "gate": "E12",
                        "terminal": "T1",
                        "seat": "Aleatorio (Sin selección previa)",
                        "boarding_group": "Group 3",
                    }
                ],
            }

        departure = datetime.now(UTC).replace(microsecond=0) + timedelta(days=2)
        return {
            "passengers": [{"id": "P1", "display_name": f"Pasajero {clean_last}"}],
            "payment_summary": {
                "amount": 3200.00,
                "currency": "MXN",
                "method": "Tarjeta",
                "status": "PAID",
            },
            "segments": [
                {
                    "flight_number": "Y4 452",
                    "departure_airport": "GDL",
                    "arrival_airport": "TIJ",
                    "scheduled_departure": departure,
                    "estimated_departure": departure,
                    "operational_status": "SCHEDULED",
                    "gate": None,
                    "terminal": "T1",
                    "seat": "Aleatorio (Sin selección previa)",
                    "boarding_group": None,
                }
            ],
        }

    async def fetch_flight_status(self, booking_ref: str, last_name: str | None = None) -> dict[str, object]:
        self._recheck_count += 1
        booking = await self.retrieve_booking(booking_ref, last_name)
        segments = booking["segments"]
        if self._recheck_count > 1:
            for segment in segments:
                segment["estimated_departure"] = segment["scheduled_departure"] + timedelta(minutes=45)
                segment["operational_status"] = "DELAYED"
                segment["gate"] = "B12"
        return {"segments": segments, "checkin_status": "CHECKIN_WINDOW_OPEN"}

    async def get_checkin_eligibility(self, booking_ref: str) -> dict[str, object]:
        return {
            "status": "CHECKIN_WINDOW_OPEN",
            "eligible": True,
        }

    async def perform_checkin(
        self, booking_ref: str, passenger_ids: list[str], policy: dict[str, object]
    ) -> dict[str, object]:
        if policy.get("seat_policy") not in ("skip_seat_selection", "free_only") or policy.get("never_purchase_extras") is not True:
            return {"status": "ACTION_REQUIRED", "reason": "unsafe_policy"}
        ref = booking_ref.upper()
        return {
            "status": "SUCCESS",
            "checkin_status": "BOARDING_PASS_READY",
            "assigned_seats": {"P1": "Aleatorio por la aerolínea (Paso de selección saltado)"},
            "boarding_passes": [
                {
                    "download_url": f"https://api.flights-mx.internal/passes/{ref}_boarding_pass.pdf",
                    "expires_at": datetime.now(UTC) + timedelta(days=7),
                }
            ],
        }

    async def retrieve_boarding_passes(self, booking_ref: str) -> list[dict[str, object]]:
        ref = booking_ref.upper()
        return [
            {
                "download_url": f"https://api.flights-mx.internal/passes/{ref}_boarding_pass.pdf",
                "expires_at": datetime.now(UTC) + timedelta(days=7),
            }
        ]


CONNECTORS = {airline: MockAirlineConnector(airline) for airline in AirlineCode}
