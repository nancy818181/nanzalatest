"""Offline assistance. Suggestions are rules; forecasts are assumptions, not AI certainty."""

from datetime import date, timedelta
from decimal import Decimal
from database_common import iso_date
from nanza_delivery.whatsapp_daily_summary import cash_balance


def suggest_category(description, accounts=()):
    from nanza.ai_accountant.classifier import suggest_account

    return suggest_account(description, accounts)


def detect_duplicate(
    invoice_no, amount, date, database=None, *, currency=None, party_id=None, kind=None, exclude_id=None
):
    if database is None:
        raise ValueError("Select a company database first")
    number = database.invoice_number_key(invoice_no)
    if not number:
        return []
    day, amount = iso_date(date), Decimal(str(amount))
    if not amount.is_finite():
        raise ValueError("Invalid amount")
    found = []
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT id,invoice_number,invoice_date,total,currency,party_id,kind,status FROM invoices WHERE status NOT IN ('deleted','cancelled','void')"  # F1 (2.9.137): a void invoice is not a duplicate
        )
        for r in rows:
            if exclude_id is not None and r["id"] == int(exclude_id):
                continue
            if (
                currency
                and r["currency"] != currency
                or party_id is not None
                and r["party_id"] != int(party_id)
                or kind
                and r["kind"] != kind
            ):
                continue
            if (
                database.invoice_number_key(r["invoice_number"]) == number
                and iso_date(r["invoice_date"]) == day
                and Decimal(str(r["total"] or 0)) == amount
            ):
                found.append(dict(r))
    return found


def cashflow_forecast(database=None, *, as_of=None, currency="USD", history_days=90):
    if database is None:
        raise ValueError("Select a company database first")
    if currency not in database.currency_codes():
        raise ValueError("Choose a company currency")
    if not 7 <= int(history_days) <= 366:
        raise ValueError("History must be 7 to 366 days")
    day = date.fromisoformat(iso_date(as_of or date.today().isoformat()))
    first = max(day - timedelta(days=int(history_days) - 1), day.replace(month=1, day=1))
    observed_days = (day - first).days + 1
    # Actual cash movements only, excluding opening/closing journals.
    months = database.cash_flow_monthly(first.isoformat(), day.isoformat(), currency)
    inflow = sum((Decimal(str(r["inflow"])) for r in months), Decimal(0))
    outflow = sum((Decimal(str(r["outflow"])) for r in months), Decimal(0))
    with database.connect() as connection:
        history = connection.execute("SELECT MIN(entry_date) FROM journal_entries").fetchone()[0]
    balance = cash_balance(database, day.isoformat(), currency)
    # Never extrapolate from an empty/new company or fabricate zero-growth confidence.
    available = history is not None and bool(months)
    average = (inflow - outflow) / observed_days if available else None
    points = (
        [{"date": (day + timedelta(days=i)).isoformat(), "balance": balance + average * i} for i in range(31)]
        if available
        else []
    )
    return {
        "currency": currency,
        "opening_cash": balance,
        "daily_average": average,
        "points": points,
        "available": available,
        "history_days": observed_days,
        "history_from": first.isoformat(),
        "assumption": "30-day illustration using average historical cash movement; no receivables/payables added. Selected company/year only. Not a commitment forecast.",
    }


def explain_profit_loss(database=None, *, start, end, currency="USD", language="en"):
    if database is None:
        raise ValueError("Select a company database first")
    first, last = date.fromisoformat(iso_date(start)), date.fromisoformat(iso_date(end))
    if first > last:
        raise ValueError("Invalid period")
    duration = (last - first).days + 1
    prior_end = first - timedelta(days=1)
    prior_start = prior_end - timedelta(days=duration - 1)
    if prior_start.year != first.year:
        return (
            "المقارنة تحتاج ملف السنة السابقة؛ لا يوجد تفسير موثوق حالياً."
            if language == "ar"
            else "Comparison needs the prior-year file; no reliable explanation is available."
        )
    current = database.profit_and_loss(first.isoformat(), last.isoformat(), currency)
    previous = database.profit_and_loss(prior_start.isoformat(), prior_end.isoformat(), currency)
    if not previous:
        return (
            "لا توجد بيانات مقارنة مرحّلة." if language == "ar" else "No posted comparison data is available."
        )

    def profit(rows):
        return sum(
            (Decimal(str(r["amount"])) * (1 if r["type"] == "income" else -1) for r in rows), Decimal(0)
        )

    a, b = profit(current), profit(previous)
    old = {r["code"]: Decimal(str(r["amount"])) for r in previous if r["type"] == "expense"}
    changes = sorted(
        (
            (Decimal(str(r["amount"])) - old.get(r["code"], Decimal(0)), r["name_en"])
            for r in current
            if r["type"] == "expense"
        ),
        reverse=True,
    )
    percentage = (
        f"{(a-b)/abs(b)*100:+.1f}%" if b else ("غير متاح" if language == "ar" else "not meaningful from zero")
    )
    driver = next(((delta, name) for delta, name in changes if delta > 0), None)
    if language == "ar":
        text = f"صافي الربح {a:,.2f} {currency}؛ التغيّر {a-b:+,.2f} ({percentage}) مقارنة بالفترة السابقة المساوية."
        return text + (
            f" أكبر زيادة بالمصاريف: {driver[1]} بقيمة {driver[0]:,.2f}. هذه مساهمة حسابية وليست إثباتاً للسبب."
            if driver
            else " لا توجد زيادة مصاريف محددة لتفسير التغيّر."
        )
    text = f"Net profit {a:,.2f} {currency}; change {a-b:+,.2f} ({percentage}) versus the preceding equal-length period."
    return text + (
        f" Largest expense increase: {driver[1]} by {driver[0]:,.2f}. This is a numerical contributor, not proof of causation."
        if driver
        else " No expense increase identified as a contributor."
    )
