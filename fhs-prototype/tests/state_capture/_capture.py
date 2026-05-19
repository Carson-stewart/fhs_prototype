"""Capture programmatic snapshot of engine + rec output for FL profiles.

Used by Pass 2 work item to verify plan-card unification doesn't regress
the recommendations payload at the data layer. Renderer-only changes
should produce IDENTICAL data layer; the user-visible delta is the
suppression of duplicates at render time.

Usage:
    python tests/state_capture/_capture.py before_pass2
    python tests/state_capture/_capture.py after_pass2
"""
import json
import os
import sys

# Repo root on sys.path
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from profiles import FREELANCER_PROFILES  # noqa: E402
from engine import score_individual, score_to_dict  # noqa: E402


def slim(rec):
    """Compact representation of a single rec card for diffing."""
    if not isinstance(rec, dict):
        return repr(rec)
    if "title" in rec:  # new shape
        return {
            "shape": "new",
            "type": rec.get("type"),
            "priority": rec.get("priority"),
            "confidence": rec.get("confidence"),
            "title": rec.get("title"),
            "body": rec.get("body"),
            "next_move": rec.get("next_move"),
            "trigger": (rec.get("context") or {}).get("trigger"),
        }
    return {
        "shape": "legacy",
        "priority": rec.get("priority"),
        "impact": rec.get("impact"),
        "action": rec.get("action"),
        "reason": rec.get("reason"),
        "phases_count": len(rec.get("phases", []) or []),
    }


def capture_one(label, inp):
    r = score_individual(inp)
    d = score_to_dict(r)
    plan = d.get("plan") or {}
    return {
        "label": label,
        "scores": {"fhs": d.get("fhs"), "fss": d.get("fss"), "frs": d.get("frs")},
        "frs_band": d.get("frs_band"),
        "plan": {
            "phases_count": len(plan.get("plan_phases", []) or []),
            "plan_phases": plan.get("plan_phases", []),
            "allocation_plan_keys": list((plan.get("allocation_plan") or {}).keys())
                if isinstance(plan.get("allocation_plan"), dict)
                else [type(plan.get("allocation_plan")).__name__],
            "state_trajectory_len": len(plan.get("state_trajectory", []) or []),
        },
        "optimal_allocation": d.get("optimal_allocation") or {},
        "trajectory_unique": sorted(set(d.get("trajectory") or [])),
        "recommendations": [slim(r) for r in (d.get("recommendations") or [])],
        "recommendations_count": len(d.get("recommendations") or []),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python _capture.py [before_pass2|after_pass2]")
        sys.exit(1)
    target = sys.argv[1]
    out_dir = os.path.join(HERE, target)
    os.makedirs(out_dir, exist_ok=True)

    for i, p in enumerate(FREELANCER_PROFILES, start=1):
        inp = p["input"]
        label = f"fl{i}"
        snap = capture_one(label, inp)
        path = os.path.join(out_dir, f"{label}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, indent=2, default=str)
        print(f"  wrote {path}  recs={snap['recommendations_count']}  phases={snap['plan']['phases_count']}")

    # fl9 = fl1 input + 2 Plaid banks state. At engine/recs layer, identical
    # to fl1 (the multi-bank-ness is a frontend Plaid integration state, not
    # an engine input divergence). Captured anyway so before/after diff shows
    # data-layer parity.
    snap = capture_one("fl9", FREELANCER_PROFILES[0]["input"])
    snap["note"] = "fl9 captured as fl1-equivalent at engine layer; multi-bank state is frontend-only."
    path = os.path.join(out_dir, "fl9.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2, default=str)
    print(f"  wrote {path}  (fl9 = fl1-equivalent)")


if __name__ == "__main__":
    main()
