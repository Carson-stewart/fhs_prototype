# Relius — Strategic Plan & Operating Document

**Owner:** Carson Stewart
**Entity:** Seneca Insights LLC (Florida) — planned conversion to Public Benefit Corporation
**Document version:** v1.1
**Last updated:** May 2026
**Purpose:** This document is the strategic source of truth for Relius. It defines mission, vision, audience, product, revenue model, roadmap, KPIs, objectives, and action items. It is intended to be reviewed quarterly and revised deliberately — not casually edited.

**v1.1 changes from v1.0:** Hardship tier reframed as Mission Membership with sliding scale, annual confirmation, and cost transparency. Public covenants rewritten to reflect "store intelligence, not raw data" principle. Phase 7 expanded to include React Native + React Native Web conversion. Couple/partner mode added to Phase 9. PBC jurisdiction (Florida), investor path (Hivers and Strivers), and other open decisions resolved. HSA/FSA pursuit deferred to Year 2–3. Timeline updated to reflect mobile-first scope.

---

## 1. Brand Foundation

### 1.1 Mission Statement

**Relius makes sophisticated financial intelligence accessible to everyone — not just enterprises and the wealthy — translating financial pressure into clarity and the next right move, with dignity and without jargon.**

### 1.2 Vision Statement

**A world where every person, freelancer, and small business operates with the financial clarity and confidence once exclusive to enterprises — where no one fails for lack of access to good financial guidance.**

### 1.3 Origin Story

Relius exists because of a specific failure: a small-business owner who didn't have access to the financial tools, intelligence, and coaching that enterprise companies take for granted. That owner is Carson's mother. Her business failed, not because the work was bad, but because the financial decisions around it were made without the visibility and guidance that should be a baseline, not a luxury.

This is the founding fact of Relius. It defines who the product is for, what it must never do, and why every architectural decision — from the optimization engine to the public covenants — is built around the people who would otherwise be priced out.

### 1.4 Core Values

These are the values that govern product, brand, and business decisions. When two values conflict, the earlier-listed wins.

1. **Dignity over judgment.** Users come to Relius often anxious, sometimes ashamed. Every interaction must reduce — never amplify — that weight. Sass, snark, or "tough love" is not the brand.
2. **Clarity over completeness.** A single accurate, actionable insight beats ten partial ones. Lead with state, justify with score, act with plan.
3. **Action over information.** The unique value Relius provides is "what to do next," not "what happened."
4. **Honesty over flattery.** Tell people the truth — including when they're improving and including when something needs attention. No shame, but no false comfort.
5. **Rigor under the hood, simplicity on top.** Real optimization beneath, plain-language translation above. The math is what makes the simplicity defensible.
6. **Mission protection over short-term revenue.** Decisions that compromise user trust are off-limits, even when financially attractive.
7. **Math, not heuristics.** When competitors use weighted averages, Relius uses constrained optimization. This is not a UX choice; it's a structural commitment.

### 1.5 Positioning Statement

For people and small businesses navigating financial decisions without an enterprise-grade finance team, Relius is a financial intelligence companion that translates today's situation into a clear state, an honest explanation, and one calm next move — powered by real optimization, not heuristics, and built without shame, dark patterns, or hidden agendas.

### 1.6 Brand Voice Principles

- **Calm, not chirpy.** No exclamation marks unless something is genuinely worth exclaiming. No emoji-as-personality. The tone is a steady friend, not an excited mascot.
- **Direct, not performative.** Say what's true. Don't decorate.
- **Plain language, always.** "Pressure is rising" beats "your liability-to-liquidity ratio is degrading." Save technical accuracy for the "Why?" view.
- **Action-oriented.** Every screen ends with something the user can do or feel oriented by — never with raw data and no next step.
- **No fear, no shame.** "Critical," "danger," "you overspent" — these words don't belong in Relius.
- **Confidence with humility.** Relius will say "we don't know" or "this insight has low confidence" before it will pretend.

### 1.7 Marketing Line (working)

> *"Other apps tell you what happened. Relius tells you what to do next."*

This is the structural pitch: every competitor is descriptive (Mint/Monarch/Copilot/YNAB). Relius is prescriptive — built on real optimization. The line works for consumer surfaces, founder-led content, and institutional pitches alike.

---

## 2. Strategic Architecture

Relius is built in four layers, each with a distinct role. Understanding these layers prevents confusion between *what the product is* and *what the product feels like*.

### 2.1 Layer 1 — Optimization Engine (Trade Secret)

The LP/MILP optimization core. Multi-period scoring with the D_min feedback loop, MILP indicator constraints on milestone variables, freed-budget propagation across phase transitions, archetype-aware constraint sets. This is the structural moat. It produces outputs that static weighted-average scorers structurally cannot.

**Status:** Built. Core engine and Phase 4 Plaid integration complete.
**Protection:** Trade secret (chosen over patent disclosure). Math never appears in API responses or user-facing surfaces.
**Visibility:** Internal only.

### 2.2 Layer 2 — Scoring Outputs (Confidence-Tagged)

The three-score model: Financial Health Score (FHS, 300–850), Financial Strain Score (FSS, 0–100), Financial Recovery Score (FRS, 0–100). Confidence ratings (high/medium/low/missing) per data field. Provenance metadata. Archetype-aware coverage.

