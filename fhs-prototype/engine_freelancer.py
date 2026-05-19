"""
Freelancer archetype scoring extensions — foundation module.

Phase 5b.1 ships only the foundation: the tax-reserve modeling helper
that 5b.2's LP/MILP work will build constraints against. The scoring
extension itself (income-volatility FSS contributor, tax-burden FHS
contributor, fixed-obligation coverage trajectory) lands in 5b.2.

Module layout mirrors `engine_sb.py`:
  • `_FREELANCER_CONFIG` block at top — calibration values.
  • Pure helpers below — no I/O, no side effects.
  • Phase 5b.2 will add `extend_score_for_freelancer(inp, result)`
    that engine.score_individual dispatches into when
    `archetype == "freelancer"`.

Trade-secret discipline
-----------------------
Internal calibration values (default tax-reserve %, status-band
thresholds) live ONLY in `_FREELANCER_CONFIG`. The helper output dict
contains only public-facing values (current_balance, target_balance,
shortfall, days-until-due, amount-due) — no LP weights, no internal
formulation references. Verified field-by-field that no key in the
helper output matches a forbidden substring (`weight`, `objective`,
`slack`, `dual_value`, etc.).
"""
from __future__ import annotations
from datetime import datetime, date
from typing import Optional


# ─────────────────────────────────────────────────────────────────────
# CALIBRATION VALUES — refined in 5b.5 once recommendation generation
# (5b.4) and full Freelancer archetype scenarios are in place.
# ─────────────────────────────────────────────────────────────────────
_FREELANCER_CONFIG = {
    # Default tax-reserve target percentage. 0.30 covers federal income
    # tax + ~15.3% self-employment tax for a typical freelancer with no
    # state income tax. Users in CA / NY / similar high-tax states
    # should configure higher per Phase 6 calibration. Per-user
    # override via `inp.tax_reserve_target_pct`.
    "default_tax_reserve_pct": 0.30,

    # Status band cutoffs (fraction of target balance covered).
    #   covered:    current_balance >= target_balance
    #   behind:     current_balance >= 0.50 × target_balance
    #   uncovered:  current_balance <  0.50 × target_balance
    # The 0.50 split is the calibration knob — half-target signals
    # "we have started but not on plan" vs zero-or-near-zero signals
    # "this isn't being reserved at all." Real-data validation in
    # Phase 6 will refine the split.
    "status_behind_threshold_pct": 0.50,
}


# ─────────────────────────────────────────────────────────────────────
# Tax-reserve modeling helper.
#
# Output contract — STABLE, what 5b.2 / 5b.4 build against:
#   {
#     "status":                     "covered" | "behind" | "uncovered",
#     "current_balance":            float,
#     "target_balance":             float,
#     "shortfall":                  float,    # max(0, target - current)
#     "next_quarterly_due_in_days": int|None,
#     "next_quarterly_amount":      float,
#     "target_pct_used":            float,
#     "recent_income_used":         float,
#   }
#
# Status semantics:
#   • "covered"   — user has saved at least the target. Recommendation
#                   layer treats this as "no action needed" / soft
#                   reinforcement.
#   • "behind"    — user has started saving but is not on plan.
#                   Recommendation layer surfaces a soft nudge.
#   • "uncovered" — user has saved less than half target, OR is at
#                   zero. Recommendation layer surfaces a primary
#                   action (build tax buffer) — high priority because
#                   SE tax is non-negotiable.
#
# The helper is intentionally small and stateless. 5b.2 wraps it in
# the LP constraint that says "owner draws / discretionary spend
# cannot push tax_reserve_balance below the rolling target."
# ─────────────────────────────────────────────────────────────────────

