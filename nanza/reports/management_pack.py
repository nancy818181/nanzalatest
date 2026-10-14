"""2.9.82: the monthly management pack, and the budget variance alerts of the Dashboard.

Every figure is in one currency, with every transaction converted (LBP payroll, EUR expenses ...):
- results of the month and of the year to date against the budget and against the same period last year;
- balance sheet summary, cash and banks, customers / suppliers ageing, VAT position of the quarter, key ratios.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from database import display_date, iso_date
import projection_model as pm

ZERO = Decimal("0")
COSTS = ("cost_of_sales", "payroll", "operating", "depreciation", "finance", "income_tax")


def _budget(db, year, currency):
    """{code: [12 months]} (an annual amount alone is spread evenly)."""
    result = {}
    try: lines = db.list_budgets(year, currency)
    except Exception: lines = []
    for line in lines:
        months = [float(v or 0) for v in line["months"]]
        if not any(months) and line.get("annual"): months = [float(line["annual"]) / 12] * 12
        result[line["account_code"]] = (months, line.get("account_type"), line.get("account_name") or "")
    return result


def _lines(rows):
    totals = {key: 0.0 for key, _en, _ar in pm.LINES}
    for row in rows or []:
        if row.get("type") in ("income", "expense"): totals[pm.line_of(row["code"], row["type"])] += float(row.get("amount") or 0)
    return totals


def _budget_lines(budget, months):
    totals = {key: 0.0 for key, _en, _ar in pm.LINES}
    for code, (values, kind, _name) in budget.items():
        kind = kind or ("income" if str(code).startswith("7") else "expense")
        totals[pm.line_of(code, kind)] += sum(values[m - 1] for m in months)
    return totals


def _statement(totals):
    gross = totals["revenue"] - totals["cost_of_sales"]
    net = totals["revenue"] + totals["other_income"] - sum(totals[k] for k in COSTS)
    return {**totals, "gross_margin": gross, "net_result": net}


ORDER = (("revenue", "Revenue"), ("cost_of_sales", "Cost of sales"), ("gross_margin", "GROSS MARGIN"), ("payroll", "Personnel charges"),
         ("operating", "Operating expenses"), ("depreciation", "Depreciation & provisions"), ("other_income", "Other income"),
         ("finance", "Financial & non-operating charges"), ("income_tax", "Income tax"), ("net_result", "NET RESULT"))


def _pct(part, whole):
    return f"{part / whole * 100:,.1f}%" if whole else ""


def build(db, month_end, currency="USD", prior_db=None):
    end = iso_date(month_end); year, month = int(end[:4]), int(end[5:7])
    end = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    first = f"{year}-{month:02d}-01"; start = f"{year}-01-01"
    prior_end = f"{year - 1}-{month:02d}-{calendar.monthrange(year - 1, month)[1]:02d}"
    previous = prior_db if prior_db is not None else db
    month_actual = _statement(_lines(db.profit_and_loss_converted(first, end, currency)))
    ytd_actual = _statement(_lines(db.profit_and_loss_converted(start, end, currency)))
    month_prior = _statement(_lines(previous.profit_and_loss_converted(f"{year - 1}-{month:02d}-01", prior_end, currency)))
    ytd_prior = _statement(_lines(previous.profit_and_loss_converted(f"{year - 1}-01-01", prior_end, currency)))
    budget = _budget(db, year, currency)
    month_budget = _statement(_budget_lines(budget, [month])); ytd_budget = _statement(_budget_lines(budget, range(1, month + 1)))
    has_budget = bool(budget)
    pl_rows = []
    for key, label in ORDER:
        a, b, p = month_actual[key], month_budget[key], month_prior[key]; ya, yb, yp = ytd_actual[key], ytd_budget[key], ytd_prior[key]
        pl_rows.append([label, round(a, 2), round(b, 2) if has_budget else "", round(a - b, 2) if has_budget else "", round(p, 2),
                        round(ya, 2), round(yb, 2) if has_budget else "", round(ya - yb, 2) if has_budget else "", round(yp, 2)])
    # ---- balance sheet summary
    balances = db.balance_sheet_converted(end, currency)
    def total(prefixes, sign=1, only=None):
        value = 0.0
        for row in balances:
            digits = "".join(ch for ch in str(row["code"]) if ch.isdigit())
            if digits.startswith(prefixes) and (only is None or only(row["balance"])): value += row["balance"] * sign
        return value
    other_codes = ("42", "43", "44", "45", "46", "47", "48", "49")
    fixed = total(("2",)); stock = total(("3",)); customers = total(("41",)); other_receivable = total(other_codes, 1, lambda v: v > 0)
    cash = total(("5",)); suppliers = total(("40",), -1); other_payable = total(other_codes, -1, lambda v: v < 0); equity = total(("1",), -1)
    result_ytd = ytd_actual["net_result"]
    assets = fixed + stock + customers + other_receivable + cash; liabilities = equity + suppliers + other_payable + result_ytd
    bs_rows = [["Fixed assets (net)", round(fixed, 2)], ["Stock", round(stock, 2)], ["Customers", round(customers, 2)], ["Other receivables", round(other_receivable, 2)],
               ["Cash and banks", round(cash, 2)], ["TOTAL ASSETS", round(assets, 2)], ["Capital, reserves and long-term debts", round(equity, 2)],
               ["Result of the year to date", round(result_ytd, 2)], ["Suppliers", round(suppliers, 2)], ["Other payables (tax, NSSF, salaries ...)", round(other_payable, 2)],
               ["TOTAL EQUITY AND LIABILITIES", round(liabilities, 2)], ["Check (should be 0)", round(assets - liabilities, 2)]]
    cash_rows = [[f'{row["code"]} - {row["name_en"]}', round(row["balance"], 2)] for row in balances if str(row["code"]).startswith("5") and abs(row["balance"]) >= 0.005]
    # ---- ageing
    buckets = ("Current", "1-30", "31-60", "61-90", "Over 90")
    ageing = {"sale": {b: 0.0 for b in buckets}, "purchase": {b: 0.0 for b in buckets}}
    for row in db.aging_report(end):
        try: rate = float(db._converted_amount(Decimal("1"), row["currency"], currency, end)) if row["currency"] != currency else 1.0
        except Exception: rate = 0.0
        ageing[row["kind"]][row["bucket"]] += float(row["outstanding"]) * rate
    ageing_rows = [[label] + [round(ageing[kind][b], 2) for b in buckets] + [round(sum(ageing[kind].values()), 2),
                   _pct(sum(ageing[kind][b] for b in buckets[2:]), sum(ageing[kind].values()))] for kind, label in (("sale", "Customers"), ("purchase", "Suppliers"))]
    # ---- VAT of the quarter
    import vat_return
    quarter = (month - 1) // 3 + 1
    try:
        vat = vat_return.build_vat_return(db, year, quarter, None, False, prior_db)
        t = vat["totals_lbp"]; vc = vat["vat_currency"]
        vat_rows = [[f"Output VAT Q{quarter} to date ({vc})", t["total_output"]], [f"Deductible VAT ({vc})", t["total_input"]], [f"Net VAT ({vc})", t["net"]],
                    [f"Credit brought forward ({vc})", vat["credit_brought_forward_lbp"]], [f"VAT payable ({vc})", vat["payable_lbp"]],
                    [f"Credit carried forward ({vc})", vat["credit_carried_forward_lbp"]], ["Return", vat["status"]], ["Due date", display_date(vat["due_date"])]]
    except Exception as exc:
        vat_rows = [["VAT position", f"not available: {exc}"]]
    # ---- ratios
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    revenue = ytd_actual["revenue"]; purchases = ytd_actual["cost_of_sales"] + ytd_actual["operating"]
    current_assets = stock + customers + other_receivable + cash; current_liabilities = suppliers + other_payable
    ratio_rows = [["Gross margin % (year to date)", _pct(ytd_actual["gross_margin"], revenue)], ["Net margin % (year to date)", _pct(ytd_actual["net_result"], revenue)],
                  ["Personnel charges / revenue", _pct(ytd_actual["payroll"], revenue)],
                  ["Current ratio (current assets / current liabilities)", f"{current_assets / current_liabilities:,.2f}" if current_liabilities else ""],
                  ["Customer days (DSO)", f"{customers / revenue * days:,.0f}" if revenue else ""], ["Supplier days (DPO)", f"{suppliers / purchases * days:,.0f}" if purchases else ""],
                  ["Revenue vs same period last year", _pct(revenue - ytd_prior["revenue"], ytd_prior["revenue"]) if ytd_prior["revenue"] else ""],
                  ["Cash months (cash / monthly costs)", f"{cash / (sum(ytd_actual[k] for k in COSTS) / month):,.1f}" if sum(ytd_actual[k] for k in COSTS) else ""]]
    pl_headers = ["", f"{calendar.month_abbr[month]} {year}", "Budget", "Variance", f"{calendar.month_abbr[month]} {year - 1}", "Year to date", "Budget YTD", "Variance YTD", f"YTD {year - 1}"]
    sections = [{"heading": f"Results - {calendar.month_name[month]} {year} and year to date ({currency})", "headers": pl_headers, "rows": pl_rows, "total_rows": [2, 9]},
                {"heading": f"Balance sheet summary at {display_date(end)} ({currency})", "headers": ["", currency], "rows": bs_rows, "total_rows": [5, 10]},
                {"heading": f"Cash and banks at {display_date(end)} ({currency})", "headers": ["Account", currency], "rows": cash_rows or [["No cash or bank balance", ""]], "total_rows": []},
                {"heading": f"Customers and suppliers ageing at {display_date(end)} ({currency})", "headers": ["", *buckets, "Total", "Over 30 days"], "rows": ageing_rows, "total_rows": []},
                {"heading": f"VAT position - Q{quarter} {year}", "headers": ["", "Amount"], "rows": vat_rows, "total_rows": []},
                {"heading": "Key ratios", "headers": ["Ratio", "Value"], "rows": ratio_rows, "total_rows": []}]
    meta = [f"Monthly management pack - {calendar.month_name[month]} {year}", f"All figures in {currency}, every currency converted at the saved rates of each entry.",
            "Budget: the company budget of the year (Financial Reports > Budget)." if has_budget else "No company budget saved for this year: the budget columns are empty.",
            "Cost of sales = purchases (601 / 611) and the stock variation: post the Monthly Stock Variation (Inventory) for the true margin of the month."]
    return {"title": f"Management Pack {calendar.month_name[month]} {year}", "meta": meta, "sections": sections, "month_end": end, "currency": currency}


def budget_variances(db, year, upto_month, currency="USD", threshold_percent=10.0):
    """Accounts whose actual of the year to date passes the budget by more than threshold % (expenses over budget,
    revenue under budget), largest first."""
    year, upto_month = int(year), int(upto_month)
    budget = _budget(db, year, currency)
    if not budget: return []
    end = f"{year}-{upto_month:02d}-{calendar.monthrange(year, upto_month)[1]:02d}"
    actual = {r["code"]: (float(r["amount"]), r["type"], r["name_en"]) for r in db.profit_and_loss_converted(f"{year}-01-01", end, currency)}
    alerts = []
    for code, (months, kind, name) in budget.items():
        planned = sum(months[:upto_month]); real, real_kind, real_name = actual.get(code, (0.0, kind, name))
        kind = real_kind or kind or ("income" if str(code).startswith("7") else "expense")
        if planned <= 0: continue
        gap = (real - planned) if kind == "expense" else (planned - real)  # bad side: costs above / revenue below the budget
        if gap / planned * 100 > float(threshold_percent):
            alerts.append({"account": code, "name": real_name or name, "type": kind, "budget": round(planned, 2), "actual": round(real, 2),
                           "gap": round(gap, 2), "percent": round(gap / planned * 100, 1)})
    return sorted(alerts, key=lambda a: -a["gap"])