**Status:** Built. 10/10 archetype compliance. Confidence ratings flow through mapper.
**Visibility:** API contract layer. Internal score names persist in API responses; consumer-friendly translations live in Layer 3.

### 2.3 Layer 3 — Translation Layer (User-Facing)

The state words, plain-language explanations, "what changed" deltas, next-move recommendations. This is where the engine becomes a *companion* rather than a calculator.

**Status:** Conceptually defined. Implementation begins in Phase 7+.
**Per-archetype vocabulary:** Different state language for Individual ("Steady / Watchful"), Small Business ("Stable / Tightening / Capital-event needed"), Freelancer ("Buffered / Tight against fixed obligations"), Startup ("Healthy runway / Burn-watch / Capital-event").

### 2.4 Layer 4 — Surface

The deployment context. Layer 4 is plural by design.

- **Surface A: Consumer mobile app + web app** — primary launch surface. Built with React Native + React Native Web for shared codebase across iOS, Android, and web.
- **Surface B (year 2+): Credit union / community bank embedded** — first institutional vertical. White-label or co-brand.
- **Surface C (year 2+): Advisor / coach platform** — per-seat licensing.
- **Surface D (year 3+): Employer benefits platform** — PEPM pricing.

The consumer app is also the **credibility object** for Surfaces B–D. Real user outcomes and engagement become the institutional sales narrative.

---

## 3. Audience Strategy

### 3.1 Four Archetypes (Equal Mission Priority, Phased Build Order)

All four archetypes are equally important to the mission. They differ only in build order, driven by market gap analysis.

| Archetype | Mission Priority | Build Order | Rationale |
|---|---|---|---|
| Small Business | Equal | **1st** (Phase 5a) | Largest underserved gap. Mother's archetype. Authenticity match. |
| Freelancer | Equal | **2nd** (Phase 5b) | Second-largest gap. Volatile income suits LP/MILP uniquely. |
| Individual W-2 | Equal | **3rd** (Phase 5c) | Saturated market but accessible. Differentiation via plan + non-shaming tone. |
| Startup | Equal | **4th** (Phase 5d) | Smallest market opportunity; Brex/Ramp/Mercury occupy funded segment. |

### 3.2 Unifying Value Proposition (Holds Across All Four)

> *"Help me understand where I stand, why my situation has changed, and the single best thing I can do next — without making me feel ashamed, overwhelmed, or judged."*

This holds for an anxious renter, a freelance designer, a small-business owner, and a startup founder. The variables — what "next" looks like, what "stand" means — change by archetype. The promise does not.

### 3.3 Per-Archetype Translation

| Archetype | "Where do I stand?" | "What changed?" | "What's the next move?" |
|---|---|---|---|
| Individual | "Steady / Watchful / Tight" | "Bills landed before payday" | "Protect $X until Friday" |
| Freelancer | "Buffered / Tight against fixed obligations" | "Invoice paid; tax reserve below threshold" | "Move $X to tax reserve before next billable" |
| Small Business | "Stable / Tightening / Capital-event needed" | "AR aging extending; payables compressed" | "Collect on invoices >30d; defer non-critical spend" |
| Startup | "Healthy runway / Burn-watch / Capital-event" | "Burn multiple expanded; runway shortened" | "Cut $X discretionary; extend payroll cycle by Y days" |

---

## 4. Product Strategy

### 4.1 Information Hierarchy (Universal)

Every screen, in order:

1. **State** — translated, single phrase, calm
2. **Justification** — one sentence, plain language
3. **Next move** — one action, specific, time-bounded
4. **Why?** — collapsed; expandable to score components without exposing optimization

**How the hierarchy maps to the strategic architecture and the moat:**

| Hierarchy step | Architecture layer | Strategic role |
|---|---|---|
| State | Layer 3 (Translation) | Friendly entry point — calm, plain language. The "translation comes first" principle. |
| Justification | Layer 2 (Scoring outputs) | The score, surfaced in plain words. The "where do they stand" principle. |
| Next move | Layer 1 (Optimization, surfaced) | **This is where the moat shows through.** The specificity, dollar amount, and time horizon are produced by real LP/MILP optimization, not heuristics. |
| Why? | Layer 1 → Layer 2 boundary | Explainability without exposing the LP/MILP formulation. Trade-secret boundary respected. |

The moat is the LP/MILP engine, but how the user *feels* the moat is through the specificity of the "Next move." When the recommendation is "protect $210 until Friday" with a precise dollar amount and a precise time horizon, that specificity is what no static-weighted-average competitor can produce. The frontend must treat the next-move surface as the centerpiece, not a footer.

### 4.2 What Relius Does

- Translates financial state into a plain-language daily/weekly read
- Explains what changed since the last check-in
- Surfaces the single best next action via constrained optimization
- Forecasts pressure changes ahead of paydays/bills/cash events
- Tracks momentum and recovery over time
- Adapts vocabulary, constraints, and recommendations per archetype
- Surfaces confidence ratings on every insight

### 4.3 What Relius Does NOT Do

- Budget category management at transaction level (not a budgeting app)
- Investment recommendations (not a robo-advisor)
- Lending/underwriting decisions
- Tax preparation or filing
- Credit score reporting (third-party)
- Generic chatbot interactions
- Advertising or affiliate product pushing
- Sass, snark, shame, or "tough love" coaching

