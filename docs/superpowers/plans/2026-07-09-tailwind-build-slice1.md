# Tailwind Build Foundation — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the runtime Tailwind CDN with a self-hosted, standalone-CLI-built `app.css` (Tailwind v4, no Node), at strict visual parity.

**Architecture:** A single `theme.css` (`@import "tailwindcss"` + `@source` globs + a border-color base-compat rule) is compiled by the pinned Tailwind v4 standalone binary to a gitignored `src/claimos/static/app.css`, served via `<link>`. Templates get a scripted, pixel-identical v3→v4 utility rename. Build runs in dev (`uv run css`), Docker (build stage), and CI (build-health gate). CDN is dropped from CSP.

**Tech Stack:** Tailwind CSS v4 standalone CLI binary, FastAPI/Jinja templates, `uv`/Python entrypoint, Docker, GitHub Actions.

## Global Constraints

- **No Node/npm.** Use the Tailwind v4 **standalone binary** only.
- **Python via venv/`uv`.** Prefix python/uv calls with `source .venv/bin/activate &&`.
- **No restyle.** The only template edits are the deterministic v3→v4 utility renames below — pixel-identical, not design changes.
- **Rename map (whole-token substitutions):** `outline-none`→`outline-hidden`, bare `rounded`→`rounded-sm`, `rounded-b`→`rounded-b-sm`, `shadow-sm`→`shadow-xs`, bare `shadow`→`shadow-sm`, bare `ring`→`ring-3`. Unaffected: `rounded-md`/`rounded-lg`/`rounded-full`, `ring-1`/`ring-2`, all explicit colors.
- **CSP:** remove `https://cdn.tailwindcss.com` from `script-src` and `style-src`; **keep** `style-src 'unsafe-inline'` (templates use dynamic `style="…{{…}}"`, e.g. `_scan_progress.html`).
- **`app.css` is generated, gitignored, never committed.** Built in dev, Docker, CI.
- **Print report untouched:** do not modify `src/claimos/templates/report/pdf.html`.
- **Run `uv run ruff format .` then `uv run ruff format --check .` and `uv run ruff check .`** before committing any `.py`.
- **Never commit to `main`.** Work on `feat/tailwind-build-foundation`.

## File Structure

- Create `src/claimos/styles/theme.css` — Tailwind entry + `@source` + border compat. (source of the build)
- Create `scripts/fetch-tailwind.sh` — download + verify the pinned standalone binary to `bin/tailwindcss`.
- Create `scripts/build-css.sh` — thin wrapper invoking the binary with fixed `-i`/`-o`.
- Create `src/claimos/css_build.py` — `uv run css` entrypoint (wraps the binary; supports `--watch`/`--minify`).
- Create `tests/test_css_build.py` — unit test for the entrypoint's command building.
- Create `tests/test_static_css.py` — integration test: pages link `app.css`, no CDN, CSP correct.
- Modify `pyproject.toml` — add `css` script.
- Modify `.gitignore` — ignore `src/claimos/static/app.css`, `bin/`.
- Modify 7 shell templates — CDN `<script>` → `<link>`.
- Modify all templates — scripted utility rename.
- Modify `src/claimos/middleware.py` — CSP.
- Modify `Dockerfile` — CSS build stage.
- Modify `.github/workflows/ci.yml` — build-health step.
- Modify `CLAUDE.md`, `README.md` — stack rule, commands, dev workflow.

---

### Task 1: Build tooling + theme.css (the pipeline)

**Files:**
- Create: `src/claimos/styles/theme.css`, `scripts/fetch-tailwind.sh`, `scripts/build-css.sh`, `src/claimos/css_build.py`
- Modify: `pyproject.toml` (`[project.scripts]`), `.gitignore`
- Test: `tests/test_css_build.py`

**Interfaces:**
- Produces: `css_build.build_command(watch: bool, minify: bool) -> list[str]`; `css_build.main() -> None` (entrypoint `css`). `scripts/build-css.sh` (accepts `--watch`/`--minify`). `bin/tailwindcss` binary. Output at `src/claimos/static/app.css`.

- [ ] **Step 1: Add gitignores first (so a generated app.css is never staged)**

Append to `.gitignore`:
```
# Tailwind build
/bin/
src/claimos/static/app.css
```

- [ ] **Step 2: Write `theme.css`**

Create `src/claimos/styles/theme.css`:
```css
@import "tailwindcss";

/* Scan the server-rendered templates so only used utilities are emitted. */
@source "../templates/**/*.html";

/* v3→v4 parity: v4 defaults an un-colored `border` to currentColor;
   the templates assume v3's gray-200 default. */
@layer base {
  *,
  ::before,
  ::after {
    border-color: var(--color-gray-200, currentColor);
  }
}
```

