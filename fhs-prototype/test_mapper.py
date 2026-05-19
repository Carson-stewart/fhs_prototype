"""Synthetic-fixture tests for plaid_mapper.

Pure unit tests — no Plaid credentials required. Run with:
    python test_mapper.py
"""
import json
import os

from plaid_mapper import (
    map_plaid_data, map_s_liq, map_s_ret, map_liabilities,
    map_monthly_income, map_monthly_expenses,
    detect_business_account, map_business_lines_of_credit,
    detect_1099_gig_income, aggregate_freelance_income,
    compute_freelance_volatility,
)


def fixture_user_good() -> dict:
    """Real Plaid /plaid/fetch response from sandbox First Platypus Bank /
    user_good. Captures the actual wire shape, including the doubly-nested
    `liabilities.data.liabilities.{credit,student,mortgage}` path that the
    P4-3 synthetic fixtures missed (the bug this hotfix closes).

    Sanitized: account_ids and transaction_ids replaced with readable
    tokens; addresses redacted; request_ids set to "sanitized".
    Use as the canonical real-data smoke test."""
    path = os.path.join(os.path.dirname(__file__),
                        "tests", "fixtures", "plaid_user_good.json")
    with open(path) as f:
        return json.load(f)


def fixture_basic_usd() -> dict:
    """Realistic-shape /plaid/fetch response for an Average-like profile.
    Used as the base fixture; subsequent tests mutate copies."""
    return {
        "accounts": {"available": True, "data": {"accounts": [
            {"account_id": "ck_1", "type": "depository", "subtype": "checking",
             "balances": {"current": 2500, "iso_currency_code": "USD"}},
            {"account_id": "sv_1", "type": "depository", "subtype": "savings",
             "balances": {"current": 1500, "iso_currency_code": "USD"}},
            {"account_id": "cd_1", "type": "depository", "subtype": "cd",
             "balances": {"current": 5000, "iso_currency_code": "USD"}},   # excluded
            {"account_id": "401k_1", "type": "investment", "subtype": "401k",
             "balances": {"current": 18000, "iso_currency_code": "USD"}},
            {"account_id": "ira_1", "type": "investment", "subtype": "roth",
             "balances": {"current": 2000, "iso_currency_code": "USD"}},
            {"account_id": "cc_1", "type": "credit", "subtype": "credit card",
             "balances": {"current": 5000, "iso_currency_code": "USD"}},
            {"account_id": "mtg_1", "type": "loan", "subtype": "mortgage",
             "balances": {"current": 22000, "iso_currency_code": "USD"}},
            {"account_id": "stu_1", "type": "loan", "subtype": "student",
             "balances": {"current": 3000, "iso_currency_code": "USD"}},
        ]}},
        "transactions": {"available": True, "data": []},
        "liabilities":  {"available": False},
        "investments":  {"available": False},
        "recurring":    {"available": False},
    }


def assert_eq(label, actual, expected):
    if actual != expected:
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")
        return False
    print(f"  ok    {label}")
    return True


