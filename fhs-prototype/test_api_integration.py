"""Integration tests for /api/score — the API surface that the Compute
button hits in production.

Why this suite exists
─────────────────────
Before Phase 6's form-submit-archetype-stripping fix, `test_runner.py`
ran `score_individual()` directly, bypassing the API contract. The bug
that silently degraded every Freelancer / Small-Business profile to
Individual scoring on form submit lived entirely at the API layer, and
all 7 existing gates were green throughout. The cost: a beta-blocker
bug that only surfaced under integration testing.

This suite is the permanent guard against that class of bug recurring.
Every archetype gets at least one test that POSTs through `/api/score`
and asserts the response is archetype-shaped (not silently-degraded
Individual-shaped).

The brief flags this as the 8th gate going forward.

Run:  python test_api_integration.py
"""
import json
import sys

from fastapi.testclient import TestClient

from api import app
from profiles import FREELANCER_PROFILES, SB_PROFILES, INDIVIDUAL_PROFILES


client = TestClient(app)
_results = []


def _record(name, ok, detail=""):
    _results.append((name, ok, detail))
    flag = "ok   " if ok else "FAIL "
    print(f"  {flag} {name}" + (f"  ({detail})" if detail else ""))


def _body_from_input(inp, *, include_extension: bool):
    """Build a /api/score POST body from an IndividualInput. If
    include_extension is False, mirrors the PRE-FIX frontend (Individual
    fields only) — useful for asserting backward compatibility."""
    body = {
        "I_gross": inp.I_gross, "I_net": inp.I_net,
        "E_ess": inp.E_ess, "E_house": inp.E_house,
        "D_min": inp.D_min, "D_hi": inp.D_hi, "D_lo": inp.D_lo,
        "S_liq": inp.S_liq, "S_ret": inp.S_ret,
        "age": inp.age,
        "has_life_insurance": inp.has_life_insurance,
        "has_disability_insurance": inp.has_disability_insurance,
        "overdraft_count_90d": inp.overdraft_count_90d,
        "late_payment_count_90d": inp.late_payment_count_90d,
        "name": inp.name,
    }
    if include_extension:
        # Thread the full archetype-extension surface as the POST-FIX
        # frontend now does. Mirrors api.ArchetypeExtensionFields and
        # api._extension_kwargs whitelist.
        body.update({
            "archetype": inp.archetype,
            "business_structure": inp.business_structure,
            "revenue_cadence":    inp.revenue_cadence,
            "payroll_periodicity":       inp.payroll_periodicity,
            "payroll_amount_per_cycle":  inp.payroll_amount_per_cycle,
            "owner_draw_amount":         inp.owner_draw_amount,
            "owner_draw_cadence":        inp.owner_draw_cadence,
            "seasonal_revenue":          inp.seasonal_revenue,
            "income_volatility_observed":      inp.income_volatility_observed,
            "months_of_income_history":        inp.months_of_income_history,
            "tax_reserve_balance":             inp.tax_reserve_balance,
            "tax_reserve_target_pct":          inp.tax_reserve_target_pct,
            "quarterly_tax_due_date":          inp.quarterly_tax_due_date,
            "quarterly_tax_estimated_amount":  inp.quarterly_tax_estimated_amount,
            "fixed_monthly_obligations":       inp.fixed_monthly_obligations,
            "freelance_account_separation":    inp.freelance_account_separation,
            # default_factory fields — only send if non-empty (engine
            # rejects explicit None for these)
            "ar_aging_buckets":   inp.ar_aging_buckets or None,
            "ap_pending":         inp.ap_pending or None,
            "business_lines_of_credit": inp.business_lines_of_credit or None,
            "seasonal_low_months":      inp.seasonal_low_months or None,
            "income_sources":           inp.income_sources or None,
        })
    return body


import uuid

def _post_score(body):
    """POST /api/score with a fresh X-User-Id per call.

    Without a per-call user ID, the api.py compute_score path reads
    `momentum_slope` and `streak_days` from a SQLite-backed user state
    that accumulates across the test session — polluting fresh-input
    scoring with stale-state values and producing per-run-order flake.
    A unique UUID per call gives each test a clean zero-state.
    """
    headers = {"X-User-Id": "test-" + uuid.uuid4().hex}
    r = client.post("/api/score", json=body, headers=headers)
    assert r.status_code == 200, f"/api/score returned {r.status_code}: {r.text}"
    return r.json()


def _fss_dim_pct(resp, dim_name):
    """Return contribution_pct for a named FSS dim from the response."""
    bd = (resp.get("breakdowns") or {}).get("fss") or {}
    v = bd.get(dim_name)
    if not isinstance(v, dict):
        return None
    return v.get("contribution_pct")