def calculate_tax_reserve_status(inp,
                                 recent_income: Optional[float] = None,
                                 today: Optional[date] = None) -> dict:
    """Assess a Freelancer's tax-reserve status against their target.

    Args:
      inp: an IndividualInput-shaped object. Reads:
        `tax_reserve_balance`, `tax_reserve_target_pct`, `I_gross`,
        `quarterly_tax_due_date`, `quarterly_tax_estimated_amount`.
      recent_income: monthly income basis for target calculation.
        Defaults to `inp.I_gross` (the current monthly gross). For a
        Freelancer with months_of_income_history >= 3, the caller
        SHOULD pass the rolling-average instead — the helper doesn't
        compute the rolling average itself (that's a mapper concern).
      today: date used for `next_quarterly_due_in_days` arithmetic.
        Defaults to `date.today()`. Injectable for tests.

    Returns: the fixed output dict described in the module docstring.
    Defensive on missing fields — a fully default IndividualInput
    returns a coherent zero-state result without raising.
    """
    cfg = _FREELANCER_CONFIG

    target_pct = float(getattr(inp, "tax_reserve_target_pct",
                               cfg["default_tax_reserve_pct"]) or 0)
    if target_pct <= 0:
        target_pct = cfg["default_tax_reserve_pct"]

    income_basis = float(
        recent_income if recent_income is not None
        else (getattr(inp, "I_gross", 0) or 0)
    )

    target_balance  = round(target_pct * income_basis, 2)
    current_balance = round(float(getattr(inp, "tax_reserve_balance", 0) or 0), 2)
    shortfall       = round(max(0.0, target_balance - current_balance), 2)

    # Status band
    behind_split = cfg["status_behind_threshold_pct"]
    if target_balance <= 0:
        # No income basis → no reserve obligation. "covered" vacuously.
        status = "covered"
    elif current_balance >= target_balance:
        status = "covered"
    elif current_balance >= behind_split * target_balance:
        status = "behind"
    else:
        status = "uncovered"

    # Days-until-next-quarterly arithmetic
    days_until: Optional[int] = None
    due_str = getattr(inp, "quarterly_tax_due_date", None)
    if due_str:
        try:
            due = datetime.strptime(str(due_str), "%Y-%m-%d").date()
            anchor = today or date.today()
            days_until = (due - anchor).days
        except (TypeError, ValueError):
            days_until = None

    return {
        "status":                     status,
        "current_balance":            current_balance,
        "target_balance":             target_balance,
        "shortfall":                  shortfall,
        "next_quarterly_due_in_days": days_until,
        "next_quarterly_amount":      round(
            float(getattr(inp, "quarterly_tax_estimated_amount", 0) or 0), 2
        ),
        "target_pct_used":            target_pct,
        "recent_income_used":         round(income_basis, 2),
    }


# ─────────────────────────────────────────────────────────────────────
# Phase 5b.2 — FSS contributors + LP-style projections.
#
# Calibration values for the FSS dim weights and trajectory thresholds.
# Refined in 5b.5. Mirrors `engine_sb._SB_CONFIG` layout.
# ─────────────────────────────────────────────────────────────────────
_FL_CONFIG = {
    # FSS dim weights — sum bounded so FL contributors can push FSS into
    # the 30-50 range without saturating, leaving room for personal-side
    # strain to stack on top.
    "fss_weights": {
        "Income volatility":             0.10,
        "Tax reserve insufficiency":     0.12,
        "Fixed-obligation coverage":     0.10,
        "Volatility trajectory":         0.08,
    },

    # FL-FSS-2 urgency multipliers per quarterly-due window.
    # Applied as: pla_base × (1 + urgency_multiplier).
    "tax_urgency_imminent_days": 14,    # ≤14 days → highest urgency
    "tax_urgency_near_days":     60,    # 15-60 days → moderate urgency
    "tax_urgency_imminent_mult": 0.50,
    "tax_urgency_near_mult":     0.25,

    # FL-FSS-2 base pla per status band.
    "tax_pla_behind":            0.40,
    "tax_pla_uncovered":         0.80,

    # FL-FSS-3 fixed-obligation coverage strain ramp.
    # Severe (pla=1.0) when coverage < severe_months; moderate (pla=0.5)
    # at the moderate breakpoint; zero at safe_months and above.
    "coverage_severe_months":    1.0,
    "coverage_moderate_months":  3.0,
    "coverage_safe_months":      3.0,   # = moderate; above this → 0 strain

    # FL-LP-3 volatility threshold above which discretionary smoothing
    # kicks in. 0.30 covers "moderately volatile" — chosen because
    # below this the boom-bust risk is small enough that smoothing
    # would feel paternalistic. Above this, the user materially
    # benefits from being told "spend against your average, not this
    # month's income."
    "volatility_threshold_for_smoothing": 0.30,

    # FL-LP-2 buffer-floor scaling under high volatility.
    # Base requirement: 1 month of fixed_monthly_obligations.
    # Volatility uplift: at vol=1.0, require an additional volatility
    # multiplier × base months. Linear ramp from 0..1 across 0..1 vol.
    "buffer_volatility_uplift_max_months": 2.0,

    # Minimum income-history months required before we trust the
    # volatility signals. Below this, FL-FSS-1 + FL-FSS-4 are
    # confidence=missing with zero strain (honest data architecture).
    "min_history_for_volatility_months": 3,
}


