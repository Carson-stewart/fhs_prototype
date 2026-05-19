"""
Small Business archetype scoring extensions.

Phase 5a.2 — additive layer on top of the Individual W-2 scoring path.
Activated by `inp.archetype == "small_business"`. The Individual path
remains unchanged; this module only fires for SB profiles.

Two extensions:

  1. SB-specific FSS contributors (AR aging, AP compression, LOC
     utilization, payroll coverage). Same pla × weight × asym pattern
     as the existing FSS dimensions in engine.compute_fss — stored in
     `result.fss_breakdown` so the existing scrubber + contribution_pct
     pipeline picks them up automatically.

  2. SB-specific forward projections (AR collection trajectory, LOC
     trajectory, AP schedule, owner-draw sustainability). Stored under
     `result.insights["small_business"]` for consumption by 5a.4
     recommendation generation.

LP framing note
---------------
The 5a.2 brief specified "LP/MILP constraint extensions" with new
variables and constraints. On close reading the SB-LP-1..5 are
projection / feasibility computations, not allocation decisions —
the existing PuLP solver optimizes how disposable income is split
across EF/savings/debt/etc., and the SB extensions forecast what
happens to AR/AP/LOC under those allocations. Implemented here as
deterministic forward simulations (O(periods)) rather than PuLP
variables. This keeps the LP solver footprint stable (no risk of
infeasibility regression on existing scenarios) and still produces
all the signals the SB-FSS contributors and 5a.4 recommendations
need. If 5a.5 calibration shows joint optimization across personal
allocation + business projections is required, that's a true MILP
refactor — flagged in the report-back.

Trade-secret discipline
-----------------------
- SB-FSS contributors store `pla` + `weighted`. The existing
  `_scrub_breakdowns_for_api` strips `weighted` from FSS dims and
  injects `contribution_pct` — new contributors are picked up
  automatically because they live in `result.fss_breakdown` with
  the same shape as existing dims.
- Internal calibration values (collection rates, strain thresholds,
  weight values) live ONLY in `_SB_CONFIG` below, never serialized
  in any projection output. Verified field-by-field that every key
  in the projection dicts is scrubber-safe (no forbidden substring
  such as "weight", "objective", "slack").
"""
from __future__ import annotations
from typing import Optional


# ─────────────────────────────────────────────────────────────────────
# CALIBRATION VALUES — refined in 5a.5 once recommendation generation
# (5a.4) and full archetype scenarios are in place. Every value below
# is a starting estimate, NOT a final tuned weight. Documented inline
# so a future calibrator knows what each lever does and what direction
# to push it.
# ─────────────────────────────────────────────────────────────────────
_SB_CONFIG = {
    # AR aging strain — per-bucket multiplier on outstanding receivables.
    # 90+ days is treated as functionally locked-up cash (full strain
    # weight); current invoices contribute zero strain.
    "ar_strain_weights": {
        "current":      0.00,
        "30_days":      0.30,
        "60_days":      0.60,
        "90_plus_days": 1.00,
    },
    # AR collection rate per bucket per period — used by the AR collection
    # trajectory projection. Probability that an outstanding receivable in
    # this bucket is collected during the next period (the rest ages
    # forward by one bucket).
    #   • current → 80% collect, 20% age to 30d
    #   • 30d     → 60% collect, 40% age to 60d
    #   • 60d     → 30% collect, 70% age to 90+
    #   • 90+     → 10% collect, 90% remains 90+ (functionally bad debt)
    # SBA / industry benchmarks — refine with real client data in 5a.5.
    "ar_collection_rates": {
        "current":      0.80,
        "30_days":      0.60,
        "60_days":      0.30,
        "90_plus_days": 0.10,
    },
    # LOC utilization strain — 0..70% maps linearly to 0..0.4 strain;
    # 70..100% maps linearly to 0.4..1.0 strain. The 70% breakpoint is
    # the SBA underwriting indicator: LOCs above 70% utilization signal
    # real distress in standard credit risk models.
    "loc_strain_threshold_pct":   0.70,
    "loc_strain_below_threshold": 0.40,
    # Payroll coverage strain — weeks of payroll covered by S_liq.
    #   • >= elevated weeks   → strain 0
    #   • <= severe weeks     → strain 1
    #   • between             → linear ramp 1..0
    # Severe = 2 weeks (one missed payroll cycle from now);
    # elevated = 4 weeks (one month).
    "payroll_severe_weeks":   2.0,
    "payroll_elevated_weeks": 4.0,
    # Tax reserve assumption per business structure — used by owner-draw
    # sustainability check. Sole prop / LLC owe self-employment tax
    # quarterly; S-corp owners pay W-2 themselves with less variability;
    # C-corp pays corporate + dividend.
    "tax_reserve_pct_by_structure": {
        "sole_proprietor": 0.25,
        "llc":             0.25,
        "s_corp":          0.20,
        "c_corp":          0.21,
        "partnership":     0.25,
        "other":           0.25,
    },
    # SB-FSS dimension weights. Each contributes up to its weight × asym
    # to the FSS sum. Sum across all four = 0.40, intentionally bounded
    # so SB strain on its own can push FSS into the 30-50 range without
    # by itself saturating FSS at 100. Personal-side strain still adds
    # on top per the existing compute_fss components.
    "fss_weights": {
        "AR aging strain":         0.10,
        "AP compression strain":   0.12,
        "LOC utilization strain":  0.10,
        "Payroll coverage strain": 0.08,
    },
    # Cycles-per-month conversion for payroll periodicity. Used to
    # convert payroll_amount_per_cycle → monthly equivalent.
    "payroll_cycles_per_month": {
        "weekly":       4.33,
        "biweekly":     2.17,
        "semimonthly":  2.00,
        "monthly":      1.00,
        "none":         0.00,
    },
    # Forward-projection horizon (periods ≈ months) for AR / LOC traj.
    "default_planning_horizon_months": 6,
}


