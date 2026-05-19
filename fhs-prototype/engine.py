"""
Financial Health Scoring Engine — Individual (W-2) Model
Implements LP Optimization Models v4.4.1 (32 fixes applied)
"""
import math
from dataclasses import dataclass, field, replace
from typing import Optional
import pulp


# ═══════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════

@dataclass
class IndividualInput:
    """Known parameters for Individual (W-2) user."""
    name: str = "User"
    # Income
    I_gross: float = 0          # Monthly gross income
    I_net: float = 0            # Monthly after-tax (take-home)
    # Expenses
    E_ess: float = 0            # Monthly essential expenses
    E_house: float = 0          # Monthly housing (subset of E_ess)
    # Debt
    D_min: float = 0            # Total minimum monthly debt payments
    D_hi: float = 0             # Total HI debt balance (>15% APR)
    D_lo: float = 0             # Total other debt balance
    # Savings
    S_liq: float = 0            # Current liquid savings
    S_ret: float = 0            # Current retirement savings
    # Demographics
    age: int = 30
    # Insurance (parameter-set binaries per Fix #32)
    has_life_insurance: bool = False    # y₂
    has_disability_insurance: bool = False  # y₃
    # Behavioral (for FSS)
    overdraft_count_90d: int = 0
    late_payment_count_90d: int = 0
    # Temporal signals
    # Linear-regression slope of recent score history. Positive = improving,
    # negative = declining. Feeds the FSS AsymmetryMult (Ch. 3.3).
    momentum_slope: float = 0.0
    # Consecutive days of logged financial activity / positive habits.
    # Feeds FRS MomentumFactor.
    streak_days: int = 0
    # Snapshot of selected fields from 30 days ago. Keys mirror IndividualInput
    # field names (S_liq, S_ret, D_hi, D_lo, E_ess, I_gross, late_payment_count_90d,
    # overdraft_count_90d, has_life_insurance, has_disability_insurance). Drives
    # FRS gap-closure computation. None ⇒ snapshot-only FRS.
    previous: Optional[dict] = None
    # Toggle the new multi-period LP solver. When True, future pipeline code
    # should dispatch to solve_individual_lp_multiperiod; the current scoring
    # path still uses the single-period solver.
    use_multiperiod: bool = True
    # Demographic context — drives milestone applicability rules. Defaults
    # leave behavior unchanged for any pre-existing input that doesn't set them.
    dependents: int = 0
    retired: bool = False

    # ── Small Business extension (Phase 5a.1) ────────────────────────
    # Optional; populated only when a profile represents a small-business
    # owner-operator. Defaults are zero / empty / "none" so non-SB
    # profiles validate cleanly with no behavioral change. The LP/MILP
    # constraints that consume these fields are added in 5a.2; until then
    # the values are carried but not yet differentially scored.
    #
    # `archetype` is the dispatch key: any value other than "individual_w2"
    # signals a non-default archetype. Phase 5a.1 introduces "small_business";
    # 5b/5d will introduce "freelancer" / "startup".
    archetype: str = "individual_w2"
    business_structure: Optional[str] = None    # sole_proprietor|llc|s_corp|c_corp|partnership|other
    revenue_cadence: Optional[str] = None       # weekly|biweekly|monthly|quarterly|irregular
    # AR aging buckets — outstanding receivables by days-past-invoice.
    # Keys: "current" | "30_days" | "60_days" | "90_plus_days". Values: $.
    ar_aging_buckets: dict = field(default_factory=dict)
    # AP pending — payables by urgency window.
    # Keys: "due_within_7d" | "due_8_to_30d" | "overdue". Values: $.
    ap_pending: dict = field(default_factory=dict)
    payroll_periodicity: str = "none"           # weekly|biweekly|semimonthly|monthly|none
    payroll_amount_per_cycle: float = 0         # $ per pay-cycle (0 if none)
    owner_draw_amount: float = 0                # monthly equivalent $
    owner_draw_cadence: str = "none"            # weekly|biweekly|monthly|quarterly|as_needed|none
    # Each line: {"limit": $, "balance": $, "apr": 0.0–1.0, "name": str}.
    business_lines_of_credit: list = field(default_factory=list)
    seasonal_revenue: bool = False              # if True, populate seasonal_low_months
    seasonal_low_months: list = field(default_factory=list)   # [1..12] month numbers

    # ── Freelancer extension (Phase 5b.1) ────────────────────────────
    # Optional; populated only when archetype == "freelancer". Defaults
    # are zero / empty / None so non-Freelancer profiles validate
    # cleanly with no behavioral change. The LP/MILP constraints that
    # consume these fields land in 5b.2; until then the values are
    # carried but not yet differentially scored.
    #
    # Why these fields specifically:
    #   • income_sources captures the multi-payer reality of freelance
    #     work (1099 contracts + gig platforms + direct freelance +
    #     royalties, often coexisting).
    #   • income_volatility_observed is the central new signal —
    #     coefficient-of-variation of recent monthly income, computed
    #     when 3+ months of history available.
    #   • tax_reserve_* fields enable the tax-burden modeling that's
    #     central to Freelancer scoring (no business-entity buffer →
    #     SE tax is a present obligation on every dollar).
    #   • fixed_monthly_obligations enables the "Famine" state
    #     calculation: months of fixed-cost coverage from current
    #     liquid + tax reserve.
    #   • freelance_account_separation gates confidence ratings on
    #     income detection (mixed_personal accounts are noisier than
    #     separate_business_account).
    #
    # Field naming: dignified, non-pejorative. `income_volatility_observed`
    # not `income_instability_score`; `tax_reserve_balance` not
    # `tax_debt_carrying`. Brand voice principles apply at every layer
    # where text appears in a response surface.
    income_sources: list = field(default_factory=list)
    # Each source: {"source_type": str, "name": str,
    #               "monthly_average": float,
    #               "volatility_coefficient": float,
    #               "is_seasonal": bool}.
    # source_type ∈ {"1099_contract", "gig_platform", "freelance_direct",
    #                "royalty", "other"}.
    income_volatility_observed: Optional[float] = None
    # 0–1 coefficient-of-variation of recent monthly income; None when
    # months_of_income_history < 3.
    months_of_income_history: int = 0
    tax_reserve_balance: float = 0
    # Liquid balance designated as tax reserve (separate from S_liq for
    # scoring purposes — Freelancer scoring treats it as encumbered).
    tax_reserve_target_pct: float = 0.30
    # Default 0.30 = federal income + SE tax estimate for typical
    # freelancer with no state income tax. CA / NY / similar high-tax
    # states should configure higher per Phase 6 calibration.
    quarterly_tax_due_date: Optional[str] = None
    # ISO 8601 date string ("YYYY-MM-DD"); next 1040-ES due date.
    quarterly_tax_estimated_amount: float = 0
    fixed_monthly_obligations: float = 0
    # Sum of rent/mortgage + insurance + subscriptions + minimum debt
    # payments — the must-pay floor regardless of whether income
    # arrived this month. Drives the Famine fixed-obligation-coverage
    # calculation.
    freelance_account_separation: str = "unknown"
    # ∈ {"separate_business_account", "mixed_personal", "unknown"}.
    # Relevant for confidence ratings on income detection in 5b.3.


@dataclass
class LPSolution:
    """Output of the LP solver."""
    status: str = "Infeasible"
    x: dict = field(default_factory=dict)       # allocations
    y: dict = field(default_factory=dict)       # milestones
    z: float = 0                                # HI debt remaining
    z2: float = 0                               # discretionary excess
    objective_value: float = 0
    objective_terms: dict = field(default_factory=dict)
    # Multi-period solver only: per-month state snapshot ({S_liq, S_ret,
    # D_hi, D_lo, D_min} × N periods). Empty for single-period runs.
    state_trajectory: list = field(default_factory=list)


@dataclass
class ScoreResult:
    """Complete scoring output."""
    fhs: float = 300
    fss: float = 100
    frs: float = 50
    fhs_breakdown: dict = field(default_factory=dict)
    fss_breakdown: dict = field(default_factory=dict)
    frs_breakdown: dict = field(default_factory=dict)
    lp_solution: Optional[LPSolution] = None
    optimal_allocation: dict = field(default_factory=dict)
    actual_vs_optimal: dict = field(default_factory=dict)
    infeasible: bool = False
    infeasibility_reason: str = ""
    recommendations: list = field(default_factory=list)
    insights: dict = field(default_factory=dict)
    trajectory: list = field(default_factory=list)
    allocation_plan: list = field(default_factory=list)
    state_trajectory: list = field(default_factory=list)
    plan_phases: list = field(default_factory=list)
    # Negative-cash-flow state: monthly take-home can't cover essentials +
    # minimums. When set, the UI replaces the phased plan with a single
    # "close the gap" priority-1 card. Populated by score_individual when
    # inp.I_net - inp.E_ess - inp.D_min < 0.
    income_shortfall: Optional[dict] = None


# ═══════════════════════════════════════════
# PLA FUNCTIONS (Ch. 2.4)
# ═══════════════════════════════════════════

def _pla_interpolate(x_val, breakpoints, values):
    """Universal PLA with clamping (Fix #18)."""
    if x_val <= breakpoints[0]:
        return values[0]
    if x_val >= breakpoints[-1]:
        return values[-1]
    for i in range(len(breakpoints) - 1):
        if breakpoints[i] <= x_val <= breakpoints[i + 1]:
            t = (x_val - breakpoints[i]) / (breakpoints[i + 1] - breakpoints[i])
            return values[i] + t * (values[i + 1] - values[i])
    return values[-1]


def pla_dim(x_val):
    """Diminishing Returns PLA (savings, emergency fund)."""
    bp = [0, 0.25, 0.50, 0.75, 1.0, 1.5, 2.0, 3.0]
    gv = [0, 0.20, 0.40, 0.58, 0.72, 0.88, 0.95, 1.0]
    return _pla_interpolate(x_val, bp, gv)


def pla_acc(x_val):
    """Accelerating Penalty PLA (DTI, burn rate, churn)."""
    bp = [0, 0.20, 0.36, 0.43, 0.50, 0.60, 0.80, 1.0]
    gv = [0, 0.05, 0.15, 0.30, 0.52, 0.75, 0.92, 1.0]
    return _pla_interpolate(x_val, bp, gv)


def pla_thresh(x_val):
    """Threshold Step PLA (runway, coverage ratios). Input in months."""
    bp = [0, 1, 2, 3, 6, 9, 12, 18, 24]
    gv = [0, 0.08, 0.18, 0.35, 0.60, 0.75, 0.85, 0.95, 1.0]
    return _pla_interpolate(x_val, bp, gv)


# ═══════════════════════════════════════════
# BENCHMARKS & CALIBRATION (Ch. 7 / Tier 3)
# ═══════════════════════════════════════════

# Initial weights from v2 pillar structure (expert consensus)
# Individual: BORROW 30%, SAVE 25%, SPEND 15%, PLAN 20%, PROTECT 10%
WEIGHTS = {
    "w1": 0.15,   # EF savings (SAVE)
    "w2": 0.10,   # Retirement (SAVE)
    "w3": 0.12,   # DTI (BORROW)
    "w4": 0.10,   # Cash flow margin (SPEND)
    "w5": 0.10,   # Milestones (PLAN/PROTECT)
    "w6": 0.18,   # HI Debt paydown (BORROW)
    "w7": 0.05,   # Discretionary penalty (SPEND)
    "w8": 0.08,   # HI Debt elimination bonus (BORROW)
    "w9": 0.08,   # Investment rate (GROW) — activates when EF is near full
}
# Note: w7 is penalty (negative). Effective positive sum ≈ 0.83, penalty = 0.05
# Remaining weight budget: 0.12 unallocated → absorbed into normalization

EPS = 0.001


# ─────────────────────────────────────────────────────────────────
# Score-band names (text equivalents for color-coded states).
# Defined here, in engine.py, so the frontend never duplicates the
# threshold logic. Exposed via score_to_dict / result_to_dict.
# ─────────────────────────────────────────────────────────────────
def fhs_band(v: float) -> str:
    """FHS: 300–850, higher is better."""
    if v >= 700: return "Strong"
    if v >= 600: return "Good"
    if v >= 450: return "Watch"
    return "Weak"


def fss_band(v: float) -> str:
    """FSS: 0–100, lower is better."""
    if v <=  25: return "Calm"
    if v <=  50: return "Manageable"
    if v <=  75: return "Strained"
    return "Critical"


def frs_band(v: float) -> str:
    """FRS: 0–100, higher is better."""
    if v >=  70: return "Strong"
    if v >=  55: return "Improving"
    if v >=  40: return "Holding"
    return "Declining"


