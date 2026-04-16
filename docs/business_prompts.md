# Market Research: Personal Property Claim Documentation Services

## The problem space

When a homeowner or renter files a personal property claim after fire, theft, water damage, or a catastrophe, the insurer typically requires a line-item inventory with quantity, age, condition, original cost, replacement cost (RCV), and depreciated value (ACV). Most policies pay ACV upfront and release the depreciation holdback only after the policyholder actually replaces items and submits receipts. Reconstructing this list from memory after a total loss is brutal, and underdocumentation directly translates into smaller payouts — which is exactly why public adjusters exist and why homeowners working with public adjusters received payouts averaging $22,266 versus $18,659 for those handling claims themselves, roughly 20% higher.

## Competitive landscape

The market splits into four buckets:

**Pre-loss consumer inventory apps** — Encircle, Sortly, HomeZada, NAIC's free Know Your Stuff, Itemtopia, Under My Roof. Mostly $0–$35/year. Adoption is low because consumers don't maintain them. HomeZada now uses AI to turn photos into organized inventory data, identifying rooms and items with less manual work, which hints at where the category is heading.

**B2B contents valuation vendors working for carriers** — Hancock Claims, Claimplus, Exact Inventory, Enservio (Verisk). They send technicians to loss sites, use proprietary pricing databases, and bill the carrier. Hancock has 500+ field technicians on standby and uses connected tablets to upload inventory and pricing in real time from the field. This is the dominant professional channel — but they work *for* the insurer, not the claimant.

**Public adjusters** — licensed professionals who represent the policyholder and typically charge between 5% and 15% of recovery nationwide, with smaller claims often running 25–40% because there's a minimum amount of work regardless of claim size. They handle the whole claim, not just contents.

**Plaintiff-side attorneys / loss consultants** — used in disputed or bad-faith claims, billed hourly or on contingency.

The gap: there is no widely-used, software-first service that sits between the free inventory app and the 15% public adjuster, specifically for the contents/personal-property line of a claim that's already in progress, working *for* the policyholder or their attorney.

## Total addressable market

Building the TAM bottom-up from public data:

- The U.S. has roughly 70 million insured homes plus tens of millions of renters with HO-4 policies. In 2023, 5.3 percent of insured homes had a claim, and property damage including theft accounted for 97.3 percent of homeowners insurance claims. That's roughly **3.5–4 million property claims per year** in the U.S. alone.
- From 2019 to 2023 the average home insurance claim amount was $17,059, with property damage claims averaging $16,857 and fire/lightning claims averaging more than $88,000.
- Personal property (Coverage C) is typically 50–70% of dwelling coverage and is the most disputed line on contents-heavy losses (fire, theft, smoke, catastrophic water).
- Homeowners filed 18% more claims in 2023 than in 2019, and the trend is accelerating with climate-driven catastrophe frequency.

A reasonable TAM framing:

| Segment | Volume | Avg. revenue per claim | TAM |
|---|---|---|---|
| All U.S. property claims with a contents component | ~3.5M/yr | — | — |
| Serviceable: contents-heavy claims ($5K+ contents loss) | ~800K–1.2M/yr | $300–$1,500 SaaS/service fee | **$240M–$1.8B** |
| Serviceable obtainable (DIY-assist software, ~$150 avg.) | ~150K–300K/yr | $150 | **$22M–$45M** |
| Premium / done-for-you tier (public adjuster + attorney channel) | ~50K–100K/yr | $1,000–$3,000 | **$50M–$300M** |

The broader claims-adjusting industry it would draw share from is roughly $14.6 billion in the U.S., so even a 2–3% share is a $300–450M opportunity. Add Canada, UK, and Australia (similar policy structures) and you're looking at a $2–3B global TAM ceiling.

## Business model options

Five models worth considering, in rough order of capital intensity:

**1. Freemium SaaS to consumers, premium unlock at claim time.** Free pre-loss inventory app; when a claim is filed, the user pays $99–$299 to unlock RCV/ACV pricing, depreciation tables, photo-to-item AI recognition, and an insurer-formatted export (Xactimate-compatible CSV, Symbility, etc.). Conversion is the hard part — most users only think about it post-loss. Margins are excellent if you get distribution.

**2. Pay-per-claim, post-loss DIY tool.** $149–$499 flat fee, marketed through Google Ads on terms like "fire damage inventory list" and "insurance contents claim help." Higher willingness to pay because the user is in pain. This is the cleanest path to revenue and avoids the freemium retention problem.

**3. Done-for-you service with software leverage.** Hybrid of Hancock's model but consumer-facing. Customer uploads photos/videos of the loss site (or pre-loss footage); your team + AI produces a priced inventory in 5–10 days. Charge $500–$2,500 flat or 1–3% of contents recovery (well under the 10–15% public adjuster rate). Higher margin per customer but requires labor.

**4. B2B2C through public adjusters and attorneys.** White-label the platform to the ~5,000+ U.S. public adjusters and property-claim law firms. They already do this work in spreadsheets; sell them seats at $200–$500/month plus per-claim pricing data fees. Sticky, recurring, and you avoid consumer CAC. Probably the highest-quality revenue.

**5. Insurer-paid (B2B carrier channel).** Same software, sold to carriers as a self-service tool they offer policyholders to speed up claims. Hancock, Enservio, and Claimplus already own this channel and it's hard to break into without IICRC-certified field operations.

