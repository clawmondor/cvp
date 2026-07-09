# Slice 2 — Semantic Color Tokens — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all color utilities (templates + JS) onto a semantic/ramp token layer defined in `theme.css` `@theme`, so the color system has one structural control point. Strict visual parity except the one approved JS drift-fold.

**Architecture:** Add the token set to `@theme` additively first (both raw shades and tokens work, app keeps rendering), migrate templates then JS by scripted whole-token substitution, then clear the default Tailwind palette (`--color-*: initial`) so only tokens remain, and rewrite the drift guard to forbid raw Tailwind color families. Type/radius get their *values* tokenized (`--font-sans`, `--radius-*`) without utility renames.

**Tech Stack:** Tailwind CSS v4 `@theme` (CSS-first tokens), standalone CLI build (Slice 1), Jinja templates + vanilla JS, `uv`/pytest.

## Global Constraints

- **Parity:** every token's value equals the current Tailwind hex it replaces (see the token table). The ONLY intended visual change is the JS drift-fold (emerald→success, violet/blue→primary) in `app.js`/`crop-editor.js`.
- **Whole-token substitution** with boundary lookarounds `(?<![\w-])…(?![\w-])` (as Slice 1) — never partial matches; preserve variant prefixes (`hover:`, `focus:`) and property prefixes.
- **Type/radius:** tokenize values in `@theme` only; do NOT rename `text-*`/`rounded-*` utilities.
- **`bg-white`→`bg-surface`; `text-white`/`ring-white`/`border-white` stay literal white.**
- Python via venv (`source .venv/bin/activate &&`). Run `uv run ruff format .` → `ruff format --check .` → `ruff check .` before committing any `.py`.
- `app.css`/`bin/` stay gitignored. Print report `report/pdf.html` untouched. No inline JS handlers.
- Branch `feat/design-tokens-slice2`; never `main`.

## Token table (name → hex → former shade)

```
primary-subtle #eef2ff (indigo-50)   primary-tint #e0e7ff (indigo-100)  primary-tint-strong #c7d2fe (indigo-200)
primary-light #6366f1 (indigo-500)   primary #4f46e5 (indigo-600)       primary-strong #4338ca (indigo-700)
neutral-50 #f9fafb  neutral-100 #f3f4f6  neutral-200 #e5e7eb  neutral-300 #d1d5db  neutral-400 #9ca3af
neutral-500 #6b7280  neutral-600 #4b5563  neutral-700 #374151  neutral-900 #111827
success-surface #f0fdf4 (green-50)  success-surface-strong #dcfce7 (green-100)  success-border #bbf7d0 (green-200)
success-emphasis #16a34a (green-600)  success #15803d (green-700)  success-strong #166534 (green-800)
error-surface #fef2f2 (red-50)  error-surface-strong #fee2e2 (red-100)  error-border #fecaca (red-200)
error #dc2626 (red-600)  error-strong #b91c1c (red-700)  error-strongest #991b1b (red-800)
warning-surface #fffbeb (amber-50)  warning-surface-strong #fef3c7 (amber-100)  warning-border #fde68a (amber-200)
warning-emphasis #d97706 (amber-600)  warning #b45309 (amber-700)  warning-strong #92400e (amber-800)
admin-300 #cbd5e1 (slate-300)  admin-400 #94a3b8 (slate-400)  admin-600 #475569 (slate-600)
admin-700 #334155 (slate-700)  admin-800 #1e293b (slate-800)
surface #ffffff   white #ffffff   black #000000
```

## Substitution map (family-shade → token), property-agnostic

```
indigo-50→primary-subtle   indigo-100→primary-tint   indigo-200→primary-tint-strong
indigo-500→primary-light   indigo-600→primary        indigo-700→primary-strong
gray-50→neutral-50  gray-100→neutral-100  gray-200→neutral-200  gray-300→neutral-300
gray-400→neutral-400  gray-500→neutral-500  gray-600→neutral-600  gray-700→neutral-700  gray-900→neutral-900
green-50→success-surface  green-100→success-surface-strong  green-200→success-border
green-600→success-emphasis  green-700→success  green-800→success-strong
red-50→error-surface  red-100→error-surface-strong  red-200→error-border
red-600→error  red-700→error-strong  red-800→error-strongest
amber-50→warning-surface  amber-100→warning-surface-strong  amber-200→warning-border
amber-600→warning-emphasis  amber-700→warning  amber-800→warning-strong
slate-300→admin-300  slate-400→admin-400  slate-600→admin-600  slate-700→admin-700  slate-800→admin-800
```
Property-specific: `bg-white`→`bg-surface` (only `bg-white`).
JS-only additional fold rules (applied to `static/*.js` on top of the map above):
```
emerald-600→success-emphasis  violet-500→primary-light  violet-600→primary  violet-700→primary-strong
blue-600→primary  indigo-400→primary-light  red-500→error
```

