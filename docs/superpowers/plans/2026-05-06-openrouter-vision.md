# OpenRouter Vision Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the direct Anthropic SDK call in the evidence-scan pipeline with an OpenRouter HTTP client and let admins curate a catalog of vision models that specialists pick from per-scan.

**Architecture:** A new `services/openrouter.py` HTTP client replaces `anthropic.Anthropic` calls inside `services/vision.py`. A new `vision_models` table holds an admin-curated catalog populated from a live OpenRouter `/api/v1/models` fetch. A small adapter registry in `services/vision_adapters.py` normalizes per-model bbox formats so cropping keeps working across providers.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Alembic, Jinja2 + HTMX, httpx (already in deps), pytest, ruff. Postgres in production, SQLite for tests/local.

**Spec:** `docs/superpowers/specs/2026-05-06-openrouter-vision-design.md`

---

## File map

**Create:**
- `src/cvp/services/openrouter.py` — HTTP client (`call_vision`, `OpenRouterError`, `fetch_models`)
- `src/cvp/services/vision_adapters.py` — bbox normalization registry
- `src/cvp/services/vision_models.py` — `RECOMMENDED_SLUGS`, `ADAPTER_SUGGESTIONS`, `suggest_adapter()`, `parse_pricing_to_cents()`
- `src/cvp/models_vision.py` — `VisionModel` ORM (separate file like `models_audit.py`)
- `src/cvp/routers/admin/vision_models.py` — admin index + add/refresh/disable/delete/set-default
- `src/cvp/templates/admin/vision_models.html` — index page
- `src/cvp/templates/admin/_vision_models_row.html` — row partial
- `src/cvp/templates/admin/_vision_models_add_modal.html` — modal with catalog
- `src/cvp/templates/_vision_model_picker.html` — `<select>` partial included in evidence grid
- `migrations/versions/<auto>_add_vision_models.py` — Alembic revision
- `tests/test_vision_adapters.py`
- `tests/test_openrouter.py`
- `tests/test_vision_models_service.py`
- `tests/test_admin_vision_models.py`
- `tests/test_vision_router.py` (extends scan-flow integration coverage)

**Modify:**
- `src/cvp/config.py` — add `openrouter_api_key`, `openrouter_referer`, `openrouter_app_title`; keep `anthropic_api_key`/`vision_model`/`vision_model_fallback` for one release (marked deprecated)
- `src/cvp/models.py` — add columns `adapter`, `cost_cents_estimated` to `VisionRun`; import `models_vision` at bottom
- `src/cvp/models_auth.py` — add `last_vision_model_slug` column to `User`
- `src/cvp/services/vision.py` — replace `anthropic.Anthropic` call with `openrouter.call_vision`; replace `_parse_bbox` with adapter dispatch; accept `model_slug` in `run_scan`; new `estimate_cost(n, slug)`
- `src/cvp/routers/vision.py` — accept `model_slug` form field; validate; update user's `last_vision_model_slug`; cost-estimate endpoint
- `src/cvp/routers/admin/__init__.py` — register vision_models router
- `src/cvp/templates/_evidence_grid.html` — add picker above grid; include via `hx-include` in per-file scan forms
- `src/cvp/templates/matter_detail.html` (or wherever evidence grid is rendered) — pass models list to template context
- `src/cvp/routers/matters.py` — pass enabled vision models + user default into evidence-grid template context
- `.env.example` — add OpenRouter keys, mark Anthropic ones as deprecated
- `tests/conftest.py` — only if a fixture for seeded vision_model is helpful (likely yes)

**Delete (eventual cleanup, not in this plan):** `anthropic` dep from `pyproject.toml` — deferred per spec.

---

## Task ordering and dependencies

1. Settings — additive, low risk
2. Bbox adapters — pure functions, TDD
3. OpenRouter client — pure HTTP, mocked in tests
4. Migration + ORM models — schema only
5. Service helpers — `vision_models.py`
6. Admin router: index + add flow (requires 3, 4, 5)
7. Admin router: row actions
8. Refactor `vision.run_scan` (requires 2, 3, 4)
9. Refactor `routers/vision.py` start_scan + cost endpoint
10. Per-scan picker UI
11. Audit-log integration for admin actions
12. `.env.example` + final config cleanup

---

### Task 1: OpenRouter settings

**Files:**
- Modify: `src/cvp/config.py`
- Test: `tests/test_config.py` (extend)

- [ ] **Step 1: Write the failing test.** Append to `tests/test_config.py`:

```python
def test_settings_has_openrouter_fields(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    monkeypatch.setenv("OPENROUTER_REFERER", "https://cvp.example")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "CVP-test")
    from cvp.config import Settings

    s = Settings()
    assert s.openrouter_api_key == "sk-or-v1-test"
    assert s.openrouter_referer == "https://cvp.example"
    assert s.openrouter_app_title == "CVP-test"


def test_settings_openrouter_defaults():
    from cvp.config import Settings

    s = Settings(_env_file=None)
    assert s.openrouter_api_key == ""
    assert s.openrouter_referer == ""
    assert s.openrouter_app_title == "CVP"
```

- [ ] **Step 2: Run tests.** `uv run pytest tests/test_config.py -v` — expect FAIL on attribute errors.
- [ ] **Step 3: Add the settings.** In `src/cvp/config.py`, add three fields beside `anthropic_api_key`:

```python
class Settings(BaseSettings):
    anthropic_api_key: str = ""           # deprecated — used to be the vision provider; remove after one release
    vision_model: str = "claude-opus-4-6"  # deprecated — replaced by VisionModel DB rows
    vision_model_fallback: str = "claude-sonnet-4-6"  # deprecated — unused; remove after one release
    openrouter_api_key: str = ""
    openrouter_referer: str = ""
    openrouter_app_title: str = "CVP"
    # ... rest unchanged
```

- [ ] **Step 4: Run tests.** `uv run pytest tests/test_config.py -v` — expect PASS.
- [ ] **Step 5: Commit.**

```bash
git add src/cvp/config.py tests/test_config.py
git commit -m "feat(config): add OpenRouter settings (api key, referer, app title)"
```

---

### Task 2: Bbox adapters

**Files:**
- Create: `src/cvp/services/vision_adapters.py`
- Create: `tests/test_vision_adapters.py`

- [ ] **Step 1: Write failing tests.**

```python
# tests/test_vision_adapters.py
import pytest

from cvp.services.vision_adapters import (
    REGISTRY,
    BboxParseError,
    gemini_normalized_1000,
    none_adapter,
    pixel_passthrough,
    resolve,
)


class TestPixelPassthrough:
    def test_basic(self):
        assert pixel_passthrough([100, 200, 300, 400], 1000, 800) is not None

    def test_returns_padded_clamped_box(self):
        # 15% padding of 200x200 box => 30 each side
        out = pixel_passthrough([100, 100, 300, 300], 1000, 1000)
        assert out == (70, 70, 330, 330)

    def test_clamps_to_image_bounds(self):
        out = pixel_passthrough([0, 0, 1000, 1000], 1000, 1000)
        assert out == (0, 0, 1000, 1000)

    def test_rejects_non_list(self):
        assert pixel_passthrough("not a list", 1000, 1000) is None

    def test_rejects_wrong_length(self):
        assert pixel_passthrough([1, 2, 3], 1000, 1000) is None

    def test_rejects_inverted(self):
        assert pixel_passthrough([300, 300, 100, 100], 1000, 1000) is None


class TestGeminiNormalized:
    def test_scales_0_1000_to_pixels(self):
        # Gemini box [100, 200, 300, 400] in 0..1000 space, image 2000x1000
        # => left=200, upper=200, right=600, lower=400 (pre-padding)
        # 15% padding of 400x200: 60, 30
        out = gemini_normalized_1000([100, 200, 300, 400], 2000, 1000)
        assert out == (140, 170, 660, 430)

    def test_clamps_to_image_bounds(self):
        out = gemini_normalized_1000([0, 0, 1000, 1000], 500, 500)
        assert out == (0, 0, 500, 500)

    def test_rejects_out_of_range(self):
        assert gemini_normalized_1000([0, 0, 1500, 500], 500, 500) is None

    def test_rejects_non_list(self):
        assert gemini_normalized_1000("nope", 500, 500) is None


class TestNoneAdapter:
    def test_always_returns_none(self):
        assert none_adapter([1, 2, 3, 4], 100, 100) is None
        assert none_adapter(None, 100, 100) is None


class TestResolve:
    def test_known_name(self):
        assert resolve("pixel_passthrough") is pixel_passthrough

    def test_unknown_falls_back_to_none(self):
        assert resolve("does_not_exist") is none_adapter
```

