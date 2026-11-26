"""Guarded write path shared by the calendar entity and the create_event service.

Every write to the frame goes through here, and every write runs
``guard.check_event`` first. Nothing in this module talks to the Skylight API
without a passing guard check.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import SkylightAPI, SkylightAPIError, SkylightAuthError
from .const import CONF_ALLOWED_CATEGORIES, CONF_DEFAULT_CATEGORY
from .event_payload import build_event_payload
from .guard import GuardViolation, check_event, event_category_ids

_LOGGER = logging.getLogger(__name__)


def allowlist(entry: ConfigEntry) -> list[str]:
    """Allowlisted category IDs from the entry options (empty = deny all)."""
    return [str(c) for c in entry.options.get(CONF_ALLOWED_CATEGORIES, []) or []]


def category_labels(entry_data: Mapping[str, Any]) -> dict[str, str]:
    """category_id -> label, from the sensor coordinator's categories payload."""
    coord = entry_data.get("sensor_coordinator")
    data = (getattr(coord, "data", None) or {}).get("categories") or {}
    out: dict[str, str] = {}
    for c in data.get("data", []) or []:
        if c.get("id") is None:
            continue
        out[str(c["id"])] = str((c.get("attributes") or {}).get("label") or "")
    return out


def resolve_categories(
    requested: Iterable[str] | None, labels: Mapping[str, str]
) -> list[str]:
    """Map profile names or IDs to category IDs.

    Unknown values are passed through unchanged so the guard reports them as
    not allowlisted instead of silently dropping them.
    """
    by_label = {v.casefold(): k for k, v in labels.items() if v}
    out: list[str] = []
    for raw in requested or []:
        value = str(raw).strip()
        if not value:
            continue
        cid = value if value in labels else by_label.get(value.casefold(), value)
        if cid not in out:
            out.append(cid)
    return out


def _guard_or_raise(**kwargs: Any) -> None:
    try:
        check_event(**kwargs)
    except GuardViolation as err:
        _LOGGER.info("Skylight Guard refused a write: %s", err.reason)
        raise HomeAssistantError(f"Skylight Guard refused this event: {err.reason}") from err


async def async_guarded_create(
    hass: HomeAssistant,
    entry: ConfigEntry,
    entry_data: Mapping[str, Any],
    *,
    summary: str,
    start: date | datetime,
    end: date | datetime,
    description: str | None = None,
    location: str | None = None,
    categories: Iterable[str] | None = None,
    private: bool = False,
) -> dict[str, Any]:
    """Guard-check then create an event. Returns ``{"event_id": ...}``."""
    labels = category_labels(entry_data)
    cats = resolve_categories(categories, labels)
    if not cats:
        default = entry.options.get(CONF_DEFAULT_CATEGORY)
        if default:
            cats = [str(default)]

    _guard_or_raise(
        title=summary,
        description=description,
        categories=cats,
        allowlist=allowlist(entry),
        private=private,
    )

    try:
        body = build_event_payload(
            summary=summary,
            start=start,
            end=end,
            category_ids=cats,
            description=description,
            location=location,
            timezone=getattr(hass.config, "time_zone", None),
        )
    except ValueError as err:
        raise HomeAssistantError(str(err)) from err

    api: SkylightAPI = entry_data["api"]
    try:
        resp = await api.create_calendar_event(entry_data["frame_id"], body)
    except (SkylightAPIError, SkylightAuthError) as err:
        raise HomeAssistantError(f"Skylight rejected the event: {err}") from err

    event_id = None
    if isinstance(resp, Mapping):
        data = resp.get("data")
        if isinstance(data, Mapping):
            event_id = data.get("id")
    await entry_data["calendar_coordinator"].async_request_refresh()
    return {"event_id": str(event_id) if event_id is not None else None}


def find_raw_event(entry_data: Mapping[str, Any], event_id: str) -> Mapping[str, Any] | None:
    coord = entry_data["calendar_coordinator"]
    events = ((coord.data or {}).get("events") or {}).get("data", []) or []
    for ev in events:
        if str(ev.get("id")) == str(event_id):
            return ev
    return None


async def async_guarded_delete(
    entry: ConfigEntry,
    entry_data: Mapping[str, Any],
    event_id: str,
    *,
    recurrence_id: str | None = None,
) -> None:
    """Guard-check then delete a non-recurring event.

    The guard refuses deletes of events outside the allowlist, so Home
    Assistant can only remove events on profiles it is allowed to write to.
    Private markers do not block a delete: removing a private event from a
    shared screen reduces exposure, it never adds to it.
    """
    raw = find_raw_event(entry_data, event_id)
    if raw is None:
        raise HomeAssistantError(f"Event {event_id} not found in the current window.")
    attrs = raw.get("attributes") or {}
    if recurrence_id or attrs.get("recurring") or attrs.get("rrule"):
        raise HomeAssistantError(
            "Deleting recurring Skylight events is not supported yet "
            "(the API's apply_to semantics for events are unverified)."
        )
    _guard_or_raise(
        title=None,
        description=None,
        categories=event_category_ids(raw),
        allowlist=allowlist(entry),
        private=False,
    )
    api: SkylightAPI = entry_data["api"]
    try:
        await api.delete_calendar_event(entry_data["frame_id"], str(event_id))
    except (SkylightAPIError, SkylightAuthError) as err:
        raise HomeAssistantError(f"Skylight rejected the delete: {err}") from err
    await entry_data["calendar_coordinator"].async_request_refresh()
