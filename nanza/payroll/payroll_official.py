"""Payroll statements laid out like the official declaration workbooks (2.9.44).

R5_BOXES / R10_BOXES : boxes 70/80 and 100-190 per column (1) board / managers and (2) employees, then 260/270.
R6_LINES             : per employee, lines 100-300 x (1) total, (2) not taxable, (3) taxable, then 310-360.
AUDIT                : sum of all R6 statements against the R5 boxes - every difference is listed.
MOVEMENT             : monthly and year-to-date movement, one line per employee.
REGISTER / LEAVERS   : employees register and register of those who left during the year.
NSSF statements and payments are not part of this module (they keep their own format).
"""
from __future__ import annotations

from decimal import Decimal

import payroll_lines as PL
from payroll_reports import _display, _load_records, period_range

ZERO = Decimal("0")
OFFICIAL = {
    "R5_BOXES": "R5 - Annual declaration (official boxes) | تصريح سنوي ر5",
    "R10_BOXES": "R10 - Periodic statement (official boxes) | بيان دوري ر10",
    "R6_LINES": "R6 - Individual annual statement (lines 100-360) | كشف سنوي إفرادي ر6",
    "AUDIT": "Audit statement R6 vs R5 | كشف إجمالي للتدقيق",
    "MOVEMENT": "Monthly and year-to-date movement | الحركة الشهرية والتجميعية",
    "REGISTER": "Employees register | سجل المستخدمين",
    "LEAVERS": "Leavers register | سجل التاركين",
}
GROUP_COLUMNS = (("manager", "(1) Board / managers | رئيس وأعضاء مجلس الإدارة"), ("employee", "(2) Employees | المستخدمون والأجراء"))


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal("1"))


def _record_lines(db, row):
    """R6 lines of one payroll record, in LBP."""
    rate = row["lbp_rate"]; lbp = row["lbp"]
    raw = lambda key: Decimal(str(row.get(key) or 0)) * rate
    family = lbp.get("family_allowance", ZERO)
    spouse = ZERO
    if family and str(row.get("marital_status") or "") in ("married", "spouse") and not int(row.get("spouse_works") or 0):
        try: spouse = min(family, Decimal(str(db.payroll_settings_for(row["period_date"]).get("family_allowance_spouse") or 0)))
        except Exception: spouse = ZERO
    values = {"salary": lbp["salary"], "retro_salary": lbp["retro_salary"], "overtime": lbp["overtime"], "commission": lbp["commission"],
              "bonus": lbp["bonus"], "thirteenth_month": lbp["thirteenth_month"], "transport": lbp["transport"],
              "exempt_transport": raw("exempt_transport"), "schooling": lbp["schooling"], "exempt_schooling": raw("exempt_schooling"),
              "director_remuneration": raw("director_remuneration"), "family_spouse": spouse, "family_children": family - spouse}
    allowances = {code: amount * rate for code, amount in db._record_allowances(row).items() if code in PL.ALLOWANCES}
    return PL.r6_lines(values, allowances)


def _employees(db, rows):
    """{employee_id: {"row", "lines", "taxable", "tax", "months"}} with amounts in LBP."""
    result = {}
    for row in rows:
        item = result.setdefault(row["employee_id"], {"row": row, "lines": {}, "taxable": ZERO, "tax": ZERO, "months": set(), "employee_nssf": ZERO})
        PL.add_lines(item["lines"], _record_lines(db, row))
        item["taxable"] += row["lbp"]["taxable_salary"]; item["tax"] += row["lbp"]["income_tax"]
        item["employee_nssf"] += row["lbp"]["employee_nssf"]; item["months"].add(row["period_date"][:7])
    for item in result.values():
        lines = item["lines"]
        item["total"] = sum((v[0] for v in lines.values()), ZERO)
        item["exempt"] = sum((v[1] for v in lines.values()), ZERO)
        item["net"] = item["total"] - item["exempt"]                      # box 160 / line 350 before family deduction
        item["family_deduction"] = max(ZERO, item["net"] - item["taxable"])  # line 330
    return result


