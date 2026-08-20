# AI Recommendations — Design Spec

**Date:** 2026-08-19
**Status:** Approved design, ready for implementation planning
**Branch context:** `cvp-legacy`

## Summary

Let external, fully-decoupled AI agents propose pricing for inventory items. An
agent fetches items that lack a valuation, shops for a matching product, and
submits a **recommendation** (source URL, unit price, shipping). Recommendations
are *proposals*: they land in a new `ai_recommendations` table and never touch
the item until a specialist reviews and **accepts** one in the UI. Acceptance
reuses the existing SERP write path, so an accepted recommendation satisfies the
immutable "every RCV must have a source" rule.

Agents are a new kind of principal — machines, not users. They authenticate with
a revocable `X-API-Key` created and managed from the admin dashboard, and are
scoped to read-all matters/items/crops and write-only to `ai_recommendations`.
Initially the discovery feed only surfaces items the vision scan identified with
high confidence (threshold configurable by a system admin).

## Goals

- A new `AiRecommendation` proposal entity, **multiple per item**, reviewed by a
  human before it affects any valuation.
- A machine-auth surface (`X-API-Key`) with **named, individually-revocable**
  keys and **per-key audit attribution**, managed from the admin dashboard.
- A JSON agent API to (a) discover items needing recommendations, filtered to a
  configurable vision-confidence threshold, and (b) submit recommendations.
- A specialist UI section ("AI Recommendations") in the item edit area with
  Accept / Dismiss write-through.

## Non-goals (v0)

- No live retailer scraping by our system (immutable rule 5 unchanged — the
  agent is external and does its own fetching).
- No screenshot capture for agent recommendations. Agents assert a `source_url`;
  screenshots remain a human/Playwright concern.
- No inbound rate limiting on agent writes (cheap; revocable keys + audit log are
  the control). Revisit if abuse appears.
- Agents are not modeled as `User`s and do not use JWT/MFA/RBAC. Rule 6
  (humans authenticate via the existing auth system) is unchanged.

## Immutable-rule compliance

- **Rule 1 (integer cents):** all money fields (`proposed_retail_unit_cents`,
  `proposed_shipping_cents`) are integer cents.
- **Rule 2 (every RCV has a source):** a recommendation carries `source_url`,
  `source_retailer`, `match_type`; acceptance stamps `source_captured_at`. An
  accepted recommendation therefore produces a fully-sourced item.
- **Rule 3 (ACV is computed):** acceptance recomputes ACV via
  `depreciation.compute_acv`; the agent never sets ACV.
- **Rule 6 (auth):** agents are a distinct machine principal, not users.

---

## 1. Data model

### 1.1 New table: `agent_keys`

Machine principals for external AI agents. New model file
`src/cvp/models_agent.py`, registered with `Base` from `models.py` like the
other `models_*` modules.

| column          | type            | notes                                                        |
|-----------------|-----------------|--------------------------------------------------------------|
| `id`            | String PK       | uuid                                                         |
| `name`          | String          | human label, e.g. "Pricing Bot A"                            |
| `key_prefix`    | String, indexed | non-secret lookup prefix, e.g. `agk_live_a1b2c3`             |
| `key_hash`      | String          | SHA-256 of the full key; full key shown once at creation     |
| `created_by_id` | FK users.id     | which admin created it                                       |
| `created_at`    | DateTime        | server default now                                           |
| `last_used_at`  | DateTime, null  | updated on each successful auth                              |
| `revoked_at`    | DateTime, null  | set on revoke; non-null ⇒ key no longer authenticates        |

The full key format is `agk_live_<prefix>_<secret>`. Only `key_prefix` and
`key_hash` are stored. Lookups match by `key_prefix`, then verify the full key
against `key_hash`.

### 1.2 New table: `ai_recommendations`

