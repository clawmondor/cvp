# Cloudflare Agent Runs — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a "Get AI Recommendations" button on the item edit row that launches one ephemeral Cloudflare container per item, streams progress into the UI, and submits a sourced pricing proposal through the existing agent API.

**Architecture:** CVP creates an `agent_runs` row and HMAC-signs a launch POST to a Cloudflare Worker. The Worker starts a Durable-Object-controlled container whose id is the run id, injecting credentials as Cloudflare secrets. A Python `runner.py` inside the container calls OpenRouter with the web-search plugin, escalates blocked pages to Browser Run, validates the result, POSTs progress back to CVP, and submits the recommendation before exiting. CVP is the only durable store.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic, Jinja2, HTMX, httpx, pytest, ruff; Cloudflare Workers + Containers (~20 lines TypeScript), Browser Run REST; OpenRouter.

**Spec:** `docs/superpowers/specs/2026-09-10-cloudflare-agent-runs-design.md`

## Global Constraints

- **Branch:** work on `feat/cloudflare-agent-runs`, cut from `cvp-legacy`. PR targets `cvp-legacy`, **not** `main` — `main` does not contain `routers/agent.py`, `models_agent.py`, or `services/runtime_config.py`.
- **Currency is integer cents** everywhere except `agent_runs.cost_micro_usd`, which is integer micro-USD by the documented carve-out in spec §5.1. Never use floats for money.
- **Every RCV needs a source.** A submitted recommendation must carry non-empty `source_url` and `source_retailer`, or it is invalid.
- **No inline JavaScript.** No `onclick=`/`onchange=`/`onsubmit=` in templates. CSP `script-src` has no `unsafe-inline`. Interactivity is HTMX attributes or delegated listeners in `src/cvp/static/app.js`.
- **CSP `connect-src 'self'`** (`src/cvp/middleware.py:31`). No browser connections to `*.workers.dev`. Progress reaches the UI by polling CVP only.
- **Type hints everywhere**, modern syntax (`list[str]`, `X | None`).
- **UUIDs as strings**, timestamps as timezone-aware UTC.
- **Run `uv run ruff format .` then `uv run ruff format --check .` before every commit.** CI enforces format and has failed on this repeatedly.
- **Never commit `.env`, `./data/`, or `./backups/`.**
- Alembic head at plan time is `46e5951cae12`. Task 2 adds the only migration in this plan.
- Cloudflare **Workers Paid** plan is a hard prerequisite (Browser Run free tier is 10 browser-min/day).

---

### Task 1: Approve the platform in rule 6 and document the data model

Rule 6 currently approves Cloudflare for "DNS, registrar, proxy" only. Every later task depends on Workers, Durable Objects, Containers, and Browser Run being approved. This mirrors PR #69, which amended rule 6 for Firecrawl alongside its spec.

**Files:**
- Modify: `CLAUDE.md` (rule 6, line 79)
- Modify: `docs/data-model.md`

- [ ] **Step 1: Read the current rule 6 text**

Run: `grep -n "Approved cloud services" CLAUDE.md`

- [ ] **Step 2: Replace rule 6 with the amended version**

Replace the single line beginning `6. **Approved cloud services:` with:

```markdown
6. **Approved cloud services: Anthropic API, OpenRouter (Claude Vision calls, model-catalog discovery, and agent inference with the web-search plugin), Firecrawl (web product search and structured price extraction), Railway (web + Postgres + volume), Cloudflare (DNS, registrar, proxy; Workers, Durable Objects, Containers with the managed image registry, and Browser Run for the per-item recommendation agents — requires the Workers Paid plan).** Not approved without re-discussion: S3, Redis, Vercel, Celery, additional managed services. Direct use of R2 remains unapproved; the Cloudflare container registry is backed by R2 internally, which is Cloudflare's implementation detail and not us adopting R2 as a service. Docker is approved as the production runtime; local development still runs on host Python.
```

- [ ] **Step 3: Append the data-model note**

Append to `docs/data-model.md`:

```markdown
## agent_runs (2026-09-10)

One row per "Get AI Recommendations" click. Records which architecture
(`agent_impl`) and which model (`model_slug`) produced a recommendation, so
A/B comparison is a SQL query rather than an impression.

`ai_recommendations.agent_run_id` is a **nullable** FK to this table. Nullable
is load-bearing: recommendations submitted by external agents through the
documented `skills/airecommendations` flow have no run, and that path must keep
working.

`agent_runs.agent_key_id` is set at row creation from the configured
`cloudflare_agent_key_id`, never on first contact, so the progress endpoint can
use a strict equality check with no trust-on-first-use window.

### Deliberate deviation from immutable rule 1

`cost_micro_usd` is integer **micro-USD**, not cents. A measured agent run costs
$0.0098, which rounds to 1 cent and quantizes away the entire signal the A/B
exists to capture. Rule 1 governs *claim* currency — anything reaching an item
valuation, a report, or an export. This is operational telemetry that never
appears in a PDF or CSV. Integer micros keep the value integer-valued and
float-free, honoring the rule's intent.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/data-model.md
git commit -m "docs: approve Cloudflare compute in rule 6; document agent_runs"
```

---

### Task 2: AgentRun model and migration

**Files:**
- Modify: `src/cvp/models_agent.py`
- Create: `migrations/versions/<generated>_add_agent_runs.py`
- Test: `tests/test_agent_run_model.py`

**Interfaces:**
- Produces: `cvp.models_agent.AgentRun` with columns listed below; `AgentRun.TERMINAL: frozenset[str]`; `AiRecommendation.agent_run_id: str | None`.

`models_agent.py` is already imported by `tests/conftest.py`, so no conftest change is needed.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_run_model.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.models import Base, Item, Matter
from cvp.models_agent import AgentKey, AgentRun, AiRecommendation
from cvp.services.agent_keys import generate_key


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_agent_run_defaults_to_queued(db):
    m = Matter(firm_name="F")
    db.add(m)
    db.flush()
    item = Item(matter_id=m.id, description="chair", quantity=1)
    db.add(item)
    _, prefix, key_hash = generate_key()
    key = AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.flush()

    run = AgentRun(
        item_id=item.id,
        matter_id=m.id,
        agent_impl="custom-python",
        model_slug="anthropic/claude-haiku-4.5",
        agent_key_id=key.id,
        started_by_id=None,
    )
    db.add(run)
    db.commit()

    assert run.status == "queued"
    assert run.browser_run_used is False
    assert run.cost_micro_usd is None


def test_terminal_set_contents():
    assert AgentRun.TERMINAL == frozenset({"succeeded", "failed"})