### 4.4 Trade-Secret/Explainability Boundary

**Explainable surfaces (allowed):**
- Score components (cash flow, debt obligations, milestone status)
- Confidence ratings per input field
- Direction of change ("your buffer improved")
- Causal drivers ("rent landed before payday")

**Protected surfaces (never exposed):**
- LP/MILP formulation
- Constraint matrices
- Internal weights or objective values
- Optimization solver state

This boundary must be checked at every API response boundary. The `_assert_no_access_token()` scrubber pattern should be paired with an analogous `_assert_no_optimization_internals()` check.

---

## 5. Revenue & Trust Model

### 5.1 Tier Structure

| Tier | Price | Audience | What's Included |
|---|---|---|---|
| **Free** | $0 forever | Everyone | Today's state, primary pressure driver, one next-move recommendation, basic confidence indicators, account connection, 14-day history |
| **Premium** | $7/mo or $69/yr | Engaged users | All Free features + multi-period forecasting, scenario testing, archetype-specific deep features, full history, partner/spouse access, the "what changed" deep view |
| **Lifetime** | $249 one-time | Subscription-averse users | All Premium features for as long as Relius operates. Open indefinitely (no cap on Lifetime sales). |
| **Mission Membership** | $0–$7 sliding scale, $3 default suggested | Self-identified financial difficulty | All Premium features. Indefinite. Plaid connection required. |

### 5.2 Mission Membership — Detailed Mechanics

Mission Membership replaces what would conventionally be called a "hardship tier." The reframing is intentional: it's not charity, it's mission participation. Mission Members are part of why Relius exists, not a cost to be minimized.

**Sliding scale at signup:**
- Default suggested contribution: **$3/month**
- Slider range: $0 to $7/month
- Framing: *"Choose what works for you. $0 is okay if that's where you are. $3 helps cover costs. $7 supports Relius and another user."*
- The default suggestion does most of the sustainability work — defaults are powerful, and people typically only deviate downward when they actually need to.

**Light affirmation at signup:**
> *"I'm contributing what I can right now, and Relius is meaningfully helpful to me."*

No verification. No proof. No income disclosure. The friction of misrepresenting yourself to claim a status you don't identify with is the abuse limiter.

**Plaid connection required.** Mission Membership is not a free-Premium-without-using-the-product loophole. The connection requirement ensures Relius is providing actual value to Mission Members and caps infrastructure exposure to active users only.

**Annual one-tap re-affirmation.** Every 12 months, Mission Members receive a single prompt:

> *"Continue your Mission Membership? — Yes, my situation hasn't improved / Switch to Free tier / Upgrade to Premium"*

One tap. No questions. This creates a natural graduation moment without forcing anyone to justify themselves. Most people in genuine ongoing difficulty will tap Yes; most people who claimed it as a workaround will quietly switch tiers.

**Cost transparency in-app.** Mission Members see, in their account view:

> *"Your Premium features cost approximately $2.50/month to operate. Pay-it-forward subscribers help cover this for Mission Members. Thank you for being part of Relius."*

Doesn't restrict access. Doesn't shame. Just makes the economics visible. Most people, when they understand the math, voluntarily contribute what they can.

**Sustainability principle.** Mission Membership operates as cost of mission, but only if the structural levers above keep the average contribution healthy. Threshold for re-evaluation: if average Mission Member contribution drops below ~$1/month sustained over a quarter, the structure is being abused at a rate that requires revisiting.

### 5.3 Benefits & Add-Ons (Available Across Tiers)

| Benefit | Eligibility | Mechanics |
|---|---|---|
| **Rough Patch** | Any user, any tier (except Lifetime, where N/A), once per 12 months | 1–2 months of full Premium features. For Free users: features unlocked. For Premium users: billing paused, features retained. Mechanically unavailable to Mission Members (they already have Premium). |
| **Pay-it-forward** | Any paying user (Premium or Lifetime) | +$5–$25/month optional add-on on top of subscription. Funds Mission Membership infrastructure. Visible impact in profile ("Your contributions this year covered X Mission Members"). |

**Rough Patch — light affirmation:**

> *"I'm experiencing a temporary financial setback — job loss, medical expense, family emergency, or similar — and would like 1–2 months of breathing room."*

If a user uses Rough Patch repeatedly (every 12 months across multiple years), the app surfaces a soft prompt: *"Mission Membership is here if your situation is ongoing — it's designed for exactly this."* Not pressure. An offering.

**Pay-it-forward — mechanics:**

A Premium or Lifetime user opts in to add $5–25/month on top of their subscription. The contribution flows into a designated Mission Membership subsidy pool that covers operational costs (Plaid API calls, storage, support) for Mission Members paying below break-even.

The user-facing experience:
- Toggle during checkout or in account settings: *"Add Pay-it-forward to my subscription. Helps cover users who can't afford Premium."*
- Choice of amount: $5, $10, $25/month, or custom.
- Profile visibility: *"Your contributions this year: $120. Estimated Mission Members supported: 4."* Calculated from cost-per-user.
- Annual transparency report includes aggregate Pay-it-forward statistics.

