# Auth & RBAC Design Spec

**Date:** 2026-04-25
**Status:** Draft
**Scope:** Authentication, role-based access control, admin panels, comments, audit logging, and security hardening for production deployment

---

## 1. Overview

This spec adds multi-user authentication and role-based access control to the CVP application, preparing it for production deployment on the public internet. The system supports five user roles across internal and external organizations, with per-user per-matter permission grants, scoped comments, full audit logging, and environment-aware security hardening.

### Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Auth method | Invite code + password | No cloud email service needed; admin-controlled access |
| Org structure | One Internal group, multiple External groups | External groups are self-contained tenants (firms, PAs, etc.) |
| Matter ownership | Separate per group, explicit sharing | Each group owns its matters; sharing bridges groups |
| Sharing direction | Bidirectional | Either side can initiate sharing |
| Per-matter permissions | Per-user named roles (Viewer/Editor/Contributor/Manager) | Granular without checkbox overload |
| Comments | Scoped visibility (internal/shared) | Internal team needs private discussion |
| Audit logging | Full trail (auth + mutations + views) | Attorney work product requires access accountability |
| Token mechanism | JWT | Stateless verification, future API support |
| JWT transport | Cookie (web UI) + Authorization header (API) | HTMX-compatible + future API clients |
| Password policy | 12+ chars, breached-password check, optional TOTP MFA | Production-grade without forcing MFA |
| Environments | Tiered (dev/preview/production) | Auto-login in dev, full hardening in prod |
| Crops endpoint | Remains public | Google Lens requires access; UUIDs provide practical obscurity |
| Admin panels | Three separate URI paths, cascading access | Clean separation of concerns |
| External group creation | System or Internal Admins | Controlled onboarding |
| Tenant isolation | Full | External groups have zero awareness of each other |
| CSRF protection | Double-submit cookie | Stateless, pairs with JWT cookies |
| Architecture | FastAPI dependency injection guards | Idiomatic, composable, testable, hard to forget |

---

## 2. System Roles

| Role | Description |
|---|---|
| **System Admin** | Full access to all matters, pages, APIs, files, evidence, rooms. Manages Internal and External Admins and Users. |
| **Internal Admin** | Confirms items. Manages Internal and External Users' access to specific matters. |
| **Internal User** | Granted access to specific matters. Can upload evidence, adjust crops, edit items. Cannot confirm items. |
| **External Admin** | Confirms items, manages rooms, manages their own group's External Users. |
| **External User** | Can view evidence and edit items on granted matters. Can make comments. Cannot see resources outside granted matters. |

---

## 3. Matter Roles (Per-User, Per-Matter)

| Matter Role | View | Comment | Edit Items | Upload/Crop | Confirm Items | Manage Rooms | Export | Manage Access |
|---|---|---|---|---|---|---|---|---|
| **Viewer** | yes | yes | no | no | no | no | no | no |
| **Editor** | yes | yes | yes | no | no | no | no | no |
| **Contributor** | yes | yes | yes | yes | no | no | no | no |
| **Manager** | yes | yes | yes | yes | yes | yes | yes | yes |

Role hierarchy: `viewer < editor < contributor < manager`

**Default matter role by system role:**
- System Admins: implicit Manager on all matters (no `matter_access` row needed)
- Internal/External Admins: Manager on their group's owned matters
- Internal/External Users: must have an explicit `matter_access` grant

---

## 4. Data Model

### New Tables

#### `groups`

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | PK |
| name | str | e.g., "Contents Valuation LLC", "Smith & Associates" |
| kind | enum | `internal`, `external` |
| is_active | bool | default true, soft-disable entire groups |
| created_at | datetime | UTC |
| updated_at | datetime | UTC |

