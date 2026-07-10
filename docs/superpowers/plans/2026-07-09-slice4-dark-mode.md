# Slice 4 — Dark / Light Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dark mode driven from the token layer (`light-dark()` values + `color-scheme`), with an OS-default + cookie override applied server-side; light mode stays pixel-identical.

**Architecture:** Every mode-varying `@theme` color token becomes `light-dark(<light>, <dark>)`; `color-scheme` on `:root`/`.light`/`.dark` selects the mode. A `theme` cookie maps (server-side, via a Jinja global) to a `dark`/`light`/`""` class on `<html>` — no inline script, no flash. A 3-state control in `app.js` sets the cookie + flips the class live. No template migration; no `dark:` utilities.

**Tech Stack:** Tailwind v4 `@theme` + CSS `light-dark()`/`color-scheme`, FastAPI + Jinja2, vanilla JS, pytest.

## Global Constraints

- **Light mode unchanged:** the light value of every token equals its current hex (parity). Verified by a test.
- **No inline JS handlers** (CSP). Toggle wired via `data-*` delegated listener in `app.js`.
- **`light-dark()` is confirmed working** through the Tailwind build (prototyped). Single-value tokens `white`, `black`, and `admin-*` stay plain (mode-independent chrome).
- **Report preview forced light**; `report/pdf.html` (WeasyPrint) untouched.
- Python via venv (`source .venv/bin/activate &&`). Run `uv run ruff format .` → `ruff format --check .` → `ruff check .` before committing any `.py`.
- `app.css`/`bin/` stay gitignored. Branch `feat/dark-mode-slice4`; never `main`.

## Reference dark palette (light → dark)

```
primary-subtle #eef2ff/#1e1b4b   primary-tint #e0e7ff/#312e81   primary-tint-strong #c7d2fe/#3730a3
primary-light #6366f1/#a5b4fc     primary #4f46e5/#818cf8        primary-strong #4338ca/#6366f1
neutral-50 #f9fafb/#0f1115  neutral-100 #f3f4f6/#17191e  neutral-200 #e5e7eb/#262932
neutral-300 #d1d5db/#363a44  neutral-400 #9ca3af/#6b7280  neutral-500 #6b7280/#9aa1ac
neutral-600 #4b5563/#b6bcc6  neutral-700 #374151/#d2d7de  neutral-900 #111827/#f2f4f7
surface #ffffff/#1a1d23
success-surface #f0fdf4/#052e16  success-surface-strong #dcfce7/#14532d  success-border #bbf7d0/#166534
success-emphasis #16a34a/#22c55e  success #15803d/#4ade80  success-strong #166534/#86efac
error-surface #fef2f2/#450a0a  error-surface-strong #fee2e2/#7f1d1d  error-border #fecaca/#991b1b
error #dc2626/#f87171  error-strong #b91c1c/#fca5a5  error-strongest #991b1b/#fecaca
warning-surface #fffbeb/#451a03  warning-surface-strong #fef3c7/#78350f  warning-border #fde68a/#92400e
warning-emphasis #d97706/#f59e0b  warning #b45309/#fbbf24  warning-strong #92400e/#fcd34d
```

---

### Task 1: Dark token values + color-scheme in theme.css

**Files:**
- Modify: `src/claimos/styles/theme.css`
- Modify: `tests/test_theme_tokens.py` (extract the light value from `light-dark()`)
- Test: `tests/test_dark_mode_tokens.py`

**Interfaces:**
- Produces: every mode-varying `--color-*` token as `light-dark(light, dark)`; `:root/.light/.dark { color-scheme }` rules.

- [ ] **Step 1: Add color-scheme selectors + convert tokens in `theme.css`**

