"""
Plaid → IndividualInput mapper.

Pure module: takes a /plaid/fetch dict, returns a MappedFields dataclass.
No I/O, no Plaid SDK calls, no DB access. Fully testable from synthetic
fixtures.

Field-name convention: the keys in MappedFields match the names on
IndividualInput in engine.py exactly (I_net, E_ess, S_liq, S_ret, D_hi,
D_lo, D_min). Demographic fields (age, dependents, retired) are NOT
mapped — they remain manual-only.

Sign-convention reminders, hardcoded in this module:
  • Plaid transaction `amount` is POSITIVE for outflows (purchases,
    bills) and NEGATIVE for inflows (deposits, paychecks).
  • Plaid recurring `inflow_streams[].average_amount.amount` is also
    NEGATIVE — they're inflows. Take abs() when summing as income.
  • A flipped sign in either direction produces a silently-wrong score.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional
from collections import defaultdict
from datetime import date as _date


Confidence = Literal["high", "medium", "low", "missing"]


@dataclass
class MappedField:
    value: Optional[float]
    confidence: Confidence
    source: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "value":      self.value,
            "confidence": self.confidence,
            "source":     self.source,
            "notes":      self.notes,
        }


@dataclass
class MapSource:
    """Provenance — which institution contributed which field(s).
    Powers the multi-bank UI summary and is invaluable for debugging."""
    item_id: str
    institution_name: str
    contributed_to: list[str]   # e.g. ["S_liq", "D_hi", "I_net"]

    def to_dict(self) -> dict:
        return {
            "item_id":          self.item_id,
            "institution_name": self.institution_name,
            "contributed_to":   list(self.contributed_to),
        }


@dataclass
class MappedFields:
    """One MappedField per IndividualInput field that Plaid can populate.
    Engine fields not in this set (I_gross, E_house, age, dependents,
    retired, has_life_insurance, has_disability_insurance, momentum_*,
    streak_*, previous, use_multiperiod) are NOT mappable from Plaid
    and must remain manual-only.

    Phase 5a.3 — Small Business extension fields:
      • `business_lines_of_credit` carries the LOC list (value=list of
        {limit, balance, apr, name} dicts). Confidence reflects detection
        quality; `value=[]` with `confidence="missing"` when none found.
      • `ar_aging_buckets` and `ap_pending` are ALWAYS missing-by-design.
        Plaid does not deliver this data; it lives in accounting software
        (QuickBooks/Xero/FreshBooks). Surfaced as
        `source="manual_entry_required"` with a clear reason note. The
        frontend will surface a "Add this manually" affordance.
    """
    I_net:  MappedField
    E_ess:  MappedField
    S_liq:  MappedField
    S_ret:  MappedField
    D_hi:   MappedField
    D_lo:   MappedField
    D_min:  MappedField
    # ── Phase 5a.3 SB extensions ────────────────────────────────────
    business_lines_of_credit: Optional[MappedField] = None
    ar_aging_buckets:         Optional[MappedField] = None
    ap_pending:               Optional[MappedField] = None
    # Phase 5a.5: per-account detection results — surfaced to the API
    # so the recommendation layer can emit detection_override cards
    # for medium-confidence heuristic detections. Each entry:
    #   {"account_id", "account_name", "is_business",
    #    "confidence", "source"}
    business_detections: list = field(default_factory=list)
    # ── Phase 5b.3 Freelancer extensions ────────────────────────────
    # Populated only when archetype == "freelancer". For other
    # archetypes these stay None (omitted from `to_dict()` output).
    income_sources:             Optional[MappedField] = None
    income_volatility_observed: Optional[MappedField] = None
    months_of_income_history:   Optional[MappedField] = None
    sources: list = field(default_factory=list)   # list[MapSource]

    def to_dict(self) -> dict:
        d = {
            "I_net":   self.I_net.to_dict(),
            "E_ess":   self.E_ess.to_dict(),
            "S_liq":   self.S_liq.to_dict(),
            "S_ret":   self.S_ret.to_dict(),
            "D_hi":    self.D_hi.to_dict(),
            "D_lo":    self.D_lo.to_dict(),
            "D_min":   self.D_min.to_dict(),
            "sources": [s.to_dict() for s in self.sources],
        }
        # SB extension fields are always emitted in the dict so the
        # contract is consistent regardless of archetype. For Individual
        # archetype scenarios these will be missing-with-empty-value.
        if self.business_lines_of_credit is not None:
            d["business_lines_of_credit"] = self.business_lines_of_credit.to_dict()
        if self.ar_aging_buckets is not None:
            d["ar_aging_buckets"] = self.ar_aging_buckets.to_dict()
        if self.ap_pending is not None:
            d["ap_pending"] = self.ap_pending.to_dict()
        if self.business_detections:
            d["business_detections"] = list(self.business_detections)
        if self.income_sources is not None:
            d["income_sources"] = self.income_sources.to_dict()
        if self.income_volatility_observed is not None:
            d["income_volatility_observed"] = self.income_volatility_observed.to_dict()
        if self.months_of_income_history is not None:
            d["months_of_income_history"] = self.months_of_income_history.to_dict()
        return d


# ─────────────────────────────────────────────────────────────────────
# Currency safety — the single highest-impact correctness check.
# ─────────────────────────────────────────────────────────────────────

def _detect_currency_issue_in_items(items: list) -> Optional[str]:
    """Return a note string if any account in any item uses a non-USD
    currency. Empty/missing currency codes are treated as USD
    (Plaid's default for US institutions)."""
    foreign = set()
    for item in items:
        accounts_section = item.get("accounts") or {}
        if not accounts_section.get("available"):
            continue
        accounts = (accounts_section.get("data") or {}).get("accounts") or []
        for acct in accounts:
            code = (acct.get("balances") or {}).get("iso_currency_code")
            if code and code.upper() != "USD":
                foreign.add(code.upper())
    if foreign:
        return ("Connected accounts include non-USD currencies "
                f"({', '.join(sorted(foreign))}). This prototype only "
                "supports USD; please connect a USD-denominated account "
                "or fill in the form manually.")
    return None


# ─────────────────────────────────────────────────────────────────────
# Phase 5a.3 — Small Business detection + manual-entry surface helpers.
#
# Maintainer note: this is the SINGLE source of truth for what Plaid
# fields and account-name patterns mark an account as part of the
# business surface. When adding a new pattern (or the Plaid
# `account.categorization` beta value set changes), update _SB_DETECTION
# and the `detect_business_account()` priority order in lockstep.
# ─────────────────────────────────────────────────────────────────────
_SB_DETECTION = {
    # Plaid `account.subtype` values that strongly imply business banking.
    # NOTE: subtype-only match returns MEDIUM confidence — many
    # institutions use these subtypes for personal accounts too (e.g., a
    # sole-prop using a "business checking" account for mixed personal +
    # business use is common). We don't claim high-confidence business
    # detection on subtype alone.
    "business_subtypes": frozenset({
        "business",                # generic
        "business checking", "business savings", "business money market",
        "commercial",
        "line of credit",          # most LOCs in retail Plaid coverage are business
    }),
    # Substring patterns matched case-insensitively against
    # `account.name` AND `account.official_name` (concatenated). Any
    # match → medium-confidence business signal. Leading spaces on legal
    # suffixes prevent word-mid false positives like "Linc" matching " inc".
    "business_name_patterns": (
        "business", "biz", "commercial",
        " llc", " inc", " corp",
        "company", " co.",
    ),
}


def detect_business_account(account: dict) -> tuple[bool, str, str]:
    """Detect whether a Plaid account belongs to the business surface.

    Priority order:
      1. `account.categorization == "business"` (Plaid beta field) →
         (True, "high", "plaid_categorization"). Requires beta access
         from the Plaid account manager; until that's enabled in
         production this branch is rarely hit. When it IS hit,
         detection upgrades automatically — no code change needed.
         `categorization == "personal"` returns (False, "high",
         "plaid_categorization") for symmetry.
      2. `account.subtype` in `_SB_DETECTION["business_subtypes"]` →
         (True, "medium", "heuristic_subtype").
      3. Name/official_name matches `_SB_DETECTION["business_name_patterns"]`
         → (True, "medium", "heuristic_name_match").
      4. `account.holder_category == "business"` (the P4-H1 signal —
         Plaid surfaces this on some institutions but coverage is
         uneven) → (True, "medium", "holder_category").
      5. No business signal → (False, "high", "default_personal").

    Returns: (is_business, confidence, source).

    Note on confidence semantics:
      - "high" for plaid_categorization OR default_personal — these are
        decisive signals (categorization is structured Plaid data;
        default_personal is the safe fallback when no business marker
        appears anywhere).
      - "medium" for any heuristic — there's real ambiguity between
        sole-prop mixed-use accounts and clean business accounts.
    """
    cat = (account.get("categorization") or "").lower()
    if cat == "business":
        return (True, "high", "plaid_categorization")
    if cat == "personal":
        return (False, "high", "plaid_categorization")

    subtype = (account.get("subtype") or "").lower()
    if subtype in _SB_DETECTION["business_subtypes"]:
        return (True, "medium", "heuristic_subtype")

    name     = (account.get("name") or "").lower()
    official = (account.get("official_name") or "").lower()
    combined = name + " " + official
    for pattern in _SB_DETECTION["business_name_patterns"]:
        if pattern in combined:
            return (True, "medium", "heuristic_name_match")

    if (account.get("holder_category") or "").lower() == "business":
        return (True, "medium", "holder_category")

    return (False, "high", "default_personal")


def map_business_lines_of_credit(accounts: list,
                                 liabilities_data: Optional[dict] = None
                                 ) -> MappedField:
    """Map Plaid LOC accounts to the `business_lines_of_credit` schema
    field (list of {name, limit, balance, apr} dicts).

    Filters: `account.subtype == "line of credit"` AND
    `detect_business_account()` returns True. APR is looked up from the
    liabilities/credit cross-reference when available; otherwise None.

    Confidence aggregation: worst-of-streams across all detected LOCs.
    No LOCs detected → MappedField(value=[], confidence="missing").
    """
    locs = []
    confidences: list[str] = []
    for acc in (accounts or []):
        subtype = (acc.get("subtype") or "").lower()
        if subtype != "line of credit":
            continue
        is_biz, det_conf, det_source = detect_business_account(acc)
        if not is_biz:
            continue
        balances = acc.get("balances") or {}
        balance = balances.get("current")
        limit   = balances.get("limit")
        # Cross-ref APR from liabilities.credit if present.
        apr = None
        if liabilities_data:
            for c in (liabilities_data.get("credit") or []):
                if c.get("account_id") != acc.get("account_id"):
                    continue
                aprs = c.get("aprs") or []
                if aprs:
                    pct = aprs[0].get("apr_percentage")
                    if pct is not None:
                        apr = float(pct) / 100.0
                break
        # Confidence rules:
        #   • detection-confidence baseline (high or medium)
        #   • degrade to medium if limit is missing
        #   • degrade to low if balance is missing
        if balance is None:
            entry_conf = "low"
        elif limit is None:
            entry_conf = "medium" if det_conf == "high" else det_conf
        else:
            entry_conf = det_conf
        confidences.append(entry_conf)
        locs.append({
            "name":    acc.get("name") or "Line of Credit",
            "limit":   float(limit)   if limit   is not None else 0.0,
            "balance": abs(float(balance)) if balance is not None else 0.0,
            "apr":     apr,
        })

    if not locs:
        return MappedField(
            value=[], confidence="missing",
            source="no_loc_accounts",
            notes=("No business lines of credit detected at connected "
                   "banks."),
        )

    rank = {"high": 3, "medium": 2, "low": 1, "missing": 0}
    worst = min(confidences, key=lambda c: rank.get(c, 0))
    note_parts = [f"{len(locs)} business line(s) of credit detected."]
    if worst != "high":
        note_parts.append(
            "Some LOC fields incomplete or based on heuristic detection — "
            "please verify."
        )
    return MappedField(
        value=locs, confidence=worst, source="plaid_loc_accounts",
        notes=" ".join(note_parts),
    )


# ─────────────────────────────────────────────────────────────────────
# Phase 5b.3 — Freelancer 1099/gig income detection.
#
# Maintainer note: the gig-platform list and business-payer patterns
# are the SINGLE source of truth for what counterparties signal
# Freelancer income. Add new platforms as they emerge in real-data
# review (Phase 6 will refine against beta data).
# ─────────────────────────────────────────────────────────────────────
_FL_DETECTION = {
    # Recognized gig-platform / payment-aggregator counterparties.
    # Substring match against transaction `name` or `merchant_name`,
    # case-insensitive. High-confidence signal for source_type=gig_platform.
    "gig_platforms": (
        "stripe", "square", "paypal", "venmo",
        "upwork", "fiverr", "toptal",
        "doordash", "uber", "lyft",
        "etsy", "patreon", "twitch",
        "youtube", "substack",
    ),
    # Business-payer suffix patterns (1099 contract income from a
    # business client). Same set as 5a.3's business name patterns —
    # leading-space prevents word-mid matches.
    "business_payer_patterns": (
        " llc", " inc", " corp", "company", " co.",
        "studio", "agency", "consulting",
    ),
    # Transaction-description keywords that signal contract-style
    # payment when combined with INCOME / TRANSFER_IN category.
    "description_keywords": (
        "invoice", "payment", "contract", "1099",
    ),
    # Plaid `personal_finance_category.primary` values that pass the
    # initial filter for gig-income detection. Anything outside this
    # set is not considered (e.g., LOAN_PAYMENTS, RENT_AND_UTILITIES
    # would never be income).
    "income_category_primaries": frozenset({
        "INCOME", "DEPOSITS", "TRANSFER_IN",
    }),
    # Minimum monthly history required before computing volatility.
    # Below this we surface manual-entry-required (honest data
    # architecture — don't fabricate volatility from sparse history).
    "min_history_months_for_volatility": 3,
    # Per-source minimum month count for inclusion in income_sources.
    # Single-occurrence payers are filtered out as noise.
    "min_months_per_source": 2,
}


def detect_1099_gig_income(transaction: dict) -> tuple:
    """Per-transaction classification: is this a 1099/gig income deposit?

    Priority order:
      1. Plaid INCOME / TRANSFER_IN category + recognized gig-platform
         counterparty → (True, "high", "gig_platform_match",
                         "gig_platform").
      2. Plaid INCOME / TRANSFER_IN + business-payer pattern in name +
         description-keyword match → (True, "medium",
         "business_payer_with_invoice_keyword", "freelance_direct").
      3. Plaid INCOME / TRANSFER_IN + business-payer pattern in name →
         (True, "medium", "business_payer_pattern", "1099_contract").
      4. Plaid INCOME / TRANSFER_IN + materially-large irregular amount
         (>$500) without recurring biweekly cadence → (True, "low",
         "heuristic_irregular_amount", "other").
      5. Otherwise → (False, "high", "no_gig_signal", None).

    Returns: (is_gig, confidence, source, source_type | None).

    Note on precision-vs-recall: tuned toward precision per the brief.
    A false positive (employment net-pay misclassified as gig) corrupts
    volatility / tax-reserve / recommendations. A false negative
    (missing some gig income) is incomplete-but-not-misleading.
    """
    pfc = transaction.get("personal_finance_category") or {}
    primary = ((pfc.get("primary") or "").upper()
               if isinstance(pfc, dict) else "")
    if primary not in _FL_DETECTION["income_category_primaries"]:
        return (False, "high", "category_not_income", None)

    # Must be an inflow (negative amount in Plaid convention).
    amt = transaction.get("amount")
    try:
        amt = float(amt) if amt is not None else 0.0
    except (TypeError, ValueError):
        return (False, "high", "invalid_amount", None)
    if amt >= 0:
        return (False, "high", "outflow_not_income", None)

    name      = (transaction.get("name") or "").lower()
    merchant  = (transaction.get("merchant_name") or "").lower()
    combined  = name + " " + merchant

    # Tier 1: gig-platform match
    for platform in _FL_DETECTION["gig_platforms"]:
        if platform in combined:
            return (True, "high", "gig_platform_match", "gig_platform")

    # Tier 2 & 3: business-payer pattern
    has_business_pattern = any(
        p in combined for p in _FL_DETECTION["business_payer_patterns"]
    )
    if has_business_pattern:
        has_keyword = any(
            kw in combined for kw in _FL_DETECTION["description_keywords"]
        )
        if has_keyword:
            return (True, "medium",
                    "business_payer_with_invoice_keyword",
                    "freelance_direct")
        return (True, "medium", "business_payer_pattern", "1099_contract")

    # Tier 4: heuristic — large irregular amount within INCOME category.
    # The category whitelist already filtered out most non-income; the
    # additional magnitude floor catches small refunds/transfers.
    if abs(amt) >= 500:
        return (True, "low", "heuristic_irregular_amount", "other")

    return (False, "high", "no_gig_signal", None)


def _normalize_payer_name(transaction: dict) -> str:
    """Canonicalize a payer name for grouping. Prefers `merchant_name`
    when present (Plaid-curated), falls back to the parsed `name`."""
    merchant = transaction.get("merchant_name")
    if merchant:
        return str(merchant).strip()
    name = (transaction.get("name") or "").strip()
    # Trim common transaction-description prefixes that don't identify
    # the payer (date stamps, ACH-route prefixes).
    for prefix in ("ACH DEPOSIT ", "DEPOSIT ", "DIRECT DEPOSIT "):
        if name.upper().startswith(prefix):
            name = name[len(prefix):]
            break
    return name or "Unknown payer"


def aggregate_freelance_income(transactions: list,
                               freelance_account_separation: str
                               ) -> tuple:
    """Group detected 1099/gig income transactions by payer and compute
    per-source aggregates.

    Returns: (income_sources_list, monthly_totals_dict)
      • income_sources_list: list of dicts matching the IndividualInput
        `income_sources` schema field — one entry per detected payer.
      • monthly_totals_dict: {YYYY-MM: total_gig_income_for_month} —
        used downstream by `compute_freelance_volatility`.

    Confidence per source incorporates the `freelance_account_separation`
    field (5a.3 priority pattern, inverted): separate_business_account →
    high baseline; mixed_personal → medium; unknown → low.
    """
    # Group transactions by canonical payer name and bucket by month.
    # Structure: per_payer = {
    #     payer_name: {
    #         "type":    source_type,
    #         "det_conf": worst-of detection confidence across txns,
    #         "monthly": {YYYY-MM: float (total inflow)},
    #     }
    # }
    per_payer: dict = {}
    monthly_totals: dict = {}
    rank = {"high": 3, "medium": 2, "low": 1, "missing": 0}

    for t in transactions or []:
        is_gig, det_conf, det_source, source_type = detect_1099_gig_income(t)
        if not is_gig:
            continue
        amt = abs(float(t.get("amount") or 0))
        d = (t.get("date") or t.get("authorized_date") or "")
        if not d:
            continue
        month = str(d)[:7]
        payer = _normalize_payer_name(t)

        bucket = per_payer.setdefault(payer, {
            "type":     source_type,
            "det_conf": det_conf,
            "monthly":  {},
        })
        # Promote to most-specific source_type if a later txn is more
        # confident; demote to worst-of detection confidence.
        if rank.get(det_conf, 0) < rank.get(bucket["det_conf"], 3):
            bucket["det_conf"] = det_conf
        if source_type and source_type != "other":
            bucket["type"] = source_type
        bucket["monthly"][month] = bucket["monthly"].get(month, 0.0) + amt
        monthly_totals[month] = monthly_totals.get(month, 0.0) + amt

    # Confidence baseline from freelance_account_separation.
    sep_baseline = {
        "separate_business_account": "high",
        "mixed_personal":            "medium",
        "unknown":                   "low",
    }.get(freelance_account_separation, "low")

    # Build income_sources list.
    sources_out: list = []
    min_months = _FL_DETECTION["min_months_per_source"]
    for payer, bucket in per_payer.items():
        months = sorted(bucket["monthly"].keys())
        if len(months) < min_months:
            # Skip single-occurrence payers — too noisy for aggregation.
            continue
        amounts = list(bucket["monthly"].values())
        n = len(amounts)
        mean = sum(amounts) / n
        if mean > 0:
            variance = sum((x - mean) ** 2 for x in amounts) / n
            std = variance ** 0.5
            cv = min(1.0, std / mean)
        else:
            cv = 0.0
        # Per-source confidence = min(detection-confidence,
        #                              account-separation-baseline).
        det_conf = bucket["det_conf"]
        per_source_conf = min(
            (det_conf, sep_baseline),
            key=lambda c: rank.get(c, 0),
        )
        sources_out.append({
            "source_type":            bucket["type"] or "other",
            "name":                   payer,
            "monthly_average":        round(mean, 2),
            "volatility_coefficient": round(cv, 3),
            "is_seasonal":            False,   # 5b.3: defer; needs multi-year history
            "confidence":             per_source_conf,
        })

    return sources_out, monthly_totals


def compute_freelance_volatility(monthly_totals: dict) -> tuple:
    """Compute coefficient-of-variation of monthly gig income.

    Args: monthly_totals — dict {YYYY-MM: total_gig_income}.

    Returns: (volatility_coefficient | None, months_count, confidence,
              source).

    Honest data architecture: when months_count <
    `min_history_months_for_volatility` (3), returns
    (None, count, "missing", "manual_entry_required") with a note.
    Don't fabricate volatility from sparse data.
    """
    months = sorted(monthly_totals.keys())
    n = len(months)
    min_n = _FL_DETECTION["min_history_months_for_volatility"]
    if n < min_n:
        return (None, n, "missing", "manual_entry_required")
    amounts = [monthly_totals[m] for m in months]
    mean = sum(amounts) / n
    if mean <= 0:
        return (None, n, "missing", "manual_entry_required")
    variance = sum((x - mean) ** 2 for x in amounts) / n
    std = variance ** 0.5
    cv = min(1.0, std / mean)
    return (round(cv, 3), n, "high", "plaid_freelance_volatility_computed")


def _fl_volatility_unavailable(months_count: int) -> MappedField:
    """Build the manual-entry-required MappedField for volatility when
    history is insufficient. Mirrors the AR/AP pattern from 5a.3."""
    return MappedField(
        value=None,
        confidence="missing",
        source="manual_entry_required",
        notes=(
            f"Volatility computation requires at least "
            f"{_FL_DETECTION['min_history_months_for_volatility']} "
            f"months of income history; current history has "
            f"{months_count} month(s). Add this manually or wait for "
            "more transaction history to accumulate."
        ),
    )


def _ar_ap_manual_entry_required(field_name: str) -> MappedField:
    """Build a missing-by-design MappedField for AR/AP fields.

    Plaid does NOT deliver receivables-aging or accounts-payable data —
    that information lives in accounting software (QuickBooks, Xero,
    FreshBooks). Inferring it from transaction patterns is fragile and
    low-confidence (per RELIUS_STRATEGY.md §1.4: dignity over flattery
    applied at the data layer). Surface the gap honestly with a
    manual-entry path; do not pretend.

    The frontend will key on `source="manual_entry_required"` to render
    a "Add this manually" affordance instead of an empty data row.
    """
    return MappedField(
        value=None,
        confidence="missing",
        source="manual_entry_required",
        notes=(f"Plaid does not provide {field_name} data; "
               "requires accounting platform integration or manual entry."),
    )


def _all_missing(reason: str, sources: Optional[list] = None) -> MappedFields:
    """Build a MappedFields where every Plaid-mappable field is missing
    with the same note. AR/AP stay on their explicit manual-entry
    provenance (NOT the generic 'unavailable' source) since they're
    missing-by-design rather than missing-by-data-failure.
    """
    mf = lambda: MappedField(value=None, confidence="missing",
                             source="unavailable", notes=reason)
    return MappedFields(
        I_net=mf(), E_ess=mf(), S_liq=mf(), S_ret=mf(),
        D_hi=mf(),  D_lo=mf(),  D_min=mf(),
        business_lines_of_credit=MappedField(
            value=[], confidence="missing", source="no_loc_accounts",
            notes="No business lines of credit detected.",
        ),
        ar_aging_buckets=_ar_ap_manual_entry_required("AR aging"),
        ap_pending=_ar_ap_manual_entry_required("AP pending"),
        # Phase 5b.3 FL fields — empty defaults; populated by
        # map_plaid_data only when archetype="freelancer".
        income_sources=MappedField(
            value=[], confidence="missing",
            source="no_freelance_detection_run",
            notes="Freelancer-specific detection runs only when "
                  "archetype='freelancer'.",
        ),
        income_volatility_observed=_fl_volatility_unavailable(0),
        months_of_income_history=MappedField(
            value=0, confidence="high",
            source="no_freelance_detection_run",
            notes="",
        ),
        sources=sources or [],
    )


def _normalize_to_items(fetch_response: dict) -> list[dict]:
    """Accept either the multi-bank shape (`items: [...]`) or the legacy
    single-bank shape (top-level `accounts`/`transactions`/...) and
    return a list of items. The single-bank case is wrapped into a
    one-element list so downstream code only handles one shape."""
    if isinstance(fetch_response.get("items"), list):
        return list(fetch_response["items"])
    # Legacy single-bank shape — wrap.
    if any(k in fetch_response for k in
           ("accounts", "transactions", "liabilities", "investments", "recurring")):
        return [fetch_response]
    return []


# ─────────────────────────────────────────────────────────────────────
# Top-level orchestrator
# ─────────────────────────────────────────────────────────────────────

def map_plaid_data(fetch_response: dict,
                   archetype: str = "individual_w2") -> MappedFields:
    """Convert a /plaid/fetch response into mapped IndividualInput fields
    with confidence flags. Pure function — no I/O.

    Accepts BOTH shapes:
      • Multi-bank (P4-4):   {session_id, items: [{accounts, transactions, …}, …]}
      • Legacy single-bank:  {accounts, transactions, liabilities, investments, recurring}

    Phase 5a.3 — `archetype` param routes business-credit-card
    inclusion (Individual excludes; Small Business includes) and adds
    SB-specific output fields (`business_lines_of_credit`,
    `ar_aging_buckets`, `ap_pending`). Defaults to `"individual_w2"` so
    existing callers see no behavior change. The fetch_response dict
    can also carry `archetype` at top-level — kwarg takes precedence
    when both are present.

    Cross-institution behavior:
      - Currency safety check runs across ALL accounts in ALL items first.
        Any non-USD currency anywhere → all 7 fields drop to missing.
      - Stocks (S_liq, S_ret) sum across institutions.
      - Liabilities (D_hi, D_lo, D_min) sum across institutions.
      - Income (I_net) concatenates inflow_streams across all items
        before applying filters and frequency conversion. A paycheck
        only appears in its destination bank — no double-count risk.
      - Expenses (E_ess) concatenate transactions before grouping by
        month. Credit-card payments (LOAN_PAYMENTS / CREDIT_CARD_*)
        are excluded so paying card-A from checking-B isn't counted.
    """
    if not isinstance(fetch_response, dict):
        return _all_missing("Plaid response was not a dict.")
    # Allow fetch_response.archetype as a fallback when caller didn't
    # pass the kwarg explicitly. Kwarg always wins when set.
    if archetype == "individual_w2":
        archetype = fetch_response.get("archetype", "individual_w2")

    items = _normalize_to_items(fetch_response)

    # Build sources skeleton early so we can return _all_missing with it.
    sources_skeleton: list[MapSource] = []
    for it in items:
        sources_skeleton.append(MapSource(
            item_id=it.get("item_id", ""),
            institution_name=it.get("institution_name") or "Unknown bank",
            contributed_to=[],
        ))

    # ── Currency safety check FIRST (applies cross-institution) ─────
    cur_issue = _detect_currency_issue_in_items(items)
    if cur_issue:
        return _all_missing(cur_issue, sources=sources_skeleton)

    # Concatenate every product slice across items.
    all_accounts: list = []
    all_transactions: list = []
    all_liabilities: list = []     # list of per-item liabilities dicts
    all_investments: list = []     # list of per-item investments dicts
    all_recurring_streams: list = []
    any_liabilities_avail = False
    any_investments_avail = False
    any_recurring_avail   = False

    # Per-item contribution flags so we can populate `sources.contributed_to`
    # without re-running mappers.
    item_contrib: dict[int, set[str]] = {i: set() for i in range(len(items))}

    for idx, it in enumerate(items):
        acc_section = it.get("accounts") or {}
        if acc_section.get("available"):
            for a in (acc_section.get("data") or {}).get("accounts") or []:
                a = dict(a); a["_item_idx"] = idx
                all_accounts.append(a)

        txn_section = it.get("transactions") or {}
        if txn_section.get("available"):
            for t in (txn_section.get("data") or []):
                t = dict(t); t["_item_idx"] = idx
                all_transactions.append(t)

        liab_section = it.get("liabilities") or {}
        if liab_section.get("available"):
            any_liabilities_avail = True
            inner = _extract_inner_liabilities(liab_section)
            if inner is not None:
                all_liabilities.append(inner)

        inv_section = it.get("investments") or {}
        if inv_section.get("available") and inv_section.get("data"):
            any_investments_avail = True
            all_investments.append(inv_section["data"])

        rec_section = it.get("recurring") or {}
        if rec_section.get("available") and rec_section.get("data"):
            any_recurring_avail = True
            for s in (rec_section["data"].get("inflow_streams") or []):
                s = dict(s); s["_item_idx"] = idx
                all_recurring_streams.append(s)

    # Sentinel: nothing connected at all.
    if not items:
        return _all_missing("No connected banks found in this session.")

    # Per-field mapping over the concatenated views.
    s_liq = map_s_liq(all_accounts, archetype=archetype)
    s_ret = map_s_ret(all_accounts,
                      _merge_investment_holdings(all_investments),
                      investments_available=any_investments_avail)
    merged_liab = _merge_liabilities(all_liabilities) if all_liabilities else None
    d_hi, d_lo, d_min = map_liabilities(
        merged_liab,
        all_accounts,
        liabilities_available=any_liabilities_avail,
        liabilities_records_present=bool(all_liabilities),
        archetype=archetype,
    )

    # ── Phase 5a.3 SB extension fields ──────────────────────────────
    # Business LOCs are detected from the merged accounts list; AR/AP
    # are missing-by-design (manual entry surface).
    business_loc_field = map_business_lines_of_credit(
        all_accounts, merged_liab,
    )
    ar_field = _ar_ap_manual_entry_required("AR aging")
    ap_field = _ar_ap_manual_entry_required("AP pending")

    # Phase 5a.5: per-account detection results — surfaced for the
    # detection_override recommendation layer.
    detections: list = []
    for acc in all_accounts:
        is_biz, conf, source = detect_business_account(acc)
        if is_biz:
            detections.append({
                "account_id":   acc.get("account_id", ""),
                "account_name": acc.get("name") or acc.get("official_name") or "Unnamed",
                "is_business":  True,
                "confidence":   conf,
                "source":       source,
            })

    # Phase 5b.3 — Freelancer-specific income detection. Runs ONLY when
    # archetype="freelancer". For Individual / Small Business archetypes
    # the FL fields stay at their no-detection-run defaults so the
    # output contract is consistent across archetypes.
    fl_income_sources_field = MappedField(
        value=[], confidence="missing",
        source="no_freelance_detection_run",
        notes="Freelancer-specific detection runs only when "
              "archetype='freelancer'.",
    )
    fl_volatility_field = _fl_volatility_unavailable(0)
    fl_history_field = MappedField(
        value=0, confidence="high",
        source="no_freelance_detection_run", notes="",
    )
    if archetype == "freelancer":
        # Read user-disclosed account separation. The mapper doesn't
        # try to compute this — it's a user statement that gates
        # confidence ratings.
        sep = (fetch_response.get("freelance_account_separation")
               or "unknown")
        sources_list, monthly_totals = aggregate_freelance_income(
            all_transactions, sep,
        )
        # Income-sources field — confidence is worst-of across detected
        # sources (P4-H4 worst-of-streams rule).
        if sources_list:
            rank = {"high": 3, "medium": 2, "low": 1, "missing": 0}
            agg_conf = min(
                (s.get("confidence", "low") for s in sources_list),
                key=lambda c: rank.get(c, 0),
            )
            fl_income_sources_field = MappedField(
                value=sources_list,
                confidence=agg_conf,
                source="plaid_freelance_detection",
                notes=(f"{len(sources_list)} freelance income source(s) "
                       f"detected. Account separation: {sep}."),
            )
        else:
            fl_income_sources_field = MappedField(
                value=[], confidence="missing",
                source="manual_entry_required",
                notes=("No 1099/gig income deposits detected in "
                       "transaction history. If you have freelance "
                       "income, add your sources manually."),
            )
        # Volatility — only computed with sufficient history.
        vol_value, months_count, vol_conf, vol_source = (
            compute_freelance_volatility(monthly_totals)
        )
        if vol_value is None:
            fl_volatility_field = _fl_volatility_unavailable(months_count)
        else:
            fl_volatility_field = MappedField(
                value=vol_value,
                confidence=vol_conf,
                source=vol_source,
                notes=(f"Coefficient-of-variation across "
                       f"{months_count} months of detected gig income."),
            )
        fl_history_field = MappedField(
            value=months_count, confidence="high",
            source="plaid_freelance_history_count",
            notes="",
        )
    i_net = map_monthly_income(
        {"inflow_streams": all_recurring_streams} if any_recurring_avail else None,
        all_transactions,
        recurring_available=any_recurring_avail,
    )
    e_ess = map_monthly_expenses(all_transactions)

    # ── Build sources provenance ─────────────────────────────────────
    # An item "contributes to" a field if its data was non-empty for that
    # field AND the resulting mapped field has a value (not missing).
    for idx, it in enumerate(items):
        contribs = item_contrib[idx]
        acc_section = it.get("accounts") or {}
        accounts = (acc_section.get("data") or {}).get("accounts") or [] if acc_section.get("available") else []
        if any((a.get("type") or "").lower() == "depository" and
               (a.get("subtype") or "").lower() in _LIQUID_SUBTYPES
               for a in accounts) and s_liq.value not in (None, 0):
            contribs.add("S_liq")
        if any((a.get("type") or "").lower() in _INVESTMENT_TYPES for a in accounts) and s_ret.value not in (None, 0):
            contribs.add("S_ret")
        liab_section = it.get("liabilities") or {}
        inner = _extract_inner_liabilities(liab_section) if liab_section.get("available") else None
        if inner is not None:
            if inner.get("credit") and d_hi.value not in (None, 0):
                contribs.add("D_hi")
            if (inner.get("student") or inner.get("mortgage")) and d_lo.value not in (None, 0):
                contribs.add("D_lo")
            if (inner.get("credit") or inner.get("student") or inner.get("mortgage")) and d_min.value not in (None, 0):
                contribs.add("D_min")
        rec_section = it.get("recurring") or {}
        if rec_section.get("available") and rec_section.get("data") and i_net.value not in (None, 0):
            if (rec_section["data"].get("inflow_streams") or []):
                contribs.add("I_net")
        # If recurring missing but heuristic income used, attribute to whichever
        # item had the qualifying inflow transactions.
        elif i_net.value not in (None, 0) and i_net.source.startswith("heuristic"):
            txn_section = it.get("transactions") or {}
            if txn_section.get("available"):
                for t in (txn_section.get("data") or []):
                    amt = t.get("amount")
                    pfc = t.get("personal_finance_category") or {}
                    primary = ((pfc.get("primary") or "").upper()
                               if isinstance(pfc, dict) else "")
                    if (amt is not None
                            and float(amt) < 0 and abs(float(amt)) >= 500
                            and primary in _INCOME_PRIMARY_WHITELIST):
                        contribs.add("I_net")
                        break
        # E_ess: any item with outflow transactions contributes
        txn_section = it.get("transactions") or {}
        if txn_section.get("available") and e_ess.value not in (None, 0):
            for t in (txn_section.get("data") or []):
                amt = t.get("amount")
                if amt is not None and float(amt) > 0 and not _is_excluded_outflow(t):
                    contribs.add("E_ess")
                    break

    sources = []
    for idx, it in enumerate(items):
        sources.append(MapSource(
            item_id=it.get("item_id", ""),
            institution_name=it.get("institution_name") or "Unknown bank",
            contributed_to=sorted(item_contrib[idx]),
        ))

    return MappedFields(
        I_net=i_net, E_ess=e_ess,
        S_liq=s_liq, S_ret=s_ret,
        D_hi=d_hi,   D_lo=d_lo,   D_min=d_min,
        business_lines_of_credit=business_loc_field,
        ar_aging_buckets=ar_field,
        ap_pending=ap_field,
        business_detections=detections,
        income_sources=fl_income_sources_field,
        income_volatility_observed=fl_volatility_field,
        months_of_income_history=fl_history_field,
        sources=sources,
    )


def _extract_inner_liabilities(liab_section: dict) -> Optional[dict]:
    """Pull the credit/student/mortgage dict out of a /liabilities/get response.

    Plaid's real wire shape wraps liabilities doubly:
        liabilities.data.liabilities.{credit,student,mortgage}[]
    Synthetic test fixtures historically used a flatter shape:
        liabilities.data.{credit,student,mortgage}[]
    Both are accepted. Returns None if neither shape is present (the
    "available reported but malformed" case)."""
    data = liab_section.get("data") or {}
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("liabilities"), dict):
        return data["liabilities"]
    if any(k in data for k in ("credit", "student", "mortgage")):
        return data
    return None


