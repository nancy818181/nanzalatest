"""2.9.81: Accounting Settings - what each company (and each user) sees, the default posting accounts in one table,
and the Year-End Check made before closing a year.

- Modules / reports: the company hides what it does not use (app_settings 'hidden_modules'); each user can hide
  more for himself (users.view_hidden in the main file). What is hidden disappears from the menu and the report tabs;
  the data and the user permissions (payroll, VAT, delete) are not changed.
- Default posting accounts: the accounts the program uses when a document does not name one (app_settings
  'default_accounts'). Every value is checked against the chart and its class.
- Year-End Check: the points an auditor looks at before the books of a year are closed.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from database import iso_date, utcnow

ZERO = Decimal("0")

# ---------------------------------------------------------------- modules and reports
# key: (label, where it is, what it hides)
MODULES = {
    "sales": ("Sales Invoice", "page", "sales_tab"),
    "uploaded": ("Uploaded Data", "page", "invoices_tab"),
    "journal_voucher": ("Journal Voucher", "page", "manual_tab"),
    "import": ("Import", "page", "import_tab"),
    "payments": ("Payment & Receipt", "page", "transactions_tab"),
    "purchases": ("Purchases & Expenses", "page", "purchases_tab"),
    "inventory": ("Inventory", "page", "inventory_tab"),
    "payroll": ("Payroll", "page", "payroll_tab"),
    "vat": ("Quarterly VAT", "page", "vat_tab"),
    "profit_loss": ("Profit & Loss", "page", "pnl_tab"),
    "financial_reports": ("Financial Reports", "page", "reports_tab"),
    "fixed_assets": ("Fixed Assets (Purchases & Expenses)", "tab", "Assets & Depreciation"),
    "production": ("Production (Inventory)", "tab", "Production"),
    "bank_reconciliation": ("Bank Reconciliation (Payment & Receipt)", "tab", "Bank Reconciliation"),
}
REPORTS = ("General Ledger", "Balance Sheet", "Lebanese VAT Report", "Cash Flow", "Cash Flow Outlook", "Cash Budget", "Comparative P&L",
           "Budget", "Projection & Budget (3D)", "Business Reports", "Management Pack")
ALWAYS_SHOWN = ("dashboard_tab", "journal_tab", "account_reports_tab", "settings_tab")  # never hidden: the books and the settings stay reachable


def _keys():
    return set(MODULES) | {f"report:{name}" for name in REPORTS}


def clean_hidden(values):
    """Only known keys, in a stable order."""
    known = _keys()
    return sorted({str(v) for v in (values or []) if str(v) in known})


def company_hidden(db):
    with db.connect() as connection:
        row = connection.execute("SELECT value FROM app_settings WHERE key='hidden_modules'").fetchone()
    try: return clean_hidden(json.loads(row["value"])) if row else []
    except (TypeError, ValueError): return []


def user_hidden(master_db, user_id):
    with master_db.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
        if "view_hidden" not in columns: return []
        row = connection.execute("SELECT view_hidden FROM users WHERE id=?", (int(user_id),)).fetchone()
    try: return clean_hidden(json.loads(row["view_hidden"] or "[]")) if row else []
    except (TypeError, ValueError): return []


def save_user_hidden(master_db, user_id, hidden):
    hidden = clean_hidden(hidden)
    with master_db.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
        if "view_hidden" not in columns: connection.execute("ALTER TABLE users ADD COLUMN view_hidden TEXT NOT NULL DEFAULT '[]'")
        connection.execute("UPDATE users SET view_hidden=? WHERE id=?", (json.dumps(hidden), int(user_id)))
    return hidden


# ---------------------------------------------------------------- default posting accounts
# key: (label, program default, allowed first digits, used for)
DEFAULT_ACCOUNTS = {
    "purchases": ("Purchases - when no account is chosen", "601100000", ("6",), "purchase invoices, imports"),
    "purchases_no_vat": ("Purchases without VAT", "601100001", ("6",), "the part of a purchase without VAT"),
    "expenses_import": ("Expenses imported without an account", "601100000", ("6",), "expenses read from Excel / PDF"),
    "sales": ("Sales / services - when no account is chosen", "713", ("7",), "sales invoices, imports"),
    "sales_goods": ("Sales of goods (items from stock)", "701100001", ("7",), "sales invoices with items"),
    "output_vat": ("Output VAT (sales)", "4427", ("4427",), "sales VAT"),
    "purchase_vat": ("Deductible VAT - purchases", "44210", ("442",), "purchase VAT"),
    "expense_vat": ("Deductible VAT - expenses", "44216", ("442",), "expense VAT"),
    "cash": ("Cash (expenses and payments)", "531", ("5",), "expenses, receipts and payments"),
    "bank_commission": ("Bank commission", "673900000", ("6",), "receipts and payments"),
    "exchange_gain": ("Exchange gain", "775100000", ("7",), "receipts, payments, DOE"),
    "exchange_loss": ("Exchange loss", "675100000", ("6",), "receipts, payments, DOE"),
    "vat_payable": ("VAT payable (settlement)", "4425", ("44",), "VAT settlement voucher"),
    "vat_credit": ("VAT credit / to recover (settlement)", "4429", ("44",), "VAT settlement voucher"),
    "vat_non_deductible": ("Non-deductible VAT expense (Art. 31)", "6459", ("6",), "VAT settlement voucher"),
}
PAYROLL_NOTE = "Payroll accounts (salaries 6311 / 6316, employer NSSF 6351, salary tax 4411, NSSF 4431) are set in Payroll > Tax & NSSF Settings > Standard Posting Accounts."


def default_accounts(db):
    """{key: code} - the company's choice, else the program default."""
    with db.connect() as connection:
        row = connection.execute("SELECT value FROM app_settings WHERE key='default_accounts'").fetchone()
    try: chosen = json.loads(row["value"]) if row else {}
    except (TypeError, ValueError): chosen = {}
    return {key: str(chosen.get(key) or spec[1]) for key, spec in DEFAULT_ACCOUNTS.items()}