- [ ] **Step 3: Write `scripts/fetch-tailwind.sh`**

Create `scripts/fetch-tailwind.sh` (make executable). Pin a version; confirm/bump to the current latest **v4** stable at https://github.com/tailwindlabs/tailwindcss/releases and record the sha256 below before running:
```bash
#!/usr/bin/env bash
set -euo pipefail
TAILWIND_VERSION="v4.1.13"   # confirm/bump to latest v4 stable; must be a v4.x tag
DEST="bin/tailwindcss"

os="$(uname -s)"; arch="$(uname -m)"
case "$os-$arch" in
  Darwin-arm64)  asset="tailwindcss-macos-arm64" ;;
  Darwin-x86_64) asset="tailwindcss-macos-x64" ;;
  Linux-x86_64)  asset="tailwindcss-linux-x64" ;;
  Linux-aarch64) asset="tailwindcss-linux-arm64" ;;
  *) echo "unsupported platform: $os-$arch" >&2; exit 1 ;;
esac

mkdir -p bin
url="https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/${asset}"
echo "Fetching $url"
curl -fsSL "$url" -o "$DEST"
chmod +x "$DEST"
"$DEST" --help >/dev/null && echo "tailwindcss ${TAILWIND_VERSION} ready at $DEST"
```

- [ ] **Step 4: Write `scripts/build-css.sh`**

Create `scripts/build-css.sh` (make executable):
```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/bin/tailwindcss"
if [[ ! -x "$BIN" ]]; then
  echo "tailwindcss binary missing; run scripts/fetch-tailwind.sh" >&2
  exit 1
fi
exec "$BIN" \
  -i "$ROOT/src/claimos/styles/theme.css" \
  -o "$ROOT/src/claimos/static/app.css" \
  "$@"
```

- [ ] **Step 5: Write the failing test for the entrypoint**

Create `tests/test_css_build.py`:
```python
from claimos import css_build


def test_build_command_default():
    cmd = css_build.build_command(watch=False, minify=False)
    assert cmd[0].endswith("bin/tailwindcss")
    assert "-i" in cmd and "-o" in cmd
    assert cmd[cmd.index("-i") + 1].endswith("src/claimos/styles/theme.css")
    assert cmd[cmd.index("-o") + 1].endswith("src/claimos/static/app.css")
    assert "--watch" not in cmd and "--minify" not in cmd


def test_build_command_watch_and_minify():
    cmd = css_build.build_command(watch=True, minify=True)
    assert "--watch" in cmd
    assert "--minify" in cmd
```