This pattern is proven in Patreon's tiered support, Substack's "founding member" pricing, and several buy-one-give-one consumer brands. It works when the mission is genuine and the impact is visible. For Relius, it converts mission-aligned users into active mission carriers.

### 5.4 Pricing Principles

- **Free tier is genuinely useful, not crippleware.** A user can use Relius forever without paying and feel served. The mission demands this.
- **Annual pricing is meaningfully discounted from monthly.** Annual = ~$5.75/mo equivalent (~17% off). Industry standard is 30%+; current discount is intentional and may be tested later.
- **Lifetime tier provides up-front cash and signals long-term commitment to users.** $249 is calibrated lower than Calm's $399 because Relius is newer; revisit after 12 months of operating data.
- **Mission Membership is not a cripple-tier.** Same Premium features, indefinite. The sliding scale captures meaningful revenue from members who can pay something while preserving access for those who can't.
- **Rough Patch is universal.** Any user can claim it. It's a "life happens" benefit, not a charity tier.
- **No price increases without explicit opt-in re-confirmation.** Auto-increase is a dark pattern; Relius doesn't do it.

### 5.5 Future Revenue (Year 2+)

- **HSA/FSA eligibility** for annual subscriptions, via Letter of Medical Necessity (Headspace pattern). Defer until Year 2–3 after outcome data exists. Not pursued in Year 1.
- **Institutional licensing** — credit unions first (see §2.4 and Phase 10), then advisor platforms, then employer benefits. Drives the Surface B–D roadmap.
- **API access tier** — for developers and small institutional partners who want to embed.

### 5.6 Public Covenants

These are **published, durable commitments** in plain English. They live on the website, in Terms of Service, and in onboarding. They do not change without public notice and user consent.

1. **We store the intelligence we produce, not the raw data we process.** Your transactions live in your bank — we don't keep copies. What we store is what we calculate from your data: your readiness state, your scores over time, your trends. Encrypted, and yours to delete at any time.
2. **We will never sell, license, or share your financial data with third parties.** Plaid is a connection, not a sale.
3. **We will never display advertising to you inside Relius.** Not now. Not later. Not after a pivot.
4. **We will never recommend products in exchange for affiliate revenue without explicit, opt-in disclosure.** No silent monetization.
5. **We will never auto-increase your subscription price without an explicit re-confirmation step.** Price changes require your active "yes."
6. **You can export all your data and disconnect at any time, in two clicks.** No "call support to cancel."
7. **Your historical scores remain accessible after cancellation.** "Keep what you made."
8. **We publish an annual transparency report** showing user outcomes, Mission Membership usage, demographic distribution, and where revenue went.

### 5.7 Structural Trust Architecture

- **Public Benefit Corporation election (Florida).** Convert Seneca Insights LLC to a Florida Public Benefit Corporation, or hold Relius under a new Florida PBC subsidiary. Florida has a Public Benefit Corporation statute. Legal commitment to consider stakeholder impact, not just shareholder value. *Talk to a Florida startup attorney about whether to convert the existing LLC or create a new entity — there are tax and operational implications either way.*
- **B-Corp certification (Year 2 target).** Third-party verification of the impact claims. Three-year recertification cycle. Annual fee starts ~$2K, scales with revenue.
- **Investor pathway.** Bootstrap and revenue-finance first. Apply to Hivers and Strivers (US Army veteran-led VC) when traction supports it. Other VC pursued only if needed. Goal: maximum founder ownership retention.
- **Mission-protection clause in any future investment terms.** Language that prevents acquirers or investors from quietly walking back the public covenants.

---

## 6. Phased Roadmap

### 6.1 Engineering Phases

| Phase | Status | Scope | Outcome |
|---|---|---|---|
| Phase 1 | ✅ Done | Core scoring engine, three-score architecture | Math validated against 10 archetypes |
| Phase 2 | ✅ Done | API layer (FastAPI) | Production-shaped routes |
| Phase 3 | ✅ Done | Initial frontend (vanilla HTML/JS) | Working prototype UI |
| Phase 4 | ✅ Done | Plaid integration, mapper, multi-bank | Real bank data flowing through engine |
| **Phase 5** | 🟡 Active | Archetype completion (Small Business → Freelancer → Individual → Startup) | Full multi-archetype platform |
| Phase 6 | Pending | Model B weight calibration from real user data | Production-grade weights |
| **Phase 7** | Pending | **(7a) React Native + React Native Web conversion**, **(7b) Production hardening** (encryption, security cleanup, monitoring) | Mobile + web app from shared codebase; production readiness |
| Phase 8 | Pending | Closed beta launch | First real users |
| Phase 9 | Pending | Public launch + couple/partner mode | General availability with shared-account support |
| Phase 10 | Year 2 | Institutional API surface, multi-tenant readiness, credit union pilot | First B2B vertical |

### 6.2 Phase 5 Sub-ordering

| Sub-phase | Archetype | Why this order | Estimated duration |
|---|---|---|---|
| 5a | **Small Business** | Largest market gap, mother's archetype, authenticity match | ~6 weeks |
| 5b | **Freelancer** | Second-largest gap, LP/MILP unique fit for volatile income | ~4–5 weeks |
| 5c | **Individual W-2** | Saturated but accessible; ship after differentiated archetypes proven | ~3–4 weeks |
| 5d | **Startup** | Smallest opportunity; defer until others ship | ~4–5 weeks |