def default_account(db, key):
    return default_accounts(db)[key]


def default_accounts_listing(db):
    codes = default_accounts(db)
    with db.connect() as connection:
        names = {row["code"]: row["name_en"] for row in connection.execute("SELECT code,name_en FROM accounts")}
    return [{"key": key, "label": spec[0], "account": codes[key], "account_name": names.get(codes[key], ""), "default": spec[1],
             "default_name": names.get(spec[1], ""), "used_for": spec[3]} for key, spec in DEFAULT_ACCOUNTS.items()]


def save_setup(db, item, user_id):
    """Company settings: hidden modules / reports and the default posting accounts."""
    with db.connect() as connection:
        names = {row["code"] for row in connection.execute("SELECT code FROM accounts")}
    changes = {}
    if "hidden" in item: changes["hidden_modules"] = json.dumps(clean_hidden(item.get("hidden")))
    if "budget_alert_percent" in item:  # 2.9.82: the Dashboard flags accounts off budget by more than this %
        try: percent = float(str(item.get("budget_alert_percent") or "10").replace("%", ""))
        except ValueError: raise ValueError("The budget alert % must be a number, for example 10")
        if not 0 < percent <= 1000: raise ValueError("The budget alert % must be between 0 and 1000")
        changes["budget_alert_percent"] = f"{percent:g}"
    if "approval_types" in item:  # 2.9.100: which kinds of documents need approval in this company
        import approvals
        approvals.save_types(db, item.get("approval_types") or [])
    elif "approval_required" in item:  # 2.9.93: documents prepared by users without "approve" wait for approval
        changes["approval_required"] = "1" if str(item.get("approval_required")).lower() in ("1", "true", "yes", "on") else "0"
        import approvals
        approvals.save_types(db, ["invoices"] if changes["approval_required"] == "1" else [])
    if "defaults" in item:
        current = default_accounts(db); chosen = {}
        for key, value in (item.get("defaults") or {}).items():
            if key not in DEFAULT_ACCOUNTS: continue
            code = str(value or "").split(" - ", 1)[0].strip() or DEFAULT_ACCOUNTS[key][1]
            label, _default, prefixes, _used = DEFAULT_ACCOUNTS[key]
            if code not in names: raise ValueError(f"{label}: account {code} is not in the chart of accounts")
            if not code.replace(".", "").startswith(prefixes): raise ValueError(f"{label}: account {code} must start with {' or '.join(prefixes)}")
            chosen[key] = code
        current.update(chosen)
        changes["default_accounts"] = json.dumps({k: v for k, v in current.items() if v != DEFAULT_ACCOUNTS[k][1]})
    with db.connect() as connection:
        for key, value in changes.items():
            connection.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        connection.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                           (user_id, "update", "accounting_setup", json.dumps(changes), utcnow()))
    return setup(db)