# ─────────────────────────────────────────────────────────────────────
# FSS contributors — pure functions. Each returns either a pla in 0..1
# or None (when confidence is missing).
# ─────────────────────────────────────────────────────────────────────

def _compute_volatility_strain(inp) -> "tuple[float | None, str]":
    """FL-FSS-1. Income volatility coefficient. Returns (pla, confidence).
    Confidence is "missing" when months_of_income_history < threshold."""
    history = int(getattr(inp, "months_of_income_history", 0) or 0)
    if history < _FL_CONFIG["min_history_for_volatility_months"]:
        return (None, "missing")
    vol = getattr(inp, "income_volatility_observed", None)
    if vol is None:
        # Fall back to weighted-average of source volatilities if we can.
        sources = getattr(inp, "income_sources", []) or []
        if not sources:
            return (None, "missing")
        weights = [float(s.get("monthly_average", 0) or 0) for s in sources]
        vols    = [float(s.get("volatility_coefficient", 0) or 0) for s in sources]
        total_w = sum(weights)
        if total_w <= 0:
            return (None, "missing")
        vol = sum(w * v for w, v in zip(weights, vols)) / total_w
    return (max(0.0, min(1.0, float(vol))), "high")


def _compute_tax_reserve_strain(inp) -> float:
    """FL-FSS-2. Tax reserve insufficiency, weighted by quarterly proximity.
    Driven by the helper output from `calculate_tax_reserve_status`."""
    status_dict = calculate_tax_reserve_status(inp)
    status = status_dict["status"]
    days   = status_dict["next_quarterly_due_in_days"]

    if status == "covered":
        return 0.0

    # Urgency: more strain as the quarterly date approaches.
    cfg = _FL_CONFIG
    if days is not None and days <= cfg["tax_urgency_imminent_days"]:
        urgency = cfg["tax_urgency_imminent_mult"]
    elif days is not None and days <= cfg["tax_urgency_near_days"]:
        urgency = cfg["tax_urgency_near_mult"]
    else:
        urgency = 0.0

    base = (cfg["tax_pla_behind"] if status == "behind"
            else cfg["tax_pla_uncovered"])
    return min(1.0, base * (1.0 + urgency))


def _compute_coverage_strain(inp) -> float:
    """FL-FSS-3. Fixed-obligation coverage shortfall. Months of fixed
    obligations covered by liquid savings + buffer above tax target.
    Severe when coverage < 1 month; zero at 3+ months."""
    fixed = float(getattr(inp, "fixed_monthly_obligations", 0) or 0)
    if fixed <= 0:
        # No fixed obligations declared → no coverage signal.
        return 0.0
    s_liq = float(getattr(inp, "S_liq", 0) or 0)
    tax_balance = float(getattr(inp, "tax_reserve_balance", 0) or 0)
    tax_status  = calculate_tax_reserve_status(inp)
    tax_target  = float(tax_status.get("target_balance", 0) or 0)
    # Only the portion of tax reserve ABOVE its own target counts as
    # discretionary buffer — the at-target portion is committed.
    available_buffer = max(0.0, tax_balance - tax_target)
    coverage_months = (s_liq + available_buffer) / fixed

    cfg = _FL_CONFIG
    severe   = cfg["coverage_severe_months"]
    moderate = cfg["coverage_moderate_months"]
    safe     = cfg["coverage_safe_months"]
    if coverage_months >= safe:
        return 0.0
    if coverage_months <= severe:
        return 1.0
    # Linear ramp severe..moderate → 1.0..0.5, then moderate..safe → 0.5..0
    if coverage_months <= moderate:
        # severe..moderate range → pla 1.0..0.5
        span = moderate - severe
        if span <= 0:
            return 1.0
        progress = (coverage_months - severe) / span
        return max(0.5, 1.0 - 0.5 * progress)
    return 0.0


