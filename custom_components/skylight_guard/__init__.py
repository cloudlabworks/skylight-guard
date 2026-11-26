"""Skylight Guard: a guarded Skylight Calendar integration for Home Assistant.

Derived from devinslick/skylight_hass (MIT), itself a fork of
MegaTheLEGEND/skylight_calendar. Uses its own domain (``skylight_guard``) so
it can be installed next to the upstream ``skylight`` integration.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import mimetypes
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import SkylightAPI, SkylightAPIError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_FINGERPRINT,
    CONF_FRAME_ID,
    CONF_FRAME_NAME,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    PLATFORM_CALENDAR,
    PLATFORM_IMAGE,
    PLATFORM_NUMBER,
    PLATFORM_SENSOR,
    PLATFORM_SWITCH,
    PLATFORM_TODO,
    SERVICE_CREATE_EVENT,
    SERVICE_UPLOAD_MEDIA,
)
from .coordinator import (
    SkylightCalendarCoordinator,
    SkylightFrameCoordinator,
    SkylightListsCoordinator,
    SkylightPhotosCoordinator,
    SkylightSensorCoordinator,
)
from .guarded import async_guarded_create

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [
    PLATFORM_CALENDAR,
    PLATFORM_TODO,
    PLATFORM_SENSOR,
    PLATFORM_IMAGE,
    PLATFORM_SWITCH,
    PLATFORM_NUMBER,
]

ATTR_CONFIG_ENTRY_ID = "config_entry_id"

_ALLOWED_EXTS = {
    # images
    "jpg", "jpeg", "png", "gif", "heic", "heif", "webp",
    # videos (Skylight app accepts short clips)
    "mp4", "mov", "m4v",
}

UPLOAD_MEDIA_SCHEMA = vol.Schema(
    {
        vol.Required("file_path"): vol.All(str, vol.Length(min=1)),
        vol.Optional("caption", default=""): str,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

CREATE_EVENT_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
            vol.Required("summary"): vol.All(cv.string, vol.Length(min=1)),
            vol.Optional("description"): cv.string,
            vol.Optional("location"): cv.string,
            vol.Optional("start_date_time"): cv.datetime,
            vol.Optional("end_date_time"): cv.datetime,
            vol.Optional("start_date"): cv.date,
            vol.Optional("end_date"): cv.date,
            vol.Optional("categories", default=[]): vol.All(
                cv.ensure_list, [cv.string]
            ),
            vol.Optional("private", default=False): cv.boolean,
        }
    ),
    cv.has_at_least_one_key("start_date_time", "start_date"),
)


def _pick_entry(hass: HomeAssistant, entry_id: str | None) -> tuple[ConfigEntry, dict]:
    loaded = hass.data.get(DOMAIN, {})
    if not loaded:
        raise HomeAssistantError("No Skylight Guard config entries are loaded.")
    if entry_id:
        if entry_id not in loaded:
            raise HomeAssistantError(
                f"Config entry {entry_id} is not a loaded Skylight Guard frame."
            )
        key = entry_id
    elif len(loaded) == 1:
        key = next(iter(loaded))
    else:
        raise HomeAssistantError(
            "Multiple Skylight frames configured; pass config_entry_id to choose one."
        )
    entry = hass.config_entries.async_get_entry(key)
    if entry is None:
        raise HomeAssistantError(f"Config entry {key} not found.")
    return entry, loaded[key]


def _event_window(data: dict[str, Any]) -> tuple[date | datetime, date | datetime]:
    if "start_date_time" in data:
        start = data["start_date_time"]
        if start.tzinfo is None:
            start = start.replace(tzinfo=dt_util.get_default_time_zone())
        end = data.get("end_date_time") or start + timedelta(hours=1)
        if end.tzinfo is None:
            end = end.replace(tzinfo=dt_util.get_default_time_zone())
        return start, end
    start_d: date = data["start_date"]
    # Home Assistant convention: all-day end date is exclusive.
    end_d: date = data.get("end_date") or start_d + timedelta(days=1)
    return start_d, end_d


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register domain services once."""

    async def _handle_create_event(call: ServiceCall) -> ServiceResponse:
        entry, entry_data = _pick_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        start, end = _event_window(dict(call.data))
        return await async_guarded_create(
            hass,
            entry,
            entry_data,
            summary=call.data["summary"],
            start=start,
            end=end,
            description=call.data.get("description"),
            location=call.data.get("location"),
            categories=call.data.get("categories") or [],
            private=call.data.get("private", False),
        )

    async def _handle_upload_media(call: ServiceCall) -> None:
        _entry, entry_data = _pick_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        api: SkylightAPI = entry_data["api"]
        frame_id: str = entry_data["frame_id"]
        caption = call.data.get("caption", "") or ""

        path = Path(call.data["file_path"]).expanduser()
        if not hass.config.is_allowed_path(str(path)):
            raise HomeAssistantError(
                f"{path} is not under an allowlist_external_dirs entry. "
                "Add its parent to `homeassistant.allowlist_external_dirs` in "
                "configuration.yaml, or drop the file into /config."
            )
        if not await hass.async_add_executor_job(path.is_file):
            raise HomeAssistantError(f"File not found: {path}")

        ext = path.suffix.lstrip(".").lower() or "jpg"
        if ext not in _ALLOWED_EXTS:
            raise HomeAssistantError(
                f"Extension .{ext} not supported. Allowed: "
                + ", ".join(sorted(_ALLOWED_EXTS))
            )
        content_type = mimetypes.guess_type(str(path))[0] or f"image/{ext}"
        file_data = await hass.async_add_executor_job(path.read_bytes)
        try:
            await api.upload_media(
                frame_ids=[frame_id],
                file_data=file_data,
                ext=ext,
                content_type=content_type,
                caption=caption,
            )
        except SkylightAPIError as err:
            raise HomeAssistantError(f"Skylight upload failed: {err}") from err
        photos_coord = entry_data.get("photos_coordinator")
        if photos_coord is not None:
            await photos_coord.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_EVENT,
        _handle_create_event,
        schema=CREATE_EVENT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPLOAD_MEDIA, _handle_upload_media, schema=UPLOAD_MEDIA_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Skylight frame from a config entry."""
    session = async_get_clientsession(hass)

    access_token = entry.data.get(CONF_ACCESS_TOKEN)
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)
    device_fp = entry.data.get(CONF_DEVICE_FINGERPRINT, "")
    frame_id = entry.data.get(CONF_FRAME_ID)
    frame_name = entry.data.get(CONF_FRAME_NAME) or "Skylight Frame"

    if not access_token or not refresh_token or not frame_id:
        _LOGGER.error(
            "Skylight Guard config entry incomplete (missing tokens or frame); "
            "remove and re-add the integration"
        )
        return False

    async def _persist_tokens(new_access: str, new_refresh: str, new_fp: str | None) -> None:
        new_data = {
            **entry.data,
            CONF_ACCESS_TOKEN: new_access,
            CONF_REFRESH_TOKEN: new_refresh,
        }
        if new_fp:
            new_data[CONF_DEVICE_FINGERPRINT] = new_fp
        hass.config_entries.async_update_entry(entry, data=new_data)

    api = SkylightAPI(
        session=session,
        access_token=access_token,
        refresh_token=refresh_token,
        device_fingerprint=device_fp,
        token_update_cb=_persist_tokens,
    )

    calendar_coord = SkylightCalendarCoordinator(hass, api, frame_id)
    lists_coord = SkylightListsCoordinator(hass, api, frame_id)
    sensor_coord = SkylightSensorCoordinator(hass, api, frame_id)
    frame_coord = SkylightFrameCoordinator(hass, api, frame_id)
    photos_coord = SkylightPhotosCoordinator(hass, api, frame_id)

    await calendar_coord.async_config_entry_first_refresh()
    await lists_coord.async_config_entry_first_refresh()
    await sensor_coord.async_config_entry_first_refresh()
    await frame_coord.async_config_entry_first_refresh()
    # Photos are optional; do not fail entry setup if the feed errors.
    try:
        await photos_coord.async_config_entry_first_refresh()
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Initial photos refresh failed; continuing without photos")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "frame_id": frame_id,
        "frame_name": frame_name,
        "calendar_coordinator": calendar_coord,
        "lists_coordinator": lists_coord,
        "sensor_coordinator": sensor_coord,
        "frame_coordinator": frame_coord,
        "photos_coordinator": photos_coord,
    }

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, frame_id)},
        manufacturer="Skylight",
        name=frame_name,
        model="Calendar Frame",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Re-run the audit when options change.

    The guard reads ``entry.options`` on every write, so no reload is needed.
    This listener also fires on token refreshes (entry data updates), which
    is why it only requests a refresh instead of reloading the entry.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data:
        await entry_data["calendar_coordinator"].async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
