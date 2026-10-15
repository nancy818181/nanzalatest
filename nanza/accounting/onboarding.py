"""2.9.119: Starting with Nanza - bring the balances of the old program in one Excel file.

One workbook, four sheets (Settings > Start with Nanza > Template):
  Opening balances       Account | Debit | Credit | Currency        -> one Opening Voucher (type 04) per currency
  Customers & Suppliers  Type | Name | Currency | VAT No. | MOF No. | Phone | Address | Payment days
  Open invoices          Type | Number | Date | Due date | Customer / Supplier | Currency | Amount still open
  Items                  Code | Name | Unit | Sales price | Opening quantity | Unit cost | Warehouse

How the open invoices and the opening balances fit together (as in Zoho "opening balance adjustments"):
  each open invoice is posted Customer (D) / CLEARING (C) - or CLEARING (D) / Supplier (C) - so the ageing, the
  statements and the receipts allocate against it, and it is NOT a sale or a purchase of this year (no revenue, no VAT,
  not on the dashboard). In the Opening balances sheet the customers / suppliers totals (40.. / 41.. accounts) are moved
  to CLEARING automatically when open invoices are imported, so CLEARING ends at zero when both agree; the Books Health
  Check and the Year-End Check show it when they do not.

Everything is checked first (preview): nothing is written while one line is wrong. A safety backup is made before.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from database_common import display_date, iso_date, utcnow

OPENING_SOURCE = "Opening balances"
CLEARING = "479"
CLEARING_NAME = "Opening balances - open documents (clearing)"
SHEETS = {
    "opening": ("Opening balances", ["Account", "Debit", "Credit", "Currency", "Description"]),
    "parties": ("Customers & Suppliers", ["Type", "Name", "Currency", "VAT No.", "MOF No.", "Phone", "Address", "Payment days"]),
    "invoices": ("Open invoices", ["Type", "Number", "Date", "Due date", "Customer / Supplier", "Currency", "Amount still open"]),
    "items": ("Items", ["Code", "Name", "Unit", "Sales price", "Opening quantity", "Unit cost", "Warehouse"]),
}
README = [
    ("Start with Nanza - how to fill this file", ""),
    ("1. Opening balances", "The trial balance of the old program on the go-live date: one line per account (Debit or Credit). Customers 41.. and "
                            "suppliers 40.. may be one total line or one line per customer / supplier account."),
    ("2. Customers & Suppliers", "Type = customer or supplier. Each gets its own account (411... / 401...)."),
    ("3. Open invoices", "Invoices not fully paid on the go-live date (Type = sale or purchase). They show in the ageing and the statements, "
                         "and receipts / payments settle them. They are not sales or purchases of this year (no VAT, no revenue)."),
    ("4. Items", "Items with their opening quantity and unit cost (opening stock of the warehouse, MAIN when empty)."),
    ("Dates", "DD-MM-YYYY. Amounts: numbers only (1250.50)."),
    ("Leave a sheet empty", "if you do not need it. Nothing is saved while a line is wrong: the check lists every problem first."),
    ("ابدأ مع نانزا", "املأ الأرصدة الافتتاحية، الزبائن والموردين، الفواتير المفتوحة والأصناف. لا يُحفظ شيء إذا كان أي سطر خاطئاً."),
]
KINDS = {"customer": "customer", "client": "customer", "زبون": "customer", "عميل": "customer",
         "supplier": "supplier", "vendor": "supplier", "مورد": "supplier", "both": "both"}
INVOICE_KINDS = {"sale": "sale", "sales": "sale", "customer": "sale", "مبيع": "sale",
                 "purchase": "purchase", "purchases": "purchase", "supplier": "purchase", "شراء": "purchase"}


def _text(value):
    if value is None: return ""
    if isinstance(value, float) and value.is_integer(): value = int(value)
    if hasattr(value, "strftime"): return value.strftime("%d-%m-%Y")
    return str(value).strip()


def _amount(value, label, problems, where):
    text = _text(value).replace(",", "")
    if not text: return Decimal(0)
    try: return Decimal(text)
    except (InvalidOperation, ValueError):
        problems.append(f"{where}: {label} '{value}' is not a number"); return Decimal(0)


# ---------------------------------------------------------------- the Excel file
def template(path):
    """Write the empty workbook (headings, a Read me sheet)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    book = Workbook(); readme = book.active; readme.title = "Read me"
    for row in README: readme.append(list(row))
    readme["A1"].font = Font(bold=True, size=13); readme.column_dimensions["A"].width = 30; readme.column_dimensions["B"].width = 120
    for _key, (title, headers) in SHEETS.items():
        sheet = book.create_sheet(title); sheet.append(headers)
        for cell in sheet[1]: cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="102A43")
        for index, header in enumerate(headers):
            sheet.column_dimensions[chr(65 + index)].width = max(14, len(header) + 4)
        sheet.freeze_panes = "A2"
    book.save(path)
    return str(path)