def _boxes_for(db, items):
    lines = {}
    for item in items: PL.add_lines(lines, item["lines"])
    taxable = sum((i["taxable"] for i in items), ZERO); tax = sum((i["tax"] for i in items), ZERO)
    family = sum((i["family_deduction"] for i in items), ZERO)
    return PL.return_boxes(lines, family, taxable, tax), lines


def _company_meta(db, label, start, end, extra=None):
    company = db.settings()
    meta = [f"Company: {company.get('company_name') or '-'}     MOF registration No.: {company.get('company_mof') or '-'}",
            f"Period: {label} ({_display(start)} to {_display(end)})     Amounts in Lebanese pounds (LBP)"]
    meta += extra or []
    meta.append("Prepared from posted payroll. Check against the current Ministry of Finance form before filing; NSSF statements are separate.")
    return meta


def _returns(db, report, period_type, year, index, include_drafts):
    start, end, label = period_range(period_type, year, index)
    rows = _load_records(db, start, end, include_drafts)
    people = _employees(db, rows)
    by_group = {key: [p for p in people.values() if (p["row"].get("employee_group") or "employee") == key] for key, _ in GROUP_COLUMNS}
    boxes = {key: _boxes_for(db, items)[0] for key, items in by_group.items()}
    body = [["70", "Number of board members / managers", "عدد رئيس وأعضاء مجلس الإدارة", len(by_group["manager"]), ""],
            ["80", "Number of employees and workers", "عدد المستخدمين والأجراء", "", len(by_group["employee"])],
            ["90", "Number of lump-sum workers", "عدد العمال الذين يتقاضون أجوراً مقطوعة", "", 0]]
    for code, ar, en in PL.BOX_LABELS:
        body.append([str(code), en, ar, _money(boxes["manager"][code]), _money(boxes["employee"][code])])
    total_taxable = boxes["manager"][180] + boxes["employee"][180]; total_tax = boxes["manager"][190] + boxes["employee"][190]
    tail = [["240", "Lump-sum wages paid", "المبالغ المدفوعة كأجور مقطوعة", "", 0], ["250", "Tax on lump-sum wages", "الضريبة على الأجور المقطوعة", "", 0],
            ["260" if report == "R10_BOXES" else "251", "Total taxable salaries and wages", "إجمالي الرواتب والأجور الخاضعة للضريبة", "", _money(total_taxable)],
            ["270" if report == "R10_BOXES" else "260", "Total tax due", "إجمالي الضريبة المتوجّبة", "", _money(total_tax)]]
    sections = [{"heading": f"{'R10' if report == 'R10_BOXES' else 'R5'} - {label}", "headers": ["Box | الخانة", "Item", "البيان", GROUP_COLUMNS[0][1], GROUP_COLUMNS[1][1]],
                 "rows": body + tail, "total_rows": [len(body) + len(tail) - 1], "fixed": True}]
    if report == "R5_BOXES":
        quarters = []
        for q in range(1, 5):
            qs, qe, ql = period_range("quarterly", year, q)
            withheld = sum((r["lbp"]["income_tax"] for r in rows if qs <= r["period_date"] <= qe), ZERO)
            quarters.append([str(q), ql, _money(withheld)])
        quarters.append(["", "Total", _money(sum((q[2] for q in quarters), ZERO))])
        sections.append({"heading": "Tax withheld by quarter (R10) - for the periodic payments box; enter the payments yourself",
                         "headers": ["Q", "Period", "Tax withheld"], "rows": quarters, "total_rows": [4]})
    return {"report": report, "title": OFFICIAL[report], "period_label": label, "date_from": start, "date_to": end,
            "meta": _company_meta(db, label, start, end), "sections": sections, "record_count": len(rows)}


