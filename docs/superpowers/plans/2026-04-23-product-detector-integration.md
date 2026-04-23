# Product Detector Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate auto-cropping of items from evidence photos and Google Lens RCV search into the Items tab, allowing specialists to find and apply prices in one click.

**Architecture:** A new `item_crops` table stores per-item bounding boxes and crop JPEG paths generated during Vision scans. A new `serp_searches` table records every Google Lens call tied to a specific crop. The Items tab gets an inline "Find price" panel that shows the crop, runs a Lens search, and pre-fills the item's RCV fields from a result.

**Tech Stack:** SQLAlchemy 2.x + Alembic migrations, Pillow for image cropping, httpx for SerpAPI calls, HTMX for the inline panel, Jinja2 partials, FastAPI.

---

## File Map

**New files:**
- `src/cvp/services/serp.py` — SerpAPI caller (`call_serp`, `build_crop_url`)
- `src/cvp/services/serp_display.py` — result extractor (`extract_results`)
- `src/cvp/routers/serp.py` — 4 endpoints + crop file serving
- `src/cvp/templates/_serp_panel.html` — inline search panel (inserted after item row)
- `src/cvp/templates/_serp_result.html` — result cards partial
- `tests/test_serp_display.py` — unit tests for result extractor
- `tests/test_vision_prompts.py` — unit tests for `build_scan_prompt`

**Modified files:**
- `pyproject.toml` — add `pillow`, promote `httpx` to main deps
- `src/cvp/config.py` — add `serp_api_key`, `public_base_url`, `crop_dir`
- `src/cvp/models.py` — add `ItemCrop`, `SerpSearch`, `Item.search_hint`, relationships
- `src/cvp/services/vision_prompts.py` — replace with merged v3 prompt + `build_scan_prompt()`
- `src/cvp/services/vision.py` — Pillow cropping, bbox parsing, `ItemCrop` creation, `search_hint` field
- `src/cvp/routers/items.py` — add `selectinload(Item.crops)` to all single-item fetches; update `_items_tbody_html`
- `src/cvp/main.py` — register serp router
- `src/cvp/templates/_item_row.html` — "Find price" / no-crop indicator; fix `search_hint` from notes
- `src/cvp/templates/_items_tbody.html` — same changes as `_item_row.html`
- `src/cvp/static/app.js` — add `toggleSerpPanel()` helper

---

## Task 1: Add Dependencies and Config

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/cvp/config.py`

- [ ] **Step 1: Add pillow and promote httpx in pyproject.toml**

In `pyproject.toml`, update the `dependencies` list and `dev` group:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "pydantic-settings>=2.0",
    "anthropic>=0.40",
    "weasyprint>=62",
    "pandas>=2.2",
    "pillow>=10.0",
    "httpx>=0.27",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
]
```

- [ ] **Step 2: Add config fields**

Replace the entire content of `src/cvp/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    vision_model: str = "claude-opus-4-6"
    vision_model_fallback: str = "claude-sonnet-4-6"
    port: int = 8000
    database_url: str = "sqlite:///./data/cvp.db"
    upload_dir: str = "./data/uploads"
    export_dir: str = "./data/exports"
    crop_dir: str = "./data/crops"
    serp_api_key: str = ""
    public_base_url: str = ""
    company_name: str = "Contents Valuation LLC"
    company_address: str = ""
    company_email: str = ""
    company_phone: str = ""


settings = Settings()
```

- [ ] **Step 3: Sync dependencies**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && uv sync
```

Expected: Resolving dependencies... Done (pillow and httpx appear in output).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml src/cvp/config.py
git commit -m "feat: add pillow, httpx deps; add serp/crop config fields"
```

---

## Task 2: Data Models

**Files:**
- Modify: `src/cvp/models.py`

- [ ] **Step 1: Add ItemCrop and SerpSearch models and Item.search_hint**

Add the following imports and classes to `src/cvp/models.py`. Add `search_hint` to `Item` and add `crops` relationships to `Item` and `EvidenceFile`.

At the top of models.py, the existing imports already cover what's needed. Add after the existing imports:

```python
# (no new imports needed — String, Integer, DateTime, ForeignKey, relationship already imported)
```

Add `search_hint` to the `Item` class after the `notes` field (after line 137):

```python
    search_hint: Mapped[str | None] = mapped_column(String, nullable=True)
```

Add `crops` relationship to `Item` (after line 144, in the Relationships section):

```python
    crops: Mapped[list["ItemCrop"]] = relationship(
        "ItemCrop", back_populates="item", cascade="all, delete-orphan"
    )
```

Add `crops` relationship to `EvidenceFile` (after line 170, in the Relationships section):

```python
    crops: Mapped[list["ItemCrop"]] = relationship(
        "ItemCrop", back_populates="evidence_file", cascade="all, delete-orphan"
    )
```

Append the two new model classes at the end of `src/cvp/models.py`:

```python
class ItemCrop(Base):
    """A cropped image of a single item extracted from an evidence photo."""

    __tablename__ = "item_crops"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("items.id"), nullable=False)
    evidence_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_files.id"), nullable=False
    )
    bbox_left: Mapped[int] = mapped_column(Integer, default=0)
    bbox_upper: Mapped[int] = mapped_column(Integer, default=0)
    bbox_right: Mapped[int] = mapped_column(Integer, default=0)
    bbox_lower: Mapped[int] = mapped_column(Integer, default=0)
    crop_path: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    item: Mapped["Item"] = relationship("Item", back_populates="crops")
    evidence_file: Mapped["EvidenceFile"] = relationship("EvidenceFile", back_populates="crops")
    serp_searches: Mapped[list["SerpSearch"]] = relationship(
        "SerpSearch", back_populates="item_crop", cascade="all, delete-orphan"
    )


class SerpSearch(Base):
    """A SerpAPI search run against a specific item crop."""

    __tablename__ = "serp_searches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    item_crop_id: Mapped[str] = mapped_column(
        String, ForeignKey("item_crops.id"), nullable=False
    )
    service: Mapped[str] = mapped_column(String, default="google_lens")
    image_url: Mapped[str] = mapped_column(String, default="")
    request_url: Mapped[str] = mapped_column(String, default="")
    request_params: Mapped[str] = mapped_column(Text, default="")
    response_json: Mapped[str] = mapped_column(Text, default="")
    status_code: Mapped[int] = mapped_column(Integer, default=0)
    ran_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    item_crop: Mapped["ItemCrop"] = relationship("ItemCrop", back_populates="serp_searches")
```

- [ ] **Step 2: Commit**

```bash
git add src/cvp/models.py
git commit -m "feat: add ItemCrop and SerpSearch models; add Item.search_hint"
```

---

## Task 3: Alembic Migration

**Files:**
- Create: `migrations/versions/<hash>_item_crops_serp_searches_search_hint.py`

