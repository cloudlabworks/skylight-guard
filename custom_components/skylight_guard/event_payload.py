"""Build the request body for creating a Skylight calendar event.

Pure Python (no Home Assistant imports).

Endpoint: ``POST /api/frames/{frame_id}/calendar_events`` (delete is
``DELETE /api/frames/{frame_id}/calendar_events/{event_id}``), as in
dknowles2/pyskylight ``client.py``. The body is flat JSON, no JSON:API
``data``/``attributes`` envelope.

Field names and formats were confirmed against a real Skylight frame by the
maintainers (pyskylight 0.6.0, September 2026):

  * ``summary``, ``description``, ``location``, ``starts_at``, ``ends_at``,
    ``all_day``, ``timezone``, ``kind`` and ``category_ids`` are accepted.
  * ``kind`` is ``"standard"`` for an ordinary event.
  * All-day events use date-only strings with an INCLUSIVE end date (a
    one-day event has ``starts_at == ends_at``). Home Assistant uses an
    exclusive end date, so it is converted here.
  * Timed events must carry a UTC offset. A naive time such as
    ``2026-09-14T07:10:00`` is stored as UTC and shows up hours off on the
    wall, so naive datetimes are refused.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

PAYLOAD_SHAPE_VERIFIED = True


def build_event_payload(
    *,
    summary: str,
    start: date | datetime,
    end: date | datetime,
    category_ids: Iterable[str],
    description: str | None = None,
    location: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Return the flat JSON body for ``POST .../calendar_events``.

    ``end`` follows Home Assistant's convention: exclusive for all-day events.
    """
    if isinstance(start, datetime) != isinstance(end, datetime):
        raise ValueError("start and end must both be dates or both be datetimes")
    all_day = not isinstance(start, datetime)
    if end < start:
        raise ValueError("end must not be before start")
    if all_day:
        last_day = end - timedelta(days=1) if end > start else start
        starts_at, ends_at = start.isoformat(), last_day.isoformat()
    else:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError(
                "timed events need a timezone-aware start and end; "
                "Skylight stores naive times as UTC"
            )
        starts_at, ends_at = start.isoformat(), end.isoformat()
    body: dict[str, Any] = {
        "summary": summary,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "all_day": all_day,
        "kind": "standard",
        "category_ids": [str(c) for c in category_ids],
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if timezone:
        body["timezone"] = timezone
    return body