def _rec_titles(resp):
    titles = []
    for r in (resp.get("recommendations") or []):
        if isinstance(r, dict):
            titles.append(r.get("title") or r.get("action") or "")
    return titles


# ─────────────────────────────────────────────────────────────────────
# Individual archetype — backward-compatibility regression
# ─────────────────────────────────────────────────────────────────────

def test_individual_default_archetype_works():
    """No archetype field → defaults to individual_w2 → engine runs the
    Individual scoring path. Asserts the pre-fix frontend body shape
    still produces a valid Individual response."""
    inp = INDIVIDUAL_PROFILES[0]["input"]
    body = _body_from_input(inp, include_extension=False)
    resp = _post_score(body)
    scores = resp.get("scores") or {}
    assert scores.get("fhs") is not None, "Individual scoring failed without archetype field"
    # FL-specific contributors should NOT appear for an Individual profile
    assert _fss_dim_pct(resp, "Income volatility") in (0.0, None), \
        "Individual archetype unexpectedly produced Income volatility contributor"


def test_individual_explicit_archetype_unchanged():
    """Sending archetype='individual_w2' explicitly produces the same
    breakdown as the implicit default."""
    inp = INDIVIDUAL_PROFILES[0]["input"]
    r1 = _post_score(_body_from_input(inp, include_extension=False))
    r2 = _post_score(_body_from_input(inp, include_extension=True))
    assert r1["scores"]["fhs"] == r2["scores"]["fhs"]


# ─────────────────────────────────────────────────────────────────────
# Freelancer archetype — the bug originally surfaced here (fl1 vs fl9)
# ─────────────────────────────────────────────────────────────────────

def test_freelancer_fields_flow_to_engine():
    """The fl1 vs fl9 divergence (50%→61% Insurance gap drift) was caused
    by income_volatility_observed flipping 0.15 → None on the form
    submit path. With the fix, sending volatility through /api/score
    must produce the FL-FSS-1 Income volatility contributor."""
    inp = FREELANCER_PROFILES[0]["input"]  # fl1 Predictable
    body = _body_from_input(inp, include_extension=True)
    resp = _post_score(body)
    # The contributor must be present with the expected pla (vol=0.15
    # → pla=0.15 → ~18.6% share given fl1's strain mix).
    pct = _fss_dim_pct(resp, "Income volatility")
    assert pct is not None and pct > 10, \
        f"Income volatility contributor missing/too low: {pct} — FL extension didn't run"


def test_freelancer_fl1_fl9_parity_via_api():
    """The originally-reported regression. fl1 (synthetic profile) and
    fl9 (same profile submitted via /api/score) must now produce
    identical breakdowns. Before the fix, Insurance gap drifted 50%→61%
    and Retirement gap drifted 32%→39%."""
    inp = FREELANCER_PROFILES[0]["input"]
    resp = _post_score(_body_from_input(inp, include_extension=True))
    ins_pct = _fss_dim_pct(resp, "Insurance gap")
    ret_pct = _fss_dim_pct(resp, "Retirement gap")
    vol_pct = _fss_dim_pct(resp, "Income volatility")
    # Tolerance ±0.5pp to absorb harmless float jitter
    assert ins_pct is not None and abs(ins_pct - 49.7) < 0.5, \
        f"Insurance gap drift: got {ins_pct}%, expected ~49.7%"
    assert ret_pct is not None and abs(ret_pct - 31.7) < 0.5, \
        f"Retirement gap drift: got {ret_pct}%, expected ~31.7%"
    assert vol_pct is not None and abs(vol_pct - 18.6) < 0.5, \
        f"Income volatility drift: got {vol_pct}%, expected ~18.6%"


def test_freelancer_buggy_path_no_longer_degrades_silently():
    """Verifies the symptom of the original bug. If a caller sends an
    FL profile's Individual-only fields WITHOUT the archetype field,
    the response degrades to Individual scoring (FL-FSS-1 missing) —
    this is documented backward-compatible behavior, the fix is that
    real frontends now send archetype. The opposite assertion (sending
    archetype DOES produce FL output) lives in test_freelancer_*."""
    inp = FREELANCER_PROFILES[0]["input"]
    resp_legacy = _post_score(_body_from_input(inp, include_extension=False))
    resp_fixed  = _post_score(_body_from_input(inp, include_extension=True))
    legacy_vol = _fss_dim_pct(resp_legacy, "Income volatility")
    fixed_vol  = _fss_dim_pct(resp_fixed,  "Income volatility")
    assert legacy_vol in (0.0, None), f"Legacy path unexpectedly produced FL contributor: {legacy_vol}"
    assert fixed_vol is not None and fixed_vol > 10, \
        f"Fixed path failed to produce FL contributor: {fixed_vol}"


