"""
Recommendation generation — the surface where Relius gets its voice.

Phase 5a.4 ships four recommendation types in a unified shape.
RELIUS_STRATEGY.md §4.1 (information hierarchy: State → Justification
→ Next move → Why?) and §1.6 (brand voice: calm, direct, plain
language, no fear/shame, present-tense actionable, confidence with
humility) are encoded directly into this module — at the data level
(uniform recommendation shape) and at the test level (programmatic
brand-voice audit on every generated string).

Recommendation shape
--------------------
Every recommendation is a dict with this contract:

    {
      "type":       "action" | "data_completion"
                  | "archetype_suggestion" | "detection_override",
      "priority":   "primary" | "secondary" | "tertiary",
      "confidence": "high" | "medium" | "low",
      "title":      <imperative phrase, the action>,
      "body":       <one-sentence justification, plain language>,
      "next_move":  <single specific action, time-bounded if applicable>,
      "context":    { ... type-specific structured data ... },
    }

Shape of `context` varies per type. See each generator's docstring.

Singular-primary discipline
---------------------------
Per RELIUS_STRATEGY.md §4.1, the user's "next calm move" surface is
one action, not a list. Multiple secondary/tertiary recommendations
can exist for users who want depth, but only ONE recommendation
carries `priority="primary"` at a time. The orchestrator
`compile_sb_recommendations()` enforces this: if more than one
generator emits a primary, the strain-magnitude tiebreaker picks the
dominant one and demotes the rest to secondary.

Trade-secret discipline
-----------------------
Recommendation strings reference score components and effects (which
are public per RELIUS_STRATEGY.md §4.4) but never the LP/MILP
formulation, weight values, or solver state. The `_assert_no_optimization_internals()`
scrubber at the API boundary catches any drift. Every recommendation
also passes `audit_brand_voice()` on construction — fail-loud if a
generator emits shame-coded copy.

Stateless
---------
Recommendation generation is stateless — same inputs produce same
outputs. Persistence (dismissed recommendations, "fires once per
session" UX state) is deferred to Phase 7. The frontend can dedupe
on `type+context` for the per-session UX.
"""
from __future__ import annotations
from typing import Optional, Iterable


# ─────────────────────────────────────────────────────────────────────
# CALIBRATION VALUES — refined in 5a.5. Each threshold is the "this is
# loud enough to surface" cutoff for a strain dimension. Direction-of-
# push noted inline so future-Carson can calibrate without re-deriving.
# ─────────────────────────────────────────────────────────────────────
_THRESHOLDS = {
    # AR aging — pla above this triggers a primary action recommendation.
    # Lower it if real-client data shows AR-driven cash crunches we miss;
    # raise if too noisy.
    "ar_strain_primary":            0.40,

    # AP compression — pla above this triggers a primary AP rec
    # ("Defer flexible payables this week" — active urgency).
    "ap_compression_primary":       0.70,
    # Phase 5a.5 calibration: chronic-awareness secondary tier.
    # When pla is in 0.50-0.70 and there's no overdue carry, current
    # behavior pre-5a.5 emitted no rec at all — the user could be
    # chronically running near-term AP at half their liquid reserve and
    # Relius would stay silent. That violates the "should not be silently
    # ignored" criterion. Soft secondary copy ("keep an eye on…") fits
    # the situation: real pressure but not yet acute.
    "ap_compression_chronic":       0.50,
    # Lower bound for the overdue-only secondary path.
    "ap_compression_secondary":     0.30,

    # LOC utilization — two-tier. The PLA-floor gate (`loc_pla_floor`)
    # is consulted first to skip LOC recs when FSS doesn't see strain;
    # once past the gate, the tier is selected from raw util %, which
    # is what the brief specifies in user-facing terms.
    #   util >= 0.70 → advisory tier ("Pause additional draws…")
    #   util >= 0.85 → urgent tier   ("Speak to your lender…")
    "loc_pla_floor":                0.40,   # ~ corresponds to util>=70%
    "loc_util_advisory":            0.70,   # util-space
    "loc_util_critical":            0.85,   # util-space

    # Payroll coverage — primary if below 2 weeks of coverage.
    # Stored as the strain pla cutoff (0.50 corresponds to 3-week
    # coverage on the 2..4 ramp); see engine_sb._compute_payroll_coverage_strain.
    "payroll_coverage_primary":     0.50,

    # Secondary tier: any strain pla above this counts as elevated
    # (informs the secondary/tertiary slotting). Below this, no action
    # rec at all.
    "secondary_strain_threshold":   0.30,
}

# ─────────────────────────────────────────────────────────────────────
# Brand voice audit — programmatic. Every recommendation built via
# `_rec()` is audited; an assertion failure surfaces a copy bug at
# test time, not at user-facing render time.
# Per RELIUS_STRATEGY.md §1.6: no fear, no shame, no past-tense
# moralizing. Words and phrases below have repeatedly produced
# shame-coded copy in fintech apps; we explicitly forbid them.
# ─────────────────────────────────────────────────────────────────────
_BRAND_VOICE_FORBIDDEN_WORDS = (
    "warning",   "critical",   "danger",  "dangerous",
    "failing",   "failure",    "crisis",  "disaster",
    "alarming",
)

_BRAND_VOICE_FORBIDDEN_PHRASES = (
    "at risk",          # alarmist framing
    "falling behind",   # shame
    "behind on",        # shame ("behind on collections")
    "you should have",  # past-tense moralizing
    "if you had",       # past-tense moralizing
    "you're failing",   # shame
    "your business is", # used in alarmist constructions
    # Phase 5b.4 — Freelancer-specific forbidden phrases. These look
    # supportive in isolation but read as patronizing when applied to
    # actual financial difficulty. Famine-state copy is the highest-
    # stakes brand-voice surface in the project; hand-review every
    # string in addition to this audit.
    "don't worry",
    "it'll be fine",
    "just temporary",
    "will get better",
    "hang in there",
    "stay strong",
)


def audit_brand_voice(rec: dict) -> None:
    """Raise AssertionError if any string in title/body/next_move (or
    string values in context) violates the brand voice rules.

    Match logic: word-boundary tokenized for forbidden words (so
    "warningful" wouldn't trip "warning" — though no such word exists,
    the precision matters), substring for forbidden phrases."""
    strings: list[str] = []
    for key in ("title", "body", "next_move"):
        v = rec.get(key, "")
        if isinstance(v, str):
            strings.append(v)
    for v in (rec.get("context") or {}).values():
        if isinstance(v, str):
            strings.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    strings.append(item)

    import re
    for s in strings:
        sl = s.lower()
        # Forbidden words: word-boundary match
        for word in _BRAND_VOICE_FORBIDDEN_WORDS:
            if re.search(r"\b" + re.escape(word) + r"\b", sl):
                raise AssertionError(
                    f"Brand voice violation: forbidden word {word!r} in "
                    f"recommendation copy: {s!r}"
                )
        for phrase in _BRAND_VOICE_FORBIDDEN_PHRASES:
            if phrase in sl:
                raise AssertionError(
                    f"Brand voice violation: forbidden phrase {phrase!r} "
                    f"in recommendation copy: {s!r}"
                )