#### `users`

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | PK |
| email | str | unique, indexed, normalized to lowercase |
| display_name | str | |
| password_hash | str | bcrypt, cost factor 12 |
| system_role | enum | `system_admin`, `internal_admin`, `internal_user`, `external_admin`, `external_user` |
| group_id | str (FK -> groups.id) | nullable for system_admins only |
| is_active | bool | default true |
| mfa_secret | str | nullable, encrypted at rest (Fernet) |
| mfa_enabled | bool | default false |
| invite_code | str | nullable, SHA-256 hashed, cleared after redemption |
| invite_expires_at | datetime | nullable |
| password_changed_at | datetime | nullable |
| last_login_at | datetime | nullable |
| created_at | datetime | UTC |
| updated_at | datetime | UTC |

#### `refresh_tokens`

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | PK |
| user_id | str (FK -> users.id) | |
| token_hash | str | SHA-256 hash of raw refresh token |
| expires_at | datetime | |
| revoked_at | datetime | nullable |
| created_at | datetime | |

#### `matter_access`

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | PK |
| user_id | str (FK -> users.id) | |
| matter_id | str (FK -> matters.id) | |
| role | enum | `viewer`, `editor`, `contributor`, `manager` |
| granted_by_id | str (FK -> users.id) | |
| created_at | datetime | |
| updated_at | datetime | |
| **unique constraint** | | (user_id, matter_id) |

#### `comments`

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | PK |
| item_id | str (FK -> items.id) | |
| user_id | str (FK -> users.id) | |
| body | text | |
| visibility | enum | `internal`, `shared` |
| created_at | datetime | |
| updated_at | datetime | |

#### `audit_logs`

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | PK |
| user_id | str (FK -> users.id) | nullable (for failed login attempts) |
| action | str | e.g., `auth.login`, `item.update`, `matter.view` |
| resource_type | str | e.g., `item`, `matter`, `evidence_file` |
| resource_id | str | nullable |
| matter_id | str | nullable, denormalized for fast queries |
| detail | JSON | action-specific payload |
| ip_address | str | |
| created_at | datetime | indexed |

Indexes on `audit_logs`: `created_at`, `user_id`, `matter_id`, `action`.

#### `rate_limits` (production/preview only; in-memory dict in dev)

| Column | Type | Notes |
|---|---|---|
| id | str (UUID) | PK |
| key | str | e.g., `login:user@example.com`, `register:192.168.1.1` |
| attempts | int | |
| window_start | datetime | |
| locked_until | datetime | nullable |

### Modifications to Existing Tables

#### `matters` -- add columns:

| Column | Type | Notes |
|---|---|---|
| owner_group_id | str (FK -> groups.id) | the group that created/owns this matter |
| created_by_id | str (FK -> users.id) | |

#### `items` -- add columns:

| Column | Type | Notes |
|---|---|---|
| confirmed_by_id | str (FK -> users.id) | nullable |
| confirmed_at | datetime | nullable |

### Unchanged Tables

`categories`, `evidence_files`, `item_crops`, `vision_runs`, `serp_searches` -- these inherit access through their parent matter relationship.

---

## 5. Auth Infrastructure

### JWT Token Design

**Access token payload:**
```json
{
  "sub": "user-uuid",
  "email": "user@example.com",
  "system_role": "internal_admin",
  "group_id": "group-uuid",
  "group_kind": "internal",
  "iat": 1714000000,
  "exp": 1714003600
}
```

- Access token TTL: 1 hour
- Refresh token TTL: 7 days
- Signing algorithm: HS256 with `JWT_SECRET` config value
- Access tokens are stateless (validated by signature only)
- Refresh tokens are server-side (stored hashed in `refresh_tokens` table, allows revocation)

### Token Transport

**Web UI:**
- Access token: HTTP-only, Secure, SameSite=Lax cookie named `cvp_access`
- Refresh token: HTTP-only, Secure, SameSite=Strict cookie named `cvp_refresh` (Path scoped to `/api/auth/refresh`)
- CSRF: `cvp_csrf` cookie (readable by JS, NOT HTTP-only) -- value sent as `X-CSRF-Token` header by HTMX

