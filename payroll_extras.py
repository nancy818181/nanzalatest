"""2.9.82: payroll additions - end-of-service indemnity provision, annual leave balances, and all the payslips of a month.

End of service (Lebanese Social Security Law, Art. 50-54): the indemnity is one month of the last salary for each year
of service; the NSSF pays it from the end-of-service contributions (8.5%) and the employer pays the difference.
The provision booked is that difference: indemnity less the contributions paid (those in Saber's payroll plus the
contributions paid before Saber, entered on the employee). It is an estimate for the accounts, not the NSSF settlement.

Annual leave (Labour Law Art. 39): 15 days a year with pay (the company or the employee can have another number);
the balance is the leave carried in + the days earned this year (pro rata) - the annual leave taken; its value is
the balance x the daily salary (monthly salary / 30).
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from database import display_date, iso_date, utcnow

ZERO = Decimal("0")
PROVISION_ACCOUNT, EXPENSE_ACCOUNT, REVERSAL_ACCOUNT = "1552.1", "6355", "7552.2"
LEAVE_TYPES = {"annual": "Annual leave", "sick": "Sick leave", "unpaid": "Unpaid leave", "other": "Other"}


def migrate(db):
    columns = {row["name"] for row in db.execute("PRAGMA table_info(employees)")}
    for column, definition in (("eos_paid_before", "TEXT NOT NULL DEFAULT '0'"), ("leave_days_year", "TEXT"), ("leave_carried", "TEXT NOT NULL DEFAULT '0'")):
        if column not in columns: db.execute(f"ALTER TABLE employees ADD COLUMN {column} {definition}")
    db.execute("""CREATE TABLE IF NOT EXISTS leave_records (id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id),
        date_from TEXT NOT NULL, date_to TEXT NOT NULL, days TEXT NOT NULL, leave_type TEXT NOT NULL DEFAULT 'annual', note TEXT,
        created_by INTEGER, created_at TEXT NOT NULL)""")


def _d(value):
    try: return Decimal(str(value if value not in (None, "") else 0).replace(",", ""))
    except Exception: return ZERO


def _lbp(db, amount, currency, day):
    if str(currency or "LBP").upper() == "LBP": return _d(amount)
    return _d(amount) * Decimal(str(db._converted_amount(Decimal("1"), currency, "LBP", day)))


def _employees(db, as_of):
    with db.connect() as connection:
        rows = [dict(r) for r in connection.execute("SELECT * FROM employees ORDER BY employee_number,full_name")]
    return [r for r in rows if r.get("active", 1) and (not r.get("leave_date") or r["leave_date"] >= as_of) and (not r.get("hire_date") or r["hire_date"] <= as_of)]


def _years(start, end):
    return Decimal((date.fromisoformat(end) - date.fromisoformat(start)).days) / Decimal("365.25")


# ---------------------------------------------------------------- end of service
def eos_provision(db, as_of, months_per_year=1):
    """Per employee: years of service, last salary (LBP), indemnity, contributions paid, provision needed; the total
    against what is booked on 1552.1, and the entry that brings it to the needed amount."""
    import ledger_reports
    as_of = iso_date(as_of); rows = []; notes = []
    with db.connect() as connection:
        paid = {}
        for r in connection.execute("SELECT employee_id,currency,period_date,employer_end_service FROM payroll_records WHERE status='posted' AND period_date<=?", (as_of,)):
            paid[r["employee_id"]] = paid.get(r["employee_id"], ZERO) + _lbp(db, r["employer_end_service"], r["currency"], r["period_date"])
    total = ZERO
    for e in _employees(db, as_of):
        if not e.get("hire_date"): notes.append(f"{e['full_name']}: starting date missing - not included"); continue
        if e.get("nssf_no_end_service"): continue
        years = _years(e["hire_date"], as_of)
        salary = _lbp(db, e["base_salary"], e["currency"], as_of)
        indemnity = (salary * years * Decimal(str(months_per_year))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        contributions = (_d(e.get("eos_paid_before")) + paid.get(e["id"], ZERO)).quantize(Decimal("1"))
        needed = max(ZERO, indemnity - contributions); total += needed
        rows.append({"employee": e["full_name"], "number": e.get("employee_number") or "", "hire_date": e["hire_date"], "years": years.quantize(Decimal("0.01")),
                     "salary_lbp": salary.quantize(Decimal("1")), "indemnity_lbp": indemnity, "contributions_lbp": contributions, "provision_lbp": needed})
    booked = ZERO
    for line in ledger_reports._load_lines(db, {"posting_status": "posted", "first_column": "LBP", "second_column": "none"}):
        if str(line["code"]) == PROVISION_ACCOUNT and line["iso_date"] <= as_of: booked -= line["signed"]["LBP"] or ZERO
    booked = booked.quantize(Decimal("1")); change = total - booked
    return {"date": as_of, "rows": rows, "total_lbp": total, "booked_lbp": booked, "change_lbp": change, "notes": notes,
            "entry": ([(EXPENSE_ACCOUNT, change, ZERO), (PROVISION_ACCOUNT, ZERO, change)] if change > 0 else
                      [(PROVISION_ACCOUNT, -change, ZERO), (REVERSAL_ACCOUNT, ZERO, -change)] if change < 0 else [])}


def post_eos_provision(db, as_of, user_id):
    result = eos_provision(db, as_of)
    if not result["entry"]: raise ValueError("The provision booked already equals the provision needed")
    lines = [{"account_code": code, "line_currency": "LBP", "side": "D" if debit else "C", "amount": str(debit or credit)} for code, debit, credit in result["entry"]]
    voucher = db.save_journal_voucher({"entry_date": display_date(result["date"]), "currency": "LBP", "voucher_type": "06",
                                       "description": f"END OF SERVICE PROVISION - {display_date(result['date'])}: needed {result['total_lbp']:,.0f} LBP, booked before {result['booked_lbp']:,.0f}"},
                                               lines, user_id)
    return {**result, "voucher": voucher["voucher"]["entry_number"]}


# ---------------------------------------------------------------- annual leave
def save_leave(db, item, user_id):
    employee_id = int(item.get("employee_id") or 0)
    start = iso_date(item.get("date_from"), "Date From"); end = iso_date(item.get("date_to"), "Date To")
    if end < start: raise ValueError("Date To cannot be before Date From")
    kind = str(item.get("leave_type") or "annual").lower()
    if kind not in LEAVE_TYPES: raise ValueError("Choose annual, sick, unpaid or other leave")
    days = _d(item.get("days")) or Decimal((date.fromisoformat(end) - date.fromisoformat(start)).days + 1)
    if days <= 0 or days > 366: raise ValueError("Enter the number of leave days")
    with db.connect() as connection:
        if not connection.execute("SELECT 1 FROM employees WHERE id=?", (employee_id,)).fetchone(): raise ValueError("Choose the employee")
        leave_id = connection.execute("INSERT INTO leave_records(employee_id,date_from,date_to,days,leave_type,note,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                      (employee_id, start, end, str(days), kind, str(item.get("note") or "").strip(), user_id, utcnow())).lastrowid
        connection.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                           (user_id, "create", "leave", leave_id, json.dumps({"employee_id": employee_id, "days": str(days), "type": kind}), utcnow()))
    return leave_id


def delete_leave(db, leave_id, user_id):
    with db.connect() as connection:
        connection.execute("DELETE FROM leave_records WHERE id=?", (int(leave_id),))
        connection.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)", (user_id, "delete", "leave", int(leave_id), "{}", utcnow()))
    return {"deleted": int(leave_id)}


def list_leave(db, year=None):
    with db.connect() as connection:
        rows = [dict(r) for r in connection.execute("""SELECT l.*,e.full_name,e.employee_number FROM leave_records l JOIN employees e ON e.id=l.employee_id
            ORDER BY l.date_from DESC,l.id DESC""")]
    return [r for r in rows if not year or r["date_from"][:4] == str(year)]


def leave_balances(db, as_of, default_days=15, with_ids=False):
    """Per employee: days a year, carried in, earned to date (pro rata from 1 January or the starting date), annual leave
    taken this year, balance and its value (balance x monthly salary / 30, in the salary currency)."""
    as_of = iso_date(as_of); year = as_of[:4]; start_year = f"{year}-01-01"; rows = []
    taken = {}
    for r in list_leave(db, year):
        if r["leave_type"] == "annual" and r["date_from"] <= as_of: taken[r["employee_id"]] = taken.get(r["employee_id"], ZERO) + _d(r["days"])
    for e in _employees(db, as_of):
        per_year = _d(e.get("leave_days_year")) or Decimal(str(default_days))
        start = max(start_year, e.get("hire_date") or start_year)
        # 2.9.84: days of this year (365 or 366): a full year earns exactly the days a year (365.25 gave 14.99 of 15)
        year_days = (date(int(year), 12, 31) - date(int(year), 1, 1)).days + 1
        months = min(Decimal(12), Decimal((date.fromisoformat(as_of) - date.fromisoformat(start)).days + 1) / Decimal(year_days) * 12)
        earned = (per_year * months / 12).quantize(Decimal("0.01"))
        carried = _d(e.get("leave_carried")); used = taken.get(e["id"], ZERO); balance = carried + earned - used
        daily = (_d(e["base_salary"]) / 30)
        rows.append({**({"employee_id": e["id"]} if with_ids else {}), "employee": e["full_name"], "number": e.get("employee_number") or "",
                "days_year": per_year, "carried": carried, "earned": earned,
                     "taken": used, "balance": balance, "currency": e["currency"], "value": (balance * daily).quantize(Decimal("0.01"))})
    return {"date": as_of, "rows": rows}


# ---------------------------------------------------------------- payslips of a month
def payslip_sections(db, month_end):
    """One section per employee for the saved payroll of the month (for one PDF with every payslip)."""
    day = iso_date(month_end); first = day[:8] + "01"
    sections = []
    for r in reversed(db.list_payroll(first, day)):
        rows = [[label, _d(r.get(key))] for key, label in (("salary", "Basic salary"), ("transport", "Transport"), ("overtime", "Overtime"), ("commission", "Commission"),
                ("retro_salary", "Retroactive salary"), ("schooling", "Schooling allowance"), ("bonus", "Bonus"), ("thirteenth_month", "13th month"),
                ("director_remuneration", "Director remuneration")) if _d(r.get(key))]
        rows += [["GROSS SALARY", _d(r["gross_salary"])], ["Less: salary tax", -_d(r["income_tax"])], ["Less: NSSF employee share", -_d(r["employee_nssf"])],
                 ["NET SALARY", _d(r["net_salary"])], ["", ""],
                 ["Employer NSSF - medical / family / end of service (information)", _d(r["employer_medical"]) + _d(r["employer_family"]) + _d(r["employer_end_service"])]]
        sections.append({"heading": f"PAYSLIP {display_date(r['period_date'])[3:]} - {r['full_name']} ({r.get('employee_number') or ''}) - {r['payroll_number']} - {r['status'].upper()}",
                         "headers": ["Item", f"Amount ({r['currency']})"], "rows": rows, "total_rows": [len(rows) - 6, len(rows) - 3], "page_break": True})
    if not sections: raise ValueError(f"No payroll saved for {display_date(day)[3:]}")
    return sections


def eos_sections(result):
    rows = [[r["number"], r["employee"], display_date(r["hire_date"]), r["years"], r["salary_lbp"], r["indemnity_lbp"], r["contributions_lbp"], r["provision_lbp"]] for r in result["rows"]]
    rows.append(["", "TOTAL", "", "", "", sum((r["indemnity_lbp"] for r in result["rows"]), ZERO), sum((r["contributions_lbp"] for r in result["rows"]), ZERO), result["total_lbp"]])
    summary = [["Provision needed", result["total_lbp"]], [f"Booked on {PROVISION_ACCOUNT}", result["booked_lbp"]], ["Entry to post", result["change_lbp"]]]
    entry = [[code, debit or "", credit or ""] for code, debit, credit in result["entry"]] or [["Nothing to post", "", ""]]
    return [{"heading": f"End-of-service indemnity provision at {display_date(result['date'])} (LBP)",
             "headers": ["No.", "Employee", "Started", "Years", "Last salary", "Indemnity (1 month / year)", "Contributions paid", "Provision"], "rows": rows, "total_rows": [len(rows) - 1]},
            {"heading": "Provision in the books", "headers": ["Item", "LBP"], "rows": summary, "total_rows": [2]},
            {"heading": "Entry", "headers": ["Account", "Debit", "Credit"], "rows": entry, "total_rows": []},
            {"heading": "Notes", "headers": ["Note"], "rows": [[n] for n in result["notes"] + [
                "Indemnity = last monthly salary x years of service (Social Security Law Art. 50-54); the NSSF pays it from the 8.5% contributions and the employer pays the difference.",
                "Contributions paid = the employer end-of-service share in Saber's posted payroll + 'End-of-service contributions before Saber' on the employee. An estimate for the accounts, not the NSSF settlement."]],
                        "total_rows": []}]


def leave_sections(result):
    rows = [[r["number"], r["employee"], r["days_year"], r["carried"], r["earned"], r["taken"], r["balance"], r["currency"], r["value"]] for r in result["rows"]]
    return [{"heading": f"Annual leave balances at {display_date(result['date'])}", "headers": ["No.", "Employee", "Days / year", "Carried in", "Earned", "Taken", "Balance", "Currency", "Value owed"],
             "rows": rows or [["No employee"] + [""] * 8], "total_rows": []}]