def _merge_liabilities(liabilities_list: list[dict]) -> dict:
    """Concatenate per-item liabilities dicts into one dict the existing
    map_liabilities() function understands."""
    out = {"credit": [], "student": [], "mortgage": []}
    for L in liabilities_list:
        for key in ("credit", "student", "mortgage"):
            entries = L.get(key) or []
            out[key].extend(entries)
    return out


def _merge_investment_holdings(investments_list: list[dict]) -> dict:
    """Concatenate per-item /investments/holdings/get dicts."""
    out = {"holdings": [], "securities": [], "accounts": []}
    for inv in investments_list:
        for key in ("holdings", "securities", "accounts"):
            entries = inv.get(key) or []
            out[key].extend(entries)
    return out


# ─────────────────────────────────────────────────────────────────────
# Per-field mappers — each function is independently testable.
# Stubs for now; subsequent subsections fill these in.
# ─────────────────────────────────────────────────────────────────────

_LIQUID_SUBTYPES = {"checking", "savings", "money market", "cash management", "hsa"}
# Phase 5a.3: SB archetype additionally counts business depository
# subtypes as liquid reserve. For Individual archetype, business
# accounts stay out (the surfaces don't bleed into each other — the
# 5a.3 separation rule).
_LIQUID_SUBTYPES_SB = _LIQUID_SUBTYPES | {
    "business checking", "business savings", "business money market",
}


