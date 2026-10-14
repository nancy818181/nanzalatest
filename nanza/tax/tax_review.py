"""2.9.98: "Rules for the tax adviser" - every payroll and VAT rule the program applies, with the value in THIS company's
settings on a date, its source and whether it is law already confirmed or still to confirm. Print it (PDF / Excel), give it
to the tax adviser, and correct any value in Payroll > Tax & NSSF Settings (or Accounting Setup for VAT)."""
from __future__ import annotations

from decimal import Decimal

from database_common import display_date, iso_date

CONFIRMED, CONFIRM, PENDING = "Law / decree - confirmed", "To confirm with the tax adviser", "Announced, not law - not applied"


def _money(value):
    try: return f"{Decimal(str(value)):,.0f}"
    except Exception: return str(value or "")


ADVISER_KEY = "tax_adviser_confirmation"


def adviser(db):
    """2.9.100: the tax adviser who checked the rules (name, licence, date, notes) - or {}."""
    import json
    with db.connect() as connection:
        row = connection.execute("SELECT value FROM app_settings WHERE key=?", (ADVISER_KEY,)).fetchone()
    try: return json.loads(row["value"]) if row and row["value"] else {}
    except (TypeError, ValueError): return {}


def save_adviser(db, item, user_id=None):
    import json
    name = str(item.get("name") or "").strip()
    if not name: raise ValueError("Enter the name of the tax adviser who checked the rules")
    record = {"name": name, "licence": str(item.get("licence") or "").strip(), "date": display_date(iso_date(item.get("date"), "Date of the check")),
              "notes": str(item.get("notes") or "").strip()[:500]}
    with db.connect() as connection:
        connection.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (ADVISER_KEY, json.dumps(record)))
        connection.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,datetime('now'))",
                           (user_id, "confirm", "tax_rules", json.dumps(record)))
    return record


