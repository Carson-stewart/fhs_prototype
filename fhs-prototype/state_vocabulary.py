"""
Per-archetype state vocabulary.

The state words ("Steady / Watchful / Tight" for Individual W-2,
"Stable / Tightening / Capital-event needed" for Small Business, etc.)
are the user-facing translation of FHS / FSS / FRS scores per the
information-hierarchy contract:

  1. State (single calm phrase)         ← THIS FILE
  2. Justification (one sentence)
  3. Next move (one specific action)
  4. Why? (collapsed score components, expandable)

See RELIUS_STRATEGY.md §3 / §3.3 / §4.4 and CLAUDE.md §2 / §7.

Maintainer note (single source of truth)
----------------------------------------
When adding a new archetype or modifying state thresholds, update
this file. Do NOT hardcode state strings elsewhere in the codebase.
The `state_for(archetype, fhs, fss, frs)` resolver is the only
supported way to map a score triple to a state.

Trade-secret boundary
---------------------
State thresholds and labels are PUBLIC. They map score outputs to
user-facing language and are explainable per RELIUS_STRATEGY.md §4.4
(score components and direction-of-change are explainable; the LP
formulation is not). Threshold values do NOT trip the
`_assert_no_optimization_internals()` scrubber — they don't include
the forbidden substrings (no "weight", "objective", "slack", etc.) —
and they're consumed at the presentation surface, not the LP boundary.

Threshold-spec grammar
----------------------
Each state's `thresholds` is one of:

  • `{"fallthrough": True}` — always matches (use as the last/middle
    state). Rest of the dict is ignored.
  • `{"any_of": [<clause>, <clause>, ...]}` — at least one clause must
    match. Use for "any single dimension is bad" ⇒ that state.
  • `{"all_of": [<clause>, <clause>, ...]}` — every clause must match.
    Use for "every dimension is good" ⇒ that state.
  • A single clause dict (no any_of/all_of/fallthrough) — short-form
    treated as `all_of: [<clause>]`.

A `<clause>` is a dict with any subset of:
    fhs_min, fhs_max, fss_min, fss_max, frs_min, frs_max
where *_min means "score >= value" and *_max means "score <= value".

States are evaluated in list order. The FIRST matching state wins.
Convention: order worst → best, with the middle state as the
fallthrough catch-all. This keeps "if anything is bad, surface that"
priority intuitive.

Initial calibration values (Phase 5a.1)
---------------------------------------
The thresholds below are INITIAL CALIBRATION, to be refined in 5a.5
once the SB constraint logic and recommendation generation are in
place. Cross-archetype consistency (Stable / Steady use the same
numeric thresholds) is intentional for now — per-archetype tuning
comes after the LP work lands.
"""
from typing import Optional


# ─── Threshold-spec resolver ──────────────────────────────────────────
def _check_clause(clause: dict, fhs: float, fss: float, frs: float) -> bool:
    """True iff every *_min/*_max bound in `clause` is satisfied."""
    if "fhs_min" in clause and not (fhs >= clause["fhs_min"]):
        return False
    if "fhs_max" in clause and not (fhs <= clause["fhs_max"]):
        return False
    if "fss_min" in clause and not (fss >= clause["fss_min"]):
        return False
    if "fss_max" in clause and not (fss <= clause["fss_max"]):
        return False
    if "frs_min" in clause and not (frs >= clause["frs_min"]):
        return False
    if "frs_max" in clause and not (frs <= clause["frs_max"]):
        return False
    return True


def _check_thresholds(spec: dict, fhs: float, fss: float, frs: float) -> bool:
    """Apply the threshold-spec grammar above."""
    if not spec:
        return False
    if spec.get("fallthrough"):
        return True
    if "any_of" in spec:
        return any(_check_clause(c, fhs, fss, frs) for c in spec["any_of"])
    if "all_of" in spec:
        return all(_check_clause(c, fhs, fss, frs) for c in spec["all_of"])
    # Short-form: a single clause dict.
    return _check_clause(spec, fhs, fss, frs)