def _compute_volatility_trajectory_strain(inp) -> "tuple[float | None, str]":
    """FL-FSS-4. Negative trajectory of recent income. Returns (pla, confidence).

    Phase 5b.2 design note: the `IndividualInput` schema doesn't carry
    a per-month income time series (5b.1 deliberately deferred that to
    Phase 6). As a pragmatic proxy, we use `inp.momentum_slope` —
    defined as "linear-regression slope of recent score history."
    For Freelancers, score trajectory tracks income trajectory closely
    enough for the directional signal. Phase 6 income-time-series
    storage will replace this with a true income-slope computation.

    Confidence is "missing" when months_of_income_history < threshold.
    """
    history = int(getattr(inp, "months_of_income_history", 0) or 0)
    if history < _FL_CONFIG["min_history_for_volatility_months"]:
        return (None, "missing")
    slope = float(getattr(inp, "momentum_slope", 0) or 0)
    if slope >= 0:
        return (0.0, "high")
    # Negative slope → pla scales 0..1 as slope goes 0..-1.
    pla = min(1.0, abs(slope))
    return (pla, "high")


# ─────────────────────────────────────────────────────────────────────
# LP-style projections. Following 5a.2's framing: forward-simulation /
# feasibility outputs that the FSS contributors and recommendation
# layer consume. No new PuLP variables added to the existing solver.
# ─────────────────────────────────────────────────────────────────────

def compute_smoothed_discretionary_max(inp) -> "dict":
    """FL-LP-3. Volatility-aware allocation smoothing. When volatility
    is elevated, recommended discretionary spend is capped at
    (rolling_avg_income - fixed_obligations - tax_reserve_target),
    not this-month's-income. Prevents the boom-bust cycle.

    Returns: {smoothing_active: bool, max_discretionary: float,
              rolling_avg_used: float, threshold: float}.
    """
    cfg = _FL_CONFIG
    threshold = cfg["volatility_threshold_for_smoothing"]
    vol = getattr(inp, "income_volatility_observed", None)
    rolling_avg = float(getattr(inp, "I_gross", 0) or 0)
    fixed = float(getattr(inp, "fixed_monthly_obligations", 0) or 0)
    tax_target = float(rolling_avg) * float(
        getattr(inp, "tax_reserve_target_pct",
                _FREELANCER_CONFIG["default_tax_reserve_pct"]) or 0
    )
    smoothing_active = vol is not None and float(vol) >= threshold
    max_disc = max(0.0, rolling_avg - fixed - tax_target)
    return {
        "smoothing_active": smoothing_active,
        "max_discretionary": round(max_disc, 2),
        "rolling_avg_used":  round(rolling_avg, 2),
        "threshold":         threshold,
    }


def compute_buffer_floor_with_volatility(inp) -> "dict":
    """FL-LP-2. Required liquid buffer floor, scaled by volatility.
    Base: 1 month of fixed obligations. Volatility uplift: up to
    `buffer_volatility_uplift_max_months` extra months at vol=1.0,
    linear ramp.

    Returns: {required_buffer_months, required_buffer_amount,
              current_buffer_months, shortfall, volatility_used}.
    """
    cfg = _FL_CONFIG
    fixed = float(getattr(inp, "fixed_monthly_obligations", 0) or 0)
    s_liq = float(getattr(inp, "S_liq", 0) or 0)
    vol = getattr(inp, "income_volatility_observed", None)
    vol_used = float(vol) if vol is not None else 0.0
    base_months = 1.0
    uplift = cfg["buffer_volatility_uplift_max_months"] * vol_used
    required_months = base_months + uplift
    required_amount = required_months * fixed
    current_months = (s_liq / fixed) if fixed > 0 else float("inf")
    shortfall = max(0.0, required_amount - s_liq)
    return {
        "required_buffer_months":  round(required_months, 2),
        "required_buffer_amount":  round(required_amount, 2),
        "current_buffer_months":   round(current_months, 2)
                                    if current_months != float("inf") else None,
        "shortfall":               round(shortfall, 2),
        "volatility_used":         round(vol_used, 3),
    }


