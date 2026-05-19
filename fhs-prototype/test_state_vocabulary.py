"""Tests for state_vocabulary — the per-archetype state resolver.

Mirrors the existing pure-test convention (test_mapper.py /
test_runner.py / test_scrubber.py): no FastAPI test client, no live
server. Imports the resolver directly and exercises it against
synthetic score triples plus the new SB_PROFILES from profiles.py.

Run with:
    python test_state_vocabulary.py
"""
from state_vocabulary import (
    state_for, known_archetypes, ARCHETYPE_STATES,
    _check_clause, _check_thresholds,
)


def assert_eq(label, actual, expected):
    if actual != expected:
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")
        return False
    print(f"  ok    {label}")
    return True


def run():
    pass_count = fail_count = 0

    # ── Clause-level grammar ─────────────────────────────────────────
    print("Clause grammar:")
    if assert_eq("fhs_min satisfied",
                 _check_clause({"fhs_min": 700}, 720, 0, 0), True):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("fhs_min not satisfied",
                 _check_clause({"fhs_min": 700}, 699, 0, 0), False):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("fss_max satisfied",
                 _check_clause({"fss_max": 30}, 0, 25, 0), True):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("fss_max not satisfied",
                 _check_clause({"fss_max": 30}, 0, 31, 0), False):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("multiple bounds in single clause (all must hold)",
                 _check_clause({"fhs_min": 700, "fss_max": 30}, 720, 25, 0), True):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("multiple bounds in single clause (one fails -> False)",
                 _check_clause({"fhs_min": 700, "fss_max": 30}, 720, 35, 0), False):
        pass_count += 1
    else: fail_count += 1

    # ── Threshold-spec grammar ───────────────────────────────────────
    print("\nThreshold-spec grammar:")
    fallthrough = {"fallthrough": True}
    if assert_eq("fallthrough always matches",
                 _check_thresholds(fallthrough, 0, 100, 0), True):
        pass_count += 1
    else: fail_count += 1

    any_of = {"any_of": [{"fhs_max": 549}, {"fss_min": 61}]}
    if assert_eq("any_of: first clause matches",
                 _check_thresholds(any_of, 500, 0, 0), True):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("any_of: second clause matches",
                 _check_thresholds(any_of, 800, 70, 0), True):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("any_of: neither matches",
                 _check_thresholds(any_of, 800, 20, 0), False):
        pass_count += 1
    else: fail_count += 1

    all_of = {"all_of": [{"fhs_min": 700}, {"fss_max": 30}, {"frs_min": 60}]}
    if assert_eq("all_of: all three match",
                 _check_thresholds(all_of, 720, 25, 65), True):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("all_of: one fails -> False",
                 _check_thresholds(all_of, 720, 25, 50), False):
        pass_count += 1
    else: fail_count += 1

    # ── Individual W-2 — Steady / Watchful / Tight ───────────────────
    print("\nIndividual W-2 state resolution:")
    s = state_for("individual_w2", 720, 25, 70)
    if assert_eq("(720, 25, 70) -> steady", s["key"], "steady"):
        pass_count += 1
    else: fail_count += 1
    s = state_for("individual_w2", 600, 40, 50)
    if assert_eq("(600, 40, 50) -> watchful (fallthrough)", s["key"], "watchful"):
        pass_count += 1
    else: fail_count += 1
    s = state_for("individual_w2", 480, 80, 25)
    if assert_eq("(480, 80, 25) -> tight (any_of)", s["key"], "tight"):
        pass_count += 1
    else: fail_count += 1
    # Worst-state-wins priority: only one dimension bad still triggers tight.
    s = state_for("individual_w2", 720, 25, 25)   # FRS bad
    if assert_eq("(720, 25, 25 — FRS bad) -> tight", s["key"], "tight"):
        pass_count += 1
    else: fail_count += 1

    # ── Small Business — Stable / Tightening / Capital-event ─────────
    print("\nSmall Business state resolution:")
    s = state_for("small_business", 720, 25, 70)
    if assert_eq("(720, 25, 70) -> stable", s["key"], "stable"):
        pass_count += 1
    else: fail_count += 1
    s = state_for("small_business", 600, 40, 50)
    if assert_eq("(600, 40, 50) -> tightening (fallthrough)",
                 s["key"], "tightening"):
        pass_count += 1
    else: fail_count += 1
    s = state_for("small_business", 480, 80, 25)
    if assert_eq("(480, 80, 25) -> capital_event_needed",
                 s["key"], "capital_event_needed"):
        pass_count += 1
    else: fail_count += 1

    # Boundary checks: exactly on the threshold should match the strict side.
    s = state_for("small_business", 700, 30, 60)
    if assert_eq("(700, 30, 60) — exact boundary -> stable",
                 s["key"], "stable"):
        pass_count += 1
    else: fail_count += 1
    s = state_for("small_business", 549, 25, 70)
    if assert_eq("(549, 25, 70) — FHS at capital boundary -> capital_event_needed",
                 s["key"], "capital_event_needed"):
        pass_count += 1
    else: fail_count += 1

    # ── Stub archetypes (Freelancer, Startup) ────────────────────────
    print("\nStub archetypes (Freelancer, Startup) — registered with placeholders:")
    for arch in ("freelancer", "startup"):
        s = state_for(arch, 720, 25, 70)
        if s["label"] != "Unknown" and s["label"] != "":
            print(f"  ok    {arch} resolves to {s['key']!r} / {s['label']!r}")
            pass_count += 1
        else:
            print(f"  FAIL  {arch} did not resolve: {s}")
            fail_count += 1

    # Unknown archetype returns the safe-default with key="unknown".
    print("\nUnknown archetype:")
    s = state_for("nonexistent_archetype", 720, 25, 70)
    if assert_eq("unknown archetype -> 'unknown' key", s["key"], "unknown"):
        pass_count += 1
    else: fail_count += 1

    # ── known_archetypes() reports the registered set ────────────────
    archs = set(known_archetypes())
    expected_archs = {"individual_w2", "small_business", "freelancer", "startup"}
    if assert_eq("known_archetypes covers all four", archs, expected_archs):
        pass_count += 1
    else: fail_count += 1

    # ── SB_PROFILES land in their declared expected_state ────────────
    # Also verify FHS / FSS / state-landing match expected ranges.
    # Two state-assertion modes supported:
    #   • `expected_state` — exact-key match
    #   • `expected_state_not` — must NOT be this key (use for the
    #     5a.2 mission-critical "must not be stable" profile where
    #     calibration determines whether tightening or capital_event_needed
    #     is the cleaner landing)
    print("\nSB_PROFILES live state-landing check:")
    from engine import score_individual
    from profiles import SB_PROFILES
    for p in SB_PROFILES:
        inp = p["input"]
        r = score_individual(inp)
        fhs_ok = p["expected_fhs"][0] <= r.fhs <= p["expected_fhs"][1]
        fss_ok = p["expected_fss"][0] <= r.fss <= p["expected_fss"][1]
        state = state_for("small_business", r.fhs, r.fss, r.frs)
        if "expected_state" in p:
            state_ok = state["key"] == p["expected_state"]
            expected_str = repr(p["expected_state"])
        elif "expected_state_not" in p:
            state_ok = state["key"] != p["expected_state_not"]
            expected_str = f"NOT {p['expected_state_not']!r}"
        else:
            state_ok = True
            expected_str = "(no state assertion)"

        line = (f"  {inp.name}: FHS={r.fhs} FSS={r.fss} FRS={r.frs} "
                f"state={state['key']!r}")
        all_ok = fhs_ok and fss_ok and state_ok
        if all_ok:
            print(f"  ok    {line}")
            pass_count += 1
        else:
            print(f"  FAIL  {line}")
            print(f"        expected_fhs={p['expected_fhs']}, fhs_ok={fhs_ok}")
            print(f"        expected_fss={p['expected_fss']}, fss_ok={fss_ok}")
            print(f"        expected_state={expected_str}, state_ok={state_ok}")
            fail_count += 1

    print(f"\n{pass_count} passed, {fail_count} failed.")
    return fail_count == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
