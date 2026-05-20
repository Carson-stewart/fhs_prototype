"""Comprehensive state capture for the fl1 vs fl9 sub-score divergence
diagnostic (Phase 6).

Captures four layers per profile state:
  L1 — IndividualInput dataclass that fed the engine
  L2 — score_individual() raw return (ScoreResult)
  L3 — score_to_dict() API JSON the renderer receives
  L4 — post-normalizeResponse simulation (what the renderer would display)

Two scenarios:
  fl1: served via /api/profile/{idx} (synthetic profile, full FL fields)
  fl9: served via /api/score (form-submit; ScoreRequest strips archetype + FL fields)
"""
import json
import os
import sys
from dataclasses import asdict, fields

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, ROOT)

from profiles import FREELANCER_PROFILES  # noqa: E402
from engine import score_individual, score_to_dict, IndividualInput  # noqa: E402


def dataclass_to_dict(inp):
    """Plain-dict view of an IndividualInput (fields only)."""
    return {f.name: getattr(inp, f.name) for f in fields(inp)}


def simulate_normalize_flat(d):
    """Mirror static/index.html:normalizeResponse for flat /api/score shape."""
    return {
        "fhs": d.get("fhs"),
        "fss": d.get("fss"),
        "frs": d.get("frs"),
        "fhs_breakdown": d.get("fhs_breakdown"),
        "fss_breakdown": d.get("fss_breakdown"),
        "frs_breakdown": d.get("frs_breakdown"),
        "plan_phases": (d.get("plan") or {}).get("plan_phases", []) if isinstance(d.get("plan"), dict) else [],
        "fhs_band": d.get("fhs_band"),
        "fss_band": d.get("fss_band"),
        "frs_band": d.get("frs_band"),
    }


def simulate_normalize_nested(d):
    """Mirror static/index.html:normalizeResponse for nested shape."""
    sc = d.get("scores") or {}
    bd = d.get("breakdowns") or {}
    pl = d.get("plan") or {}
    return {
        "fhs": sc.get("fhs"),
        "fss": sc.get("fss"),
        "frs": sc.get("frs"),
        "fhs_breakdown": bd.get("fhs"),
        "fss_breakdown": bd.get("fss"),
        "frs_breakdown": bd.get("frs"),
        "plan_phases": pl.get("plan_phases", []),
        "fhs_band": sc.get("fhs_band"),
        "fss_band": sc.get("fss_band"),
        "frs_band": sc.get("frs_band"),
    }


def extract_visible_fss_pcts(norm):
    """Re-render the bars the user actually sees on the FSS card."""
    bd = norm.get("fss_breakdown") or {}
    out = {}
    for k, v in bd.items():
        if k.startswith("_"):
            continue
        pct = v.get("contribution_pct") if isinstance(v, dict) else None
        if pct is not None:
            out[k] = round(pct, 1)
    return out


def capture_fl1():
    """fl1: synthetic profile path. /api/profile/{idx} runs score_individual
    on the full FREELANCER_PROFILES[0]['input'] (archetype=freelancer)."""
    inp = FREELANCER_PROFILES[0]["input"]
    r = score_individual(inp)
    d = score_to_dict(r)
    return {
        "scenario": "fl1",
        "route": "/api/profile/{idx} (synthetic-profile path)",
        "L1_individualinput": dataclass_to_dict(inp),
        "L2_scoreresult": {
            "fhs": r.fhs, "fss": r.fss, "frs": r.frs,
            "fss_breakdown_keys": list(r.fss_breakdown.keys()),
        },
        "L3_score_to_dict": d,
        "L4_visible_fss_pcts_nested": extract_visible_fss_pcts(simulate_normalize_nested(d)),
    }


def capture_fl9():
    """fl9: form-submit path. /api/score builds IndividualInput from
    ScoreRequest, which strips archetype + all FL/SB-specific fields."""
    src = FREELANCER_PROFILES[0]["input"]
    # Mirror api.py:768 compute_score's IndividualInput construction
    # using only ScoreRequest fields (api.py:44-65).
    inp = IndividualInput(
        I_gross=src.I_gross, I_net=src.I_net,
        E_ess=src.E_ess, E_house=src.E_house,
        D_min=src.D_min, D_hi=src.D_hi, D_lo=src.D_lo,
        S_liq=src.S_liq, S_ret=src.S_ret,
        age=src.age,
        has_life_insurance=src.has_life_insurance,
        has_disability_insurance=src.has_disability_insurance,
        overdraft_count_90d=src.overdraft_count_90d,
        late_payment_count_90d=src.late_payment_count_90d,
        momentum_slope=src.momentum_slope,
        streak_days=src.streak_days,
        name=src.name,
    )
    r = score_individual(inp)
    d = score_to_dict(r)
    return {
        "scenario": "fl9",
        "route": "/api/score (form-submit; ScoreRequest strips archetype + FL fields)",
        "L1_individualinput": dataclass_to_dict(inp),
        "L2_scoreresult": {
            "fhs": r.fhs, "fss": r.fss, "frs": r.frs,
            "fss_breakdown_keys": list(r.fss_breakdown.keys()),
        },
        "L3_score_to_dict": d,
        "L4_visible_fss_pcts_nested": extract_visible_fss_pcts(simulate_normalize_nested(d)),
    }


def main():
    os.makedirs(HERE, exist_ok=True)
    fl1 = capture_fl1()
    fl9 = capture_fl9()
    with open(os.path.join(HERE, "fl1.json"), "w", encoding="utf-8") as f:
        json.dump(fl1, f, indent=2, default=str)
    with open(os.path.join(HERE, "fl9.json"), "w", encoding="utf-8") as f:
        json.dump(fl9, f, indent=2, default=str)

    # Diff summary
    diff = {
        "fl1_visible_pcts": fl1["L4_visible_fss_pcts_nested"],
        "fl9_visible_pcts": fl9["L4_visible_fss_pcts_nested"],
        "fl1_archetype": fl1["L1_individualinput"].get("archetype"),
        "fl9_archetype": fl9["L1_individualinput"].get("archetype"),
        "fl1_volatility": fl1["L1_individualinput"].get("income_volatility_observed"),
        "fl9_volatility": fl9["L1_individualinput"].get("income_volatility_observed"),
        "fl1_fhs_band": fl1["L2_scoreresult"]["fhs"],
        "fl9_fhs_band": fl9["L2_scoreresult"]["fhs"],
        "input_fields_differ": [
            k for k in fl1["L1_individualinput"]
            if fl1["L1_individualinput"][k] != fl9["L1_individualinput"][k]
        ],
    }
    with open(os.path.join(HERE, "_diff_summary.json"), "w", encoding="utf-8") as f:
        json.dump(diff, f, indent=2, default=str)

    print("=== fl1 visible FSS percentages ===")
    for k, p in fl1["L4_visible_fss_pcts_nested"].items():
        print(f"  {k}: {p}%")
    print("\n=== fl9 visible FSS percentages ===")
    for k, p in fl9["L4_visible_fss_pcts_nested"].items():
        print(f"  {k}: {p}%")
    print("\n=== Input fields that differ ===")
    for k in diff["input_fields_differ"]:
        print(f"  {k}: fl1={fl1['L1_individualinput'][k]!r}  fl9={fl9['L1_individualinput'][k]!r}")


if __name__ == "__main__":
    main()