def _r6(db, year, include_drafts, employee_id=None):
    start, end, label = period_range("yearly", year, 1)
    rows = [r for r in _load_records(db, start, end, include_drafts) if not employee_id or r["employee_id"] == int(employee_id)]
    sections = []
    for item in _employees(db, rows).values():
        r = item["row"]; lines = item["lines"]
        body = [[str(code), en, ar] + [_money(v) for v in lines.get(code, [ZERO, ZERO, ZERO])] for code, ar, en in PL.R6_LINES]
        body.append(["310", "Total", "المجموع", _money(item["total"]), _money(item["exempt"]), _money(item["net"])])
        body.append(["330", "Family deduction", "التنزيل العائلي", "", "", _money(item["family_deduction"])])
        body.append(["340", "Other deductions", "تنزيلات أخرى", "", "", 0])
        body.append(["350", "Net taxable income", "صافي الإيرادات", "", "", _money(item["taxable"])])
        body.append(["360", "Annual tax due", "الضريبة السنوية المتوجّبة", "", "", _money(item["tax"])])
        months = sorted(item["months"])
        heading = (f"R6 - {r['employee_number']} {r['full_name']} - MOF No. {r.get('mof_number') or '-'} - {r.get('job_title') or 'no job title'} - "
                   f"{_family_en(r)} - worked {months[0][5:]}-{months[0][:4]} to {months[-1][5:]}-{months[-1][:4]}")
        sections.append({"heading": heading, "headers": ["Line | السطر", "Item", "الشرح", "(1) Total | إجمالي الإيرادات",
                         "(2) Not taxable | غير خاضعة", "(3) Taxable | خاضعة"], "rows": body, "total_rows": [len(PL.R6_LINES)], "fixed": True})
    if not sections:
        sections.append({"heading": "R6", "headers": ["Note"], "rows": [["No posted payroll in this year"]], "total_rows": []})
    return {"report": "R6_LINES", "title": OFFICIAL["R6_LINES"], "period_label": label, "date_from": start, "date_to": end,
            "meta": _company_meta(db, label, start, end), "sections": sections, "record_count": len(rows)}


def _family_en(r):
    status = {"married": "married", "spouse": "married", "widowed": "widowed", "divorced": "divorced"}.get(str(r.get("marital_status") or ""), "single")
    children = int(r.get("children") or 0)
    return f"{status}, {children} child" + ("ren" if children != 1 else "")


def _family(r):
    status = {"married": "متزوّج", "spouse": "متزوّج", "widowed": "أرمل", "divorced": "مطلّق"}.get(str(r.get("marital_status") or ""), "أعزب")
    return f"{status} · {int(r.get('children') or 0)} ولد"