def read(path):
    """{sheet key: [row dict]} - the sheets found by name, the columns by heading (any order)."""
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    names = {name.strip().lower(): name for name in book.sheetnames}
    data = {}
    for key, (title, headers) in SHEETS.items():
        sheet_name = names.get(title.lower())
        if not sheet_name: data[key] = []; continue
        rows = list(book[sheet_name].iter_rows(values_only=True))
        if not rows: data[key] = []; continue
        heading = [_text(v).lower() for v in rows[0]]
        columns = {h: heading.index(h.lower()) for h in headers if h.lower() in heading}
        found = []
        for number, values in enumerate(rows[1:], start=2):
            row = {h: _text(values[i] if i < len(values) else None) for h, i in columns.items()}  # text: sent as JSON
            if any(_text(v) for v in row.values()): found.append({"_row": number, **row})
        data[key] = found
    return data


# ---------------------------------------------------------------- check (nothing is written)
def check(database, data, opening_date):
    """{"problems": [...], "notes": [...], "counts": {...}, "plan": {...}} - the plan is what apply() writes."""
    problems, notes = [], []
    day = iso_date(opening_date, "Opening date"); shown = display_date(day)
    currencies = set(database.currency_codes()); main = str((database.settings() or {}).get("base_currency") or "USD").upper()
    with database.connect() as db:
        accounts = {r["code"] for r in db.execute("SELECT code FROM accounts")}
        parties = {(r["kind"], r["name"].strip().lower()): dict(r) for r in db.execute("SELECT * FROM parties")}
        items = {r["sku"].upper() for r in db.execute("SELECT sku FROM inventory_items")}
        warehouses = {str(r["code"]).upper(): r["id"] for r in db.execute("SELECT id, code FROM warehouses")}
        existing_invoices = {(r["kind"], r["invoice_number"]) for r in db.execute("SELECT kind, invoice_number FROM invoices")}
        opening_done = [r[0] for r in db.execute("SELECT entry_number FROM journal_entries WHERE entry_number LIKE ?", (f"OB-{day[:4]}-%",))]
    if opening_done: problems.append(f"Opening balances of {day[:4]} were already imported ({', '.join(opening_done)}): delete those vouchers first")

    # customers / suppliers
    new_parties = []; seen = set()
    for row in data.get("parties", []):
        where = f"Customers & Suppliers row {row['_row']}"
        kind = KINDS.get(_text(row.get("Type")).lower()); name = _text(row.get("Name")); currency = (_text(row.get("Currency")) or main).upper()
        if not kind: problems.append(f"{where}: Type must be customer or supplier"); continue
        if not name: problems.append(f"{where}: the name is empty"); continue
        if currency not in currencies: problems.append(f"{where}: currency {currency} is not in Settings > Currencies"); continue
        days = _text(row.get("Payment days")) or "0"
        if not days.isdigit(): problems.append(f"{where}: Payment days must be a whole number"); continue
        key = (kind, name.lower())
        if key in seen: problems.append(f"{where}: {name} appears twice"); continue
        seen.add(key)
        if key in parties: notes.append(f"{name} already exists - its details are updated"); continue
        new_parties.append({"kind": "client" if kind == "customer" else kind, "name": name, "currency": currency,
                            "tax_number": _text(row.get("VAT No.")), "mof_number": _text(row.get("MOF No.")),
                            "contact_number": _text(row.get("Phone")), "address": _text(row.get("Address")), "due_days": int(days)})
    known_party = lambda kind, name: (kind, name.lower()) in parties or (kind, name.lower()) in seen or ("both", name.lower()) in parties

    # open invoices
    invoices = []; open_totals = {}
    for row in data.get("invoices", []):
        where = f"Open invoices row {row['_row']}"
        kind = INVOICE_KINDS.get(_text(row.get("Type")).lower()); number = _text(row.get("Number")); party = _text(row.get("Customer / Supplier"))
        currency = (_text(row.get("Currency")) or main).upper(); amount = _amount(row.get("Amount still open"), "Amount", problems, where)
        if not kind: problems.append(f"{where}: Type must be sale or purchase"); continue
        if not number: problems.append(f"{where}: the invoice number is empty"); continue
        if (kind, number) in existing_invoices: problems.append(f"{where}: invoice {number} already exists"); continue
        if not party: problems.append(f"{where}: the customer / supplier is empty"); continue
        if not known_party("customer" if kind == "sale" else "supplier", party):
            problems.append(f"{where}: {party} is not in the Customers & Suppliers sheet nor in Nanza"); continue
        if currency not in currencies: problems.append(f"{where}: currency {currency} is not in Settings > Currencies"); continue
        if amount <= 0: problems.append(f"{where}: the amount still open must be above zero"); continue
        try: date = iso_date(_text(row.get("Date")), "Date")
        except ValueError as exc: problems.append(f"{where}: {exc}"); continue
        if date > day: problems.append(f"{where}: dated after the opening date {shown} - enter it as a normal invoice"); continue
        due = _text(row.get("Due date"))
        if due:
            try: due = display_date(iso_date(due, "Due date"))
            except ValueError as exc: problems.append(f"{where}: {exc}"); continue
        invoices.append({"invoice_number": number, "invoice_date": display_date(date), "due_date": due or None, "party_name": party, "kind": kind,
                         "currency": currency, "subtotal": str(amount), "vat": "0", "total": str(amount), "status": "posted",
                         "expense_account": CLEARING, "expense_no_vat_account": CLEARING, "source_file": OPENING_SOURCE,
                         "description": f"Open on {shown} (brought from the previous program)"})
        if kind == "sale": invoices[-1]["revenue_splits"] = [(CLEARING, str(amount))]  # a sale posts to class 7 unless split: here the clearing account
        side = 1 if kind == "sale" else -1
        open_totals[currency] = open_totals.get(currency, Decimal(0)) + side * amount

    # opening balances
    vouchers = {}
    for row in data.get("opening", []):
        where = f"Opening balances row {row['_row']}"
        code = _text(row.get("Account")).split(" - ", 1)[0].strip(); currency = (_text(row.get("Currency")) or main).upper()
        debit = _amount(row.get("Debit"), "Debit", problems, where); credit = _amount(row.get("Credit"), "Credit", problems, where)
        if not code: problems.append(f"{where}: the account is empty"); continue
        if code not in accounts: problems.append(f"{where}: account {code} is not in the chart of accounts"); continue
        if currency not in currencies: problems.append(f"{where}: currency {currency} is not in Settings > Currencies"); continue
        if debit < 0 or credit < 0 or (debit and credit) or not (debit or credit):
            problems.append(f"{where}: enter either a Debit or a Credit (positive)"); continue
        if code.startswith(("6", "7")): problems.append(f"{where}: {code} is an expense / income account - an opening balance has no 6 / 7 accounts"); continue
        description = _text(row.get("Description")) or f"Opening {shown}"
        if invoices and code.startswith(("40", "41")) and currency in open_totals:  # the open invoices carry them
            notes.append(f"{code} {currency}: moved to {CLEARING} (the open invoices post the customer / supplier side)")
            code = CLEARING
        vouchers.setdefault(currency, []).append({"account_code": code, "debit": str(debit), "credit": str(credit), "description": description})
    for currency, lines in vouchers.items():
        difference = sum(Decimal(l["debit"]) - Decimal(l["credit"]) for l in lines)
        if difference: problems.append(f"Opening balances in {currency} are not balanced: debit - credit = {difference:,.2f}")
    for currency, total in open_totals.items():
        moved = sum(Decimal(l["debit"]) - Decimal(l["credit"]) for l in vouchers.get(currency, []) if l["account_code"] == CLEARING)
        if vouchers.get(currency) and moved != total:
            notes.append(f"{currency}: open invoices (customers - suppliers) {total:,.2f} differ from the 40 / 41 balances {moved:,.2f}; "
                         f"the difference stays on {CLEARING} until it is explained")

    # items
    new_items = []; stock = {}
    for row in data.get("items", []):
        where = f"Items row {row['_row']}"
        code = _text(row.get("Code")).upper(); name = _text(row.get("Name"))
        quantity = _amount(row.get("Opening quantity"), "Opening quantity", problems, where); cost = _amount(row.get("Unit cost"), "Unit cost", problems, where)
        price = _amount(row.get("Sales price"), "Sales price", problems, where); warehouse = (_text(row.get("Warehouse")) or "MAIN").upper()
        if not name: problems.append(f"{where}: the item name is empty"); continue
        if code and code in items: problems.append(f"{where}: item {code} already exists"); continue
        if quantity < 0 or cost < 0 or price < 0: problems.append(f"{where}: quantity, cost and price cannot be negative"); continue
        if quantity and warehouse not in warehouses: problems.append(f"{where}: warehouse {warehouse} does not exist (Inventory > Warehouses)"); continue
        if quantity and not cost: problems.append(f"{where}: enter the unit cost of the opening quantity"); continue
        new_items.append({"sku": code, "name": name, "unit": _text(row.get("Unit")) or "unit", "sales_price": str(price), "_row": row["_row"]})
        if quantity: stock.setdefault(warehouses[warehouse], []).append({"_row": row["_row"], "quantity": str(quantity), "unit_cost": str(cost)})
    counts = {"customers_suppliers": len(new_parties), "open_invoices": len(invoices), "items": len(new_items),
              "opening_lines": sum(len(v) for v in vouchers.values()), "currencies": sorted(vouchers)}
    return {"problems": problems, "notes": notes, "counts": counts, "date": shown,
            "plan": {"parties": new_parties, "invoices": invoices, "vouchers": vouchers, "items": new_items, "stock": stock}}


