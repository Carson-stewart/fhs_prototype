"""Post-fix visual re-test (programmatic equivalent).

The brief asks for a browser visual re-test of fl3 / fl8 / fl9 through
the actual /api/score path, comparing against the Pass 1/Pass 2 post-
polish state. No browser is available in this environment, so we
substitute a state capture that POSTs through /api/score with the
post-fix frontend body shape (archetype + extension fields) and diffs
against Pass 2's after_pass2 captures (which were made via direct
score_individual() calls — bypassing the bug — i.e. they represent the
intended correct state).

If the post-fix /api/score path produces the same scores + breakdown
contributors as the direct path, the fix has landed end-to-end.

Run:  python tests/state_capture/post_fix_visual/_capture.py
"""
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from profiles import FREELANCER_PROFILES  # noqa: E402
from api import app  # noqa: E402

CLIENT = TestClient(app)


def _body(inp):
    """Mirror the post-fix frontend body assembly."""
    return {
        "I_gross": inp.I_gross, "I_net": inp.I_net,
        "E_ess": inp.E_ess, "E_house": inp.E_house,
        "D_min": inp.D_min, "D_hi": inp.D_hi, "D_lo": inp.D_lo,
        "S_liq": inp.S_liq, "S_ret": inp.S_ret,
        "age": inp.age,
        "has_life_insurance": inp.has_life_insurance,
        "has_disability_insurance": inp.has_disability_insurance,
        "name": inp.name,
        "archetype": inp.archetype,
        "business_structure": inp.business_structure,
        "income_volatility_observed": inp.income_volatility_observed,
        "months_of_income_history":   inp.months_of_income_history,
        "tax_reserve_balance":        inp.tax_reserve_balance,
        "tax_reserve_target_pct":     inp.tax_reserve_target_pct,
        "quarterly_tax_due_date":     inp.quarterly_tax_due_date,
        "quarterly_tax_estimated_amount": inp.quarterly_tax_estimated_amount,
        "fixed_monthly_obligations":  inp.fixed_monthly_obligations,
        "freelance_account_separation": inp.freelance_account_separation,
        "income_sources":             inp.income_sources or None,
    }


def fss_pcts(resp):
    bd = (resp.get("breakdowns") or {}).get("fss") or {}
    return {k: round(v.get("contribution_pct") or 0, 1)
            for k, v in bd.items() if not k.startswith("_")
            and (v.get("contribution_pct") or 0) > 0}


def rec_titles(resp):
    return [
        (r.get("title") or r.get("action") or "")
        for r in (resp.get("recommendations") or [])
        if isinstance(r, dict)
    ]


def post(body):
    headers = {"X-User-Id": "post-fix-test-" + uuid.uuid4().hex}
    r = CLIENT.post("/api/score", json=body, headers=headers)
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    return r.json()


def capture_profile(label, inp):
    resp = post(_body(inp))
    return {
        "label": label,
        "scores": resp.get("scores"),
        "fss_pcts": fss_pcts(resp),
        "rec_titles": rec_titles(resp),
        "famine_context_present": "famine_context" in (
            (resp.get("insights") or {}).get("freelancer") or {}
        ),
        "plan_phases_count": len(((resp.get("plan") or {}).get("plan_phases") or [])),
    }


def main():
    os.makedirs(HERE, exist_ok=True)
    snapshots = {
        "fl3_famine":           capture_profile("fl3", FREELANCER_PROFILES[2]["input"]),
        "fl8_quarterly_due":    capture_profile("fl8", FREELANCER_PROFILES[7]["input"]),
        # fl9 == fl1 at the engine layer (multi-bank Plaid is a frontend state).
        # The originally-reported divergence was fl9 going through /api/score
        # producing 61%/39% instead of fl1's 50%/32%. Post-fix, going through
        # /api/score must reproduce the fl1 numbers.
        "fl9_predictable_via_api": capture_profile("fl9", FREELANCER_PROFILES[0]["input"]),
    }

    for k, v in snapshots.items():
        with open(os.path.join(HERE, f"{k}.json"), "w", encoding="utf-8") as f:
            json.dump(v, f, indent=2, default=str)

    # ── Acceptance checks ──
    print("\n=== Acceptance ===\n")

    # fl3 — Famine framing must fire via /api/score
    fl3 = snapshots["fl3_famine"]
    famine_titles = ("Focus on essentials this period", "Protect your tax reserve")
    fl3_has_famine = any(t in famine_titles for t in fl3["rec_titles"])
    print(f"[fl3] Famine framing fires:                          {'YES' if fl3_has_famine else 'NO'}")
    print(f"      famine_context present:                        {fl3['famine_context_present']}")
    print(f"      titles[:4]: {fl3['rec_titles'][:4]}")

    # fl8 — tax-reserve recommendation must fire
    fl8 = snapshots["fl8_quarterly_due"]
    fl8_tax_rec = any("tax" in t.lower() for t in fl8["rec_titles"])
    print(f"\n[fl8] Tax-reserve recommendation present:            {'YES' if fl8_tax_rec else 'NO'}")
    print(f"      plan phases: {fl8['plan_phases_count']} (Pass 2 baseline = 2)")
    print(f"      titles[:4]: {fl8['rec_titles'][:4]}")

    # fl9 — must match fl1 numbers (the originally-reported regression)
    fl9 = snapshots["fl9_predictable_via_api"]
    ins = fl9["fss_pcts"].get("Insurance gap")
    ret = fl9["fss_pcts"].get("Retirement gap")
    vol = fl9["fss_pcts"].get("Income volatility")
    fl9_matches_fl1 = (
        ins is not None and abs(ins - 49.7) < 0.5
        and ret is not None and abs(ret - 31.7) < 0.5
        and vol is not None and abs(vol - 18.6) < 0.5
    )
    print(f"\n[fl9] /api/score path matches fl1 sub-scores:        {'YES' if fl9_matches_fl1 else 'NO'}")
    print(f"      Insurance gap:     {ins}% (expected 49.7%, was 61.1% before fix)")
    print(f"      Retirement gap:    {ret}% (expected 31.7%, was 38.9% before fix)")
    print(f"      Income volatility: {vol}% (expected 18.6%, was 0%   before fix — contributor missing entirely)")

    overall = fl3_has_famine and fl8_tax_rec and fl9_matches_fl1
    print(f"\n=== Overall: {'PASS' if overall else 'FAIL'} ===")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