# ─────────────────────────────────────────────────────────────────────
# SB-FSS contributors — pure functions. Each returns a `pla` value
# (bounded 0..1) representing the saturation of that strain dimension.
# The caller multiplies by the dimension weight and the asymmetry
# multiplier to get the contribution to FSS.
# ─────────────────────────────────────────────────────────────────────

def _compute_ar_aging_strain(inp) -> float:
    """SB-FSS-1. Weighted aging of receivables. 1.0 = entire AR is 90+
    days aged (functionally bad debt)."""
    buckets = inp.ar_aging_buckets or {}
    total_ar = sum(float(buckets.get(k, 0)) for k in
                   ("current", "30_days", "60_days", "90_plus_days"))
    if total_ar <= 0:
        return 0.0
    weights = _SB_CONFIG["ar_strain_weights"]
    weighted_ar = sum(float(buckets.get(k, 0)) * w
                      for k, w in weights.items())
    return min(1.0, max(0.0, weighted_ar / total_ar))


def _compute_ap_compression_strain(inp) -> float:
    """SB-FSS-2. Ratio of near-term payables (due_within_7d + overdue)
    to liquid reserves. ≥1.0 means immediate-pressure payables exceed
    all liquid reserves — the canonical small-business cash crunch."""
    ap = inp.ap_pending or {}
    near_term = float(ap.get("due_within_7d", 0)) + float(ap.get("overdue", 0))
    if near_term <= 0:
        return 0.0
    if inp.S_liq <= 0:
        return 1.0
    return min(1.0, near_term / inp.S_liq)


def _compute_loc_utilization_strain(inp) -> float:
    """SB-FSS-3. Weighted utilization across all business lines of
    credit. Non-linear above the 70% SBA-distress threshold."""
    lines = inp.business_lines_of_credit or []
    if not lines:
        return 0.0
    total_balance = sum(float(line.get("balance", 0)) for line in lines)
    total_limit   = sum(float(line.get("limit", 0))   for line in lines)
    if total_limit <= 0:
        return 0.0
    util = total_balance / total_limit
    threshold = _SB_CONFIG["loc_strain_threshold_pct"]
    below_max = _SB_CONFIG["loc_strain_below_threshold"]
    if util <= threshold:
        # Linear ramp 0..below_max across 0..threshold
        return below_max * (util / threshold)
    # Non-linear above threshold: below_max..1.0 across threshold..1.0
    return below_max + (1.0 - below_max) * ((util - threshold) / (1.0 - threshold))


