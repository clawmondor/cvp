# Rebranding ClaimOS

How to produce a re-skinned version of the app's UI. Thanks to the 4-slice design-system
work (PRs #36–#38, #40), **the entire visual theme lives in one file:**

```
src/claimos/styles/theme.css
```

A rebrand edits that file — token *values* and, if desired, component-class definitions. You
do **not** touch templates or JS: they reference semantic tokens and component classes
(`bg-primary`, `text-neutral-500`, `.card`, `.btn-primary`, …), so changing a token's value
re-skins every usage automatically. The compiled output (`src/claimos/static/app.css`) is
generated and gitignored — never edited by hand.

> **Scope of a "rebrand" here:** the *visual theme* — colors (light **and** dark), the font,
> corner radii, and the look of the component atoms. Two things are **separate** and covered
> at the end: the **product name / wordmark** (in templates) and the **PDF report** styling
> (its own inline CSS).

---

## 0. One-time setup

```bash
brew install pango cairo libffi        # macOS system libs (if not already present)
uv sync                                 # Python deps
bash scripts/fetch-tailwind.sh          # download the pinned Tailwind v4 standalone binary
```

To see changes as you edit, run the CSS build in watch mode in one terminal and the app in
another:

```bash
uv run css --watch      # rebuilds src/claimos/static/app.css on save
uv run dev              # FastAPI on http://localhost:8000
```

`app.css` is gitignored and generated — if styles look missing on a fresh checkout, you just
haven't built it yet (`uv run css`).

---

## 1. The mental model

`theme.css` has three editable regions:

| Region | What it controls | Rebrand action |
|---|---|---|
| `@theme { --color-* }` | the color palette (every token, **light + dark**) | change the hex values |
| `@theme { --font-sans, --radius-* }` | the font family and corner-radius scale | change the values |
| `@layer components { … }` | the *look* of `.card` / `.input` / `.btn-*` / `.badge-*` | change the `@apply` recipes |

**You change values, not names.** Token names (`--color-primary`, `--color-neutral-500`, …)
are referenced throughout templates/JS. Renaming one would break usages and is guarded
against (see §6). A rebrand only changes what those names *resolve to*.

---

## 2. Colors — every token needs a light AND a dark value

Each color token is a CSS `light-dark(<light>, <dark>)` value. `color-scheme` (set from the
`theme` cookie / OS) picks which half renders. **When you rebrand, supply both** — a token
with only a light value will look wrong in dark mode.

```css
/* before */
--color-primary: light-dark(#4f46e5, #818cf8);
/* after — a teal rebrand */
--color-primary: light-dark(#0d9488, #2dd4bf);
```

### The token groups (edit values only)

- **Accent** — `primary`, `primary-light`, `primary-strong`, `primary-subtle`, `primary-tint`,
  `primary-tint-strong`. `primary` is the single interaction color (buttons, links, active).
  The `-light`/`-strong` are lightness steps (hover/active/border); `-subtle`/`-tint*` are
  tinted backgrounds.
- **Neutral ramp** — `neutral-50 … neutral-900`. Used *role-by-position*: low = surfaces/fills,
  high = text, mids = borders. In dark mode the dark values are inverted-and-tuned (low→dark
  surfaces, high→light text). Keep that ordering when you re-tune.
- **Status** — `success*`, `error*`, `warning*` (each: `-surface`, `-surface-strong`, `-border`,
  `-emphasis`, base, `-strong`). Both the tint background and the text flip together, so badges
  stay legible in both modes automatically.
- **Surface** — `surface` (card/panel background; white in light).

### Mode-independent tokens (single value, NOT `light-dark()`)

- `--color-white` (`#ffffff`) and `--color-black` (`#000000`) — literal, used for e.g. white
  button text in both modes. Leave as single values.
- `--color-admin-300 … admin-800` — the **admin sidebar chrome**, which is a dark slate in
  *both* modes today. If your rebrand wants the admin chrome to also switch with dark mode,
  convert these to `light-dark(<light>, <dark>)` like the others.

### Do a proper dark pass, don't just invert

Dark is not a mathematical negative of light. Pick a dark `surface` that isn't pure black,
soften text (not pure white), and lighten accents/status for contrast on dark. A quick
**WCAG contrast check** on the result is strongly recommended (this pass was explicitly left
as a follow-up on the reference palette).

---

## 3. Typography & radii

```css
--font-sans: ui-sans-serif, system-ui, sans-serif;   /* -> your brand font stack */
--radius-sm: 0.25rem;   /* rounded-sm  */
--radius-md: 0.375rem;  /* rounded-md  */
--radius-lg: 0.5rem;    /* rounded-lg  */
```

- **Font:** change `--font-sans` to your brand stack. If it's a *web font* (not a system font),
  you must also load it — add a `<link>` in the shell templates' `<head>`
  (`src/claimos/templates/base.html` and the other shells) and **add the host to the CSP**
  `style-src`/`font-src` in `src/claimos/middleware.py`, or self-host it under `static/`.
  Templates keep using `font-sans` — only the value and the font source change.
- **Radii:** change the `--radius-*` values to make the whole UI more or less rounded
  (buttons, inputs, cards all use these). Templates keep `rounded-sm`/`-md`/`-lg`.

---

## 4. Component look (optional)

To change *how a component looks* beyond raw color/radius — e.g. make buttons pill-shaped or
give cards a border instead of a shadow — edit the `@layer components` recipes:

```css
.card {
  @apply bg-surface shadow-sm rounded-lg;      /* -> e.g. border border-neutral-200 rounded-xl */
}
.btn-primary {
  @apply bg-primary text-white font-semibold shadow-xs hover:bg-primary-light;  /* -> rounded-full … */
}
```

The `@apply` recipe may only use tokens/utilities that exist. Existing classes: `.card`,
`.input`, `.btn-primary`, `.btn-secondary`, `.badge-success`, `.badge-error`, `.badge-warning`.
Not every button/badge in the app uses these classes (some are still inline utilities by
design) — component-look changes reach only the elements that use the class.

---

## 5. Step-by-step: create a rebranded version

```bash
# 1. start from a clean, up-to-date main
git checkout main && git pull

# 2. branch per rebrand candidate (this is what makes A/B review easy)
git checkout -b rebrand-teal

# 3. edit the values in src/claimos/styles/theme.css  (colors light+dark, font, radii, components)

# 4. build + preview
uv run css --watch     # terminal 1
uv run dev             # terminal 2  -> http://localhost:8000
#    use the System / Light / Dark toggle in the nav to check BOTH modes

# 5. update the light-parity test to your new light values (see §6, required or tests fail)

# 6. verify (see §7), commit, push, open a PR for review
git add src/claimos/styles/theme.css tests/test_theme_tokens.py
git commit -m "rebrand: teal theme"
```

**Side-by-side comparison:** make each candidate its own branch off `main`
(`rebrand-teal`, `rebrand-navy`, …), each changing essentially just `theme.css`. Reviewers
compare one-file diffs, or check out each branch and eyeball it. (A build-time
`app.<theme>.css` + env selector — switching themes without branches — is a possible future
enhancement, not built today.)

---

## 6. Required: update the light-parity test

`tests/test_theme_tokens.py` asserts each token's **light** value equals a frozen `EXPECTED`
hex. That test exists to catch *accidental* light-mode drift during development — but a
**rebrand changes light values on purpose**, so the test *will* fail until you update it.

Update the `EXPECTED` dict in `tests/test_theme_tokens.py` to your new light hexes (this makes
the change explicit and reviewable). The other design-system checks stay valid and should keep
passing without edits:

- `tests/test_dark_mode_tokens.py` — every color token is `light-dark()` (except white/black/
  admin-*). Keep it green: if you add a color token, give it both values.
- `scripts/audit_design_tokens.py` — forbids raw Tailwind families (`bg-indigo-600`, …) in
  templates/JS. You're changing values, not adding raw utilities, so this stays clean.

---

## 7. Verify checklist

```bash
source .venv/bin/activate
uv run css                                   # builds cleanly (bad token/@apply => build error)
python scripts/audit_design_tokens.py        # design token guard: clean
uv run pytest -q                             # all tests pass (incl. your updated EXPECTED)
uv run ruff format --check . && uv run ruff check .
```

Then **eyeball both modes**: `uv run dev`, open representative pages (dashboard, a form, an
admin page), and use the nav **System / Light / Dark** toggle to confirm light and dark both
look right. Open a **report preview** — it must stay **light** regardless of the toggle.

---

## 8. Out of scope of `theme.css` (separate changes)

- **Product name / wordmark.** The literal text "ClaimOS" and any tagline live in the
  templates (e.g. `src/claimos/templates/base.html`, `splash.html`) and in
  `src/claimos/config.py` (`openrouter_app_title`). Renaming the product is a template/config
  edit, independent of the visual theme. Legal/vocabulary rules in `CLAUDE.md` still apply.
- **The PDF report.** `src/claimos/templates/report/pdf.html` is rendered by WeasyPrint with
  its **own inline CSS** (Arial + Courier, print-specific grays) — it does **not** use
  `theme.css` and is intentionally always light (attorney work product). To restyle the
  report, edit `pdf.html` directly. The report *preview* (`report/preview.html`) is forced
  light to match.
- **Layout / structure.** `theme.css` changes look, not layout. Moving elements or changing
  page structure is template work.

---

## Reference: the current default palette

The shipped values are the source of truth in `src/claimos/styles/theme.css`. Human-readable
token documentation (names + roles) is in `DESIGN.md`. Start a rebrand by copying the
`@theme` block and changing values.