- [ ] **Step 2: Run.** `uv run pytest tests/test_vision_adapters.py -v` — expect FAIL (module missing).
- [ ] **Step 3: Implement the adapters.**

```python
# src/cvp/services/vision_adapters.py
"""Per-model bbox adapters.

Vision models report bounding boxes in different formats.  Each adapter takes
the raw bbox from the model response and returns ``(left, upper, right, lower)``
in image pixels with 15% generous padding applied, or ``None`` if the input is
malformed or the model isn't expected to produce usable bboxes at all.

The 15% padding and clamping behavior mirrors the historical _parse_bbox in
services/vision.py — we move it here unchanged so existing crops stay
visually consistent.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class BboxParseError(Exception):
    """Raised when raw bbox input is malformed beyond recovery."""


_PadResult = tuple[int, int, int, int] | None


def _pad_clamp(left: int, upper: int, right: int, lower: int, w: int, h: int) -> _PadResult:
    if left >= right or upper >= lower:
        return None
    pad_x = round((right - left) * 0.15)
    pad_y = round((lower - upper) * 0.15)
    left = max(0, left - pad_x)
    upper = max(0, upper - pad_y)
    right = min(w, right + pad_x)
    lower = min(h, lower + pad_y)
    if left >= right or upper >= lower:
        return None
    return left, upper, right, lower


def pixel_passthrough(raw: Any, w: int, h: int) -> _PadResult:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        left, upper, right, lower = (int(v) for v in raw)
    except (TypeError, ValueError):
        return None
    return _pad_clamp(left, upper, right, lower, w, h)


def gemini_normalized_1000(raw: Any, w: int, h: int) -> _PadResult:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        nl, nu, nr, nlo = (int(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if not all(0 <= v <= 1000 for v in (nl, nu, nr, nlo)):
        return None
    left = round(nl / 1000 * w)
    upper = round(nu / 1000 * h)
    right = round(nr / 1000 * w)
    lower = round(nlo / 1000 * h)
    return _pad_clamp(left, upper, right, lower, w, h)


def none_adapter(raw: Any, w: int, h: int) -> _PadResult:
    return None


REGISTRY: dict[str, Callable[[Any, int, int], _PadResult]] = {
    "pixel_passthrough": pixel_passthrough,
    "gemini_normalized_1000": gemini_normalized_1000,
    "none": none_adapter,
}


def resolve(name: str) -> Callable[[Any, int, int], _PadResult]:
    fn = REGISTRY.get(name)
    if fn is None:
        logger.warning("unknown vision adapter %r — falling back to 'none'", name)
        return none_adapter
    return fn
```

- [ ] **Step 4: Run tests.** `uv run pytest tests/test_vision_adapters.py -v` — expect PASS.
- [ ] **Step 5: Commit.**

```bash
git add src/cvp/services/vision_adapters.py tests/test_vision_adapters.py
git commit -m "feat(vision): add per-model bbox adapter registry"
```

---

### Task 3: OpenRouter HTTP client

**Files:**
- Create: `src/cvp/services/openrouter.py`
- Create: `tests/test_openrouter.py`

- [ ] **Step 1: Write failing tests.** Tests use `respx` if available; if not, use `unittest.mock` for `httpx.Client.post`. The codebase already uses `httpx`; check existing tests for the convention. If `respx` isn't installed, mock with `unittest.mock`.

```python
# tests/test_openrouter.py
from unittest.mock import MagicMock, patch

import httpx
import pytest

from cvp.services.openrouter import (
    OpenRouterError,
    call_vision,
    fetch_models,
    parse_pricing_to_cents,
)


def _build_response(status: int, json_body: dict) -> httpx.Response:
    return httpx.Response(status, json=json_body, request=httpx.Request("POST", "https://o"))


class TestCallVision:
    def test_happy_path_returns_text(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        body = {"choices": [{"message": {"content": "[]"}}]}
        with patch("httpx.Client.post", return_value=_build_response(200, body)) as p:
            text = call_vision("anthropic/claude-opus-4", b"\x89PNG", "image/png", "prompt")
        assert text == "[]"
        # Headers + auth should be set
        kwargs = p.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == "Bearer sk-or-test"

    def test_raises_on_4xx(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk")
        body = {"error": {"message": "rate limit"}}
        with patch("httpx.Client.post", return_value=_build_response(429, body)):
            with pytest.raises(OpenRouterError) as exc:
                call_vision("x/y", b"", "image/jpeg", "p")
        assert "429" in str(exc.value)
        assert "rate limit" in str(exc.value)

    def test_raises_on_5xx(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk")
        with patch("httpx.Client.post", return_value=_build_response(503, {})):
            with pytest.raises(OpenRouterError):
                call_vision("x/y", b"", "image/jpeg", "p")

    def test_propagates_timeout(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk")
        with patch("httpx.Client.post", side_effect=httpx.TimeoutException("slow")):
            with pytest.raises(httpx.TimeoutException):
                call_vision("x/y", b"", "image/jpeg", "p")


class TestFetchModels:
    def test_filters_to_image_capable(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk")
        body = {
            "data": [
                {
                    "id": "vision/one",
                    "name": "Vision One",
                    "architecture": {"input_modalities": ["text", "image"]},
                    "pricing": {"image": "0.001"},
                    "context_length": 200000,
                    "description": "yes",
                },
                {
                    "id": "text-only/two",
                    "name": "Text Only",
                    "architecture": {"input_modalities": ["text"]},
                    "pricing": {},
                    "context_length": 100000,
                    "description": "no",
                },
            ]
        }
        with patch("httpx.Client.get", return_value=_build_response(200, body)):
            models = fetch_models()
        assert len(models) == 1
        assert models[0]["id"] == "vision/one"


class TestParsePricing:
    def test_decimal_string_to_cents(self):
        assert parse_pricing_to_cents("0.025") == 2  # 2.5 -> rounded to 2 cents (banker's rounding)
        assert parse_pricing_to_cents("0.10") == 10
        assert parse_pricing_to_cents("0") is None
        assert parse_pricing_to_cents("") is None
        assert parse_pricing_to_cents(None) is None
        assert parse_pricing_to_cents("not-a-number") is None
```

