"""Parameterised ledger queries for supported accountant-assistant filters."""
from __future__ import annotations

from datetime import date, timedelta

from nanza.ai_accountant.nlu import ACCOUNT_KEYWORDS, parse_question
from nanza.reports import cash_forecast_13_week


SUPPORTED_FILTERS = ("account", "vendor", "project", "period")
PAYROLL_KEYWORDS = ("salary", "salaries", "payroll", "wage", "wages", "staff",
                    "personnel", "salaire", "salaires", "رواتب", "راتب", "أجور")


def _table_names(connection, table):
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _matching_account_ids(connection, category):
    aliases = ACCOUNT_KEYWORDS.get(category)
    if not aliases:
        raise ValueError(f"Cannot filter by account {category!r}")
    account_columns = _table_names(connection, "accounts")
    name_columns = [column for column in ("name_en", "name_ar", "name_fr")
                    if column in account_columns]
    if not name_columns:
        raise ValueError("Account names are unavailable for account filtering")
    terms = [f"LOWER(COALESCE(a.{column},'')) LIKE ?" for column in name_columns for _ in aliases]
    parameters = [f"%{word.casefold()}%" for _column in name_columns for word in aliases]
    posting_clause = ("AND NOT EXISTS (SELECT 1 FROM accounts child WHERE child.parent_id=a.id)"
                      if "parent_id" in account_columns else "")
    rows = connection.execute(
        "SELECT a.id FROM accounts a WHERE a.type='expense' AND COALESCE(a.active,1)=1 "
        f"{posting_clause} AND ({' OR '.join(terms)})", parameters).fetchall()
    return [int(row["id"]) for row in rows]


def _match_named_entity(connection, table, candidate):
    if table not in ("parties", "projects"):
        raise ValueError("Unsupported named-entity filter")
    name_column = "name"
    if name_column not in _table_names(connection, table):
        return None
    rows = connection.execute(
        f"SELECT id,name FROM {table} WHERE LOWER(name)=? OR LOWER(name) LIKE ? ORDER BY LENGTH(name),id LIMIT 1",
        (candidate.casefold(), f"%{candidate.casefold()}%")).fetchone()
    return dict(rows) if rows else None


def query_expenses(database, question, user=None, today=None):
    parsed = parse_question(question, today=today)
    if parsed["intent"] != "expense_report":
        supported = "expense report"
        return {"ok": False, "message": f"That request is not supported yet. Supported: {supported}.",
                "intent": parsed["intent"], "filters_applied": [], "rows": [], "totals": {}}
    entities = parsed["entities"]
    account_filter = entities.get("account")
    if isinstance(entities.get("period"), list):
        return {"ok": False, "message": "Choose one reporting period per question.",
                "intent": parsed["intent"], "filters_applied": [], "rows": [], "totals": {}}
    if isinstance(account_filter, list):
        return {"ok": False, "message": "Choose one account category per question.",
                "intent": parsed["intent"], "filters_applied": [], "rows": [], "totals": {}}
    if account_filter == "salary" and user and (
            user["role"] == "viewer" or not database.user_can(user, "payroll")):
        return {"ok": False, "message": "You do not have permission to view payroll accounts.",
                "intent": parsed["intent"], "filters_applied": [], "rows": [], "totals": {}}

    conditions = ["a.type='expense'", "COALESCE(a.active,1)=1", "e.posting_status='posted'",
                  "(e.source_type!='invoice' OR i.status IN ('posted','cancelled','void') OR i.status IS NULL)"]
    parameters = []
    filters = []
    with database.connect() as connection:
        if user and (user["role"] == "viewer" or not database.user_can(user, "payroll")):
            conditions.append("e.source_type!='payroll'")
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM salary_payments sp WHERE sp.entry_id=e.id)")
            account_columns = _table_names(connection, "accounts")
            name_columns = [column for column in ("name_en", "name_ar", "name_fr")
                            if column in account_columns]
            if name_columns:
                payroll_terms = [f"LOWER(COALESCE(a.{column},'')) LIKE ?"
                                 for column in name_columns for _ in PAYROLL_KEYWORDS]
                conditions.append(f"NOT ({' OR '.join(payroll_terms)})")
                parameters.extend(f"%{word.casefold()}%" for _column in name_columns
                                  for word in PAYROLL_KEYWORDS)
        account_ids = None
        if account_filter:
            account_ids = _matching_account_ids(connection, account_filter)
            if not account_ids:
                return {"ok": False, "message": f"No active posting expense account matched {account_filter!r}.",
                        "intent": parsed["intent"], "filters_applied": [], "rows": [], "totals": {}}
            conditions.append(f"a.id IN ({','.join('?' for _ in account_ids)})")
            parameters.extend(account_ids)
            filters.append(f"account={account_filter}")
        if entities.get("vendor"):
            vendor = _match_named_entity(connection, "parties", entities["vendor"])
            if not vendor:
                return {"ok": False, "message": f"Cannot filter by vendor {entities['vendor']!r}; supported filters: {', '.join(SUPPORTED_FILTERS)}.",
                        "intent": parsed["intent"], "filters_applied": [], "rows": [], "totals": {}}
            conditions.append("j.party_id=?")
            parameters.append(vendor["id"])
            filters.append(f"vendor={vendor['name']}")
        if entities.get("project"):
            project = _match_named_entity(connection, "projects", entities["project"])
            if not project:
                return {"ok": False, "message": f"Cannot filter by project {entities['project']!r}; supported filters: {', '.join(SUPPORTED_FILTERS)}.",
                        "intent": parsed["intent"], "filters_applied": [], "rows": [], "totals": {}}
            conditions.append("j.project_id=?")
            parameters.append(project["id"])
            filters.append(f"project={project['name']}")
        start = entities.get("date_from")
        end = entities.get("date_to")
        normalized_date = ("CASE WHEN e.entry_date GLOB '??-??-????' "
                           "THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2) "
                           "ELSE e.entry_date END")
        if start:
            conditions.append(f"{normalized_date}>=?")
            parameters.append(start)
            filters.append(f"from={start}")
        if end:
            conditions.append(f"{normalized_date}<=?")
            parameters.append(end)
            filters.append(f"to={end}")
        if not account_filter:
            filters.append("account=all active expense posting accounts")
        rows = [dict(row) for row in connection.execute(
            f"""SELECT e.id journal_id,e.entry_number,e.entry_date,e.description,
                a.code account_code,a.name_en account_name,COALESCE(p.name,'') vendor,
                COALESCE(pr.name,'') project,COALESCE(j.line_currency,e.currency) currency,
                CASE WHEN j.line_currency IS NOT NULL AND j.amount IS NOT NULL
                     THEN CAST(j.amount AS REAL) * CASE WHEN CAST(j.debit AS REAL)-CAST(j.credit AS REAL)<0 THEN -1 ELSE 1 END
                     ELSE CAST(j.debit AS REAL)-CAST(j.credit AS REAL) END amount
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id
                JOIN accounts a ON a.id=j.account_id
                LEFT JOIN invoices i ON e.source_type='invoice' AND i.id=e.source_id
                LEFT JOIN parties p ON p.id=j.party_id
                LEFT JOIN projects pr ON pr.id=j.project_id
                WHERE {' AND '.join(conditions)}
                ORDER BY {normalized_date},e.entry_number,a.code""", parameters)]
    for row in rows:
        row["entry_date"] = str(row["entry_date"] or "")[:10]
        row["amount"] = round(float(row["amount"] or 0), 2)
    totals = {}
    for row in rows:
        currency = str(row.get("currency") or "USD").upper()
        totals[currency] = round(totals.get(currency, 0.0) + row["amount"], 2)
    return {"ok": True, "intent": parsed["intent"], "filters_applied": filters,
            "period": {"from": start, "to": end}, "rows": rows, "totals": totals}