The most defensible play is probably a combination of (2) and (4): direct-to-consumer for awareness and SEO, with the real revenue coming from public adjusters and plaintiff attorneys who file dozens of claims a year. Note one regulatory wrinkle: in many states, charging a percentage of recovery may legally constitute "public adjusting" and require licensure. Flat-fee or SaaS subscription pricing avoids this; contingency pricing requires state-by-state licensing.

## Operating cost structure

For a software-first version (model 1, 2, or 4), assuming a small team building toward $2–5M ARR:

| Category | Year 1 | Year 2 | Notes |
|---|---|---|---|
| Engineering (3–5 FTE) | $450K–$900K | $700K–$1.4M | Founding team plus one ML engineer for photo recognition |
| Pricing data / catalog | $50K–$150K | $100K–$250K | License from a data provider, scrape retail catalogs, or build your own; this is the moat |
| Cloud / infra | $20K–$60K | $60K–$200K | Image storage is the main driver; budget S3 + GPU inference for vision models |
| Customer support / claim specialists | $80K–$200K | $250K–$600K | Even SaaS needs humans during a stressful claim |
| Sales & marketing (SEO, paid, BD to PAs) | $150K–$400K | $400K–$1.2M | Google Ads on claim-related terms is competitive but intent is high |
| Compliance, legal, licensing | $30K–$100K | $50K–$150K | Especially if you touch contingency fees |
| G&A, tools, insurance (E&O is essential) | $50K–$120K | $100K–$250K | E&O coverage is non-negotiable |
| **Total burn** | **$830K–$1.9M** | **$1.7M–$4M** | |

If you add a done-for-you service tier (model 3), add roughly $40K–$60K fully loaded per claim specialist, each able to handle 150–250 claims per year — meaning the unit economics work above ~$300 per claim with reasonable utilization.

The two cost items most founders underestimate: (1) the pricing/depreciation database — Verisk and Mitchell have spent decades building theirs, and matching their accuracy is a real engineering investment; (2) E&O insurance and state-by-state regulatory compliance, especially if you ever touch contingency-based pricing.

## What I'd validate next

Three questions would meaningfully sharpen this analysis: how many of those 3.5M annual claims actually involve a contested or labor-intensive contents inventory (vs. small wind/hail roof claims with little personal property), what public adjusters and plaintiff attorneys currently pay for contents valuation tooling, and how Verisk/Enservio's pricing API is licensed to third parties. Want me to dig into any of those — or sketch a financial model for a specific business model variant?

# Business Plan: Contents Valuation Platform for Public Adjusters & First-Party Property Attorneys

Before laying out the plan, a key signal in your founder description is worth pulling forward: your sales co-founder already has lawyers *actively asking* for a "human-based solution." That phrase changes the strategy. They aren't asking for an app — they're asking for a deliverable. The right wedge is therefore **service-first, productize-second**, not the other way around. I'll explain why below and build the plan around it.

## 1. Validation: what the market actually looks like

A few things I dug up that sharpen Option 4:

**The competing software is structural, not contents.** Xactimate (Verisk) and Symbility (CoreLogic) dominate, with around 75-80% of adjusters using Xactimate to estimate claim-related restoration work. But both tools are overwhelmingly built for *building/structural* estimates — drywall, flooring, framing, roofing — with cost databases updated monthly per region. They're weak on Coverage C personal property. Symbility's pricing data flows into CoreLogic's component-cost approach, and Xactimate's contents pricing is famously thin and out-of-date. This is the gap.

**There's an existing "estimate-as-a-service" precedent.** Companies like Assistimate and Estimate Claim Pros already sell done-for-you Xactimate/Symbility estimates to public adjusters and attorneys. Assistimate explicitly markets to construction consultants, public adjusters, and attorneys, offering to write estimates from exported ESX files including fair market costs for moving, cleaning, and storage of contents and other personal property items. This validates that the buyer exists, the channel works, and the willingness to pay for outsourced estimating is real. None of them appear to specialize in contents/personal property at scale — they bolt it on.

**The buyer universe is meaningful but bounded.** There are roughly 365,300 licensed adjusters across the United States as of 2024, but the vast majority are carrier-side staff and independent adjusters. The licensed *public* adjuster population is much smaller — industry sources put it at roughly 5,000–8,000 active practitioners across the ~46 licensing states, concentrated in Florida, Texas, New York, California, Louisiana, and the Northeast. Add to that an estimated 2,000–4,000 first-party property law firms and you're looking at a serviceable buyer pool of ~7,000–12,000 firms, of which perhaps 1,500–2,500 actively handle enough fire/theft/CAT contents losses to be real customers.

**The economics work in your favor.** Public adjusters typically charge 10-20% of the final settlement, and homeowners working with public adjusters received payouts averaging $22,266 versus $18,659 for those handling claims themselves — about 20% higher. A PA on a $100K contents claim is collecting $10K–$15K in fees. They will happily pay $500–$2,000 to a vendor that produces a defensible inventory faster and tighter than they can do themselves — and they'll happily pay a recurring SaaS fee on top once they trust the workflow.

## 2. Refined TAM/SAM/SOM for this channel