Each sub-phase requires 10/10 archetype test compliance before moving forward, matching the existing Phase 1–4 quality bar.

### 6.3 Phase 7 — Detailed Scope

**7a — React Native + React Native Web conversion (4–6 weeks).** Refactor the vanilla HTML/JS frontend into a single React Native codebase that compiles to:
- Native iOS app
- Native Android app
- Web app (via React Native Web)

This is the architectural commitment to "mobile-first AND web app" from a single codebase. Doing the conversion at the start of Phase 7 — after Phase 6 weight calibration but before production hardening — means production security work is built into the new architecture, not retrofitted.

**7b — Production hardening (4 weeks).**
- Plaid access token encryption (current plaintext storage is a critical liability)
- Removal of debug/raw-data surfaces
- Sensitive value masking
- Audit logging
- Data deletion flow
- Account disconnect flow
- Plaid item re-auth handling
- Production environment configuration

### 6.4 Architectural Constraints (Non-Negotiable Going Forward)

- **API-first.** No scoring logic in the frontend. Every screen must be reproducible via raw API calls.
- **Multi-tenant readiness.** Schemas designed so a `tenant_id` column can be added later without migration trauma. Don't ship multi-tenant in v1, but don't preclude it.
- **Theming abstraction.** CSS variables / theme tokens for colors, typography, logos. White-label requires this from day one.
- **Trade-secret boundary.** API responses pass through a `_assert_no_optimization_internals()` scrubber.
- **Confidence flow-through.** Every score response carries confidence metadata. Frontend surfaces it.
- **Graceful degradation.** SQLite/external service failures degrade to zero-state defaults, never crash the API.
- **Compute-and-discard for raw Plaid data.** Phase 7 architectural separation: raw transactions are transient processing data (in memory during a scoring pass, discarded after); only derived intelligence (scores, profile, trends) is persistent.
- **Shared codebase across iOS, Android, web.** React Native + React Native Web is the long-term architectural commitment. No platform-specific divergence except where genuinely necessary.
- **Plaid connection required for Mission Membership.** Mission Membership tier is mechanically gated on an active Plaid connection.

---

## 7. Twelve-Month Timeline (Realistic with Mobile-First Scope)

### 7.1 Timeline Honest Read

The original 12-month target was 5,000 MAU. With the mobile-first decision (React Native + Web from launch) and full archetype scope (all four archetypes shipped), the realistic shape becomes:

- **Public launch: month 10** (later than original month 9 estimate due to RN conversion)
- **Month 12 MAU: 1,500–2,500 realistic** (5K is stretch)
- **5,000 MAU: month 14–16 realistic**
- **First credit union pilot conversation: month 12 (early stage)**

**The 5,000 MAU goal at 12 months is retained as a stretch target**, not a base case. The base case is 2,000 MAU at 12 months and 5,000 MAU at 15 months. This is the cost of the mobile-first decision, and it's worth it — without mobile, MAU growth would hit a ceiling sooner.

### 7.2 Quarter-by-Quarter Overview

| Quarter | Focus | Headline Outcome |
|---|---|---|
| **Q1** (Months 1–3) | Phase 5a + 5b (Small Business, Freelancer) + PBC conversion | Multi-archetype platform proven on the underserved segments |
| **Q2** (Months 4–6) | Phase 5c + 5d (Individual, Startup) + Phase 6 weight calibration | Full archetype coverage, calibrated weights |
| **Q3** (Months 7–9) | Phase 7a (React Native conversion) + 7b (production hardening) + Phase 8 closed beta | Mobile + web from shared codebase; first real users |
| **Q4** (Months 10–12) | Phase 9 public launch + couple/partner mode + growth + B-Corp groundwork | Public launch; 2,000+ MAU; institutional conversations begun |

### 7.3 Detailed Month-by-Month

| Month | Focus |
|---|---|
| 1 | Complete Phase 5 multi-bank test (in-flight); Phase 5a kickoff (Small Business archetype build); Florida PBC attorney consult |
| 2 | Phase 5a build continues; LP archetype constraints, AR/AP timing, business credit card re-integration; PBC filing initiated |
| 3 | Phase 5a ships with 10/10 tests; Phase 5b kickoff (Freelancer); volatile income + tax reserve modeling |
| 4 | Phase 5b ships; Phase 5c kickoff (Individual W-2 refinement) |
| 5 | Phase 5c ships; Phase 5d kickoff (Startup); Phase 6 (weight calibration) preparation begins |
| 6 | Phase 5d ships — all four archetypes complete; Phase 6 calibration runs |
| 7 | Phase 7a (React Native + React Native Web conversion) begins |
| 8 | Phase 7a continues; Phase 7b (production hardening) begins in parallel |
| 9 | Phase 7 ships; Phase 8 closed beta opens (50–100 invited users); public covenants document published; landing site live |
| 10 | Public launch (Phase 9) including couple/partner mode; founder-led content begins (origin story, market gap content, social media primary) |
| 11 | Growth phase; Hivers and Strivers application if traction supports; first credit union outreach conversations |
| 12 | First annual transparency report drafted; B-Corp certification application; 2,000–5,000 MAU range |

---

## 8. Milestones

### 8.1 Engineering Milestones

