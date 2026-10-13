"""Payroll allowances and the official line codes (2.9.44).

The individual annual statement R6 lists every earning on a numbered line (100 ... 300), each split into
(1) total, (2) not taxable and (3) taxable. The annual R5 and quarterly R10 returns group them into boxes
100 / 110 / 120 ... 190. This module holds that catalogue so the monthly payroll, the reports and the
audit statement all use the same classification.

Which allowance is taxable is decided by the user: most of them exist twice (taxable / not taxable) and the
amount is entered in the right one, as in the paper declaration workbooks. Taxable allowances are also
subject to NSSF unless the company marks them as not subject (Settings key payroll_allowances_not_nssf).
"""
from __future__ import annotations

from decimal import Decimal

# R6 lines: code -> (Arabic, English)
R6_LINES = (
    (100, "الراتب الأساسي / الأجور اليومية", "Basic salary / daily wages"),
    (110, "بدل تمثيل", "Representation allowance"),
    (120, "مكافآت وعمولات وساعات إضافية", "Bonuses, commissions and overtime"),
    (130, "تعويض عائلي عن الزوجة", "Family allowance - spouse"),
    (140, "تعويض عائلي عن الأولاد", "Family allowance - children"),
    (150, "تعويضات نقل وانتقال", "Transport allowances"),
    (160, "بدل سيارة", "Car allowance"),
    (170, "بدل سكن", "Housing allowance"),
    (180, "بدل طعام", "Food allowance"),
    (190, "بدل ملبس", "Clothing allowance"),
    (200, "تعويض صندوق", "Cash handling allowance"),
    (210, "تأمينات صحيّة على أنواعها", "Health insurance"),
    (220, "منح تعليم", "Education grants"),
    (230, "منح زواج", "Marriage grants"),
    (240, "منح ولادة", "Birth grants"),
    (250, "مساعدات مرضية", "Sickness aid"),
    (260, "مساعدات وفاة", "Death aid"),
    (300, "منح وتقديمات أخرى", "Other grants and benefits"),
)
LINE_NAMES = {code: (ar, en) for code, ar, en in R6_LINES}

# Allowances entered in the monthly payroll (besides salary, transport, overtime, commission, bonus, 13th,
# schooling and retro, which already exist). code -> (R6 line, taxable, recurring, Arabic, English)
# recurring=False: one-off grants, taxed like a bonus (on top of the annual regular pay).
ALLOWANCES = {
    "cost_of_living":         (100, True,  True,  "زيادة غلاء معيشة", "Cost of living increase"),
    "extra_indemnity":        (100, True,  True,  "تعويض إضافي (هاتف وما شابه)", "Extra indemnity (phone etc.)"),
    "representation_taxable": (110, True,  True,  "بدل تمثيل خاضع", "Representation - taxable"),
    "representation_exempt":  (110, False, True,  "بدل تمثيل غير خاضع", "Representation - not taxable"),
    "car":                    (160, True,  True,  "بدل سيارة", "Car allowance"),
    "housing":                (170, True,  True,  "بدل سكن", "Housing allowance"),
    "food_taxable":           (180, True,  True,  "بدل طعام خاضع", "Food - taxable"),
    "food_exempt":            (180, False, True,  "بدل طعام غير خاضع", "Food - not taxable"),
    "clothing_taxable":       (190, True,  True,  "بدل ملبس خاضع", "Clothing - taxable"),
    "clothing_exempt":        (190, False, True,  "بدل ملبس غير خاضع", "Clothing - not taxable"),
    "cash_taxable":           (200, True,  True,  "تعويض صندوق خاضع", "Cash handling - taxable"),
    "cash_exempt":            (200, False, True,  "تعويض صندوق غير خاضع", "Cash handling - not taxable"),
    "health_insurance":       (210, True,  True,  "تأمينات صحية", "Health insurance"),
    "education_taxable":      (220, True,  False, "منح تعليم خاضعة", "Education grant - taxable"),
    "education_exempt":       (220, False, False, "منح تعليم غير خاضعة", "Education grant - not taxable"),
    "marriage_taxable":       (230, True,  False, "منح زواج خاضعة", "Marriage grant - taxable"),
    "marriage_exempt":        (230, False, False, "منح زواج غير خاضعة", "Marriage grant - not taxable"),
    "birth_taxable":          (240, True,  False, "منح ولادة خاضعة", "Birth grant - taxable"),
    "birth_exempt":           (240, False, False, "منح ولادة غير خاضعة", "Birth grant - not taxable"),
    "sickness":               (250, True,  False, "مساعدات مرضية", "Sickness aid"),
    "death_taxable":          (260, True,  False, "مساعدات وفاة خاضعة", "Death aid - taxable"),
    "death_exempt":           (260, False, False, "مساعدات وفاة غير خاضعة", "Death aid - not taxable"),
    "other_taxable":          (300, True,  False, "منح وتقديمات أخرى خاضعة", "Other benefits - taxable"),
    "other_exempt":           (300, False, False, "منح وتقديمات أخرى غير خاضعة", "Other benefits - not taxable"),
}
ALLOWANCE_CODES = tuple(ALLOWANCES)
# Recurring amounts kept on the employee register and proposed every month in the payroll sheet.
EMPLOYEE_DEFAULTS = ("cost_of_living", "extra_indemnity", "representation_taxable", "representation_exempt")

