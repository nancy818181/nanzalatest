"""Lebanese quarterly VAT calculation and preparation schedules; internal refs only."""
from __future__ import annotations

import calendar
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from database import display_date, iso_date, utcnow

ZERO = Decimal("0")
CENT = Decimal("0.01")
CATEGORIES = {"sales": "Sales", "purchases": "Purchases", "assets": "Fixed assets", "expenses": "Expenses", "customs": "Customs (import VAT)"}
ADJUSTMENT_TYPES = {"output": "Output VAT adjustment", "input": "Deductible VAT adjustment", "non_deductible": "Non-deductible VAT adjustment"}
# These A-F identifiers are internal schedule references, not Ministry form box numbers.
# The public Ministry specimen does not certify this mapping to its current issued form.
LINES = (
    ("A1", "sales", "Taxable supplies at 11% (base / output VAT)"),
    ("A2", "sales_zero", "Zero-rated supplies - exports & like transactions (Art. 19-21)"),
    ("A3", "sales_exempt", "Exempt supplies (Art. 16-17)"),
    ("A4", "sales_out", "Supplies outside the scope of VAT"),
    ("B1", "reverse_output", "VAT on services acquired from abroad (reverse charge, Art. 40)"),
    ("B2", "adj_output", "Output VAT adjustments"),
    ("B3", "total_output", "TOTAL OUTPUT VAT"),
    ("C1", "purchases", "Deductible VAT - local purchases of goods & services"),
    ("C2", "assets", "Deductible VAT - fixed assets"),
    ("C3", "expenses", "Deductible VAT - general expenses"),
    ("C4", "customs", "Deductible VAT - imports (customs)"),
    ("C5", "prorata", "Less: VAT not deductible under the partial deduction ratio (Art. 31)"),
    ("C6", "annual_adjustment", "Annual adjustment of the deduction ratio (Q4)"),
    ("C7", "adj_input", "Deductible VAT adjustments"),
    ("C8", "total_input", "TOTAL DEDUCTIBLE VAT"),
    ("D1", "non_deductible", "VAT not deductible (Art. 28 / 31, for information)"),
    ("E1", "net", "NET VAT FOR THE PERIOD (output VAT less deductible input VAT)"),
)
RATE = Decimal("0.11")
ARABIC = {"sales": "المبيعات الخاضعة للضريبة بمعدل 11%", "sales_zero": "العمليات المعفاة مع حق الحسم - التصدير (المواد 19-21)",
          "sales_exempt": "العمليات المعفاة (المادتان 16 و17)", "sales_out": "عمليات خارج نطاق الضريبة",
          "reverse_output": "الضريبة على الخدمات المستوردة من الخارج (المادة 40)", "adj_output": "تسويات الضريبة المستحقة", "total_output": "مجموع الضريبة المستحقة",
          "purchases": "الضريبة القابلة للحسم - المشتريات المحلية", "assets": "الضريبة القابلة للحسم - الأصول الثابتة", "expenses": "الضريبة القابلة للحسم - المصاريف العامة",
          "customs": "الضريبة القابلة للحسم - الاستيراد (الجمارك)", "prorata": "ينزل: الضريبة غير القابلة للحسم وفق نسبة الحسم الجزئي (المادة 31)",
          "annual_adjustment": "التسوية السنوية لنسبة الحسم (الفصل الرابع)", "adj_input": "تسويات الضريبة القابلة للحسم", "total_input": "مجموع الضريبة القابلة للحسم",
          "non_deductible": "ضريبة غير قابلة للحسم (للعلم)", "net": "صافي الضريبة عن الفترة", "credit_bf": "الرصيد الدائن المدور من الفترة السابقة",
          "payable": "الضريبة المتوجبة الدفع لوزارة المالية", "refund": "طلب استرداد الرصيد الدائن (المادة 30)", "credit_cf": "الرصيد الدائن المدور إلى الفترة التالية"}
ARABIC_TITLE = "التصريح الدوري عن الضريبة على القيمة المضافة"


def quarter_range(year, quarter):
    try: year = int(year); quarter = int(quarter)
    except (TypeError, ValueError) as exc: raise ValueError("Enter a valid year and quarter") from exc
    if year < 2000 or year > 2100 or quarter not in (1, 2, 3, 4): raise ValueError("Quarter must be Q1, Q2, Q3 or Q4")
    first = 3 * quarter - 2
    return date(year, first, 1).isoformat(), date(year, first + 2, calendar.monthrange(year, first + 2)[1]).isoformat()


def previous_quarter(year, quarter):
    return (int(year), int(quarter) - 1) if int(quarter) > 1 else (int(year) - 1, 4)


def _money(value):
    try: return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)
    except Exception: return ZERO