- [ ] **Step 6: Run it — expect failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_css_build.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'claimos.css_build'`.

- [ ] **Step 7: Write `css_build.py`**

Create `src/claimos/css_build.py`:
```python
"""`uv run css` — build the Tailwind stylesheet via the standalone binary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent  # src/claimos
_ROOT = _BASE.parent.parent  # repo root
BIN = _ROOT / "bin" / "tailwindcss"
INPUT = _BASE / "styles" / "theme.css"
OUTPUT = _BASE / "static" / "app.css"


def build_command(watch: bool, minify: bool) -> list[str]:
    cmd = [str(BIN), "-i", str(INPUT), "-o", str(OUTPUT)]
    if watch:
        cmd.append("--watch")
    if minify:
        cmd.append("--minify")
    return cmd


def main() -> None:
    args = sys.argv[1:]
    if not BIN.exists():
        print(
            f"tailwindcss binary not found at {BIN}; run scripts/fetch-tailwind.sh",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise SystemExit(subprocess.call(build_command("--watch" in args, "--minify" in args)))
```

- [ ] **Step 8: Register the `css` entrypoint**

In `pyproject.toml` under `[project.scripts]`, add after the `dev` line:
```toml
css = "claimos.css_build:main"
```

- [ ] **Step 9: Run tests — expect pass**

Run: `source .venv/bin/activate && uv sync --quiet && uv run pytest tests/test_css_build.py -q`
Expected: PASS (2 passed).

- [ ] **Step 10: Smoke-build the real CSS**

Run:
```bash
source .venv/bin/activate
bash scripts/fetch-tailwind.sh
uv run css --minify
test -s src/claimos/static/app.css && echo "app.css built ($(wc -c < src/claimos/static/app.css) bytes)"
grep -q '\.rounded-lg' src/claimos/static/app.css && echo "contains expected utilities"
```
Expected: `app.css built (…)` with a non-trivial byte count and "contains expected utilities". (Note: at this point templates still use v3 names like bare `rounded`, so `app.css` will contain those; the rename in Task 2 aligns them to v4.)

- [ ] **Step 11: Format, lint, commit**

```bash
source .venv/bin/activate && uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add .gitignore pyproject.toml src/claimos/styles/theme.css src/claimos/css_build.py \
        scripts/fetch-tailwind.sh scripts/build-css.sh tests/test_css_build.py
git commit -m "feat: tailwind v4 standalone build pipeline (theme.css, css_build, scripts)"
```

---

### Task 2: Scripted v3→v4 utility rename in templates

**Files:**
- Modify: `src/claimos/templates/**/*.html` (whole-token renames; `report/pdf.html` excluded by the map since it uses inline hex, but the script will visit it — confirm no false hits)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: templates using v4 utility names, pixel-identical rendering.

- [ ] **Step 1: Write the one-shot rename script to scratchpad**

Save to `/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad/v4rename.py`:
```python
import glob, re

# whole-token renames: (regex, replacement). Boundaries: not preceded/followed by [\w-],
# so `rounded-md` is never hit by the bare-`rounded` rule, and variant prefixes
# (hover:, focus:, sm:) are preserved.
RULES = [
    (r'(?<![\w-])outline-none(?![\w-])', 'outline-hidden'),
    (r'(?<![\w-])rounded-b(?![\w-])',    'rounded-b-sm'),
    (r'(?<![\w-])rounded(?![\w-])',      'rounded-sm'),
    (r'(?<![\w-])shadow-sm(?![\w-])',    'shadow-xs'),
    (r'(?<![\w-])shadow(?![\w-])',       'shadow-sm'),
    (r'(?<![\w-])ring(?![\w-])',         'ring-3'),
]
# Order note: `rounded-b` before bare `rounded`; `shadow-sm` before bare `shadow`.
# Because every rule is a whole-token match, the negative lookarounds already prevent
# cross-contamination (e.g. bare `shadow` won't touch `shadow-sm`/`shadow-xs`), but the
# ordering makes intent explicit.

total = 0
for fp in glob.glob("src/claimos/templates/**/*.html", recursive=True):
    s = open(fp).read()
    orig = s
    for pat, repl in RULES:
        s = re.sub(pat, repl, s)
    if s != orig:
        open(fp, "w").write(s)
        total += 1
        print("renamed", fp)
print("files changed:", total)
```

- [ ] **Step 2: Dry-count expected hits first (safety check)**

Run:
```bash
cd /Users/cmondor/consulting/tor
grep -roE '(?<=[ "])(outline-none|rounded-b|rounded|shadow-sm|shadow|ring)(?=[ "])' src/claimos/templates | \
  grep -oE '(outline-none|rounded-b|rounded|shadow-sm|shadow|ring)$' | sort | uniq -c
```
Expected (approx, from the spec's measured counts): `outline-none 76`, bare `rounded ~250`, `rounded-b 1`, `shadow-sm 65`, bare `shadow 42`, bare `ring 9`. (grep's lookbehind needs `-P`; if unavailable, skip this check and rely on Step 4's audit.)

- [ ] **Step 3: Run the rename**

Run: `source .venv/bin/activate && python "/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad/v4rename.py"`
Expected: lists renamed files, `files changed: N`.

- [ ] **Step 4: Verify no stale v3 names remain and no double-renames occurred**

Run:
```bash
cd /Users/cmondor/consulting/tor
echo "stale bare v3 names (expect 0):"
grep -roE '(?:class="[^"]*)( |")(rounded|shadow|shadow-sm|outline-none|ring)( |")' src/claimos/templates | wc -l
echo "double-rename artifacts (expect 0):"
grep -rE 'rounded-sm-sm|shadow-sm-xs|shadow-xs-sm|ring-3-3|outline-hidden-hidden' src/claimos/templates | wc -l
```
Expected: both `0`. (The first heuristic may catch legitimately-renamed tokens indirectly; the authoritative signal is 0 double-rename artifacts and Task 6's build+render.)

- [ ] **Step 5: Confirm the existing color drift-audit still passes (renames don't touch colors)**

Run: `source .venv/bin/activate && python scripts/audit_design_tokens.py; echo "exit=$?"`
Expected: `clean ✓`, `exit=0`.

- [ ] **Step 6: Commit**

```bash
git add src/claimos/templates
git commit -m "refactor(ui): rename utilities to Tailwind v4 names (outline-hidden/rounded-sm/shadow-xs/shadow-sm/ring-3) — pixel-identical"
```

---

### Task 3: Serve app.css, drop the CDN, tighten CSP

**Files:**
- Modify: `src/claimos/templates/base.html`, `admin/base.html`, `splash.html`, `login.html`, `login_mfa.html`, `register.html`, `report/preview.html` (CDN `<script>` → `<link>`)
- Modify: `src/claimos/middleware.py` (CSP)
- Test: `tests/test_static_css.py`

**Interfaces:**
- Consumes: `app.css` at `/static/app.css` (built by Task 1).
- Produces: app served with self-hosted CSS, no CDN.

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_static_css.py`:
```python
from fastapi.testclient import TestClient

from claimos.main import app

client = TestClient(app)


def test_splash_links_selfhosted_css_not_cdn():
    r = client.get("/splash")
    assert r.status_code == 200
    assert '/static/app.css' in r.text
    assert 'cdn.tailwindcss.com' not in r.text


def test_csp_drops_cdn_keeps_style_unsafe_inline():
    r = client.get("/splash")
    csp = r.headers["content-security-policy"]
    assert 'cdn.tailwindcss.com' not in csp
    # dynamic style="" attributes (e.g. progress bars) still need this:
    assert "style-src 'self' 'unsafe-inline'" in csp
```
(If `/splash` is not the correct public path, use `/` or `/login`, whichever renders a shell template without auth — confirm via `src/claimos/routers`.)

- [ ] **Step 2: Run it — expect failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_static_css.py -q`
Expected: FAIL (templates still reference the CDN; CSP still lists it).

- [ ] **Step 3: Swap the CDN `<script>` for a `<link>` in all 7 shell templates**

In each of `base.html`, `admin/base.html`, `splash.html`, `login.html`, `login_mfa.html`, `register.html`, `report/preview.html`, replace the line:
```html
<script src="https://cdn.tailwindcss.com"></script>
```
with:
```html
<link rel="stylesheet" href="/static/app.css" />
```

- [ ] **Step 4: Update the CSP in `middleware.py`**

Replace the `script-src`/`style-src` lines (currently lines ~27–29):
```python
            "script-src 'self' https://unpkg.com https://cdn.tailwindcss.com"
            " https://claimos.cmondor.com https://static.cloudflareinsights.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
```
with:
```python
            "script-src 'self' https://unpkg.com"
            " https://claimos.cmondor.com https://static.cloudflareinsights.com; "
            "style-src 'self' 'unsafe-inline'; "
```

- [ ] **Step 5: Run the test — expect pass**

Run: `source .venv/bin/activate && uv run css && uv run pytest tests/test_static_css.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Format, lint, commit**

```bash
source .venv/bin/activate && uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/claimos/templates src/claimos/middleware.py tests/test_static_css.py
git commit -m "feat: serve self-hosted app.css, drop Tailwind CDN from templates and CSP"
```

---

### Task 4: Build CSS in Docker and CI

**Files:**
- Modify: `Dockerfile` (add a CSS build stage / step producing `app.css` in the image)
- Modify: `.github/workflows/ci.yml` (build-health step)

**Interfaces:**
- Consumes: `scripts/fetch-tailwind.sh`, `scripts/build-css.sh`, `theme.css`.
- Produces: prod image with `src/claimos/static/app.css`; CI gate that fails on build breakage.

- [ ] **Step 1: Add the CSS build to the Dockerfile**

In `Dockerfile`, after `COPY . .` and before/around the app `uv sync`, add a step that fetches the binary (Linux) and builds minified CSS into the image:
```dockerfile
# Build the Tailwind stylesheet (standalone binary, no Node)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && bash scripts/fetch-tailwind.sh \
    && bash scripts/build-css.sh --minify \
    && test -s src/claimos/static/app.css
```
(Place this after `COPY . .`; `curl` is needed to fetch the binary. `app.css` is gitignored, so it must be built here — it is not copied in.)

- [ ] **Step 2: Verify the image builds and contains app.css**

Run:
```bash
docker build -t claimos-csstest . \
  && docker run --rm claimos-csstest test -s src/claimos/static/app.css \
  && echo "image contains built app.css"
```
Expected: build succeeds; prints "image contains built app.css". (If Docker is unavailable in the environment, record that and rely on CI Step 4.)

- [ ] **Step 3: Add a build-health step to CI**

In `.github/workflows/ci.yml`, add a new job after `test`:
```yaml
  css:
    name: css-build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Tailwind CSS
        run: |
          bash scripts/fetch-tailwind.sh
          bash scripts/build-css.sh --minify
          test -s src/claimos/static/app.css
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .github/workflows/ci.yml
git commit -m "ci: build app.css in Docker image and add CI build-health gate"
```

---

### Task 5: Docs — stack rule, commands, dev workflow

**Files:**
- Modify: `CLAUDE.md` (tech-stack line + Commands block)
- Modify: `README.md` (prereqs/dev workflow)

**Interfaces:** none (documentation).

- [ ] **Step 1: Update the CLAUDE.md tech-stack line**

In `CLAUDE.md`, change the Tailwind bullet from:
```
- **Tailwind via CDN** (no build step)
```
to:
```
- **Tailwind CSS v4**, compiled by the standalone CLI binary (no Node) to `src/claimos/static/app.css` (generated, gitignored). Source of truth: `src/claimos/styles/theme.css`.
```
And in the "Do not add" line, keep the no-npm/Node stance but remove any wording that forbids a build step (the standalone-CLI build is now approved).

- [ ] **Step 2: Add the CSS commands to the CLAUDE.md Commands block**

Add under the existing `uv run …` list:
```bash
bash scripts/fetch-tailwind.sh   # one-time: download the pinned Tailwind v4 binary
uv run css                       # build src/claimos/static/app.css once
uv run css --watch               # rebuild on template/theme changes (run alongside `uv run dev`)
```

- [ ] **Step 3: Update README dev workflow**

In `README.md`, in the local-dev section, document that styling now requires the CSS build: run `bash scripts/fetch-tailwind.sh` once, then run `uv run css --watch` in a second terminal alongside `uv run dev`. Note that `app.css` is generated and gitignored (not present on a fresh checkout until built).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: document Tailwind v4 standalone build (stack rule, commands, dev workflow)"
```

---

### Task 6: Parity + full verification

**Files:** none (verification only)

- [ ] **Step 1: Clean build the CSS**

Run: `source .venv/bin/activate && rm -f src/claimos/static/app.css && uv run css --minify && test -s src/claimos/static/app.css && echo built`
Expected: `built`.

- [ ] **Step 2: Confirm the built CSS contains the v4-renamed utilities (structural parity signal)**

Run:
```bash
cd /Users/cmondor/consulting/tor
for u in 'rounded-sm' 'shadow-xs' 'shadow-sm' 'outline-hidden' 'ring-3'; do
  grep -q "\.$u" src/claimos/static/app.css && echo "present: .$u" || echo "MISSING: .$u"
done
```
Expected: all "present" (each renamed utility actually compiled — i.e. the names are valid v4 utilities that templates use).

- [ ] **Step 3: App renders + serves CSS (no CDN anywhere)**

Run: `source .venv/bin/activate && uv run pytest -q`
Expected: all pass (includes `test_static_css.py` and the router render tests — templates render without error under the renamed utilities).

- [ ] **Step 4: No CDN references remain in the repo (templates or CSP)**

Run: `grep -rn "cdn.tailwindcss.com" src/claimos && echo "FOUND (bad)" || echo "none ✓"`
Expected: `none ✓`.

- [ ] **Step 5: Lint/format + color drift guard**

Run: `source .venv/bin/activate && uv run ruff format --check . && uv run ruff check . && python scripts/audit_design_tokens.py`
Expected: format clean, lint clean, `DESIGN.md token audit: clean ✓`.

- [ ] **Step 6: Manual smoke (optional but recommended)**

Run `uv run css` then `uv run dev`, open `http://localhost:8000`, and eyeball a dashboard, a form (login), and an admin page against the pre-change appearance. Confirm buttons, cards, borders, focus rings, and radii look unchanged.

---

## Self-Review

- **Spec coverage:** build pipeline (T1), v4 rename (T2), serve+CSP (T3), Docker+CI (T4), docs incl. CLAUDE.md stack rule (T5), parity/acceptance (T6). All Slice-1 spec bullets map to a task. Slices 2–3 are explicitly out of scope.
- **Placeholder scan:** none — every code/command step is concrete. The only deferred value is the exact Tailwind patch version, with an explicit confirm/pin step (version-pinning inherently requires checking the release).
- **Type/name consistency:** `build_command(watch, minify)`, `main()`, `BIN/INPUT/OUTPUT`, `scripts/build-css.sh`, `/static/app.css`, and the `css` entrypoint are used identically across T1/T3/T4/T6.
- **Parity honesty:** the plan does not claim pixel-diffing; parity rests on the deterministic rename map (pixel-identical by construction) plus build+render verification, matching the spec.
- **Risk note for executor:** if Step 2 of Task 6 shows a MISSING utility, a rename target was wrong — reconcile against the rename map before proceeding.
