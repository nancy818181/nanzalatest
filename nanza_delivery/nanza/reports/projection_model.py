"""Financial projection and budget model (2.9.50).

Built from the books: the base is the profit and loss of the base year by account and by month (a year still in
progress is annualised from its complete months), plus the cash, customer and supplier balances at the end of the
base period. Each projected year has its own growth % per line (revenue, cost of sales, personnel, operating
expenses, other income, financial charges), investments and financing. Three scenarios (pessimistic / base /
optimistic) move revenue growth by a spread. Results:

- projected income statement, cash flow (indirect method) and key indicators per year
- budget by account per year, and the monthly budget of any projected year (seasonality of the base year)
- scenario comparison, and 3D charts (chart3d) for the screen, PDF and Excel.
"""
from __future__ import annotations

import calendar
from datetime import datetime

LINES = (("revenue", "Revenue", "الإيرادات"), ("cost_of_sales", "Cost of sales", "كلفة المبيعات"),
         ("payroll", "Personnel charges", "أعباء المستخدمين"), ("operating", "Operating expenses", "المصاريف التشغيلية"),
         ("depreciation", "Depreciation & provisions", "الاستهلاكات والمؤونات"), ("other_income", "Other income", "إيرادات أخرى"),
         ("finance", "Financial & non-operating charges", "أعباء مالية وغير تشغيلية"), ("income_tax", "Income tax", "ضريبة الدخل"))
LINE_NAMES = {key: en for key, en, _ar in LINES}
GROWTH_FIELDS = (("revenue", "Revenue %"), ("cost_of_sales", "Cost of sales %"), ("payroll", "Personnel %"), ("operating", "Operating exp. %"),
                 ("other_income", "Other income %"), ("finance", "Financial charges %"))
SCENARIOS = ("Pessimistic", "Base", "Optimistic")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MAX_YEARS = 5


def line_of(code, account_type):
    """Lebanese chart: 70-73 sales, 74-78 other income, 60-61 purchases, 63 personnel, 65 depreciation,
    67-68 financial / non-operating, 69 income tax, 62 / 64 / 66 operating expenses."""
    code = str(code or "")
    if account_type == "income" or code.startswith("7"):
        return "revenue" if code[:2] in ("70", "71", "72", "73") or len(code) < 2 else "other_income"
    prefix = code[:2]
    return {"60": "cost_of_sales", "61": "cost_of_sales", "63": "payroll", "65": "depreciation", "67": "finance", "68": "finance",
            "69": "income_tax"}.get(prefix, "operating")


def default_year():
    return {"revenue": 10.0, "cost_of_sales": None, "payroll": 5.0, "operating": 5.0, "other_income": 0.0, "finance": 0.0, "capex": 0.0, "financing": 0.0}


def default_assumptions(base_year, years=3):
    return {"base_year": int(base_year), "years": int(years), "scenario_spread": 10.0, "tax_rate": 17.0, "dso": None, "dpo": None,
            "asset_life": 5.0, "per_year": {str(int(base_year) + i): default_year() for i in range(1, int(years) + 1)}}


def _f(value, default=0.0):
    if value in (None, ""): return default
    try: return float(str(value).replace(",", "").rstrip("%"))
    except ValueError: raise ValueError(f"'{value}' is not a number")


# ---------------------------------------------------------------- base from the books
def base_period(base_year, now=None):
    """(months available, label). A past year uses its 12 months; the current year its complete months."""
    today = now or datetime.now(); base_year = int(base_year)
    if base_year > today.year: raise ValueError("Choose this year or an earlier year as the base year")
    months = 12 if base_year < today.year else today.month - 1
    if months < 1: raise ValueError(f"No complete month in {base_year} yet; choose {base_year - 1} as the base year")
    label = f"Actual {base_year}" if months == 12 else f"{base_year} annualised (Jan-{MONTHS[months - 1]})"
    return months, label