def _audit(db, year, include_drafts):
    """Sum of the individual R6 statements against the R5 boxes; any difference is shown."""
    start, end, label = period_range("yearly", year, 1)
    rows = _load_records(db, start, end, include_drafts)
    people = list(_employees(db, rows).values())
    total_lines = {}
    for item in people: PL.add_lines(total_lines, item["lines"])
    body = [[str(code), en, ar] + [_money(v) for v in total_lines.get(code, [ZERO] * 3)] for code, ar, en in PL.R6_LINES]
    total = [sum((v[i] for v in total_lines.values()), ZERO) for i in range(3)]
    body.append(["310", "Grand total", "المجموع العام", *[_money(v) for v in total]])
    r6_sum = {"income": total[0], "family": sum((i["family_deduction"] for i in people), ZERO),
              "taxable": sum((i["taxable"] for i in people), ZERO), "tax": sum((i["tax"] for i in people), ZERO)}
    boxes = {key: _boxes_for(db, [p for p in people if (p["row"].get("employee_group") or "employee") == key])[0] for key, _ in GROUP_COLUMNS}
    r5 = {"income": boxes["manager"][120] + boxes["employee"][120], "family": boxes["manager"][170] + boxes["employee"][170],
          "taxable": boxes["manager"][180] + boxes["employee"][180], "tax": boxes["manager"][190] + boxes["employee"][190]}
    withheld = sum((r["lbp"]["income_tax"] for r in rows), ZERO)
    check = []
    for key, name in (("income", "Total income (R6 line 310 / R5 box 120)"), ("family", "Family deductions (R6 330 / R5 170)"),
                      ("taxable", "Net taxable (R6 350 / R5 180)"), ("tax", "Tax due (R6 360 / R5 190)")):
        diff = r6_sum[key] - r5[key]
        check.append([name, _money(r6_sum[key]), _money(r5[key]), _money(diff), "OK" if abs(diff) < 1 else "CHECK"])
    check.append(["Tax withheld in monthly payroll vs tax due", _money(withheld), _money(r5["tax"]), _money(withheld - r5["tax"]), "OK" if abs(withheld - r5["tax"]) < 1 else "CHECK"])
    summary = [["Employees", "إجمالي عدد الأجراء", len(people)],
               ["of which with no tax due", "غير الخاضعين للضريبة", sum(1 for i in people if i["tax"] == 0)]]
    sections = [{"heading": "For accounting audit only", "headers": ["Item", "البيان", "Value"], "rows": summary, "total_rows": [], "fixed": True},
                {"heading": "Sum of all R6 statements by line", "headers": ["Line", "Item", "الشرح", "(1) Total", "(2) Not taxable", "(3) Taxable"],
                        "rows": body, "total_rows": [len(body) - 1], "fixed": True},
                {"heading": "Reconciliation R6 vs R5", "headers": ["Check", "Sum of R6", "R5", "Difference", "Result"], "rows": check, "total_rows": [], "fixed": True}]
    return {"report": "AUDIT", "title": OFFICIAL["AUDIT"], "period_label": label, "date_from": start, "date_to": end,
            "meta": _company_meta(db, label, start, end), "sections": sections, "record_count": len(rows),
            "ok": all(row[-1] == "OK" for row in check)}


def _movement(db, year, month, include_drafts):
    """One line per employee: this month and year-to-date (like the monthly / cumulative movement sheet)."""
    month = int(month); start_m, end_m, label = period_range("monthly", year, month)
    start_y = f"{int(year)}-01-01"
    rows = _load_records(db, start_y, end_m, include_drafts)
    month_rows = [r for r in rows if r["period_date"] >= start_m]
    month_people = _employees(db, month_rows); ytd_people = _employees(db, rows)
    headers = ["Reg. No.", "Name | الإسم", "Unit | الوحدة", "Job | الوظيفة", "Family status | الوضع العائلي",
               "Salary | الراتب", "Allowances taxable | بدلات خاضعة", "Not taxable | غير خاضعة", "Gross | المجموع",
               "Employee NSSF", "Tax withheld | الضريبة المقتطعة", "Net | الصافي",
               "YTD gross | التجميع السنوي", "YTD taxable | الخاضع", "YTD tax | الضريبة"]
    body = []
    for employee_id, item in ytd_people.items():
        r = item["row"]; m = month_people.get(employee_id)
        month_record = next((x for x in month_rows if x["employee_id"] == employee_id), None)
        salary = (month_record["lbp"]["salary"] + month_record["lbp"]["retro_salary"]) if month_record else ZERO
        gross = m["total"] if m else ZERO; exempt = m["exempt"] if m else ZERO
        body.append([r["employee_number"], r["full_name"], r.get("unit_code") or "", r.get("job_title") or "", _family_en(r),
                     _money(salary), _money(gross - exempt - salary), _money(exempt), _money(gross),
                     _money(m["employee_nssf"] if m else 0), _money(m["tax"] if m else 0),
                     _money(month_record["lbp"]["net_salary"] if month_record else 0),
                     _money(item["total"]), _money(item["taxable"]), _money(item["tax"])])
    totals = ["TOTAL", f"{len(body)}", "", "", ""] + [sum((row[i] for row in body), Decimal(0)) for i in range(5, len(headers))]
    body.append(totals)
    return {"report": "MOVEMENT", "title": OFFICIAL["MOVEMENT"], "period_label": label, "date_from": start_m, "date_to": end_m,
            "meta": _company_meta(db, label, start_m, end_m, ["Year-to-date columns: 01-01 to the end of the month."]),
            "sections": [{"heading": f"{label}", "headers": headers, "rows": body, "total_rows": [len(body) - 1]}], "record_count": len(rows)}


