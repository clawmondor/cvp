# Design Token Drift Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate color/type token drift between the Jinja templates and `DESIGN.md`, and add a committed guard script that fails on future drift.

**Architecture:** Three moves. (1) Add `scripts/audit_design_tokens.py` — derives the allowed token set from `DESIGN.md`'s YAML front matter and exits non-zero if any template uses an off-token color/type utility. (2) Expand `DESIGN.md`'s token ramps to the curated set below. (3) Apply a deterministic class-substitution map across the templates so every color utility resolves to a documented token. The audit script is the executable check that gates each step.

**Tech Stack:** Python 3.11 (stdlib `re`/`glob` + `pyyaml`, already a transitive dep), Tailwind-via-CDN utility classes in Jinja HTML. No new dependencies.

## Global Constraints

- **Descriptive, not a rebrand.** This conforms templates to the existing palette; it does not introduce a new visual direction. The deferred rebrand slice is out of scope (CLAUDE.md).
- **Only class/token substitution.** Do not restructure markup, move elements, or change any non-color/non-type class. No functional or layout changes.
- **No inline JS.** Do not add `onclick=`/`onchange=` etc. (CSP blocks them). This refactor touches only `class="..."` attributes, so no JS changes are expected.
- **Print report is a separate context.** `templates/report/pdf.html` uses inline `<style>` hex (`#6b7280`, Arial, Courier) — that is the documented print surface. Do NOT remap its inline hex. Only Tailwind `family-shade` utility classes are in scope.
- **Run `uv run ruff format .` then `uv run ruff format --check .` before committing** any `.py` file (the audit script). CI enforces format.
- **Python only via venv:** prefix every python/pip call with `source .venv/bin/activate &&` (or `~/.venvs/shared`).
- **Never commit to `main`.** Work happens on branch `refactor/design-token-drift`.

## Curated Token Set (target)

Every color utility must resolve to one of these family-shades after the refactor:

| Family | Role | Allowed shades |
|---|---|---|
| indigo | primary/accent | 50, 100, 200, 500, 600, 700 |
| gray | neutral | 50, 100, 200, 300, 400, 500, 600, 700, 900 |
| green | success | 50, 100, 200, 600, 700, 800 |
| red | error | 50, 100, 200, 600, 700, 800 |
| amber | warning | 50, 100, 200, 600, 700, 800 |
| slate | admin chrome | 300, 400, 600, 700, 800 |

## Substitution Map (old family-shade → new)

Off-system family folds + shade snapping. Entries not listed are already in-set and unchanged.

```
# violet/purple → primary (indigo)
violet-50→indigo-50   violet-100→indigo-100  violet-200→indigo-200
violet-300→indigo-200 violet-400→indigo-500  violet-500→indigo-500
violet-600→indigo-600 violet-700→indigo-700  violet-800→indigo-700
purple-50→indigo-50
# blue → primary (indigo)
blue-100→indigo-100   blue-600→indigo-600    blue-800→indigo-700
# indigo off-ramp shades → nearest token
indigo-400→indigo-500 indigo-800→indigo-700  indigo-900→indigo-700
# emerald → success (green)
emerald-50→green-50   emerald-300→green-200  emerald-500→green-600
emerald-600→green-600 emerald-700→green-700
green-500→green-600
# neutral
gray-800→gray-900
# error (red)
red-400→red-600       red-500→red-600
# warning: amber off-ramp + yellow fold → amber
amber-300→amber-200   amber-500→amber-600
yellow-100→amber-100  yellow-800→amber-800
```

Type: `text-4xl` and `text-xl` are the only off-scale sizes (9 total uses). They are legitimate heading sizes, so they are **added to the DESIGN.md type scale** (`display` = text-4xl, `title-lg` = text-xl) rather than remapped — no template edits for type.

## File Structure

- Create: `scripts/audit_design_tokens.py` — drift guard (reads DESIGN.md, scans templates, exits 1 on drift). ~90 lines, single responsibility.
- Modify: `DESIGN.md` — front matter color ramps + two type levels; prose in Colors/Typography/Do's & Don'ts to match.
- Modify: ~30 files under `src/claimos/templates/**/*.html` — via the substitution map (mechanical).

---

### Task 1: Add the drift-audit guard script

**Files:**
- Create: `scripts/audit_design_tokens.py`

**Interfaces:**
- Produces: CLI `python scripts/audit_design_tokens.py` → prints drift table, exit 0 if clean else 1. Later tasks run it as the gate.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Fail if any Jinja template uses a color/type utility not in DESIGN.md's tokens."""
from __future__ import annotations
import glob, re, sys, collections
import yaml

