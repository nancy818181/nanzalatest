"""Posted-ledger executive view. Missing forecasts/cash-flow mappings stay unavailable."""

from calendar import monthrange
from datetime import date
from decimal import Decimal
import management_pack
from database_common import iso_date

ZERO = Decimal(0)


def build(db, start, end, currency="USD", prior_db=None, language="en"):
    start, end = iso_date(start), iso_date(end)
    result = management_pack.brief(db, start, end, currency, prior_db, language)
    year = int(start[:4])
    months = []
    ledger = db._converted_lines(currency, start, end)
    with db.connect() as connection:
        budget = [
            dict(row)
            for row in connection.execute(
                """SELECT b.account_code,b.month,b.amount,a.type
            FROM budgets b JOIN accounts a ON a.code=b.account_code WHERE b.year=? AND b.currency=?
            AND b.department_id=0 AND b.project_id=0 AND a.type IN ('income','expense')""",
                (year, currency),
            )
        ]
    for month in range(int(start[5:7]), int(end[5:7]) + 1):
        first = max(start, f"{year}-{month:02d}-01")
        last = min(end, f"{year}-{month:02d}-{monthrange(year,month)[1]}")
        income = expense = ZERO
        for row in ledger:
            if not first <= row["iso_date"] <= last:
                continue
            value = Decimal(str(row["signed"].get(currency) or 0))
            if row["account_type"] == "income":
                income -= value
            elif row["account_type"] == "expense":
                expense += value
        planned = ZERO
        for row in budget:
            if row["month"] not in (0, month):
                continue
            amount = Decimal(str(row["amount"])) / (12 if row["month"] == 0 else 1)
            fraction = (
                Decimal((date.fromisoformat(last) - date.fromisoformat(first)).days + 1)
                / monthrange(year, month)[1]
            )
            planned += amount * fraction * (1 if row["type"] == "income" else -1)
        months.append(
            {
                "month": f"{year}-{month:02d}",
                "income": income,
                "expenses": expense,
                "profit": income - expense,
                "budget_profit": planned if budget else None,
            }
        )
    metrics = result["metrics"]
    metrics["profit_margin"] = (
        (metrics["profit"] * 100 / metrics["income"]) if metrics["income"] > 0 else None
    )
    metrics["budget_profit"] = (
        sum((row["budget_profit"] for row in months), ZERO) if budget else None
    )
    metrics["budget_variance"] = (
        metrics["profit"] - metrics["budget_profit"] if budget else None
    )
    metrics.update(
        operating_cash_flow=None, free_cash_flow=None, gross_margin=None, forecast=None
    )
    ar = language == "ar"
    notes = (
        [
            (
                "الموازنة العامة بالعملة المختارة؛ المبلغ السنوي موزع بالتساوي، والشهر الجزئي موزع حسب الأيام."
                if ar
                else "Company-wide budgets in the selected currency; annual amounts spread evenly and partial months prorated by calendar days."
            )
        ]
        if budget
        else [
            (
                "الموازنة غير مدخلة لهذه العملة؛ الفراغ لا يعني صفراً."
                if ar
                else "No company-wide budget in this currency; blank is not zero."
            )
        ]
    )
    notes.append(
        "التوقعات وهامش الربح الإجمالي والتدفق النقدي التشغيلي والحر غير محسوبة دون إعداد ومراجعة إضافيين."
        if ar
        else "Forecast, gross margin, operating and free cash flow are unavailable without additional reviewed inputs/mappings."
    )
    actions = []
    if metrics["overdue_receivables"] > 0:
        actions.append(
            "تابع تحصيل الذمم المتأخرة" if ar else "Follow up overdue customer balances"
        )
    if metrics["overdue_payables"] > 0:
        actions.append(
            "راجع جدول سداد الموردين" if ar else "Review the supplier payment schedule"
        )
    if metrics["profit"] < 0:
        actions.append(
            "راجع أسباب خسارة الفترة وتفاصيل المصاريف"
            if ar
            else "Review the period loss and expense detail"
        )
    if not actions:
        actions.append(
            "راجع مطابقة الأرصدة والمستندات غير المرحّلة"
            if ar
            else "Review reconciliations and unposted documents"
        )
    result.update(
        title="لوحة الإدارة المالية" if ar else "Executive Financial Dashboard",
        months=months,
        budget_available=bool(budget),
        actions=actions,
        notes=notes,
    )
    result["meta"] += notes
    result["sections"].append(
        {
            "heading": "الأداء الشهري" if ar else "Monthly performance",
            "headers": (
                ["الشهر", "الإيرادات", "المصاريف", "صافي الربح", "الربح بالموازنة"]
                if ar
                else ["Month", "Income", "Expenses", "Net profit", "Budget profit"]
            ),
            "rows": [
                [
                    row["month"],
                    row["income"],
                    row["expenses"],
                    row["profit"],
                    row["budget_profit"] if budget else "",
                ]
                for row in months
            ],
            "total_rows": [],
        }
    )
    result["sections"].append(
        {
            "heading": "متابعة الإدارة" if ar else "Management actions",
            "headers": [""],
            "rows": [[action] for action in actions],
            "total_rows": [],
        }
    )
    for section in result["sections"]:section["report_language"]=language
    return result