- **M1:** Phase 5a (Small Business archetype) shipped with 10/10 archetype tests passing — Month 3
- **M2:** Phase 5b (Freelancer archetype) shipped — Month 4
- **M3:** All four archetypes shipped (Phase 5c, 5d) — Month 6
- **M4:** Phase 6 weight calibration complete — Month 6
- **M5:** Phase 7a React Native + Web conversion complete — Month 8
- **M6:** Phase 7b production hardening complete — Month 9
- **M7:** Closed beta live with first connected users — Month 9
- **M8:** Public launch on iOS, Android, and web simultaneously — Month 10
- **M9:** Couple/partner mode shipped — Month 10
- **M10:** API surface documented and available for institutional partners — Month 12

### 8.2 Business / Brand Milestones

- **B1:** Florida Public Benefit Corporation conversion filed — Month 2
- **B2:** Public covenants document published — Month 9
- **B3:** Landing site and brand identity live — Month 9
- **B4:** First paying customer — Month 10
- **B5:** First $1K MRR — Month 11
- **B6:** First Lifetime tier purchase — Month 10–11
- **B7:** First Pay-it-forward subscription — Month 11
- **B8:** First Mission Member who later upgrades to Premium — Month 12
- **B9:** Hivers and Strivers application submitted — Month 11–12 (if pursuing)
- **B10:** B-Corp certification application submitted — Month 12
- **B11:** First annual transparency report — Month 12
- **B12:** First credit union pilot conversation in late stage — Month 12

### 8.3 Mission Milestones

- **MM1:** First Mission Member — within 1 month of public launch
- **MM2:** First user reports meaningful financial outcome improvement — Month 11
- **MM3:** 100+ small business owners active — Month 12
- **MM4:** First user testimonial referencing the mother-as-origin story — anytime; this validates the personal positioning
- **MM5:** Mission Membership average contribution at or above $1.50/month after Month 12 — sustainability validation

---

## 9. Key Performance Indicators (KPIs)

### 9.1 Acquisition

- Monthly signups
- Plaid connection completion rate (target: >70%)
- Time to first value — first state shown to user (target: <2 minutes from signup)
- Onboarding completion rate (target: >65%)
- App Store / Play Store rating (target: 4.5+)

### 9.2 Engagement

- Daily, weekly, monthly active users (DAU / WAU / MAU)
- Check-ins per week per user (target: 2.5+)
- "What changed?" view rate per check-in (target: 40%+)
- Recommendation acceptance/action rate — surveyed (target: 30%+)
- D1 retention (target: 50%+), D7 (target: 30%+), D30 (target: 20%+)

### 9.3 Trust & UX Health

- Plaid disconnect rate (lower = better; track baseline first)
- Manual data correction rate per user (lower = mapper accuracy good)
- Confidence indicator distribution (target: 70%+ of insights at high confidence after Phase 6)
- Subscription cancellation reason distribution — categorized as "achieved goals," "didn't get value," "switched to alternative," "financial reasons" (target: <30% in "didn't get value")
- Emotional pulse: "How do you feel after this check-in?" — Clearer / Relieved / Focused / Still confused / More worried (target: 70%+ in first three categories)

### 9.4 Revenue

- Free → Premium conversion rate (target: 5–8%)
- ARPU among paying users
- Monthly churn rate (target: <5% monthly)
- Lifetime tier purchase rate
- Mission Membership ratio (target: 15–25% of total users; sustainability threshold ~30%)
- Mission Membership average contribution (target: $1.50–2.00/month; floor: $1.00/month — below this, structure needs revisiting)
- Pay-it-forward enrollment rate among paying users (target: 8–10%)
- Rough Patch claims per user per year (track for trend signals)

### 9.5 Mission Metrics (Tracked Annually)

- Demographic distribution of user base (income brackets, archetype distribution, geography)
- Self-reported financial outcome improvement (annual user survey)
- Number of Mission Members who graduate to Premium each year
- Hardship-to-mission graduation pathway: Mission Members → Premium → Pay-it-forward enrollment
- Pay-it-forward dollars contributed / Mission Membership operating cost (target: ratio approaching 1.0 by year 2)
- Number of users who would otherwise lack access to comparable tools (proxy: Mission Membership + small business below revenue threshold)

---

## 10. Quarterly Objectives (OKR-Style)

### Q1 — Multi-Archetype Foundation

**Objective:** Prove the engine works across the underserved archetypes that justify the mission.

- **KR1:** Phase 5a (Small Business) ships with 10/10 archetype tests passing
- **KR2:** Phase 5b (Freelancer) ships with 10/10 archetype tests passing
- **KR3:** Florida Public Benefit Corporation conversion filed
- **KR4:** Architectural constraints (API-first, multi-tenant readiness, theming, trade-secret boundary, compute-and-discard) audited and documented in `CLAUDE.md`

### Q2 — Full Archetype Coverage and Calibration

**Objective:** Complete the platform engine and prepare for mobile-first conversion.

- **KR1:** Phase 5c (Individual) and Phase 5d (Startup) ship — all four archetypes complete
- **KR2:** Phase 6 weight calibration complete; production weights locked
- **KR3:** React Native + React Native Web architecture decisions made (Expo vs bare RN, navigation, state management) and documented
- **KR4:** Public covenants document drafted, reviewed by Florida attorney, ready to publish