One row per proposal. New model in `src/cvp/models_agent.py` (or a sibling
`models_recommendations.py` — implementer's choice, keep it under 200 lines).

| column                       | type              | notes                                             |
|------------------------------|-------------------|---------------------------------------------------|
| `id`                         | String PK         | uuid                                              |
| `item_id`                    | FK items.id       | indexed                                           |
| `item_crop_id`               | FK item_crops.id, null | which crop the agent used (optional)         |
| `agent_key_id`               | FK agent_keys.id  | audit attribution                                 |
| `proposed_retail_unit_cents` | Integer           | cents                                             |
| `proposed_shipping_cents`    | Integer, default 0 | cents                                            |
| `source_url`                 | String            | required                                          |
| `source_retailer`            | String            | required                                          |
| `match_type`                 | String            | e.g. `exact`                                      |
| `product_title`              | String            | what the agent thinks it found                    |
| `rationale`                  | Text              | short free-text why this match                    |
| `status`                     | String            | `pending` / `accepted` / `rejected` / `superseded`|
| `created_at`                 | DateTime          | server default now                                |
| `source_captured_at`         | DateTime          | server-stamped at submit time                     |
| `resolved_at`                | DateTime, null    | set on accept/dismiss                             |
| `resolved_by_id`             | FK users.id, null | which specialist resolved it                      |

Relationship: `Item.ai_recommendations` (back-populates), ordered by
`created_at`.

### 1.3 New column: `Item.vision_confidence`

`vision_confidence: Mapped[str | None]` — one of `high` / `medium` / `low` /
`null`. Indexed (used by the discovery filter).

- **Going forward:** `services/vision.py` sets it from the model's
  `confidence` value at item-creation time (today that value is only written
  into the `notes` string as `|confidence:...`). Keep writing `notes` as-is for
  backward compatibility; additionally populate the column.
- **Backfill:** the Alembic migration parses existing `notes` for
  `confidence:(high|medium|low)` and populates the new column for existing rows.

### 1.4 Migration

One Alembic revision: create `agent_keys`, create `ai_recommendations`, add
`items.vision_confidence` (+ index), backfill `vision_confidence` from `notes`.

---

## 2. Auth: `X-API-Key`

New machinery in `src/cvp/dependencies.py` (or a small `agent_auth.py` if it
keeps `dependencies.py` lean):

- `AgentPrincipal` pydantic context: `agent_key_id`, `name`.
- `require_agent_key(request)` dependency:
  1. Read `X-API-Key` header. Missing ⇒ `401`.
  2. Parse the prefix, look up `agent_keys` by `key_prefix`.
  3. Verify the full key against `key_hash` (constant-time compare). Mismatch ⇒ `401`.
  4. Reject if `revoked_at` is set ⇒ `401`.
  5. Update `last_used_at`.
  6. Return `AgentPrincipal`.

Agents bypass `MatterAccess` entirely — read-all is intentional and part of the
scope. They have no route access outside `/api/agent/*`.

Every agent write calls the existing `write_audit_log` with the `agent_key_id`
as the actor. (Audit schema currently keys on `user_id`; store the agent key id
there with an `actor_type`/prefix convention, or extend the audit helper —
implementer decides, but the key id MUST be recorded.)

---

## 3. Agent API

All under `/api/agent/`, all behind `Depends(require_agent_key)`, all JSON.
New router `src/cvp/routers/agent.py`, included in `main.py`.

### 3.1 `GET /api/agent/items`

Paged discovery feed. Query params: `min_confidence` (optional override, else the
configured threshold), `limit` (default 50, capped), `cursor` (opaque paging).

Returns items where **all** hold:
1. `vision_confidence` at or above the configured/queried threshold
   (ordering high > medium > low).
2. No accepted source yet — `source_url` is empty.
3. Fewer than **5 pending** recommendations (accepted/rejected/superseded do not
   count toward the cap).

Each item payload includes: `item_id`, `description`, `brand`, `model`,
`category` (name), `quantity`, `vision_confidence`, `matter_id` + minimal matter
context, and `crops` (list of `{item_crop_id, image_url}` pointing at
§3.3).

### 3.2 `GET /api/agent/items/{item_id}`

Single-item detail + crops. Same shape as one feed entry.

### 3.3 `GET /api/agent/crops/{crop_path:path}`

Serves crop image bytes to an agent. Same path-traversal guard as the existing
`/crops/` route, but authed by `require_agent_key` instead of `optional_user`.
The discovery feed emits URLs pointing here so crop access is agent-key-gated
(not the existing public-ish `/crops/` route).

### 3.4 `POST /api/agent/items/{item_id}/recommendations`

Submit a recommendation. JSON body: `proposed_retail_unit_cents`,
`proposed_shipping_cents`, `source_url`, `source_retailer`, `match_type`,
`product_title`, `rationale`, `item_crop_id` (optional).

Behavior:
- Validate `source_url` and `source_retailer` are non-empty (rule 2 for the
  eventual accept).
- **Enforce the cap:** if the item already has **5 pending** recommendations,
  return `409 Conflict`. (Slots free when a rec is accepted → others superseded,
  or dismissed → rejected.)
- Server-stamp `source_captured_at = now`, `status = pending`,
  `agent_key_id = principal.agent_key_id`.
- Audit-log with the agent key id.
- Return the created recommendation (`201`).

---

## 4. Specialist UI

New **"AI Recommendations"** section rendered in the item edit area, positioned
**above** the existing "Google Lens" (SERP) section. Likely a partial
(`_ai_recommendations.html`) loaded alongside / within the existing item-edit
expansion, following the SERP panel pattern
(`/api/items/{item_id}/serp-panel`).

- **Empty state:** the section renders the literal text
  **"No Existing Recommendations."**
- **Populated:** one card per **pending** recommendation showing product title,
  proposed unit price + shipping (formatted from cents), retailer, source link
  (opens in new tab), rationale, submitting agent name, and submission
  timestamp.
- **Accept** button per card → `POST /api/items/{item_id}/recommendations/{rec_id}/accept`:
  - Writes through to the item using the **same logic as `serp_apply`**:
    `retail_unit_cents = proposed_retail_unit_cents`,
    `shipping_cents = proposed_shipping_cents`, `source_url`,
    `source_retailer`, `source_captured_at = now`, `match_type`;
    `rcv_total_cents = retail_unit_cents * quantity + shipping_cents`;
    recompute `acv_total_cents` via `compute_acv`.
  - Marks this rec `accepted` (sets `resolved_at`, `resolved_by_id`); marks all
    other pending recs for the item `superseded`.
  - Returns the re-rendered item row (HTMX), consistent with `serp_apply`.
- **Dismiss** button per card → `POST /api/items/{item_id}/recommendations/{rec_id}/dismiss`:
  marks the rec `rejected` (frees a pending slot). Re-renders the section.

These specialist-facing routes are authed by the normal human dependency
(`require_matter_role("editor")`), not `require_agent_key`.

**CSP note:** wire Accept/Dismiss via `data-*` attributes + delegated listeners
in `app.js` (or HTMX attributes). No inline `onclick`/`onchange` handlers.

## 5. Admin dashboard: Agent Keys

New page under `routers/admin/` (e.g. `admin/agent_keys.py`, prefix
`/admin/system/agent-keys`), system-admin only (`require_system_admin`),
following the `runtime_config` / `vision_models` router pattern.

- **List:** name, `key_prefix`, created-by, `created_at`, `last_used_at`,
  status (Active / Revoked).
- **Create:** form with a name → generates `agk_live_<prefix>_<secret>`, stores
  `key_prefix` + `key_hash`, and displays the **full key exactly once** with a
  clear "copy it now, it won't be shown again" warning.
- **Revoke:** sets `revoked_at`; the key stops authenticating immediately.

Link the page from the System Admin panel navigation alongside the other admin
tools.

## 6. Configuration

Add one knob to the existing System Admin runtime-config page
(`routers/admin/runtime_config.py` + `services/runtime_config.py`):

- `ai_recommendation_min_confidence` — `high` / `medium` / `low`, default
  `high`. Governs the §3.1 discovery threshold.

`runtime_config` currently only has `get_int`; add a `get_str` (with an allowed-
values guard) for this string-valued knob. The runtime-config admin template
gains a select input for it.

---

## Components & boundaries

| Unit                                   | Responsibility                                              | Depends on                          |
|----------------------------------------|------------------------------------------------------------|-------------------------------------|
| `models_agent.py`                      | `AgentKey`, `AiRecommendation` ORM                         | `models.Base`                       |
| `Item.vision_confidence`               | queryable confidence                                       | migration + `vision.py`             |
| `require_agent_key` (dependencies)     | machine auth, `last_used_at` update                        | `agent_keys`                        |
| `routers/agent.py`                     | discovery feed, item detail, crop serving, submit          | `require_agent_key`, models         |
| `routers/items.py` (or new sub-router) | Accept / Dismiss write-through                             | `require_matter_role`, `compute_acv`, `serp_apply` logic |
| `_ai_recommendations.html`             | specialist section rendering                               | items UI                            |
| `admin/agent_keys.py`                  | key CRUD (create/list/revoke)                              | `require_system_admin`              |
| `services/runtime_config.py`           | `get_str` + confidence knob                                | `app_setting`                       |

## Testing

- **Migration:** backfill correctly maps `notes` `confidence:*` → column, and
  leaves rows without a confidence marker `null`.
- **Auth:** valid key authenticates; revoked key ⇒ 401; unknown prefix ⇒ 401;
  tampered secret ⇒ 401; `last_used_at` updates.
- **Discovery filter:** excludes low/medium below threshold, items with a
  source, and items already at 5 pending recs; threshold override respected.
- **Cap:** 6th pending submission ⇒ 409.
- **Accept:** writes correct integer-cents fields, recomputes ACV, marks others
  superseded; produces a fully-sourced item (rule 2).
- **Dismiss:** marks rejected, frees a slot.
- **Audit:** every agent write records the `agent_key_id`.
- **Admin:** create shows full key once and stores only the hash; revoke blocks
  subsequent auth.

## Open items for the implementation plan

- Exact audit-log actor representation for a machine key (extend the helper vs.
  encode into `user_id`) — must record the key id either way.
- Whether Accept/Dismiss live in `items.py` or a small dedicated
  `recommendations.py` router (keep files < 200 lines).
- Cursor/paging encoding for the discovery feed.