def age_target(age, annual_salary):
    """Fidelity-benchmark retirement target (1×@30, 2×@35, 3×@40, 4×@45,
    6×@50, 7×@55, 8×@60, 10×@67). Previous values were inflated by ~1.5×
    at mid-career, which starved every profile of retirement credit."""
    if age < 30:
        return annual_salary * 1.0
    elif age < 35:                           # 30→35: 1× → 2×
        return annual_salary * (1.0 + (age - 30) * 0.2)
    elif age < 40:                           # 35→40: 2× → 3×
        return annual_salary * (2.0 + (age - 35) * 0.2)
    elif age < 45:                           # 40→45: 3× → 4×
        return annual_salary * (3.0 + (age - 40) * 0.2)
    elif age < 50:                           # 45→50: 4× → 6×
        return annual_salary * (4.0 + (age - 45) * 0.4)
    elif age < 55:                           # 50→55: 6× → 7×
        return annual_salary * (6.0 + (age - 50) * 0.2)
    elif age < 60:                           # 55→60: 7× → 8×
        return annual_salary * (7.0 + (age - 55) * 0.2)
    elif age < 67:                           # 60→67: 8× → 10×
        return annual_salary * (8.0 + (age - 60) * (2.0 / 7.0))
    else:
        return annual_salary * 10.0


# ═══════════════════════════════════════════
# LP SOLVER — MODEL A (Ch. 3.1)
# ═══════════════════════════════════════════

def _x_month0(sol: LPSolution) -> dict:
    """Return month-0 allocation dict regardless of solver shape.
    Single-period: sol.x is a dict. Multi-period: sol.x is a list."""
    if isinstance(sol.x, list):
        return sol.x[0] if sol.x else {}
    return sol.x


def solve_individual_lp(inp: IndividualInput) -> LPSolution:
    """Solve the Individual user-state optimization (Model A)."""
    sol = LPSolution()

    # Computed parameters
    disposable = inp.I_net - inp.E_ess - inp.D_min
    min_discret = 0.05 * inp.I_gross

    # ── Graceful degradation for tight budgets (Infeasibility Step 1) ──
    # When a user cannot cover essentials + full minimum debt payments, the old
    # behavior was to bail with Infeasible → FHS=300. That hides real signal and
    # makes every "stretched" archetype look identical to "distressed".
    # Instead, scale back D_min to what the user can actually pay and record
    # the shortfall in sol.debt_shortfall so FSS can pick it up as severe strain.
    effective_D_min = inp.D_min
    debt_shortfall = 0.0
    if disposable <= 0:
        # What's left after essentials is all we can send to debt
        room_for_debt = max(0.0, inp.I_net - inp.E_ess)
        debt_shortfall = inp.D_min - room_for_debt
        # Leave a small sliver ($50 or 2% of gross, whichever smaller) for any
        # discretionary/savings so the LP stays feasible and differentiated.
        sliver = min(50.0, 0.02 * inp.I_gross)
        effective_D_min = max(0.0, room_for_debt - sliver)
        disposable = inp.I_net - inp.E_ess - effective_D_min
        sol.objective_terms["debt_shortfall"] = debt_shortfall

    if disposable <= 0:
        # Cannot even cover essentials — genuine distress
        sol.status = "Infeasible"
        return sol

    # C3 floor: relax to a fraction of disposable when the normal 5%-of-gross
    # floor would itself make the problem infeasible.
    # In graceful-degradation mode (debt_shortfall > 0) the user is ALREADY
    # forgoing required debt payments to afford essentials — we shouldn't then
    # force them to burn 50% of the remaining sliver on discretionary. Drop the
    # floor to zero so every dollar can go toward debt paydown or EF building.
    if debt_shortfall > 0:
        c3_floor = 0.0
    else:
        c3_floor = min(min_discret, disposable * 0.50)

    annual_salary = inp.I_gross * 12
    age_tgt = age_target(inp.age, annual_salary)
    b_ef = inp.E_ess * 0.5      # Build 6-month EF in 12 months → monthly target
    b_ret = age_tgt / (12 * 10)  # Spread retirement gap over 10 years
    if b_ret < 100:
        b_ret = 100
    # Saturation factor: once the user is past a healthy EF (3–6 months), every
    # additional EF dollar should score near zero marginal value so the LP
    # prefers retirement / investment. Without this, a user with 12+ months of
    # runway still sees the LP dump all disposable income into x1.
    ef_months_cur = inp.S_liq / max(EPS, inp.E_ess)
    if ef_months_cur >= 12:
        ef_saturation = 0.02
    elif ef_months_cur >= 6:
        ef_saturation = 0.15 - (ef_months_cur - 6) / 6 * 0.13    # 6mo→0.15, 12mo→0.02
    elif ef_months_cur >= 3:
        ef_saturation = 0.50 - (ef_months_cur - 3) / 3 * 0.35    # 3mo→0.50, 6mo→0.15
    else:
        ef_saturation = 1.0

    # Investment (x6) — target 10% of gross income. Activates meaningfully
    # only when EF is at least 80% of its 6-month target (≈4.8 months); below
    # that, the LP still prefers EF / debt / retirement.
    b_invest = 0.10 * inp.I_gross
    if ef_months_cur >= 6:
        invest_activation = 1.0
    elif ef_months_cur >= 4.8:                                   # 4.8mo→0.05, 6mo→1.0
        invest_activation = 0.05 + (ef_months_cur - 4.8) / 1.2 * 0.95
    else:
        invest_activation = 0.05
    x5_target = 0.30 * disposable
    M = 10 * max(inp.I_gross * 12, inp.D_hi + 1, inp.S_liq + 1, 100000)

    # ── Create LP ──
    prob = pulp.LpProblem("IndividualFHS", pulp.LpMaximize)

    # Decision variables
    x1 = pulp.LpVariable("x1_ef", lowBound=0)
    x2 = pulp.LpVariable("x2_ret", lowBound=0)
    x3 = pulp.LpVariable("x3_hi_debt", lowBound=0)
    x4 = pulp.LpVariable("x4_lo_debt", lowBound=0)
    x5 = pulp.LpVariable("x5_discret", lowBound=0)
    # Capped EF reward: x1_eff = min(x1/b_ef, 1). LP will push it to its upper
    # bound in maximize so this models PLA_dim's saturation at 1.0x target.
    x1_eff = pulp.LpVariable("x1_ef_capped_reward", lowBound=0, upBound=1)
    # Same pattern for investment rate.
    x6_eff = pulp.LpVariable("x6_invest_capped_reward", lowBound=0, upBound=1)
    x6 = pulp.LpVariable("x6_invest", lowBound=0)

    y1 = pulp.LpVariable("y1_ef_adequate", cat="Binary")
    y4 = pulp.LpVariable("y4_ret_ontrack", cat="Binary")
    y5 = pulp.LpVariable("y5_hi_elim", cat="Binary")

    z = pulp.LpVariable("z_debt_remain", lowBound=0)
    z2 = pulp.LpVariable("z2_discret_excess", lowBound=0)

    # Parameter-set binaries (Fix #32)
    y2_val = 1 if inp.has_life_insurance else 0
    y3_val = 1 if inp.has_disability_insurance else 0

    # ── Hard Constraints ──
    # C1: Budget
    prob += x1 + x2 + x3 + x4 + x5 + x6 == disposable, "C1_budget"
    # Link the capped EF reward to x1: x1_eff ≤ x1/b_ef (and ≤ 1 from upBound).
    if b_ef > 0:
        prob += x1_eff * b_ef <= x1, "C1b_ef_reward_cap"
    if b_invest > 0:
        prob += x6_eff * b_invest <= x6, "C1c_invest_reward_cap"
    # C3: Minimum discretionary (Fix #12, with Step 2 relaxation if needed)
    prob += x5 >= c3_floor, "C3_min_living"
    # C4: HI Debt ceiling
    if inp.D_hi > 0:
        prob += x3 <= inp.D_hi / 12.0, "C4_hi_debt_cap"
    else:
        prob += x3 == 0, "C4_no_hi_debt"
    # C5: Retirement cap
    ret_cap = min(inp.I_gross * 0.25, 23500.0 / 12.0)
    prob += x2 <= ret_cap, "C5_ret_cap"
    # C6, C7: z₂ linearization (Fix #27)
    prob += z2 >= 0, "C6_z2_lower"
    prob += z2 >= x5 - x5_target, "C7_z2_linearize"

    # ── Soft Constraints ──
    s1p = pulp.LpVariable("s1_plus", lowBound=0)
    s1m = pulp.LpVariable("s1_minus", lowBound=0)
    prob += inp.S_liq + x1 * 12 + s1p - s1m == 6 * inp.E_ess, "S1_ef_target"

    s3p = pulp.LpVariable("s3_plus", lowBound=0)
    s3m = pulp.LpVariable("s3_minus", lowBound=0)
    if inp.I_gross > 0:
        prob += (x1 + x2 + x6) == 0.20 * inp.I_gross + (s3m - s3p) * inp.I_gross, "S3_savings"

    # ── MILP Indicator Constraints ──
    # M1: y₁ EF adequate (Fix #13)
    ef_proj = inp.S_liq + x1 * 6
    ef_threshold = 3 * inp.E_ess
    prob += ef_proj >= ef_threshold - M * (1 - y1), "M1a_ef"
    prob += ef_proj <= ef_threshold + M * y1 - EPS, "M1b_ef"

    # M2: y₅ HI debt elimination (Fix #8, #14)
    if inp.D_hi > 0:
        prob += z >= 0, "M2a_z_lower"
        prob += z >= inp.D_hi - x3 * 12, "M2b_z_debt"
        prob += z <= M * (1 - y5), "M2c_z_indicator"
    else:
        # Fix #29: D_hi = 0 → y₅ = 1 auto, M2 deactivated
        prob += y5 == 1, "M2_no_debt"
        prob += z == 0, "M2_z_zero"

    # M3: y₄ retirement on track (Fix #32)
    ret_proj = inp.S_ret + x2 * 12
    # "On track" = at/above 50% of the Fidelity age-based benchmark (softened
    # from full 100% — same threshold the FHS resilience milestone uses).
    prob += ret_proj >= 0.5 * age_tgt - M * (1 - y4), "M3a_ret"
    prob += ret_proj <= 0.5 * age_tgt + M * y4 - EPS, "M3b_ret"

    # ── Objective Function ──
    # We approximate PLA terms linearly for the LP.
    # For a proper implementation, use SOS2 variables.
    # MVP approach: linearize each PLA term at its expected operating point.

    # Term 1: w₁·PLA_dim(x₁/b_ef)  — approximate as linear coefficient
    # PLA_dim is concave → LP-compatible if we use the PLA breakpoints directly
    # For MVP, we use a simplified linear approximation:
    # PLA_dim(x/b) ≈ min(1, x/b) for the relevant range
    w = WEIGHTS

    # Simplified objective: weighted sum of normalized terms
    # This is a valid LP relaxation — the PLA refinement comes in scoring
    obj = 0
    if b_ef > 0:
        obj += w["w1"] * ef_saturation * x1_eff   # Term 1: EF savings rate, capped + saturated
    if b_invest > 0:
        obj += w["w9"] * invest_activation * x6_eff   # Term 9: Investment rate, gated on EF fill
    if b_ret > 0:
        obj += w["w2"] * (x2 / b_ret)       # Term 2: Retirement rate
    # Term 3: DTI (constant, included for Z value)
    dti = inp.D_min / max(EPS, inp.I_gross)
    obj += w["w3"] * (1 - dti)
    # Term 4: Cash flow margin
    if inp.I_net > 0:
        obj += w["w4"] * (1 - x5 / inp.I_net)  # Higher margin = less discretionary
    # Term 5: Milestones
    obj += w["w5"] * (y1 + y2_val + y3_val + y4) / 4.0
    # Term 6: HI debt paydown (continuous)
    if inp.D_hi > 0:
        obj += w["w6"] * (1 - z / inp.D_hi)
    else:
        obj += w["w6"]  # Fix #29: full score
    # Term 7 (w₈): y₅ bonus (Fix #20)
    obj += w["w8"] * y5
    # Term 8 (-w₇): discretionary penalty
    if disposable > 0:
        obj -= w["w7"] * (z2 / disposable)

    prob += obj

    # ── Solve ──
    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    if prob.status != 1:
        sol.status = "Infeasible"
        return sol

    sol.status = "Optimal"
    sol.x = {
        "x1_ef_savings": pulp.value(x1),
        "x2_retirement": pulp.value(x2),
        "x3_hi_debt_paydown": pulp.value(x3),
        "x4_lo_debt_paydown": pulp.value(x4),
        "x5_discretionary": pulp.value(x5),
        "x6_investment": pulp.value(x6),
    }
    sol.y = {
        "y1_ef_adequate": int(pulp.value(y1)),
        "y2_life_insurance": y2_val,
        "y3_disability_insurance": y3_val,
        "y4_retirement_ontrack": int(pulp.value(y4)),
        "y5_hi_debt_eliminated": int(pulp.value(y5)),
    }
    sol.z = pulp.value(z)
    sol.z2 = pulp.value(z2)
    sol.objective_value = pulp.value(prob.objective)
    # Record the EF saturation factor so FHS scoring can re-normalize the
    # "LP optimization" dimension — otherwise a user with an already-full
    # emergency fund gets penalized for not being able to earn the uncapped
    # EF reward any more.
    sol.objective_terms["ef_saturation"] = ef_saturation
    sol.objective_terms["invest_activation"] = invest_activation

    return sol