def compute_famine_context(inp, result) -> "dict":
    """FL-LP-4. Structured Famine context for downstream framing.
    Populated when the engine returns floor scores via either the
    LP-infeasibility branch OR the income-shortfall override.

    Output contract — STABLE, what 5b.4 builds against:
      {
        "uncovered_obligations":    float,
        "fixed_obligations_total":  float,
        "minimum_protected":        float,
        "tax_reserve_at_risk":      bool,
        "estimated_runway_months":  float,
      }
    """
    i_net = float(getattr(inp, "I_net", 0) or 0)
    e_ess = float(getattr(inp, "E_ess", 0) or 0)
    d_min = float(getattr(inp, "D_min", 0) or 0)
    fixed = float(getattr(inp, "fixed_monthly_obligations", 0) or 0)
    s_liq = float(getattr(inp, "S_liq", 0) or 0)
    tax_balance = float(getattr(inp, "tax_reserve_balance", 0) or 0)

    # Use fixed_monthly_obligations when set; fall back to E_ess + D_min.
    obligations_total = fixed if fixed > 0 else (e_ess + d_min)
    uncovered = max(0.0, obligations_total - i_net)

    # Tax reserve at risk if income < obligations AND user is currently
    # holding tax reserve that could be tempted to drain.
    tax_at_risk = (i_net < obligations_total) and (tax_balance > 0)

    # Runway: how many months of obligations are funded by liquid only.
    runway = (s_liq / obligations_total) if obligations_total > 0 else float("inf")
    runway_out = round(runway, 2) if runway != float("inf") else None

    return {
        "uncovered_obligations":   round(uncovered, 2),
        "fixed_obligations_total": round(obligations_total, 2),
        "minimum_protected":       round(e_ess, 2),
        "tax_reserve_at_risk":     bool(tax_at_risk),
        "estimated_runway_months": runway_out,
    }


# ─────────────────────────────────────────────────────────────────────
# Main extension entry points. Called from engine.score_individual when
# `inp.archetype == "freelancer"`.
# ─────────────────────────────────────────────────────────────────────

def populate_famine_context(inp, result) -> None:
    """Set `result.insights["freelancer"]["famine_context"]` for the
    LP-infeasibility (Famine) path. Called from the early-return branch
    in score_individual; the full extension function isn't safe to run
    on an infeasible LP solution because the FSS recompute would be
    over a degenerate breakdown.

    Phase 5b.4 — also generates the Famine-state recommendations and
    prepends them to result.recommendations. Both LP-infeasibility and
    income-shortfall paths converge on the same Famine-rec set.
    """
    if getattr(inp, "archetype", None) != "freelancer":
        return
    # Defensive: result.insights is initialized as {} on ScoreResult.
    # Don't use `(result.insights or {})` — empty dict is falsy in
    # Python and the short-circuit creates a throwaway dict. (See
    # CLAUDE.md §7 architectural rule on defensive shorthand idioms.)
    if result.insights is None:
        result.insights = {}
    fl = result.insights.setdefault("freelancer", {})
    fl["famine_context"] = compute_famine_context(inp, result)

    # Famine recommendations — branched on tax_reserve_at_risk inside
    # the recommendation generator. Prepend so they appear ahead of
    # any legacy "close the gap" recommendation the engine generated
    # at the LP-infeasibility floor-score branch.
    from recommendations import generate_freelancer_recommendations
    famine_recs = generate_freelancer_recommendations(inp, result)
    if famine_recs:
        # Demote any pre-existing primary (legacy or otherwise) to
        # secondary — the Famine primary is the singular primary now.
        for r in (result.recommendations or []):
            if isinstance(r, dict):
                if r.get("priority") == "primary":
                    r["priority"] = "secondary"
                elif r.get("priority") == 1:   # legacy numeric
                    r["priority"] = 2
        result.recommendations = famine_recs + (result.recommendations or [])