**API clients:**
- `Authorization: Bearer <access_token>` header
- Refresh via `POST /api/auth/refresh` with refresh token in request body

### Token Refresh Flow

1. Request arrives with expired access token
2. Web UI: middleware checks `cvp_refresh` cookie -> refreshes transparently -> sets new `cvp_access` cookie -> retries original request
3. API: returns 401 -> client calls `POST /api/auth/refresh` explicitly

### Auth Endpoints

| Method | Path | Purpose | Auth Required |
|---|---|---|---|
| GET | `/` | Splash/landing page | No |
| GET | `/login` | Login page | No |
| POST | `/api/auth/login` | Validate credentials, return tokens | No |
| POST | `/api/auth/mfa/verify` | Validate TOTP code after password | Partial |
| POST | `/api/auth/refresh` | Refresh access token | Refresh token only |
| POST | `/api/auth/logout` | Revoke refresh token, clear cookies | Yes |
| GET | `/register/{invite_code}` | Invite redemption page | No |
| POST | `/api/auth/register` | Redeem invite, set password | No (invite code validates) |

### Password Security

- Hashing: bcrypt with cost factor 12
- Minimum length: 12 characters, maximum 128 characters
- Breached-password check: local top-100k list from Have I Been Pwned (no external API call)
- Rate limiting: 5 failed login attempts per email per 15-minute window -> 15-minute lockout

### TOTP MFA

1. User enables MFA in profile -> server generates secret -> displays QR code
2. User scans with authenticator app -> enters 6-digit code to confirm
3. Server stores encrypted `mfa_secret`, sets `mfa_enabled = true`
4. Subsequent logins: password validates -> partial auth state -> TOTP code -> full session
5. Recovery: System Admin can disable MFA for a user via admin panel
6. MFA is optional -- not enforced by default for any role

### CSRF Protection

Double-submit cookie pattern:
1. On login, server sets `cvp_csrf` cookie (NOT HTTP-only, JS-readable)
2. HTMX configured globally to send `X-CSRF-Token` header with the cookie value on all mutating requests
3. Server validates: `cvp_csrf` cookie value == `X-CSRF-Token` header value
4. Skipped when auth comes from `Authorization` header (API clients)
5. Integrated into `require_active_user` dependency -- automatic, no per-route opt-in

---

## 6. Dependency Injection Guard System

### Dependency Chain

```
get_current_user (extract + validate JWT from cookie or header)
    |-- require_active_user (check is_active, not locked out; validate CSRF for cookie auth)
    |   |-- require_system_role(role) (check system_role >= required)
    |   |   +-- require_system_admin()
    |   |-- require_group_member(group_id) (check user belongs to group)
    |   |   +-- require_group_admin(group_id)
    |   +-- require_matter_access(matter_id)
    |       |-- require_matter_role(role) (check matter_access.role >= required)
    |       +-- require_matter_owner() (check matter.owner_group_id == user.group_id)
    +-- optional_user (returns None for unauthenticated -- for public endpoints)
```

### Core Dependencies

**`get_current_user(request)`:**
1. Check `Authorization: Bearer` header first, then `cvp_access` cookie
2. Decode JWT, validate signature + expiry
3. If expired and cookie-based: attempt transparent refresh
4. Return `CurrentUser` Pydantic model (lightweight, no DB hit)

```python
class CurrentUser(BaseModel):
    id: str
    email: str
    system_role: SystemRole
    group_id: str | None
    group_kind: GroupKind | None
```

**`require_matter_role(minimum_role)`:**
1. Depends on `require_active_user`
2. Extracts `matter_id` from path params
3. System Admins: always pass (implicit Manager)
4. Group-owned matters: if user's group owns the matter, Internal/External Admins get implicit Manager
5. Shared matters: look up `matter_access` row -> compare role against minimum
6. Raises 403 with generic message (no information leakage)

### Endpoint Guard Mapping