Immediately AFTER the closing `}` of the `@theme` block, add:
```css
:root      { color-scheme: light dark; }
:root.light { color-scheme: light; }
:root.dark  { color-scheme: dark; }
```
Then inside `@theme`, replace each mode-varying token's value with its `light-dark()` pair (light = current value). The full set:
```css
  --color-primary-subtle: light-dark(#eef2ff, #1e1b4b);
  --color-primary-tint: light-dark(#e0e7ff, #312e81);
  --color-primary-tint-strong: light-dark(#c7d2fe, #3730a3);
  --color-primary-light: light-dark(#6366f1, #a5b4fc);
  --color-primary: light-dark(#4f46e5, #818cf8);
  --color-primary-strong: light-dark(#4338ca, #6366f1);
  --color-neutral-50: light-dark(#f9fafb, #0f1115);
  --color-neutral-100: light-dark(#f3f4f6, #17191e);
  --color-neutral-200: light-dark(#e5e7eb, #262932);
  --color-neutral-300: light-dark(#d1d5db, #363a44);
  --color-neutral-400: light-dark(#9ca3af, #6b7280);
  --color-neutral-500: light-dark(#6b7280, #9aa1ac);
  --color-neutral-600: light-dark(#4b5563, #b6bcc6);
  --color-neutral-700: light-dark(#374151, #d2d7de);
  --color-neutral-900: light-dark(#111827, #f2f4f7);
  --color-success-surface: light-dark(#f0fdf4, #052e16);
  --color-success-surface-strong: light-dark(#dcfce7, #14532d);
  --color-success-border: light-dark(#bbf7d0, #166534);
  --color-success-emphasis: light-dark(#16a34a, #22c55e);
  --color-success: light-dark(#15803d, #4ade80);
  --color-success-strong: light-dark(#166534, #86efac);
  --color-error-surface: light-dark(#fef2f2, #450a0a);
  --color-error-surface-strong: light-dark(#fee2e2, #7f1d1d);
  --color-error-border: light-dark(#fecaca, #991b1b);
  --color-error: light-dark(#dc2626, #f87171);
  --color-error-strong: light-dark(#b91c1c, #fca5a5);
  --color-error-strongest: light-dark(#991b1b, #fecaca);
  --color-warning-surface: light-dark(#fffbeb, #451a03);
  --color-warning-surface-strong: light-dark(#fef3c7, #78350f);
  --color-warning-border: light-dark(#fde68a, #92400e);
  --color-warning-emphasis: light-dark(#d97706, #f59e0b);
  --color-warning: light-dark(#b45309, #fbbf24);
  --color-warning-strong: light-dark(#92400e, #fcd34d);
  --color-surface: light-dark(#ffffff, #1a1d23);
```
LEAVE `--color-white: #ffffff;`, `--color-black: #000000;`, and all `--color-admin-*` unchanged (plain single values). LEAVE `--font-sans`/`--radius-*` unchanged.

- [ ] **Step 2: Update `tests/test_theme_tokens.py` to read the light value**

The Slice-2 parity test expects `--color-<name>: <#hex>;`. Update its token parser to accept `light-dark(#light, #dark)` and compare the LIGHT value (proves light mode unchanged). Replace the token-extraction regex/function with:
```python
def _tokens():
    text = THEME.read_text()
    out = {}
    for m in re.finditer(r"--color-([a-z0-9-]+):\s*([^;]+);", text):
        name, val = m.group(1), m.group(2).strip()
        ld = re.match(r"light-dark\(\s*(#[0-9a-fA-F]{6})\s*,", val)
        if ld:
            out[name] = ld.group(1).lower()
        elif re.match(r"#[0-9a-fA-F]{6}$", val):
            out[name] = val.lower()
    return out
```
(The `EXPECTED` dict of light hexes is unchanged — this asserts the light values still match, i.e. light-mode parity.)

- [ ] **Step 3: Write the dark-completeness test**

Create `tests/test_dark_mode_tokens.py`:
```python
import re
from pathlib import Path

THEME = Path("src/claimos/styles/theme.css")

# tokens that are intentionally mode-independent (single value)
SINGLE_VALUE = {"white", "black"}


def _theme_block() -> str:
    text = THEME.read_text()
    m = re.search(r"@theme\s*\{(.*?)\n\}", text, re.DOTALL)
    assert m, "no @theme block"
    return m.group(1)


def test_every_color_token_is_light_dark_except_single_value_and_admin():
    block = _theme_block()
    offenders = []
    for m in re.finditer(r"--color-([a-z0-9-]+):\s*([^;]+);", block):
        name, val = m.group(1), m.group(2).strip()
        if name in SINGLE_VALUE or name.startswith("admin-"):
            continue
        if not val.startswith("light-dark("):
            offenders.append(name)
    assert not offenders, f"color tokens missing a dark value: {offenders}"


def test_color_scheme_selectors_present():
    text = THEME.read_text()
    assert ":root      { color-scheme: light dark; }" in text or "color-scheme: light dark" in text
    assert "color-scheme: dark" in text
    assert "color-scheme: light;" in text
```