# ═══════════════════════════════════════════
# MULTI-PERIOD LP (Step 1 of 3 — solver only, not yet wired to scoring)
# ═══════════════════════════════════════════

def solve_individual_lp_multiperiod(inp: IndividualInput, periods: int = 6) -> LPSolution:
    """Multi-period variant that optimizes allocations across `periods` months
    simultaneously. The key insight versus the single-period model: as HI debt
    is retired, its share of D_min shrinks, which frees budget that the LP can
    redirect to later-period savings/retirement. The single-period model is
    structurally blind to this feedback.

    Output shape differs from the single-period solver:
      • sol.x is a LIST of per-period allocation dicts (index 0 = month 1)
      • sol.state_trajectory is a LIST of per-period state snapshots
      • sol.y summarizes milestones at the LAST period (after all plan effort)
    """
    sol = LPSolution()

    # ── Upstream coefficients (same shape as single-period) ────────────
    min_discret = 0.05 * inp.I_gross
    disposable0 = inp.I_net - inp.E_ess - inp.D_min

    # Graceful degradation: scale D_min's pay-per-dollar-of-debt factor so the
    # initial month is feasible even when essentials + full minimums > net.
    effective_D_min_0 = inp.D_min
    debt_shortfall = 0.0
    if disposable0 <= 0:
        room_for_debt = max(0.0, inp.I_net - inp.E_ess)
        debt_shortfall = inp.D_min - room_for_debt
        sliver = min(50.0, 0.02 * inp.I_gross)
        effective_D_min_0 = max(0.0, room_for_debt - sliver)
        sol.objective_terms["debt_shortfall"] = debt_shortfall

    total_debt_init = inp.D_hi + inp.D_lo
    # scale_dmin: dollars of minimum payment per dollar of outstanding debt.
    # Using effective_D_min_0 ensures month 1 is feasible in shortfall cases.
    scale_dmin = (effective_D_min_0 / total_debt_init) if total_debt_init > 0 else 0.0

    if inp.I_net - inp.E_ess - effective_D_min_0 <= 0:
        # Truly infeasible: essentials alone exceed net income.
        sol.status = "Infeasible"
        return sol

    # EF / investment saturation (same as single-period, evaluated at time 0)
    annual_salary = inp.I_gross * 12
    age_tgt = age_target(inp.age, annual_salary)
    b_ef  = inp.E_ess * 0.5
    b_ret = age_tgt / (12 * 10)
    if b_ret < 100:
        b_ret = 100
    ef_months_cur = inp.S_liq / max(EPS, inp.E_ess)
    if   ef_months_cur >= 12: ef_saturation = 0.02
    elif ef_months_cur >=  6: ef_saturation = 0.15 - (ef_months_cur - 6) / 6 * 0.13
    elif ef_months_cur >=  3: ef_saturation = 0.50 - (ef_months_cur - 3) / 3 * 0.35
    else:                     ef_saturation = 1.0

    b_invest = 0.10 * inp.I_gross
    if   ef_months_cur >= 6:   invest_activation = 1.0
    elif ef_months_cur >= 4.8: invest_activation = 0.05 + (ef_months_cur - 4.8) / 1.2 * 0.95
    else:                      invest_activation = 0.05

    y2_val = 1 if inp.has_life_insurance else 0
    y3_val = 1 if inp.has_disability_insurance else 0

    M = 10 * max(annual_salary, inp.D_hi + 1, inp.S_liq + 1, 100000)

    # ── LP build ───────────────────────────────────────────────────────
    prob = pulp.LpProblem("IndividualFHS_MP", pulp.LpMaximize)

    # Per-period decision variables (t = 0..periods-1, representing months 1..periods)
    x1 = [pulp.LpVariable(f"x1_{t}", lowBound=0) for t in range(periods)]
    x2 = [pulp.LpVariable(f"x2_{t}", lowBound=0) for t in range(periods)]
    x3 = [pulp.LpVariable(f"x3_{t}", lowBound=0) for t in range(periods)]
    x4 = [pulp.LpVariable(f"x4_{t}", lowBound=0) for t in range(periods)]
    x5 = [pulp.LpVariable(f"x5_{t}", lowBound=0) for t in range(periods)]
    x6 = [pulp.LpVariable(f"x6_{t}", lowBound=0) for t in range(periods)]

    # Capped reward aux vars per period — all three savings allocations saturate
    # at 1.0x of their target rate. Without x2_eff, heavy retirement contributions
    # (x2/b_ret > 1.0) earned uncapped reward, causing the LP to prefer retirement
    # even when the user had large HI debt that should be prioritized.
    x1_eff = [pulp.LpVariable(f"x1_eff_{t}", lowBound=0, upBound=1) for t in range(periods)]
    x2_eff = [pulp.LpVariable(f"x2_eff_{t}", lowBound=0, upBound=1) for t in range(periods)]
    x6_eff = [pulp.LpVariable(f"x6_eff_{t}", lowBound=0, upBound=1) for t in range(periods)]

    # Continuous state variables
    S_liq = [pulp.LpVariable(f"S_liq_{t}", lowBound=0) for t in range(periods)]
    S_ret = [pulp.LpVariable(f"S_ret_{t}", lowBound=0) for t in range(periods)]
    D_hi  = [pulp.LpVariable(f"D_hi_{t}",  lowBound=0) for t in range(periods)]
    D_lo  = [pulp.LpVariable(f"D_lo_{t}",  lowBound=0) for t in range(periods)]

    # Monotonic milestone binaries
    y1 = [pulp.LpVariable(f"y1_{t}", cat="Binary") for t in range(periods)]
    y4 = [pulp.LpVariable(f"y4_{t}", cat="Binary") for t in range(periods)]
    y5 = [pulp.LpVariable(f"y5_{t}", cat="Binary") for t in range(periods)]

    # ── Constraints ─────────────────────────────────────────────────────
    for t in range(periods):
        prev_S_liq = inp.S_liq if t == 0 else S_liq[t-1]
        prev_S_ret = inp.S_ret if t == 0 else S_ret[t-1]
        prev_D_hi  = inp.D_hi  if t == 0 else D_hi [t-1]
        prev_D_lo  = inp.D_lo  if t == 0 else D_lo [t-1]

        # State transitions (linear; D_hi/D_lo ≥ 0 bound via lowBound on vars)
        prob += S_liq[t] == prev_S_liq + x1[t], f"trans_Sliq_{t}"
        prob += S_ret[t] == prev_S_ret + x2[t], f"trans_Sret_{t}"
        # Cap debt paydown at remaining balance so D_hi/D_lo stay ≥ 0 without
        # needing max() — the LP has no reward for over-paying.
        prob += x3[t] <= prev_D_hi, f"cap_x3_{t}"
        prob += x4[t] <= prev_D_lo, f"cap_x4_{t}"
        prob += D_hi[t] == prev_D_hi - x3[t], f"trans_Dhi_{t}"
        prob += D_lo[t] == prev_D_lo - x4[t], f"trans_Dlo_{t}"

        # Budget: D_min(t) scales with START-of-period (prev) balance —
        # mirrors real credit-card minimums billed on last statement. As debt
        # shrinks, later-period budget grows naturally.
        dmin_prev = scale_dmin * (prev_D_hi + prev_D_lo)
        prob += (
            x1[t] + x2[t] + x3[t] + x4[t] + x5[t] + x6[t]
            == inp.I_net - inp.E_ess - dmin_prev
        ), f"budget_{t}"

        # C3 floor (same relaxation rule as single-period)
        if debt_shortfall > 0:
            c3_floor_t = 0.0
        else:
            c3_floor_t = min(min_discret, max(0.0, disposable0) * 0.50)
        prob += x5[t] >= c3_floor_t, f"c3_min_{t}"

        # Capped reward links
        if b_ef > 0:
            prob += x1_eff[t] * b_ef     <= x1[t], f"cap_x1_eff_{t}"
        if b_ret > 0:
            prob += x2_eff[t] * b_ret    <= x2[t], f"cap_x2_eff_{t}"
        if b_invest > 0:
            prob += x6_eff[t] * b_invest <= x6[t], f"cap_x6_eff_{t}"

        # Milestones (Big-M — achievement side only; reward-only direction)
        prob += S_liq[t] + M * (1 - y1[t]) >= 3 * inp.E_ess, f"M1_y1_{t}"
        prob += S_ret[t] + M * (1 - y4[t]) >= 0.5 * age_tgt,  f"M3_y4_{t}"
        prob += D_hi[t]  <= M * (1 - y5[t]),                  f"M2_y5_{t}"

        # Milestones, once achieved, stay achieved
        if t > 0:
            prob += y1[t] >= y1[t-1], f"mono_y1_{t}"
            prob += y4[t] >= y4[t-1], f"mono_y4_{t}"
            prob += y5[t] >= y5[t-1], f"mono_y5_{t}"

    # ── Objective: time-discounted sum across periods ──────────────────
    w = WEIGHTS
    obj = 0
    for t in range(periods):
        disc = 1.0 / (1.02 ** t)     # slight preference for earlier improvement
        term_t = 0
        if b_ef > 0:
            term_t += w["w1"] * ef_saturation * x1_eff[t]              # Term 1
        if b_ret > 0:
            term_t += w["w2"] * x2_eff[t]                              # Term 2 (capped)
        dti = inp.D_min / max(EPS, inp.I_gross)
        term_t += w["w3"] * (1 - dti)                                  # Term 3
        if inp.I_net > 0:
            term_t += w["w4"] * (1 - x5[t] / inp.I_net)                # Term 4
        term_t += w["w5"] * (y1[t] + y2_val + y3_val + y4[t]) / 4.0    # Term 5
        if inp.D_hi > 0:
            term_t += w["w6"] * (1 - D_hi[t] / inp.D_hi)               # Term 6
        else:
            term_t += w["w6"]
        term_t += w["w8"] * y5[t]                                      # Term 8
        if b_invest > 0:
            term_t += w["w9"] * invest_activation * x6_eff[t]          # Term 9

        obj += disc * term_t

    # Terminal-state bonus — reward the LP for paying down HI debt rather
    # than plateauing at a break-even marginal. Critical for large-balance
    # profiles: `term 6` reward per $ = w6 / D_hi_init, which is tiny at
    # D_hi=30k (~6e-6) and loses to term-2 (retirement) per-$ (~3.3e-5).
    # Scale the terminal weight with HI-debt urgency: users whose HI debt is
    # at or above 25% of annual gross get a 4.0 multiplier (makes x3 the
    # dominant allocation); low-HI-debt users keep the 0.80 baseline.
    if inp.D_hi > 0:
        hi_debt_ratio = inp.D_hi / max(EPS, annual_salary)
        terminal_weight = 0.80 + 3.20 * min(1.0, hi_debt_ratio / 0.25)
        obj += terminal_weight * (1 - D_hi[periods - 1] / inp.D_hi)

    prob += obj

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    if prob.status != 1:
        sol.status = "Infeasible"
        return sol

    sol.status = "Optimal"
    sol.x = [
        {
            "x1_ef_savings":      float(pulp.value(x1[t]) or 0.0),
            "x2_retirement":      float(pulp.value(x2[t]) or 0.0),
            "x3_hi_debt_paydown": float(pulp.value(x3[t]) or 0.0),
            "x4_lo_debt_paydown": float(pulp.value(x4[t]) or 0.0),
            "x5_discretionary":   float(pulp.value(x5[t]) or 0.0),
            "x6_investment":      float(pulp.value(x6[t]) or 0.0),
        }
        for t in range(periods)
    ]

    sol.state_trajectory = []
    for t in range(periods):
        sliq = float(pulp.value(S_liq[t]) or 0.0)
        sret = float(pulp.value(S_ret[t]) or 0.0)
        dhi  = float(pulp.value(D_hi[t])  or 0.0)
        dlo  = float(pulp.value(D_lo[t])  or 0.0)
        prev_dhi = inp.D_hi if t == 0 else float(pulp.value(D_hi[t-1]) or 0.0)
        prev_dlo = inp.D_lo if t == 0 else float(pulp.value(D_lo[t-1]) or 0.0)
        sol.state_trajectory.append({
            "S_liq": sliq,
            "S_ret": sret,
            "D_hi":  dhi,
            "D_lo":  dlo,
            "D_min": scale_dmin * (prev_dhi + prev_dlo),
        })

    # Summary milestone snapshot at the end of the horizon
    sol.y = {
        "y1_ef_adequate":          int(pulp.value(y1[-1]) or 0),
        "y2_life_insurance":       y2_val,
        "y3_disability_insurance": y3_val,
        "y4_retirement_ontrack":   int(pulp.value(y4[-1]) or 0),
        "y5_hi_debt_eliminated":   int(pulp.value(y5[-1]) or 0),
    }
    sol.z  = float(pulp.value(D_hi[-1]) or 0.0)
    sol.z2 = 0.0
    sol.objective_value = float(pulp.value(prob.objective) or 0.0)
    sol.objective_terms["ef_saturation"]     = ef_saturation
    sol.objective_terms["invest_activation"] = invest_activation
    sol.objective_terms["periods"]           = periods
    # Retained so compute_fhs can credit realized plan-driven contributions
    # when scoring projected states along the horizon.
    sol.objective_terms["initial_S_ret"]     = inp.S_ret

    return sol


