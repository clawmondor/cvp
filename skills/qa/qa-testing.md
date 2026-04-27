# QA Testing Skill

Automated browser-based QA testing for the Contents Valuation Platform using Playwright.

## When to use

Use this skill when asked to run QA tests, verify features after a code change, or test specific areas of the application. Always confirm the dev server is running before invoking.

## Usage

```bash
# Run all suites
uv run python skills/qa/runner.py

# Run a specific suite
uv run python skills/qa/runner.py --suite auth
uv run python skills/qa/runner.py --suite rbac
uv run python skills/qa/runner.py --suite matters
uv run python skills/qa/runner.py --suite evidence
uv run python skills/qa/runner.py --suite items
uv run python skills/qa/runner.py --suite comments
uv run python skills/qa/runner.py --suite exports

# Stop on first failure
uv run python skills/qa/runner.py --fail-fast
uv run python skills/qa/runner.py --suite auth --fail-fast

# Remove all QA test data (safe to run any time)
uv run python skills/qa/cleanup.py
```

## Required .env variables

These must be set in `.env` before running QA tests:

```
QA_ADMIN_EMAIL=admin@example.com
QA_ADMIN_PASSWORD=your-admin-password
```

The admin user must exist and have `system_admin` role. These credentials are used to log in for tests that require elevated access.

## How it works

1. **Preflight** — checks `.env` exists, `QA_ADMIN_EMAIL` and `QA_ADMIN_PASSWORD` are set, reads `PORT` (default 8000), and verifies the server responds at `http://localhost:{PORT}/`.
2. **Data setup** — each suite creates test data in the database using SQLAlchemy directly (fast, no browser needed). All test records are named with a `QA_` prefix and a Unix timestamp suffix: `QA_Firm_1714000000`. This makes them easy to identify and clean up.
3. **Tests run** — Playwright drives a real browser (Chromium, headless). Each test logs in, performs actions, and asserts outcomes.
4. **Teardown** — each suite deletes all rows it created by querying for the `QA_` timestamp prefix, regardless of pass/fail.
5. **Summary** — final pass/fail count printed. Exit code 0 if all pass, 1 if any fail.

## Available suites

| Suite | What it tests |
|---|---|
| `auth` | Login, logout, wrong password, locked account, MFA, invite flow, password change, token refresh |
| `rbac` | System admin access, internal admin boundaries, external admin scoping, matter role grants, cross-org isolation, comment visibility |
| `matters` | Create, view, update status, field validation |
| `evidence` | Upload photo, delete file, 403 without access |
| `items` | Create, edit, confirm, exclude, delete, 403 without access |
| `comments` | Post internal vs shared, visibility enforcement |
| `exports` | CSV download, PDF download |

## Negative tests

Every suite includes negative tests that verify the app returns the correct error (usually 403) when a user attempts an action they are not authorized for. For example:
- External user accessing a matter without a grant → 403
- Viewer attempting to edit an item → 403
- Cross-org data isolation

## Test data cleanup

Test data is prefixed with `QA_` so it is safe to identify and delete. The `cleanup.py` script removes all rows matching the prefix pattern from:
- `users` (email starts with `qa_`)
- `groups` (name starts with `QA_`)
- `matters` (firm_name starts with `QA_`)
- `matter_access` rows for those users/matters
- `items`, `rooms` in those matters
- `evidence_files` in those matters (file records only — physical files in `data/uploads/` are not deleted)

The teardown step in each suite run already cleans up. Run `cleanup.py` to remove any leftover data from aborted runs.

## Notes

- Tests run headless by default. Set `QA_HEADFUL=true` in `.env` to watch the browser.
- Test data is scoped to the run timestamp so multiple runs can overlap safely.
- The skill does not start the server. If the server is not running, the preflight check exits with instructions.
- Playwright must be installed: `uv run playwright install chromium`