def _lbp(value):
    return Decimal(str(value or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _vat_setup(db):
    """2.9.72: (standard rate as a fraction, VAT currency, second VAT currency) of this company: 0.11, LBP, USD in Lebanon."""
    try: rate = Decimal(str(db.vat_rate_percent())) / Decimal("100")
    except Exception: rate = RATE
    try: first, second = db.vat_currencies()
    except Exception: first, second = "LBP", "USD"
    return rate, str(first or "LBP").upper(), str(second or "USD").upper()


RATIO_METHODS = ("quarter", "annual")


def vat_ratio_method(db):
    """2.9.83: how the Art. 31 deduction ratio is set - 'quarter' (default: each quarter from its own turnover, no
    year-end adjustment) or 'annual' (provisional / year-to-date for Q1-Q3, final annual ratio and adjustment in Q4)."""
    try: value = str(db.settings().get("vat_ratio_method") or "quarter").strip().lower()
    except Exception: value = "quarter"
    return value if value in RATIO_METHODS else "quarter"


def _documents(db, start, end, currency, include_review, memo=None):
    statuses = ("posted", "review") if include_review else ("posted",)
    std_rate = _vat_setup(db)[0]
    documents = []; skipped = []; review_excluded = 0
    key = ("documents", str(getattr(db, "path", id(db))))
    if memo is not None and key in memo: invoices, expenses = memo[key]  # 2.9.91: read once per calculation (it was read 16 times)
    else:
        with db.connect() as connection:
            invoices = [dict(row) for row in connection.execute("""SELECT i.*,p.name party_name,COALESCE(NULLIF(p.mof_number,''),p.tax_number) party_mof FROM invoices i
                LEFT JOIN parties p ON p.id=i.party_id WHERE i.status NOT IN ('cancelled','deleted')""")]
            expenses = [dict(row) for row in connection.execute("SELECT * FROM expenses")]
        if memo is not None: memo[key] = (invoices, expenses)
    for row in invoices:
        try: day = iso_date(row["invoice_date"])
        except ValueError: skipped.append(row["invoice_number"]); continue
        if not start <= day <= end or (currency and row["currency"] != currency): continue
        if row["status"] not in statuses:
            if row["status"] == "review": review_excluded += 1
            continue
        if row["kind"] == "sale": category = "sales"
        elif row.get("source_file") == "Customs Case": category = "customs"
        elif row.get("entry_type") == "assets": category = "assets"
        elif row.get("entry_type") == "expenses": category = "expenses"
        else: category = "purchases"
        documents.append({"source": "invoice", "id": row["id"], "date": day, "number": row["invoice_number"], "party": row.get("party_name") or "",
            "party_id": row.get("party_id"), "party_mof": row.get("party_mof") or "",
            "category": category, "currency": row["currency"], "base": _money(row.get("deductible_subtotal") or row.get("subtotal")),
            "exempt": _money(row.get("non_deductible_subtotal")), "vat": _money(row.get("vat")), "status": row["status"],
            "recoverable": category == "sales" or bool(int(row.get("vat_recoverable") if row.get("vat_recoverable") is not None else 1)),
            "treatment": row.get("vat_treatment") or "standard", "use": row.get("vat_use") or "mixed", "std_rate": std_rate})
        if row.get("doc_subtype") == "credit_note":  # a credit note reduces the supplies and the VAT of the period
            documents[-1].update(base=-documents[-1]["base"], exempt=-documents[-1]["exempt"], vat=-documents[-1]["vat"])
    for row in expenses:
        try: day = iso_date(row["expense_date"])
        except ValueError: skipped.append(f"EXP-{row['id']}"); continue
        if not start <= day <= end or (currency and row["currency"] != currency): continue
        documents.append({"source": "expense", "id": row["id"], "date": day, "number": row.get("reference") or f"EXP-{row['id']}",
            "party": row.get("description") or "", "category": "expenses", "currency": row["currency"],
            "base": _money(row.get("with_vat_subtotal") or row.get("subtotal")), "exempt": _money(row.get("without_vat_subtotal")),
            "vat": _money(row.get("vat")), "status": "posted", "recoverable": bool(int(row.get("vat_recoverable") if row.get("vat_recoverable") is not None else 1)),
            "treatment": "standard", "use": row.get("vat_use") or "mixed", "std_rate": std_rate})
    documents.sort(key=lambda item: (item["date"], item["category"], str(item["number"])))
    return documents, skipped, review_excluded


def list_adjustments(db, year, quarter):
    with db.connect() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM vat_adjustments WHERE year=? AND quarter=? ORDER BY id", (int(year), int(quarter)))]


def saved_return(db, year, quarter):
    with db.connect() as connection:
        row = connection.execute("SELECT * FROM vat_returns WHERE year=? AND quarter=?", (int(year), int(quarter))).fetchone()
    return dict(row) if row else None


def list_saved_returns(db):
    with db.connect() as connection:
        return [dict(row) for row in connection.execute("""SELECT id,year,quarter,net_lbp,credit_brought_forward_lbp,payable_lbp,
            credit_carried_forward_lbp,saved_at,saved_by_name FROM vat_returns ORDER BY year DESC,quarter DESC""")]


def _rounded_up(value, day):
    """Legacy worksheet estimate: 10,000 LBP ceiling from 25-11-2024.

    The cited MoF decision 1195 has not been verified as a VAT payable rule.
    Do not treat this estimate as a filing instruction.
    """
    if value <= 0 or day < "2024-11-25": return _lbp(value)
    step = Decimal("10000")
    return (Decimal(value) / step).to_integral_value(rounding="ROUND_CEILING") * step


def due_date(year, quarter):
    """20 days after the quarter; one month after it from 2026 (Budget Law 2026, Art. 51)."""
    from datetime import timedelta
    end = date.fromisoformat(quarter_range(year, quarter)[1])
    if int(year) >= 2026:
        month = end.month % 12 + 1; year_due = end.year + (1 if end.month == 12 else 0)
        return date(year_due, month, min(end.day, calendar.monthrange(year_due, month)[1])).isoformat()
    return (end + timedelta(days=20)).isoformat()


# 2.9.92: Budget Law 2026 (Law 40, Official Gazette 10-02-2026), Art. 30: no input VAT on utilities; on passenger cars
# the input VAT is deductible on a cost up to USD 30,000 only. To confirm with the tax adviser; dates and cap are here.
BUDGET_2026_FROM = "2026-02-10"
PASSENGER_CAR_CAP_USD = Decimal("30000")


def _restricted_share(db, doc):
    """Part of the input VAT of this document that the 2026 rules make non-deductible (0 to 1)."""
    use = doc.get("use")
    if doc.get("category") == "sales" or doc.get("date", "") < BUDGET_2026_FROM: return ZERO
    if use == "utilities": return Decimal("1")
    if use == "passenger_car":
        try: base_usd = db._converted_amount(doc["base"] + doc["exempt"], doc["currency"], "USD", doc["date"])
        except Exception: return ZERO
        if base_usd <= PASSENGER_CAR_CAP_USD or base_usd <= 0: return ZERO
        return ((base_usd - PASSENGER_CAR_CAP_USD) / base_usd).quantize(Decimal("0.000001"))
    return ZERO


def _classify(doc):
    """Where a document goes on the return, and how much of its VAT is output, fully / partially deductible or blocked."""
    base = doc["base"]; exempt = doc["exempt"]; vat = doc["vat"]
    if doc["category"] == "sales":
        treatment = doc["treatment"]
        if treatment == "zero_rated": return {"sales_zero": base + exempt, "sales": vat}
        if treatment == "exempt": return {"sales_exempt": base + exempt, "sales": vat}
        if treatment == "out_of_scope": return {"sales_out": base + exempt}
        return {"sales_base": base, "sales": vat, "sales_exempt": exempt}
    result = {}
    if doc["treatment"] == "reverse_charge":
        vat = vat if vat else ((base + exempt) * Decimal(str(doc.get("std_rate", RATE)))).quantize(CENT, rounding=ROUND_HALF_UP)
        result["reverse_output"] = vat
    if not doc["recoverable"] or doc["use"] == "exempt": result["blocked"] = vat
    else:
        share = Decimal(str(doc.get("restricted_share") or 0))
        restricted = (vat * share).quantize(CENT, rounding=ROUND_HALF_UP) if share else ZERO
        if restricted: result["blocked"] = restricted; result["restricted"] = restricted  # booked in 442x, moved to cost by the settlement
        rest = vat - restricted
        if rest or not restricted:
            result[doc["category"]] = rest
            result["mixed" if doc["use"] in ("mixed", "utilities", "passenger_car") else "full"] = rest  # "export" and "taxable" uses are fully deductible
    return result


def _sales_detail(documents, rates):
    """Sales in LBP split as in the recoverable-rate worksheet: taxable, export / zero-rated, exempt, outside the scope."""
    detail = {"taxable": ZERO, "export": ZERO, "exempt": ZERO, "out": ZERO}
    for doc in documents:
        if doc["category"] != "sales": continue
        parts = _classify(doc); rate = rates(doc["currency"], doc["date"])
        detail["taxable"] += parts.get("sales_base", ZERO) * rate; detail["export"] += parts.get("sales_zero", ZERO) * rate
        detail["exempt"] += parts.get("sales_exempt", ZERO) * rate; detail["out"] += parts.get("sales_out", ZERO) * rate
    return detail


def _turnover(db, start, end, include_review, rates, detail_out=None, memo=None):
    """Turnover in LBP for the partial deduction ratio (Art. 31, note of form Q11-2):
    revenues giving the right of deduction (taxable + zero-rated) / total revenues (+ exempt + outside the scope)."""
    documents, _skipped, _review = _documents(db, start, end, None, include_review, memo)
    detail = _sales_detail(documents, rates)
    if detail_out is not None: detail_out.update(detail)
    return detail["taxable"] + detail["export"], detail["exempt"] + detail["out"]


def _ratio(taxable, exempt):
    total = taxable + exempt
    # 2.9.50: six decimals, as the accountants' worksheet (the rate rounded to 0.01% moved the recoverable VAT by hundreds of LBP)
    return Decimal("1") if total <= 0 or exempt <= 0 else (taxable / total).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def build_vat_return(db, year, quarter, currency=None, include_review=False, previous_year_db=None, credit_brought_forward=None, refund_requested=None, _memo=None):
    # 2.9.80: returns of earlier quarters calculated for the credit chain are kept for this one calculation
    memo = {} if _memo is None else _memo
    key = (str(getattr(db, "path", id(db))), int(year), int(quarter), str(currency), bool(include_review), str(getattr(previous_year_db, "path", None)))
    if credit_brought_forward in (None, "") and refund_requested in (None, "") and key in memo: return memo[key]
    result = _build_vat_return(db, year, quarter, currency, include_review, previous_year_db, credit_brought_forward, refund_requested, memo)
    if credit_brought_forward in (None, "") and refund_requested in (None, ""): memo[key] = result
    return result


def _build_vat_return(db, year, quarter, currency, include_review, previous_year_db, credit_brought_forward, refund_requested, memo):
    start, end = quarter_range(year, quarter)
    currency = str(currency).upper() if currency and str(currency).upper() not in ("ALL", "ALL CURRENCIES") else None
    documents, skipped, review_excluded = _documents(db, start, end, currency, include_review, memo)
    # 2.9.72: everything is added up in the company's VAT currency (LBP in Lebanon: whole pounds, as before;
    # another currency such as AED or EUR: 2 decimals). The "_lbp" names are kept for the saved returns.
    std_rate, vat_currency, vat_second = _vat_setup(db)
    rnd = _lbp if vat_currency == "LBP" else _money
    rates = {}
    def rate_of(code, day):
        if code == vat_currency: return Decimal("1")
        key = (code, day)
        if key not in rates: rates[key] = db._converted_amount(Decimal("1"), code, vat_currency, day)
        return rates[key]
    to_lbp = lambda amount, code, day: rnd(Decimal(amount) * rate_of(code, day))
    # ---- partial deduction ratio (Art. 31)
    # 2.9.83 (owner decision): by default each quarter uses the ratio of its own turnover, calculated automatically,
    # with no year-end adjustment. The earlier method (provisional / year-to-date for Q1-Q3, final annual ratio and
    # adjustment of Q1-Q3 in Q4) stays available: Settings > VAT ratio method = annual.
    method = vat_ratio_method(db)
    year_start = f"{int(year)}-01-01"; year_end = f"{int(year)}-12-31"
    ytd_detail = {}
    ytd_taxable, ytd_exempt = _turnover(db, start if method == "quarter" else year_start, end, include_review, rate_of, ytd_detail, memo)
    provisional = db.vat_provisional_ratio(year)
    final_detail = ytd_detail
    if method == "quarter":
        ratio = _ratio(ytd_taxable, ytd_exempt); ratio_source = f"turnover of Q{int(quarter)} {int(year)} only"
    elif int(quarter) == 4:
        final_detail = {}
        final_taxable, final_exempt = _turnover(db, year_start, year_end, include_review, rate_of, final_detail, memo)
        ratio = _ratio(final_taxable, final_exempt); ratio_source = "final annual ratio"
    elif provisional is not None: ratio = provisional; ratio_source = "provisional ratio set for the year"
    else: ratio = _ratio(ytd_taxable, ytd_exempt); ratio_source = "year-to-date turnover"
    per_currency = {}; warnings = []
    def bucket(code):
        keys = [key for _, key, _ in LINES] + ["blocked", "mixed", "full", "restricted"]
        return per_currency.setdefault(code, {key: {"base": ZERO, "vat": ZERO, "vat_lbp": ZERO, "count": 0} for key in keys})
    for doc in documents:
        doc["lbp_rate"] = rate_of(doc["currency"], doc["date"]); doc["vat_lbp"] = to_lbp(doc["vat"], doc["currency"], doc["date"])
        doc["restricted_share"] = _restricted_share(db, doc)
        parts = _classify(doc); values = bucket(doc["currency"])
        if doc["category"] == "sales":
            if doc["treatment"] in ("zero_rated", "exempt") and doc["vat"]: warnings.append(f"{doc['number']}: {doc['treatment'].replace('_', ' ')} sale shows VAT {doc['vat']:,.2f}")
            for key, base_key in (("sales", "sales_base"), ("sales_zero", "sales_zero"), ("sales_exempt", "sales_exempt"), ("sales_out", "sales_out")):
                if base_key in parts: values[key]["base"] += parts[base_key]; values[key]["count"] += 1
            if parts.get("sales"): values["sales"]["vat"] += parts["sales"]; values["sales"]["vat_lbp"] += to_lbp(parts["sales"], doc["currency"], doc["date"])
            doc["deductible_share"] = ""
            continue
        base = doc["base"] + doc["exempt"]
        for key, value in parts.items():
            line = values[key]; line["vat"] += value; line["vat_lbp"] += to_lbp(value, doc["currency"], doc["date"]); line["count"] += 1
            if key in ("purchases", "assets", "expenses", "customs", "reverse_output", "blocked"): line["base"] += base
        doc["deductible_share"] = ("0%" if "blocked" in parts and "restricted" not in parts else
                                   f"{(1 - doc['restricted_share']) * 100:.2f}% (2026 rule)" if "restricted" in parts else
                                   f"{ratio * 100:.2f}%" if doc["use"] == "mixed" else "100%")
    if vat_currency != "LBP":
        warnings.append(f"VAT return in {vat_currency} at {(std_rate * 100).normalize():f}%: the Lebanese MoF forms (Q11-2, recoverable-rate sheet) apply to LBP returns only - use the summary in {vat_currency}.")
    elif any(doc["currency"] != "LBP" for doc in documents):
        warnings.append("Foreign-currency VAT uses the saved document-date accounting rate as an estimate. Decree 11230/2023 distinguishes imports (customs rate), professional customers (then-Sayrafa rate), telecom invoices and airport/port fees; it also addresses VAT actually collected at a higher value. Verify the applicable current rate, tax-point date and deductible VAT on each document before filing.")
    adjustments = list_adjustments(db, year, quarter)
    for adjustment in adjustments:
        if currency and adjustment["currency"] != currency: continue
        amount = _money(adjustment["amount"]); amount_lbp = to_lbp(amount, adjustment["currency"], end)
        adjustment["amount_lbp"] = amount_lbp
        key = {"output": "adj_output", "input": "adj_input", "non_deductible": "non_deductible"}[adjustment["adjustment_type"]]
        line = bucket(adjustment["currency"])[key]; line["vat"] += amount; line["vat_lbp"] += amount_lbp; line["count"] += 1
    for values in per_currency.values():
        for field in ("vat", "vat_lbp"):
            values["prorata"][field] = -(values["mixed"][field] * (1 - ratio)).quantize(CENT, rounding=ROUND_HALF_UP)
            values["non_deductible"][field] += values["blocked"][field] - values["prorata"][field]
            values["total_output"][field] = values["sales"][field] + values["reverse_output"][field] + values["adj_output"][field]
            values["total_input"][field] = sum((values[k][field] for k in ("purchases", "assets", "expenses", "customs", "prorata", "adj_input")), ZERO)
            values["net"][field] = values["total_output"][field] - values["total_input"][field]
        values["non_deductible"]["base"] += values["blocked"]["base"]
        values["total_output"]["base"] = values["sales"]["base"]
        values["total_input"]["base"] = sum((values[k]["base"] for k in ("purchases", "assets", "expenses", "customs")), ZERO)
    totals_lbp = {key: sum((values[key]["vat_lbp"] for values in per_currency.values()), ZERO) for _, key, _ in LINES}
    restricted_lbp = sum((values["restricted"]["vat_lbp"] for values in per_currency.values()), ZERO)
    if restricted_lbp: totals_lbp["restricted"] = restricted_lbp  # 2.9.92
    # ---- Q4: adjust Q1-Q3 to the final annual ratio (Art. 32 adjustment of deductions)
    annual_adjustment = ZERO; adjustment_detail = []
    if int(quarter) == 4 and not currency and method == "annual":
        for previous_q in (1, 2, 3):
            previous = build_vat_return(db, year, previous_q, None, include_review, previous_year_db, None, _memo=memo)
            mixed = sum((values["mixed"]["vat_lbp"] for values in previous["per_currency"].values()), ZERO)
            saved = saved_return(db, year, previous_q)
            applied = Decimal(str(saved["deduction_ratio"])) if saved and saved.get("deduction_ratio") not in (None, "") else previous["deduction_ratio"]
            change = rnd(mixed * (ratio - applied))
            if mixed: adjustment_detail.append({"quarter": previous_q, "mixed_vat_lbp": mixed, "ratio_applied": applied, "adjustment_lbp": change})
            annual_adjustment += change
        totals_lbp["annual_adjustment"] = annual_adjustment
        totals_lbp["total_input"] += annual_adjustment; totals_lbp["net"] -= annual_adjustment; totals_lbp["non_deductible"] -= annual_adjustment
    source = "none"
    if credit_brought_forward not in (None, ""):
        credit_bf = rnd(credit_brought_forward); source = "manual"
    else:
        credit_bf = ZERO; previous_year, previous_q = previous_quarter(year, quarter)
        for candidate in ([db] if previous_year == int(year) else [previous_year_db, db]):
            if candidate is None: continue
            try: previous = saved_return(candidate, previous_year, previous_q)
            except Exception: previous = None
            if previous:
                credit_bf = rnd(previous["credit_carried_forward_lbp"]); source = f"Q{previous_q} {previous_year} saved return"; break
        else:
            # 2.9.80: the previous quarter was not saved (a quiet quarter, or forgotten): its credit carried forward is
            # calculated (and so on back to the first quarter of the books), so an older credit is never lost.
            chain_db = db if previous_year == int(year) else previous_year_db
            if chain_db is not None and _has_vat_history(chain_db, previous_year, previous_q):
                try:
                    previous = build_vat_return(chain_db, previous_year, previous_q, None, include_review, None if chain_db is previous_year_db else previous_year_db, _memo=memo)
                    credit_bf = rnd(previous["credit_carried_forward_lbp"])
                    source = f"Q{previous_q} {previous_year} not saved - calculated"
                    if credit_bf or previous["payable_lbp"]:
                        warnings.append(f"Q{previous_q} {previous_year} is not saved: its credit carried forward ({credit_bf:,.2f}) is calculated. Save Q{previous_q} {previous_year} first.")
                except ValueError: pass
    net_after_credit = totals_lbp["net"] - credit_bf
    payable = (_rounded_up(net_after_credit, end) if vat_currency == "LBP" else rnd(net_after_credit)) if net_after_credit > 0 else ZERO
    if net_after_credit > 0 and end >= "2024-11-25" and vat_currency == "LBP":
        warnings.append("Payable is estimated by rounding up to LBP 10,000; the cited MoF decision 1195 has not been verified as a VAT payable rule. Confirm the current filing/payment rounding with the VAT Directorate before filing.")
    credit = -net_after_credit if net_after_credit < 0 else ZERO
    refund = rnd(refund_requested) if refund_requested not in (None, "") else ZERO
    if refund < 0: raise ValueError("The refund requested cannot be negative")
    if refund > credit: raise ValueError(f"The refund requested cannot exceed the credit of {credit:,.2f} {vat_currency}")
    if refund:
        warnings.append("Refund eligibility is not validated. MoF guidance permits semiannual requests after Q2 or annual requests after year-end; quarterly requests require qualifying exporter status and are limited by the export proportion (Art. 30).")
    credit_cf = credit - refund
    saved = saved_return(db, year, quarter)
    changed = bool(saved) and (rnd(saved["net_lbp"]) != rnd(totals_lbp["net"]) or rnd(saved["credit_brought_forward_lbp"]) != credit_bf)
    # 2.9.72: the main figures also in the second VAT currency, at the rate of the last day of the period
    try: second_rate = db._converted_amount(Decimal("1"), vat_currency, vat_second, end) if vat_second != vat_currency else Decimal("1")
    except Exception: second_rate = None
    second = {key: (_money(value * second_rate) if second_rate is not None else None) for key, value in
              (("net", totals_lbp["net"]), ("payable", payable), ("credit_carried_forward", credit_cf), ("credit_brought_forward", credit_bf))}
    return {"year": int(year), "quarter": int(quarter), "date_from": start, "date_to": end, "due_date": due_date(year, quarter), "currency_filter": currency or "All",
        "include_review": bool(include_review), "per_currency": per_currency, "totals_lbp": totals_lbp,
        "deduction_ratio": ratio, "ratio_source": ratio_source, "ratio_method": method, "ytd_turnover_lbp": {"taxable": ytd_taxable, "exempt": ytd_exempt},
                "ytd_turnover_detail": ytd_detail if int(quarter) != 4 else final_detail, "annual_adjustment_detail": adjustment_detail,
        "credit_brought_forward_lbp": credit_bf, "credit_source": source, "net_after_credit_lbp": net_after_credit,
        "payable_lbp": payable, "refund_requested_lbp": refund, "credit_carried_forward_lbp": credit_cf, "documents": documents, "adjustments": adjustments,
        "skipped": skipped, "review_excluded": review_excluded, "warnings": warnings, "saved": saved, "changed_since_saved": changed,
        "status": "saved" if saved and not changed else "changed after saving" if changed else "not saved",
        "vat_currency": vat_currency, "vat_second_currency": vat_second, "vat_rate": (std_rate * 100).normalize(), "second_rate": second_rate, "second": second}


def _has_vat_history(db, year, quarter):
    """A saved return or a VAT document on or before the end of this quarter (else the chain of credits stops)."""
    end = quarter_range(year, quarter)[1]
    with db.connect() as connection:
        if connection.execute("SELECT 1 FROM vat_returns WHERE year*4+quarter<=? LIMIT 1", (int(year) * 4 + int(quarter),)).fetchone(): return True
        for table, column in (("invoices", "invoice_date"), ("expenses", "expense_date")):
            for row in connection.execute(f"SELECT {column} d FROM {table} WHERE CAST(COALESCE(vat,'0') AS REAL)<>0"):
                try:
                    if iso_date(row["d"]) <= end: return True
                except ValueError: continue
    return False


def _ensure_not_saved(db, year, quarter):
    if saved_return(db, year, quarter):
        raise ValueError(f"The Q{int(quarter)} {int(year)} VAT return is saved. An administrator must reopen it before it can be changed")


def add_adjustment(db, item, user_id, user_name=""):
    year = int(item.get("year") or 0); quarter = int(item.get("quarter") or 0); quarter_range(year, quarter)
    kind = str(item.get("adjustment_type") or "").lower()
    if kind not in ADJUSTMENT_TYPES: raise ValueError("Choose Output, Deductible or Non-deductible VAT adjustment")
    currency = str(item.get("currency") or "LBP").upper()
    if currency not in db.currency_codes(): raise ValueError(f"Currency {currency} is not set up (Security / Backup / Rates > Exchange Rates)")
    try: amount = Decimal(str(item.get("amount") or "").replace(",", ""))
    except Exception as exc: raise ValueError("Adjustment amount must be a number (use a minus sign to reduce)") from exc
    if not amount: raise ValueError("Adjustment amount cannot be zero")
    reason = str(item.get("reason") or "").strip()
    if len(reason) < 3: raise ValueError("Enter the reason for the adjustment")
    _ensure_not_saved(db, year, quarter)
    with db.connect() as connection:
        adjustment_id = connection.execute("""INSERT INTO vat_adjustments(year,quarter,currency,adjustment_type,amount,reason,created_by,created_by_name,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""", (year, quarter, currency, kind, str(amount.quantize(CENT)), reason, user_id, user_name, utcnow())).lastrowid
        connection.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, "create", "vat_adjustment", adjustment_id, json.dumps({"year": year, "quarter": quarter, "type": kind, "amount": str(amount), "reason": reason}), utcnow()))
    return adjustment_id