def map_s_liq(accounts: list,
              archetype: str = "individual_w2") -> MappedField:
    """Sum balances.current across depository accounts of liquid subtypes.
    CDs are deliberately excluded — they're not actually accessible.
    HSAs ARE counted as liquid (medically restricted but withdraw-able);
    a note flags this so users with non-medical-spending HSAs can adjust.

    Phase 5a.3: For Small Business archetype, business depository
    subtypes (business checking / savings / money market) are included
    in the liquid sum. For Individual archetype, those stay out —
    business accounts don't bleed into personal liquid reserve.
    """
    if not accounts:
        return MappedField(
            value=None, confidence="missing", source="plaid_balance_get",
            notes="No accounts found in Plaid response.",
        )

    liquid_set = _LIQUID_SUBTYPES_SB if archetype == "small_business" else _LIQUID_SUBTYPES
    total = 0.0
    matched = 0
    has_hsa = False
    for acct in accounts:
        if (acct.get("type") or "").lower() != "depository":
            continue
        sub = (acct.get("subtype") or "").lower()
        if sub not in liquid_set:
            continue
        bal = ((acct.get("balances") or {}).get("current"))
        if bal is None:
            continue
        total += float(bal)
        matched += 1
        if sub == "hsa":
            has_hsa = True

    if matched == 0:
        return MappedField(
            value=None, confidence="missing", source="plaid_balance_get",
            notes="No liquid depository accounts (checking/savings) detected.",
        )
    notes = ""
    if has_hsa:
        notes = ("HSA balance is included as liquid savings. "
                 "If you only use yours for medical expenses, "
                 "subtract that amount from your liquid savings.")
    return MappedField(
        value=round(total, 2), confidence="high",
        source="plaid_balance_get", notes=notes,
    )


