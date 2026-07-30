import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.connectors.airline_apis import AIRLINE_APIS, VolarisAPI, AeromexicoAPI, VivaAerobusAPI, UnitedAPI
from app.connectors.mock import MockAirlineConnector
from app.domain.models import AirlineCode

logger = logging.getLogger(__name__)


class LiveAirlineConnector:
    def __init__(self, airline_code: AirlineCode) -> None:
        self.airline_code = airline_code.value
        self.mock_fallback = MockAirlineConnector(airline_code)
        self.api_class = AIRLINE_APIS.get(airline_code.value)

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
        clean_last = (last_name or "").strip().capitalize()

        if not clean_last:
            return {
                "error": True,
                "reason": "MISSING_LAST_NAME",
                "message": "Se requiere el apellido para consultar la reserva.",
            }

        # 1. Try mobile app REST API endpoints (fast, no proxy, no CAPTCHA)
        if self.api_class:
            try:
                mobile_data = await self.api_class.retrieve_booking(ref, clean_last)
                if mobile_data:
                    logger.info(f"Successfully retrieved {self.airline_code} booking {ref} via mobile API")
                    return mobile_data
            except Exception as e:
                logger.info(f"Mobile API fetch note for {self.airline_code} {ref}: {e}")

        # 2. Try live web query from airline servers (Standard HTTP)
        live_data = await self._fetch_live_airline_data(ref, clean_last)
        if live_data:
            return live_data

        # 3. Try Stealth Browser (Playwright) + AI Extractor
        try:
            from app.connectors.stealth_browser import StealthBrowserManager
            from app.services.ai_extractor import extract_booking_via_llm

            logger.info(f"Attempting Stealth Browser + AI Extractor for {self.airline_code} {ref}")
            json_data, page_text = None, None
            
            # Retry up to 2 times because Akamai can randomly block sessions
            for attempt in range(2):
                json_data, page_text = await StealthBrowserManager.fetch_live_booking_stealth(self.airline_code, ref, clean_last)
                if json_data:
                    break
                logger.info(f"Stealth Browser attempt {attempt + 1} captured 0 JSONs, retrying if possible...")
            
            # If the stealth browser somehow captured the actual JSON, we can try to parse it
            parsed_res = None
            if json_data:
                # json_data is now a list of all matching captured JSONs
                if self.airline_code == AirlineCode.VOLARIS.value:
                    for jd in (json_data if isinstance(json_data, list) else [json_data]):
                        parsed_res = self._parse_volaris_live(jd, ref, clean_last)
                        if parsed_res: break
                elif self.airline_code == AirlineCode.AEROMEXICO.value:
                    for jd in (json_data if isinstance(json_data, list) else [json_data]):
                        parsed_res = self._parse_aeromexico_live(jd, ref, clean_last)
                        if parsed_res: break
                elif self.airline_code == AirlineCode.VIVA.value:
                    for jd in (json_data if isinstance(json_data, list) else [json_data]):
                        parsed_res = self._parse_viva_live(jd, ref, clean_last)
                        if parsed_res: break
                elif self.airline_code == AirlineCode.UNITED.value:
                    for jd in (json_data if isinstance(json_data, list) else [json_data]):
                        parsed_res = self._parse_united_live(jd, ref, clean_last)
                        if parsed_res: break

                if not parsed_res:
                    # For others, let the LLM parse both the intercepted JSON and the visible text
                    import json
                    
                    filtered_jsons = []
                    for jd in (json_data if isinstance(json_data, list) else [json_data]):
                        jd_str = json.dumps(jd)
                        # Filter out huge unrelated payloads (Viva JSONs can be ~60-80KB)
                        if len(jd_str) < 150000 and ("passengers" in jd_str.lower() or "journeys" in jd_str.lower() or "itinerary" in jd_str.lower()):
                            filtered_jsons.append(jd)
                    
                    page_text = f"INTERCEPTED JSON(S):\n{json.dumps(filtered_jsons)}\n\nVISIBLE PAGE TEXT:\n{page_text}"
            
            # If we only got text/HTML or if JSON parsing failed, fallback to LLM
            if not parsed_res and page_text:
                parsed_res = await extract_booking_via_llm(page_text, ref, clean_last)
                
            if parsed_res:
                # Post-process to detect check-in completion for Viva Aerobus
                if self.airline_code == AirlineCode.VIVA.value and page_text:
                    checkin_indicators = [
                        "pases de abordar", "descargar pases", "pase de abordar",
                        "boarding pass", "boarding passes", "ver pases", "imprimir pases",
                        "imprimir pase", "ver pase"
                    ]
                    page_text_lower = page_text.lower()
                    if any(ind in page_text_lower for ind in checkin_indicators):
                        logger.info(f"Viva: detected check-in completion in page_text for {ref}")
                        if "segments" in parsed_res:
                            for seg in parsed_res["segments"]:
                                seg["is_checked_in"] = True
                return parsed_res
                    
        except Exception as e:
            logger.info(f"Stealth Browser / AI Extractor failed: {e}")

        # 4. Fallback to mock connector for known test bookings
        mock_data = await self.mock_fallback.retrieve_booking(ref, clean_last)
        if mock_data:
            return mock_data

        return {
            "error": True,
            "reason": "NOT_FOUND_ON_AIRLINE",
            "message": f"No se encontraron datos en vivo para la reserva {ref} ({clean_last}) en {self.airline_code}. Verifica el código y apellido.",
        }

    async def _fetch_live_airline_data(self, pnr: str, last_name: str) -> dict[str, Any] | None:
        """Fallback to web endpoints if mobile API fails."""
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "application/json"}

        try:
            async with __import__("httpx").AsyncClient(timeout=10, headers=headers, follow_redirects=True) as client:
                if self.airline_code == AirlineCode.VOLARIS.value:
                    url = f"https://www.volaris.com/api/v1/booking/{pnr}"
                    res = await client.get(url, params={"lastName": last_name})
                    if res.status_code == 200:
                        return self._parse_volaris_live(res.json(), pnr, last_name)

                elif self.airline_code == AirlineCode.AEROMEXICO.value:
                    url = "https://www.aeromexico.com/api/v1/booking/retrieve"
                    res = await client.post(url, json={"pnr": pnr, "lastName": last_name})
                    if res.status_code == 200:
                        return self._parse_aeromexico_live(res.json(), pnr, last_name)

                elif self.airline_code == AirlineCode.VIVA.value:
                    url = f"https://www.vivaaerobus.com/api/booking/{pnr}"
                    res = await client.get(url, params={"lastName": last_name})
                    if res.status_code == 200:
                        return self._parse_viva_live(res.json(), pnr, last_name)

                elif self.airline_code == AirlineCode.UNITED.value:
                    # United requires the web form at /manageres/mytrips — handled by
                    # StealthBrowserManager._united_camoufox_session (called above in retrieve_booking).
                    # No direct REST API is publicly available without auth.
                    pass

        except Exception as e:
            logger.info(f"Live web query for {self.airline_code} {pnr} note: {e}")

        return None

    def _parse_volaris_live(self, data: dict[str, Any], pnr: str, last_name: str) -> dict[str, Any] | None:
        if not data.get("passengers") or not data.get("journeys"):
            return None
            
        passengers = []
        pax_data = data.get("passengers", {})
        pax_list = pax_data.values() if isinstance(pax_data, dict) else (pax_data if isinstance(pax_data, list) else [])
        
        for idx, pax in enumerate(pax_list, 1):
            pax_name = pax.get("name", {})
            name = f"{pax_name.get('first', '')} {pax_name.get('last', last_name)}".strip().title()
            passengers.append({"id": pax.get("passengerKey", f"P{idx}"), "display_name": name})

        segments = []
        journeys = data.get("journeys", [])
        if journeys and isinstance(journeys, list):
            for seg in journeys[0].get("segments", []):
                designator = seg.get("designator", {})
                ident = seg.get("identifier", {})
                carrier = ident.get("carrierCode", "Y4")
                flt_num = ident.get("identifier", pnr)
                
                dep_str = designator.get("departure", datetime.now(UTC).isoformat())
                est_str = designator.get("departure", dep_str)

                fn = flt_num.strip()
                if not fn.startswith(carrier):
                    fn = f"{carrier} {fn}"
                if fn.startswith(carrier) and not fn.startswith(f"{carrier} "):
                    fn = f"{carrier} {fn[len(carrier):]}"

                # Parse seat from data.seats.seats, or from pax assignments, or from passengerSegment
                seats_list = data.get("seats", {}).get("seats", [])
                seg_seats = []
                
                # Check passengerSegment inside the segment
                for ps in seg.get("passengerSegment", {}).values():
                    # Seats inside passengerSegment
                    for s in ps.get("seats", []):
                        seat = s.get("unitDesignator") or s.get("designator")
                        if seat: seg_seats.append(seat)
                
                # Check pax boarding passes directly as fallback
                if not seg_seats:
                    for pax in pax_list:
                        for bp in pax.get("boardingPasses", []):
                            if bp.get("segmentKey") == seg.get("key") or (designator.get("origin") in bp.get("segmentKey", "") and designator.get("destination") in bp.get("segmentKey", "")):
                                seat = bp.get("seat") or bp.get("seatNumber") or bp.get("designator")
                                if seat: seg_seats.append(seat)
                        for s in pax.get("seats", []):
                            if s.get("segmentKey") == seg.get("key") or (designator.get("origin") in s.get("segmentKey", "") and designator.get("destination") in s.get("segmentKey", "")):
                                seat = s.get("seatNumber") or s.get("designator") or s.get("unitDesignator")
                                if seat: seg_seats.append(seat)
                
                # Check liftStatus for checkin (2 = CheckedIn, 3 = Boarded)
                is_checked_in = False
                for ps in seg.get("passengerSegment", {}).values():
                    if ps.get("liftStatus") in (2, 3, "2", "3", "CheckedIn", "Boarded"):
                        is_checked_in = True

                if not seg_seats:
                    for s in seats_list:
                        if len(journeys[0].get("segments", [])) == 1 or s.get("segmentKey") == seg.get("key"):
                            seat_num = s.get("seatNumber") or s.get("designator")
                            if seat_num:
                                seg_seats.append(seat_num)
                    if not seg_seats:
                        for s in seats_list:
                            seat_seg_key = s.get("segmentKey", "")
                            if designator.get("origin") in seat_seg_key and designator.get("destination") in seat_seg_key:
                                seat_num = s.get("seatNumber") or s.get("designator")
                                if seat_num:
                                    seg_seats.append(seat_num)
                    if not seg_seats and seats_list:
                        for s in seats_list:
                            seat_num = s.get("seatNumber") or s.get("designator")
                            if seat_num:
                                seg_seats.append(seat_num)
                                
                seat_val = ", ".join(sorted(list(set(seg_seats)))) if seg_seats else "Sin asignar"

                segments.append({
                    "flight_number": fn,
                    "departure_airport": designator.get("origin", "MEX"),
                    "arrival_airport": designator.get("destination", "CUN"),
                    "scheduled_departure": datetime.fromisoformat(dep_str),
                    "estimated_departure": datetime.fromisoformat(est_str),
                    "operational_status": "Normal" if seg.get("status") == 6 else "SCHEDULED",
                    "gate": "TBD",
                    "terminal": "T1",
                    "seat": seat_val,
                    "boarding_group": "Grupo 1",
                    "is_checked_in": is_checked_in,
                })
        
        breakdown = data.get("breakdown", {})
        total = float(breakdown.get("totalAmount", 0.0))
        currency = data.get("currencyCode", "MXN")

        return {
            "passengers": passengers or [{"id": "P1", "display_name": f"Pasajero {last_name}"}],
            "payment_summary": {"amount": total, "currency": currency, "method": "Tarjeta", "status": "PAID" if data.get("info", {}).get("paidStatus") == 1 else "PENDING"},
            "segments": segments or [],
        }

    def _parse_aeromexico_live(self, data: dict[str, Any], pnr: str, last_name: str) -> dict[str, Any] | None:
        if "bookedLegCollection" not in data and "confirmedBookedLegCollection" not in data:
            return None
            
        passengers = []
        for pax in data.get("passengers", []):
            details = pax.get("passengerDetails", {})
            first = details.get("firstName", "")
            last = details.get("lastName", last_name)
            passengers.append({"id": pax.get("id", "P1"), "display_name": f"{first} {last}".strip()})
            
        segments = []
        legs = data.get("confirmedBookedLegCollection") or data.get("bookedLegCollection", [])
        for leg in legs:
            for seg in leg.get("segments", []):
                carrier = seg.get("marketingCarrier", "AM")
                flt = seg.get("marketingFlightCode", pnr)
                dep_str = seg.get("departureDateTime", datetime.now(UTC).isoformat())
                if not dep_str.endswith("Z") and "+" not in dep_str:
                    dep_str += "+00:00"
                
                # Parse seat from passengers list or seg keys
                seg_seats = []
                for pax in data.get("passengers", []):
                    for s in pax.get("seats", []) or pax.get("seatSelections", []) or pax.get("assignedSeats", []):
                        seat_num = s.get("seatNumber") or s.get("number") or s.get("designator")
                        if seat_num:
                            seg_seats.append(seat_num)
                if not seg_seats:
                    for k in ["seat", "seatNumber", "assignedSeat", "preReservedSeat", "seatSelection"]:
                        if seg.get(k):
                            seg_seats.append(str(seg[k]))
                            break
                # Check liftStatus/checkInStatus for checkin
                is_checked_in = False
                if seg.get("checkInStatus") == "CHECKED_IN" or seg.get("isCheckedIn") is True:
                    is_checked_in = True
                else:
                    for pax in data.get("passengers", []):
                        if pax.get("checkInStatus") == "CHECKED_IN":
                            is_checked_in = True
                            
                seat_val = ", ".join(sorted(list(set(seg_seats)))) if seg_seats else "Sin asignar"

                segments.append({
                    "flight_number": f"{carrier}{flt}",
                    "departure_airport": seg.get("departureAirport", "MEX"),
                    "arrival_airport": seg.get("arrivalAirport", "CUN"),
                    "scheduled_departure": datetime.fromisoformat(dep_str),
                    "estimated_departure": datetime.fromisoformat(dep_str),
                    "operational_status": "SCHEDULED" if seg.get("segmentStatusCode") == "HK" else seg.get("segmentStatusCode", "SCHEDULED"),
                    "gate": "TBD",
                    "terminal": seg.get("departureTerminal") or "T1",
                    "seat": seat_val,
                    "boarding_group": "TBD",
                    "is_checked_in": is_checked_in,
                })
                
        currency_data = data.get("currency", {})
        amount = currency_data.get("total", 0.0)
        currency = currency_data.get("currencyCode", "MXN")
        
        return {
            "passengers": passengers or [{"id": "P1", "display_name": last_name}],
            "payment_summary": {"amount": amount, "currency": currency, "method": "Tarjeta", "status": "PAID" if data.get("typeReservation") == "PAID" else "PENDING"},
            "segments": segments,
        }

    def _parse_viva_live(self, data: dict[str, Any], pnr: str, last_name: str) -> dict[str, Any] | None:
        # Locate the actual booking object in the payload
        booking = data.get("data", data)
        if isinstance(booking, dict) and "data" in booking:
            booking = booking.get("data", booking)
            
        if not isinstance(booking, dict) or ("journeys" not in booking and "passengers" not in booking):
            return None # Not the booking payload

        passengers = []
        for pax in booking.get("passengers", []):
            info = pax.get("info", pax)
            name = f"{info.get('firstName', '')} {info.get('lastName', last_name)}".strip()
            passengers.append({"id": pax.get("passengerKey", "P1"), "display_name": name})

        segments = []
        for journey in booking.get("journeys", []):
            for seg in journey.get("segments", []):
                dep = seg.get("departureDate", {})
                arr = seg.get("arrivalDate", {})
                origin = seg.get("origin", {})
                dest = seg.get("destination", {})
                
                orig_code = origin.get("code", origin) if isinstance(origin, dict) else origin
                dest_code = dest.get("code", dest) if isinstance(dest, dict) else dest

                dep_str = dep.get("scheduledUtc") or dep.get("scheduled") or datetime.now(UTC).isoformat()
                if dep_str and dep_str.endswith("Z"): dep_str = dep_str[:-1] + "+00:00"
                
                est_str = dep.get("estimated") or dep_str
                if est_str and est_str.endswith("Z"): est_str = est_str[:-1] + "+00:00"

                # Parse seat from booking.seats.seats, or from pax assignments, or passengerSegment
                seats_list = booking.get("seats", {}).get("seats", [])
                seg_seats = []
                
                # Check passengerSegment inside the segment
                ps_data = seg.get("passengerSegment", {})
                ps_list = ps_data.values() if isinstance(ps_data, dict) else (ps_data if isinstance(ps_data, list) else [])
                for ps in ps_list:
                    for s in ps.get("seats", []):
                        seat = s.get("unitDesignator") or s.get("designator")
                        if seat: seg_seats.append(seat)
                
                # Check pax boarding passes directly as fallback
                if not seg_seats:
                    for pax in booking.get("passengers", []):
                        for bp in pax.get("boardingPasses", []):
                            if bp.get("segmentKey") == seg.get("key") or (orig_code in bp.get("segmentKey", "") and dest_code in bp.get("segmentKey", "")):
                                seat = bp.get("seat") or bp.get("seatNumber") or bp.get("designator")
                                if seat: seg_seats.append(seat)
                        for s in pax.get("seats", []):
                            if s.get("segmentKey") == seg.get("key") or (orig_code in s.get("segmentKey", "") and dest_code in s.get("segmentKey", "")):
                                seat = s.get("seatNumber") or s.get("designator") or s.get("unitDesignator")
                                if seat: seg_seats.append(seat)
                                
                # Check liftStatus and passenger status for checkin
                is_checked_in = False
                
                # Method 1: Check passengerSegment liftStatus
                ps_data2 = seg.get("passengerSegment", {})
                ps_list2 = ps_data2.values() if isinstance(ps_data2, dict) else (ps_data2 if isinstance(ps_data2, list) else [])
                for ps in ps_list2:
                    if ps.get("liftStatus") in (2, 3, "2", "3", "CheckedIn", "Boarded"):
                        is_checked_in = True

                # Method 2: Check passengers array for check-in status
                for pax in booking.get("passengers", []):
                    # In some responses pax has "boardingPasses" if checked in
                    if pax.get("boardingPasses") and len(pax["boardingPasses"]) > 0:
                        for bp in pax["boardingPasses"]:
                            if bp.get("segmentKey") == seg.get("key") or (orig_code in bp.get("segmentKey", "") and dest_code in bp.get("segmentKey", "")):
                                is_checked_in = True

                if not seg_seats:
                    for s in seats_list:
                        if len(booking.get("journeys", [])) == 1 or s.get("segmentKey") == seg.get("key"):
                            seat_num = s.get("seatNumber") or s.get("designator")
                            if seat_num:
                                seg_seats.append(seat_num)
                    if not seg_seats:
                        for s in seats_list:
                            seat_seg_key = s.get("segmentKey", "")
                            if orig_code in seat_seg_key and dest_code in seat_seg_key:
                                seat_num = s.get("seatNumber") or s.get("designator")
                                if seat_num:
                                    seg_seats.append(seat_num)
                    if not seg_seats and seats_list:
                        for s in seats_list:
                            seat_num = s.get("seatNumber") or s.get("designator")
                            if seat_num:
                                seg_seats.append(seat_num)
                                
                seat_val = ", ".join(sorted(list(set(seg_seats)))) if seg_seats else "Sin asignar"

                segments.append({
                    "flight_number": seg.get("flightNumber", f"VB {pnr}"),
                    "departure_airport": orig_code or "MEX",
                    "arrival_airport": dest_code or "CUN",
                    "scheduled_departure": datetime.fromisoformat(dep_str),
                    "estimated_departure": datetime.fromisoformat(est_str),
                    "operational_status": seg.get("status", "SCHEDULED"),
                    "gate": seg.get("departureTerminal", "T1"),
                    "terminal": seg.get("departureTerminal", "T1"),
                    "seat": seat_val,
                    "boarding_group": "Grupo 1",
                    "is_checked_in": is_checked_in,
                })

        # Calculate total price
        amount = 0.0
        currency = "MXN"
        for payment in booking.get("payments", []):
            amt_info = payment.get("collectedAmount", payment.get("amount", {}))
            amount += float(amt_info.get("value", 0))
            currency = amt_info.get("currencyCode", currency)
            
        return {
            "passengers": passengers or [{"id": "P1", "display_name": f"Pasajero {last_name}"}],
            "payment_summary": {"amount": amount, "currency": currency, "method": "Online", "status": booking.get("paidStatus", "UNKNOWN")},
            "segments": segments or [],
            "pnr": pnr,
        }

    def _parse_united_live(self, data: dict[str, Any], pnr: str, last_name: str) -> dict[str, Any] | None:
        """
        Parse United Airlines real booking JSON from the tripdetails page API.
        United's response nests data under various keys; we try the most common paths.
        """
        # United wraps response in different shapes; try to unwrap
        inner = data
        for key in ("data", "tripDetails", "reservation", "booking"):
            if isinstance(inner.get(key), dict):
                inner = inner[key]
                break

        # ── Passengers ─────────────────────────────────────────────────────────
        passengers = []
        pax_list = inner.get("travelers") or inner.get("passengers") or inner.get("paxList") or []
        for i, pax in enumerate(pax_list, 1):
            first = (
                pax.get("firstName") or pax.get("first_name") or
                pax.get("givenName") or pax.get("name", {}).get("first") or ""
            )
            last = (
                pax.get("lastName") or pax.get("last_name") or
                pax.get("surname") or pax.get("name", {}).get("last") or last_name
            )
            display = f"{first} {last}".strip().title()
            passengers.append({"id": pax.get("id") or pax.get("passengerId") or f"P{i}", "display_name": display})

        # ── Segments / Flights ────────────────────────────────────────────────
        segments = []
        # Try various nesting paths United uses
        flights_raw = (
            inner.get("flights") or
            inner.get("segments") or
            inner.get("legs") or
            (inner.get("trip", {}) or {}).get("flights") or
            []
        )
        if not flights_raw:
            # Some shapes nest under trips[0]
            for trip in (inner.get("trips") or []):
                flights_raw.extend(trip.get("flights") or trip.get("segments") or [])

        for flt in flights_raw:
            carrier = flt.get("marketingCarrier") or flt.get("carrier") or "UA"
            flt_num = flt.get("flightNumber") or flt.get("flightNum") or pnr
            fn = f"{carrier} {flt_num}".strip() if not str(flt_num).startswith(carrier) else str(flt_num)

            dep_str = (
                flt.get("departureDateTime") or flt.get("scheduledDeparture") or
                flt.get("departure", {}).get("dateTime") or
                flt.get("departureTime") or datetime.now(UTC).isoformat()
            )
            if isinstance(dep_str, str) and dep_str.endswith("Z"):
                dep_str = dep_str[:-1] + "+00:00"

            dep_airport = (
                flt.get("departureAirport") or flt.get("origin") or
                flt.get("departure", {}).get("airport") or "MEX"
            )
            arr_airport = (
                flt.get("arrivalAirport") or flt.get("destination") or
                flt.get("arrival", {}).get("airport") or "ORD"
            )

            # Seat
            seat_val = "Sin asignar"
            for seat_key in ["seat", "seatNumber", "assignedSeat", "seatAssignment"]:
                sv = flt.get(seat_key)
                if sv:
                    seat_val = str(sv)
                    break
            if seat_val == "Sin asignar":
                for pax in pax_list:
                    for s in (pax.get("seats") or pax.get("seatAssignments") or []):
                        sn = s.get("seatNumber") or s.get("seat") or s.get("number")
                        if sn:
                            seat_val = str(sn)
                            break

            gate = flt.get("departureGate") or flt.get("gate") or "TBD"
            terminal = flt.get("departureTerminal") or flt.get("terminal") or "TBD"
            status = flt.get("status") or flt.get("flightStatus") or "SCHEDULED"

            try:
                dep_dt = datetime.fromisoformat(dep_str)
            except Exception:
                dep_dt = datetime.now(UTC)
                
            # Check for check-in status
            is_checked_in = False
            for k in ["checkInStatus", "checkinStatus", "isCheckedIn", "isCheckinEligible"]:
                val = flt.get(k)
                if val == "CHECKED_IN" or val is True or val == "Y":
                    is_checked_in = True
                    break
            
            # Also check passengers
            if not is_checked_in:
                for pax in pax_list:
                    if pax.get("isCheckedIn") or pax.get("checkInStatus") == "CHECKED_IN" or pax.get("hasBoardingPass"):
                        is_checked_in = True
                        break

            segments.append({
                "flight_number": fn,
                "departure_airport": dep_airport,
                "arrival_airport": arr_airport,
                "scheduled_departure": dep_dt,
                "estimated_departure": dep_dt,
                "operational_status": str(status),
                "gate": gate,
                "terminal": terminal,
                "seat": seat_val,
                "boarding_group": flt.get("boardingGroup") or "TBD",
                "is_checked_in": is_checked_in,
            })

        if not segments:
            return None  # empty = not a booking payload

        # ── Payment ───────────────────────────────────────────────────────────
        total = 0.0
        currency = "MXN"
        for pay_key in ["totalPrice", "totalAmount", "price", "amount"]:
            raw = inner.get(pay_key)
            if isinstance(raw, (int, float)):
                total = float(raw)
                break
            if isinstance(raw, dict):
                total = float(raw.get("amount") or raw.get("value") or 0)
                currency = raw.get("currency") or raw.get("currencyCode") or currency
                break

        return {
            "passengers": passengers or [{"id": "P1", "display_name": last_name.title()}],
            "payment_summary": {
                "amount": total,
                "currency": currency,
                "method": "Tarjeta",
                "status": "PAID",
            },
            "segments": segments,
            "pnr": pnr,
        }

    async def fetch_flight_status(self, booking_ref: str, last_name: str | None = None) -> dict[str, object]:
        return await self.mock_fallback.fetch_flight_status(booking_ref, last_name)

    async def get_checkin_eligibility(self, booking_ref: str) -> dict[str, object]:
        return await self.mock_fallback.get_checkin_eligibility(booking_ref)

    async def perform_checkin(
        self, booking_ref: str, passenger_ids: list[str], policy: dict[str, object]
    ) -> dict[str, object]:
        # Try to find the real PNR and passenger details from database
        from app.repositories.sqlite import store_sqlite
        from app.security.crypto import decrypt_from_storage
        
        booking = None
        for b in store_sqlite.bookings.values():
            if str(b.id)[:8].upper() == booking_ref or b.encrypted_locator == booking_ref:
                booking = b
                break

        if booking and booking.airline == AirlineCode.VIVA:
            real_pnr = decrypt_from_storage(booking.encrypted_locator)
            real_last_name = decrypt_from_storage(booking.encrypted_last_name)
            
            if real_pnr and real_last_name:
                logger.info(f"Attempting 100% REAL check-in via Camoufox for Viva booking {real_pnr}")
                res = await self._run_real_viva_checkin(real_pnr, real_last_name, policy)
                if res:
                    return res

        return await self.mock_fallback.perform_checkin(booking_ref, passenger_ids, policy)

    async def _run_real_viva_checkin(self, pnr: str, last_name: str, policy: dict) -> dict | None:
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError:
            return None

        try:
            cfg = {
                "os": "windows",
                "humanize": True,
                "headless": True,
                "geoip": True,
            }
            import os
            from app.connectors.stealth_browser import parse_proxy_setting
            proxy_dict = parse_proxy_setting(os.getenv("RESIDENTIAL_PROXY_URL"))
            if proxy_dict:
                cfg["proxy"] = proxy_dict

            async with AsyncCamoufox(**cfg) as browser:
                page = await browser.new_page()
                
                # Warm up
                await page.goto("https://www.vivaaerobus.com/es-mx", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                
                # Navigate to booking details
                booking_url = f"https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr={pnr}&lastName={last_name}"
                await page.goto(booking_url, wait_until="domcontentloaded", timeout=40000)
                await page.wait_for_timeout(6000)

                # Accept cookies
                for selector in ["text='Aceptar'", "text='Accept'", "[id*='cookie'] button", ".accept-btn"]:
                    try:
                        await page.click(selector, timeout=1500)
                        await page.wait_for_timeout(500)
                        break
                    except Exception:
                        pass

                # Locate the check-in button
                checkin_selectors = [
                    "button:has-text('Check-in')",
                    "a:has-text('Check-in')",
                    "button:has-text('Hacer Check-in')",
                    "button:has-text('Iniciar Check-in')",
                    "a:has-text('Hacer Check-in')",
                    "a:has-text('Iniciar Check-in')"
                ]

                checkin_btn = None
                for sel in checkin_selectors:
                    try:
                        checkin_btn = await page.wait_for_selector(sel, timeout=3000)
                        if checkin_btn:
                            await checkin_btn.click()
                            await page.wait_for_timeout(5000)
                            break
                    except Exception:
                        pass

                if not checkin_btn:
                    passes_btn = await page.query_selector(
                        "button:has-text('Pases de abordar'), button:has-text('Pase de abordar'), "
                        "button:has-text('Descargar pases'), button:has-text('Descargar pase'), "
                        "a:has-text('Pases de abordar'), a:has-text('Pase de abordar'), "
                        "a:has-text('Descargar pases')"
                    )
                    if passes_btn:
                        return {
                            "success": True, 
                            "status": "BOARDING_PASS_READY",
                            "boarding_passes": [
                                {
                                    "passenger_id": "P1",
                                    "download_url": f"https://official.airline.com/passes/{pnr[:8]}_boarding_pass.pdf",
                                    "expires_at": datetime.now(UTC) + timedelta(days=2),
                                }
                            ]
                        }
                    return None

                # Confirm passengers
                try:
                    passengers_checkboxes = await page.query_selector_all("input[type='checkbox']")
                    for cb in passengers_checkboxes:
                        if not await cb.is_checked():
                            await cb.click()
                            await page.wait_for_timeout(500)
                except Exception:
                    pass

                continue_selectors = [
                    "button:has-text('Continuar')",
                    "button:has-text('Siguiente')",
                    "button:has-text('Confirmar')",
                    "button[type='submit']"
                ]
                for sel in continue_selectors:
                    try:
                        btn = await page.wait_for_selector(sel, timeout=4000)
                        if btn:
                            await btn.click()
                            await page.wait_for_timeout(4000)
                            break
                    except Exception:
                        pass

                # Hazardous materials terms
                try:
                    checkboxes = await page.query_selector_all("input[type='checkbox']")
                    for cb in checkboxes:
                        if not await cb.is_checked():
                            await cb.click()
                            await page.wait_for_timeout(500)
                    
                    for sel in continue_selectors:
                        btn = await page.query_selector(sel)
                        if btn:
                            await btn.click()
                            await page.wait_for_timeout(4000)
                            break
                except Exception:
                    pass

                # Skip seat selection (assign free seat)
                seat_skip_selectors = [
                    "button:has-text('Saltar')",
                    "button:has-text('Saltar selección')",
                    "button:has-text('Asignar gratis')",
                    "button:has-text('Continuar sin asiento')",
                    "button:has-text('No, gracias')",
                    "button:has-text('Skip')",
                    "button:has-text('Continue without choosing')"
                ]
                for sel in seat_skip_selectors:
                    try:
                        btn = await page.wait_for_selector(sel, timeout=3000)
                        if btn:
                            await btn.click()
                            await page.wait_for_timeout(4000)
                            break
                    except Exception:
                        pass

                # Skip baggage / extras selection
                extras_skip_selectors = [
                    "button:has-text('Continuar')",
                    "button:has-text('Saltar')",
                    "button:has-text('Saltar extras')",
                    "button:has-text('Continuar sin extras')",
                    "button:has-text('No, gracias')",
                    "button:has-text('Siguiente')"
                ]
                for sel in extras_skip_selectors:
                    try:
                        btn = await page.wait_for_selector(sel, timeout=3000)
                        if btn:
                            await btn.click()
                            await page.wait_for_timeout(4000)
                            break
                    except Exception:
                        pass

                # Final confirmation
                finish_selectors = [
                    "button:has-text('Finalizar check-in')",
                    "button:has-text('Terminar check-in')",
                    "button:has-text('Confirmar check-in')",
                    "button:has-text('Obtener pases')",
                    "button:has-text('Finalizar')"
                ]
                for sel in finish_selectors:
                    try:
                        btn = await page.wait_for_selector(sel, timeout=3000)
                        if btn:
                            await btn.click()
                            await page.wait_for_timeout(5000)
                            break
                    except Exception:
                        pass

                await page.wait_for_timeout(5000)
                success_indicators = [
                    "pases de abordar",
                    "descargar pases",
                    "pase de abordar",
                    "check-in completado",
                    "check-in exitoso",
                    "boarding pass",
                    "imprimir pases"
                ]
                page_content = await page.content()
                if any(ind.lower() in page_content.lower() for ind in success_indicators):
                    logger.info(f"Real check-in success for Viva booking: {pnr}")
                    return {
                        "success": True,
                        "status": "BOARDING_PASS_READY",
                        "boarding_passes": [
                            {
                                "passenger_id": "P1",
                                "download_url": f"https://official.airline.com/passes/{pnr[:8]}_boarding_pass.pdf",
                                "expires_at": datetime.now(UTC) + timedelta(days=2),
                            }
                        ],
                    }

        except Exception as e:
            logger.error(f"Error performing real check-in for Viva Aerobus: {e}")
        
        return None

    async def fetch_flight_status(self, booking_ref: str, last_name: str | None = None) -> dict[str, object]:
        try:
            live_data = await self.retrieve_booking(booking_ref, last_name)
            if live_data and not live_data.get("error"):
                checkin_status = "NOT_ELIGIBLE"
                # Check for explicit is_checked_in flag first
                is_checked_in = any(s.get("is_checked_in") for s in live_data.get("segments", []))
                has_seats = any(s.get("seat") and s.get("seat") != "Sin asignar" for s in live_data.get("segments", []))
                
                # If we have seats and it's within 24-48 hours, or if we have explicit flag
                if is_checked_in or has_seats:
                    checkin_status = "BOARDING_PASS_READY"
                elif self.airline_code == AirlineCode.VOLARIS.value and hasattr(self.api_class, 'check_in') and last_name:
                    should_check_in = any(
                        s.get("scheduled_departure") and (s["scheduled_departure"] - datetime.now(UTC)).total_seconds() < 72 * 3600
                        for s in live_data.get("segments", [])
                    )
                    if should_check_in:
                        success = await self.api_class.check_in(booking_ref, last_name)
                        if success:
                            checkin_status = "BOARDING_PASS_READY"
                            
                return {
                    "segments": live_data.get("segments", []),
                    "checkin_status": checkin_status,
                }
        except Exception as e:
            logger.info(f"Live fetch_flight_status error: {e}")
        return await self.mock_fallback.fetch_flight_status(booking_ref, last_name)

    async def get_checkin_eligibility(self, booking_ref: str, last_name: str | None = None) -> dict[str, object]:
        return await self.mock_fallback.get_checkin_eligibility(booking_ref)

    async def retrieve_boarding_passes(self, booking_ref: str) -> list[dict[str, object]]:
        # Try to find the real PNR and passenger details from database
        from app.repositories.sqlite import store_sqlite
        from app.security.crypto import decrypt_from_storage
        from app.connectors.boarding_pass_manager import download_boarding_passes
        
        last_name = None
        for b in store_sqlite.bookings.values():
            if str(b.id)[:8].upper() == booking_ref or b.encrypted_locator == booking_ref:
                last_name = decrypt_from_storage(b.encrypted_last_name)
                booking_ref = decrypt_from_storage(b.encrypted_locator)
                break
                
        if last_name:
            passes = await download_boarding_passes(self.airline_code, booking_ref, last_name)
            if passes:
                return passes
                
        # Never fallback to mock if real passes are requested
        return []


LIVE_CONNECTORS: dict[str, LiveAirlineConnector] = {
    AirlineCode.VOLARIS.value: LiveAirlineConnector(AirlineCode.VOLARIS),
    AirlineCode.VIVA.value: LiveAirlineConnector(AirlineCode.VIVA),
    AirlineCode.AEROMEXICO.value: LiveAirlineConnector(AirlineCode.AEROMEXICO),
    AirlineCode.UNITED.value: LiveAirlineConnector(AirlineCode.UNITED),
}