# ═══════════════════════════════════════════
# FHS COMPUTATION (Ch. 3.2)
# ═══════════════════════════════════════════

def compute_fhs(inp: IndividualInput, sol: LPSolution, round_output: bool = True) -> tuple:
    """Compute FHS as direct composite of financial state metrics.
    
    MVP approach: score current state directly against benchmarks using PLAs.
    Phase 2 (with Plaid allocation data): switch to D_weighted(Actual, LP_Optimal).
    """
    if sol.status != "Optimal":
        return 300.0, {}

    annual_salary = inp.I_gross * 12
    age_tgt = age_target(inp.age, annual_salary)
    I = max(EPS, inp.I_gross)
    disposable = inp.I_net - inp.E_ess - inp.D_min

    breakdown = {}
    composite = 0.0

    # 1. Emergency Fund (weight 0.18) — months of expenses covered
    ef_months = inp.S_liq / max(EPS, inp.E_ess)
    score = pla_thresh(ef_months)  # 0-24 months → 0-1
    composite += 0.18 * score
    breakdown["Emergency fund"] = {"value": round(ef_months, 1), "unit": "months", "score": round(score, 3), "weight": 0.18}

    # 2. Debt Health (weight 0.22) — DTI + HI debt burden + LO debt burden,
    # with capacity penalty: if the user is missing any debt minimums, collapse
    # the score proportionally. A user "paying 20% DTI" who can't actually
    # make the payments is not in good debt health.
    dti = inp.D_min / I
    dti_score = pla_acc(1 - dti)  # Lower DTI = higher score
    hi_debt_burden = inp.D_hi / max(EPS, annual_salary)
    hi_score = pla_acc(1 - min(1, hi_debt_burden * 2))  # HI debt < 50% salary = good
    # LO debt burden: other debts (student loans, car loans, mortgage principal).
    # Infer an allowance for mortgage principal from monthly housing cost
    # (30-yr @ ~6% ≈ 150× monthly payment) so homeowners aren't punished for
    # carrying a reasonable mortgage. Excess non-mortgage LO debt is what hurts.
    mortgage_allowance = inp.E_house * 150.0
    lo_net = max(0.0, inp.D_lo - mortgage_allowance)
    lo_burden_excess = min(1.0, lo_net / max(EPS, 0.5 * annual_salary))  # 50% of salary = full penalty
    lo_score = 1.0 - lo_burden_excess
    debt_score = 0.5 * dti_score + 0.3 * hi_score + 0.2 * lo_score
    # Capacity penalty: full shortfall = score floored at 20% of nominal
    capacity_shortfall = sol.objective_terms.get("debt_shortfall", 0.0) if sol.objective_terms else 0.0
    if capacity_shortfall > 0 and inp.D_min > 0:
        capacity_factor = max(0.20, 1.0 - (capacity_shortfall / inp.D_min))
        debt_score *= capacity_factor
    composite += 0.22 * debt_score
    breakdown["Debt health"] = {"DTI": round(dti, 3), "HI_burden": round(hi_debt_burden, 3), "shortfall": round(capacity_shortfall, 0), "score": round(debt_score, 3), "weight": 0.22}

    # 3. Savings Capacity (weight 0.15) — disposable/income ratio
    savings_capacity = max(0, disposable) / max(EPS, inp.I_net)
    score = pla_dim(savings_capacity / 0.30)  # 30% disposable = 1.0 target
    composite += 0.15 * score
    breakdown["Savings capacity"] = {"value": round(savings_capacity, 3), "score": round(score, 3), "weight": 0.15}

    # 4. Housing Affordability (weight 0.08) — housing/income ratio. Full credit
    # below the classic 28% threshold; linear drop to zero at 45%. (Previous
    # version piped a goodness signal through pla_acc, inverting the curve so
    # that good housing scored low — fixed here.)
    housing_ratio = inp.E_house / I
    if housing_ratio <= 0.28:
        score = 1.0
    elif housing_ratio >= 0.45:
        score = 0.0
    else:
        score = 1.0 - (housing_ratio - 0.28) / (0.45 - 0.28)
    composite += 0.08 * score
    breakdown["Housing"] = {"ratio": round(housing_ratio, 3), "score": round(score, 3), "weight": 0.08}

    # 5. Retirement Progress (weight 0.15) — on track vs age target
    ret_progress = inp.S_ret / max(EPS, age_tgt)
    score = pla_dim(ret_progress)  # 0 = nothing saved, 1 = at target, >1 = ahead
    # Plan-contribution credit: when projecting along the multi-period horizon,
    # compute_fhs is called with a proj_inp whose S_ret has grown from the LP's
    # monthly contributions. Without this bonus, the PLA's diminishing-returns
    # curve saturates in the 0.25–0.70 zone so a $4k/month plan contribution
    # barely moves the needle. Add up to +0.15 score once the cumulative
    # contribution meets a 6-month target of 7.5% of annual gross.
    initial_S_ret = sol.objective_terms.get("initial_S_ret") if sol.objective_terms else None
    if initial_S_ret is not None and inp.S_ret > initial_S_ret:
        cum_contrib = inp.S_ret - initial_S_ret
        target_6mo  = 0.075 * annual_salary
        contrib_bonus = 0.15 * min(1.0, cum_contrib / max(EPS, target_6mo))
        score = min(1.0, score + contrib_bonus)
    composite += 0.15 * score
    breakdown["Retirement"] = {"progress": round(ret_progress, 3), "target": round(age_tgt, 0), "score": round(score, 3), "weight": 0.15}

    # 6. Financial Resilience (weight 0.15) — insurance + protective milestones.
    # Changed from 4 to 5 milestones with a softer retirement threshold
    # (on-track at 50% of age target, not at target). The old threshold of
    # "S_ret >= full age_tgt" was unreachable for even excellent profiles
    # before ~age 60, so it was not a meaningful signal.
    milestones = [
        inp.S_liq >= 3 * inp.E_ess,                 # 3+ month emergency fund
        inp.has_life_insurance,
        inp.has_disability_insurance,
        inp.S_ret >= 0.5 * age_tgt,                 # on track for retirement
        inp.D_hi == 0,                              # free of high-interest debt
    ]
    milestone_count = sum(1 for m in milestones if m)
    score = milestone_count / 5.0
    composite += 0.15 * score
    breakdown["Resilience"] = {"milestones": milestone_count, "of": 5, "score": round(score, 3), "weight": 0.15}

    # 7. LP Optimization Gap (weight 0.07) — how close to optimal allocation?
    # Down-weighted from 0.12: the LP objective includes constants that reflect
    # user-state (no HI debt bonus, low DTI) which double-counts signals scored
    # elsewhere. Now a tiebreaker, not a headline dimension.
    # Max achievable objective depends on the EF saturation applied in the LP:
    # when the user already has 6+ months of runway, Term 1's ceiling drops to
    # w1·ef_saturation instead of w1. Adjust obj_max accordingly so a
    # well-optimized plan still hits ratio = 1.0.
    ef_sat   = sol.objective_terms.get("ef_saturation",     1.0) if sol.objective_terms else 1.0
    inv_act  = sol.objective_terms.get("invest_activation", 1.0) if sol.objective_terms else 1.0
    w1_ceiling = WEIGHTS.get("w1", 0) * ef_sat
    w9_ceiling = WEIGHTS.get("w9", 0) * inv_act
    # w2 is now capped at 1.0x of its target rate via x2_eff — use raw weight
    # as ceiling (was implicitly uncapped before, which overstated obj_max).
    obj_max = w1_ceiling + w9_ceiling + sum(v for k, v in WEIGHTS.items() if k not in ("w7", "w1", "w9"))
    # Multi-period objective sums per-period terms with time discounts. Scale
    # obj_max by the discount-sum so the ratio stays comparable to single-period.
    periods = sol.objective_terms.get("periods", 1) if sol.objective_terms else 1
    if periods > 1:
        disc_sum = sum(1.0 / (1.02 ** t) for t in range(periods))
        obj_max *= disc_sum
    obj_ratio = sol.objective_value / max(EPS, obj_max)
    obj_ratio = min(1.0, max(0.0, obj_ratio))
    score = obj_ratio
    composite += 0.07 * score
    breakdown["LP optimization"] = {"objective": round(sol.objective_value, 4), "ratio": round(obj_ratio, 3), "score": round(score, 3), "weight": 0.07}

    # ── Vulnerability (red-flag) multiplier ──
    # The dimensional composite rewards surface ratios (DTI, housing %, cash-flow
    # margin) that a struggling user may nominally pass while still being in
    # fragile shape. Each of these hard-vulnerability signals multiplicatively
    # compresses the composite: −7% per flag, floored at 60% of the nominal score.
    ret_progress_for_flag = inp.S_ret / max(EPS, age_tgt)
    shortfall_for_flag = sol.objective_terms.get("debt_shortfall", 0.0) if sol.objective_terms else 0.0
    flags = [
        inp.S_liq < 2 * inp.E_ess,                                  # EF under 2 months
        (ret_progress_for_flag < 0.25) if inp.age < 40 else (ret_progress_for_flag < 0.50),
        inp.D_hi > 0,                                               # any HI debt
        not (inp.has_life_insurance or inp.has_disability_insurance),  # no insurance at all
        shortfall_for_flag > 0,                                     # missing debt minimums
        (inp.overdraft_count_90d + inp.late_payment_count_90d) > 0,  # behavioral strain
    ]
    flag_count = sum(1 for f in flags if f)
    vuln_multiplier = max(0.60, 1.0 - 0.07 * flag_count)
    composite *= vuln_multiplier
    breakdown["_vulnerability"] = {"flags": flag_count, "multiplier": round(vuln_multiplier, 3)}

    # Clamp and scale
    composite = min(1.0, max(0.0, composite))
    fhs = 300 + 550 * composite
    fhs = min(850.0, max(300.0, fhs))
    if round_output:
        fhs = round(fhs)

    return fhs, breakdown


# ═══════════════════════════════════════════
# FSS COMPUTATION (Ch. 3.3)
# ═══════════════════════════════════════════

