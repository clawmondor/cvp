# Authentication

This document describes how authentication works end-to-end: session tokens, login flows, MFA, invites, password rules, and the dev bypass.

---

## Token Model

Sessions use three HTTP-only cookies set together on every successful authentication:

| Cookie | `httponly` | `samesite` | Path | Lifetime | Purpose |
|---|---|---|---|---|---|
| `cvp_access` | yes | lax | `/` | 60 min | JWT access token. Sent with every request. |
| `cvp_refresh` | yes | strict | `/api/auth/refresh` | 7 days | Opaque refresh token. Only sent to the refresh endpoint. |
| `cvp_csrf` | **no** | lax | `/` | 60 min | CSRF token. JS reads it and sends it as `X-CSRF-Token`. |

The access token is a signed HS256 JWT. Its payload:

```json
{
  "sub": "<user_id>",
  "email": "user@example.com",
  "system_role": "internal_user",
  "group_id": "<group_uuid>",
  "group_kind": "internal",
  "exp": <unix_timestamp>
}
```

No database hit is required to validate the access token — it is verified against `JWT_SECRET` in memory. The `CurrentUser` object is built from the JWT payload and injected into route handlers via `Depends(require_active_user)`.

---

## CSRF Protection

All mutating requests (`POST`, `PATCH`, `PUT`, `DELETE`) made with cookie-based auth require the `X-CSRF-Token` header to match the `cvp_csrf` cookie value. This is the double-submit cookie pattern.

Requests authenticated via the `Authorization: Bearer <token>` header bypass CSRF validation (API clients).

HTMX sends the CSRF header automatically via an `hx-headers` attribute set on `<body>` by an inline `<script>` in the admin base template and on the main dashboard. If a mutating HTMX request fails with 403, check that the CSRF script ran before HTMX loaded.

---

## Login Flow

```
POST /api/auth/login  (email + password + optional ?next)
  │
  ├─ email/password wrong or user inactive → 401, back to login.html
  │
  ├─ user.mfa_enabled == True
  │    └─ issue 5-minute MFA JWT → render login_mfa.html
  │         └─ POST /api/auth/mfa/verify (mfa_token + code)
  │               ├─ expired or invalid token → 401, back to login.html
  │               ├─ wrong TOTP code (< 3 attempts) → 401, back to login_mfa.html
  │               ├─ wrong TOTP code (3rd attempt) → 401, back to login.html ("too many attempts")
  │               └─ code valid → create full session → redirect to ?next or /dashboard
  │
  └─ MFA not enabled → create full session → redirect to ?next or /dashboard
```

"Create full session" means: issue access JWT, create a `RefreshToken` row (hashed), set three cookies, update `user.last_login_at`.

Failed login attempts (wrong password, inactive account, MFA failures) are written to the audit log as `auth.login_failed` or `auth.mfa_failed`.

---

## Token Refresh

The refresh endpoint (`POST /api/auth/refresh`) is called automatically when the access token expires. It:

1. Reads the `cvp_refresh` cookie, hashes it, looks up the `RefreshToken` row.
2. Checks the row is not revoked and not expired.
3. Checks the user is still active.
4. Revokes the old refresh token and issues a new one (rotation).
5. Issues a new access JWT and resets all three cookies.

If anything is invalid, it clears cookies and redirects to `/login`.

---

## Logout

`POST /api/auth/logout` revokes the current refresh token in the database (sets `revoked_at`) and deletes all three cookies. The user is redirected to `/`.

---

## Invite-Based Registration

There is no self-registration. New users are created by an admin via an admin panel. The flow:

1. Admin creates the user (sets email, system role, group). The backend generates a random invite code, stores its SHA-256 hash on the `users` row, and sets `invite_expires_at = now + 7 days`.
2. The admin copies the registration URL shown: `https://<host>/register/<raw_code>`.
3. The invitee visits the URL. The backend hashes the code from the URL and looks it up — if it matches and is not expired, the registration form is shown with the email pre-filled.
4. The invitee enters a display name and password. On submit, `password_hash` is set, the invite code is cleared, and `password_changed_at` is set.
5. The invitee is redirected to `/login`. They log in normally.

Invite codes cannot be reused after registration is complete. Expired codes show an invalid-invite page.

---

## Password Rules

Passwords are validated by `validate_password_strength()` in `src/claimos/auth.py`:

- Minimum 12 characters.
- Maximum 128 characters.
- Must not appear in the top-100k breached passwords list (loaded from `src/claimos/data/pwned_passwords_top100k.txt` at startup; if the file is absent, this check is skipped).

These rules apply on registration and on the password change form in the profile page.

---

## Password Change

Authenticated users can change their own password at `/profile`:

1. Enter current password (required — cannot be skipped even if set by invite flow).
2. Enter new password twice.
3. The same strength rules apply.