def extend_score_for_freelancer(inp, result) -> None:
    """Mutate `result` in place: add FL-FSS contributors to
    `result.fss_breakdown`, recompute `result.fss`, stash forward
    projections under `result.insights["freelancer"]`, and populate
    `famine_context` if the income-shortfall override fired.

    No-op for non-Freelancer archetypes — defensive guard at the top.
    """
    if getattr(inp, "archetype", None) != "freelancer":
        return

    fss_breakdown = result.fss_breakdown
    weights = _FL_CONFIG["fss_weights"]

    vol_pla, vol_conf = _compute_volatility_strain(inp)
    tax_pla = _compute_tax_reserve_strain(inp)
    cov_pla = _compute_coverage_strain(inp)
    traj_pla, traj_conf = _compute_volatility_trajectory_strain(inp)

    # Income volatility (FL-FSS-1)
    vol_weighted = (vol_pla * weights["Income volatility"]
                    if vol_pla is not None else 0.0)
    fss_breakdown["Income volatility"] = {
        "pla": round(vol_pla, 3) if vol_pla is not None else 0,
        "weighted": round(vol_weighted, 4),
        "confidence": vol_conf,
    }

    # Tax reserve insufficiency (FL-FSS-2)
    tax_weighted = tax_pla * weights["Tax reserve insufficiency"]
    fss_breakdown["Tax reserve insufficiency"] = {
        "pla": round(tax_pla, 3),
        "weighted": round(tax_weighted, 4),
    }

    # Fixed-obligation coverage shortfall (FL-FSS-3)
    cov_weighted = cov_pla * weights["Fixed-obligation coverage"]
    fss_breakdown["Fixed-obligation coverage"] = {
        "pla": round(cov_pla, 3),
        "weighted": round(cov_weighted, 4),
    }

    # Volatility trajectory (FL-FSS-4)
    traj_weighted = (traj_pla * weights["Volatility trajectory"]
                     if traj_pla is not None else 0.0)
    fss_breakdown["Volatility trajectory"] = {
        "pla": round(traj_pla, 3) if traj_pla is not None else 0,
        "weighted": round(traj_weighted, 4),
        "confidence": traj_conf,
    }

    # Recompute FSS = 100 × min(1, total_weighted × asym_mult)
    asym = (fss_breakdown.get("_asymmetry") or {}).get("multiplier", 1.0)
    total_weighted = sum(
        float(v.get("weighted", 0))
        for k, v in fss_breakdown.items()
        if not k.startswith("_") and isinstance(v, dict)
    )
    new_fss = round(100 * min(1.0, max(0.0, total_weighted * asym)))
    result.fss = new_fss

    # FL-LP-style projections — stashed for 5b.4 recommendation gen.
    fl_insights = result.insights.setdefault("freelancer", {})
    fl_insights["tax_reserve_status"] = calculate_tax_reserve_status(inp)
    fl_insights["smoothed_discretionary"] = compute_smoothed_discretionary_max(inp)
    fl_insights["buffer_floor"] = compute_buffer_floor_with_volatility(inp)

    # Famine context — populated whenever income-shortfall fired (the
    # override that runs when LP succeeded but I_net < E_ess + D_min).
    if getattr(result, "income_shortfall", None):
        fl_insights["famine_context"] = compute_famine_context(inp, result)

    # Phase 5b.4 — generate FL recommendations. The generator branches
    # internally: famine_context populated → Famine recs; otherwise →
    # 4 FL-REC types + data-completion hooks. Singular-primary
    # discipline is enforced inside.
    from recommendations import generate_freelancer_recommendations
    fl_recs = generate_freelancer_recommendations(inp, result)
    if fl_recs:
        # If any FL rec is primary, demote pre-existing primaries
        # (legacy Individual recs that ran before this dispatch).
        if any(r.get("priority") == "primary" for r in fl_recs):
            for legacy in (result.recommendations or []):
                if isinstance(legacy, dict):
                    if legacy.get("priority") == 1:
                        legacy["priority"] = 2
                    elif legacy.get("priority") == "primary":
                        legacy["priority"] = "secondary"
        # Prepend FL recs so they render first.
        result.recommendations = fl_recs + (result.recommendations or [])