### Q3 — Mobile-First Architecture and Closed Beta

**Objective:** Ship mobile and web from shared codebase, get first real users.

- **KR1:** Phase 7a (React Native + Web conversion) complete
- **KR2:** Phase 7b (production hardening) complete — Plaid token encryption shipped, debug surfaces removed, audit logging live
- **KR3:** Closed beta launched with 50–100 connected users
- **KR4:** Mission Membership tier mechanics live, including sliding scale, annual confirmation logic, cost transparency surface
- **KR5:** Pay-it-forward and Rough Patch benefits live in beta

### Q4 — Public Launch and Institutional Groundwork

**Objective:** Launch publicly across iOS, Android, and web. Lay groundwork for the institutional path.

- **KR1:** Public launch (Phase 9) executed across iOS, Android, web simultaneously
- **KR2:** Couple/partner mode shipped at public launch
- **KR3:** 2,000+ MAU by end of Q4 (5,000 stretch target)
- **KR4:** Free → Premium conversion at 5%+
- **KR5:** First credit union pilot conversation in late stage (LOI or term sheet, not necessarily signed)
- **KR6:** First annual transparency report drafted and published
- **KR7:** B-Corp certification application submitted
- **KR8:** Hivers and Strivers application submitted (if traction supports)

---

## 11. Action Items by Horizon

### 11.1 This Week (Immediate)

- [ ] Finish Test 3 (multi-bank flow) currently paused mid-test
- [ ] Add `_assert_no_optimization_internals()` scrubber to API response boundary, mirroring the existing access-token scrubber pattern
- [ ] Update `CLAUDE.md` with project rename to Relius and updated strategic context (mission, vision, core values, marketing line)
- [ ] Commit this strategy document to the repo as `RELIUS_STRATEGY.md` alongside `CLAUDE.md`

### 11.2 This Month

- [ ] Schedule Florida startup attorney consultation for Public Benefit Corporation conversion (convert Seneca Insights LLC vs. create new PBC subsidiary; tax/operational implications)
- [ ] Phase 5a (Small Business archetype) build kickoff: define LP constraints, AR/AP timing model, business credit card re-integration
- [ ] Sketch first version of public covenants document (plain-language draft, not yet legal-reviewed)
- [ ] Define the per-archetype state vocabulary (the table in §3.3) into a structured config, not hardcoded strings
- [ ] Audit the existing frontend for theming abstraction: extract colors, typography to CSS variables / theme tokens; remove hardcoded brand assumptions (preparation for RN conversion)
- [ ] Reserve `relius.com` (or chosen domain), trademark search, social handles
- [ ] Begin a private founder journal documenting the build for future content (origin story material)
- [ ] Reach out to marketing friends to scope Q3–Q4 social media content collaboration

### 11.3 This Quarter

- [ ] Phase 5a + Phase 5b shipped with full test compliance
- [ ] Florida PBC conversion filed
- [ ] First draft of public covenants document, attorney-reviewed
- [ ] Architectural constraints audited and documented
- [ ] Begin defining Phase 6 calibration methodology (what data sources, what user populations, how to validate)
- [ ] Begin React Native + React Native Web architecture research (Expo vs bare RN; this is research, not build)

### 11.4 Strategic — Recurring

- [ ] **Quarterly:** Review this strategy document. Note what's changed, what's still open, what needs revision. Don't edit casually.
- [ ] **Quarterly:** Review KPI dashboard against targets. Adjust resource allocation based on what the numbers say, not what's most fun to build.
- [ ] **Quarterly:** Mission Membership average contribution health check. If trending below $1/month, structural revisit required.
- [ ] **Annually:** Publish transparency report. Even if first version is small, the discipline of writing it shapes the year's decisions.
- [ ] **Ongoing:** Document the build for future founder-led content. Origin story, technical decisions, why certain choices were made.

---

## 12. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Plaid token leak (current plaintext storage)** | Catastrophic — breach liability, trust collapse | Phase 7b priority; encrypt before any external user beta. Non-negotiable. |
| **Recommendations construed as financial advice** | Regulatory exposure | Florida attorney review of recommendation copy before public launch; potential RIA/coaching disclosure; conservative language defaults |
| **Mission Membership abuse at scale (drops average contribution below threshold)** | Revenue erosion, mission dilution | Sliding scale + annual confirmation + cost transparency. Quarterly health check. If average drops below $1/month sustained, revisit structure. |
| **Trade-secret leakage via API responses** | Loss of moat | Scrubber pattern at every boundary; code review checklist; periodic audit |
| **Distribution failure (consumer FinTech is hard)** | Mission failure | Founder-led content from launch; community-driven channels; lean toward small business / freelancer where the gap is real and content lands |
| **Solo founder bandwidth (engineering + brand + business)** | Burnout, slow execution | Session-based development pattern (already working); ruthless scope discipline; defer institutional sales until consumer is stable |
| **Investor / acquirer mission drift** | Long-term mission risk | PBC charter; public covenants in TOS; mission-protection clauses in any future investment terms |
| **Calibration data scarcity (Phase 6)** | Weights stay synthetic | Closed beta is the calibration vehicle; design beta intake to maximize calibration value |
| **React Native conversion complexity (4–6 week estimate optimistic)** | Timeline slippage | Architecture research in Q2 before build begins; consider Expo for faster setup; have fallback to PWA-only if RN conversion blocks |
| **Mobile app store approval delays (especially Apple)** | Launch slip | Begin App Store / Play Store registration in Month 7 during Phase 7a, not Month 9 |