def compute_fss(inp: IndividualInput, sol: LPSolution) -> tuple:
    """Compute Financial Strain Score from constraint violations."""
    I = max(EPS, inp.I_gross)
    breakdown = {}
    total = 0

    # AsymmetryMult — temporal momentum adjustment (Ch. 3.3). Declining users
    # get amplified strain; improving users get dampened strain. Applied to
    # every weighted FSS component.
    m = inp.momentum_slope
    if m < 0:
        asym = 1.0 + 0.30 * abs(m)
    elif m > 0:
        asym = max(0.0, 1.0 - 0.15 * m)
    else:
        asym = 1.0
    breakdown["_asymmetry"] = {"momentum_slope": round(m, 3), "multiplier": round(asym, 3)}

    # s₁⁻: EF deficit
    ef_target_3mo = 3 * inp.E_ess
    ef_deficit = max(0, ef_target_3mo - inp.S_liq)
    tol_ef = ef_target_3mo if ef_target_3mo > 0 else 1
    ratio = min(1.0, ef_deficit / tol_ef)
    contrib = 0.20 * pla_acc(ratio)
    breakdown["EF deficit"] = {"deficit": round(ef_deficit, 0), "pla": round(pla_acc(ratio), 3), "weighted": round(contrib, 4)}
    contrib *= asym
    total += contrib

    # s₂⁻: DTI excess. Standard mortgage-industry guidance flags back-end DTI
    # above 28%; we start counting strain there (was 36%, too lenient for the
    # "Stretched" archetype at 32.7%) and saturate at 48% DTI.
    dti = inp.D_min / I
    dti_excess = max(0, dti - 0.28)
    tol_dti = 0.20
    ratio = min(1.0, dti_excess / tol_dti)
    contrib = 0.20 * pla_acc(ratio)
    breakdown["DTI excess"] = {"deficit": round(dti_excess, 4), "pla": round(pla_acc(ratio), 3), "weighted": round(contrib, 4)}
    contrib *= asym
    total += contrib

    # HI debt burden — outstanding high-interest balance relative to annual income.
    # Full strain weight when HI debt reaches 40% of annual income.
    annual_income = 12 * I
    hi_burden_ratio = min(1.0, inp.D_hi / max(EPS, annual_income * 0.40))
    contrib = 0.12 * pla_acc(hi_burden_ratio)
    breakdown["HI debt burden"] = {"balance": inp.D_hi, "pla": round(pla_acc(hi_burden_ratio), 3), "weighted": round(contrib, 4)}
    contrib *= asym
    total += contrib

    # s₃⁻: Savings rate deficit
    actual_savings_rate = 0
    if sol.status == "Optimal":
        x = _x_month0(sol)
        x1 = x.get("x1_ef_savings", 0)
        x2 = x.get("x2_retirement", 0)
        x6 = x.get("x6_investment", 0)
        actual_savings_rate = (x1 + x2 + x6) / I
    sr_deficit = max(0, 0.20 - actual_savings_rate)
    tol_sr = 0.20
    ratio = min(1.0, sr_deficit / tol_sr)
    contrib = 0.15 * pla_acc(ratio)
    breakdown["Savings rate deficit"] = {"deficit": round(sr_deficit, 4), "pla": round(pla_acc(ratio), 3), "weighted": round(contrib, 4)}
    contrib *= asym
    total += contrib

    # s₄⁻: Housing excess
    housing_ratio = inp.E_house / I
    housing_excess = max(0, housing_ratio - 0.28)
    tol_housing = 0.08
    ratio = min(1.0, housing_excess / tol_housing)
    contrib = 0.10 * pla_acc(ratio)
    breakdown["Housing excess"] = {"deficit": round(housing_excess, 4), "pla": round(pla_acc(ratio), 3), "weighted": round(contrib, 4)}
    contrib *= asym
    total += contrib

    # Behavioral alerts
    alert_count = inp.overdraft_count_90d + inp.late_payment_count_90d
    alert_ratio = min(1.0, alert_count / 5.0)  # 5 alerts = full penalty
    contrib = 0.10 * pla_acc(alert_ratio)
    breakdown["Behavioral alerts"] = {"count": alert_count, "pla": round(pla_acc(alert_ratio), 3), "weighted": round(contrib, 4)}
    contrib *= asym
    total += contrib

    # Debt-minimum shortfall — user cannot cover required debt payments from
    # take-home after essentials. This is the #1 signal of acute financial
    # distress and must dominate FSS when present. Tolerance: full shortfall
    # relative to required D_min.
    debt_shortfall = 0.0
    if sol.status == "Optimal" and sol.objective_terms:
        debt_shortfall = sol.objective_terms.get("debt_shortfall", 0.0)
    # Tolerance: 25% of required D_min missed = full strain (sharper than before).
    shortfall_tol = max(EPS, 0.25 * inp.D_min)
    shortfall_ratio = min(1.0, debt_shortfall / shortfall_tol) if inp.D_min > 0 else 0
    contrib = 0.20 * pla_acc(shortfall_ratio)
    breakdown["Debt payment shortfall"] = {"amount": round(debt_shortfall, 0), "pla": round(pla_acc(shortfall_ratio), 3), "weighted": round(contrib, 4)}
    contrib *= asym
    total += contrib

    # Insurance coverage gap — missing life/disability protection creates
    # tail-risk strain that doesn't show up in cashflow metrics. Small per-gap
    # weight so fully-covered profiles stay low.
    ins_gap = 0.0
    if not inp.has_life_insurance:
        ins_gap += 0.5
    if not inp.has_disability_insurance:
        ins_gap += 0.5
    contrib = 0.08 * ins_gap
    breakdown["Insurance gap"] = {"missing_life": int(not inp.has_life_insurance),
                                   "missing_disab": int(not inp.has_disability_insurance),
                                   "weighted": round(contrib, 4)}
    contrib *= asym
    total += contrib

    # Retirement progress gap — strain scaled by age (minimal impact for young
    # savers, dominant for those nearing retirement).
    annual_salary = 12 * I
    age_tgt_fss = age_target(inp.age, annual_salary)
    ret_progress = inp.S_ret / max(EPS, age_tgt_fss)
    ret_gap = max(0.0, 1.0 - ret_progress)
    age_factor = max(0.0, min(1.0, (inp.age - 25) / 30.0))
    contrib = 0.10 * age_factor * ret_gap
    breakdown["Retirement gap"] = {"progress": round(ret_progress, 3),
                                    "age_factor": round(age_factor, 3),
                                    "weighted": round(contrib, 4)}
    contrib *= asym
    total += contrib

    # FVI placeholder (simplified: negative if debt growing or savings shrinking)
    fvi_contrib = 0.0  # Neutral for snapshot (no temporal data)
    breakdown["FVI momentum"] = {"value": 0, "pla": 0, "weighted": 0}
    total += fvi_contrib

    fss = round(100 * min(1.0, max(0.0, total)))
    return fss, breakdown


# ═══════════════════════════════════════════
# FRS COMPUTATION (Ch. 3.4)
# ═══════════════════════════════════════════

def compute_frs(inp: IndividualInput, sol: LPSolution, previous: Optional[dict] = None) -> tuple:
    """Compute Financial Recovery Score (Ch. 3.4) via gap-closure across five
    recovery dimensions, scaled by the engagement MomentumFactor.

    Falls back to a snapshot FRS (baseline + slope, scaled by streak) when no
    30-day comparison snapshot is available.
    """
    # MomentumFactor: 30 days of engagement = 1.08x, 6 months ≈ 1.48x, capped at 1.5x.
    momentum_factor = min(1.5, 1.0 + (inp.streak_days / 30.0) * 0.08)
    base = 50.0 + 20.0 * max(-1.0, min(1.0, inp.momentum_slope))

    # Resolve previous from arg or input object — FIRST, so the real-snapshot
    # branch can take priority over the LP projection. Observed improvement
    # beats projected improvement.
    if previous is None:
        previous = inp.previous

    # Branch 2 (fallback when no real snapshot): LP multi-period trajectory.
    if previous is None and sol.state_trajectory and len(sol.state_trajectory) >= 2:
        s0 = sol.state_trajectory[0]
        s1 = sol.state_trajectory[1]
        I_net = max(EPS, inp.I_net)

        def clamp(x): return max(-1.0, min(1.0, x))

        closure_debt     = clamp(((s0["D_hi"] + 0.3*s0["D_lo"]) - (s1["D_hi"] + 0.3*s1["D_lo"])) / I_net)
        closure_savings  = clamp(((s1["S_liq"] - s0["S_liq"]) + (s1["S_ret"] - s0["S_ret"])) / I_net)
        closure_spending = 0.0   # spending doesn't change month-to-month in LP
        closure_income   = 0.0   # income is fixed in LP horizon
        # Milestone delta between month-1 and month-0 projected states
        annual_salary = 12 * max(EPS, inp.I_gross)
        age_tgt_v = age_target(inp.age, annual_salary)
        def _miles(st):
            return sum([
                st["S_liq"] >= 3 * inp.E_ess,
                st["S_ret"] >= 0.5 * age_tgt_v,
                st["D_hi"] == 0,
            ])
        closure_milestones = clamp((_miles(s1) - _miles(s0)) / 5.0)

        w = {"debt": 0.30, "savings": 0.25, "spending": 0.20, "income": 0.10, "milestones": 0.15}
        weighted_closure = (
            w["debt"]       * closure_debt +
            w["savings"]    * closure_savings +
            w["spending"]   * closure_spending +
            w["income"]     * closure_income +
            w["milestones"] * closure_milestones
        )
        frs_val = base + 50.0 * weighted_closure * momentum_factor
        frs_val = max(0.0, min(100.0, frs_val))
        return round(frs_val), {
            "source": "multiperiod_trajectory",
            "base": round(base, 2),
            "momentum_factor": round(momentum_factor, 3),
            "weighted_closure": round(weighted_closure, 4),
            "dimensions": {
                "debt_reduction":        {"closure": round(closure_debt, 3)},
                "savings_building":      {"closure": round(closure_savings, 3)},
                "milestone_achievement": {"closure": round(closure_milestones, 3)},
            },
        }

    # Branch 3 (last resort): baseline — reached only when NEITHER a real
    # snapshot NOR a multi-period LP trajectory is available.
    if previous is None:
        frs_val = max(0.0, min(100.0, base * momentum_factor))
        return round(frs_val), {
            "source": "baseline",
            "note": "Snapshot FRS: baseline + momentum slope, scaled by streak.",
            "streak_days": inp.streak_days,
            "momentum_factor": round(momentum_factor, 3),
            "momentum_slope": round(inp.momentum_slope, 3),
            "base": round(base, 2),
        }

    # Branch 1: Real 30-day snapshot gap-closure. Takes priority — runs
    # whenever `previous` is non-None, regardless of LP trajectory availability.

    # ── Gap-closure dimensions ──────────────────────────────────────────────
    p = previous
    S_liq_p   = p.get("S_liq", inp.S_liq)
    S_ret_p   = p.get("S_ret", inp.S_ret)
    D_hi_p    = p.get("D_hi",  inp.D_hi)
    D_lo_p    = p.get("D_lo",  inp.D_lo)
    E_ess_p   = p.get("E_ess", inp.E_ess)
    I_gross_p = p.get("I_gross", inp.I_gross)
    has_life_p  = p.get("has_life_insurance", inp.has_life_insurance)
    has_disab_p = p.get("has_disability_insurance", inp.has_disability_insurance)

    I_net = max(EPS, inp.I_net)

    def clamp(x):
        return max(-1.0, min(1.0, x))

    # 1. Debt reduction — HI debt weighted heavier (1.0 vs 0.3 for LO).
    debt_prev = D_hi_p   + 0.3 * D_lo_p
    debt_curr = inp.D_hi + 0.3 * inp.D_lo
    closure_debt = clamp((debt_prev - debt_curr) / I_net)

    # 2. Savings building — combined liquid + retirement growth, normalized to monthly net income.
    savings_delta = (inp.S_liq - S_liq_p) + (inp.S_ret - S_ret_p)
    closure_savings = clamp(savings_delta / I_net)

    # 3. Spending optimization — drop in essential outflow.
    closure_spending = clamp((E_ess_p - inp.E_ess) / I_net)

    # 4. Income growth — relative to previous gross income.
    if I_gross_p > 0:
        closure_income = clamp((inp.I_gross - I_gross_p) / I_gross_p)
    else:
        closure_income = 0.0

    # 5. Milestone achievement — net new milestones earned vs lost.
    annual_salary = 12 * max(EPS, inp.I_gross)
    age_tgt_v = age_target(inp.age, annual_salary)

    def milestones(s_liq, s_ret, d_hi, life, disab, e_ess):
        return sum([
            s_liq >= 3 * e_ess,
            bool(life),
            bool(disab),
            s_ret >= 0.5 * age_tgt_v,
            d_hi == 0,
        ])
    miles_curr = milestones(inp.S_liq, inp.S_ret, inp.D_hi,
                            inp.has_life_insurance, inp.has_disability_insurance, inp.E_ess)
    miles_prev = milestones(S_liq_p, S_ret_p, D_hi_p,
                            has_life_p, has_disab_p, E_ess_p)
    closure_milestones = clamp((miles_curr - miles_prev) / 5.0)

    # Weighted aggregation per spec.
    w = {"debt": 0.30, "savings": 0.25, "spending": 0.20, "income": 0.10, "milestones": 0.15}
    weighted_closure = (
        w["debt"]       * closure_debt +
        w["savings"]    * closure_savings +
        w["spending"]   * closure_spending +
        w["income"]     * closure_income +
        w["milestones"] * closure_milestones
    )

    # Compose FRS: momentum-adjusted slope baseline + amplified gap closure scaled by engagement.
    frs_val = base + 50.0 * weighted_closure * momentum_factor
    frs_val = max(0.0, min(100.0, frs_val))

    return round(frs_val), {
        "source": "real_snapshot",
        "base": round(base, 2),
        "momentum_factor": round(momentum_factor, 3),
        "weighted_closure": round(weighted_closure, 4),
        "dimensions": {
            "debt_reduction":        {"weight": w["debt"],       "closure": round(closure_debt, 3)},
            "savings_building":      {"weight": w["savings"],    "closure": round(closure_savings, 3)},
            "spending_optimization": {"weight": w["spending"],   "closure": round(closure_spending, 3)},
            "income_growth":         {"weight": w["income"],     "closure": round(closure_income, 3)},
            "milestone_achievement": {"weight": w["milestones"], "closure": round(closure_milestones, 3)},
        },
        "milestones_curr": miles_curr,
        "milestones_prev": miles_prev,
    }


# ═══════════════════════════════════════════
# INSIGHTS (plain-language commentary per dimension)
# ═══════════════════════════════════════════