def _rec(type_: str, priority: str, confidence: str,
         title: str, body: str, next_move: str,
         context: Optional[dict] = None) -> dict:
    """Construct + audit a recommendation. Use ALWAYS — never build a
    rec dict by hand; this builder is the single audit chokepoint."""
    rec = {
        "type":       type_,
        "priority":   priority,
        "confidence": confidence,
        "title":      title,
        "body":       body,
        "next_move":  next_move,
        "context":    context or {},
    }
    audit_brand_voice(rec)
    return rec


# ─────────────────────────────────────────────────────────────────────
# Confidence-driven copy helpers — render specificity scales with
# input confidence (RELIUS_STRATEGY.md §1.6: "confidence with humility").
# ─────────────────────────────────────────────────────────────────────
def _money(amount: float, confidence: str) -> str:
    """Format a dollar amount with confidence-appropriate hedging.
    high   → "$X,YYY"
    medium → "around $X,YYY"
    low    → "roughly $X,XXX"
    missing → returns "" (caller should surface data_completion instead)."""
    if confidence == "missing":
        return ""
    formatted = f"${amount:,.0f}"
    if confidence == "high":
        return formatted
    if confidence == "medium":
        return f"around {formatted}"
    return f"roughly {formatted}"


def _confidence_preface(confidence: str) -> str:
    """Optional preface phrase — empty for high, hedged for low.
    Returns a phrase that fits at the start of a body sentence."""
    if confidence == "high":
        return ""
    if confidence == "medium":
        return "From what we can see, "
    return "Based on partial data, "


# ─────────────────────────────────────────────────────────────────────
# Action recommendations (Part B). Triggered by SB-FSS dimensions and
# SB forward simulations. Generators take the relevant slice of the
# scoring output + optional confidence kwarg.
# ─────────────────────────────────────────────────────────────────────

def _ar_aging_action(ar_buckets: dict, ar_pla: float,
                     confidence: str = "high") -> Optional[dict]:
    """Build an AR-aging action rec when strain is elevated. Picks
    body copy based on which aged bucket dominates."""
    if ar_pla < _THRESHOLDS["ar_strain_primary"]:
        return None
    bucket_60   = float(ar_buckets.get("60_days", 0))
    bucket_90   = float(ar_buckets.get("90_plus_days", 0))
    if bucket_90 >= bucket_60:
        # 90+ dominant
        title = "Prioritize collecting on invoices over 90 days"
        amount_label = _money(bucket_90, confidence)
        body = (f"{_confidence_preface(confidence)}"
                f"{amount_label} of your receivables is more than 90 days old, "
                "which is the slice most likely to become uncollectible.")
        next_move = (f"Reach out to those customers this week — start with "
                     "the largest invoice.")
    else:
        title = "Reach out to customers with invoices over 60 days"
        amount_label = _money(bucket_60, confidence)
        body = (f"{_confidence_preface(confidence)}"
                f"{amount_label} of your receivables has aged past 60 days. "
                "A quick check-in often resolves slow payment.")
        next_move = (f"Send a friendly follow-up to the largest 60-day invoice "
                     "in the next 48 hours.")
    return _rec(
        "action", "primary", confidence, title, body, next_move,
        context={
            "trigger": "ar_aging_strain",
            "ar_60_days": bucket_60,
            "ar_90_plus_days": bucket_90,
        },
    )


def _ap_compression_action(ap_pending: dict, ap_pla: float, s_liq: float,
                           confidence: str = "high") -> Optional[dict]:
    """Build an AP-compression action rec when 7-day payables exceed
    a meaningful portion of liquid coverage."""
    due_7   = float((ap_pending or {}).get("due_within_7d", 0))
    overdue = float((ap_pending or {}).get("overdue", 0))
    near_term = due_7 + overdue
    if ap_pla < _THRESHOLDS["ap_compression_primary"]:
        # Secondary tier — three sub-paths (in priority order):
        #   • Overdue carrying (pla >= 0.30) → "Catch up on overdue"
        #   • Chronic compression (pla >= 0.50, no overdue) → soft awareness
        #   • Below all secondary thresholds → no rec
        if overdue > 0 and ap_pla >= _THRESHOLDS["ap_compression_secondary"]:
            title = "Catch up on overdue payables"
            body  = (f"{_confidence_preface(confidence)}"
                     f"You have {_money(overdue, confidence)} in overdue "
                     "payables — clearing those first protects vendor "
                     "relationships.")
            next_move = ("Set up payments for the 2 oldest overdue "
                         "invoices today.")
        elif ap_pla >= _THRESHOLDS["ap_compression_chronic"]:
            # Phase 5a.5 calibration — chronic 50-70% AP compression
            # without overdue carry. The user is staying current but
            # the buffer is thin; surface awareness without urgency.
            title = "Keep an eye on near-term payables"
            body  = (f"{_confidence_preface(confidence)}"
                     f"You have {_money(near_term, confidence)} due in "
                     "the next 7 days against a tighter cash buffer. "
                     "You're staying current, but the cushion is thin.")
            next_move = ("Review your 7-day payables once before the "
                         "weekend so nothing slips.")
        else:
            return None
        priority = "secondary"
    else:
        gap = max(0.0, near_term - s_liq)
        title = "Defer flexible payables this week"
        gap_label = _money(gap, confidence) if gap > 0 else _money(near_term, confidence)
        body = (f"{_confidence_preface(confidence)}"
                f"You have {_money(near_term, confidence)} due in the next "
                "7 days against a tighter cash buffer. Picking which "
                "vendors can wait gives you breathing room.")
        next_move = (f"Review your 7-day payables and identify "
                     f"{gap_label} that can shift to next week.")
        priority = "primary"
    return _rec(
        "action", priority, confidence, title, body, next_move,
        context={
            "trigger": "ap_compression",
            "due_within_7d": due_7,
            "overdue": overdue,
        },
    )


def _loc_utilization_action(locs: list, loc_pla: float,
                            confidence: str = "high") -> Optional[dict]:
    """Build a LOC utilization action rec. Two tiers: 70% util advisory,
    85% util urgent (lender conversation suggested)."""
    if loc_pla < _THRESHOLDS["loc_pla_floor"]:
        return None
    # Compute aggregate utilization from the LOC list.
    total_balance = sum(float(L.get("balance", 0)) for L in (locs or []))
    total_limit   = sum(float(L.get("limit", 0))   for L in (locs or []))
    if total_limit <= 0:
        return None
    util = total_balance / total_limit
    if util < _THRESHOLDS["loc_util_advisory"]:
        return None
    util_pct = round(util * 100)
    if util >= _THRESHOLDS["loc_util_critical"]:
        title = "LOC near limit — consider speaking to your lender"
        body  = (f"{_confidence_preface(confidence)}"
                 f"Your line of credit is at {util_pct}% utilization. "
                 "Lenders typically prefer to discuss restructuring "
                 "before a limit is reached.")
        next_move = ("Schedule a 15-minute call with your lender this week.")
    else:
        title = "Pause additional LOC draws this week"
        body  = (f"{_confidence_preface(confidence)}"
                 f"Your line of credit is at {util_pct}% utilization, past "
                 "the level where lenders start asking questions.")
        next_move = ("Hold off on new draws and identify one obligation you "
                     "can pay from operating cash instead.")
    return _rec(
        "action", "primary", confidence, title, body, next_move,
        context={
            "trigger": "loc_utilization",
            "utilization_pct": util_pct,
            "total_balance": total_balance,
            "total_limit": total_limit,
        },
    )