---

### Task 1: Define @theme tokens (additive) + type/radius values + parity test

**Files:**
- Modify: `src/claimos/styles/theme.css`
- Test: `tests/test_theme_tokens.py`

**Interfaces:**
- Produces: `--color-<token>` variables in `@theme` for every token in the table; `--font-sans`; `--radius-sm|md|lg`. (Default palette still present — cleared in Task 4.)

- [ ] **Step 1: Write the failing parity test**

Create `tests/test_theme_tokens.py`:
```python
import re
from pathlib import Path

THEME = Path("src/claimos/styles/theme.css")

EXPECTED = {
    "primary-subtle": "#eef2ff", "primary-tint": "#e0e7ff", "primary-tint-strong": "#c7d2fe",
    "primary-light": "#6366f1", "primary": "#4f46e5", "primary-strong": "#4338ca",
    "neutral-50": "#f9fafb", "neutral-100": "#f3f4f6", "neutral-200": "#e5e7eb",
    "neutral-300": "#d1d5db", "neutral-400": "#9ca3af", "neutral-500": "#6b7280",
    "neutral-600": "#4b5563", "neutral-700": "#374151", "neutral-900": "#111827",
    "success-surface": "#f0fdf4", "success-surface-strong": "#dcfce7", "success-border": "#bbf7d0",
    "success-emphasis": "#16a34a", "success": "#15803d", "success-strong": "#166534",
    "error-surface": "#fef2f2", "error-surface-strong": "#fee2e2", "error-border": "#fecaca",
    "error": "#dc2626", "error-strong": "#b91c1c", "error-strongest": "#991b1b",
    "warning-surface": "#fffbeb", "warning-surface-strong": "#fef3c7", "warning-border": "#fde68a",
    "warning-emphasis": "#d97706", "warning": "#b45309", "warning-strong": "#92400e",
    "admin-300": "#cbd5e1", "admin-400": "#94a3b8", "admin-600": "#475569",
    "admin-700": "#334155", "admin-800": "#1e293b",
    "surface": "#ffffff", "white": "#ffffff", "black": "#000000",
}


def _tokens():
    text = THEME.read_text()
    return {m.group(1): m.group(2).lower()
            for m in re.finditer(r'--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;', text)}


def test_every_expected_token_present_with_correct_hex():
    toks = _tokens()
    for name, hex_ in EXPECTED.items():
        assert toks.get(name) == hex_, f"{name}: expected {hex_}, got {toks.get(name)}"


def test_font_and_radius_scales_defined():
    text = THEME.read_text()
    assert "--font-sans:" in text
    for r in ("--radius-sm:", "--radius-md:", "--radius-lg:"):
        assert r in text
```

