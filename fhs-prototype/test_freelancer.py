"""Tests for Phase 5b.1 — Freelancer schema + state vocab + tax-reserve helper.

Pure tests, no API client. Mirrors the test_state_vocabulary /
test_recommendations convention.

Run with:
    python test_freelancer.py
"""
import os, sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import IndividualInput, score_individual
from engine_freelancer import (
    calculate_tax_reserve_status, _FREELANCER_CONFIG,
)
from state_vocabulary import state_for, ARCHETYPE_STATES
from profiles import FREELANCER_PROFILES


def assert_eq(label, actual, expected):
    if actual != expected:
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")
        return False
    print(f"  ok    {label}")
    return True


def assert_truthy(label, value):
    if value:
        print(f"  ok    {label}")
        return True
    print(f"  FAIL  {label}: got {value!r}")
    return False


def run():
    pp = ff = 0

    # ── Schema sanity: new fields default cleanly ───────────────────
    print("Schema sanity:")
    base = IndividualInput()
    if assert_eq("default income_sources is empty list",
                 base.income_sources, []): pp += 1
    else: ff += 1
    if assert_eq("default income_volatility_observed is None",
                 base.income_volatility_observed, None): pp += 1
    else: ff += 1
    if assert_eq("default months_of_income_history is 0",
                 base.months_of_income_history, 0): pp += 1
    else: ff += 1
    if assert_eq("default tax_reserve_balance is 0",
                 base.tax_reserve_balance, 0): pp += 1
    else: ff += 1
    if assert_eq("default tax_reserve_target_pct is 0.30",
                 base.tax_reserve_target_pct, 0.30): pp += 1
    else: ff += 1
    if assert_eq("default fixed_monthly_obligations is 0",
                 base.fixed_monthly_obligations, 0): pp += 1
    else: ff += 1
    if assert_eq("default freelance_account_separation is 'unknown'",
                 base.freelance_account_separation, "unknown"): pp += 1
    else: ff += 1

    # ── Tax-reserve helper: covered status ──────────────────────────
    print("\nTax-reserve helper — covered status:")
    inp = IndividualInput(
        I_gross=8000,
        tax_reserve_balance=2400,        # exactly target = 0.30 × 8000
        tax_reserve_target_pct=0.30,
    )
    r = calculate_tax_reserve_status(inp)
    if assert_eq("status=covered when balance == target",
                 r["status"], "covered"): pp += 1
    else: ff += 1
    if assert_eq("target_balance computed from pct × income",
                 r["target_balance"], 2400.0): pp += 1
    else: ff += 1
    if assert_eq("shortfall = 0 when covered",
                 r["shortfall"], 0.0): pp += 1
    else: ff += 1
    if assert_eq("recent_income_used reflects I_gross",
                 r["recent_income_used"], 8000.0): pp += 1
    else: ff += 1

    # ── Tax-reserve helper: behind status ───────────────────────────
    print("\nTax-reserve helper — behind status:")
    inp = IndividualInput(
        I_gross=8000,
        tax_reserve_balance=1500,        # 0.625 × target = behind
        tax_reserve_target_pct=0.30,
    )
    r = calculate_tax_reserve_status(inp)
    if assert_eq("status=behind when 0.5×target <= balance < target",
                 r["status"], "behind"): pp += 1
    else: ff += 1
    if assert_eq("shortfall = 900 (target 2400 - current 1500)",
                 r["shortfall"], 900.0): pp += 1
    else: ff += 1

    # ── Tax-reserve helper: uncovered status ────────────────────────
    print("\nTax-reserve helper — uncovered status:")
    inp = IndividualInput(
        I_gross=8000,
        tax_reserve_balance=500,         # 0.21 × target = uncovered
        tax_reserve_target_pct=0.30,
    )
    r = calculate_tax_reserve_status(inp)
    if assert_eq("status=uncovered when balance < 0.5×target",
                 r["status"], "uncovered"): pp += 1
    else: ff += 1
    if assert_eq("shortfall = 1900",
                 r["shortfall"], 1900.0): pp += 1
    else: ff += 1

    # Boundary: zero balance is uncovered (Famine archetype case).
    inp = IndividualInput(I_gross=4000, tax_reserve_balance=0,
                          tax_reserve_target_pct=0.30)
    r = calculate_tax_reserve_status(inp)
    if assert_eq("zero balance with positive target = uncovered",
                 r["status"], "uncovered"): pp += 1
    else: ff += 1

    # ── Tax-reserve helper: vacuous-covered when no income ─────────
    print("\nTax-reserve helper — vacuous covered (no income):")
    inp = IndividualInput(I_gross=0, tax_reserve_balance=0)
    r = calculate_tax_reserve_status(inp)
    if assert_eq("zero income → vacuously covered (no obligation)",
                 r["status"], "covered"): pp += 1
    else: ff += 1
    if assert_eq("zero target when no income",
                 r["target_balance"], 0.0): pp += 1
    else: ff += 1

    # ── Tax-reserve helper: explicit recent_income override ────────
    print("\nTax-reserve helper — recent_income override (rolling avg):")
    inp = IndividualInput(I_gross=2000,         # current month is low
                          tax_reserve_balance=1800,
                          tax_reserve_target_pct=0.30)
    # Caller passes 6000 as the rolling 3-mo average.
    r = calculate_tax_reserve_status(inp, recent_income=6000)
    if assert_eq("target uses recent_income override (1800)",
                 r["target_balance"], 1800.0): pp += 1
    else: ff += 1
    if assert_eq("status=covered against rolling target",
                 r["status"], "covered"): pp += 1
    else: ff += 1

    # ── Tax-reserve helper: quarterly due-date arithmetic ──────────
    print("\nTax-reserve helper — quarterly due-date arithmetic:")
    inp = IndividualInput(
        I_gross=5000, tax_reserve_balance=1500,
        quarterly_tax_due_date="2026-06-15",
        quarterly_tax_estimated_amount=3200,
    )
    r = calculate_tax_reserve_status(inp, today=date(2026, 5, 1))
    if assert_eq("days-until-due (May 1 → June 15) = 45",
                 r["next_quarterly_due_in_days"], 45): pp += 1
    else: ff += 1
    if assert_eq("next_quarterly_amount surfaced",
                 r["next_quarterly_amount"], 3200.0): pp += 1
    else: ff += 1

    # Past-due → negative days
    r = calculate_tax_reserve_status(inp, today=date(2026, 7, 1))
    if assert_truthy("past-due returns negative days",
                     r["next_quarterly_due_in_days"] < 0): pp += 1
    else: ff += 1

    # Missing date → None
    inp_no_date = IndividualInput(I_gross=5000, tax_reserve_balance=1500)
    r = calculate_tax_reserve_status(inp_no_date, today=date(2026, 5, 1))
    if assert_eq("missing due date → None",
                 r["next_quarterly_due_in_days"], None): pp += 1
    else: ff += 1

    # Invalid date string → None (defensive)
    inp_bad = IndividualInput(
        I_gross=5000, tax_reserve_balance=1500,
        quarterly_tax_due_date="not-a-date",
    )
    r = calculate_tax_reserve_status(inp_bad, today=date(2026, 5, 1))
    if assert_eq("invalid date string → None (defensive)",
                 r["next_quarterly_due_in_days"], None): pp += 1
    else: ff += 1

    # ── Output shape contract — every documented key present ───────
    print("\nTax-reserve helper — output-shape contract:")
    inp = IndividualInput(I_gross=4000, tax_reserve_balance=600)
    r = calculate_tax_reserve_status(inp)
    expected_keys = {
        "status", "current_balance", "target_balance", "shortfall",
        "next_quarterly_due_in_days", "next_quarterly_amount",
        "target_pct_used", "recent_income_used",
    }
    if assert_eq("output dict carries the 8 contracted keys",
                 set(r.keys()), expected_keys): pp += 1
    else: ff += 1

    # ── State vocabulary: Freelancer entry fully populated ─────────
    print("\nState vocabulary — Freelancer entry:")
    fl = ARCHETYPE_STATES.get("freelancer") or {}
    states = {s["key"] for s in (fl.get("states") or [])}
    if assert_eq("all three Freelancer states registered",
                 states, {"famine", "predictable", "lumpy"}): pp += 1
    else: ff += 1
    # No state description should still say "stub" or "TBD"
    has_stub = any(("stub" in (s.get("description") or "").lower()
                    or "tbd" in (s.get("description") or "").lower())
                   for s in fl["states"])
    if assert_eq("no state description still marked stub/TBD",
                 has_stub, False): pp += 1
    else: ff += 1
    # Famine description must NOT use crisis language
    famine = next(s for s in fl["states"] if s["key"] == "famine")
    fd = famine["description"].lower()
    bad = ("crisis", "warning", "critical", "danger", "failing", "alarming")
    has_bad = any(w in fd for w in bad)
    if assert_eq("Famine description avoids crisis language",
                 has_bad, False): pp += 1
    else: ff += 1
    print(f"        Famine description: {famine['description']!r}")

    # ── State landings: programmatic resolver checks ───────────────
    print("\nFreelancer state-resolver landings:")
    s = state_for("freelancer", 720, 25, 70)
    if assert_eq("(720, 25, 70) → predictable",
                 s["key"], "predictable"): pp += 1
    else: ff += 1
    s = state_for("freelancer", 600, 40, 50)
    if assert_eq("(600, 40, 50) → lumpy (fallthrough)",
                 s["key"], "lumpy"): pp += 1
    else: ff += 1
    s = state_for("freelancer", 480, 80, 25)
    if assert_eq("(480, 80, 25) → famine (any_of)",
                 s["key"], "famine"): pp += 1
    else: ff += 1

    # ── FREELANCER_PROFILES live state-landing check ───────────────
    print("\nFREELANCER_PROFILES live state-landing:")
    for p in FREELANCER_PROFILES:
        inp = p["input"]
        r = score_individual(inp)
        fhs_ok = p["expected_fhs"][0] <= r.fhs <= p["expected_fhs"][1]
        fss_ok = p["expected_fss"][0] <= r.fss <= p["expected_fss"][1]
        st = state_for("freelancer", r.fhs, r.fss, r.frs)
        state_ok = st["key"] == p["expected_state"]
        line = (f"  {inp.name}: FHS={r.fhs} FSS={r.fss} FRS={r.frs} "
                f"state={st['key']!r}")
        if fhs_ok and fss_ok and state_ok:
            print(f"  ok    {line}")
            pp += 1
        else:
            print(f"  FAIL  {line}")
            print(f"        expected_fhs={p['expected_fhs']}, fhs_ok={fhs_ok}")
            print(f"        expected_fss={p['expected_fss']}, fss_ok={fss_ok}")
            print(f"        expected_state={p['expected_state']!r}, state_ok={state_ok}")
            ff += 1

    # ── Tax-reserve helper on the live FREELANCER_PROFILES ─────────
    print("\nTax-reserve helper on FREELANCER_PROFILES:")
    expected_status = {
        "FL Predictable — Long-term retainers, low volatility":   "covered",
        "FL Lumpy — Contract-to-contract, irregular timing":      "behind",
        "FL Famine — Creative, two slow months, tax reserve drained": "uncovered",
        # Phase 5b.2 volatility-vs-trajectory profiles — both have
        # tax_reserve_balance=1500 against ~$1350/$1200 targets → covered.
        "FL Volatile-Declining — declining trend, this month OK": "covered",
        "FL Volatile-Stable — same volatility, no trajectory":    "covered",
        # Phase 5b.4 profiles
        "FL Trajectory-Aware — solid runway, declining trend":    "covered",
        "FL Low-Confidence Detection — unknown separation":       "behind",
        "FL Quarterly-Due-Soon — tax reserve uncovered, due in 14d": "uncovered",
    }
    for p in FREELANCER_PROFILES:
        inp = p["input"]
        r = calculate_tax_reserve_status(inp, today=date(2026, 5, 1))
        exp = expected_status[inp.name]
        line = (f"  {inp.name[:60]}: status={r['status']!r}, "
                f"target=${r['target_balance']}, shortfall=${r['shortfall']}")
        if r["status"] == exp:
            print(f"  ok    {line}")
            pp += 1
        else:
            print(f"  FAIL  {line}  expected={exp!r}")
            ff += 1

    # ── Phase 5b.2 — volatility-vs-trajectory distinction ─────────
    print("\nPhase 5b.2 — volatility-vs-trajectory distinction:")
    declining = next(p for p in FREELANCER_PROFILES
                     if "Volatile-Declining" in p["input"].name)
    stable    = next(p for p in FREELANCER_PROFILES
                     if "Volatile-Stable" in p["input"].name)
    r_decl = score_individual(declining["input"])
    r_stab = score_individual(stable["input"])
    # FSS-4 (Volatility trajectory) should fire on declining, NOT on stable.
    decl_traj = (r_decl.fss_breakdown.get("Volatility trajectory") or {}).get("pla", 0)
    stab_traj = (r_stab.fss_breakdown.get("Volatility trajectory") or {}).get("pla", 0)
    if assert_truthy("Declining: FL-FSS-4 trajectory pla > 0", decl_traj > 0): pp += 1
    else: ff += 1
    if assert_eq("Stable: FL-FSS-4 trajectory pla == 0", stab_traj, 0): pp += 1
    else: ff += 1
    # FSS-1 (Income volatility) should fire on BOTH at the same level
    # (same volatility coefficient).
    decl_vol = (r_decl.fss_breakdown.get("Income volatility") or {}).get("pla", 0)
    stab_vol = (r_stab.fss_breakdown.get("Income volatility") or {}).get("pla", 0)
    if assert_eq("Declining and Stable: FL-FSS-1 volatility pla equal",
                 decl_vol, stab_vol): pp += 1
    else: ff += 1
    # Net effect: Declining FSS > Stable FSS (trajectory adds strain)
    if assert_truthy(f"Declining FSS ({r_decl.fss}) > Stable FSS ({r_stab.fss})",
                     r_decl.fss > r_stab.fss): pp += 1
    else: ff += 1

    # ── Famine context populated on the Famine profile ────────────
    print("\nFamine context — populated on Famine profile:")
    famine = next(p for p in FREELANCER_PROFILES
                  if "Famine" in p["input"].name)
    r_fam = score_individual(famine["input"])
    fl_ins = (r_fam.insights or {}).get("freelancer", {})
    fc = fl_ins.get("famine_context")
    if assert_truthy("famine_context present", fc is not None): pp += 1
    else: ff += 1
    if fc:
        expected_keys = {
            "uncovered_obligations", "fixed_obligations_total",
            "minimum_protected", "tax_reserve_at_risk",
            "estimated_runway_months",
        }
        if assert_eq("famine_context carries 5 contracted keys",
                     set(fc.keys()), expected_keys): pp += 1
        else: ff += 1
        if assert_truthy("uncovered_obligations > 0",
                         fc["uncovered_obligations"] > 0): pp += 1
        else: ff += 1

    # ── Forward projections present on Lumpy profile ──────────────
    print("\nForward projections on Lumpy profile:")
    lumpy = next(p for p in FREELANCER_PROFILES
                 if p["input"].name.startswith("FL Lumpy"))
    r_lump = score_individual(lumpy["input"])
    fl_ins = (r_lump.insights or {}).get("freelancer", {})
    for key in ("tax_reserve_status", "smoothed_discretionary",
                "buffer_floor"):
        if assert_truthy(f"insights.freelancer.{key} present",
                         key in fl_ins): pp += 1
        else: ff += 1

    # Smoothing should be active for Lumpy (volatility=0.40 > 0.30 threshold)
    sm = fl_ins.get("smoothed_discretionary", {})
    if assert_eq("smoothing_active=True for Lumpy (vol=0.40)",
                 sm.get("smoothing_active"), True): pp += 1
    else: ff += 1

    # ── Predictable: smoothing inactive (vol=0.15 < 0.30) ─────────
    pred = next(p for p in FREELANCER_PROFILES
                if "Predictable" in p["input"].name)
    r_pred = score_individual(pred["input"])
    sm_pred = (r_pred.insights or {}).get("freelancer", {}) \
                                     .get("smoothed_discretionary", {})
    if assert_eq("smoothing_active=False for Predictable (vol=0.15)",
                 sm_pred.get("smoothing_active"), False): pp += 1
    else: ff += 1

    # ── Buffer floor scales with volatility ───────────────────────
    bf_pred = (r_pred.insights or {}).get("freelancer", {}) \
                                     .get("buffer_floor", {})
    bf_decl = (r_decl.insights or {}).get("freelancer", {}) \
                                     .get("buffer_floor", {})
    # Declining vol=0.45, Predictable vol=0.15 → Declining required
    # buffer months should be larger.
    if assert_truthy(
        f"buffer floor scales with vol (decl={bf_decl.get('required_buffer_months')} "
        f"> pred={bf_pred.get('required_buffer_months')})",
        (bf_decl.get("required_buffer_months", 0)
         > bf_pred.get("required_buffer_months", 0))
    ): pp += 1
    else: ff += 1

    # ── Phase 5b.4 — FL recommendation generation ─────────────────
    print("\nPhase 5b.4 — FL recommendation generation:")
    from recommendations import (
        generate_freelancer_recommendations,
        select_primary_freelancer_rec,
        _confidence_baseline_from_separation,
    )

    # Confidence baseline mapping from separation
    class _Stub:
        pass
    s = _Stub(); s.freelance_account_separation = "separate_business_account"
    if assert_eq("separate_business_account → high confidence",
                 _confidence_baseline_from_separation(s), "high"): pp += 1
    else: ff += 1
    s.freelance_account_separation = "mixed_personal"
    if assert_eq("mixed_personal → medium confidence",
                 _confidence_baseline_from_separation(s), "medium"): pp += 1
    else: ff += 1
    s.freelance_account_separation = "unknown"
    if assert_eq("unknown → low confidence",
                 _confidence_baseline_from_separation(s), "low"): pp += 1
    else: ff += 1

    # ── Famine profile produces 4 Famine recs (1 primary + 3 secondary) ─
    print("\nFamine profile — recommendation set:")
    famine = next(p for p in FREELANCER_PROFILES
                  if "Famine" in p["input"].name)
    r_fam = score_individual(famine["input"])
    fl_recs = [x for x in (r_fam.recommendations or [])
               if isinstance(x, dict) and "type" in x]
    famine_recs = [x for x in fl_recs
                   if (x.get("context") or {}).get("trigger") == "famine"]
    if assert_eq("Famine: 4 famine-trigger recs",
                 len(famine_recs), 4): pp += 1
    else: ff += 1
    primaries = [x for x in famine_recs if x.get("priority") == "primary"]
    if assert_eq("Famine: exactly 1 primary",
                 len(primaries), 1): pp += 1
    else: ff += 1
    # tax_reserve_at_risk=False → focus_essentials branch
    primary_branch = (primaries[0].get("context") or {}).get("famine_branch")
    if assert_eq("Famine (tax_reserve_at_risk=False): focus_essentials branch",
                 primary_branch, "focus_essentials"): pp += 1
    else: ff += 1

    # ── Trajectory-Aware profile fires FL-REC-4 (secondary) ───────
    print("\nFL Trajectory-Aware — trajectory rec fires:")
    traj = next(p for p in FREELANCER_PROFILES
                if "Trajectory-Aware" in p["input"].name)
    r_traj = score_individual(traj["input"])
    fl_recs = [x for x in (r_traj.recommendations or [])
               if isinstance(x, dict) and "type" in x]
    traj_recs = [x for x in fl_recs
                 if (x.get("context") or {}).get("trigger") == "trajectory_decline"]
    if assert_eq("Trajectory-Aware: 1 trajectory_decline rec",
                 len(traj_recs), 1): pp += 1
    else: ff += 1
    if assert_eq("Trajectory-Aware: trajectory rec is secondary",
                 traj_recs[0]["priority"], "secondary"): pp += 1
    else: ff += 1

    # ── Low-Confidence profile produces hedged copy ───────────────
    print("\nFL Low-Confidence Detection — hedging:")
    lowconf = next(p for p in FREELANCER_PROFILES
                   if "Low-Confidence Detection" in p["input"].name)
    r_lc = score_individual(lowconf["input"])
    fl_recs = [x for x in (r_lc.recommendations or [])
               if isinstance(x, dict) and "type" in x]
    # All non-data_completion FL recs should carry confidence="low"
    action_recs = [x for x in fl_recs if x.get("type") == "action"]
    all_low = all(x.get("confidence") == "low" for x in action_recs)
    if assert_eq("Low-Confidence: all action recs have confidence=low",
                 all_low, True): pp += 1
    else: ff += 1
    # Volatility-buffer rec should appear with hedged body
    vbuf = [x for x in fl_recs
            if (x.get("context") or {}).get("trigger", "").startswith("volatility_buffer")]
    if vbuf:
        body = vbuf[0]["body"]
        # Hedged variant doesn't reference specific dollar surplus
        # (the direct variant does); the hedge softens with "looks"
        is_hedged = ("looks" in body.lower()
                     or "any thinner months" in body.lower()
                     or "stronger months" in body.lower())
        if assert_eq("Low-Confidence: volatility-buffer body is hedged",
                     is_hedged, True): pp += 1
        else: ff += 1
    # Account-separation data-completion rec should fire
    dc_sep = [x for x in fl_recs
              if x.get("type") == "data_completion"
              and (x.get("context") or {}).get("field") == "freelance_account_separation"]
    if assert_eq("Low-Confidence: account_separation data_completion fires",
                 len(dc_sep), 1): pp += 1
    else: ff += 1

    # ── Quarterly-Due-Soon profile — imminent tier primary ─────────
    print("\nFL Quarterly-Due-Soon — imminent-tier primary:")
    # Use the tax-reserve helper directly with injected today=2026-05-08
    # so the test is deterministic regardless of when it runs.
    qsoon = next(p for p in FREELANCER_PROFILES
                 if "Quarterly-Due-Soon" in p["input"].name)
    tax_status = calculate_tax_reserve_status(
        qsoon["input"], today=date(2026, 5, 8),
    )
    if assert_eq("Quarterly-Due-Soon tax status uncovered",
                 tax_status["status"], "uncovered"): pp += 1
    else: ff += 1
    if assert_eq("Quarterly-Due-Soon days_until_due ≤14",
                 tax_status["next_quarterly_due_in_days"] <= 14, True):
        pp += 1
    else: ff += 1
    # Drive the rec generator with this status by manually constructing
    # the result.insights state. (The live engine call uses today=now,
    # which may not match 2026-05-08; we want determinism here.)
    from recommendations import _tax_reserve_action
    rec = _tax_reserve_action(tax_status, confidence="high")
    if rec is not None and assert_eq(
        "Quarterly-Due-Soon: tax-reserve rec is primary",
        rec["priority"], "primary"): pp += 1
    else: ff += 1
    if rec is not None and assert_eq(
        "Quarterly-Due-Soon: trigger=tax_reserve_uncovered_imminent",
        (rec.get("context") or {}).get("trigger"),
        "tax_reserve_uncovered_imminent"): pp += 1
    else: ff += 1

    # ── Singular-primary discipline across all FL profiles ─────────
    print("\nSingular-primary discipline across all FL profiles:")
    for p in FREELANCER_PROFILES:
        r = score_individual(p["input"])
        fl_recs = [x for x in (r.recommendations or [])
                   if isinstance(x, dict) and "type" in x]
        primaries = [x for x in fl_recs if x.get("priority") == "primary"]
        if len(primaries) <= 1:
            print(f"  ok    {p['input'].name[:60]}: "
                  f"primary count = {len(primaries)}")
            pp += 1
        else:
            print(f"  FAIL  {p['input'].name[:60]}: "
                  f"primary count = {len(primaries)}")
            ff += 1

    # ── Brand voice sweep across all FL recommendations ────────────
    print("\nBrand voice sweep across all FL recommendation strings:")
    from recommendations import audit_brand_voice
    swept = 0
    for p in FREELANCER_PROFILES:
        r = score_individual(p["input"])
        for rec in (r.recommendations or []):
            if isinstance(rec, dict) and rec.get("type"):
                try:
                    audit_brand_voice(rec)
                    swept += 1
                except AssertionError as e:
                    print(f"  FAIL  brand voice in {p['input'].name}: {e}")
                    ff += 1
    print(f"  ok    {swept} FL recs swept, all pass brand voice audit")
    pp += 1

    # ── select_primary_freelancer_rec resolution rule ──────────────
    print("\nselect_primary_freelancer_rec — hierarchical resolution:")
    # Synthetic candidate list with two primaries — famine should win.
    candidates = [
        {"priority": "primary", "context": {"trigger": "tax_reserve_uncovered_far"}},
        {"priority": "primary", "context": {"trigger": "famine"}},
        {"priority": "secondary", "context": {"trigger": "coverage_moderate"}},
    ]
    out = select_primary_freelancer_rec(candidates)
    primary_triggers = [(x.get("context") or {}).get("trigger")
                        for x in out if x.get("priority") == "primary"]
    if assert_eq("famine outranks tax_reserve_uncovered_far",
                 primary_triggers, ["famine"]): pp += 1
    else: ff += 1
    # Tax imminent vs coverage severe: tax_imminent should win
    candidates = [
        {"priority": "primary", "context": {"trigger": "coverage_severe"}},
        {"priority": "primary", "context": {"trigger": "tax_reserve_uncovered_imminent"}},
    ]
    out = select_primary_freelancer_rec(candidates)
    primary_triggers = [(x.get("context") or {}).get("trigger")
                        for x in out if x.get("priority") == "primary"]
    if assert_eq("tax_imminent outranks coverage_severe",
                 primary_triggers, ["tax_reserve_uncovered_imminent"]): pp += 1
    else: ff += 1

    print(f"\n{pp} passed, {ff} failed.")
    return ff == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
