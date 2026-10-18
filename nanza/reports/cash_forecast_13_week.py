"""Short-term cash forecast from due receivables, payables, payroll and tax liabilities."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from database import iso_date

ZERO = Decimal("0")
WEEKS = 13
CASH_PREFIXES = ("511", "512", "519", "53")


def _amount(value):
    return Decimal(str(value or 0))


def _next_month_day(value, day=15):
    year, month = value.year, value.month + 1
    if month == 13:
        year += 1
        month = 1
    return date(year, month, day)


def _ledger_balance(database, accounts, as_of):
    if not accounts:
        return {}
    with database.connect() as db:
        rows = db.execute("""SELECT a.code,e.currency,e.entry_date,l.debit,l.credit,
            l.line_currency,l.amount,l.amount_lbp,l.amount_usd
            FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id JOIN accounts a ON a.id=l.account_id
            WHERE a.code IN (%s)""" % ",".join("?" for _ in accounts), tuple(accounts)).fetchall()
    result = defaultdict(Decimal)
    for row in rows:
        day = iso_date(row["entry_date"])
        if day > as_of.isoformat():
            continue
        native_currency = str(row["line_currency"] or row["currency"] or "USD").upper()
        if native_currency == row["currency"]:
            amount = _amount(row["debit"]) - _amount(row["credit"])
        else:
            field = "amount_lbp" if native_currency == "LBP" else "amount_usd" if native_currency == "USD" else None
            if field and row[field] not in (None, ""):
                amount = _amount(row[field])
                if _amount(row["credit"]) > 0:
                    amount = -amount
            else:
                amount = _amount(row["debit"]) - _amount(row["credit"])
        result[native_currency] += amount
    return result


def _tax_accounts(database):
    accounts = set()
    with database.connect() as db:
        for row in db.execute("SELECT payroll_tax_account,nssf_payable_account FROM payroll_settings"):
            accounts.update(code for code in row if code)
        rows = db.execute("SELECT code,name_en,name_ar,name_fr FROM accounts WHERE type='liability'").fetchall()
    for row in rows:
        text = " ".join(str(row[field] or "") for field in ("name_en", "name_ar", "name_fr")).casefold()
        if any(word in text for word in ("tax", "vat", "nssf", "social security",
                                         "ضريبة", "الضمان", "tva", "cotisation")):
            accounts.add(row["code"])
    try:
        accounts.add(database.default_accounts()["vat_payable"])
    except (AttributeError, KeyError):
        pass
    return sorted(accounts)


def build(database, today=None):
    """Return weekly totals by currency; undated statutory due dates are identified as estimates."""
    today = date.fromisoformat(iso_date(today)) if today else date.today()
    if isinstance(today, datetime):
        today = today.date()
    start = today - timedelta(days=today.weekday())
    horizon_end = start + timedelta(days=WEEKS * 7 - 1)
    movements = defaultdict(lambda: {"cash_in": ZERO, "cash_out": ZERO, "events": []})
    currencies = set()

    with database.connect() as db:
        invoices = db.execute("""SELECT id,invoice_number,kind,currency,total,amount_paid,invoice_date,due_date
            FROM invoices WHERE status='posted' AND cancelled_at IS NULL
            AND COALESCE(payment_status,'unpaid')<>'paid'""").fetchall()
        payroll = db.execute("""SELECT id,payroll_number,period_date,currency,net_salary
            FROM payroll_records WHERE status='posted'""").fetchall()

    for row in invoices:
        outstanding = _amount(row["total"]) - _amount(row["amount_paid"])
        if outstanding <= ZERO:
            continue
        raw_day = row["due_date"] or row["invoice_date"]
        if not raw_day:
            continue
        due = date.fromisoformat(iso_date(raw_day))
        if due > horizon_end:
            continue
        currency = str(row["currency"] or "USD").upper()
        currencies.add(currency)
        kind = "receipt" if row["kind"] == "sale" else "bill"
        scheduled = max(due, start)
        movements[(currency, scheduled)]["cash_in" if kind == "receipt" else "cash_out"] += outstanding
        movements[(currency, scheduled)]["events"].append({"type": kind, "reference": row["invoice_number"],
            "amount": str(outstanding), "due_date": due.isoformat(), "estimated_due_date": False})

    with database.connect() as db:
        paid_rows = db.execute("""SELECT s.payroll_id,COALESCE(DSUM(CAST(s.amount AS REAL)),0) paid
            FROM salary_payments s JOIN journal_entries e ON e.id=s.entry_id
            WHERE s.status='active' AND e.approval_status IS NULL GROUP BY s.payroll_id""").fetchall()
    paid_by_payroll = {row["payroll_id"]: _amount(row["paid"]) for row in paid_rows}
    for row in payroll:
        outstanding = _amount(row["net_salary"]) - paid_by_payroll.get(row["id"], ZERO)
        if outstanding <= ZERO:
            continue
        period = date.fromisoformat(iso_date(row["period_date"]))
        due = _next_month_day(period)
        if due > horizon_end:
            continue
        currency = str(row["currency"] or "USD").upper()
        currencies.add(currency)
        scheduled = max(due, start)
        movements[(currency, scheduled)]["cash_out"] += outstanding
        movements[(currency, scheduled)]["events"].append({"type": "payroll", "reference": row["payroll_number"],
            "amount": str(outstanding), "due_date": due.isoformat(), "estimated_due_date": True})

    tax_accounts = _tax_accounts(database)
    tax_balances = _ledger_balance(database, tax_accounts, today)
    for currency, balance in tax_balances.items():
        if balance >= ZERO:
            continue
        balance = -balance
        due = today
        currencies.add(currency)
        movements[(currency, due)]["cash_out"] += balance
        movements[(currency, due)]["events"].append({"type": "tax", "reference": "Outstanding statutory liability",
            "amount": str(balance), "due_date": due.isoformat(), "estimated_due_date": True})

    cash_codes = []
    with database.connect() as db:
        cash_codes = [row["code"] for row in db.execute("SELECT code FROM accounts WHERE active=1")
                      if row["code"].startswith(CASH_PREFIXES)]
    opening = _ledger_balance(database, cash_codes, today)
    currencies.update(opening)
    currencies.update(currency for currency, _due in movements)
    currencies.add(str(database.settings().get("base_currency") or "USD").upper())
    rows = []
    for currency in sorted(currencies):
        balance = opening.get(currency, ZERO)
        for week in range(WEEKS):
            week_start = start + timedelta(days=week * 7)
            week_end = week_start + timedelta(days=6)
            values = {"cash_in": ZERO, "cash_out": ZERO}
            events = []
            for (event_currency, due), item in movements.items():
                if event_currency == currency and week_start <= due <= week_end:
                    values["cash_in"] += item["cash_in"]
                    values["cash_out"] += item["cash_out"]
                    events.extend(item["events"])
            opening_balance = balance
            net = values["cash_in"] - values["cash_out"]
            balance += net
            rows.append({"week": week + 1, "from": week_start.isoformat(), "to": week_end.isoformat(),
                "currency": currency, "opening": opening_balance, "cash_in": values["cash_in"],
                "cash_out": values["cash_out"], "net": net, "closing": balance, "events": events})

    return {"title": "13-week cash forecast", "from": start.isoformat(), "to": horizon_end.isoformat(),
        "weeks": WEEKS, "rows": rows, "assumptions": [
            "Invoice cash flow uses the unpaid balance and due date; documents without a due date use invoice date.",
            "Payroll due dates are estimated as the 15th of the month after the payroll period.",
            "Tax due dates are estimated in the current week because statutory due dates are not stored.",
            "Currencies are forecast separately; no foreign-exchange conversion is applied."
        ]}
