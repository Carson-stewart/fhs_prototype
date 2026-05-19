"""
Plaid SDK wrapper. Single place that knows about the Plaid client.

Reads PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV from the environment. Fails
fast at import time if credentials are missing — easier to debug a clear
error at startup than `INVALID_API_KEYS` from the first request.

The secret is server-only. It must NEVER be exposed to the frontend, logged,
or returned in an API response. Only this module reads it; consumers import
the configured `client` (or call `get_client()`).
"""
import os
import logging

import plaid
from plaid.api import plaid_api
from plaid.configuration import Configuration
from plaid.api_client import ApiClient

logger = logging.getLogger("fhs.plaid")


# ── Environment mapping ────────────────────────────────────────────────
_ENV_HOSTS = {
    "sandbox":    plaid.Environment.Sandbox,
    # Production / development support intentionally omitted for now —
    # we'll wire those in when the prototype graduates.
}


def _build_client() -> plaid_api.PlaidApi:
    """Construct a Plaid API client from environment vars.

    Strips whitespace on values so a stray newline in `.env` doesn't produce
    `INVALID_API_KEYS` — that's the most common debugging trap on first run.
    """
    client_id = (os.environ.get("PLAID_CLIENT_ID") or "").strip()
    secret    = (os.environ.get("PLAID_SECRET")    or "").strip()
    env_name  = (os.environ.get("PLAID_ENV") or "sandbox").strip().lower()

    if not client_id:
        raise RuntimeError(
            "PLAID_CLIENT_ID is not set. Add it to your .env file. "
            "See .env.example for the required keys."
        )
    if not secret:
        raise RuntimeError(
            "PLAID_SECRET is not set. Add your Sandbox secret to your .env file. "
            "See .env.example for the required keys."
        )
    if env_name not in _ENV_HOSTS:
        raise RuntimeError(
            f"PLAID_ENV={env_name!r} is not supported. "
            f"Only {list(_ENV_HOSTS)} are configured for this prototype."
        )

    cfg = Configuration(
        host=_ENV_HOSTS[env_name],
        api_key={
            "clientId": client_id,
            "secret":   secret,
        },
    )
    api_client = ApiClient(cfg)
    return plaid_api.PlaidApi(api_client)


# Module-level singleton — built lazily so `import plaid_client` doesn't
# crash a script that doesn't actually need Plaid (e.g. test_runner.py).
_client_instance: plaid_api.PlaidApi | None = None


def get_client() -> plaid_api.PlaidApi:
    global _client_instance
    if _client_instance is None:
        _client_instance = _build_client()
        logger.info("Plaid client initialized for env=%s",
                    os.environ.get("PLAID_ENV", "sandbox"))
    return _client_instance


# ─────────────────────────────────────────────────────────────────────
# Typed-request helpers — keep route handlers free of Plaid SDK glue.
# Every helper:
#   • uses the SDK's typed request objects (NOT raw dicts — the dict
#     pattern is deprecated in plaid-python 39.x and silently fails)
#   • returns Plaid SDK response objects; callers use `.to_dict()` at
#     the API boundary to serialize
#   • never logs the access token — not at DEBUG, not anywhere
# ─────────────────────────────────────────────────────────────────────

def exchange_public_token(public_token: str) -> tuple[str, str]:
    """Exchange a Plaid Link public_token for a long-lived access_token.

    Returns (access_token, item_id). Raises plaid.ApiException on Plaid-side
    failures — callers translate to HTTP status codes.
    """
    from plaid.model.item_public_token_exchange_request import (
        ItemPublicTokenExchangeRequest,
    )
    req = ItemPublicTokenExchangeRequest(public_token=public_token)
    resp = get_client().item_public_token_exchange(req)
    return resp["access_token"], resp["item_id"]


def fetch_balances(access_token: str) -> dict:
    """Plaid /accounts/balance/get — current balances per linked account."""
    from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
    req = AccountsBalanceGetRequest(access_token=access_token)
    resp = get_client().accounts_balance_get(req)
    return resp.to_dict()


def fetch_transactions(access_token: str) -> list:
    """Plaid /transactions/sync — full historical sync, paginated.

    Loops on `has_more` until exhausted. Returns the accumulated `added`
    list as plain dicts. Sandbox `user_good` typically returns 100–200
    transactions (well below the count=500 page size), but real users with
    multi-year history easily exceed one page — never short-circuit this.
    """
    from plaid.model.transactions_sync_request import TransactionsSyncRequest
    client = get_client()
    cursor: str | None = None
    added: list = []
    safety_iter = 0
    while True:
        # SDK requires the cursor to be omitted (not None) on first call.
        kwargs = {"access_token": access_token, "count": 500}
        if cursor is not None:
            kwargs["cursor"] = cursor
        req = TransactionsSyncRequest(**kwargs)
        resp = client.transactions_sync(req)
        added.extend([t.to_dict() for t in resp["added"]])
        if not resp["has_more"]:
            break
        cursor = resp["next_cursor"]
        safety_iter += 1
        if safety_iter > 50:   # 50 × 500 = 25 000 transactions ceiling
            logger.warning("transactions_sync hit pagination safety limit (50 iterations)")
            break
    return added


def fetch_liabilities(access_token: str) -> dict | None:
    """Plaid /liabilities/get. Returns None on PRODUCT_NOT_READY (sandbox
    sometimes returns this on freshly-connected items)."""
    import plaid as _plaid
    from plaid.model.liabilities_get_request import LiabilitiesGetRequest
    req = LiabilitiesGetRequest(access_token=access_token)
    try:
        resp = get_client().liabilities_get(req)
        return resp.to_dict()
    except _plaid.ApiException as e:
        # Plaid encodes error_code in the response body
        body = (getattr(e, "body", "") or "")
        if "PRODUCT_NOT_READY" in body:
            return None
        raise


def fetch_investments(access_token: str) -> dict | None:
    """Plaid /investments/holdings/get. Returns None on PRODUCT_NOT_READY."""
    import plaid as _plaid
    from plaid.model.investments_holdings_get_request import (
        InvestmentsHoldingsGetRequest,
    )
    req = InvestmentsHoldingsGetRequest(access_token=access_token)
    try:
        resp = get_client().investments_holdings_get(req)
        return resp.to_dict()
    except _plaid.ApiException as e:
        body = (getattr(e, "body", "") or "")
        if "PRODUCT_NOT_READY" in body:
            return None
        raise


def fetch_recurring_transactions(access_token: str,
                                  account_ids: list[str]) -> dict | None:
    """Plaid /transactions/recurring/get — paystubs, bills, subscriptions.
    Returns None on PRODUCT_NOT_READY (Sandbox often takes a few minutes
    to populate this on a freshly-connected item).

    `account_ids` is required by Plaid (must be non-empty). The /plaid/fetch
    route passes the depository account IDs from balances. Recurring is
    part of the Transactions product, so it's enabled automatically for
    any item that requested `transactions` at link-token-creation time.
    """
    if not account_ids:
        return None
    import plaid as _plaid
    from plaid.model.transactions_recurring_get_request import (
        TransactionsRecurringGetRequest,
    )
    req = TransactionsRecurringGetRequest(
        access_token=access_token,
        account_ids=account_ids,
    )
    try:
        resp = get_client().transactions_recurring_get(req)
        return resp.to_dict()
    except _plaid.ApiException as e:
        body = (getattr(e, "body", "") or "")
        if "PRODUCT_NOT_READY" in body:
            return None
        raise