def collect_base(monthly_rows, months_available):
    """monthly_rows: {month (1-12): [profit and loss rows {code, name_en, type, amount}]}.
    Returns {code: {"name","type","line","months":[12],"annual"}} with missing months filled by the average."""
    accounts = {}
    for month, rows in monthly_rows.items():
        for row in rows or []:
            if row.get("type") not in ("income", "expense"): continue
            item = accounts.setdefault(str(row["code"]), {"name": row.get("name_en") or "", "type": row["type"], "line": line_of(row["code"], row["type"]), "months": [0.0] * 12})
            item["months"][int(month) - 1] += float(row.get("amount") or 0)
    for item in accounts.values():
        known = item["months"][:months_available]; average = sum(known) / months_available if months_available else 0.0
        for index in range(months_available, 12): item["months"][index] = average
        item["annual"] = sum(item["months"])
    return {code: item for code, item in accounts.items() if any(abs(v) > 0.004 for v in item["months"])}


def balances_from(balance_rows):
    """Cash (class 5), customers (41) and suppliers (40) at the end of the base period, from balance sheet rows."""
    cash = receivables = payables = 0.0
    for row in balance_rows or []:
        code = str(row.get("code") or ""); balance = float(row.get("balance") or 0)
        if code.startswith("5"): cash += balance
        elif code.startswith("41"): receivables += balance
        elif code.startswith("40"): payables -= balance
    return {"cash": cash, "receivables": max(receivables, 0.0), "payables": max(payables, 0.0)}


def statement_from_rows(rows):
    """Income statement lines of a whole period from profit and loss rows (2.9.52: earlier years)."""
    totals = {line: 0.0 for line, _en, _ar in LINES}
    for row in rows or []:
        if row.get("type") in ("income", "expense"): totals[line_of(row["code"], row["type"])] += float(row.get("amount") or 0)
    return _statement(totals)


def historical_growth(history, base):
    """Average yearly revenue growth % from the earlier actual years up to the base (None when it cannot be measured)."""
    revenues = [statement["revenue"] for _label, statement in history] + [base["revenue"]]
    first = next((v for v in revenues if v > 0), None)
    if first is None or len(revenues) < 2 or base["revenue"] <= 0: return None
    years = len(revenues) - 1 - revenues.index(first)
    return round(((base["revenue"] / first) ** (1 / years) - 1) * 100, 1) if years > 0 else None


# ---------------------------------------------------------------- projection
def _lines_total(accounts, key="annual"):
    totals = {line: 0.0 for line, _en, _ar in LINES}
    for item in accounts.values(): totals[item["line"]] += item[key] if key == "annual" else item["months"][key]
    return totals


def _statement(values):
    v = dict(values)
    v["gross_profit"] = v["revenue"] - v["cost_of_sales"]
    v["ebitda"] = v["gross_profit"] - v["payroll"] - v["operating"] + v["other_income"]
    v["ebit"] = v["ebitda"] - v["depreciation"]
    v["profit_before_tax"] = v["ebit"] - v["finance"]
    v["net_profit"] = v["profit_before_tax"] - v["income_tax"]
    return v