def _compute_payroll_coverage_strain(inp) -> float:
    """SB-FSS-4. Inverted: weeks of payroll obligations covered by
    liquid reserves. Severe strain when coverage drops below 2 weeks
    (one missed payroll cycle); zero strain at 4+ weeks (one month)."""
    cpm = _SB_CONFIG["payroll_cycles_per_month"].get(
        inp.payroll_periodicity, 0.0)
    monthly_payroll = cpm * float(inp.payroll_amount_per_cycle or 0)
    if monthly_payroll <= 0:
        # No payroll obligations → no strain on this dimension. (Solo
        # owner-operators with no employees fall here.)
        return 0.0
    if inp.S_liq <= 0:
        return 1.0
    weeks_of_coverage = (inp.S_liq / monthly_payroll) * 4.33
    severe   = _SB_CONFIG["payroll_severe_weeks"]
    elevated = _SB_CONFIG["payroll_elevated_weeks"]
    if weeks_of_coverage >= elevated:
        return 0.0
    if weeks_of_coverage <= severe:
        return 1.0
    # Linear ramp severe..elevated → 1..0
    return 1.0 - (weeks_of_coverage - severe) / (elevated - severe)


# ─────────────────────────────────────────────────────────────────────
# SB forward projections (LP-style, deterministic). Outputs become
# `result.insights["small_business"]` for 5a.4 recommendation
# generation.
# ─────────────────────────────────────────────────────────────────────

def simulate_ar_collection_trajectory(inp, periods: Optional[int] = None) -> list:
    """SB-LP-1. Forward-project AR aging buckets over N periods.

    Bucket transitions: in each period a fraction collects (per
    `_SB_CONFIG["ar_collection_rates"]`) and the rest ages forward by
    one bucket. 90+ aged that doesn't collect stays 90+ (functionally
    bad debt). No new invoices are added in this projection — it
    answers "what happens to current AR if we collect nothing new
    over the planning horizon?"

    Returns: list of {period, current, 30_days, 60_days, 90_plus_days,
    collected_this_period}, period 0 = starting state.
    """
    if periods is None:
        periods = _SB_CONFIG["default_planning_horizon_months"]
    rates = _SB_CONFIG["ar_collection_rates"]
    buckets = inp.ar_aging_buckets or {}
    state = {
        "current":      float(buckets.get("current", 0)),
        "30_days":      float(buckets.get("30_days", 0)),
        "60_days":      float(buckets.get("60_days", 0)),
        "90_plus_days": float(buckets.get("90_plus_days", 0)),
    }
    trajectory = [{
        "period": 0,
        "current":      round(state["current"], 2),
        "30_days":      round(state["30_days"], 2),
        "60_days":      round(state["60_days"], 2),
        "90_plus_days": round(state["90_plus_days"], 2),
        "collected_this_period": 0.0,
    }]
    for p in range(1, periods + 1):
        coll_cur = state["current"]      * rates["current"]
        coll_30  = state["30_days"]      * rates["30_days"]
        coll_60  = state["60_days"]      * rates["60_days"]
        coll_90  = state["90_plus_days"] * rates["90_plus_days"]
        total_collected = coll_cur + coll_30 + coll_60 + coll_90
        new_state = {
            # No new invoices in this projection.
            "current":      0.0,
            "30_days":      state["current"]      - coll_cur,
            "60_days":      state["30_days"]      - coll_30,
            "90_plus_days": (state["60_days"] - coll_60)
                            + (state["90_plus_days"] - coll_90),
        }
        state = new_state
        trajectory.append({
            "period": p,
            "current":      round(state["current"], 2),
            "30_days":      round(state["30_days"], 2),
            "60_days":      round(state["60_days"], 2),
            "90_plus_days": round(state["90_plus_days"], 2),
            "collected_this_period": round(total_collected, 2),
        })
    return trajectory


def simulate_loc_trajectory(inp, periods: Optional[int] = None) -> list:
    """SB-LP-4. Project per-LOC balance over N periods assuming current
    interest-only carry (no new draws, no principal pay-down). Surfaces
    the natural decay/growth trajectory under default behavior — a
    rising trajectory at constant inputs is a strong tightening signal.

    Returns: one entry per LOC with {name, limit, starting_balance,
    projected_balances, utilization_pct_start, utilization_pct_end}.
    Internal `apr` value not surfaced (calibration data).
    """
    if periods is None:
        periods = _SB_CONFIG["default_planning_horizon_months"]
    out = []
    for line in (inp.business_lines_of_credit or []):
        balance = float(line.get("balance", 0))
        limit   = float(line.get("limit", 0))
        apr     = float(line.get("apr", 0))
        # Interest-only carry: balance grows by balance × (apr/12) per month.
        path = [round(balance, 2)]
        b = balance
        for _ in range(periods):
            b = b * (1 + apr / 12)
            path.append(round(b, 2))
        util_start = round(balance / limit * 100, 1) if limit > 0 else 0.0
        util_end   = round(path[-1] / limit * 100, 1) if limit > 0 else 0.0
        out.append({
            "name": line.get("name", "LOC"),
            "limit": round(limit, 2),
            "starting_balance": round(balance, 2),
            "projected_balances": path,
            "utilization_pct_start": util_start,
            "utilization_pct_end":   util_end,
        })
    return out


