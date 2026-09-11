# Cloudflare Agent Runs — per-item AI pricing recommendations

**Status:** design, awaiting review
**Date:** 2026-09-10
**Branch:** `feat/cloudflare-agent-runs`

## 1. Problem

A specialist looking at an unpriced item has no way to ask for a pricing
recommendation from the app. Today recommendations arrive only when someone runs
an external agent by hand against `/api/agent/*` using the
`skills/airecommendations` contract.

We want a **"Get AI Recommendations"** button in the item edit section that
launches a single ephemeral agent for that one item, streams progress back into
the UI while it works, and shuts down after submitting its proposals through the
existing recommendation API.

Two agent implementations will exist behind one contract so their output can be
compared on data rather than impression.

## 2. Goals and non-goals

**Goals**

- One-click, per-item recommendation runs from the item edit row.
- Live progress visible to the specialist while the agent works.
- Agents run on Cloudflare, not on the Railway web dyno.
- Credentials never transit from CVP to the agent; Cloudflare holds them.
- Every run records which architecture and model produced it, so A/B is a query.
- Ephemeral compute and storage. CVP is the only durable store.

**Non-goals (v0)**

- Batch or matter-wide runs. One item per click.
- Agents mutating item valuations. Recommendations stay proposals requiring
  human accept, exactly as the skill already specifies.
- Persisting agent state on Cloudflare. No Durable Object storage, no R2 use by us.
- Replacing the existing external-agent path, which must keep working untouched.

## 3. Measurements that drive this design

Taken live on 2026-09-10 against the project's own keys. These numbers are the
reason the design looks the way it does.

**OpenRouter is not a throughput constraint.**

| Probe | Result |
|---|---|
| 100 concurrent minimal calls | 100× HTTP 200, 3.3s wall, zero 429 |
| 30 concurrent realistic turns (Haiku 4.5 + web plugin) | 30× 200, 6.3s wall, p50 3.9s, zero 429 |
| Rate-limit headers | none returned |
| `GET /api/v1/key` → `rate_limit.requests` | `-1`, flagged deprecated |

**Cost per item: $0.01069 measured** (mean over 30 realistic turns) — about
**$10.69 per 1000 items**. Inference is only ~$0.0028 of that; web search is
~$0.007. Search dominates, so result count matters far more than model choice:
Haiku → Sonnet moves a run from ~$0.011 to ~$0.017.

Caveat carried forward: that figure is one turn, five results, one
recommendation. The documented workflow wants two recommendations per item with
exact-match preference, so budget **$20–35 per 1000 items** for real work.

**Spend, not rate, is the binding constraint.** The OpenRouter key carries a $10
cap. `usage.cost` on each response is exact and immediate; `GET /api/v1/key`
lags 20–60s behind. Any budget enforcement must meter the response field, not
the key endpoint.

**Firecrawl was measured and rejected**: 15 req/min, `maxConcurrency: 2`
(queues rather than rejects), ~30 credits per production search against a
1000-credit/month plan — roughly 33 searches per month. It cannot serve this
feature. Blocked-page handling moves to Cloudflare Browser Run.

**Browser Run limits** (Workers **Paid** — the free tier's 10 browser-min/day
and 3 concurrent browsers cannot support this):

| | Paid | Free |
|---|---|---|
| Quick Actions (REST) | 30 req/s | 1 per 10s |
| Concurrent browsers (Sessions) | 200/account | 3/account |
| Browser hours | unlimited, usage-priced | 10 min/day |

Quick Actions are a plain REST API (`/markdown`, `/scrape`, `/json`), callable
from the container with a token — no Puppeteer session, no Workers binding.

**Implication for architecture.** At 30-wide concurrency a 1000-item backlog
clears in ~3.5 minutes. The fan-out this feature needs is tens, not thousands.
Nothing here is justified by scale; it is justified by isolation and by keeping
long-running agent work off the web dyno.

## 4. Architecture

```
specialist clicks "Get AI Recommendations"
  │
  ├─ CVP: guards (model allowlist, no in-flight run, under 5-pending cap)
  ├─ CVP: INSERT agent_runs (queued, model_slug, agent_impl, started_by_id)
  ├─ CVP: return status partial immediately (HTMX polls every 2s)
  └─ CVP BackgroundTask: POST {worker}/runs
        headers: X-CVP-Timestamp, X-CVP-Signature
        body:    {run_id, matter_id, item_id, model_slug, agent_impl}   ← no credentials
             │
             ├─ Worker: verify HMAC + ±300s freshness, else 401
             ├─ Worker: Durable Object id = run_id
             ├─ DO: container.start({env: {...secrets...}, enableInternet: true})
             └─ Worker: 202 Accepted
                   │
                   container: POST /api/agent/runs/{run_id}/progress   (X-API-Key) ×N
                              POST /api/agent/items/{id}/recommendations (X-API-Key)
                              exit 0 → sleepAfter → instance reclaimed
```