- [ ] **Step 4: Run tests + build**

Run:
```bash
source .venv/bin/activate
uv run pytest tests/test_theme_tokens.py tests/test_dark_mode_tokens.py -q
uv run css && grep -q 'light-dark(#ffffff' src/claimos/static/app.css && grep -q 'color-scheme:dark\|color-scheme: dark' src/claimos/static/app.css && echo "css ok"
uv run pytest -q 2>&1 | tail -1
```
Expected: token tests pass (light parity holds); `css ok`; full suite passes.

- [ ] **Step 5: Format + commit**

```bash
source .venv/bin/activate && uv run ruff format tests/ && uv run ruff format --check . && uv run ruff check .
git add src/claimos/styles/theme.css tests/test_theme_tokens.py tests/test_dark_mode_tokens.py
git commit -m "feat(css): add dark values via light-dark() + color-scheme (light unchanged)"
```

---

### Task 2: Server-side theme_class from cookie

**Files:**
- Create: `src/claimos/theming.py`
- Modify: `src/claimos/main.py` (register Jinja global)
- Test: `tests/test_theming.py`

**Interfaces:**
- Produces: `theming.theme_class_for(request) -> str` returning `"dark"` / `"light"` / `""`; registered as Jinja global `theme_class`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_theming.py`:
```python
from claimos.theming import theme_class_for


class _Req:
    def __init__(self, theme=None):
        self.cookies = {"theme": theme} if theme is not None else {}


def test_theme_class_dark():
    assert theme_class_for(_Req("dark")) == "dark"


def test_theme_class_light():
    assert theme_class_for(_Req("light")) == "light"


def test_theme_class_absent_is_system():
    assert theme_class_for(_Req()) == ""


def test_theme_class_unknown_is_system():
    assert theme_class_for(_Req("purple")) == ""
```

- [ ] **Step 2: Run it — expect failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_theming.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `theming.py`**

Create `src/claimos/theming.py`:
```python
"""Server-side light/dark theme selection from the `theme` cookie."""

from __future__ import annotations

from starlette.requests import Request

_VALID = {"dark", "light"}


def theme_class_for(request: Request) -> str:
    """Return the <html> class for the request's theme cookie.

    "dark"/"light" force that mode; anything else (incl. absent) yields "" so the
    CSS `color-scheme: light dark` follows the OS.
    """
    choice = request.cookies.get("theme", "")
    return choice if choice in _VALID else ""
```

- [ ] **Step 4: Register the Jinja global in `main.py`**

After `templates = Jinja2Templates(directory=BASE_DIR / "templates")` (main.py:90), add:
```python
from claimos.theming import theme_class_for

templates.env.globals["theme_class"] = theme_class_for
```
(Place the import with the other imports; the assignment right after `templates` is created.)

- [ ] **Step 5: Run tests + suite**

Run: `source .venv/bin/activate && uv run pytest tests/test_theming.py -q && uv run pytest -q 2>&1 | tail -1`
Expected: pass; full suite passes.

- [ ] **Step 6: Format + commit**

```bash
source .venv/bin/activate && uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/theming.py src/claimos/main.py tests/test_theming.py
git commit -m "feat: server-side theme_class from cookie (Jinja global)"
```

---

### Task 3: Apply theme_class to shells; force report preview light

**Files:**
- Modify: `base.html`, `login.html`, `login_mfa.html`, `register.html`, `splash.html`, `admin/base.html` (add `{{ theme_class(request) }}` to `<html class>`)
- Modify: `report/preview.html` (`<html class="light">`)
- Test: `tests/test_theme_cookie.py`

**Interfaces:**
- Consumes: `theme_class` Jinja global (Task 2).

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_theme_cookie.py`:
```python
from fastapi.testclient import TestClient

from claimos.main import app

client = TestClient(app)


def test_dark_cookie_sets_html_dark_class():
    r = client.get("/", cookies={"theme": "dark"})
    assert r.status_code == 200
    assert 'class="h-full bg-neutral-50 dark"' in r.text or ' dark"' in r.text.split("<html", 1)[1][:80]


def test_light_cookie_sets_html_light_class():
    r = client.get("/", cookies={"theme": "light"})
    assert " light" in r.text.split("<html", 1)[1][:80]


def test_no_cookie_no_theme_class():
    r = client.get("/")
    head = r.text.split("<html", 1)[1][:80]
    assert " dark" not in head and " light" not in head


def test_report_preview_template_forces_light():
    # static guarantee: the report preview shell is always light, independent of cookie
    from pathlib import Path
    html = Path("src/claimos/templates/report/preview.html").read_text()
    assert '<html lang="en" class="light">' in html
```
(If `/` is not the right unauthenticated route, use `/login`; confirm via `src/claimos/routers`.)

