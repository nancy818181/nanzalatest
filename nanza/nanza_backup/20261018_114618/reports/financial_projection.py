"""Small, explicit forecasts from complete monthly accounting periods."""
import calendar
from datetime import datetime

HORIZONS = {"Quarter (3 months)": 3, "6 Months": 6, "Yearly (12 months)": 12}
MAX_LONG_TERM_YEARS = 5


def completed_months(year, now=None):
    today = now or datetime.now()
    if year > today.year:
        raise ValueError("Choose this year or an earlier report year")
    return 12 if year < today.year else today.month - 1


def month_range(year, month):
    end = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{end:02d}"


def future_months(year, last, count):
    if count not in HORIZONS.values():
        raise ValueError("Choose Quarter, 6 Months, or Yearly")
    return [((year * 12 + last - 1 + offset) // 12,
             (year * 12 + last - 1 + offset) % 12 + 1) for offset in range(1, count + 1)]


def trailing_average(monthly, last, field, window=3):
    months = range(max(1, last - window + 1), last + 1)
    return sum(float(monthly.get(month, {}).get(field, 0)) for month in months) / len(months) if last else 0.0


# ---------------------------------------------------------------- long-term (up to 5 years) projection
def apply_growth(base_annual, years_ahead, growth_rate):
    """Compound base_annual by growth_rate (e.g. 0.10 for +10%) for the given whole number of years ahead."""
    return float(base_annual or 0) * ((1 + float(growth_rate or 0)) ** years_ahead)


def compound_factor(base_year, year, growth_rate=None, growth_by_year=None):
    """Cumulative growth factor from `base_year` up to (and including) `year`.

    When `growth_by_year` (a dict {year: rate}) has an entry for a given step year, that year's own
    rate is compounded; otherwise the single `growth_rate` is used for that step. This lets each future
    year carry a different growth assumption (e.g. 2027 +10%, 2028 +5%) instead of one flat rate.
    """
    growth_by_year = growth_by_year or {}
    default_rate = float(growth_rate or 0)
    factor = 1.0
    for step in range(base_year + 1, year + 1):
        rate = growth_by_year.get(step)
        rate = default_rate if rate in (None, "") else float(rate)
        factor *= (1 + rate)
    return factor


def year_fraction(target):
    """Fraction of `target`'s calendar year that has elapsed by `target` (a datetime), 1.0 on 31 December."""
    days_in_year = 366 if calendar.isleap(target.year) else 365
    day_of_year = (target - datetime(target.year, 1, 1)).days + 1
    return min(1.0, day_of_year / days_in_year)


def long_term_projection(base_year_values, base_year, target_date, growth_rate=None, budget_by_year=None, growth_by_year=None):
    """Year-by-year projection from `base_year_values` (a dict of category/account -> full base-year amount)
    up to `target_date` ("YYYY-MM-DD"), at most MAX_LONG_TERM_YEARS years ahead of `base_year`.

    For each future year, a saved budget for that year (via `budget_by_year`, a dict {year: {key: amount}})
    is used when present; otherwise the base-year amounts are compounded by the growth assumptions for the
    number of years ahead. `growth_by_year` (a dict {year: rate}) supplies a per-year growth rate that
    overrides the single `growth_rate` for that step, so each future year can grow at its own rate. The
    final year is prorated to the fraction of the year reached by `target_date` when that date does not
    land on 31 December.

    Returns a list of {"year", "date_to", "fraction", "source" ("budget"/"growth"), "growth_rate", "values"}.
    """
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("Enter a valid target date (YYYY-MM-DD)")
    try:
        base_year = int(base_year)
    except (TypeError, ValueError):
        raise ValueError("Enter a valid base year")
    if target.year == base_year:
        raise ValueError("Target date must be at least one year after the base year")
    if target.year - base_year > MAX_LONG_TERM_YEARS:
        raise ValueError(f"Target date cannot be more than {MAX_LONG_TERM_YEARS} years ahead of {base_year}")
    budget_by_year = budget_by_year or {}
    growth_by_year = growth_by_year or {}
    rows = []
    for year in range(base_year + 1, target.year + 1):
        years_ahead = year - base_year
        budget_values = budget_by_year.get(year)
        year_rate = growth_by_year.get(year)
        year_rate = float(growth_rate or 0) if year_rate in (None, "") else float(year_rate)
        if budget_values:
            values = {key: float(amount or 0) for key, amount in budget_values.items()}; source = "budget"
        else:
            factor = compound_factor(base_year, year, growth_rate, growth_by_year)
            values = {key: float(amount or 0) * factor for key, amount in base_year_values.items()}
            source = "growth"
        fraction = 1.0
        if year == target.year and not (target.month == 12 and target.day == 31):
            fraction = year_fraction(target)
            values = {key: amount * fraction for key, amount in values.items()}
        rows.append({"year": year, "date_to": target.strftime("%Y-%m-%d") if year == target.year else f"{year}-12-31",
                     "fraction": round(fraction, 4), "source": source, "growth_rate": year_rate, "values": values})
    return rows