- [ ] **Step 2: Run it — expect failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_theme_tokens.py -q`
Expected: FAIL (tokens not defined yet).

- [ ] **Step 3: Add the `@theme` block to `theme.css`**

Insert after the `@source` lines and before the `@layer base` block:
```css
@theme {
  /* Accent (primary) */
  --color-primary-subtle: #eef2ff;
  --color-primary-tint: #e0e7ff;
  --color-primary-tint-strong: #c7d2fe;
  --color-primary-light: #6366f1;
  --color-primary: #4f46e5;
  --color-primary-strong: #4338ca;
  /* Neutral ramp */
  --color-neutral-50: #f9fafb;
  --color-neutral-100: #f3f4f6;
  --color-neutral-200: #e5e7eb;
  --color-neutral-300: #d1d5db;
  --color-neutral-400: #9ca3af;
  --color-neutral-500: #6b7280;
  --color-neutral-600: #4b5563;
  --color-neutral-700: #374151;
  --color-neutral-900: #111827;
  /* Status */
  --color-success-surface: #f0fdf4;
  --color-success-surface-strong: #dcfce7;
  --color-success-border: #bbf7d0;
  --color-success-emphasis: #16a34a;
  --color-success: #15803d;
  --color-success-strong: #166534;
  --color-error-surface: #fef2f2;
  --color-error-surface-strong: #fee2e2;
  --color-error-border: #fecaca;
  --color-error: #dc2626;
  --color-error-strong: #b91c1c;
  --color-error-strongest: #991b1b;
  --color-warning-surface: #fffbeb;
  --color-warning-surface-strong: #fef3c7;
  --color-warning-border: #fde68a;
  --color-warning-emphasis: #d97706;
  --color-warning: #b45309;
  --color-warning-strong: #92400e;
  /* Admin chrome */
  --color-admin-300: #cbd5e1;
  --color-admin-400: #94a3b8;
  --color-admin-600: #475569;
  --color-admin-700: #334155;
  --color-admin-800: #1e293b;
  /* Surface + literals */
  --color-surface: #ffffff;
  --color-white: #ffffff;
  --color-black: #000000;
  /* Type + radius (rebrand control points; values match current) */
  --font-sans: ui-sans-serif, system-ui, sans-serif;
  --radius-sm: 0.25rem;
  --radius-md: 0.375rem;
  --radius-lg: 0.5rem;
}
```

- [ ] **Step 4: Update the border-compat rule to the neutral token**

In `theme.css`, change the `@layer base` border rule from `var(--color-gray-200, currentColor)` to:
```css
    border-color: var(--color-neutral-200, currentColor);
```

- [ ] **Step 5: Run the test — expect pass; confirm app still builds (palette still additive)**

Run:
```bash
source .venv/bin/activate
uv run pytest tests/test_theme_tokens.py -q
uv run css && test -s src/claimos/static/app.css && echo "builds"
```
Expected: tests pass; `builds`. (Raw shades still work — palette not cleared yet — so the app renders unchanged.)

- [ ] **Step 6: Format + commit**

```bash
source .venv/bin/activate && uv run ruff format tests/test_theme_tokens.py && uv run ruff format --check tests/test_theme_tokens.py
git add src/claimos/styles/theme.css tests/test_theme_tokens.py
git commit -m "feat(css): add semantic color tokens + type/radius scale to @theme (additive)"
```

---

### Task 2: Migrate template color utilities to tokens

**Files:**
- Modify: `src/claimos/templates/**/*.html`

**Interfaces:**
- Consumes: the tokens from Task 1.
- Produces: templates using only token color names (no raw families).

- [ ] **Step 1: Write the migration script to scratchpad**

Save to `/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad/tok_templates.py`:
```python
import glob, re

MAP = {
 "indigo-50":"primary-subtle","indigo-100":"primary-tint","indigo-200":"primary-tint-strong",
 "indigo-500":"primary-light","indigo-600":"primary","indigo-700":"primary-strong",
 "gray-50":"neutral-50","gray-100":"neutral-100","gray-200":"neutral-200","gray-300":"neutral-300",
 "gray-400":"neutral-400","gray-500":"neutral-500","gray-600":"neutral-600","gray-700":"neutral-700",
 "gray-900":"neutral-900",
 "green-50":"success-surface","green-100":"success-surface-strong","green-200":"success-border",
 "green-600":"success-emphasis","green-700":"success","green-800":"success-strong",
 "red-50":"error-surface","red-100":"error-surface-strong","red-200":"error-border",
 "red-600":"error","red-700":"error-strong","red-800":"error-strongest",
 "amber-50":"warning-surface","amber-100":"warning-surface-strong","amber-200":"warning-border",
 "amber-600":"warning-emphasis","amber-700":"warning","amber-800":"warning-strong",
 "slate-300":"admin-300","slate-400":"admin-400","slate-600":"admin-600","slate-700":"admin-700",
 "slate-800":"admin-800",
}
# Apply longest keys first is unnecessary (boundary lookarounds), but sort for determinism.
total = 0
for fp in glob.glob("src/claimos/templates/**/*.html", recursive=True):
    s = open(fp).read(); orig = s
    # property-specific first: bg-white -> bg-surface
    s = re.sub(r'(?<![\w-])bg-white(?![\w-])', 'bg-surface', s)
    for shade, tok in MAP.items():
        s = re.sub(rf'(?<![\w-]){re.escape(shade)}(?![\w-])', tok, s)
    if s != orig:
        open(fp, "w").write(s); total += 1; print("migrated", fp)