def generate_insights(inp: IndividualInput, fhs_breakdown: dict, fss_breakdown: dict) -> dict:
    """One-line human insight per scoring dimension.

    FHS insights are emitted only for dimensions scoring below 80% (good
    scores don't need commentary). FSS insights are returned for the top
    2–3 strain contributors with non-trivial weight.
    """
    insights = {"fhs": {}, "fss": {}}

    # ── FHS dimensions ────────────────────────────────────────────────
    ef = fhs_breakdown.get("Emergency fund", {})
    months = ef.get("value", 0)
    score = ef.get("score", 0)
    if score < 0.80:
        if score >= 0.50:
            insights["fhs"]["Emergency fund"] = (
                f"You have {months:.1f} months saved — the sweet spot is 6 months."
            )
        else:
            insights["fhs"]["Emergency fund"] = (
                f"Only {months:.1f} months of runway — this is your most vulnerable spot."
            )

    dh = fhs_breakdown.get("Debt health", {})
    score = dh.get("score", 0)
    est_interest = inp.D_hi * 0.20 / 12.0   # rough 20% APR estimate
    if score < 0.80:
        if score >= 0.40:
            insights["fhs"]["Debt health"] = (
                f"Manageable for now, but costing you about ${est_interest:,.0f}/month in interest."
            )
        else:
            insights["fhs"]["Debt health"] = (
                f"High-interest debt is eating about ${est_interest:,.0f}/month — this is priority #1."
            )

    sc = fhs_breakdown.get("Savings capacity", {})
    score = sc.get("score", 0)
    if score < 0.80:
        if score >= 0.30:
            insights["fhs"]["Savings capacity"] = (
                "Decent margin, but not much room for surprises."
            )
        else:
            insights["fhs"]["Savings capacity"] = (
                "Very tight — most of your income is already spoken for."
            )

    ret = fhs_breakdown.get("Retirement", {})
    score = ret.get("score", 0)
    progress = ret.get("progress", 0)
    gap_pct = max(0, 100 - progress * 100)
    if score < 0.80:
        # Age-conditional framing: young users need encouragement, not
        # "you're 92% behind" — mathematically defensible, emotionally
        # crushing, and genuinely unhelpful at age 25.
        if inp.age < 25:
            insights["fhs"]["Retirement"] = (
                "Start early — any amount you save now compounds for 40+ years."
            )
        elif inp.age < 30:
            insights["fhs"]["Retirement"] = (
                "Ahead of where most people start — keep the habit going."
            )
        elif score >= 0.40:
            insights["fhs"]["Retirement"] = (
                f"Behind target by about {gap_pct:.0f}% — catching up is still very doable."
            )
        else:
            insights["fhs"]["Retirement"] = (
                "Significantly behind — even small monthly increases compound over decades."
            )

    # ── FSS top contributors (top 3 with weighted > 1%) ───────────────
    I = max(EPS, inp.I_gross)
    fss_items = sorted(
        (
            (k, v) for k, v in fss_breakdown.items()
            if not k.startswith("_") and isinstance(v, dict) and v.get("weighted", 0) > 0.01
        ),
        key=lambda kv: kv[1].get("weighted", 0),
        reverse=True,
    )[:3]
    for k, _v in fss_items:
        if k == "EF deficit":
            insights["fss"][k] = "Your biggest risk right now: no cushion for emergencies."
        elif k == "DTI excess":
            dti_pct = (inp.D_min / I) * 100
            insights["fss"][k] = (
                f"{dti_pct:.0f}% of income goes to debt — above the 36% threshold lenders watch."
            )
        elif k == "Savings rate deficit":
            insights["fss"][k] = (
                "You're saving less than recommended — even $50 more a month helps."
            )
        elif k == "Housing excess":
            housing_pct = (inp.E_house / I) * 100
            insights["fss"][k] = (
                f"Housing takes {housing_pct:.0f}% of income — above 28% starts to squeeze everything else."
            )

    return insights


# ═══════════════════════════════════════════
# RECOMMENDATIONS
# ═══════════════════════════════════════════

def generate_recommendations(inp: IndividualInput, sol: LPSolution) -> list:
    """Translate the LP optimal allocation into 3–5 plain-language actions.

    Each recommendation: {action, impact, priority (1=most urgent), reason}.
    Sorted by ascending priority and capped at 5.
    """
    recs = []
    if sol.status != "Optimal":
        return recs

    x0 = _x_month0(sol)
    x1 = x0.get("x1_ef_savings", 0)
    x2 = x0.get("x2_retirement", 0)
    x3 = x0.get("x3_hi_debt_paydown", 0)
    x5 = x0.get("x5_discretionary", 0)
    y4 = sol.y.get("y4_retirement_ontrack", 0)

    # Append phased plan summary as the final recommendation if multi-period
    phases = _build_plan_phases(sol, inp) if sol.state_trajectory else []

    I_gross = max(EPS, inp.I_gross)
    disposable = inp.I_net - inp.E_ess - inp.D_min
    ef_target = 3 * inp.E_ess
    ef_months = inp.S_liq / max(EPS, inp.E_ess)

    # 1) DTI red flag — usually the highest-priority structural issue.
    dti = inp.D_min / I_gross
    if dti > 0.36:
        recs.append({
            "action": f"Restructure debt — your minimums consume {dti*100:.0f}% of gross income",
            "impact": "FSS",
            "priority": 1,
            "reason": "Healthy back-end DTI is under 36%. Consolidate or refinance the highest-rate balances first.",
        })

    # 2) Emergency fund. Surface whenever EF is below the 3-month floor —
    # even if the LP routed cash to higher-yield uses (e.g. high-APR debt),
    # the user should know the gap exists and what monthly contribution closes it.
    if inp.S_liq < ef_target:
        priority = 1 if ef_months < 1 else 2
        # Use the LP's allocation if non-zero; otherwise suggest 5% of disposable
        # (a sensible starter contribution) with a $50 floor.
        suggested = x1 if x1 > 0 else max(50.0, 0.05 * max(0.0, disposable))
        framing = (
            "Once your high-interest debt is paid down, redirect this amount to your emergency fund."
            if x1 == 0 and x3 > 0 else
            "Three months is the minimum buffer to absorb income shocks."
        )
        recs.append({
            "action": f"Save ${suggested:,.0f}/month toward your emergency fund (target ${ef_target:,.0f})",
            "impact": "FHS",
            "priority": priority,
            "reason": (
                f"You currently have {ef_months:.1f} months of essential expenses saved. {framing}"
            ),
        })

    # 3) High-interest debt paydown.
    if x3 > 0 and inp.D_hi > 0:
        months_to_clear = inp.D_hi / max(EPS, x3)
        priority = 1 if inp.D_hi > 6 * I_gross else 2
        if months_to_clear <= 60:
            action = (
                f"Put ${x3:,.0f}/month against your high-interest debt to clear it "
                f"in ~{months_to_clear:.0f} {'month' if round(months_to_clear) == 1 else 'months'}"
            )
            reason = (
                f"You carry ${inp.D_hi:,.0f} in high-interest balances. "
                f"Compounding above 15% APR erodes net worth faster than any investment can grow it."
            )
        else:
            # At this paydown pace the full payoff is >5 years away — quoting the
            # horizon discourages the user. Reframe as "what this gets you in a year."
            assumed_apr = 0.20
            interest_saved_year = inp.D_hi * assumed_apr * (x3 * 12) / max(inp.D_hi, EPS)
            interest_saved_year = min(interest_saved_year, x3 * 12 * assumed_apr * 6)  # rough cap
            interest_saved_year = round(max(50.0, interest_saved_year) / 10) * 10
            action = (
                f"Paying even ${x3:,.0f}/month toward your high-interest debt "
                f"saves you about ${interest_saved_year:,.0f} in interest over the next year"
            )
            reason = (
                f"Your ${inp.D_hi:,.0f} in high-interest balances is tough to clear fast, "
                f"but every dollar reduces the 20%+ APR compounding against you."
            )
        recs.append({"action": action, "impact": "FHS", "priority": priority, "reason": reason})

    # 4) Retirement gap.
    if x2 > 0 and not y4:
        annual_salary = 12 * I_gross
        target = age_target(inp.age, annual_salary)
        progress_pct = (inp.S_ret / max(EPS, target)) * 100
        gap_pct = max(0, 100 - progress_pct)
        # Age-conditional framing — young users get encouragement instead of
        # a gap percentage that reads as demoralizing.
        if inp.age < 25:
            reason = ("Start early — any amount you save now compounds for 40+ years. "
                      "You're setting a foundation most people wait too long to start.")
        elif inp.age < 30:
            reason = ("Ahead of where most people start. Consistency beats catch-up — "
                      "keep the habit going and it grows on autopilot.")
        else:
            reason = (
                f"At your age the target for your age is roughly ${target:,.0f}; "
                f"you're about {gap_pct:.0f}% behind. "
                f"Consistent contributions today compound into the next decade."
            )
        recs.append({
            "action": f"Direct ${x2:,.0f}/month into retirement savings",
            "impact": "FHS",
            "priority": 2 if inp.age >= 40 else 3,
            "reason": reason,
        })

    # 5) Over-spending on discretionary.
    if disposable > 0 and x5 > 0.30 * disposable:
        target_x5 = 0.30 * disposable
        excess = x5 - target_x5
        recs.append({
            "action": f"Cap discretionary spending around ${target_x5:,.0f}/month (currently allocated ${x5:,.0f})",
            "impact": "FSS",
            "priority": 3,
            "reason": (
                f"You're allocating ${excess:,.0f} above the 30%-of-disposable guideline. "
                f"Redirecting that to debt or savings accelerates every other goal."
            ),
        })

    # 6) Insurance gaps — protective milestones.
    if not inp.has_life_insurance:
        recs.append({
            "action": "Get term life insurance",
            "impact": "FHS",
            "priority": 3,
            "reason": "Life coverage is one of five resilience milestones; term policies are inexpensive at younger ages.",
        })
    if not inp.has_disability_insurance:
        recs.append({
            "action": "Add disability insurance to your benefits",
            "impact": "FHS",
            "priority": 3,
            "reason": "Disability is a top cause of unplanned income loss; check whether your employer offers it.",
        })

    # 7) Behavioral hygiene — overdrafts/late payments push FSS up sharply.
    alerts = inp.overdraft_count_90d + inp.late_payment_count_90d
    if alerts > 0:
        recs.append({
            "action": "Set up autopay and overdraft alerts on every account",
            "impact": "FSS",
            "priority": 2,
            "reason": (
                f"You've had {alerts} overdraft/late-payment events in the last 90 days. "
                f"Each one signals strain to lenders and inflates strain scoring."
            ),
        })

    # Sort by priority asc, stable on insertion order (for ties).
    recs.sort(key=lambda r: r["priority"])

    # Ensure we always return at least 3 recommendations by topping up with
    # general-purpose nudges if the rule set produced fewer.
    fallbacks = [
        {
            # Phase 6 polish (Pass 1, WI-3d) — reframed from the prior
            # "Track every dollar for the next 30 days" copy, which read as
            # obligatory / shame-coded for users already doing well. The
            # weekly check-in framing keeps the engagement signal without
            # implying the user is failing to manage their money.
            "action": "Check in weekly on your spending",
            "impact": "FRS",
            "priority": 4,
            "reason": "A weekly look at where your money went is the strongest predictor of momentum — a few minutes is enough.",
        },
        {
            "action": "Increase retirement contributions by 1% of gross income",
            "impact": "FHS",
            "priority": 4,
            "reason": "Small annual escalations are the most reliable way to hit age-based wealth targets.",
        },
        {
            "action": "Review your insurance coverage annually",
            "impact": "FHS",
            "priority": 5,
            "reason": "Life events (marriage, kids, a raise) change how much protection you need.",
        },
    ]
    i = 0
    while len(recs) < 3 and i < len(fallbacks):
        recs.append(fallbacks[i])
        i += 1

    if phases:
        recs.append({
            "action": phases[0]["description"],   # immediate first action
            "impact": "FHS",
            "priority": 1,
            "reason": (
                "Your personalised plan: "
                + " → ".join(p["description"] for p in phases)
            ),
            "phases": phases,   # structured list for UI rendering
        })
        recs.sort(key=lambda r: r["priority"])

    return recs[:5]


# ═══════════════════════════════════════════
# 6-MONTH TRAJECTORY PROJECTION
# ═══════════════════════════════════════════