Sizing strictly the public-adjuster + plaintiff-attorney channel:

| Segment | Buyers | Avg. annual contracts | Wallet | Channel TAM |
|---|---|---|---|---|
| All US public adjusters + first-party property attorneys | ~12,000 firms | — | — | — |
| Active firms with meaningful contents-claim volume (SAM) | ~2,000 firms | ~30 contents-heavy claims/yr | ~$1,500/claim service + $500/mo SaaS | **~$120M/yr** |
| Year-3 obtainable share (SOM, 2-3% penetration) | ~50–80 firms | ~30 claims/yr each | $1,500/claim + SaaS | **~$3M–$5M ARR** |

That's not a venture-scale market on its own, but it's a profitable bootstrappable business that can be expanded later into adjacent channels (renters insurance carriers, restoration contractors, FEMA-related disaster claims, international markets with similar policy structures).

## 3. Strategic wedge: service-first, then product

Your sales co-founder's lawyers are telling you exactly what to build. They want **someone to do this for them today**, not a tool to do it themselves in 18 months. The right play:

**Phase 1 — Done-for-you service (months 0–9).** Two founders + 1–2 contractor "claim specialists" deliver itemized RCV/ACV reports as a service. Workflow: client uploads photos, videos, and any partial inventory the policyholder has → your team reconstructs the inventory in a structured spreadsheet → researches replacement pricing from current retail/wholesale sources → applies depreciation tables → delivers a PDF + Xactimate-compatible export. Charge $750–$2,500 per claim flat fee depending on item count. Leverage the warm lawyer leads to land 5–10 paying customers in the first 60 days.

**Phase 2 — Internal tooling (months 6–15).** Your engineering co-founder builds the workflow software your own team uses internally — a structured intake form, an item database with category-based pricing, a depreciation engine, photo-to-item AI-assisted classification, and an automated report generator. You're not selling this yet. You're using it to do 3x more reports per specialist, building proprietary pricing data from every report you produce, and learning the *exact* workflow.

**Phase 3 — SaaS layer (months 12–24).** Open the platform up to the firms that have been buying the service. Pricing: $299–$499/mo per seat (covers the platform + the pricing database) plus $99–$299 per claim for the AI-assisted report assembly. The done-for-you service stays available as a premium tier for overflow, complex claims, and customers who prefer to outsource entirely. This is the model Gusto, Pilot, and many vertical SaaS companies used: start as a service, productize the back office, then sell the back office as software.

Why this sequence works for you specifically:
- You have warm demand *now*. A pure-software path leaves that demand on the table for 12+ months.
- Service revenue funds the engineering build with no outside capital.
- The pricing database — the thing that's hardest to acquire and most defensible — gets built as a *byproduct* of doing the work.
- You discover the actual workflow from the customer's side rather than guessing.
- The early customers become the most credible reference accounts when SaaS launches; they've already trusted you with high-stakes claims.

## 4. The product, concretely

The Phase 2/3 product needs four things. None of them are individually hard, but the integration is the moat:

1. **Structured intake & evidence management.** Web + mobile capture for photos, videos, receipts, prior insurance docs, room-by-room walk-throughs. Designed for the policyholder to use under PA/attorney guidance during the most stressful moment of their life. UX bar: as simple as ordering an Uber.

2. **AI-assisted item identification.** Upload a video of a closet; the system extracts individual items ("Patagonia Better Sweater fleece, men's medium, navy"), groups them, lets the human reviewer correct. This is now feasible with current vision models. It's the single highest-leverage feature for reducing claim-prep hours.