print("files changed:", total)
```

- [ ] **Step 2: Run it**

Run: `source .venv/bin/activate && python "/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad/tok_templates.py"`
Expected: lists migrated files, `files changed: N`.

- [ ] **Step 3: Verify no raw Tailwind color families remain in templates**

Run:
```bash
cd /Users/cmondor/consulting/tor
grep -roE '(bg|text|border|ring|divide|from|to|via|outline|placeholder)-(gray|indigo|slate|green|red|amber|emerald|violet|blue|purple|yellow)-[0-9]+' src/claimos/templates | sort -u
```
Expected: no output. (`text-white`/`ring-white` remain but are not shade utilities, so they don't match.)

- [ ] **Step 4: Build and confirm token utilities emit; app renders in tests**

Run:
```bash
source .venv/bin/activate
uv run css && grep -q '\.bg-primary' src/claimos/static/app.css && grep -q '\.text-neutral-500' src/claimos/static/app.css && echo "tokens emit"
uv run pytest -q 2>&1 | tail -1
```
Expected: `tokens emit`; full suite passes (templates render).

- [ ] **Step 5: Commit**

```bash
git add src/claimos/templates
git commit -m "refactor(ui): migrate template color utilities to semantic tokens"
```

---

### Task 3: Migrate JS color utilities to tokens (with drift fold)

**Files:**
- Modify: `src/claimos/static/app.js`, `src/claimos/static/crop-editor.js`

**Interfaces:**
- Consumes: tokens from Task 1.
- Produces: JS using only token color names; drift colors folded (emerald→success, violet/blue→primary).

- [ ] **Step 1: Write the JS migration script to scratchpad**

Save to `/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad/tok_js.py`:
```python
import glob, re

MAP = {
 # base map (same as templates)
 "indigo-50":"primary-subtle","indigo-100":"primary-tint","indigo-200":"primary-tint-strong",
 "indigo-500":"primary-light","indigo-600":"primary","indigo-700":"primary-strong",
 "gray-50":"neutral-50","gray-100":"neutral-100","gray-200":"neutral-200","gray-300":"neutral-300",
 "gray-400":"neutral-400","gray-500":"neutral-500","gray-600":"neutral-600","gray-700":"neutral-700",
 "gray-900":"neutral-900",
 "green-50":"success-surface","green-100":"success-surface-strong","green-200":"success-border",
 "green-600":"success-emphasis","green-700":"success","green-800":"success-strong",
 "red-50":"error-surface","red-100":"error-surface-strong","red-200":"error-border",
 "red-600":"error","red-700":"error-strong","red-800":"error-strongest",
 "amber-50":"warning-surface","amber-100":"warning-surface-strong","amber-200":"warning-border",
 "amber-600":"warning-emphasis","amber-700":"warning","amber-800":"warning-strong",
 "slate-300":"admin-300","slate-400":"admin-400","slate-600":"admin-600","slate-700":"admin-700",
 "slate-800":"admin-800",
 # JS drift fold (approved: emerald->success, violet/blue->primary) + off-ramp snaps
 "emerald-600":"success-emphasis",
 "violet-500":"primary-light","violet-600":"primary","violet-700":"primary-strong",
 "blue-600":"primary","indigo-400":"primary-light","red-500":"error",
}
total = 0
for fp in glob.glob("src/claimos/static/*.js"):
    s = open(fp).read(); orig = s
    s = re.sub(r'(?<![\w-])bg-white(?![\w-])', 'bg-surface', s)
    for shade, tok in MAP.items():
        s = re.sub(rf'(?<![\w-]){re.escape(shade)}(?![\w-])', tok, s)
    if s != orig:
        open(fp, "w").write(s); total += 1; print("migrated", fp)
