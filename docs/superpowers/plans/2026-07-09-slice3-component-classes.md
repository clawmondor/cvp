# Slice 3 — Component Classes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the stable core of the recurring UI atoms into `@layer components` classes in `theme.css` and migrate the exact-core-match template instances onto them, at strict visual parity.

**Architecture:** Add 7 component classes (`@apply` from Slice-2 tokens) to `theme.css`. Migrate templates with a per-instance **set-membership** script: an element is migrated only if its class list contains a component's exact core set; that core is replaced by the component class, other classes stay inline; divergent instances are left untouched. Parity is guaranteed by construction (component class ≡ the removed core) and verified by a re-expansion multiset check.

**Tech Stack:** Tailwind v4 `@layer components` + `@apply`, Jinja templates, standalone-CLI build, `uv`/pytest.

## Global Constraints

- **Parity:** migrating an instance must not change its computed styles. A component class `@apply`s exactly the core it replaces; only exact-core-match instances are migrated; **never normalize** divergent instances.
- **Core-only** in each class (color/font/radius/shadow/focus); size/padding/width/margin/layout stay inline — EXCEPT `.input`, which includes its uniform padding.
- **Skip dynamic class attrs:** if a `class="…"` contains `{%` or `{{` (Jinja), do not migrate it.
- **`.btn-secondary` is element-scoped:** only migrate its core inside `<a>` or `<button>` opening tags.
- **Templates only.** Do NOT migrate `app.js`/`crop-editor.js` (JS component extraction is out of scope; the raw-family guard keeps JS token-clean).
- Python via venv (`source .venv/bin/activate &&`). Run `uv run ruff format .` → `ruff format --check .` → `ruff check .` before committing any `.py`.
- `app.css`/`bin/` stay gitignored. `report/pdf.html` untouched. No inline JS handlers.
- Branch `feat/design-components-slice3`; never `main`.

## Component set + exact core tokens

```
card           : bg-surface shadow-sm rounded-lg
input          : block rounded-md border border-neutral-300 px-3 py-2 text-sm shadow-xs
                 focus:border-primary-light focus:outline-hidden focus:ring-1 focus:ring-primary-light
btn-primary    : bg-primary text-white font-semibold shadow-sm hover:bg-primary-light
btn-secondary  : text-neutral-500 hover:text-neutral-700          (element-scoped: <a>,<button>)
badge-success  : inline-flex items-center rounded-full bg-success-surface-strong px-2 py-0.5 text-xs font-medium text-success
badge-error    : inline-flex items-center rounded-full bg-error-surface-strong  px-2 py-0.5 text-xs font-medium text-error
badge-warning  : inline-flex items-center rounded-full bg-warning-surface-strong px-2 py-0.5 text-xs font-medium text-warning
```

---

### Task 1: Add the `@layer components` classes + emit test

**Files:**
- Modify: `src/claimos/styles/theme.css`
- Test: `tests/test_component_classes.py`

**Interfaces:**
- Produces: component selectors `.card`, `.input`, `.btn-primary`, `.btn-secondary`, `.badge-success`, `.badge-error`, `.badge-warning` emitted into `app.css`.

- [ ] **Step 1: Write the failing emit test**

Create `tests/test_component_classes.py`:
```python
import subprocess
from pathlib import Path

APP_CSS = Path("src/claimos/static/app.css")
SELECTORS = [
    ".card", ".input", ".btn-primary", ".btn-secondary",
    ".badge-success", ".badge-error", ".badge-warning",
]


def test_component_classes_emit_in_app_css():
    # ensure a fresh build, then confirm every component selector is present
    subprocess.run(["uv", "run", "css"], check=True)
    css = APP_CSS.read_text()
    missing = [s for s in SELECTORS if s + "{" not in css and s + " {" not in css and s + "," not in css]
    assert not missing, f"missing component selectors in app.css: {missing}"
```
NOTE: unused component classes still emit their rules in v4, so this test passes once the classes are defined even before any template uses them.

