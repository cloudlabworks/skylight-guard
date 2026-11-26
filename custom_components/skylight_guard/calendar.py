"""Calendar entities: one aggregate 'Calendar' + one per source calendar.

Derived from devinslick/skylight_hass (MIT). Skylight Guard adds guarded
CREATE_EVENT (aggregate entity) and DELETE_EVENT (all entities).
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from dateutil.parser import parse as parse_datetime
from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import SkylightCalendarCoordinator
from .guarded import async_guarded_create, async_guarded_delete

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coord: SkylightCalendarCoordinator = data["calendar_coordinator"]
    frame_id: str = data["frame_id"]
    frame_name: str = data["frame_name"]

    entities: list[CalendarEntity] = [
        SkylightAggregateCalendar(coord, entry, frame_id, frame_name),
    ]

    seen: set[str] = set()

    def _current_sources() -> list[dict]:
        d = coord.data or {}
        return d.get("source_calendars", []) or []

    for sc in _current_sources():
        sid = sc["id"]
        entities.append(
            SkylightSourceCalendar(coord, entry, frame_id, frame_name, sid, sc.get("name") or sid)
        )
        seen.add(sid)

    async_add_entities(entities)

    @callback
    def _handle_update() -> None:
        new_entities: list[CalendarEntity] = []
        for sc in _current_sources():
            sid = sc["id"]
            if sid in seen:
                continue
            new_entities.append(
                SkylightSourceCalendar(
                    coord, entry, frame_id, frame_name, sid, sc.get("name") or sid
                )
            )
            seen.add(sid)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coord.async_add_listener(_handle_update))


def _parse_events(raw_events: dict, source_id: str | None = None) -> list[CalendarEvent]:
    """Parse the Skylight event feed into CalendarEvents, optionally per source."""
    events: list[CalendarEvent] = []
    for ev in raw_events.get("data", []):
        attrs = ev.get("attributes", {})
        if source_id is not None:
            rels = ev.get("relationships", {}) or {}
            sc_rel = rels.get("source_calendar", {}) or {}
            sc_data = sc_rel.get("data") or {}
            ev_source = str(sc_data.get("id") or attrs.get("source_calendar_id") or "")
            if ev_source and ev_source != str(source_id):
                continue
            if not ev_source:
                continue
        starts = attrs.get("starts_at")
        ends = attrs.get("ends_at")
        if not starts or not ends:
            continue
        try:
            start_dt = parse_datetime(starts)
            end_dt = parse_datetime(ends)
        except (ValueError, TypeError):
            continue
        events.append(
            CalendarEvent(
                start=start_dt,
                end=end_dt,
                summary=attrs.get("summary") or "Skylight Event",
                description=attrs.get("description") or "",
                location=attrs.get("location") or "",
                uid=str(ev.get("id")) if ev.get("id") is not None else None,
            )
        )
    return events


class _SkylightCalendarBase(CoordinatorEntity[SkylightCalendarCoordinator], CalendarEntity):
    _attr_has_entity_name = True
    _attr_supported_features = CalendarEntityFeature.DELETE_EVENT

    def __init__(
        self,
        coordinator: SkylightCalendarCoordinator,
        entry: ConfigEntry,
        frame_id: str,
        frame_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._frame_id = frame_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, frame_id)},
            name=frame_name,
            manufacturer="Skylight",
            model="Calendar Frame",
        )

    def _entry_data(self) -> dict[str, Any]:
        return self.hass.data[DOMAIN][self._entry.entry_id]

    def _source_filter(self) -> str | None:
        return None

    def _all_events(self) -> list[CalendarEvent]:
        raw = (self.coordinator.data or {}).get("events", {}) or {}
        return _parse_events(raw, self._source_filter())

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        events = self._all_events()
        for ev in events:
            start = ev.start if isinstance(ev.start, datetime) else None
            end = ev.end if isinstance(ev.end, datetime) else None
            if start and end and start <= now <= end:
                return ev
        upcoming = [e for e in events if isinstance(e.start, datetime) and e.start >= now]
        upcoming.sort(key=lambda e: e.start)
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        result = []
        for ev in self._all_events():
            ev_start = ev.start if isinstance(ev.start, datetime) else None
            ev_end = ev.end if isinstance(ev.end, datetime) else None
            if not ev_start or not ev_end:
                continue
            if ev_end < start_date or ev_start > end_date:
                continue
            result.append(ev)
        return result

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        await async_guarded_delete(
            self._entry, self._entry_data(), uid, recurrence_id=recurrence_id
        )


class SkylightAggregateCalendar(_SkylightCalendarBase):
    """Merged view of every source calendar; the only entity that creates events."""

    _attr_name = "Calendar"
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
    )

    def __init__(self, coordinator, entry, frame_id, frame_name):
        super().__init__(coordinator, entry, frame_id, frame_name)
        self._attr_unique_id = f"{DOMAIN}_{frame_id}_calendar"

    async def async_create_event(self, **kwargs: Any) -> None:
        """Create an event through the guard.

        Home Assistant's calendar UI has no profile picker, so events created
        here are assigned to the default write profile from the options. With
        no default configured the guard refuses the write.
        """
        if kwargs.get("rrule"):
            raise HomeAssistantError("Recurring events are not supported by Skylight Guard yet.")
        await async_guarded_create(
            self.hass,
            self._entry,
            self._entry_data(),
            summary=kwargs.get("summary") or "",
            start=kwargs["dtstart"],
            end=kwargs["dtend"],
            description=kwargs.get("description"),
            location=kwargs.get("location"),
            categories=None,
            private=False,
        )


class SkylightSourceCalendar(_SkylightCalendarBase):
    """Per-source-calendar entity (one per connected calendar)."""

    def __init__(self, coordinator, entry, frame_id, frame_name, source_id: str, source_name: str):
        super().__init__(coordinator, entry, frame_id, frame_name)
        self._source_id = str(source_id)
        self._attr_name = source_name
        self._attr_unique_id = f"{DOMAIN}_{frame_id}_calendar_source_{source_id}"

    def _source_filter(self) -> str | None:
        return self._source_id