# ---------------------------------------------------------------- import (all lines checked first)
def apply(database, data, opening_date, user_id):
    result = check(database, data, opening_date)
    if result["problems"]:
        raise ValueError("Nothing was imported - correct these lines first:\n" + "\n".join(result["problems"][:30]))
    plan = result["plan"]; day = iso_date(opening_date, "Opening date"); shown = display_date(day)
    database.backup("safety")
    with database.connect() as db:
        db.execute("INSERT OR IGNORE INTO accounts(code,name_en,name_ar,type,parent_id) VALUES(?,?,?,?,(SELECT id FROM accounts WHERE code='47'))",
                   (CLEARING, CLEARING_NAME, "أرصدة افتتاحية - مستندات مفتوحة (حساب وسيط)", "asset"))
    for party in plan["parties"]: database.save_party(party, user_id)
    for invoice in plan["invoices"]: database.import_invoice(invoice, user_id)
    vouchers = []
    for currency, lines in sorted(plan["vouchers"].items()):
        saved = database.save_journal_voucher({"entry_number": f"OB-{day[:4]}-{currency}", "entry_date": shown, "currency": currency, "voucher_type": "04",
                                               "description": f"Opening balances {shown} ({currency})"}, lines, user_id)
        vouchers.append(((saved or {}).get("voucher") or {}).get("entry_number") or f"OB-{day[:4]}-{currency}")
    import inventory
    skus = {}
    for item in plan["items"]:
        saved = inventory.save_item(database, {k: v for k, v in item.items() if not k.startswith("_")}, user_id); skus[item["_row"]] = saved["sku"]
    stock_documents = []
    for warehouse_id, lines in plan["stock"].items():
        document = inventory.save_document(database, {"doc_type": "opening", "doc_date": shown, "warehouse_id": warehouse_id, "notes": f"Opening stock {shown}"},
                                           [{"sku": skus[l["_row"]], "quantity": l["quantity"], "unit_cost": l["unit_cost"]} for l in lines], user_id)
        stock_documents.append(document.get("number") if isinstance(document, dict) else "")
    with database.connect() as db:
        db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                   (user_id, "import", "opening_balances", json.dumps({**result["counts"], "vouchers": vouchers, "stock": stock_documents}), utcnow()))
    return {**result["counts"], "vouchers": vouchers, "stock_documents": stock_documents, "notes": result["notes"]}


def is_opening_invoice(row):
    return str((row or {}).get("source_file") or "") == OPENING_SOURCE