def test_recommendation_agent_run_id_is_nullable(db):
    """External-agent submissions have no run; that path must keep working."""
    m = Matter(firm_name="F")
    db.add(m)
    db.flush()
    item = Item(matter_id=m.id, description="chair", quantity=1)
    db.add(item)
    _, prefix, key_hash = generate_key()
    key = AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.flush()

    rec = AiRecommendation(
        item_id=item.id,
        agent_key_id=key.id,
        proposed_retail_unit_cents=1000,
        source_url="https://shop.example/x",
        source_retailer="Shop",
    )
    db.add(rec)
    db.commit()
    assert rec.agent_run_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_run_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'AgentRun'`

- [ ] **Step 3: Add the model**

Append to `src/cvp/models_agent.py`:

```python
class AgentRun(Base):
    """One launch of an ephemeral pricing agent for a single item.

    Records which architecture and model produced a recommendation so that
    A/B comparison is a query. CVP is the only durable store for a run —
    the Cloudflare container keeps nothing.
    """

    __tablename__ = "agent_runs"

    #: Statuses after which no further progress is accepted.
    TERMINAL = frozenset({"succeeded", "failed"})

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("items.id"), nullable=False, index=True)
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="queued", server_default="queued"
    )
    status_message: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_impl: Mapped[str] = mapped_column(String, nullable=False)
    model_slug: Mapped[str] = mapped_column(String, nullable=False)
    image_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    cost_micro_usd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    browser_run_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    agent_key_id: Mapped[str] = mapped_column(String, ForeignKey("agent_keys.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

Add `agent_run_id` to `AiRecommendation`, directly after `agent_key_id`:

```python
    agent_run_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agent_runs.id"), nullable=True, index=True
    )
```

Update the import line at the top of the file to include `Boolean`:

```python
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_agent_run_model.py -v`
Expected: 3 passed

- [ ] **Step 5: Generate the migration**

Run: `uv run alembic revision --autogenerate -m "add agent_runs"`

Open the generated file and verify `upgrade()` creates the `agent_runs` table with all columns above **and** adds the `agent_run_id` column to `ai_recommendations`. Autogenerate on SQLite will not emit the FK for the added column; add it explicitly using batch mode:

```python
def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("matter_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="queued", nullable=False),
        sa.Column("status_message", sa.String(), nullable=True),
        sa.Column("agent_impl", sa.String(), nullable=False),
        sa.Column("model_slug", sa.String(), nullable=False),
        sa.Column("image_tag", sa.String(), nullable=True),
        sa.Column("cost_micro_usd", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("browser_run_used", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_by_id", sa.String(), nullable=True),
        sa.Column("agent_key_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"]),
        sa.ForeignKeyConstraint(["started_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["agent_key_id"], ["agent_keys.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_runs_item_id"), "agent_runs", ["item_id"])
    with op.batch_alter_table("ai_recommendations") as batch:
        batch.add_column(sa.Column("agent_run_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_ai_recommendations_agent_run_id", "agent_runs", ["agent_run_id"], ["id"]
        )
    op.create_index(
        op.f("ix_ai_recommendations_agent_run_id"), "ai_recommendations", ["agent_run_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_recommendations_agent_run_id"), table_name="ai_recommendations")
    with op.batch_alter_table("ai_recommendations") as batch:
        batch.drop_constraint("fk_ai_recommendations_agent_run_id", type_="foreignkey")
        batch.drop_column("agent_run_id")
    op.drop_index(op.f("ix_agent_runs_item_id"), table_name="agent_runs")
    op.drop_table("agent_runs")
```

- [ ] **Step 6: Apply and verify the migration round-trips**

```bash
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```
Expected: all three succeed with no error.

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/models_agent.py migrations/versions/ tests/test_agent_run_model.py
git commit -m "feat(agent-runs): AgentRun model and migration"
```

---

### Task 3: Model allowlist and configuration

**Files:**
- Create: `src/cvp/services/agent_models.py`
- Modify: `src/cvp/config.py`
- Modify: `src/cvp/services/runtime_config.py:33-35`
- Modify: `.env.example`
- Test: `tests/test_agent_models.py`

**Interfaces:**
- Produces: `ALLOWED_MODEL_SLUGS: tuple[str, ...]`, `DEFAULT_MODEL_SLUG: str`, `is_allowed(slug: str) -> bool`, `resolve_model(db: Session, requested: str | None) -> str` (raises `ValueError` on a disallowed slug).
- Produces settings: `cloudflare_agent_worker_url`, `cloudflare_launch_hmac_secret`, `cloudflare_agent_key_id`, `agent_run_stale_minutes`, `ai_recommendation_model`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_models.py`:

```python
import pytest

from cvp.services.agent_models import (
    ALLOWED_MODEL_SLUGS,
    DEFAULT_MODEL_SLUG,
    is_allowed,
    resolve_model,
)


def test_default_is_allowed():
    assert DEFAULT_MODEL_SLUG in ALLOWED_MODEL_SLUGS


def test_is_allowed_rejects_unknown():
    assert is_allowed("anthropic/claude-haiku-4.5") is True
    assert is_allowed("some/expensive-model") is False
    assert is_allowed("") is False


def test_resolve_model_uses_default_when_not_requested(db_session):
    assert resolve_model(db_session, None) == DEFAULT_MODEL_SLUG


def test_resolve_model_accepts_allowed_override(db_session):
    assert resolve_model(db_session, "anthropic/claude-sonnet-4.6") == "anthropic/claude-sonnet-4.6"


def test_resolve_model_rejects_disallowed_override(db_session):
    with pytest.raises(ValueError, match="not allowed"):
        resolve_model(db_session, "some/expensive-model")
```

Add this fixture at the top of the same file:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cvp.models import Base


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cvp.services.agent_models'`

- [ ] **Step 3: Create the allowlist service**

Create `src/cvp/services/agent_models.py`:

```python
"""Which OpenRouter models the recommendation agents may use.

Code-defined, not admin-editable, following the same reasoning as
`vision_models.py`: choosing which models are allowed to spend money is an
engineering decision. Validation happens here, in CVP, and never in the
Cloudflare Worker — the Worker holds the OpenRouter key, and an unvalidated
slug is a direct path to spending against a capped key on any of the
catalog's several hundred models.

Every slug below was verified against the live OpenRouter catalog as
supporting both tool use and the web-search plugin.
"""

from sqlalchemy.orm import Session

from cvp.services import runtime_config

ALLOWED_MODEL_SLUGS: tuple[str, ...] = (
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-sonnet-4.6",
    "anthropic/claude-opus-4.6",
)

DEFAULT_MODEL_SLUG: str = "anthropic/claude-haiku-4.5"


def is_allowed(slug: str) -> bool:
    return slug in ALLOWED_MODEL_SLUGS


def resolve_model(db: Session, requested: str | None) -> str:
    """Return the model slug to run, validating any caller-supplied override.

    Raises ValueError if the override is not on the allowlist.
    """
    if requested:
        if not is_allowed(requested):
            raise ValueError(f"model {requested!r} is not allowed")
        return requested
    return runtime_config.get_str(db, "ai_recommendation_model")
```

- [ ] **Step 4: Add the settings**

In `src/cvp/config.py`, after the `firecrawl_api_key` line, add:

```python
    # Cloudflare agent runs
    cloudflare_agent_worker_url: str = ""
    cloudflare_launch_hmac_secret: str = ""
    cloudflare_agent_key_id: str = ""
    agent_run_stale_minutes: int = 15
    ai_recommendation_model: str = "anthropic/claude-haiku-4.5"
```

In `src/cvp/services/runtime_config.py`, extend `_ALLOWED_STR`:

```python
_ALLOWED_STR: dict[str, tuple[str, ...]] = {
    "ai_recommendation_min_confidence": ("high", "medium", "low"),
    "ai_recommendation_model": ALLOWED_MODEL_SLUGS,
}
```

and add the import at the top of `runtime_config.py`:

```python
from cvp.services.agent_models import ALLOWED_MODEL_SLUGS
```

> If this import creates a cycle (`agent_models` imports `runtime_config`),
> break it by moving `ALLOWED_MODEL_SLUGS` and `DEFAULT_MODEL_SLUG` into
> `src/cvp/services/agent_model_slugs.py` (constants only, no imports) and
> importing that from both modules. Verify with
> `uv run python -c "import cvp.main"`.

Append to `.env.example`:

```
# Cloudflare agent runs
CLOUDFLARE_AGENT_WORKER_URL=
CLOUDFLARE_LAUNCH_HMAC_SECRET=
CLOUDFLARE_AGENT_KEY_ID=
AGENT_RUN_STALE_MINUTES=15
AI_RECOMMENDATION_MODEL=anthropic/claude-haiku-4.5
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_agent_models.py -v
uv run python -c "import cvp.main; print('no import cycle')"
```
Expected: 5 passed, then `no import cycle`

- [ ] **Step 6: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/services/ src/cvp/config.py .env.example tests/test_agent_models.py
git commit -m "feat(agent-runs): model allowlist and configuration"
```

---

### Task 4: HMAC request signing

Pure function, isolated so CVP and the Worker cannot drift. The fixed vector in the test is the contract both sides implement.

**Files:**
- Create: `src/cvp/services/agent_launch.py`
- Test: `tests/test_agent_launch_signing.py`

**Interfaces:**
- Produces: `sign_payload(secret: str, timestamp: str, body: str) -> str` returning `"v1=<hex>"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_launch_signing.py`:

```python
from cvp.services.agent_launch import sign_payload


def test_known_vector():
    """Fixed vector — the Cloudflare Worker implements the same computation.

    If this value changes, the Worker's verify() must change with it.
    """
    sig = sign_payload("topsecret", "1757462400", '{"run_id":"abc"}')
    assert sig == (
        "v1=8c9b1e9a1b0b2e6a6f3c4b6b1c4d4f3a8b2e7c1d9a0f5e3b7c8d2a1e4f6b9c0d"
    )


def test_signature_is_prefixed_and_hex():
    sig = sign_payload("k", "1", "{}")
    assert sig.startswith("v1=")
    assert len(sig) == 3 + 64
    int(sig[3:], 16)  # raises if not hex


def test_different_body_changes_signature():
    a = sign_payload("k", "1", '{"a":1}')
    b = sign_payload("k", "1", '{"a":2}')
    assert a != b


def test_different_timestamp_changes_signature():
    a = sign_payload("k", "1", "{}")
    b = sign_payload("k", "2", "{}")
    assert a != b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_launch_signing.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `src/cvp/services/agent_launch.py`:

```python
"""Launching a Cloudflare agent run: signing, payload, and the outbound POST.

The Worker is world-reachable, so a forged launch would spend real money
against a capped OpenRouter key. Requests are HMAC-signed over
"<timestamp>.<body>" and the Worker enforces a freshness window.
"""

import hashlib
import hmac


def sign_payload(secret: str, timestamp: str, body: str) -> str:
    """Return "v1=<hex>" for HMAC-SHA256 over "<timestamp>.<body>".

    The Cloudflare Worker implements the identical computation; the fixed
    vector in tests/test_agent_launch_signing.py is the shared contract.
    """
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body}".encode("utf-8"),
        hashlib.sha256,
    )
    return f"v1={mac.hexdigest()}"
```

- [ ] **Step 4: Correct the fixed vector and confirm**

The literal in Step 1 is a placeholder shape, not a real digest. Compute the true value once and paste it into the test:

```bash
uv run python -c "from cvp.services.agent_launch import sign_payload; print(sign_payload('topsecret','1757462400','{\"run_id\":\"abc\"}'))"
```

Replace the expected string in `test_known_vector` with the printed value, then run:

`uv run pytest tests/test_agent_launch_signing.py -v`
Expected: 4 passed

Record the same vector as a comment in the Worker source in Task 12.

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/services/agent_launch.py tests/test_agent_launch_signing.py
git commit -m "feat(agent-runs): HMAC launch signing"
```

---

### Task 5: Launch service — the outbound POST

**Files:**
- Modify: `src/cvp/services/agent_launch.py`
- Test: `tests/test_agent_launch_service.py`

**Interfaces:**
- Consumes: `sign_payload` (Task 4), `AgentRun` (Task 2).
- Produces: `launch_run(run_id: str) -> None` — opens its own session, POSTs to the Worker, and transitions the run. Safe to hand to `BackgroundTasks`; never raises.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_launch_service.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.models import Base, Item, Matter
from cvp.models_agent import AgentKey, AgentRun
from cvp.services import agent_launch
from cvp.services.agent_keys import generate_key


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def run_id(session_factory, monkeypatch):
    monkeypatch.setattr(agent_launch, "SessionLocal", session_factory)
    db = session_factory()
    m = Matter(firm_name="F")
    db.add(m)
    db.flush()
    item = Item(matter_id=m.id, description="chair", quantity=1)
    db.add(item)
    _, prefix, key_hash = generate_key()
    key = AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.flush()
    run = AgentRun(
        item_id=item.id,
        matter_id=m.id,
        agent_impl="custom-python",
        model_slug="anthropic/claude-haiku-4.5",
        agent_key_id=key.id,
    )
    db.add(run)
    db.commit()
    rid = run.id
    db.close()
    return rid


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_successful_launch_marks_running(run_id, session_factory, monkeypatch):
    captured = {}

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, content=None, headers=None):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return _Resp(202)

    monkeypatch.setattr(agent_launch.httpx, "Client", _Client)
    monkeypatch.setattr(agent_launch.settings, "cloudflare_agent_worker_url", "https://w.example")
    monkeypatch.setattr(agent_launch.settings, "cloudflare_launch_hmac_secret", "s3cret")

    agent_launch.launch_run(run_id)

    db = session_factory()
    run = db.get(AgentRun, run_id)
    assert run.status == "running"
    assert run.started_at is not None
    assert captured["url"] == "https://w.example/runs"
    assert "X-CVP-Signature" in captured["headers"]
    assert "X-CVP-Timestamp" in captured["headers"]
    # The launch payload must never carry credentials.
    assert "KEY" not in captured["content"]
    assert "secret" not in captured["content"].lower()
    db.close()


def test_non_2xx_marks_failed(run_id, session_factory, monkeypatch):
    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, content=None, headers=None):
            return _Resp(500, "boom")

    monkeypatch.setattr(agent_launch.httpx, "Client", _Client)
    monkeypatch.setattr(agent_launch.settings, "cloudflare_agent_worker_url", "https://w.example")
    monkeypatch.setattr(agent_launch.settings, "cloudflare_launch_hmac_secret", "s3cret")

    agent_launch.launch_run(run_id)

    db = session_factory()
    run = db.get(AgentRun, run_id)
    assert run.status == "failed"
    assert "500" in run.error
    db.close()


def test_unconfigured_worker_marks_failed(run_id, session_factory, monkeypatch):
    monkeypatch.setattr(agent_launch.settings, "cloudflare_agent_worker_url", "")

    agent_launch.launch_run(run_id)

    db = session_factory()
    run = db.get(AgentRun, run_id)
    assert run.status == "failed"
    assert "not configured" in run.error
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_launch_service.py -v`
Expected: FAIL with `AttributeError: module 'cvp.services.agent_launch' has no attribute 'launch_run'`

- [ ] **Step 3: Implement**

Add to `src/cvp/services/agent_launch.py` (extend the existing imports):

```python
import json
import logging
import time
from datetime import datetime, timezone

import httpx

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.models_agent import AgentRun

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0


def launch_run(run_id: str) -> None:
    """POST the launch to the Cloudflare Worker and transition the run.

    Runs in a BackgroundTask, so it owns its session and never raises —
    every failure is recorded on the run row where the UI can show it.
    """
    db = SessionLocal()
    try:
        run = db.get(AgentRun, run_id)
        if run is None:
            logger.warning("launch_run: no such run %s", run_id)
            return

        if not settings.cloudflare_agent_worker_url:
            _fail(db, run, "Cloudflare agent worker is not configured.")
            return

        body = json.dumps(
            {
                "run_id": run.id,
                "matter_id": run.matter_id,
                "item_id": run.item_id,
                "model_slug": run.model_slug,
                "agent_impl": run.agent_impl,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-CVP-Timestamp": timestamp,
            "X-CVP-Signature": sign_payload(
                settings.cloudflare_launch_hmac_secret, timestamp, body
            ),
        }
        url = f"{settings.cloudflare_agent_worker_url.rstrip('/')}/runs"

        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                response = client.post(url, content=body, headers=headers)
        except Exception as exc:  # noqa: BLE001
            logger.exception("launch_run: transport failure for %s", run_id)
            _fail(db, run, f"Could not reach the agent worker: {exc}")
            return

        if response.status_code >= 300:
            _fail(db, run, f"Worker returned {response.status_code}: {response.text[:200]}")
            return

        run.status = "running"
        run.started_at = datetime.now(tz=timezone.utc)
        db.commit()
    finally:
        db.close()


def _fail(db, run: AgentRun, message: str) -> None:
    run.status = "failed"
    run.error = message
    run.finished_at = datetime.now(tz=timezone.utc)
    db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_agent_launch_service.py -v`
Expected: 3 passed

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/services/agent_launch.py tests/test_agent_launch_service.py
git commit -m "feat(agent-runs): launch service with HMAC-signed worker POST"
```

---

### Task 6: Launch endpoint and guards

**Files:**
- Create: `src/cvp/routers/agent_runs.py`
- Modify: `src/cvp/main.py:18-37` (import) and `:98` (registration)
- Test: `tests/test_agent_runs_launch.py`

**Interfaces:**
- Consumes: `resolve_model` (Task 3), `launch_run` (Task 5), `AgentRun` (Task 2).
- Produces: `POST /api/items/{item_id}/agent-runs`; module-level `EDITOR` for test override by identity.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_runs_launch.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.db import get_db
from cvp.main import app
from cvp.models import Base, Item, Matter
from cvp.models_agent import AgentKey, AgentRun, AiRecommendation
from cvp.routers import agent_runs as agent_runs_router
from cvp.services.agent_keys import generate_key


@pytest.fixture
def ctx(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    m = Matter(firm_name="F")
    db.add(m)
    db.flush()
    item = Item(matter_id=m.id, description="chair", quantity=1)
    db.add(item)
    _, prefix, key_hash = generate_key()
    key = AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.commit()

    launched: list[str] = []
    monkeypatch.setattr(
        agent_runs_router.agent_launch, "launch_run", lambda rid: launched.append(rid)
    )
    monkeypatch.setattr(
        agent_runs_router.settings, "cloudflare_agent_key_id", key.id, raising=False
    )

    class _User:
        id = "u1"

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[agent_runs_router.EDITOR] = lambda: _User()
    yield TestClient(app), db, item.id, key.id, launched
    app.dependency_overrides.clear()
    db.close()


def test_launch_creates_queued_run(ctx):
    client, db, item_id, key_id, launched = ctx
    r = client.post(f"/api/items/{item_id}/agent-runs")
    assert r.status_code == 200

    run = db.query(AgentRun).one()
    assert run.status == "queued"
    assert run.item_id == item_id
    assert run.agent_key_id == key_id
    assert run.agent_impl == "custom-python"
    assert run.model_slug == "anthropic/claude-haiku-4.5"
    assert launched == [run.id]


def test_launch_rejects_disallowed_model(ctx):
    client, db, item_id, _key_id, launched = ctx
    r = client.post(
        f"/api/items/{item_id}/agent-runs", params={"model_slug": "evil/expensive"}
    )
    assert r.status_code == 400
    assert db.query(AgentRun).count() == 0
    assert launched == []


def test_launch_rejects_when_run_already_in_flight(ctx):
    client, db, item_id, key_id, launched = ctx
    db.add(
        AgentRun(
            item_id=item_id,
            matter_id=db.query(Item).first().matter_id,
            agent_impl="custom-python",
            model_slug="anthropic/claude-haiku-4.5",
            agent_key_id=key_id,
            status="running",
        )
    )
    db.commit()

    r = client.post(f"/api/items/{item_id}/agent-runs")
    assert r.status_code == 409
    assert launched == []


def test_launch_rejects_at_pending_cap(ctx):
    client, db, item_id, key_id, launched = ctx
    for _ in range(5):
        db.add(
            AiRecommendation(
                item_id=item_id,
                agent_key_id=key_id,
                proposed_retail_unit_cents=100,
                source_url="https://x.example/a",
                source_retailer="X",
                status="pending",
            )
        )
    db.commit()

    r = client.post(f"/api/items/{item_id}/agent-runs")
    assert r.status_code == 409
    assert db.query(AgentRun).count() == 0
    assert launched == []


def test_launch_404s_for_unknown_item(ctx):
    client, _db, _item_id, _key_id, _launched = ctx
    r = client.post("/api/items/does-not-exist/agent-runs")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_runs_launch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cvp.routers.agent_runs'`

- [ ] **Step 3: Implement the router**

Create `src/cvp/routers/agent_runs.py`:

```python
"""Per-item AI recommendation runs: launch, status polling, and agent progress.

Three routes with two different principals. Launch and status are session-authed
specialist actions; progress is called by the Cloudflare container with an
X-API-Key. Auth is declared per route rather than per file.
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, selectinload

from cvp.config import settings
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import Item
from cvp.models_agent import AgentRun
from cvp.services import agent_launch
from cvp.services.agent_models import resolve_model
from cvp.services.recommendation_feed import MAX_PENDING_PER_ITEM, pending_count

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["cents"] = lambda c: f"${c / 100:,.2f}" if c else "$0.00"

router = APIRouter()

# Single module-level dependency instance so tests can override it by identity.
EDITOR = require_matter_role("editor")

AGENT_IMPL = "custom-python"

#: Statuses that mean a run still occupies the item.
IN_FLIGHT = ("queued", "running", "searching", "submitting")


def _load_item(db: Session, item_id: str) -> Item:
    item = (
        db.query(Item)
        .options(selectinload(Item.ai_recommendations))
        .filter(Item.id == item_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.post("/api/items/{item_id}/agent-runs", response_class=HTMLResponse)
def launch(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    model_slug: str | None = Query(default=None),
    user: CurrentUser = Depends(EDITOR),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Create a run and hand the outbound POST to a background task.

    Every guard runs before anything leaves Railway: a bad model, a duplicate
    click, or an item already at the pending cap must not cost a container
    start and an LLM call.
    """
    item = _load_item(db, item_id)

    try:
        model = resolve_model(db, model_slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    in_flight = (
        db.query(AgentRun)
        .filter(AgentRun.item_id == item_id, AgentRun.status.in_(IN_FLIGHT))
        .first()
    )
    if in_flight is not None:
        raise HTTPException(status_code=409, detail="A recommendation run is already in progress.")

    if pending_count(db, item_id) >= MAX_PENDING_PER_ITEM:
        raise HTTPException(
            status_code=409,
            detail="This item already has the maximum number of pending recommendations.",
        )

    if not settings.cloudflare_agent_key_id:
        raise HTTPException(
            status_code=503, detail="No Cloudflare agent key is configured."
        )

    run = AgentRun(
        item_id=item.id,
        matter_id=item.matter_id,
        agent_impl=AGENT_IMPL,
        model_slug=model,
        agent_key_id=settings.cloudflare_agent_key_id,
        started_by_id=user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(agent_launch.launch_run, run.id)

    return HTMLResponse(
        templates.get_template("_agent_run_status.html").render(
            request=request, run=run, item=item, recommendations=[]
        )
    )
```

- [ ] **Step 4: Register the router**

In `src/cvp/main.py`, add `agent_runs` to the `from cvp.routers import (...)` block (alphabetical, after `agent`), and add after line 100:

```python
app.include_router(agent_runs.router)
```

- [ ] **Step 5: Create a minimal status template so the endpoint renders**

Create `src/cvp/templates/_agent_run_status.html` with a placeholder body; Task 8 replaces it in full:

```html
<div id="agent-run-{{ item.id }}" data-run-status="{{ run.status }}"></div>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_runs_launch.py -v`
Expected: 5 passed

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/agent_runs.py src/cvp/main.py src/cvp/templates/_agent_run_status.html tests/test_agent_runs_launch.py
git commit -m "feat(agent-runs): launch endpoint with model, in-flight, and pending-cap guards"
```

---

### Task 7: Progress endpoint

**Files:**
- Modify: `src/cvp/routers/agent_runs.py`
- Test: `tests/test_agent_runs_progress.py`

**Interfaces:**
- Consumes: `require_agent_key` → `AgentPrincipal` (existing, `src/cvp/agent_auth.py`).
- Produces: `POST /api/agent/runs/{run_id}/progress` accepting `ProgressIn`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_runs_progress.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.db import get_db
from cvp.main import app
from cvp.models import Base, Item, Matter
from cvp.models_agent import AgentKey, AgentRun
from cvp.services.agent_keys import generate_key


@pytest.fixture
def ctx():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    m = Matter(firm_name="F")
    db.add(m)
    db.flush()
    item = Item(matter_id=m.id, description="chair", quantity=1)
    db.add(item)

    mine_full, mine_prefix, mine_hash = generate_key()
    mine = AgentKey(name="cf", key_prefix=mine_prefix, key_hash=mine_hash)
    other_full, other_prefix, other_hash = generate_key()
    other = AgentKey(name="other", key_prefix=other_prefix, key_hash=other_hash)
    db.add_all([mine, other])
    db.flush()

    run = AgentRun(
        item_id=item.id,
        matter_id=m.id,
        agent_impl="custom-python",
        model_slug="anthropic/claude-haiku-4.5",
        agent_key_id=mine.id,
        status="running",
    )
    db.add(run)
    db.commit()

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app), db, run.id, mine_full, other_full
    app.dependency_overrides.clear()
    db.close()


def test_progress_updates_status_and_message(ctx):
    client, db, run_id, key, _other = ctx
    r = client.post(
        f"/api/agent/runs/{run_id}/progress",
        json={"status": "searching", "message": "Looking for retail matches…"},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    db.expire_all()
    run = db.get(AgentRun, run_id)
    assert run.status == "searching"
    assert run.status_message == "Looking for retail matches…"
    assert run.finished_at is None


def test_terminal_success_records_telemetry(ctx):
    client, db, run_id, key, _other = ctx
    r = client.post(
        f"/api/agent/runs/{run_id}/progress",
        json={
            "status": "succeeded",
            "agent_impl": "custom-python",
            "image_tag": "a1b2c3d",
            "model_slug": "anthropic/claude-haiku-4.5",
            "cost_micro_usd": 9835,
            "latency_ms": 3521,
            "browser_run_used": False,
        },
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    db.expire_all()
    run = db.get(AgentRun, run_id)
    assert run.status == "succeeded"
    assert run.cost_micro_usd == 9835
    assert run.latency_ms == 3521
    assert run.image_tag == "a1b2c3d"
    assert run.finished_at is not None


def test_progress_rejects_missing_key(ctx):
    client, _db, run_id, _key, _other = ctx
    r = client.post(f"/api/agent/runs/{run_id}/progress", json={"status": "running"})
    assert r.status_code == 401


def test_progress_rejects_another_principals_run(ctx):
    client, _db, run_id, _key, other = ctx
    r = client.post(
        f"/api/agent/runs/{run_id}/progress",
        json={"status": "running"},
        headers={"X-API-Key": other},
    )
    assert r.status_code == 403


def test_progress_rejected_after_terminal(ctx):
    client, db, run_id, key, _other = ctx
    run = db.get(AgentRun, run_id)
    run.status = "succeeded"
    db.commit()

    r = client.post(
        f"/api/agent/runs/{run_id}/progress",
        json={"status": "running"},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 409


def test_progress_rejects_unknown_status(ctx):
    client, _db, run_id, key, _other = ctx
    r = client.post(
        f"/api/agent/runs/{run_id}/progress",
        json={"status": "bogus"},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_runs_progress.py -v`
Expected: FAIL — all six return 404 because the route does not exist

- [ ] **Step 3: Implement**

Add to `src/cvp/routers/agent_runs.py`. Extend imports with:

```python
from pydantic import BaseModel, Field, field_validator

from cvp.agent_auth import AgentPrincipal, require_agent_key
```

Then append:

```python
_VALID_STATUSES = (
    "queued",
    "running",
    "searching",
    "submitting",
    "succeeded",
    "failed",
)


class ProgressIn(BaseModel):
    """A progress report from the container. Terminal reports carry telemetry."""

    status: str
    message: str | None = None
    error: str | None = None
    agent_impl: str | None = None
    image_tag: str | None = None
    model_slug: str | None = None
    cost_micro_usd: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    browser_run_used: bool | None = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, v: str) -> str:
        if v not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {_VALID_STATUSES}")
        return v


@router.post("/api/agent/runs/{run_id}/progress")
def progress(
    run_id: str,
    body: ProgressIn,
    principal: AgentPrincipal = Depends(require_agent_key),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Record progress from the container.

    The run is bound to an agent key at creation, so this is a strict equality
    check — a valid key must not be able to write progress onto another
    principal's run.
    """
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.agent_key_id != principal.agent_key_id:
        raise HTTPException(status_code=403, detail="Run belongs to another agent key")
    if run.status in AgentRun.TERMINAL:
        raise HTTPException(status_code=409, detail="Run has already finished")

    run.status = body.status
    if body.message is not None:
        run.status_message = body.message
    if body.error is not None:
        run.error = body.error
    # Telemetry is reported by the image, so it describes what actually ran.
    if body.image_tag is not None:
        run.image_tag = body.image_tag
    if body.agent_impl is not None:
        run.agent_impl = body.agent_impl
    if body.model_slug is not None:
        run.model_slug = body.model_slug
    if body.cost_micro_usd is not None:
        run.cost_micro_usd = body.cost_micro_usd
    if body.latency_ms is not None:
        run.latency_ms = body.latency_ms
    if body.browser_run_used is not None:
        run.browser_run_used = body.browser_run_used

    if body.status in AgentRun.TERMINAL:
        run.finished_at = datetime.now(tz=timezone.utc)

    db.commit()
    return {"status": run.status}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_runs_progress.py -v`
Expected: 6 passed

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/agent_runs.py tests/test_agent_runs_progress.py
git commit -m "feat(agent-runs): agent progress endpoint with per-run key binding"
```

---

### Task 8: Status partial and polling

**Files:**
- Modify: `src/cvp/templates/_agent_run_status.html` (replace the Task 6 placeholder)
- Modify: `src/cvp/routers/agent_runs.py`
- Test: `tests/test_agent_run_status_ui.py`

**Interfaces:**
- Produces: `GET /api/items/{item_id}/agent-runs/{run_id}` rendering `_agent_run_status.html`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_run_status_ui.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.db import get_db
from cvp.main import app
from cvp.models import Base, Item, Matter
from cvp.models_agent import AgentKey, AgentRun
from cvp.routers import agent_runs as agent_runs_router
from cvp.services.agent_keys import generate_key


@pytest.fixture
def ctx():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    m = Matter(firm_name="F")
    db.add(m)
    db.flush()
    item = Item(matter_id=m.id, description="chair", quantity=1)
    db.add(item)
    _, prefix, key_hash = generate_key()
    key = AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.flush()
    run = AgentRun(
        item_id=item.id,
        matter_id=m.id,
        agent_impl="custom-python",
        model_slug="anthropic/claude-haiku-4.5",
        agent_key_id=key.id,
        status="searching",
        status_message="Looking for retail matches…",
    )
    db.add(run)
    db.commit()

    class _User:
        id = "u1"

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[agent_runs_router.EDITOR] = lambda: _User()
    yield TestClient(app), db, item.id, run.id
    app.dependency_overrides.clear()
    db.close()


def test_running_state_polls(ctx):
    client, _db, item_id, run_id = ctx
    html = client.get(f"/api/items/{item_id}/agent-runs/{run_id}").text
    assert 'hx-trigger="every 2s"' in html
    assert f"/api/items/{item_id}/agent-runs/{run_id}" in html
    assert "Looking for retail matches" in html


def test_terminal_state_stops_polling(ctx):
    client, db, item_id, run_id = ctx
    run = db.get(AgentRun, run_id)
    run.status = "succeeded"
    db.commit()

    html = client.get(f"/api/items/{item_id}/agent-runs/{run_id}").text
    assert "hx-trigger" not in html


def test_success_swaps_recommendations_out_of_band(ctx):
    client, db, item_id, run_id = ctx
    run = db.get(AgentRun, run_id)
    run.status = "succeeded"
    db.commit()

    html = client.get(f"/api/items/{item_id}/agent-runs/{run_id}").text
    assert 'hx-swap-oob="true"' in html
    assert f'id="ai-recs-{item_id}"' in html


def test_failed_state_shows_error(ctx):
    client, db, item_id, run_id = ctx
    run = db.get(AgentRun, run_id)
    run.status = "failed"
    run.error = "Worker returned 500"
    db.commit()

    html = client.get(f"/api/items/{item_id}/agent-runs/{run_id}").text
    assert "Worker returned 500" in html
    assert "hx-trigger" not in html


def test_no_inline_event_handlers(ctx):
    """CSP script-src has no unsafe-inline; inline handlers are hard-blocked."""
    client, _db, item_id, run_id = ctx
    html = client.get(f"/api/items/{item_id}/agent-runs/{run_id}").text
    for handler in ("onclick=", "onchange=", "onsubmit=", "onload="):
        assert handler not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_run_status_ui.py -v`
Expected: FAIL — the GET route returns 404

- [ ] **Step 3: Add the status route**

Append to `src/cvp/routers/agent_runs.py`:

```python
@router.get("/api/items/{item_id}/agent-runs/{run_id}", response_class=HTMLResponse)
def status(
    request: Request,
    item_id: str,
    run_id: str,
    user: CurrentUser = Depends(EDITOR),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render the polling partial. Stops polling once the run is terminal."""
    item = _load_item(db, item_id)
    run = db.get(AgentRun, run_id)
    if run is None or run.item_id != item_id:
        raise HTTPException(status_code=404, detail="Run not found")

    recommendations = [r for r in item.ai_recommendations if r.status == "pending"]
    return HTMLResponse(
        templates.get_template("_agent_run_status.html").render(
            request=request, run=run, item=item, recommendations=recommendations
        )
    )
```

- [ ] **Step 4: Write the full template**

Replace `src/cvp/templates/_agent_run_status.html` entirely:

```html
{# Polling status for one agent run. Modeled on _scan_progress.html: the
   element re-fetches itself while the run is live and simply stops emitting
   hx-trigger once terminal. No JavaScript — CSP forbids inline handlers and
   connect-src is 'self', so a direct socket to the Worker is not an option. #}
{% set terminal = run.status in ["succeeded", "failed"] %}
{% set labels = {
     "queued": "Queued",
     "running": "Starting…",
     "searching": "Searching retailers…",
     "submitting": "Submitting…",
     "succeeded": "Done",
     "failed": "Failed",
   } %}
<div id="agent-run-{{ item.id }}"
     data-run-status="{{ run.status }}"
     {% if not terminal %}
     hx-get="/api/items/{{ item.id }}/agent-runs/{{ run.id }}"
     hx-trigger="every 2s"
     hx-target="this"
     hx-swap="outerHTML"
     {% endif %}
     class="mt-2 rounded border p-2 text-xs
            {% if run.status == 'failed' %}border-red-200 bg-red-50 text-red-700
            {% elif run.status == 'succeeded' %}border-green-200 bg-green-50 text-green-700
            {% else %}border-indigo-200 bg-indigo-50 text-indigo-700{% endif %}">

  <div class="flex items-center justify-between">
    <span class="font-medium">{{ labels.get(run.status, run.status) }}</span>
    {% if not terminal %}<span class="animate-pulse">●</span>
    {% elif run.status == "succeeded" %}<span>✓</span>
    {% else %}<span>⚠</span>{% endif %}
  </div>

  {% if run.status_message and not terminal %}
    <p class="mt-1 text-gray-600">{{ run.status_message }}</p>
  {% endif %}

  {% if run.status == "failed" and run.error %}
    <p class="mt-1">{{ run.error }}</p>
  {% endif %}

  {% if terminal %}
    <p class="mt-1 text-gray-500">
      {{ run.model_slug }} · {{ run.agent_impl }}
      {%- if run.latency_ms %} · {{ (run.latency_ms / 1000) | round(1) }}s{% endif %}
    </p>
  {% endif %}
</div>

{# On success, refresh the recommendations list in place rather than making the
   specialist reload the page. #}
{% if run.status == "succeeded" %}
<div id="ai-recs-{{ item.id }}" hx-swap-oob="true">
  {% include "_ai_recommendations.html" %}
</div>
{% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_run_status_ui.py -v`
Expected: 5 passed

- [ ] **Step 6: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/routers/agent_runs.py src/cvp/templates/_agent_run_status.html tests/test_agent_run_status_ui.py
git commit -m "feat(agent-runs): polling status partial with OOB recommendation refresh"
```

---

### Task 9: The button in the item edit row

**Files:**
- Modify: `src/cvp/templates/_item_row_edit.html` (insert before the Web search block at line ~283)
- Modify: `src/cvp/routers/items.py` (add `latest_agent_run` to the edit-row context)
- Test: `tests/test_item_edit_agent_button.py`

- [ ] **Step 1: Find the edit-row context builder**

Run: `grep -n "firecrawl_configured\|default_query" src/cvp/routers/items.py`

Note the function that builds the edit-row template context — the new key goes in the same dict.

- [ ] **Step 2: Write the failing test**

Create `tests/test_item_edit_agent_button.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.db import get_db
from cvp.main import app
from cvp.models import Base, Item, Matter
from cvp.models_agent import AgentKey, AgentRun
from cvp.routers import items as items_router
from cvp.services.agent_keys import generate_key


@pytest.fixture
def ctx():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    m = Matter(firm_name="F")
    db.add(m)
    db.flush()
    item = Item(matter_id=m.id, description="chair", quantity=1)
    db.add(item)
    _, prefix, key_hash = generate_key()
    db.add(AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash))
    db.commit()

    class _User:
        id = "u1"

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[items_router.EDITOR] = lambda: _User()
    yield TestClient(app), db, item.id
    app.dependency_overrides.clear()
    db.close()


def test_edit_row_renders_launch_button(ctx):
    client, _db, item_id = ctx
    html = client.get(f"/api/items/{item_id}/edit").text
    assert "Get AI Recommendations" in html
    assert f'hx-post="/api/items/{item_id}/agent-runs"' in html


def test_edit_row_has_no_inline_handlers(ctx):
    client, _db, item_id = ctx
    html = client.get(f"/api/items/{item_id}/edit").text
    for handler in ("onclick=", "onchange=", "onsubmit="):
        assert handler not in html


def test_edit_row_shows_existing_run_status(ctx):
    client, db, item_id = ctx
    key = db.query(AgentKey).first()
    item = db.get(Item, item_id)
    db.add(
        AgentRun(
            item_id=item_id,
            matter_id=item.matter_id,
            agent_impl="custom-python",
            model_slug="anthropic/claude-haiku-4.5",
            agent_key_id=key.id,
            status="searching",
            status_message="Looking for retail matches…",
        )
    )
    db.commit()

    html = client.get(f"/api/items/{item_id}/edit").text
    assert "Looking for retail matches" in html
    assert 'hx-trigger="every 2s"' in html
```

> **Note:** confirm the edit-row URL with
> `grep -n '"/api/items/{item_id}/edit"' src/cvp/routers/items.py` and adjust
> the three requests above if the real route differs.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_item_edit_agent_button.py -v`
Expected: FAIL — `"Get AI Recommendations" not in html`

- [ ] **Step 4: Add the context key**

In the edit-row context dict in `src/cvp/routers/items.py`, alongside `firecrawl_configured`, add:

```python
        "latest_agent_run": (
            db.query(AgentRun)
            .filter(AgentRun.item_id == item.id)
            .order_by(AgentRun.created_at.desc())
            .first()
        ),
```

and import at the top of the file:

```python
from cvp.models_agent import AgentRun
```

- [ ] **Step 5: Add the template section**

In `src/cvp/templates/_item_row_edit.html`, immediately **before** the
`{# ── Web search (Firecrawl) ──` comment block, insert:

```html
    {# ── AI Recommendations ─────────────────────────────────────────────
       One click launches a single ephemeral Cloudflare agent for this item.
       Status polls via _agent_run_status.html; no JavaScript is involved. #}
    <div class="mt-3 border-t border-indigo-100 pt-3">
      <p class="text-xs font-semibold text-gray-600 mb-2">AI Recommendations</p>

      <form hx-post="/api/items/{{ item.id }}/agent-runs"
            hx-target="#agent-run-{{ item.id }}"
            hx-swap="outerHTML"
            hx-disabled-elt="find button[type='submit']"
            class="flex items-center gap-2">
        <button type="submit"
                class="text-xs px-3 py-1.5 rounded text-white whitespace-nowrap
                       bg-indigo-600 hover:bg-indigo-700">
          Get AI Recommendations
        </button>
      </form>

      {% if latest_agent_run %}
        {% set run = latest_agent_run %}
        {% include "_agent_run_status.html" %}
      {% else %}
        <div id="agent-run-{{ item.id }}"></div>
      {% endif %}
    </div>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_item_edit_agent_button.py -v`
Expected: 3 passed

- [ ] **Step 7: Run the whole suite — this task touches a shared template**

Run: `uv run pytest -q`
Expected: no new failures. `cvp-legacy` has one known pre-existing vision test failure; anything beyond that is yours.

- [ ] **Step 8: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/templates/_item_row_edit.html src/cvp/routers/items.py tests/test_item_edit_agent_button.py
git commit -m "feat(agent-runs): Get AI Recommendations button on the item edit row"
```

---

### Task 10: Stale-run sweeper

An ephemeral container that dies leaves its row `running` forever, and CVP cannot interrogate Cloudflare to find out. Mirrors `vision_worker.recover_stale_jobs()`.

**Files:**
- Create: `src/cvp/services/agent_run_sweeper.py`
- Modify: `src/cvp/main.py` (lifespan startup)
- Test: `tests/test_agent_run_sweeper.py`

**Interfaces:**
- Produces: `sweep_stale_runs(db: Session, *, older_than_minutes: int) -> int` returning the number reaped.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_run_sweeper.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.models import Base, Item, Matter
from cvp.models_agent import AgentKey, AgentRun
from cvp.services.agent_keys import generate_key
from cvp.services.agent_run_sweeper import sweep_stale_runs


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _make_run(db, *, status: str, age_minutes: int) -> AgentRun:
    m = Matter(firm_name="F")
    db.add(m)
    db.flush()
    item = Item(matter_id=m.id, description="chair", quantity=1)
    db.add(item)
    _, prefix, key_hash = generate_key()
    key = AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.flush()
    run = AgentRun(
        item_id=item.id,
        matter_id=m.id,
        agent_impl="custom-python",
        model_slug="anthropic/claude-haiku-4.5",
        agent_key_id=key.id,
        status=status,
        created_at=datetime.now(tz=timezone.utc) - timedelta(minutes=age_minutes),
    )
    db.add(run)
    db.commit()
    return run


def test_old_running_run_is_failed(db):
    run = _make_run(db, status="running", age_minutes=60)
    assert sweep_stale_runs(db, older_than_minutes=15) == 1
    db.refresh(run)
    assert run.status == "failed"
    assert "timed out" in run.error
    assert run.finished_at is not None


def test_recent_run_is_left_alone(db):
    run = _make_run(db, status="running", age_minutes=2)
    assert sweep_stale_runs(db, older_than_minutes=15) == 0
    db.refresh(run)
    assert run.status == "running"


def test_terminal_run_is_left_alone(db):
    run = _make_run(db, status="succeeded", age_minutes=60)
    assert sweep_stale_runs(db, older_than_minutes=15) == 0
    db.refresh(run)
    assert run.status == "succeeded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_run_sweeper.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `src/cvp/services/agent_run_sweeper.py`:

```python
"""Reap agent runs whose container never reported a terminal status.

Storage on Cloudflare is ephemeral and logs live there, so CVP cannot ask a
dead container what happened — it can only notice that nothing arrived.
Mirrors `vision_worker.recover_stale_jobs()`.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from cvp.models_agent import AgentRun

logger = logging.getLogger(__name__)


def sweep_stale_runs(db: Session, *, older_than_minutes: int) -> int:
    """Mark non-terminal runs older than the cutoff as failed. Returns the count."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=older_than_minutes)
    stale = (
        db.query(AgentRun)
        .filter(AgentRun.status.notin_(tuple(AgentRun.TERMINAL)), AgentRun.created_at < cutoff)
        .all()
    )
    for run in stale:
        run.status = "failed"
        run.error = f"Agent run timed out after {older_than_minutes} minutes with no response."
        run.finished_at = datetime.now(tz=timezone.utc)
    if stale:
        db.commit()
        logger.info("agent_run_sweeper: reaped %d stale runs", len(stale))
    return len(stale)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_run_sweeper.py -v`
Expected: 3 passed

- [ ] **Step 5: Call it on startup**

Find the lifespan function in `src/cvp/main.py` (it already calls `vision_worker.recover_stale_jobs()`), and add alongside:

```python
    from cvp.db import SessionLocal
    from cvp.services.agent_run_sweeper import sweep_stale_runs

    _db = SessionLocal()
    try:
        sweep_stale_runs(_db, older_than_minutes=settings.agent_run_stale_minutes)
    finally:
        _db.close()
```

- [ ] **Step 6: Verify the app still boots**

Run: `uv run python -c "import cvp.main; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add src/cvp/services/agent_run_sweeper.py src/cvp/main.py tests/test_agent_run_sweeper.py
git commit -m "feat(agent-runs): reap stale runs on startup"
```

---

### Task 11: Container search helper

**Files:**
- Create: `cloudflare/images/shared/search.py`
- Test: `tests/test_container_search.py`

**Interfaces:**
- Produces: `SearchResult` dataclass (`product_title, price_usd, retailer, source_url, match_type, rationale`), `search_for_item(...) -> tuple[SearchResult | None, int, bool]` returning `(result, cost_micro_usd, browser_run_used)`, and `dollars_to_cents(amount) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_container_search.py`:

```python
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare" / "images" / "shared"))

import search  # noqa: E402


def test_dollars_to_cents_is_half_up_and_integral():
    assert search.dollars_to_cents("129.99") == 12999
    assert search.dollars_to_cents("0.005") == 1
    assert search.dollars_to_cents(3.97) == 397
    assert isinstance(search.dollars_to_cents("1.00"), int)


def test_cost_is_converted_to_micro_usd():
    assert search.usd_to_micro(0.009835) == 9835
    assert search.usd_to_micro(0) == 0


def test_parses_fenced_json_reply(monkeypatch):
    payload = {
        "choices": [
            {
                "message": {
                    "content": (
                        '```json\n{"product_title":"Chair","price_usd":1249.0,'
                        '"retailer":"Stickley","source_url":"https://s.example/c",'
                        '"match_type":"brand","rationale":"why"}\n```'
                    )
                }
            }
        ],
        "usage": {"cost": 0.009835},
    }
    monkeypatch.setattr(search, "_post_openrouter", lambda *a, **k: payload)

    result, cost, used_browser = search.search_for_item(
        description="oak dining chair",
        brand="Stickley",
        model=None,
        model_slug="anthropic/claude-haiku-4.5",
        openrouter_key="k",
        browser_account_id="",
        browser_token="",
    )

    assert result.product_title == "Chair"
    assert result.source_url == "https://s.example/c"
    assert result.match_type == "brand"
    assert cost == 9835
    assert used_browser is False


def test_returns_none_when_model_finds_nothing(monkeypatch):
    payload = {"choices": [{"message": {"content": "no match found"}}], "usage": {"cost": 0.001}}
    monkeypatch.setattr(search, "_post_openrouter", lambda *a, **k: payload)

    result, cost, _ = search.search_for_item(
        description="x",
        brand=None,
        model=None,
        model_slug="anthropic/claude-haiku-4.5",
        openrouter_key="k",
        browser_account_id="",
        browser_token="",
    )
    assert result is None
    assert cost == 1000


def test_rejects_result_missing_source_url(monkeypatch):
    """Every RCV must have a source — an unsourced match is not a match."""
    payload = {
        "choices": [
            {"message": {"content": json.dumps({"product_title": "C", "price_usd": 10.0})}}
        ],
        "usage": {"cost": 0.001},
    }
    monkeypatch.setattr(search, "_post_openrouter", lambda *a, **k: payload)

    result, _cost, _ = search.search_for_item(
        description="x",
        brand=None,
        model=None,
        model_slug="anthropic/claude-haiku-4.5",
        openrouter_key="k",
        browser_account_id="",
        browser_token="",
    )
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_container_search.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'search'`

- [ ] **Step 3: Implement**

Create `cloudflare/images/shared/search.py`:

```python
"""Find one purchasable retail match for an item.

One OpenRouter call with the web-search plugin does search and reasoning
together. Measured on 2026-09-10: ~$0.0098 per call at five results, of which
only ~$0.0028 is inference — search dominates, so result count matters far more
than model choice.

Blocked retailer pages escalate to a Cloudflare Browser Run Quick Action rather
than shipping a browser in this image.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_TIMEOUT_SECONDS = 120.0
_MAX_RESULTS = 5

PROMPT = (
    "You are pricing an item for a first-party property insurance claim. "
    "Find ONE currently-purchasable retail match for: {query}. "
    "Reply with ONLY a JSON object with keys: product_title, price_usd, "
    "retailer, source_url, match_type (exact or brand), rationale. "
    "source_url must be the real product page you found. "
    "If you cannot find a match, reply exactly: no match found"
)


@dataclass
class SearchResult:
    product_title: str
    price_usd: float
    retailer: str
    source_url: str
    match_type: str
    rationale: str


def dollars_to_cents(amount: str | int | float | Decimal) -> int:
    """Convert dollars to integer cents, half-up. Currency is never a float."""
    cents = (Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def usd_to_micro(amount: float) -> int:
    """Convert a USD cost to integer micro-USD (see spec 5.1)."""
    return int(
        (Decimal(str(amount)) * 1_000_000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def build_query(description: str, brand: str | None, model: str | None) -> str:
    parts = [brand, model, description]
    cleaned = [re.sub(r"\s+", " ", p).strip() for p in parts if p and p.strip()]
    return " ".join(cleaned)


def _post_openrouter(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    """Split out so tests can substitute a payload without a network call."""
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        response = client.post(url, headers=headers, json=body)
    response.raise_for_status()
    return response.json()


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull a JSON object out of a reply that may be fenced or prose-wrapped."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = fenced.group(1) if fenced else None
    if raw is None:
        bare = re.search(r"\{.*\}", text, re.DOTALL)
        raw = bare.group(0) if bare else None
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def search_for_item(
    *,
    description: str,
    brand: str | None,
    model: str | None,
    model_slug: str,
    openrouter_key: str,
    browser_account_id: str,
    browser_token: str,
) -> tuple[SearchResult | None, int, bool]:
    """Return (result, cost_micro_usd, browser_run_used).

    A result missing a usable source_url or price is discarded: every RCV must
    carry a source, so an unsourced match is not a match.
    """
    query = build_query(description, brand, model)
    body = {
        "model": model_slug,
        "max_tokens": 1200,
        "plugins": [{"id": "web", "max_results": _MAX_RESULTS}],
        "usage": {"include": True},
        "messages": [{"role": "user", "content": PROMPT.format(query=query)}],
    }
    headers = {
        "Authorization": f"Bearer {openrouter_key}",
        "Content-Type": "application/json",
    }

    data = _post_openrouter(OPENROUTER_URL, headers, body)
    cost_micro = usd_to_micro((data.get("usage") or {}).get("cost") or 0)

    choices = data.get("choices") or []
    content = choices[0].get("message", {}).get("content", "") if choices else ""

    parsed = _extract_json(content)
    if not parsed:
        return None, cost_micro, False

    source_url = str(parsed.get("source_url") or "").strip()
    retailer = str(parsed.get("retailer") or "").strip()
    price = parsed.get("price_usd")
    if not source_url or not retailer or price is None:
        return None, cost_micro, False

    match_type = str(parsed.get("match_type") or "exact").strip().lower()
    if match_type not in ("exact", "brand"):
        match_type = "brand"

    return (
        SearchResult(
            product_title=str(parsed.get("product_title") or "").strip(),
            price_usd=float(price),
            retailer=retailer,
            source_url=source_url,
            match_type=match_type,
            rationale=str(parsed.get("rationale") or "").strip(),
        ),
        cost_micro,
        False,
    )


def fetch_blocked_page(account_id: str, token: str, url: str) -> str:
    """Fetch a bot-blocked page as markdown via a Browser Run Quick Action.

    Quick Actions are plain REST — no Puppeteer session and no Workers binding,
    which is why this image ships no browser. Paid-plan limit is 30 req/s.
    """
    endpoint = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        f"/browser-rendering/markdown"
    )
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        response = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            json={"url": url},
        )
    response.raise_for_status()
    return (response.json() or {}).get("result", "")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_container_search.py -v`
Expected: 5 passed

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add cloudflare/images/shared/search.py tests/test_container_search.py
git commit -m "feat(agent-runs): container search helper over OpenRouter web plugin"
```

---

### Task 12: Container runner — the contract implementation

The runner owns progress, validation, submission, and telemetry. The agent proposes; the runner disposes. This is what keeps the audit-trail invariants in code we control and keeps `CVP_AGENT_KEY` out of any model-reachable surface.

**Files:**
- Create: `cloudflare/images/shared/runner.py`
- Test: `tests/test_container_runner.py`

**Interfaces:**
- Consumes: `search.search_for_item`, `search.dollars_to_cents` (Task 11).
- Produces: `Config.from_env()`, `post_progress(cfg, status, **fields)`, `run(cfg) -> int` (process exit code).

- [ ] **Step 1: Write the failing test**

Create `tests/test_container_runner.py`:

```python
import sys
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parents[1] / "cloudflare" / "images" / "shared"
sys.path.insert(0, str(SHARED))

import runner  # noqa: E402
import search  # noqa: E402


@pytest.fixture
def cfg(monkeypatch):
    for k, v in {
        "RUN_ID": "run-1",
        "MATTER_ID": "m-1",
        "ITEM_ID": "item-1",
        "MODEL_SLUG": "anthropic/claude-haiku-4.5",
        "CVP_BASE_URL": "https://cvp.example",
        "CVP_AGENT_KEY": "agk_live_x_y",
        "OPENROUTER_API_KEY": "or-key",
        "BROWSER_RUN_ACCOUNT_ID": "acct",
        "BROWSER_RUN_TOKEN": "tok",
        "AGENT_IMPL": "custom-python",
        "IMAGE_TAG": "a1b2c3d",
    }.items():
        monkeypatch.setenv(k, v)
    return runner.Config.from_env()


def test_config_reads_env(cfg):
    assert cfg.run_id == "run-1"
    assert cfg.image_tag == "a1b2c3d"
    assert cfg.agent_impl == "custom-python"


def test_successful_run_submits_and_reports(cfg, monkeypatch):
    progress: list[dict] = []
    submitted: list[dict] = []

    monkeypatch.setattr(runner, "_post_progress_raw", lambda c, b: progress.append(b))
    monkeypatch.setattr(runner, "_fetch_item", lambda c: {"description": "chair", "brand": "S", "model": None})
    monkeypatch.setattr(runner, "_submit_recommendation", lambda c, b: submitted.append(b))
    monkeypatch.setattr(
        runner.search,
        "search_for_item",
        lambda **kw: (
            search.SearchResult("Chair", 129.99, "Shop", "https://s.example/c", "exact", "why"),
            9835,
            False,
        ),
    )

    assert runner.run(cfg) == 0

    assert submitted == [
        {
            "proposed_retail_unit_cents": 12999,
            "proposed_shipping_cents": 0,
            "source_url": "https://s.example/c",
            "source_retailer": "Shop",
            "match_type": "exact",
            "product_title": "Chair",
            "rationale": "why",
        }
    ]
    assert progress[-1]["status"] == "succeeded"
    assert progress[-1]["cost_micro_usd"] == 9835
    assert progress[-1]["image_tag"] == "a1b2c3d"
    assert progress[-1]["browser_run_used"] is False
    assert [p["status"] for p in progress[:-1]] == ["running", "searching", "submitting"]


def test_no_match_reports_failed_and_submits_nothing(cfg, monkeypatch):
    progress: list[dict] = []
    submitted: list[dict] = []
    monkeypatch.setattr(runner, "_post_progress_raw", lambda c, b: progress.append(b))
    monkeypatch.setattr(runner, "_fetch_item", lambda c: {"description": "chair", "brand": None, "model": None})
    monkeypatch.setattr(runner, "_submit_recommendation", lambda c, b: submitted.append(b))
    monkeypatch.setattr(runner.search, "search_for_item", lambda **kw: (None, 1000, False))

    assert runner.run(cfg) == 1
    assert submitted == []
    assert progress[-1]["status"] == "failed"
    assert "no match" in progress[-1]["error"].lower()


def test_exception_still_reports_terminal_status(cfg, monkeypatch):
    """The container must always post a terminal status, in a finally."""
    progress: list[dict] = []
    monkeypatch.setattr(runner, "_post_progress_raw", lambda c, b: progress.append(b))
    monkeypatch.setattr(runner, "_fetch_item", lambda c: {"description": "chair", "brand": None, "model": None})

    def _boom(**kw):
        raise RuntimeError("openrouter exploded")

    monkeypatch.setattr(runner.search, "search_for_item", _boom)

    assert runner.run(cfg) == 1
    assert progress[-1]["status"] == "failed"
    assert "openrouter exploded" in progress[-1]["error"]


def test_unsourced_result_is_never_submitted(cfg, monkeypatch):
    """Defence in depth: the runner validates even if search returns junk."""
    progress: list[dict] = []
    submitted: list[dict] = []
    monkeypatch.setattr(runner, "_post_progress_raw", lambda c, b: progress.append(b))
    monkeypatch.setattr(runner, "_fetch_item", lambda c: {"description": "chair", "brand": None, "model": None})
    monkeypatch.setattr(runner, "_submit_recommendation", lambda c, b: submitted.append(b))
    monkeypatch.setattr(
        runner.search,
        "search_for_item",
        lambda **kw: (search.SearchResult("C", 10.0, "", "", "exact", ""), 500, False),
    )

    assert runner.run(cfg) == 1
    assert submitted == []
    assert progress[-1]["status"] == "failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_container_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'runner'`

- [ ] **Step 3: Implement**

Create `cloudflare/images/shared/runner.py`:

```python
"""Container entrypoint: run one pricing agent for one item, then exit.

The agent proposes and this runner disposes. The model returns a structured
match; this module validates it against the skill's invariants and performs the
submission itself. That keeps the audit-trail rules in code rather than in
prose the model may ignore, and means CVP_AGENT_KEY never has to be reachable
from a model-driven tool surface.

Invariant: a terminal status is always posted, even on crash.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass

import httpx
import search

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("runner")

_TIMEOUT_SECONDS = 30.0


@dataclass
class Config:
    run_id: str
    matter_id: str
    item_id: str
    model_slug: str
    cvp_base_url: str
    cvp_agent_key: str
    openrouter_api_key: str
    browser_account_id: str
    browser_token: str
    agent_impl: str
    image_tag: str

    @classmethod
    def from_env(cls) -> "Config":
        def need(name: str) -> str:
            value = os.environ.get(name, "")
            if not value:
                raise SystemExit(f"missing required env var {name}")
            return value

        return cls(
            run_id=need("RUN_ID"),
            matter_id=os.environ.get("MATTER_ID", ""),
            item_id=need("ITEM_ID"),
            model_slug=need("MODEL_SLUG"),
            cvp_base_url=need("CVP_BASE_URL").rstrip("/"),
            cvp_agent_key=need("CVP_AGENT_KEY"),
            openrouter_api_key=need("OPENROUTER_API_KEY"),
            browser_account_id=os.environ.get("BROWSER_RUN_ACCOUNT_ID", ""),
            browser_token=os.environ.get("BROWSER_RUN_TOKEN", ""),
            # Baked into the image, not injected, so telemetry describes what
            # actually ran rather than what the Worker believed it launched.
            agent_impl=os.environ.get("AGENT_IMPL", "custom-python"),
            image_tag=os.environ.get("IMAGE_TAG", "unknown"),
        )


def _headers(cfg: Config) -> dict[str, str]:
    return {"X-API-Key": cfg.cvp_agent_key, "Content-Type": "application/json"}


def _post_progress_raw(cfg: Config, body: dict) -> None:
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        client.post(
            f"{cfg.cvp_base_url}/api/agent/runs/{cfg.run_id}/progress",
            headers=_headers(cfg),
            json=body,
        )


def post_progress(cfg: Config, status: str, **fields) -> None:
    """Best-effort progress report. Never raises — losing a progress ping must
    not kill a run that is otherwise fine; the CVP sweeper is the backstop."""
    body = {"status": status, **fields}
    try:
        _post_progress_raw(cfg, body)
    except Exception:  # noqa: BLE001
        logger.warning("progress post failed for status=%s", status, exc_info=True)


def _fetch_item(cfg: Config) -> dict:
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        response = client.get(
            f"{cfg.cvp_base_url}/api/agent/items/{cfg.item_id}", headers=_headers(cfg)
        )
    response.raise_for_status()
    return response.json()


def _submit_recommendation(cfg: Config, body: dict) -> None:
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{cfg.cvp_base_url}/api/agent/items/{cfg.item_id}/recommendations",
            headers=_headers(cfg),
            json=body,
        )
    response.raise_for_status()