def simulate_ap_schedule(inp) -> dict:
    """SB-LP-2. Build a 4-week AP payment schedule from `ap_pending`.
    `due_within_7d` is non-deferrable; `due_8_to_30d` spreads weeks 2-4;
    `overdue` enters catch-up across weeks 1-3.

    This is intentionally simple — the recommendation layer in 5a.4
    will translate the schedule + payable amounts into a "defer
    non-critical payables" / "catch up overdue" next-move."""
    ap = inp.ap_pending or {}
    due_7    = float(ap.get("due_within_7d", 0))
    due_8_30 = float(ap.get("due_8_to_30d", 0))
    overdue  = float(ap.get("overdue", 0))
    schedule = [
        {"week": 1, "payment": round(due_7 + overdue * 0.50, 2),
         "category": "due_within_7d + overdue catch-up (50%)"},
        {"week": 2, "payment": round(due_8_30 * 0.50 + overdue * 0.30, 2),
         "category": "due_8_to_30d (50%) + overdue (30%)"},
        {"week": 3, "payment": round(due_8_30 * 0.30 + overdue * 0.20, 2),
         "category": "due_8_to_30d (30%) + overdue (final 20%)"},
        {"week": 4, "payment": round(due_8_30 * 0.20, 2),
         "category": "due_8_to_30d (20%) — tail"},
    ]
    return {
        "schedule": schedule,
        "total_required":  round(due_7 + due_8_30 + overdue, 2),
        "total_scheduled": round(sum(s["payment"] for s in schedule), 2),
        "overdue_carrying": overdue > 0,
    }


def assess_owner_draw_sustainability(inp) -> dict:
    """SB-LP-3. Determine whether the configured owner draw is feasible
    given revenue, near-term obligations, and tax reserve.

    Compares `inp.owner_draw_amount` against
        revenue − tax_reserve − near-term_obligations
    where `revenue` is `inp.I_gross` (interpreted as monthly business
    income for an SB owner) and tax_reserve % is structure-dependent.

    Returns a dict with `sustainable`, `max_sustainable_draw`,
    `headroom`, and contextual values. Internal calibration values
    (tax_reserve_pct) are surfaced because they're public-knowledge
    benchmarks (see SBA / IRS guidance), not LP weights.
    """
    if (inp.owner_draw_amount or 0) <= 0:
        return {
            "sustainable": True,
            "reason": "no_owner_draws",
            "max_sustainable_draw": 0.0,
            "current_draw": 0.0,
            "headroom": 0.0,
        }
    structure = (inp.business_structure or "other")
    tax_pct = _SB_CONFIG["tax_reserve_pct_by_structure"].get(structure, 0.25)
    revenue = float(inp.I_gross or 0)
    tax_reserve = revenue * tax_pct
    # Near-term obligations — the AP coming due plus the LOC interest
    # the owner needs to service this month.
    ap = inp.ap_pending or {}
    near_term_ap = (float(ap.get("due_within_7d", 0))
                    + float(ap.get("due_8_to_30d", 0)))
    loc_interest = sum(
        float(L.get("balance", 0)) * (float(L.get("apr", 0)) / 12.0)
        for L in (inp.business_lines_of_credit or [])
    )
    obligations = near_term_ap + loc_interest
    available = revenue - tax_reserve - obligations
    sustainable = float(inp.owner_draw_amount) <= available
    return {
        "sustainable": bool(sustainable),
        "max_sustainable_draw": round(max(0.0, available), 2),
        "current_draw": round(float(inp.owner_draw_amount), 2),
        "headroom": round(available - float(inp.owner_draw_amount), 2),
        "tax_reserve_pct": tax_pct,
        "tax_reserve_amount": round(tax_reserve, 2),
        "near_term_obligations": round(obligations, 2),
    }