print("files changed:", total)
```

- [ ] **Step 2: Run it**

Run: `source .venv/bin/activate && python "/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad/tok_js.py"`
Expected: `migrated src/claimos/static/app.js`, `migrated src/claimos/static/crop-editor.js`, `files changed: 2`.

- [ ] **Step 3: Verify no raw families remain in JS**

Run:
```bash
cd /Users/cmondor/consulting/tor
grep -roE '(bg|text|border|ring)-(gray|indigo|slate|green|red|amber|emerald|violet|blue|purple|yellow)-[0-9]+' src/claimos/static/*.js | sort -u
```
Expected: no output.

- [ ] **Step 4: Build and confirm the folded JS classes now emit as tokens**

Run:
```bash
source .venv/bin/activate
uv run css
for c in 'bg-success-emphasis' 'bg-primary' 'border-primary-light' 'text-error' 'text-primary'; do
  grep -q "\.$c" src/claimos/static/app.css && echo "present: $c" || echo "MISSING: $c"
done
```
Expected: all present.

- [ ] **Step 5: Commit**

```bash
git add src/claimos/static/app.js src/claimos/static/crop-editor.js
git commit -m "refactor(ui): migrate JS color utilities to tokens + fold drift colors (emerald->success, violet/blue->primary)"
```

---

### Task 4: Close the palette + rewrite the drift guard

**Files:**
- Modify: `src/claimos/styles/theme.css` (clear default palette)
- Modify: `scripts/audit_design_tokens.py` (raw-family blocklist over templates + JS)
- Test: `tests/test_design_token_guard.py`

**Interfaces:**
- Consumes: migrated templates/JS (Tasks 2–3).
- Produces: `audit_design_tokens.main() -> int` (0 clean / 1 on any raw Tailwind color family in templates or `static/*.js`).

- [ ] **Step 1: Clear the default palette in `theme.css`**

Make the first line inside `@theme` clear all default colors, so only our tokens remain:
```css
@theme {
  --color-*: initial;
  /* Accent (primary) */
  --color-primary-subtle: #eef2ff;
  ...
```
(Keep every token definition from Task 1 after the `initial` line.)

- [ ] **Step 2: Write the failing guard test**

Create `tests/test_design_token_guard.py`:
```python
import subprocess
import sys