def run(cfg: Config) -> int:
    """Execute one run. Returns a process exit code."""
    started = time.monotonic()
    cost_micro = 0
    used_browser = False
    error: str | None = None

    try:
        post_progress(cfg, "running", message="Starting…")
        item = _fetch_item(cfg)

        post_progress(cfg, "searching", message="Looking for retail matches…")
        result, cost_micro, used_browser = search.search_for_item(
            description=item.get("description") or "",
            brand=item.get("brand"),
            model=item.get("model"),
            model_slug=cfg.model_slug,
            openrouter_key=cfg.openrouter_api_key,
            browser_account_id=cfg.browser_account_id,
            browser_token=cfg.browser_token,
        )

        if result is None:
            error = "No match found for this item."
        elif not result.source_url.strip() or not result.retailer.strip():
            # Every RCV must have a source; refuse to submit an unsourced price.
            error = "Match was missing a source URL or retailer."
        else:
            post_progress(cfg, "submitting", message="Submitting recommendation…")
            _submit_recommendation(
                cfg,
                {
                    "proposed_retail_unit_cents": search.dollars_to_cents(result.price_usd),
                    "proposed_shipping_cents": 0,
                    "source_url": result.source_url,
                    "source_retailer": result.retailer,
                    "match_type": result.match_type,
                    "product_title": result.product_title,
                    "rationale": result.rationale,
                },
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("run failed")
        error = str(exc)

    latency_ms = int((time.monotonic() - started) * 1000)
    telemetry = {
        "agent_impl": cfg.agent_impl,
        "image_tag": cfg.image_tag,
        "model_slug": cfg.model_slug,
        "cost_micro_usd": cost_micro,
        "latency_ms": latency_ms,
        "browser_run_used": used_browser,
    }

    if error is None:
        post_progress(cfg, "succeeded", **telemetry)
        return 0
    post_progress(cfg, "failed", error=error, **telemetry)
    return 1


if __name__ == "__main__":
    sys.exit(run(Config.from_env()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_container_runner.py -v`
Expected: 5 passed

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format .
uv run ruff format --check .
git add cloudflare/images/shared/runner.py tests/test_container_runner.py
git commit -m "feat(agent-runs): container runner enforcing skill invariants"
```

---

### Task 13: Dockerfile for the custom-python image

**Files:**
- Create: `cloudflare/images/custom-python/Dockerfile`
- Modify: `.dockerignore`

- [ ] **Step 1: Write the Dockerfile**

Create `cloudflare/images/custom-python/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.7
# Built from the REPOSITORY ROOT so it can COPY skills/ directly:
#   docker build -f cloudflare/images/custom-python/Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Baked, not injected — telemetry must describe the image that actually ran.
ARG IMAGE_TAG=dev
ENV IMAGE_TAG=${IMAGE_TAG} \
    AGENT_IMPL=custom-python

RUN pip install --no-cache-dir httpx==0.27.2

WORKDIR /app

COPY cloudflare/images/shared/ /app/
# Used from source rather than duplicated, so the reference client cannot drift.
COPY skills/airecommendations/scripts/agent_client.py /app/agent_client.py

ENTRYPOINT ["python", "/app/runner.py"]
```

- [ ] **Step 2: Keep the image lean**

Append to `.dockerignore`:

```
cloudflare/images/*/Dockerfile
```

> This only excludes the Dockerfiles from the build context; `cloudflare/images/shared/`
> and `skills/` must stay included.

- [ ] **Step 3: Build it**

Run:
```bash
docker build -f cloudflare/images/custom-python/Dockerfile --build-arg IMAGE_TAG=dev -t cvp-agent-custom:dev .
```
Expected: build succeeds.

- [ ] **Step 4: Verify it fails loudly without configuration**

Run: `docker run --rm cvp-agent-custom:dev`
Expected: exits non-zero with `missing required env var RUN_ID`

- [ ] **Step 5: Commit**

```bash
git add cloudflare/images/custom-python/Dockerfile .dockerignore
git commit -m "feat(agent-runs): custom-python container image"
```

---

### Task 14: Worker shim and wrangler configuration

The only JavaScript in this feature. It carries no business logic — it verifies the signature, picks a Durable Object by run id, and starts the container.

**Files:**
- Create: `cloudflare/src/index.ts`
- Create: `cloudflare/wrangler.toml`
- Create: `cloudflare/package.json`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "cvp-agents",
  "private": true,
  "type": "module",
  "dependencies": {
    "@cloudflare/containers": "^0.0.42"
  },
  "devDependencies": {
    "wrangler": "^4.0.0"
  }
}
```

- [ ] **Step 2: Create the Worker**

Create `cloudflare/src/index.ts`:

```ts
import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  CUSTOM_PYTHON_AGENT: DurableObjectNamespace;
  LAUNCH_HMAC_SECRET: string;
  CVP_BASE_URL: string;
  CVP_AGENT_KEY: string;
  OPENROUTER_API_KEY: string;
  BROWSER_RUN_ACCOUNT_ID: string;
  BROWSER_RUN_TOKEN: string;
}

interface Job {
  run_id: string;
  matter_id: string;
  item_id: string;
  model_slug: string;
  agent_impl: string;
}

export class CustomPythonAgent extends Container {
  // The run is a one-shot batch job: no port, no request forwarding.
  sleepAfter = "30s";
  private launched = false;

  async launch(job: Job, secrets: Record<string, string>): Promise<void> {
    // The DO id IS the run id, so a replayed launch lands here and is refused.
    if (this.launched) return;
    this.launched = true;
    await this.ctx.container.start({
      enableInternet: true,
      env: {
        RUN_ID: job.run_id,
        MATTER_ID: job.matter_id,
        ITEM_ID: job.item_id,
        MODEL_SLUG: job.model_slug,
        ...secrets,
      },
    });
  }
}

/**
 * Verify the HMAC CVP signed over "<timestamp>.<body>".
 * Must stay identical to sign_payload() in src/cvp/services/agent_launch.py —
 * the fixed vector in tests/test_agent_launch_signing.py is the shared contract.
 */
async function verify(req: Request, secret: string): Promise<string | null> {
  const ts = req.headers.get("X-CVP-Timestamp");
  const sig = req.headers.get("X-CVP-Signature");
  if (!ts || !sig) return null;

  const skew = Math.abs(Date.now() / 1000 - Number(ts));
  if (!Number.isFinite(skew) || skew > 300) return null;

  const body = await req.text();
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(`${ts}.${body}`));
  const hex = [...new Uint8Array(mac)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  const expected = `v1=${hex}`;

  if (sig.length !== expected.length) return null;
  let diff = 0;
  for (let i = 0; i < sig.length; i++) diff |= sig.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0 ? body : null;
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (req.method !== "POST" || url.pathname !== "/runs") {
      return new Response("not found", { status: 404 });
    }

    const body = await verify(req, env.LAUNCH_HMAC_SECRET);
    if (body === null) return new Response("unauthorized", { status: 401 });

    let job: Job;
    try {
      job = JSON.parse(body) as Job;
    } catch {
      return new Response("bad request", { status: 400 });
    }
    if (!job.run_id || !job.item_id || !job.model_slug) {
      return new Response("bad request", { status: 400 });
    }

    const stub = getContainer(env.CUSTOM_PYTHON_AGENT, job.run_id);
    await stub.launch(job, {
      CVP_BASE_URL: env.CVP_BASE_URL,
      CVP_AGENT_KEY: env.CVP_AGENT_KEY,
      OPENROUTER_API_KEY: env.OPENROUTER_API_KEY,
      BROWSER_RUN_ACCOUNT_ID: env.BROWSER_RUN_ACCOUNT_ID,
      BROWSER_RUN_TOKEN: env.BROWSER_RUN_TOKEN,
    });

    return new Response(JSON.stringify({ accepted: job.run_id }), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    });
  },
};
```

- [ ] **Step 3: Create wrangler.toml**

```toml
name = "cvp-agents"
main = "src/index.ts"
compatibility_date = "2026-09-10"