- [ ] **Step 1: Generate the migration**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && uv run alembic revision --autogenerate -m "item_crops_serp_searches_search_hint"
```

Expected: `Generating .../migrations/versions/<hash>_item_crops_serp_searches_search_hint.py`

- [ ] **Step 2: Open the generated migration file and add the backfill**

The autogenerated file will have `upgrade()` and `downgrade()`. After the table creation ops, add the `search_hint` backfill. Find the generated file (it's the newest file in `migrations/versions/`) and edit `upgrade()` to add at the end, before `pass` or after the last `op.create_table` / `op.add_column` call:

```python
# Backfill search_hint from the "search_hint:..." fragment in item notes
import re as _re
from alembic import op as _op
import sqlalchemy as sa

def upgrade() -> None:
    # --- autogenerated ops above (keep them) ---
    # (op.create_table for item_crops, op.create_table for serp_searches,
    #  op.add_column for items.search_hint will be here from autogenerate)

    # Backfill: parse search_hint from notes field
    conn = _op.get_bind()
    rows = conn.execute(sa.text("SELECT id, notes FROM items WHERE notes LIKE '%search_hint:%'")).fetchall()
    for row in rows:
        match = _re.search(r'search_hint:([^|]*)', row.notes or "")
        hint = match.group(1).strip() if match else None
        if hint:
            conn.execute(
                sa.text("UPDATE items SET search_hint = :hint WHERE id = :id"),
                {"hint": hint, "id": row.id},
            )
        # Strip search_hint segment from notes
        cleaned = _re.sub(r'\|?search_hint:[^|]*', '', row.notes or "").strip("|").strip()
        conn.execute(
            sa.text("UPDATE items SET notes = :notes WHERE id = :id"),
            {"notes": cleaned, "id": row.id},
        )
```

**Important:** The autogenerated `upgrade()` function already exists — add the backfill code at the END of that function, inside it. Do not replace the autogenerated table/column creation ops.

- [ ] **Step 3: Apply the migration**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && uv run alembic upgrade head
```

Expected: `Running upgrade <prev> -> <new>, item_crops_serp_searches_search_hint`

- [ ] **Step 4: Verify tables exist**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && python -c "
from cvp.db import engine
from sqlalchemy import inspect
i = inspect(engine)
print(i.get_table_names())
print(i.get_columns('item_crops'))
print(i.get_columns('serp_searches'))
"
```

Expected: `['categories', 'evidence_files', 'item_crops', 'items', 'matters', 'rooms', 'serp_searches', 'vision_runs']` and columns for both new tables.

- [ ] **Step 5: Commit**

```bash
git add migrations/
git commit -m "feat: migration — item_crops, serp_searches, Item.search_hint with backfill"
```

---

## Task 4: Vision Prompt v3

**Files:**
- Modify: `src/cvp/services/vision_prompts.py`
- Create: `tests/test_vision_prompts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_vision_prompts.py`:

```python
"""Tests for vision prompt v3."""

from cvp.services.vision_prompts import SCAN_PROMPT_VERSION, build_scan_prompt


def test_version_is_v3():
    assert SCAN_PROMPT_VERSION == "v3"


def test_build_scan_prompt_injects_dimensions():
    prompt = build_scan_prompt(1920, 1080)
    assert "1920" in prompt
    assert "1080" in prompt
    assert "1920×1080" in prompt


def test_build_scan_prompt_contains_bounding_box():
    prompt = build_scan_prompt(800, 600)
    assert '"bounding_box"' in prompt


def test_build_scan_prompt_contains_insurance_framing():
    prompt = build_scan_prompt(800, 600)
    assert "insurance claim" in prompt
    assert "contents inventory specialist" in prompt


def test_build_scan_prompt_contains_category_hints():
    prompt = build_scan_prompt(800, 600)
    assert "Electronics, TVs and displays" in prompt
    assert "Miscellaneous household goods" in prompt


def test_build_scan_prompt_contains_search_hint():
    prompt = build_scan_prompt(800, 600)
    assert '"search_hint"' in prompt


def test_build_scan_prompt_bbox_example_coordinates_are_in_bounds():
    w, h = 640, 480
    prompt = build_scan_prompt(w, h)
    # ex_left = round(w * 2/3) = 427, ex_right = w - 20 = 620, ex_lower = round(h * 0.85) = 408
    assert "427" in prompt
    assert "620" in prompt
    assert "408" in prompt
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && uv run pytest tests/test_vision_prompts.py -v
```

Expected: All 7 tests FAIL (ImportError or AttributeError since `build_scan_prompt` doesn't exist yet).

- [ ] **Step 3: Replace vision_prompts.py with merged v3 prompt**

Replace the entire content of `src/cvp/services/vision_prompts.py`:

```python
"""Versioned prompts for the Vision scan service.

v3 — merged from:
  - tor v2: insurance framing, RCV documentation purpose, category hints
  - productdetector v7: bounding box guidance (generous, overlapping ok, skip partial/racked items)
"""