def test_guard_passes_on_migrated_tree():
    r = subprocess.run([sys.executable, "scripts/audit_design_tokens.py"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_guard_flags_a_raw_family(tmp_path, monkeypatch):
    # a raw-family utility anywhere in templates must fail the guard
    from scripts import audit_design_tokens as guard

    assert guard.find_raw_family_hits('<div class="bg-indigo-600">')  # raw family -> hit
    assert not guard.find_raw_family_hits('<div class="bg-primary text-neutral-500">')  # tokens -> clean
```

- [ ] **Step 3: Run it — expect failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_design_token_guard.py -q`
Expected: FAIL (guard not yet rewritten; `find_raw_family_hits` undefined).

- [ ] **Step 4: Rewrite `scripts/audit_design_tokens.py` to the raw-family blocklist**

Replace the file contents with:
```python
#!/usr/bin/env python3
"""Fail if templates or static JS use a raw Tailwind color family instead of a design token.

Slice 2 closed the Tailwind palette to a fixed token set (primary*/neutral-*/success*/
error*/warning*/admin-*/surface/white/black). Any raw family utility (bg-indigo-600,
text-gray-500, bg-emerald-600, …) is drift. `neutral` is intentionally NOT forbidden —
it is our repurposed ramp name, the only neutral in the closed palette.
"""

from __future__ import annotations

import glob
import re
import sys

SCAN_GLOBS = ["src/claimos/templates/**/*.html", "src/claimos/static/*.js"]

# raw Tailwind color families we migrated away from (excludes `neutral`, now our token)
_FAMILIES = (
    "gray|slate|zinc|stone|red|orange|amber|yellow|lime|green|emerald|teal|"
    "cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
)
_PROPS = (
    "bg|text|border|ring|divide|from|to|via|outline|placeholder|fill|stroke|decoration|accent|shadow"
)
RAW_RE = re.compile(rf"(?:[a-z-]+:)*(?:{_PROPS})-(?:{_FAMILIES})-\d{{2,3}}(?![\w-])")


def find_raw_family_hits(text: str) -> list[str]:
    return RAW_RE.findall(text)


def main() -> int:
    hits: dict[str, int] = {}
    for pattern in SCAN_GLOBS:
        for fp in glob.glob(pattern, recursive=True):
            found = find_raw_family_hits(open(fp).read())
            if found:
                hits[fp] = len(found)
    if not hits:
        print("design token guard: clean ✓ (no raw Tailwind color families)")
        return 0
    print("design token DRIFT — raw Tailwind color families found:")
    for fp, n in sorted(hits.items()):
        print(f"  {n:4d}  {fp}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```
Note: `find_raw_family_hits` returns the matched utility strings; a non-empty list means drift. The test imports it via `from scripts import audit_design_tokens` — ensure `scripts/__init__.py` exists (create an empty one if absent).

- [ ] **Step 5: Ensure `scripts` is importable**

Run: `test -f scripts/__init__.py || touch scripts/__init__.py`

- [ ] **Step 6: Run guard + test + rebuild**

Run:
```bash
source .venv/bin/activate
python scripts/audit_design_tokens.py; echo "exit=$?"
uv run pytest tests/test_design_token_guard.py -q
rm -f src/claimos/static/app.css && uv run css && echo built
```
Expected: guard prints `clean ✓`, `exit=0`; tests pass; `built`.

- [ ] **Step 7: Format, lint, commit**

```bash
source .venv/bin/activate && uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/styles/theme.css scripts/audit_design_tokens.py scripts/__init__.py tests/test_design_token_guard.py
git commit -m "feat(css): close Tailwind palette to tokens + rewrite drift guard (raw-family blocklist)"
```

---

### Task 5: Full parity verification

**Files:** none (verification only)

- [ ] **Step 1: Clean build; app.css has token utilities and zero raw families**

Run:
```bash
cd /Users/cmondor/consulting/tor && source .venv/bin/activate
rm -f src/claimos/static/app.css && uv run css --minify && test -s src/claimos/static/app.css && echo built
grep -oE '(bg|text|border|ring)-(gray|indigo|slate|green|red|amber|emerald|violet|blue)-[0-9]+' src/claimos/static/app.css | sort -u
```
Expected: `built`; the grep prints nothing (no raw-family rules emitted).

- [ ] **Step 2: Guard + token parity test + full suite**

Run: `source .venv/bin/activate && python scripts/audit_design_tokens.py && uv run pytest -q 2>&1 | tail -1`
Expected: guard clean; all tests pass (incl. `test_theme_tokens.py`, `test_design_token_guard.py`, `test_static_css.py`).

- [ ] **Step 3: Lint/format**

Run: `source .venv/bin/activate && uv run ruff format --check . && uv run ruff check .`
Expected: clean.

- [ ] **Step 4: Manual smoke (recommended)**

`uv run css` then `uv run dev`; open the dashboard, a form, and an admin page. Confirm identical appearance EXCEPT the intended JS fold (crop-editor draw-mode toggle now green not emerald; tab indicator / rename input now indigo not violet).

---

### Task 6: Docs — reconcile DESIGN.md + note the token source of truth

**Files:**
- Modify: `DESIGN.md` (colors front-matter token names + a note that `theme.css` `@theme` is now the build source of truth)

**Interfaces:** none (documentation).

- [ ] **Step 1: Update DESIGN.md colors to the shipped token names**

In `DESIGN.md`, reconcile the `colors:` front-matter so the token names match the `@theme` set (primary/primary-light/primary-strong/primary-subtle/primary-tint/primary-tint-strong, neutral-50…900, success*/error*/warning*, admin-300…800, surface). Keep the hex values (unchanged). In the `## Colors` prose, note that **`src/claimos/styles/theme.css` `@theme` is the structural source of truth** for color tokens (compiled into `app.css`); DESIGN.md documents the same tokens for humans. Do not alter the depreciation/legal/other sections.

- [ ] **Step 2: Confirm nothing else references the old token names**

Run: `grep -rn "primary-hover\|primary-active\|text-muted\|text-strong-alt\|success-icon" DESIGN.md || echo "no stale token names ✓"`
Expected: either shows the lines to reconcile (fix them) or `no stale token names ✓`.

- [ ] **Step 3: Commit**

```bash
git add DESIGN.md
git commit -m "docs: reconcile DESIGN.md color tokens with theme.css @theme (source of truth)"
```

---

## Self-Review

- **Spec coverage:** token set + palette-clear (T1+T4), template migration (T2), JS migration + fold (T3), guard rewrite (T4), type/radius values (T1), parity verification (T5), docs (T6). All spec sections mapped.
- **Placeholder scan:** none — every step has concrete code/commands and the full substitution maps.
- **Type/name consistency:** the `MAP` dicts in T2/T3, the `EXPECTED` dict in T1, the token table, and the guard families list all use the same token names and hexes. `find_raw_family_hits`/`main` are defined in T4 and used by its test.
- **Ordering safety:** palette is cleared only in T4 (after T2/T3 migration), so the app renders at every prior step; `neutral` excluded from the guard blocklist to avoid flagging our own ramp.
- **Parity honesty:** each token hex == former shade (T1 test); the JS fold is the sole intended visual change and is called out in T3/T5.