def project(base_accounts, assumptions, balances=None, scenario="Base"):
    """The projection for one scenario. Returns {"years":[...], "base":{...}, "rows":{year: statement}, "cash":{year: {...}},
    "accounts":{year: {code: amount}}, "factors":{year: {line: factor}}}."""
    base_year = int(assumptions["base_year"]); count = int(assumptions.get("years") or 3)
    if not 1 <= count <= MAX_YEARS: raise ValueError(f"Project between 1 and {MAX_YEARS} years ahead")
    if not base_accounts: raise ValueError("There is no posted income or expense in the base period to project from")
    spread = _f(assumptions.get("scenario_spread"), 10.0) * {"Pessimistic": -1, "Base": 0, "Optimistic": 1}[scenario]
    tax_rate = _f(assumptions.get("tax_rate"), 17.0) / 100; life = max(1.0, _f(assumptions.get("asset_life"), 5.0))
    balances = balances or {"cash": 0.0, "receivables": 0.0, "payables": 0.0}
    base = _statement(_lines_total(base_accounts))
    revenue0 = base["revenue"]; spend0 = base["cost_of_sales"] + base["operating"]
    dso = assumptions.get("dso"); dpo = assumptions.get("dpo")
    dso = _f(dso) if dso not in (None, "") else (min(365.0, balances["receivables"] / revenue0 * 365) if revenue0 > 0 else 30.0)
    dpo = _f(dpo) if dpo not in (None, "") else (min(365.0, balances["payables"] / spend0 * 365) if spend0 > 0 else 30.0)
    years = [base_year + i for i in range(1, count + 1)]
    factors = {line: 1.0 for line, _en, _ar in LINES}
    rows = {}; cash = {}; accounts = {}; year_factors = {}
    receivable = balances["receivables"]; payable = balances["payables"]; closing = balances["cash"]; investments = 0.0
    per_year = assumptions.get("per_year") or {}
    for year in years:
        settings = {**default_year(), **(per_year.get(str(year)) or per_year.get(year) or {})}
        revenue_rate = _f(settings.get("revenue")) + spread
        factors["revenue"] *= 1 + revenue_rate / 100
        cost_rate = settings.get("cost_of_sales")
        factors["cost_of_sales"] = factors["revenue"] if cost_rate in (None, "") else factors["cost_of_sales"] * (1 + _f(cost_rate) / 100)
        for line in ("payroll", "operating", "other_income", "finance"):
            factors[line] *= 1 + _f(settings.get(line)) / 100
        capex = _f(settings.get("capex")); financing = _f(settings.get("financing"))
        values = {line: base[line] * factors[line] for line in ("revenue", "cost_of_sales", "payroll", "operating", "other_income", "finance")}
        # depreciation: the base charge continues; new investments depreciate over the asset life (half a year when bought)
        values["depreciation"] = base["depreciation"] + investments / life + capex / life / 2
        investments += capex
        before_tax = values["revenue"] - values["cost_of_sales"] - values["payroll"] - values["operating"] + values["other_income"] - values["depreciation"] - values["finance"]
        values["income_tax"] = max(0.0, before_tax) * tax_rate
        statement = _statement(values); rows[year] = statement
        factors["depreciation"] = values["depreciation"] / base["depreciation"] if base["depreciation"] else 1.0
        factors["income_tax"] = values["income_tax"] / base["income_tax"] if base["income_tax"] else 1.0
        year_factors[year] = dict(factors)
        accounts[year] = {code: item["annual"] * factors[item["line"]] for code, item in base_accounts.items()}
        new_receivable = statement["revenue"] * dso / 365; new_payable = (statement["cost_of_sales"] + statement["operating"]) * dpo / 365
        operating = statement["net_profit"] + statement["depreciation"] - (new_receivable - receivable) + (new_payable - payable)
        opening = closing; closing = opening + operating - capex + financing
        cash[year] = {"opening": opening, "net_profit": statement["net_profit"], "depreciation": statement["depreciation"],
                      "receivables_change": -(new_receivable - receivable), "payables_change": new_payable - payable, "operating": operating,
                      "capex": -capex, "financing": financing, "net_change": operating - capex + financing, "closing": closing,
                      "receivables": new_receivable, "payables": new_payable}
        receivable, payable = new_receivable, new_payable
    return {"scenario": scenario, "years": years, "base": base, "rows": rows, "cash": cash, "accounts": accounts, "factors": year_factors,
            "dso": dso, "dpo": dpo, "balances": balances}


def monthly_budget(base_accounts, projection, year):
    """{code: [12 amounts]} for a projected year, spread with the base year's monthly pattern of each account."""
    result = {}
    for code, item in base_accounts.items():
        annual = projection["accounts"][year][code]; months = item["months"]; total = sum(months)
        if total and all(v >= 0 for v in months) or total and all(v <= 0 for v in months):
            shares = [v / total for v in months]
        else: shares = [1 / 12] * 12
        values = [round(annual * share, 2) for share in shares]
        values[-1] = round(annual - sum(values[:-1]), 2)
        result[code] = values
    return result


