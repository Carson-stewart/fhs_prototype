"""
Test Archetypes for Financial Health Scoring Engine validation.

Phase 5a.5 closeout: unified across Individual W-2 and Small Business
archetypes. The list `PROFILES` is the single source of truth for
`test_runner.py`; `INDIVIDUAL_PROFILES` and `SB_PROFILES` are
filtered views for archetype-specific tests.

Compliance gate is now "X/X archetype compliance" where X is
`len(PROFILES)` — this is intentional. Archetype expansion is now a
normal pattern, not a major event.
"""
from engine import IndividualInput

INDIVIDUAL_PROFILES = [
    {
        "input": IndividualInput(
            name="Excellent — High earner, debt-free",
            I_gross=15000, I_net=10500, E_ess=4000, E_house=2000,
            D_min=0, D_hi=0, D_lo=0,
            S_liq=50000, S_ret=200000, age=35,
            has_life_insurance=True, has_disability_insurance=True,
            streak_days=180, momentum_slope=0.5,
            previous={"S_liq": 49500, "S_ret": 199000, "D_hi": 0, "D_lo": 0},
        ),
        "expected_fhs": (780, 850),
        "expected_fss": (0, 10),
    },
    {
        "input": IndividualInput(
            name="Strong — Solid earner, small mortgage",
            I_gross=9000, I_net=6500, E_ess=3200, E_house=1600,
            D_min=500, D_hi=0, D_lo=120000,
            S_liq=20000, S_ret=80000, age=38,
            has_life_insurance=True, has_disability_insurance=False,
            streak_days=90, momentum_slope=0.3,
            previous={"S_liq": 18000, "S_ret": 78000, "D_hi": 0, "D_lo": 120000},
        ),
        "expected_fhs": (680, 760),
        "expected_fss": (5, 25),
    },
    {
        "input": IndividualInput(
            name="Average — Median income, some CC debt",
            I_gross=6000, I_net=4500, E_ess=2800, E_house=1400,
            D_min=600, D_hi=5000, D_lo=25000,
            S_liq=4000, S_ret=20000, age=32,
            has_life_insurance=False, has_disability_insurance=False,
            streak_days=30, momentum_slope=0.1,
            previous={"S_liq": 3000, "S_ret": 19500, "D_hi": 5500, "D_lo": 25000},
        ),
        "expected_fhs": (480, 580),
        "expected_fss": (25, 45),
    },
    {
        "input": IndividualInput(
            name="Stretched — High DTI, thin savings",
            I_gross=5500, I_net=4200, E_ess=2600, E_house=1500,
            D_min=1800, D_hi=12000, D_lo=35000,
            S_liq=1500, S_ret=8000, age=40,
            has_life_insurance=False, has_disability_insurance=False,
            streak_days=0, momentum_slope=-0.4,
            previous={"S_liq": 2000, "S_ret": 8000, "D_hi": 13000, "D_lo": 35000,
                      "late_payment_count_90d": 2},
        ),
        "expected_fhs": (370, 460),
        "expected_fss": (45, 70),
    },
    {
        "input": IndividualInput(
            name="Distressed — Collections, zero savings",
            I_gross=3500, I_net=2900, E_ess=2400, E_house=1200,
            D_min=800, D_hi=18000, D_lo=5000,
            S_liq=200, S_ret=0, age=28,
            has_life_insurance=False, has_disability_insurance=False,
            overdraft_count_90d=3, late_payment_count_90d=2,
            streak_days=0, momentum_slope=-0.8,
            previous={"S_liq": 200, "S_ret": 0, "D_hi": 18000, "D_lo": 5000},
        ),
        "expected_fhs": (300, 370),
        "expected_fss": (75, 100),
    },
    {
        "input": IndividualInput(
            name="Young professional — Entry level, student loans",
            I_gross=5000, I_net=3800, E_ess=2200, E_house=1100,
            D_min=400, D_hi=0, D_lo=35000,
            S_liq=3000, S_ret=5000, age=25,
            has_life_insurance=False, has_disability_insurance=False,
            streak_days=45, momentum_slope=0.2,
            previous={"S_liq": 1500, "S_ret": 5000, "D_hi": 0, "D_lo": 35000},
        ),
        "expected_fhs": (440, 540),
        "expected_fss": (20, 45),
    },
    {
        "input": IndividualInput(
            name="High earner, high spender — Lifestyle inflation",
            I_gross=12000, I_net=8500, E_ess=6000, E_house=3000,
            D_min=800, D_hi=8000, D_lo=40000,
            S_liq=5000, S_ret=30000, age=34,
            has_life_insurance=True, has_disability_insurance=False,
            streak_days=10, momentum_slope=-0.1,
            previous={"S_liq": 6000, "S_ret": 30000, "D_hi": 8000, "D_lo": 40000},
        ),
        "expected_fhs": (440, 560),
        "expected_fss": (20, 40),
    },
    {
        "input": IndividualInput(
            name="Debt destroyer — Aggressively paying off CC",
            I_gross=6500, I_net=4800, E_ess=2500, E_house=1200,
            D_min=700, D_hi=30000, D_lo=10000,
            S_liq=2000, S_ret=15000, age=30,
            has_life_insurance=False, has_disability_insurance=False,
            streak_days=120, momentum_slope=0.6,
            previous={"S_liq": 2000, "S_ret": 15000, "D_hi": 33000, "D_lo": 10000},
        ),
        "expected_fhs": (400, 500),
        "expected_fss": (35, 55),
    },
    {
        "input": IndividualInput(
            name="Recently divorced — Income halved",
            I_gross=4500, I_net=3500, E_ess=2800, E_house=1400,
            D_min=600, D_hi=3000, D_lo=15000,
            S_liq=1000, S_ret=40000, age=42,
            has_life_insurance=False, has_disability_insurance=False,
            overdraft_count_90d=1,
            streak_days=5, momentum_slope=-0.5,
            previous={"S_liq": 3000, "S_ret": 40000, "D_hi": 3000, "D_lo": 15000},
        ),
        "expected_fhs": (340, 430),
        "expected_fss": (50, 75),
    },
    {
        "input": IndividualInput(
            name="Near retirement — Behind on retirement target",
            I_gross=8000, I_net=5800, E_ess=3500, E_house=1500,
            D_min=300, D_hi=0, D_lo=50000,
            S_liq=25000, S_ret=150000, age=55,
            has_life_insurance=True, has_disability_insurance=True,
            streak_days=200, momentum_slope=0.1,
            previous={"S_liq": 25000, "S_ret": 145000, "D_hi": 0, "D_lo": 50000},
        ),
        "expected_fhs": (580, 700),
        "expected_fss": (5, 25),
    },
]


