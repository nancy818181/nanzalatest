"""2.9.107: the NSSF (CNSS) and MOF payroll forms as editable Excel, filled from Saber.

Replaces the earlier PDF copies with typed overlays. Each form is an Excel workbook in the layout of the printed form
(right-to-left, A4): light-yellow cells stay editable, options are marked with X, amounts are numbers and totals are
formulas, so the form stays correct when a value is changed.

Employee forms   - filled from Settings > Company and the employee record:
                   MOF R3, MOF R3-1 (company letter), CNSS 2AA, CNSS 41A, CNSS leaving notice
Contribution forms - filled from Settings > Company and the posted payroll (the NSSF report figures):
                   CNSS 190A (month / quarter), CNSS 351 (yearly settlement), CNSS 386 (annual declaration + schedule)"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date
from typing import Any, Callable, Mapping, Sequence

import cnss_contribution_forms as contributions
import payroll_excel_forms as employee_forms


@dataclass(frozen=True)
class CNSSForm:
    key: str
    label: str
    kind: str          # "employee" (needs an employee), "company", "period", "yearly", "annual"
    builder: Callable


FORMS = (
    CNSSForm("cnss_contributions_monthly_quarterly", "CNSS 190A — Contributions due, monthly / quarterly | جدول الإشتراكات المستحقة",
             "period", contributions.build_cnss_190a),
    CNSSForm("cnss_contributions_yearly", "CNSS 351 — Contributions from the annual declaration | جدول الإشتراكات السنوي", "yearly",
             contributions.build_cnss_351),
    CNSSForm("cnss_annual_declaration", "CNSS 386 — Annual nominative declaration | التصريح الإسمي السنوي", "annual", contributions.build_cnss_386),
    CNSSForm("cnss_employment_declaration", "CNSS 2AA — Employment declaration | تصريح باستخدام أجير", "employee", employee_forms.build_cnss_2aa),
    CNSSForm("cnss_employee_use_notice", "CNSS 41A — Employment notice | إعلام عن استخدام أجير", "employee", employee_forms.build_cnss_41a),
    CNSSForm("cnss_termination_notice", "CNSS — Employee leaving notice | إعلام عن ترك أجير عمله", "employee", employee_forms.build_cnss_leave),
    CNSSForm("cnss_r3", "MOF R3 — New employee registration | طلب تسجيل مستخدم/أجير جديد", "employee", employee_forms.build_mof_r3),
    CNSSForm("cnss_r3_employee_registration", "MOF R3-1 — Letter to register employees | كتاب طلب تسجيل مستخدمين/أجراء", "company",
             employee_forms.build_mof_r3_1),
)

FORM_BY_KEY = {item.key: item for item in FORMS}
FORM_BY_LABEL = {item.label: item.key for item in FORMS}

LEGACY_FORM_KEYS = {
    "R3": "cnss_r3",
    "R3-1": "cnss_r3_employee_registration",
    "NSSF-DUE": "cnss_contributions_monthly_quarterly",
    "NSSF-SETTLEMENT": "cnss_annual_declaration",
    "NSSF-ANNUAL": "cnss_contributions_yearly",
    "NSSF-HIRE-NEW": "cnss_employee_use_notice",
    "NSSF-HIRE-EXISTING": "cnss_employment_declaration",
    "NSSF-LEAVE": "cnss_termination_notice",
    # the keys of the former "Official Forms (Excel)" window
    "MOF_R3": "cnss_r3", "MOF_R3_1": "cnss_r3_employee_registration", "CNSS_2AA": "cnss_employment_declaration",
    "CNSS_41A": "cnss_employee_use_notice", "CNSS_LEAVE": "cnss_termination_notice",
}

MONTH_NAMES = ("كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب", "أيلول", "تشرين الأول", "تشرين الثاني", "كانون الأول")


def period_months(period_type: str, year: int, index: int) -> list[int]:
    kind = str(period_type or "").lower()
    if kind == "monthly":
        return [int(index)]
    if kind == "quarterly":
        first = (int(index) - 1) * 3 + 1
        return [first, first + 1, first + 2]
    return list(range(1, 13))


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _display_date(value: Any) -> str:
    text = _text(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text[:10]):
        return f"{text[8:10]}-{text[5:7]}-{text[:4]}"
    return text.replace("/", "-")


def _period_text(period_type: str, year: int, index: int) -> str:
    if period_type == "monthly":
        return f"{MONTH_NAMES[int(index) - 1]} {year}"
    if period_type == "quarterly":
        return f"الفصل {'الأول الثاني الثالث الرابع'.split()[int(index) - 1]} {year}"
    return str(year)


def form_data(
    form_key: str,
    company: Mapping[str, Any] | None,
    employee: Mapping[str, Any] | None = None,
    report: Mapping[str, Any] | None = None,
    filed_wages: Sequence[Mapping[str, Any]] = (),
    *,
    year: int | None = None,
    period_type: str = "monthly",
    index: int = 1,
    payment_details: Mapping[str, Any] | None = None,
    language: str = "ar",
) -> tuple[dict[str, Any], list[str]]:
    """The values a form is filled with, and the user-facing notes about anything missing.
    Nothing is invented: what Nanza does not hold stays empty for the user to complete in Excel."""
    form = FORM_BY_KEY.get(LEGACY_FORM_KEYS.get(form_key, form_key))
    if form is None:
        raise ValueError(f"Unknown form: {form_key}")
    company = dict(company or {})
    missing: list[str] = []
    for key, label in (("company_name", "Company name"), ("company_nssf", "Employer NSSF number")):
        if not _text(company.get(key)):
            missing.append(f"{label} is missing in Settings > Company.")
    if form.kind == "company" and not _text(company.get("company_mof")):
        missing.append("Company MOF registration number is missing in Settings > Company.")

    if form.kind in ("employee", "company"):
        data = employee_forms.form_data(company, employee if form.kind == "employee" else None, language=language)  # 2.9.112
        if form.kind == "employee":
            if not employee:
                missing.insert(0, "Select an employee to fill this form.")
            else:
                for key, label in (("full_name", "Employee name"), ("nssf_number", "Employee NSSF number"), ("national_id", "National ID"),
                                   ("birth_date", "Birth date"), ("sex", "Sex (for official forms)")):
                    if not _text(employee.get(key)):
                        missing.append(f"{label} is missing in the employee file.")
                if form.key == "cnss_termination_notice":
                    if not _text(employee.get("leave_date")):
                        missing.append("No leaving date in the employee file.")
                    if not data.get("leave_code"):
                        missing.append("Leaving reason not recognised in the employee file: mark it with X in Excel.")
        return data, missing

    # ---- contribution forms (posted payroll)
    year = int(year or date.today().year)
    payment = dict(payment_details or {})
    data: dict[str, Any] = {key: company.get(key) for key in ("company_nssf", "company_mof", "company_phone")}
    data.update(company_name=_text(company.get("company_name_ar")) or company.get("company_name"),  # 2.9.108: Arabic first
                company_address=_text(company.get("company_address_ar")) or company.get("company_address"))
    data.update(today=date.today().strftime("%d-%m-%Y"), year=str(year))
    if not report:
        missing.append("No payroll report loaded: generate payroll for the period first.")
        report = {}
    elif int(report.get("record_count") or 0) == 0:
        missing.append("There is no posted payroll in this period: the amounts are empty.")

    if form.kind == "period":
        figures = contributions.branch_figures(report)
        data.update(period_text=_period_text(period_type, year, index), date_from=_display_date(report.get("date_from")),
                    date_to=_display_date(report.get("date_to")), allowance=figures["allowance"],
                    payment_method=_text(payment.get("method")), receipt_number=_text(payment.get("reference")),
                    payment_date=_display_date(payment.get("payment_date")))
        for branch in ("sick", "eos", "family"):
            data[branch] = dict(figures[branch])
        if not data["payment_method"]: missing.append("Payment method not entered: mark it with X in Excel or choose it above.")
        if not data["receipt_number"]: missing.append("NSSF receipt / document number not entered.")
        return data, missing

    figures = contributions.branch_figures(report)
    filed, from_payroll = contributions.filed_bases(filed_wages, report)
    employees = contributions.employee_months(report)
    rates = {branch: figures[branch]["rate"] for branch in ("sick", "eos", "family")}
    if from_payroll:
        missing.append("Wages declared during the year were not saved for months " + ", ".join(f"{m:02d}" for m in from_payroll)
                       + ": the posted payroll of those months is used (change them in Excel if you declared other amounts).")
    if form.kind == "annual":
        data.update(filed=filed, employees=employees, rates=rates)
        if not employees:
            missing.append("No employee / month payroll lines for this year: the attached schedule is empty.")
        return data, missing

    # CNSS 351: contributions resulting from the annual declaration = (wages of the year - wages declared) x rate
    actual = contributions.monthly_bases(report)
    for branch in ("sick", "eos", "family"):
        settlement = sum(actual[m][branch] for m in range(1, 13)) - sum((filed[m] or {}).get(branch) or 0 for m in range(1, 13))
        data[branch] = {"count": figures[branch]["count"], "wages": settlement, "rate": rates[branch]}
    data.update(pay_until=f"31-03-{year + 1}", date_from=f"01-01-{year}", date_to=f"31-12-{year}",
                payment_method=_text(payment.get("method")), receipt_number=_text(payment.get("reference")),
                payment_date=_display_date(payment.get("payment_date")),
                declaration={"monthly": "monthly", "quarterly": "quarterly"}.get(str(report.get("declaration_period") or "")))
    if not data["declaration"]:
        missing.append("Mark in Excel whether the company declares monthly (شهرية) or quarterly (فصلية).")
    return data, missing


def build_workbook(form_key: str, data: Mapping[str, Any], path=None):
    """Write the filled Excel form (returns the openpyxl workbook)."""
    form = FORM_BY_KEY[LEGACY_FORM_KEYS.get(form_key, form_key)]
    return form.builder(dict(data), path)


def _decimal(value) -> Decimal:
    """2.9.138 review: an amount or rate as an exact Decimal (empty / unreadable = 0)."""
    try: return Decimal(str(value if value not in (None, "") else 0).replace(",", ""))
    except (InvalidOperation, ValueError): return Decimal("0")


def _whole(value) -> Decimal:
    """Whole LBP, half away from zero - the same as the Excel ROUND(x, 0) used in the form (Python round() rounds half to even)."""
    return _decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def summary_rows(form_key: str, data: Mapping[str, Any]) -> list[tuple[str, str]]:
    """What the form will be filled with, for the screen (label, value)."""
    form = FORM_BY_KEY[LEGACY_FORM_KEYS.get(form_key, form_key)]
    money = lambda value: "" if value in (None, "") else f"{_whole(value):,.0f}"
    rows = [("Company", _text(data.get("company_name"))), ("Employer NSSF No.", _text(data.get("company_nssf")))]
    if form.kind in ("employee", "company"):
        for label, key in (("MOF No.", "company_mof"), ("Employee", "full_name"), ("Father", "father_name"), ("Mother", "mother_name"),
                           ("Birth", "birth"), ("Nationality", "nationality"), ("National ID", "national_id"), ("Employee NSSF No.", "nssf_number"),
                           ("Employee MOF No.", "mof_number"), ("Marital status", "marital_status"), ("Children", "children"),
                           ("Hire date", "hire_date"), ("Leave date", "leave_date"), ("Job", "job_title"), ("Salary", "salary_text")):
            if form.kind == "company" and key not in ("company_mof",): continue
            rows.append((label, _text(data.get(key))))
        return rows
    names = {"sick": "Sickness & maternity | المرض والأمومة", "eos": "End of service | نهاية الخدمة", "family": "Family allowances | التعويضات العائلية"}
    if form.kind == "annual":
        filed = data.get("filed") or {}
        rates = data.get("rates") or {}
        rows.append(("Year", _text(data.get("year"))))
        for branch in ("sick", "family", "eos"):
            declared = sum((filed.get(m) or {}).get(branch) or 0 for m in range(1, 13))
            actual = sum((months.get(m) or {}).get(branch) or 0 for months in (data.get("employees") or {}).values() for m in range(1, 13))
            rows.append((f"{names[branch]} — wages per schedule / declared", f"{money(actual)} / {money(declared)}"))
            rows.append((f"{names[branch]} — settlement contribution",
                         money((_decimal(actual) - _decimal(declared)) * _decimal(rates.get(branch)))))
        rows.append(("Employees in the schedule", str(len(data.get("employees") or {}))))
        return rows
    total = Decimal("0")
    rows.append(("Period", _text(data.get("period_text") or data.get("year"))))
    for branch in ("sick", "eos", "family"):
        item = data.get(branch) or {}
        due = _whole(_decimal(item.get("wages")) * _decimal(item.get("rate"))); total += due  # each line rounded as in the form
        rows.append((names[branch], f"{item.get('count') or 0} employee(s) · wages {money(item.get('wages'))} × {_decimal(item.get('rate')):.2%} = {money(due)}"))
    rows.append(("Total contributions", money(total)))
    if form.kind == "period":
        rows.append(("Family allowances paid", money(data.get("allowance"))))
        rows.append(("Net due to the NSSF", money(total - _decimal(data.get("allowance")))))
    return rows