def budget_lines(base_accounts, projection, year):
    """Lines for Database.save_budget (amounts cannot be negative: negative accounts are left out)."""
    lines = []
    for code, months in sorted(monthly_budget(base_accounts, projection, year).items()):
        if sum(months) <= 0 or any(v < 0 for v in months): continue
        lines.append({"account_code": code, "annual": round(sum(months), 2), "months": months})
    return lines


# ---------------------------------------------------------------- report sections
def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else 0.0


def _r(value):
    return round(float(value or 0), 2)


def report_sections(base_accounts, assumptions, balances, base_label, currency, scenario="Base", budget_year=None, history=None):
    """All the projection reports, each a section for report_export (with 3D charts where they help).
    history: [(label, statement)] of earlier actual years, shown before the base in the income statement."""
    projections = {name: project(base_accounts, assumptions, balances, name) for name in SCENARIOS}
    history = [(label, statement) for label, statement in (history or []) if any(abs(statement[k]) > 0.004 for k in ("revenue", "cost_of_sales", "payroll", "operating"))]
    p = projections[scenario]; years = p["years"]
    labels = [label for label, _s in history] + [base_label] + [str(y) for y in years]
    table = [statement for _l, statement in history] + [p["base"]] + [p["rows"][y] for y in years]
    sections = []
    # assumptions
    per_year = assumptions.get("per_year") or {}
    rows = []
    for year in years:
        s = {**default_year(), **(per_year.get(str(year)) or {})}
        rows.append([str(year)] + [("follows revenue" if key == "cost_of_sales" and s.get(key) in (None, "") else _f(s.get(key))) for key, _label in GROWTH_FIELDS]
                    + [_f(s.get("capex")), _f(s.get("financing"))])
    sections.append({"heading": f"Assumptions - {scenario} scenario (revenue growth {'+' if p['scenario'] == 'Optimistic' else '-' if p['scenario'] == 'Pessimistic' else '±'}"
                                f"{_f(assumptions.get('scenario_spread'), 10):g} points in the other scenarios)",
                     "headers": ["Year"] + [label for _key, label in GROWTH_FIELDS] + [f"Investments ({currency})", f"Financing ({currency})"], "rows": rows, "total_rows": []})
    sections.append({"heading": "Other assumptions", "headers": ["Item", "Value"], "rows": [
        ["Base period", base_label], ["Income tax rate %", _f(assumptions.get("tax_rate"), 17.0)], ["Customer collection days (DSO)", round(p["dso"], 1)],
        ["Supplier payment days (DPO)", round(p["dpo"], 1)], ["Asset life for new investments (years)", _f(assumptions.get("asset_life"), 5.0)],
        [f"Cash at end of base period ({currency})", _r(balances.get("cash"))], [f"Customers at end of base period ({currency})", _r(balances.get("receivables"))],
        [f"Suppliers at end of base period ({currency})", _r(balances.get("payables"))],
        ["Average revenue growth of the actual years %", "-" if historical_growth(history, p["base"]) is None else historical_growth(history, p["base"])]], "total_rows": []})
    # income statement
    def line(label, key, bold=False):
        return [label] + [_r(t[key]) for t in table], bold
    entries = [line("Revenue", "revenue"), line("Cost of sales", "cost_of_sales"), line("Gross profit", "gross_profit", True),
               (["Gross margin %"] + [_pct(t["gross_profit"], t["revenue"]) for t in table], False),
               line("Personnel charges", "payroll"), line("Operating expenses", "operating"), line("Other income", "other_income"),
               line("EBITDA", "ebitda", True), line("Depreciation & provisions", "depreciation"), line("Operating result (EBIT)", "ebit", True),
               line("Financial & non-operating charges", "finance"), line("Profit before tax", "profit_before_tax", True),
               line("Income tax", "income_tax"), line("NET PROFIT", "net_profit", True),
               (["Net margin %"] + [_pct(t["net_profit"], t["revenue"]) for t in table], False)]
    sections.append({"heading": f"Projected income statement - {scenario} ({currency})", "headers": ["Item"] + labels,
                     "rows": [r for r, _b in entries], "total_rows": [i for i, (_r_, bold) in enumerate(entries) if bold],
                     "chart": {"title": "Income statement by year (3D)", "series": ["Revenue", "Total costs", "EBITDA", "Net profit"], "categories": labels,
                               "values": [[t["revenue"] for t in table], [t["cost_of_sales"] + t["payroll"] + t["operating"] + t["depreciation"] + t["finance"] + t["income_tax"] for t in table],
                                          [t["ebitda"] for t in table], [t["net_profit"] for t in table]]}})
    # cash flow
    c = [p["cash"][y] for y in years]
    cash_rows = [["Opening cash"] + [_r(x["opening"]) for x in c], ["Net profit"] + [_r(x["net_profit"]) for x in c],
                 ["Add: depreciation"] + [_r(x["depreciation"]) for x in c], ["Change in customers (receivables)"] + [_r(x["receivables_change"]) for x in c],
                 ["Change in suppliers (payables)"] + [_r(x["payables_change"]) for x in c], ["Cash from operations"] + [_r(x["operating"]) for x in c],
                 ["Investments (capex)"] + [_r(x["capex"]) for x in c], ["Financing (loans / capital, net)"] + [_r(x["financing"]) for x in c],
                 ["Net change in cash"] + [_r(x["net_change"]) for x in c], ["CLOSING CASH"] + [_r(x["closing"]) for x in c]]
    sections.append({"heading": f"Projected cash flow (indirect method) - {scenario} ({currency})", "headers": ["Item"] + [str(y) for y in years],
                     "rows": cash_rows, "total_rows": [5, 8, 9],
                     "chart": {"title": "Cash flow by year (3D)", "series": ["Cash from operations", "Investments", "Financing", "Closing cash"],
                               "categories": [str(y) for y in years], "values": [[x["operating"] for x in c], [x["capex"] for x in c], [x["financing"] for x in c], [x["closing"] for x in c]]}})
    # key indicators
    kpi = []
    previous = p["base"]
    for year in years:
        t = p["rows"][year]; fixed = t["payroll"] + t["operating"] + t["depreciation"] + t["finance"] - t["other_income"]
        contribution = (t["revenue"] - t["cost_of_sales"]) / t["revenue"] if t["revenue"] else 0
        cash_row = p["cash"][year]; burn = -cash_row["net_change"] / 12 if cash_row["net_change"] < 0 else 0
        kpi.append([str(year), _pct(t["revenue"] - previous["revenue"], previous["revenue"]), _pct(t["gross_profit"], t["revenue"]), _pct(t["ebitda"], t["revenue"]),
                    _pct(t["net_profit"], t["revenue"]), _r(fixed / contribution) if contribution > 0 else "n/a",
                    (round(cash_row["closing"] / burn, 1) if burn and cash_row["closing"] > 0 else "-" if not burn else 0)])
        previous = t
    sections.append({"heading": "Key indicators", "headers": ["Year", "Revenue growth %", "Gross margin %", "EBITDA margin %", "Net margin %",
                                                                f"Break-even revenue ({currency})", "Cash runway (months, if cash falls)"], "rows": kpi, "total_rows": []})
    # scenarios
    scen_rows = []
    for name in SCENARIOS:
        q = projections[name]
        scen_rows.append([name, "Revenue"] + [_r(q["rows"][y]["revenue"]) for y in years])
        scen_rows.append([name, "Net profit"] + [_r(q["rows"][y]["net_profit"]) for y in years])
        scen_rows.append([name, "Closing cash"] + [_r(q["cash"][y]["closing"]) for y in years])
    sections.append({"heading": "Scenario comparison", "headers": ["Scenario", "Item"] + [str(y) for y in years], "rows": scen_rows, "total_rows": [],
                     "chart": {"title": "Net profit by scenario (3D)", "series": list(SCENARIOS), "categories": [str(y) for y in years],
                               "values": [[projections[n]["rows"][y]["net_profit"] for y in years] for n in SCENARIOS]}})
    # budget by account per year
    budget_rows = []
    for code, item in sorted(base_accounts.items()):
        budget_rows.append([code, item["name"], LINE_NAMES[item["line"]], _r(item["annual"])] + [_r(p["accounts"][y][code]) for y in years])
    income = [i for i, r in enumerate(budget_rows) if base_accounts[r[0]]["type"] == "income"]
    budget_rows.append(["", "TOTAL INCOME", "", _r(sum(budget_rows[i][3] for i in income))] + [_r(sum(budget_rows[i][4 + n] for i in income)) for n in range(len(years))])
    expense = [i for i, r in enumerate(budget_rows[:-1]) if base_accounts[r[0]]["type"] == "expense"]
    budget_rows.append(["", "TOTAL EXPENSES", "", _r(sum(budget_rows[i][3] for i in expense))] + [_r(sum(budget_rows[i][4 + n] for i in expense)) for n in range(len(years))])
    sections.append({"heading": f"Budget projection by account - {scenario} ({currency})", "headers": ["Account", "Name", "Line", base_label] + [str(y) for y in years],
                     "rows": budget_rows, "total_rows": [len(budget_rows) - 2, len(budget_rows) - 1]})
    # monthly budget of the chosen year
    year = int(budget_year) if budget_year and int(budget_year) in years else years[0]
    months = monthly_budget(base_accounts, p, year)
    month_rows = []
    totals = {"income": [0.0] * 12, "expense": [0.0] * 12}
    for code, values in sorted(months.items()):
        item = base_accounts[code]; month_rows.append([f"{code} - {item['name']}"[:34]] + [_r(v) for v in values] + [_r(sum(values))])
        totals[item["type"]] = [a + b for a, b in zip(totals[item["type"]], values)]
    result = [a - b for a, b in zip(totals["income"], totals["expense"])]
    month_rows += [["TOTAL INCOME"] + [_r(v) for v in totals["income"]] + [_r(sum(totals["income"]))],
                   ["TOTAL EXPENSES"] + [_r(v) for v in totals["expense"]] + [_r(sum(totals["expense"]))],
                   ["RESULT"] + [_r(v) for v in result] + [_r(sum(result))]]
    sections.append({"heading": f"Monthly budget {year} - {scenario} ({currency}, seasonality of the base period)", "headers": ["Account"] + list(MONTHS) + ["Year"],
                     "rows": month_rows, "total_rows": [len(month_rows) - 3, len(month_rows) - 2, len(month_rows) - 1],
                     "chart": {"title": f"Monthly budget {year} (3D)", "series": ["Income", "Expenses", "Result"], "categories": list(MONTHS),
                               "values": [totals["income"], totals["expense"], result]}})
    # monthly cash plan of the same year
    cash_year = p["cash"][year]; share_income = [v / sum(totals["income"]) if sum(totals["income"]) else 1 / 12 for v in totals["income"]]
    opening = cash_year["opening"]; plan = []
    for index in range(12):
        change = (cash_year["operating"]) * share_income[index] + (cash_year["capex"] + cash_year["financing"]) / 12
        closing = opening + change
        plan.append([MONTHS[index], _r(opening), _r(cash_year["operating"] * share_income[index]), _r(cash_year["capex"] / 12), _r(cash_year["financing"] / 12), _r(change), _r(closing)])
        opening = closing
    sections.append({"heading": f"Monthly cash plan {year} - {scenario} ({currency})", "headers": ["Month", "Opening cash", "From operations", "Investments",
            "Financing", "Net change", "Closing cash"],
                     "rows": plan, "total_rows": [], "chart": {"title": f"Cash by month {year} (3D)", "series": ["From operations", "Closing cash"], "categories": list(MONTHS),
                                                                "values": [[r[2] for r in plan], [r[6] for r in plan]]}})
    return projections, sections


def month_end(year, month):
    return f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
