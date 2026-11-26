# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Blueprint kit: "Make it yours" guide, one-click import buttons, a community
  blueprints folder with a starter template, and issue forms for new uses,
  blueprint submissions and bugs.
- Blueprints `frame_bedtime` (sleep-mode schedule or quiet-mode toggle) and
  `home_event_to_frame` (any state change becomes a guarded frame event).
- CI checks for every blueprint, including community ones: inputs declared and
  used, no hard-coded entity IDs, writes only through `skylight_guard.create_event`,
  and `source_url` matching the file path in any fork.

## [0.1.0] - 2026-11-26

### Added

- Initial release, derived from devinslick/skylight_hass v3.0.0 (MIT).
- New domain `skylight_guard` so it can run next to the upstream `skylight`
  integration (entities, unique IDs, devices, and services are separate).
- Guard layer (`guard.py`, pure Python): refuses writes with private markers
  (`[private]`, `🔒`, `#private`), private-flagged writes, and writes to
  profiles outside a configurable allowlist. Empty allowlist denies all.
- Options flow: profile allowlist, default write profile, audit settings.
- Calendar event create and delete on the calendar entity, plus the
  `skylight_guard.create_event` action, all through the guard. Payload shape
  confirmed against a real frame.
- `rogue_events` audit sensor and `skylight_guard_rogue_event` bus event.
- Blueprints: rogue event alert, morning greeting with weather, chore due
  reminder.
- Tests for the guard, the event payload builder, and blueprint structure.
- CI: ruff, pytest, hassfest, HACS validation.

### Changed (from upstream)

- Meal slot sensors match slots by label instead of hard-coded category IDs.
- `upload_media` targets a frame by `config_entry_id` instead of `frame_id`.
- Services are registered once in `async_setup`.