| Router | Endpoints | Guard |
|---|---|---|
| matters | list all | `require_active_user` (filtered by access in query) |
| matters | create | `require_active_user` (creates for user's group) |
| matters | view/preview | `require_matter_role("viewer")` |
| matters | update/status | `require_matter_role("manager")` |
| evidence | upload | `require_matter_role("contributor")` |
| evidence | delete | `require_matter_role("manager")` |
| evidence | serve file | `require_matter_role("viewer")` |
| rooms | create/rename/delete | `require_matter_role("manager")` |
| items | create | `require_matter_role("contributor")` |
| items | edit/update | `require_matter_role("editor")` |
| items | confirm/toggle | `require_matter_role("manager")` |
| items | delete | `require_matter_role("manager")` |
| crops | adjust/recrop | `require_matter_role("contributor")` |
| crops | serve image | `optional_user` (public) |
| serp | search/apply | `require_matter_role("editor")` |
| vision | scan/poll | `require_matter_role("contributor")` |
| exports | generate/download | `require_matter_role("manager")` |
| comments | create/edit | `require_matter_role("viewer")` + visibility rules |
| comments | view internal | `require_internal_group_member()` |
| admin | system panel | `require_system_admin()` |
| admin | internal panel | `require_system_role("internal_admin")` |
| admin | external panel | `require_group_admin()` |

### Data Filtering

- Matter listings: only matters where user has `matter_access` OR user's group owns the matter. System Admins see all.
- User listings: External users see only their own group. Internal users see Internal users + External users on shared matters. System Admins see all.
- Comments: filtered by visibility -- External users never see `internal` comments.
- Audit logs: System Admins see all. Group admins see logs for their group's matters.

---

## 7. Admin Panels

### System Admin Panel (`/admin/system/`)

**Access:** System Admins only

| Path | Purpose |
|---|---|
| `/admin/system/` | Dashboard -- user count, group count, matter count, recent audit events |
| `/admin/system/users` | All users list -- search, filter by role/group/active, create invites |
| `/admin/system/users/{id}` | User detail -- edit role, deactivate, reset MFA, view login history |
| `/admin/system/groups` | All groups list -- create new, activate/deactivate |
| `/admin/system/groups/{id}` | Group detail -- edit name, view members, view group's matters |
| `/admin/system/matters` | All matters list -- search, filter, view access grants |
| `/admin/system/audit` | Audit log viewer -- filter by user, action, resource, date range; CSV export |

### Internal Admin Panel (`/admin/internal/`)

**Access:** Internal Admins + System Admins (cascading)

| Path | Purpose |
|---|---|
| `/admin/internal/` | Dashboard -- Internal team overview, assigned matters |
| `/admin/internal/users` | Internal Users list -- create invites, deactivate |
| `/admin/internal/users/{id}` | User detail -- view assigned matters, login history |
| `/admin/internal/matters` | Matters the Internal group owns or has access to |
| `/admin/internal/matters/{id}/access` | Manage per-user access grants for a matter |
| `/admin/internal/groups` | External groups list -- create groups, create External Admin invites |
| `/admin/internal/groups/{id}` | External group detail -- view members, shared matters |

### External Admin Panel (`/admin/org/`)

**Access:** External Admins (scoped to own group) + Internal Admins + System Admins (cascading)

| Path | Purpose |
|---|---|
| `/admin/org/` | Dashboard -- group overview, own matters, shared matters |
| `/admin/org/users` | Group's users list -- create invites, deactivate |
| `/admin/org/users/{id}` | User detail -- view assigned matters |
| `/admin/org/matters` | Matters this group owns or has been granted access to |
| `/admin/org/matters/{id}/access` | Manage per-user access for group members on a matter |
| `/admin/org/profile` | Group profile -- edit name, contact info |

### Cascading Access

- System Admin visits `/admin/org/`: sees group selector -> picks which External group to administer
- Internal Admin visits `/admin/org/`: sees group selector limited to External groups sharing matters with Internal group
- External Admin visits `/admin/org/`: sees only their own group, no selector

Same pattern for `/admin/internal/` -- System Admins see full panel, Internal Admins see their own team.

### Admin Panel Templates

All admin panels share `admin/base.html` layout:
- Sidebar navigation scoped to the panel
- Breadcrumbs
- Panel-specific color accent for visual distinction
- User info + logout in header

---

## 8. Comments System

### Behavior

- Flat list of timestamped comments per item, chronological order
- **`shared` visibility:** visible to anyone with `viewer`+ access to the matter
- **`internal` visibility:** visible only to users with `group_kind = internal`
- Internal group users default to `internal` visibility when composing (can toggle to `shared`)
- External group users can only create `shared` comments (no toggle, no awareness of internal comments)

### Permissions

- Create: any user with `viewer`+ matter role
- Edit own: within 15 minutes of creation
- Delete own: within 15 minutes of creation
- Delete any: matter Managers, System Admins

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/items/{item_id}/comments` | Create comment |
| PATCH | `/api/comments/{comment_id}` | Edit own comment (within time window) |
| DELETE | `/api/comments/{comment_id}` | Delete comment (own within window, or manager/admin) |
| GET | `/api/items/{item_id}/comments` | List comments (filtered by visibility) |

### UI

- Expandable "Comments (N)" section in item row
- Internal comments: subtle background tint + "Internal" badge
- Compose form: text area + submit, with visibility toggle for Internal users (defaults to `internal`)

---

## 9. Audit Logging

### Action Taxonomy

Actions follow `resource.verb` naming.

**Auth events:**

| Action | Detail |
|---|---|
| `auth.login` | IP, user agent |
| `auth.login_failed` | IP, user agent, email attempted |
| `auth.logout` | IP |
| `auth.token_refresh` | IP |
| `auth.mfa_enabled` | -- |
| `auth.mfa_disabled` | who disabled (self or admin) |
| `auth.mfa_failed` | IP, attempt count |
| `auth.password_changed` | self or admin-initiated |
| `auth.invite_created` | target email, role, group, expiry |
| `auth.invite_redeemed` | invite code (hashed) |
| `auth.lockout` | IP, email, duration |

**Data mutations:**

| Action | Detail |
|---|---|
| `matter.create` | matter_id, owner_group_id |
| `matter.update` | changed fields with old/new values |
| `matter.status_change` | old -> new status |
| `matter.share` | target user_id, granted role |
| `matter.revoke` | target user_id, removed role |
| `item.create` | matter_id, description |
| `item.update` | changed fields with old/new values |
| `item.confirm` | confirmed_by_id |
| `item.unconfirm` | -- |
| `item.exclude` | -- |
| `item.delete` | snapshot of deleted item |
| `evidence.upload` | filename, mime_type, size |
| `evidence.delete` | filename |
| `room.create` | matter_id, name |
| `room.update` | old -> new name |
| `room.delete` | name, items unassigned count |
| `crop.adjust` | crop_id, old -> new bbox |
| `crop.recrop` | crop_id |
| `vision.scan` | matter_id, file count, model |
| `serp.search` | item_id, crop_id, service |
| `serp.apply` | item_id, old -> new price, source_url |
| `export.generate` | matter_id, format |
| `comment.create` | item_id, visibility |
| `comment.update` | old -> new body |
| `comment.delete` | deleted by (self or admin) |

**View events:**

| Action | Detail |
|---|---|
| `matter.view` | matter_id, tab |
| `evidence.view` | file_id |
| `evidence.download` | file_id |
| `export.download` | matter_id, format |
| `item.view_edit` | item_id |
| `admin.access` | panel, page |

### Implementation

- Writes via FastAPI `BackgroundTask` (non-blocking)
- View events debounced: same user + same resource within 5 minutes = no duplicate
- `detail` column is JSON (flexible schema per action)
- IP from `X-Forwarded-For` (behind proxy) or `request.client.host`
- Retained indefinitely (attorney work product)
- CSV export from System Admin audit viewer

### Not Logged

- Static asset requests (CSS, JS, CDN)
- Crop image requests (`/crops/` -- public, high volume)
- Health check endpoints
- Token validation internals

---

## 10. Security Hardening

### HTTP Security Headers (middleware, every response)

| Header | Value |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (prod/preview only) |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' https://unpkg.com; style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; img-src 'self' data:; connect-src 'self'` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `X-Request-ID` | UUID per request |

### Cookie Security

| Attribute | `cvp_access` | `cvp_refresh` | `cvp_csrf` |
|---|---|---|---|
| HttpOnly | yes | yes | no (JS reads) |
| Secure | yes (prod/preview) | yes (prod/preview) | yes (prod/preview) |
| SameSite | Lax | Strict | Lax |
| Path | `/` | `/api/auth/refresh` | `/` |
| Max-Age | 3600 | 604800 | 3600 |

### Rate Limiting

| Endpoint | Limit | Window | Lockout |
|---|---|---|---|
| `POST /api/auth/login` | 5 per email | 15 min | 15 min |
| `POST /api/auth/mfa/verify` | 3 per session | 15 min | Session invalidated |
| `POST /api/auth/register` | 3 per IP | 1 hour | 1 hour block |
| `POST /api/*/vision-scan` | 10 per matter | 1 hour | Soft block (warning) |

### Input Validation

- All auth inputs validated via Pydantic with strict constraints
- Password: 12-128 chars, checked against breached-password list
- Email: validated format, normalized to lowercase
- Invite code: 32 chars alphanumeric, generated via `secrets.token_urlsafe`
- TOTP code: exactly 6 digits, numeric only

### Secret Management

| Secret | Storage | Notes |
|---|---|---|
| `JWT_SECRET` | `.env` | min 32 chars, `secrets.token_hex(32)` |
| `MFA_ENCRYPTION_KEY` | `.env` | Fernet key for TOTP secrets at rest |
| Passwords | `users.password_hash` | bcrypt, cost 12 |
| Refresh tokens | `refresh_tokens.token_hash` | SHA-256, raw never stored |
| Invite codes | `users.invite_code` | SHA-256 hashed, raw shown once |

### Session Revocation

- Logout: revokes refresh token; access token valid until 1-hour expiry
- Deactivate user: `is_active = false`; `require_active_user` rejects on next request; refresh fails
- Emergency revoke: System Admin revokes all refresh tokens for a user, forcing re-login within 1 hour

---

## 11. Pages and Navigation

### Public Pages (no auth)

| Path | Purpose |
|---|---|
| `/` | Splash page -- company name, tagline, "Sign In" button |
| `/login` | Email + password form |
| `/login/mfa` | TOTP 6-digit code input (after successful password) |
| `/register/{invite_code}` | Set password + display name for invite redemption |

### Authenticated Navigation Changes

- `GET /` (current dashboard) moves to `GET /dashboard`
- `base.html` header adds: user display name + role badge, logout button, admin panel links (based on system_role)
- Unauthenticated requests to protected pages redirect to `/login?next=/original/path`
- HTMX 401 responses return `HX-Redirect: /login` header

### Environment Behavior

| Setting | Dev | Preview | Production |
|---|---|---|---|
| Auto-login | Seeded dev user | Disabled | Disabled |
| Cookie Secure | false | true | true |
| Rate limiting | Disabled | Enabled | Enabled |
| HTTPS required | No | Yes | Yes |
| MFA available | Yes | Yes | Yes |

---

## 12. Configuration Additions

```python
# Added to config.py (src/cvp/config.py)
environment: str = "production"      # dev | preview | production
jwt_secret: str = ""                 # REQUIRED -- min 32 chars
jwt_access_ttl_minutes: int = 60
jwt_refresh_ttl_days: int = 7
mfa_encryption_key: str = ""         # Fernet key for TOTP secrets
auto_login_user_id: str = ""         # dev only
cookie_secure: bool = True           # False in dev
cookie_domain: str = ""              # set per environment
rate_limit_enabled: bool = True      # False in dev
```

---

## 13. Implementation Phases

### Phase 1: Core Auth Infrastructure

**Scope:** Users, groups, JWT, login/logout, middleware, splash page, registration, security headers, CSRF

- `users` and `groups` tables + migrations
- `refresh_tokens` table
- JWT creation, validation, refresh logic
- `get_current_user`, `require_active_user`, `optional_user` dependencies
- Login, logout, splash, registration pages + endpoints
- Password hashing, breached-password check
- Security headers middleware
- CSRF double-submit cookie
- Cookie + Authorization header transport
- Environment-based config
- Dev auto-login
- Seed script: initial System Admin + Internal group
- Rate limiting on auth endpoints

**Outcome:** App requires login. All existing endpoints behind `require_active_user` (any authenticated user can do anything). Safe intermediate state.

### Phase 2: RBAC + Matter Access Control

**Scope:** `matter_access` table, matter ownership, dependency guards, data filtering, sharing

- `matter_access` table + migration
- `owner_group_id` and `created_by_id` on `matters` + migration
- `confirmed_by_id` and `confirmed_at` on `items` + migration
- `require_matter_role()`, `require_system_admin()`, `require_group_admin()`, `require_matter_owner()` dependencies
- Matter listing filtered by access
- Matter sharing endpoints (grant/revoke)
- All endpoints upgraded to specific guards
- Tenant isolation for External groups

**Outcome:** Full RBAC enforced. Users see/do only what their roles allow.

### Phase 3: Admin Panels

**Scope:** System, Internal, External admin UIs

- `/admin/system/` -- all pages
- `/admin/internal/` -- all pages
- `/admin/org/` -- all pages
- Cascading access + group selector
- Invite creation UI
- User activate/deactivate
- MFA reset (admin-initiated)
- Admin panel base template + nav

**Outcome:** Full user/group/matter administration through web UI.

### Phase 4: Comments + Audit Logging

**Scope:** Comments system, full audit trail

- `comments` table + migration
- Comment endpoints + visibility scoping
- Comment UI in item rows
- `audit_logs` table + migration
- Audit logging dependency + background task writer
- Full action taxonomy instrumented across all endpoints
- View event debouncing
- Audit log viewer in System Admin panel (filters + CSV export)

**Outcome:** Complete accountability trail and collaborative commenting.

### Phase 5: MFA + Password Hardening

**Scope:** TOTP setup, verification, password policies

- MFA setup flow (secret generation, QR code, confirmation)
- MFA verification during login
- `mfa_secret` encryption at rest (Fernet)
- MFA management in user profile
- Admin MFA reset
- Breached-password list bundling + check
- Password change flow in user profile
- Rate limiting on MFA verification

**Outcome:** Optional MFA available. Production-grade password security.

### Phase 6: OAuth/SSO (Future -- not specced)

Google OAuth and potentially other providers. Separate brainstorm + spec cycle.

### Phase Dependencies

```
Phase 1 (Auth) -> Phase 2 (RBAC) -> Phase 3 (Admin Panels)
                                  -> Phase 4 (Comments + Audit)
                                  -> Phase 5 (MFA)
```

Phases 3, 4, 5 can proceed in any order after Phase 2. Recommended order: 3 -> 4 -> 5.

---

## 14. New Dependencies

| Package | Purpose | Notes |
|---|---|---|
| `PyJWT` | JWT creation and validation | Lightweight, no unnecessary deps |
| `bcrypt` | Password hashing | Industry standard |
| `cryptography` | Fernet encryption for MFA secrets | Also needed by PyJWT for some algorithms |
| `pyotp` | TOTP generation and verification | Phase 5 only |
| `qrcode` | QR code generation for MFA setup | Phase 5 only |

All are pure Python or have well-maintained binary wheels. No cloud services, no Docker, no infrastructure changes.