def _payroll_coverage_action(payroll_pla: float, weeks_of_coverage: float,
                             confidence: str = "high") -> Optional[dict]:
    """Build a payroll-coverage action rec when coverage drops below
    2 weeks (one missed cycle from now)."""
    if payroll_pla < _THRESHOLDS["payroll_coverage_primary"]:
        return None
    title = "Payroll coverage is tight — consider deferring owner draws"
    body  = (f"{_confidence_preface(confidence)}"
            f"Your liquid reserve covers about {weeks_of_coverage:.1f} weeks "
            "of payroll. Holding owner draws this cycle keeps employees paid.")
    next_move = ("Pause your next owner draw and revisit when reserve "
                 "covers 4 weeks of payroll.")
    return _rec(
        "action", "primary", confidence, title, body, next_move,
        context={
            "trigger": "payroll_coverage",
            "weeks_of_coverage": round(weeks_of_coverage, 2),
        },
    )


def _owner_draw_action(assessment: dict,
                       confidence: str = "high") -> Optional[dict]:
    """Build an owner-draw action rec when the sustainability check
    failed. Driven by 5a.2's `assess_owner_draw_sustainability`."""
    if not assessment or assessment.get("sustainable", True):
        return None
    if assessment.get("reason") == "no_owner_draws":
        return None
    current = float(assessment.get("current_draw", 0))
    sustainable_max = float(assessment.get("max_sustainable_draw", 0))
    gap = max(0.0, current - sustainable_max)
    title = "Pause owner draws this month — current pace is unsustainable"
    body = (f"{_confidence_preface(confidence)}"
            f"At current revenue, your business can sustain "
            f"{_money(sustainable_max, confidence)} in owner draws. "
            f"You're drawing {_money(current, confidence)}.")
    next_move = (f"Pause draws for one cycle, or trim by "
                 f"{_money(gap, confidence)} until revenue catches up.")
    return _rec(
        "action", "primary", confidence, title, body, next_move,
        context={
            "trigger": "owner_draw_sustainability",
            "current_draw": current,
            "sustainable_max": sustainable_max,
        },
    )


def generate_action_recommendations(inp, result,
                                    confidence_overrides: Optional[dict] = None
                                    ) -> list:
    """Generate SB action recommendations from FSS contributors and
    forward simulations. Only runs for `archetype="small_business"`.

    Returns a list of recs with at most ONE primary. Singular-primary
    discipline: when multiple generators emit primary candidates, the
    one with the highest underlying strain pla wins; the others are
    demoted to secondary.

    `confidence_overrides`: optional dict mapping trigger key → confidence
    string. Lets tests exercise medium/low gating without changing the
    underlying inp values. Defaults to "high" for every trigger.
    """
    if getattr(inp, "archetype", None) != "small_business":
        return []
    if not result.fss_breakdown:
        return []

    overrides = confidence_overrides or {}
    sb_insights = (result.insights or {}).get("small_business") or {}

    candidates: list[tuple[float, dict]] = []   # (pla, rec) for primary tiebreak

    def _add(rec, pla):
        if rec is None:
            return
        candidates.append((float(pla), rec))

    # AR aging
    ar_dim = result.fss_breakdown.get("AR aging strain") or {}
    ar_pla = float(ar_dim.get("pla", 0))
    _add(_ar_aging_action(
        getattr(inp, "ar_aging_buckets", {}) or {},
        ar_pla,
        confidence=overrides.get("ar", "high"),
    ), ar_pla)

    # AP compression
    ap_dim = result.fss_breakdown.get("AP compression strain") or {}
    ap_pla = float(ap_dim.get("pla", 0))
    _add(_ap_compression_action(
        getattr(inp, "ap_pending", {}) or {},
        ap_pla,
        getattr(inp, "S_liq", 0),
        confidence=overrides.get("ap", "high"),
    ), ap_pla)

    # LOC utilization
    loc_dim = result.fss_breakdown.get("LOC utilization strain") or {}
    loc_pla = float(loc_dim.get("pla", 0))
    _add(_loc_utilization_action(
        getattr(inp, "business_lines_of_credit", []) or [],
        loc_pla,
        confidence=overrides.get("loc", "high"),
    ), loc_pla)

    # Payroll coverage — derive weeks from inp for body copy.
    payroll_dim = result.fss_breakdown.get("Payroll coverage strain") or {}
    payroll_pla = float(payroll_dim.get("pla", 0))
    weeks = 0.0
    cycles = {"weekly": 4.33, "biweekly": 2.17, "semimonthly": 2.0,
              "monthly": 1.0, "none": 0.0}.get(
                  getattr(inp, "payroll_periodicity", "none"), 0.0)
    monthly_payroll = cycles * float(getattr(inp, "payroll_amount_per_cycle", 0) or 0)
    if monthly_payroll > 0 and inp.S_liq > 0:
        weeks = (inp.S_liq / monthly_payroll) * 4.33
    _add(_payroll_coverage_action(
        payroll_pla, weeks,
        confidence=overrides.get("payroll", "high"),
    ), payroll_pla)

    # Owner draw sustainability — pla proxy = 1.0 if unsustainable, else 0.
    owner_assessment = sb_insights.get("owner_draw_assessment") or {}
    owner_pla = 0.0 if owner_assessment.get("sustainable", True) else 1.0
    _add(_owner_draw_action(
        owner_assessment,
        confidence=overrides.get("owner", "high"),
    ), owner_pla)

    # Singular-primary discipline. Pick the highest-strain primary;
    # demote the rest. (Owner draw with pla=1.0 wins ties.)
    primaries = [(pla, rec) for pla, rec in candidates
                 if rec.get("priority") == "primary"]
    if len(primaries) > 1:
        primaries.sort(key=lambda t: t[0], reverse=True)
        winner_id = id(primaries[0][1])
        for _, rec in candidates:
            if rec.get("priority") == "primary" and id(rec) != winner_id:
                rec["priority"] = "secondary"

    # Order: primary first, then secondaries by strain magnitude desc.
    candidates.sort(key=lambda t: (
        0 if t[1]["priority"] == "primary"
        else 1 if t[1]["priority"] == "secondary"
        else 2,
        -t[0],
    ))
    return [rec for _, rec in candidates]


# ─────────────────────────────────────────────────────────────────────
# Data completion recommendations (Part C). Fire when manual-entry
# fields are missing — currently AR aging and AP pending. These take
# PRIMARY priority over action recs because action recs can't fire
# without the underlying data.
# ─────────────────────────────────────────────────────────────────────

