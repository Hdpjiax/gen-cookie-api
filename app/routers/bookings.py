from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.schemas import (
    BookingCreate,
    BookingRead,
    BoardingPassRead,
    CheckinConsentCreate,
    FlightEventRead,
    RecheckRead,
    SegmentDeleteRead,
    SegmentRecheckRead,
)
from app.services.bookings import booking_service

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("", response_model=BookingRead, status_code=status.HTTP_201_CREATED)
async def create_booking(payload: BookingCreate) -> BookingRead:
    return await booking_service.create_booking(payload)


@router.get("", response_model=list[BookingRead])
async def list_bookings(telegram_id: int) -> list[BookingRead]:
    return booking_service.list_bookings(telegram_id)


@router.get("/{booking_id}", response_model=BookingRead)
async def get_booking(booking_id: UUID, telegram_id: int) -> BookingRead:
    booking = booking_service.get_booking(booking_id, telegram_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="booking_not_found")
    return booking


@router.post("/{booking_id}/recheck", response_model=RecheckRead)
async def recheck_booking(booking_id: UUID, telegram_id: int) -> RecheckRead:
    result = await booking_service.recheck_booking(booking_id, telegram_id)
    if result is None:
        raise HTTPException(status_code=404, detail="booking_not_found")
    return result


@router.post("/{booking_id}/checkin-consent", response_model=BookingRead)
async def grant_checkin_consent(
    booking_id: UUID, telegram_id: int, payload: CheckinConsentCreate
) -> BookingRead:
    booking = booking_service.grant_checkin_consent(booking_id, telegram_id, payload)
    if booking is None:
        raise HTTPException(status_code=404, detail="booking_not_found")
    return booking


@router.post("/{booking_id}/checkin", response_model=BookingRead)
async def process_checkin(booking_id: UUID, telegram_id: int) -> BookingRead:
    res = await booking_service.process_auto_checkin(booking_id, telegram_id)
    if res is None:
        booking = booking_service.get_booking(booking_id, telegram_id)
        if booking is None:
            raise HTTPException(status_code=404, detail="booking_not_found")
        return booking
    return res[0]


@router.get("/{booking_id}/events", response_model=list[FlightEventRead])
async def list_events(booking_id: UUID, telegram_id: int) -> list[FlightEventRead]:
    events = booking_service.list_events(booking_id, telegram_id)
    if events is None:
        raise HTTPException(status_code=404, detail="booking_not_found")
    return events


@router.get("/{booking_id}/boarding-passes", response_model=list[BoardingPassRead])
async def list_boarding_passes(booking_id: UUID, telegram_id: int) -> list[BoardingPassRead]:
    passes = booking_service.list_boarding_passes(booking_id, telegram_id)
    if passes is None:
        raise HTTPException(status_code=404, detail="booking_not_found")
    return passes


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_booking(booking_id: UUID, telegram_id: int) -> None:
    deleted = booking_service.delete_booking(booking_id, telegram_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="booking_not_found")


@router.post("/{booking_id}/recheck/{segment_index}", response_model=SegmentRecheckRead)
async def recheck_segment(booking_id: UUID, segment_index: int, telegram_id: int) -> SegmentRecheckRead:
    result = await booking_service.recheck_segment(booking_id, telegram_id, segment_index)
    if result is None:
        raise HTTPException(status_code=404, detail="booking_or_segment_not_found")
    return result


@router.delete("/{booking_id}/segments/{segment_index}", response_model=SegmentDeleteRead)
async def delete_segment(booking_id: UUID, segment_index: int, telegram_id: int) -> SegmentDeleteRead:
    result = booking_service.delete_segment(booking_id, telegram_id, segment_index)
    if result is None:
        raise HTTPException(status_code=404, detail="booking_or_segment_not_found")
    return result