def project_trajectory(inp: IndividualInput, sol: LPSolution, current_fhs: int, months: int = 6) -> list:
    """Project FHS forward `months` months assuming the user follows the LP plan.

    Each month: apply the LP allocation to balances (EF/retirement grow,
    HI/LO debt shrink, floors at 0), free the proportional share of D_min
    the first month a debt category is eliminated, rebuild the input, re-solve
    and re-score. Caps values at 850.

    Infeasible LP ⇒ flat line at the current FHS value (we can't project
    an improvement plan that doesn't exist).
    """
    # Multi-period fast path: trajectory IS the LP solution — no re-solve needed.
    if sol.state_trajectory and sol.status == "Optimal":
        annual_salary = inp.I_gross * 12
        age_tgt = age_target(inp.age, annual_salary)
        result = []
        # Month 0: score against current inp state
        fhs0, _ = compute_fhs(inp, sol, round_output=False)
        result.append(round(float(fhs0), 1))
        for st in sol.state_trajectory:
            proj_inp = replace(
                inp,
                S_liq=st["S_liq"],
                S_ret=st["S_ret"],
                D_hi=st["D_hi"],
                D_lo=st["D_lo"],
                D_min=st["D_min"],
            )
            # Re-use the same multi-period sol for the objective_terms (ef_saturation etc.)
            # but score the projected state directly — no new LP solve.
            proj_fhs, _ = compute_fhs(proj_inp, sol, round_output=False)
            result.append(round(min(850.0, max(300.0, float(proj_fhs))), 1))
        return result

    if sol.status == "Optimal":
        # Unrounded month-0 keeps the whole 7-point series on the same
        # precision basis — avoids a tiny dip at month 1 when the rounded
        # current FHS is slightly above the raw composite.
        fhs0_raw, _ = compute_fhs(inp, sol, round_output=False)
        trajectory = [round(float(fhs0_raw), 1)]
    else:
        trajectory = [round(float(current_fhs), 1)]

    # ── Minimum-improvement floor ───────────────────────────────────────
    # Tight-budget and infeasible profiles would otherwise project a flat
    # line, which isn't actionable or hopeful. Model a baseline effort of
    # 5% of post-essentials cash flow toward savings + 5% toward debt every
    # month — representing small lifestyle redirections the user could plan
    # themselves even when the LP has no feasible plan.
    positive_flow = max(0.0, inp.I_net - inp.E_ess)
    floor_save = 0.05 * positive_flow
    floor_debt = 0.05 * positive_flow

    if sol.status == "Optimal":
        x1 = max(sol.x.get("x1_ef_savings", 0),  floor_save)
        x2 =     sol.x.get("x2_retirement",  0)
        # Floor applies to whichever debt bucket has a balance; HI first.
        if inp.D_hi > 0:
            x3 = max(sol.x.get("x3_hi_debt_paydown", 0), floor_debt)
            x4 =     sol.x.get("x4_lo_debt_paydown", 0)
        elif inp.D_lo > 0:
            x3 = 0.0
            x4 = max(sol.x.get("x4_lo_debt_paydown", 0), floor_debt)
        else:
            x3 = 0.0; x4 = 0.0
    else:
        # Infeasible LP — no plan exists, project the floor effort only.
        x1 = floor_save
        x2 = 0.0
        if inp.D_hi > 0:
            x3 = floor_debt; x4 = 0.0
        elif inp.D_lo > 0:
            x3 = 0.0; x4 = floor_debt
        else:
            x3 = 0.0; x4 = 0.0

    # Apportion D_min across HI and LO proportionally to starting balances,
    # then let each slice scale CONTINUOUSLY with its remaining balance —
    # mimics real credit-card minimums (≈2–3% of balance). This makes
    # graceful-degradation profiles unlock budget room as they pay down debt.
    total_debt = inp.D_hi + inp.D_lo
    hi_dmin_init = (inp.D_min * (inp.D_hi / total_debt)) if total_debt > 0 else 0.0
    lo_dmin_init = inp.D_min - hi_dmin_init
    D_hi_init = inp.D_hi
    D_lo_init = inp.D_lo

    # Mutable state
    S_liq, S_ret = inp.S_liq, inp.S_ret
    D_hi, D_lo = inp.D_hi, inp.D_lo

    for _ in range(months):
        S_liq += x1
        S_ret += x2
        D_hi  = max(0.0, D_hi - x3)
        D_lo  = max(0.0, D_lo - x4)

        hi_dmin = hi_dmin_init * (D_hi / D_hi_init) if D_hi_init > 0 else 0.0
        lo_dmin = lo_dmin_init * (D_lo / D_lo_init) if D_lo_init > 0 else 0.0
        D_min = hi_dmin + lo_dmin

        proj_inp = replace(
            inp,
            S_liq=S_liq, S_ret=S_ret,
            D_hi=D_hi, D_lo=D_lo, D_min=D_min,
        )
        proj_sol = solve_individual_lp(proj_inp)
        if proj_sol.status == "Optimal":
            proj_fhs, _ = compute_fhs(proj_inp, proj_sol, round_output=False)
        else:
            # Still infeasible after this month's effort — fabricate a minimal
            # LPSolution so compute_fhs reflects the state changes (EF growing,
            # HI debt shrinking) rather than pinning to the previous value.
            stub = LPSolution(
                status="Optimal",
                x={"x1_ef_savings": x1, "x2_retirement": x2,
                   "x3_hi_debt_paydown": x3, "x4_lo_debt_paydown": x4,
                   "x5_discretionary": 0.0, "x6_investment": 0.0},
                objective_terms={"debt_shortfall": max(0.0, inp.D_min - (proj_inp.I_net - proj_inp.E_ess))},
            )
            proj_fhs, _ = compute_fhs(proj_inp, stub, round_output=False)
        # Keep one decimal so the chart line slopes even when integer FHS
        # rounds tie — e.g. Stretched moving 397.8 → 398.4 over 6 months.
        trajectory.append(round(min(850.0, max(300.0, float(proj_fhs))), 1))

    return trajectory


def _build_plan_phases(sol: LPSolution, inp: IndividualInput) -> list:
    """Derive human-readable phase descriptions from the multi-period allocation plan.

    A 'phase' is a contiguous run of months where the dominant allocation
    category doesn't change. Returns a list of dicts:
      {months: "1-3", dominant: "HI debt paydown", amount: 816, description: str}
    """
    if not sol.state_trajectory or not isinstance(sol.x, list):
        return []

    phases = []
    prev_dominant = None
    phase_start = 1
    phase_amount = 0
    phase_anchor_alloc = None     # the first month's full allocation for this phase

    LABELS = {
        "x3_hi_debt_paydown": "HI debt paydown",
        "x1_ef_savings":      "Emergency fund",
        "x2_retirement":      "Retirement savings",
        "x6_investment":      "Investment",
        "x4_lo_debt_paydown": "Debt paydown",
        "x5_discretionary":   "Discretionary",
    }
    # Short fragment used when surfacing a secondary allocation alongside dominant.
    SHORT = {
        "x3_hi_debt_paydown": "high-interest debt",
        "x1_ef_savings":      "emergency fund",
        "x2_retirement":      "retirement savings",
        "x6_investment":      "investments",
        "x4_lo_debt_paydown": "other debt",
    }

    def dominant_key(alloc: dict) -> str:
        # Exclude discretionary from dominance — it's a floor, not a choice.
        candidates = {k: v for k, v in alloc.items() if k != "x5_discretionary"}
        return max(candidates, key=candidates.get)

    def secondary_info(alloc: dict, dom_key: str, dom_amount: float):
        """Return (key, amount) for the next-biggest non-discretionary, non-
        dominant allocation when it's >= 30% of the dominant's amount."""
        if dom_amount <= 0:
            return (None, 0)
        candidates = [
            (k, v) for k, v in alloc.items()
            if k not in ("x5_discretionary", dom_key) and v > 0
        ]
        if not candidates:
            return (None, 0)
        k2, v2 = max(candidates, key=lambda kv: kv[1])
        if v2 >= 0.30 * dom_amount:
            return (k2, v2)
        return (None, 0)

    def flush(start, end, dom, amount, anchor_alloc):
        label = LABELS.get(dom, dom)
        month_str = f"{start}" if start == end else f"{start}–{end}"
        sec_key, sec_amount = secondary_info(anchor_alloc or {}, dom, amount)
        sec_tail = ""
        if sec_key and sec_amount > 0:
            sec_tail = f" + ${sec_amount:,.0f}/month to {SHORT.get(sec_key, sec_key)}"

        if dom == "x3_hi_debt_paydown":
            desc = f"Months {month_str}: Put ${amount:,.0f}/month toward high-interest debt{sec_tail}"
        elif dom == "x1_ef_savings":
            desc = f"Months {month_str}: Build emergency fund — ${amount:,.0f}/month{sec_tail}"
        elif dom == "x2_retirement":
            desc = f"Months {month_str}: Redirect ${amount:,.0f}/month to retirement savings{sec_tail}"
        elif dom == "x6_investment":
            desc = f"Months {month_str}: Invest ${amount:,.0f}/month{sec_tail}"
        else:
            desc = f"Months {month_str}: ${amount:,.0f}/month toward {label}{sec_tail}"

        out = {"months": month_str, "dominant": label,
               "amount": round(amount, 0), "description": desc}
        if sec_key and sec_amount > 0:
            out["secondary"]        = LABELS.get(sec_key, sec_key)
            out["secondary_amount"] = round(sec_amount, 0)
        return out

    for t, alloc in enumerate(sol.x):
        month = t + 1
        dom = dominant_key(alloc)
        amount = alloc.get(dom, 0)
        if dom != prev_dominant:
            if prev_dominant is not None:
                phases.append(flush(phase_start, month - 1, prev_dominant, phase_amount, phase_anchor_alloc))
            prev_dominant = dom
            phase_start = month
            phase_amount = amount
            phase_anchor_alloc = alloc
        else:
            pass  # keep phase_amount as the first month's value — most actionable

    if prev_dominant is not None:
        phases.append(flush(phase_start, len(sol.x), prev_dominant, phase_amount, phase_anchor_alloc))

    return phases


def build_milestones_detail(inp: IndividualInput, sol_y: dict) -> list:
    """Render milestones with three-state applicability metadata.

    Returns a list of {key, label, achieved, applicability, applicability_reason}
    so the frontend can render done / not yet / not applicable without
    duplicating any age- or dependent-threshold logic in JS.
    """
    LABELS = {
        "y1_ef_adequate":          "EF adequate",
        "y2_life_insurance":       "Life insurance",
        "y3_disability_insurance": "Disability insurance",
        "y4_retirement_ontrack":   "Retirement on track",
        "y5_hi_debt_eliminated":   "HI debt eliminated",
    }

    out = []
    for key, label in LABELS.items():
        achieved = bool(sol_y.get(key, 0))
        applicability = "applicable"
        reason = None

        if key == "y2_life_insurance" and inp.age < 30 and inp.dependents == 0:
            applicability = "not_applicable"
            reason = ("No dependents and under 30 — life insurance is "
                      "typically not a priority yet. Revisit when you have "
                      "people who depend on your income.")
        elif key == "y3_disability_insurance" and inp.retired:
            applicability = "not_applicable"
            reason = ("Once you're retired your income isn't at risk from "
                      "disability — this milestone no longer applies.")

        if achieved and applicability == "applicable":
            applicability = "done"

        out.append({
            "key": key,
            "label": label,
            "achieved": achieved,
            "applicability": applicability,
            "applicability_reason": reason,
        })
    return out