_INVESTMENT_TYPES = {"investment", "brokerage"}    # plaid type field


def map_s_ret(accounts: list, investments: Optional[dict],
              investments_available: bool) -> MappedField:
    """Sum retirement / investment balances.

    Two paths to total: (1) account-level — sum balances.current across
    investment-typed accounts; (2) holdings-level — sum holdings[].institution_value
    from /investments/holdings/get. Use account-level as primary; cross-check
    with holdings when both are available.

    Always carries the 401k-coverage note since Plaid is known to miss
    workplace plans even when other investment accounts come through cleanly.
    """
    workplace_note = ("Plaid may not capture employer-sponsored 401(k) "
                      "plans. Add manually if missing.")

    # Account-level total
    acct_total = 0.0
    acct_matched = 0
    for acct in (accounts or []):
        t = (acct.get("type") or "").lower()
        if t in _INVESTMENT_TYPES:
            bal = ((acct.get("balances") or {}).get("current"))
            if bal is not None:
                acct_total += float(bal)
                acct_matched += 1

    # Holdings-level total (only if /investments returned data)
    holdings_total = None
    if investments_available and investments:
        holdings = investments.get("holdings") or []
        if holdings:
            ht = 0.0
            for h in holdings:
                v = h.get("institution_value")
                if v is not None:
                    ht += float(v)
            holdings_total = ht

    # Decision tree
    if acct_matched == 0 and holdings_total is None:
        return MappedField(
            value=None, confidence="missing", source="plaid_balance_get",
            notes=("No investment accounts detected via Plaid. " + workplace_note),
        )

    if acct_matched > 0 and holdings_total is not None:
        # Both available — cross-check.
        if acct_total > 0 and abs(holdings_total - acct_total) / max(acct_total, 1.0) <= 0.05:
            return MappedField(
                value=round(acct_total, 2), confidence="high",
                source="plaid_balance_get", notes=workplace_note,
            )
        # Disagreement > 5% — keep account-level but note the gap.
        return MappedField(
            value=round(acct_total, 2), confidence="medium",
            source="plaid_balance_get",
            notes=(f"Account-level balance (${acct_total:,.0f}) and Plaid "
                   f"holdings sum (${holdings_total:,.0f}) disagree. "
                   + workplace_note),
        )

    if acct_matched > 0:
        return MappedField(
            value=round(acct_total, 2), confidence="medium",
            source="plaid_balance_get",
            notes=("Investment holdings detail not available. " + workplace_note),
        )

    # Holdings-only (rare): no account-typed entries but holdings present.
    return MappedField(
        value=round(holdings_total or 0.0, 2), confidence="medium",
        source="plaid_investments_holdings",
        notes=("Account-level balance not available. " + workplace_note),
    )