def _aging(database, kind, today=None, currency=None):
    reference_day = today or date.today()
    if not isinstance(reference_day, date):
        reference_day = date.fromisoformat(str(reference_day)[:10])
    as_of = reference_day.isoformat()
    items = database.aging_report(as_of, kind, currency)
    grouped = {}
    for item in items:
        days = int(item.get("days_overdue") or 0)
        bucket = "current" if days == 0 else "1_30" if days <= 30 else (
            "31_60" if days <= 60 else "61_90" if days <= 90 else "over_90")
        key = (item.get("party_name") or "Unassigned", item.get("currency") or "USD")
        summary = grouped.setdefault(key, {
            "party": key[0], "currency": key[1], "current": 0.0, "1_30": 0.0,
            "31_60": 0.0, "61_90": 0.0, "over_90": 0.0, "balance": 0.0,
        })
        amount = float(item.get("outstanding") or 0)
        summary[bucket] += amount
        summary["balance"] += amount
    rows = sorted(grouped.values(), key=lambda row: (row["currency"], row["party"].casefold()))
    currency_totals = {}
    for row in rows:
        currency_totals[row["currency"]] = currency_totals.get(row["currency"], 0.0) + row["balance"]

    account_prefixes = ("41", "1100") if kind == "sale" else ("40", "20", "2000")
    account_type = "asset" if kind == "sale" else "liability"
    with database.connect() as connection:
        control_accounts = [row["id"] for row in connection.execute(
            "SELECT id,code FROM accounts WHERE type=? AND active=1 ORDER BY code",
            (account_type,)) if str(row["code"]).startswith(account_prefixes)]
        if control_accounts:
            placeholders = ",".join("?" for _ in control_accounts)
            normalized_day = ("CASE WHEN e.entry_date GLOB '??-??-????' "
                              "THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2) "
                              "ELSE e.entry_date END")
            balances = connection.execute(f"""SELECT e.currency,
                DSUM(CAST(j.debit AS REAL)-CAST(j.credit AS REAL)) balance
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id
                WHERE j.account_id IN ({placeholders}) AND e.posting_status='posted'
                  AND {normalized_day}<=?
                  AND (e.source_type!='invoice' OR EXISTS(
                    SELECT 1 FROM invoices i WHERE i.id=e.source_id
                      AND i.status IN ('posted','cancelled','void')))
                GROUP BY e.currency""", (*control_accounts, as_of)).fetchall()
        else:
            balances = []
    gl_sign = 1 if kind == "sale" else -1
    gl_by_currency = {
        row["currency"]: round(float(row["balance"] or 0) * gl_sign, 2)
        for row in balances
    }
    reconciliation = {
        code: {"aging": round(amount, 2), "gl": gl_by_currency.get(code, 0.0),
               "difference": round(amount-gl_by_currency.get(code, 0.0), 2),
               "matches": abs(amount-gl_by_currency.get(code, 0.0)) <= 0.01}
        for code, amount in currency_totals.items()
    }
    return {
        "ok": True, "intent": "ar_aging" if kind == "sale" else "ap_aging",
        "as_of": as_of, "rows": rows, "totals": currency_totals,
        "reconciliation": reconciliation,
        "filters_applied": [f"as_of={as_of}", f"kind={kind}"],
    }