- [ ] **Step 2: Run it — expect failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_component_classes.py -q`
Expected: FAIL (selectors not defined).

- [ ] **Step 3: Add the `@layer components` block to `theme.css`**

Append after the existing `@layer base` block:
```css
@layer components {
  .card {
    @apply bg-surface shadow-sm rounded-lg;
  }
  .input {
    @apply block rounded-md border border-neutral-300 px-3 py-2 text-sm shadow-xs
           focus:border-primary-light focus:outline-hidden focus:ring-1 focus:ring-primary-light;
  }
  .btn-primary {
    @apply bg-primary text-white font-semibold shadow-sm hover:bg-primary-light;
  }
  .btn-secondary {
    @apply text-neutral-500 hover:text-neutral-700;
  }
  .badge-success {
    @apply inline-flex items-center rounded-full bg-success-surface-strong px-2 py-0.5 text-xs font-medium text-success;
  }
  .badge-error {
    @apply inline-flex items-center rounded-full bg-error-surface-strong px-2 py-0.5 text-xs font-medium text-error;
  }
  .badge-warning {
    @apply inline-flex items-center rounded-full bg-warning-surface-strong px-2 py-0.5 text-xs font-medium text-warning;
  }
}
```

- [ ] **Step 4: Run test + full suite**

Run: `source .venv/bin/activate && uv run pytest tests/test_component_classes.py -q && uv run pytest -q 2>&1 | tail -1`
Expected: component test passes; full suite passes (nothing references the classes yet → no visual change).

- [ ] **Step 5: Format + commit**

```bash
source .venv/bin/activate && uv run ruff format tests/test_component_classes.py && uv run ruff format --check tests/test_component_classes.py
git add src/claimos/styles/theme.css tests/test_component_classes.py
git commit -m "feat(css): add @layer components classes (card/input/btn/badge)"
```

---

### Task 2: Write the migration script + migrate `.card` and `.input`

**Files:**
- Modify: `src/claimos/templates/**/*.html` (card + input matches)

**Interfaces:**
- Produces: the reusable migration script at the scratchpad path (used again in Task 3) and migrated card/input instances.

- [ ] **Step 1: Write the migration script to scratchpad**

Save to `/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad/comp_migrate.py`:
```python
import glob, re, sys

COMPONENTS = {
    "card": {"core": {"bg-surface", "shadow-sm", "rounded-lg"}},
    "input": {"core": {
        "block", "rounded-md", "border", "border-neutral-300", "px-3", "py-2", "text-sm",
        "shadow-xs", "focus:border-primary-light", "focus:outline-hidden",
        "focus:ring-1", "focus:ring-primary-light",
    }},
    "btn-primary": {"core": {
        "bg-primary", "text-white", "font-semibold", "shadow-sm", "hover:bg-primary-light",
    }},
    "btn-secondary": {"core": {"text-neutral-500", "hover:text-neutral-700"},
                      "elements": ("a", "button")},
    "badge-success": {"core": {
        "inline-flex", "items-center", "rounded-full", "bg-success-surface-strong",
        "px-2", "py-0.5", "text-xs", "font-medium", "text-success"}},
    "badge-error": {"core": {
        "inline-flex", "items-center", "rounded-full", "bg-error-surface-strong",
        "px-2", "py-0.5", "text-xs", "font-medium", "text-error"}},
    "badge-warning": {"core": {
        "inline-flex", "items-center", "rounded-full", "bg-warning-surface-strong",
        "px-2", "py-0.5", "text-xs", "font-medium", "text-warning"}},
}


def _apply(cls: str, names: list[str]) -> str:
    if "{%" in cls or "{{" in cls:  # dynamic Jinja class attr — skip
        return cls
    toks = cls.split()
    for name in names:
        core = COMPONENTS[name]["core"]
        tokset = set(toks)
        if name in tokset or not core <= tokset:
            continue
        toks = [name] + [t for t in toks if t not in core]
    return " ".join(toks)


def migrate(text: str, names: list[str]) -> str:
    globals_ = [n for n in names if "elements" not in COMPONENTS[n]]
    scoped = [n for n in names if "elements" in COMPONENTS[n]]
    if globals_:
        text = re.sub(r'class="([^"]*)"',
                      lambda m: 'class="' + _apply(m.group(1), globals_) + '"', text)
    for name in scoped:
        els = "|".join(COMPONENTS[name]["elements"])
        text = re.sub(rf'(<(?:{els})\b[^>]*?class=")([^"]*)("[^>]*>)',
                      lambda m: m.group(1) + _apply(m.group(2), [name]) + m.group(3),
                      text, flags=re.DOTALL)
    return text