def _liabilities_unavailable() -> tuple[MappedField, MappedField, MappedField]:
    note = ("Liabilities data not yet available from Plaid. "
            "Try reconnecting in a few minutes, or fill in manually.")
    mf = lambda: MappedField(value=None, confidence="missing",
                             source="plaid_liabilities_unavailable", notes=note)
    return mf(), mf(), mf()


def map_liabilities(liabilities: Optional[dict],
                    accounts: list,
                    liabilities_available: bool,
                    liabilities_records_present: Optional[bool] = None,
                    archetype: str = "individual_w2",
                    ) -> tuple[MappedField, MappedField, MappedField]:
    """Returns (D_hi, D_lo, D_min).

    Archetype-aware business credit card handling (Phase 5a.3):
      • `individual_w2` (default): business CCs (`holder_category="business"`)
        are EXCLUDED from D_hi / D_min — preserved P4-H1 behavior. The
        `business_excluded` count is surfaced in `notes` so users see
        the rationale.
      • `small_business`: business CCs are INCLUDED in D_hi / D_min as
        part of the business debt surface. The Plaid detection logic
        itself is unchanged from P4-H1 (still keys on
        `holder_category="business"` only); the inclusion/exclusion
        decision is what flips on archetype.
    Other archetypes (`freelancer`, `startup`) currently fall through
    to the Individual path until 5b/5d add their own treatment.

    D_hi = sum of credit-card balances. PERSONAL holders for Individual;
           ALL CCs (personal + business) for Small Business.
    D_lo = sum of student-loan + mortgage balances (cross-referenced to
           account.balances.current via account_id).
    D_min = sum of minimum_payment_amount across credit (personal only) +
            student (with last_payment_amount fallback) + last_payment_amount
            on mortgages (Plaid doesn't expose a min on mortgages — last
            payment is the conventional proxy).

    Three "no data" branches:
      1. liabilities_available=False → PRODUCT_NOT_READY message.
      2. liabilities_available=True but no inner records dict found
         (Plaid claims the product but the wire shape was malformed) →
         distinct "available but no records" missing message rather than
         silently emitting value=0/confidence=high (the P4-3→P4-4 bug).
      3. liabilities_available=True with proper inner dict (possibly with
         empty arrays — a legitimate "user has $0 in these debts" case).
    """
    if not liabilities_available:
        return _liabilities_unavailable()

    # Backward-compat: when caller doesn't pass `liabilities_records_present`,
    # infer from the dict (None or empty → no records).
    if liabilities_records_present is None:
        liabilities_records_present = bool(liabilities)

    if liabilities is None or not liabilities_records_present:
        note = ("Liabilities reported as available but no liability "
                "records were returned. Please enter manually if you have any.")
        mf = lambda: MappedField(value=None, confidence="missing",
                                 source="plaid_liabilities", notes=note)
        return mf(), mf(), mf()

    # Build account_id → balance, holder_category, and subtype lookups.
    bal_by_id: dict = {}
    holder_by_id: dict = {}
    subtype_by_id: dict = {}
    for a in (accounts or []):
        aid = a.get("account_id")
        if not aid:
            continue
        cur = ((a.get("balances") or {}).get("current"))
        if cur is not None:
            bal_by_id[aid] = float(cur)
        holder = (a.get("holder_category") or "").lower()
        holder_by_id[aid] = holder
        subtype_by_id[aid] = (a.get("subtype") or "").lower()

    credit_list   = liabilities.get("credit")   or []
    student_list  = liabilities.get("student")  or []
    mortgage_list = liabilities.get("mortgage") or []

    # P4-H1 + 5a.3: archetype-aware business CC inclusion.
    # Individual archetype EXCLUDES business CCs (preserves P4-H1).
    # Small Business archetype INCLUDES them as part of business debt.
    include_business_cc = (archetype == "small_business")
    business_excluded = 0
    business_included = 0

    # ── D_hi (credit cards) ─────────────────────────────────────────
    # Phase 5a.3: Plaid's `liabilities.credit` array includes ALL
    # credit-type liabilities, which means business lines of credit
    # (subtype="line of credit") show up here even though they're
    # surfaced separately in `business_lines_of_credit`. Filter them
    # out so we don't double-count: an LOC's $5,000 balance shouldn't
    # appear in BOTH the LOC field AND D_hi.
    d_hi_total = 0.0
    for c in credit_list:
        aid = c.get("account_id")
        if subtype_by_id.get(aid) == "line of credit":
            # LOCs belong to business_lines_of_credit, not D_hi.
            continue
        is_business_cc = holder_by_id.get(aid) == "business"
        if is_business_cc and not include_business_cc:
            business_excluded += 1
            continue
        if is_business_cc and include_business_cc:
            business_included += 1
        bal = bal_by_id.get(aid)
        if bal is None:
            # Liabilities object doesn't carry balance directly; fall
            # back to last_statement_balance if present.
            bal = c.get("last_statement_balance")
        if bal is not None:
            d_hi_total += float(bal)

    # ── D_lo (student + mortgage) ────────────────────────────────────
    d_lo_total = 0.0
    for s in student_list:
        aid = s.get("account_id")
        bal = bal_by_id.get(aid)
        if bal is None:
            bal = s.get("outstanding_interest_amount") or 0.0
        d_lo_total += float(bal or 0)

    for m in mortgage_list:
        aid = m.get("account_id")
        bal = bal_by_id.get(aid)
        if bal is not None:
            d_lo_total += float(bal)

    # ── D_min (personal CC only + student + mortgage proxy) ─────────
    d_min_total = 0.0
    used_fallback = False

    for c in credit_list:
        aid = c.get("account_id")
        if subtype_by_id.get(aid) == "line of credit":
            # Same de-dup as D_hi — LOC mins belong to the LOC surface.
            continue
        is_business_cc = holder_by_id.get(aid) == "business"
        if is_business_cc and not include_business_cc:
            continue
        m = c.get("minimum_payment_amount")
        if m is not None:
            d_min_total += float(m)

    # Student loans: minimum_payment_amount, fall back to last_payment_amount
    for s in student_list:
        m = s.get("minimum_payment_amount")
        if m is None:
            m = s.get("last_payment_amount")
            if m is not None:
                used_fallback = True
        if m is not None:
            d_min_total += float(m)

    # Mortgages: last_payment_amount (no minimum field exists)
    for m in mortgage_list:
        last = m.get("last_payment_amount")
        if last is not None:
            d_min_total += float(last)

    business_note = ""
    if business_excluded > 0:
        business_note = (f"{business_excluded} business credit card(s) "
                          "excluded from personal debt totals.")
    elif business_included > 0:
        business_note = (f"{business_included} business credit card(s) "
                          "included as small-business archetype debt.")

    d_hi = MappedField(
        value=round(d_hi_total, 2),
        confidence="high",
        source="plaid_liabilities",
        notes=business_note,
    )
    d_lo = MappedField(
        value=round(d_lo_total, 2),
        confidence="high",
        source="plaid_liabilities",
    )
    fallback_note = ("Some minimum payments fell back to last-payment amount."
                     if used_fallback else "")
    d_min_notes = " ".join(n for n in (fallback_note, business_note) if n)
    d_min = MappedField(
        value=round(d_min_total, 2),
        confidence=("medium" if used_fallback else "high"),
        source="plaid_liabilities",
        notes=d_min_notes,
    )
    return d_hi, d_lo, d_min