def _register(db, year, leavers=False):
    year = int(year)
    employees = db.list_employees()
    if leavers:
        employees = [e for e in employees if str(e.get("leave_date") or "")[:4] == str(year)]
        headers = ["Reg. No.", "Name | الإسم", "Father | إسم الأب", "MOF No.", "NSSF No.", "Job", "Start | المباشرة", "Left | الترك", "Reason | سبب الترك"]
        body = [[e["employee_number"], e["full_name"], e.get("father_name") or "", e.get("mof_number") or "", e.get("nssf_number") or "",
                 e.get("job_title") or "", _display(e.get("hire_date")), _display(e.get("leave_date")), e.get("leave_reason") or ""] for e in employees]
        key = "LEAVERS"
    else:
        headers = ["Reg. No.", "Name | الإسم", "Father | إسم الأب", "Job | الوظيفة", "Unit | القسم", "MOF No.", "NSSF No.", "Birth | الولادة",
                   "Start | المباشرة", "Left | الترك", "Family | الوضع العائلي", "Spouse works", "Nationality", "Basic salary", "Cost of living",
                   "Extra indemnity", "Representation (taxable / not)", "No NSSF (end / family / sickness)", "Address | العنوان"]
        body = []
        for e in employees:
            address = " - ".join(str(e.get(k) or "") for k in ("addr_governorate", "addr_caza", "addr_town", "addr_district", "addr_street", "addr_building",
                    "addr_floor") if e.get(k)) or (e.get("address") or "")
            flags = "/".join("x" if str(e.get(k) or "0") == "1" else "-" for k in ("nssf_no_end_service", "nssf_no_family", "nssf_no_medical"))
            body.append([e["employee_number"], e["full_name"], e.get("father_name") or "", e.get("job_title") or "",
                         " ".join(x for x in (e.get("unit_code") or "", e.get("unit_name") or "") if x), e.get("mof_number") or "", e.get("nssf_number") or "",
                         str(e.get("birth_date") or "")[:4], _display(e.get("hire_date")), _display(e.get("leave_date")), _family_en(e),
                         "yes" if int(e.get("spouse_works") or 0) else "no", e.get("nationality") or "", _money(e.get("base_salary")),
                         _money(e.get("cost_of_living")), _money(e.get("extra_indemnity")),
                         f"{_money(e.get('representation_taxable'))} / {_money(e.get('representation_exempt'))}", flags, address])
        key = "REGISTER"
    active = sum(1 for e in employees if not e.get("leave_date"))
    start, end, label = period_range("yearly", year, 1)
    meta = _company_meta(db, label, start, end, [f"Total staff: {len(employees)}   Active: {active}   Left: {len(employees) - active}"])
    return {"report": key, "title": OFFICIAL[key], "period_label": label, "date_from": start, "date_to": end, "meta": meta,
            "sections": [{"heading": OFFICIAL[key], "headers": headers, "rows": body or [["-"] * len(headers)], "total_rows": []}],
            "record_count": len(employees)}


def build_official(db, report, period_type="yearly", year=None, index=1, include_drafts=False, employee_id=None):
    from datetime import date
    report = str(report).upper(); year = int(year or date.today().year)
    if report in ("R5_BOXES", "R10_BOXES"):
        if report == "R5_BOXES": period_type, index = "yearly", 1
        return _returns(db, report, period_type, year, index, include_drafts)
    if report == "R6_LINES": return _r6(db, year, include_drafts, employee_id)
    if report == "AUDIT": return _audit(db, year, include_drafts)
    if report == "MOVEMENT": return _movement(db, year, index if period_type == "monthly" else 12, include_drafts)
    if report in ("REGISTER", "LEAVERS"): return _register(db, year, report == "LEAVERS")
    raise ValueError("Unknown payroll statement")
