# Skylight Guard for Home Assistant

[![CI](https://github.com/cloudlabworks/skylight-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudlabworks/skylight-guard/actions/workflows/ci.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)

A Home Assistant custom integration for the [Skylight Calendar](https://www.ourskylight.com/)
frame that can **write** calendar events, with a **guard** in front of every write
and an **audit** sensor that watches what the frame is showing.

## Why this exists: the privacy problem

A Skylight frame sits in a kitchen or hallway and shows every event on it to
whoever is standing in front of it. There are no per-viewer permissions. A
surprise party, a medical appointment, or a work meeting that was only meant
for one person is on the screen for guests, kids, and visitors alike.

Once Home Assistant can write to that screen, an automation bug or a careless
template can put something private there with nobody noticing. Skylight Guard
adds guardrails:

- **Refuses private writes.** Any event whose title or description contains
  `[private]`, `🔒` or `#private` (case-insensitive, after Unicode normalization,
  zero-width characters ignored), or that is flagged private, is never written.
- **Writes only to allowlisted profiles.** You pick which of the frame's
  profiles Home Assistant may write to. **An empty allowlist denies every
  write**, so a fresh install is read-only until you opt in.
- **Audits what is already there.** `sensor.<frame>_rogue_events` counts upcoming
  events (next 14 days) that are private-marked or sit on non-allowlisted
  profiles, and fires a `skylight_guard_rogue_event` event when the count rises.

The guard cannot stop events that reach the frame from other places (the
Skylight app, synced Google or iCloud calendars). That is what the audit sensor
is for.

## Features

| Platform | What | Notes |
|---|---|---|
| `calendar` | Aggregate calendar plus one per source calendar | Aggregate supports **create** (guarded) and **delete** (guarded); source calendars support delete. |
| `sensor` | Chores, meals, meal slots, stars, task box (from upstream) | Rich attributes for dashboards. |
| `sensor` | `rogue_events` (new) | Count + offending event titles in attributes. |
| `todo` | Skylight lists, per-profile chore queues | From upstream. |
| `switch`, `number`, `image` | Sleep mode, brightness, slideshow speed, latest photo | From upstream. |

Actions:

- `skylight_guard.create_event`: guarded event creation (timed or all-day,
  profiles by name or ID, optional `private` flag which is always refused).
  Returns `{"event_id": ...}` when called with a response variable.
- `skylight_guard.upload_media`: upload a photo or short video (from upstream).

It uses its own domain, `skylight_guard`, so it can be installed next to the
upstream `skylight` integration. Entities, unique IDs, devices, and services do
not collide. Both will poll the Skylight API, so expect twice the traffic if
you run both.

## Installation

### HACS (custom repository)

1. HACS, three-dot menu, **Custom repositories**.
2. Repository `https://github.com/cloudlabworks/skylight-guard`, type **Integration**.

   [![Open your Home Assistant instance and open a repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cloudlabworks&repository=skylight-guard&category=integration)
3. Download **Skylight Guard**, then restart Home Assistant.

### Manual

Copy `custom_components/skylight_guard/` into your Home Assistant
`config/custom_components/` folder and restart.

Requires Home Assistant 2024.11 or newer.

## Sign in

Skylight uses OAuth with PKCE. There is no redirect back to Home Assistant, so
you copy a code by hand:

1. **Settings, Devices & services, Add integration, Skylight Guard.**
2. Click the sign-in link in the dialog. It opens Skylight's login in a new tab.
3. Sign in with your Skylight email and password.
4. When the page finishes loading, the address bar contains `?code=...`. Copy
   the code (or the whole URL) and paste it into the dialog.
5. **Be quick: codes expire after about 30 seconds.** If you get "code
   rejected", click the link again for a fresh one.
6. If the account has more than one frame, pick one. Repeat to add others.

Tokens are stored in the config entry and refreshed automatically. Use
**Reconfigure** or the reauth prompt to sign in again.

## Configure the guard

Open the integration, **Configure**:

| Option | Default | Meaning |
|---|---|---|
| Profiles Home Assistant may write to | none | The allowlist. Empty means **deny all writes**. |
| Default write profile | none | Used when a write names no profile, including events created from the Home Assistant calendar UI (which has no profile picker). Must be in the allowlist. |
| Show titles of private-marked events | off | When off, the audit sensor and the rogue event show `[redacted]` for private-marked titles so they do not end up in Home Assistant history. |
| Count events without a profile as rogue | off | Synced calendars often have events with no profile; turn this on to audit them too. |

What the guard refuses, in order:

1. `private: true` on the write.
2. A private marker in the title or description: `[private]`, `🔒`, `#private`
   (whole hashtag; `#privateer` is fine). Matching is case-insensitive and runs
   on NFKC-normalized text with invisible format characters removed, so
   full-width or zero-width tricks do not get around it.
3. An empty allowlist.
4. No profile (and no default write profile).
5. Any profile not in the allowlist.

Refusals raise an error in Home Assistant with the reason, so a failing
automation tells you why. Deletes are guarded by the allowlist only: private
markers never block a delete, because removing an event from a shared screen
can only reduce exposure.

Example:

```yaml
action: skylight_guard.create_event
data:
  summary: Soccer practice
  start_date_time: "2026-03-02 16:00:00"
  end_date_time: "2026-03-02 17:30:00"
  categories:
    - Kids
response_variable: created
```

## Audit sensor and event

`sensor.<frame>_rogue_events`:

- **state**: number of rogue events in the next 14 days
- **attributes**: `titles`, `events` (id, title, starts_at, reasons),
  `allowlist_configured`, `horizon_days`

Reasons are `private_flag`, `private_marker`, `category_not_allowed`, and
`no_category` (only with the uncategorized option). With an empty allowlist,
every event that has a profile counts as rogue, so configure the allowlist first.

When the count rises, Home Assistant fires `skylight_guard_rogue_event` with
`entity_id`, `count`, `previous_count`, and `titles`. The first reading after
startup sets a baseline and does not fire.

## Blueprints

| Blueprint | Import |
|---|---|
| **Rogue event alert**: notify when the audit finds new rogue events | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fcloudlabworks%2Fskylight-guard%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fskylight_guard%2Frogue_event_alert.yaml) |
| **Morning greeting**: daily all-day event with the forecast from a weather entity, written through the guarded action | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fcloudlabworks%2Fskylight-guard%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fskylight_guard%2Fmorning_greeting.yaml) |
| **Chore due reminder**: notify at a set time with chores not yet complete | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fcloudlabworks%2Fskylight-guard%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fskylight_guard%2Fchore_due_reminder.yaml) |

The notify blueprints take the notify action name as text (for example
`notify.mobile_app_my_phone`).

## Limitations

- **Unofficial API.** Skylight has no public API. This integration talks to the
  same endpoints the Skylight app uses and can break whenever Skylight changes them.
- **Impersonates the mobile client.** Like upstream, it signs in with
  Skylight's own `skylight-mobile` OAuth client ID. Skylight could block that
  at any time. Use at your own risk.
- **Event write payload is UNVERIFIED.** The create and delete endpoints
  (`POST` and `DELETE /api/frames/{frame}/calendar_events`) and the rule that
  writes take a flat JSON body come from the public
  [pyskylight](https://github.com/dknowles2/pyskylight) library and its API
  notes. The **field names** in the create body (`summary`, `starts_at`,
  `ends_at`, `all_day`, `timezone`, `category_ids`, `description`, `location`)
  and the all-day format (date strings, exclusive end) are not documented
  anywhere public. They mirror the fields Skylight returns when reading events.
  All of this lives in one function, `event_payload.build_event_payload`. Please
  open an issue if a create fails or lands without its profile.
- **Recurring events** cannot be created or deleted yet.
- **The private flag on read** (`private`, `is_private`, `visibility`) is a
  best guess; Skylight may not expose one. Markers in the title are reliable.
- The guard protects writes made through this integration only. It cannot see
  or block writes from the Skylight app or synced calendars.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest
```

`guard.py` and `event_payload.py` have no Home Assistant imports, so the tests
run without Home Assistant installed. CI also runs hassfest and HACS validation.

## Credits

Skylight Guard is derived from MIT-licensed work:

- [devinslick/skylight_hass](https://github.com/devinslick/skylight_hass) v3.0.0:
  OAuth2 PKCE flow, API client, and the calendar, todo, sensor, switch,
  number, and image platforms.
- [MegaTheLEGEND/skylight_calendar](https://github.com/MegaTheLEGEND/skylight_calendar):
  the original integration that skylight_hass was forked from.
- [dknowles2/pyskylight](https://github.com/dknowles2/pyskylight): reference for
  the calendar event write endpoints (no code included).

See [LICENSE](LICENSE) and [NOTICE](NOTICE). Skylight is a trademark of its
owner; this project is not affiliated with Skylight.
