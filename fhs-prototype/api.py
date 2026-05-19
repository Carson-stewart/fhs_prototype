"""
Financial Health Scoring Engine — API Server
FastAPI backend + HTML form frontend
"""
# CRITICAL: load_dotenv must run before any module that reads PLAID_* env vars.
# plaid_client reads them at import time, so loading here ensures the .env
# values are present before that import resolves.
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, Annotated
import json

from engine import IndividualInput, score_individual, ScoreResult, score_to_dict, fhs_band, fss_band, frs_band
from profiles import PROFILES
from history import init_db, get_user_state, record_score, get_score_history, compute_fingerprint, history_interpretation

import os
import logging
logger = logging.getLogger("fhs")

app = FastAPI(title="Financial Health Scoring Engine", version="0.1.0")
init_db()
# Plaid token storage table — same SQLite file, idempotent.
import plaid_storage
plaid_storage.init_db()

import time as _time
_startup_time = _time.time()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _user_id(x_user_id: Annotated[Optional[str], Header()] = None) -> str:
    """Use the client-supplied ID or fall back to 'anonymous'."""
    uid = (x_user_id or "").strip()
    return uid if uid else "anonymous"


class ScoreRequest(BaseModel):
    I_gross: float = Field(..., ge=0, le=1_000_000)
    I_net:   float = Field(..., ge=0, le=1_000_000)
    E_ess:   float = Field(..., ge=0, le=500_000)
    E_house: float = Field(..., ge=0, le=500_000)
    D_min:   float = Field(..., ge=0, le=100_000)
    D_hi:    float = Field(0,   ge=0, le=10_000_000)
    D_lo:    float = Field(0,   ge=0, le=10_000_000)
    S_liq:   float = Field(0,   ge=0, le=100_000_000)
    S_ret:   float = Field(0,   ge=0, le=100_000_000)
    age:     int   = Field(18,  ge=18, le=85)
    has_life_insurance:       bool = False
    has_disability_insurance: bool = False
    overdraft_count_90d:    int = Field(0, ge=0, le=999)
    late_payment_count_90d: int = Field(0, ge=0, le=999)
    momentum_slope: float = Field(0.0, ge=-1.0, le=1.0)
    streak_days:    int   = Field(0,   ge=0, le=3650)
    name:           str   = Field("User", max_length=100)
    previous:       Optional[dict] = None
    use_multiperiod: bool = True
    dependents:     int  = Field(0, ge=0, le=20)
    retired:        bool = False


class PreviousSnapshotRequest(BaseModel):
    # Current state — same required fields as ScoreRequest
    I_gross: float = Field(..., ge=0, le=1_000_000)
    I_net:   float = Field(..., ge=0, le=1_000_000)
    E_ess:   float = Field(..., ge=0, le=500_000)
    E_house: float = Field(..., ge=0, le=500_000)
    D_min:   float = Field(..., ge=0, le=100_000)
    D_hi:    float = Field(0,   ge=0, le=10_000_000)
    D_lo:    float = Field(0,   ge=0, le=10_000_000)
    S_liq:   float = Field(0,   ge=0, le=100_000_000)
    S_ret:   float = Field(0,   ge=0, le=100_000_000)
    age:     int   = Field(18,  ge=18, le=85)
    has_life_insurance:       bool = False
    has_disability_insurance: bool = False
    overdraft_count_90d:    int = Field(0, ge=0, le=999)
    late_payment_count_90d: int = Field(0, ge=0, le=999)
    momentum_slope: float = Field(0.0, ge=-1.0, le=1.0)
    streak_days:    int   = Field(0,   ge=0, le=3650)
    name:           str   = Field("User", max_length=100)
    use_multiperiod: bool = True
    dependents:     int  = Field(0, ge=0, le=20)
    retired:        bool = False
    # 30-day snapshot — all optional, falls back to current value if omitted
    prev_S_liq:   Optional[float] = Field(None, ge=0, le=100_000_000)
    prev_S_ret:   Optional[float] = Field(None, ge=0, le=100_000_000)
    prev_D_hi:    Optional[float] = Field(None, ge=0, le=10_000_000)
    prev_D_lo:    Optional[float] = Field(None, ge=0, le=10_000_000)
    prev_E_ess:   Optional[float] = Field(None, ge=0, le=500_000)
    prev_I_gross: Optional[float] = Field(None, ge=0, le=1_000_000)
    prev_has_life_insurance:       Optional[bool] = None
    prev_has_disability_insurance: Optional[bool] = None
    prev_overdraft_count_90d:    Optional[int] = Field(None, ge=0, le=999)
    prev_late_payment_count_90d: Optional[int] = Field(None, ge=0, le=999)