3. **Pricing & depreciation engine.** Live retail pricing pulled from a maintained catalog (Amazon, Walmart, Home Depot, Best Buy, brand-specific sources), with category-based depreciation tables that match what carriers actually accept (IRS-style useful life tables, ACV calculators that mirror Xactimate Contents and Enservio's logic). Critically, your sources need to be *defensible* in an appraisal or litigation — screenshots, URLs, dates.

4. **Carrier-formatted output.** PDF report, Excel export, Xactimate ESX import format, Symbility-compatible CSV. Adjusters on the carrier side need to consume your output without retyping it. This is what makes you the path of least resistance.

A fifth feature — depreciation recovery tracking — becomes a strong wedge for renewal/expansion. RCV claims pay ACV upfront and release recoverable depreciation only after the policyholder replaces items and submits receipts. Most of that depreciation gets left on the table because nobody tracks it. If your platform follows the claim through replacement and helps the PA collect the holdback, you justify a recurring per-claim fee long after the initial inventory is delivered.

## 5. Pricing model

Three-tier structure once you reach Phase 3:

| Tier | Price | What it includes | Target buyer |
|---|---|---|---|
| **Done-for-you** | $750–$2,500 / claim flat | Full report produced by your team; 5–10 day turnaround | Solo PAs, attorneys without operations staff, complex claims |
| **Pro SaaS** | $399 / mo / seat + $149 / claim | Self-serve platform, pricing DB, AI-assist, exports, unlimited team training | Mid-size PA firms (2–10 adjusters) |
| **Enterprise** | $1,500–$3,500 / mo, claim volume tiers | Multi-seat, white-label reports, API, priority support, custom depreciation tables | Large PA firms (10+ adjusters), national law firms, restoration network buyers |

Rough Year-3 revenue mix at ~$3M ARR: 40% Pro SaaS, 35% done-for-you, 25% enterprise. This mix is healthy because the service revenue is high-margin overflow work, the SaaS is sticky and predictable, and enterprise gives you the lighthouse logos.

**Important regulatory note:** in many states, charging a *percentage of recovery* may legally constitute "public adjusting" and trigger licensure under state insurance department rules. Stay on flat-fee and SaaS pricing. Per-claim fees are fine; contingency is not.

## 6. Unit economics

Service tier (Phase 1, sanity-checking the cash machine):

- Average revenue per claim: ~$1,400
- Specialist labor: 6–10 hours per claim at fully-loaded $45/hr = $270–$450
- Pricing data, software, overhead allocation: ~$100
- Gross margin per claim: ~$850–$1,000 (60–70%)
- A specialist handling 200 claims/year produces ~$280K revenue against ~$80–90K fully-loaded cost

SaaS tier (Phase 3):

- ARPU on Pro: ~$8K/yr blended (subscription + per-claim)
- COGS (compute, pricing data, support): ~$1.2K/yr → ~85% gross margin
- CAC at Year 2: $1,500–$2,500 per firm via outbound + NAPIA conferences + lawyer referrals
- Payback: ~3–4 months
- LTV at 3-year retention: $24K → LTV/CAC ~10–16x

These are healthy vertical-SaaS numbers, well above the 3x LTV/CAC threshold most investors look for if you decide to raise.

## 7. Cost structure & funding need

Bootstrapped path (likely the right call given the cash flow from service revenue):

| Category | Year 1 | Year 2 | Year 3 |
|---|---|---|---|
| Founders (deferred comp / minimal salary) | $100K | $250K | $400K |
| 2–3 claim specialists (1099 → FT) | $80K | $220K | $450K |
| Engineering (founder + 1 contractor in Y2) | $40K | $180K | $400K |
| Pricing data licensing / data ops | $30K | $80K | $150K |
| Cloud infra (storage-heavy) | $12K | $40K | $90K |
| E&O insurance + legal/compliance | $25K | $40K | $60K |
| Sales & marketing (NAPIA conferences, content, paid) | $40K | $120K | $300K |
| G&A / tools / accounting | $20K | $45K | $80K |
| **Total operating cost** | **~$350K** | **~$975K** | **~$1.93M** |
| **Revenue (service-led, ramping)** | $180K–$300K | $700K–$1.1M | $2.2M–$3.5M |
| **Net cash position** | (~$100K) | break-even to slightly + | clearly profitable |

You'd need roughly **$150–$250K in starting capital** to bridge the first 9–12 months until service revenue covers the burn. This can come from founder savings, a friends-and-family round, or a small revenue-based financing facility. You almost certainly do not need venture capital to reach $3M ARR on this path, and staying unfunded preserves optionality on whether to push for venture-scale growth later.

## 8. The first 90 days

This is where your sales co-founder's warm leads turn into proof. Concrete plan:

- **Week 1–2:** Both founders interview 10 of the warm-lead lawyers + 5 PAs. Five questions only: How do you currently handle contents valuation? How long does it take? What does it cost you in time/money? What would you pay for a finished report? Would you sign an LOI today?
- **Week 3–4:** Build the v0 service workflow on Google Drive + Sheets + a pricing template. No software yet. Land the first 2 paying customers.
- **Week 5–8:** Deliver the first 5 reports. Document every step. Time every task. Note every place a human is doing something a machine could do.
- **Week 9–12:** Engineering co-founder starts building internal tooling against the documented workflow. Sales co-founder closes 5 more customers and locks in 2 LOIs from PA firms for early SaaS access.

The deliverable at Day 90 is: 10 paying customers, ~$15–25K in revenue, a documented workflow, a 12-month engineering plan, and a list of features the customers themselves prioritized.

## 9. Key risks

Four to take seriously:

1. **Verisk or CoreLogic decides contents matter.** Either incumbent could plug this gap themselves. Mitigation: move fast, build deep relationships in the PA channel where these incumbents are *not* loved (they're seen as carrier-aligned), and make your output interoperable with their tools so they have less reason to fight you.

2. **Pricing data accuracy & defensibility.** If your prices get successfully challenged by a carrier in appraisal or litigation, your customer's case is weakened and your reputation craters. Mitigation: every price source is logged with URL, screenshot, and timestamp; you publish your methodology; you maintain an appraiser-ready audit trail on every line item.

3. **Regulatory risk on unauthorized public adjusting (UPPA).** State insurance departments police this aggressively, particularly Florida and Texas. Stay strictly on flat-fee/SaaS pricing, never negotiate with a carrier on a policyholder's behalf, and have a property-insurance attorney review your terms of service in each state where you operate.

4. **CAT-driven demand volatility.** Your revenue will be lumpy — wildfires in California, hurricanes in Florida, hail in Texas all cause 3–6 month surges followed by quiet periods. Mitigation: build to handle 3x normal volume with surge contractors; price the SaaS subscription so the recurring base covers your fixed costs in quiet quarters.

## 10. Things I'd want to know from you before tightening this further

A few things would meaningfully shape the plan if you can answer them:

- **How many warm-lead lawyers are we talking about, and what geographies?** If it's 5 firms in one metro, the plan is different from 30 firms across 4 states.
- **Do those lawyers handle volume first-party property cases, or is contents valuation a one-off pain for them?** A single firm doing 200 fire claims a year is worth more than 20 firms doing 5 each.
- **Is there capital available, or are we strictly bootstrapping from founder savings?** Affects how aggressively to hire claim specialists in Year 1.
- **Geographic concentration of the founders.** California, Florida, and Texas have the most volume but also the heaviest regulation; the Northeast is friendlier but lower volume.
- **Does the engineering co-founder have any computer-vision/ML experience?** The AI item-recognition feature is the biggest leverage point and the hardest to outsource cleanly.

Once I have those, I can: (a) build a real 36-month financial model in a spreadsheet with sensitivity on key assumptions, (b) draft a one-page LOI you can put in front of the warm leads this week, and (c) sketch the v0 workflow and intake form in enough detail that you could deliver your first paid report within 3 weeks. Want to start with the customer interview list and the LOI, or jump straight to the financial model?

# Revised Plan: LA-Based, $50K Bootstrap, Wildfire Wedge

Three things your constraints tell me that I didn't know before — and all three push the plan in the same direction.

## You're sitting on the single best possible launch timing

You live 15 miles from Pacific Palisades. On January 7, 2025, the Palisades and Eaton fires destroyed roughly 16,000 structures and triggered what is now the largest residential insurance event in California history. The California Insurance Commissioner issued a bulletin on January 23 ordering insurance companies to provide advance funds for replacing personal property or contents in an amount equal to 30 percent of the policy's dwelling limit, up to $250,000, without requiring the policyholder to file an itemized claim. That's the first 30%. Collecting the remaining 70% of Coverage C — typically $150K–$500K per household — requires a line-item inventory with prices, ages, and depreciation. That's the work nobody wants to do, and it's exactly what your service produces.

Over 40 separate lawsuits have already been filed against Southern California Edison alleging that the utility company's negligence caused the Eaton wildfire, and law firms like Matthews & Associates, McNicholas & McNicholas, and Naumann Law are actively building books of hundreds of clients each. Every one of those clients needs a defensible contents inventory — first for the insurance claim, then potentially again for the subrogation/third-party case against SCE. The work doesn't go away; it compounds.

This isn't a hypothetical tailwind. It's a 24–36 month surge of concentrated demand inside a 30-mile radius of your house, with a buyer pool (plaintiff lawyers) who already know each other, already talk to each other, and already have budget for exactly this kind of work. Launch the company with the positioning "We produce the contents inventories your Palisades and Eaton fire clients need," not "We're a SaaS platform for public adjusters." The general platform story can come in Year 2.

## The CA regulatory picture narrows your options in a helpful way

California passed SB 488 in 2017 which closed the loophole that previously let attorneys and brokers act as public adjusters without a license. Until 2017, the California Public Insurance Adjusters Act made insurance brokers, attorneys and select others exempt from needing a license to act as a public adjuster, and many other entities had long been representing policyholders under a wrongly assumed exemption from licensure, until Senate Bill 488 was passed. The California PA license itself is serious infrastructure: applicants need at least two years of certified experience — 4,000 hours of compensated time or 12 months as a licensed Apprentice Public Adjuster — plus a 20-hour prelicensing course, a 100-question exam, a $20,000 surety bond, and $264 in fees. And the California PA license explicitly covers adjusting claims for fire and allied coverages, burglary, flood, and all property claims both real and personal, and loss of income — so personal property is squarely in scope.

What this means for you, practically:

1. **You cannot hold yourself out directly to fire victims as "claim help" without a PA license.** Marketing to consumers post-loss in California is a regulatory trap.
2. **You can sell a documentation and valuation product to licensed public adjusters and attorneys**, who are the parties handling settlement and representation. The attorney is practicing law; you're providing an expert inventory. This is essentially how appraisers, forensic accountants, and estimating services like Assistimate already operate.
3. **Longer term, one founder should pursue an Apprentice Public Adjuster license** — it dramatically increases credibility with PA firms, opens enterprise carrier channels, and becomes an upsell path if you later want to offer end-to-end service. It also lets that founder log hours toward the full license.

The bottom line: your Option 4 B2B2C model isn't just strategic — it's the only regulatorily clean path in California. Your warm leads being lawyers is perfect.

## A $50K plan has to be ruthlessly sequenced

$50K between two founders is tight, and my earlier financial plan assumed roughly 3x that. Here's what changes:

**No hires in Year 1.** Both founders do everything. The sales co-founder closes deals and builds the first 30–50 inventory reports by hand using templates. The engineering co-founder shadows the first 10 reports, then starts building internal tooling. There's no claims specialist headcount until service revenue can fund it (probably month 6–9).

**No venture-style marketing spend.** Warm outreach to your 2 leads, expansion through their referrals, cold outreach to the 30–50 LA-area fire-involved law firms you'll scrape from the CA Bar, and in-person presence at United Policyholders workshops and LA County Bar Association events. Marketing budget in Year 1: probably under $3K, mostly for a simple landing page, business cards, and a few breakfast/coffee meetings.

**No custom ML in Year 1.** Your engineering co-founder's background is a feature here, not a bug. Don't try to train vision models. Use off-the-shelf vendor APIs (Claude Vision, OpenAI GPT-4V, or Google Vision) at pennies per image to extract item data from photos. This plays directly to the DevOps/cloud strength — build a clean Python/Node web app, React frontend, Postgres + S3, deploy on AWS or Fly.io — and outsources the hard ML to vendors who'll do it better than you could.

**Founders pay themselves nothing until Month 6+.** The $50K is working capital for the business, not founder salaries. You'll need to know whether your personal savings, spouses' incomes, or other side work can cover your household expenses for 9–12 months. That's the real question for bootstrap viability, not the company budget.

Here's a working $50K allocation for the first 9 months:

| Category | Amount | Notes |
|---|---|---|
| Legal + incorporation + CA business registration | $3,000 | Delaware C-corp or CA LLC; attorney review of service agreement and TOS |
| Errors & Omissions insurance | $2,500 | Non-negotiable; premium for documentation/expert-services firms starts ~$1.5K/yr |
| Cloud infrastructure (AWS/Fly, DB, storage) | $1,500 | Scale up as you land customers |
| Vendor APIs (Claude/GPT-4V, pricing data scraping infra) | $2,000 | Pay-as-you-go; likely <$200/mo at first |
| Software tools (Google Workspace, Notion, QuickBooks, CRM) | $2,000 | Keep it cheap and stitched together |
| Website, branding, domain | $1,500 | Webflow or a simple Next.js site; no agency |
| Networking, conferences, UP workshops, CLE events | $2,500 | LA County Bar Assn events, CAOC, PLRB, UP wildfire clinics |
| Sales tools (scraping, email, signatures) | $1,000 | Apollo or Clay or a light custom scraper for the CA Bar site |
| Accounting & bookkeeping (first year) | $2,000 | Cheap CPA or bench.co |
| CA PA bond + Apprentice PA license fees (one founder, optional) | $1,500 | Start the clock on the PA license early |
| **Operating subtotal** | **$19,500** | |
| **Working capital / contingency** | **$30,500** | Buffer for slow months, legal surprises, a contractor if you get slammed |

Notice what's missing: salaries, marketing agencies, custom ML development, outside sales, paid ads, an office. None of that is affordable or necessary in the first year.

## Pricing optimized for the wildfire customer

For a total-loss Palisades/Eaton claim, the contents inventory typically runs 500–2,000 line items and 40–80 hours of specialist labor. A plaintiff lawyer handling 50 fire cases is facing 2,000–4,000 hours of paralegal work to produce these inventories in-house — at a fully-loaded $60–$120/hr paralegal cost, that's $120K–$500K of internal expense they'd love to offload.

Three pricing tiers for Year 1:

| Package | Price | Scope | Turnaround |
|---|---|---|---|
| **Partial-loss inventory** | $1,500 flat | Up to 250 items, standard report, one revision round | 7–10 business days |
| **Total-loss inventory** | $3,500 flat | Up to 1,500 items, comprehensive reconstruction including social-media-assisted recall, two revision rounds, Xactimate ESX export | 14–21 business days |
| **Complex/high-value claim** | $5,000–$8,000 | 1,500+ items or high-value items requiring appraisal research, expert declaration if needed for litigation, unlimited revisions | 21–35 business days |

For perspective: at a $3,500 average and 6 total-loss reports per month, that's $21K/month or $252K run-rate. If each founder runs 3 active reports simultaneously in Year 1, that's clearly achievable with the warm-lead base alone.

Offer the first 2–3 reports at a steep discount ($1,500 flat for a total-loss) to your warm leads in exchange for a written testimonial and permission to reference the case in sales conversations. You're buying social proof, not revenue, at this stage.

## Technology plan that fits your engineering co-founder

Phase 1 (months 0–4) is not a product — it's internal tooling to deliver the service reliably:

- **Intake form** built in Typeform or a custom Next.js form. Collects claim metadata, policyholder info, attorney contact, Google Drive folder with all available evidence (photos, videos, receipts, credit card statements, Zillow floor plans, social media archives).
- **Evidence organization**: Google Drive + a Postgres metadata table to track every file, every item, every version.
- **Item database**: spreadsheet at first, then a normalized Postgres schema (items, categories, brands, models, conditions, sources). This becomes your moat.
- **Pricing research workflow**: founders or contractors manually look up prices from 5–10 approved retail sources per item, capture URL + screenshot + date. Build scrapers for your top 10 sources (Amazon, Walmart, Target, Best Buy, Home Depot, Wayfair, West Elm, Crate & Barrel, Williams-Sonoma, Pottery Barn) to pre-populate candidate prices.
- **Depreciation engine**: start with public Marshall & Swift / IRS / NAIC useful-life tables in a Python script; refine from what carriers actually accept in your first 20 claims.
- **Report generator**: Python/Jinja2 + WeasyPrint to produce a branded PDF report; a CSV/XLSX exporter for Xactimate ESX import.

Phase 2 (months 4–9) layers in vendor AI:

- **Photo intake** → Claude Vision or GPT-4V identifies items, brand, model, condition from user-provided photos and social media imagery. Human-in-the-loop review for accuracy.
- **OCR of receipts and credit card statements** → feeds items and dates into the database automatically.
- **Auto-populate from item recognition** → reduces specialist time per report from 60 hours to an estimated 20–25 hours.

Phase 3 (months 9–18) opens the platform for self-service use by licensed PAs and attorney paralegals. Same software, different UX: they do the work, you provide the tooling + data.

None of this requires custom model training. All of it plays to a cloud-engineering background.

## Customer acquisition: specific to your situation

Your sales co-founder has two warm leads and a plan to source from the CA Bar. Let me make that plan concrete.

**Week 1–2:** Both founders take each warm lead out for coffee (or a Zoom if needed). Interview them with a structured script: How many fire cases? How are you producing contents inventories today? What's the pain? What would you pay for a finished report? Can we deliver our first report for client X this month? Goal: 2 LOIs and 1 live paying engagement out of these meetings.

**Week 2–4:** Scrape a target list of LA-area first-party property firms. The CA Bar website lets you search by practice area; you can also pull lawyer names from the 40+ SCE lawsuits already filed against Southern California Edison via court records on PACER and LA Superior Court. Expected hit list: 30–60 firms actively handling Palisades/Eaton cases. Separately, build a list of 30–50 CA-licensed public adjusters from the CDI's public adjuster registry.

**Week 3–6:** Attend United Policyholders wildfire workshops as a resource partner (not to solicit policyholders directly — to be visible to the attorneys and PAs who also show up). Attend LACBA Insurance Law Section events. Join PLRB (Property Loss Research Bureau) as a vendor/associate member.

**Week 4–8:** Outbound to the target list. Sales co-founder sends personalized emails to 10 firms a day referencing specific cases they're handling, offering a free sample report on a demo dataset or at steep discount for the first engagement. Conversion target: 10–15% of cold outreach to discovery call; 30% of discovery calls to first paid engagement. From 200 contacts → 25 discovery calls → 7–8 paid engagements. Combined with warm leads, this gets you to ~10 customers by month 3.

**Month 3+:** Referral engine. Every completed report ships with a "if you liked this, here are three colleagues who should know about us" ask. Plaintiff lawyers in LA talk constantly to each other about vendors.

## Revenue trajectory at these constraints

| Month | Reports/mo | Avg. price | Revenue | Cumulative |
|---|---|---|---|---|
| 1 | 0 | — | $0 | $0 |
| 2 | 1 | $1,500 | $1,500 | $1,500 |
| 3 | 2 | $2,000 | $4,000 | $5,500 |
| 4 | 3 | $2,500 | $7,500 | $13,000 |
| 5 | 4 | $2,800 | $11,200 | $24,200 |
| 6 | 5 | $3,000 | $15,000 | $39,200 |
| 7 | 6 | $3,000 | $18,000 | $57,200 |
| 8 | 7 | $3,200 | $22,400 | $79,600 |
| 9 | 8 | $3,200 | $25,600 | $105,200 |
| 10 | 10 | $3,300 | $33,000 | $138,200 |
| 11 | 12 | $3,300 | $39,600 | $177,800 |
| 12 | 14 | $3,400 | $47,600 | $225,400 |

Year 1 revenue: ~$225K. Year 1 gross margin with two founders as labor: effectively 95% (you're not paying yourselves). Operating cost: ~$50K. Net cash generated: ~$175K, which funds (a) founder salaries starting Month 9, (b) the first claim specialist hire in Month 10–12, (c) continued software investment, and (d) a real Year 2 plan with a healthy cash cushion.

This is deliberately conservative. With the Palisades/Eaton tailwind and engaged warm leads, you could plausibly 2x these numbers. I'd rather the plan be achievable and pleasantly exceeded than aspirational and demoralizing.

## Risks that matter for your specific situation

1. **The wildfires create a "fat year" illusion.** Don't hire a big team based on Y1 volume — the Palisades/Eaton claim tail tapers by mid-2026. Use the surge to fund the platform build and geographic expansion, not to fund overhead.
2. **Warm-lead concentration.** If 60% of Y1 revenue comes from 2 firms, losing one is catastrophic. By Month 6, no single customer should be more than 25% of revenue.
3. **UPPA enforcement.** Stay strictly B2B. Every customer contract should specify that you are providing expert documentation services to a licensed attorney or public adjuster, not representing the policyholder. Have a CA insurance attorney review the agreement template. Consider an "expert consultant" framing similar to how forensic accountants or structural engineers work in litigation.
4. **Pricing database accuracy in CA specifically.** California appraisal panels and bad-faith litigation are sophisticated. Every price source must be contemporaneous, cited, and defensible. A single destroyed report used in a $2M lawsuit is worth more in reputational damage than 50 happy reports.
5. **Cash runway at $50K.** One personal emergency or one delayed payment from a customer can break the plan. Keep at least $15K untouched as a true reserve; don't count it in the operating budget.

## What I'd build for you next

To actually move on this plan, the four most valuable deliverables are:

1. **A customer interview script** your sales co-founder can use on the warm leads this week — 8 questions, 30-minute format, designed to end with a committed first engagement.
2. **A one-page service agreement / LOI template** tailored to CA first-party property attorneys, with the UPPA-safe framing already worked out.
3. **A 36-month financial model in Excel** with assumptions you can flex (reports/month, avg price, specialist hires, SaaS conversion) so you can stress-test scenarios before committing.
4. **A v0 report template** — the actual PDF deliverable format your first customer will receive — so you can walk into the first paid engagement knowing exactly what you'll produce.

I'd suggest starting with the interview script and LOI template, since those unlock the warm-lead conversations this week. The financial model and report template can come after you've had the first two customer conversations and have real data on what they want.

Which of those would you like me to tackle first? Or if you'd like, I can build all four as a set of files you can download and start using immediately.

LOI validated. Now the financial model.I successfully built the first two files and was partway through the financial model when the tool-use limit cut me off. Here's where things stand and what the numbers from the model reveal before I write the fourth file.

## Status of the deliverables

**File 1 — `01_Customer_Interview_Guide.docx`** ✅ Built and validated. Covers the purpose, 8-question interview script with listening notes, a 6-signal scoring rubric for ranking leads, post-call decision criteria, and a reusable interview log template.

**File 2 — `02_LOI_and_Service_Agreement.docx`** ✅ Built and validated. Contains Part 1 (one-page LOI with a pilot terms table), Part 2 (20-clause services agreement with UPPA-safe scope language, liability cap, confidentiality/work product, CA governing law), and Exhibit A for engagement specifics. Marked with a clear "must be reviewed by a CA attorney" disclaimer.

**File 3 — `03_Financial_Model.xlsx`** ✅ Built and validated — 1,125 formulas, zero errors, 7 sheets (README, Assumptions, Revenue, Costs, P&L, Cash, Scenarios), industry-standard color coding. The model ran clean but I didn't get to hand it off to you or build File 4.

**File 4 — v0 report template (docx)** ❌ Not started.

## What the model is telling us — and it's worth pausing on

Year 1 revenue: $184K. Year 1 net income: $110K. Minimum cash balance across 36 months: **$43,565** (occurs in Month 1). That means your $50K bootstrap survives — barely — under the base case. Good news.

But there's a warning sign in Year 3: net income drops to $60K on $739K revenue (8% margin). That's because the model hires 4–5 specialists while the wildfire tail flattens revenue growth. The base case over-hires relative to the Y3 demand curve. You'd want to either delay specialist hiring, push harder on SaaS revenue, or accept thinner Y3 margins as the cost of building capacity for Y4+.

The Y1 result also assumes zero founder salary for 8 months. That only works if you can actually live off savings or other income during that period. That question is more important than any spreadsheet assumption.

## What I need to do next session

Rerun this in a fresh turn and I'll (a) package the three existing files plus build File 4 (the v0 report template showing the actual deliverable format — cover page, methodology, itemized inventory, depreciation schedule, pricing audit trail, sign-off), and (b) present all four to you via `present_files` so you can download them. Just reply "continue" or "finish the files" and I'll pick up where I left off.

All four files are built and validated. Now let me copy them to the outputs directory and present them.All four files are ready. A quick tour of what you've got:

**01 — Customer Interview Guide.** Use this on your two warm leads this week. Eight questions in a specific order (pain discovery before price anchor), listening notes for each, and a 6-signal scoring rubric so you can decide within 30 minutes whether each interview is a "send LOI today" lead or a "quarterly check-in" lead.

**02 — LOI and Service Agreement.** Two-part document. Part 1 is a one-page LOI you can edit in 10 minutes and send after a good interview. Part 2 is a 20-clause services agreement with the UPPA-safe scope language baked into clause 1, the no-contingency fee structure in clause 3, the CA governing law clause in clause 16, and an Exhibit A for per-engagement terms. Opens with a red-boxed disclaimer reminding you that it still needs a California insurance attorney's review before you sign anything with it.

**03 — Financial Model.** Seven sheets, 1,125 formulas, zero errors. Start on the README tab, then go straight to Assumptions — that's where every lever lives. The cells in blue are inputs you edit; everything downstream recalculates. The Cash sheet will show you, on the day you change any assumption, whether your $50K survives. Base case runs: Y1 revenue $184K, Y1 net income $110K, minimum cash $44K in Month 1. That's survivable but thin — if Y1 reports per month ramps slower than modeled, the minimum cash can go negative. Stress-test it before you commit.

**04 — Report Template v0.** This is the deliverable format — what a customer actually receives. Cover page, executive summary with headline figures, full methodology section, data sources inventory, a 42-category depreciation schedule (17 shown, full set in the evidence archive), room-by-room summary, a sample of the itemized inventory with 12 representative West Elm / Sony / Sonos line items, a matching pricing audit trail showing how every price traces to a retailer URL, certifications/limitations, and a preparer signature page. Walk this through your warm leads in the interview — "here's what you'd actually get back" is the single most persuasive thing you can show.

## The immediate sequence

1. **This week:** schedule both warm leads using the interview guide. Don't pitch — listen.
2. **Before the first real customer:** get the services agreement reviewed by a California insurance attorney (budget $1,500–$3,000; your network may have a referral).
3. **Before month 1:** open the financial model, set your starting cash, stress-test what happens if Y1 ramps at half the base rate, and pre-decide what you'd cut.
4. **Month 1:** deliver your first report using the template. Every item you add to the template becomes training data for v1.

What's the next thing — do you want me to build out the v0 workflow (intake form, evidence-archive structure, a couple of sample pricing scrapers), or draft the cold outreach email sequence for the CA Bar list your sales co-founder will be scraping?