def test_freelancer_famine_framing_via_api():
    """fl3 (Famine) is the highest-stakes brand-voice surface. The bug
    completely skipped Famine recommendations on form submit because
    `extend_score_for_freelancer` gates on archetype. Post-fix, Famine
    primary recs must fire when an FL Famine-shaped input is submitted."""
    inp = FREELANCER_PROFILES[2]["input"]  # fl3 Famine
    body = _body_from_input(inp, include_extension=True)
    resp = _post_score(body)
    titles = _rec_titles(resp)
    famine_titles = ("Focus on essentials this period", "Protect your tax reserve")
    has_famine_primary = any(t in famine_titles for t in titles)
    assert has_famine_primary, \
        f"Famine framing did not fire via /api/score. Got titles: {titles}"


# ─────────────────────────────────────────────────────────────────────
# Small Business archetype — same shape of bug applies
# ─────────────────────────────────────────────────────────────────────

def test_smallbusiness_fields_flow_to_engine():
    """SB Tightening should produce non-zero strain on the SB-specific
    FSS contributors (AR aging / AP compression / LOC utilization)
    when archetype='small_business' is sent."""
    inp = SB_PROFILES[1]["input"]  # SB Tightening
    body = _body_from_input(inp, include_extension=True)
    resp = _post_score(body)
    sb_dims = ["AR aging strain", "AP compression strain",
               "LOC utilization strain", "Payroll coverage strain"]
    nonzero = [d for d in sb_dims if (_fss_dim_pct(resp, d) or 0) > 0]
    assert nonzero, \
        f"No SB FSS contributors fired — SB extension didn't dispatch. " \
        f"Response FSS dims: {list((resp.get('breakdowns') or {}).get('fss') or {})}"


def test_smallbusiness_buggy_path_degrades_silently():
    """Mirror of the FL silent-degradation test for SB archetype."""
    inp = SB_PROFILES[1]["input"]
    resp_legacy = _post_score(_body_from_input(inp, include_extension=False))
    sb_dims = ["AR aging strain", "AP compression strain",
               "LOC utilization strain", "Payroll coverage strain"]
    # Without archetype, none of the SB contributors should appear in the
    # response (engine never dispatches the SB extension)
    legacy_keys = list((resp_legacy.get("breakdowns") or {}).get("fss") or {})
    sb_keys_present = [d for d in sb_dims if d in legacy_keys]
    assert not sb_keys_present, \
        f"Legacy body (no archetype) unexpectedly returned SB contributors: {sb_keys_present}"


# ─────────────────────────────────────────────────────────────────────
# Scrubber + plumbing regression
# ─────────────────────────────────────────────────────────────────────

def test_all_archetypes_scrubber_clean():
    """The trade-secret scrubber must still pass on every archetype's
    /api/score response after the contract widened."""
    from engine import _scrub_breakdowns_for_api  # noqa: F401
    from api import _assert_no_optimization_internals

    cases = [
        ("Individual W-2", INDIVIDUAL_PROFILES[0]["input"]),
        ("Freelancer",     FREELANCER_PROFILES[0]["input"]),
        ("Famine",         FREELANCER_PROFILES[2]["input"]),
        ("Small Business", SB_PROFILES[1]["input"]),
    ]
    for label, inp in cases:
        body = _body_from_input(inp, include_extension=True)
        resp = _post_score(body)
        try:
            _assert_no_optimization_internals(resp)
        except AssertionError as e:
            raise AssertionError(f"Scrubber tripped on {label} response: {e}")


# ─────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────

def main():
    tests = [
        ("Individual: default archetype works",     test_individual_default_archetype_works),
        ("Individual: explicit archetype unchanged", test_individual_explicit_archetype_unchanged),
        ("FL: extension fields flow to engine",     test_freelancer_fields_flow_to_engine),
        ("FL: fl1↔fl9 parity via API (regression)", test_freelancer_fl1_fl9_parity_via_api),
        ("FL: buggy path degrades, fixed path doesn't", test_freelancer_buggy_path_no_longer_degrades_silently),
        ("FL: Famine framing fires via /api/score", test_freelancer_famine_framing_via_api),
        ("SB: extension fields flow to engine",     test_smallbusiness_fields_flow_to_engine),
        ("SB: buggy path degrades silently",        test_smallbusiness_buggy_path_degrades_silently),
        ("All archetypes: scrubber stays clean",    test_all_archetypes_scrubber_clean),
    ]
    print(f"Running {len(tests)} API integration tests...\n")
    for name, fn in tests:
        try:
            fn()
            _record(name, True)
        except AssertionError as e:
            _record(name, False, str(e))
        except Exception as e:
            _record(name, False, f"{type(e).__name__}: {e}")

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = len(_results) - passed
    print(f"\n{passed} passed, {failed} failed.")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