_FREQ_TO_MONTHLY = {
    "WEEKLY":      52 / 12,    # ≈ 4.333
    "BIWEEKLY":    26 / 12,    # ≈ 2.167
    "SEMI_MONTHLY": 2.0,
    "MONTHLY":     1.0,
    "ANNUALLY":    1 / 12,
}


def _stream_categories(stream: dict) -> set[str]:
    """Aggregate every category-ish string on a stream into one set, upper-cased.
    Recurring streams expose `personal_finance_category` (preferred) and
    `category` (legacy)."""
    out = set()
    pfc = stream.get("personal_finance_category") or {}
    if isinstance(pfc, dict):
        for k in ("primary", "detailed"):
            v = pfc.get(k)
            if v: out.add(str(v).upper())
    cats = stream.get("category") or []
    if isinstance(cats, list):
        for c in cats:
            if c: out.add(str(c).upper())
    return out


def _is_excluded_inflow(stream: dict, monthly_amount: float) -> bool:
    """Return True if a recurring inflow stream should be excluded from
    income totals — transfers, tax refunds, small interest/dividends."""
    cats = _stream_categories(stream)
    if any("TRANSFER" in c for c in cats):
        return True
    if any("TAX_REFUND" in c for c in cats):
        return True
    if any("INTEREST" in c or "DIVIDEND" in c for c in cats) and monthly_amount < 100:
        return True
    return False


