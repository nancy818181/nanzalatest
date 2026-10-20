"""Allowlisted posted-sales and ordered ledger layouts with per-user templates.

Filters never contain SQL. Warehouse uses EXISTS so multiple stock movements
cannot multiply invoice amounts. Only actual linked lines match a warehouse.
"""

import json
from decimal import Decimal
from database_common import iso_date

FILTERS = {"date_from", "date_to", "customer", "product", "warehouse", "currency", "definition"}
HEADERS = [
    "Date",
    "Invoice",
    "Customer",
    "Product",
    "Description",
    "Currency",
    "Quantity",
    "Subtotal",
    "VAT",
    "Total",
]


def validate_filters(filters):
    if not isinstance(filters, dict) or set(filters) - FILTERS:
        raise ValueError("Unsupported report filters")
    result = {k: str(v).strip() for k, v in filters.items() if v not in (None, "")}
    for field in ("date_from", "date_to"):
        if not result.get(field):
            raise ValueError("Choose a date range")
        result[field] = iso_date(result[field])
    if result["date_from"] > result["date_to"]:
        raise ValueError("Date From cannot be after Date To")
    if result["date_from"][:4] != result["date_to"][:4]:
        raise ValueError("Choose a range within the selected fiscal year")
    for field in ("customer", "warehouse"):
        if field in result and (not result[field].isdigit() or int(result[field]) <= 0):
            raise ValueError(f"Invalid {field}")
    if 'definition' in result:
        if len(result['definition']) > 32000 or set(result) - {'date_from', 'date_to', 'definition'}:
            raise ValueError('Ledger layouts cannot contain sales-only filters')
        try:
            definition = validate_definition(json.loads(result['definition']))
        except (TypeError, json.JSONDecodeError):
            raise ValueError('Invalid ledger report definition') from None
        if any(result[k] != definition[k] for k in ('date_from', 'date_to')):
            raise ValueError('Layout dates must match report filters')
        result['definition'] = json.dumps(definition, ensure_ascii=False)
    if any(len(v) > 120 for k, v in result.items() if k != 'definition'):
        raise ValueError("Filter value is too long")
    return result


def build_report(database, filters, *, limit=500, offset=0):
    filters = validate_filters(filters)
    if 'definition' in filters:
        return build_ledger_report(database, json.loads(filters['definition']), limit=limit, offset=offset)
    limit, offset = int(limit), int(offset)
    if not 1 <= limit <= 5000 or offset < 0:
        raise ValueError("Invalid page size")
    day = "CASE WHEN i.invoice_date GLOB '??-??-????' THEN substr(i.invoice_date,7,4)||'-'||substr(i.invoice_date,4,2)||'-'||substr(i.invoice_date,1,2) ELSE i.invoice_date END"
    conditions = ["i.status='posted'", "i.kind='sale'", f"{day}>=?", f"{day}<=?"]
    params = [filters["date_from"], filters["date_to"]]
    for field, sql in (
        ("customer", "i.party_id=?"),
        ("product", "l.item_code=?"),
        ("currency", "i.currency=?"),
    ):
        if filters.get(field):
            conditions.append(sql)
            params.append(filters[field])
    if filters.get("warehouse"):
        conditions.append(
            "EXISTS (SELECT 1 FROM stock_movements m WHERE m.invoice_item_id=l.id AND m.warehouse_id=?)"
        )
        params.append(int(filters["warehouse"]))
    with database.connect() as connection:
        records = [
            dict(r)
            for r in connection.execute(
                f"""SELECT {day} day,i.id invoice_id,i.invoice_number,
            p.name customer,l.item_code,l.description,i.currency,l.quantity,l.subtotal,l.vat,l.total,
            CASE WHEN i.doc_subtype='credit_note' THEN -1 ELSE 1 END sign
            FROM invoices i JOIN invoice_items l ON l.invoice_id=i.id LEFT JOIN parties p ON p.id=i.party_id
            WHERE {' AND '.join(conditions)} ORDER BY {day},i.id,l.id LIMIT ? OFFSET ?""",
                [*params, limit + 1, offset],
            )
        ]
    more = len(records) > limit
    records = records[:limit]
    rows, totals = [], {}
    for r in records:
        amounts = [Decimal(str(r[k] or 0)) * r["sign"] for k in ("quantity", "subtotal", "vat", "total")]
        rows.append(
            [
                r["day"],
                r["invoice_number"],
                r["customer"] or "",
                r["item_code"] or "",
                r["description"],
                r["currency"],
                *amounts,
            ]
        )
        totals[r["currency"]] = totals.get(r["currency"], Decimal(0)) + amounts[-1]
    return {
        "title": "Custom posted sales / المبيعات المرحّلة",
        "headers": HEADERS,
        "rows": rows,
        "totals": totals,
        "has_more": more,
        "offset": offset,
        "next_offset": offset + len(rows),
        "filters": filters,
        "note": "Line totals, native currencies, net of credit notes. Header-only invoices without lines are excluded. Totals cover this page only.",
    }