# CVP_BASE_URL is not secret; the rest are set with `wrangler secret put`.
[vars]
CVP_BASE_URL = "https://cvp.cmondor.com"

[[containers]]
class_name = "CustomPythonAgent"
# CI rewrites this to registry.cloudflare.com/<ACCOUNT_ID>/cvp-agent-custom:<sha>
image = "../cloudflare/images/custom-python/Dockerfile"
max_instances = 20
instance_type = "basic"

[[durable_objects.bindings]]
name = "CUSTOM_PYTHON_AGENT"
class_name = "CustomPythonAgent"

[[migrations]]
tag = "v1"
new_sqlite_classes = ["CustomPythonAgent"]
```

> The `new_sqlite_classes` migration is required by the Containers API even
> though this design never writes to Durable Object storage. The DO is a
> control plane, not a store.

- [ ] **Step 4: Type-check the Worker**

```bash
cd cloudflare && npm install && npx wrangler types && npx tsc --noEmit; cd ..
```
Expected: no type errors. If `stub.launch(...)` does not type-check against the
installed `@cloudflare/containers`, consult `node_modules/@cloudflare/containers/README.md`
for the current RPC surface and adjust the call — the contract (per-instance
`env`, `enableInternet`, no port) does not change.

- [ ] **Step 5: Verify signature parity with CVP**

```bash
uv run python -c "from cvp.services.agent_launch import sign_payload; print(sign_payload('topsecret','1757462400','{\"run_id\":\"abc\"}'))"
cd cloudflare && node -e '
const c=require("crypto");
const m=c.createHmac("sha256","topsecret").update("1757462400.{\"run_id\":\"abc\"}").digest("hex");
console.log("v1="+m);'; cd ..
```
Expected: both print the identical `v1=...` string. If they differ, the Worker
and CVP disagree and every launch will 401.

- [ ] **Step 6: Commit**

```bash
git add cloudflare/src/index.ts cloudflare/wrangler.toml cloudflare/package.json
git commit -m "feat(agent-runs): Cloudflare Worker shim and wrangler config"
```

---

### Task 15: CI, runbook, and the full-suite gate

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/RUNBOOK.md`

