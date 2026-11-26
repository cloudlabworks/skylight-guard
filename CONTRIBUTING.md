# Contributing

Thanks for helping. Keep changes small and focused.

1. Fork, branch from `main`, and open a pull request.
2. Run the checks locally:

   ```sh
   python3 -m venv .venv
   .venv/bin/pip install -r requirements-dev.txt
   .venv/bin/ruff check .
   .venv/bin/pytest
   ```

3. Any change to `guard.py` needs tests. The guard is the reason this
   project exists; refusals must stay the safe default.
4. Use [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`).
5. **No personal data** in code, tests, fixtures, logs, or issues: no real
   names, emails, frame, profile or device IDs, addresses, or tokens. Use
   placeholders like `111` or `Kids`.

If you have confirmed the Skylight calendar event payload shape against a
frame, an issue or PR describing the fields that worked is very welcome
(redact IDs first).