---

## 13. Open Decisions (Still Requiring Deliberate Choice)

The original 10 open decisions from v1.0 have all been resolved (see §13.1). The following are new open decisions surfaced by the design conversation; they require attention but are not blocking near-term work.

### 13.1 Resolved Decisions (Logged for Reference)

| Decision | Resolution |
|---|---|
| PBC jurisdiction | **Florida** (existing LLC in Florida) |
| Investor pathway | **Bootstrap → Hivers and Strivers (veteran-focused VC) → other VC if needed**; goal is maximum founder ownership |
| Mobile-first vs web-first | **Both, via React Native + React Native Web** (single codebase) |
| Hardship verification | **Light affirmation, no verification** (Mission Membership) |
| Content channels | **Social media primary**, with marketing-friend support |
| Annual subscription discount | **17% (current); revisit later** |
| Lifetime tier cap | **Open indefinitely** |
| Couple/partner mode in v1 | **Yes, in Phase 9** at public launch |
| HSA/FSA pursuit timing | **Year 2–3**, not Year 1 |
| First institutional vertical | **Credit unions** |
| Hardship/Mission Membership floor | **Treat as cost of mission**, with structural levers (sliding scale, annual confirmation, cost transparency) keeping average contribution healthy |
| Plaid required for Mission Membership | **Yes** |
| React Native conversion timing | **Start of Phase 7** (before production hardening) |

### 13.2 New Open Decisions

1. **React Native architecture choices.** Expo vs bare React Native. Navigation library (React Navigation vs alternatives). State management (Redux vs Zustand vs Context). These are engineering choices to make in Q2 research before Q3 build.
2. **App Store positioning category.** "Finance" is the obvious fit but "Health & Fitness" or "Lifestyle" might serve the wellness positioning better and reduce competition with Mint clones. Decision needed before Phase 9 submission.
3. **Closed beta intake design.** The closed beta is also Phase 6's calibration data source. How to structure beta intake (questionnaire depth, archetype distribution, demographic sampling) matters for both UX validation and weight calibration. Decision needed in Q2.
4. **Couple/partner mode permissions model.** Equal access? Owner + viewer? Per-account splitting? Affects Phase 9 scope materially.
5. **Annual transparency report — first version scope.** Minimum viable v1 vs ambitious v1. Lean toward minimum and iterate; first version sets precedent for what's expected.
6. **Mobile push notification strategy.** Frequency, content, opt-in defaults. Critical UX decision before public launch — can make or break retention. Notifications should match the brand voice (calm, useful, rare).

---

## 14. Reference: Architectural Constants

These are facts about Relius that should not change casually. They're listed here as the tail end of the document so they're easy to find.

- **Three-score model:** FHS (300–850), FSS (0–100), FRS (0–100)
- **Four user archetypes:** Individual W-2, Freelancer, Small Business, Startup
- **FRS branch priority:** real snapshot > LP trajectory > baseline
- **10/10 archetype compliance** is the ongoing gate for any release
- **Average FHS sitting just above lower bound** is intentional (per existing project memory)
- **Business credit card exclusion for Individual user type** is a deliberate interim decision, revisited in Phase 5
- **Mapper unit tests must include real Plaid wire-shape fixtures**, not just synthetic
- **Lazy Plaid client initialization** — avoids import-time credential failures
- **`_assert_no_access_token()` scrubber** at all API response boundaries
- **`_assert_no_optimization_internals()` scrubber** to be added at all API response boundaries
- **SQLite failures degrade gracefully** — zero-state defaults, never crash
- **Internal LP weights and objective values** stripped from all API responses
- **Plaid connection required for Mission Membership** — tier mechanically gated on active connection
- **Compute-and-discard for raw Plaid data** — raw transactions are transient processing data; only derived intelligence is persistent
- **Shared codebase across iOS, Android, web** via React Native + React Native Web
- **FastAPI backend separated from React Native frontend** via API contract; frontend never embeds scoring logic

---

## Appendix A — One-Page Summary (For Sharing)

**Relius** is a financial intelligence companion that translates today's situation into a clear state, an honest explanation, and one calm next move — for individuals, freelancers, and small businesses who deserve the kind of financial guidance enterprises take for granted.

Built on real optimization, not heuristics. Operated as a Florida Public Benefit Corporation. Free tier with full daily readiness. Premium at $69/year. Lifetime at $249. Mission Membership — sliding scale ($0–$7/month, $3 suggested) for self-identified financial difficulty, with annual one-tap re-confirmation and full cost transparency. Pay-it-forward subsidy contributions for users who want to fund the mission. Rough Patch benefit for anyone going through a hard month.

Public covenants: store the intelligence we produce, not the raw data we process; never sell your data; never advertise; never push affiliate products; easy export; easy cancel.

Founded by Carson Stewart after his mother's small business failed for lack of access to financial tools. Built so that doesn't have to happen again.

> *"Other apps tell you what happened. Relius tells you what to do next."*

---

*End of document. Quarterly review next due: end of Q1 deployment cycle.*