### 4.1 Why a container and not a Worker

A Worker alone could do this work, and would delete the image, registry, and CI
push entirely. It is rejected deliberately: the project does not want TypeScript
in its codebase or infrastructure, and the agent logic must stay Python.

This cannot reach zero JavaScript. Cloudflare Containers are controlled by a
class extending `Container` from `@cloudflare/containers`, itself a Durable
Object subclass, and it is TypeScript. Python Workers are open beta and do not
cover the container-control surface. The accepted cost is a ~20-line vendor shim
carrying no business logic, no CVP contract, and no skill rules.

## 5. Data model

New table **`agent_runs`** — one row per click:

| column | type | notes |
|---|---|---|
| `id` | str pk | also the Durable Object id |
| `item_id` | str fk items.id, indexed | |
| `matter_id` | str fk matters.id | |
| `status` | str | `queued\|running\|searching\|submitting\|succeeded\|failed` |
| `status_message` | str \| None | latest line shown in the UI |
| `agent_impl` | str | `custom-python` \| `pi` — the architecture |
| `model_slug` | str | e.g. `anthropic/claude-haiku-4.5` |
| `image_tag` | str | git sha of the container build |
| `cost_micro_usd` | int \| None | from OpenRouter `usage.cost` |
| `latency_ms` | int \| None | |
| `browser_run_used` | bool | did it escalate to Browser Run |
| `error` | str \| None | |
| `started_by_id` | str fk users.id | who clicked |
| `agent_key_id` | str fk agent_keys.id | authorizes progress writes; see §5.2 |
| `created_at` / `started_at` / `finished_at` | datetime | |

**`ai_recommendations.agent_run_id`** — new **nullable** FK to `agent_runs`.
Nullable is load-bearing: recommendations from external agents using the
existing skill flow have no run, and that path must keep working.

### 5.1 Deliberate deviation from immutable rule 1

Rule 1 requires currency as integer cents. `cost_micro_usd` deviates on purpose:
a measured run costs $0.0098, which rounds to 1 cent and quantizes away the
entire signal the A/B exists to capture.

The reading: rule 1 governs **claim** currency — anything reaching an item
valuation, a report, or an export. This is operational telemetry that never
appears in a PDF or CSV. Integer micro-USD keeps the value integer-valued and
float-free, honoring the rule's intent. Recorded here and in `docs/data-model.md`
so it is not later mistaken for an oversight.

### 5.2 Binding a run to an agent key

`agent_runs.agent_key_id` is set **at creation**, not on first contact, so the
progress route can use a strict equality check with no trust-on-first-use
window in which another key could claim an unclaimed run.

CVP cannot infer which key the container will present — it is a Cloudflare
secret. So the key is named in configuration: an admin mints one key under
**System Admin → Agent Keys** for the Cloudflare agent, stores the secret in
Cloudflare, and records its **id** in CVP as `cloudflare_agent_key_id`. CVP
stamps that id onto every run it creates.

Consequences worth stating: rotating the key is a two-step runbook operation
(mint, set the Cloudflare secret, update `cloudflare_agent_key_id`, revoke the
old key), and runs created before a rotation will reject progress from the new
key — so rotate when no runs are in flight. Revoking the key fails launches
loudly at the existing `require_agent_key` check rather than silently.

### 5.3 Why A/B works without new outcome tracking

`ai_recommendations` already carries `status`, `resolved_at`, `resolved_by_id`,
and the Accept/Dismiss buttons already write them. The lifecycle is
`pending → accepted | rejected | superseded`, and `superseded` is set on the
*other* recommendations when one is accepted — so when two implementations price
the same item, a **direct head-to-head winner is recorded for free**.

```sql
select r.agent_impl, r.model_slug,
       count(*) filter (where a.status = 'accepted') * 1.0 / nullif(count(*),0) as accept_rate,
       count(*) filter (where a.match_type = 'exact') * 1.0 / nullif(count(*),0) as exact_rate,
       avg(r.cost_micro_usd) / 1e6 as avg_cost_usd,
       avg(r.latency_ms) as avg_ms
from ai_recommendations a
join agent_runs r on a.agent_run_id = r.id
group by 1, 2;
```

## 6. Model selection

Three layers, following existing patterns:

1. **Default** — new `runtime_config` key `ai_recommendation_model` (env default
   `anthropic/claude-haiku-4.5`), beside the existing
   `ai_recommendation_min_confidence`.