On success, `password_hash` and `password_changed_at` are updated. No session invalidation occurs — existing tokens remain valid. If a session needs to be forced out after a password change, the user must log out and back in.

Invited users who have never set a password (`password_hash` is null) cannot use the password change form — they should complete registration first.

---

## Two-Factor Authentication (TOTP)

MFA is optional and per-user. Any authenticated user can enable it from `/profile`.

### Setup

1. User clicks "Set up MFA". The server generates a TOTP secret (32-char base32), encrypts it with the `MFA_ENCRYPTION_KEY` Fernet key, and returns a QR code and a manual entry code.
2. User scans the QR code in their authenticator app (Google Authenticator, Authy, 1Password, etc.).
3. User enters the 6-digit code to confirm. The server decrypts the secret and verifies the code. On success, the encrypted secret is stored on `user.mfa_secret` and `user.mfa_enabled = True`.

### Login with MFA enabled

After a successful password check, the server issues a short-lived (5-minute) "MFA verification JWT" with `purpose: mfa_verification`. This token is posted back to `/api/auth/mfa/verify` along with the 6-digit code.

- The TOTP verification allows a ±30-second clock drift window (`valid_window=1`).
- After 3 failed attempts, the MFA session is invalidated and the user must re-enter their password.
- Successful verification creates the full session (all three cookies).

### Disable

Users can disable MFA from `/profile` — this clears `mfa_secret` and sets `mfa_enabled = False`. No code confirmation is required to disable (the user is already authenticated).

### Admin MFA reset

System Admins can reset MFA for any user from `/admin/system/users/<id>`. This clears `mfa_secret` and `mfa_enabled`. The action is written to the audit log as `admin.mfa_reset`.

### Key management

`MFA_ENCRYPTION_KEY` must be a valid Fernet key (44-character base64 string). Generate one:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add to `.env`:
```
MFA_ENCRYPTION_KEY=<generated_key>
```

This key is never rotated automatically. If it is lost, all existing MFA secrets become unreadable and MFA must be reset for all users.

---

## Audit Events

The following auth events are written to the `audit_logs` table as background tasks:

| Action | Trigger |
|---|---|
| `auth.login` | Successful login (with or without MFA) |
| `auth.login_failed` | Wrong password, inactive account |
| `auth.mfa_failed` | Wrong TOTP code |
| `auth.logout` | Logout |
| `auth.token_refresh` | Refresh token rotation |
| `auth.register` | Invite redeemed, account activated |
| `admin.mfa_reset` | System admin reset a user's MFA |

All events include `ip_address` (from `X-Forwarded-For` or `request.client.host`) and `user_id` where available.

---

## Dev Mode

In development, set these in `.env`:

```
ENVIRONMENT=dev
AUTO_LOGIN_USER_ID=<user_uuid>
```

When `ENVIRONMENT=dev` and `AUTO_LOGIN_USER_ID` is set, the JWT validation middleware is bypassed entirely. The user identified by that UUID is returned as the current user for every request without cookies or tokens. The splash page also redirects straight to `/dashboard`.

**Never set `AUTO_LOGIN_USER_ID` in production.** The code checks `settings.environment == "dev"` before activating the bypass.

---

## Testing

Run the scenarios below in a local dev environment. Start the server with `uv run dev` (runs on `localhost:8000`).

For most scenarios, disable `AUTO_LOGIN_USER_ID` so the login flow is exercised. Use a separate browser or incognito window for each persona.

### Setup: Create test users

Log in as a `system_admin`. From `/admin/system/users`, create and register these accounts:

| Email | Role |
|---|---|
| `sysadmin@test.local` | `system_admin` |
| `intuser@test.local` | `internal_user` |
| `extadmin@test.local` | `external_admin` (Acme Corp external group) |
| `extuser@test.local` | `external_user` (Acme Corp external group) |
| `mfauser@test.local` | `internal_user` (for MFA tests) |

---

### Scenario 1: Normal login and logout

1. Navigate to `http://localhost:8000/login`.
2. Enter `intuser@test.local` credentials.
3. Expect: redirect to `/dashboard`. Browser DevTools → Application → Cookies shows `cvp_access`, `cvp_refresh`, `cvp_csrf`.
4. Click "Sign out".
5. Expect: redirected to `/`. Cookies cleared.
6. Navigate to `http://localhost:8000/dashboard` — expect: redirect to `/login` (401).

---

### Scenario 2: Wrong password

1. Navigate to `/login`.
2. Enter correct email, wrong password.
3. Expect: login page shows "Invalid email or password." No cookies set.
4. Check audit log in System Admin panel — expect: `auth.login_failed` event with the attempted email.

---

### Scenario 3: Deactivated account

1. Log in as `sysadmin@test.local`. Deactivate `intuser@test.local` from `/admin/system/users`.
2. Attempt to log in as `intuser@test.local`.
3. Expect: "Account is deactivated. Contact your administrator."
4. Re-activate the user and confirm login succeeds.