def delete_adjustment(db, adjustment_id, user_id):
    with db.connect() as connection:
        row = connection.execute("SELECT * FROM vat_adjustments WHERE id=?", (int(adjustment_id),)).fetchone()
    if not row: raise KeyError("Adjustment not found")
    _ensure_not_saved(db, row["year"], row["quarter"])
    with db.connect() as connection:
        connection.execute("DELETE FROM vat_adjustments WHERE id=?", (int(adjustment_id),))
        connection.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, "delete", "vat_adjustment", int(adjustment_id), json.dumps(dict(row)), utcnow()))
    return {"deleted": int(adjustment_id)}


def save_return(db, year, quarter, user_id, previous_year_db=None, credit_brought_forward=None, user_name="", refund_requested=None):
    result = build_vat_return(db, year, quarter, None, False, previous_year_db, credit_brought_forward, refund_requested)
    snapshot = json.dumps(json_ready({k: result[k] for k in ("per_currency", "totals_lbp", "credit_source", "review_excluded")}))
    with db.connect() as connection:
        connection.execute("""INSERT INTO vat_returns(year,quarter,net_lbp,credit_brought_forward_lbp,payable_lbp,credit_carried_forward_lbp,snapshot,saved_by,saved_by_name,saved_at)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(year,quarter) DO UPDATE SET net_lbp=excluded.net_lbp,
            credit_brought_forward_lbp=excluded.credit_brought_forward_lbp,payable_lbp=excluded.payable_lbp,
            credit_carried_forward_lbp=excluded.credit_carried_forward_lbp,snapshot=excluded.snapshot,saved_by=excluded.saved_by,
            saved_by_name=excluded.saved_by_name,saved_at=excluded.saved_at""",
            (int(year), int(quarter), str(result["totals_lbp"]["net"]), str(result["credit_brought_forward_lbp"]), str(result["payable_lbp"]),
             str(result["credit_carried_forward_lbp"]), snapshot, user_id, user_name, utcnow()))
        connection.execute("UPDATE vat_returns SET refund_requested_lbp=?,deduction_ratio=? WHERE year=? AND quarter=?",
            (str(result["refund_requested_lbp"]), str(result["deduction_ratio"]), int(year), int(quarter)))
        connection.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
            (user_id, "save", "vat_return", json.dumps({"year": int(year), "quarter": int(quarter), "payable_lbp": str(result["payable_lbp"]),
             "credit_carried_forward_lbp": str(result["credit_carried_forward_lbp"])}), utcnow()))
        import vat_ledgers
        auto = vat_ledgers.auto_close(connection)
    saved = build_vat_return(db, year, quarter, None, False, previous_year_db, credit_brought_forward, refund_requested)
    if auto:  # 2.9.97: automatic VAT closing - the closing by ledger and the settlement are posted when the return is saved
        try: saved["settlement"] = post_settlement(db, year, quarter, user_id, previous_year_db)
        except ValueError as exc: saved["settlement_note"] = str(exc)  # e.g. nothing to settle
    return saved


