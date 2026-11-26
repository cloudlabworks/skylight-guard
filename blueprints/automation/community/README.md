# Community blueprints

New uses for a Skylight frame, written by people running Skylight Guard at home.
Every file here is checked by CI the same way the core blueprints are.

## Add yours

1. Fork this repo (or click **Use this template** to start your own copy).
2. Copy [`_template.yaml`](_template.yaml) to `<your-github-name>/<short_name>.yaml`
   in this folder.
3. Fill it in. Keep it generic: every entity, profile and frame is an `!input`,
   never a hard-coded ID from your house.
4. Run the checks (see [CONTRIBUTING.md](../../../CONTRIBUTING.md)).
5. Open a pull request. Add a one-line entry to the table below in the same PR.

Rules that CI enforces:

- `name` starts with `Skylight`.
- `source_url` points at the file's own path in a GitHub repo, so the
  one-click import works from your fork as well as from upstream.
- Every declared input is used and every `!input` is declared.
- No hard-coded `entity_id` values: entities come from inputs.
- Writes to the frame use `skylight_guard.create_event`, so the guard sees them.
  Plain `calendar.create_event` is refused by the checks.

## Index

| Blueprint | Author | What it does |
|---|---|---|
| _yours here_ | | |