2. **Per-run override** — optional `model_slug` in the launch payload.
3. **Allowlist** — code-defined, following `services/vision_models.py`'s stated
   principle that choosing models is an engineering decision, not an admin one.
   Seeded with slugs verified against the live catalog as supporting both tool
   use and web search: `anthropic/claude-haiku-4.5`,
   `anthropic/claude-sonnet-4.6`, `anthropic/claude-opus-4.6`.

**Validation happens in CVP, never in the Worker.** The Worker holds the
OpenRouter key; an unvalidated slug is a direct path to spending against a
capped key on any of the catalog's 435 models. A model lacking `tools` or
`web_search` support also fails only *after* a container cold start, wasting the
launch.

`openrouter.fetch_models()` already pulls the catalog filtered to vision-capable
models; a sibling filter for web-search-capable entries lets an admin screen
validate the allowlist against the live catalog rather than trusting a hardcoded
list to age well.

**UI:** the main path stays one click using the configured default. The override
appears only behind an Advanced disclosure for system admins.

## 7. Launch handshake

**CVP → Worker.** `X-CVP-Timestamp` plus
`X-CVP-Signature: v1=<hmac_sha256(secret, timestamp + "." + body)>`, verified
with a constant-time compare and a ±300s freshness window. A bare `workers.dev`
URL is world-reachable and a forged launch spends real money against a capped
key; this costs little more than a static bearer token and defeats replay.

Replay inside the freshness window is handled structurally: **the DO id is the
`run_id`**, so a replayed launch lands on the same Durable Object, which refuses
if already started. No storage required. CVP independently rejects progress for
a run already in a terminal state.

**Credentials.** The launch payload contains **no secrets** — only run
parameters. Everything sensitive is a Cloudflare secret injected into the
container via `start({env})`:

| Secret | Purpose |
|---|---|
| `LAUNCH_HMAC_SECRET` | verify CVP called the Worker |
| `CVP_AGENT_KEY` | container → CVP (existing `X-API-Key` auth) |
| `OPENROUTER_API_KEY` | container → OpenRouter |
| `BROWSER_RUN_TOKEN` | container → Browser Run Quick Actions |

**Shutdown and stuck runs.** The container exits 0 after its terminal POST;
`sleepAfter` reclaims the instance. Because storage is ephemeral and logs live
on Cloudflare, CVP cannot interrogate a hung container — so a sweeper marks
non-terminal runs older than `agent_run_stale_minutes` as `failed: timed out`,
modeled on `vision_worker.recover_stale_jobs()`.

**Launch guards**, all before anything leaves Railway: valid `model_slug`, no run
already in flight for the item (double-click protection), and the item under the
5-pending-recommendation cap — the skill's existing 409 rule enforced at launch
rather than discovered after paying for a container and an LLM call.

## 8. Container contract

The contract is the interface; the agent is a swappable implementation.

**Injected per run** via `start({env})`: `RUN_ID`, `MATTER_ID`, `ITEM_ID`,
`MODEL_SLUG`, `CVP_BASE_URL`, `CVP_AGENT_KEY`, `OPENROUTER_API_KEY`,
`BROWSER_RUN_ACCOUNT_ID`, `BROWSER_RUN_TOKEN`. `enableInternet: true` is
required.

**Baked at build**, not injected: `AGENT_IMPL` and `IMAGE_TAG` (git sha), as
Docker `ARG`/`ENV`. These describe the image, so the image reports them — the
run record then reflects what actually ran, not what the Worker believed it
launched.

**No port.** This is a one-shot batch job: `start()` with an entrypoint, process
exits, `onStop` reclaims.

**Progress protocol** — `POST /api/agent/runs/{RUN_ID}/progress`, `X-API-Key`:

```jsonc
// non-terminal, as often as it likes
{"status": "searching", "message": "Looking for retail matches…"}

// terminal success — carries A/B telemetry
{"status": "succeeded", "agent_impl": "pi", "image_tag": "a1b2c3d",
 "model_slug": "anthropic/claude-haiku-4.5", "cost_micro_usd": 9835,
 "latency_ms": 3521, "browser_run_used": false}

// terminal failure
{"status": "failed", "error": "…"}
```

Invariant: the container **always** posts a terminal status, in a `finally`. The
sweeper is the backstop for when it cannot.

### 8.1 The agent proposes, the runner submits

The model returns structured JSON describing a match. A shared `runner.py`
validates it — integer cents, non-empty `source_url` and `source_retailer`,
`match_type` — and performs the actual `POST .../recommendations` via
`agent_client.py`.

