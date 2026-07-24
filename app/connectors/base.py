from typing import Protocol


class AirlineConnector(Protocol):
    airline_code: str

    async def validate_input(
        self,
        pnr: str | None,
        last_name: str | None,
        ticket_number: str | None,
        source_url: str | None,
    ) -> dict[str, object]: ...

    async def retrieve_booking(self, booking_ref: str, last_name: str | None = None) -> dict[str, object]: ...

    async def fetch_flight_status(self, booking_ref: str, last_name: str | None = None) -> dict[str, object]: ...

    async def get_checkin_eligibility(self, booking_ref: str) -> dict[str, object]: ...

    async def perform_checkin(
        self, booking_ref: str, passenger_ids: list[str], policy: dict[str, object]
    ) -> dict[str, object]: ...

    async def retrieve_boarding_passes(self, booking_ref: str) -> list[dict[str, object]]: ...