# R5 / R10 boxes. Box 100 = salaries and their accessories (R6 lines 100-150), box 110 = cash and in-kind
# benefits (R6 lines 160-300).
SALARY_LINES = (100, 110, 120, 130, 140, 150)
BENEFIT_LINES = (160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 300)
D = Decimal
ZERO = D("0")


def clean_allowances(raw) -> dict:
    """{code: Decimal} for known codes with a non-zero amount; refuses text and negative amounts."""
    result = {}
    for code, value in dict(raw or {}).items():
        if code not in ALLOWANCES: raise ValueError(f"Unknown allowance: {code}")
        text = str(value if value is not None else "").replace(",", "").strip()
        if not text: continue
        try: amount = D(text)
        except Exception as exc: raise ValueError(f"{ALLOWANCES[code][4]} must be a number") from exc
        if amount < 0: raise ValueError(f"{ALLOWANCES[code][4]} cannot be negative")
        if amount: result[code] = amount
    return result


def split(allowances: dict, not_nssf=()):
    """Totals used by the calculation: taxable recurring, taxable one-off, not taxable, NSSF base."""
    out = {"taxable_recurring": ZERO, "taxable_one_off": ZERO, "exempt": ZERO, "nssf": ZERO, "total": ZERO}
    for code, amount in allowances.items():
        line, taxable, recurring, _ar, _en = ALLOWANCES[code]
        out["total"] += amount
        if taxable:
            out["taxable_recurring" if recurring else "taxable_one_off"] += amount
            if code not in not_nssf: out["nssf"] += amount
        else:
            out["exempt"] += amount
    return out


def r6_lines(record_lbp: dict, allowances_lbp: dict) -> dict:
    """One payroll record (amounts in LBP) on the R6 lines: {line: [total, not taxable, taxable]}.

    record_lbp keys: salary, retro_salary, overtime, commission, bonus, thirteenth_month, transport, exempt_transport,
    schooling, exempt_schooling, director_remuneration, family_spouse, family_children."""
    lines = {code: [ZERO, ZERO, ZERO] for code, _a, _e in R6_LINES}

    def add(line, amount, exempt=ZERO):
        amount = D(str(amount or 0)); exempt = min(D(str(exempt or 0)), amount)
        lines[line][0] += amount; lines[line][1] += exempt; lines[line][2] += amount - exempt

    g = lambda key: D(str(record_lbp.get(key) or 0))
    add(100, g("salary") + g("retro_salary"))
    add(100, g("director_remuneration"), g("director_remuneration"))  # paid with payroll, not subject to salary tax (as configured)
    add(120, g("overtime") + g("commission") + g("bonus") + g("thirteenth_month"))
    add(130, g("family_spouse"), g("family_spouse"))
    add(140, g("family_children"), g("family_children"))
    add(150, g("transport"), g("exempt_transport"))
    add(220, g("schooling"), g("exempt_schooling"))
    for code, amount in allowances_lbp.items():
        line, taxable, _r, _ar, _en = ALLOWANCES[code]
        add(line, amount, ZERO if taxable else amount)
    return lines


def add_lines(total: dict, more: dict) -> dict:
    for line, values in more.items():
        bucket = total.setdefault(line, [ZERO, ZERO, ZERO])
        for i in range(3): bucket[i] += values[i]
    return total


def return_boxes(lines: dict, family_deduction, taxable, tax) -> dict:
    """R5 / R10 boxes 100-190 from summed R6 lines (all LBP)."""
    box = {}
    box[100] = sum((lines.get(code, [ZERO])[0] for code in SALARY_LINES), ZERO)
    box[110] = sum((lines.get(code, [ZERO])[0] for code in BENEFIT_LINES), ZERO)
    box[120] = box[100] + box[110]
    box[130] = lines.get(150, [ZERO, ZERO])[1]                     # transport not taxable
    box[140] = lines.get(110, [ZERO, ZERO])[1]                     # representation not taxable
    box[150] = sum((v[1] for code, v in lines.items() if code not in (110, 150)), ZERO)  # other not taxable
    box[160] = box[120] - box[130] - box[140] - box[150]
    box[170] = D(str(family_deduction or 0))
    box[180] = D(str(taxable or 0))
    box[190] = D(str(tax or 0))
    return box


BOX_LABELS = (
    (100, "الرواتب وملحقاتها", "Salaries and accessories"),
    (110, "المنافع النقدية والعينية", "Cash and in-kind benefits"),
    (120, "مجموع المبالغ المدفوعة", "Total amounts paid"),
    (130, "ينزّل: تعويضات نقل وانتقال", "Less: transport allowances"),
    (140, "ينزّل: تعويضات تمثيل", "Less: representation allowances"),
    (150, "ينزّل: تنزيلات أخرى", "Less: other deductions"),
    (160, "المبالغ الصافية", "Net amounts"),
    (170, "التنزيل العائلي", "Family deduction"),
    (180, "الرواتب والأجور الخاضعة للضريبة", "Taxable salaries and wages"),
    (190, "الضريبة المتوجّبة", "Tax due"),
)