def build(db, date):
    day = iso_date(date, "Date")
    s = db.payroll_settings_for(day) or {}
    brackets = s.get("tax_brackets") or []
    previous = 0; bands = []
    for limit, rate in brackets:
        bands.append(f"{rate * 100:g}% {'above ' + _money(previous) if limit is None else 'to ' + _money(limit)}")
        previous = limit or previous
    try: vat = db.settings().get("vat_rate") or "11"
    except Exception: vat = "11"
    rows = [
        ["Salary tax", "Annual brackets", "; ".join(bands) or "-", "Budget Law 324/2024", CONFIRM],
        ["Salary tax", "Personal (single) deduction / year", _money(s.get("single_allowance")), "Law 324/2024", CONFIRM],
        ["Salary tax", "Spouse deduction / year (dependent spouse)", _money(s.get("spouse_allowance")), "Law 324/2024", CONFIRM],
        ["Salary tax", "Child deduction / year, maximum children", f"{_money(s.get('child_allowance'))} x max {s.get('max_children_deduction') or 5}", "Law 324/2024", CONFIRM],
        ["Salary tax", "Rounding of the tax", f"up to LBP {_money(s.get('tax_rounding'))}" if Decimal(str(s.get("tax_rounding") or 0)) else "none", "MoF Decision 1195 (25-11-2024)", CONFIRM],
        ["Salary tax", "Family changes during the year", "spouse from the month of marriage, child from the month of birth", "Practice (program 2.9.96)", CONFIRM],
        ["Exemptions", "Transport allowance exempt / working day", _money(s.get("transport_daily_exempt")), "Decree 12966/2024", CONFIRM],
        ["Exemptions", "Food allowance exempt / working day (from 10-02-2026)", "300,000", "Budget Law 2026 Art. 26 (program reading)", CONFIRM],
        ["Exemptions", "Schooling allowance exempt / year", _money(s.get("schooling_annual_exempt")), "MoF practice", CONFIRM],
        ["NSSF", "Employee sickness & maternity rate", f"{Decimal(str(s.get('employee_nssf_rate') or 0)) * 100:g}%", "CNSS decrees", CONFIRMED],
        ["NSSF", "Employer sickness & maternity rate", f"{Decimal(str(s.get('medical_rate') or 0)) * 100:g}%", "CNSS decrees", CONFIRMED],
        ["NSSF", "Family allowances rate", f"{Decimal(str(s.get('family_rate') or 0)) * 100:g}%", "CNSS decrees", CONFIRMED],
        ["NSSF", "End-of-service rate", f"{Decimal(str(s.get('end_service_rate') or 0)) * 100:g}%", "Social Security Law", CONFIRMED],
        ["NSSF", "Sickness & maternity ceiling / month", _money(s.get("medical_ceiling")), "Decree 887 (14-08-2025); Memo 801 said 140M", CONFIRM],
        ["NSSF", "Family allowances ceiling / month", _money(s.get("family_ceiling")), "Decree 2923 / Memo 831", CONFIRMED],
        ["NSSF", "Family allowance: spouse / child / cap per month",
         f"{_money(s.get('family_allowance_spouse'))} / {_money(s.get('family_allowance_child'))} / {_money(s.get('family_allowance_cap'))}", "Decree 2923 / Memo 831", CONFIRMED],
        ["Minimum wage", "Minimum wage / month", _money(s.get("minimum_wage")), "CNSS Memo 801 (01-08-2025)", CONFIRMED],
        ["VAT", "Standard rate", f"{vat}%", "VAT Law 379/2001 as amended", CONFIRMED],
        ["VAT", "Return and payment", "quarterly, within one month after the quarter", "VAT Law", CONFIRMED],
        ["VAT", "Utilities (electricity, water, telephone) - input VAT", "not recovered from 10-02-2026", "Budget Law 2026 Art. 30 (program reading)", CONFIRM],
        ["VAT", "Passenger cars - input VAT", "recovered on the first USD 30,000 of the price only", "Budget Law 2026 Art. 30 (program reading)", CONFIRM],
        ["VAT", "Partial deduction (mixed use)", "taxable / total revenue, per quarter", "VAT Law Art. 31", CONFIRMED],
        ["VAT", "VAT account per customer / supplier, closing at quarter end", "4421 / 4427 / 44216 / 44213 sub-accounts", "Lebanese practice (VAT 140)", CONFIRMED],
        ["Pending", "VAT at 12%", "not applied", "Announced", PENDING],
        ["Pending", "Transport allowance LBP 500,000 - 800,000 / day", "not applied", "Announced", PENDING],
    ]
    checked = adviser(db)  # 2.9.100: once the adviser has checked them, the rules show as confirmed by him
    if checked:
        label = f"Confirmed by the tax adviser {checked['name']}" + (f" ({checked['licence']})" if checked.get("licence") else "") + f" on {checked['date']}"
        rows = [row[:4] + [label] if row[4] == CONFIRM else row for row in rows]
    to_confirm = sum(1 for row in rows if row[4] == CONFIRM)
    status_line = (f"Checked by the tax adviser {checked['name']} on {checked['date']}" + (f" - {checked['notes']}" if checked.get("notes") else "")) if checked \
        else f"{to_confirm} rule(s) to confirm with the tax adviser"
    return {"title": "Rules for the Tax Adviser", "date": display_date(day), "to_confirm": to_confirm, "adviser": checked,
            "meta": [f"Values in this company's settings on {display_date(day)}", status_line,
                     "Correct a value in Payroll > Tax & NSSF Settings (VAT: Accounting Setup); every later payslip and return uses it."],
            "sections": [{"heading": "Payroll and VAT rules applied by the program", "headers": ["Area", "Rule", "Value used", "Source", "Status"], "rows": rows},
                         {"heading": "Adviser sign-off", "headers": ["Item", "Answer"],
                          "rows": [["Reviewed by (name, licence)", ""], ["Date", ""], ["Values to change (rule -> correct value)", ""], ["Signature", ""]]}]}


