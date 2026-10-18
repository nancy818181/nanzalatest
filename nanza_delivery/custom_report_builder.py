"""Allowlisted, parameterized posted-sales reports and per-user company templates.

Filters never contain SQL. Warehouse uses EXISTS so multiple stock movements
cannot multiply invoice amounts. Only actual linked lines match a warehouse.
"""

import json
from decimal import Decimal
from database_common import iso_date

FILTERS = {"date_from", "date_to", "customer", "product", "warehouse", "currency"}
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
    if any(len(v) > 120 for v in result.values()):
        raise ValueError("Filter value is too long")
    return result


def build_report(database, filters, *, limit=500, offset=0):
    filters = validate_filters(filters)
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