# ─── Small Business archetype profiles ────────────────────────────────
# Phase 5a.5 closeout: SB profiles are now folded into `PROFILES`
# alongside Individual W-2. They carry the same `expected_fhs` /
# `expected_fss` keys as the legacy archetypes plus optional
# `expected_state` / `expected_state_not` keys consumed by
# `test_state_vocabulary.py` for SB-specific state-landing assertions.
#
# Each profile sets `archetype="small_business"` so the state
# vocabulary resolver and engine_sb extension dispatch correctly.
SB_PROFILES = [
    {
        # Mother's archetype, the why-we're-building-this-archetype case.
        # Solo LLC, steady monthly revenue, AR aging mostly current,
        # AP manageable, owner draws sustainable, line of credit unused.
        # Should land `stable` once 5a.5 calibration is final.
        "input": IndividualInput(
            name="SB Healthy — Solo LLC, steady revenue",
            archetype="small_business",
            # Personal-side scoring inputs (owner take-home is the "I_net"
            # the engine reasons about; SB-specific fields layer on top
            # in 5a.2).
            I_gross=11000, I_net=8200, E_ess=3500, E_house=1800,
            D_min=400, D_hi=0, D_lo=140000,
            S_liq=45000, S_ret=110000, age=48,
            has_life_insurance=True, has_disability_insurance=True,
            streak_days=120, momentum_slope=0.3,
            previous={"S_liq": 43000, "S_ret": 108000, "D_hi": 0, "D_lo": 141000},
            # Small-business specifics
            business_structure="llc",
            revenue_cadence="monthly",
            ar_aging_buckets={
                "current": 8500, "30_days": 1500,
                "60_days": 0,    "90_plus_days": 0,
            },
            ap_pending={
                "due_within_7d": 800, "due_8_to_30d": 1500, "overdue": 0,
            },
            payroll_periodicity="biweekly",
            payroll_amount_per_cycle=2800,
            owner_draw_amount=2500,
            owner_draw_cadence="monthly",
            business_lines_of_credit=[
                {"limit": 30000, "balance": 0, "apr": 0.085,
                 "name": "Chase Business LOC"},
            ],
            seasonal_revenue=False,
        ),
        "expected_fhs":   (700, 800),
        "expected_fss":   (5, 25),
        "expected_state": "stable",
    },
    {
        # Sole prop with extending AR (60+ bucket non-trivial), AP
        # compressing into the 7-day window, owner draws as-needed,
        # LOC partly drawn, seasonal Jan/Feb dip. Should land
        # `tightening` — the deliberate-move-needed middle state.
        "input": IndividualInput(
            name="SB Tightening — Sole prop, extending AR, LOC drawing",
            archetype="small_business",
            # Personal side is mid-range — this archetype's stress is on
            # the BUSINESS surface (AR/AP/LOC), not personal debt. Many
            # real SB owners are personally debt-free but business-debt
            # loaded; the SB-specific fields below carry that signal.
            I_gross=9200, I_net=6800, E_ess=3500, E_house=1800,
            D_min=350, D_hi=0, D_lo=70000,
            S_liq=8500, S_ret=35000, age=51,
            has_life_insurance=True, has_disability_insurance=False,
            streak_days=15, momentum_slope=-0.1,
            previous={"S_liq": 9500, "S_ret": 35000, "D_hi": 0, "D_lo": 70000},
            business_structure="sole_proprietor",
            revenue_cadence="irregular",
            ar_aging_buckets={
                "current": 5500, "30_days": 6000,
                "60_days": 8500, "90_plus_days": 4000,
            },
            ap_pending={
                "due_within_7d": 3500, "due_8_to_30d": 2800, "overdue": 1200,
            },
            payroll_periodicity="none",
            payroll_amount_per_cycle=0,
            owner_draw_amount=2200,
            owner_draw_cadence="as_needed",
            business_lines_of_credit=[
                {"limit": 30000, "balance": 22000, "apr": 0.115,
                 "name": "BoA Business LOC"},
            ],
            seasonal_revenue=True,
            seasonal_low_months=[1, 2],
        ),
        # FHS lands in the tightening band (550-699) per design.
        # 5a.1: FSS=14 (personal-only). 5a.2: FSS rises into the 25-45
        # range as AR aging + AP compression + LOC utilization
        # contributors come online — see `engine_sb._SB_CONFIG`.
        "expected_fhs":   (550, 670),
        "expected_fss":   (15, 45),
        "expected_state": "tightening",
    },

    # ── Phase 5a.2: mission-critical independent-stress-driver test ──
    # Personal-side numbers look fine (no high-interest debt, decent EF,
    # good income, both insurances). But the BUSINESS surface is loud:
    # AR aging stuck in 60+/90+ buckets, AP compressing into the 7-day
    # window plus overdue carry, LOC at 90% of limit. With the SB-FSS
    # contributors landed in 5a.2, this profile MUST land `tightening`
    # or `capital_event_needed` even though personal-side scoring alone
    # would put it in `stable`. If it stays `stable`, the SB-FSS
    # contributors are structurally insufficient and the work item has
    # failed its strategic goal.
    {
        "input": IndividualInput(
            name="SB Stress Personal Healthy — business loud, personal quiet",
            archetype="small_business",
            # Personal: clean. No HI debt; mortgage only. Decent EF and
            # retirement, both insurances, healthy momentum.
            I_gross=10000, I_net=7500, E_ess=3500, E_house=1800,
            D_min=0, D_hi=0, D_lo=140000,
            S_liq=20000, S_ret=80000, age=50,
            has_life_insurance=True, has_disability_insurance=True,
            streak_days=90, momentum_slope=0.1,
            previous={"S_liq": 21000, "S_ret": 78000, "D_hi": 0, "D_lo": 141000},
            # Business: loud distress signals.
            business_structure="sole_proprietor",
            revenue_cadence="irregular",
            # AR mostly aged into 60+/90+ — over half of receivables
            # are functionally locked up.
            ar_aging_buckets={
                "current":      500,
                "30_days":      3000,
                "60_days":      12000,
                "90_plus_days": 18000,
            },
            # AP compressed: $14k due within 7 days against $20k S_liq,
            # plus overdue carry. Near-term ratio = 0.80 → high strain.
            ap_pending={
                "due_within_7d": 14000, "due_8_to_30d": 4500, "overdue": 2000,
            },
            payroll_periodicity="biweekly",
            payroll_amount_per_cycle=3500,    # 1 employee + self
            owner_draw_amount=3000,
            owner_draw_cadence="monthly",
            # LOC at 90% utilization — well past the 70% SBA distress
            # threshold.
            business_lines_of_credit=[
                {"limit": 40000, "balance": 36000, "apr": 0.115,
                 "name": "Wells Fargo Business LOC"},
            ],
            seasonal_revenue=False,
        ),
        # FHS observed at 676 — in the "Good" band (≥600). Personal
        # numbers genuinely look healthy at this level; the gap from
        # 700 ("Strong") comes from age-50 retirement-target headroom,
        # not from any actual personal stress signal. The mission-
        # critical assertion here is the STATE landing, not the FHS
        # range — see `expected_state_not` below. Range bounded loosely
        # to flag any unexpected drift across calibration cycles.
        "expected_fhs":   (640, 740),
        # FSS observed at 32 — driven entirely by SB contributors since
        # personal-side strain is near zero.
        "expected_fss":   (25, 55),
        # MUST be tightening or capital_event_needed (NOT stable).
        # The state assertion in test_state_vocabulary.py treats this
        # as a "not stable" check rather than an exact-state check, since
        # the boundary depends on calibration. Mission-critical: this is
        # the test that validates business stress drives state
        # independently of personal-side health.
        "expected_state_not": "stable",
    },

    # ── Phase 5a.2: severe SB distress test — must land capital_event_needed ──
    # Business stress is severe across every dimension. Personal numbers
    # are also poor (low S_liq, some debt) so this profile shouldn't be
    # confused with the personal-healthy variant — it's the "everything
    # is failing at once" archetype where capital event is the only path.
    {
        "input": IndividualInput(
            name="SB Capital Event — severe AR rot, LOC maxed, payroll uncovered",
            archetype="small_business",
            I_gross=8000, I_net=5500, E_ess=3500, E_house=1800,
            D_min=600, D_hi=0, D_lo=85000,
            S_liq=4500, S_ret=22000, age=49,
            has_life_insurance=True, has_disability_insurance=False,
            streak_days=0, momentum_slope=-0.4,
            previous={"S_liq": 7000, "S_ret": 23000, "D_hi": 0, "D_lo": 85000},
            business_structure="sole_proprietor",
            revenue_cadence="irregular",
            # Almost all AR is 90+ days — functionally bad debt.
            ar_aging_buckets={
                "current":      0,
                "30_days":      1000,
                "60_days":      4000,
                "90_plus_days": 25000,
            },
            # AP severely overdue; $20k near-term against $4.5k S_liq.
            ap_pending={
                "due_within_7d": 8000, "due_8_to_30d": 3000, "overdue": 12000,
            },
            payroll_periodicity="weekly",
            payroll_amount_per_cycle=1500,    # weekly = ~$6.5k/mo
            owner_draw_amount=3500,           # unsustainable at this revenue
            owner_draw_cadence="as_needed",
            # LOC at 98% of limit.
            business_lines_of_credit=[
                {"limit": 25000, "balance": 24500, "apr": 0.135,
                 "name": "Capital One Business LOC"},
            ],
            seasonal_revenue=False,
        ),
        # FHS observed at 548 — in the "Watch" band (450-599).
        # Multiple weak dimensions (low EF, weak momentum, retirement
        # behind), no HI personal debt so not floor-300. The state
        # landing is the binding criterion.
        "expected_fhs":   (500, 600),
        # FSS expected very high — personal stress (low EF, behavioral)
        # plus full SB stress saturates the score above the 60 boundary.
        "expected_fss":   (60, 100),
        "expected_state": "capital_event_needed",
    },

    # ── Phase 5a.5: 5th SB profile — both surfaces actively stressed ──
    # Sole-prop carrying personal HI-debt AND business-side strain on
    # AR + AP (overdue carrying). Owner draw runs slightly past
    # sustainable. Designed to exercise the case where multiple
    # generators emit primary candidates simultaneously — owner-draw's
    # pla=1.0 wins the tiebreaker, AR + AP get demoted to secondary
    # but stay visible. Validates singular-primary discipline under
    # multi-dim saturation across both personal and business surfaces.
    {
        "input": IndividualInput(
            name="SB Mixed Surfaces — both personal and business pressure",
            archetype="small_business",
            # Personal: carrying HI debt, EF buffer thin but not zero.
            I_gross=8500, I_net=6200, E_ess=3500, E_house=1800,
            D_min=550, D_hi=5000, D_lo=80000,
            S_liq=14000, S_ret=55000, age=49,
            has_life_insurance=True, has_disability_insurance=False,
            streak_days=30, momentum_slope=0.0,
            previous={"S_liq": 13500, "S_ret": 54000,
                      "D_hi": 5500, "D_lo": 80500},
            # Business: AR aged into 60+/90+ buckets; AP compressing
            # with overdue carry; LOC drawn but below SBA distress;
            # owner draw slightly past sustainable.
            business_structure="sole_proprietor",
            revenue_cadence="monthly",
            ar_aging_buckets={
                "current": 4000, "30_days": 3500,
                "60_days": 4500, "90_plus_days": 2000,
            },
            ap_pending={
                "due_within_7d": 4500, "due_8_to_30d": 2000, "overdue": 300,
            },
            payroll_periodicity="biweekly",
            payroll_amount_per_cycle=2400,
            owner_draw_amount=2200,
            owner_draw_cadence="monthly",
            business_lines_of_credit=[
                {"limit": 25000, "balance": 12000, "apr": 0.10,
                 "name": "Chase Business LOC"},
            ],
            seasonal_revenue=False,
        ),
        # FHS expected mid-band — personal HI debt drags but mortgage-only
        # D_lo and decent retirement keep it from collapsing. State should
        # land tightening; calibrated post-observation in 5a.5.
        "expected_fhs":   (480, 640),
        "expected_fss":   (15, 50),
        "expected_state": "tightening",
    },
]