def reopen_return(db, year, quarter, user_id):
    if not saved_return(db, year, quarter): raise ValueError("This VAT return has not been saved")
    with db.connect() as connection:
        connection.execute("DELETE FROM vat_returns WHERE year=? AND quarter=?", (int(year), int(quarter)))
        connection.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
            (user_id, "reopen", "vat_return", json.dumps({"year": int(year), "quarter": int(quarter)}), utcnow()))
    return {"reopened": True}


# ---------------------------------------------------------------- 2.9.79: check against the books, settlement voucher
SETTLEMENT_PREFIX = "VAT SETTLEMENT - "
SETTLEMENT_DEFAULTS = {"payable_account": "4425", "credit_account": "4429", "non_deductible_account": "6459"}
_SETTLEMENT_CODES = ("4425", "4428", "4429")  # VAT payable / to recover: balances of the settlement, not VAT of the quarter


def vat_account_role(code):
    """'output' (4427...), 'input' (other 442 accounts: 44210, 44211, 44216, 442660000 ...) or None (not a VAT account of the quarter)."""
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    if not digits.startswith("442") or digits.startswith(_SETTLEMENT_CODES): return None
    return "output" if digits.startswith("4427") else "input"


def _quarter_vat_lines(db, result):
    """Posted journal lines on the VAT accounts in the quarter, in the VAT currency (settlement vouchers left out)."""
    from ledger_reports import _load_lines
    vc = result.get("vat_currency") or "LBP"
    rows = _load_lines(db, {"first_column": vc, "second_column": "none", "posting_status": "posted"})
    with db.connect() as connection:
        sources = {row["id"]: (row["source_type"], row["source_id"]) for row in connection.execute("SELECT id,source_type,source_id FROM journal_entries")}
    lines = []
    for row in rows:
        role = vat_account_role(row["code"])
        if not role or not result["date_from"] <= row["iso_date"] <= result["date_to"]: continue
        if str(row.get("entry_description") or "").startswith(SETTLEMENT_PREFIX): continue
        amount = Decimal(str(row["signed"].get(vc) if row["signed"].get(vc) is not None else 0))
        lines.append({**row, "role": role, "value": amount, "source": sources.get(row["entry_id"], (None, None))})
    return lines


def ledger_check(db, result):
    """The quarterly return against the books: VAT accounts of the quarter (number - name), the return's output and deductible VAT
    against the ledger, and the documents whose VAT in the books differs from the VAT on the document."""
    vc = result.get("vat_currency") or "LBP"; rnd = _lbp if vc == "LBP" else _money; tolerance = Decimal("1") if vc == "LBP" else CENT
    lines = _quarter_vat_lines(db, result)
    with db.connect() as connection:
        names = {row["code"]: row["name_en"] for row in connection.execute("SELECT code,name_en FROM accounts")}
    by_account = {}
    for line in lines:
        values = by_account.setdefault(str(line["code"]), {"role": line["role"], "debit": ZERO, "credit": ZERO})
        if line["value"] >= 0: values["debit"] += line["value"]
        else: values["credit"] -= line["value"]
    account_rows = []
    for code, values in sorted(by_account.items()):
        net = values["debit"] - values["credit"]
        account_rows.append([f"{code} - {names.get(code, '')}", "Output VAT" if values["role"] == "output" else "Deductible VAT", rnd(values["debit"]), rnd(values["credit"]), rnd(net)])
    ledger_output = sum((v["credit"] - v["debit"] for v in by_account.values() if v["role"] == "output"), ZERO)
    ledger_input = sum((v["debit"] - v["credit"] for v in by_account.values() if v["role"] == "input"), ZERO)
    totals = {}
    for values in result["per_currency"].values():
        for key in ("sales", "reverse_output", "purchases", "assets", "expenses", "customs"):
            totals[key] = totals.get(key, ZERO) + values[key]["vat_lbp"]
    return_output = totals.get("sales", ZERO); return_input = sum((totals.get(k, ZERO) for k in ("purchases", "assets", "expenses", "customs")), ZERO)
    compare = [["Output VAT on sales (return B: sales VAT)", rnd(return_output), rnd(ledger_output), rnd(return_output - ledger_output)],
               ["Deductible VAT before the partial deduction (return C1-C4)", rnd(return_input), rnd(ledger_input), rnd(return_input - ledger_input)]]
    # documents: VAT on the document against the VAT lines of its journal entry
    posted = {}
    for line in lines:
        source_type, source_id = line["source"]
        if source_type in ("invoice", "expense") and source_id is not None:
            sign = -1 if line["role"] == "output" else 1
            posted[(source_type, int(source_id))] = posted.get((source_type, int(source_id)), ZERO) + line["value"] * sign
    differences = []
    for doc in result["documents"]:
        if doc["category"] != "sales" and (not doc["recoverable"] or doc.get("use") == "exempt"): continue  # blocked VAT is part of the cost
        expected = doc["vat_lbp"]; booked = posted.pop((doc["source"], int(doc["id"])), ZERO)
        if doc.get("treatment") == "reverse_charge": continue
        if abs(expected - booked) >= tolerance:
            differences.append([display_date(doc["date"]), doc["number"], doc["party"], CATEGORIES[doc["category"]], rnd(expected), rnd(booked), rnd(expected - booked)])
    with db.connect() as connection:
        numbers = {("invoice", row["id"]): (row["invoice_number"], row["invoice_date"]) for row in connection.execute("SELECT id,invoice_number,invoice_date FROM invoices")}
    for (source_type, source_id), booked in sorted(posted.items(), key=lambda item: str(item[0])):  # VAT booked by documents that are not on the return
        if abs(booked) < tolerance: continue
        number, day = numbers.get((source_type, source_id), (f"{source_type} {source_id}", ""))
        differences.append([display_date(day) if day else "", number, "(not on the return: status, date or currency filter)", "", ZERO, rnd(booked), rnd(-booked)])
    other = rnd(sum((line["value"] if line["role"] == "input" else -line["value"] for line in lines if line["source"][0] not in ("invoice", "expense")), ZERO))
    sections = [{"heading": f"VAT accounts in the books - Q{result['quarter']} {result['year']} ({vc})", "headers": ["Account", "Kind", "Debit", "Credit", "Net (Dr + / Cr -)"],
                 "rows": account_rows or [["No VAT account movement in the quarter", "", "", "", ""]], "total_rows": []},
                {"heading": "Return against the books", "headers": ["Item", f"Return ({vc})", f"Books ({vc})", "Difference"], "rows": compare, "total_rows": []},
                {"heading": "Documents to check (VAT on the document is not the VAT in its journal entry)",
                 "headers": ["Date", "Document", "Customer / Supplier", "Category", f"VAT document ({vc})", f"VAT books ({vc})", "Difference"],
                 "rows": differences or [["Every document agrees with the books", "", "", "", "", "", ""]], "total_rows": []}]
    notes = [f"Vouchers and other entries on the VAT accounts (not invoices / expenses): {other:,.2f} {vc} net debit." if other else "",
             "Manual adjustments, the partial deduction (Art. 31) and the credit brought forward are on the return only: they are not differences."]
    agreed = all(abs(Decimal(str(row[3]))) < tolerance for row in compare) and not differences
    return {"sections": sections, "agreed": agreed, "notes": [n for n in notes if n], "ledger_output": ledger_output, "ledger_input": ledger_input,
            "return_output": return_output, "return_input": return_input, "documents_to_check": len(differences)}