# ─── Archetype-keyed state vocabulary ─────────────────────────────────
# States are listed worst → best; first match wins. Each state has:
#   key         — stable internal identifier (snake_case)
#   label       — user-facing single-phrase label
#   description — one-sentence plain-language explanation
#   thresholds  — per the grammar in this file's docstring
ARCHETYPE_STATES = {
    # ── Individual W-2 ───────────────────────────────────────────────
    # Vocabulary: Steady / Watchful / Tight per RELIUS_STRATEGY.md §3.3.
    # Migrated here from "informal everywhere" — this file is now the
    # single source of truth.
    "individual_w2": {
        "states": [
            {
                "key": "tight",
                "label": "Tight",
                "description": (
                    "Day-to-day cash flow is squeezed; recovery requires "
                    "a deliberate move."
                ),
                "thresholds": {
                    "any_of": [
                        {"fhs_max": 549},
                        {"fss_min": 61},
                        {"frs_max": 29},
                    ],
                },
            },
            {
                "key": "steady",
                "label": "Steady",
                "description": (
                    "Income covers essentials with room to save and "
                    "recover from a setback."
                ),
                "thresholds": {
                    "all_of": [
                        {"fhs_min": 700},
                        {"fss_max": 30},
                        {"frs_min": 60},
                    ],
                },
            },
            {
                "key": "watchful",
                "label": "Watchful",
                "description": (
                    "Some pressure — a single setback would tighten the "
                    "budget."
                ),
                "thresholds": {"fallthrough": True},
            },
        ],
    },

    # ── Small Business ───────────────────────────────────────────────
    # Vocabulary: Stable / Tightening / Capital-event needed per
    # RELIUS_STRATEGY.md §3.3.
    "small_business": {
        "states": [
            {
                "key": "capital_event_needed",
                "label": "Capital-event needed",
                "description": (
                    "Operating cash flow won't close the gap. Bridge "
                    "financing, owner contribution, or a structural "
                    "change is required."
                ),
                "thresholds": {
                    "any_of": [
                        {"fhs_max": 549},
                        {"fss_min": 61},
                        {"frs_max": 29},
                    ],
                },
            },
            {
                "key": "stable",
                "label": "Stable",
                "description": (
                    "Cash flow covers obligations; AR/AP cycles aren't "
                    "bottlenecking growth."
                ),
                "thresholds": {
                    "all_of": [
                        {"fhs_min": 700},
                        {"fss_max": 30},
                        {"frs_min": 60},
                    ],
                },
            },
            {
                "key": "tightening",
                "label": "Tightening",
                "description": (
                    "AR aging or AP compression is starting to constrain "
                    "options. Manageable with a deliberate move."
                ),
                "thresholds": {"fallthrough": True},
            },
        ],
    },

    # ── Freelancer (Phase 5b.1) ──────────────────────────────────────
    # Vocabulary: Predictable / Lumpy / Famine per RELIUS_STRATEGY.md
    # §3.3.
    #
    # Tone calibration is the most consequential design choice in this
    # entry. "Famine" is a first-class dignified state, not a crisis
    # flag. The user knows their income is light this period; the
    # description must respect that and frame Relius's role as
    # protection of essentials and tax reserve, not advice on getting
    # more work. Brand voice §1.6 applies at the description level.
    #
    # Initial calibration (refined in 5b.5 once 5b.2's volatility +
    # tax-reserve scoring contributions land). The 5b.1 thresholds
    # only consult FHS / FSS / FRS — once 5b.2 surfaces volatility
    # via FSS contribution and tax-reserve via FHS contribution, the
    # state landings will reflect the volatility-with-declining-trajectory
    # and fixed-obligation-coverage triggers from the brief.
    "freelancer": {
        "states": [
            {
                "key": "famine",
                "label": "Famine",
                "description": (
                    "Income is light this period. Relius helps you "
                    "prioritize fixed obligations and protect tax "
                    "reserve while work picks back up."
                ),
                "thresholds": {
                    "any_of": [
                        {"fhs_max": 549},
                        {"fss_min": 61},
                        {"frs_max": 29},
                    ],
                },
            },
            {
                "key": "predictable",
                "label": "Predictable",
                "description": (
                    "Income arrives on a steady cadence with low "
                    "volatility. Tax reserve and emergency fund "
                    "are tracking on plan."
                ),
                "thresholds": {
                    "all_of": [
                        {"fhs_min": 680},
                        {"fss_max": 30},
                        {"frs_min": 60},
                    ],
                },
            },
            {
                "key": "lumpy",
                "label": "Lumpy",
                "description": (
                    "Income is irregular but covering essentials and "
                    "growing reserves over time. Use flush months to "
                    "build buffer for the lean ones."
                ),
                "thresholds": {"fallthrough": True},
            },
        ],
    },

    # ── Startup (stub — populated in Phase 5d) ───────────────────────
    # Placeholder labels. Vocabulary per RELIUS_STRATEGY.md §3.3 is
    # "Runway / Tight runway / Out-of-runway"; thresholds need
    # burn-rate / months-of-runway tuning that depends on the runway
    # model arriving in 5d.
    "startup": {
        "states": [
            {
                "key": "out_of_runway",
                "label": "Out-of-runway",
                "description": "Phase 5d stub. To be calibrated.",
                "thresholds": {
                    "any_of": [
                        {"fhs_max": 549},
                        {"fss_min": 61},
                        {"frs_max": 29},
                    ],
                },
            },
            {
                "key": "runway",
                "label": "Runway",
                "description": "Phase 5d stub. To be calibrated.",
                "thresholds": {
                    "all_of": [
                        {"fhs_min": 700},
                        {"fss_max": 30},
                        {"frs_min": 60},
                    ],
                },
            },
            {
                "key": "tight_runway",
                "label": "Tight runway",
                "description": "Phase 5d stub. To be calibrated.",
                "thresholds": {"fallthrough": True},
            },
        ],
    },
}


def state_for(archetype: str, fhs: float, fss: float, frs: float) -> dict:
    """Resolve a (archetype, FHS, FSS, FRS) tuple to a state dict.

    Returns a dict with keys: `key`, `label`, `description`, `thresholds`.
    On unknown archetype, returns a safe default with `key="unknown"`.
    On a known archetype where no state matches (shouldn't happen if a
    `fallthrough` state is present), returns the LAST state in the list
    as a defensive fall-back.

    This is the ONLY supported way to translate scores into the
    user-facing state vocabulary. Do not bypass.
    """
    arch = ARCHETYPE_STATES.get(archetype)
    if not arch:
        return {
            "key": "unknown",
            "label": "Unknown",
            "description": (
                f"No state vocabulary registered for archetype "
                f"{archetype!r}. Add an entry to "
                f"state_vocabulary.ARCHETYPE_STATES."
            ),
            "thresholds": {},
        }
    states = arch.get("states") or []
    for s in states:
        if _check_thresholds(s.get("thresholds") or {}, fhs, fss, frs):
            return s
    return states[-1] if states else {
        "key": "unknown", "label": "Unknown", "description": "", "thresholds": {},
    }


def known_archetypes() -> list:
    """List of archetype keys with state vocabulary registered."""
    return list(ARCHETYPE_STATES.keys())