# ─── Freelancer archetype profiles ────────────────────────────────────
# Phase 5b.1: kept SEPARATE from `PROFILES` until 5b.5 reintegration —
# mirrors the Phase 5a.1 pattern for SB_PROFILES. The 15/15 unified
# compliance gate stays at 15/15 through 5b.1–5b.4 and increments at
# 5b.5 close.
#
# Each profile sets `archetype="freelancer"` so the state vocabulary
# resolver routes them correctly. The Freelancer-specific fields
# carry realistic values now; 5b.2's LP/MILP work will consume them.
#
# State landings under 5b.1 thresholds rely on FHS / FSS / FRS only
# (volatility + tax-reserve-driven thresholds land in 5b.2 once those
# signals contribute to the score components).
FREELANCER_PROFILES = [
    {
        # Long-term retainer client + steady supplemental contracts.
        # Tax reserve well-stocked, EF strong, decent retirement.
        # Should land `predictable`.
        "input": IndividualInput(
            name="FL Predictable — Long-term retainers, low volatility",
            archetype="freelancer",
            # Personal-side: solid retirement progress (above the
            # Fidelity-benchmark 1×@30 floor), strong EF buffer, no HI
            # debt. The Predictable archetype is meant to read as "this
            # freelancer has it together" — adequate retirement on plan
            # is part of that picture.
            I_gross=8500, I_net=6500, E_ess=2800, E_house=1500,
            D_min=500, D_hi=0, D_lo=22000,
            S_liq=18000, S_ret=150000, age=40,
            has_life_insurance=True, has_disability_insurance=False,
            streak_days=120, momentum_slope=0.3,
            previous={"S_liq": 17000, "S_ret": 145000,
                      "D_hi": 0, "D_lo": 22500},
            # Freelancer-specific
            business_structure="sole_proprietor",
            income_sources=[
                {"source_type": "1099_contract", "name": "Acme Studio retainer",
                 "monthly_average": 5000, "volatility_coefficient": 0.05,
                 "is_seasonal": False},
                {"source_type": "freelance_direct", "name": "Direct freelance projects",
                 "monthly_average": 3500, "volatility_coefficient": 0.30,
                 "is_seasonal": False},
            ],
            income_volatility_observed=0.15,    # low — retainer dominates
            months_of_income_history=24,
            tax_reserve_balance=8500,           # near full target
            tax_reserve_target_pct=0.30,
            quarterly_tax_due_date="2026-06-15",
            quarterly_tax_estimated_amount=6400,
            fixed_monthly_obligations=3000,
            freelance_account_separation="separate_business_account",
        ),
        "expected_fhs":   (650, 750),
        "expected_fss":   (5, 25),
        "expected_state": "predictable",
    },
    {
        # Project-based contractor. Decent annualized income but
        # uneven monthly arrival. Tax reserve partially built.
        # Should land `lumpy` (fallthrough — neither extreme).
        "input": IndividualInput(
            name="FL Lumpy — Contract-to-contract, irregular timing",
            archetype="freelancer",
            I_gross=6500, I_net=4500, E_ess=2800, E_house=1400,
            D_min=400, D_hi=0, D_lo=15000,
            S_liq=8000, S_ret=22000, age=35,
            has_life_insurance=False, has_disability_insurance=False,
            streak_days=20, momentum_slope=0.0,
            previous={"S_liq": 6500, "S_ret": 21000,
                      "D_hi": 0, "D_lo": 15500},
            business_structure="sole_proprietor",
            income_sources=[
                {"source_type": "1099_contract", "name": "Project-based contracts",
                 "monthly_average": 4500, "volatility_coefficient": 0.45,
                 "is_seasonal": False},
                {"source_type": "gig_platform", "name": "Upwork / freelance platforms",
                 "monthly_average": 2000, "volatility_coefficient": 0.55,
                 "is_seasonal": False},
            ],
            income_volatility_observed=0.40,    # moderate
            months_of_income_history=18,
            # Tax reserve at ~75% of target (1500 vs 1950) — lands as
            # `behind` per the helper's status bands. Captures the
            # "started but not on plan" reality of many lumpy
            # freelancers who reserve when flush, draw down when lean.
            tax_reserve_balance=1500,
            tax_reserve_target_pct=0.30,
            quarterly_tax_due_date="2026-06-15",
            quarterly_tax_estimated_amount=4800,
            fixed_monthly_obligations=2800,
            freelance_account_separation="separate_business_account",
        ),
        # FSS expected low — personal-side strain is mild (no HI debt,
        # decent EF). 5b.2 will introduce volatility-driven FSS
        # contributions that move FSS into the 25-45 range for this
        # profile; for now FSS reflects only the personal-side signals.
        "expected_fhs":   (480, 620),
        "expected_fss":   (5, 30),
        "expected_state": "lumpy",
    },
    {
        # The architecturally important profile.
        # Creative professional with strong year averaged but two
        # consecutive low-income months. Fixed obligations exceed
        # current month's income. Tax reserve depleted. Liquid savings
        # draining. Negative momentum. Anchors what Famine means in
        # the system. Must land `famine` cleanly.
        "input": IndividualInput(
            name="FL Famine — Creative, two slow months, tax reserve drained",
            archetype="freelancer",
            I_gross=2200, I_net=1850,            # current month is light
            E_ess=2400, E_house=1100,            # essentials > income
            D_min=350, D_hi=2500, D_lo=8000,
            S_liq=850, S_ret=12000, age=32,
            has_life_insurance=False, has_disability_insurance=False,
            overdraft_count_90d=1,
            streak_days=0, momentum_slope=-0.6,  # declining
            previous={"S_liq": 2400, "S_ret": 12000,
                      "D_hi": 2500, "D_lo": 8200},
            business_structure="sole_proprietor",
            income_sources=[
                {"source_type": "freelance_direct", "name": "Creative client work",
                 "monthly_average": 4200, "volatility_coefficient": 0.65,
                 "is_seasonal": False},
                {"source_type": "royalty", "name": "Stock & licensing royalties",
                 "monthly_average": 600, "volatility_coefficient": 0.40,
                 "is_seasonal": False},
            ],
            income_volatility_observed=0.65,     # high
            months_of_income_history=12,
            tax_reserve_balance=0,               # depleted — central to the narrative
            tax_reserve_target_pct=0.30,
            quarterly_tax_due_date="2026-06-15",
            quarterly_tax_estimated_amount=3600,
            fixed_monthly_obligations=2400,
            freelance_account_separation="mixed_personal",
        ),
        # Famine should land via FHS<550 OR FSS>60 OR FRS<29.
        "expected_fhs":   (300, 480),
        "expected_fss":   (50, 100),
        "expected_state": "famine",
    },

    # ── Phase 5b.2 — volatility-vs-trajectory distinction validators ──
    # Two profiles with the same average income and same volatility
    # coefficient. The only difference is direction-of-change:
    # Volatile-Declining has negative momentum; Volatile-Stable has zero.
    # Together they validate that FL-FSS-1 (volatility) and FL-FSS-4
    # (trajectory) are independent signals — declining adds strain on
    # top of volatility, even when current-month income looks fine.
    {
        # Healthy current-month income but recent declining trajectory.
        # Reads as: "I had a good month last month but it's the third
        # in a row with lower numbers — the trend is bad even though
        # this month covers essentials."
        "input": IndividualInput(
            name="FL Volatile-Declining — declining trend, this month OK",
            archetype="freelancer",
            I_gross=4500, I_net=3500, E_ess=2200, E_house=1100,
            D_min=300, D_hi=0, D_lo=12000,
            S_liq=8000, S_ret=18000, age=33,
            has_life_insurance=False, has_disability_insurance=False,
            streak_days=10, momentum_slope=-0.5,    # negative trajectory
            previous={"S_liq": 10000, "S_ret": 17500,
                      "D_hi": 0, "D_lo": 12500},
            business_structure="sole_proprietor",
            income_sources=[
                {"source_type": "freelance_direct",
                 "name": "Direct freelance projects",
                 "monthly_average": 5000,
                 "volatility_coefficient": 0.45,
                 "is_seasonal": False},
            ],
            income_volatility_observed=0.45,
            months_of_income_history=6,
            tax_reserve_balance=1500,           # covered (target = 0.30 × 4500 = 1350)
            tax_reserve_target_pct=0.30,
            quarterly_tax_due_date="2026-06-15",
            quarterly_tax_estimated_amount=4000,
            fixed_monthly_obligations=2500,
            freelance_account_separation="separate_business_account",
        ),
        # FSS expected meaningfully elevated by FL-FSS-1 (vol=0.45) +
        # FL-FSS-4 (slope=-0.5). Tax reserve covered (zero strain on FL-FSS-2).
        # Coverage = (8000 + 150 buffer) / 2500 = 3.26 months → zero strain on FL-FSS-3.
        # State should land lumpy at minimum.
        "expected_fhs":   (440, 610),
        "expected_fss":   (10, 40),
        "expected_state": "lumpy",
    },
    {
        # Same average income and volatility coefficient as Volatile-
        # Declining but with zero momentum (alternating up-down months
        # without trend). Validates that trajectory is its own signal:
        # no slope → FL-FSS-4 zero, only FL-FSS-1 contributes.
        "input": IndividualInput(
            name="FL Volatile-Stable — same volatility, no trajectory",
            archetype="freelancer",
            I_gross=4000, I_net=3200, E_ess=2200, E_house=1100,
            D_min=300, D_hi=0, D_lo=12000,
            S_liq=8000, S_ret=18000, age=33,
            has_life_insurance=False, has_disability_insurance=False,
            streak_days=30, momentum_slope=0.0,     # NO trajectory
            previous={"S_liq": 8000, "S_ret": 17800,
                      "D_hi": 0, "D_lo": 12200},
            business_structure="sole_proprietor",
            income_sources=[
                {"source_type": "freelance_direct",
                 "name": "Alternating gig + project work",
                 "monthly_average": 4000,
                 "volatility_coefficient": 0.45,
                 "is_seasonal": False},
            ],
            income_volatility_observed=0.45,        # same as Declining
            months_of_income_history=6,
            tax_reserve_balance=1500,
            tax_reserve_target_pct=0.30,
            quarterly_tax_due_date="2026-06-15",
            quarterly_tax_estimated_amount=3600,
            fixed_monthly_obligations=2500,
            freelance_account_separation="separate_business_account",
        ),
        # FSS expected lower than Volatile-Declining (FL-FSS-4 zero
        # because slope=0). Pure volatility strain only.
        "expected_fhs":   (440, 610),
        "expected_fss":   (5, 30),
        "expected_state": "lumpy",
    },

    # ── Phase 5b.4 — three new synthetic profiles for recommendation
    #     coverage. Each validates a specific FL recommendation path
    #     that wasn't exercised by the 5b.1/5b.2 profile set.
    {
        # Adequate liquid coverage but elevated trajectory pla.
        # Validates FL-REC-4 trajectory-aware action.
        "input": IndividualInput(
            name="FL Trajectory-Aware — solid runway, declining trend",
            archetype="freelancer",
            I_gross=7500, I_net=5800, E_ess=2200, E_house=1100,
            D_min=300, D_hi=0, D_lo=8000,
            S_liq=15000, S_ret=40000, age=37,
            has_life_insurance=True, has_disability_insurance=False,
            streak_days=8, momentum_slope=-0.5,
            previous={"S_liq": 16000, "S_ret": 39000,
                      "D_hi": 0, "D_lo": 8500},
            business_structure="sole_proprietor",
            income_sources=[
                {"source_type": "1099_contract",
                 "name": "Studio retainer",
                 "monthly_average": 5500,
                 "volatility_coefficient": 0.30, "is_seasonal": False},
                {"source_type": "freelance_direct",
                 "name": "Direct project work",
                 "monthly_average": 2000,
                 "volatility_coefficient": 0.50, "is_seasonal": False},
            ],
            income_volatility_observed=0.35,
            months_of_income_history=10,
            tax_reserve_balance=2500,
            tax_reserve_target_pct=0.30,
            quarterly_tax_due_date="2026-06-15",
            quarterly_tax_estimated_amount=5400,
            fixed_monthly_obligations=2200,
            freelance_account_separation="separate_business_account",
        ),
        # Coverage = 15000/2200 = 6.8 months → ample.
        # FL-FSS-4 pla = 0.50 → trajectory rec fires (secondary).
        # No primary candidate — secondaries-only is intentional.
        "expected_fhs":   (520, 680),
        "expected_fss":   (10, 35),
        "expected_state": "lumpy",
    },
    {
        # freelance_account_separation = "unknown" drives low-confidence
        # baseline across all FL recs. Validates confidence-driven
        # hedging in FL-REC-2 / FL-REC-4 + the data-completion hook
        # for account-separation disclosure.
        "input": IndividualInput(
            name="FL Low-Confidence Detection — unknown separation",
            archetype="freelancer",
            I_gross=4500, I_net=3700, E_ess=2400, E_house=1200,
            D_min=300, D_hi=0, D_lo=8000,
            S_liq=6000, S_ret=15000, age=30,
            has_life_insurance=False, has_disability_insurance=False,
            streak_days=15, momentum_slope=-0.2,
            previous={"S_liq": 6500, "S_ret": 14500,
                      "D_hi": 0, "D_lo": 8200},
            business_structure="sole_proprietor",
            income_sources=[
                {"source_type": "other",
                 "name": "Mixed deposits (heuristic detection)",
                 "monthly_average": 4500,
                 "volatility_coefficient": 0.50, "is_seasonal": False},
            ],
            income_volatility_observed=0.50,
            months_of_income_history=4,
            tax_reserve_balance=1000,        # behind: target 1350
            tax_reserve_target_pct=0.30,
            quarterly_tax_due_date="2026-06-15",
            quarterly_tax_estimated_amount=3600,
            fixed_monthly_obligations=2400,
            freelance_account_separation="unknown",
        ),
        # Coverage = 6000/2400 = 2.5 months → moderate.
        # Tax reserve behind. Volatility 0.50 → buffer rec fires.
        # All FL recs use low-confidence hedging.
        # Data-completion: account_separation=unknown fires.
        "expected_fhs":   (520, 640),
        "expected_fss":   (15, 50),
        "expected_state": "lumpy",
    },
    {
        # Tax reserve uncovered AND quarterly due ≤14 days. Validates
        # the imminent-urgency tier of FL-REC-1.
        # NOTE: due_date set to 2026-05-22 lands as imminent on
        # 2026-05-08 (the brief's working date). If run far in the
        # future, the tier shifts; tests using this profile inject
        # `today=` into calculate_tax_reserve_status to keep
        # determinism.
        "input": IndividualInput(
            name="FL Quarterly-Due-Soon — tax reserve uncovered, due in 14d",
            archetype="freelancer",
            I_gross=6000, I_net=4800, E_ess=2200, E_house=1100,
            D_min=400, D_hi=2000, D_lo=15000,
            S_liq=8000, S_ret=20000, age=34,
            has_life_insurance=False, has_disability_insurance=False,
            streak_days=20, momentum_slope=0.1,
            previous={"S_liq": 7500, "S_ret": 19500,
                      "D_hi": 2200, "D_lo": 15500},
            business_structure="sole_proprietor",
            income_sources=[
                {"source_type": "1099_contract",
                 "name": "Steady contracts",
                 "monthly_average": 6000,
                 "volatility_coefficient": 0.25, "is_seasonal": False},
            ],
            income_volatility_observed=0.25,
            months_of_income_history=8,
            tax_reserve_balance=400,         # uncovered: target 1800
            tax_reserve_target_pct=0.30,
            quarterly_tax_due_date="2026-05-22",  # 14 days from 2026-05-08
            quarterly_tax_estimated_amount=3500,
            fixed_monthly_obligations=2200,
            freelance_account_separation="separate_business_account",
        ),
        # Coverage = 8000/2200 = 3.6 months → ample.
        # Tax reserve uncovered + imminent due date → primary FL-REC-1.
        "expected_fhs":   (440, 620),
        "expected_fss":   (10, 50),
        "expected_state": "lumpy",
    },
]


# ─── Unified PROFILES list ────────────────────────────────────────────
# Phase 5a.5 introduced this unified surface. Phase 5b.5 closes by
# folding FREELANCER_PROFILES in — the 23/23 unified compliance gate
# is the moment Freelancer becomes first-class alongside Individual
# W-2 and Small Business.
#
# `test_runner.py` iterates this list; `INDIVIDUAL_PROFILES`,
# `SB_PROFILES`, and `FREELANCER_PROFILES` remain available for
# archetype-filtered tests.
#
# Compliance gate: 23/23 (10 Individual + 5 SB + 8 Freelancer).
# Future archetype additions increment the count without ceremony.
PROFILES = INDIVIDUAL_PROFILES + SB_PROFILES + FREELANCER_PROFILES