def settlement_lines(db, result, payable_account=None, credit_account=None, non_deductible_account=None):
    """Quarter-end VAT settlement voucher: the VAT accounts of the quarter are closed (Dr output / Cr deductible, as in the books),
    the VAT that the partial deduction makes non-deductible goes to an expense, the credit brought forward is used,
    and the rest is VAT payable (Cr 4425) or VAT to recover (Dr 4429)."""
    vc = result.get("vat_currency") or "LBP"; rnd = _lbp if vc == "LBP" else _money
    try: chosen = db.default_accounts()  # 2.9.81: Settings > Accounting Settings
    except Exception: chosen = {}
    payable_account = str(payable_account or chosen.get("vat_payable") or SETTLEMENT_DEFAULTS["payable_account"]).split(" - ", 1)[0].strip()
    credit_account = str(credit_account or chosen.get("vat_credit") or SETTLEMENT_DEFAULTS["credit_account"]).split(" - ", 1)[0].strip()
    non_deductible_account = str(non_deductible_account or chosen.get("vat_non_deductible") or SETTLEMENT_DEFAULTS["non_deductible_account"]).split(" - ", 1)[0].strip()
    if not payable_account.startswith("44") or not credit_account.startswith("44"): raise ValueError("VAT payable and VAT to recover must be class 44 accounts (4425 / 4429)")
    if not non_deductible_account.startswith("6"): raise ValueError("Non-deductible VAT goes to an expense account (class 6)")
    balances = {}
    for line in _quarter_vat_lines(db, result):
        balances[str(line["code"])] = balances.get(str(line["code"]), ZERO) + line["value"]
    lines = []
    def add(code, amount, note):
        amount = rnd(amount)
        if amount > 0: lines.append({"account_code": code, "line_currency": vc, "side": "D", "amount": str(amount), "description": note})
        elif amount < 0: lines.append({"account_code": code, "line_currency": vc, "side": "C", "amount": str(-amount), "description": note})
    closing = []
    import vat_ledgers
    with db.connect() as connection:
        if vat_ledgers.enabled(connection):  # 2.9.97: each customer / supplier VAT account is first closed into its ledger's closing account
            moves, balances = vat_ledgers.closing_lines(connection, balances)
            for code, amount, note in moves:
                amount = rnd(amount)
                if amount: closing.append({"account_code": code, "line_currency": vc, "side": "D" if amount > 0 else "C", "amount": str(abs(amount)), "description": note})
    for code, balance in sorted(balances.items()): add(code, -balance, "VAT of the quarter closed")
    totals = result["totals_lbp"]
    blocked = -(totals.get("prorata", ZERO) + totals.get("annual_adjustment", ZERO))  # prorata is negative: VAT that is not deductible
    if blocked: add(non_deductible_account, blocked, "VAT not deductible (Art. 31)")
    restricted = totals.get("restricted", ZERO)
    if restricted: add(non_deductible_account, restricted, "VAT not deductible: utilities / passenger cars (Budget Law 2026 Art. 30)")  # 2.9.92
    net = sum((Decimal(line["amount"]) * (1 if line["side"] == "D" else -1) for line in lines), ZERO)  # debit left to balance = VAT owed (+) / credit (-)
    credit_bf = rnd(result.get("credit_brought_forward_lbp") or ZERO)
    if net > 0:
        used = min(credit_bf, net)
        if used: add(credit_account, -used, "Credit brought forward used")
        add(payable_account, -(net - used), "VAT payable to the Ministry of Finance")
    elif net < 0: add(credit_account, -net, "VAT credit to recover / carry forward")
    with db.connect() as connection:
        names = {row["code"]: row["name_en"] for row in connection.execute("SELECT code,name_en FROM accounts")}
    for line in lines + closing:
        if line["account_code"] not in names: raise ValueError(f"Account {line['account_code']} was not found in the chart of accounts")
        line["account_name"] = names[line["account_code"]]
    payable = sum((Decimal(l["amount"]) for l in lines if l["account_code"] == payable_account and l["side"] == "C"), ZERO)
    description = f"{SETTLEMENT_PREFIX}Q{result['quarter']} {result['year']}"
    return {"lines": lines, "payable": payable, "net": net, "return_payable": result["payable_lbp"], "currency": vc,
            "date": result["date_to"], "description": description,
            "closing_lines": closing, "closing_description": f"{description} - VAT closing by ledger"}  # 2.9.97


def post_settlement(db, year, quarter, user_id, previous_year_db=None, payable_account=None, credit_account=None, non_deductible_account=None):
    """Post (or replace) the settlement voucher of a SAVED quarterly return."""
    result = build_vat_return(db, year, quarter, None, False, previous_year_db)
    if not result["saved"] or result["changed_since_saved"]: raise ValueError(f"Save the Q{int(quarter)} {int(year)} VAT return first (documents changed after saving count as not saved)")
    plan = settlement_lines(db, result, payable_account, credit_account, non_deductible_account)
    if len(plan["lines"]) < 2: raise ValueError("Nothing to settle: no VAT movement in the quarter")
    with db.connect() as connection:
        for row in connection.execute("SELECT id FROM journal_entries WHERE source_type='journal_voucher' AND (description=? OR description=?)",
                                      (plan["description"], plan["closing_description"])).fetchall():
            connection.execute("DELETE FROM journal_entries WHERE id=?", (row["id"],))
    closing_number = None
    if plan.get("closing_lines"):  # 2.9.97: customer / supplier VAT accounts -> closing accounts (44210 / 44270 / 44265 / 44263)
        closing = db.save_journal_voucher({"entry_date": display_date(plan["date"]), "description": plan["closing_description"], "currency": plan["currency"], "voucher_type": "06"},
                                          [{k: v for k, v in line.items() if k != "account_name"} for line in plan["closing_lines"]], user_id)
        closing_number = closing["voucher"]["entry_number"]
    voucher = db.save_journal_voucher({"entry_date": display_date(plan["date"]), "description": plan["description"], "currency": plan["currency"], "voucher_type": "06"},
                                      [{k: v for k, v in line.items() if k != "account_name"} for line in plan["lines"]], user_id)
    return {**plan, "voucher": voucher["voucher"]["entry_number"], "closing_voucher": closing_number}


