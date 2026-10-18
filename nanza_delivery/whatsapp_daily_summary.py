"""Local WhatsApp text preparation. This module never sends messages."""

from datetime import date as Date
from decimal import Decimal
from database_common import iso_date
from nanza_delivery.ageing_report import get_ageing_buckets


def cash_balance(database, day, currency):
    rows = database._native_trial_balance("0001-01-01", iso_date(day), currency)
    return sum(
        (
            r["closing_balance"]
            for r in rows
            if "".join(c for c in r["code"] if c.isdigit()).startswith(("51", "53"))
        ),
        Decimal(0),
    )


def daily_metrics(database, day, currency="USD"):
    day = iso_date(day)
    if currency not in database.currency_codes():
        raise ValueError("Choose a company currency")
    sales = Decimal(0)
    for row in database.list_invoices():
        if (
            row["kind"] == "sale"
            and row["status"] == "posted"
            and row["currency"] == currency
            and iso_date(row["invoice_date"]) == day
        ):
            sales += Decimal(str(row["total"] or 0)) * (-1 if row.get("doc_subtype") == "credit_note" else 1)
    expenses = sum(
        (
            Decimal(str(r["amount"]))
            for r in database.profit_and_loss(day, day, currency)
            if r["type"] == "expense"
        ),
        Decimal(0),
    )
    ageing = get_ageing_buckets(day, database, currency=currency)
    overdue = sorted(
        (r for r in ageing["parties"] if r["overdue"] > 0), key=lambda r: (-r["overdue"], r["party_name"])
    )[:3]
    return {
        "date": day,
        "currency": currency,
        "sales": sales,
        "expenses": expenses,
        "cash": cash_balance(database, day, currency),
        "overdue": overdue,
    }


def generate_whatsapp_summary(date, database=None, *, currency="USD", language="en") -> str:
    if database is None:
        raise ValueError("Select a company database first")
    m = daily_metrics(database, date, currency)
    ar = language == "ar"
    labels = (
        [
            "ملخص نانزا",
            "المبيعات المرحّلة اليوم (شاملة الضريبة)",
            "مصاريف قائمة الدخل اليوم",
            "رصيد النقد والمصارف الدفتري",
            "أعلى 3 عملاء متأخرين",
        ]
        if ar
        else [
            "NANZA daily summary",
            "Posted sales today (VAT included)",
            "P&L expenses today",
            "Book cash / bank balance",
            "Top 3 overdue customers",
        ]
    )
    lines = [
        f"📊 *{labels[0]} — {m['date']}*",
        f"💱 {currency}",
        f"💰 {labels[1]}: {m['sales']:,.2f}",
        f"🧾 {labels[2]}: {m['expenses']:,.2f}",
        f"🏦 {labels[3]}: {m['cash']:,.2f}",
        f"⏰ *{labels[4]}*",
    ]
    lines.extend(
        f"{i}. {r['party_name']}: {r['overdue']:,.2f} {currency}" for i, r in enumerate(m["overdue"], 1)
    )
    if not m["overdue"]:
        lines.append("لا توجد ذمم متأخرة" if ar else "No overdue balances")
    lines.append(
        "هذه السنة والشركة فقط؛ العملات غير محوّلة."
        if ar
        else "Selected company/year only; native currency, no FX conversion."
    )
    return "\n".join(lines)


def reminder_due(now, enabled, last_day=None):
    """Local reminder only, while the application is open; no catch-up from yesterday."""
    return bool(enabled and now.hour >= 18 and last_day != now.date().isoformat())


def preferences(database, user_id):
    with database.connect() as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workbench_preferences'"
        ).fetchone()
        row = (
            connection.execute(
                "SELECT * FROM workbench_preferences WHERE user_id=?", (int(user_id),)
            ).fetchone()
            if exists
            else None
        )
        return {
            "reminder_6pm": bool(row["reminder_6pm"]) if row else False,
            "last_day": row["last_day"] if row else None,
            "auto_send_available": False,
        }


def save_preferences(database, user_id, values):
    enabled = values.get("reminder_6pm")
    if not isinstance(enabled, bool):
        raise ValueError("Reminder must be true or false")
    last = values.get("last_day")
    if last is not None:
        last = iso_date(last)
    with database.connect() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS workbench_preferences (
            user_id INTEGER PRIMARY KEY, reminder_6pm INTEGER NOT NULL DEFAULT 0, last_day TEXT)""")
        connection.execute(
            """INSERT INTO workbench_preferences(user_id,reminder_6pm,last_day) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET reminder_6pm=excluded.reminder_6pm,last_day=excluded.last_day""",
            (int(user_id), int(enabled), last),
        )
    return preferences(database, user_id)