This deviates from the original request, in which the agent itself posts.
Reasons:

- The audit-trail invariants are enforced by Python we control rather than by
  trusting a model to follow prose. The audit trail is the product.
- `CVP_AGENT_KEY` need never be reachable from model-generated `bash`. Pi's
  tool surface includes `bash`; a container holding a live CVP key plus
  model-driven shell is a real exfiltration surface.
- Both images validate identically by construction.

The POST still originates in the container and still uses the documented
endpoint; the skill's submission section becomes code-enforced rather than
agent-performed.

### 8.2 The two images

Both are `python:3.11-slim` plus a **shared `runner.py`** owning progress,
validation, submission, telemetry, and error handling. Only the find-a-match
function differs. The contract is therefore shared code, not just a document —
two implementations of the *agent*, one implementation of the *contract*.

- **custom-python** — `runner.py` calls OpenRouter directly with
  `plugins:[{id:"web"}]`, escalating blocked URLs to a Browser Run Quick Action.
- **pi** — adds Node and `@earendil-works/pi-coding-agent`; `runner.py` spawns
  it and parses `--mode json` into progress POSTs:

  ```
  pi -p --no-session --mode json --provider openrouter --model $MODEL_SLUG \
     --skill /app/skills/airecommendations --tools bash,read \
     "Price item $ITEM_ID. Follow the airecommendations skill."
  ```

**Why Pi** over the alternatives probed (opencode 1.17.9, hermes 0.14.0): it is
the only one combining first-class OpenRouter support (`OPENROUTER_API_KEY`,
provider `openrouter`), ephemeral-by-flag (`--no-session`), structured progress
events (`--mode json`), a strict tool allowlist (`--tools`), and a
standards-based skill loader (Agent Skills standard, `--skill <path>`).

Pi has **no built-in web search** — built-ins are `read`, `bash`, `powershell`,
`edit`, `write`, `grep`, `find`, `ls`, and its reference search skill wraps the
Brave API (a new vendor). Not needed: Pi has `bash`, and both search paths are
plain HTTP, so search is a Python helper inside the skill.

**Prerequisite work item:** `skills/airecommendations/` contains
`airecommendations.md` with no frontmatter, so it is not discoverable as a
skill. It must be renamed `SKILL.md` and given `name`/`description` frontmatter.
`skills/MakeAIRecommendations/SKILL.md` already conforms.

Pi's own docs note skills load on demand and "models don't always do this" — the
prompt will force it explicitly.

## 9. CVP surface

**One new router**, `src/cvp/routers/agent_runs.py` (~150 lines). `items.py` is
already 767 lines against the 200-line guidance and will not be added to.

| Route | Auth | Purpose |
|---|---|---|
| `POST /api/items/{item_id}/agent-runs` | `EDITOR` | launch; returns status partial |
| `GET /api/items/{item_id}/agent-runs/{run_id}` | `EDITOR` | status partial for polling |
| `POST /api/agent/runs/{run_id}/progress` | `require_agent_key` | container → CVP |

The progress route additionally asserts
`run.agent_key_id == principal.agent_key_id`, so a valid key cannot write
progress onto another principal's run.

**Services** (side effects belong in `services/` per CLAUDE.md):

- `services/agent_launch.py` — payload, HMAC, outbound POST, status transitions.
- `services/agent_run_sweeper.py` — stale-run reaper.

**Templates — zero JavaScript**, which matters given `connect-src 'self'` in
`middleware.py:31` and the no-inline-handlers rule.

`_agent_run_status.html` follows `_scan_progress.html` exactly:

```html
<div id="agent-run-{{ item.id }}"
  {% if run.status not in TERMINAL %}
  hx-get="/api/items/{{ item.id }}/agent-runs/{{ run.id }}"
  hx-trigger="every 2s" hx-target="this" hx-swap="outerHTML"
  {% endif %}>
```

On terminal success it additionally carries an out-of-band swap refreshing the
existing recommendations block, so proposals appear in place:

```html
<div id="ai-recs-{{ item.id }}" hx-swap-oob="true">
  {% include "_ai_recommendations.html" %}
</div>
```

The button section goes into `_item_row_edit.html` beside the Web search block
(lines 283–329), same visual idiom, with `hx-disabled-elt` while in flight.

**Config:** `cloudflare_agent_worker_url`, `cloudflare_launch_hmac_secret`,
`agent_run_stale_minutes`, `cloudflare_agent_key_id` (§5.2), plus the
`ai_recommendation_model` runtime_config key.

## 10. CI, registry, secrets