def export_sections(result):
    """Export an internal VAT calculation schedule plus supporting documents."""
    title = f"Quarterly VAT Calculation Schedule - Q{result['quarter']} {result['year']} | {ARABIC_TITLE}"
    ratio = Decimal(str(result.get("deduction_ratio", 1)))
    vc = result.get("vat_currency") or "LBP"; vc2 = result.get("vat_second_currency") or "USD"  # 2.9.72
    rate_text = f"{Decimal(str(result.get('vat_rate') or 11)).normalize():f}%"
    label_of = lambda label: label.replace("11%", rate_text)
    meta = [f"Period: {display_date(result['date_from'])} to {display_date(result['date_to'])}   Due date: {display_date(result['due_date'])}   Currency filter: {result['currency_filter']}",
            f"Partial deduction ratio (Art. 31): {ratio * 100:.2f}% ({result.get('ratio_source', '')})   Status: {result['status']}",
            "Internal schedule references only: A-F labels are not certified Ministry of Finance form box numbers.",
            "Conversion uses saved accounting rates at each document date; the legally applicable tax-point/rate can differ (Decree 11230/2023). The 10,000 LBP payable ceiling from 25-11-2024 is an unverified worksheet estimate, not a certified VAT filing rule."
            if vc == "LBP" else f"VAT return in {vc} at {rate_text}, converted at the saved accounting rate of each document date; second currency {vc2} at the rate of the last day of the period."]
    if result["review_excluded"]: meta.append(f"Note: {result['review_excluded']} document(s) in Review status are excluded from this return")
    for warning in result.get("warnings", []): meta.append("Check: " + warning)
    keys = [key for _, key, _ in LINES]; totals_index = [keys.index(k) for k in ("total_output", "total_input", "net")]
    no_base = ("adj_output", "adj_input", "net", "prorata", "annual_adjustment", "total_output")
    sections = []
    for code, values in sorted(result["per_currency"].items()):
        rows = [[number, label_of(label), ARABIC.get(key, ""), values[key]["base"] if key not in no_base else "", values[key]["vat"] if key not in ("sales_zero", "sales_exempt", "sales_out") else "",
                 values[key]["vat_lbp"] if key not in ("sales_zero", "sales_exempt", "sales_out") else ""] for number, key, label in LINES if key in values]
        sections.append({"heading": f"VAT calculation by currency - {code}", "headers": ["Internal ref.", "Description", "البيان", f"Base ({code})", f"VAT ({code})", f"VAT ({vc})"],
                         "rows": rows, "total_rows": totals_index})
    totals = result["totals_lbp"]
    summary = [[number, label_of(label), ARABIC.get(key, ""), totals.get(key, ZERO)] for number, key, label in LINES if key not in ("sales_zero", "sales_exempt", "sales_out")]
    summary += [["F1", f"Credit brought forward ({result['credit_source']})", ARABIC["credit_bf"], result["credit_brought_forward_lbp"]],
                ["F2", "VAT PAYABLE TO THE MINISTRY OF FINANCE", ARABIC["payable"], result["payable_lbp"]],
                ["F3", "Refund of VAT credit requested (Art. 30)", ARABIC["refund"], result.get("refund_requested_lbp", ZERO)],
                ["F4", "Credit carried forward to the next period", ARABIC["credit_cf"], result["credit_carried_forward_lbp"]]]
    labels = [row[1] for row in summary]
    second_rate = result.get("second_rate")
    headers = ["Internal ref.", "Description", "البيان", f"Amount ({vc})"]
    if vc2 and vc2 != vc and second_rate is not None:  # 2.9.72: the same figures in the second VAT currency
        headers.append(f"Amount ({vc2})")
        for row in summary: row.append(_money(Decimal(str(row[3] or 0)) * Decimal(str(second_rate))) if row[3] not in ("", None) else "")
        meta.append(f"{vc2} equivalent at 1 {vc} = {Decimal(str(second_rate)):.6g} {vc2} ({display_date(result['date_to'])}).")
    sections.append({"heading": f"VAT calculation summary - all currencies in {vc} | ملخص احتساب الضريبة", "headers": headers, "rows": summary,
                     "total_rows": [labels.index(l) for l in ("TOTAL OUTPUT VAT", "TOTAL DEDUCTIBLE VAT",
                             "NET VAT FOR THE PERIOD (output VAT less deductible input VAT)", "VAT PAYABLE TO THE MINISTRY OF FINANCE",
                             "Credit carried forward to the next period")]})
    turnover = result.get("ytd_turnover_lbp", {})
    ratio_rows = [[f"Taxable and zero-rated turnover ({vc}, year to date)", turnover.get("taxable", ZERO)], [f"Exempt turnover ({vc}, year to date)", turnover.get("exempt", ZERO)],
                  ["Deduction ratio applied", f"{ratio * 100:.2f}%"], ["Basis", result.get("ratio_source", "")]]
    for item in result.get("annual_adjustment_detail", []):
        ratio_rows.append([f"Q{item['quarter']}: mixed-use VAT {item['mixed_vat_lbp']:,.2f} {vc} at {Decimal(str(item['ratio_applied'])) * 100:.2f}%", item["adjustment_lbp"]])
    sections.append({"heading": "Partial deduction right (Art. 31)", "headers": ["Item", "Value"], "rows": ratio_rows, "total_rows": [2]})
    detail = [[display_date(d["date"]), d["number"], d["party"], CATEGORIES[d["category"]], d.get("treatment", "standard").replace("_", " "),
               d.get("deductible_share", ""), d["currency"], d["base"], d["vat"], d["lbp_rate"], d["vat_lbp"], d["status"]] for d in result["documents"]]
    sections.append({"heading": "Supporting documents", "headers": ["Date", "Document", "Customer / Supplier", "Category", "VAT Treatment", "Deductible",
                     "Currency", "Base", "VAT", f"{vc} Rate", f"VAT ({vc})", "Status"], "rows": detail or [["No documents in this quarter"] + [""] * 11], "total_rows": []})
    if result["adjustments"]:
        sections.append({"heading": "Manual adjustments", "headers": ["Type", "Currency", "Amount", f"Amount ({vc})", "Reason", "Entered by", "Entered at"],
            "rows": [[ADJUSTMENT_TYPES[a["adjustment_type"]], a["currency"], _money(a["amount"]), a.get("amount_lbp", ""), a["reason"],
                      a.get("created_by_name") or "", str(a["created_at"])[:16].replace("T", " ")] for a in result["adjustments"]], "total_rows": []})
    return title, meta, sections


def filing_worksheet(result, company):
    """Auto-fill a filing preparation sheet from the same quarterly VAT calculation.

    Sections follow the subjects of the public Q1-2 and Q11-2 specimens,
    not their box layout. A-F references remain internal worksheet references.
    """
    if result.get("currency_filter") != "All" or result.get("include_review"):
        raise ValueError("The filing worksheet requires All Currencies and excludes Review documents")
    totals = result["totals_lbp"]
    company_fields = (
        ("Registered company name", company.get("company_name")),
        ("Ministry of Finance / VAT number", company.get("company_mof")),
        ("Registered address", company.get("company_address")),
        ("Contact phone", company.get("company_phone")),
    )
    company_rows = [[label, str(value).strip() if value else "MISSING - complete in Settings"] for label, value in company_fields]
    missing = [label for label, value in company_fields if not str(value or "").strip()]
    worksheet = [
        ["Tax period", f"Q{result['quarter']} {result['year']}"],
        ["Period from", display_date(result["date_from"])],
        ["Period to", display_date(result["date_to"])],
        ["Filing due date", display_date(result["due_date"])],
        ["Deduction ratio", f"{Decimal(str(result['deduction_ratio'])) * 100:.2f}% ({result['ratio_source']})"],
        ["Source", "Posted invoices, expenses, customs and approved VAT adjustments"],
        ["Return state", result["status"]],
    ]
    bases = {}
    for doc in result["documents"]:
        parts = _classify(doc)
        if doc["category"] == "sales":
            for key in ("sales_base", "sales_zero", "sales_exempt", "sales_out"):
                bases[key] = bases.get(key, ZERO) + _lbp(parts.get(key, ZERO) * doc["lbp_rate"])
        else:
            key = doc["category"] if doc["recoverable"] and doc["use"] != "exempt" else "non_deductible"
            bases[key] = bases.get(key, ZERO) + _lbp((doc["base"] + doc["exempt"]) * doc["lbp_rate"])
    lines = [[number, label, ARABIC.get(key, ""), bases.get("sales_base" if key == "sales" else key, ""),
              totals.get(key, ZERO)] for number, key, label in LINES
             if key not in ("sales_zero", "sales_exempt", "sales_out")]
    # Taxable/exempt turnover is a base, not output tax. Convert each document
    # separately at its own historical LBP rate, rather than using a current rate.
    for number, key, label in (("A2", "sales_zero", "Zero-rated supplies (LBP)"),
                               ("A3", "sales_exempt", "Exempt supplies (LBP)"),
                               ("A4", "sales_out", "Outside scope supplies (LBP)")):
        lines.append([number, label, ARABIC.get(key, ""), bases.get(key, ZERO), ""])
    lines += [
        ["F1", "Credit brought forward", ARABIC["credit_bf"], "", result["credit_brought_forward_lbp"]],
        ["F2", "Amount payable", ARABIC["payable"], "", result["payable_lbp"]],
        ["F3", "Refund requested", ARABIC["refund"], "", result["refund_requested_lbp"]],
        ["F4", "Credit carried forward", ARABIC["credit_cf"], "", result["credit_carried_forward_lbp"]],
    ]
    by_ref = {line[0]: line for line in lines}
    headers = ["Internal ref.", "Description", "البيان", "Base (LBP)", "VAT / balance (LBP)"]
    def group(heading, refs, total_refs=()):
        rows = [by_ref[ref] for ref in refs]
        return {"heading": heading, "headers": headers, "rows": rows,
                "total_rows": [index for index, row in enumerate(rows) if row[0] in total_refs]}
    turnover = result.get("ytd_turnover_lbp", {})
    ratio = Decimal(str(result["deduction_ratio"]))
    notices = [
        "Preparation worksheet inspired by the sections of the Ministry's published Q1-2 and Q11-2 specimens (marked 2010), NOT a copy of either form.",
        "A-F references are internal and are not certified Ministry of Finance form box numbers. No current issued-form box mapping has been verified.",
        "The published specimens must not be used for filing; obtain the current issued Q1-2 and, where applicable, Q11-2 from the VAT Directorate and compare all amounts and schedules manually.",
        "The partial-deduction section is a calculation review, NOT a completed Q11-2 supplement; the published supplement asks for purchase, expense and asset use breakdowns not reproduced here.",
        "No electronic filing or submission is performed by this software.",
    ]
    if missing: notices.append("Missing employer information: " + ", ".join(missing))
    if result["review_excluded"]: notices.append(f"{result['review_excluded']} Review document(s) excluded; resolve before filing.")
    if result.get("changed_since_saved"): notices.append("Saved return changed: review and save it again.")
    if result.get("skipped"): notices.append(f"{len(result['skipped'])} document(s) skipped due to unreadable dates.")
    notices += ["Check: " + warning for warning in result.get("warnings", [])]
    return notices, [
        {"heading": "Taxpayer / المكلف (published Q1-2 specimen)", "headers": ["Field", "Value"], "rows": company_rows, "total_rows": []},
        {"heading": "Tax period / الفترة الضريبية (published Q1-2 specimen)", "headers": ["Field", "Value"], "rows": worksheet, "total_rows": []},
        group("Revenue and output VAT / الإيرادات والضريبة المستحقة (published Q1-2 specimen)",
              ("A1", "A2", "A3", "A4", "B1", "B2", "B3"), ("B3",)),
        group("Purchases, expenses and deductible VAT / المشتريات والأعباء (published Q1-2 specimen)",
              ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "D1"), ("C8",)),
        {"heading": "Partial-deduction review / حق الحسم الجزئي (Q11-2 specimen subject, not its boxes)",
         "headers": ["Internal calculation", "Value"],
         "rows": [["Taxable and zero-rated turnover (LBP, year to date)", turnover.get("taxable", ZERO)],
                  ["Exempt turnover (LBP, year to date)", turnover.get("exempt", ZERO)],
                  ["Deduction ratio applied", f"{ratio * 100:.2f}%"],
                  ["Ratio basis", result["ratio_source"]]],
         "total_rows": [2]},
        group("VAT balance and credit / الرصيد الضريبي (published Q1-2 specimen)",
              ("E1", "F1", "F2", "F3", "F4"), ("E1", "F2", "F4")),
    ]