TEMPLATES = "src/claimos/templates/**/*.html"

# Minimal Tailwind v3 default palette for the families we use (hex -> lookup).
TW = {
 "indigo": {50:"#eef2ff",100:"#e0e7ff",200:"#c7d2fe",400:"#818cf8",500:"#6366f1",600:"#4f46e5",700:"#4338ca",800:"#3730a3",900:"#312e81"},
 "gray":   {50:"#f9fafb",100:"#f3f4f6",200:"#e5e7eb",300:"#d1d5db",400:"#9ca3af",500:"#6b7280",600:"#4b5563",700:"#374151",800:"#1f2937",900:"#111827"},
 "green":  {50:"#f0fdf4",100:"#dcfce7",200:"#bbf7d0",500:"#22c55e",600:"#16a34a",700:"#15803d",800:"#166534"},
 "red":    {50:"#fef2f2",100:"#fee2e2",200:"#fecaca",400:"#f87171",500:"#ef4444",600:"#dc2626",700:"#b91c1c",800:"#991b1b"},
 "amber":  {50:"#fffbeb",100:"#fef3c7",200:"#fde68a",300:"#fcd34d",500:"#f59e0b",600:"#d97706",700:"#b45309",800:"#92400e"},
 "slate":  {300:"#cbd5e1",400:"#94a3b8",600:"#475569",700:"#334155",800:"#1e293b",900:"#0f172a"},
 "emerald":{50:"#ecfdf5",300:"#6ee7b7",500:"#10b981",600:"#059669",700:"#047857"},
 "yellow": {100:"#fef9c3",800:"#854d0e"},
 "blue":   {100:"#dbeafe",600:"#2563eb",800:"#1e40af"},
 "violet": {50:"#f5f3ff",100:"#ede9fe",200:"#ddd6fe",300:"#c4b5fd",400:"#a78bfa",500:"#8b5cf6",600:"#7c3aed",700:"#6d28d9",800:"#5b21b6"},
 "purple": {50:"#faf5ff"},
}
HEX2TW = {v.lower(): (fam, sh) for fam, d in TW.items() for sh, v in d.items()}

ALLOWED_TYPE = {"text-xs","text-sm","text-base","text-lg","text-xl","text-2xl","text-3xl","text-4xl"}

def allowed_colors() -> set[tuple[str, int]]:
    fm = open("DESIGN.md").read().split("---\n", 2)[1]
    data = yaml.safe_load(fm)
    out = set()
    for hexv in data["colors"].values():
        key = str(hexv).lower()
        if key in HEX2TW:
            out.add(HEX2TW[key])
    return out

def allowed_type() -> set[str]:
    fm = open("DESIGN.md").read().split("---\n", 2)[1]
    data = yaml.safe_load(fm)
    sizes = {int(str(v["fontSize"]).replace("px","")) for v in data["typography"].values()
             if str(v.get("fontSize","")).endswith("px")}
    px2tw = {12:"text-xs",14:"text-sm",16:"text-base",18:"text-lg",20:"text-xl",24:"text-2xl",30:"text-3xl",36:"text-4xl"}
    return {px2tw[s] for s in sizes if s in px2tw}

COLOR_RE = re.compile(r'(?:[a-z-]+:)*(?:bg|text|border|ring|divide|outline|from|to|via|fill|stroke|placeholder|decoration|accent)-(indigo|gray|slate|zinc|neutral|stone|red|rose|pink|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|violet|purple|fuchsia)-(\d{2,3})(?!\d)')
SIZE_RE  = re.compile(r'(?:[a-z-]+:)*(text-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl))(?=[\s"\'])')

def main() -> int:
    color_ok, type_ok = allowed_colors(), allowed_type()
    bad_color = collections.Counter(); bad_type = collections.Counter()
    files = collections.defaultdict(set)
    for fp in glob.glob(TEMPLATES, recursive=True):
        s = open(fp).read()
        short = fp.replace("src/claimos/templates/", "")
        for fam, sh in COLOR_RE.findall(s):
            if (fam, int(sh)) not in color_ok:
                k = f"{fam}-{sh}"; bad_color[k] += 1; files[k].add(short)
        for sz in SIZE_RE.findall(s):
            if sz not in type_ok:
                bad_type[sz] += 1
    if not bad_color and not bad_type:
        print("DESIGN.md token audit: clean ✓"); return 0
    print("DESIGN.md token DRIFT detected:\n")
    for k, c in bad_color.most_common():
        print(f"  color  {c:4d}  {k:16s} {', '.join(sorted(files[k])[:4])}")
    for k, c in bad_type.most_common():
        print(f"  type   {c:4d}  {k}")
    return 1

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it to confirm it FAILS on current drift**