def map_monthly_income(recurring: Optional[dict],
                       transactions: list,
                       recurring_available: bool) -> MappedField:
    """Detect monthly net income from Plaid.

    Primary path: /transactions/recurring/get inflow streams. The most
    reliable signal — Plaid has already grouped repeating deposits.

    Sign convention: Plaid's recurring inflow `average_amount.amount`
    is NEGATIVE (the entry is an account inflow, accounting-positive).
    We `abs()` it before summing.

    Fallback: if recurring is unavailable or yields zero qualifying
    streams, use a transaction-history heuristic (largest inflow per
    month, last 3 months).
    """
    if not recurring_available or not isinstance(recurring, dict):
        return _income_heuristic_fallback(
            transactions,
            preface_note=("Recurring transactions data not yet available "
                          "from Plaid. "),
        )

    streams = recurring.get("inflow_streams") or []
    if not streams:
        return _income_heuristic_fallback(
            transactions,
            preface_note=("No recurring inflow streams detected. "),
        )

    monthly_total = 0.0
    any_early_detection = False
    kept = 0
    excluded_transfers = 0
    skipped_unknown_freq = 0

    for s in streams:
        status = (s.get("status") or "").upper()
        if status == "TOMBSTONED":
            continue   # stream has stopped — stop counting it
        # average_amount.amount is negative for inflows
        avg = (s.get("average_amount") or {}).get("amount")
        if avg is None:
            continue
        freq = (s.get("frequency") or "").upper()
        if freq not in _FREQ_TO_MONTHLY:
            skipped_unknown_freq += 1
            continue
        monthly = abs(float(avg)) * _FREQ_TO_MONTHLY[freq]
        if _is_excluded_inflow(s, monthly):
            excluded_transfers += 1
            continue
        monthly_total += monthly
        if status == "EARLY_DETECTION":
            any_early_detection = True
        kept += 1

    if kept == 0:
        # All streams were excluded — fall back to transaction heuristic
        # rather than reporting $0 income (which would be misleading).
        return _income_heuristic_fallback(
            transactions,
            preface_note=("Recurring streams found but none qualified as "
                          "income (transfers / tax refunds excluded). "),
        )

    confidence: Confidence = "medium" if any_early_detection else "high"
    source = ("plaid_recurring_early_detection"
              if any_early_detection
              else "plaid_recurring_mature")
    notes_bits = []
    if excluded_transfers:
        notes_bits.append(f"{excluded_transfers} stream(s) excluded as transfer/refund.")
    if skipped_unknown_freq:
        notes_bits.append(f"{skipped_unknown_freq} stream(s) skipped (unknown frequency).")
    if any_early_detection:
        notes_bits.append("Some streams are still being learned by Plaid; "
                          "verify amount.")
    return MappedField(
        value=round(monthly_total, 2),
        confidence=confidence,
        source=source,
        notes=" ".join(notes_bits),
    )


