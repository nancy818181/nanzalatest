"""Dashboard data and PDF export for an analytic study."""
from __future__ import annotations

from nanza.ui.i18n import tr


def build_report(study, filters=None):
    filters = dict(filters or {})
    totals = study.get("totals") or {}
    expenses = study.get("expenses") or {}
    profitability = study.get("profitability") or {}
    cashflow = study.get("cashflow") or {}
    categories = expenses.get("top_10") or []
    vendors = profitability.get("vendors") or []
    projects = profitability.get("projects") or []
    quarters = cashflow.get("quarters") or []
    budget_rows = study.get("budgets") or []
    pnl_check = study.get("pnl_check") or {}
    language = filters.get("language", "en")
    kpis = [
        {"label": tr(language, "revenue"), "value": totals.get("revenue", 0), "border": "#d4a017", "value_color": "#0a1931"},
        {"label": tr(language, "gross_profit"), "value": totals.get("gross_profit", 0), "border": "#d4a017", "value_color": "#0a1931"},
        {"label": tr(language, "net_profit"), "value": totals.get("net_profit", 0), "border": "#d4a017", "value_color": "#0a1931"},
        {"label": tr(language, "expenses"), "value": totals.get("expenses", 0) + totals.get("cost_of_sales", 0), "border": "#d4a017", "value_color": "#0a1931"},
    ]
    months = (study.get("expenses") or {}).get("monthly_seasonality") or []
    chart_data = {
        "expense_trend": {"type": "line", "categories": [row["month"] for row in months],
                          "series": [{"name": "Expense", "values": [row["expense"] for row in months]}]},
        "expense_mix": {"type": "pie", "categories": [row["name"] for row in categories],
                        "values": [row["cost_of_sales"] + row["expenses"] for row in categories]},
        "vendor_spend": {"type": "bar", "categories": [row["name"] for row in vendors[:10]],
                         "series": [{"name": "Spend", "values": [row["cost_of_sales"] + row["expenses"] for row in vendors[:10]]}]},
        "profitability": {"type": "waterfall", "categories": ["Revenue", "Cost of sales", "Expenses", "Net profit"],
                          "values": [totals.get("revenue", 0), -totals.get("cost_of_sales", 0),
                                     -totals.get("expenses", 0), totals.get("net_profit", 0)]},
        "cashflow_quarters": {"type": "bar", "categories": [row["quarter"] for row in quarters],
                              "series": [{"name": "Cash in", "values": [row["cash_in"] for row in quarters]},
                                         {"name": "Cash out", "values": [row["cash_out"] for row in quarters]}]},
    }
    chart_specs = {
        "expense_trend": {"title": "Monthly expense trend", "series": ["Expenses"],
                          "categories": [row["month"] for row in months],
                          "values": [[row["expense"] for row in months]]},
        "expense_mix": {"title": "Expense categories", "series": ["Spend"],
                        "categories": [row["name"] for row in categories],
                        "values": [[row["cost_of_sales"] + row["expenses"] for row in categories]]},
        "vendor_spend": {"title": "Vendor spend", "series": ["Spend"],
                         "categories": [row["name"] for row in vendors[:10]],
                         "values": [[row["cost_of_sales"] + row["expenses"] for row in vendors[:10]]]},
        "project_profit": {"title": "Project contribution", "series": ["Revenue", "Net contribution"],
                           "categories": [row["name"] for row in projects[:10]],
                           "values": [[row["revenue"] for row in projects[:10]],
                                      [row["net_contribution"] for row in projects[:10]]]},
        "cashflow_quarters": {"title": "Quarterly cashflow", "series": ["Cash in", "Cash out"],
                              "categories": [row["quarter"] for row in quarters],
                              "values": [[row["cash_in"] for row in quarters], [row["cash_out"] for row in quarters]]},
        "budget_variance": {"title": "Budget variance by account", "series": ["Variance"],
                    "categories": [row["category"] for row in budget_rows[:15]],
                    "values": [[row["variance"] for row in budget_rows[:15]]]},
    }
    sections = [
        {"key": "executive_summary", "heading": tr(language, "executive_summary"), "headers": ["KPI", study.get("currency", "USD")],
         "rows": [[item["label"], round(float(item["value"] or 0), 2)] for item in kpis], "total_rows": []},
        {"key": "project_profitability", "heading": tr(language, "project_profitability"), "headers": ["Project", "Revenue", "Cost of sales", "Expenses", "Net contribution", "Net margin %"],
         "rows": [[row["name"], row["revenue"], row["cost_of_sales"], row["expenses"], row["net_contribution"],
                   row["net_margin_percent"] if row["net_margin_percent"] is not None else "Unavailable"] for row in projects[:25]],
         "total_rows": [], "chart": chart_specs["project_profit"]},
        {"key": "expense_categories", "heading": tr(language, "expense_categories"), "headers": ["Category", "Cost of sales", "Other expenses", "Total"],
         "rows": [[row["name"], row["cost_of_sales"], row["expenses"], row["cost_of_sales"] + row["expenses"]] for row in categories],
         "total_rows": [], "chart": chart_specs["expense_mix"]},
        {"key": "vendor_spend", "heading": tr(language, "vendor_spend"), "headers": ["Vendor", "Cost of sales", "Other expenses", "Spend share %", "Margin status"],
         "rows": [[row["name"], row["cost_of_sales"], row["expenses"], row["share_of_expense_percent"],
                   "Revenue-linked" if row["margin_available"] else "Spend only; margin unavailable"] for row in vendors[:25]],
         "total_rows": [], "chart": chart_specs["vendor_spend"]},
        {"key": "quarterly_cashflow", "heading": tr(language, "quarterly_cashflow"), "headers": ["Quarter", "Currency", "Opening", "Cash in", "Cash out", "Net", "Closing", "Status"],
         "rows": [[row["quarter"], row["currency"], row["opening"], row["cash_in"], row["cash_out"], row["net"], row["closing"], row["status"]]
                  for row in quarters], "total_rows": [], "chart": chart_specs["cashflow_quarters"]},
        {"key": "budget_variances", "heading": tr(language, "budget_variances"), "headers": ["Account", "Type", "Budget", "Actual", "Variance", "Variance %", "Adverse"],
         "rows": [[row["category"], row["type"].title(), row["budget"], row["actual"], row["variance"],
               row["variance_percent"], "Yes" if row["adverse"] else "No"] for row in budget_rows],
         "total_rows": [], "chart": chart_specs["budget_variance"]},
        {"key": "actionable_insights", "heading": tr(language, "actionable_insights"), "headers": ["Severity", "Insight"],
         "rows": [[row["severity"], row["text"]] for row in study.get("insights", [])], "total_rows": []},
    ]
    warning = None
    if pnl_check and not pnl_check.get("matches", True):
        differences = pnl_check.get("totals") or {}
        difference = sum(abs(float(item.get("difference") or 0)) for item in differences.values())
        warning = tr(language, "analytic_unreconciled").format(difference=difference)
        details = [[name.replace("_", " ").title(), item.get("difference", 0)]
                   for name, item in differences.items()]
        sections.insert(0, {"key": "reconciliation_warning", "heading": warning, "headers": ["P&L check", "Difference"],
                            "rows": details, "total_rows": []})
    meta = [
        tr(language, "analytic_report_period").format(
            start=study.get("from_date") or "All", end=study.get("to_date") or "All"),
        tr(language, "analytic_report_currency").format(currency=study.get("currency", "USD")),
        tr(language, "analytic_report_margin_note"),
    ]
    warnings = list(study.get("warnings") or [])
    meta.extend(warnings)
    if warning:
        meta.insert(0, warning)
    return {"title": tr(filters.get("language", "en"), "analytic_study_title"),
            "warning": warning, "warnings": warnings, "filters": filters, "kpis": kpis,
            "charts": chart_data, "charts3d": chart_specs, "sections": sections, "meta": meta}


def export_pdf(path, report):
    from report_export import export_sections_pdf
    return export_sections_pdf(path, report["title"], report.get("meta", []), report.get("sections", []))


def export_excel(path, report):
    from report_export import export_sections_excel
    return export_sections_excel(path, report["title"], report.get("meta", []), report.get("sections", []))