Run: `source .venv/bin/activate && python scripts/audit_design_tokens.py; echo "exit=$?"`
Expected: prints a drift table (emerald/violet/blue/gray-700/… rows) and `exit=1`.

- [ ] **Step 3: Format + commit**

```bash
source .venv/bin/activate && uv run ruff format scripts/audit_design_tokens.py && uv run ruff format --check scripts/audit_design_tokens.py
git add scripts/audit_design_tokens.py
git commit -m "chore: add DESIGN.md token drift audit script"
```

---

### Task 2: Expand DESIGN.md token ramps to the curated set

**Files:**
- Modify: `DESIGN.md` (front-matter `colors` + `typography`; prose in Colors, Typography, Do's and Don'ts)

**Interfaces:**
- Consumes: allowed-set derivation in `scripts/audit_design_tokens.py` (Task 1) — every hex added here must map to a curated family-shade in that script's `TW` table.
- Produces: the documented token vocabulary Task 3's templates must resolve to.

- [ ] **Step 1: Add the missing color tokens to the `colors:` front matter**

Insert these keys (keep existing ones; these fill the curated ramps). Values are Tailwind hex:

```yaml
  # primary tints
  primary-tint: "#e0e7ff"        # indigo-100
  primary-tint-strong: "#c7d2fe" # indigo-200
  # neutral — add the missing body-text tier
  text-strong-alt: "#374151"     # gray-700 (secondary heading / dense body text)
  # success ramp
  success-surface-strong: "#dcfce7" # green-100
  success-border: "#bbf7d0"         # green-200
  success-strong: "#166534"         # green-800
  # error ramp
  error-surface-strong: "#fee2e2"   # red-100
  error-border: "#fecaca"           # red-200
  error-strong: "#b91c1c"           # red-700
  error-strongest: "#991b1b"        # red-800
  # warning ramp (amber; yellow is folded in)
  warning-surface: "#fffbeb"        # amber-50  (replaces prior yellow-100 value)
  warning-surface-strong: "#fef3c7" # amber-100
  warning-border: "#fde68a"         # amber-200
  warning-icon: "#d97706"           # amber-600
  warning-strong: "#92400e"         # amber-800
  # admin chrome extra steps
  admin-on-surface-dim: "#94a3b8"   # slate-400
  admin-surface-light: "#475569"    # slate-600
```

Also change the existing `warning-surface` line's value from `"#fef9c3"` (yellow-100) to be removed/replaced by the amber `warning-surface` above (no yellow tokens remain).

- [ ] **Step 2: Add two type levels to `typography:`**

```yaml
  display:
    fontFamily: ui-sans-serif, system-ui, sans-serif
    fontSize: 36px            # text-4xl — hero / marquee numbers
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: -0.02em
  title-lg:
    fontFamily: ui-sans-serif, system-ui, sans-serif
    fontSize: 20px            # text-xl — prominent section titles
    fontWeight: 600
    lineHeight: 1.3
```

- [ ] **Step 3: Update prose** — in `## Colors` note the full ramps (neutral now includes gray-700; warning is amber-based and absorbs the former yellow usages; no emerald/violet/blue). In `## Typography` mention `display`/`title-lg`. In `## Do's and Don'ts` keep "one accent hue (indigo)" and add a line: "Warning = amber (never yellow); success = green (never emerald); there is no separate info/blue or violet accent — those fold into primary."

- [ ] **Step 4: Validate the front matter still parses and references resolve**

Run:
```bash
source .venv/bin/activate && python - <<'PY'
import yaml
d = yaml.safe_load(open("DESIGN.md").read().split("---\n",2)[1])
print("colors:", len(d["colors"]), "typography:", len(d["typography"]))
PY
```
Expected: prints counts, no exception.

- [ ] **Step 5: Commit**

```bash
git add DESIGN.md
git commit -m "docs: expand DESIGN.md token ramps to curated set (neutral/success/error/warning), add display+title-lg type levels"
```

---

### Task 3: Apply the substitution map to templates

**Files:**
- Modify: `src/claimos/templates/**/*.html` (the ~30 files containing drift; the script is a no-op on the rest)

**Interfaces:**
- Consumes: the Substitution Map above; the curated tokens documented in Task 2.
- Produces: templates whose every color utility resolves to a Task-2 token.

- [ ] **Step 1: Write a one-shot substitution script to scratchpad**

