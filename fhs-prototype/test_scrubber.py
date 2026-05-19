"""Trade-secret scrubber tests.

Mirrors the existing pure-test convention (test_mapper.py / test_runner.py):
no FastAPI test client, no live server. Imports the scrubber function
directly and exercises it against synthetic payloads, plus runs the
real engine output through it to confirm whether any current API
response trips the tripwire (per the P4 §11.1 spec).

Run with:
    python test_scrubber.py
"""
from api import (
    _assert_no_optimization_internals,
    _assert_no_access_token,
    _FORBIDDEN_OPTIMIZATION_INTERNALS,
)


def assert_eq(label, actual, expected):
    if actual != expected:
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")
        return False
    print(f"  ok    {label}")
    return True


def assert_raises(label, exc_type, fn):
    try:
        fn()
    except exc_type as e:
        print(f"  ok    {label}  (raised {exc_type.__name__}: {str(e)[:120]})")
        return True
    except Exception as e:
        print(f"  FAIL  {label}: expected {exc_type.__name__}, got "
              f"{type(e).__name__}: {e}")
        return False
    print(f"  FAIL  {label}: expected {exc_type.__name__}, no exception raised")
    return False


def assert_does_not_raise(label, fn):
    try:
        fn()
    except Exception as e:
        print(f"  FAIL  {label}: unexpected {type(e).__name__}: {e}")
        return False
    print(f"  ok    {label}")
    return True


def run():
    pass_count = fail_count = 0

    # ── Test 1 — clean response, no error ────────────────────────────
    print("Test 1 — clean response (no forbidden keys):")
    clean = {
        "scores": {"fhs": 720, "fss": 25, "frs": 60},
        "confidence": "high",
        "archetype": "Average",
        "recommendations": [
            {"priority": "high", "next_move": "Build emergency fund"},
        ],
        "meta": {"solver": "multiperiod", "infeasible": False},
    }
    if assert_does_not_raise("clean dict passes",
                             lambda: _assert_no_optimization_internals(clean)):
        pass_count += 1
    else:
        fail_count += 1

    # ── Test 2 — forbidden top-level field raises ────────────────────
    print("\nTest 2 — forbidden top-level field raises AssertionError:")
    leaky_top = {"score": 720, "weight": 0.18}
    if assert_raises("top-level 'weight' raises AssertionError",
                     AssertionError,
                     lambda: _assert_no_optimization_internals(leaky_top)):
        pass_count += 1
    else:
        fail_count += 1

    leaky_top2 = {"objective_value": 3.5}
    if assert_raises("top-level 'objective_value' raises",
                     AssertionError,
                     lambda: _assert_no_optimization_internals(leaky_top2)):
        pass_count += 1
    else:
        fail_count += 1

    # ── Test 3 — forbidden nested field raises (recursion) ───────────
    print("\nTest 3 — forbidden nested field raises (recursion):")
    nested = {
        "scores": {"fhs": 720},
        "breakdowns": {
            "fhs": {
                "Emergency fund": {"value": 3.2, "weight": 0.18, "score": 0.5},
            },
        },
    }
    if assert_raises("nested 'weight' raises AssertionError",
                     AssertionError,
                     lambda: _assert_no_optimization_internals(nested)):
        pass_count += 1
    else:
        fail_count += 1

    deeply_nested = {"a": {"b": {"c": [{"d": {"slack": 0.0}}]}}}
    if assert_raises("deeply-nested through list 'slack' raises",
                     AssertionError,
                     lambda: _assert_no_optimization_internals(deeply_nested)):
        pass_count += 1
    else:
        fail_count += 1

    # ── Test 4 — allowed fields with superficial substring matches ───
    # If any of these trips, that's a finding to report (not suppress).
    print("\nTest 4 — allowed fields don't trip:")
    allowed = {
        "score": 720,                       # NOT a substring of any forbidden token
        "fhs_score": 720,
        "confidence": "high",
        "archetype": "Average",
        "recommendation": {"priority": "high"},
        "next_move": "Build emergency fund",
        "momentum_slope": 0.1,              # contains "slope" but NOT "slack"
        "lp_status": "Optimal",             # status string, not internal state
        "objective": 3.5,                   # NOT a substring of any forbidden token
        "solver": "multiperiod",            # public-surface label
        # Edge case: a label containing "constraint" should NOT trip because
        # `constraint` is intentionally NOT in the forbidden list.
        "constraint_count": 12,
    }
    if assert_does_not_raise("'score', 'momentum_slope', 'objective', etc. don't trip",
                             lambda: _assert_no_optimization_internals(allowed)):
        pass_count += 1
    else:
        fail_count += 1

    # Substring match is case-insensitive.
    print("\n   (case-insensitive coverage)")
    if assert_raises("uppercase 'WEIGHT' still trips", AssertionError,
                     lambda: _assert_no_optimization_internals({"WEIGHT": 0.5})):
        pass_count += 1
    else:
        fail_count += 1
    if assert_raises("mixed-case 'Weighted' still trips", AssertionError,
                     lambda: _assert_no_optimization_internals({"Weighted": 0.5})):
        pass_count += 1
    else:
        fail_count += 1

    # The access-token scrubber should still work — sanity check that
    # adding the new scrubber didn't break the original.
    print("\n   (access-token scrubber still works)")
    if assert_raises("'access_token' raises RuntimeError", RuntimeError,
                     lambda: _assert_no_access_token({"access_token": "secret"})):
        pass_count += 1
    else:
        fail_count += 1

    # ── Test 5 — real engine output (current API responses) ─────────
    # This is the live tripwire — runs the actual scoring pipeline used
    # by /api/score and walks every response field. Per the P4 §11.1
    # spec: if anything trips, that's a finding to report, not suppress.
    print("\nTest 5 — real engine output through scrubber (tripwire):")
    findings = []

    from engine import score_individual, score_to_dict
    from profiles import PROFILES
    for p in PROFILES:
        result = score_individual(p["input"])
        response = score_to_dict(result)
        try:
            _assert_no_optimization_internals(response)
            print(f"  ok    {p['input'].name}: clean")
        except AssertionError as e:
            msg = str(e)
            print(f"  FAIL  {p['input'].name}: {msg[:200]}")
            findings.append((p["input"].name, msg))

    # Also exercise the /api/profile/{idx} surface (uses result_to_dict).
    from api import result_to_dict
    for p in PROFILES[:1]:   # one profile is enough — same shape across all
        result = score_individual(p["input"])
        response = result_to_dict(result)
        try:
            _assert_no_optimization_internals(response)
            print(f"  ok    /api/profile result_to_dict({p['input'].name}): clean")
        except AssertionError as e:
            msg = str(e)
            print(f"  FAIL  /api/profile result_to_dict({p['input'].name}): {msg[:200]}")
            findings.append((f"result_to_dict({p['input'].name})", msg))

    if findings:
        # Findings — report and fail loud.
        print(f"\n  FINDINGS ({len(findings)} surface(s) trip the scrubber):")
        for name, msg in findings:
            print(f"    - {name}: {msg}")
        fail_count += 1
    else:
        pass_count += 1
        print("  ok    no findings — every score response is scrubber-clean")

    print(f"\n{pass_count} passed, {fail_count} failed.")
    print(f"Forbidden tokens in matcher: {_FORBIDDEN_OPTIMIZATION_INTERNALS}")
    return fail_count == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