def _setting(db, key, default=""):
    with db.connect() as connection:
        row = connection.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def setup(db, master_db=None, user_id=None):
    with db.connect() as connection:
        row = connection.execute("SELECT value FROM app_settings WHERE key='budget_alert_percent'").fetchone()
    return {"budget_alert_percent": row["value"] if row else "10", "hidden": company_hidden(db), "user_hidden": user_hidden(master_db, user_id) if master_db is not None and user_id else [],
            "modules": [{"key": key, "label": spec[0]} for key, spec in MODULES.items()], "reports": list(REPORTS),
            "defaults": default_accounts_listing(db), "payroll_note": PAYROLL_NOTE,
            "approval_required": _setting(db, "approval_required", "0") == "1"}


# ---------------------------------------------------------------- Year-End Check
OK, WARNING, ERROR = "OK", "WARNING", "ERROR"


def year_end_check(db, year, previous_year_db=None):
    """[{status, check, detail, fix}] - every point is checked; nothing is changed."""
    import ledger_reports, vat_return, inventory, fixed_assets
    year = int(year); start, end = f"{year}-01-01", f"{year}-12-31"; results = []
    def add(status, check, detail, fix=""): results.append({"status": status, "check": check, "detail": detail, "fix": fix})
    try: lines = [r for r in ledger_reports._load_lines(db, {"posting_status": "posted", "first_column": "USD", "second_column": "LBP"}) if r["iso_date"] <= end]
    except ValueError as exc:
        add(ERROR, "Exchange rates", str(exc), "Settings > Exchange Rates: add the missing rate"); lines = []
    # 1. the books balance
    usd = sum((r["signed"]["USD"] or ZERO for r in lines), ZERO); lbp = sum((r["signed"]["LBP"] or ZERO for r in lines), ZERO)
    unbalanced = db.unbalanced_entries() if hasattr(db, "unbalanced_entries") else []
    if abs(usd) >= Decimal("0.05") or abs(lbp) >= 5 or unbalanced:
        add(ERROR, "Trial balance", f"Difference USD {usd:,.2f} / LBP {lbp:,.0f}; {len(unbalanced)} unbalanced entr{'y' if len(unbalanced) == 1 else 'ies'}",
            "General Journal: correct the entries listed in Security / Backup > unbalanced entries")
    else: add(OK, "Trial balance", "Debit = credit in USD and in LBP; every entry is balanced")
    with db.connect() as connection:
        invoices = [dict(r) for r in connection.execute("SELECT invoice_number,invoice_date,status FROM invoices WHERE status='review'")]
        payroll = [dict(r) for r in connection.execute("SELECT payroll_number,period_date FROM payroll_records WHERE status!='posted'")]
    def in_year(value):
        try: return start <= iso_date(value) <= end
        except ValueError: return False
    # 2. documents still in Review
    review = [r["invoice_number"] for r in invoices if in_year(r["invoice_date"])]
    add(WARNING if review else OK, "Documents in Review", (f"{len(review)} document(s) not posted: " + ", ".join(review[:6])) if review else "None",
        "Uploaded Data: review and post them, or delete them" if review else "")
    # 3. payroll saved but not posted
    open_payroll = [r["payroll_number"] for r in payroll if in_year(r["period_date"])]
    add(WARNING if open_payroll else OK, "Payroll not posted", (f"{len(open_payroll)} payroll(s): " + ", ".join(open_payroll[:6])) if open_payroll else "None",
        "Payroll: post them" if open_payroll else "")
    # 4. VAT: each quarter with VAT saved and agreeing with the books
    vat_issues = []; vat_quarters = 0
    for quarter in (1, 2, 3, 4):
        try: result = vat_return.build_vat_return(db, year, quarter, None, False, previous_year_db)
        except Exception as exc: vat_issues.append(f"Q{quarter}: {exc}"); continue
        if not result["documents"] and not result["saved"]: continue
        vat_quarters += 1
        if not result["saved"]: vat_issues.append(f"Q{quarter} not saved")
        elif result["changed_since_saved"]: vat_issues.append(f"Q{quarter} changed after saving")
        try:
            if not vat_return.ledger_check(db, result)["agreed"]: vat_issues.append(f"Q{quarter} differs from the books")
        except Exception as exc: vat_issues.append(f"Q{quarter} check: {exc}")
    add(WARNING if vat_issues else OK, "Quarterly VAT",
            "; ".join(vat_issues) if vat_issues else (f"{vat_quarters} quarter(s) saved and agreeing with the books" if vat_quarters else "No VAT in the year"),
        "Quarterly VAT: Generate, Check with the Books, Save Return, VAT Settlement Entry" if vat_issues else "")
    # 5. VAT accounts not settled at year end
    vat_left = {}
    for r in lines:
        if vat_return.vat_account_role(r["code"]): vat_left[str(r["code"])] = vat_left.get(str(r["code"]), ZERO) + (r["signed"]["LBP"] or ZERO)
    vat_left = {k: v for k, v in vat_left.items() if abs(v) >= 1}
    add(WARNING if vat_left else OK, "VAT accounts settled", ("Balances left: " + ", ".join(f"{k} {v:,.0f} LBP" for k, v in sorted(vat_left.items()))) if vat_left else "4427 and 442... are settled",
        "Quarterly VAT: post the VAT Settlement Entry of each quarter" if vat_left else "")
    # 6. receipts / payments not allocated
    with db.connect() as connection:
        free = [dict(r) for r in connection.execute("""SELECT x.payment_number,x.currency,p.name party,
            CAST(x.amount AS REAL)+CAST(COALESCE(x.exchange_difference,'0') AS REAL)-COALESCE((SELECT DSUM(CAST(a.amount AS REAL)) FROM payment_allocations a WHERE a.payment_id=x.id),0) free
            FROM payments x LEFT JOIN parties p ON p.id=x.party_id""")]
    free = [r for r in free if abs(r["free"] or 0) >= 0.01]
    add(WARNING if free else OK, "Receipts / payments allocated",
            (f"{len(free)} not (fully) allocated, e.g. " + ", ".join(f"{r['payment_number']} {r['party']} {r['free']:,.2f} {r['currency']}" for r in free[:4])) if free else "All allocated to invoices",
        "Payment & Receipt: open each one and Auto Allocate (the ageing already applies them oldest first)" if free else "")
    # 7. negative stock
    try:
        items = inventory.list_items(db, end)
        negative = [f"{i['sku']} {i['quantity']:g}" for i in items if i["quantity"] < -0.0005]
        add(ERROR if negative else OK, "Stock not negative", ("Negative on 31-12: " + ", ".join(negative[:6])) if negative else f"{len(items)} item(s) checked",
            "Inventory: enter the missing receipts / opening stock, or correct the issues" if negative else "")
    except Exception as exc: add(WARNING, "Stock", f"Could not be checked: {exc}")
    # 8. cash and bank accounts not negative (in their own currency)
    cash = {}
    for r in lines:
        digits = ledger_reports._digits(r["code"])
        if digits.startswith(("51", "53")):
            key = (str(r["code"]), r["account_currency"]); cash[key] = cash.get(key, ZERO) + (r["signed"].get("account") or ZERO)
    negative_cash = [f"{code} {cur} {value:,.2f}" for (code, cur), value in sorted(cash.items()) if value < Decimal("-0.005")]
    add(ERROR if negative_cash else OK, "Cash and bank not negative", ("Negative: " + ", ".join(negative_cash[:6])) if negative_cash else "No cash / bank account below zero",
        "A receipt or a bank statement line is missing; check the cash book / bank reconciliation" if negative_cash else "")
    # 9. suspense / transit accounts (47) cleared
    suspense = {}
    for r in lines:
        if ledger_reports._digits(r["code"]).startswith("47"): suspense[str(r["code"])] = suspense.get(str(r["code"]), ZERO) + (r["signed"]["USD"] or ZERO)
    suspense = {k: v for k, v in suspense.items() if abs(v) >= Decimal("0.01")}
    add(WARNING if suspense else OK, "Suspense accounts (47) cleared", ("Left: " + ", ".join(f"{k} {v:,.2f} USD" for k, v in sorted(suspense.items()))) if suspense else "Nothing left on 47...",
        "Journal Voucher: move each amount to its final account" if suspense else "")
    # 10. depreciation of the year posted
    missing = []
    try:
        for asset in fixed_assets.list_assets(db):
            if asset.get("status", "active") != "active": continue
            for row in fixed_assets.schedule(db, asset["id"]):
                if start <= row["period_end"] <= end and not row["posted"] and Decimal(str(row["amount"])) > 0:
                    missing.append(asset["asset_code"]); break
    except Exception as exc: missing.append(f"(not checked: {exc})")
    add(WARNING if missing else OK, "Depreciation posted", ("Months not posted for: " + ", ".join(missing[:8])) if missing else "Every month of the year is posted",
        "Purchases & Expenses > Assets > 3. Monthly Depreciation Table: post each month" if missing else "")
    # 11. foreign-currency balances revalued (DOE) at 31-12
    try:
        candidates = db.doe_candidates(f"31-12-{year}").get("items", [])
        def difference(c):  # LBP value at the rate of 31-12 less the LBP carried in the books
            try: return Decimal(str(c["balance"])) * Decimal(str(c["suggested_rate"])) - Decimal(str(c["carrying_lbp"]))
            except Exception: return ZERO
        to_revalue = [c for c in candidates if abs(difference(c)) >= 1000]  # under LBP 1,000 is rounding
        add(WARNING if to_revalue else OK, "Exchange differences (DOE) at 31-12",
            (f"{len(to_revalue)} balance(s) to revalue in LBP, e.g. " + ", ".join(f"{c['account']} {c['currency']}" for c in to_revalue[:5])) if to_revalue else "No LBP revaluation needed",
            "Journal Voucher > Automatic DOE at 31-12" if to_revalue else "")
    except Exception as exc: add(WARNING, "Exchange differences (DOE)", f"Could not be checked: {exc}")
    # 11b. 2.9.84: the same in the main currency of the books when it is not LBP (USD books, EUR books)
    main = str((db.settings() or {}).get("base_currency") or "USD").upper()
    if main != "LBP":
        try:
            candidates = db.doe_candidates(f"31-12-{year}", main).get("items", [])
            def difference_main(c):
                carrying = c.get(f"carrying_{main.lower()}", c.get("carrying"))
                try: return Decimal(str(c["balance"])) * Decimal(str(c["suggested_rate"])) - Decimal(str(carrying))
                except Exception: return ZERO
            to_revalue = [c for c in candidates if abs(difference_main(c)) >= 1]  # under 1 unit is rounding
            add(WARNING if to_revalue else OK, f"Exchange differences (DOE) in {main} at 31-12",
                (f"{len(to_revalue)} balance(s) to revalue in {main}, e.g. " + ", ".join(f"{c['account']} {c['currency']}" for c in to_revalue[:5])) if to_revalue else f"No {main} revaluation needed",
                f"Journal Voucher > Automatic DOE at 31-12 (basis {main})" if to_revalue else "")
        except Exception as exc: add(WARNING, f"Exchange differences (DOE) in {main}", f"Could not be checked: {exc}")
    # 12. customers in credit / suppliers in debit (information)
    parties = {}
    for r in lines:
        digits = ledger_reports._digits(r["code"])
        if len(digits) >= 9 and digits.startswith(("40", "41")): parties[str(r["code"])] = parties.get(str(r["code"]), ZERO) + (r["signed"]["USD"] or ZERO)
    odd = [f"{code} {value:,.2f}" for code, value in sorted(parties.items()) if (code.startswith("41") and value < Decimal("-0.01")) or (code.startswith("40") and value > Decimal("0.01"))]
    add(WARNING if odd else OK, "Customers / suppliers on the right side",
            ("Customers in credit / suppliers in debit (USD): " + ", ".join(odd[:6])) if odd else "Customers in debit, suppliers in credit",
        "Usually an advance or a payment on the wrong party: check their statements" if odd else "")
    errors = sum(1 for r in results if r["status"] == ERROR); warnings = sum(1 for r in results if r["status"] == WARNING)
    return {"year": year, "results": results, "errors": errors, "warnings": warnings,
            "summary": "Ready to close" if not errors and not warnings else f"{errors} error(s), {warnings} warning(s) before closing"}


def year_end_sections(check):
    rows = [[r["status"], r["check"], r["detail"], r["fix"]] for r in check["results"]]
    return [{"heading": f"Year-End Check {check['year']} - {check['summary']}", "headers": ["Status", "Check", "Result", "What to do"], "rows": rows, "total_rows": []}]
