"""Evidence-based analytic study built from posted, converted ledger lines."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import json


_ZERO = 0.0


def _month(day):
    return str(day or "")[:7]


def _periods(rows, start_date=None, end_date=None):
    selected = []
    start = str(start_date or "")[:10]
    end = str(end_date or "")[:10]
    for row in rows or ():
        day = str(row.get("iso_date") or row.get("entry_date") or "")[:10]
        if start and day < start or end and day > end:
            continue
        selected.append(row)
    return selected


def _dimension_summary(buckets, denominator):
    result = []
    for name, values in buckets.items():
        revenue = round(values["revenue"], 2)
        costs = round(values["cost"], 2)
        expenses = round(values["expense"], 2)
        profit = round(revenue - costs - expenses, 2)
        result.append({"name": name, "revenue": revenue, "cost_of_sales": costs,
                       "expenses": expenses, "net_contribution": profit,
                       "gross_margin_percent": round((revenue - costs) / revenue * 100, 1) if revenue else None,
                       "net_margin_percent": round(profit / revenue * 100, 1) if revenue else None,
                       "margin_available": bool(revenue),
                       "share_of_expense_percent": round(expenses / denominator * 100, 1) if denominator else 0.0})
    return sorted(result, key=lambda item: item["net_contribution"], reverse=True)


def _with_vat_evidence(db, rows):
    """Attach provenance to actual VAT cost lines, never estimate or add costs.

    Legacy VAT reclassifications omit dimensions. Inherit the documented header
    allocation only when there are no conflicting original expense-line dimensions.
    Unlinked/manual/quarterly settlement entries remain unallocated.
    """
    from nanza.ai_accountant.classifier import _non_deductible_category
    ids = list({r['entry_id'] for r in rows if r.get('source_type') in ('vat_reclass', 'journal_voucher')})
    evidence = {}
    if not ids:
        return rows
    with db.connect() as connection:
        for offset in range(0, len(ids), 400):
            batch = ids[offset:offset + 400]
            records = connection.execute(f"""SELECT report.id,
                COALESCE(i.source_file,x.category,'') category,COALESCE(v.name,'') vendor_name,
                COALESCE(i.invoice_number,x.reference,'') reference,
                COALESCE(i.expense_account,x.expense_account,'') expense_account,
                COALESCE(i.department_id,x.department_id) department_id,
                COALESCE(i.project_id,x.project_id) project_id,
                COALESCE(x.description,i.source_file,'') description,
                COALESCE(d.code,'') department_code,COALESCE(d.name,'') department_name,
                COALESCE(p.code,'') project_code,COALESCE(p.name,'') project_name,
                COALESCE(b.name,'') branch_name,
                (SELECT COUNT(DISTINCT COALESCE(j.department_id,0)||':'||COALESCE(j.project_id,0))
                 FROM journal_entries o JOIN journal_lines j ON j.entry_id=o.id
                 JOIN accounts a ON a.id=j.account_id
                 WHERE o.source_id=e.source_id AND a.type='expense'
                 AND o.source_type=CASE WHEN i.id IS NOT NULL THEN 'invoice' ELSE 'expense' END
                 AND (COALESCE(j.department_id,0)<>COALESCE(i.department_id,x.department_id,0)
                      OR COALESCE(j.project_id,0)<>COALESCE(i.project_id,x.project_id,0))) conflicts
                FROM journal_entries report JOIN journal_entries e
                  ON e.id=CASE WHEN report.source_type='vat_reclass' THEN report.id ELSE report.reversal_of END
                LEFT JOIN invoices i ON i.id=e.source_id AND e.entry_number='VATND-INV-'||i.id
                LEFT JOIN expenses x ON x.id=e.source_id AND e.entry_number='VATND-EXP-'||x.id
                LEFT JOIN parties v ON v.id=i.party_id
                LEFT JOIN departments d ON d.id=COALESCE(i.department_id,x.department_id)
                LEFT JOIN projects p ON p.id=COALESCE(i.project_id,x.project_id)
                LEFT JOIN branches b ON b.id=i.branch_id
                WHERE report.id IN ({','.join('?' for _ in batch)})
                  AND e.source_type='vat_reclass' AND e.posting_status='posted' AND report.posting_status='posted'
                  AND (i.id IS NOT NULL OR x.id IS NOT NULL)""", batch)
            evidence.update({r['id']: dict(r) for r in records})
    result = []
    for original in rows:
        row = dict(original)
        source = evidence.get(row.get('entry_id'))
        if source and row.get('account_type') == 'expense':
            row['vat_component'] = True
            row['vat_category'] = _non_deductible_category({
                'description': ' '.join(str(source.get(k) or '') for k in
                                        ('description', 'category', 'reference', 'vendor_name')) + ' ' + str(row.get('name_en') or ''),
                'expense_category': source['category']}) or 'OTHER'
            row['vat_provenance'] = 'posted_vat_reclass'
            if not source['conflicts']:
                for dimension in ('department', 'project'):
                    if not row.get(dimension + '_code') and not row.get(dimension + '_name'):
                        row[dimension + '_code'] = source[dimension + '_code']
                        row[dimension + '_name'] = source[dimension + '_name']
                if source['branch_name']:
                    row['branch_name'] = source['branch_name']
            row['vat_dimension_status'] = 'unallocated' if source['conflicts'] else 'document_header'
        result.append(row)
    return result


def cost_center_analysis(rows, currency):
    """Cross-reference department × project × branch × account × month.

    Capitalized VAT is a signed subset of posted expense, not an extra charge.
    Missing provenance is reported as unavailable rather than inferred from a rate.
    """
    from decimal import Decimal
    dimensions = ('department_code', 'department_name', 'project_code', 'project_name',
                  'branch_name', 'account_code', 'month')
    cross = {}
    summaries = {}
    for row in rows:
        kind = row.get('account_type') or row.get('type')
        if kind not in ('expense', 'income'):
            continue
        value = (row.get('signed') or {}).get(currency)
        if value is None:
            raise ValueError(f'Missing {currency} ledger equivalent for cost-center analysis')
        value = Decimal(str(value))
        if not value.is_finite():
            raise ValueError('Non-finite analytic ledger amount')
        code = str(row.get('code') or row.get('account_code') or '')
        keys = (str(row.get('department_code') or ''), str(row.get('department_name') or 'Unassigned'),
                str(row.get('project_code') or ''), str(row.get('project_name') or 'Unassigned'),
                str(row.get('branch_name') or 'Unassigned'), code,
                _month(row.get('iso_date') or row.get('entry_date')))
        key = keys
        entry = cross.setdefault(key, dict(zip(dimensions, keys), currency=currency,
            revenue=Decimal(0), expense_cost=Decimal(0), capitalized_vat=Decimal(0),
            vat_by_category={c: Decimal(0) for c in ('EDL', 'TEL', 'CELL', 'FUEL', 'OTHER')},
            unverified_expense_lines=0, ledger_line_ids=[]))
        if kind == 'income':
            entry['revenue'] -= value
        else:
            entry['expense_cost'] += value
            if row.get('vat_component') is True and row.get('vat_provenance') == 'posted_vat_reclass':
                entry['capitalized_vat'] += value
                entry['vat_by_category'][row.get('vat_category') if row.get('vat_category') in entry['vat_by_category'] else 'OTHER'] += value
            else:
                entry['unverified_expense_lines'] += 1
        if row.get('id') is not None:
            entry['ledger_line_ids'].append(row['id'])
    for key, entry in sorted(cross.items()):
        center = summaries.setdefault(key[:2], dict(department_code=key[0], department_name=key[1],
            currency=currency, revenue=Decimal(0), expense_cost=Decimal(0), capitalized_vat=Decimal(0),
            vat_by_category={c: Decimal(0) for c in ('EDL', 'TEL', 'CELL', 'FUEL', 'OTHER')},
            unverified_expense_lines=0))
        for field in ('revenue', 'expense_cost', 'capitalized_vat', 'unverified_expense_lines'):
            center[field] += entry[field]
        for category, amount in entry['vat_by_category'].items():
            center['vat_by_category'][category] += amount
    for entry in [*cross.values(), *summaries.values()]:
        entry['expense_excluding_identified_vat'] = entry['expense_cost'] - entry['capitalized_vat']
        entry['net_contribution'] = entry['revenue'] - entry['expense_cost']
        entry['vat_evidence_status'] = 'partial' if entry['unverified_expense_lines'] else 'identified'
        for field, value in list(entry.items()):
            if isinstance(value, Decimal):
                entry[field] = float(value.quantize(Decimal('0.01')))
        entry['vat_by_category'] = {k: float(v.quantize(Decimal('0.01'))) for k, v in entry['vat_by_category'].items()}
    return {'dimensions': list(dimensions), 'summaries': list(summaries.values()),
            'cross_references': [cross[k] for k in sorted(cross)],
            'vat_note': 'VAT components identify posted reclassifications only; no rates or allocations are inferred. Other embedded VAT remains unavailable.'}


def analyze_rows(rows, start_date=None, end_date=None, currency="USD", language="en", budgets=None):
    """Analyze rows from `ledger_reports._load_lines`; all amounts use the selected currency."""
    currency = str(currency or "USD").upper()
    lines = [row for row in _periods(rows, start_date, end_date)
             if row.get("posting_status", "posted") == "posted"]
    category = defaultdict(lambda: {"revenue": 0.0, "cost": 0.0, "expense": 0.0})
    project = defaultdict(lambda: {"revenue": 0.0, "cost": 0.0, "expense": 0.0})
    vendor = defaultdict(lambda: {"revenue": 0.0, "cost": 0.0, "expense": 0.0})
    monthly = defaultdict(lambda: {"revenue": 0.0, "expense": 0.0})
    vendors_by_month = defaultdict(float)
    actual_by_account = defaultdict(float)
    account_types = {}
    total_revenue = total_expense = total_cost = 0.0

    for row in lines:
        account_type = str(row.get("account_type") or row.get("type") or "").lower()
        signed = row.get("signed") or {}
        amount = float(signed.get(currency) or 0) if isinstance(signed, dict) else float(row.get("amount") or 0)
        code = "".join(ch for ch in str(row.get("code") or row.get("account_code") or "") if ch.isdigit())
        if account_type == "income":
            value = -amount
            bucket = "revenue"
            total_revenue += value
        elif account_type == "expense":
            value = amount
            bucket = "cost" if code.startswith(("60", "61")) else "expense"
            if bucket == "cost":
                total_cost += value
            else:
                total_expense += value
        else:
            continue
        actual_by_account[code] += value
        account_types[code] = account_type

        category_name = f'{code[:2] or "Other"} - {row.get("name_en") or row.get("account_name") or "Unclassified"}'
        for group, name in ((category, category_name),
                            (project, str(row.get("project_name") or row.get("project_code") or "Unassigned project")),
                            (vendor, str(row.get("party_name") or "Unassigned vendor"))):
            group[name][bucket] += value
        month = _month(row.get("iso_date") or row.get("entry_date"))
        if month:
            monthly[month]["revenue" if bucket == "revenue" else "expense"] += value
            if bucket != "revenue":
                vendors_by_month[(month, str(row.get("party_name") or "Unassigned vendor"))] += value

    overall_expense = total_cost + total_expense
    categories = _dimension_summary(category, overall_expense)
    projects = _dimension_summary(project, overall_expense)
    vendors = _dimension_summary(vendor, overall_expense)
    month_keys = sorted(monthly)
    top_expenses = sorted(categories, key=lambda item: item["cost_of_sales"] + item["expenses"], reverse=True)[:10]
    spikes = []
    for month in month_keys:
        year, number = map(int, month.split("-"))
        prior_month = f"{year - (number == 1):04d}-{12 if number == 1 else number - 1:02d}"
        prior = monthly.get(prior_month, {}).get("expense", 0.0)
        current = monthly[month]["expense"]
        if prior > 0 and current >= prior * 1.4:
            spikes.append({"month": month, "previous_expense": round(prior, 2), "expense": round(current, 2),
                           "increase_percent": round((current / prior - 1) * 100, 1)})

    vendor_totals = defaultdict(float)
    for (_month_key, vendor_name), amount in vendors_by_month.items():
        vendor_totals[vendor_name] += amount
    named_vendor_totals = {name: amount for name, amount in vendor_totals.items() if name != "Unassigned vendor"}
    largest_vendor = max(named_vendor_totals.items(), key=lambda item: item[1], default=("", 0.0))
    vendor_share = largest_vendor[1] / overall_expense * 100 if overall_expense else 0.0

    budget_rows = []
    for code, planned_value in (budgets or {}).items():
        planned = float(planned_value or 0)
        actual = actual_by_account.get(str(code), 0.0)
        if planned > 0:
            kind = account_types.get(str(code), "expense")
            variance = actual - planned
            adverse = variance < 0 if kind == "income" else variance > 0
            budget_rows.append({"category": str(code), "type": kind, "budget": round(planned, 2), "actual": round(actual, 2),
                                "variance": round(variance, 2), "adverse": adverse,
                                "variance_percent": round(variance / planned * 100, 1)})

    insights = []
    arabic = str(language).lower().startswith("ar")
    if spikes:
        spike = max(spikes, key=lambda item: item["increase_percent"])
        insights.append({"kind": "unusual_spend", "severity": "warning", "month": spike["month"],
                         "text": (f"إنفاق الفئة ارتفع {spike['increase_percent']:.0f}% في {spike['month']} مقارنة بالشهر السابق؛ راجع الفواتير والموردين."
                                  if arabic else f"Expense spending rose {spike['increase_percent']:.0f}% in {spike['month']} versus the prior month; review invoices and vendors."),
                         "details": spike})
    if vendor_share >= 80:
        insights.append({"kind": "vendor_dependency", "severity": "warning", "vendor": largest_vendor[0],
                         "text": (f"يعتمد الإنفاق بنسبة {vendor_share:.0f}% على المورد {largest_vendor[0]}؛ قيّم مخاطر الاعتماد."
                                  if arabic else f"{vendor_share:.0f}% of recorded expenses are with {largest_vendor[0]}; review supplier concentration risk."),
                         "details": {"share_percent": round(vendor_share, 1), "vendor": largest_vendor[0]}})
    if projects:
        valid_projects = [item for item in projects if item["margin_available"] and item["name"] != "Unassigned project"]
        if valid_projects:
            lowest = min(valid_projects, key=lambda item: item["net_margin_percent"])
            insights.append({"kind": "project_margin", "severity": "info", "project": lowest["name"],
                             "text": (f"هامش صافي المشروع {lowest['name']} هو {lowest['net_margin_percent']:.1f}%. راجع تكاليف المشروع."
                                      if arabic else f"Project {lowest['name']} has a {lowest['net_margin_percent']:.1f}% net margin; review project costs."),
                             "details": lowest})
    seasonal = defaultdict(list)
    for month, values in monthly.items():
        seasonal[int(month[5:7])].append(values["expense"])
    seasonal_patterns = [{"month_number": month, "average_expense": round(sum(values) / len(values), 2),
                          "periods": len(values)} for month, values in sorted(seasonal.items())]

    always_over = [row for row in budget_rows if row["adverse"]]
    for item in always_over:
        insights.append({"kind": "budget_overrun", "severity": "warning", "category": item["category"],
                         "text": (f"الفئة {item['category']} تتجاوز الموازنة بنسبة {item['variance_percent']:.1f}%."
                                  if arabic else f"Category {item['category']} is over budget by {item['variance_percent']:.1f}%.") ,
                         "details": item})

    return {"currency": currency, "from_date": start_date, "to_date": end_date,
            "totals": {"revenue": round(total_revenue, 2), "cost_of_sales": round(total_cost, 2),
                       "expenses": round(total_expense, 2), "gross_profit": round(total_revenue - total_cost, 2),
                       "net_profit": round(total_revenue - total_cost - total_expense, 2)},
            "cost_centers": cost_center_analysis(lines, currency),
            "profitability": {"projects": projects, "vendors": vendors, "categories": categories},
            "expenses": {"top_10": top_expenses, "unusual_spending": spikes,
                         "vendor_dependency": {"vendor": largest_vendor[0], "share_percent": round(vendor_share, 1),
                                               "risk": vendor_share >= 80},
                         "monthly_seasonality": [{"month": month, **{k: round(v, 2) for k, v in monthly[month].items()}}
                                                 for month in month_keys],
                         "seasonal_patterns": seasonal_patterns},
            "cashflow": {"quarters": [], "monthly": []}, "budgets": budget_rows,
            "insights": insights}


def build_study(db, from_date, to_date, currency="USD", language="en",
                sources=None, opening_db=None):
    """Build a study from posted ledger records, retaining converted-currency semantics."""
    from ledger_reports import _load_lines
    from database import iso_date
    currency = str(currency or "USD").upper()
    start = iso_date(from_date)
    end = iso_date(to_date)
    source_ranges = sources or [(db, start, end)]
    rows = []
    budgets = defaultdict(float)
    for source_db, source_start, source_end in source_ranges:
        source_start, source_end = iso_date(source_start), iso_date(source_end)
        options = {"first_column": currency, "second_column": "none", "posting_status": "posted",
                   "without_closing": True, "exclude_closing": True, "without_opening": True,
                   "date_from": source_start, "date_to": source_end}
        rows.extend(_with_vat_evidence(source_db, _load_lines(source_db, options)))
        if currency:
            for code, amount in source_db.budget_for_period(currency, source_start, source_end).items():
                budgets[code] += float(amount)
    study = analyze_rows(rows, start, end, currency, language, budgets)
    study["opening_balance"] = None
    study["warnings"] = []
    prior_year = int(start[:4]) - 1
    if opening_db is None:
        study["warnings"].append("Opening balance unavailable - no prior year")
        study["comparative_prior_year"] = {
            "year": prior_year,
            "available": False,
            "status": "unavailable",
        }
        if prior_year == 2025:
            study["comparative_2025"] = {
                "available": False,
                "status": "unavailable",
                "reason": "Historical data for FY 2025 unavailable - cannot compare",
            }
    pnl_totals = {"revenue": 0.0, "cost_of_sales": 0.0, "expenses": 0.0}
    for source_db, source_start, source_end in source_ranges:
        pnl_rows = (source_db.profit_and_loss_converted(source_start, source_end, currency)
                    if currency else source_db.profit_and_loss(source_start, source_end))
        for row in pnl_rows:
            amount = float(row.get("amount") or 0)
            if row.get("type") == "income":
                pnl_totals["revenue"] += amount
            elif row.get("type") == "expense":
                code = "".join(ch for ch in str(row.get("code") or "") if ch.isdigit())
                pnl_totals["cost_of_sales" if code.startswith(("60", "61")) else "expenses"] += amount
    check = {}
    matches = True
    for key, pnl_value in pnl_totals.items():
        analytic_value = study["totals"][key]
        difference = round(analytic_value - pnl_value, 2)
        check[key] = {"analytic": round(analytic_value, 2), "pnl": round(pnl_value, 2),
                      "difference": difference}
        matches = matches and abs(difference) <= 0.01
    study["pnl_check"] = {"matches": matches, "totals": check}
    try:
        monthly_by_key = {}
        for source_db, source_start, source_end in source_ranges:
            for row in source_db.cash_flow_monthly(source_start, source_end, currency, bool(currency)):
                key = (row["month"], row["currency"], row["source"])
                item = monthly_by_key.setdefault(key, {**row, "inflow": 0.0, "outflow": 0.0})
                item["inflow"] += float(row.get("inflow") or 0)
                item["outflow"] += float(row.get("outflow") or 0)
        monthly = []
        for row in monthly_by_key.values():
            row["inflow"] = round(row["inflow"], 2); row["outflow"] = round(row["outflow"], 2)
            row["net"] = round(row["inflow"] - row["outflow"], 2); monthly.append(row)
        opening = defaultdict(float)
        if opening_db is not None:
            previous_day = (datetime.fromisoformat(start).date() - timedelta(days=1)).isoformat()
            balances = (opening_db.balance_sheet_converted(previous_day, currency) if currency
                        else opening_db.balance_sheet(previous_day))
            for row in balances:
                if str(row.get("code") or "").startswith(("51", "53")):
                    opening[str(row.get("currency") or currency or "USD").upper()] += float(row.get("balance") or 0)
            study["opening_balance"] = dict(opening)
        from financial_projection import get_quarterly_cashflow
        study["cashflow"]["monthly"] = monthly
        study["cashflow"]["quarters"] = get_quarterly_cashflow(monthly, opening, 0, start, end)
        if opening_db is None:
            for quarter in study["cashflow"]["quarters"]:
                quarter["opening"] = None
                quarter["closing"] = None
    except (AttributeError, ValueError):
        pass
    return study


def save_insights(db, insights, from_date, to_date, currency="USD", language="en"):
    """Persist generated recommendations as reviewable records; never post accounting entries."""
    with db.connect() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS analytic_insights (
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, from_date TEXT, to_date TEXT,
            currency TEXT NOT NULL, language TEXT NOT NULL, kind TEXT NOT NULL,
            severity TEXT NOT NULL, message TEXT NOT NULL, details_json TEXT NOT NULL)""")
        for insight in insights:
            connection.execute("""INSERT INTO analytic_insights
                (created_at,from_date,to_date,currency,language,kind,severity,message,details_json)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (datetime.now().isoformat(timespec="seconds"), from_date, to_date, str(currency).upper(), language,
                 insight["kind"], insight["severity"], insight["text"],
                 json.dumps(insight.get("details") or {}, ensure_ascii=False)))


def list_saved_insights(db, limit=100):
    limit = max(1, min(500, int(limit)))
    with db.connect() as connection:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='analytic_insights'").fetchone()
        if not exists:
            return []
        return [dict(row) for row in connection.execute(
            "SELECT * FROM analytic_insights ORDER BY id DESC LIMIT ?", (limit,))]