- [ ] **Step 1: Add the containers job**

Append to `.github/workflows/ci.yml`:

```yaml
  containers:
    name: containers
    runs-on: ubuntu-latest
    strategy:
      matrix:
        image: [custom-python]
    steps:
      - uses: actions/checkout@v4
      - name: Build image
        run: |
          docker build \
            -f cloudflare/images/${{ matrix.image }}/Dockerfile \
            --build-arg IMAGE_TAG=${{ github.sha }} \
            -t cvp-agent-${{ matrix.image }}:${{ github.sha }} .
      # PRs build only. Pushing on every review round would consume the
      # 50 GB per-account registry budget, which has no automatic GC.
      - name: Push to Cloudflare registry
        if: github.event_name == 'push'
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
        run: |
          npx wrangler containers push \
            cvp-agent-${{ matrix.image }}:${{ github.sha }}
```

- [ ] **Step 2: Add the runbook section**

Append to `docs/RUNBOOK.md`:

```markdown
## Cloudflare agent runs

**Prerequisite:** Workers **Paid** plan. Browser Run's free tier allows only
10 browser-minutes/day and 3 concurrent browsers, which cannot support this.

### First deploy

1. Mint an agent key in the app under **System Admin → Agent Keys**, named
   `cloudflare-agent`. The full key is shown once — copy it.
2. Record its **id** (not the key) in CVP's environment as
   `CLOUDFLARE_AGENT_KEY_ID`. Runs are bound to this key at creation, so the
   progress endpoint can use a strict equality check.
3. Generate a launch secret: `openssl rand -hex 32`. Set it in CVP's
   environment as `CLOUDFLARE_LAUNCH_HMAC_SECRET`.
4. Set the Cloudflare secrets — these never pass through CI:

   ```bash
   cd cloudflare
   wrangler secret put LAUNCH_HMAC_SECRET       # same value as step 3
   wrangler secret put CVP_AGENT_KEY            # the key from step 1
   wrangler secret put OPENROUTER_API_KEY
   wrangler secret put BROWSER_RUN_ACCOUNT_ID
   wrangler secret put BROWSER_RUN_TOKEN
   ```

5. Deploy: `wrangler deploy`.
6. Set `CLOUDFLARE_AGENT_WORKER_URL` in CVP to the deployed Worker URL.

### Rotating the agent key

Sequenced, and only when no runs are in flight — runs created before the
rotation will reject progress from the new key:

1. Mint a new key; 2. `wrangler secret put CVP_AGENT_KEY`; 3. update
`CLOUDFLARE_AGENT_KEY_ID` in CVP; 4. revoke the old key. Revocation fails
launches loudly at the existing auth check rather than silently.

### Pruning images

The registry has a **50 GB per-account cap and no automatic garbage
collection**. Every merge pushes a new image, so prune periodically:

```bash
wrangler containers images list
wrangler containers images delete <IMAGE>:<TAG>
```

Keep the currently deployed tag and the last few for rollback. Deleting an
image a deployed Worker still references will break that Worker.

### Diagnosing a stuck run

Container storage is ephemeral and logs live on Cloudflare, so CVP cannot
interrogate a dead container — it only notices that nothing arrived. A run
stuck in a non-terminal state is reaped on app startup by
`agent_run_sweeper.sweep_stale_runs` after `AGENT_RUN_STALE_MINUTES`
(default 15). For the container's own output use `wrangler tail`.
```