> Note on rounding: `parse_pricing_to_cents` should round half-up to nearest cent. The "0.025 -> 2 or 3" case is documented in the implementation. Adjust the test to match the chosen rounding mode (we use `round()` which is banker's rounding in Python 3 — `round(2.5) == 2`). If you prefer half-up, switch to `math.floor(x + 0.5)` and update the test to `== 3`.

- [ ] **Step 2: Run tests.** `uv run pytest tests/test_openrouter.py -v` — expect FAIL (module missing).
- [ ] **Step 3: Implement the client.**

```python
# src/cvp/services/openrouter.py
"""OpenRouter HTTP client for vision calls and model catalog discovery.

Replaces the historical anthropic.Anthropic client.  Uses the OpenAI-compatible
chat completions endpoint with a base64 data: URL for the image part.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from cvp.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://openrouter.ai/api/v1"
_CHAT_URL = f"{_BASE_URL}/chat/completions"
_MODELS_URL = f"{_BASE_URL}/models"


class OpenRouterError(Exception):
    """Raised on any non-2xx response from OpenRouter."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


def _headers() -> dict[str, str]:
    h = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if settings.openrouter_referer:
        h["HTTP-Referer"] = settings.openrouter_referer
    if settings.openrouter_app_title:
        h["X-Title"] = settings.openrouter_app_title
    return h


def call_vision(
    model_slug: str,
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
    *,
    timeout_seconds: float = 120.0,
) -> str:
    """POST to OpenRouter chat completions; return the raw text content of the
    first choice. Raises OpenRouterError on 4xx/5xx, httpx.TimeoutException on
    timeout."""
    b64 = base64.standard_b64encode(image_bytes).decode()
    payload = {
        "model": model_slug,
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                    },
                ],
            }
        ],
    }
    with httpx.Client(timeout=timeout_seconds) as client:
        resp = client.post(_CHAT_URL, headers=_headers(), json=payload)
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", {}).get("message") or resp.text
        except Exception:  # noqa: BLE001
            err = resp.text
        raise OpenRouterError(resp.status_code, err)
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""


def fetch_models() -> list[dict[str, Any]]:
    """Return the OpenRouter model catalog filtered to vision-capable entries.
    Each entry preserves the upstream shape (id, name, architecture, pricing,
    context_length, description)."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(_MODELS_URL, headers=_headers())
    if resp.status_code >= 400:
        raise OpenRouterError(resp.status_code, resp.text[:500])
    data = resp.json().get("data") or []
    out: list[dict[str, Any]] = []
    for m in data:
        modalities = (m.get("architecture") or {}).get("input_modalities") or []
        if "image" in modalities:
            out.append(m)
    return out


def parse_pricing_to_cents(value: Any) -> int | None:
    """OpenRouter returns pricing as decimal-string USD-per-image (e.g. '0.025').
    Convert to integer cents.  Returns None for missing, zero, or unparseable
    inputs."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return None
    return round(f * 100)
```

- [ ] **Step 4: Run tests.** `uv run pytest tests/test_openrouter.py -v` — expect PASS. If `parse_pricing_to_cents("0.025")` test fails because of `round()` banker's rounding, accept whichever value Python returns and document it in the test.
- [ ] **Step 5: Commit.**

```bash
git add src/cvp/services/openrouter.py tests/test_openrouter.py
git commit -m "feat(vision): add OpenRouter HTTP client and model catalog fetch"
```

---

### Task 4: Database schema — VisionModel + new audit columns

**Files:**
- Create: `src/cvp/models_vision.py`
- Modify: `src/cvp/models.py` (add `adapter`, `cost_cents_estimated` to `VisionRun`; import `models_vision`)
- Modify: `src/cvp/models_auth.py` (add `last_vision_model_slug` to `User`)
- Create: `migrations/versions/<auto>_add_vision_models.py`

- [ ] **Step 1: Write the model file.**

```python
# src/cvp/models_vision.py
"""Admin-curated catalog of vision models exposed in the per-scan picker."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cvp.models import Base, _new_uuid


class VisionModel(Base):
    __tablename__ = "vision_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    adapter: Mapped[str] = mapped_column(String, nullable=False, default="none")
    prompt_image_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supports_bbox: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    added_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 2: Add new columns to `VisionRun` in `src/cvp/models.py`.** After existing columns, add:

```python
    adapter: Mapped[str] = mapped_column(String, nullable=False, default="none")
    cost_cents_estimated: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 3: Add `last_vision_model_slug` to `User` in `src/cvp/models_auth.py`.** Insert before `created_at`:

```python
    last_vision_model_slug: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Register `models_vision` import.** At the bottom of `src/cvp/models.py`, alongside the other `_register` imports:

```python
import cvp.models_vision as _vision_models  # noqa: F401, E402 — register vision_models table with Base
```

Also add the import to `tests/conftest.py`:

```python
import cvp.models_vision  # noqa: F401
```

- [ ] **Step 5: Generate Alembic migration.**

```bash
uv run alembic revision --autogenerate -m "add vision_models table and audit columns"
```

Open the generated file. Verify it:
- Creates `vision_models` table with all columns above
- Adds `vision_runs.adapter` (default `"none"`, nullable=False)
- Adds `vision_runs.cost_cents_estimated` (nullable)
- Adds `users.last_vision_model_slug` (nullable)
- Creates a partial unique index on `vision_models(is_default) WHERE is_default IS TRUE` — Alembic autogen will likely miss this; **add manually**:

```python
op.create_index(
    "ix_vision_models_one_default",
    "vision_models",
    ["is_default"],
    unique=True,
    postgresql_where=sa.text("is_default IS TRUE"),
    sqlite_where=sa.text("is_default = 1"),
)
```

And in `downgrade()`: `op.drop_index("ix_vision_models_one_default", table_name="vision_models")`.

- [ ] **Step 6: Add seed insert into the migration's `upgrade()`.** After `op.create_table('vision_models', ...)`:

```python
op.execute(
    "INSERT INTO vision_models "
    "(slug, display_name, adapter, supports_bbox, is_default, is_enabled, recommended) "
    "VALUES ('anthropic/claude-opus-4', 'Claude Opus 4', 'pixel_passthrough', "
    "TRUE, TRUE, TRUE, TRUE)"
)
```

For SQLite-compatible bools, use `1`/`0`:

```python
from alembic import op
import sqlalchemy as sa

bind = op.get_bind()
is_sqlite = bind.dialect.name == "sqlite"
true_lit = "1" if is_sqlite else "TRUE"
op.execute(
    f"INSERT INTO vision_models "
    f"(slug, display_name, adapter, supports_bbox, is_default, is_enabled, recommended) "
    f"VALUES ('anthropic/claude-opus-4', 'Claude Opus 4', 'pixel_passthrough', "
    f"{true_lit}, {true_lit}, {true_lit}, {true_lit})"
)
```

- [ ] **Step 7: Apply migration.** `uv run alembic upgrade head`. Expect success.
- [ ] **Step 8: Smoke-test the seed.** `uv run python -c "from cvp.db import SessionLocal; from cvp.models_vision import VisionModel; db = SessionLocal(); rows = db.query(VisionModel).all(); print([(r.slug, r.is_default) for r in rows])"`. Expect `[('anthropic/claude-opus-4', True)]`.
- [ ] **Step 9: Run full test suite.** `uv run pytest -q`. The `Base.metadata.create_all(engine)` in `tests/conftest.py` will pick up the new table; existing tests should still pass.
- [ ] **Step 10: Commit.**

```bash
git add src/cvp/models.py src/cvp/models_auth.py src/cvp/models_vision.py \
        migrations/versions/*_add_vision_models.py tests/conftest.py
git commit -m "feat(db): add vision_models catalog table, audit columns, seed default"
```

---

### Task 5: Service helpers — `vision_models.py`

**Files:**
- Create: `src/cvp/services/vision_models.py`
- Create: `tests/test_vision_models_service.py`

- [ ] **Step 1: Write failing tests.**

```python
# tests/test_vision_models_service.py
from cvp.services.vision_models import (
    ADAPTER_SUGGESTIONS,
    RECOMMENDED_SLUGS,
    is_recommended,
    suggest_adapter,
)


class TestSuggestAdapter:
    def test_anthropic_returns_pixel_passthrough(self):
        assert suggest_adapter("anthropic/claude-opus-4") == "pixel_passthrough"

    def test_gemini_returns_normalized(self):
        assert suggest_adapter("google/gemini-2.5-pro") == "gemini_normalized_1000"

    def test_unknown_returns_none(self):
        assert suggest_adapter("openai/gpt-4o") == "none"


class TestIsRecommended:
    def test_known_slug(self):
        assert is_recommended("anthropic/claude-opus-4") is True

    def test_unknown_slug(self):
        assert is_recommended("random/model") is False
```

- [ ] **Step 2: Run.** `uv run pytest tests/test_vision_models_service.py -v` — expect FAIL.
- [ ] **Step 3: Implement.**

```python
# src/cvp/services/vision_models.py
"""Constants and helpers for the vision-model catalog.

These are intentionally code-defined (not DB-stored) — adding a recommended
slug or a new auto-adapter is an engineering decision, not an admin one.
"""

from __future__ import annotations

RECOMMENDED_SLUGS: set[str] = {
    "anthropic/claude-opus-4",
    "anthropic/claude-sonnet-4",
    "google/gemini-2.5-pro",
}

# Order matters: first matching prefix wins.
ADAPTER_SUGGESTIONS: list[tuple[str, str]] = [
    ("anthropic/", "pixel_passthrough"),
    ("google/gemini-", "gemini_normalized_1000"),
]


def suggest_adapter(slug: str) -> str:
    for prefix, adapter in ADAPTER_SUGGESTIONS:
        if slug.startswith(prefix):
            return adapter
    return "none"


def is_recommended(slug: str) -> bool:
    return slug in RECOMMENDED_SLUGS
```

- [ ] **Step 4: Run tests.** `uv run pytest tests/test_vision_models_service.py -v` — expect PASS.
- [ ] **Step 5: Commit.**

```bash
git add src/cvp/services/vision_models.py tests/test_vision_models_service.py
git commit -m "feat(vision): add catalog helpers (RECOMMENDED_SLUGS, suggest_adapter)"
```

---

### Task 6: Admin router — index page

**Files:**
- Create: `src/cvp/routers/admin/vision_models.py`
- Create: `src/cvp/templates/admin/vision_models.html`
- Create: `src/cvp/templates/admin/_vision_models_row.html`
- Modify: `src/cvp/routers/admin/__init__.py` (or wherever admin routers register — check `src/cvp/main.py`)
- Create: `tests/test_admin_vision_models.py`

- [ ] **Step 1: Look at how an existing admin router is wired.** Open `src/cvp/routers/admin/system.py` and `src/cvp/main.py`. Note how routers are registered (likely `app.include_router(system.router)` in `main.py`). Mirror that for the new file.

- [ ] **Step 2: Write failing test for the index page.**

```python
# tests/test_admin_vision_models.py
import pytest

from cvp.db import SessionLocal
from cvp.models_vision import VisionModel


def test_admin_vision_models_index_lists_seeded_default(client_admin):
    """client_admin fixture: TestClient with system_admin auth — see existing
    tests/test_admin_system.py for the pattern."""
    resp = client_admin.get("/admin/vision-models")
    assert resp.status_code == 200
    body = resp.text
    assert "anthropic/claude-opus-4" in body
    assert "Claude Opus 4" in body
    # Default row marked as default
    assert "checked" in body  # default radio is checked


def test_admin_vision_models_index_requires_admin(client):
    resp = client.get("/admin/vision-models", follow_redirects=False)
    assert resp.status_code in (302, 303, 401, 403)
```

> The test depends on a `client_admin` fixture. Check `tests/conftest.py` and `tests/test_admin_system.py` for the existing pattern; reuse it. If no such fixture exists, write one in `tests/conftest.py` that creates a system_admin user, logs them in, and returns a `TestClient` with auth cookies.

- [ ] **Step 3: Run test.** `uv run pytest tests/test_admin_vision_models.py::test_admin_vision_models_index_lists_seeded_default -v` — expect FAIL (404 or import error).

- [ ] **Step 4: Implement the router (index only for now).**

```python
# src/cvp/routers/admin/vision_models.py
"""Admin-only catalog management for vision models."""

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.models_vision import VisionModel

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter(prefix="/admin/vision-models")


@router.get("", response_class=HTMLResponse)
def index(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rows = (
        db.query(VisionModel)
        .order_by(VisionModel.recommended.desc(), VisionModel.display_name.asc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin/vision_models.html",
        {"user": user, "rows": rows, "panel_title": "Vision Models"},
    )
```

- [ ] **Step 5: Create the template.**

```html
<!-- src/cvp/templates/admin/vision_models.html -->
{% extends "base.html" %}
{% block title %}Vision Models — Admin{% endblock %}
{% block content %}
<div class="mx-auto max-w-5xl p-6">
  <div class="mb-4 flex items-center justify-between">
    <h1 class="text-xl font-semibold">Vision Models</h1>
    <button hx-get="/admin/vision-models/add"
            hx-target="#add-modal"
            class="rounded bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white">
      Add model
    </button>
  </div>

  <table class="w-full text-sm">
    <thead class="border-b text-left text-xs uppercase text-gray-500">
      <tr>
        <th class="py-2">Name</th>
        <th>Slug</th>
        <th>Per-image</th>
        <th>Bbox</th>
        <th>Default</th>
        <th>Enabled</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody id="vision-models-tbody">
      {% for r in rows %}
        {% include "admin/_vision_models_row.html" %}
      {% endfor %}
    </tbody>
  </table>

  <div id="add-modal"></div>
</div>
{% endblock %}
```

```html
<!-- src/cvp/templates/admin/_vision_models_row.html -->
<tr id="vm-row-{{ r.id }}" class="border-b">
  <td class="py-2 font-medium">
    {{ r.display_name }}
    {% if r.recommended %}<span title="Recommended" class="ml-1 text-amber-500">★</span>{% endif %}
  </td>
  <td class="font-mono text-xs">{{ r.slug }}</td>
  <td>
    {% if r.prompt_image_cost_cents is none %}<span class="text-gray-400">?</span>
    {% else %}${{ "%.4f"|format(r.prompt_image_cost_cents / 100) }}
    {% endif %}
  </td>
  <td>{% if r.supports_bbox %}✓{% else %}—{% endif %}</td>
  <td>
    <form hx-post="/admin/vision-models/{{ r.id }}/set-default"
          hx-target="#vision-models-tbody" hx-swap="outerHTML">
      <input type="radio" name="default-radio" {% if r.is_default %}checked{% endif %}
             onchange="this.form.requestSubmit()">
    </form>
  </td>
  <td>
    <form hx-post="/admin/vision-models/{{ r.id }}/{% if r.is_enabled %}disable{% else %}enable{% endif %}"
          hx-target="#vm-row-{{ r.id }}" hx-swap="outerHTML">
      <button class="text-xs {% if r.is_enabled %}text-green-600{% else %}text-gray-400{% endif %}">
        {% if r.is_enabled %}enabled{% else %}disabled{% endif %}
      </button>
    </form>
  </td>
  <td class="space-x-2 text-xs">
    <button hx-post="/admin/vision-models/{{ r.id }}/refresh-pricing"
            hx-target="#vm-row-{{ r.id }}" hx-swap="outerHTML"
            class="text-blue-600">refresh</button>
    {% if not r.is_default %}
    <button hx-delete="/admin/vision-models/{{ r.id }}"
            hx-confirm="Delete {{ r.slug }}? Only allowed if no scans reference it."
            hx-target="#vm-row-{{ r.id }}" hx-swap="outerHTML"
            class="text-red-600">delete</button>
    {% endif %}
  </td>
</tr>
```

- [ ] **Step 6: Register the router.** In `src/cvp/main.py` (or wherever existing admin routers are included), add:

```python
from cvp.routers.admin import vision_models as admin_vision_models
app.include_router(admin_vision_models.router)
```

- [ ] **Step 7: Run tests.** `uv run pytest tests/test_admin_vision_models.py -v` — expect PASS for the index test (the action endpoints will 404; we add them next).
- [ ] **Step 8: Commit.**

```bash
git add src/cvp/routers/admin/vision_models.py \
        src/cvp/templates/admin/vision_models.html \
        src/cvp/templates/admin/_vision_models_row.html \
        src/cvp/main.py tests/test_admin_vision_models.py
git commit -m "feat(admin): vision models index page"
```

---

### Task 7: Admin "Add model" modal + insert

**Files:**
- Modify: `src/cvp/routers/admin/vision_models.py`
- Create: `src/cvp/templates/admin/_vision_models_add_modal.html`
- Modify: `tests/test_admin_vision_models.py`

- [ ] **Step 1: Write failing test.**

```python
def test_admin_vision_models_add_flow(client_admin, monkeypatch):
    fake_catalog = [
        {
            "id": "openai/gpt-4o",
            "name": "GPT-4o",
            "architecture": {"input_modalities": ["text", "image"]},
            "pricing": {"image": "0.005"},
            "context_length": 128000,
            "description": "OpenAI multimodal",
        }
    ]
    monkeypatch.setattr(
        "cvp.routers.admin.vision_models.openrouter.fetch_models",
        lambda: fake_catalog,
    )
    # Modal opens
    resp = client_admin.get("/admin/vision-models/add")
    assert resp.status_code == 200
    assert "openai/gpt-4o" in resp.text
    # Submit
    resp = client_admin.post(
        "/admin/vision-models",
        data={"slug": "openai/gpt-4o", "adapter": "none"},
    )
    assert resp.status_code in (200, 303)

    db = SessionLocal()
    try:
        row = db.query(VisionModel).filter_by(slug="openai/gpt-4o").one()
        assert row.adapter == "none"
        assert row.supports_bbox is False
        assert row.prompt_image_cost_cents == 1  # 0.005 * 100 = 0.5 -> rounds to 0 or 1; adjust
    finally:
        db.close()


def test_admin_vision_models_add_rejects_duplicate(client_admin, monkeypatch):
    monkeypatch.setattr(
        "cvp.routers.admin.vision_models.openrouter.fetch_models",
        lambda: [],
    )
    resp = client_admin.post(
        "/admin/vision-models",
        data={"slug": "anthropic/claude-opus-4", "adapter": "pixel_passthrough"},
    )
    # Already seeded — should be rejected
    assert resp.status_code in (400, 409)
```

- [ ] **Step 2: Run.** Expect FAIL (404).

- [ ] **Step 3: Implement modal endpoint and POST.** Append to `src/cvp/routers/admin/vision_models.py`:

```python
import time

from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from cvp.services import openrouter
from cvp.services.vision_models import is_recommended, suggest_adapter

# in-process cache: (timestamp, list)
_catalog_cache: tuple[float, list[dict]] | None = None
_CATALOG_TTL_SECONDS = 3600.0


def _get_catalog() -> list[dict]:
    global _catalog_cache
    now = time.time()
    if _catalog_cache and (now - _catalog_cache[0]) < _CATALOG_TTL_SECONDS:
        return _catalog_cache[1]
    fresh = openrouter.fetch_models()
    _catalog_cache = (now, fresh)
    return fresh


@router.get("/add", response_class=HTMLResponse)
def add_modal(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    existing_slugs = {r.slug for r in db.query(VisionModel.slug).all()}
    catalog = [m for m in _get_catalog() if m["id"] not in existing_slugs]
    enriched = [
        {
            **m,
            "is_recommended": is_recommended(m["id"]),
            "suggested_adapter": suggest_adapter(m["id"]),
            "image_price": (m.get("pricing") or {}).get("image") or "",
        }
        for m in catalog
    ]
    return templates.TemplateResponse(
        request,
        "admin/_vision_models_add_modal.html",
        {"user": user, "catalog": enriched},
    )


@router.post("", response_class=HTMLResponse)
def add_model(
    request: Request,
    slug: str = Form(...),
    adapter: str = Form(...),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if db.query(VisionModel).filter_by(slug=slug).first():
        raise HTTPException(status_code=409, detail=f"slug {slug} already exists")
    if adapter not in ("pixel_passthrough", "gemini_normalized_1000", "none"):
        raise HTTPException(status_code=400, detail="invalid adapter")
    # Look up snapshot data from the cached catalog
    catalog_entry = next((m for m in _get_catalog() if m["id"] == slug), None)
    display_name = (catalog_entry or {}).get("name") or slug
    image_price = (catalog_entry or {}).get("pricing", {}).get("image")
    cost_cents = openrouter.parse_pricing_to_cents(image_price)
    context_length = (catalog_entry or {}).get("context_length")

    row = VisionModel(
        slug=slug,
        display_name=display_name,
        adapter=adapter,
        prompt_image_cost_cents=cost_cents,
        context_length=context_length,
        supports_bbox=(adapter != "none"),
        is_default=False,
        is_enabled=True,
        recommended=is_recommended(slug),
        added_by_user_id=user.id,
    )
    db.add(row)
    db.commit()
    return RedirectResponse(url="/admin/vision-models", status_code=303)
```

- [ ] **Step 4: Create the modal template.**

```html
<!-- src/cvp/templates/admin/_vision_models_add_modal.html -->
<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
  <div class="max-h-[80vh] w-full max-w-3xl overflow-y-auto rounded bg-white p-6 shadow-xl">
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-semibold">Add a vision model</h2>
      <button onclick="document.getElementById('add-modal').innerHTML=''" class="text-gray-500">✕</button>
    </div>
    {% if not catalog %}
      <p class="text-sm text-gray-500">No new models available — every vision-capable model from OpenRouter is already added.</p>
    {% endif %}
    <table class="w-full text-sm">
      <thead><tr class="border-b text-left text-xs uppercase text-gray-500">
        <th class="py-2">Name</th><th>Slug</th><th>Per-image</th><th>Ctx</th><th></th>
      </tr></thead>
      <tbody>
        {% for m in catalog %}
        <tr class="border-b">
          <td class="py-2">{{ m.name }}{% if m.is_recommended %} <span class="text-amber-500">★</span>{% endif %}</td>
          <td class="font-mono text-xs">{{ m.id }}</td>
          <td>{% if m.image_price %}${{ m.image_price }}{% else %}<span class="text-gray-400">?</span>{% endif %}</td>
          <td>{{ m.context_length or "" }}</td>
          <td>
            <form hx-post="/admin/vision-models" hx-target="body" hx-swap="outerHTML">
              <input type="hidden" name="slug" value="{{ m.id }}">
              <select name="adapter" class="rounded border px-1 text-xs">
                <option value="pixel_passthrough" {% if m.suggested_adapter == "pixel_passthrough" %}selected{% endif %}>pixel_passthrough</option>
                <option value="gemini_normalized_1000" {% if m.suggested_adapter == "gemini_normalized_1000" %}selected{% endif %}>gemini_normalized_1000</option>
                <option value="none" {% if m.suggested_adapter == "none" %}selected{% endif %}>none (no cropping)</option>
              </select>
              <button class="ml-2 rounded bg-indigo-600 px-2 py-0.5 text-xs text-white">Add</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
```

- [ ] **Step 5: Run tests.** `uv run pytest tests/test_admin_vision_models.py -v` — expect PASS. If `prompt_image_cost_cents` test fails because of rounding, adjust the assertion to whatever Python's `round()` returns for `0.005 * 100`.
- [ ] **Step 6: Commit.**

```bash
git add src/cvp/routers/admin/vision_models.py \
        src/cvp/templates/admin/_vision_models_add_modal.html \
        tests/test_admin_vision_models.py
git commit -m "feat(admin): add-model modal with live OpenRouter catalog fetch"
```

---

### Task 8: Admin row actions — set-default, enable/disable, refresh-pricing, delete

**Files:**
- Modify: `src/cvp/routers/admin/vision_models.py`
- Modify: `tests/test_admin_vision_models.py`

- [ ] **Step 1: Write failing tests.**

```python
def test_set_default_flips_previous(client_admin, monkeypatch):
    monkeypatch.setattr(
        "cvp.routers.admin.vision_models.openrouter.fetch_models", lambda: []
    )
    db = SessionLocal()
    try:
        new = VisionModel(slug="x/y", display_name="X", adapter="none", supports_bbox=False)
        db.add(new)
        db.commit()
        new_id = new.id
    finally:
        db.close()
    resp = client_admin.post(f"/admin/vision-models/{new_id}/set-default")
    assert resp.status_code in (200, 303)
    db = SessionLocal()
    try:
        defaults = db.query(VisionModel).filter_by(is_default=True).all()
        assert len(defaults) == 1
        assert defaults[0].id == new_id
    finally:
        db.close()


def test_disable_default_is_rejected(client_admin):
    db = SessionLocal()
    try:
        default = db.query(VisionModel).filter_by(is_default=True).one()
        default_id = default.id
    finally:
        db.close()
    resp = client_admin.post(f"/admin/vision-models/{default_id}/disable")
    assert resp.status_code == 400


def test_delete_blocked_when_in_use(client_admin, matter_with_image):
    """Create a VisionRun referencing a slug, then try to hard-delete that
    catalog row. Should 409."""
    matter_id, file_id = matter_with_image
    db = SessionLocal()
    try:
        row = VisionModel(
            slug="someprov/inuse", display_name="In Use",
            adapter="none", supports_bbox=False, is_default=False, is_enabled=True,
        )
        db.add(row)
        db.commit()
        row_id = row.id
        db.add(VisionRun(
            matter_id=matter_id,
            evidence_file_id=file_id,
            model="someprov/inuse",
            prompt_version="v3",
            raw_response="[]",
            items_created=0,
            adapter="none",
        ))
        db.commit()
    finally:
        db.close()
    resp = client_admin.delete(f"/admin/vision-models/{row_id}")
    assert resp.status_code == 409
```

- [ ] **Step 2: Run.** Expect FAIL.

- [ ] **Step 3: Implement the action endpoints.** Append to `routers/admin/vision_models.py`:

```python
from cvp.models import VisionRun


@router.post("/{model_id}/set-default", response_class=HTMLResponse)
def set_default(
    request: Request,
    model_id: int,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.query(VisionModel).filter_by(id=model_id).first()
    if target is None:
        raise HTTPException(404)
    if not target.is_enabled:
        raise HTTPException(400, "cannot make a disabled model the default")
    db.query(VisionModel).filter(VisionModel.is_default.is_(True)).update(
        {"is_default": False}
    )
    target.is_default = True
    db.commit()
    return RedirectResponse("/admin/vision-models", status_code=303)


@router.post("/{model_id}/disable", response_class=HTMLResponse)
def disable_model(
    request: Request,
    model_id: int,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    row = db.query(VisionModel).filter_by(id=model_id).first()
    if row is None:
        raise HTTPException(404)
    if row.is_default:
        raise HTTPException(400, "cannot disable the default model")
    row.is_enabled = False
    db.commit()
    return _render_row(request, row, user)


@router.post("/{model_id}/enable", response_class=HTMLResponse)
def enable_model(
    request: Request,
    model_id: int,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    row = db.query(VisionModel).filter_by(id=model_id).first()
    if row is None:
        raise HTTPException(404)
    row.is_enabled = True
    db.commit()
    return _render_row(request, row, user)


@router.post("/{model_id}/refresh-pricing", response_class=HTMLResponse)
def refresh_pricing(
    request: Request,
    model_id: int,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    row = db.query(VisionModel).filter_by(id=model_id).first()
    if row is None:
        raise HTTPException(404)
    global _catalog_cache
    _catalog_cache = None  # bust cache so we get current pricing
    catalog = _get_catalog()
    entry = next((m for m in catalog if m["id"] == row.slug), None)
    if entry is None:
        # No-op; render the row with a flash flag we can show inline
        return _render_row(request, row, user, flash="not listed by OpenRouter")
    row.prompt_image_cost_cents = openrouter.parse_pricing_to_cents(
        (entry.get("pricing") or {}).get("image")
    )
    row.context_length = entry.get("context_length")
    db.commit()
    return _render_row(request, row, user)


@router.delete("/{model_id}", response_class=HTMLResponse)
def delete_model(
    request: Request,
    model_id: int,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    row = db.query(VisionModel).filter_by(id=model_id).first()
    if row is None:
        raise HTTPException(404)
    if row.is_default:
        raise HTTPException(400, "cannot delete the default model — change default first")
    in_use = db.query(VisionRun).filter(VisionRun.model == row.slug).first() is not None
    if in_use:
        raise HTTPException(409, "model in use by historical scans — disable instead")
    db.delete(row)
    db.commit()
    return HTMLResponse("")  # row is removed via hx-swap=outerHTML


def _render_row(
    request: Request, row: VisionModel, user: CurrentUser, flash: str | None = None
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/_vision_models_row.html",
        {"r": row, "user": user, "flash": flash},
    )
```

- [ ] **Step 4: Run tests.** `uv run pytest tests/test_admin_vision_models.py -v` — expect PASS.
- [ ] **Step 5: Commit.**

```bash
git add src/cvp/routers/admin/vision_models.py tests/test_admin_vision_models.py
git commit -m "feat(admin): vision-model row actions (set-default, disable, refresh, delete)"
```

---

### Task 9: Refactor `services/vision.py` to use OpenRouter + adapters

**Files:**
- Modify: `src/cvp/services/vision.py`
- Modify: `tests/test_vision_router.py` (create or extend) — integration test mocking `openrouter.call_vision`

- [ ] **Step 1: Write failing integration test.**

```python
# tests/test_vision_router.py
"""End-to-end test of run_scan with OpenRouter mocked."""
import json
from unittest.mock import patch

from cvp.db import SessionLocal
from cvp.models import EvidenceFile, Item, ItemCrop, VisionRun
from cvp.models_vision import VisionModel
from cvp.services import vision as vision_svc


def test_run_scan_creates_items_and_crops(matter_with_image, client_admin):
    """matter_with_image: fixture that creates a matter with one uploaded
    image evidence file. See tests/conftest.py — write the fixture if missing."""
    matter_id, file_id = matter_with_image

    fake_response = json.dumps([
        {
            "description": "Samsung 65-inch QLED TV",
            "brand": "Samsung",
            "model": "QN65Q80C",
            "category_hint": "Electronics, TVs and displays",
            "quantity": 1,
            "condition": "average",
            "search_hint": "Samsung 65 QLED QN65Q80C",
            "room_hint": "Living Room",
            "confidence": "high",
            "bounding_box": [100, 100, 500, 400],
        }
    ])

    job_id = vision_svc.create_job([file_id])
    with patch(
        "cvp.services.vision.openrouter.call_vision",
        return_value=fake_response,
    ):
        vision_svc.run_scan(job_id, matter_id, [file_id], "anthropic/claude-opus-4")

    db = SessionLocal()
    try:
        items = db.query(Item).filter_by(matter_id=matter_id).all()
        assert len(items) == 1
        assert items[0].description == "Samsung 65-inch QLED TV"
        crops = db.query(ItemCrop).filter_by(item_id=items[0].id).all()
        assert len(crops) == 1
        runs = db.query(VisionRun).filter_by(matter_id=matter_id).all()
        assert len(runs) == 1
        assert runs[0].model == "anthropic/claude-opus-4"
        assert runs[0].adapter == "pixel_passthrough"
    finally:
        db.close()


def test_run_scan_skips_crop_when_adapter_none(matter_with_image, monkeypatch):
    matter_id, file_id = matter_with_image
    db = SessionLocal()
    try:
        db.add(VisionModel(
            slug="openai/gpt-4o", display_name="GPT-4o",
            adapter="none", supports_bbox=False, is_default=False, is_enabled=True,
        ))
        db.commit()
    finally:
        db.close()

    fake_response = json.dumps([{
        "description": "Anything", "category_hint": "Miscellaneous household goods",
        "quantity": 1, "condition": "average", "bounding_box": [0, 0, 100, 100],
    }])
    job_id = vision_svc.create_job([file_id])
    with patch("cvp.services.vision.openrouter.call_vision", return_value=fake_response):
        vision_svc.run_scan(job_id, matter_id, [file_id], "openai/gpt-4o")

    db = SessionLocal()
    try:
        items = db.query(Item).filter_by(matter_id=matter_id).all()
        assert len(items) == 1
        crops = db.query(ItemCrop).filter_by(item_id=items[0].id).all()
        assert len(crops) == 0  # adapter=none -> no crop
    finally:
        db.close()
```

- [ ] **Step 2: Add `matter_with_image` fixture.** In `tests/conftest.py` (extend), create a fixture that:
  - inserts a `Matter` row
  - copies a tiny test JPEG (e.g. a 10x10 white square — write it once with `PIL.Image.new("RGB", (200, 200), "white").save(path)`) into the configured `upload_dir`
  - inserts an `EvidenceFile` row pointing at it with `kind="image"`, `mime_type="image/jpeg"`
  - returns `(matter_id, file_id)`

If `tests/conftest.py` already has a similar fixture, reuse it.

- [ ] **Step 3: Run.** `uv run pytest tests/test_vision_router.py -v` — expect FAIL (signature mismatch on `run_scan`).

- [ ] **Step 4: Refactor `services/vision.py`.** Replace the top of the file:

```python
"""Vision scan service — sequential image processing via OpenRouter."""

import base64
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy import func as sqlfunc

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.models import Category, EvidenceFile, Item, ItemCrop, VisionRun
from cvp.models_vision import VisionModel
from cvp.services import openrouter
from cvp.services.crop import recrop_item_crop
from cvp.services.vision_adapters import resolve as resolve_adapter
from cvp.services.vision_prompts import SCAN_PROMPT_VERSION, build_scan_prompt

logger = logging.getLogger(__name__)
```

Remove the old `import anthropic` and `_parse_bbox` function. Update `run_scan`:

```python
def run_scan(job_id: str, matter_id: str, file_ids: list[str], model_slug: str) -> None:
    """Process each evidence file sequentially via OpenRouter, creating Item +
    ItemCrop rows."""
    upload_base = Path(settings.upload_dir).resolve()
    crop_base = Path(settings.crop_dir).resolve()

    db = SessionLocal()
    try:
        vm = db.query(VisionModel).filter_by(slug=model_slug, is_enabled=True).first()
        if vm is None:
            with _lock:
                _jobs[job_id]["errors"].append(f"unknown or disabled model: {model_slug}")
                _jobs[job_id]["status"] = "error"
            return
        adapter_name = vm.adapter
        adapter_fn = resolve_adapter(adapter_name)
        cost_snapshot = vm.prompt_image_cost_cents

        categories = db.query(Category).order_by(Category.id).all()

        for idx, file_id in enumerate(file_ids):
            try:
                ef = db.get(EvidenceFile, file_id)
                if ef is None or ef.kind != "image":
                    _update_job(job_id, progress=idx + 1)
                    continue

                image_path = (upload_base / ef.stored_path).resolve()
                if not image_path.exists():
                    _update_job(job_id, progress=idx + 1)
                    continue

                with Image.open(image_path) as img:
                    img_width, img_height = img.size

                mime = ef.mime_type or "image/jpeg"
                image_bytes = image_path.read_bytes()

                raw_text = openrouter.call_vision(
                    model_slug=model_slug,
                    image_bytes=image_bytes,
                    mime_type=mime,
                    prompt=build_scan_prompt(img_width, img_height),
                )
                parsed = _parse_response(raw_text)
                items_this_file = 0

                max_line = (
                    db.query(sqlfunc.max(Item.line_number))
                    .filter(Item.matter_id == matter_id)
                    .scalar()
                    or 0
                )

                for raw_item in parsed:
                    if not isinstance(raw_item, dict):
                        continue
                    description = str(raw_item.get("description") or "").strip()
                    if not description:
                        continue

                    cat_id = _match_category_id(raw_item.get("category_hint"), categories)
                    qty = int(raw_item.get("quantity") or 1)
                    if qty < 1:
                        qty = 1
                    condition = str(raw_item.get("condition") or "average")
                    if condition not in (
                        "excellent", "above_average", "average", "below_average",
                    ):
                        condition = "average"

                    search_hint = str(raw_item.get("search_hint") or "").strip() or None

                    max_line += 1
                    item = Item(
                        matter_id=matter_id, category_id=cat_id, line_number=max_line,
                        description=description,
                        brand=str(raw_item.get("brand") or "").strip() or None,
                        model=str(raw_item.get("model") or "").strip() or None,
                        quantity=qty, age_years=0.0, condition=condition,
                        rcv_unit_cents=0, rcv_total_cents=0, acv_total_cents=0,
                        confirmed=False, search_hint=search_hint,
                        notes=(
                            f"room_hint:{raw_item.get('room_hint') or ''}"
                            f"|confidence:{raw_item.get('confidence') or 'medium'}"
                        ),
                    )
                    db.add(item)
                    db.flush()

                    bbox = adapter_fn(raw_item.get("bounding_box"), img_width, img_height)
                    if bbox is not None:
                        left, upper, right, lower = bbox
                        item_crop = ItemCrop(
                            item_id=item.id, evidence_file_id=file_id,
                            bbox_left=left, bbox_upper=upper,
                            bbox_right=right, bbox_lower=lower,
                        )
                        item_crop.crop_path = recrop_item_crop(
                            item_crop, ef, upload_base, crop_base
                        )
                        db.add(item_crop)

                    items_this_file += 1

                vr = VisionRun(
                    matter_id=matter_id,
                    evidence_file_id=file_id,
                    model=model_slug,
                    prompt_version=SCAN_PROMPT_VERSION,
                    raw_response=raw_text,
                    items_created=items_this_file,
                    adapter=adapter_name,
                    cost_cents_estimated=cost_snapshot,
                )
                db.add(vr)
                ef.scanned = True
                db.commit()

                with _lock:
                    _jobs[job_id]["progress"] = idx + 1
                    _jobs[job_id]["items_created"] += items_this_file

            except openrouter.OpenRouterError as exc:
                db.rollback()
                with _lock:
                    _jobs[job_id]["errors"].append(
                        f"File {file_id}: API error — {exc.status} {exc.message}"
                    )
                    _jobs[job_id]["progress"] = idx + 1
            except httpx.TimeoutException:
                db.rollback()
                with _lock:
                    _jobs[job_id]["errors"].append(f"File {file_id}: timeout")
                    _jobs[job_id]["progress"] = idx + 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.exception("vision scan failure")
                with _lock:
                    _jobs[job_id]["errors"].append(f"File {file_id}: {exc}")
                    _jobs[job_id]["progress"] = idx + 1

            if idx < len(file_ids) - 1:
                time.sleep(0.5)

    finally:
        db.close()

    _update_job(job_id, status="done" if not _jobs[job_id]["errors"] else "error")
```

Replace `estimate_cost`:

```python
def estimate_cost(n_images: int, model_slug: str) -> str:
    db = SessionLocal()
    try:
        vm = db.query(VisionModel).filter_by(slug=model_slug).first()
    finally:
        db.close()
    if vm is None or vm.prompt_image_cost_cents is None:
        return "~$?"
    total_cents = n_images * vm.prompt_image_cost_cents
    return f"~${total_cents / 100:.2f}"
```

Remove `_COST_PER_IMAGE_USD = 0.025`.

- [ ] **Step 5: Run tests.** `uv run pytest tests/test_vision_router.py -v` — expect PASS. Existing scan tests may need to be updated to pass `model_slug`; fix as needed.
- [ ] **Step 6: Run full suite.** `uv run pytest -q`. Triage failures — most should be call-site changes (`run_scan` signature, `estimate_cost` signature).
- [ ] **Step 7: Commit.**

```bash
git add src/cvp/services/vision.py tests/test_vision_router.py tests/conftest.py
git commit -m "refactor(vision): route scans through OpenRouter, dispatch via VisionModel"
```

---

### Task 10: Refactor `routers/vision.py` — accept model_slug, update last-used, cost estimate

**Files:**
- Modify: `src/cvp/routers/vision.py`
- Extend: `tests/test_vision_router.py`

- [ ] **Step 1: Write failing tests.**

```python
def test_start_scan_validates_model_slug(client_contributor, matter_with_image):
    matter_id, file_id = matter_with_image
    resp = client_contributor.post(
        f"/api/matters/{matter_id}/vision-scan",
        data={"evidence_file_ids": file_id, "model_slug": "made/up"},
    )
    assert resp.status_code == 400


def test_start_scan_records_last_used(client_contributor, matter_with_image):
    matter_id, file_id = matter_with_image
    resp = client_contributor.post(
        f"/api/matters/{matter_id}/vision-scan",
        data={
            "evidence_file_ids": file_id,
            "model_slug": "anthropic/claude-opus-4",
        },
    )
    assert resp.status_code == 200
    db = SessionLocal()
    try:
        from cvp.models_auth import User
        u = db.query(User).filter_by(email=CONTRIBUTOR_EMAIL).one()
        assert u.last_vision_model_slug == "anthropic/claude-opus-4"
    finally:
        db.close()


def test_estimate_cost_endpoint(client_contributor, matter_with_image):
    matter_id, _ = matter_with_image
    # Default seed has no pricing yet -> "~$?"
    resp = client_contributor.get(
        f"/api/matters/{matter_id}/vision-scan/estimate"
        "?count=3&model_slug=anthropic/claude-opus-4"
    )
    assert resp.status_code == 200
    assert "$" in resp.text
```

- [ ] **Step 2: Run.** Expect FAIL.

- [ ] **Step 3: Refactor `routers/vision.py`.** Replace the file contents:

```python
"""Vision scan endpoints — start scan, poll progress, estimate cost."""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import EvidenceFile
from cvp.models_auth import User
from cvp.models_vision import VisionModel
from cvp.services import vision as vision_svc
from cvp.services.audit import get_client_ip, write_audit_log

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


@router.post("/api/matters/{matter_id}/vision-scan", response_class=HTMLResponse)
async def start_scan(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("contributor")),
    evidence_file_ids: list[str] = Form(default=[]),
    model_slug: str = Form(...),
) -> HTMLResponse:
    if not evidence_file_ids:
        return HTMLResponse(
            '<p class="text-sm text-red-600">Select at least one image to scan.</p>'
        )

    db = SessionLocal()
    try:
        vm = db.query(VisionModel).filter_by(slug=model_slug, is_enabled=True).first()
        if vm is None:
            raise HTTPException(400, f"unknown or disabled vision model: {model_slug}")

        files = (
            db.query(EvidenceFile)
            .filter(
                EvidenceFile.id.in_(evidence_file_ids),
                EvidenceFile.matter_id == matter_id,
                EvidenceFile.kind == "image",
            )
            .all()
        )
        image_ids = [f.id for f in files]

        # Update last-used
        u = db.query(User).filter_by(id=user.id).first()
        if u is not None:
            u.last_vision_model_slug = model_slug
            db.commit()
    finally:
        db.close()

    if not image_ids:
        return HTMLResponse(
            '<p class="text-sm text-red-600">No image files selected.</p>'
        )

    job_id = vision_svc.create_job(image_ids)
    background_tasks.add_task(
        vision_svc.run_scan, job_id, matter_id, image_ids, model_slug
    )
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="vision.run",
        resource_type="matter",
        resource_id=matter_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
        detail=f"model={model_slug}",
    )

    job = vision_svc.get_job(job_id)
    html = templates.get_template("_scan_progress.html").render(
        job_id=job_id, matter_id=matter_id, **job
    )
    return HTMLResponse(html)


@router.get("/api/matters/{matter_id}/vision-scan/{job_id}", response_class=HTMLResponse)
def poll_scan(
    matter_id: str, job_id: str,
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> HTMLResponse:
    job = vision_svc.get_job(job_id)
    if job is None:
        return HTMLResponse('<p class="text-sm text-red-600">Scan job not found.</p>')
    html = templates.get_template("_scan_progress.html").render(
        job_id=job_id, matter_id=matter_id, **job
    )
    return HTMLResponse(html)


@router.get("/api/matters/{matter_id}/vision-scan/estimate", response_class=HTMLResponse)
def estimate(
    matter_id: str,
    count: int,
    model_slug: str,
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> HTMLResponse:
    label = vision_svc.estimate_cost(count, model_slug)
    return HTMLResponse(f'<span id="cost-estimate" class="text-xs text-gray-500">{label}</span>')
```

> Note: ordering of routes matters here. Put the more specific `…/vision-scan/estimate` and `…/vision-scan/{job_id}` routes such that `estimate` is matched before the `{job_id}` route. With FastAPI, register the static path **before** the dynamic one, OR rely on the fact that `estimate` is a plain string while job_ids are also plain strings — to be safe, change the estimate path to `/api/matters/{matter_id}/vision-scan-estimate` to avoid the collision. Update the test accordingly.

- [ ] **Step 4: Run tests.** `uv run pytest tests/test_vision_router.py -v` — expect PASS.
- [ ] **Step 5: Commit.**

```bash
git add src/cvp/routers/vision.py tests/test_vision_router.py
git commit -m "feat(vision): per-scan model_slug picker, cost-estimate endpoint"
```

---

### Task 11: Per-scan picker UI

**Files:**
- Modify: `src/cvp/templates/_evidence_grid.html`
- Modify: `src/cvp/routers/matters.py` — pass enabled vision models + user default into evidence-grid context
- Create: `src/cvp/templates/_vision_model_picker.html`

- [ ] **Step 1: Locate where the evidence grid template is rendered.** `grep -rn "_evidence_grid" src/cvp/`. The matter detail handler in `routers/matters.py` likely passes `evidence_files`; we need to also pass `vision_models` and `default_model_slug`.

- [ ] **Step 2: Update the matter handler.** In `routers/matters.py`, find the handler rendering `matter_detail.html` (or the partial that includes `_evidence_grid.html`) and add to the template context:

```python
from cvp.models_vision import VisionModel

# Inside the handler, after fetching the matter:
vision_models = (
    db.query(VisionModel)
    .filter_by(is_enabled=True)
    .order_by(VisionModel.recommended.desc(), VisionModel.display_name.asc())
    .all()
)
default_slug = (
    user.last_vision_model_slug
    if user.last_vision_model_slug
       and any(vm.slug == user.last_vision_model_slug for vm in vision_models)
    else next((vm.slug for vm in vision_models if vm.is_default), None)
)
context["vision_models"] = vision_models
context["default_vision_slug"] = default_slug
```

(Adjust to whatever the existing context-building pattern looks like; reuse the response template-render call.)

- [ ] **Step 3: Create the picker partial.**

```html
<!-- src/cvp/templates/_vision_model_picker.html -->
<div id="vision-model-picker-row" class="mb-3 flex items-center gap-3 text-sm">
  <label for="model_slug" class="font-medium text-gray-700">Vision model:</label>
  <select id="model_slug" name="model_slug"
          hx-get="/api/matters/{{ matter_id }}/vision-scan-estimate"
          hx-trigger="change"
          hx-target="#cost-estimate"
          hx-swap="outerHTML"
          hx-vals='{"count": {{ evidence_files | selectattr("kind", "equalto", "image") | list | length }}}'
          class="rounded border px-2 py-1">
    {% for vm in vision_models %}
    <option value="{{ vm.slug }}" {% if vm.slug == default_vision_slug %}selected{% endif %}>
      {{ vm.display_name }}
      {% if vm.prompt_image_cost_cents is not none %}— ~${{ "%.4f"|format(vm.prompt_image_cost_cents / 100) }}/img{% endif %}
      {% if not vm.supports_bbox %} 📎 (no auto-crop){% endif %}
      {% if vm.recommended %} ★{% endif %}
    </option>
    {% endfor %}
  </select>
  <span id="cost-estimate" class="text-xs text-gray-500"></span>
</div>
```

- [ ] **Step 4: Wire the picker into `_evidence_grid.html`.** At the very top of the file, before `<div id="evidence-grid">`:

```html
{% include "_vision_model_picker.html" %}
```

And modify each per-file `<form hx-post="/api/matters/{{ matter_id }}/vision-scan" ...>` to include the picker value via `hx-include`:

```html
<form hx-post="/api/matters/{{ matter_id }}/vision-scan"
      hx-target="#scan-progress-{{ f.id }}"
      hx-include="#model_slug"
      hx-swap="innerHTML"
      class="mt-1">
```

- [ ] **Step 5: Manual smoke test.** Start the dev server (`uv run dev`), log in, open a matter with an unscanned image, confirm:
  - the picker shows at least the seeded `Claude Opus 4` row
  - changing the picker triggers a cost-estimate refresh
  - clicking "Scan Now" sends `model_slug` in the form payload (verify via the browser network tab; the actual scan call will hit OpenRouter — that's expected at this point because the picker test is a real round trip)
- [ ] **Step 6: Commit.**

```bash
git add src/cvp/templates/_evidence_grid.html \
        src/cvp/templates/_vision_model_picker.html \
        src/cvp/routers/matters.py
git commit -m "feat(vision): per-scan model picker in evidence grid"
```

---

### Task 12: Audit-log integration for admin actions

**Files:**
- Modify: `src/cvp/routers/admin/vision_models.py`

- [ ] **Step 1: Add audit-log writes to each mutating handler.** Use the existing `write_audit_log` from `services/audit`. Example pattern (already used in `routers/admin/system.py`):

```python
from cvp.services.audit import get_client_ip, write_audit_log

# In add_model, after db.commit():
write_audit_log(
    user_id=user.id,
    action="vision_model.add",
    resource_type="vision_model",
    resource_id=str(row.id),
    detail=f"slug={slug} adapter={adapter}",
    ip_address=get_client_ip(request),
)

# Likewise for set_default ("vision_model.set_default"),
# disable/enable ("vision_model.disable"/"enable"),
# refresh_pricing ("vision_model.refresh_pricing"),
# delete ("vision_model.delete").
```

- [ ] **Step 2: Update existing admin tests.** Assert one audit-log entry is written per action. Reuse the audit-log assertion pattern from `tests/test_audit.py` if present.

- [ ] **Step 3: Run tests.** `uv run pytest tests/test_admin_vision_models.py -v` — expect PASS.
- [ ] **Step 4: Commit.**

```bash
git add src/cvp/routers/admin/vision_models.py tests/test_admin_vision_models.py
git commit -m "feat(audit): record vision_model admin actions"
```

---

### Task 13: `.env.example` + lint + final smoke

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Update `.env.example`.** Append:

```
# OpenRouter — vision provider
OPENROUTER_API_KEY=
OPENROUTER_REFERER=https://your-domain.example
OPENROUTER_APP_TITLE=CVP

# Deprecated — replaced by OpenRouter; remove after one release.
# ANTHROPIC_API_KEY=
# VISION_MODEL=
# VISION_MODEL_FALLBACK=
```

- [ ] **Step 2: Run lint.** `uv run ruff check . && uv run ruff format .`. Fix any issues.
- [ ] **Step 3: Run full test suite.** `uv run pytest -q`. Expect PASS.
- [ ] **Step 4: Manual smoke test.** With a real `OPENROUTER_API_KEY` in `.env`:
  - `uv run dev`
  - Log in as system admin → `/admin/vision-models` → Add `google/gemini-2.5-pro` (suggested adapter `gemini_normalized_1000`).
  - Set Gemini as default; reload matter detail; picker shows Gemini and Claude Opus.
  - Run a scan with each model on the same image; check `VisionRun.adapter` and `VisionRun.model` are recorded correctly. Verify Items are created in both runs and crops appear under both.
- [ ] **Step 5: Commit.**

```bash
git add .env.example
git commit -m "docs(env): document OpenRouter env vars; mark Anthropic ones deprecated"
```

---

## Self-review notes

**Spec coverage check:**
- Provider client replaced — Task 9.
- `vision_models` table — Task 4.
- User `last_vision_model_slug` — Task 4.
- `VisionRun.adapter` and `VisionRun.cost_cents_estimated` — Task 4.
- Adapter registry — Task 2.
- Configuration changes — Tasks 1, 13.
- Admin index — Task 6.
- Admin add flow with live OpenRouter catalog + 1-hour cache — Task 7.
- Refresh pricing, soft-disable, hard-delete with in-use guard, default-flip — Task 8.
- `RECOMMENDED_SLUGS`, `ADAPTER_SUGGESTIONS` — Task 5.
- Per-scan picker, last-used preference, cost-estimate endpoint with HTMX reactivity — Tasks 10, 11.
- Cost display fallback to `~$?` — Task 9 (`estimate_cost` returns the literal string).
- Error taxonomy: `OpenRouterError`, `httpx.TimeoutException`, bare `Exception` — Task 9.
- 500 ms inter-call sleep retained — Task 9.
- No automatic fallback — confirmed (no fallback code added).
- Audit-log entries for admin actions — Task 12.
- `.env.example` update — Task 13.

**Out of scope (per spec, intentionally not in plan):**
- Removing the `anthropic` package from `pyproject.toml`.
- Per-image model selection.
- Auto-fallback on error.
- Cost dashboards / budget caps.
- Streaming responses.

**Known unknowns the executor will need to resolve in-flight:**
- Exact pattern of the `client_admin` / `client_contributor` test fixtures — read `tests/conftest.py` and `tests/test_admin_system.py` first.
- Where matter-detail rendering reads `evidence_files` from — `routers/matters.py` is the likely location but the engineer should `grep -rn "_evidence_grid" src/cvp/templates/` to find the include site.
- Python's `round()` half-to-even behavior may make `parse_pricing_to_cents("0.025")` return 2 rather than 3 cents; tests should match implementation, not the other way around.
- Whether the existing scan UI for already-scanned files (the "Edit crops" button) needs any change — it should not, but verify the partial still renders cleanly.