_DATA_COMPLETION_DEFS = {
    "ar_aging_buckets": {
        "title": "Add your accounts receivable aging",
        "body":  ("Once we know how your invoices are aged, we can prioritize "
                  "collections and forecast cash flow more accurately."),
        "next_move": "Add this manually — it takes about 2 minutes.",
        "fields_required": ["current", "30_days", "60_days", "90_plus_days"],
        "unlocks": [
            "AR collection prioritization",
            "Cash flow trajectory accuracy",
            "Aged-receivable strain monitoring",
        ],
    },
    "ap_pending": {
        "title": "Add your near-term payables",
        "body":  ("When we know what's due and when, we can help you sequence "
                  "payments and spot pressure before it lands."),
        "next_move": "Add this manually — it takes about 2 minutes.",
        "fields_required": ["due_within_7d", "due_8_to_30d", "overdue"],
        "unlocks": [
            "AP scheduling guidance",
            "Cash compression detection",
            "Vendor-relationship protection",
        ],
    },
}


def generate_data_completion_recommendations(mapped_fields_dict: dict
                                             ) -> list:
    """For each field in the mapped output with
    `source == "manual_entry_required"`, generate a data-completion rec.

    Input: a dict in the shape of `MappedFields.to_dict()` (or a subset).
    Output: list of recs, all `priority="primary"` (data completion
    blocks downstream action recs, so it earns primary slot).
    """
    recs = []
    for field_name, defn in _DATA_COMPLETION_DEFS.items():
        mf = mapped_fields_dict.get(field_name)
        if not isinstance(mf, dict):
            continue
        if mf.get("source") != "manual_entry_required":
            continue
        recs.append(_rec(
            "data_completion", "primary", "high",
            defn["title"], defn["body"], defn["next_move"],
            context={
                "field": field_name,
                "fields_required": defn["fields_required"],
                "unlocks": defn["unlocks"],
            },
        ))
    return recs


# ─────────────────────────────────────────────────────────────────────
# Archetype suggestion (Part D). Fires when business accounts are
# detected but the user's archetype isn't `"small_business"`. Surface
# the suggestion once per session; persistence is a frontend concern.
# ─────────────────────────────────────────────────────────────────────