- [ ] **Step 3: Run the full suite and linter**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```
Expected: ruff clean; pytest shows no new failures beyond the one known
pre-existing vision failure on `cvp-legacy`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml docs/RUNBOOK.md
git commit -m "ci(agent-runs): build container images; document deploy and rotation"
```

- [ ] **Step 5: Push and open the PR**

```bash
git push -u origin feat/cloudflare-agent-runs
gh pr create --base cvp-legacy \
  --title "feat(agent-runs): per-item AI recommendation agents on Cloudflare" \
  --body "Implements docs/superpowers/specs/2026-09-10-cloudflare-agent-runs-design.md (Phase 1).

Adds a Get AI Recommendations button to the item edit row that launches one
ephemeral Cloudflare container per item, polls progress into the UI, and
submits a sourced proposal through the existing agent API.

Phase 2 (the Pi image) and Phase 3 (the A/B analysis) follow in separate PRs.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01R4q2g6NAtkWMPH3PjpSrPy"
```

**Base is `cvp-legacy`, not `main`.**

---

## Deferred to later phases

- **Phase 2** — the Pi image behind the same contract: `pi -p --no-session
  --mode json --provider openrouter --skill /app/skills/airecommendations
  --tools bash,read`, plus renaming `skills/airecommendations/airecommendations.md`
  to `SKILL.md` with `name`/`description` frontmatter so Pi can discover it.
  `cost_micro_usd` may be null for this arm; reconcile manually from OpenRouter
  usage reports until verified.
- **Phase 3** — A/B on match quality over real unpriced items, using the
  `agent_runs` ⋈ `ai_recommendations` query in spec §5.3.
- **Advanced model override** in the UI for system admins (spec §6). The
  endpoint already accepts `model_slug`; only the control is deferred.