def main() -> None:
    names = sys.argv[1].split(",")  # e.g. "card,input"
    total = 0
    for fp in glob.glob("src/claimos/templates/**/*.html", recursive=True):
        s = open(fp).read()
        out = migrate(s, names)
        if out != s:
            open(fp, "w").write(out)
            total += 1
            print("migrated", fp)
    print("files changed:", total)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it for card + input**

Run: `source .venv/bin/activate && python "/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad/comp_migrate.py" card,input`
Expected: lists migrated files; `files changed: N` (N ≈ 20–40).

- [ ] **Step 3: Verify card/input classes now used; build + suite**

Run:
```bash
source .venv/bin/activate
grep -rl '"card\| card\|"input\| input' src/claimos/templates | head
uv run css && uv run pytest -q 2>&1 | tail -1
```
Expected: files reference `card`/`input`; build ok; full suite passes.

- [ ] **Step 4: Parity re-expansion check vs the pre-migration commit**

Run:
```bash
source .venv/bin/activate
python - <<'PY'
import glob, re, subprocess, sys
from collections import Counter
sys.path.insert(0, "/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad")
from comp_migrate import COMPONENTS
# Migration is UNCOMMITTED here, so HEAD is Task 1's commit (the pre-migration baseline).
EXP = {n: sorted(s["core"]) for n, s in COMPONENTS.items()}
def multiset(text):
    c = Counter()
    for m in re.finditer(r'class="([^"]*)"', text):
        for t in m.group(1).split():
            c.update(EXP.get(t, [t]))
    return c
bad = []
for fp in glob.glob("src/claimos/templates/**/*.html", recursive=True):
    cur = open(fp).read()
    orig = subprocess.run(["git", "show", f"HEAD:{fp}"], capture_output=True, text=True).stdout
    if not orig:
        continue
    if multiset(cur) != multiset(orig):
        bad.append(fp)
print("PARITY MISMATCH files:", bad or "NONE — expanded class-token multisets identical ✓")
PY
```
Expected: `NONE — expanded class-token multisets identical ✓`. (Compares HEAD — Task 1's commit — to the uncommitted working tree; expanding component names back to their cores must reproduce the original token multiset exactly.)

- [ ] **Step 5: Commit**

```bash
git add src/claimos/templates
git commit -m "refactor(ui): migrate card + input instances to component classes"
```

---

### Task 3: Migrate `.btn-primary`, `.badge-*`, `.btn-secondary`

**Files:**
- Modify: `src/claimos/templates/**/*.html` (button + badge matches)

**Interfaces:**
- Consumes: the migration script from Task 2 (same scratchpad path).

- [ ] **Step 1: Run the migration for buttons + badges**

Run:
```bash
source .venv/bin/activate
python "/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad/comp_migrate.py" btn-primary,badge-success,badge-error,badge-warning,btn-secondary
```
Expected: lists migrated files; `files changed: N` (partial coverage expected — fragmented atoms).

- [ ] **Step 2: Confirm divergent instances were NOT migrated (spot-check)**

Run:
```bash
cd /Users/cmondor/consulting/tor
echo "buttons still inline (e.g. hover:bg-primary-strong variants) — expected to remain:"
grep -rl 'hover:bg-primary-strong' src/claimos/templates | head
echo "btn-secondary only on a/button (no <summary> migrated):"
grep -rn 'class="[^"]*btn-secondary' src/claimos/templates | grep -iE '<summary' && echo "LEAK: summary migrated (bad)" || echo "no summary migrated ✓"
```
Expected: divergent buttons still present inline; no `<summary>` got `btn-secondary`.

- [ ] **Step 3: Build + suite + parity re-expansion (this task's commit vs pre-task)**

Run:
```bash
source .venv/bin/activate
uv run css && uv run pytest -q 2>&1 | tail -1
python - <<'PY'
import glob, re, subprocess, sys
sys.path.insert(0,"/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad")
from comp_migrate import COMPONENTS
from collections import Counter
EXP={n:sorted(s["core"]) for n,s in COMPONENTS.items()}
def ms(text):
    c=Counter()
    for m in re.finditer(r'class="([^"]*)"',text):
        for t in m.group(1).split(): c.update(EXP.get(t,[t]))
    return c
bad=[fp for fp in glob.glob("src/claimos/templates/**/*.html",recursive=True)
     if ms(open(fp).read())!=ms(subprocess.run(["git","show",f"HEAD:{fp}"],capture_output=True,text=True).stdout)]
print("PARITY MISMATCH vs HEAD(pre-task):", bad or "NONE ✓")
PY
```
Expected: full suite passes; `PARITY MISMATCH vs HEAD(pre-task): NONE ✓` (HEAD here = Task 2's commit, before this task's edits — run this BEFORE committing Step 4 so `HEAD` is the pre-task state).

- [ ] **Step 4: Commit**

```bash
git add src/claimos/templates
git commit -m "refactor(ui): migrate btn-primary/btn-secondary/badge instances to component classes"
```

---

### Task 4: Full verification + docs

**Files:**
- Modify: `DESIGN.md` (note component classes are now real, backed by `@layer components`)

- [ ] **Step 1: Guard + full suite + lint**

Run:
```bash
source .venv/bin/activate
python scripts/audit_design_tokens.py
uv run pytest -q 2>&1 | tail -1
uv run ruff format --check . && uv run ruff check .
```
Expected: guard `clean ✓`; all tests pass; ruff clean. (The raw-family guard is unaffected — component classes contain tokens internally, templates still use tokens + component classes + layout utilities.)

- [ ] **Step 2: Whole-slice parity check vs the branch base**

Run:
```bash
source .venv/bin/activate
python - <<'PY'
import glob, re, subprocess, sys
sys.path.insert(0,"/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad")
from comp_migrate import COMPONENTS
from collections import Counter
base=subprocess.run(["git","merge-base","main","HEAD"],capture_output=True,text=True).stdout.strip()
EXP={n:sorted(s["core"]) for n,s in COMPONENTS.items()}
def ms(text):
    c=Counter()
    for m in re.finditer(r'class="([^"]*)"',text):
        for t in m.group(1).split(): c.update(EXP.get(t,[t]))
    return c
bad=[fp for fp in glob.glob("src/claimos/templates/**/*.html",recursive=True)
     if ms(open(fp).read())!=ms(subprocess.run(["git","show",f"{base}:{fp}"],capture_output=True,text=True).stdout)]
print("WHOLE-SLICE PARITY vs base:", bad or "NONE — every template's effective utility set is unchanged ✓")
PY
```
Expected: `NONE — every template's effective utility set is unchanged ✓`.

- [ ] **Step 3: Report coverage (informational)**

Run:
```bash
cd /Users/cmondor/consulting/tor
for c in card input btn-primary btn-secondary badge-success badge-error badge-warning; do
  printf "%-16s %s\n" "$c" "$(grep -roE "class=\"[^\"]*\\b$c\\b" src/claimos/templates | wc -l | tr -d ' ')"
done
```
Expected: nonzero counts for card/input; partial for buttons/badges (informational — no assertion).

- [ ] **Step 4: DESIGN.md note**

In `DESIGN.md`'s `## Components` prose, add one line noting these atoms are now backed by real classes in `theme.css` `@layer components` (`.card`, `.input`, `.btn-primary`, `.btn-secondary`, `.badge-*`), composed from the color tokens; size/layout stays inline; divergent instances remain on inline utilities by design. Do not alter other sections.

- [ ] **Step 5: Commit**

```bash
source .venv/bin/activate && uv run ruff format --check .   # no-op for md, sanity
git add DESIGN.md
git commit -m "docs: note component classes are backed by @layer components"
```

---

## Self-Review

- **Spec coverage:** component classes (T1), card/input migration (T2), btn/badge migration incl. element-scoped btn-secondary (T3), guard+parity+docs (T4). All spec sections mapped.
- **Placeholder scan:** none — the migration script and component config are given in full; parity checks are concrete.
- **Consistency:** the `COMPONENTS` config (T2 script) is the single source for cores; the parity re-expansion (T2/T3/T4) imports it, so cores can't drift between migration and verification. Component `@apply` sets (T1) list the same tokens as the config cores.
- **Parity honesty:** parity is guaranteed by construction (exact-core-match swap) and verified by class-token multiset equality (expanding component names to cores) at each migration and whole-slice. Partial coverage on fragmented atoms is expected, not a failure.
- **Skip/scoping rules:** dynamic Jinja attrs skipped; btn-secondary scoped to `<a>`/`<button>`; JS untouched — all enforced in the script.