def generate_archetype_suggestion(detected_business_accounts: Iterable[str],
                                  current_archetype: str
                                  ) -> Optional[dict]:
    """Return a single archetype-suggestion rec when the user has
    business accounts but isn't on the SB archetype. Returns None
    when the suggestion shouldn't fire (already SB, or no business
    accounts detected).
    """
    accounts = [a for a in (detected_business_accounts or []) if a]
    if not accounts:
        return None
    if current_archetype == "small_business":
        return None

    title = "We see business accounts in your profile"
    body  = ("Switching your archetype to Small Business gives Relius the "
             "right lens for the AR/AP and cash-flow signals on those accounts.")
    next_move = "Update your archetype in settings."
    return _rec(
        "archetype_suggestion", "secondary", "medium",
        title, body, next_move,
        context={
            "detected_business_accounts": list(accounts),
            "current_archetype":  current_archetype,
            "suggested_archetype": "small_business",
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Detection override (Part E). Surfaces when business detection ran
# on a heuristic (medium confidence). Lets the user confirm or
# correct — sticky correction is a frontend / user-state concern,
# the recommendation surface only opens the door.
# ─────────────────────────────────────────────────────────────────────

def generate_detection_overrides(detections: Iterable[dict]) -> list:
    """For each detection dict where is_business=True with confidence
    less than `"high"`, generate a confirmation/override rec.

    Each detection dict shape:
        {
          "account_id":       str,
          "account_name":     str,
          "is_business":      bool,
          "confidence":       "high" | "medium" | "low",
          "source":           str (e.g. "heuristic_subtype"),
        }

    High-confidence detections (e.g., from Plaid `categorization` beta)
    don't surface — they're correct by data, not heuristic.
    """
    recs = []
    for d in (detections or []):
        if not d.get("is_business"):
            continue
        if d.get("confidence") == "high":
            continue
        name   = d.get("account_name", "this account")
        title  = "Is this a business account?"
        body   = (f"We detected '{name}' as a business account. "
                  "If that's not how you use it, you can correct it.")
        next_move = "Confirm or correct in account settings."
        recs.append(_rec(
            "detection_override", "tertiary", d.get("confidence", "medium"),
            title, body, next_move,
            context={
                "account_name":         name,
                "account_id":           d.get("account_id", ""),
                "detected_as":          "business",
                "detection_source":     d.get("source", ""),
                "detection_confidence": d.get("confidence", "medium"),
            },
        ))
    return recs


# ─────────────────────────────────────────────────────────────────────
# Top-level orchestrator. Combines all four generator outputs with
# singular-primary enforcement: data_completion outranks action when
# present, action outranks archetype_suggestion outranks
# detection_override.
# ─────────────────────────────────────────────────────────────────────

def compile_sb_recommendations(inp,
                               result,
                               mapped_fields_dict: Optional[dict] = None,
                               detections: Optional[Iterable[dict]] = None,
                               confidence_overrides: Optional[dict] = None,
                               ) -> list:
    """Compile the full SB recommendation set in the right order.

    Priority cascade:
      1. data_completion recs (block downstream action recs)
      2. action recs (only fire when underlying data is present)
      3. archetype_suggestion (cross-archetype hint)
      4. detection_override (per-account heuristic correction)

    When data_completion recs exist for ar_aging_buckets / ap_pending,
    the corresponding action recs are suppressed (no point recommending
    AR collections when we don't know the user's AR).
    """
    out: list = []

    # Data completion (top of stack — primary)
    dc_recs: list = []
    if mapped_fields_dict:
        dc_recs = generate_data_completion_recommendations(mapped_fields_dict)
    suppressed_triggers = set()
    for r in dc_recs:
        field = r["context"].get("field")
        if field == "ar_aging_buckets":
            suppressed_triggers.add("ar_aging_strain")
        if field == "ap_pending":
            suppressed_triggers.add("ap_compression")
    out.extend(dc_recs)

    # Action recs — but suppress those whose underlying data is missing.
    action_recs = generate_action_recommendations(
        inp, result, confidence_overrides=confidence_overrides,
    )
    action_recs = [
        r for r in action_recs
        if r["context"].get("trigger") not in suppressed_triggers
    ]
    # If a data_completion rec already holds primary, demote action primaries.
    if dc_recs:
        for r in action_recs:
            if r["priority"] == "primary":
                r["priority"] = "secondary"
    out.extend(action_recs)

    # Archetype suggestion
    if detections is not None:
        biz_account_names = [d.get("account_name", "")
                             for d in detections
                             if d.get("is_business")]
        sug = generate_archetype_suggestion(
            biz_account_names, getattr(inp, "archetype", "individual_w2")
        )
        if sug is not None:
            # Demote priority if anything higher already in stack.
            if out and any(r["priority"] == "primary" for r in out):
                pass  # already secondary by default
            out.append(sug)

        # Detection overrides (tertiary)
        out.extend(generate_detection_overrides(detections))

    # Singular-primary final enforcement: if multiple primaries leaked
    # through, demote all but the first (which was generated by the
    # earliest-priority generator in the cascade). Defensive; the
    # cascade above should already maintain this.
    primaries_seen = 0
    for r in out:
        if r["priority"] == "primary":
            primaries_seen += 1
            if primaries_seen > 1:
                r["priority"] = "secondary"

    return out


# ─────────────────────────────────────────────────────────────────────
# Phase 5b.4 — Freelancer recommendations.
#
# Four FL-REC types (action recs):
#   FL-REC-1  Tax reserve actions    (driven by calculate_tax_reserve_status)
#   FL-REC-2  Volatility buffer      (driven by income_volatility + coverage)
#   FL-REC-3  Coverage buffer        (driven by fixed_monthly_obligations)
#   FL-REC-4  Trajectory-aware       (driven by FL-FSS-4 + adequate coverage)
#
# Plus Famine-state recommendations — branched on famine_context.
# tax_reserve_at_risk, the highest-stakes brand-voice surface in the
# project. Every Famine copy string is hand-reviewed in addition to
# the programmatic audit above.
#
# Three data-completion hooks:
#   • freelance_account_separation == "unknown"
#   • income_volatility_observed.source == "manual_entry_required"
#   • tax_reserve_balance == 0 AND quarterly_tax_estimated_amount == 0
#
# Singular-primary discipline holds. The hierarchical priority order
# in `select_primary_freelancer_rec()` resolves multi-primary
# conflicts deterministically.
# ─────────────────────────────────────────────────────────────────────


# Calibration values for FL recommendation triggers. Refined in 5b.5.
_FL_REC_THRESHOLDS = {
    # Volatility floor for "save during good months" recommendations.
    "volatility_for_smoothing":     0.30,
    # Coverage floors (months of fixed obligations covered by liquid).
    "coverage_severe_months":       1.0,
    "coverage_buffer_target_months": 3.0,
    # Trajectory pla floor — FL-FSS-4 above this triggers trajectory
    # recommendations even when current liquid is adequate.
    "trajectory_pla_floor":         0.30,
    # Tax-reserve next-quarterly-due tiering (days).
    "tax_imminent_days":            14,
    "tax_near_days":                60,
}


# Hierarchical priority order for singular-primary resolution.
# Lower index = higher priority. Encoded as triggers used in rec
# context dicts; the selection function maps from triggers to ranks.
_FL_PRIMARY_PRIORITY_ORDER = (
    "famine",                       # 1. Famine state always outranks
    "tax_reserve_uncovered_imminent",  # 2. Quarterly within 14 days
    "coverage_severe",              # 3. < 1 month fixed-obligation coverage
    "tax_reserve_uncovered_near",   # 4. Quarterly within 15-60 days
    "volatility_buffer_no_coverage",   # 5. Vol elevated AND coverage <1mo
    # All other primaries demote to secondary.
)


# ─────────────────────────────────────────────────────────────────────
# Confidence baseline derivation. The recommendation generators read
# `inp.freelance_account_separation` as the source-of-truth for how
# confident we should be in income-derived signals.
#
# Mirrors the 5b.3 mapper's per-source confidence rule:
#   separate_business_account → high  (user-disclosed clean separation)
#   mixed_personal            → medium (heuristic detection on personal)
#   unknown                   → low    (no disclosure → least confident)
# ─────────────────────────────────────────────────────────────────────
def _confidence_baseline_from_separation(inp) -> str:
    sep = getattr(inp, "freelance_account_separation", "unknown") or "unknown"
    return {
        "separate_business_account": "high",
        "mixed_personal":            "medium",
        "unknown":                   "low",
    }.get(sep, "low")


def _hedge_for_confidence(confidence: str, body_direct: str,
                          body_hedged: str) -> str:
    """Return body copy variant appropriate to the confidence level.

    high / medium → direct assertion (no preface, full specificity)
    low           → hedged variant (caller-provided)
    missing       → caller should be emitting data_completion instead

    The hedge is never just a preface like "Based on partial data" —
    it's a complete copy variant the writer hand-authored. This
    prevents grafting a hedge onto copy that asserts a number we
    don't actually have.
    """
    if confidence in ("high", "medium"):
        return body_direct
    return body_hedged


# ─────────────────────────────────────────────────────────────────────
# FL-REC-1 — Tax reserve actions.
#
# Branches on `calculate_tax_reserve_status()` output.status:
#   covered     → no rec (tertiary reinforcement only when budget allows)
#   behind      → secondary "catch up before next quarterly"
#   uncovered   → primary, urgency from next_quarterly_due_in_days
#
# Brand voice: SE tax is non-negotiable, so directness is appropriate.
# Specific numbers are dignified — vague tax language is patronizing.
# ─────────────────────────────────────────────────────────────────────
def _tax_reserve_action(tax_status: dict,
                        confidence: str = "high") -> Optional[dict]:
    status = tax_status.get("status", "covered")
    if status == "covered":
        return None
    days = tax_status.get("next_quarterly_due_in_days")
    target = float(tax_status.get("target_balance", 0) or 0)
    current = float(tax_status.get("current_balance", 0) or 0)
    shortfall = float(tax_status.get("shortfall", 0) or 0)

    if status == "uncovered":
        # Primary tier with three urgency variants.
        if days is not None and days <= _FL_REC_THRESHOLDS["tax_imminent_days"]:
            trigger = "tax_reserve_uncovered_imminent"
            title = "Set aside tax money this week"
            body = (
                f"Your tax reserve is {_money(current, confidence)} of an "
                f"estimated {_money(target, confidence)} target. Your next "
                f"quarterly is due in {days} days."
            )
            next_move = (
                f"Move {_money(shortfall, confidence)} to a tax-reserve "
                "account this week."
            )
        elif days is not None and days <= _FL_REC_THRESHOLDS["tax_near_days"]:
            trigger = "tax_reserve_uncovered_near"
            title = "Build your tax reserve before next quarter"
            weekly = max(50.0, shortfall / max(1, days // 7))
            body = (
                f"Your reserve is {_money(current, confidence)} of an "
                f"estimated {_money(target, confidence)} target. Next "
                f"quarterly is in {days} days — that's about "
                f"{max(1, days // 7)} weeks to catch up."
            )
            next_move = (
                f"Set up a recurring transfer of "
                f"{_money(weekly, confidence)}/week to a tax-reserve account."
            )
        else:
            # >60 days or null → "build the habit now"
            trigger = "tax_reserve_uncovered_far"
            title = "Start building your tax reserve"
            body = (
                f"You have {_money(current, confidence)} reserved against "
                f"an estimated {_money(target, confidence)} owed. Starting "
                "now means smaller monthly transfers than catching up later."
            )
            next_move = (
                "Set up a recurring transfer to a separate "
                "tax-reserve account."
            )
        priority = "primary"
    else:
        # behind → secondary
        trigger = "tax_reserve_behind"
        title = "Catch up on your tax reserve"
        body = (
            f"Your reserve is {_money(current, confidence)} of an estimated "
            f"{_money(target, confidence)} target. You've started — staying "
            "on plan keeps you ahead of next quarter."
        )
        if days is not None and days <= _FL_REC_THRESHOLDS["tax_near_days"]:
            next_move = (
                f"Add {_money(shortfall, confidence)} before your next "
                f"quarterly (due in {days} days)."
            )
        else:
            next_move = (
                f"Add {_money(shortfall, confidence)} over the next two "
                "months to close the gap."
            )
        priority = "secondary"

    return _rec(
        "action", priority, confidence, title, body, next_move,
        context={
            "trigger": trigger,
            "tax_status": status,
            "shortfall": shortfall,
            "next_quarterly_due_in_days": days,
        },
    )


# ─────────────────────────────────────────────────────────────────────
# FL-REC-2 — Volatility buffer-building.
#
# Triggers when income volatility is elevated AND coverage is below
# the 3-month buffer target. The "save during good months" surface.
# Body explicitly references the rolling-average baseline so the user
# feels Relius understands their work pattern.
# ─────────────────────────────────────────────────────────────────────
def _volatility_buffer_action(inp, smoothed_disc: dict,
                              coverage_months: float,
                              confidence: str = "high") -> Optional[dict]:
    vol = getattr(inp, "income_volatility_observed", None)
    if vol is None or float(vol) < _FL_REC_THRESHOLDS["volatility_for_smoothing"]:
        return None
    if coverage_months >= _FL_REC_THRESHOLDS["coverage_buffer_target_months"]:
        return None
    if not (smoothed_disc or {}).get("smoothing_active"):
        return None

    rolling_avg = float((smoothed_disc or {}).get("rolling_avg_used", 0) or 0)
    current_income = float(getattr(inp, "I_gross", 0) or 0)
    surplus = max(0.0, current_income - rolling_avg)
    save_amt = round(surplus * 0.5, 2) if surplus > 0 else round(rolling_avg * 0.05, 2)

    # Severe coverage (<1 month) is its own primary; this rec is
    # secondary unless current month is materially above average AND
    # coverage is below 1 month.
    severe_coverage = coverage_months < _FL_REC_THRESHOLDS["coverage_severe_months"]

    if surplus > 0:
        # Direct (high/medium) variant
        body_direct = (
            f"This month's income is {_money(surplus, confidence)} above "
            f"your typical {_money(rolling_avg, confidence)}. Saving "
            f"{_money(save_amt, confidence)} of that builds toward 3 "
            "months of fixed-obligation coverage."
        )
        # Hedged (low) variant
        body_hedged = (
            f"This month's income looks above your recent average. Setting "
            f"aside {_money(save_amt, confidence)} this month builds buffer "
            "for any thinner months ahead."
        )
        title = "Save what's above your typical this month"
        next_move = (
            f"Transfer {_money(save_amt, confidence)} to liquid savings "
            "while this month's surplus is still in your account."
        )
    else:
        body_direct = (
            f"Your income runs irregularly with about {round(float(vol)*100)}% "
            "month-to-month variation. The months you have surplus are how "
            "you build buffer for the lean ones."
        )
        body_hedged = (
            "Your income shows month-to-month variation. Earmarking part of "
            "stronger months builds buffer for the lean ones."
        )
        title = "Build buffer during your stronger months"
        next_move = (
            "When income comes in above your typical, redirect the "
            "difference to liquid savings before it gets reabsorbed."
        )

    body = _hedge_for_confidence(confidence, body_direct, body_hedged)
    priority = "primary" if severe_coverage else "secondary"
    trigger = ("volatility_buffer_no_coverage" if severe_coverage
               else "volatility_buffer")
    return _rec(
        "action", priority, confidence, title, body, next_move,
        context={
            "trigger": trigger,
            "volatility": float(vol),
            "coverage_months": coverage_months,
            "rolling_avg": rolling_avg,
        },
    )


# ─────────────────────────────────────────────────────────────────────
# FL-REC-3 — Fixed-obligation coverage actions.
#
# Triggers regardless of volatility when coverage_months < 3.
# Severe (<1) → primary; moderate (1-3) → secondary.
# Copy grounds in months, not dollars (the more intuitive frame for
# "how long can I cover my must-pays").
# ─────────────────────────────────────────────────────────────────────
def _coverage_action(coverage_months: float, fixed_obligations: float,
                     buffer_floor: dict,
                     confidence: str = "high") -> Optional[dict]:
    if fixed_obligations <= 0:
        return None

    # Phase 6 polish (Pass 1, WI-1) — gate on the user's per-volatility
    # buffer floor (from `compute_buffer_floor_with_volatility`), not the
    # universal 3.0 month target. The previous static-3.0 gate fired this
    # rec for users whose coverage was already above their personalized
    # floor, producing two related visual bugs:
    #   (1) "Add $-X" negative dollar copy in the next_move
    #   (2) "Reaching N.N months gives you room" where N.N < current
    # Both share root cause: target_months pulled from buffer_floor was
    # less than current coverage. Now: don't fire when above floor.
    target_months = (buffer_floor or {}).get(
        "required_buffer_months",
        _FL_REC_THRESHOLDS["coverage_buffer_target_months"],
    )
    if coverage_months >= target_months:
        return None

    months_str = f"{coverage_months:.1f}"
    target_amount = (buffer_floor or {}).get("required_buffer_amount", 0)
    current_buffer_months = (buffer_floor or {}).get("current_buffer_months",
                                                      coverage_months)

    severe = coverage_months < _FL_REC_THRESHOLDS["coverage_severe_months"]

    if severe:
        title = "Build a coverage buffer this month"
        body = (
            f"You have {months_str} months of fixed costs covered. "
            f"Building toward {round(target_months, 1)} months protects "
            "against any income gap, especially given the volatility we "
            "see in your income."
        )
        next_move = (
            f"Reduce discretionary spending by {_money(fixed_obligations * 0.10, confidence)}/month "
            "and direct it to liquid savings until you reach 1 month of coverage."
        )
        priority = "primary"
        trigger = "coverage_severe"
    else:
        title = "Stretch your coverage toward 3 months"
        body = (
            f"You have {months_str} months of fixed costs covered. "
            f"Reaching {round(target_months, 1)} months gives you room "
            "to weather a slow month without immediate pressure."
        )
        next_move = (
            f"Add {_money(target_amount - (current_buffer_months or 0) * fixed_obligations, confidence)} "
            "over the next few months to liquid savings."
        )
        priority = "secondary"
        trigger = "coverage_moderate"

    return _rec(
        "action", priority, confidence, title, body, next_move,
        context={
            "trigger": trigger,
            "coverage_months": coverage_months,
            "target_months": target_months,
        },
    )


# ─────────────────────────────────────────────────────────────────────
# FL-REC-4 — Trajectory-aware actions.
#
# Triggers when FL-FSS-4 (volatility trajectory) is elevated AND
# coverage is already adequate (≥3 months). The user's runway is OK
# right now, but the trend says preserve rather than grow.
#
# Confidence-driven: low confidence renders "may be declining" rather
# than asserting decline.
# ─────────────────────────────────────────────────────────────────────
def _trajectory_action(inp, trajectory_pla: float, coverage_months: float,
                       confidence: str = "high") -> Optional[dict]:
    if trajectory_pla < _FL_REC_THRESHOLDS["trajectory_pla_floor"]:
        return None
    if coverage_months < _FL_REC_THRESHOLDS["coverage_buffer_target_months"]:
        # Coverage is the bigger issue — let FL-REC-3 handle as primary.
        return None

    fixed = float(getattr(inp, "fixed_monthly_obligations", 0) or 0)
    monthly_trim = round(max(50.0, fixed * 0.05), 2)

    # Direct (high/medium) — assert the trend
    body_direct = (
        f"Your recent income has been declining. With about "
        f"{coverage_months:.1f} months of coverage already, the action is "
        "preserving runway, not growing it."
    )
    # Hedged (low) — frame as "may be"
    body_hedged = (
        "Your recent income may be declining — we have partial data. With "
        f"about {coverage_months:.1f} months of coverage, preserving "
        "runway protects against a longer thin stretch."
    )
    body = _hedge_for_confidence(confidence, body_direct, body_hedged)

    return _rec(
        "action", "secondary", confidence,
        "Stretch your buffer to cover a longer thin period",
        body,
        f"Trim discretionary by {_money(monthly_trim, confidence)}/month "
        "and direct it to liquid savings.",
        context={
            "trigger": "trajectory_decline",
            "trajectory_pla": trajectory_pla,
            "coverage_months": coverage_months,
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Famine-state recommendations.
#
# THE highest-stakes brand-voice surface. Every string below is
# hand-authored and hand-reviewed.
#
# Branches on `famine_context.tax_reserve_at_risk`. Three secondary
# recs always render in Famine to give the user clear priorities
# without overwhelming.
# ─────────────────────────────────────────────────────────────────────

def _famine_primary_protect_tax_reserve(famine_ctx: dict, inp) -> dict:
    """Famine + tax_reserve_at_risk=True. Protect-the-reserve framing."""
    tax_balance = float(getattr(inp, "tax_reserve_balance", 0) or 0)
    next_due = getattr(inp, "quarterly_tax_due_date", None) or "your next quarterly"
    return _rec(
        "action", "primary", "high",
        "Protect your tax reserve",
        ("Your tax reserve is the one obligation you cannot reschedule. "
         "Keeping it untouched protects you from a federal-tax shortfall "
         "later, even when work is light."),
        (f"Keep {_money(tax_balance, 'high')} untouched until {next_due}. "
         "Other discretionary spending is fair to defer right now."),
        context={
            "trigger": "famine",
            "famine_branch": "protect_tax_reserve",
        },
    )


def _famine_primary_focus_essentials(famine_ctx: dict, inp) -> dict:
    """Famine + tax_reserve_at_risk=False. Focus-on-essentials framing.

    The "while work picks back up" registered phrase is the brand
    presumption that work returns. Never written as if extended
    Famine is the new normal.
    """
    runway = famine_ctx.get("estimated_runway_months")
    weeks = round(runway * 4.33) if runway else None
    # Phase 6 polish (Pass 1, WI-3b) — pluralize "week(s)" so a 1-week
    # runway reads "about 1 week" rather than the ungrammatical "1 weeks".
    weeks_phrase = (f"about {weeks} {'week' if weeks == 1 else 'weeks'}" if weeks
                    else "your current liquid savings")
    return _rec(
        "action", "primary", "high",
        "Focus on essentials this period",
        (f"Your runway covers {weeks_phrase} at current spending. Holding "
         "to rent, utilities, groceries, and minimums protects what you "
         "have while work picks back up."),
        "Cover the must-pays this week. Re-evaluate when work picks back up.",
        context={
            "trigger": "famine",
            "famine_branch": "focus_essentials",
            "estimated_runway_months": runway,
        },
    )


def _famine_secondary_pause_subscriptions() -> dict:
    """Reversibility framing — pause is not cancel."""
    return _rec(
        "action", "secondary", "high",
        "Pause subscriptions you can re-enable later",
        ("Recurring costs compound during periods when work is light. "
         "Pausing now and resuming later is reversible — canceling outright "
         "is not."),
        "List your recurring subscriptions and pause the ones you don't need this month.",
        context={
            "trigger": "famine",
            "famine_branch": "pause_subscriptions",
        },
    )


def _famine_secondary_form_1127() -> dict:
    """Real federal hardship option. IRS Form 1127 = Application for
    Extension of Time for Payment of Tax Due to Undue Hardship.
    Extends payment up to 6 months when paying creates hardship.
    """
    return _rec(
        "action", "secondary", "high",
        "Tax payment coming up? IRS Form 1127 can extend it",
        ("If your next quarterly is due soon and paying it would create "
         "genuine hardship, IRS Form 1127 can extend the payment up to "
         "six months."),
        "Look up Form 1127 on IRS.gov. The application takes about 15 minutes.",
        context={
            "trigger": "famine",
            "famine_branch": "form_1127_information",
            "irs_form": "1127",
        },
    )


def _famine_secondary_reach_out_clients() -> dict:
    """Re-engagement framing — leading indicators are conversations,
    not deposits. Specific action."""
    return _rec(
        "action", "secondary", "high",
        "Reach out to your top clients about upcoming work",
        ("The leading indicator of recovery is conversations, not "
         "deposits. A check-in this week may surface work for next month."),
        "Email or message your three most reliable clients.",
        context={
            "trigger": "famine",
            "famine_branch": "client_outreach",
        },
    )


def _generate_famine_recommendations(inp, result) -> list:
    """Generate the Famine-state recommendation set. Called from both
    the LP-infeasibility path (engine_freelancer.populate_famine_context)
    and the income-shortfall path (extend_score_for_freelancer end).

    Output: 1 primary (branched on tax_reserve_at_risk) + 3 secondaries.
    Total: 4 recommendations. Famine users don't need a long list —
    they need clear priorities.
    """
    famine_ctx = ((result.insights or {})
                  .get("freelancer", {})
                  .get("famine_context") or {})
    if not famine_ctx:
        return []

    out: list = []
    if famine_ctx.get("tax_reserve_at_risk"):
        out.append(_famine_primary_protect_tax_reserve(famine_ctx, inp))
    else:
        out.append(_famine_primary_focus_essentials(famine_ctx, inp))

    out.append(_famine_secondary_pause_subscriptions())
    # Form 1127 only mentioned when there's an upcoming quarterly.
    days = getattr(inp, "quarterly_tax_due_date", None)
    if days:
        out.append(_famine_secondary_form_1127())
    out.append(_famine_secondary_reach_out_clients())
    return out


# ─────────────────────────────────────────────────────────────────────
# Three data-completion hooks.
# ─────────────────────────────────────────────────────────────────────

def _fl_data_completion_account_separation(inp) -> Optional[dict]:
    """Hook 1: freelance_account_separation == "unknown"."""
    sep = getattr(inp, "freelance_account_separation", "unknown")
    if sep != "unknown":
        return None
    return _rec(
        "data_completion", "secondary", "high",
        "Tell us how you handle your freelance income",
        ("A separate business account gives us more confidence in scoring "
         "your income volatility and tax-reserve target."),
        "Confirm in settings whether you use a separate business account "
        "or mix freelance with personal banking.",
        context={
            "field": "freelance_account_separation",
            "current_value": sep,
        },
    )


def _fl_data_completion_volatility_history(inp, mapped_volatility) -> Optional[dict]:
    """Hook 2: insufficient income history for volatility computation."""
    if mapped_volatility is None:
        return None
    if not isinstance(mapped_volatility, dict):
        return None
    if mapped_volatility.get("source") != "manual_entry_required":
        return None
    months = (getattr(inp, "months_of_income_history", 0) or 0)
    return _rec(
        "data_completion", "secondary", "high",
        "Add a few more months of income data",
        (f"Right now we have {months} month(s) of income to score against. "
         "Three or more months lets us calibrate to your actual income "
         "patterns."),
        "Connect any additional accounts that hold your freelance income, "
        "or wait a few weeks as new transactions accumulate.",
        context={
            "field": "income_volatility_observed",
            "months_of_history": months,
        },
    )


def _fl_data_completion_tax_setup(inp) -> Optional[dict]:
    """Hook 3: tax_reserve_balance == 0 AND quarterly_tax_estimated_amount == 0."""
    bal = float(getattr(inp, "tax_reserve_balance", 0) or 0)
    qamt = float(getattr(inp, "quarterly_tax_estimated_amount", 0) or 0)
    if bal != 0 or qamt != 0:
        return None
    return _rec(
        "data_completion", "secondary", "high",
        "Tell us about your quarterly tax setup",
        ("Self-employment tax is a real obligation that doesn't show up on "
         "regular employment surfaces. Sharing your quarterly amount lets "
         "us build it into your plan."),
        "Open settings and add your estimated quarterly tax amount and "
        "next due date.",
        context={
            "fields": ["tax_reserve_balance",
                       "quarterly_tax_estimated_amount",
                       "quarterly_tax_due_date"],
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Singular-primary resolution. Hierarchical priority order from the
# brief. Pure function for testability — takes a list of candidate
# recs, returns the same list with at most one priority="primary".
# ─────────────────────────────────────────────────────────────────────

def select_primary_freelancer_rec(candidates: list) -> list:
    """Apply the singular-primary discipline to a list of FL recs.

    The first rec whose `context.trigger` matches an entry in
    `_FL_PRIMARY_PRIORITY_ORDER` keeps `priority="primary"`; other
    primaries demote to `priority="secondary"`. Triggers not in the
    priority order are treated as lowest-rank — they only stay primary
    if no higher-ranked candidate exists.

    Pure function: returns a new list, doesn't mutate inputs.
    """
    out = [dict(r) for r in candidates]
    primary_candidates = [
        (i, r) for i, r in enumerate(out) if r.get("priority") == "primary"
    ]
    if len(primary_candidates) <= 1:
        return out

    def _rank(rec):
        trigger = (rec.get("context") or {}).get("trigger", "")
        for idx, ordered in enumerate(_FL_PRIMARY_PRIORITY_ORDER):
            if trigger == ordered:
                return idx
        return len(_FL_PRIMARY_PRIORITY_ORDER)  # lowest rank

    # Sort candidates by rank ascending; first one keeps primary.
    primary_candidates.sort(key=lambda t: _rank(t[1]))
    keep_idx = primary_candidates[0][0]
    for i, r in primary_candidates[1:]:
        out[i]["priority"] = "secondary"
    return out


# ─────────────────────────────────────────────────────────────────────
# Top-level FL recommendation generator. Called from
# `engine_freelancer.extend_score_for_freelancer()` and from
# `engine_freelancer.populate_famine_context()` (LP-infeasible path).
# ─────────────────────────────────────────────────────────────────────

def generate_freelancer_recommendations(inp, result) -> list:
    """Generate the full Freelancer recommendation set.

    Branches:
      • If famine_context populated → Famine recommendations only
        (1 primary + up to 3 secondaries).
      • Otherwise → 4 FL-REC types (action) + 3 data-completion hooks,
        with singular-primary resolution.

    Confidence is derived from `inp.freelance_account_separation`.

    Returns: a list of recommendation dicts. Singular-primary
    discipline holds: at most one priority="primary".
    """
    # Famine path
    famine_ctx = ((result.insights or {})
                  .get("freelancer", {})
                  .get("famine_context") or {})
    if famine_ctx:
        return _generate_famine_recommendations(inp, result)

    # Non-Famine path
    confidence = _confidence_baseline_from_separation(inp)

    # Pull insights produced by extend_score_for_freelancer
    fl_ins = (result.insights or {}).get("freelancer", {})
    tax_status = fl_ins.get("tax_reserve_status") or {}
    smoothed_disc = fl_ins.get("smoothed_discretionary") or {}
    buffer_floor = fl_ins.get("buffer_floor") or {}

    # Coverage months from buffer_floor (computed in 5b.2 helper)
    coverage_months = float(buffer_floor.get("current_buffer_months") or 0)

    # Trajectory pla from FSS breakdown
    fss_bd = result.fss_breakdown or {}
    traj_pla = float((fss_bd.get("Volatility trajectory") or {}).get("pla", 0))

    # Build candidate list
    candidates: list = []

    rec = _tax_reserve_action(tax_status, confidence=confidence)
    if rec:
        candidates.append(rec)

    fixed = float(getattr(inp, "fixed_monthly_obligations", 0) or 0)
    rec = _coverage_action(coverage_months, fixed, buffer_floor,
                           confidence=confidence)
    if rec:
        candidates.append(rec)

    rec = _volatility_buffer_action(inp, smoothed_disc, coverage_months,
                                    confidence=confidence)
    if rec:
        candidates.append(rec)

    rec = _trajectory_action(inp, traj_pla, coverage_months,
                             confidence=confidence)
    if rec:
        candidates.append(rec)

    # Data-completion hooks
    rec = _fl_data_completion_account_separation(inp)
    if rec:
        candidates.append(rec)
    # Volatility manual-entry hook needs the mapped volatility shape;
    # at scoring time we synthesize it from inp's history depth.
    if (getattr(inp, "income_volatility_observed", None) is None
            and (getattr(inp, "months_of_income_history", 0) or 0) < 3):
        candidates.append(_rec(
            "data_completion", "secondary", "high",
            "Add a few more months of income data",
            (f"Right now we have "
             f"{getattr(inp, 'months_of_income_history', 0) or 0} month(s) "
             "of income to score against. Three or more months lets us "
             "calibrate to your actual income patterns."),
            ("Connect any additional accounts that hold your freelance "
             "income, or wait a few weeks as new transactions accumulate."),
            context={"field": "income_volatility_observed",
                     "months_of_history": getattr(inp, "months_of_income_history", 0) or 0},
        ))
    rec = _fl_data_completion_tax_setup(inp)
    if rec:
        candidates.append(rec)

    # Apply singular-primary discipline
    return select_primary_freelancer_rec(candidates)
