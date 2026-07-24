from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.diff import build_snapshot, diff_snapshots


def test_diff_creates_dedupable_delay_event() -> None:
    segment_id = uuid4()
    departure = datetime(2026, 8, 1, 12, tzinfo=UTC)
    previous = build_snapshot(
        segment_id,
        {"estimated_departure": departure, "operational_status": "scheduled", "gate": None},
    )
    current = build_snapshot(
        segment_id,
        {
            "estimated_departure": departure + timedelta(minutes=45),
            "operational_status": "delayed",
            "gate": "B12",
        },
    )

    events = diff_snapshots(previous, current)

    assert {event.event_type for event in events}
    assert len({event.dedupe_key for event in events}) == len(events)