# ---------------------------------------------------------------- 2.9.79: budget and cash budget from a chosen year and %
def _pct(value):
    """'10', '10%', '-5', '' -> 0.10, 0.10, -0.05, 0.0"""
    text = str(value if value is not None else "").strip().replace(",", "").rstrip("%").strip()
    if not text: return 0.0
    try: number = float(text)
    except ValueError: raise ValueError(f"Enter the % as a number, for example 10 or -5 (not '{value}')")
    if number <= -100: raise ValueError("A decrease cannot be 100% or more")
    return number / 100


def budget_from_year(monthly_by_account, types, base_year, budget_year, revenue_pct, expense_pct):
    """Draft budget of `budget_year` from the actual months of `base_year`, account by account:
    every month of the base year x (1 + revenue %) for income accounts and x (1 + expense %) for expense accounts,
    compounded once per year between the two years. Returns [(account, type, [12 months], annual)]."""
    years = int(budget_year) - int(base_year)
    if years < 1: raise ValueError("The budget year must come after the base year")
    if years > MAX_LONG_TERM_YEARS: raise ValueError(f"The budget year can be at most {MAX_LONG_TERM_YEARS} years after the base year")
    factors = {"income": (1 + _pct(revenue_pct)) ** years, "expense": (1 + _pct(expense_pct)) ** years}
    lines = []
    for code, months in sorted(monthly_by_account.items()):
        kind = types.get(code)
        if kind not in factors: continue
        values = [round(max(0.0, float(months.get(month, 0) or 0)) * factors[kind], 2) for month in range(1, 13)]
        if any(values): lines.append((code, kind, values, round(sum(values), 2)))
    return lines


def cash_budget(monthly_flows, opening_cash, base_year, budget_year, inflow_pct, outflow_pct):
    """Monthly cash budget of `budget_year`: the base year's cash in / out of each month x (1 + %) per year ahead.
    The years between the base year and the budget year are added to the opening cash.
    monthly_flows = {month: {"inflow": x, "outflow": y}} of the base year; opening_cash = cash at the end of the base year.
    Returns {"rows": [{month, opening, inflow, outflow, net, closing}], "opening": cash at 1 January of the budget year, "totals": {...}}."""
    years = int(budget_year) - int(base_year)
    if years < 1: raise ValueError("The cash budget year must come after the base year")
    if years > MAX_LONG_TERM_YEARS: raise ValueError(f"The cash budget year can be at most {MAX_LONG_TERM_YEARS} years after the base year")
    grow_in = 1 + _pct(inflow_pct); grow_out = 1 + _pct(outflow_pct)
    cash = float(opening_cash or 0)
    for ahead in range(1, years):  # years in between: their whole net cash movement
        cash += sum(float(v.get("inflow", 0)) * grow_in ** ahead - float(v.get("outflow", 0)) * grow_out ** ahead for v in monthly_flows.values())
    opening = round(cash, 2); rows = []
    for month in range(1, 13):
        flows = monthly_flows.get(month, {})
        inflow = round(float(flows.get("inflow", 0)) * grow_in ** years, 2); outflow = round(float(flows.get("outflow", 0)) * grow_out ** years, 2)
        start = round(cash, 2); cash = round(cash + inflow - outflow, 2)
        rows.append({"month": f"{int(budget_year)}-{month:02d}", "opening": start, "inflow": inflow, "outflow": outflow, "net": round(inflow - outflow, 2), "closing": cash})
    totals = {"inflow": round(sum(r["inflow"] for r in rows), 2), "outflow": round(sum(r["outflow"] for r in rows), 2)}
    totals["net"] = round(totals["inflow"] - totals["outflow"], 2)
    lowest = min(rows, key=lambda r: r["closing"])
    return {"rows": rows, "opening": opening, "closing": cash, "totals": totals, "lowest": {"month": lowest["month"], "closing": lowest["closing"]}}
