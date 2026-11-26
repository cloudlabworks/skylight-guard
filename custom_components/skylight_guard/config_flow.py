"""Config + options flow.

Config flow (derived from devinslick/skylight_hass, MIT): OAuth2
authorization_code + PKCE.
  step_user          -> show the authorize URL, the user signs in and pastes
                        back the full callback URL or just the ?code=... value.
  step_pick_frame    -> if the account has more than one frame, choose one.
  step_reauth / step_reconfigure -> same as step_user.

Options flow (Skylight Guard): the write allowlist of frame profiles, the
default write profile, and audit settings.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from typing import Any
import urllib.parse as _up

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .api import (
    SkylightAPI,
    SkylightAPIError,
    SkylightAuthError,
    exchange_authorization_code,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ALLOWED_CATEGORIES,
    CONF_DEFAULT_CATEGORY,
    CONF_DEVICE_FINGERPRINT,
    CONF_FLAG_UNCATEGORIZED,
    CONF_FRAME_ID,
    CONF_FRAME_NAME,
    CONF_REFRESH_TOKEN,
    CONF_SHOW_PRIVATE_TITLES,
    DOMAIN,
    OAUTH_AUTHORIZE_URL,
    OAUTH_CLIENT_ID,
    OAUTH_REDIRECT_URI,
    OAUTH_SCOPE,
)

_LOGGER = logging.getLogger(__name__)

CONF_CODE = "code"


def _pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge) for RFC 7636 S256 PKCE."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _authorize_url(challenge: str) -> str:
    qs = _up.urlencode(
        {
            "client_id": OAUTH_CLIENT_ID,
            "response_type": "code",
            "scope": OAUTH_SCOPE,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "login",
        }
    )
    return f"{OAUTH_AUTHORIZE_URL}?{qs}"


def _extract_code(raw: str) -> str | None:
    """Accept either a raw code or the full callback URL and return the code."""
    raw = raw.strip()
    if not raw:
        return None
    if "://" in raw or raw.startswith("/"):
        try:
            qs = _up.parse_qs(_up.urlparse(raw).query)
        except ValueError:
            return None
        code = qs.get("code", [None])[0]
        return code
    # Strip a stray leading "code=" if the user pasted the fragment.
    if raw.lower().startswith("code="):
        return raw.split("=", 1)[1]
    return raw


class SkylightGuardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """OAuth authorization_code + PKCE config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._verifier: str = ""
        self._challenge: str = ""
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._device_fingerprint: str = ""
        self._frames: list[dict] = []
        self._reauth_entry: ConfigEntry | None = None

    # ── Primary user step ────────────────────────────────────────────────

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        # Generate PKCE once per flow so refresh preserves it across form errors.
        if not self._verifier:
            self._verifier, self._challenge = _pkce_pair()

        auth_url = _authorize_url(self._challenge)

        if user_input is not None:
            code = _extract_code(user_input.get(CONF_CODE, ""))
            if not code:
                errors[CONF_CODE] = "invalid_code"
            else:
                session = async_get_clientsession(self.hass)
                # New fingerprint per install so multiple HA instances don't collide.
                self._device_fingerprint = secrets.token_hex(16)
                try:
                    tokens = await exchange_authorization_code(
                        session,
                        code=code,
                        code_verifier=self._verifier,
                        device_fingerprint=self._device_fingerprint,
                    )
                except SkylightAuthError as err:
                    _LOGGER.warning("OAuth code exchange failed: %s", err)
                    errors["base"] = "invalid_auth"
                except SkylightAPIError:
                    _LOGGER.exception("Skylight OAuth token endpoint error")
                    errors["base"] = "cannot_connect"
                else:
                    self._access_token = tokens["access_token"]
                    self._refresh_token = tokens["refresh_token"]

                    if self._reauth_entry is not None:
                        return await self._finish_reauth()

                    api = SkylightAPI(
                        session=session,
                        access_token=self._access_token,
                        refresh_token=self._refresh_token,
                        device_fingerprint=self._device_fingerprint,
                    )
                    try:
                        self._frames = await api.get_frames()
                    except SkylightAPIError:
                        _LOGGER.exception("Failed to enumerate frames")
                        errors["base"] = "cannot_connect"

                    if not errors:
                        if not self._frames:
                            errors["base"] = "no_frames"
                        elif len(self._frames) == 1:
                            return await self._create_entry(self._frames[0])
                        else:
                            return await self.async_step_pick_frame()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
            description_placeholders={"auth_url": auth_url},
            errors=errors,
        )

    # ── Frame selection ─────────────────────────────────────────────────

    async def async_step_pick_frame(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        configured_ids = {e.data.get(CONF_FRAME_ID) for e in self._async_current_entries()}
        available = [f for f in self._frames if f["id"] not in configured_ids]
        if not available:
            return self.async_abort(reason="all_frames_configured")

        if user_input is not None:
            frame_id = user_input[CONF_FRAME_ID]
            frame = next((f for f in available if f["id"] == frame_id), None)
            if frame:
                return await self._create_entry(frame)

        options = {f["id"]: f["name"] for f in available}
        return self.async_show_form(
            step_id="pick_frame",
            data_schema=vol.Schema({vol.Required(CONF_FRAME_ID): vol.In(options)}),
        )

    async def _create_entry(self, frame: dict) -> FlowResult:
        await self.async_set_unique_id(f"{DOMAIN}_frame_{frame['id']}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=frame["name"],
            data={
                CONF_ACCESS_TOKEN: self._access_token,
                CONF_REFRESH_TOKEN: self._refresh_token,
                CONF_DEVICE_FINGERPRINT: self._device_fingerprint,
                CONF_FRAME_ID: frame["id"],
                CONF_FRAME_NAME: frame["name"],
            },
        )

    # ── Reauth ──────────────────────────────────────────────────────────

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_user()

    async def _finish_reauth(self) -> FlowResult:
        entry = self._reauth_entry
        assert entry is not None
        new_data = {
            **entry.data,
            CONF_ACCESS_TOKEN: self._access_token,
            CONF_REFRESH_TOKEN: self._refresh_token,
            CONF_DEVICE_FINGERPRINT: self._device_fingerprint,
        }
        self.hass.config_entries.async_update_entry(entry, data=new_data)
        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_abort(reason="reauth_successful")

    # ── Reconfigure ─────────────────────────────────────────────────────

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SkylightGuardOptionsFlow:
        return SkylightGuardOptionsFlow()


def profile_options(categories_payload: dict | None) -> list[tuple[str, str]]:
    """(category_id, label) for the frame's profiles, from the categories payload."""
    out: list[tuple[str, str]] = []
    for c in (categories_payload or {}).get("data", []) or []:
        attrs = c.get("attributes", {}) or {}
        if not attrs.get("linked_to_profile"):
            continue
        label = str(attrs.get("label") or "")
        if "@" in label:  # skip synced Google-calendar sub-categories
            continue
        if c.get("id") is not None:
            out.append((str(c["id"]), label or str(c["id"])))
    return out


class SkylightGuardOptionsFlow(config_entries.OptionsFlow):
    """Configure which profiles Home Assistant may write to."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if not entry_data:
            return self.async_abort(reason="not_loaded")
        coord = entry_data["sensor_coordinator"]
        profiles = profile_options((coord.data or {}).get("categories"))
        choices = [SelectOptionDict(value=cid, label=label) for cid, label in profiles]
        known = {cid for cid, _ in profiles}

        errors: dict[str, str] = {}
        current = self.config_entry.options
        if user_input is not None:
            allowed = [c for c in user_input.get(CONF_ALLOWED_CATEGORIES, []) if c]
            default = user_input.get(CONF_DEFAULT_CATEGORY) or ""
            if default and default not in allowed:
                errors[CONF_DEFAULT_CATEGORY] = "default_not_allowed"
            else:
                return self.async_create_entry(
                    data={
                        CONF_ALLOWED_CATEGORIES: allowed,
                        CONF_DEFAULT_CATEGORY: default,
                        CONF_SHOW_PRIVATE_TITLES: bool(
                            user_input.get(CONF_SHOW_PRIVATE_TITLES, False)
                        ),
                        CONF_FLAG_UNCATEGORIZED: bool(
                            user_input.get(CONF_FLAG_UNCATEGORIZED, False)
                        ),
                    }
                )

        default_allowed = [c for c in current.get(CONF_ALLOWED_CATEGORIES, []) if c in known]
        default_cat = current.get(CONF_DEFAULT_CATEGORY) or ""
        schema = vol.Schema(
            {
                vol.Optional(CONF_ALLOWED_CATEGORIES, default=default_allowed): SelectSelector(
                    SelectSelectorConfig(
                        options=choices,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_DEFAULT_CATEGORY,
                    description={"suggested_value": default_cat or None},
                ): SelectSelector(
                    SelectSelectorConfig(options=choices, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(
                    CONF_SHOW_PRIVATE_TITLES,
                    default=bool(current.get(CONF_SHOW_PRIVATE_TITLES, False)),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_FLAG_UNCATEGORIZED,
                    default=bool(current.get(CONF_FLAG_UNCATEGORIZED, False)),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
