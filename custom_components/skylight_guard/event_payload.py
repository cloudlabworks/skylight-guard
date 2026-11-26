"""Build the request body for creating a Skylight calendar event.

Pure Python (no Home Assistant imports).

What is sourced from public code:
  * Endpoint: ``POST /api/frames/{frame_id}/calendar_events`` and
    ``DELETE /api/frames/{frame_id}/calendar_events/{event_id}``, from
    dknowles2/pyskylight ``client.py`` (``create_calendar_event`` /
    ``delete_calendar_event``).
  * Body shape: flat JSON, no JSON:API ``data``/``attributes`` envelope. The
    pyskylight ``docs/api-notes.md`` states that writes for calendar events
    (among other resources) take a flat body.

UNVERIFIED (not confirmed by any public source we could find):
  * The exact field names accepted on create. pyskylight passes caller
    supplied ``**fields`` through untouched and documents none. The names
    below mirror the attributes Skylight returns when reading an event
    (``summary``, ``description``, ``location``, ``starts_at``, ``ends_at``,
    ``all_day``, ``timezone``) and the ``category_ids`` naming used by the
    related rewards / nudges endpoints.
  * How all-day events must be expressed (date-only strings with an
    exclusive end date are sent here, matching Home Assistant's convention).

Everything that depends on those guesses lives in ``build_event_payload`` so
there is exactly one place to fix once the shape is confirmed.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

PAYLOAD_SHAPE_VERIFIED = False


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
    """Return the flat JSON body for ``POST .../calendar_events`` (UNVERIFIED)."""
    all_day = not isinstance(start, datetime) and not isinstance(end, datetime)
    if isinstance(start, datetime) != isinstance(end, datetime):
        raise ValueError("start and end must both be dates or both be datetimes")
    if end < start:
        raise ValueError("end must not be before start")
    body: dict[str, Any] = {
        "summary": summary,
        "starts_at": start.isoformat(),
        "ends_at": end.isoformat(),
        "all_day": all_day,
        "category_ids": [str(c) for c in category_ids],
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if timezone:
        body["timezone"] = timezone
    return body