def official_form(result, company):
    """The return in the layout of the Ministry's periodic declaration Q1-2, with its annexes Q11-2 (partial right of
    deduction, Art. 31: deductible VAT on mixed purchases = VAT x ratio) and Q13-2 (ten largest suppliers and customers).
    Amounts in LBP. Boxes that Saber does not record separately (advances, tax withheld at source, sales of fixed assets,
    penalties) show 0 and are filled by hand when they apply."""
    if result.get("currency_filter") != "All" or result.get("include_review"):
        raise ValueError("The official form requires All Currencies and excludes Review documents")
    D = lambda v: Decimal(str(v or 0)); ratio = D(result["deduction_ratio"]); totals = {k: D(v) for k, v in result["totals_lbp"].items()}
    box = {code: [ZERO, ZERO, ZERO] for code in (100, 110, 120, 130, 140, 150, 160, 156, 170, 180, 190, 200, 210, 220, 230, 240, 250)}
    annex = {code: [ZERO, ZERO] for code in (600, 610, 620, 630, 460, 560, 660, 670, 680, 690, 700, 710)}
    groups = {"purchases": (600, 610, 620), "customs": (600, 610, 620), "expenses": (460, 560, 660), "assets": (680, 690, 700)}
    suppliers = {}; customers = {}
    for doc in result.get("documents", []):
        rate = D(doc.get("lbp_rate") or 1); base = D(doc["base"]) * rate; exempt = D(doc["exempt"]) * rate; vat = D(doc["vat"]) * rate
        if doc["category"] == "sales":
            treatment = doc.get("treatment") or "standard"
            if treatment == "zero_rated": box[130][0] += base + exempt
            elif treatment == "exempt": box[140][0] += base + exempt
            elif treatment == "out_of_scope": box[150][0] += base + exempt
            else: box[100][0] += base; box[100][1] += vat; box[140][0] += exempt
            key = (doc.get("party") or "-", doc.get("party_mof") or ""); customers[key] = customers.get(key, ZERO) + base + exempt
            continue
        only, never, mixed = groups.get(doc["category"], groups["purchases"])
        blocked = not doc.get("recoverable", True) or doc.get("use") == "exempt" or Decimal(str(doc.get("restricted_share") or 0)) >= 1
        line = never if blocked else (mixed if doc.get("use") in ("mixed", "utilities", "passenger_car") else only)
        annex[line][0] += base + exempt
        if not blocked: annex[line][1] += vat * (1 - Decimal(str(doc.get("restricted_share") or 0))) * (ratio if line == mixed else 1)
        if doc.get("source") == "invoice":
            key = (doc.get("party") or "-", doc.get("party_mof") or ""); suppliers[key] = suppliers.get(key, ZERO) + base + exempt
    for total, parts in ((630, (600, 610, 620)), (670, (460, 560, 660)), (710, (680, 690, 700))):
        annex[total] = [sum((annex[p][i] for p in parts), ZERO) for i in (0, 1)]
    box[170][1] = totals.get("reverse_output", ZERO); box[180][1] = totals.get("adj_output", ZERO)
    box[190] = [sum((box[c][i] for c in (100, 110, 120, 130, 140, 150, 160, 156, 170, 180)), ZERO) for i in (0, 1, 2)]
    box[200] = [annex[630][0], ZERO, annex[630][1]]; box[210] = [annex[670][0], ZERO, annex[670][1]]; box[230] = [annex[710][0], ZERO, annex[710][1]]
    box[250] = [sum((box[c][i] for c in (200, 210, 220, 230, 240)), ZERO) for i in (0, 1, 2)]
    m = lambda v: _lbp(v)
    labels = ((100, "صافي الإيرادات الخاضعة", "Net taxable revenues"), (110, "سلفات مقبوضة عن عمليات خاضعة", "Advances received on taxable operations"),
              (120, "صافي الإيرادات الخاضعة المحتسبة ضريبتها مسبقاً لدى المنبع", "Taxable revenues with VAT already withheld at source"),
              (130, "صافي الإيرادات المعفاة مع حق الحسم", "Exempt revenues with right of deduction (zero-rated)"),
              (140, "صافي الإيرادات المعفاة دون حق الحسم", "Exempt revenues without right of deduction"),
              (150, "صافي الإيرادات الخارجة عن نطاق الضريبة", "Revenues outside the scope of VAT"), (160, "صافي مبيع أصول ثابتة خاضعة", "Sales of taxable fixed assets"),
              (156, "صافي مبيع أصول ثابتة غير خاضعة", "Sales of non-taxable fixed assets"), (170, "ضريبة مستحقة للدفع عن مبالغ مستحقة لغير المقيمين", "VAT due on amounts owed to non-residents"),
              (180, "مختلف", "Other / adjustments"), (190, "المجموع", "Total"),
              (200, "صافي المشتريات (+/- التغيير في المخزون)", "Net purchases"), (210, "صافي الأعباء", "Net charges (expenses)"),
              (220, "سلفات مدفوعة عن عمليات خاضعة", "Advances paid on taxable operations"), (230, "صافي مشتريات أصول ثابتة", "Net purchases of fixed assets"),
              (240, "مبالغ مشتريات محتسبة ضريبتها مسبقاً لدى المنبع", "Purchases with VAT withheld at source"), (250, "المجموع", "Total"))
    q12 = [[str(c), en, ar, m(box[c][0]), m(box[c][1]) if c < 200 else "", m(box[c][2]) if c >= 200 else ""] for c, ar, en in labels]
    credit_bf = D(result.get("credit_brought_forward_lbp")); payable = D(result.get("payable_lbp")); credit_cf = D(result.get("credit_carried_forward_lbp"))
    settlement = [["300", "Tax payable", "الضريبة المستحقة للدفع", m(totals["total_output"])],
                  ["310", "Less: credit brought forward from the previous period", "تنزيل: الرصيد المدور من الفترة الضريبية السابقة", m(credit_bf)],
                  ["330", "Less: deductible VAT for the current period", "تنزيل: ضريبة قابلة للحسم عن الفترة الحالية", m(totals["total_input"])],
                  ["340", "Net tax payable", "صافي الضريبة المستحقة للدفع", m(payable)],
                  ["350", "Credit carried forward, refundable", "رصيد مدور قابل للإسترداد", m(credit_cf)],
                  ["355", "Amount offset (refund request)", "المبلغ الذي أجري به مقاصة", m(D(result.get("refund_requested_lbp")))],
                  ["360-368", "Penalties (fill in when applicable)", "الغرامات", 0],
                  ["370", "Total due", "إجمالي المتوجب دفعه", m(payable)]]
    a_labels = ((600, "Purchases used only for operations giving the right of deduction", "المشتريات المستعملة فقط لعمليات تتيح حق الحسم"),
                (610, "Purchases used only for operations not giving the right of deduction", "المشتريات المستعملة فقط لعمليات لا تتيح حق الحسم"),
                (620, "Purchases whose use cannot be determined *", "المشتريات التي لا يمكن تحديد وجهة استعمالها"), (630, "Total (600+610+620)", "المجموع"),
                (460, "Charges used only for operations giving the right of deduction", "الأعباء المستعملة فقط لعمليات تتيح حق الحسم"),
                (560, "Charges used only for operations not giving the right of deduction", "الأعباء المستعملة فقط لعمليات لا تتيح حق الحسم"),
                (660, "Charges whose use cannot be determined *", "الأعباء التي لا يمكن تحديد وجهة استعمالها"), (670, "Total (460+560+660)", "المجموع"),
                (680, "Fixed assets used only for operations giving the right of deduction", "الأصول الثابتة المستعملة فقط لعمليات تتيح حق الحسم"),
                (690, "Fixed assets used only for operations not giving the right of deduction", "الأصول الثابتة المستعملة فقط لعمليات لا تتيح حق الحسم"),
                (700, "Fixed assets whose use cannot be determined *", "الأصول الثابتة التي لا يمكن تحديد وجهة استعمالها"), (710, "Total (680+690+700)", "المجموع"))
    q11 = [[str(c), en, ar, m(annex[c][0]), m(annex[c][1]) if c not in (610, 560, 690) else ""] for c, en, ar in a_labels]
    turnover = result.get("ytd_turnover_lbp") or {}
    ratio_rows = [["Revenues giving the right of deduction (100+120+130+160+180)", "الإيرادات التي تتيح حق الحسم", m(D(turnover.get("taxable")))],
                  ["Total revenues (100+120+130+140+150+160+156+180)", "إجمالي الإيرادات", m(D(turnover.get("taxable")) + D(turnover.get("exempt")))],
                  ["Deduction ratio applied (Art. 31)", "نسبة الحسم", f"{ratio * 100:.2f}% ({result.get('ratio_source', '')})"],
                  ["* Deductible VAT on 620 / 660 / 700 = VAT paid x ratio", "الضريبة القابلة للحسم = الضريبة المدفوعة x النسبة", ""]]
    def top(data):
        rows = sorted(data.items(), key=lambda pair: -pair[1])[:10]
        return [[str(i), name, mof, m(value)] for i, ((name, mof), value) in enumerate(rows, 1)] or [["-", "None in this period", "", 0]]
    head = [f"Company: {company.get('company_name') or '-'}     VAT registration No.: {company.get('company_mof') or '-'}",
            f"Period: Q{result['quarter']} {result['year']} ({display_date(result['date_from'])} to {display_date(result['date_to'])})     Filing due: {display_date(result['due_date'])}     Amounts in LBP",
            "Prepared from posted documents in the layout of the periodic declaration Q1-2 and its annexes Q11-2 and Q13-2. Check against the form issued by the Ministry before filing."]
    sections = [{"heading": "Q1-2 Periodic declaration | ق1-2 التصريح الدوري - Revenues and purchases", "fixed": True,
                 "headers": ["Box | الخانة", "Item", "البيان", "(1) Amount | المبلغ", "(2) VAT due | الضريبة المستحقة", "(3) Deductible VAT | الضريبة القابلة للحسم"],
                 "rows": q12, "total_rows": [10, 16]},
                {"heading": "Q1-2 Settlement | التسوية", "fixed": True, "headers": ["Box | الخانة", "Item", "البيان", "Amount (LBP) | المبلغ"], "rows": settlement, "total_rows": [3, 7]},
                {"heading": "Q11-2 Annex - partial right of deduction (Art. 31) | ملحق التصريح الدوري لحق الحسم الجزئي", "fixed": True,
                 "headers": ["Box | الخانة", "Item", "البيان", "(1) Amount | المبلغ", "(2) Deductible VAT | الضريبة القابلة للحسم"], "rows": q11, "total_rows": [3, 7, 11]},
                {"heading": "Deduction ratio | نسبة الحسم", "fixed": True, "headers": ["Item", "البيان", "Value"], "rows": ratio_rows, "total_rows": []},
                {"heading": "Q13-2 Annex - ten largest suppliers | أكبر عشرة موردين", "fixed": True, "headers": ["#", "Supplier | المورد",
                        "MOF No. | رقم التسجيل", "Purchases (LBP)"], "rows": top(suppliers), "total_rows": []},
                {"heading": "Q13-2 Annex - ten largest customers | أكبر عشرة زبائن", "fixed": True, "headers": ["#", "Customer | الزبون",
                        "MOF No. | رقم التسجيل", "Sales (LBP)"], "rows": top(customers), "total_rows": []}]
    return head, sections