def _is_seasonal_low_now(inp, current_month: Optional[int] = None) -> bool:
    """SB-LP-5 helper. True iff the profile flags `seasonal_revenue` and
    the supplied month is in `seasonal_low_months`. With no month given,
    returns False (the strain dimensions don't currently consume this —
    it's a hook for 5a.4 / 5a.5 to surface a 'low-season tightening'
    qualifier on the state explanation copy)."""
    if not getattr(inp, "seasonal_revenue", False):
        return False
    months = getattr(inp, "seasonal_low_months", None) or []
    if current_month is None:
        return False
    return current_month in months


# ─────────────────────────────────────────────────────────────────────
# Main extension entry point. Called from engine.score_individual when
# `inp.archetype == "small_business"`.
# ─────────────────────────────────────────────────────────────────────

def extend_score_for_small_business(inp, result) -> None:
    """Mutate `result` in place: add SB-FSS contributors to
    `result.fss_breakdown`, recompute `result.fss`, and stash forward
    projections under `result.insights["small_business"]`.

    No-op for non-SB archetypes — defensive guard at the top.

    The recompute approach follows engine.compute_fss exactly: each
    contributor is stored with its `pla` and `weighted` (= pla × weight)
    pre-asymmetry-multiplier values, and the new total reaggregates
    `weighted × asym` across all FSS dims (existing + new), then clamps
    and scales 0..100. This keeps the math identical to compute_fss —
    we're literally adding terms to the same sum.
    """
    if getattr(inp, "archetype", None) != "small_business":
        return

    fss_breakdown = result.fss_breakdown
    weights = _SB_CONFIG["fss_weights"]

    # Compute the four SB strain plas.
    ar_pla      = _compute_ar_aging_strain(inp)
    ap_pla      = _compute_ap_compression_strain(inp)
    loc_pla     = _compute_loc_utilization_strain(inp)
    payroll_pla = _compute_payroll_coverage_strain(inp)

    # Add to the fss_breakdown using the exact same shape as existing
    # FSS dims (engine.compute_fss). The `weighted` value is pre-asym;
    # the FSS aggregator below applies asym uniformly.
    fss_breakdown["AR aging strain"] = {
        "pla":      round(ar_pla, 3),
        "weighted": round(ar_pla * weights["AR aging strain"], 4),
    }
    fss_breakdown["AP compression strain"] = {
        "pla":      round(ap_pla, 3),
        "weighted": round(ap_pla * weights["AP compression strain"], 4),
    }
    fss_breakdown["LOC utilization strain"] = {
        "pla":      round(loc_pla, 3),
        "weighted": round(loc_pla * weights["LOC utilization strain"], 4),
    }
    fss_breakdown["Payroll coverage strain"] = {
        "pla":      round(payroll_pla, 3),
        "weighted": round(payroll_pla * weights["Payroll coverage strain"], 4),
    }

    # Recompute FSS with all dims (existing + SB).
    asym = (fss_breakdown.get("_asymmetry") or {}).get("multiplier", 1.0)
    total_weighted = sum(
        float(v.get("weighted", 0))
        for k, v in fss_breakdown.items()
        if not k.startswith("_") and isinstance(v, dict)
    )
    new_fss = round(100 * min(1.0, max(0.0, total_weighted * asym)))
    result.fss = new_fss

    # Forward projections — stashed for 5a.4 recommendation gen.
    sb_insights = result.insights.setdefault("small_business", {})
    sb_insights["ar_trajectory"]         = simulate_ar_collection_trajectory(inp)
    sb_insights["loc_trajectory"]        = simulate_loc_trajectory(inp)
    sb_insights["ap_schedule"]           = simulate_ap_schedule(inp)
    sb_insights["owner_draw_assessment"] = assess_owner_draw_sustainability(inp)

    # Phase 5a.4: action recommendations from SB-FSS contributors and
    # forward simulations. Existing Individual-archetype recs (allocation
    # guidance from `engine.generate_recommendations`) still apply for
    # the SB user's personal-side surface — prepend SB recs so the
    # primary slot reflects business-side urgency.
    from recommendations import generate_action_recommendations
    sb_recs = generate_action_recommendations(inp, result)
    if sb_recs:
        # Singular-primary across the merged list: any new SB primary
        # demotes pre-existing primaries to secondary slot.
        if any(r.get("priority") == "primary" for r in sb_recs):
            for legacy in (result.recommendations or []):
                # Legacy recs use a numeric `priority` field (1, 2, 3);
                # only touch the one(s) marked priority=1 (top tier).
                if isinstance(legacy, dict) and legacy.get("priority") == 1:
                    legacy["priority"] = 2
        # Prepend SB recs so they render first.
        result.recommendations = sb_recs + (result.recommendations or [])