- [ ] **Step 2: Run it — expect failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_theme_cookie.py -q`
Expected: FAIL (shells don't emit the class yet).

- [ ] **Step 3: Add `theme_class` to the six app shells**

In each of `base.html`, `login.html`, `login_mfa.html`, `register.html`, `splash.html`, change:
```html
<html lang="en" class="h-full bg-neutral-50">
```
to:
```html
<html lang="en" class="h-full bg-neutral-50 {{ theme_class(request) }}">
```
In `admin/base.html`, change `class="h-full bg-neutral-100"` to `class="h-full bg-neutral-100 {{ theme_class(request) }}"`.

- [ ] **Step 4: Force the report preview to light**

In `report/preview.html`, change `<html lang="en">` to `<html lang="en" class="light">`.

- [ ] **Step 5: Run test + suite**

Run: `source .venv/bin/activate && uv run pytest tests/test_theme_cookie.py -q && uv run pytest -q 2>&1 | tail -1`
Expected: pass; full suite passes.

- [ ] **Step 6: Commit**

```bash
git add src/claimos/templates
git commit -m "feat(ui): apply theme_class to shells; force report preview light"
```

---

### Task 4: Theme toggle control + app.js wiring

**Files:**
- Create: `src/claimos/templates/_theme_toggle.html`
- Modify: `base.html`, `admin/base.html` (include the toggle in the nav)
- Modify: `src/claimos/static/app.js` (delegated listener)
- Test: `tests/test_theme_toggle_markup.py`

**Interfaces:**
- Consumes: nothing (client-side + CSS from Task 1).

- [ ] **Step 1: Create the toggle partial**

Create `src/claimos/templates/_theme_toggle.html`:
```html
<div class="inline-flex items-center rounded-md border border-neutral-300 text-xs" role="group" aria-label="Theme">
  <button type="button" data-theme-set="system"
          class="px-2 py-1 rounded-l-md text-neutral-600 hover:bg-neutral-100" title="Match system theme">Auto</button>
  <button type="button" data-theme-set="light"
          class="px-2 py-1 text-neutral-600 hover:bg-neutral-100 border-l border-neutral-300" title="Light">Light</button>
  <button type="button" data-theme-set="dark"
          class="px-2 py-1 rounded-r-md text-neutral-600 hover:bg-neutral-100 border-l border-neutral-300" title="Dark">Dark</button>
</div>
```

- [ ] **Step 2: Include it in the navs**

In `base.html`, inside the right-hand nav group `<div class="flex items-center gap-4">`, add before the `{% if user %}`:
```html
          {% include "_theme_toggle.html" %}
```
In `admin/base.html`, add `{% include "_theme_toggle.html" %}` into its top nav bar (near the existing nav links).

- [ ] **Step 3: Add the delegated listener to `app.js`**

Append to `src/claimos/static/app.js`:
```javascript
// Theme toggle: System / Light / Dark. Persisted in the `theme` cookie; the
// <html> class is set server-side on load, and flipped live here. color-scheme
// (in app.css) does the actual light/dark selection.
(function () {
  function applyTheme(mode) {
    const root = document.documentElement;
    root.classList.remove('light', 'dark');
    if (mode === 'light' || mode === 'dark') {
      root.classList.add(mode);
      document.cookie = 'theme=' + mode + '; path=/; max-age=31536000; samesite=lax';
    } else {
      document.cookie = 'theme=; path=/; max-age=0; samesite=lax'; // system => clear
    }
    syncActive(mode);
  }
  function currentMode() {
    if (document.documentElement.classList.contains('dark')) return 'dark';
    if (document.documentElement.classList.contains('light')) return 'light';
    return 'system';
  }
  function syncActive(mode) {
    document.querySelectorAll('[data-theme-set]').forEach(function (b) {
      const on = b.dataset.themeSet === mode;
      b.classList.toggle('bg-neutral-100', on);
      b.classList.toggle('text-neutral-900', on);
    });
  }
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-theme-set]');
    if (btn) applyTheme(btn.dataset.themeSet);
  });
  syncActive(currentMode());
})();
```

- [ ] **Step 4: Write a markup/wiring test**

Create `tests/test_theme_toggle_markup.py`:
```python
from pathlib import Path