# NOTE: ruff E501 (line length) is suppressed for this file in pyproject.toml
_SCAN_PROMPT_V3_TEMPLATE = """You are an expert contents inventory specialist helping document personal property for an insurance claim. Your goal is to produce line items detailed enough that a pricing researcher can find an exact or near-exact replacement on a retail website within 60 seconds.

The image is exactly {width}×{height} pixels (width × height). All bounding box coordinates must be within these bounds.

Examine this photo carefully and identify every distinct personal property item visible. For each item, return a JSON object.

Return ONLY a JSON array with no preamble, explanation, or markdown fences. Each object must have these exact keys:

- "bounding_box": [left, upper, right, lower] — pixel coordinates of the item's bounding box relative to the original image dimensions (top-left origin, x increases right, y increases down).
  Estimate carefully; every item MUST have one. Ensure 0 ≤ left < right ≤ {width} and 0 ≤ upper < lower ≤ {height}.
  Be GENEROUS — it is far better to include extra background than to clip any part of the item.
  Extend each edge an extra 10–15% past where you think the item ends.
  Include the full item extent: soles of footwear, legs of furniture, handles, straps, and any protruding parts.
  For footwear, always extend the lower edge to include the complete sole resting on the surface.
  Bounding boxes MAY overlap with the bounding boxes of other items — this is expected and encouraged.
  Do NOT shrink a box to avoid overlapping a neighbor; always prioritize capturing the full item.
  Example for an item in the right third of this image: [{ex_left}, 100, {ex_right}, {ex_lower}]

- "description": specific item name including any size, color, material, or style visible
  (e.g. "65-inch Samsung QLED 4K Smart TV", "gray L-shaped microfiber sectional sofa",
  "KitchenAid 5-quart stand mixer, red", "Dewalt 20V cordless drill, model DCD777")
  Be as specific as possible — generic names like "TV" or "sofa" are not acceptable.

- "brand": PRIORITY FIELD. Examine the image carefully for:
    • Logos on the product itself (front panel, label, tag, screen, housing)
    • Text printed or embossed on the item
    • Packaging, boxes, or manuals visible nearby
    • Distinctive design language that strongly implies a brand (e.g. KitchenAid color, Apple product shape)
  Return the brand name string if identified with any reasonable confidence. Return null only if truly unidentifiable.

- "model": model name or number if visible anywhere in the image (labels, screens, packaging). Return null if not visible.

- "category_hint": one of these exact strings:
    "Clothing, everyday", "Clothing, outerwear and formal", "Clothing, children",
    "Footwear", "Accessories (belts, bags, scarves, hats)", "Designer handbags and luxury accessories",
    "Jewelry", "Watches", "Furniture, upholstered (sofas, chairs)", "Furniture, wood case goods",
    "Furniture, mattresses and box springs", "Bedding, linens, towels",
    "Window treatments (curtains, blinds, shades)", "Rugs, machine-made", "Rugs, handmade or antique",
    "Kitchen appliances, large", "Kitchen appliances, small", "Cookware, bakeware, utensils",
    "Dinnerware, glassware, flatware", "Small kitchen goods (storage, serveware)",
    "Electronics, TVs and displays", "Electronics, computers and tablets", "Electronics, smartphones",
    "Electronics, audio and home theater", "Electronics, cameras and lenses",
    "Electronics, gaming consoles and games", "Electronics, small and miscellaneous",
    "Books, records, physical media", "Toys and games", "Sporting goods and exercise equipment",
    "Outdoor furniture and grills", "Outdoor equipment (lawn, garden, tools)",
    "Power tools and workshop", "Hand tools and hardware", "Musical instruments",
    "Artwork", "Collectibles and memorabilia", "Precious metals and coins",
    "Food, pantry, household consumables", "Personal care and cosmetics",
    "Office supplies and stationery", "Miscellaneous household goods"

- "quantity": integer count of identical items visible (default 1)

- "condition": one of "excellent", "above_average", "average", "below_average"
  Base this on visible wear, damage, fading, or age cues in the photo.

- "search_hint": a concise search query string (under 80 characters) that a researcher could
  paste directly into Amazon or Google Shopping to find this exact item.
  Include brand + key model details + size/color where known.
  Example: "Samsung 65 inch QLED 4K Smart TV QN65Q80C"
  Example: "KitchenAid 5qt stand mixer empire red KSM150"
  Example: "Dewalt 20V MAX cordless drill driver DCD777"

- "room_hint": room name if inferable from surroundings (e.g. "Living Room", "Kitchen", "Master Bedroom"), otherwise null

- "confidence": "high" (brand/model clearly visible), "medium" (brand inferred, model unknown), or "low" (item type clear but brand uncertain)

Rules:
- Every identified item MUST have a bounding_box. Never omit it.
- CRITICAL: Only include items where the ENTIRE item is fully visible within the frame. If any part of an item is cut off by the image edge, obscured by another object, or extends beyond what you can see, SKIP it entirely. A partial item is worse than no item.
- CRITICAL: Only detect items that are individually placed — lying flat on a surface, leaning freely against a wall, or set down as a standalone object. SKIP any item that is slotted into, hanging on, or packed tightly in a display rack, wire shelving, bookcase, cabinet, pegboard, or retail display stand. If an item is flush against other items on two or more sides with no visible gap between them, skip it.
- Only include clearly visible personal property. Exclude structural elements (walls, floors, built-in fixtures, plumbing), whiteboards, easels, and display furniture.
- Skip items too blurry or too small to identify at "low" confidence or better.
- If the same item appears multiple times and they are individually placed, use quantity rather than separate entries, and draw the box around the cluster.
- Return ONLY the JSON array. No commentary before or after.
"""

SCAN_PROMPT_VERSION = "v3"