def result_to_dict(r: ScoreResult) -> dict:
    """Convert ScoreResult to JSON-serializable dict.

    Trade-secret boundary (CLAUDE.md §7 / §11.1): the breakdown dicts
    carry internal LP/MILP weights and weighted values. The shared
    helper `engine._scrub_breakdowns_for_api` strips those and adds a
    public-facing `contribution_pct` per dimension where appropriate.
    See that function's docstring for the full strip taxonomy and
    rationale.

    The `_assert_no_optimization_internals` scrubber at every endpoint
    return path is the runtime tripwire that catches drift; this
    function is the design-time discipline that keeps the contract
    clean. Both `score_to_dict` (engine.py) and this function call the
    same helper so the boundary contract is identical.
    """
    from engine import _scrub_breakdowns_for_api

    d = {
        "fhs": r.fhs,
        "fss": r.fss,
        "frs": r.frs,
        "fhs_band": fhs_band(r.fhs),
        "fss_band": fss_band(r.fss),
        "frs_band": frs_band(r.frs),
        "infeasible": r.infeasible,
        "infeasibility_reason": r.infeasibility_reason,
        "fhs_breakdown": r.fhs_breakdown,
        "fss_breakdown": r.fss_breakdown,
        "frs_breakdown": r.frs_breakdown,
        "optimal_allocation": r.optimal_allocation,
        "actual_vs_optimal": r.actual_vs_optimal,
        "recommendations": r.recommendations,
        "insights": r.insights,
        "trajectory": r.trajectory,
        "allocation_plan":  r.allocation_plan,
        "state_trajectory": r.state_trajectory,
        "plan_phases":      r.plan_phases,
        "lp_solver": "multiperiod" if r.state_trajectory else "single_period",
        "income_shortfall": r.income_shortfall,
    }
    if r.lp_solution:
        d["lp_status"] = r.lp_solution.status
        # Keep lp_status (useful for debugging infeasible cases).
        # Do NOT expose lp_objective — implies internal weight structure.

    # Trade-secret strip — see _scrub_breakdowns_for_api docstring.
    _scrub_breakdowns_for_api(d)

    return d


@app.post("/plaid/link-token")
async def create_link_token(request: Request):
    """Mint a short-lived Plaid Link token for the frontend.

    The token is what the Plaid Link JS SDK needs to open its modal. It's
    ephemeral (4h) but still credential-grade — never log it at INFO level
    and never return it through anything other than this dedicated endpoint.
    """
    # Late imports keep the existing scoring pipeline runnable without
    # Plaid configured (test_runner.py never calls this route).
    import uuid
    import plaid as _plaid
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.products import Products
    from plaid.model.country_code import CountryCode
    from plaid_client import get_client

    user_id = request.headers.get("x-user-id") or str(uuid.uuid4())

    try:
        client = get_client()
        plaid_req = LinkTokenCreateRequest(
            client_name="Innovera FHS",
            # Request all three product groups now even though P4-1 only opens
            # the Link modal — Sandbox isn't billed per product, and asking
            # later would force the user to reconnect.
            products=[
                Products("transactions"),
                Products("liabilities"),
                Products("investments"),
            ],
            country_codes=[CountryCode("US")],
            language="en",
            user=LinkTokenCreateRequestUser(client_user_id=str(uuid.uuid4())),
        )
        resp = client.link_token_create(plaid_req)
        # `expiration` is a datetime — coerce to ISO 8601 string for JSON.
        expiration = resp["expiration"]
        if hasattr(expiration, "isoformat"):
            expiration = expiration.isoformat()
        return _scrubbed_response({
            "link_token": resp["link_token"],
            "expiration": expiration,
        })
    except _plaid.ApiException:
        # Plaid raw responses can leak internal field names / institution IDs;
        # log fully server-side, return a clean error to the client.
        logger.exception("Plaid link_token_create failed for user %s", user_id)
        return JSONResponse(
            status_code=502,
            content={"error": "Could not create Plaid link token. Please try again."},
        )
    except RuntimeError as exc:
        # Missing credentials (clear startup error from plaid_client.get_client).
        logger.error("Plaid not configured: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": "Bank connection is not configured on this server."},
        )


# ─────────────────────────────────────────────────────────────────────
# Plaid token-exchange + data-fetch endpoints
# ─────────────────────────────────────────────────────────────────────

class _PlaidInstitution(BaseModel):
    name: Optional[str] = None
    institution_id: Optional[str] = None


class PlaidExchangeRequest(BaseModel):
    public_token: str = Field(..., min_length=10, max_length=200)
    institution: Optional[_PlaidInstitution] = None
    session_id:  Optional[str] = Field(None, min_length=8, max_length=200)


class PlaidFetchRequest(BaseModel):
    # Either field may be present; session_id is preferred (multi-bank).
    # item_id stays as a fallback for in-flight tabs from before P4-4.
    item_id:    Optional[str] = Field(None, min_length=1, max_length=200)
    session_id: Optional[str] = Field(None, min_length=8, max_length=200)
    # Phase 5a.5: archetype routes mapper behavior (business CC inclusion,
    # business depository in S_liq). Defaults to "individual_w2" when
    # absent — preserves all pre-Phase-5a callers.
    archetype:  Optional[str] = Field(None, min_length=1, max_length=50)