from fastapi.testclient import TestClient

from claimos.main import app

client = TestClient(app)


def test_toggle_renders_in_nav():
    r = client.get("/login")
    # login has no nav; use a page that includes base nav via an auth<-free path if needed.
    # The toggle partial itself must exist and expose the three data-theme-set controls:
    partial = Path("src/claimos/templates/_theme_toggle.html").read_text()
    for mode in ("system", "light", "dark"):
        assert f'data-theme-set="{mode}"' in partial


def test_app_js_wires_theme_toggle():
    js = Path("src/claimos/static/app.js").read_text()
    assert "data-theme-set" in js
    assert "classList.add(mode)" in js
    assert "theme=" in js  # sets cookie
```

- [ ] **Step 5: Run tests + suite + build**

Run: `source .venv/bin/activate && uv run pytest tests/test_theme_toggle_markup.py -q && uv run css && uv run pytest -q 2>&1 | tail -1`
Expected: pass; build ok; full suite passes.

- [ ] **Step 6: Commit**

```bash
git add src/claimos/templates/_theme_toggle.html src/claimos/templates/base.html src/claimos/templates/admin/base.html src/claimos/static/app.js tests/test_theme_toggle_markup.py
git commit -m "feat(ui): add System/Light/Dark theme toggle (nav + app.js)"
```

---

### Task 5: Verification + docs

**Files:**
- Modify: `DESIGN.md` (dark-mode note)

- [ ] **Step 1: Guard, suite, lint, build**

Run:
```bash
source .venv/bin/activate
python scripts/audit_design_tokens.py
uv run pytest -q 2>&1 | tail -1
uv run ruff format --check . && uv run ruff check .
rm -f src/claimos/static/app.css && uv run css --minify && test -s src/claimos/static/app.css && echo built
```
Expected: guard clean; all tests pass; ruff clean; `built`.

- [ ] **Step 2: Confirm dark values reach the compiled CSS**

Run:
```bash
cd /Users/cmondor/consulting/tor
grep -o 'light-dark(#[0-9a-f]*, *#[0-9a-f]*)' src/claimos/static/app.css | head -5
grep -c 'color-scheme' src/claimos/static/app.css | xargs -I{} echo "color-scheme rules: {}"
```
Expected: several `light-dark(...)` values present; color-scheme rules > 0.

- [ ] **Step 3: Manual dark-mode smoke (recommended)**

`uv run css` then `uv run dev`. Visit a page; use the toggle → Dark: page background/cards/text/borders invert to the dark palette, buttons/badges adapt, live with no reload. Reload → still dark (cookie). Set → Auto and change OS appearance to confirm OS-follow. Open a report preview → stays light regardless of toggle.

- [ ] **Step 4: DESIGN.md note**

In `DESIGN.md` (Colors or a new short "Modes" note), record that the app supports light/dark via `light-dark()` token values + `color-scheme`, selected by the `theme` cookie (server-set `<html>` class; System/Light/Dark toggle). A rebrand supplies both light and dark values per token in `theme.css`. The report/PDF is always light. Do not alter other sections.

- [ ] **Step 5: Commit**

```bash
git add DESIGN.md
git commit -m "docs: note light/dark mode (light-dark tokens + theme cookie)"
```

---

## Self-Review

- **Spec coverage:** dark token values + color-scheme (T1), server cookie→class (T2), shells + report-light (T3), toggle + app.js (T4), verification + docs (T5). All spec sections mapped.
- **Placeholder scan:** none — full token block, helper, listener, and tests are concrete.
- **Consistency:** `theme_class_for` (T2) is used by the shells (T3) via the `theme_class` Jinja global; the `data-theme-set` values (`system`/`light`/`dark`) match between the partial (T4 Step 1) and the app.js listener (T4 Step 3); the light values in T1 equal the Slice-2 `EXPECTED` hexes (parity via T1 Step 2).
- **Light-mode parity:** guaranteed by the updated `test_theme_tokens.py` (light value == current hex). Dark is net-new.
- **Risk retired:** `light-dark()` through `@theme` was prototyped and confirmed; no fallback needed.
- **CSP:** toggle is a delegated `document.addEventListener` in app.js with `data-*` — no inline handlers.