Save to `/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad/remap.py`:

```python
import glob, re
MAP = {
 ("violet",50):("indigo",50),("violet",100):("indigo",100),("violet",200):("indigo",200),
 ("violet",300):("indigo",200),("violet",400):("indigo",500),("violet",500):("indigo",500),
 ("violet",600):("indigo",600),("violet",700):("indigo",700),("violet",800):("indigo",700),
 ("purple",50):("indigo",50),
 ("blue",100):("indigo",100),("blue",600):("indigo",600),("blue",800):("indigo",700),
 ("indigo",400):("indigo",500),("indigo",800):("indigo",700),("indigo",900):("indigo",700),
 ("emerald",50):("green",50),("emerald",300):("green",200),("emerald",500):("green",600),
 ("emerald",600):("green",600),("emerald",700):("green",700),("green",500):("green",600),
 ("gray",800):("gray",900),
 ("red",400):("red",600),("red",500):("red",600),
 ("amber",300):("amber",200),("amber",500):("amber",600),
 ("yellow",100):("amber",100),("yellow",800):("amber",800),
}
total = 0
for fp in glob.glob("src/claimos/templates/**/*.html", recursive=True):
    s = open(fp).read(); orig = s
    for (fam,sh),(nf,ns) in MAP.items():
        # match `family-shade` not followed by another digit, preceded by non-letter
        s = re.sub(rf'(?<![a-zA-Z]){fam}-{sh}(?!\d)', f'{nf}-{ns}', s)
    if s != orig:
        open(fp,"w").write(s); total += 1; print("rewrote", fp)
print("files changed:", total)
```

- [ ] **Step 2: Run it**

Run: `source .venv/bin/activate && python "/private/tmp/claude-501/-Users-cmondor-consulting-tor/a61dba6c-cc85-4f3f-acc7-4b6c694b7969/scratchpad/remap.py"`
Expected: lists ~30 rewritten files, `files changed: ~30`.

- [ ] **Step 3: Run the audit guard — must now PASS**

Run: `source .venv/bin/activate && python scripts/audit_design_tokens.py; echo "exit=$?"`
Expected: `DESIGN.md token audit: clean ✓` and `exit=0`.

- [ ] **Step 4: Sanity-check the diff is class-only**

Run: `git diff --stat && git diff -U0 | grep -E '^[+-]' | grep -viE 'indigo|gray|green|red|amber|slate' | grep -vE '^(\+\+\+|---)' | head`
Expected: the second grep prints nothing (every changed line only touches an in-family color class). If anything prints, inspect it before continuing.

- [ ] **Step 5: Commit**

```bash
git add src/claimos/templates
git commit -m "refactor(ui): conform template color tokens to DESIGN.md (fold emerald→success, violet/blue→primary, snap off-ramp shades)"
```

---

### Task 4: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Guard passes**

Run: `source .venv/bin/activate && python scripts/audit_design_tokens.py; echo "exit=$?"`
Expected: clean, `exit=0`.

- [ ] **Step 2: Test suite green**

Run: `source .venv/bin/activate && uv run pytest -q`
Expected: all pass (templates render; no behavior changed).

- [ ] **Step 3: Lint/format clean**

Run: `source .venv/bin/activate && uv run ruff format --check . && uv run ruff check .`
Expected: no reformatting needed, no lint errors.

- [ ] **Step 4: Confirm no stray off-system families remain**

Run: `grep -roE '(bg|text|border|ring)-(emerald|violet|purple|blue|yellow|zinc|neutral|stone|rose|pink|orange|lime|teal|cyan|sky|fuchsia)-[0-9]+' src/claimos/templates | sort -u`
Expected: no output.

- [ ] **Step 5: Confirm the print report was untouched**

Run: `git diff main --stat -- src/claimos/templates/report/pdf.html`
Expected: no output (pdf.html unchanged — its inline hex is the documented print context).

---

## Self-Review

- **Spec coverage:** emerald/violet/blue folds ✓ (Map + Task 3), gray-700 & off-ramp shades ✓ (Task 2 tokens + Map), type sizes ✓ (Task 2 levels), guard ✓ (Task 1), verification ✓ (Task 4).
- **Placeholders:** none — every step has concrete code/commands.
- **Type consistency:** the audit script's `TW` hex table (Task 1) and the DESIGN.md hex values (Task 2) use the same Tailwind v3 defaults; the substitution `MAP` (Task 3) targets only shades present in the curated set.
- **Scope:** single subsystem (UI tokens), one plan. Print-report inline hex explicitly excluded.