def migrate(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS custom_reports (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
        definition TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
        UNIQUE(user_id,name))""")


def save_template(database, user_id, name, filters):
    name = str(name or "").strip()
    if not name or len(name) > 100:
        raise ValueError("Enter a template name of at most 100 characters")
    definition = json.dumps(validate_filters(filters), ensure_ascii=False, sort_keys=True)
    with database.connect() as connection:
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        migrate(connection)
        connection.execute(
            """INSERT INTO custom_reports(user_id,name,definition) VALUES(?,?,?)
            ON CONFLICT(user_id,name) DO UPDATE SET definition=excluded.definition,revision=custom_reports.revision+1""",
            (int(user_id), name, definition),
        )
    return {"name": name, "filters": json.loads(definition)}


def list_templates(database, user_id):
    # GET stays read-only, including on an untouched company.
    with database.connect() as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='custom_reports'"
        ).fetchone():
            return []
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "revision": r["revision"],
                "filters": json.loads(r["definition"]),
            }
            for r in connection.execute(
                "SELECT * FROM custom_reports WHERE user_id=? ORDER BY name", (int(user_id),)
            )
        ]


def export_report(database, filters, *, max_rows=50000):
    """Read a consistent snapshot; refuse oversized exports instead of silently truncating."""
    validated = validate_filters(filters)
    if 'definition' in validated:
        pages, records, offset = [], [], 0
        with database.connect() as connection:
            if not connection.in_transaction:
                connection.execute('BEGIN')
            while True:
                page = build_report(database, validated, limit=5000, offset=offset)
                pages.extend(page['rows'])
                records.extend(page['records'])
                if len(pages) > max_rows:
                    raise ValueError('Export exceeds its row limit; narrow the filters')
                if not page['has_more']:
                    break
                offset = page['next_offset']
        page.update(rows=pages, records=records, offset=0, has_more=False, next_offset=len(pages))
        return page
    rows = []
    with database.connect() as connection:
        if not connection.in_transaction:
            connection.execute("BEGIN")
        offset = 0
        while True:
            page = build_report(database, filters, limit=5000, offset=offset)
            rows.extend(page["rows"])
            if len(rows) > max_rows:
                raise ValueError("Export exceeds 50,000 lines; narrow the filters")
            if not page["has_more"]:
                break
            offset = page["next_offset"]
    totals = {}
    for row in rows:
        totals[row[5]] = totals.get(row[5], Decimal(0)) + row[-1]
    page.update(
        rows=rows,
        totals=totals,
        offset=0,
        has_more=False,
        note="Complete filtered line report; native currencies, net of credit notes. Header-only invoices excluded.",
    )
    return page

LEDGER_DIMENSIONS = ('account', 'department', 'project', 'branch', 'month')
LEDGER_MEASURES = ('debit', 'credit', 'balance', 'amount')


def validate_definition(definition):
    """Versioned ordered layout; drag/drop changes lists, never SQL or ledger rows."""
    import re
    allowed = {'version', 'kind', 'date_from', 'date_to', 'group_by', 'columns', 'currencies', 'account_codes'}
    if not isinstance(definition, dict) or set(definition) - allowed:
        raise ValueError('Unsupported ledger report definition')
    if definition.get('version') != 1 or definition.get('kind') not in ('pnl', 'balance'):
        raise ValueError('Choose a version 1 P&L or balance layout')
    dates = validate_filters({k: definition.get(k) for k in ('date_from', 'date_to')})
    result = dict(definition, **dates)
    for field, choices, default in (
        ('group_by', LEDGER_DIMENSIONS, ['account']),
        ('columns', LEDGER_MEASURES, ['amount']),
    ):
        values = definition.get(field, default)
        if not isinstance(values, list) or not values or any(v not in choices for v in values) or len(set(values)) != len(values):
            raise ValueError(f'Invalid ordered {field}')
        result[field] = list(values)
    if 'account' not in result['group_by']:
        raise ValueError('Account must remain a ledger grouping dimension')
    currencies = definition.get('currencies', ['native'])
    if (not isinstance(currencies, list) or not 1 <= len(currencies) <= 5
            or any(not isinstance(c, str) or not re.fullmatch(r'[A-Z]{3}|native', c) for c in currencies)
            or len(set(currencies)) != len(currencies) or 'native' in currencies and len(currencies) != 1):
        raise ValueError('Choose native currencies or up to five explicit reporting currencies')
    result['currencies'] = list(currencies)
    codes = definition.get('account_codes', [])
    if not isinstance(codes, list) or len(codes) > 500 or any(not isinstance(c, str) or not re.fullmatch(r'[0-9]{9}', c) for c in codes):
        raise ValueError('Account filters must use existing exact nine-digit codes')
    result['account_codes'] = list(dict.fromkeys(codes))
    return result


def reorder_layout(definition, field, source_index, target_index):
    """Pure drag/drop operation suitable for desktop and API clients."""
    result = validate_definition(definition)
    if field not in ('group_by', 'columns', 'currencies'):
        raise ValueError('Unsupported draggable layout field')
    values = list(result[field])
    if not (isinstance(source_index, int) and isinstance(target_index, int)
            and 0 <= source_index < len(values) and 0 <= target_index < len(values)):
        raise ValueError('Invalid layout position')
    values.insert(target_index, values.pop(source_index))
    result[field] = values
    return result


def build_ledger_report(database, definition, *, limit=500, offset=0, max_lines=100000):
    """Read-only posted ledger snapshot with separate currency totals and drilldown IDs.

    P&L signs: income credit-positive, expenses debit-positive. Balance is the
    debit-minus-credit account balance as at date_to, including opening entries.
    No synthetic profit/equity line or currency exchange rate is invented.
    """
    import re
    from ledger_reports import _load_lines
    definition = validate_definition(definition)
    limit, offset = int(limit), int(offset)
    if not 1 <= limit <= 5000 or offset < 0:
        raise ValueError('Invalid page size')
    allowed_currencies = set(database.currency_codes())
    for c in definition['currencies']:
        if c != 'native' and c not in allowed_currencies:
            raise ValueError(f'Unknown reporting currency: {c}')
    selected = set(definition['account_codes'])
    if selected:
        with database.connect() as connection:
            existing = {r['code'] for r in connection.execute('SELECT code FROM accounts')}
        if selected - existing:
            raise ValueError('Account filter contains accounts absent from this company')
    grouped, totals, excluded = {}, {}, set()
    source_line_count = 0
    with database.connect() as connection:
        if not connection.in_transaction:
            connection.execute('BEGIN')
        for target in definition['currencies']:
            options = {'date_to': definition['date_to'], 'posting_status': 'posted',
                       'first_column': 'account' if target == 'native' else target, 'second_column': 'none'}
            if definition['kind'] == 'pnl':
                options.update(date_from=definition['date_from'], without_opening=True,
                               without_closing=True, exclude_closing=True)
            lines = _load_lines(database, options)
            source_line_count = max(source_line_count, len(lines))
            if len(lines) > max_lines:
                raise ValueError('Ledger report exceeds its line limit; narrow the period')
            for row in lines:
                code = str(row['code'])
                if not re.fullmatch(r'[0-9]{9}', code):
                    excluded.add(code)
                    continue
                if selected and code not in selected:
                    continue
                kind = row['account_type']
                if definition['kind'] == 'pnl':
                    if kind not in ('income', 'expense') or code[0] not in '67':
                        continue
                elif code[0] not in '12345':
                    continue
                currency = row['account_currency'] if target == 'native' else target
                value = row['signed'].get('account' if target == 'native' else target)
                if value is None or not Decimal(str(value)).is_finite():
                    raise ValueError(f'Missing or invalid {currency} ledger equivalent')
                value = Decimal(str(value))
                dimensions = {'account': code, 'department': (row.get('department_code') or '') + ' ' + (row.get('department_name') or 'Unassigned'),
                              'project': (row.get('project_code') or '') + ' ' + (row.get('project_name') or 'Unassigned'),
                              'branch': row.get('branch_name') or 'Unassigned', 'month': row['iso_date'][:7]}
                key = (currency, *(dimensions[d] for d in definition['group_by']))
                item = grouped.setdefault(key, {'dimensions': [dimensions[d] for d in definition['group_by']],
                    'currency': currency, 'debit': Decimal(0), 'credit': Decimal(0), 'balance': Decimal(0),
                    'amount': Decimal(0), 'ledger_line_ids': []})
                item['debit'] += max(value, Decimal(0))
                item['credit'] += max(-value, Decimal(0))
                item['balance'] += value
                item['amount'] += -value if definition['kind'] == 'pnl' and kind == 'income' else value
                item['ledger_line_ids'].append(row['id'])
                summary = totals.setdefault(currency, {'debit': Decimal(0), 'credit': Decimal(0), 'revenue': Decimal(0), 'expense': Decimal(0)})
                summary['debit'] += max(value, Decimal(0))
                summary['credit'] += max(-value, Decimal(0))
                if kind == 'income': summary['revenue'] -= value
                if kind == 'expense': summary['expense'] += value
    records = [grouped[k] for k in sorted(grouped)]
    page = records[offset:offset + limit]
    for summary in totals.values():
        summary['net_profit'] = summary['revenue'] - summary['expense']
        summary['balance'] = summary['debit'] - summary['credit']
    definition_filters = {'date_from': definition['date_from'], 'date_to': definition['date_to'],
                          'definition': json.dumps(definition, ensure_ascii=False)}
    return {'title': 'Ledger P&L / أرباح وخسائر' if definition['kind'] == 'pnl' else 'Account balances / أرصدة الحسابات',
            'headers': [*definition['group_by'], 'Currency', *definition['columns']],
            'rows': [[*r['dimensions'], r['currency'], *[r[c] for c in definition['columns']]] for r in page],
            'records': page, 'totals': {c: s['net_profit'] if definition['kind'] == 'pnl' else s['balance'] for c, s in totals.items()},
            'currency_summaries': totals, 'totals_scope': 'complete_filtered_ledger', 'definition': definition,
            'has_more': offset + len(page) < len(records), 'offset': offset, 'next_offset': offset + len(page),
            'filters': definition_filters, 'source_line_count': source_line_count,
            'excluded_legacy_account_codes': sorted(excluded),
            'note': 'Posted nine-digit ledger accounts only; currencies remain separate. Balance views include opening entries; no synthetic current-year profit is added.'
                    + (' Excluded legacy accounts: ' + ', '.join(sorted(excluded)) if excluded else '')}
