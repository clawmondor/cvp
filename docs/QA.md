# QA Testing

Automated browser-based QA testing for the Contents Valuation Platform. Tests run against the local development server using Playwright to drive a real browser.

---

## Prerequisites

### 1. Install Playwright

```bash
uv run playwright install chromium
```

### 2. Configure QA credentials

Add these to your `.env` file:

```
QA_ADMIN_EMAIL=admin@example.com
QA_ADMIN_PASSWORD=your-admin-password
```

The admin user must already exist with `system_admin` role. If you haven't set one up yet, follow step 6 of the [local development setup](../README.md#6-create-the-initial-system-admin-account) in the README.

### 3. Start the dev server

```bash
uv run dev
```

The runner checks that the server is reachable before starting. If it's not running, you'll get instructions to start it.

---

## Running tests

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

# Combine: targeted suite, stop on first failure
uv run python skills/qa/runner.py --suite auth --fail-fast

# Watch the browser (non-headless)
QA_HEADFUL=true uv run python skills/qa/runner.py --suite auth

# List available suites
uv run python skills/qa/runner.py --list
```

---

## Test suites

| Suite | What it covers |
|---|---|
| `auth` | Login/logout, wrong password, deactivated account, auth cookies, profile page, password change validation, admin panel access control |
| `rbac` | System admin unrestricted, internal admin boundaries, internal user blocked from admin panels, external user requires explicit matter grant, viewer cannot edit items, cross-org isolation, internal users implicit matter access |
| `matters` | New matter form, create via POST, detail page, dashboard listing, status update |
| `evidence` | Upload photo, file appears on matter page, unauthenticated upload rejected, external user without grant rejected, delete file |
| `items` | Create item, item appears on matter page, edit via PATCH, confirm, exclude, viewer cannot edit (403), delete |
| `comments` | Post internal comment, post shared comment, internal user sees both, external viewer sees only shared, external user cannot create internal-visibility comments |
| `exports` | CSV download with correct Xactimate columns, PDF download, external user without grant cannot export, report preview renders |

---

## Test data convention

All test data created during a run is prefixed with `QA_` and includes a Unix timestamp suffix from when the run started:

- Users: `qa_intuser_1714000000@qa.local`
- Groups: `QA_Group_1714000000_A`
- Matters: `QA_Firm_1714000000_A`

This makes test data easy to identify and clean up. Each suite teardown deletes the data it created. If a run is aborted mid-way, leftover data can be removed with the cleanup command.

---

## Cleaning up test data

```bash
# Remove all QA_ prefixed test data
uv run python skills/qa/cleanup.py

# Preview what would be deleted (no changes)
uv run python skills/qa/cleanup.py --dry-run
```

The cleanup script removes users, groups, matters, matter access grants, items, rooms, and evidence file records. Physical files in `data/uploads/` are not removed (they are small test PNGs and harmless).

---

## Negative tests

Each suite includes negative tests that verify the app rejects unauthorized requests:

- **auth**: deactivated account rejected, admin panel blocked for `internal_user`
- **rbac**: external user blocked from ungranted matter, viewer cannot edit items (PATCH → 403), cross-org user blocked
- **evidence**: unauthenticated upload rejected, external user without grant rejected
- **items**: viewer cannot PATCH item (403)
- **exports**: external user without grant cannot download CSV

---

## Troubleshooting

**`ERROR: Cannot connect to http://localhost:8000`**
The dev server is not running. Start it with `uv run dev`.

**`ERROR: Required QA environment variables are not set`**
Add `QA_ADMIN_EMAIL` and `QA_ADMIN_PASSWORD` to your `.env` file.

**Tests fail with "browser not found"**
Run `uv run playwright install chromium`.

**Tests fail intermittently**
Use `QA_HEADFUL=true` to watch the browser and diagnose timing issues. Most failures are due to the page not being ready — if you see this consistently, the app may have a performance issue.

**Test data left over after aborted run**
Run `uv run python skills/qa/cleanup.py` to remove it.