def _assert_no_access_token(payload, path="$") -> None:
    """Defensive scrub: walk the response tree and fail loudly if an
    `access_token` key surfaces anywhere. Plaid responses don't include
    it but a bug somewhere in this app could — we want a 500 here, not
    a quiet credential leak."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k == "access_token":
                raise RuntimeError(
                    f"access_token leaked at {path} — refusing to send response"
                )
            _assert_no_access_token(v, f"{path}.{k}")
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            _assert_no_access_token(v, f"{path}[{i}]")


# ─── Trade-secret scrubber (CLAUDE.md §11.1) ─────────────────────────
# Forbidden-substring tokens, case-insensitive substring match against
# each key name. Mirrors the access-token scrubber pattern: structural
# walk, no content inspection.
#
# `solver_status` is intentionally NOT in this list — the legacy
# `lp_status` field carries "Optimal" / "Infeasible" (a public-surface
# label, useful for explaining infeasibility), and `meta.solver` carries
# "single_period" / "multiperiod" (also public). Add `solver_status` if
# raw CBC state is ever surfaced.
#
# `constraint` / `constraints` are intentionally NOT in this list —
# the substring matcher can't distinguish a count metadata field
# ("constraint_count": 12) from a matrix payload. If any future endpoint
# surfaces a coefficient or RHS matrix, add the specific key here.
_FORBIDDEN_OPTIMIZATION_INTERNALS = (
    "weight",                    # also catches "weights", "weighted", "weighted_closure"
    "objective_value", "objective_val", "obj_val",
    "solver_state",
    "lp_formulation", "milp_formulation",
    "dual_value", "reduced_cost",
    "slack",
    "coefficient_matrix", "bound_matrix",
    "internal_score_components",
)


def _assert_no_optimization_internals(payload, path="$") -> None:
    """Defensive scrub: walk the response tree and raise AssertionError
    if any key matches an internal LP/MILP optimization token (weights,
    objective values, solver state, coefficient/bound matrices, ...).

    Per the architectural-constants contract (CLAUDE.md §11 / §7), the
    LP optimizer is a trade secret — internal weights, objective values,
    and constraint matrices must never reach an API consumer. This is a
    development-time tripwire designed to fail loud: AssertionError, not
    log-and-continue, not silent strip.

    Mirrors `_assert_no_access_token` exactly: same module, recursive
    walk, applied at every endpoint return path. Matching is
    case-insensitive substring on the key name (not value) — chosen
    because the trade-secret signal is structural, and a substring
    matcher catches drift where someone introduces a new `weight_v2`
    field without thinking about the boundary.
    """
    if isinstance(payload, dict):
        for k, v in payload.items():
            kl = str(k).lower()
            for tok in _FORBIDDEN_OPTIMIZATION_INTERNALS:
                if tok in kl:
                    raise AssertionError(
                        f"optimization internal {k!r} (matches forbidden "
                        f"substring {tok!r}) leaked at {path} — "
                        f"refusing to send response"
                    )
            _assert_no_optimization_internals(v, f"{path}.{k}")
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            _assert_no_optimization_internals(v, f"{path}[{i}]")


def _augment_recommendations_from_inp(response: dict, inp) -> None:
    """Phase 5a.5: augment a /api/score response with cross-archetype
    recommendations derivable from IndividualInput alone (no mapper
    context required).

    Generates:
      • data_completion — for SB archetype with empty AR/AP fields.
        These prepend to the recommendations list (priority="primary"),
        and per the recommendations module's cascade rule, demote any
        existing primary action recs to secondary on a downstream merge.
      • archetype_suggestion — when archetype != "small_business" but
        SB-specific fields are populated (heuristic: business_lines_of_credit
        non-empty, or business_structure set). Surfaced as secondary.

    `detection_override` requires per-account data which IndividualInput
    doesn't carry; it surfaces only via /plaid/map.

    Mutates `response["recommendations"]` in place; safe no-op if the
    inp signals don't match.
    """
    from recommendations import (
        generate_data_completion_recommendations,
        generate_archetype_suggestion,
    )
    archetype = getattr(inp, "archetype", "individual_w2")
    new_recs: list = []

    # Synthesize a minimal mapper-shape dict from inp so the data-
    # completion generator's existing logic can fire. AR / AP empty
    # dict means "user hasn't filled this in", which IS the manual-
    # entry-required state — surface a data_completion card.
    if archetype == "small_business":
        synthetic_mapped = {}
        if not getattr(inp, "ar_aging_buckets", None):
            synthetic_mapped["ar_aging_buckets"] = {
                "value": None, "confidence": "missing",
                "source": "manual_entry_required",
            }
        if not getattr(inp, "ap_pending", None):
            synthetic_mapped["ap_pending"] = {
                "value": None, "confidence": "missing",
                "source": "manual_entry_required",
            }
        if synthetic_mapped:
            new_recs.extend(
                generate_data_completion_recommendations(synthetic_mapped)
            )

    # Archetype suggestion — heuristic: non-SB archetype with at least
    # one populated business field signals possible mis-archetype.
    if archetype != "small_business":
        biz_signals = []
        if getattr(inp, "business_lines_of_credit", None):
            for L in inp.business_lines_of_credit:
                name = (L or {}).get("name")
                if name:
                    biz_signals.append(name)
        if not biz_signals and getattr(inp, "business_structure", None):
            # User explicitly set a business structure but archetype is
            # personal — generic anchor name since we have no account list.
            biz_signals.append("a connected business account")
        sug = generate_archetype_suggestion(biz_signals, archetype)
        if sug is not None:
            new_recs.append(sug)

    if not new_recs:
        return

    existing = response.get("recommendations") or []
    # If we're prepending a data_completion (always primary), demote
    # any existing primary in the legacy / SB action stack to secondary.
    has_new_primary = any(r.get("priority") == "primary" for r in new_recs)
    if has_new_primary:
        for r in existing:
            if isinstance(r, dict):
                # New-shape SB rec: priority is "primary" / "secondary" string
                if r.get("priority") == "primary":
                    r["priority"] = "secondary"
                # Legacy shape: priority is integer 1, 2, 3
                elif r.get("priority") == 1:
                    r["priority"] = 2

    response["recommendations"] = new_recs + existing


def _scrubbed_response(content, status_code: int = 200) -> JSONResponse:
    """Build a JSONResponse after running both scrubbers. If either
    tripwire fires, return a 500 with no internals leaked — same pattern
    `_assert_no_access_token` uses at /plaid/fetch and /plaid/map.
    Centralizing here keeps the scrub call out of every route body.
    """
    try:
        _assert_no_access_token(content)
        _assert_no_optimization_internals(content)
    except (RuntimeError, AssertionError):
        logger.exception(
            "response scrubber tripped — refusing to send response"
        )
        return JSONResponse(
            status_code=500,
            content={"error": "Internal serialization error; please retry."},
        )
    return JSONResponse(status_code=status_code, content=content)


@app.post("/plaid/exchange")
async def plaid_exchange(req: PlaidExchangeRequest, request: Request):
    """Exchange a Plaid Link public_token for a long-lived access_token.

    Persists the token in `plaid_items` and returns ONLY the safe-to-surface
    item_id + institution_name. The access_token never reaches the wire.
    """
    if not req.public_token.startswith("public-"):
        # Cheap shape check before incurring a Plaid round-trip.
        return JSONResponse(
            status_code=400,
            content={"error": "Public token shape invalid; please reconnect."},
        )

    import plaid as _plaid
    import plaid_client
    user_id = request.headers.get("x-user-id") or "anonymous"

    try:
        access_token, item_id = plaid_client.exchange_public_token(req.public_token)
    except _plaid.ApiException as exc:
        body = (getattr(exc, "body", "") or "")
        # Don't include exc body in the user-facing payload (could leak
        # internal Plaid identifiers). Log fully server-side.
        logger.exception("Plaid exchange failed for user %s", user_id)
        if "INVALID_PUBLIC_TOKEN" in body:
            return JSONResponse(
                status_code=400,
                content={"error": "Token exchange failed; please reconnect."},
            )
        return JSONResponse(
            status_code=502,
            content={"error": "Bank connection failed; please try again."},
        )
    except RuntimeError as exc:
        logger.error("Plaid not configured: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": "Bank connection is not configured on this server."},
        )

    inst = req.institution or _PlaidInstitution()
    try:
        plaid_storage.save_item(
            item_id=item_id,
            access_token=access_token,
            institution_name=inst.name,
            institution_id=inst.institution_id,
            session_id=req.session_id,
        )
    except Exception:
        # Successfully exchanged but couldn't persist — acceptable degradation
        # for prototype; the user can reconnect to retry.
        logger.exception("save_item failed for item_id=%s", item_id)
        return JSONResponse(
            status_code=500,
            content={"error": "Connection succeeded but couldn't be saved. Please reconnect."},
        )

    # P4-H4 Fix #1 — same-institution dedupe.
    # Plaid mints a fresh item_id every Link session, so re-connecting to
    # the same bank used to add a SECOND row (and the mapper would sum
    # accounts/balances from both items, double-counting the user's
    # money). Dedupe by institution_id at this seam: any older item from
    # the same session + institution_id is removed, leaving only the
    # freshly-exchanged token.
    superseded = 0
    if req.session_id and inst.institution_id:
        superseded = plaid_storage.delete_other_items_for_institution(
            session_id=req.session_id,
            institution_id=inst.institution_id,
            keep_item_id=item_id,
        )
        if superseded:
            logger.info(
                "Plaid re-connect superseded %d prior item(s) for "
                "session=%s institution=%s", superseded,
                req.session_id, inst.institution_id,
            )

    return _scrubbed_response({
        "item_id":          item_id,
        "institution_name": inst.name,
        "superseded":       superseded,
    })


def _fetch_one_item(item_id: str, access_token: str) -> dict:
    """Fetch all five product groups for a single Plaid item.

    Handles PRODUCT_NOT_READY non-fatally for liabilities, investments,
    and recurring. Returns a dict shaped like:
      {item_id, institution_name, fetched_at,
       accounts:{available,data}, transactions:{...}, liabilities:{...},
       investments:{...}, recurring:{...}}
    Updates the item's last_synced_at on completion.
    """
    import plaid as _plaid
    import plaid_client
    from datetime import datetime as _dt

    meta = plaid_storage.get_item_metadata(item_id) or {}
    out = {
        "item_id":          item_id,
        "institution_name": meta.get("institution_name"),
        "fetched_at":       _dt.utcnow().isoformat(timespec="seconds") + "Z",
    }

    # ── Accounts (balances) ──────────────────────────────────────────
    try:
        out["accounts"] = {"available": True, "data": plaid_client.fetch_balances(access_token)}
    except _plaid.ApiException:
        logger.exception("fetch_balances failed")
        out["accounts"] = {"available": False, "reason": "plaid_error"}
    except Exception:
        logger.exception("fetch_balances unexpected failure")
        out["accounts"] = {"available": False, "reason": "internal_error"}

    # ── Transactions (paginated) ─────────────────────────────────────
    try:
        out["transactions"] = {
            "available": True,
            "data": plaid_client.fetch_transactions(access_token),
        }
    except _plaid.ApiException:
        logger.exception("fetch_transactions failed")
        out["transactions"] = {"available": False, "reason": "plaid_error"}
    except Exception:
        logger.exception("fetch_transactions unexpected failure")
        out["transactions"] = {"available": False, "reason": "internal_error"}

    # ── Liabilities (PRODUCT_NOT_READY non-fatal) ────────────────────
    try:
        liab = plaid_client.fetch_liabilities(access_token)
        if liab is None:
            out["liabilities"] = {"available": False, "reason": "product_not_ready"}
        else:
            out["liabilities"] = {"available": True, "data": liab}
    except _plaid.ApiException:
        logger.exception("fetch_liabilities failed")
        out["liabilities"] = {"available": False, "reason": "plaid_error"}
    except Exception:
        logger.exception("fetch_liabilities unexpected failure")
        out["liabilities"] = {"available": False, "reason": "internal_error"}

    # ── Investments (PRODUCT_NOT_READY non-fatal) ────────────────────
    try:
        inv = plaid_client.fetch_investments(access_token)
        if inv is None:
            out["investments"] = {"available": False, "reason": "product_not_ready"}
        else:
            out["investments"] = {"available": True, "data": inv}
    except _plaid.ApiException:
        logger.exception("fetch_investments failed")
        out["investments"] = {"available": False, "reason": "plaid_error"}
    except Exception:
        logger.exception("fetch_investments unexpected failure")
        out["investments"] = {"available": False, "reason": "internal_error"}

    # ── Recurring (paystubs, bills, subscriptions; PRODUCT_NOT_READY non-fatal) ──
    # Recurring requires explicit account_ids. We feed it the list extracted
    # from the balances response — typically the depository accounts where
    # paychecks land. Skip if the balances call itself failed.
    try:
        if out["accounts"].get("available"):
            account_ids = [a.get("account_id")
                           for a in (out["accounts"]["data"].get("accounts") or [])
                           if a.get("account_id")]
        else:
            account_ids = []
        rec = plaid_client.fetch_recurring_transactions(access_token, account_ids)
        if rec is None:
            out["recurring"] = {"available": False, "reason": "product_not_ready"}
        else:
            out["recurring"] = {"available": True, "data": rec}
    except _plaid.ApiException:
        logger.exception("fetch_recurring_transactions failed")
        out["recurring"] = {"available": False, "reason": "plaid_error"}
    except Exception:
        logger.exception("fetch_recurring_transactions unexpected failure")
        out["recurring"] = {"available": False, "reason": "internal_error"}

    plaid_storage.update_last_synced(item_id)
    return out


def _fetch_all_for_session(session_id: str) -> dict:
    """Multi-bank orchestrator. Looks up every item connected within a
    session and runs `_fetch_one_item` for each. Returns:

        {session_id, items: [<per-item fetch dict>, ...]}

    Each item carries its own product slices (accounts/transactions/...).
    Cross-institution merging happens in plaid_mapper, NOT here — this
    layer stays Plaid-shaped so the mapper has full visibility per bank.
    """
    items_meta = plaid_storage.get_items_for_session(session_id)
    items_out: list[dict] = []
    for meta in items_meta:
        item_id = meta.get("item_id")
        if not item_id:
            continue
        access_token = plaid_storage.get_access_token(item_id)
        if not access_token:
            continue
        items_out.append(_fetch_one_item(item_id, access_token))
    return {"session_id": session_id, "items": items_out}


# Helper that routes use to resolve "what should we fetch?" given a body
# that may carry session_id, item_id, or both. Single-item lookups still
# work for in-flight requests pre-deploy.
def _resolve_fetch_target(req: "PlaidFetchRequest") -> tuple[Optional[str], Optional[dict]]:
    """Returns (error_response, fetched_dict). Exactly one is non-None."""
    if getattr(req, "session_id", None):
        items = plaid_storage.get_items_for_session(req.session_id)
        if not items:
            return ({"status_code": 404,
                     "error": "No connected banks for this session — please connect one first."},
                    None)
        return (None, _fetch_all_for_session(req.session_id))
    # Legacy single-item path
    if getattr(req, "item_id", None):
        access_token = plaid_storage.get_access_token(req.item_id)
        if not access_token:
            return ({"status_code": 404, "error": "Item not found; please reconnect."}, None)
        single = _fetch_one_item(req.item_id, access_token)
        # Wrap single item into multi-bank shape so the mapper sees one
        # consistent contract.
        return (None, {"session_id": None, "items": [single]})
    return ({"status_code": 422,
             "error": "Either session_id or item_id is required."}, None)


@app.post("/plaid/fetch")
async def plaid_fetch(req: PlaidFetchRequest, request: Request):
    """Pull all five product groups for every bank in the session.
    Returns the multi-bank `{session_id, items: [...]}` shape — single-
    item legacy callers see a one-element items list."""
    err, fetched = _resolve_fetch_target(req)
    if err:
        return JSONResponse(status_code=err["status_code"],
                            content={"error": err["error"]})

    # Plaid SDK responses contain non-JSON-native types (datetime, Decimal,
    # enums via .to_dict()). FastAPI's JSONResponse uses jsonable_encoder
    # which handles datetime; Decimal needs a tiny coercion.
    # `_scrubbed_response` runs both the access-token scrubber and the
    # optimization-internals scrubber before serializing.
    return _scrubbed_response(jsonable_plaid(fetched))


@app.post("/plaid/map")
async def plaid_map(req: PlaidFetchRequest, request: Request):
    """Fetch Plaid data across the session's connected banks and translate
    into IndividualInput field values with confidence ratings + per-bank
    provenance. The frontend uses this to prefill the manual form —
    never as a binding decision. Users can override any field."""
    err, fetched = _resolve_fetch_target(req)
    if err:
        return JSONResponse(status_code=err["status_code"],
                            content={"error": err["error"]})

    fetched = jsonable_plaid(fetched)   # coerce types BEFORE the mapper sees it

    from plaid_mapper import map_plaid_data
    # Phase 5a.5: archetype on the request enables SB-aware mapping
    # (business CC inclusion, business depository in S_liq). Fall back
    # to "individual_w2" when the request didn't carry it.
    archetype = getattr(req, "archetype", None) or "individual_w2"
    mapped = map_plaid_data(fetched, archetype=archetype)

    # Phase 5a.5: cross-archetype recommendations from mapper context.
    # data_completion fires for AR/AP manual-entry fields. archetype_suggestion
    # fires when business accounts appear on a non-SB archetype.
    # detection_override fires for medium-confidence heuristic detections.
    from recommendations import (
        generate_data_completion_recommendations,
        generate_archetype_suggestion,
        generate_detection_overrides,
    )
    mapped_dict = mapped.to_dict()
    recs: list = []
    recs.extend(generate_data_completion_recommendations(mapped_dict))
    biz_account_names = [d["account_name"] for d in mapped.business_detections
                         if d.get("is_business")]
    arch_sug = generate_archetype_suggestion(biz_account_names, archetype)
    if arch_sug is not None:
        recs.append(arch_sug)
    recs.extend(generate_detection_overrides(mapped.business_detections))

    items_list = fetched.get("items") or []
    # P4-H4 Fix #3 — singular `item_id` / `institution_name` were a
    # back-compat shim from the P4-3 → P4-4 migration. No frontend
    # consumer reads them post-multi-bank: the pill list lives in the
    # local `_plaidConnectedBanks` array, the review banner consumes
    # `item_count` + `institutions`, and the renderer walks `items[]`
    # directly. Dropped to keep the contract intentional.
    response = {
        "session_id":   fetched.get("session_id"),
        "item_count":   len(items_list),
        "institutions": [it.get("institution_name") for it in items_list],
        "fetched_at":   items_list[-1].get("fetched_at") if items_list else None,
        "mapped":       mapped_dict,
        "recommendations": recs,
    }

    # Defensive scrub at the boundary — both access_token and optimization
    # internals (CLAUDE.md §11.1).
    return _scrubbed_response(response)


def jsonable_plaid(obj):
    """Coerce Plaid SDK output into JSON-native types (Decimal → float,
    datetime → ISO 8601, date → ISO 8601). Operates recursively."""
    from datetime import date, datetime as _dt
    from decimal import Decimal
    if isinstance(obj, dict):
        return {k: jsonable_plaid(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [jsonable_plaid(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, _dt):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


@app.get("/api/health")
async def health():
    from history import DB_PATH
    return _scrubbed_response({
        "status": "ok",
        "uptime_seconds": round(_time.time() - _startup_time, 1),
        "db": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
    })


@app.post("/api/score")
async def compute_score(req: ScoreRequest, request: Request):
    user_id = _user_id(request.headers.get("x-user-id"))
    state = get_user_state(user_id)

    inp = IndividualInput(
        name=req.name,
        I_gross=req.I_gross,
        I_net=req.I_net,
        E_ess=req.E_ess,
        E_house=req.E_house,
        D_min=req.D_min,
        D_hi=req.D_hi,
        D_lo=req.D_lo,
        S_liq=req.S_liq,
        S_ret=req.S_ret,
        age=req.age,
        has_life_insurance=req.has_life_insurance,
        has_disability_insurance=req.has_disability_insurance,
        overdraft_count_90d=req.overdraft_count_90d,
        late_payment_count_90d=req.late_payment_count_90d,
        momentum_slope=state["momentum_slope"],   # stored value wins
        streak_days=state["streak_days"],          # stored value wins
        previous=req.previous,
        use_multiperiod=req.use_multiperiod,
        dependents=req.dependents,
        retired=req.retired,
    )
    try:
        result = score_individual(inp)
    except Exception as exc:
        logger.exception("score_individual failed for user %s", user_id)
        return JSONResponse(
            status_code=500,
            content={"error": "Scoring engine error. Please try again.", "detail": str(exc)}
        )

    solver = "multiperiod" if result.state_trajectory else "single_period"
    fp = compute_fingerprint(req.model_dump())
    updated_state = record_score(
        user_id, result.fhs, result.fss, result.frs, solver, fingerprint=fp
    )

    response = score_to_dict(result)
    response["meta"]["streak_days"]    = updated_state["streak_days"]
    response["meta"]["momentum_slope"] = updated_state["momentum_slope"]
    response["meta"]["last_score_date"] = updated_state["last_score_date"]
    response["meta"]["input_fingerprint"] = fp

    # Phase 5a.5: cross-archetype recommendations driven by IndividualInput
    # alone. Mapper context isn't available here; the heuristic uses inp
    # values to detect manual-entry gaps and archetype-mismatch hints.
    # `detection_override` requires per-account data and lives only on
    # /plaid/map.
    _augment_recommendations_from_inp(response, inp)

    return _scrubbed_response(response)


@app.post("/api/score/previous")
async def compute_score_with_previous(req: PreviousSnapshotRequest, request: Request):
    """Score with a real 30-day comparison snapshot for accurate FRS."""
    user_id = _user_id(request.headers.get("x-user-id"))
    state = get_user_state(user_id)
    # Build the previous dict from prev_* fields.
    # Only include keys where a value was explicitly provided —
    # compute_frs falls back to inp.* for any missing key.
    previous = {}
    if req.prev_S_liq    is not None: previous["S_liq"]    = req.prev_S_liq
    if req.prev_S_ret    is not None: previous["S_ret"]    = req.prev_S_ret
    if req.prev_D_hi     is not None: previous["D_hi"]     = req.prev_D_hi
    if req.prev_D_lo     is not None: previous["D_lo"]     = req.prev_D_lo
    if req.prev_E_ess    is not None: previous["E_ess"]    = req.prev_E_ess
    if req.prev_I_gross  is not None: previous["I_gross"]  = req.prev_I_gross
    if req.prev_has_life_insurance         is not None:
        previous["has_life_insurance"]         = req.prev_has_life_insurance
    if req.prev_has_disability_insurance   is not None:
        previous["has_disability_insurance"]   = req.prev_has_disability_insurance
    if req.prev_overdraft_count_90d        is not None:
        previous["overdraft_count_90d"]        = req.prev_overdraft_count_90d
    if req.prev_late_payment_count_90d     is not None:
        previous["late_payment_count_90d"]     = req.prev_late_payment_count_90d

    inp = IndividualInput(
        name=req.name,
        I_gross=req.I_gross,
        I_net=req.I_net,
        E_ess=req.E_ess,
        E_house=req.E_house,
        D_min=req.D_min,
        D_hi=req.D_hi,
        D_lo=req.D_lo,
        S_liq=req.S_liq,
        S_ret=req.S_ret,
        age=req.age,
        has_life_insurance=req.has_life_insurance,
        has_disability_insurance=req.has_disability_insurance,
        overdraft_count_90d=req.overdraft_count_90d,
        late_payment_count_90d=req.late_payment_count_90d,
        momentum_slope=state["momentum_slope"],   # stored value wins
        streak_days=state["streak_days"],          # stored value wins
        previous=previous if previous else None,
        use_multiperiod=req.use_multiperiod,
        dependents=req.dependents,
        retired=req.retired,
    )
    try:
        result = score_individual(inp)
    except Exception as exc:
        logger.exception("score_individual failed for user %s (with previous)", user_id)
        return JSONResponse(
            status_code=500,
            content={"error": "Scoring engine error. Please try again.", "detail": str(exc)}
        )

    solver = "multiperiod" if result.state_trajectory else "single_period"
    fp = compute_fingerprint(req.model_dump())
    updated_state = record_score(
        user_id, result.fhs, result.fss, result.frs, solver, fingerprint=fp
    )

    response = score_to_dict(result)
    response["meta"]["streak_days"]    = updated_state["streak_days"]
    response["meta"]["momentum_slope"] = updated_state["momentum_slope"]
    response["meta"]["last_score_date"] = updated_state["last_score_date"]
    response["meta"]["input_fingerprint"] = fp

    # Phase 5a.5: cross-archetype recommendations on the previous-snapshot
    # path too — same heuristic as /api/score.
    _augment_recommendations_from_inp(response, inp)

    return _scrubbed_response(response)


@app.get("/api/history")
async def get_history(request: Request):
    user_id = _user_id(request.headers.get("x-user-id"))
    # Optional fingerprint filter — when present, the chart shows only history
    # entries sharing the current profile's inputs. Prevents cross-profile
    # contamination when the user explores multiple archetypes.
    fp = (request.query_params.get("fingerprint")
          or request.headers.get("x-input-fingerprint")
          or "").strip()
    history = get_score_history(user_id, limit=30, fingerprint=fp)
    state = get_user_state(user_id)
    return _scrubbed_response({
        "user_id": user_id,
        "streak_days": state["streak_days"],
        "momentum_slope": state["momentum_slope"],
        "fingerprint": fp,
        "history": history,
        "interpretation": history_interpretation(history),
    })


@app.delete("/api/history")
async def reset_history(request: Request):
    """Reset streak and history for a user. Used for testing."""
    user_id = _user_id(request.headers.get("x-user-id"))
    import sqlite3 as _sq
    from history import DB_PATH
    with _sq.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM score_history WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_state WHERE user_id = ?", (user_id,))
    return _scrubbed_response({"reset": True, "user_id": user_id})


@app.get("/api/profiles")
async def get_profiles():
    results = []
    for p in PROFILES:
        inp = p["input"]
        result = score_individual(inp)
        results.append({
            "name": inp.name,
            "fhs": result.fhs,
            "fss": result.fss,
            "frs": result.frs,
            "expected_fhs": p["expected_fhs"],
            "expected_fss": p["expected_fss"],
            "fhs_in_range": p["expected_fhs"][0] <= result.fhs <= p["expected_fhs"][1],
            "fss_in_range": p["expected_fss"][0] <= result.fss <= p["expected_fss"][1],
            "infeasible": result.infeasible,
        })
    return _scrubbed_response(results)


@app.get("/api/profile/{idx}")
async def get_profile_detail(idx: int):
    if idx < 0 or idx >= len(PROFILES):
        return JSONResponse(content={"error": "Invalid profile index"}, status_code=404)
    inp = PROFILES[idx]["input"]
    result = score_individual(inp)
    return _scrubbed_response({
        "name": inp.name,
        "expected_fhs": PROFILES[idx]["expected_fhs"],
        "expected_fss": PROFILES[idx]["expected_fss"],
        # Raw input fields so the frontend can populate the form
        "input": {
            "I_gross": inp.I_gross,
            "I_net": inp.I_net,
            "E_ess": inp.E_ess,
            "E_house": inp.E_house,
            "D_min": inp.D_min,
            "D_hi": inp.D_hi,
            "D_lo": inp.D_lo,
            "S_liq": inp.S_liq,
            "S_ret": inp.S_ret,
            "age": inp.age,
            "has_life_insurance": inp.has_life_insurance,
            "has_disability_insurance": inp.has_disability_insurance,
            "overdraft_count_90d": inp.overdraft_count_90d,
            "late_payment_count_90d": inp.late_payment_count_90d,
        },
        **result_to_dict(result),
    })


@app.get("/", response_class=HTMLResponse)
async def index():
    import os
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