def _scrub_breakdowns_for_api(response: dict) -> None:
    """In-place: strip trade-secret optimizer internals from a serialized
    score response, and add the public-facing `contribution_pct` field
    where the strip removed the only relative-ranking signal.

    Called by both `engine.score_to_dict` and `api.result_to_dict` so the
    boundary contract is identical regardless of which serializer the
    endpoint uses.

    What gets stripped and why
    --------------------------
    The architectural-constants contract (CLAUDE.md §7 / §11.1) forbids
    surfacing internal LP/MILP weights, objective values, and
    coefficient matrices. The breakdown dicts that `compute_fhs`,
    `compute_fss`, and `compute_frs` produce carry several of these:

      • FHS dim.`weight` — published per-dimension weight (Em fund 0.18,
        Debt health 0.22, …). Exposing them lets a consumer back out
        the entire FHS formula. STRIPPED.

      • FSS dim.`weighted` — the per-component contribution to FSS,
        equal to `pla(deficit) × weight`. Combined with `pla` (kept,
        public-safe) the consumer can divide to recover `weight`.
        STRIPPED. Replaced by `contribution_pct` (normalized 0–100,
        sums to ~100 across dims) which conveys relative ranking
        without revealing absolute weights.
        Phase 5a.2 — same strip applies to the new SB-FSS contributors
        ("AR aging strain", "AP compression strain", "LOC utilization
        strain", "Payroll coverage strain") added by `engine_sb`. They
        share the dim shape (`pla`, `weighted`) so this loop picks them
        up automatically; no per-key special-casing required.
        Phase 5b.2 — same applies to the new FL-FSS contributors
        ("Income volatility", "Tax reserve insufficiency",
        "Fixed-obligation coverage", "Volatility trajectory") from
        `engine_freelancer`. Same dim shape, picked up automatically.

      • FRS dim.`weight` — published recovery weights (debt 0.30,
        savings 0.25, …). STRIPPED on real_snapshot branch (the only
        branch that surfaces them; multiperiod_trajectory and baseline
        branches never include `weight` in dimensions).

      • FRS top-level `weighted_closure` — the weighted sum of
        per-dimension closures. STRIPPED on real_snapshot and
        multiperiod_trajectory branches. Replaced by per-dimension
        `contribution_pct` so the consumer can still see relative
        impact ranking.

    Do NOT extend this strip pattern by adding new keys to the
    breakdowns; either route them through `contribution_pct`
    (relative-ranking only) or pop them here. The
    `_assert_no_optimization_internals()` scrubber at every API
    return path will catch a re-introduced leak — but only at request
    time. Catching it here keeps the score-to-dict contract clean.
    """
    # ── FHS: strip dim.weight (existing pre-§11.1 behavior) ─────────
    fhs_bd = (response.get("breakdowns") or {}).get("fhs") or response.get("fhs_breakdown") or {}
    for dim in fhs_bd.values():
        if isinstance(dim, dict):
            dim.pop("weight", None)

    # ── FSS: add contribution_pct, then strip dim.weighted ──────────
    fss_bd = (response.get("breakdowns") or {}).get("fss") or response.get("fss_breakdown") or {}
    fss_total = 0.0
    for k, dim in fss_bd.items():
        if k.startswith("_") or not isinstance(dim, dict):
            continue
        w = dim.get("weighted")
        if w is not None:
            fss_total += float(w)
    for k, dim in fss_bd.items():
        if k.startswith("_") or not isinstance(dim, dict):
            continue
        w = dim.get("weighted")
        if w is None:
            continue
        if fss_total > 0:
            dim["contribution_pct"] = round(float(w) / fss_total * 100.0, 1)
        else:
            dim["contribution_pct"] = 0.0
        dim.pop("weighted", None)

    # ── FRS: handle each branch by source field ─────────────────────
    frs_bd = (response.get("breakdowns") or {}).get("frs") or response.get("frs_breakdown") or {}
    if isinstance(frs_bd, dict):
        source = frs_bd.get("source")
        dims = frs_bd.get("dimensions") or {}
        if isinstance(dims, dict):
            # Compute |weight × closure| for each dim BEFORE stripping.
            # multiperiod_trajectory dims only carry `closure` (no `weight`)
            # — fall back to internal published weights so contribution_pct
            # is still meaningful on that branch. Internal weight dict is
            # NOT serialized; it's only used as a normalization basis here.
            _MP_TRAJ_WEIGHTS = {
                "debt_reduction": 0.30, "savings_building": 0.25,
                "spending_optimization": 0.20, "income_growth": 0.10,
                "milestone_achievement": 0.15,
            }
            magnitudes = {}
            for dk, dv in dims.items():
                if not isinstance(dv, dict):
                    continue
                closure = float(dv.get("closure", 0) or 0)
                if "weight" in dv:
                    weight = float(dv["weight"])
                else:
                    weight = _MP_TRAJ_WEIGHTS.get(dk, 0.0)
                magnitudes[dk] = abs(weight * closure)
            total_mag = sum(magnitudes.values())
            for dk, dv in dims.items():
                if not isinstance(dv, dict):
                    continue
                if total_mag > 0:
                    dv["contribution_pct"] = round(magnitudes.get(dk, 0.0) / total_mag * 100.0, 1)
                else:
                    dv["contribution_pct"] = 0.0
                dv.pop("weight", None)
        # Strip top-level weighted_closure regardless of branch.
        frs_bd.pop("weighted_closure", None)


def score_to_dict(result: ScoreResult) -> dict:
    """Serialize ScoreResult to a JSON-safe dict for the API response.

    Trade-secret boundary: the breakdown dicts carry internal
    LP/MILP weights and weighted values. `_scrub_breakdowns_for_api`
    strips those and adds a public-facing `contribution_pct` per
    dimension where appropriate. See that function's docstring for the
    full strip taxonomy and rationale. The
    `_assert_no_optimization_internals` scrubber at every endpoint
    return path is the runtime tripwire that catches drift; this
    function is the design-time discipline that keeps the contract
    clean.
    """
    response = {
        "scores": {
            "fhs": result.fhs,
            "fss": result.fss,
            "frs": result.frs,
            "fhs_band": fhs_band(result.fhs),
            "fss_band": fss_band(result.fss),
            "frs_band": frs_band(result.frs),
        },
        "breakdowns": {
            "fhs": result.fhs_breakdown,
            "fss": result.fss_breakdown,
            "frs": result.frs_breakdown,
        },
        "optimal_allocation": result.optimal_allocation,
        "actual_vs_optimal": result.actual_vs_optimal,
        "recommendations": result.recommendations,
        "insights": result.insights,
        "trajectory": result.trajectory,
        "plan": {
            "allocation_plan": result.allocation_plan,
            "state_trajectory": result.state_trajectory,
            "plan_phases": result.plan_phases,
        },
        "meta": {
            "infeasible": result.infeasible,
            "infeasibility_reason": result.infeasibility_reason,
            "solver": "multiperiod" if result.state_trajectory else "single_period",
            "income_shortfall": result.income_shortfall,
        },
    }

    # Trade-secret strip — see _scrub_breakdowns_for_api docstring.
    _scrub_breakdowns_for_api(response)

    return response


# ═══════════════════════════════════════════
# MAIN SCORING PIPELINE
# ═══════════════════════════════════════════

def score_individual(inp: IndividualInput) -> ScoreResult:
    """Full scoring pipeline: LP → FHS + FSS + FRS."""
    result = ScoreResult()

    # Step 1: Solve LP (multi-period by default, fall back to single-period)
    if inp.use_multiperiod:
        sol = solve_individual_lp_multiperiod(inp)
        if sol.status != "Optimal":
            sol = solve_individual_lp(inp)
    else:
        sol = solve_individual_lp(inp)
    result.lp_solution = sol

    if sol.status != "Optimal":
        result.infeasible = True
        result.infeasibility_reason = (
            f"Income cannot cover minimum obligations. "
            f"Disposable = ${inp.I_net - inp.E_ess - inp.D_min:.0f}/mo, "
            f"Min discretionary = ${0.05 * inp.I_gross:.0f}/mo."
        )
        result.fhs = 300
        result.fss = 100
        result.frs = 50
        result.trajectory = [300] * 7
        # Phase 5b.2 — populate Famine context for Freelancer archetype
        # on the LP-infeasibility floor-score path. The full extension
        # function isn't safe to run on a degenerate LP solution; this
        # narrower hook only sets `famine_context` so 5b.4's Famine-state
        # framing has its input contract.
        if getattr(inp, "archetype", "individual_w2") == "freelancer":
            from engine_freelancer import populate_famine_context
            populate_famine_context(inp, result)
        return result

    # Step 2: Compute scores
    result.fhs, result.fhs_breakdown = compute_fhs(inp, sol)
    result.fss, result.fss_breakdown = compute_fss(inp, sol)
    result.frs, result.frs_breakdown = compute_frs(inp, sol)

    # Step 3: Build allocation comparison (always month-0 allocation, regardless of solver shape)
    disposable = inp.I_net - inp.E_ess - inp.D_min
    month0 = _x_month0(sol)
    result.optimal_allocation = {k: round(v, 2) for k, v in month0.items()}

    # ── UI consistency patch: if the recommendation engine will surface an EF
    # floor (x1=0 while S_liq is below the 3-month target), apply that floor
    # to the ALLOCATION TABLE too — otherwise the user sees "$0/mo to emergency
    # fund" in the table while the rec card says "save $55/month". Amount is
    # redirected from discretionary (x5) so the budget stays balanced.
    ef_target_3mo = 3 * inp.E_ess
    if (result.optimal_allocation.get("x1_ef_savings", 0) == 0
            and inp.S_liq < ef_target_3mo):
        suggested_ef = round(max(50.0, 0.05 * max(0.0, disposable)), 2)
        x5_cur = result.optimal_allocation.get("x5_discretionary", 0)
        suggested_ef = min(suggested_ef, x5_cur)   # never go negative on x5
        if suggested_ef > 0:
            result.optimal_allocation["x1_ef_savings"] = suggested_ef
            result.optimal_allocation["x5_discretionary"] = round(x5_cur - suggested_ef, 2)
    result.actual_vs_optimal = {
        "disposable_income": round(disposable, 2),
        "milestones_achieved": sol.y,                                 # legacy key
        "milestones_detail":   build_milestones_detail(inp, sol.y),  # 3-state detail
        "hi_debt_remaining": round(sol.z, 2) if sol.z else 0,
        "discretionary_excess": round(sol.z2, 2) if sol.z2 else 0,
    }

    # Step 4: Plain-language recommendations from the optimal allocation.
    result.recommendations = generate_recommendations(inp, sol)
    # Step 5: Per-dimension insight sentences.
    result.insights = generate_insights(inp, result.fhs_breakdown, result.fss_breakdown)
    # Step 6: 6-month projected FHS trajectory assuming the plan is followed.
    result.trajectory = project_trajectory(inp, sol, result.fhs, months=6)
    # Step 7: Expose multi-period plan data if available
    if sol.state_trajectory:
        result.allocation_plan = sol.x       # list of per-month dicts
        result.state_trajectory = sol.state_trajectory
        result.plan_phases = _build_plan_phases(sol, inp)

    # Step 8: Income-shortfall override — if take-home can't cover essentials
    # + required minimum debt payments, force all allocations to zero and
    # replace the phased plan with a single "close the gap" recommendation.
    # Users cannot allocate money they don't have; the LP's graceful-
    # degradation sliver was producing misleading non-zero allocations here.
    true_disposable = inp.I_net - inp.E_ess - inp.D_min
    if true_disposable < 0:
        shortfall_amount = -true_disposable
        result.income_shortfall = {
            "amount": round(shortfall_amount, 2),
            "I_net": inp.I_net,
            "E_ess": inp.E_ess,
            "D_min": inp.D_min,
            "note": (
                "Your monthly expenses exceed your take-home pay by "
                f"${shortfall_amount:,.0f}. Before any plan can work, "
                "we need to close this gap."
            ),
        }
        # Zero out the allocation table and plan output.
        result.optimal_allocation = {k: 0.0 for k in result.optimal_allocation}
        result.allocation_plan = []
        result.plan_phases = []
        # Replace recommendations with a single top-priority "close the gap" card.
        result.recommendations = [{
            "action": (
                f"Close your ${shortfall_amount:,.0f}/month income shortfall first"
            ),
            "impact": "FSS",
            "priority": 1,
            "reason": (
                "Your monthly expenses exceed your take-home pay by "
                f"${shortfall_amount:,.0f}. Before any plan can work, we need "
                "to close this gap — through reducing essentials, reducing "
                "minimums (consolidation or refinance), or adding income."
            ),
        }]

    # ── Phase 5a.2: Small Business archetype extension ───────────────
    # Single dispatch line. Individual archetype path completes
    # untouched above; SB archetype gets additional FSS contributors
    # (AR aging / AP compression / LOC utilization / payroll coverage)
    # and forward projections layered on top. The extension function
    # is a no-op for non-SB archetypes — defensive guard inside.
    if getattr(inp, "archetype", "individual_w2") == "small_business":
        from engine_sb import extend_score_for_small_business
        extend_score_for_small_business(inp, result)

    # ── Phase 5b.2: Freelancer archetype extension ───────────────────
    # Same dispatch pattern as SB. Adds 4 FSS contributors (income
    # volatility, tax-reserve insufficiency, fixed-obligation coverage,
    # volatility trajectory) plus forward projections (tax-reserve
    # status, smoothed-discretionary-max, buffer-floor-with-volatility,
    # and famine_context if income-shortfall fired).
    if getattr(inp, "archetype", "individual_w2") == "freelancer":
        from engine_freelancer import extend_score_for_freelancer
        extend_score_for_freelancer(inp, result)

    return result


# ═══════════════════════════════════════════
# FULL-PIPELINE SMOKE TEST (run via `python engine.py`)
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import sys, io, time, json

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        except Exception:
            pass

    archetypes = [
        IndividualInput(
            name="Average",
            I_gross=6000, I_net=4500, E_ess=2800, E_house=1400,
            D_min=600, D_hi=5000, D_lo=25000,
            S_liq=4000, S_ret=20000, age=32,
        ),
        IndividualInput(
            name="Debt Destroyer",
            I_gross=7500, I_net=5500, E_ess=2500, E_house=1200,
            D_min=1200, D_hi=18000, D_lo=10000,
            S_liq=3000, S_ret=15000, age=34,
        ),
        IndividualInput(
            name="Excellent",
            I_gross=12000, I_net=8800, E_ess=3200, E_house=1800,
            D_min=400, D_hi=0, D_lo=15000,
            S_liq=30000, S_ret=120000, age=38,
            has_life_insurance=True, has_disability_insurance=True,
        ),
    ]

    print(f"{'Profile':<20} {'FHS':>5} {'FSS':>5} {'FRS':>5}  Phases")
    print("-" * 80)
    for inp in archetypes:
        t0 = time.perf_counter()
        result = score_individual(inp)
        dt = (time.perf_counter() - t0) * 1000
        phases_str = " → ".join(p["months"] + ":" + p["dominant"] for p in result.plan_phases)
        print(f"{inp.name:<20} {result.fhs:>5} {result.fss:>5} {result.frs:>5}  {phases_str}  ({dt:.0f}ms)")
        if result.recommendations:
            print(f"  Top rec: {result.recommendations[0]['action']}")
        print(f"  Trajectory: {result.trajectory}")
        print()