```
cloudflare/
├── wrangler.toml
├── src/index.ts                    # ~20-line shim + two Container classes
└── images/
    ├── shared/runner.py
    ├── shared/search.py
    ├── custom-python/Dockerfile
    └── pi/Dockerfile
```

Both Dockerfiles build from the **repo root** so they can `COPY skills/`
directly. `.dockerignore` does not exclude `skills/`, so `agent_client.py` is
used from source rather than duplicated — one more drift vector closed.

**CI** — a `containers` job in the existing `.github/workflows/ci.yml`, matrixed
over `[custom-python, pi]`:

- **PRs: build only, never push.** Catches Dockerfile breakage without consuming
  the 50 GB registry budget every review round.
- **Push to the base branch: build and push**, tagged `:${{ github.sha }}` — the
  same value baked in as `IMAGE_TAG`, so every recommendation in the A/B data
  traces to an exact commit.
- **Deploy pins the sha** in `wrangler.toml` before `wrangler deploy`, rather
  than chasing a moving `:latest`. Rollback is redeploying an older sha.

CI needs only `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.

**Secrets are provisioned out-of-band**, once, by an operator via
`wrangler secret put`, documented in `docs/RUNBOOK.md`. None belong in GitHub
secrets: CI builds images and never talks to CVP or OpenRouter. The existing
gitleaks job remains the backstop.

**Two operational gotchas designed for now:**

1. **No image GC.** Two images × every merge, against a hard 50 GB cap with no
   automatic cleanup. The runbook needs a prune step
   (`wrangler containers images list` / `delete`, keeping the last N plus
   whatever is deployed).
2. **The registry is backed by R2.** Rule 6 lists R2 as not-approved; this is
   Cloudflare's internal implementation of the registry, not us adopting R2 as a
   service. Stated so it is not later read as a silent rule violation.

## 11. Phasing

1. **Shared spine + `custom-python` image.** Migration, endpoints, UI, Worker
   shim, CI, secrets. The custom loop is deterministic, measured, has no
   third-party harness risk, and is the control group.
2. **`pi` image** behind the same contract.
3. **A/B on match quality** over a sample of real unpriced items.

Sequential, not parallel: "both" is only worth paying for if you can tell which
is better, and the deciding metric is match quality, which is unmeasured.

## 12. Testing

Per CLAUDE.md conventions:

- launch: happy path, plus each guard (invalid model, in-flight run, 5-pending cap)
- progress: 401 on bad key, 403 on valid key for another principal's run,
  terminal transition writes telemetry
- status partial: renders each state, stops polling on terminal, OOB swap present
- HMAC signing: fixed-vector unit test so CVP and the Worker cannot drift
- sweeper: stale `running` row becomes `failed`
- **contract suite run against both images**, asserting the skill's invariants
  (integer cents, non-empty source fields, 409 on the pending cap, 401 handling)

## 13. Risks and open questions

- **Match quality is unmeasured.** The one sampled run returned
  `match_type: "brand"`, not `exact`. A fleet cheaply producing confident
  brand-level guesses a specialist must reject is worse than no fleet. This is
  the single largest risk, and the telemetry in §5 exists to answer it.
- **Pi cost reporting.** Whether `--mode json` exposes token cost is unverified.
  Stop-gap accepted: `cost_micro_usd` nullable for the Pi arm, reconciled
  manually from OpenRouter usage reports, correlated by `model_slug` and the
  run's `started_at`/`finished_at`.
- **The custom loop may converge on being a bad harness.** Two recommendations
  per item, exact-match preference, and blocked-page escalation are genuinely
  multi-turn. If the custom image grows retries and tool dispatch, the honest
  read is that Pi is the destination and the custom loop stays a thin baseline.
- **$10 OpenRouter key cap** must be raised before any volume run; a 1000-item
  pass at measured cost exceeds it.
- **Workers Paid plan** is a hard prerequisite for Browser Run.
- **Two implementations, one contract.** Contained by the shared `runner.py` and
  the contract test suite. Two implementations of the agent are fine; two
  interpretations of the audit-trail rules are not.

## 14. Required documentation changes

- **`CLAUDE.md` rule 6** — approve Cloudflare **Workers, Durable Objects,
  Containers + managed registry, and Browser Run**, noting Workers Paid is
  required. Follows the precedent of PR #69, which amended rule 6 for Firecrawl
  in the same PR as its design spec.
- **`docs/data-model.md`** — `agent_runs`, the `agent_run_id` FK, and the
  `cost_micro_usd` carve-out.
- **`docs/RUNBOOK.md`** — first-deploy secret provisioning, image pruning, and
  diagnosing a stuck run given ephemeral storage and Cloudflare-side logs, and
  agent-key rotation (§5.2).