def _profit_comparison(database, today=None):
    today = today or date.today()
    if not isinstance(today, date):
        today = date.fromisoformat(str(today)[:10])
    current_from = today.replace(day=1)
    prior_end = current_from - timedelta(days=1)
    prior_from = prior_end.replace(day=1)
    normalized_day = ("CASE WHEN e.entry_date GLOB '??-??-????' "
                      "THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2) "
                      "ELSE e.entry_date END")
    with database.connect() as connection:
        rows = connection.execute(f"""SELECT a.code account_code,a.name_en account_name,a.type,
            e.currency,
            SUM(CASE WHEN {normalized_day} BETWEEN ? AND ? THEN
                CASE WHEN a.type='income' THEN CAST(j.credit AS REAL)-CAST(j.debit AS REAL)
                     ELSE CAST(j.debit AS REAL)-CAST(j.credit AS REAL) END ELSE 0 END) current_amount,
            SUM(CASE WHEN {normalized_day} BETWEEN ? AND ? THEN
                CASE WHEN a.type='income' THEN CAST(j.credit AS REAL)-CAST(j.debit AS REAL)
                     ELSE CAST(j.debit AS REAL)-CAST(j.credit AS REAL) END ELSE 0 END) prior_amount
            FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id
            JOIN accounts a ON a.id=j.account_id
            WHERE e.posting_status='posted' AND a.type IN ('income','expense')
              AND (({normalized_day} BETWEEN ? AND ?) OR ({normalized_day} BETWEEN ? AND ?))
            GROUP BY a.code,a.name_en,a.type,e.currency
            ORDER BY e.currency,a.code""",
            (current_from.isoformat(), today.isoformat(), prior_from.isoformat(),
             prior_end.isoformat(), current_from.isoformat(), today.isoformat(),
             prior_from.isoformat(), prior_end.isoformat())).fetchall()
    result_rows = []
    totals = {}
    for row in rows:
        current = round(float(row["current_amount"] or 0), 2)
        prior = round(float(row["prior_amount"] or 0), 2)
        result_rows.append({
            "account_code": row["account_code"], "account_name": row["account_name"],
            "type": row["type"], "currency": row["currency"],
            "current_month": current, "previous_month": prior,
            "change": round(current-prior, 2),
        })
        currency_totals = totals.setdefault(row["currency"], {"current_month": 0.0, "previous_month": 0.0})
        currency_totals["current_month"] += current
        currency_totals["previous_month"] += prior
    return {
        "ok": True, "intent": "profit_why", "rows": result_rows,
        "totals": {currency: {key: round(value, 2) for key, value in values.items()}
                   for currency, values in totals.items()},
        "filters_applied": [f"current_month={current_from.isoformat()}..{today.isoformat()}",
                            f"previous_month={prior_from.isoformat()}..{prior_end.isoformat()}"],
    }


def query_accountant(database, question, user=None, today=None):
    parsed = parse_question(question, today=today)
    intent = parsed["intent"]
    if intent == "expense_report":
        return query_expenses(database, question, user=user, today=today)
    if intent in ("ar_aging", "ap_aging"):
        return _aging(database, "sale" if intent == "ar_aging" else "purchase",
                      today=today)
    if intent == "cash_forecast":
        forecast = cash_forecast_13_week.build(database, today=today)
        return {"ok": True, "intent": intent, "rows": forecast["rows"],
                "totals": {}, "filters_applied": ["13-week cash forecast"],
                "assumptions": forecast["assumptions"]}
    if intent == "duplicate_check":
        from nanza.ai_accountant.anomaly import find_duplicates
        rows = find_duplicates(database, today=today)
        return {"ok": True, "intent": intent, "rows": rows, "totals": {},
                "filters_applied": ["same supplier, currency and amount within 7 days"]}
    if intent == "profit_why":
        return _profit_comparison(database, today=today)
    supported = "expense reports, AR/AP aging, 13-week cash forecast, duplicate checks, and profit comparisons"
    return {"ok": False, "intent": intent, "message": f"That request is not supported yet. Supported: {supported}.",
            "filters_applied": [], "rows": [], "totals": {}}
