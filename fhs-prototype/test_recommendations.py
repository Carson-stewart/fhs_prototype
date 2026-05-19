"""Tests for the recommendations module (Phase 5a.4).

Pure tests — no API client, no live server. Exercises:
  • Action recommendations (4 SB-FSS triggers + owner draw)
  • Data completion (AR aging / AP pending)
  • Archetype suggestion (Individual+business → fires; SB → does not)
  • Detection override (medium → fires; high → does not)
  • Confidence-driven copy gating (high / medium / low / missing)
  • Brand voice audit — programmatic check on every generated string
  • Live profile recommendations across SB_PROFILES
  • No regression on Individual archetype recommendations

Run with:
    python test_recommendations.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recommendations import (
    audit_brand_voice, _rec,
    _ar_aging_action, _ap_compression_action,
    _loc_utilization_action, _payroll_coverage_action,
    _owner_draw_action,
    generate_action_recommendations,
    generate_data_completion_recommendations,
    generate_archetype_suggestion,
    generate_detection_overrides,
    compile_sb_recommendations,
    _BRAND_VOICE_FORBIDDEN_WORDS, _BRAND_VOICE_FORBIDDEN_PHRASES,
)


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


def assert_raises(label, exc_type, fn):
    try:
        fn()
    except exc_type:
        print(f"  ok    {label}")
        return True
    except Exception as e:
        print(f"  FAIL  {label}: expected {exc_type.__name__}, got "
              f"{type(e).__name__}")
        return False
    print(f"  FAIL  {label}: expected {exc_type.__name__}, no exception")
    return False


def run():
    pp = ff = 0

    # ── Action recommendations (per dimension) ──────────────────────
    print("Action recs — per SB-FSS trigger:")

    # AR aging — 90+ dominant
    rec = _ar_aging_action(
        ar_buckets={"current": 500, "30_days": 1000, "60_days": 2000,
                    "90_plus_days": 18000},
        ar_pla=0.85,
    )
    if assert_truthy("AR aging triggers when pla > 0.4", rec is not None): pp += 1
    else: ff += 1
    if assert_eq("AR aging type=action", rec["type"], "action"): pp += 1
    else: ff += 1
    if assert_eq("AR aging priority=primary", rec["priority"], "primary"): pp += 1
    else: ff += 1
    if assert_truthy("AR aging title mentions 90 days",
                     "90 days" in rec["title"]): pp += 1
    else: ff += 1

    # AR aging — 60-day dominant
    rec = _ar_aging_action(
        ar_buckets={"current": 500, "30_days": 1000, "60_days": 8000,
                    "90_plus_days": 2000},
        ar_pla=0.55,
    )
    if assert_truthy("AR aging 60-day path: title mentions 60 days",
                     "60 days" in rec["title"]): pp += 1
    else: ff += 1

    # AR aging below threshold → None
    rec = _ar_aging_action(
        ar_buckets={"current": 5000, "30_days": 500},
        ar_pla=0.1,
    )
    if assert_eq("AR aging below threshold returns None",
                 rec, None): pp += 1
    else: ff += 1

    # AP compression — primary
    rec = _ap_compression_action(
        ap_pending={"due_within_7d": 14000, "due_8_to_30d": 4000, "overdue": 2000},
        ap_pla=0.85,
        s_liq=20000,
    )
    if assert_truthy("AP compression primary fires", rec is not None): pp += 1
    else: ff += 1
    if assert_eq("AP compression priority=primary",
                 rec["priority"], "primary"): pp += 1
    else: ff += 1

    # AP compression — secondary (overdue carrying, low overall pla)
    rec = _ap_compression_action(
        ap_pending={"due_within_7d": 500, "due_8_to_30d": 1000, "overdue": 800},
        ap_pla=0.35,
        s_liq=30000,
    )
    if assert_truthy("AP secondary (overdue carrying) fires",
                     rec is not None): pp += 1
    else: ff += 1
    if assert_eq("AP secondary priority=secondary",
                 rec["priority"], "secondary"): pp += 1
    else: ff += 1

    # LOC utilization — primary, advisory tier (70-85%)
    rec = _loc_utilization_action(
        locs=[{"limit": 30000, "balance": 23000, "apr": 0.12, "name": "X"}],
        loc_pla=0.55,
    )
    if assert_truthy("LOC advisory tier fires at 76%", rec is not None): pp += 1
    else: ff += 1
    if assert_truthy("LOC advisory: 'pause' in title",
                     "Pause" in rec["title"]): pp += 1
    else: ff += 1

    # LOC utilization — critical tier (>85%)
    rec = _loc_utilization_action(
        locs=[{"limit": 30000, "balance": 27000, "apr": 0.12, "name": "X"}],
        loc_pla=0.85,
    )
    if assert_truthy("LOC critical tier: 'lender' in title",
                     "lender" in rec["title"].lower()): pp += 1
    else: ff += 1

    # Payroll coverage
    rec = _payroll_coverage_action(payroll_pla=0.7, weeks_of_coverage=1.5)
    if assert_truthy("Payroll coverage primary fires",
                     rec is not None): pp += 1
    else: ff += 1

    # Owner draw — unsustainable
    rec = _owner_draw_action({
        "sustainable": False,
        "current_draw": 3000,
        "max_sustainable_draw": 0,
        "headroom": -3000,
    })
    if assert_truthy("Owner draw unsustainable fires", rec is not None): pp += 1
    else: ff += 1
    if assert_truthy("Owner draw title mentions pause",
                     "Pause" in rec["title"]): pp += 1
    else: ff += 1

    # Owner draw — sustainable → None
    rec = _owner_draw_action({"sustainable": True, "current_draw": 1000,
                              "max_sustainable_draw": 5000, "headroom": 4000})
    if assert_eq("Owner draw sustainable returns None", rec, None): pp += 1
    else: ff += 1

    # ── Data completion ────────────────────────────────────────────
    print("\nData completion recs:")

    mapped = {
        "ar_aging_buckets": {"value": None, "confidence": "missing",
                             "source": "manual_entry_required",
                             "notes": "Plaid does not provide..."},
        "ap_pending":       {"value": None, "confidence": "missing",
                             "source": "manual_entry_required",
                             "notes": "..."},
        "S_liq":            {"value": 5000, "confidence": "high",
                             "source": "plaid_balance_get", "notes": ""},
    }
    recs = generate_data_completion_recommendations(mapped)
    if assert_eq("data completion: 2 recs (AR + AP)", len(recs), 2): pp += 1
    else: ff += 1
    if assert_eq("data completion type",
                 recs[0]["type"], "data_completion"): pp += 1
    else: ff += 1
    if assert_eq("data completion priority=primary",
                 recs[0]["priority"], "primary"): pp += 1
    else: ff += 1
    fields = {r["context"]["field"] for r in recs}
    if assert_eq("data completion covers ar+ap fields",
                 fields, {"ar_aging_buckets", "ap_pending"}): pp += 1
    else: ff += 1

    # When manual entry is satisfied (S_liq has plaid source),
    # data completion does NOT fire for it.
    only_s_liq = {"S_liq": mapped["S_liq"]}
    recs = generate_data_completion_recommendations(only_s_liq)
    if assert_eq("data completion: no recs when no manual_entry_required fields",
                 len(recs), 0): pp += 1
    else: ff += 1

    # ── Archetype suggestion ────────────────────────────────────────
    print("\nArchetype suggestion:")

    # Individual + business accounts → fires
    sug = generate_archetype_suggestion(
        ["Acme LLC Operating", "Acme Business Card"],
        current_archetype="individual_w2",
    )
    if assert_truthy("Individual+business: suggestion fires",
                     sug is not None): pp += 1
    else: ff += 1
    if assert_eq("suggestion type",
                 sug["type"], "archetype_suggestion"): pp += 1
    else: ff += 1

    # SB + business accounts → does NOT fire
    sug = generate_archetype_suggestion(
        ["Acme LLC Operating"], current_archetype="small_business",
    )
    if assert_eq("SB archetype: suggestion suppressed", sug, None): pp += 1
    else: ff += 1

    # No business accounts → does NOT fire
    sug = generate_archetype_suggestion([], current_archetype="individual_w2")
    if assert_eq("no business accounts: suggestion suppressed",
                 sug, None): pp += 1
    else: ff += 1

    # ── Detection override ──────────────────────────────────────────
    print("\nDetection override:")

    detections = [
        {"account_id": "a1", "account_name": "Tartan Plumbing LLC",
         "is_business": True, "confidence": "medium", "source": "heuristic_name_match"},
        {"account_id": "a2", "account_name": "Plaid Categorized Biz",
         "is_business": True, "confidence": "high", "source": "plaid_categorization"},
        {"account_id": "a3", "account_name": "Personal Checking",
         "is_business": False, "confidence": "high", "source": "default_personal"},
    ]
    overrides = generate_detection_overrides(detections)
    if assert_eq("override: 1 rec (medium-confidence biz only)",
                 len(overrides), 1): pp += 1
    else: ff += 1
    if assert_eq("override mentions correct account",
                 overrides[0]["context"]["account_name"],
                 "Tartan Plumbing LLC"): pp += 1
    else: ff += 1
    if assert_eq("override priority=tertiary",
                 overrides[0]["priority"], "tertiary"): pp += 1
    else: ff += 1

    # ── Confidence-driven copy gating ───────────────────────────────
    print("\nConfidence-driven copy gating:")

    ar_buckets = {"current": 0, "30_days": 1000, "60_days": 2000,
                  "90_plus_days": 18000}
    rec_high = _ar_aging_action(ar_buckets, 0.8, confidence="high")
    rec_med  = _ar_aging_action(ar_buckets, 0.8, confidence="medium")
    rec_low  = _ar_aging_action(ar_buckets, 0.8, confidence="low")

    if assert_truthy("high-conf body: no preface phrase",
                     "From what we can see" not in rec_high["body"]
                     and "Based on partial data" not in rec_high["body"]): pp += 1
    else: ff += 1
    if assert_truthy("medium-conf body: 'From what we can see'",
                     "From what we can see" in rec_med["body"]): pp += 1
    else: ff += 1
    if assert_truthy("low-conf body: 'Based on partial data'",
                     "Based on partial data" in rec_low["body"]): pp += 1
    else: ff += 1
    if assert_truthy("high-conf body: dollar formatted directly",
                     "$18,000" in rec_high["body"]): pp += 1
    else: ff += 1
    if assert_truthy("medium-conf body: 'around $'",
                     "around $" in rec_med["body"]): pp += 1
    else: ff += 1
    if assert_truthy("low-conf body: 'roughly $'",
                     "roughly $" in rec_low["body"]): pp += 1
    else: ff += 1

    # ── Brand voice audit — explicit failure cases ──────────────────
    print("\nBrand voice audit:")

    if assert_raises(
        "audit raises on 'WARNING'", AssertionError,
        lambda: _rec("action", "primary", "high",
                     "WARNING: pay this now", "ok body", "ok next"),
    ): pp += 1
    else: ff += 1
    if assert_raises(
        "audit raises on 'falling behind'", AssertionError,
        lambda: _rec("action", "primary", "high",
                     "Catch up", "You're falling behind on payments",
                     "ok next"),
    ): pp += 1
    else: ff += 1
    if assert_raises(
        "audit raises on 'at risk'", AssertionError,
        lambda: _rec("action", "primary", "high",
                     "Take action",
                     "Your business is at risk if you don't",
                     "ok next"),
    ): pp += 1
    else: ff += 1
    if assert_raises(
        "audit raises on 'critical'", AssertionError,
        lambda: _rec("action", "primary", "high",
                     "critical alert", "ok body", "ok next"),
    ): pp += 1
    else: ff += 1

    # Audit allows correct copy
    rec = _rec("action", "primary", "high",
               "Pause owner draws this cycle",
               "Current pace exceeds what your business can sustain.",
               "Trim by $1,200 until revenue catches up.")
    if assert_truthy("audit passes calm copy", rec is not None): pp += 1
    else: ff += 1

    # ── Live profile recommendations ─────────────────────────────────
    print("\nLive SB profile recommendations:")
    from engine import score_individual
    from profiles import SB_PROFILES

    # SB Healthy → no action recs (low strain across dims)
    healthy = next(p for p in SB_PROFILES
                   if "Healthy" in p["input"].name)
    r = score_individual(healthy["input"])
    sb_action_recs = [rec for rec in (r.recommendations or [])
                      if isinstance(rec, dict) and rec.get("type") == "action"]
    if assert_eq("SB Healthy: no action recs from SB layer",
                 len(sb_action_recs), 0): pp += 1
    else: ff += 1

    # SB Stress Personal Healthy → at least one SB primary
    stress = next(p for p in SB_PROFILES
                  if "Stress Personal Healthy" in p["input"].name)
    r = score_individual(stress["input"])
    sb_recs = [rec for rec in (r.recommendations or [])
               if isinstance(rec, dict) and rec.get("type") == "action"]
    if assert_truthy("SB Stress: at least 1 action rec",
                     len(sb_recs) >= 1): pp += 1
    else: ff += 1
    primaries = [rec for rec in sb_recs if rec.get("priority") == "primary"]
    if assert_eq("SB Stress: exactly 1 primary",
                 len(primaries), 1): pp += 1
    else: ff += 1
    print(f"        SB Stress primary: {primaries[0]['title']!r}")

    # SB Capital Event → multiple SB action recs
    capital = next(p for p in SB_PROFILES
                   if "Capital Event" in p["input"].name)
    r = score_individual(capital["input"])
    sb_recs = [rec for rec in (r.recommendations or [])
               if isinstance(rec, dict) and rec.get("type") == "action"]
    if assert_truthy("SB Capital Event: multiple action recs",
                     len(sb_recs) >= 2): pp += 1
    else: ff += 1
    primaries = [rec for rec in sb_recs if rec.get("priority") == "primary"]
    if assert_eq("SB Capital Event: still exactly 1 primary",
                 len(primaries), 1): pp += 1
    else: ff += 1
    print(f"        SB Capital Event primary: {primaries[0]['title']!r}")
    print(f"        SB Capital Event total recs (incl. legacy): "
          f"{len(r.recommendations)}")

    # ── No regression on Individual archetype ───────────────────────
    print("\nIndividual archetype regression check:")
    from profiles import PROFILES
    avg = PROFILES[2]   # "Average"
    r = score_individual(avg["input"])
    # Individual archetype must NOT receive any new-shape recs (those
    # only fire under SB). Only legacy {action, impact, priority(int),
    # reason} shape.
    sb_shape_recs = [rec for rec in (r.recommendations or [])
                     if isinstance(rec, dict) and "type" in rec]
    if assert_eq("Individual: no SB-shape recs",
                 len(sb_shape_recs), 0): pp += 1
    else: ff += 1
    # Existing legacy recs still produced.
    legacy = [rec for rec in (r.recommendations or [])
              if isinstance(rec, dict) and "action" in rec
              and "type" not in rec]
    if assert_truthy("Individual: legacy recs still produced",
                     len(legacy) > 0): pp += 1
    else: ff += 1

    # ── Brand voice sweep across every generated rec everywhere ─────
    print("\nBrand voice sweep across all SB profile recommendations:")
    swept = 0
    for p in SB_PROFILES:
        r = score_individual(p["input"])
        for rec in (r.recommendations or []):
            if isinstance(rec, dict) and rec.get("type"):
                # New-shape SB rec — runs through audit at construction,
                # but re-audit here to be safe (catches any post-mutation).
                try:
                    audit_brand_voice(rec)
                    swept += 1
                except AssertionError as e:
                    print(f"  FAIL  brand voice violation in "
                          f"{p['input'].name}: {e}")
                    ff += 1
    print(f"  ok    {swept} SB recs swept, all pass brand voice audit")
    pp += 1

    # ── compile_sb_recommendations top-level orchestrator ──────────
    print("\ncompile_sb_recommendations orchestrator:")

    # Data completion suppresses action recs on its surface
    inp = stress["input"]
    r = score_individual(inp)
    mapped_with_missing_ar = {
        "ar_aging_buckets": {"value": None, "confidence": "missing",
                             "source": "manual_entry_required"},
    }
    compiled = compile_sb_recommendations(
        inp, r, mapped_fields_dict=mapped_with_missing_ar,
    )
    # AR-driven action rec must NOT appear when AR is missing.
    ar_action_present = any(
        rec.get("type") == "action"
        and rec.get("context", {}).get("trigger") == "ar_aging_strain"
        for rec in compiled
    )
    if assert_eq("compile: AR action suppressed when AR field missing",
                 ar_action_present, False): pp += 1
    else: ff += 1
    # data_completion present
    dc_present = any(rec.get("type") == "data_completion" for rec in compiled)
    if assert_truthy("compile: data_completion present", dc_present): pp += 1
    else: ff += 1
    # Singular primary across the cascade
    primaries = [r for r in compiled if r["priority"] == "primary"]
    if assert_eq("compile: exactly 1 primary across cascade",
                 len(primaries), 1): pp += 1
    else: ff += 1

    print(f"\n{pp} passed, {ff} failed.")
    return ff == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