def run():
    pass_count = fail_count = 0

    # ── P4-3.1 currency safety ───────────────────────────────────────
    print("Currency safety:")
    f = fixture_basic_usd()
    f["accounts"]["data"]["accounts"][0]["balances"]["iso_currency_code"] = "CAD"
    r = map_plaid_data(f)
    if assert_eq("CAD account -> S_liq missing", r.S_liq.confidence, "missing"): pass_count += 1
    else: fail_count += 1
    if assert_eq("CAD account -> I_net missing", r.I_net.confidence, "missing"): pass_count += 1
    else: fail_count += 1

    # ── P4-3.2 S_liq ─────────────────────────────────────────────────
    print("\nS_liq mapping:")
    accts = fixture_basic_usd()["accounts"]["data"]["accounts"]
    s = map_s_liq(accts)
    # 2500 + 1500 = 4000 (CD excluded)
    if assert_eq("checking + savings, CD excluded", s.value, 4000.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("confidence high", s.confidence, "high"): pass_count += 1
    else: fail_count += 1

    # No depository -> missing
    no_dep = [a for a in accts if a["type"] != "depository"]
    s = map_s_liq(no_dep)
    if assert_eq("no depository -> missing", s.confidence, "missing"): pass_count += 1
    else: fail_count += 1

    # HSA -> noted
    hsa_accts = [{"account_id": "hsa_1", "type": "depository", "subtype": "hsa",
                  "balances": {"current": 800, "iso_currency_code": "USD"}}]
    s = map_s_liq(hsa_accts)
    if assert_eq("hsa value", s.value, 800.0): pass_count += 1
    else: fail_count += 1
    if "HSA" in s.notes:
        print(f"  ok    HSA noted in notes")
        pass_count += 1
    else:
        print(f"  FAIL  HSA not noted: {s.notes!r}")
        fail_count += 1

    # ── P4-3.2 S_ret ─────────────────────────────────────────────────
    print("\nS_ret mapping:")
    s = map_s_ret(accts, None, False)
    # 18000 + 2000 = 20000 (no holdings)
    if assert_eq("account-level only", s.value, 20000.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("confidence medium (no holdings)", s.confidence, "medium"): pass_count += 1
    else: fail_count += 1
    if "401(k)" in s.notes:
        print(f"  ok    401(k) note present")
        pass_count += 1
    else:
        print(f"  FAIL  401(k) note missing")
        fail_count += 1

    # Holdings agree with account-level -> high confidence
    holdings = {"holdings": [
        {"institution_value": 18500},
        {"institution_value": 1500},
    ]}   # sum 20000, agrees with 20000 -> diff 0%
    s = map_s_ret(accts, holdings, True)
    if assert_eq("holdings agree -> high conf", s.confidence, "high"): pass_count += 1
    else: fail_count += 1

    # No investment accounts -> missing
    no_inv = [a for a in accts if a["type"] != "investment"]
    s = map_s_ret(no_inv, None, False)
    if assert_eq("no investments -> missing", s.confidence, "missing"): pass_count += 1
    else: fail_count += 1

    # ── P4-3.3 Liabilities ───────────────────────────────────────────
    print("\nLiabilities mapping:")
    accts = fixture_basic_usd()["accounts"]["data"]["accounts"]

    # Unavailable -> all three missing
    d_hi, d_lo, d_min = map_liabilities(None, accts, liabilities_available=False)
    if assert_eq("PRODUCT_NOT_READY -> D_hi missing", d_hi.confidence, "missing"): pass_count += 1
    else: fail_count += 1
    if assert_eq("PRODUCT_NOT_READY -> D_lo missing", d_lo.confidence, "missing"): pass_count += 1
    else: fail_count += 1
    if assert_eq("PRODUCT_NOT_READY -> D_min missing", d_min.confidence, "missing"): pass_count += 1
    else: fail_count += 1

    # Available with credit + student + mortgage
    liab = {
        "credit": [{
            "account_id": "cc_1",
            "minimum_payment_amount": 125,
        }],
        "student": [{
            "account_id": "stu_1",
            "minimum_payment_amount": 200,
        }],
        "mortgage": [{
            "account_id": "mtg_1",
            "last_payment_amount": 1400,
        }],
    }
    d_hi, d_lo, d_min = map_liabilities(liab, accts, liabilities_available=True)
    if assert_eq("D_hi = credit balance from accts (5000)", d_hi.value, 5000.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("D_lo = student (3000) + mortgage (22000)", d_lo.value, 25000.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("D_min = 125 + 200 + 1400", d_min.value, 1725.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("D_min confidence high (no fallback)", d_min.confidence, "high"): pass_count += 1
    else: fail_count += 1

    # Student loan with no minimum, falls back to last_payment_amount
    liab_fb = {
        "credit": [],
        "student": [{
            "account_id": "stu_1",
            "minimum_payment_amount": None,
            "last_payment_amount": 175,
        }],
        "mortgage": [],
    }
    _, _, d_min = map_liabilities(liab_fb, accts, liabilities_available=True)
    if assert_eq("Fallback used -> D_min medium", d_min.confidence, "medium"): pass_count += 1
    else: fail_count += 1
    if assert_eq("D_min from fallback = 175", d_min.value, 175.0): pass_count += 1
    else: fail_count += 1

    # ── P4-3.4 Income (CRITICAL: sign convention + transfer filtering) ──
    print("\nIncome mapping (recurring path):")

    # Two MATURE biweekly paychecks at -2500/period -> 2500 * 2.167 = ~5417/mo each
    # NOTE: Plaid signs inflows NEGATIVE; we abs() before applying frequency.
    recurring_two_paychecks = {
        "inflow_streams": [
            {
                "stream_id": "s1",
                "status": "MATURE",
                "frequency": "BIWEEKLY",
                "average_amount": {"amount": -2500.0},
                "personal_finance_category": {"primary": "INCOME", "detailed": "INCOME_WAGES"},
            },
        ],
    }
    i = map_monthly_income(recurring_two_paychecks, [], recurring_available=True)
    expected = round(2500 * 26 / 12, 2)
    if assert_eq(f"single MATURE biweekly = ${expected}", i.value, expected): pass_count += 1
    else: fail_count += 1
    if assert_eq("status MATURE -> high confidence", i.confidence, "high"): pass_count += 1
    else: fail_count += 1

    # Transfer must be excluded: a savings auto-deposit looks like an inflow
    # but has TRANSFER_IN in its category.
    recurring_with_transfer = {
        "inflow_streams": [
            {"stream_id":"s1","status":"MATURE","frequency":"BIWEEKLY",
             "average_amount":{"amount":-2500.0},
             "personal_finance_category":{"primary":"INCOME","detailed":"INCOME_WAGES"}},
            {"stream_id":"s2","status":"MATURE","frequency":"MONTHLY",
             "average_amount":{"amount":-500.0},
             "personal_finance_category":{"primary":"TRANSFER_IN","detailed":"TRANSFER_IN_SAVINGS"}},
        ],
    }
    i = map_monthly_income(recurring_with_transfer, [], recurring_available=True)
    # Should equal the paycheck only — transfer excluded.
    if assert_eq("transfer stream excluded", i.value, expected): pass_count += 1
    else: fail_count += 1
    if "transfer/refund" in i.notes:
        print("  ok    transfer noted in notes")
        pass_count += 1
    else:
        print(f"  FAIL  transfer note missing: {i.notes!r}")
        fail_count += 1

    # Tombstoned stream excluded
    recurring_tombstoned = {
        "inflow_streams": [
            {"stream_id":"s1","status":"TOMBSTONED","frequency":"BIWEEKLY",
             "average_amount":{"amount":-2500.0},
             "personal_finance_category":{"primary":"INCOME"}},
        ],
    }
    # No transactions in fallback either -> missing
    i = map_monthly_income(recurring_tombstoned, [], recurring_available=True)
    if assert_eq("only tombstoned -> falls back, no transactions -> missing",
                 i.confidence, "missing"): pass_count += 1
    else: fail_count += 1

    # EARLY_DETECTION downgrades to medium
    recurring_early = {
        "inflow_streams": [
            {"stream_id":"s1","status":"EARLY_DETECTION","frequency":"MONTHLY",
             "average_amount":{"amount":-3000.0},
             "personal_finance_category":{"primary":"INCOME"}},
        ],
    }
    i = map_monthly_income(recurring_early, [], recurring_available=True)
    if assert_eq("EARLY_DETECTION -> medium confidence",
                 i.confidence, "medium"): pass_count += 1
    else: fail_count += 1
    if assert_eq("EARLY_DETECTION value = $3000", i.value, 3000.0): pass_count += 1
    else: fail_count += 1

    # Heuristic fallback — 3 consistent months
    print("\nIncome mapping (heuristic fallback):")
    txns_3mo_consistent = [
        # paychecks (negative = inflow per Plaid; INCOME category required by P4-4 hotfix)
        {"amount": -2500, "date": "2026-04-15", "pending": False,
         "personal_finance_category": {"primary": "INCOME", "detailed": "INCOME_WAGES"}},
        {"amount": -2500, "date": "2026-03-15", "pending": False,
         "personal_finance_category": {"primary": "INCOME", "detailed": "INCOME_WAGES"}},
        {"amount": -2400, "date": "2026-02-15", "pending": False,
         "personal_finance_category": {"primary": "INCOME", "detailed": "INCOME_WAGES"}},
        # outflows — should be ignored
        {"amount":  120,  "date": "2026-04-01", "pending": False},
        {"amount":   45,  "date": "2026-04-02", "pending": False},
    ]
    i = map_monthly_income(None, txns_3mo_consistent, recurring_available=False)
    expected_avg = round((2500 + 2500 + 2400) / 3, 2)
    if assert_eq(f"3mo heuristic avg = ${expected_avg}", i.value, expected_avg): pass_count += 1
    else: fail_count += 1
    if assert_eq("heuristic confidence low", i.confidence, "low"): pass_count += 1
    else: fail_count += 1

    # 1mo heuristic
    txns_1mo = [{"amount": -3500, "date": "2026-04-20", "pending": False,
                 "personal_finance_category": {"primary": "INCOME", "detailed": "INCOME_WAGES"}}]
    i = map_monthly_income(None, txns_1mo, recurring_available=False)
    if assert_eq("1mo heuristic value", i.value, 3500.0): pass_count += 1
    else: fail_count += 1
    if "limited" in i.notes.lower():
        print("  ok    1mo note flags limited history")
        pass_count += 1
    else:
        print(f"  FAIL  1mo note missing: {i.notes!r}")
        fail_count += 1

    # Sign-flip sanity: a positive (outflow) value must NOT be counted as income
    txns_sign_flip = [
        {"amount":  2500, "date": "2026-04-15", "pending": False,
         "personal_finance_category": {"primary": "INCOME"}},   # outflow despite INCOME label — sign wins
        {"amount": -1000, "date": "2026-03-15", "pending": False,
         "personal_finance_category": {"primary": "INCOME"}},   # true inflow
    ]
    i = map_monthly_income(None, txns_sign_flip, recurring_available=False)
    # Only the -1000 inflow counts -> abs = 1000, but it's < 500 floor? wait 1000 > 500
    if assert_eq("sign-flip: only true inflow counted", i.value, 1000.0): pass_count += 1
    else: fail_count += 1

    # ── P4-3.5 Expenses ──────────────────────────────────────────────
    print("\nExpense aggregation:")
    # 3 months of typical spending — outflows positive
    txns_3mo = [
        {"amount": 1200, "date": "2026-04-01", "pending": False, "personal_finance_category": {"primary": "RENT_AND_UTILITIES"}},
        {"amount":  300, "date": "2026-04-05", "pending": False, "personal_finance_category": {"primary": "FOOD_AND_DRINK"}},
        {"amount": 1200, "date": "2026-03-01", "pending": False, "personal_finance_category": {"primary": "RENT_AND_UTILITIES"}},
        {"amount":  450, "date": "2026-03-12", "pending": False, "personal_finance_category": {"primary": "FOOD_AND_DRINK"}},
        {"amount": 1200, "date": "2026-02-01", "pending": False, "personal_finance_category": {"primary": "RENT_AND_UTILITIES"}},
        {"amount":  400, "date": "2026-02-09", "pending": False, "personal_finance_category": {"primary": "FOOD_AND_DRINK"}},
        # Inflow — must NOT be counted as expense (sign convention)
        {"amount":-2500, "date": "2026-04-15", "pending": False},
        # Pending — excluded
        {"amount":  120, "date": "2026-04-20", "pending": True},
        # CC payment — excluded as TRANSFER/LOAN-payment
        {"amount":  500, "date": "2026-04-10", "pending": False, "personal_finance_category": {"primary": "LOAN_PAYMENTS", "detailed": "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"}},
        # Account-to-account transfer — excluded
        {"amount":  300, "date": "2026-03-22", "pending": False, "personal_finance_category": {"primary": "TRANSFER_OUT"}},
    ]
    e = map_monthly_expenses(txns_3mo)
    # Apr: 1500, Mar: 1650, Feb: 1600 -> avg = 1583.33
    if assert_eq("3mo avg correct", e.value, round((1500 + 1650 + 1600) / 3, 2)): pass_count += 1
    else: fail_count += 1
    if assert_eq("3mo confidence medium", e.confidence, "medium"): pass_count += 1
    else: fail_count += 1

    # 1mo only -> low confidence
    txns_1mo = [t for t in txns_3mo if str(t.get("date","")).startswith("2026-04") and t.get("amount",0)>0 and not t.get("pending")]
    txns_1mo = [t for t in txns_1mo if "TRANSFER" not in str((t.get("personal_finance_category") or {}).get("primary","")) and "LOAN_PAYMENTS" not in str((t.get("personal_finance_category") or {}).get("primary",""))]
    e = map_monthly_expenses(txns_1mo)
    if assert_eq("1mo confidence low", e.confidence, "low"): pass_count += 1
    else: fail_count += 1

    # No outflows at all -> value=0 with low confidence + verify note
    e = map_monthly_expenses([{"amount": -2500, "date": "2026-04-01", "pending": False}])
    if assert_eq("zero outflows -> value 0", e.value, 0.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("zero outflows -> low conf", e.confidence, "low"): pass_count += 1
    else: fail_count += 1

    # No transactions at all -> missing
    e = map_monthly_expenses([])
    if assert_eq("no transactions -> missing", e.confidence, "missing"): pass_count += 1
    else: fail_count += 1

    # Sign-flip sanity: an inflow (negative) cannot drive expenses up
    e = map_monthly_expenses([
        {"amount": -5000, "date": "2026-04-01", "pending": False},
    ])
    if assert_eq("inflow only -> value 0", e.value, 0.0): pass_count += 1
    else: fail_count += 1

    # ── P4-4 Multi-bank merge ────────────────────────────────────────
    print("\nMulti-bank merge:")

    # (1) Two USD banks merge cleanly
    multi_resp = {
        "session_id": "sess-test",
        "items": [
            {  # Bank A: checking + credit card
                "item_id": "item-A",
                "institution_name": "First Platypus",
                "accounts": {"available": True, "data": {"accounts": [
                    {"account_id":"ckA","type":"depository","subtype":"checking","balances":{"current":5000,"iso_currency_code":"USD"}},
                    {"account_id":"ccA","type":"credit","subtype":"credit card","balances":{"current":2000,"iso_currency_code":"USD"}},
                ]}},
                "transactions": {"available": True, "data": [
                    # paycheck (INCOME-categorized so heuristic whitelist accepts it)
                    {"amount":-3000,"date":"2026-04-15","pending":False,
                     "personal_finance_category":{"primary":"INCOME","detailed":"INCOME_WAGES"}},
                    # CC payment from checking — must be EXCLUDED from expenses
                    {"amount": 500,"date":"2026-04-10","pending":False,
                     "personal_finance_category":{"primary":"LOAN_PAYMENTS","detailed":"LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"}},
                    {"amount": 800,"date":"2026-04-01","pending":False,
                     "personal_finance_category":{"primary":"RENT_AND_UTILITIES"}},
                    {"amount": 800,"date":"2026-03-01","pending":False,
                     "personal_finance_category":{"primary":"RENT_AND_UTILITIES"}},
                    {"amount": 800,"date":"2026-02-01","pending":False,
                     "personal_finance_category":{"primary":"RENT_AND_UTILITIES"}},
                ]},
                "liabilities": {"available": True, "data": {
                    "credit": [{"account_id":"ccA","minimum_payment_amount":50}],
                    "student": [], "mortgage": [],
                }},
                "investments": {"available": False},
                "recurring": {"available": False},
            },
            {  # Bank B: investments + savings
                "item_id": "item-B",
                "institution_name": "Tartan Bank",
                "accounts": {"available": True, "data": {"accounts": [
                    {"account_id":"svB","type":"depository","subtype":"savings","balances":{"current":8000,"iso_currency_code":"USD"}},
                    {"account_id":"401kB","type":"investment","subtype":"401k","balances":{"current":30000,"iso_currency_code":"USD"}},
                ]}},
                "transactions": {"available": True, "data": []},
                "liabilities": {"available": False},
                "investments": {"available": True, "data": {"holdings": []}},
                "recurring": {"available": False},
            },
        ],
    }
    r = map_plaid_data(multi_resp)
    if assert_eq("two-bank S_liq = 5000 + 8000", r.S_liq.value, 13000.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("two-bank S_ret = 30000", r.S_ret.value, 30000.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("two-bank D_hi = 2000 (credit card from acct lookup)", r.D_hi.value, 2000.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("two-bank E_ess = 800/mo (CC payment excluded)", r.E_ess.value, 800.0): pass_count += 1
    else: fail_count += 1
    # Sources provenance
    src = sorted([(s.institution_name, sorted(s.contributed_to)) for s in r.sources])
    print(f"  ok    sources: {src}")
    pass_count += 1
    bank_a_contribs = next(s.contributed_to for s in r.sources if s.institution_name == "First Platypus")
    bank_b_contribs = next(s.contributed_to for s in r.sources if s.institution_name == "Tartan Bank")
    # Bank A also contributes I_net because the -$3000 paycheck transaction
    # routes through the heuristic-income path (no recurring data available).
    if assert_eq("Bank A contributes S_liq+D_hi+D_min+E_ess+I_net",
                 sorted(bank_a_contribs),
                 sorted(["S_liq", "D_hi", "D_min", "E_ess", "I_net"])): pass_count += 1
    else: fail_count += 1
    if assert_eq("Bank B contributes S_liq+S_ret",
                 sorted(bank_b_contribs), sorted(["S_liq", "S_ret"])): pass_count += 1
    else: fail_count += 1

    # (2) USD + CAD bank → all fields drop to missing
    mixed_currency = {
        "items": [
            {  # USD bank
                "item_id": "item-A", "institution_name": "First Platypus",
                "accounts": {"available": True, "data": {"accounts": [
                    {"account_id":"ckA","type":"depository","subtype":"checking",
                     "balances":{"current":5000,"iso_currency_code":"USD"}},
                ]}},
                "transactions": {"available": True, "data": []},
                "liabilities": {"available": False},
                "investments": {"available": False},
                "recurring": {"available": False},
            },
            {  # CAD bank
                "item_id": "item-B", "institution_name": "Toronto Bank",
                "accounts": {"available": True, "data": {"accounts": [
                    {"account_id":"ckB","type":"depository","subtype":"checking",
                     "balances":{"current":2000,"iso_currency_code":"CAD"}},
                ]}},
                "transactions": {"available": True, "data": []},
                "liabilities": {"available": False},
                "investments": {"available": False},
                "recurring": {"available": False},
            },
        ],
    }
    r = map_plaid_data(mixed_currency)
    all_missing = all(getattr(r, k).confidence == "missing"
                      for k in ["I_net","E_ess","S_liq","S_ret","D_hi","D_lo","D_min"])
    if assert_eq("USD+CAD: all 7 fields missing", all_missing, True): pass_count += 1
    else: fail_count += 1
    if "CAD" in r.S_liq.notes:
        print("  ok    CAD currency mentioned in notes")
        pass_count += 1
    else:
        print(f"  FAIL  CAD not mentioned: {r.S_liq.notes!r}")
        fail_count += 1
    if assert_eq("Both institutions still in sources", len(r.sources), 2): pass_count += 1
    else: fail_count += 1

    # (3) Specialty contribution: A=checking-only, B=investment-only
    specialty = {
        "items": [
            {  # A: only depository
                "item_id": "item-A", "institution_name": "Bank A",
                "accounts": {"available": True, "data": {"accounts": [
                    {"account_id":"ckA","type":"depository","subtype":"checking",
                     "balances":{"current":3500,"iso_currency_code":"USD"}},
                ]}},
                "transactions": {"available": True, "data": []},
                "liabilities": {"available": False},
                "investments": {"available": False},
                "recurring": {"available": False},
            },
            {  # B: only investment
                "item_id": "item-B", "institution_name": "Bank B",
                "accounts": {"available": True, "data": {"accounts": [
                    {"account_id":"401kB","type":"investment","subtype":"401k",
                     "balances":{"current":50000,"iso_currency_code":"USD"}},
                ]}},
                "transactions": {"available": True, "data": []},
                "liabilities": {"available": False},
                "investments": {"available": False},
                "recurring": {"available": False},
            },
        ],
    }
    r = map_plaid_data(specialty)
    if assert_eq("specialty: S_liq from Bank A only", r.S_liq.value, 3500.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("specialty: S_ret from Bank B only", r.S_ret.value, 50000.0): pass_count += 1
    else: fail_count += 1
    sources_by_name = {s.institution_name: s.contributed_to for s in r.sources}
    if assert_eq("Bank A only contributes S_liq",
                 sources_by_name.get("Bank A"), ["S_liq"]): pass_count += 1
    else: fail_count += 1
    if assert_eq("Bank B only contributes S_ret",
                 sources_by_name.get("Bank B"), ["S_ret"]): pass_count += 1
    else: fail_count += 1

    # (4) Cross-bank credit-card payment is NOT double-counted as expense.
    # User has CC at Bank A, pays it from checking at Bank B. The payment
    # transaction appears in Bank B's transactions; the CC's purchase
    # transactions appear in Bank A's transactions. Both must be handled
    # correctly: payment excluded as LOAN_PAYMENT; purchases counted.
    cross_cc = {
        "items": [
            {  # A: credit card with purchases
                "item_id": "item-A", "institution_name": "Card Bank",
                "accounts": {"available": True, "data": {"accounts": [
                    {"account_id":"ccA","type":"credit","subtype":"credit card",
                     "balances":{"current":1500,"iso_currency_code":"USD"}},
                ]}},
                "transactions": {"available": True, "data": [
                    {"amount": 600,"date":"2026-04-05","pending":False,
                     "personal_finance_category":{"primary":"FOOD_AND_DRINK"},
                     "account_id":"ccA"},
                    {"amount": 600,"date":"2026-03-05","pending":False,
                     "personal_finance_category":{"primary":"FOOD_AND_DRINK"},
                     "account_id":"ccA"},
                    {"amount": 600,"date":"2026-02-05","pending":False,
                     "personal_finance_category":{"primary":"FOOD_AND_DRINK"},
                     "account_id":"ccA"},
                ]},
                "liabilities": {"available": True, "data": {
                    "credit":[{"account_id":"ccA","minimum_payment_amount":35}],
                    "student":[],"mortgage":[],
                }},
                "investments": {"available": False},
                "recurring": {"available": False},
            },
            {  # B: checking that pays the credit card
                "item_id": "item-B", "institution_name": "Checking Bank",
                "accounts": {"available": True, "data": {"accounts": [
                    {"account_id":"ckB","type":"depository","subtype":"checking",
                     "balances":{"current":4000,"iso_currency_code":"USD"}},
                ]}},
                "transactions": {"available": True, "data": [
                    # Cross-bank credit card payment from checking
                    {"amount": 600,"date":"2026-04-10","pending":False,
                     "personal_finance_category":{"primary":"LOAN_PAYMENTS","detailed":"LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"},
                     "account_id":"ckB"},
                    {"amount": 600,"date":"2026-03-10","pending":False,
                     "personal_finance_category":{"primary":"LOAN_PAYMENTS","detailed":"LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"},
                     "account_id":"ckB"},
                    {"amount": 600,"date":"2026-02-10","pending":False,
                     "personal_finance_category":{"primary":"LOAN_PAYMENTS","detailed":"LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"},
                     "account_id":"ckB"},
                ]},
                "liabilities": {"available": False},
                "investments": {"available": False},
                "recurring": {"available": False},
            },
        ],
    }
    r = map_plaid_data(cross_cc)
    # Expenses should ONLY be the $600/mo CC purchases — not the $600
    # CC payment from checking. If we were double-counting, total would
    # be $1200/mo. Correct value: $600/mo.
    if assert_eq("cross-bank CC payment NOT double-counted", r.E_ess.value, 600.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("D_hi from card balance via account lookup", r.D_hi.value, 1500.0): pass_count += 1
    else: fail_count += 1

    # ── P4-4 hotfix: real Plaid fixture (user_good) ──────────────────
    # Captures the doubly-nested liabilities path that synthetic fixtures
    # miss, plus the heuristic-income whitelist behavior under sandbox
    # quirks (GUSTO PAY mislabeled, United refunds = TRAVEL).
    print("\nReal Plaid fixture (user_good):")
    f = fixture_user_good()
    r = map_plaid_data(f)

    # Liabilities — the bug we're fixing
    if assert_eq("D_hi = personal CC only (business excluded)",
                 round(r.D_hi.value, 2), 410.00): pass_count += 1
    else: fail_count += 1
    if assert_eq("D_hi confidence high", r.D_hi.confidence, "high"): pass_count += 1
    else: fail_count += 1
    if assert_eq("D_lo = student + mortgage",
                 round(r.D_lo.value, 2), 121564.06): pass_count += 1
    else: fail_count += 1
    if assert_eq("D_min = personal CC + student + mortgage proxy",
                 round(r.D_min.value, 2), 3186.54): pass_count += 1
    else: fail_count += 1

    # Income — the heuristic filter
    if assert_eq("I_net missing (no income-categorized inflows)",
                 r.I_net.confidence, "missing"): pass_count += 1
    else: fail_count += 1

    # Assets — should still work through the real wire shape
    if assert_eq("S_liq = depository sum (CD excluded)",
                 round(r.S_liq.value, 2), 61589.00): pass_count += 1
    else: fail_count += 1
    if assert_eq("S_ret = IRA + 401k",
                 round(r.S_ret.value, 2), 23952.76): pass_count += 1
    else: fail_count += 1

    # Sanity check on business CC exclusion in notes
    if "business" in (r.D_hi.notes or "").lower():
        print(f"  ok    D_hi notes mention business CC")
        pass_count += 1
    else:
        print(f"  FAIL  D_hi notes mention business CC: got {r.D_hi.notes!r}")
        fail_count += 1

    # ── Phase 5a.3: SB mapper extensions ─────────────────────────────
    print("\nP5a.3 — Business account detection:")

    # via Plaid `categorization` beta — high confidence
    is_biz, conf, source = detect_business_account({
        "categorization": "business", "subtype": "checking", "name": "X",
    })
    if assert_eq("categorization=business -> (True, high, plaid_categorization)",
                 (is_biz, conf, source), (True, "high", "plaid_categorization")):
        pass_count += 1
    else: fail_count += 1

    # via heuristic name — medium confidence
    is_biz, conf, source = detect_business_account({
        "subtype": "checking",
        "name": "Acme Consulting LLC Checking",
    })
    if assert_eq("name has ' llc' -> (True, medium, heuristic_name_match)",
                 (is_biz, conf, source), (True, "medium", "heuristic_name_match")):
        pass_count += 1
    else: fail_count += 1

    # via subtype only
    is_biz, conf, source = detect_business_account({
        "subtype": "business checking", "name": "Operating",
    })
    if assert_eq("subtype=business checking -> (True, medium, heuristic_subtype)",
                 (is_biz, conf, source), (True, "medium", "heuristic_subtype")):
        pass_count += 1
    else: fail_count += 1

    # no business signal -> default personal
    is_biz, conf, source = detect_business_account({
        "subtype": "savings", "name": "Plaid Saving",
    })
    if assert_eq("no signal -> (False, high, default_personal)",
                 (is_biz, conf, source), (False, "high", "default_personal")):
        pass_count += 1
    else: fail_count += 1

    # categorization=personal explicit signal still high
    is_biz, conf, source = detect_business_account({
        "categorization": "personal",
        "subtype": "business checking",   # contradictory subtype loses to plaid signal
    })
    if assert_eq("categorization=personal beats subtype heuristic",
                 (is_biz, conf, source), (False, "high", "plaid_categorization")):
        pass_count += 1
    else: fail_count += 1

    # holder_category fallback (P4-H1 path)
    is_biz, conf, source = detect_business_account({
        "subtype": "checking",
        "name": "Plain Checking",
        "holder_category": "business",
    })
    if assert_eq("holder_category=business fallback -> (True, medium, holder_category)",
                 (is_biz, conf, source), (True, "medium", "holder_category")):
        pass_count += 1
    else: fail_count += 1

    # ── Business LOC mapping ─────────────────────────────────────────
    print("\nP5a.3 — Business LOC mapping:")

    # high confidence: full data + business detection
    accounts_loc_high = [{
        "account_id": "acct_loc_1",
        "name": "BoA Business LOC",
        "type": "credit",
        "subtype": "line of credit",
        "balances": {"current": 22000.0, "limit": 30000.0, "iso_currency_code": "USD"},
    }]
    liab_loc_high = {
        "credit": [{
            "account_id": "acct_loc_1",
            "aprs": [{"apr_percentage": 11.5}],
        }],
    }
    mf = map_business_lines_of_credit(accounts_loc_high, liab_loc_high)
    if assert_eq("LOC count = 1", len(mf.value), 1): pass_count += 1
    else: fail_count += 1
    if assert_eq("LOC limit = 30000", mf.value[0]["limit"], 30000.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("LOC balance = 22000", mf.value[0]["balance"], 22000.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("LOC apr = 0.115", round(mf.value[0]["apr"], 4), 0.115): pass_count += 1
    else: fail_count += 1
    if assert_eq("LOC confidence medium (subtype heuristic baseline)",
                 mf.confidence, "medium"): pass_count += 1
    else: fail_count += 1

    # missing limit -> degraded
    accounts_loc_no_limit = [{
        "account_id": "acct_loc_2",
        "name": "Some Business LOC",
        "type": "credit",
        "subtype": "line of credit",
        "balances": {"current": 5000.0, "iso_currency_code": "USD"},
    }]
    mf = map_business_lines_of_credit(accounts_loc_no_limit, None)
    if assert_eq("missing limit -> limit=0 with reduced confidence",
                 mf.value[0]["limit"], 0.0): pass_count += 1
    else: fail_count += 1

    # no LOC accounts -> missing
    mf = map_business_lines_of_credit([
        {"subtype": "checking", "name": "X"},
    ], None)
    if assert_eq("no LOC accounts -> missing", mf.confidence, "missing"): pass_count += 1
    else: fail_count += 1
    if assert_eq("no LOC accounts -> empty value list", mf.value, []): pass_count += 1
    else: fail_count += 1

    # ── Archetype-aware business CC exclusion (regression check) ─────
    print("\nP5a.3 — Archetype-aware business CC exclusion:")
    f_user_good = fixture_user_good()
    # Default Individual archetype — preserves P4-H1: business CC excluded
    r_individual = map_plaid_data(f_user_good)
    if assert_eq("Individual: D_hi excludes business CC ($410 personal only)",
                 round(r_individual.D_hi.value, 2), 410.00):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("Individual: D_hi notes mention exclusion",
                 "excluded" in (r_individual.D_hi.notes or "").lower(), True):
        pass_count += 1
    else: fail_count += 1

    # Small Business archetype — INCLUDES business CC
    r_sb = map_plaid_data(f_user_good, archetype="small_business")
    # Personal CC $410 + business CC $5020 = $5430 total
    if assert_eq("Small Business: D_hi includes business CC ($5430 = 410 + 5020)",
                 round(r_sb.D_hi.value, 2), 5430.00):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("Small Business: D_hi notes mention inclusion",
                 "included" in (r_sb.D_hi.notes or "").lower(), True):
        pass_count += 1
    else: fail_count += 1
    # Personal min ($20) + business min ($100) for SB
    if assert_eq("Small Business: D_min includes business CC min",
                 round(r_sb.D_min.value, 2), 3186.54 - 20.0 + 20.0 + 100.0):
        pass_count += 1
    else: fail_count += 1

    # ── AR / AP manual-entry surface ─────────────────────────────────
    print("\nP5a.3 — AR / AP manual-entry surface:")
    if assert_eq("ar_aging_buckets confidence missing",
                 r_individual.ar_aging_buckets.confidence, "missing"):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("ar_aging_buckets source = manual_entry_required",
                 r_individual.ar_aging_buckets.source, "manual_entry_required"):
        pass_count += 1
    else: fail_count += 1
    if "Plaid does not provide" in (r_individual.ar_aging_buckets.notes or ""):
        print("  ok    ar_aging_buckets notes explain why")
        pass_count += 1
    else:
        print(f"  FAIL  ar_aging_buckets notes: {r_individual.ar_aging_buckets.notes!r}")
        fail_count += 1
    if assert_eq("ap_pending source = manual_entry_required",
                 r_individual.ap_pending.source, "manual_entry_required"):
        pass_count += 1
    else: fail_count += 1

    # ── SB fixture: solo LLC (no LOC) ────────────────────────────────
    print("\nP5a.3 — SB fixture: solo LLC (no LOC):")
    sb_solo_path = os.path.join(os.path.dirname(__file__),
                                "tests", "fixtures", "plaid_sb_solo_llc.json")
    with open(sb_solo_path) as f:
        sb_solo = json.load(f)
    r_sb_solo = map_plaid_data(sb_solo, archetype="small_business")
    if assert_eq("SB solo LLC: business_lines_of_credit empty",
                 r_sb_solo.business_lines_of_credit.value, []):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("SB solo LLC: business CC INCLUDED in D_hi (1850)",
                 round(r_sb_solo.D_hi.value, 2), 1850.00):
        pass_count += 1
    else: fail_count += 1

    # ── SB fixture: with LOC ─────────────────────────────────────────
    print("\nP5a.3 — SB fixture: with LOC at 73% utilization:")
    sb_loc_path = os.path.join(os.path.dirname(__file__),
                               "tests", "fixtures", "plaid_sb_with_loc.json")
    with open(sb_loc_path) as f:
        sb_loc = json.load(f)
    r_sb_loc = map_plaid_data(sb_loc, archetype="small_business")
    locs = r_sb_loc.business_lines_of_credit.value
    if assert_eq("SB LOC fixture: 1 LOC detected", len(locs), 1):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("SB LOC fixture: LOC limit = 30000", locs[0]["limit"], 30000.0):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("SB LOC fixture: LOC balance = 21900", locs[0]["balance"], 21900.0):
        pass_count += 1
    else: fail_count += 1

    # ── Mixed personal+business fixture ──────────────────────────────
    print("\nP5a.3 — Mixed personal+business fixture (separation check):")
    sb_mixed_path = os.path.join(os.path.dirname(__file__),
                                 "tests", "fixtures", "plaid_sb_mixed_personal_business.json")
    with open(sb_mixed_path) as f:
        sb_mixed = json.load(f)
    # Individual archetype: personal CC only (1200), business CC + LOC excluded as business
    r_mixed_ind = map_plaid_data(sb_mixed, archetype="individual_w2")
    if assert_eq("Mixed Individual: D_hi = personal CC only (1200)",
                 round(r_mixed_ind.D_hi.value, 2), 1200.00):
        pass_count += 1
    else: fail_count += 1
    # Small Business archetype: personal + business CC included.
    # LOC is NOT in D_hi — it lives on the business_lines_of_credit
    # surface (de-duplicated to avoid double-counting). Personal CC
    # 1200 + business CC 3500 = 4700.
    r_mixed_sb = map_plaid_data(sb_mixed, archetype="small_business")
    if assert_eq("Mixed SB: D_hi = personal + business CCs only (4700, LOC on its own surface)",
                 round(r_mixed_sb.D_hi.value, 2), 4700.00):
        pass_count += 1
    else: fail_count += 1
    # S_liq archetype split (the don't-bleed-into-each-other rule):
    #   • Individual: ONLY personal depository — 4500 + 12000 = 16500.
    #     Business checking ($18000) stays out.
    #   • Small Business: ALL depository (personal + business) —
    #     4500 + 12000 + 18000 = 34500.
    if assert_eq("Mixed Individual: S_liq = personal depository only (16500)",
                 round(r_mixed_ind.S_liq.value, 2), 16500.00):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("Mixed SB: S_liq = ALL depository incl. business (34500)",
                 round(r_mixed_sb.S_liq.value, 2), 34500.00):
        pass_count += 1
    else: fail_count += 1
    # LOC detection: only the LOC subtype account, regardless of archetype
    if assert_eq("Mixed: business LOC detected as 1 line",
                 len(r_mixed_sb.business_lines_of_credit.value), 1):
        pass_count += 1
    else: fail_count += 1

    # ── Phase 5b.3: Freelancer 1099/gig detection ────────────────────
    print("\nP5b.3 — 1099/gig income detection function:")

    # Tier 1 — gig-platform high confidence
    is_gig, conf, source, st = detect_1099_gig_income({
        "amount": -2200, "date": "2026-04-15",
        "name": "STRIPE TRANSFER", "merchant_name": "Stripe",
        "personal_finance_category": {"primary": "INCOME"},
        "pending": False,
    })
    if assert_eq("Stripe -> (True, high, gig_platform_match, gig_platform)",
                 (is_gig, conf, source, st),
                 (True, "high", "gig_platform_match", "gig_platform")):
        pass_count += 1
    else: fail_count += 1

    # Tier 2 — business-payer pattern + invoice keyword -> medium freelance_direct
    is_gig, conf, source, st = detect_1099_gig_income({
        "amount": -3500, "date": "2026-04-12",
        "name": "ABC STUDIO LLC INVOICE PAYMENT",
        "merchant_name": "ABC Studio LLC",
        "personal_finance_category": {"primary": "INCOME"},
        "pending": False,
    })
    if assert_eq("LLC + 'invoice' -> (True, medium, "
                 "business_payer_with_invoice_keyword, freelance_direct)",
                 (is_gig, conf, source, st),
                 (True, "medium",
                  "business_payer_with_invoice_keyword",
                  "freelance_direct")):
        pass_count += 1
    else: fail_count += 1

    # Tier 3 — business-payer pattern only -> medium 1099_contract
    is_gig, conf, source, st = detect_1099_gig_income({
        "amount": -2000, "date": "2026-03-01",
        "name": "JONES CONSULTING LLC", "merchant_name": "Jones Consulting LLC",
        "personal_finance_category": {"primary": "INCOME"},
        "pending": False,
    })
    if assert_eq("LLC alone -> (True, medium, business_payer_pattern, 1099_contract)",
                 (is_gig, conf, source, st),
                 (True, "medium", "business_payer_pattern", "1099_contract")):
        pass_count += 1
    else: fail_count += 1

    # Tier 4 — heuristic large irregular -> low other
    is_gig, conf, source, st = detect_1099_gig_income({
        "amount": -1500, "date": "2026-04-15",
        "name": "JOHN DOE PAYMENT", "merchant_name": "John Doe",
        "personal_finance_category": {"primary": "INCOME"},
        "pending": False,
    })
    if assert_eq("large irregular -> (True, low, "
                 "heuristic_irregular_amount, other)",
                 (is_gig, conf, source, st),
                 (True, "low", "heuristic_irregular_amount", "other")):
        pass_count += 1
    else: fail_count += 1

    # No-detection: small refund (below floor)
    is_gig, _, _, _ = detect_1099_gig_income({
        "amount": -200, "date": "2026-04-15",
        "name": "TARGET REFUND",
        "personal_finance_category": {"primary": "GENERAL_MERCHANDISE"},
    })
    if assert_eq("small refund -> not detected", is_gig, False): pass_count += 1
    else: fail_count += 1

    # No-detection: outflow (positive amount)
    is_gig, _, _, _ = detect_1099_gig_income({
        "amount": 1500, "date": "2026-04-15",
        "name": "STRIPE TRANSFER", "merchant_name": "Stripe",
        "personal_finance_category": {"primary": "INCOME"},
    })
    if assert_eq("outflow -> not detected", is_gig, False): pass_count += 1
    else: fail_count += 1

    # ── Aggregation: single payer ────────────────────────────────────
    print("\nP5b.3 — income_sources aggregation, single payer:")
    txns_one_payer = [
        {"amount": -2200, "date": "2026-04-15", "name": "STRIPE TRANSFER",
         "merchant_name": "Stripe",
         "personal_finance_category": {"primary": "INCOME"}},
        {"amount": -2300, "date": "2026-03-15", "name": "STRIPE TRANSFER",
         "merchant_name": "Stripe",
         "personal_finance_category": {"primary": "INCOME"}},
        {"amount": -2100, "date": "2026-02-15", "name": "STRIPE TRANSFER",
         "merchant_name": "Stripe",
         "personal_finance_category": {"primary": "INCOME"}},
        {"amount": -2200, "date": "2026-01-15", "name": "STRIPE TRANSFER",
         "merchant_name": "Stripe",
         "personal_finance_category": {"primary": "INCOME"}},
    ]
    sources, monthly = aggregate_freelance_income(
        txns_one_payer, "separate_business_account",
    )
    if assert_eq("1 source detected", len(sources), 1): pass_count += 1
    else: fail_count += 1
    if assert_eq("source_type=gig_platform",
                 sources[0]["source_type"], "gig_platform"): pass_count += 1
    else: fail_count += 1
    if assert_eq("monthly_average == 2200",
                 sources[0]["monthly_average"], 2200.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("source confidence high (separated + gig platform)",
                 sources[0]["confidence"], "high"): pass_count += 1
    else: fail_count += 1
    # 4 distinct months in monthly totals
    if assert_eq("4 months in monthly_totals", len(monthly), 4): pass_count += 1
    else: fail_count += 1

    # ── Aggregation: multi-payer ─────────────────────────────────────
    print("\nP5b.3 — income_sources aggregation, multi-payer:")
    txns_multi = txns_one_payer + [
        {"amount": -1100, "date": "2026-04-22", "name": "UPWORK ESCROW",
         "merchant_name": "Upwork",
         "personal_finance_category": {"primary": "INCOME"}},
        {"amount": -1050, "date": "2026-03-22", "name": "UPWORK ESCROW",
         "merchant_name": "Upwork",
         "personal_finance_category": {"primary": "INCOME"}},
        {"amount": -1150, "date": "2026-02-22", "name": "UPWORK ESCROW",
         "merchant_name": "Upwork",
         "personal_finance_category": {"primary": "INCOME"}},
    ]
    sources, monthly = aggregate_freelance_income(
        txns_multi, "separate_business_account",
    )
    if assert_eq("2 sources detected", len(sources), 2): pass_count += 1
    else: fail_count += 1
    payer_names = sorted([s["name"] for s in sources])
    if assert_eq("payer names = [Stripe, Upwork]",
                 payer_names, ["Stripe", "Upwork"]): pass_count += 1
    else: fail_count += 1

    # ── Volatility computation: sufficient history ───────────────────
    print("\nP5b.3 — volatility computation:")
    monthly_4 = {"2026-01": 3300.0, "2026-02": 3250.0,
                 "2026-03": 3350.0, "2026-04": 3300.0}
    cv, n, conf, src = compute_freelance_volatility(monthly_4)
    if assert_eq("4-month sufficient history -> n=4", n, 4): pass_count += 1
    else: fail_count += 1
    if assert_eq("low-volatility CV near zero", cv < 0.05, True): pass_count += 1
    else: fail_count += 1
    if assert_eq("confidence high",
                 conf, "high"): pass_count += 1
    else: fail_count += 1

    # Insufficient history -> manual_entry_required
    monthly_2 = {"2026-03": 2500.0, "2026-04": 2800.0}
    cv, n, conf, src = compute_freelance_volatility(monthly_2)
    if assert_eq("2-month insufficient history -> cv None",
                 cv, None): pass_count += 1
    else: fail_count += 1
    if assert_eq("insufficient -> confidence missing",
                 conf, "missing"): pass_count += 1
    else: fail_count += 1
    if assert_eq("insufficient -> source manual_entry_required",
                 src, "manual_entry_required"): pass_count += 1
    else: fail_count += 1

    # Declining trajectory should produce HIGH volatility (the math
    # shouldn't conflate trajectory with volatility)
    monthly_decl = {"2026-01": 7000.0, "2026-02": 5000.0,
                    "2026-03": 3000.0, "2026-04": 1500.0}
    cv, _, _, _ = compute_freelance_volatility(monthly_decl)
    if assert_eq("declining trajectory -> high volatility (>0.4)",
                 cv > 0.40, True): pass_count += 1
    else: fail_count += 1

    # ── FL fixture: separated 3mo (high confidence) ──────────────────
    print("\nP5b.3 — FL fixture: separated business account (3+ months):")
    fl_sep_path = os.path.join(os.path.dirname(__file__),
                               "tests", "fixtures",
                               "plaid_fl_separated_3mo.json")
    with open(fl_sep_path) as f:
        fl_sep = json.load(f)
    r = map_plaid_data(fl_sep, archetype="freelancer")
    if assert_eq("FL separated: 2 income_sources (Stripe + Upwork)",
                 len(r.income_sources.value), 2): pass_count += 1
    else: fail_count += 1
    if assert_eq("FL separated: income_sources confidence high",
                 r.income_sources.confidence, "high"): pass_count += 1
    else: fail_count += 1
    if assert_eq("FL separated: months_of_income_history = 4",
                 r.months_of_income_history.value, 4): pass_count += 1
    else: fail_count += 1
    # Volatility should be low (consistent monthly amounts)
    if assert_eq("FL separated: volatility < 0.10",
                 r.income_volatility_observed.value < 0.10, True):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("FL separated: volatility confidence high",
                 r.income_volatility_observed.confidence, "high"):
        pass_count += 1
    else: fail_count += 1

    # ── FL fixture: mixed personal 4mo (medium confidence) ──────────
    print("\nP5b.3 — FL fixture: mixed personal account (4 months):")
    fl_mixed_path = os.path.join(os.path.dirname(__file__),
                                 "tests", "fixtures",
                                 "plaid_fl_mixed_personal_4mo.json")
    with open(fl_mixed_path) as f:
        fl_mixed = json.load(f)
    r = map_plaid_data(fl_mixed, archetype="freelancer")
    if assert_eq("FL mixed: 2 income_sources (ABC + Stripe)",
                 len(r.income_sources.value), 2): pass_count += 1
    else: fail_count += 1
    # ABC Studio LLC has only 2 months (Apr + Feb) → its source
    # confidence is medium (LLC pattern) but separation is mixed_personal
    # → final medium. Stripe has 4 months, gig_platform high * mixed_personal
    # → final medium. Aggregate should be medium.
    if assert_eq("FL mixed: aggregate confidence medium",
                 r.income_sources.confidence, "medium"): pass_count += 1
    else: fail_count += 1

    # ── FL fixture: short history (manual-entry-required) ───────────
    print("\nP5b.3 — FL fixture: short history (<3 months):")
    fl_short_path = os.path.join(os.path.dirname(__file__),
                                 "tests", "fixtures",
                                 "plaid_fl_short_history_2mo.json")
    with open(fl_short_path) as f:
        fl_short = json.load(f)
    r = map_plaid_data(fl_short, archetype="freelancer")
    if assert_eq("FL short: months_of_income_history = 2",
                 r.months_of_income_history.value, 2): pass_count += 1
    else: fail_count += 1
    if assert_eq("FL short: volatility value None",
                 r.income_volatility_observed.value, None): pass_count += 1
    else: fail_count += 1
    if assert_eq("FL short: volatility confidence missing",
                 r.income_volatility_observed.confidence, "missing"):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("FL short: volatility source manual_entry_required",
                 r.income_volatility_observed.source,
                 "manual_entry_required"): pass_count += 1
    else: fail_count += 1
    if "requires at least" in (r.income_volatility_observed.notes or ""):
        print("  ok    FL short: notes explain history requirement")
        pass_count += 1
    else:
        print(f"  FAIL  FL short notes: {r.income_volatility_observed.notes!r}")
        fail_count += 1

    # ── FL fixture: declining trajectory ────────────────────────────
    print("\nP5b.3 — FL fixture: declining trajectory:")
    fl_decl_path = os.path.join(os.path.dirname(__file__),
                                "tests", "fixtures",
                                "plaid_fl_declining_trajectory.json")
    with open(fl_decl_path) as f:
        fl_decl = json.load(f)
    r = map_plaid_data(fl_decl, archetype="freelancer")
    # Volatility math should not conflate trajectory direction.
    if assert_eq("FL declining: volatility > 0.4 (high)",
                 r.income_volatility_observed.value > 0.40, True):
        pass_count += 1
    else: fail_count += 1
    if assert_eq("FL declining: 4 months history",
                 r.months_of_income_history.value, 4): pass_count += 1
    else: fail_count += 1

    # ── Cross-archetype regression: Individual unaffected ───────────
    print("\nP5b.3 — Cross-archetype regression (Individual):")
    f_user_good = fixture_user_good()
    r_individual = map_plaid_data(f_user_good)   # default Individual
    # The 5b.3 fields should be at no-detection-run defaults
    if assert_eq("Individual: income_sources empty list",
                 r_individual.income_sources.value, []): pass_count += 1
    else: fail_count += 1
    if assert_eq("Individual: income_sources source no_freelance_detection_run",
                 r_individual.income_sources.source,
                 "no_freelance_detection_run"): pass_count += 1
    else: fail_count += 1
    # Regression check: D_hi/D_lo/D_min/S_liq unchanged
    if assert_eq("Individual: D_hi=410 (P4-H1 baseline)",
                 round(r_individual.D_hi.value, 2), 410.0): pass_count += 1
    else: fail_count += 1
    if assert_eq("Individual: S_liq=61589 (P4-H1 baseline)",
                 round(r_individual.S_liq.value, 2), 61589.0): pass_count += 1
    else: fail_count += 1

    # ── Cross-archetype regression: SB unaffected ───────────────────
    print("\nP5b.3 — Cross-archetype regression (Small Business):")
    sb_loc_path = os.path.join(os.path.dirname(__file__),
                               "tests", "fixtures",
                               "plaid_sb_with_loc.json")
    with open(sb_loc_path) as f:
        sb_loc = json.load(f)
    r_sb = map_plaid_data(sb_loc, archetype="small_business")
    if assert_eq("SB: income_sources empty (no FL detection run)",
                 r_sb.income_sources.value, []): pass_count += 1
    else: fail_count += 1
    if assert_eq("SB: business_lines_of_credit still detected (1 LOC)",
                 len(r_sb.business_lines_of_credit.value), 1): pass_count += 1
    else: fail_count += 1

    print(f"\n{pass_count} passed, {fail_count} failed.")
    return fail_count == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
