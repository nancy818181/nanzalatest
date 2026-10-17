"""Independent checks on saved payroll values; these do not certify tax eligibility."""
from decimal import Decimal


def review(records):
    zero = Decimal("0")
    totals, seen, issues = {}, set(), []
    drafts = 0
    for row in records:
        key = (row["employee_id"], row["period_date"][:7])
        if key in seen:
            issues.append([row.get("payroll_number", ""), "More than one payroll in the same employee month"])
        seen.add(key)
        if row.get("status") != "posted": drafts += 1
        values = [Decimal(str(row.get(name) or 0)) for name in
                  ("gross_salary", "family_allowance", "employee_nssf", "income_tax", "net_salary")]
        difference = values[0] + values[1] - values[2] - values[3] - values[4]
        if abs(difference) > Decimal(".01"):
            issues.append([row.get("payroll_number", ""), f"Gross + family allowance - NSSF - income tax - net = {difference} {row['currency']}"])
        total = totals.setdefault(row["currency"], [zero] * 6)
        for i, value in enumerate([*values, difference]): total[i] += value
    controls = {"record_count": len(records), "draft_count": drafts, "issue_count": len(issues),
                "arithmetic_agreed": not issues, "posted_only": not drafts}
    sections = [{"heading": "Payroll control totals (original currency)",
                 "headers": ["Currency", "Gross", "Family allowance", "Employee NSSF", "Income tax", "Net", "Difference (expected zero)"],
                 "rows": [[currency, *values] for currency, values in sorted(totals.items())], "total_rows": [], "fixed": True, "keep_together": True},
                {"heading": "Payroll preparation controls", "headers": ["Control", "Result"],
                 "rows": [["Payroll records", len(records)], ["Draft records (not final)", drafts],
                          ["Arithmetic / duplicate issues", len(issues)],
                          ["Scope", "Saved payroll values only. Review annual cumulative tax and statutory eligibility separately."]], "total_rows": []}]
    if issues:
        sections.append({"heading": "Payroll exceptions to resolve", "headers": ["Payroll", "Issue"], "rows": issues, "total_rows": []})
    return controls, sections