_INCOME_PRIMARY_WHITELIST = {"INCOME", "DEPOSITS"}
# Defensive blacklist — anything in here is definitively NOT income.
# In practice the whitelist alone handles every case; this list documents
# the most common false-positive categories observed during sandbox
# testing (United refunds = TRAVEL, internal interest = TRANSFER_IN, etc.).
_INCOME_PRIMARY_BLACKLIST = {
    "TRANSFER_IN", "TRANSFER_OUT",
    "TRAVEL", "GENERAL_MERCHANDISE",
    "FOOD_AND_DRINK", "ENTERTAINMENT",
    "LOAN_PAYMENTS", "BANK_FEES",
}


def _income_heuristic_fallback(transactions: list, preface_note: str = "") -> MappedField:
    """Largest-inflow-per-month, last 3 months. Plaid amount sign is
    POSITIVE for outflows, NEGATIVE for inflows — filter `amount < 0`.

    Category whitelist applied: only transactions whose
    `personal_finance_category.primary` is in {INCOME, DEPOSITS} qualify
    as income. This is the filter that prevents flight/retail refunds and
    internal transfers from being mistaken for paychecks (the sandbox
    United Airlines refund case from P4-3 live testing)."""
    if not transactions:
        return MappedField(
            value=None, confidence="missing", source="unavailable",
            notes=(preface_note +
                   "No income signal detected in available data. "
                   "Please enter manually."),
        )

    # Group eligible inflows by YYYY-MM
    by_month: dict[str, list[float]] = defaultdict(list)
    for t in transactions:
        if t.get("pending"):
            continue
        amt = t.get("amount")
        if amt is None:
            continue
        try:
            amt = float(amt)
        except (TypeError, ValueError):
            continue
        # NEGATIVE = inflow per Plaid convention. abs() to compare magnitudes.
        if amt >= 0:
            continue
        magnitude = abs(amt)
        if magnitude < 500:        # filter small refunds / micro-deposits
            continue
        # Category whitelist: only INCOME / DEPOSITS qualify. The
        # blacklist is defensive — should be redundant given the
        # whitelist, but documents intent for future Plaid taxonomy
        # additions.
        pfc = t.get("personal_finance_category") or {}
        primary = ((pfc.get("primary") or "").upper()
                   if isinstance(pfc, dict) else "")
        if primary in _INCOME_PRIMARY_BLACKLIST:
            continue
        if primary not in _INCOME_PRIMARY_WHITELIST:
            continue
        d = t.get("date") or t.get("authorized_date")
        if not d:
            continue
        # `date` is YYYY-MM-DD string from .to_dict() coercion
        try:
            month = str(d)[:7]
        except Exception:
            continue
        by_month[month].append(magnitude)

    if not by_month:
        return MappedField(
            value=None, confidence="missing", source="unavailable",
            notes=(preface_note +
                   "No qualifying inflows found in transaction history. "
                   "Please enter manually."),
        )

    # Sort months descending, take up to last 3
    sorted_months = sorted(by_month.keys(), reverse=True)[:3]
    largest_per_month = [max(by_month[m]) for m in sorted_months]

    if len(largest_per_month) >= 3:
        avg = sum(largest_per_month) / 3
        # Within-20% consistency check
        max_v = max(largest_per_month); min_v = min(largest_per_month)
        spread = (max_v - min_v) / max(avg, 1.0)
        if spread <= 0.20:
            return MappedField(
                value=round(avg, 2),
                confidence="low",
                source="heuristic_3mo_max_inflow",
                notes=(preface_note +
                       "Income estimated from transaction history; please verify."),
            )
        # Spread too wide — still use the average but flag it harder
        return MappedField(
            value=round(avg, 2),
            confidence="low",
            source="heuristic_3mo_max_inflow",
            notes=(preface_note +
                   "Income estimate is volatile across recent months — "
                   "please verify."),
        )

    # < 3 months of data
    estimate = max(largest_per_month)
    return MappedField(
        value=round(estimate, 2),
        confidence="low",
        source="heuristic_1mo_estimate",
        notes=(preface_note +
               "Income estimated from limited transaction history. "
               "Verification strongly recommended."),
    )


def _txn_categories(t: dict) -> set[str]:
    """Aggregate every category-ish string on a transaction. Recent Plaid
    payloads carry both `personal_finance_category.{primary,detailed}`
    AND legacy `category[]` — we check all of them."""
    out = set()
    pfc = t.get("personal_finance_category") or {}
    if isinstance(pfc, dict):
        for k in ("primary", "detailed"):
            v = pfc.get(k)
            if v: out.add(str(v).upper())
    cats = t.get("category") or []
    if isinstance(cats, list):
        for c in cats:
            if c: out.add(str(c).upper())
    return out


def _is_excluded_outflow(t: dict) -> bool:
    """Exclude transfers and debt payments from expense totals — counting
    those would either double-count against D_min or inflate expenses with
    flow that's already accounted for elsewhere."""
    cats = _txn_categories(t)
    for marker in ("TRANSFER_OUT", "LOAN_PAYMENTS",
                   "CREDIT_CARD_PAYMENT", "CREDIT_CARD"):
        if any(marker in c for c in cats):
            return True
    return False


def map_monthly_expenses(transactions: list) -> MappedField:
    """Aggregate non-transfer outflows by month and average over the last
    3 complete months.

    Sign convention reminder: Plaid `amount > 0` = outflow. We filter to
    positives, drop pending, drop transfer/loan-payment categories.
    """
    if not transactions:
        return MappedField(
            value=None, confidence="missing", source="unavailable",
            notes="No transaction history available — please enter manually.",
        )

    by_month: dict[str, float] = defaultdict(float)
    for t in transactions:
        if t.get("pending"):
            continue
        amt = t.get("amount")
        if amt is None:
            continue
        try:
            amt = float(amt)
        except (TypeError, ValueError):
            continue
        if amt <= 0:           # negatives are inflows; we only count outflows
            continue
        if _is_excluded_outflow(t):
            continue
        d = t.get("date") or t.get("authorized_date")
        if not d:
            continue
        month = str(d)[:7]
        by_month[month] += amt

    if not by_month:
        return MappedField(
            value=0.0, confidence="low", source="transactions_zero",
            notes=("No spending detected — please verify. (Often a sign that "
                   "your day-to-day account isn't connected here.)"),
        )

    months_sorted = sorted(by_month.keys(), reverse=True)

    if len(months_sorted) >= 3:
        recent_3 = months_sorted[:3]
        avg = sum(by_month[m] for m in recent_3) / 3
        return MappedField(
            value=round(avg, 2),
            confidence="medium",
            source="transactions_3mo_avg",
            notes=("Category data has known gaps — please review and "
                   "adjust if your essentials look off."),
        )

    # 1–2 months only
    most_recent = by_month[months_sorted[0]]
    return MappedField(
        value=round(most_recent, 2),
        confidence="low",
        source="transactions_recent_month",
        notes="Expense estimate based on limited history — please verify.",
    )