---

### Scenario 4: Invite flow end to end

1. Log in as `sysadmin@test.local`. Go to `/admin/system/users`.
2. Invite `newqa@test.local` as `internal_user`.
3. Copy the invite URL shown (e.g., `http://localhost:8000/register/abc123...`).
4. Open the invite URL in a new incognito window. Expect: registration form with email pre-filled.
5. Enter display name and a valid password (≥12 chars, not common).
6. Expect: redirect to `/login?message=Account+created...`.
7. Log in as `newqa@test.local` — expect: success.
8. Try to reuse the same invite URL — expect: "Invalid or expired invite" page.

---

### Scenario 5: Invite expiry

1. Create an invite for `expiredqa@test.local`.
2. In the database (`data/claimos.db`), set `invite_expires_at` to a past timestamp for that user:
   ```bash
   sqlite3 data/claimos.db "UPDATE users SET invite_expires_at='2000-01-01 00:00:00' WHERE email='expiredqa@test.local';"
   ```
3. Visit the invite URL — expect: "Invalid or expired invite" page.

---

### Scenario 6: Password strength validation

1. Open any registration invite URL.
2. Try password `short` (< 12 chars) — expect: error "Password must be at least 12 characters."
3. Try password `password123456` (common password) — expect: error "This password is too common."
4. Try password `CorrectHorseBatteryStaple2024` — expect: success.

---

### Scenario 7: Password change

1. Log in as `intuser@test.local`. Navigate to `/profile`.
2. Enter wrong current password — expect: "Current password is incorrect."
3. Enter correct current password, mismatched new passwords — expect: "New passwords do not match."
4. Enter correct current password, weak new password — expect: strength error.
5. Enter correct current password, valid matching new passwords — expect: "Password updated successfully."
6. Log out and log in with the new password — expect: success.

---

### Scenario 8: TOTP MFA setup and login

1. Log in as `mfauser@test.local`. Navigate to `/profile`.
2. Click "Set up MFA" — expect: QR code appears with manual entry code.
3. Scan the QR code with an authenticator app (or manually enter the code).
4. Enter the 6-digit code from the app — expect: "MFA is enabled" shown on profile.
5. Log out.
6. Log in as `mfauser@test.local` — expect: after password, MFA verification page appears.
7. Enter the current 6-digit code — expect: redirect to `/dashboard`.
8. Log out and log in again. Enter a **wrong** code — expect: "Invalid code. Try again."
9. Enter wrong code two more times — expect: "Too many failed MFA attempts. Please sign in again." Redirected back to login.

---

### Scenario 9: MFA clock drift

1. If you can simulate a 29-second time offset in your authenticator app, do so.
2. Log in with MFA — expect: the code still works (±30s window).

---

### Scenario 10: Admin MFA reset

1. Log in as `mfauser@test.local` with MFA enabled. Log out.
2. Log in as `sysadmin@test.local`. Go to `/admin/system/users/<mfauser_id>`.
3. Click "Reset MFA".
4. Log in as `mfauser@test.local` — expect: no MFA prompt. Login goes straight to dashboard.
5. Check audit log — expect: `admin.mfa_reset` event with the sysadmin's user ID.

---

### Scenario 11: MFA disable by user

1. Log in as `mfauser@test.local` (re-enable MFA first if it was reset).
2. Navigate to `/profile`. Click "Disable MFA".
3. Expect: page updates to show "Set up MFA" button (MFA disabled).
4. Log out and log back in — expect: no MFA prompt.

---

### Scenario 12: Token refresh

1. Log in as `intuser@test.local`.
2. In the database, set the access token expiry to the past. The easiest way is to set `JWT_ACCESS_TTL_MINUTES=0` in `.env` and restart the server, then log in.
3. After expiry, navigate to any protected page. Expect: the refresh endpoint is called automatically and access is restored without re-login.
4. In the database, also set the refresh token `expires_at` to the past. Repeat — expect: redirect to `/login`.

---

### Scenario 13: CSRF validation

1. Log in as `intuser@test.local`.
2. Using `curl` or a REST client, make a `POST` request to a mutation endpoint with the `cvp_access` cookie but **without** the `X-CSRF-Token` header:
   ```bash
   curl -X POST http://localhost:8000/api/auth/logout \
     -H "Cookie: cvp_access=<token>; cvp_csrf=<csrf>"
   ```
3. Expect: **403** (CSRF validation failed).
4. Repeat with the header added:
   ```bash
   curl -X POST http://localhost:8000/api/auth/logout \
     -H "Cookie: cvp_access=<token>; cvp_csrf=<csrf>" \
     -H "X-CSRF-Token: <csrf>"
   ```
5. Expect: 303 redirect (logout succeeds).