def build_scan_prompt(width: int, height: int) -> str:
    """Return the v3 scan prompt with actual image dimensions substituted in."""
    return _SCAN_PROMPT_V3_TEMPLATE.format(
        width=width,
        height=height,
        ex_left=round(width * 2 / 3),
        ex_right=width - 20,
        ex_lower=round(height * 0.85),
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && uv run pytest tests/test_vision_prompts.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cvp/services/vision_prompts.py tests/test_vision_prompts.py
git commit -m "feat: vision prompt v3 — merge bbox guidance from productdetector with insurance framing"
```

---

## Task 5: Update Vision Service for Bbox + Auto-Cropping

**Files:**
- Modify: `src/cvp/services/vision.py`

- [ ] **Step 1: Replace the run_scan function**

The key changes to `src/cvp/services/vision.py`:
1. Import `PIL.Image` and `build_scan_prompt`
2. Read image dimensions before the API call
3. Parse `bounding_box` from each Vision response item
4. Apply 15% padding, clamp to bounds, crop with Pillow
5. Save crop to `data/crops/{evidence_file_id}/{item_id}.jpg`
6. Create `ItemCrop` row alongside each `Item` row
7. Write `search_hint` to `Item.search_hint` (not `notes`)

Replace the entire content of `src/cvp/services/vision.py`:

```python
"""Vision scan service — sequential image processing via Anthropic API."""

import base64
import json
import re
import threading
import time
import uuid
from pathlib import Path

import anthropic
from PIL import Image

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.models import Category, EvidenceFile, Item, ItemCrop, VisionRun
from cvp.services.vision_prompts import SCAN_PROMPT_VERSION, build_scan_prompt

# ---------------------------------------------------------------------------
# In-memory job registry (single-user local app — no persistence needed)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def create_job(file_ids: list[str]) -> str:
    job_id = str(uuid.uuid4())[:8]
    with _lock:
        _jobs[job_id] = {
            "status": "running",  # running | done | error
            "progress": 0,
            "total": len(file_ids),
            "items_created": 0,
            "errors": [],
        }
    return job_id


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def _update_job(job_id: str, **kwargs) -> None:
    with _lock:
        _jobs[job_id].update(kwargs)


# ---------------------------------------------------------------------------
# Category matching
# ---------------------------------------------------------------------------

def _match_category_id(hint: str | None, categories: list[Category]) -> int:
    """Best-effort fuzzy match of Vision's category_hint to a DB category id."""
    if not hint:
        return categories[-1].id  # Miscellaneous household goods

    hint_lower = hint.lower()
    # Exact or substring match
    for cat in categories:
        if hint_lower in cat.name.lower() or cat.name.lower() in hint_lower:
            return cat.id
    # Word-level match
    hint_words = set(hint_lower.split())
    best_id, best_score = categories[-1].id, 0
    for cat in categories:
        cat_words = set(cat.name.lower().split(",")[0].split())
        score = len(hint_words & cat_words)
        if score > best_score:
            best_score, best_id = score, cat.id
    return best_id


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_response(text: str) -> list[dict]:
    """Extract a JSON array from the model response, tolerating markdown fences."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return []


# ---------------------------------------------------------------------------
# Bounding box helpers
# ---------------------------------------------------------------------------

def _parse_bbox(raw: object, img_width: int, img_height: int) -> tuple[int, int, int, int] | None:
    """
    Parse and validate a bounding_box value from the Vision response.

    Returns (left, upper, right, lower) clamped to image bounds with 15% padding,
    or None if the bbox is missing or malformed.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        left, upper, right, lower = (int(v) for v in raw)
    except (TypeError, ValueError):
        return None

    # Apply 15% generous padding
    pad_x = round((right - left) * 0.15)
    pad_y = round((lower - upper) * 0.15)
    left = max(0, left - pad_x)
    upper = max(0, upper - pad_y)
    right = min(img_width, right + pad_x)
    lower = min(img_height, lower + pad_y)

    if left >= right or upper >= lower:
        return None
    return left, upper, right, lower


# ---------------------------------------------------------------------------
# Core scan logic (called from BackgroundTasks thread)
# ---------------------------------------------------------------------------

def run_scan(job_id: str, matter_id: str, file_ids: list[str]) -> None:
    """Process each evidence file sequentially, creating Item + ItemCrop rows."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    upload_base = Path(settings.upload_dir).resolve()
    crop_base = Path(settings.crop_dir).resolve()

    db = SessionLocal()
    try:
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

                # Read image dimensions for the prompt
                with Image.open(image_path) as img:
                    img_width, img_height = img.size

                mime = ef.mime_type or "image/jpeg"
                image_data = base64.standard_b64encode(image_path.read_bytes()).decode()

                response = client.messages.create(
                    model=settings.vision_model,
                    max_tokens=4096,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime,
                                        "data": image_data,
                                    },
                                },
                                {"type": "text", "text": build_scan_prompt(img_width, img_height)},
                            ],
                        }
                    ],
                )

                raw_text = response.content[0].text if response.content else ""
                parsed = _parse_response(raw_text)
                items_this_file = 0

                from sqlalchemy import func as sqlfunc

                max_line = (
                    db.query(sqlfunc.max(Item.line_number))
                    .filter(Item.matter_id == matter_id)
                    .scalar()
                    or 0
                )

                # Prepare crop output directory
                crop_dir = crop_base / file_id
                crop_dir.mkdir(parents=True, exist_ok=True)

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
                    if condition not in ("excellent", "above_average", "average", "below_average"):
                        condition = "average"

                    search_hint = str(raw_item.get("search_hint") or "").strip() or None

                    max_line += 1
                    item = Item(
                        matter_id=matter_id,
                        category_id=cat_id,
                        line_number=max_line,
                        description=description,
                        brand=str(raw_item.get("brand") or "").strip() or None,
                        model=str(raw_item.get("model") or "").strip() or None,
                        quantity=qty,
                        age_years=0.0,
                        condition=condition,
                        rcv_unit_cents=0,
                        rcv_total_cents=0,
                        acv_total_cents=0,
                        confirmed=False,
                        search_hint=search_hint,
                        notes=(
                            f"room_hint:{raw_item.get('room_hint') or ''}"
                            f"|confidence:{raw_item.get('confidence') or 'medium'}"
                        ),
                    )
                    db.add(item)
                    db.flush()  # get item.id before creating ItemCrop

                    # Attempt crop
                    bbox = _parse_bbox(raw_item.get("bounding_box"), img_width, img_height)
                    if bbox:
                        left, upper, right, lower = bbox
                        crop_filename = f"{item.id}.jpg"
                        crop_dest = crop_dir / crop_filename
                        with Image.open(image_path) as img:
                            cropped = img.crop((left, upper, right, lower)).convert("RGB")
                            cropped.save(crop_dest, "JPEG", quality=85)
                        crop_path = f"{file_id}/{crop_filename}"
                        item_crop = ItemCrop(
                            item_id=item.id,
                            evidence_file_id=file_id,
                            bbox_left=left,
                            bbox_upper=upper,
                            bbox_right=right,
                            bbox_lower=lower,
                            crop_path=crop_path,
                        )
                        db.add(item_crop)

                    items_this_file += 1

                vr = VisionRun(
                    matter_id=matter_id,
                    evidence_file_id=file_id,
                    model=settings.vision_model,
                    prompt_version=SCAN_PROMPT_VERSION,
                    raw_response=raw_text,
                    items_created=items_this_file,
                )
                db.add(vr)
                ef.scanned = True
                db.commit()

                with _lock:
                    _jobs[job_id]["progress"] = idx + 1
                    _jobs[job_id]["items_created"] += items_this_file

            except anthropic.APIError as exc:
                db.rollback()
                with _lock:
                    _jobs[job_id]["errors"].append(f"File {file_id}: API error — {exc}")
                    _jobs[job_id]["progress"] = idx + 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                with _lock:
                    _jobs[job_id]["errors"].append(f"File {file_id}: {exc}")
                    _jobs[job_id]["progress"] = idx + 1

            if idx < len(file_ids) - 1:
                time.sleep(0.5)

    finally:
        db.close()

    _update_job(job_id, status="done" if not _jobs[job_id]["errors"] else "error")


# ---------------------------------------------------------------------------
# Cost estimate (rough — shown in UI before scan)
# ---------------------------------------------------------------------------

_COST_PER_IMAGE_USD = 0.025


def estimate_cost(n_images: int) -> str:
    total = n_images * _COST_PER_IMAGE_USD
    return f"~${total:.2f}"
```

- [ ] **Step 2: Run existing tests to verify nothing is broken**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && uv run pytest -v
```

Expected: All existing tests PASS (depreciation, csv_export, seed, vision_prompts).

- [ ] **Step 3: Commit**

```bash
git add src/cvp/services/vision.py
git commit -m "feat: vision service v3 — bbox parsing, Pillow auto-crop, ItemCrop rows, search_hint field"
```

---

## Task 6: Serp Services

**Files:**
- Create: `src/cvp/services/serp.py`
- Create: `src/cvp/services/serp_display.py`
- Create: `tests/test_serp_display.py`

- [ ] **Step 1: Write failing tests for serp_display**

Create `tests/test_serp_display.py`:

```python
"""Tests for SerpAPI result extraction."""

from cvp.services.serp_display import extract_results


GOOGLE_LENS_FIXTURE = {
    "visual_matches": [
        {
            "title": "KitchenAid 5-Qt. Artisan Stand Mixer",
            "source": "amazon.com",
            "link": "https://www.amazon.com/dp/B00005UP2P",
            "thumbnail": "https://example.com/thumb1.jpg",
            "source_icon": "https://example.com/amazon.ico",
            "price": {"value": "$449.99", "extracted_value": 449.99, "currency": "$"},
        },
        {
            "title": "KitchenAid Stand Mixer Red",
            "source": "target.com",
            "link": "https://www.target.com/p/12345",
            "thumbnail": "https://example.com/thumb2.jpg",
            "source_icon": None,
            "price": None,
        },
        {"title": "Mixer 3", "source": "walmart.com", "link": "https://walmart.com/p/3", "thumbnail": None, "source_icon": None},
        {"title": "Mixer 4", "source": "homedepot.com", "link": "https://homedepot.com/p/4", "thumbnail": None, "source_icon": None},
        {"title": "Mixer 5", "source": "bestbuy.com", "link": "https://bestbuy.com/p/5", "thumbnail": None, "source_icon": None},
        {"title": "Mixer 6 — should be excluded", "source": "extra.com", "link": "https://extra.com", "thumbnail": None, "source_icon": None},
    ]
}


def test_extract_google_lens_returns_up_to_5():
    results = extract_results("google_lens", GOOGLE_LENS_FIXTURE)
    assert len(results) == 5


def test_extract_google_lens_fields():
    results = extract_results("google_lens", GOOGLE_LENS_FIXTURE)
    first = results[0]
    assert first["title"] == "KitchenAid 5-Qt. Artisan Stand Mixer"
    assert first["source"] == "amazon.com"
    assert first["link"] == "https://www.amazon.com/dp/B00005UP2P"
    assert first["thumbnail"] == "https://example.com/thumb1.jpg"
    assert first["source_icon"] == "https://example.com/amazon.ico"


def test_extract_google_lens_price_cents():
    results = extract_results("google_lens", GOOGLE_LENS_FIXTURE)
    assert results[0]["price_cents"] == 44999
    assert results[1]["price_cents"] is None


def test_extract_google_lens_empty_response():
    results = extract_results("google_lens", {})
    assert results == []


def test_extract_unknown_service_returns_empty():
    results = extract_results("unknown_service", GOOGLE_LENS_FIXTURE)
    assert results == []
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && uv run pytest tests/test_serp_display.py -v
```

Expected: All 5 tests FAIL (ImportError — module doesn't exist yet).

- [ ] **Step 3: Create serp_display.py**

Create `src/cvp/services/serp_display.py`:

```python
"""Per-service result extractors for SerpAPI responses.

Public API
----------
extract_results(service, response_dict) -> list[dict]
    Returns up to 5 normalized result dicts for the given service.
    Returns [] for unmapped services or empty responses.

Each result dict has these keys (all values may be None unless noted):
    title       : str | None
    source      : str | None
    link        : str | None
    thumbnail   : str | None
    source_icon : str | None
    price_cents : int | None   — extracted price in integer cents, or None
"""

from collections.abc import Callable

_RESULT_LIMIT = 5


def extract_results(service: str, response_dict: dict) -> list[dict]:
    extractor = _EXTRACTORS.get(service)
    if extractor is None:
        return []
    return extractor(response_dict)


# ---------------------------------------------------------------------------
# Price parsing
# ---------------------------------------------------------------------------

def _parse_price_cents(price_obj: object) -> int | None:
    """Extract integer cents from a SerpAPI price object like {"extracted_value": 49.99}."""
    if not isinstance(price_obj, dict):
        return None
    extracted = price_obj.get("extracted_value")
    if extracted is None:
        return None
    try:
        return round(float(extracted) * 100)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Per-service extractors
# ---------------------------------------------------------------------------

def _extract_google_lens(response_dict: dict) -> list[dict]:
    matches = response_dict.get("visual_matches", [])[:_RESULT_LIMIT]
    return [
        {
            "title": m.get("title"),
            "source": m.get("source"),
            "link": m.get("link"),
            "thumbnail": m.get("thumbnail"),
            "source_icon": m.get("source_icon"),
            "price_cents": _parse_price_cents(m.get("price")),
        }
        for m in matches
    ]


# Dispatch table — add new services here as they are implemented
_EXTRACTORS: dict[str, Callable[[dict], list[dict]]] = {
    "google_lens": _extract_google_lens,
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && uv run pytest tests/test_serp_display.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Create serp.py service**

Create `src/cvp/services/serp.py`:

```python
"""SerpAPI caller service."""

import json
import logging
import re

import httpx

from cvp.config import settings
from cvp.models import ItemCrop

logger = logging.getLogger(__name__)

SERP_BASE = "https://serpapi.com/search"

ENGINE_MAP: dict[str, dict] = {
    "google_lens": {"engine": "google_lens"},
}

_SENSITIVE_KEYS = {"api_key"}


def _mask_key(value: str, show_chars: int = 4) -> str:
    if not value:
        return "(not set)"
    if len(value) <= show_chars:
        return "****"
    return f"****...{value[-show_chars:]}"


def _mask_params(params: dict) -> dict:
    return {
        k: (_mask_key(v) if k in _SENSITIVE_KEYS and isinstance(v, str) else v)
        for k, v in params.items()
    }


def _mask_url(url: str) -> str:
    return re.sub(r"([?&]api_key=)[^&]+", lambda m: m.group(1) + "****", url)


def build_crop_url(item_crop: ItemCrop) -> str | None:
    """Return a public URL for the crop if PUBLIC_BASE_URL is configured."""
    if settings.public_base_url and item_crop.crop_path:
        base = settings.public_base_url.rstrip("/")
        return f"{base}/crops/{item_crop.crop_path}"
    return None


def call_serp(
    service: str,
    item_crop: ItemCrop,
    image_url: str | None = None,
) -> tuple[str, dict, dict, int]:
    """
    Call SerpAPI for the given service.

    Returns (request_url, params_dict, response_dict, status_code).
    image_url takes precedence over build_crop_url() if provided.
    """
    if service not in ENGINE_MAP:
        raise ValueError(f"Unknown service: {service}")

    params: dict = {
        "api_key": settings.serp_api_key,
        **ENGINE_MAP[service],
    }

    url = image_url or build_crop_url(item_crop)
    if not url:
        return (
            SERP_BASE,
            params,
            {"error": "No image URL available. Paste a public URL or set PUBLIC_BASE_URL in .env."},
            0,
        )
    params["url"] = url

    logger.debug(
        "SerpAPI request | service=%s crop=%s params=%s",
        service,
        item_crop.id,
        _mask_params(params),
    )

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(SERP_BASE, params=params)
        status_code = response.status_code
        request_url = str(response.request.url)
        ct = response.headers.get("content-type", "")
        response_data = response.json() if "json" in ct else {"raw": response.text}
    except httpx.TimeoutException:
        logger.warning("SerpAPI timeout | service=%s crop=%s", service, item_crop.id)
        return SERP_BASE, params, {"error": "Request timed out after 30 seconds"}, 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("SerpAPI call failed | service=%s crop=%s", service, item_crop.id)
        return SERP_BASE, params, {"error": str(exc)}, 0

    logger.debug(
        "SerpAPI response | service=%s crop=%s status=%d url=%s",
        service,
        item_crop.id,
        status_code,
        _mask_url(request_url),
    )
    logger.debug(
        "SerpAPI response body | service=%s crop=%s |\n%s",
        service,
        item_crop.id,
        json.dumps(response_data, indent=2, ensure_ascii=False)[:4000],
    )

    return request_url, params, response_data, status_code
```

- [ ] **Step 6: Run all tests**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && uv run pytest -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/cvp/services/serp.py src/cvp/services/serp_display.py tests/test_serp_display.py
git commit -m "feat: add serp service and result extractor (Google Lens)"
```

---

## Task 7: Serp Router + Main Registration

**Files:**
- Create: `src/cvp/routers/serp.py`
- Modify: `src/cvp/main.py`

- [ ] **Step 1: Create the serp router**

Create `src/cvp/routers/serp.py`:

```python
"""SerpAPI search endpoints and crop file serving."""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.depreciation import compute_acv
from cvp.models import Category, Item, ItemCrop, Room, SerpSearch
from cvp.services.serp import build_crop_url, call_serp
from cvp.services.serp_display import extract_results

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["pretty_json"] = (
    lambda v: json.dumps(json.loads(v), indent=2) if v else ""
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Crop file serving
# ---------------------------------------------------------------------------

@router.get("/crops/{crop_path:path}")
def serve_crop(crop_path: str) -> FileResponse:
    crop_base = Path(settings.crop_dir).resolve()
    dest = (crop_base / crop_path).resolve()
    if not str(dest).startswith(str(crop_base)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not dest.exists():
        raise HTTPException(status_code=404, detail="Crop not found")
    return FileResponse(dest)


# ---------------------------------------------------------------------------
# Serp panel (inline panel inserted below item row)
# ---------------------------------------------------------------------------

@router.get("/api/items/{item_id}/serp-panel", response_class=HTMLResponse)
def serp_panel(item_id: str) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = (
            db.query(Item)
            .options(selectinload(Item.crops))
            .filter(Item.id == item_id)
            .first()
        )
        if not item:
            raise HTTPException(status_code=404)

        latest_by_crop: dict[str, SerpSearch | None] = {}
        display_by_crop: dict[str, list[dict]] = {}
        for crop in item.crops:
            search = (
                db.query(SerpSearch)
                .filter(SerpSearch.item_crop_id == crop.id)
                .order_by(SerpSearch.ran_at.desc())
                .first()
            )
            latest_by_crop[crop.id] = search
            if search:
                display_by_crop[crop.id] = extract_results(
                    "google_lens", json.loads(search.response_json)
                )
            else:
                display_by_crop[crop.id] = []

        public_base_url = settings.public_base_url or ""
    finally:
        db.close()

    return HTMLResponse(
        templates.get_template("_serp_panel.html").render(
            item=item,
            public_base_url=public_base_url,
            latest_by_crop=latest_by_crop,
            display_by_crop=display_by_crop,
        )
    )


# ---------------------------------------------------------------------------
# Run Google Lens search
# ---------------------------------------------------------------------------

@router.post(
    "/api/items/{item_id}/crops/{crop_id}/serp/google_lens",
    response_class=HTMLResponse,
)
async def run_google_lens(
    item_id: str,
    crop_id: str,
    request: Request,
) -> HTMLResponse:
    db = SessionLocal()
    try:
        crop = db.get(ItemCrop, crop_id)
        if not crop or crop.item_id != item_id:
            return HTMLResponse(
                "<p class='text-red-500 text-xs'>Crop not found.</p>", status_code=404
            )

        form_data = await request.form()
        image_url: str | None = str(form_data.get("image_url") or "").strip() or None

        request_url, params_dict, response_dict, status_code = call_serp(
            "google_lens", crop, image_url
        )
        used_url = image_url or build_crop_url(crop) or ""

        search = SerpSearch(
            item_crop_id=crop_id,
            service="google_lens",
            image_url=used_url,
            request_url=request_url,
            request_params=json.dumps(params_dict),
            response_json=json.dumps(response_dict),
            status_code=status_code,
        )
        db.add(search)
        db.commit()
        db.refresh(search)

        display_results = extract_results("google_lens", response_dict)
    finally:
        db.close()

    return HTMLResponse(
        templates.get_template("_serp_result.html").render(
            s=search,
            display_results=display_results,
            item_id=item_id,
        )
    )


# ---------------------------------------------------------------------------
# Apply a search result to the item (pre-fill RCV fields)
# ---------------------------------------------------------------------------

@router.post("/api/items/{item_id}/serp-apply", response_class=HTMLResponse)
async def serp_apply(
    item_id: str,
    source_url: str = Form(""),
    source_retailer: str = Form(""),
    rcv_unit_cents: str = Form(""),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = (
            db.query(Item)
            .options(selectinload(Item.crops))
            .filter(Item.id == item_id)
            .first()
        )
        if not item:
            raise HTTPException(status_code=404)

        item.source_url = source_url.strip()
        item.source_retailer = source_retailer.strip()
        item.source_captured_at = datetime.now(tz=timezone.utc)
        item.match_type = "exact"

        if rcv_unit_cents.strip():
            try:
                item.rcv_unit_cents = int(rcv_unit_cents.strip())
            except ValueError:
                pass

        cat = db.get(Category, item.category_id)
        item.rcv_total_cents = item.rcv_unit_cents * item.quantity
        item.acv_total_cents = compute_acv(
            rcv_unit_cents=item.rcv_unit_cents,
            quantity=item.quantity,
            age_years=item.age_years,
            useful_life_years=cat.useful_life_years if cat else None,
            acv_floor_pct=cat.acv_floor_pct if cat else 0.2,
            condition=item.condition,
            acv_override_cents=item.acv_override_cents,
        )
        db.commit()
        db.refresh(item)

        categories = db.query(Category).order_by(Category.id).all()
        rooms = db.query(Room).filter(Room.matter_id == item.matter_id).order_by(Room.sort_order).all()
        html = templates.get_template("_item_row.html").render(
            item=item, categories=categories, rooms=rooms
        )
    finally:
        db.close()
    return HTMLResponse(html)
```

- [ ] **Step 2: Register the serp router in main.py**

In `src/cvp/main.py`, change:

```python
from cvp.routers import evidence, exports, items, matters, rooms, vision
```

to:

```python
from cvp.routers import evidence, exports, items, matters, rooms, serp, vision
```

And add after `app.include_router(vision.router)`:

```python
app.include_router(serp.router)
```

- [ ] **Step 3: Verify the app starts without errors**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && python -c "from cvp.main import app; print('OK')"
```

Expected: `OK` (no import errors).

- [ ] **Step 4: Commit**

```bash
git add src/cvp/routers/serp.py src/cvp/main.py
git commit -m "feat: add serp router (panel, google lens search, apply) + crop file serving"
```

---

## Task 8: UI Templates

**Files:**
- Create: `src/cvp/templates/_serp_result.html`
- Create: `src/cvp/templates/_serp_panel.html`
- Modify: `src/cvp/templates/_item_row.html`
- Modify: `src/cvp/templates/_items_tbody.html`
- Modify: `src/cvp/routers/items.py`
- Modify: `src/cvp/static/app.js`

- [ ] **Step 1: Create _serp_result.html**

Create `src/cvp/templates/_serp_result.html`:

```html
<div class="space-y-2 text-xs">

  {# ── Formatted results grid ─────────────────────────────────────────── #}
  {% if display_results %}
    <div class="divide-y divide-gray-100">
      {% for result in display_results %}
      <div class="flex items-center gap-3 py-2">

        {# Thumbnail #}
        {% if result.thumbnail %}
          <img src="{{ result.thumbnail }}" alt=""
               class="w-12 h-12 object-contain rounded flex-shrink-0 bg-gray-50 border border-gray-100" />
        {% else %}
          <div class="w-12 h-12 rounded flex-shrink-0 bg-gray-100 border border-gray-200"></div>
        {% endif %}

        <div class="flex-1 min-w-0">
          {% if result.link %}
            <a href="{{ result.link }}" target="_blank" rel="noopener noreferrer"
               class="font-medium text-indigo-600 hover:underline truncate block leading-snug">
              {{ result.title or "Untitled" }}
            </a>
          {% else %}
            <span class="font-medium text-gray-800 truncate block leading-snug">
              {{ result.title or "Untitled" }}
            </span>
          {% endif %}

          {% if result.source %}
            <div class="flex items-center gap-1 mt-0.5 text-gray-400">
              {% if result.source_icon %}
                <img src="{{ result.source_icon }}" alt=""
                     class="w-4 h-4 object-contain flex-shrink-0" />
              {% endif %}
              <span class="truncate">{{ result.source }}</span>
            </div>
          {% endif %}

          {% if result.price_cents %}
            <span class="mt-0.5 text-green-700 font-medium">
              ${{ "%.2f" % (result.price_cents / 100) }}
            </span>
          {% endif %}
        </div>

        {# Use this button #}
        <form hx-post="/api/items/{{ item_id }}/serp-apply"
              hx-target="#item-row-{{ item_id }}"
              hx-swap="outerHTML"
              hx-on::after-request="document.getElementById('serp-panel-{{ item_id }}')?.remove()">
          <input type="hidden" name="source_url" value="{{ result.link or '' }}">
          <input type="hidden" name="source_retailer" value="{{ result.source or '' }}">
          {% if result.price_cents %}
          <input type="hidden" name="rcv_unit_cents" value="{{ result.price_cents }}">
          {% endif %}
          <button type="submit"
                  class="text-xs bg-green-600 hover:bg-green-700 text-white px-2 py-1.5 rounded transition whitespace-nowrap">
            Use this
          </button>
        </form>

      </div>
      {% endfor %}
    </div>

  {% else %}
    <p class="text-gray-400 italic">No results found.</p>
  {% endif %}

  {# ── Raw response toggle ─────────────────────────────────────────────── #}
  <details class="mt-3">
    <summary class="cursor-pointer text-gray-400 hover:text-gray-600 select-none py-1">
      Show raw response
    </summary>
    <div class="mt-2 space-y-3">
      <div>
        <p class="font-semibold text-gray-600 mb-1">Request URL</p>
        <pre class="bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto text-gray-800 whitespace-pre-wrap break-all text-xs">{{ s.request_url }}</pre>
      </div>
      <div>
        <p class="font-semibold text-gray-600 mb-1">Response <span class="text-gray-400">(HTTP {{ s.status_code }})</span></p>
        <pre class="bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto overflow-y-auto text-gray-800 max-h-64 text-xs">{{ s.response_json | pretty_json }}</pre>
      </div>
    </div>
  </details>

  <p class="text-gray-400 mt-1">Searched {{ s.ran_at.strftime('%b %d, %Y %H:%M:%S') }}</p>

</div>
```

- [ ] **Step 2: Create _serp_panel.html**

Create `src/cvp/templates/_serp_panel.html`:

```html
<tr id="serp-panel-{{ item.id }}">
  <td colspan="12" class="px-4 py-4 bg-violet-50 border-b border-violet-100">
    <div class="flex items-center justify-between mb-3">
      <h4 class="text-xs font-semibold text-violet-800">Google Lens — {{ item.description }}</h4>
      <button onclick="document.getElementById('serp-panel-{{ item.id }}').remove()"
              class="text-xs text-gray-400 hover:text-gray-600">✕ Close</button>
    </div>

    {% if not item.crops %}
      <p class="text-xs text-gray-400 italic">No crop available. Re-scan this evidence image to enable Lens search.</p>
    {% else %}

      {# Multiple crops: show selector strip #}
      {% if item.crops | length > 1 %}
      <div class="flex gap-2 mb-3">
        {% for crop in item.crops %}
        <button onclick="showCropPanel('{{ item.id }}', '{{ crop.id }}')"
                id="crop-tab-{{ crop.id }}"
                class="border-2 rounded overflow-hidden focus:outline-none
                       {% if loop.first %}border-violet-500{% else %}border-transparent hover:border-violet-300{% endif %}">
          <img src="/crops/{{ crop.crop_path }}" alt="Crop {{ loop.index }}"
               class="w-16 h-16 object-contain bg-white" />
        </button>
        {% endfor %}
      </div>
      {% endif %}

      {# One panel per crop #}
      {% for crop in item.crops %}
      <div id="crop-panel-{{ crop.id }}"
           class="{% if not loop.first %}hidden{% endif %} flex gap-4">

        {# Crop thumbnail #}
        <div class="flex-shrink-0">
          <img src="/crops/{{ crop.crop_path }}" alt="{{ item.description }}"
               class="w-32 h-32 object-contain rounded border border-gray-200 bg-white shadow-sm" />
          <p class="mt-1 text-xs text-gray-400 text-center">
            {{ crop.bbox_right - crop.bbox_left }}×{{ crop.bbox_lower - crop.bbox_upper }}px
          </p>
        </div>

        {# Search form + results #}
        <div class="flex-1 min-w-0">
          <form hx-post="/api/items/{{ item.id }}/crops/{{ crop.id }}/serp/google_lens"
                hx-target="#lens-result-{{ crop.id }}"
                hx-swap="innerHTML"
                hx-indicator="#lens-spinner-{{ crop.id }}"
                class="flex items-center gap-2 mb-3">
            {% if public_base_url %}
              <input type="hidden" name="image_url"
                     value="{{ public_base_url.rstrip('/') }}/crops/{{ crop.crop_path }}">
              <button type="submit"
                      class="text-xs bg-violet-600 hover:bg-violet-700 text-white px-3 py-1.5 rounded transition">
                Search Google Lens
              </button>
            {% else %}
              <input type="url" name="image_url"
                     placeholder="Paste public URL to crop image (or set PUBLIC_BASE_URL)"
                     class="flex-1 text-xs border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-400" />
              <button type="submit"
                      class="text-xs bg-violet-600 hover:bg-violet-700 text-white px-3 py-1.5 rounded transition">
                Search
              </button>
            {% endif %}
            <svg id="lens-spinner-{{ crop.id }}"
                 class="htmx-indicator animate-spin h-4 w-4 text-violet-500"
                 xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
            </svg>
          </form>

          <div id="lens-result-{{ crop.id }}">
            {% if latest_by_crop.get(crop.id) %}
              {% set s = latest_by_crop[crop.id] %}
              {% set display_results = display_by_crop.get(crop.id, []) %}
              {% set item_id = item.id %}
              {% include "_serp_result.html" %}
            {% else %}
              <p class="text-xs text-gray-400 italic">No search run yet.</p>
            {% endif %}
          </div>
        </div>
      </div>
      {% endfor %}

    {% endif %}
  </td>
</tr>
```

- [ ] **Step 3: Add toggleSerpPanel and showCropPanel to app.js**

Open `src/cvp/static/app.js` and append at the end:

```javascript
// ── Serp panel toggle ────────────────────────────────────────────────────
function toggleSerpPanel(itemId) {
  const existing = document.getElementById('serp-panel-' + itemId);
  if (existing) {
    existing.remove();
    return;
  }
  htmx.ajax('GET', '/api/items/' + itemId + '/serp-panel', {
    target: document.getElementById('item-row-' + itemId),
    swap: 'afterend',
  });
}

function showCropPanel(itemId, cropId) {
  // Hide all crop panels for this item, show the selected one
  const panel = document.getElementById('serp-panel-' + itemId);
  if (!panel) return;
  panel.querySelectorAll('[id^="crop-panel-"]').forEach(el => el.classList.add('hidden'));
  panel.querySelectorAll('[id^="crop-tab-"]').forEach(el => {
    el.classList.remove('border-violet-500');
    el.classList.add('border-transparent');
  });
  const target = document.getElementById('crop-panel-' + cropId);
  if (target) target.classList.remove('hidden');
  const tab = document.getElementById('crop-tab-' + cropId);
  if (tab) {
    tab.classList.remove('border-transparent');
    tab.classList.add('border-violet-500');
  }
}
```

- [ ] **Step 4: Update _item_row.html**

There are two changes to `_item_row.html`:

**Change 1:** Replace the `search_hint` notes-parsing block (lines 13–20) with a cleaner version using `item.search_hint`:

Old:
```html
    {% if not item.source_url %}
    {% set _hint = "" %}
    {% for seg in item.notes.split("|") %}{% if seg.startswith("search_hint:") %}{% set _hint = seg[12:] %}{% endif %}{% endfor %}
    {% set _q = (_hint if _hint else ((item.description or "") + (" " + item.brand if item.brand else ""))) | qplus %}
```

New:
```html
    {% if not item.source_url %}
    {% set _q = (item.search_hint if item.search_hint else ((item.description or "") + (" " + item.brand if item.brand else ""))) | qplus %}
```

**Change 2:** In the last `<td>` (the actions column), add the "Find price" button alongside Edit/Del. Replace:

```html
  <td class="whitespace-nowrap px-3 py-2 text-center">
    <div class="flex items-center gap-1 justify-center">
      <button hx-get="/api/items/{{ item.id }}/edit"
              hx-target="#item-row-{{ item.id }}"
              hx-swap="outerHTML"
              class="rounded px-2 py-0.5 text-xs text-indigo-600 hover:bg-indigo-50">Edit</button>
      <button hx-delete="/api/items/{{ item.id }}"
              hx-target="#item-row-{{ item.id }}"
              hx-swap="outerHTML"
              hx-confirm="Delete this item?"
              class="rounded px-2 py-0.5 text-xs text-red-600 hover:bg-red-50">Del</button>
    </div>
  </td>
```

With:

```html
  <td class="whitespace-nowrap px-3 py-2 text-center">
    <div class="flex items-center gap-1 justify-center">
      {% if item.crops %}
      <button onclick="toggleSerpPanel('{{ item.id }}')"
              class="rounded px-2 py-0.5 text-xs text-violet-600 hover:bg-violet-50"
              title="Find price with Google Lens">🔍</button>
      {% else %}
      <span class="text-gray-300 text-xs px-1" title="Re-scan evidence to enable Lens search">📷</span>
      {% endif %}
      <button hx-get="/api/items/{{ item.id }}/edit"
              hx-target="#item-row-{{ item.id }}"
              hx-swap="outerHTML"
              class="rounded px-2 py-0.5 text-xs text-indigo-600 hover:bg-indigo-50">Edit</button>
      <button hx-delete="/api/items/{{ item.id }}"
              hx-target="#item-row-{{ item.id }}"
              hx-swap="outerHTML"
              hx-confirm="Delete this item?"
              class="rounded px-2 py-0.5 text-xs text-red-600 hover:bg-red-50">Del</button>
    </div>
  </td>
```

- [ ] **Step 5: Apply the same two changes to _items_tbody.html**

`_items_tbody.html` contains the same row HTML as `_item_row.html`. Apply the identical two changes from Step 4 to `_items_tbody.html` (the changes appear inside the `{% for item in items %}` loop).

- [ ] **Step 6: Update items.py to load crops via selectinload**

In `src/cvp/routers/items.py`, add `selectinload` to imports:

```python
from sqlalchemy.orm import selectinload
```

Then update each function that fetches a single item and calls `_item_row_html` to use selectinload. Replace the `db.get(Item, item_id)` calls in `item_view_row`, `update_item`, `toggle_confirm`, and `toggle_exclude` with:

```python
item = (
    db.query(Item)
    .options(selectinload(Item.crops))
    .filter(Item.id == item_id)
    .first()
)
if item is None:
    raise HTTPException(status_code=404)
```

Also update `_items_tbody_html` to load crops:

```python
def _items_tbody_html(matter_id: str, db) -> str:
    items = (
        db.query(Item)
        .filter(Item.matter_id == matter_id)
        .options(selectinload(Item.crops))
        .order_by(Item.line_number)
        .all()
    )
    categories, rooms = _get_context(matter_id, db)
    return templates.get_template("_items_tbody.html").render(
        items=items, categories=categories, rooms=rooms, conditions=CONDITIONS
    )
```

- [ ] **Step 7: Run all tests**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && uv run pytest -v
```

Expected: All tests PASS.

- [ ] **Step 8: Run lint**

```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate && uv run ruff check . && uv run ruff format .
```

Fix any lint errors before committing.

- [ ] **Step 9: Commit**

```bash
git add src/cvp/templates/_serp_result.html src/cvp/templates/_serp_panel.html \
        src/cvp/templates/_item_row.html src/cvp/templates/_items_tbody.html \
        src/cvp/routers/items.py src/cvp/static/app.js
git commit -m "feat: add Lens search panel UI — Find price button, crop view, result cards, Use this"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ `ItemCrop` table (Task 2, 3)
- ✅ `SerpSearch` table linked to `item_crop_id` (Task 2, 3)
- ✅ `Item.search_hint` promoted from notes (Task 2, 3)
- ✅ `SERP_API_KEY`, `PUBLIC_BASE_URL`, `crop_dir` in config (Task 1)
- ✅ Vision prompt v3 merging both prompts (Task 4)
- ✅ `build_scan_prompt(width, height)` (Task 4)
- ✅ Pillow cropping + 15% padding in vision service (Task 5)
- ✅ `ItemCrop` rows created alongside `Item` rows (Task 5)
- ✅ `call_serp("google_lens", item_crop, image_url)` (Task 6)
- ✅ `extract_results` with `price_cents` (Task 6)
- ✅ `/crops/{path}` file serving (Task 7)
- ✅ `GET /api/items/{id}/serp-panel` (Task 7)
- ✅ `POST /api/items/{id}/crops/{crop_id}/serp/google_lens` (Task 7)
- ✅ `POST /api/items/{id}/serp-apply` — pre-fills `source_url`, `source_retailer`, `rcv_unit_cents`, recomputes ACV (Task 7)
- ✅ PUBLIC_BASE_URL auto-populates URL / manual paste fallback (Task 8)
- ✅ "Find price" 🔍 button / 📷 no-crop indicator (Task 8)
- ✅ Panel toggle (open/close), crop selector for multi-crop items (Task 8)
- ✅ "Use this" button removes panel after apply (Task 8)
- ✅ `selectinload(Item.crops)` in all item row renders (Task 8)