def settings_report(db, date):
    """2.9.100: Payroll > Tax & NSSF Settings on paper - every value of the period, the tax brackets, the NSSF periods, the family
    allowance by period and the posting accounts (Print / PDF)."""
    import json, lebanese_payroll
    day = iso_date(date, "Date"); s = db.payroll_settings_for(day) or {}
    pct = lambda v: f"{Decimal(str(v or 0)) * 100:g}%"
    period = f"{display_date(s.get('date_from'))} - {display_date(s.get('date_to')) if s.get('date_to') else 'until further notice'}" if s.get("date_from") else "-"
    values = [
        ["Period of these settings", period],
        ["Single / spouse / child deduction (year)", f"{_money(s.get('single_allowance'))} / {_money(s.get('spouse_allowance'))} / {_money(s.get('child_allowance'))}"],
        ["Maximum children (tax deduction)", s.get("max_children_deduction") or "5"],
        ["Tax rounded up to", _money(s.get("tax_rounding")) or "-"],
        ["Employee NSSF rate", pct(s.get("employee_nssf_rate"))], ["Employer sickness & maternity rate", pct(s.get("medical_rate"))],
        ["Family allowances rate", pct(s.get("family_rate"))], ["End-of-service rate", pct(s.get("end_service_rate"))],
        ["Employee NSSF ceiling / month", _money(s.get("employee_ceiling"))], ["Sickness & maternity ceiling / month", _money(s.get("medical_ceiling"))],
        ["Family allowances ceiling / month", _money(s.get("family_ceiling"))], ["End-of-service ceiling",
                _money(s.get("end_service_ceiling")) if Decimal(str(s.get("end_service_ceiling") or 0)) else "no ceiling"],
        ["Transport exempt / working day", _money(s.get("transport_daily_exempt"))], ["Default transport days", s.get("default_transport_days") or ""],
        ["Schooling exempt / year, children", f"{_money(s.get('schooling_annual_exempt'))}, {s.get('schooling_max_children') or ''}"],
        ["Public school / child, cap", f"{_money(s.get('schooling_public_child'))} / {_money(s.get('schooling_public_cap'))}"],
        ["Private school / child, cap", f"{_money(s.get('schooling_private_child'))} / {_money(s.get('schooling_private_cap'))}"],
        ["Minimum wage / month", _money(s.get("minimum_wage"))],
        ["Family allowance spouse / child / cap (month)", f"{_money(s.get('family_allowance_spouse'))} / {_money(s.get('family_allowance_child'))} / {_money(s.get('family_allowance_cap'))}"],
    ]
    brackets, previous = [], 0
    for limit, rate in s.get("tax_brackets") or []:
        brackets.append([_money(previous), "and above" if limit is None else _money(limit), f"{rate * 100:g}%"]); previous = limit or previous
    with db.connect() as connection:
        periods = [dict(r) for r in connection.execute("SELECT * FROM payroll_settings ORDER BY date_from")]
    period_rows = [[display_date(p["date_from"]), display_date(p["date_to"]) if p.get("date_to") else "open", _money(p.get("employee_ceiling")), _money(p.get("medical_ceiling")),
                    _money(p.get("family_ceiling")), pct(p.get("employee_nssf_rate")), pct(p.get("medical_rate")), pct(p.get("family_rate")), pct(p.get("end_service_rate"))]
                   for p in periods]
    family = [[display_date(a), display_date(b) if b else "open", _money(sp), _money(ch), _money(cap)] for a, b, sp, ch, cap in lebanese_payroll.FAMILY_ALLOWANCE_PERIODS]
    labels = {"salary": "Salary", "overtime": "Overtime", "retro_salary": "Retro salary", "bonus": "Bonus", "thirteenth_month": "13th month", "commission": "Commission",
              "schooling": "Schooling", "transport": "Transport", "tax": "Payroll tax", "nssf": "NSSF", "payable": "Net salary payable",
              "director_remuneration": "Director remuneration", "family_allowance": "Family allocation", "employer_social": "Employer NSSF (expense)"}
    employees, managers = s.get("employee_account_map") or {}, s.get("manager_account_map") or {}
    accounts = [[label, employees.get(key) or "-", managers.get(key) or "-"] for key, label in labels.items()]
    checked = adviser(db)
    meta = [f"Settings in force on {display_date(day)}", "Lebanese law: Budget Law 324/2024, Decree 12966/2024, CNSS memos 793 / 801 / 831, Decrees 887 / 2923, Budget Law 2026"]
    meta.append(f"Checked by the tax adviser {checked['name']}" + (f" ({checked['licence']})" if checked.get("licence") else "") + f" on {checked['date']}" if checked
                else "Not yet confirmed by a tax adviser (Payroll > Tax & NSSF Settings > Adviser confirmation)")
    return {"title": "Tax & NSSF Settings", "meta": meta, "sections": [
        {"heading": "Values in force", "headers": ["Setting", "Value"], "rows": values},
        {"heading": "Salary tax brackets (annual LBP)", "headers": ["From", "To", "Rate"], "rows": brackets},
        {"heading": "NSSF ceilings and rates by period (LBP / month)", "headers": ["From", "To", "Employee ceiling", "Sickness ceiling", "Family ceiling",
                "Employee %", "Employer sick. %", "Family %", "EOS %"], "rows": period_rows},
        {"heading": "NSSF family allowance by period (LBP / month)", "headers": ["From", "To", "Spouse", "Per child (up to 5)", "Monthly maximum"], "rows": family},
        {"heading": "Standard posting accounts", "headers": ["Component", "Employees", "Managers"], "rows": accounts},
    ]}

