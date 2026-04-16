I have what I need. Let me build both files. The PRD will be thorough (it's the build spec Claude Code reads), while CLAUDE.md will be lean (it loads into every session, so only high-signal rules).Both files ready. Two things worth explaining since they shape how your engineering co-founder will use them.

**The stack I chose and why.** Python 3.11 + FastAPI + SQLite + Jinja + HTMX + WeasyPrint. Not glamorous, but it's the fastest path from "DevOps engineer" to "working internal tool." No build pipeline, no SPA, no Docker, no cloud. One laptop, one database file, one `uv run dev` command. The Anthropic Python SDK is the only cloud dependency. Your co-founder can clone the repo and be running in under 5 minutes. If he'd rather use Node/Next.js because that's more familiar from Yahoo, that's a reasonable swap — but I'd push back gently, because PDF generation in Python (WeasyPrint + Jinja) is genuinely nicer than the Node equivalents and you'll spend a lot of time on that.

**Why the CLAUDE.md is short and the PRD is long.** CLAUDE.md loads into every Claude Code session, so every byte is context budget you're spending on every single prompt. The rule of thumb is: put "things Claude must never forget" in CLAUDE.md, and "things Claude needs to look up when building a specific feature" in `@docs/PRD.md`. The immutable domain rules (currency as cents, audit trail required, no contingency pricing, UPPA-safe language) are in CLAUDE.md because getting any of those wrong is a disaster. The API surface and data model and build phases are in the PRD because they're reference material — Claude Code pulls them in when working on the relevant feature.

**The build phases in PRD section 15 are the important bit.** They're strictly ordered. Phase 1 is skeleton + data model, Phase 5 is Vision integration, Phase 7 is PDF/CSV export. Each phase has its own acceptance test. Tell Claude Code "do phase 1" and it should produce something runnable before touching phase 2. This prevents the classic AI-coding failure mode of building half of every feature and nothing that works end-to-end.

## To start building

Your co-founder creates an empty directory, drops both files in (CLAUDE.md at the root, PRD.md under `docs/`), runs `claude` in that directory, and says:

> Read CLAUDE.md and docs/PRD.md. Then start on Phase 1 from PRD section 15. Stop when you've met the acceptance criteria for Phase 1 and I'll review before you start Phase 2.

That's the whole kickoff prompt. The rest is iteration.

One thing I didn't build but probably should exist: `docs/depreciation-schedule.md` (the full 42-category useful-life table) and `docs/data-model.md` (schema rationale). The PRD references them, and Phase 1's seed script needs the schedule file to exist. Want me to build those two supporting docs next, or sketch the first few cold-outreach email drafts for your sales co-founder's CA Bar list?

Both supporting docs are ready. Quick notes on what's in each and a couple of decisions worth flagging.

**`depreciation-schedule.md`** — the full 42-category table your seed script needs, plus the formula, condition multipliers, floor logic, and the exact edge cases `tests/test_depreciation.py` must cover (brand-new, past-useful-life, fractional ages, overrides, non-depreciable categories, tiny and huge RCVs). The useful-life values are deliberately conservative midpoints — they're defensible without being aggressive, which matters when a carrier challenges your numbers in appraisal. Three categories worth explaining because they might seem surprising:

- **Smartphones at 3 years** (category 23) — faster than IRS guidance, slower than market-price reality, matches what carriers accept.
- **Food and consumables at 1 year, 100% annual depreciation** (category 39) — this captures the "pantry after a fire" case; you'll get asked for it on every total-loss.
- **Children's clothing at 3 years** (category 3) — separate from adult clothing because kids outgrow things faster than they wear out, and specialists need a shorter life to avoid underpaying that subset.

**`data-model.md`** — full schema with rationale, ER diagram, SQLite PRAGMA configuration (including the trap about foreign keys being off by default), index plans, the ORM validation rules that enforce the audit-trail contract, migration policy, and an open-questions section. A few decisions I made that you should sanity-check before Phase 1:

1. **Rooms are per-matter, not global.** A free-text room list lets specialists handle "pool house," "wine cellar," "kids' reading nook" without schema changes. The downside is minor typo variance ("bedroom" vs "Bedroom"). Worth it.
2. **Categories are integer-IDed, read-only, seeded from the schedule doc.** I made the only exception to the UUID-primary-key rule for categories because integer IDs are more readable in logs and the set is fixed at 42.
3. **Stored totals, not computed on read.** `rcv_total_cents` and `acv_total_cents` are persisted, not recalculated every page load. This matters because if the depreciation formula ever changes, you need to know what the report said *at delivery time* — it's part of the audit trail, not a performance optimization.
4. **Exports snapshot their totals.** The `exports` table stores `rcv_total_cents` and `acv_total_cents` at generation time, so even if a specialist later edits items, you can prove what the PDF said when it was emailed.

## How the four files fit together

```
project-root/
├── CLAUDE.md                         ← loads every session (lean)
└── docs/
    ├── PRD.md                        ← @referenced by CLAUDE.md
    ├── data-model.md                 ← @referenced by PRD and CLAUDE.md
    └── depreciation-schedule.md      ← @referenced by PRD and CLAUDE.md
```

Your engineering co-founder creates the project directory, drops `CLAUDE.md` at the root, creates `docs/` and drops the other three in there, then runs `claude` and says:

> Read CLAUDE.md and docs/PRD.md. Start on Phase 1 from PRD section 15. Stop when Phase 1's acceptance criteria pass and I'll review before Phase 2.

Claude Code will ingest the CLAUDE.md (which loads forever into every session), lazy-load the PRD when it needs the build spec, and pull in `data-model.md` and `depreciation-schedule.md` when it's building the models and the seed script. Each doc is sized for the job it has to do: CLAUDE.md is ~200 lines (every-session budget), PRD is the full spec, and the two supporting docs are focused reference material.

One thing to decide before you start: **the name of the company on line 1 of every report**. The PRD and CLAUDE.md both use `[Your Company Name]` as a placeholder and `.env.example` has `COMPANY_NAME=Acme Contents Valuation LLC`. Once you pick a real name, grep the four files for placeholder strings and replace them. It's easier to do that on Day 0 than to find them all after the first report ships.

Ready for Phase 1. Want me to help draft the cold-outreach email sequence for the CA Bar list next, or sketch the first few `pyproject.toml` + `.env.example` + `alembic.ini` starter files so your co-founder has a head start when they boot up Claude Code?