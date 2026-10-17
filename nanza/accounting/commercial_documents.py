"""Reviewed quotations, consignment notes and purchase order -> receipt -> draft invoice.

Commercial documents never post a journal. Only an explicit receipt moves stock;
linked purchase invoices omit stock item codes because the receipt already moved it.
"""

from __future__ import annotations
import hashlib
import json
from decimal import Decimal, InvalidOperation
from database_common import atomic, iso_date, utcnow

KINDS = {"quotation": "QUO", "consignment": "CON", "purchase_order": "PO"}
CENT = Decimal("0.01")


def migrate(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS commercial_documents (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, number TEXT NOT NULL UNIQUE, doc_date TEXT NOT NULL,
        party_id INTEGER NOT NULL REFERENCES parties(id), currency TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft', revision INTEGER NOT NULL DEFAULT 1, lines TEXT NOT NULL,
        valid_until TEXT, terms TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        created_by INTEGER, updated_at TEXT NOT NULL)""")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS commercial_events (
        id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES commercial_documents(id),
        kind TEXT NOT NULL, reference TEXT NOT NULL, request_hash TEXT NOT NULL, doc_date TEXT NOT NULL,
        rows TEXT NOT NULL, stock_document_id INTEGER, invoice_id INTEGER REFERENCES invoices(id),
        created_by INTEGER, created_at TEXT NOT NULL, UNIQUE(document_id,kind,reference))"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_commercial_invoice ON commercial_events(invoice_id)"
    )


def money(value, label, positive=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {label}") from exc
    if not result.is_finite() or result < 0 or (positive and not result):
        raise ValueError(f"Invalid {label}")
    return result


def _audit(connection, user, action, document_id, details):
    connection.execute(
        "INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
        (
            user,
            action,
            "commercial_document",
            document_id,
            json.dumps(details),
            utcnow(),
        ),
    )


def get(database, document_id):
    with database.connect() as connection:
        row = connection.execute(
            """SELECT d.*,p.name party_name FROM commercial_documents d
            JOIN parties p ON p.id=d.party_id WHERE d.id=?""",
            (int(document_id),),
        ).fetchone()
        if not row:
            raise KeyError("Commercial document not found")
        result = dict(row)
        result["lines"] = json.loads(result["lines"])
        result["events"] = [
            dict(r)
            for r in connection.execute(
                """SELECT e.*,i.invoice_number,i.status invoice_status
            FROM commercial_events e LEFT JOIN invoices i ON i.id=e.invoice_id WHERE document_id=? ORDER BY e.id""",
                (int(document_id),),
            )
        ]
    received, invoiced = {}, {}
    for event in result["events"]:
        event["rows"] = json.loads(event["rows"])
        if event["kind"] == "invoice" and event["invoice_status"] in (
            "cancelled",
            "deleted",
        ):
            continue
        target = received if event["kind"] == "receipt" else invoiced
        for line in event["rows"]:
            key = int(line["line"])
            target[key] = target.get(key, Decimal(0)) + Decimal(line["quantity"])
    for index, line in enumerate(result["lines"], 1):
        line["received"] = str(received.get(index, Decimal(0)))
        line["invoiced"] = str(invoiced.get(index, Decimal(0)))
    return result


def listing(database):
    with database.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                """SELECT d.id,d.number,d.kind,d.doc_date,d.status,
            d.currency,d.revision,p.name party_name FROM commercial_documents d JOIN parties p ON p.id=d.party_id ORDER BY d.id DESC"""
            )
        ]


@atomic
def save(database, header, rows, user, document_id=None):
    kind = header.get("kind")
    if kind not in KINDS:
        raise ValueError("Choose quotation, consignment or purchase order")
    day = iso_date(header.get("doc_date"))
    database._assert_period_open(day)
    currency = str(header.get("currency") or "").upper()
    if currency not in database.currency_codes():
        raise ValueError("Choose a configured currency")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise ValueError("Enter 1 to 500 lines")
    lines = []
    with database.connect() as connection:
        party = connection.execute(
            "SELECT * FROM parties WHERE id=?", (int(header.get("party_id") or 0),)
        ).fetchone()
        if not party:
            raise ValueError("Choose a customer or supplier")
        if kind == "purchase_order" and party["kind"] not in ("supplier", "both"):
            raise ValueError("Choose a supplier for a purchase order")
        for index, row in enumerate(rows, 1):
            description = str(row.get("description") or "").strip()
            if not description:
                raise ValueError(f"Line {index}: description is required")
            qty = money(row.get("quantity"), "quantity", True)
            price = money(row.get("unit_price"), "unit price")
            rate = money(row.get("vat_rate"), "VAT rate")
            if rate > 100:
                raise ValueError("VAT rate cannot exceed 100%")
            sku = str(row.get("sku") or "").strip()
            if (
                sku
                and not connection.execute(
                    "SELECT 1 FROM inventory_items WHERE sku=? AND active=1", (sku,)
                ).fetchone()
            ):
                raise ValueError(f"Unknown or inactive item {sku}")
            base = (qty * price).quantize(CENT)
            tax = (base * rate / 100).quantize(CENT)
            lines.append(
                {
                    "description": description,
                    "sku": sku,
                    "quantity": str(qty),
                    "unit_price": str(price),
                    "vat_rate": str(rate),
                    "subtotal": str(base),
                    "vat": str(tax),
                    "total": str(base + tax),
                }
            )
        until = iso_date(header["valid_until"]) if header.get("valid_until") else None
        if until and until < day:
            raise ValueError("Validity date cannot precede the document date")
        values = (
            day,
            party["id"],
            currency,
            json.dumps(lines, ensure_ascii=False),
            until,
            str(header.get("terms") or ""),
            str(header.get("notes") or ""),
            utcnow(),
        )
        if document_id:
            old = get(database, document_id)
            if old["status"] != "draft":
                raise ValueError("Only draft commercial documents may be edited")
            if old["kind"] != kind:
                raise ValueError("Document type cannot change")
            if old["revision"] != int(header.get("revision") or 0):
                raise ValueError("Document changed; reload before saving")
            connection.execute(
                """UPDATE commercial_documents SET doc_date=?,party_id=?,currency=?,lines=?,valid_until=?,terms=?,notes=?,
                updated_at=?,revision=revision+1 WHERE id=?""",
                (*values, int(document_id)),
            )
            saved = int(document_id)
        else:
            prefix = f"{KINDS[kind]}-{day[:4]}-"
            last = connection.execute(
                "SELECT number FROM commercial_documents WHERE number LIKE ? ORDER BY number DESC LIMIT 1",
                (prefix + "%",),
            ).fetchone()
            number = prefix + f"{int(last[0].rsplit('-',1)[-1]) + 1 if last else 1:06d}"
            saved = connection.execute(
                """INSERT INTO commercial_documents(kind,number,doc_date,party_id,currency,lines,
                valid_until,terms,notes,updated_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (kind, number, *values, user),
            ).lastrowid
        _audit(connection, user, "save", saved, {"kind": kind})
    return get(database, saved)


@atomic
def set_status(database, document_id, status, revision, user):
    if status not in ("confirmed", "cancelled"):
        raise ValueError("Invalid document action")
    document = get(database, document_id)
    if document["revision"] != int(revision):
        raise ValueError("Document changed; reload first")
    if document["status"] == "cancelled":
        raise ValueError("Document is cancelled")
    if status == "confirmed" and document["status"] != "draft":
        raise ValueError("Document already confirmed")
    if status == "cancelled" and document["events"]:
        raise ValueError(
            "Document has receipts/invoices; preserve it and reverse linked records through their own workflows"
        )
    database._assert_period_open(document["doc_date"])
    with database.connect() as connection:
        connection.execute(
            "UPDATE commercial_documents SET status=?,revision=revision+1,updated_at=? WHERE id=?",
            (status, utcnow(), int(document_id)),
        )
        _audit(connection, user, status, document_id, {})
    return get(database, document_id)


def _request(database, document_id, kind, body):
    reference = str(body.get("reference") or "").strip()
    if not reference or len(reference) > 120:
        raise ValueError("Enter an operation reference")
    fingerprint = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    with database.connect() as connection:
        old = connection.execute(
            "SELECT * FROM commercial_events WHERE document_id=? AND kind=? AND reference=?",
            (int(document_id), kind, reference),
        ).fetchone()
    if old and old["request_hash"] != fingerprint:
        raise ValueError("Reference already used with different values")
    return reference, fingerprint, dict(old) if old else None


def _quantities(document, rows, action):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Enter the lines and quantities")
    result, seen = [], set()
    for row in rows:
        index = int(row.get("line") or 0)
        if index in seen or not 1 <= index <= len(document["lines"]):
            raise ValueError("Invalid or repeated line")
        seen.add(index)
        source = document["lines"][index - 1]
        qty = money(row.get("quantity"), "quantity", True)
        limit = (
            Decimal(source["quantity"]) - Decimal(source["received"])
            if action == "receipt"
            else (
                Decimal(
                    source["received"]
                    if document["kind"] == "purchase_order"
                    else source["quantity"]
                )
                - Decimal(source["invoiced"])
            )
        )
        if qty > limit:
            raise ValueError(f"Line {index}: maximum {limit} remaining for {action}")
        result.append((index, source, qty, row))
    return result


def _event(
    connection,
    document_id,
    kind,
    reference,
    fingerprint,
    day,
    rows,
    user,
    stock_id=None,
    invoice_id=None,
):
    connection.execute(
        """INSERT INTO commercial_events(document_id,kind,reference,request_hash,doc_date,rows,
        stock_document_id,invoice_id,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            document_id,
            kind,
            reference,
            fingerprint,
            day,
            json.dumps(rows),
            stock_id,
            invoice_id,
            user,
            utcnow(),
        ),
    )
    _audit(
        connection,
        user,
        kind,
        document_id,
        {
            "reference": reference,
            "stock_document_id": stock_id,
            "invoice_id": invoice_id,
        },
    )


@atomic
def receive(database, document_id, body, user):
    import inventory

    reference, fingerprint, old = _request(database, document_id, "receipt", body)
    if old:
        return get(database, document_id)
    document = get(database, document_id)
    if document["kind"] != "purchase_order" or document["status"] != "confirmed":
        raise ValueError("Confirm a purchase order before receiving")
    day = iso_date(body.get("doc_date"))
    database._assert_period_open(day)
    if day < document["doc_date"]:
        raise ValueError("Receipt cannot precede the order")
    selected = _quantities(document, body.get("rows"), "receipt")
    stock, rows = [], []
    for index, line, qty, _raw in selected:
        rows.append({"line": index, "quantity": str(qty)})
        if line["sku"]:
            rate = inventory._recorded_conversion_rate(
                database,
                document["currency"],
                inventory.settings(database)["currency"],
                day,
            )
            stock.append(
                {
                    "sku": line["sku"],
                    "quantity": str(qty),
                    "unit_cost": str(Decimal(line["unit_price"]) * rate),
                }
            )
    stock_id = None
    if stock:
        stock_doc = inventory.save_document(
            database,
            {
                "doc_type": "receipt",
                "doc_date": day,
                "warehouse_id": body.get("warehouse_id"),
                "party_id": document["party_id"],
                "reference": document["number"] + " / " + reference,
            },
            stock,
            user,
        )
        stock_id = stock_doc["id"]
    with database.connect() as connection:
        _event(
            connection,
            document_id,
            "receipt",
            reference,
            fingerprint,
            day,
            rows,
            user,
            stock_id,
        )
    return get(database, document_id)


@atomic
def invoice(database, document_id, body, user):
    reference, fingerprint, old = _request(database, document_id, "invoice", body)
    if old:
        return database.invoice_detail(old["invoice_id"])
    document = get(database, document_id)
    if (
        document["kind"] not in ("quotation", "purchase_order")
        or document["status"] != "confirmed"
    ):
        raise ValueError("Confirm a quotation or purchase order first")
    day = iso_date(body.get("doc_date"))
    database._assert_period_open(day)
    if day < document["doc_date"]:
        raise ValueError("Invoice cannot precede its source document")
    if document["valid_until"] and day > document["valid_until"]:
        raise ValueError("Commercial document has expired")
    selected = _quantities(document, body.get("rows"), "invoice")
    purchase = document["kind"] == "purchase_order"
    number = str(body.get("invoice_number") or "").strip()
    if purchase and not number:
        raise ValueError("Enter the supplier's actual invoice number")
    lines = [
        {
            "description": line["description"],
            "quantity": str(qty),
            "unit_price": str(
                money(raw.get("unit_price", line["unit_price"]), "invoice unit price")
            ),
            "vat_rate": line["vat_rate"],
        }
        for _index, line, qty, raw in selected
    ]
    # Stock is handled by receipts / Stock Documents, separately from this accounting
    # draft. Preserve source SKUs on the commercial lines, without a second movement.
    header = {
        "kind": "purchase" if purchase else "sale",
        "status": "review",
        "invoice_date": day,
        "invoice_number": number,
        "party_name": document["party_name"],
        "commercial_party_id": document["party_id"],
        "currency": document["currency"],
        "source_file": document["number"],
        "description": (
            f"From {document['number']}; receipt recorded separately"
            if purchase
            else f"From {document['number']}"
        ),
    }
    for key in (
        "expense_account",
        "vat_account",
        "vat_use",
        "vat_treatment",
        "vat_recoverable",
    ):
        if key in body:
            header[key] = body[key]
    saved = database.create_manual_invoice(header, lines, user)
    invoice_id = saved["id"] if isinstance(saved, dict) else int(saved)
    with database.connect() as connection:
        rows = [
            {"line": index, "quantity": str(qty), "unit_price": output["unit_price"]}
            for (index, _source, qty, _raw), output in zip(selected, lines)
        ]
        _event(
            connection,
            document_id,
            "invoice",
            reference,
            fingerprint,
            day,
            rows,
            user,
            invoice_id=invoice_id,
        )
    return database.invoice_detail(invoice_id)


def guard_invoice_edit(database, invoice_id, item=None):
    with database.connect() as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='commercial_events'"
        ).fetchone():
            return
        linked = connection.execute(
            "SELECT 1 FROM commercial_events WHERE invoice_id=?", (int(invoice_id),)
        ).fetchone()
    if not linked:
        return
    changed = item is None
    if item is not None:
        current = database.get_invoice(invoice_id)
        for key in (
            "currency",
            "party_name",
            "invoice_date",
            "subtotal",
            "vat",
            "total",
        ):
            if key not in item:
                continue
            if key in ("subtotal", "vat", "total"):
                changed = changed or money(item[key], key) != money(current[key], key)
            elif key == "invoice_date":
                changed = changed or iso_date(item[key]) != iso_date(current[key])
            else:
                changed = changed or str(item[key]) != str(current[key])
        if "kind" in item:
            changed = changed or database._entry_type(item) != database._entry_type(
                current
            )
    if changed:
        raise ValueError(
            "Linked commercial invoice: preserve quantities and prices; cancel the draft and recreate it from its source to correct amounts"
        )


def guard_stock_document(database, document_id):
    with database.connect() as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='commercial_events'"
        ).fetchone():
            return
        if connection.execute(
            "SELECT 1 FROM commercial_events WHERE stock_document_id=?",
            (int(document_id),),
        ).fetchone():
            raise ValueError(
                "Receipt linked to a purchase order: preserve this stock document; correct it with a separately reviewed return/adjustment"
            )


def sections(document, language="en"):
    ar = language == "ar"
    titles = {
        "quotation": ("Quotation", "عرض سعر"),
        "purchase_order": ("Purchase Order", "أمر شراء"),
        "consignment": ("Consignment Note", "سند إرسال بضاعة بالأمانة"),
    }
    title = titles[document["kind"]][ar]
    meta = [
        document["number"],
        document["party_name"],
        document["doc_date"],
        document["currency"],
        document["status"],
        (
            "مستند تجاري؛ لا يرحّل قيداً أو حركة مخزون تلقائياً"
            if ar
            else "Commercial document: no automatic journal entry or stock movement"
        ),
    ]
    if document.get("valid_until"):
        meta.append(("صالح حتى " if ar else "Valid until ") + document["valid_until"])
    if document["kind"] == "consignment":
        meta.append(
            "يبقى التملك للمرسل؛ سجّل النقل الفعلي في مستندات المخزون"
            if ar
            else "Ownership retained by sender; record physical warehouse transfers separately in Stock Documents"
        )
    headers = (
        [
            "الصنف",
            "الوصف",
            "الكمية",
            "السعر",
            "الضريبة %",
            "الأساس",
            "الضريبة",
            "المجموع",
        ]
        if ar
        else [
            "Item",
            "Description",
            "Qty",
            "Unit price",
            "VAT %",
            "Subtotal",
            "VAT",
            "Total",
        ]
    )
    rows = [
        [
            line["sku"],
            line["description"],
            *[
                Decimal(line[key])
                for key in (
                    "quantity",
                    "unit_price",
                    "vat_rate",
                    "subtotal",
                    "vat",
                    "total",
                )
            ],
        ]
        for line in document["lines"]
    ]
    totals = [
        sum((Decimal(line[key]) for line in document["lines"]), Decimal(0))
        for key in ("subtotal", "vat", "total")
    ]
    rows.append(["", "الإجمالي" if ar else "Total", "", "", "", *totals])
    return {
        "title": title,
        "meta": meta,
        "sections": [
            {
                "heading": title,
                "report_language": language,
                "headers": headers,
                "rows": rows,
                "total_rows": [len(rows) - 1],
            },
            {
                "heading": "الشروط والملاحظات" if ar else "Terms and notes",
                "report_language": language,
                "narrative": True,
                "headers": [""],
                "rows": [
                    [document.get("terms") or ""],
                    [document.get("notes") or ""],
                    [
                        (
                            "توقيع المرسل: __________    توقيع المستلم: __________"
                            if ar
                            else "Sender signature: __________    Recipient signature: __________"
                        )
                    ],
                ],
                "total_rows": [],
            },
        ],
    }


def matching(database, document_id, language="en"):
    document = get(database, document_id)
    if document["kind"] != "purchase_order":
        raise ValueError(
            "Order / receipt / invoice matching is available for purchase orders"
        )
    rows = []
    for index, line in enumerate(document["lines"], 1):
        ordered, received, invoiced = (
            Decimal(line[key]) for key in ("quantity", "received", "invoiced")
        )
        rows.append(
            [
                index,
                line["sku"],
                line["description"],
                ordered,
                received,
                invoiced,
                ordered - received,
                received - invoiced,
                "Invoice review required" if invoiced else "Open",
            ]
        )
    prices = []
    for event in document["events"]:
        if event["kind"] != "invoice" or event["invoice_status"] in (
            "cancelled",
            "deleted",
        ):
            continue
        for row in event["rows"]:
            source = document["lines"][int(row["line"]) - 1]
            expected, actual, qty = (
                Decimal(source["unit_price"]),
                Decimal(row["unit_price"]),
                Decimal(row["quantity"]),
            )
            prices.append(
                [
                    event["invoice_number"],
                    event["invoice_status"],
                    row["line"],
                    qty,
                    expected,
                    actual,
                    (actual - expected) * qty,
                    (
                        "Review price variance / inventory cost"
                        if expected != actual
                        else "Matched"
                    ),
                ]
            )
    report = {
        "title": "Order / Receipt / Invoice Matching",
        "meta": [
            document["number"],
            document["party_name"],
            document["currency"],
            "Receipt cost follows the order. Invoice price differences require a reviewed stock-cost adjustment where applicable.",
        ],
        "sections": [
            {
                "heading": "Quantity control (draft invoices reserve quantities)",
                "headers": [
                    "Line",
                    "Item",
                    "Description",
                    "Ordered",
                    "Received",
                    "Invoiced",
                    "Not received",
                    "Not invoiced",
                    "Review",
                ],
                "rows": rows,
                "total_rows": [],
            },
            {
                "heading": "Invoice price control",
                "headers": [
                    "Invoice",
                    "Status",
                    "Line",
                    "Qty",
                    "Order unit price",
                    "Invoice unit price",
                    "Price difference",
                    "Review",
                ],
                "rows": prices,
                "total_rows": [],
            },
        ],
    }

    if language == "ar":
        report["title"] = "مطابقة طلب الشراء والاستلام والفاتورة"
        report["meta"][
            -1
        ] = "كلفة الاستلام حسب الطلب؛ فروقات سعر الفاتورة تتطلب مراجعة وتسوية كلفة المخزون عند الاقتضاء."
        report["sections"][0][
            "heading"
        ] = "رقابة الكميات (الفواتير المسودة تحجز الكميات)"
        report["sections"][0]["headers"] = [
            "السطر",
            "الصنف",
            "الوصف",
            "المطلوب",
            "المستلم",
            "المفوتر",
            "غير المستلم",
            "غير المفوتر",
            "المراجعة",
        ]
        report["sections"][1]["heading"] = "رقابة سعر الفاتورة"
        report["sections"][1]["headers"] = [
            "الفاتورة",
            "الحالة",
            "السطر",
            "الكمية",
            "سعر الطلب",
            "سعر الفاتورة",
            "فرق السعر",
            "المراجعة",
        ]
        for row in rows:
            row[-1] = "مراجعة الفاتورة مطلوبة" if row[5] else "مفتوح"
        for row in prices:
            row[-1] = "مراجعة فرق السعر وكلفة المخزون" if row[4] != row[5] else "مطابق"
    for section in report["sections"]:
        section["report_language"] = language
    return report