def recoverable_rate_sheet(result, company):
    """'Calcul du taux récupérable' in the layout of the accountants' worksheet (PROGRAMME CALCUL TAUX RECUPERABLE TVA):
    revenue accounts split taxable / exempt, the recoverable rate (Art. 31), then the VAT on fixed assets, goods, packaging
    and overheads split into recoverable and non-recoverable, VAT collected and VAT payable (negative = credit).
    VAT on goods / assets / expenses whose use is "taxable" or "export" is 100% recoverable, "mixed" use x rate,
    "exempt" use or non-deductible = 0%. Amounts in LBP."""
    if result.get("currency_filter") != "All" or result.get("include_review"):
        raise ValueError("The recoverable rate sheet requires All Currencies and excludes Review documents")
    D = lambda v: Decimal(str(v or 0)); ratio = D(result["deduction_ratio"]); totals = {k: D(v) for k, v in result["totals_lbp"].items()}
    quarter = {"taxable": ZERO, "export": ZERO, "exempt": ZERO, "out": ZERO}
    for doc in result.get("documents", []):
        if doc["category"] != "sales": continue
        parts = _classify({**doc, "base": D(doc["base"]), "exempt": D(doc["exempt"]), "vat": D(doc["vat"])}); rate = D(doc.get("lbp_rate") or 1)
        quarter["taxable"] += parts.get("sales_base", ZERO) * rate; quarter["export"] += parts.get("sales_zero", ZERO) * rate
        quarter["exempt"] += parts.get("sales_exempt", ZERO) * rate; quarter["out"] += parts.get("sales_out", ZERO) * rate
    year = {k: D(v) for k, v in (result.get("ytd_turnover_detail") or {}).items()} or dict(quarter)
    m = lambda v: _lbp(v)
    def produits(values):
        taxable = values.get("taxable", ZERO) + values.get("export", ZERO); exempt = values.get("exempt", ZERO) + values.get("out", ZERO)
        return taxable, exempt, taxable + exempt
    q_tax, q_exe, q_all = produits(quarter); y_tax, y_exe, y_all = produits(year)
    rows = [["VENTES MARCHANDISES TAXABLES", "مبيعات خاضعة", m(quarter["taxable"]), m(year.get("taxable"))],
            ["VENTES MARCHANDISES EXPORT", "مبيعات تصدير (معفاة مع حق الحسم)", m(quarter["export"]), m(year.get("export"))],
            ["VENTES MARCHANDISES (FREE ZONE)", "مبيعات منطقة حرة", 0, 0],
            ["VENTES IMMOBILISATIONS TAXABLES", "مبيع أصول ثابتة خاضعة", 0, 0],
            ["DIVERS TAXABLES", "مختلف خاضع", 0, 0],
            ["TOTAL PRODUITS TAXABLES", "مجموع الإيرادات الخاضعة", m(q_tax), m(y_tax)],
            ["VENTES MARCHANDISES EXEMPTES", "مبيعات معفاة", m(quarter["exempt"]), m(year.get("exempt"))],
            ["VENTES MARCHANDISES HORS TAXES", "مبيعات خارج نطاق الضريبة", m(quarter["out"]), m(year.get("out"))],
            ["VENTES IMMOBILISATIONS EXEMPTES", "مبيع أصول ثابتة غير خاضعة", 0, 0],
            ["DIVERS EXEMPTES", "مختلف معفى", 0, 0],
            ["TOTAL PRODUITS EXEMPTES", "مجموع الإيرادات المعفاة", m(q_exe), m(y_exe)],
            ["TOTAL PRODUITS", "مجموع الإيرادات", m(q_all), m(y_all)]]
    quarter_rate = (q_tax / q_all) if q_all > 0 else Decimal("1")
    rate_rows = [["TAUX DU TRIMESTRE (taxables / total)", "نسبة الفصل", f"{quarter_rate * 100:.4f}%"],
                 ["TAUX RECUPERABLE APPLIQUE", "النسبة المطبقة (المادة 31)", f"{ratio * 100:.4f}%"],
                 ["Base du taux appliqué", "أساس النسبة", result.get("ratio_source", "")]]
    groups = {"assets": 0, "purchases": 1, "customs": 1, "packaging": 2, "expenses": 3}
    lines = [[ZERO, ZERO, ZERO] for _ in range(4)]  # initial, recoverable, non recoverable
    for doc in result.get("documents", []):
        if doc["category"] == "sales": continue
        index = groups.get(doc["category"], 3); rate = D(doc.get("lbp_rate") or 1)
        vat = D(doc["vat"]) * rate
        if doc.get("treatment") == "reverse_charge" and not D(doc["vat"]):
            vat = ((D(doc["base"]) + D(doc["exempt"])) * D(doc.get("std_rate", RATE))).quantize(CENT, rounding=ROUND_HALF_UP) * rate
        blocked = not doc.get("recoverable", True) or doc.get("use") == "exempt"
        share = ZERO if blocked else (ratio if doc.get("use") in ("mixed", "utilities", "passenger_car") else Decimal("1"))
        share *= 1 - Decimal(str(doc.get("restricted_share") or 0))  # 2.9.92
        lines[index][0] += vat; lines[index][1] += vat * share; lines[index][2] += vat * (1 - share)
    labels = (("TVA SUR ACQUISITION IMMOBILISATIONS", "ضريبة على شراء أصول ثابتة"), ("TVA SUR ACHATS MARCHANDISES", "ضريبة على شراء البضائع"),
              ("TVA SUR ACHATS EMBALLAGES", "ضريبة على شراء التوضيب"), ("TVA SUR FRAIS GENERAUX", "ضريبة على المصاريف العامة"))
    vat_rows = [[en, ar, m(a), m(b), m(c)] for (en, ar), (a, b, c) in zip(labels, lines)]
    extra = totals.get("adj_input", ZERO) + totals.get("annual_adjustment", ZERO)
    if extra: vat_rows.append(["REGULARISATIONS (ajustements / Art. 32)", "تسويات", m(extra), m(extra), 0])
    initial = sum((l[0] for l in lines), ZERO) + extra; recoverable = sum((l[1] for l in lines), ZERO) + extra
    vat_rows.append(["TOTAL", "المجموع", m(initial), m(recoverable), m(initial - recoverable)])
    collected = totals.get("total_output", ZERO); to_pay = collected - recoverable
    credit_bf = D(result.get("credit_brought_forward_lbp"))
    pay_rows = [["TVA COLLECTEES", "الضريبة المحصلة", m(collected)],
                ["TVA RECUPERABLE", "الضريبة القابلة للاسترداد", m(recoverable)],
                ["TVA A PAYER (négatif = crédit)", "الضريبة المستحقة (سالب = رصيد دائن)", m(to_pay)],
                ["Crédit reporté du trimestre précédent", "الرصيد المدور من الفترة السابقة", m(credit_bf)],
                ["NET A PAYER", "الصافي المتوجب", m(D(result.get("payable_lbp")))],
                ["CREDIT A REPORTER", "رصيد مدور", m(D(result.get("credit_carried_forward_lbp")))]]
    meta = [f"SOCIETE: {company.get('company_name') or '-'}     N° TVA: {company.get('company_mof') or '-'}",
            f"PERIODE: {result['quarter']} EME TRIMESTRE {result['year']} ({display_date(result['date_from'])} - {display_date(result['date_to'])})     Montants en LBP",
            "Use per document: taxable / export = 100% recoverable, mixed = x rate, exempt or non-deductible = 0%."]
    sections = [{"heading": "DETAILS COMPTES PRODUITS | تفاصيل حسابات الإيرادات", "fixed": True,
                 "headers": ["Compte", "البيان", "Trimestre (LBP)", "Cumul année - base du taux (LBP)"], "rows": rows, "total_rows": [5, 10, 11]},
                {"heading": "TAUX RECUPERABLE | نسبة الاسترداد", "fixed": True, "headers": ["", "البيان", "Taux"], "rows": rate_rows, "total_rows": [1]},
                {"heading": "CALCUL DE LA TVA A RECUPERER | احتساب الضريبة القابلة للاسترداد", "fixed": True,
                 "headers": ["", "البيان", "Montant initial", "Récupérable", "Non récupérable"], "rows": vat_rows, "total_rows": [len(vat_rows) - 1]},
                {"heading": "TVA A PAYER | الضريبة المتوجبة", "fixed": True, "headers": ["", "البيان", "Montant (LBP)"], "rows": pay_rows, "total_rows": [2, 4]}]
    return meta, sections


def json_ready(value):
    if isinstance(value, Decimal): return float(value)
    if isinstance(value, list): return [json_ready(v) for v in value]
    if isinstance(value, dict): return {k: json_ready(v) for k, v in value.items()}
    return value
