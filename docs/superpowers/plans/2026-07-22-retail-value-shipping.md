# Retail Value + Shipping Cost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RCV a computed value (`RCV = retail value + shipping`) by renaming the stored price to `retail_unit_cents`, adding a per-line `shipping_cents`, and threading shipping (undepreciated) through ACV, exports, and UI — on both `main` (ClaimOS) and `cvp-legacy` (CVP).

**Architecture:** Retail is the stored per-unit base; `shipping_cents` is a per-line total; `rcv_total_cents` and `acv_total_cents` stay stored-but-derived, recomputed on every save. Shipping rides inside RCV but passes through ACV undepreciated. Xactimate CSV headers stay locked (shipping only in `Notes`); the PDF/preview reports and item UI gain an explicit Shipping column.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, Jinja2/HTMX, Tailwind v4, WeasyPrint, pytest + ruff, `uv`.

## Global Constraints

- **Currency is always integer cents.** Never a float. Format to dollars only at display/export. (immutable rule #1)
- **Xactimate CSV column names are frozen.** Do NOT add/rename CSV columns. Shipping appears in the CSV only via the existing `Notes` field. (immutable rule / "Things NOT to do")
- **ACV is computed in `depreciation.py`.** The shipping term lives inside that pure module so the formula stays the single source of truth. (immutable rule #3)
- **`acv_override_cents` is the absolute final ACV.** Shipping is NOT added on top of an override; `rcv_total` still includes shipping.
- **No new dependencies.** Nothing beyond what `pyproject.toml` already has.
- **No inline JS event handlers** in templates (CSP blocks them). New inputs are plain form fields — no `onclick`/`onchange`.
- **`uv run ruff format .` then `uv run ruff format --check .`** must show zero reformatted files before every commit. Line length 100.
- **Two branches:** Phase 1 (Tasks 1–4) is `main` (`claimos` / `Claim` / `claim_id`). Phase 2 (Task 5) mirrors Tasks 1–3 on `cvp-legacy` (`cvp` / `Matter` / `matter_id`), no migrate_db change.

## File Structure (Phase 1 — `main`)

- `src/claimos/depreciation.py` — add `shipping_cents` param; rename first param to `retail_unit_cents` (Task 1).
- `src/claimos/models.py` — rename `Item.rcv_unit_cents` → `retail_unit_cents`; add `shipping_cents` (Task 2).
- `migrations/versions/<new>.py` — Alembic rename + add-column (Task 2).
- `src/claimos/routers/items.py`, `src/claimos/routers/serp.py`, `src/claimos/services/vision.py` — attribute renames (Task 2), then shipping wiring + form params (Task 3).
- `src/claimos/services/csv_export.py` — Shipping in `Notes` (Task 3).
- `src/claimos/templates/*.html`, `templates/report/*.html` — attribute renames (Task 2), then Retail label + Shipping input/column (Task 3).
- `src/claimos/migrate_db.py` — safety-net rename entry (Task 4).
- `tests/*` — updated alongside each task.

---

### Task 1: Depreciation formula — shipping term (undepreciated)

**Files:**
- Modify: `src/claimos/depreciation.py`
- Modify: `src/claimos/routers/items.py:70-78` (call-site keyword only)
- Modify: `src/claimos/routers/serp.py:163-171` (call-site keyword only)
- Test: `tests/test_depreciation.py`

**Interfaces:**
- Produces: `compute_acv(retail_unit_cents: int, quantity: int, age_years: float, useful_life_years: int | None, acv_floor_pct: float, condition: str, acv_override_cents: int | None = None, shipping_cents: int = 0) -> int`. Returns depreciated item ACV **plus** `shipping_cents` (undepreciated); when `acv_override_cents` is set, returns it unchanged (shipping not added).

- [ ] **Step 1: Write failing tests** — append to `tests/test_depreciation.py`:

```python
def test_shipping_added_undepreciated():
    # Same as test_normal_case (acv item portion = 14_000) plus $30 shipping
    result = compute_acv(
        retail_unit_cents=10_000,
        quantity=2,
        age_years=3.0,
        useful_life_years=10,
        acv_floor_pct=0.20,
        condition="average",
        shipping_cents=3_000,
    )
    assert result == 14_000 + 3_000


def test_shipping_is_per_line_not_per_unit():
    # shipping added once for the whole line regardless of quantity
    no_ship = compute_acv(
        retail_unit_cents=10_000, quantity=5, age_years=0.0,
        useful_life_years=10, acv_floor_pct=0.20, condition="average",
    )
    with_ship = compute_acv(
        retail_unit_cents=10_000, quantity=5, age_years=0.0,
        useful_life_years=10, acv_floor_pct=0.20, condition="average",
        shipping_cents=2_000,
    )
    assert with_ship - no_ship == 2_000  # not 2_000 * 5


def test_override_ignores_shipping():
    # Override is absolute final ACV; shipping is NOT added on top
    result = compute_acv(
        retail_unit_cents=10_000, quantity=2, age_years=3.0,
        useful_life_years=10, acv_floor_pct=0.20, condition="average",
        acv_override_cents=9_999, shipping_cents=3_000,
    )
    assert result == 9_999
```

- [ ] **Step 2: Rename existing test keywords** — in `tests/test_depreciation.py`, replace every `rcv_unit_cents=` argument to `compute_acv(` with `retail_unit_cents=` (the existing tests at `test_normal_case`, `test_zero_age`, `test_age_exceeds_useful_life_hits_floor`, and any others). Command to find them:

Run: `grep -n "rcv_unit_cents=" tests/test_depreciation.py`
Change each to `retail_unit_cents=`.

- [ ] **Step 3: Run tests to verify new ones fail**

Run: `uv run pytest tests/test_depreciation.py -q`
Expected: FAIL — `compute_acv() got an unexpected keyword argument 'shipping_cents'` / `'retail_unit_cents'`.

- [ ] **Step 4: Update `depreciation.py`** — replace the function with:

```python
def compute_acv(
    retail_unit_cents: int,
    quantity: int,
    age_years: float,
    useful_life_years: int | None,
    acv_floor_pct: float,
    condition: str,
    acv_override_cents: int | None = None,
    shipping_cents: int = 0,
) -> int:
    """
    Return ACV total cents per the depreciation schedule.

    RCV = retail value + shipping. Shipping is part of RCV but passes through
    ACV undepreciated (you cannot depreciate the cost of shipping a new
    replacement item), so it is added after depreciation.

    If acv_override_cents is set it is the absolute final ACV — shipping is NOT
    added on top of it. If useful_life_years is None the item is
    non-depreciable: item ACV == item RCV (shipping still added).
    """
    if acv_override_cents is not None:
        return acv_override_cents

    if useful_life_years is None:
        return retail_unit_cents * quantity + shipping_cents  # non-depreciable

    multiplier = CONDITION_MULTIPLIERS.get(condition, 1.00)
    dep_rate = 1.0 / useful_life_years
    max_dep = 1.0 - acv_floor_pct  # floor enforced here
    accumulated_dep = min(dep_rate * age_years * multiplier, max_dep)
    acv_unit = round(retail_unit_cents * (1.0 - accumulated_dep))
    return acv_unit * quantity + shipping_cents
```

- [ ] **Step 5: Update the two call sites' keyword** (value still reads the not-yet-renamed model attr):

In `src/claimos/routers/items.py` `_compute_and_set_totals`, change the `compute_acv(...)` call's first keyword `rcv_unit_cents=item.rcv_unit_cents,` → `retail_unit_cents=item.rcv_unit_cents,`.

In `src/claimos/routers/serp.py`, change `rcv_unit_cents=item.rcv_unit_cents,` → `retail_unit_cents=item.rcv_unit_cents,` inside its `compute_acv(...)` call.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_depreciation.py -q`
Expected: PASS (all, including 3 new).

- [ ] **Step 7: Format + commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/claimos/depreciation.py src/claimos/routers/items.py src/claimos/routers/serp.py tests/test_depreciation.py
git commit -m "feat(depreciation): add undepreciated per-line shipping term to compute_acv

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Rename `rcv_unit_cents` → `retail_unit_cents` + add `shipping_cents` column

Atomic column rename: the model attribute change breaks every Python and template reference at once, so they move together. `shipping_cents` is added here but stays `0` (unwired) until Task 3.

**Files:**
- Modify: `src/claimos/models.py:161` (Item price columns)
- Create: `migrations/versions/20260722_<rev>_retail_value_shipping.py`
- Modify: `src/claimos/routers/items.py` (`compute_items_totals`, `_compute_and_set_totals`, add/edit routes — attribute refs)
- Modify: `src/claimos/routers/serp.py`, `src/claimos/services/vision.py`
- Modify templates: `_item_row.html`, `_item_row_edit.html`, `_serp_result.html`, `report/pdf.html`, `report/preview.html`
- Modify tests: `test_csv_export.py`, `test_items_summary.py`, `test_items_pagination.py`, `test_items_template.py`, `test_item_approval.py`, `test_items_group_assignment.py`, `test_evidence_cleanup.py`

**Interfaces:**
- Produces: `Item.retail_unit_cents: int` (was `rcv_unit_cents`) and `Item.shipping_cents: int` (default 0). `rcv_total_cents`/`acv_total_cents` unchanged names.

- [ ] **Step 1: Update the model** — in `src/claimos/models.py`, replace the price line:

```python
    retail_unit_cents: Mapped[int] = mapped_column(Integer, default=0)
    shipping_cents: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    rcv_total_cents: Mapped[int] = mapped_column(Integer, default=0)
    acv_total_cents: Mapped[int] = mapped_column(Integer, default=0)
```

(i.e. rename `rcv_unit_cents` → `retail_unit_cents` and insert `shipping_cents` directly after it.)

- [ ] **Step 2: Create the Alembic migration**

Run: `uv run alembic revision -m "retail value + shipping"`
This creates `migrations/versions/<rev>_retail_value_shipping.py`. Edit its body so `down_revision` is the current head and the ops are:

```python
down_revision = "c9851834200b"  # current head — verify with: uv run alembic heads


def upgrade() -> None:
    op.alter_column("items", "rcv_unit_cents", new_column_name="retail_unit_cents")
    op.add_column(
        "items",
        sa.Column("shipping_cents", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("items", "shipping_cents")
    op.alter_column("items", "retail_unit_cents", new_column_name="rcv_unit_cents")
```

Ensure `import sqlalchemy as sa` and `from alembic import op` are present (autogenerate template includes them).

- [ ] **Step 3: Apply and verify the migration round-trips**

Run: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: no errors; final state at head with `items.retail_unit_cents` and `items.shipping_cents` present. (SQLite batch mode handles the rename automatically for local dev.)

- [ ] **Step 4: Rename all Python attribute references**

Run to find them: `grep -rn "rcv_unit_cents" src/claimos`
Edit each occurrence of `.rcv_unit_cents` / `rcv_unit_cents=` to `retail_unit_cents`:
- `routers/items.py`: `compute_items_totals` query column `Item.rcv_unit_cents` → `Item.retail_unit_cents`; `missing_price_count` uses `r.retail_unit_cents == 0`; `_compute_and_set_totals` line `item.rcv_total_cents = item.rcv_unit_cents * item.quantity` → `item.retail_unit_cents * item.quantity`, and the `compute_acv(retail_unit_cents=item.rcv_unit_cents, ...)` → `item.retail_unit_cents`; add route `Item(... rcv_unit_cents=_parse_cents(rcv_unit_dollars) ...)` → `retail_unit_cents=`; edit route `item.rcv_unit_cents = _parse_cents(...)` → `item.retail_unit_cents = _parse_cents(...)`.
- `routers/serp.py`: `item.rcv_unit_cents = int(...)` → `item.retail_unit_cents`; `item.rcv_total_cents = item.rcv_unit_cents * item.quantity` → `item.retail_unit_cents`; `compute_acv(retail_unit_cents=item.rcv_unit_cents, ...)` → `item.retail_unit_cents`.
- `services/vision.py`: `rcv_unit_cents=0` in the `Item(...)` construction → `retail_unit_cents=0`.

(Form param `rcv_unit_dollars` stays as-is this task; renamed in Task 3.)

- [ ] **Step 5: Rename template attribute references**

Run to find: `grep -rn "item.rcv_unit_cents\|rcv_unit_cents" src/claimos/templates`
Change each `item.rcv_unit_cents` → `item.retail_unit_cents`:
- `_item_row.html:55`, `_item_row_edit.html:83`, `report/pdf.html:350`, `report/preview.html:387,445`.
- `_serp_result.html:54`: the hidden input `name="rcv_unit_cents"` posts to serp; leave the **form field name** `rcv_unit_cents` (the serp route param is still `rcv_unit_cents` in Task 2) — do NOT change this one here. (Serp param rename is out of scope; the serp route keeps `rcv_unit_cents: str = Form("")`.)

- [ ] **Step 6: Rename test references**

Run: `grep -rln "rcv_unit_cents" tests`
In each listed file replace `rcv_unit_cents=` (kwargs building `Item(...)`) and `.rcv_unit_cents` with `retail_unit_cents`. Files: `test_csv_export.py` (lines ~52,71,87), `test_items_summary.py`, `test_items_pagination.py`, `test_items_template.py`, `test_item_approval.py`, `test_items_group_assignment.py`, `test_evidence_cleanup.py`.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (green). If a template test fails with an `Undefined` on `retail_unit_cents`, a template reference was missed in Step 5.

- [ ] **Step 8: Format + commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add -A
git commit -m "refactor: rename rcv_unit_cents -> retail_unit_cents, add shipping_cents column

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Wire shipping through save paths, CSV notes, and UI

Now `shipping_cents` becomes user-editable and flows into totals, the CSV `Notes`, and the report/UI Shipping column.

**Files:**
- Modify: `src/claimos/routers/items.py` (form params + `_compute_and_set_totals`)
- Modify: `src/claimos/routers/serp.py` (rcv_total formula includes shipping)
- Modify: `src/claimos/services/csv_export.py` (Notes annotation)
- Modify: `src/claimos/templates/_item_row_edit.html`, `_tab_items.html` (inputs), `report/pdf.html`, `report/preview.html` (Shipping column)
- Test: `tests/test_csv_export.py`, `tests/test_depreciation.py` already cover math; add a save-path integration assertion in `tests/test_items_summary.py` (or nearest items router test).

**Interfaces:**
- Consumes: `compute_acv(..., shipping_cents=...)` from Task 1; `Item.shipping_cents`, `Item.retail_unit_cents` from Task 2.
- Produces: add/edit item routes accept `retail_unit_dollars` and `shipping_dollars` form fields; `rcv_total_cents = retail_unit_cents * quantity + shipping_cents`.

- [ ] **Step 1: Write failing CSV test** — in `tests/test_csv_export.py`, extend the fixture item that already has a retailer/url so it carries shipping, and assert the Notes annotation. Add:

```python
def test_shipping_annotated_in_notes(tmp_path):
    # Build a confirmed item with shipping and assert Notes carries it while
    # headers stay unchanged. Reuse the module's existing claim/item fixture
    # helper; set retail_unit_cents=120_000, shipping_cents=2_500 on the item.
    # (Follow the existing test_* setup in this file for claim/session wiring.)
    ...
    row = ...  # the DictReader row for that item
    assert "Shipping: $25.00" in row["Notes"]
```

Match the existing fixture style already used in `test_csv_export.py` (it constructs a claim + items and calls `generate_csv`). Set `shipping_cents=2_500` on the priced item.

- [ ] **Step 2: Update `_compute_and_set_totals`** in `src/claimos/routers/items.py`:

```python
def _compute_and_set_totals(item: Item, cat: Category) -> None:
    item.rcv_total_cents = item.retail_unit_cents * item.quantity + item.shipping_cents
    item.acv_total_cents = compute_acv(
        retail_unit_cents=item.retail_unit_cents,
        quantity=item.quantity,
        age_years=item.age_years,
        useful_life_years=cat.useful_life_years,
        acv_floor_pct=cat.acv_floor_pct,
        condition=item.condition,
        acv_override_cents=item.acv_override_cents,
        shipping_cents=item.shipping_cents,
    )
```

- [ ] **Step 3: Add form params + parsing** in `items.py` add and edit routes:

In the **add** route signature add after `retail... `: rename `rcv_unit_dollars: str = Form("0")` → `retail_unit_dollars: str = Form("0")` and add `shipping_dollars: str = Form("0")`. In the `Item(...)` construction set `retail_unit_cents=_parse_cents(retail_unit_dollars)` and `shipping_cents=_parse_cents(shipping_dollars)`.

In the **edit** route signature rename `rcv_unit_dollars` → `retail_unit_dollars` and add `shipping_dollars: str = Form("0")`. In the body set `item.retail_unit_cents = _parse_cents(retail_unit_dollars)` and `item.shipping_cents = _parse_cents(shipping_dollars)` (before the `_compute_and_set_totals` call that recomputes totals). Confirm `_compute_and_set_totals(item, cat)` runs after these assignments so totals reflect the new shipping.

- [ ] **Step 4: Update serp rcv_total formula** in `src/claimos/routers/serp.py`:

Change `item.rcv_total_cents = item.retail_unit_cents * item.quantity` →
`item.rcv_total_cents = item.retail_unit_cents * item.quantity + item.shipping_cents`
and add `shipping_cents=item.shipping_cents,` to that file's `compute_acv(...)` call. (Serp does not collect shipping; it preserves the item's existing `shipping_cents`.)

- [ ] **Step 5: Annotate shipping in CSV `Notes`** in `src/claimos/services/csv_export.py` — replace the `source_notes` construction (lines ~75-84) with:

```python
                note_parts = [
                    item.source_retailer or "",
                    item.source_url or "",
                    item.match_type or "",
                ]
                if item.shipping_cents:
                    note_parts.append(f"Shipping: ${_dollars(item.shipping_cents)}")
                source_notes = " | ".join(filter(None, note_parts))
```

Headers (`CSV_HEADERS`) are unchanged.

- [ ] **Step 6: Run CSV test**

Run: `uv run pytest tests/test_csv_export.py -q`
Expected: PASS, including `test_shipping_annotated_in_notes` and the existing header/Notes assertions.

- [ ] **Step 7: Add Shipping input to the edit form** — in `src/claimos/templates/_item_row_edit.html`, rename the price input and add a shipping input. Replace the RCV/unit block (around lines 80-85):

```html
        <div class="col-span-2">
          <label class="text-xs font-medium text-neutral-600">Retail / unit ($)</label>
          <input name="retail_unit_dollars" type="number" min="0" step="0.01"
                 value="{{ "%.2f" % (item.retail_unit_cents / 100) }}"
                 class="mt-0.5 block w-full rounded-sm border border-neutral-300 px-2 py-1 text-sm focus:border-primary-light focus:outline-hidden font-mono">
        </div>
        <div class="col-span-2">
          <label class="text-xs font-medium text-neutral-600">Shipping / line ($)</label>
          <input name="shipping_dollars" type="number" min="0" step="0.01"
                 value="{{ "%.2f" % (item.shipping_cents / 100) }}"
                 class="mt-0.5 block w-full rounded-sm border border-neutral-300 px-2 py-1 text-sm focus:border-primary-light focus:outline-hidden font-mono">
        </div>
```

- [ ] **Step 8: Add Shipping input to the add-item form** — in `src/claimos/templates/_tab_items.html`, rename the RCV/unit input (`name="rcv_unit_dollars"` → `name="retail_unit_dollars"`, label `RCV/unit ($)` → `Retail/unit ($)`) and add next to it:

```html
            <label class="text-xs font-medium text-neutral-600">Shipping/line ($)</label>
            <input name="shipping_dollars" type="number" min="0" step="0.01" value="0"
                   class="mt-0.5 block w-full rounded-sm border border-neutral-300 px-2 py-1 text-sm focus:border-primary-light focus:outline-hidden font-mono">
```

(Place the label+input following the existing retail input, matching the surrounding grid/markup.)

- [ ] **Step 9: Add Shipping column to the PDF report** — in `src/claimos/templates/report/pdf.html`, in the line-items table add a header after `RCV/unit` (line ~330) and a cell after the retail cell (line ~350):

Header: `<th class="right">Shipping</th>` (insert after the `RCV/unit` `<th>`, before `RCV total`).
Cell: `<td class="right mono">${{ "{:,.2f}".format(item.shipping_cents / 100) }}</td>` (insert after the retail-unit `<td>`, before the RCV-total `<td>`).

- [ ] **Step 10: Add Shipping column to the preview report** — in `src/claimos/templates/report/preview.html`, do the same in its line-items table: add `<th class="text-right px-2 py-2 border border-neutral-200">Shipping</th>` after the `RCV/unit` header (line ~367) and `<td class="px-2 py-1.5 border border-neutral-200 text-right font-mono">${{ "{:,.2f}".format(item.shipping_cents / 100) }}</td>` after the retail-unit cell (line ~387).

- [ ] **Step 11: Add the save-path integration assertion** — in `tests/test_items_summary.py` (or the nearest items-router integration test with a client fixture), add a test that POSTs the add-item route with `retail_unit_dollars="100.00"`, `quantity=3`, `shipping_dollars="20.00"` and asserts the persisted item has `retail_unit_cents == 10000`, `shipping_cents == 2000`, and `rcv_total_cents == 32000`. Follow the existing add-item POST test in that file for route path and auth/session wiring.

- [ ] **Step 12: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 13: Format + commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add -A
git commit -m "feat: capture per-line shipping and thread it through totals, CSV notes, report/UI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `migrate_db.py` cutover safety-net (main only)

Make the legacy→ClaimOS copy robust whether or not the `cvp-legacy` DB has been migrated to `retail_unit_cents`.

**Files:**
- Modify: `src/claimos/migrate_db.py:48` (items TABLE_PLAN entry)
- Test: `tests/test_migrate_db.py`

**Interfaces:**
- Consumes: the `_copy_table` rename map (`{source_col: target_col}`) applied via `renames.get(k, k)`.

- [ ] **Step 1: Write a failing test** — in `tests/test_migrate_db.py`, add a test asserting the items plan maps the legacy price column:

```python
def test_items_plan_renames_rcv_to_retail():
    from claimos.migrate_db import TABLE_PLAN

    items_entry = next(e for e in TABLE_PLAN if e[0] == "items")
    renames = items_entry[2]
    assert renames.get("rcv_unit_cents") == "retail_unit_cents"
    assert renames.get("matter_id") == "claim_id"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_migrate_db.py::test_items_plan_renames_rcv_to_retail -q`
Expected: FAIL — `assert None == 'retail_unit_cents'`.

- [ ] **Step 3: Update the items TABLE_PLAN entry** in `src/claimos/migrate_db.py`:

```python
    ("items", "items", {"matter_id": "claim_id", "rcv_unit_cents": "retail_unit_cents"}),
```

- [ ] **Step 4: Run the migrate_db tests**

Run: `uv run pytest tests/test_migrate_db.py -q`
Expected: PASS, including the existing TABLE_PLAN ↔ ORM metadata invariant (adding a column rename does not change table coverage).

- [ ] **Step 5: Format + commit**

```bash
uv run ruff format . && uv run ruff format --check .
git add src/claimos/migrate_db.py tests/test_migrate_db.py
git commit -m "feat(migrate-db): remap legacy rcv_unit_cents -> retail_unit_cents on cutover

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 6: Phase 1 gate** — run everything before opening the PR:

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: all green. Open the `main` PR (base `main`).

---

### Task 5: Mirror on `cvp-legacy` (Phase 2 — separate branch + PR)

The legacy codebase is structurally identical to `main` — only naming differs. Replicate Tasks 1–3 with the translation below. **Do NOT replicate Task 4** (migrate_db is the target-side tool on `main`; legacy is the source).

**Branch setup:**
```bash
git fetch origin
git checkout -b feat/retail-value-shipping-legacy origin/cvp-legacy
```

**Name translation (apply everywhere):**

| `main` (ClaimOS)              | `cvp-legacy` (CVP)          |
|-------------------------------|-----------------------------|
| package `claimos`             | package `cvp`               |
| `src/claimos/…`               | `src/cvp/…`                 |
| `Claim` model / `claim_id`    | `Matter` model / `matter_id`|
| `from claimos.…`              | `from cvp.…`                |
| migrations dir (confirm path) | confirm with `uv run alembic heads` on the legacy branch |

Everything else — `Item`, `retail_unit_cents`, `shipping_cents`, `rcv_total_cents`, `acv_total_cents`, `compute_acv` signature, `depreciation.py` body, CSV headers, `Notes` annotation, template markup — is **identical**.

- [ ] **Step 1: Depreciation (mirror Task 1)** — apply the exact `compute_acv` body and the three new tests from Task 1 to `src/cvp/depreciation.py` and `tests/test_depreciation.py`; update the two call-site keywords in `src/cvp/routers/items.py` and `src/cvp/routers/serp.py`. Run `uv run pytest tests/test_depreciation.py -q` → PASS. Format + commit.

- [ ] **Step 2: Rename + column (mirror Task 2)** — apply the model change to `src/cvp/models.py`; create a new Alembic revision on the legacy head (`op.alter_column("items","rcv_unit_cents",new_column_name="retail_unit_cents")` + add `shipping_cents server_default="0"`); round-trip `uv run alembic upgrade head && downgrade -1 && upgrade head`; rename every `rcv_unit_cents` → `retail_unit_cents` reference across `src/cvp/**` and `tests/**` (use `grep -rn "rcv_unit_cents" src/cvp tests`), except the serp form-field `name="rcv_unit_cents"` and serp route param. Run `uv run pytest -q` → PASS. Format + commit.

- [ ] **Step 3: Shipping wiring (mirror Task 3)** — apply the `_compute_and_set_totals` formula, add/edit route `retail_unit_dollars` + `shipping_dollars` params, serp `rcv_total` formula, CSV `Notes` annotation, edit-form + add-form Shipping inputs, and PDF + preview Shipping column — all identical markup/logic. Add the CSV Notes test and the save-path integration assertion. Run `uv run pytest -q` → PASS. Format + commit.

- [ ] **Step 4: Phase 2 gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: all green. Open the `cvp-legacy` PR (base `cvp-legacy`).

---

## Self-Review

- **Spec coverage:** model rename + shipping_cents (Task 2) ✓; RCV=retail+shipping & undepreciated ACV & override behavior (Task 1) ✓; per-line shipping (Task 1 test) ✓; rename-in-place migration preserving data (Task 2 Step 2-3) ✓; stored-derived totals recomputed on save (Task 3 Step 2/4) ✓; CSV headers locked + Notes annotation (Task 3 Step 5) ✓; PDF/UI Shipping column (Task 3 Steps 7-10) ✓; migrate_db safety-net (Task 4) ✓; two-branch execution (Task 5) ✓.
- **Placeholder scan:** Task 3 Step 1 and Step 11 reference "the existing fixture/test in this file" rather than reproducing large client-fixture scaffolding — this is a deliberate pointer to concrete existing patterns in named files, not an unspecified requirement; the assertions and inputs are given explicitly.
- **Type consistency:** `compute_acv` signature identical across Task 1 (def), Task 1 Step 5 / Task 3 Step 2/4 (calls). `retail_unit_cents`, `shipping_cents`, `rcv_total_cents` spelled consistently everywhere.
