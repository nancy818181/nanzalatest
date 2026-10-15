"""Inventory: items, warehouses, stock documents, weighted-average / FIFO costing, reports and the
year-end stock variation voucher of the Lebanese chart (6051 opening stock / 6052 closing stock / 37 stock).

Accounting follows the periodic method of the Lebanese chart of accounts: purchases stay in 601, and the
stock value is booked at the period end by a 'STOCK VARIATION' Journal Voucher (type 06)."""
from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal

from database import display_date, iso_date, utcnow

ZERO = Decimal("0")
DOC_TYPES = {"opening": ("OPN", "Opening Stock", 1), "receipt": ("GRN", "Stock Receipt", 1), "issue": ("GIN", "Stock Issue", -1),
             "adjustment_in": ("ADJ", "Adjustment +", 1), "adjustment_out": ("ADJ", "Adjustment -", -1), "transfer": ("TRF", "Transfer", 0),
             "production": ("PRD", "Production", 0)}  # 2.9.65: materials out, finished product in (production.py)
STOCK_ACCOUNT, OPENING_ACCOUNT, CLOSING_ACCOUNT = "37", "6051", "6052"
# 2.9.79: each item has its stock account (class 3), linked to its cost (purchases) account and to the stock-variation
# accounts of the Lebanese chart used at year end (periodic method):
#   stock prefix: (purchases / cost account, variation - opening stock, variation - closing stock, description)
STOCK_LINKS = {
    "37": ("601100000", "6051", "6052", "Goods for sale: purchases 6011, variation 6051 / 6052"),
    "31": ("611100000", "6151", "6152", "Raw materials & consumables: purchases 6111, variation 6151 / 6152"),
    "33": ("", "7211", "7211", "Work in progress: production variation 7211"),
    "35": ("", "7255", "7255", "Manufactured products: production variation 7255"),
}


def stock_link(stock_account):
    """(cost account, opening variation, closing variation, note) of a stock account: the longest prefix of STOCK_LINKS.
    31 covers 311, 312 ... but not 33 / 35 / 37, which have their own link."""
    code = str(stock_account or STOCK_ACCOUNT).split(" - ", 1)[0].strip() or STOCK_ACCOUNT
    for prefix in sorted(STOCK_LINKS, key=len, reverse=True):
        if code.startswith(prefix): return STOCK_LINKS[prefix]
    raise ValueError(f"Stock account {code} is not a stock account: use 31 (raw materials), 33 (work in progress), 35 (products) or 37 (goods)")

# ---------------------------------------------------------------- negative stock (2.9.45)
# Stock may go below zero only after the user confirmed the alert. The confirmation applies to the request
# being saved (thread-local, set by the data service from the X-Allow-Negative-Stock header); the documents
# that end up below zero are then marked allow_negative=1 so later, unrelated saves are not blocked by them.
NEGATIVE_MARKER = "[NEGATIVE_STOCK] "
_ALLOW = threading.local()
log = logging.getLogger("saber.inventory")


class NegativeStock(ValueError):
    """Raised when a change would take stock below zero and the user has not confirmed it."""


@contextmanager
def negative_stock_allowed(flag=True):
    previous = getattr(_ALLOW, "value", False); _ALLOW.value = bool(flag)
    try: yield
    finally: _ALLOW.value = previous


def negative_allowed():
    return bool(getattr(_ALLOW, "value", False))


def _negative_message(lines):
    shown = "\n".join(lines[:6]) + (f"\n... and {len(lines) - 6} more" if len(lines) > 6 else "")
    return (NEGATIVE_MARKER + "Stock will go below zero:\n" + shown +
            "\n\nSave anyway? The stock will show negative until the goods are received.")


def _d(value):
    try: return Decimal(str(value if value not in (None, "") else 0).replace(",", ""))
    except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError(f"'{value}' is not a number") from exc


def migrate(db):
    """Called from Database.initialize: inventory tables and columns."""
    db.execute("""CREATE TABLE IF NOT EXISTS warehouses (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)""")
    db.execute("""CREATE TABLE IF NOT EXISTS stock_documents (
        id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE, doc_type TEXT NOT NULL, doc_date TEXT NOT NULL, warehouse_id INTEGER NOT NULL,
        to_warehouse_id INTEGER, party_id INTEGER, invoice_id INTEGER, reference TEXT, notes TEXT, created_by INTEGER, created_at TEXT NOT NULL)""")
    item_columns = {row["name"] for row in db.execute("PRAGMA table_info(inventory_items)")}
    for column, definition in (("category", "TEXT"), ("reorder_level", "TEXT NOT NULL DEFAULT '0'"), ("sales_price", "TEXT NOT NULL DEFAULT '0'"),
                               ("active", "INTEGER NOT NULL DEFAULT 1"), ("notes", "TEXT"), ("barcode", "TEXT"), ("created_at", "TEXT")):
        if column not in item_columns: db.execute(f"ALTER TABLE inventory_items ADD COLUMN {column} {definition}")
    movement_columns = {row["name"] for row in db.execute("PRAGMA table_info(stock_movements)")}
    for column, definition in (("warehouse_id", "INTEGER"), ("document_id", "INTEGER"), ("movement_type", "TEXT"), ("sales_price", "TEXT"), ("line_no", "INTEGER"),
                               ("invoice_item_id","INTEGER"),("cost_layers","TEXT")):
        if column not in movement_columns: db.execute(f"ALTER TABLE stock_movements ADD COLUMN {column} {definition}")
    document_columns = {row["name"] for row in db.execute("PRAGMA table_info(stock_documents)")}
    for column, definition in (("allow_negative", "INTEGER NOT NULL DEFAULT 0"), ("project_id", "INTEGER"), ("branch_id", "INTEGER")):
        if column not in document_columns: db.execute(f"ALTER TABLE stock_documents ADD COLUMN {column} {definition}")
    if "brand" not in {row["name"] for row in db.execute("PRAGMA table_info(inventory_items)")}:
        db.execute("ALTER TABLE inventory_items ADD COLUMN brand TEXT")
    if "customs_group" not in {row["name"] for row in db.execute("PRAGMA table_info(inventory_items)")}:  # 2.9.106: '' none, '1', '2'
        db.execute("ALTER TABLE inventory_items ADD COLUMN customs_group TEXT")
    db.execute("CREATE TABLE IF NOT EXISTS landed_cost_parts (id INTEGER PRIMARY KEY, cost_invoice_id INTEGER NOT NULL, component TEXT NOT NULL, amount TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS item_categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL, parent_id INTEGER, UNIQUE(name,parent_id))")
    db.execute("CREATE TABLE IF NOT EXISTS item_units (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
    db.execute("""CREATE TABLE IF NOT EXISTS physical_counts (id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE, count_date TEXT NOT NULL, warehouse_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft', lines TEXT NOT NULL, adjustment_numbers TEXT, notes TEXT, created_by INTEGER, created_at TEXT NOT NULL)""")
    item_columns = {row["name"] for row in db.execute("PRAGMA table_info(inventory_items)")}
    for column in ("subcategory", "supplier_id", "location"):
        if column not in item_columns: db.execute(f"ALTER TABLE inventory_items ADD COLUMN {column} TEXT")
    if "default_vat" not in item_columns: db.execute("ALTER TABLE inventory_items ADD COLUMN default_vat TEXT NOT NULL DEFAULT '11'")
    if "cost_account" not in item_columns: db.execute("ALTER TABLE inventory_items ADD COLUMN cost_account TEXT")
    if "stock_account" not in item_columns: db.execute("ALTER TABLE inventory_items ADD COLUMN stock_account TEXT")  # 2.9.79
    if "sales_account" not in item_columns: db.execute("ALTER TABLE inventory_items ADD COLUMN sales_account TEXT")  # 2.9.90: the item's revenue account
    # 2.9.65: production - recipe (bill of materials) of a finished product, and the extra cost of a production order
    db.execute("""CREATE TABLE IF NOT EXISTS bom_headers (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL UNIQUE, output_qty TEXT NOT NULL DEFAULT '1',
        overhead_per_unit TEXT NOT NULL DEFAULT '0', notes TEXT, active INTEGER NOT NULL DEFAULT 1, updated_by INTEGER, updated_at TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS bom_lines (id INTEGER PRIMARY KEY, bom_id INTEGER NOT NULL REFERENCES bom_headers(id) ON DELETE CASCADE,
        component_id INTEGER NOT NULL, quantity TEXT NOT NULL, line_no INTEGER NOT NULL DEFAULT 0)""")
    document_columns = {row["name"] for row in db.execute("PRAGMA table_info(stock_documents)")}
    if "extra_cost" not in document_columns: db.execute("ALTER TABLE stock_documents ADD COLUMN extra_cost TEXT")
    for unit in ("unit", "piece", "sheet", "m", "m2", "kg", "box", "roll", "set"): db.execute("INSERT OR IGNORE INTO item_units(name) VALUES(?)", (unit,))
    db.execute("INSERT OR IGNORE INTO warehouses(code,name) VALUES('MAIN','Main Store')")
    db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('inventory_currency','USD')")
    db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('inventory_method','average')")
    db.execute("UPDATE stock_movements SET warehouse_id=(SELECT id FROM warehouses WHERE code='MAIN') WHERE warehouse_id IS NULL")


SHOW_KEYS = ("brand", "warehouse", "project", "branch")  # which of these appear in the inventory screens (2.9.45)
ASK_KEYS = ("category", "subcategory", "brand")  # 2.9.101: asked for each new item a purchase creates


def settings(database):
    values = database.settings()
    result = {"currency": values.get("inventory_currency", "USD"), "method": values.get("inventory_method", "average")}
    for key in SHOW_KEYS: result[f"show_{key}"] = values.get(f"inventory_show_{key}", "1") != "0"
    for key in ASK_KEYS: result[f"ask_{key}"] = values.get(f"inventory_ask_{key}", "0") == "1"
    return result


def brands(database):
    with database.connect() as db:
        return [r["brand"] for r in db.execute("SELECT DISTINCT brand FROM inventory_items WHERE brand IS NOT NULL AND brand<>'' ORDER BY brand COLLATE NOCASE")]


def save_settings(database, item, user_id):
    currency = str(item.get("currency") or "USD").upper(); method = str(item.get("method") or "average").lower()
    if currency not in database.currency_codes() or method not in ("average", "fifo"): raise ValueError("Choose a listed currency and Average or FIFO")
    pairs = [("inventory_currency", currency), ("inventory_method", method)]
    pairs += [(f"inventory_show_{key}", "1" if item.get(f"show_{key}") else "0") for key in SHOW_KEYS if f"show_{key}" in item]
    pairs += [(f"inventory_ask_{key}", "1" if item.get(f"ask_{key}") else "0") for key in ASK_KEYS if f"ask_{key}" in item]
    with database.connect() as db:
        for key, value in pairs:
            db.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    return settings(database)


# ---------------------------------------------------------------- master data
def list_warehouses(database):
    with database.connect() as db: return [dict(r) for r in db.execute("SELECT * FROM warehouses ORDER BY code")]


def save_warehouse(database, item, user_id):
    name = str(item.get("name") or "").strip(); code = str(item.get("code") or "").strip().upper()
    if not name: raise ValueError("Warehouse name is required")
    with database.connect() as db:
        if not code:
            numbers = [int(r["code"][2:]) for r in db.execute("SELECT code FROM warehouses WHERE code GLOB 'WH[0-9]*'") if r["code"][2:].isdigit()]
            code = f"WH{max(numbers, default=0) + 1:02d}"
        if db.execute("SELECT 1 FROM warehouses WHERE code=? AND id<>?", (code, int(item.get("id") or 0))).fetchone(): raise ValueError(f"Warehouse code {code} is already used")
        if item.get("id"): db.execute("UPDATE warehouses SET code=?,name=?,active=? WHERE id=?", (code, name, 1 if item.get("active", True) else 0, int(item["id"]))); saved = int(item["id"])
        else: saved = db.execute("INSERT INTO warehouses(code,name,active) VALUES(?,?,?)", (code, name, 1 if item.get("active", True) else 0)).lastrowid
    return next(w for w in list_warehouses(database) if w["id"] == saved)


def save_item(database, item, user_id):
    name = str(item.get("name") or "").strip(); sku = str(item.get("sku") or "").strip().upper()
    if not name: raise ValueError("Item name is required")
    reorder = _d(item.get("reorder_level")); price = _d(item.get("sales_price"))
    if reorder < 0 or price < 0: raise ValueError("Reorder level and sales price cannot be negative")
    with database.connect() as db:
        if not sku:
            numbers = [int(r["sku"][4:]) for r in db.execute("SELECT sku FROM inventory_items WHERE sku GLOB 'ITM-[0-9]*'") if r["sku"][4:].isdigit()]
            sku = f"ITM-{max(numbers, default=0) + 1:05d}"
        if db.execute("SELECT 1 FROM inventory_items WHERE sku=? AND id<>?", (sku, int(item.get("id") or 0))).fetchone(): raise ValueError(f"Item code {sku} is already used")
        supplier = item.get("supplier_id")
        if not supplier and str(item.get("supplier_name") or "").strip():
            row = db.execute("SELECT id FROM parties WHERE name=? ORDER BY id LIMIT 1", (str(item["supplier_name"]).strip(),)).fetchone(); supplier = row["id"] if row else None
        unit = str(item.get("unit") or "unit").strip() or "unit"; db.execute("INSERT OR IGNORE INTO item_units(name) VALUES(?)", (unit,))
        # 2.9.72: an item is zero-rated ("0") or at the company's standard VAT rate (Settings > General)
        company_rate = db.execute("SELECT value FROM app_settings WHERE key='vat_rate'").fetchone()
        default_vat = "0" if str(item.get("default_vat") or "11").strip() in ("0", "0.0", "0%") else str((company_rate[0] if company_rate else None) or "11")
        cost_account = str(item.get("cost_account") or "").split(" - ", 1)[0].strip() or None
        # 2.9.79: the stock account (37 when none is given) and, when no cost account is chosen, its linked purchases account
        stock_account = str(item.get("stock_account") or "").split(" - ", 1)[0].strip() or STOCK_ACCOUNT
        if not stock_account.isdigit() or not stock_account.startswith("3") or stock_account.startswith("39"):
            raise ValueError("The stock account must be a class 3 account: 31 raw materials, 33 work in progress, 35 products, 37 goods (39 is for provisions)")
        linked_cost = stock_link(stock_account)[0]
        if cost_account and not cost_account.replace(".", "").isdigit(): raise ValueError("Choose the cost account from the chart of accounts")
        # goods (37) keep the account of the purchase screen (601100000 by default) when no cost account is chosen
        if not cost_account and linked_cost and not stock_account.startswith(STOCK_ACCOUNT): cost_account = linked_cost
        brand = str(item.get("brand") or "").strip() or None
        values = (sku, name, unit, str(item.get("category") or "").strip() or None, str(reorder), str(price),
                  1 if item.get("active", True) else 0, str(item.get("notes") or "").strip() or None, str(item.get("barcode") or "").strip() or None,
                  str(item.get("subcategory") or "").strip() or None, str(supplier) if supplier else None, str(item.get("location") or "").strip() or None, default_vat, cost_account)
        if item.get("id"):
            db.execute("UPDATE inventory_items SET sku=?,name=?,unit=?,category=?,reorder_level=?,sales_price=?,active=?,notes=?,barcode=?,subcategory=?,supplier_id=?,location=?,default_vat=?,cost_account=? WHERE id=?",
                    values + (int(item["id"]),)); saved = int(item["id"])
            if "brand" in item: db.execute("UPDATE inventory_items SET brand=? WHERE id=?", (brand, saved))
        else:
            saved = db.execute("INSERT INTO inventory_items(sku,name,unit,category,reorder_level,sales_price,active,notes,barcode,subcategory,supplier_id,location,default_vat,cost_account,created_at,brand) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    values + (utcnow(), brand)).lastrowid
        db.execute("UPDATE inventory_items SET stock_account=? WHERE id=?", (stock_account, saved))
        if "customs_group" in item: db.execute("UPDATE inventory_items SET customs_group=? WHERE id=?", (customs_group(item.get("customs_group")), saved))
        if "sales_account" in item:  # 2.9.90
            sales_account = str(item.get("sales_account") or "").split(" - ", 1)[0].strip() or None
            if sales_account and not sales_account.startswith("7"): raise ValueError("The sales account must be a class 7 account (for example 7011 sales of goods)")
            db.execute("UPDATE inventory_items SET sales_account=? WHERE id=?", (sales_account, saved))
        db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)", (user_id, "save", "inventory_item", saved, json.dumps({"sku": sku}), utcnow()))
    return next(i for i in list_items(database) if i["id"] == saved)


# ---------------------------------------------------------------- costing engine
def _movements(database, date_to=None, exclude_document_id=None):
    with database.connect() as db:
        rows = [dict(r) for r in db.execute("""SELECT m.*,d.number,d.doc_type,d.doc_date,d.reference,d.party_id,d.invoice_id,d.allow_negative,d.project_id,d.branch_id,d.extra_cost,p.name party_name,w.code warehouse_code
            FROM stock_movements m JOIN stock_documents d ON d.id=m.document_id LEFT JOIN parties p ON p.id=d.party_id LEFT JOIN warehouses w ON w.id=m.warehouse_id
            ORDER BY d.doc_date,d.id,m.id""")]
    return [r for r in rows if (not date_to or r["doc_date"] <= date_to) and r["document_id"] != exclude_document_id]


CUSTOMS_GROUPS = {"": "No customs", "1": "Subject to customs"}
GROUP_COMPONENTS = {"customs_group_1": "1", "customs_group_2": "2"}  # 2.9.106: shared only by the items subject to customs


def customs_group(value):
    """'' (no customs) or '1' (subject to customs) - from '1', 'Yes', 'Subject to customs', 'No customs'... ('2' kept for a 2nd group)."""
    text = str(value or "").strip().casefold()
    if text in ("2", "group 2", "customs group 2"): return "2"
    if text in ("1", "yes", "y", "true", "subject to customs", "customs", "group 1", "customs group 1"): return "1"
    return ""


def _spread(lines, amount, result):
    """Add amount to result {movement id: extra per unit}, shared over lines by value (by quantity when there is no value)."""
    value = sum((_d(r["quantity"]) * _d(r["unit_cost"]) for r in lines), ZERO)
    quantity = sum((_d(r["quantity"]) for r in lines), ZERO)
    for line in lines:
        share = (_d(line["quantity"]) * _d(line["unit_cost"]) / value) if value else (_d(line["quantity"]) / quantity if quantity else ZERO)
        if _d(line["quantity"]): result[line["id"]] = result.get(line["id"], ZERO) + amount * share / _d(line["quantity"])


def _landed_cost_per_unit(database):
    """2.9.82: {stock movement id: extra cost per unit}. The landed costs of a purchase (its linked 'Customs Case':
    freight, insurance, customs duties, broker fees, other - not the import VAT) are spread over the items received
    with that purchase, in proportion to their value, in the inventory currency (IAS 2: costs of purchase).
    2.9.106: "Customs per item" is shared only by the items subject to customs (Inventory > Items > Customs); everything
    else ("Customs fees", freight, insurance, broker, other) by all the items of the purchase."""
    currency = settings(database)["currency"]
    with database.connect() as db:
        costs = [dict(r) for r in db.execute("""SELECT id,linked_invoice_id,currency,invoice_date,CAST(subtotal AS REAL) subtotal FROM invoices
            WHERE source_file='Customs Case' AND linked_invoice_id IS NOT NULL AND status NOT IN ('cancelled','deleted')""")]
        if not costs: return {}
        receipts = [dict(r) for r in db.execute("""SELECT m.id,m.quantity,m.unit_cost,d.invoice_id,COALESCE(i.customs_group,'') customs_group
            FROM stock_movements m JOIN stock_documents d ON d.id=m.document_id LEFT JOIN inventory_items i ON i.id=m.item_id
            WHERE d.doc_type='receipt' AND d.invoice_id IS NOT NULL AND CAST(m.quantity AS REAL)>0""")]
        parts = {}
        for row in db.execute("SELECT cost_invoice_id,component,amount FROM landed_cost_parts"):
            parts.setdefault(row["cost_invoice_id"], []).append((row["component"], _d(row["amount"])))
    result = {}
    for cost in costs:
        if not cost["subtotal"]: continue
        try: rate = _recorded_conversion_rate(database, cost["currency"], currency, cost["invoice_date"])
        except ValueError: rate = None
        if rate is None: continue
        lines = [r for r in receipts if r["invoice_id"] == cost["linked_invoice_id"]]
        if not lines: continue
        shared = _d(cost["subtotal"])
        for component, amount in parts.get(cost["id"], []):
            group = GROUP_COMPONENTS.get(component)
            if not group or not amount: continue
            members = [r for r in lines if r["customs_group"] == group] or lines  # nobody in the group: shared by all
            _spread(members, amount * _d(rate), result); shared -= amount
        if shared: _spread(lines, shared * _d(rate), result)
    return result


def run_costing(database, date_to=None, method=None, callback=None, exclude_document_id=None, layers_callback=None):
    """Replays every movement in date order. Returns per-item {qty, value, by_warehouse, last_date}.

    Average: company-wide moving average; transfers carry that average cost.
    FIFO: issues consume the source warehouse's oldest layers; transfers carry those layers."""
    method = method or settings(database)["method"]; state = {}; transfers = {}; produced = {}
    landed = _landed_cost_per_unit(database)  # 2.9.82: freight, customs ... of the purchase are part of the cost of its items
    for row in _movements(database, date_to, exclude_document_id):
        extra = landed.get(row.get("id"))
        if extra and not row.get("cost_layers"): row = {**row, "unit_cost": str(_d(row["unit_cost"]) + extra)}
        if row.get("movement_type") == "production_output":
            # 2.9.65: the finished product costs the materials used by the same order (at their real cost now) plus its extra cost
            made = _d(row["quantity"])
            total = produced.pop(row["document_id"], ZERO) + _d(row.get("extra_cost"))
            row["unit_cost"] = str(total / made) if made else "0"
        item = state.setdefault(row["item_id"], {"qty": ZERO, "value": ZERO, "layers": [], "warehouse_layers": {},
                                                   "by_warehouse": {}, "last_date": None, "last_out": None})
        qty = _d(row["quantity"]); cost = _d(row["unit_cost"])
        wid = row["warehouse_id"]
        item["by_warehouse"][wid] = item["by_warehouse"].get(wid, ZERO) + qty
        item["last_date"] = row["doc_date"]
        layers = item["warehouse_layers"].setdefault(wid, [])
        def take_layers(amount):
            taken = []
            while amount > 0 and layers:
                layer = layers[0]; take = min(layer[0], amount)
                taken.append([take, layer[1], layer[2],layer[3],layer[4]])
                layer[0] -= take; amount -= take
                if layer[0] == 0: layers.pop(0)
            if amount:
                if not (row.get("allow_negative") or negative_allowed()):
                    raise ValueError(f"FIFO stock history has insufficient layers for item {row['item_id']} in warehouse {wid}")
                # Confirmed negative stock: the missing quantity goes out at the last known cost and is
                # owed by the warehouse; the next receipts there settle it first.
                last = item.get("last_cost") or ZERO
                taken.append([amount, last, row["doc_date"], row["document_id"], row["line_no"]])
                debts = item.setdefault("debt", {}); debts[wid] = debts.get(wid, ZERO) + amount
            return taken
        def take_specific_layers(requested):
            taken=[]
            for target in requested:
                amount=_d(target.get("quantity"))
                for layer in list(layers):
                    if (layer[3],layer[4])!=(int(target["source_document_id"]),int(target["source_line_no"])): continue
                    take=min(amount,layer[0])
                    if take:
                        taken.append([take,layer[1],layer[2],layer[3],layer[4]])
                        layer[0]-=take; amount-=take
                        if not layer[0]: layers.remove(layer)
                    if not amount: break
                if amount:
                    raise ValueError(f"Original FIFO purchase layer for item {row['item_id']} has only {(_d(target.get('quantity'))-amount):,.3f} available in this warehouse")
            return taken
        if row["doc_type"] == "transfer":
            key = (row["document_id"], row["line_no"], row["item_id"])
            if method == "fifo":
                if qty < 0:
                    moved = take_layers(-qty)
                    transfers[key] = moved
                else:
                    moved = transfers.pop(key, None)
                    if moved is None or sum((part[0] for part in moved), ZERO) != qty:
                        raise ValueError(f"Unpaired FIFO transfer in stock document {row['number']}")
                    layers.extend(moved)
                unit = sum((part[0] * part[1] for part in moved), ZERO) / abs(qty)
            else:
                unit = (item["value"] / item["qty"]) if item["qty"] else ZERO
            if callback: callback(row, unit, ZERO)
            continue
        if qty > 0:
            item["qty"] += qty; item["value"] += qty * cost
            if method == "fifo":
                try: costing_layers=json.loads(row.get("cost_layers") or "[]")
                except (TypeError,ValueError): costing_layers=[]
                if costing_layers:
                    added=sum((_d(part["quantity"])*_d(part["unit_cost"]) for part in costing_layers),ZERO)
                    if added.quantize(Decimal("0.000001"))!=(qty*cost).quantize(Decimal("0.000001")):
                        raise ValueError(f"Receipt {row['number']} has invalid costing layers")
                    for part in costing_layers:
                        layers.append([_d(part["quantity"]),_d(part["unit_cost"]),row["doc_date"],row["document_id"],row["line_no"]])
                else: layers.append([qty, cost, row["doc_date"],row["document_id"],row["line_no"]])
                owed = item.get("debt", {}).get(wid, ZERO)
                while owed > 0 and layers:
                    layer = layers[0]; take = min(layer[0], owed); layer[0] -= take; owed -= take
                    if layer[0] == 0: layers.pop(0)
                if "debt" in item: item["debt"][wid] = owed
            else: item["layers"].append([qty, cost])
            issued_cost = cost
            if cost > 0: item["last_cost"] = cost
        else:
            out = -qty
            try: explicit_layers=json.loads(row.get("cost_layers") or "[]")
            except (TypeError,ValueError): explicit_layers=[]
            if row.get("movement_type")=="purchase_return" and explicit_layers:
                if sum((_d(part["quantity"]) for part in explicit_layers),ZERO)!=out:
                    raise ValueError(f"Purchase return {row['number']} has invalid original-layer quantities")
                taken=take_specific_layers(explicit_layers) if method=="fifo" else []
                issued_cost=sum((_d(part.get("unit_cost") or part.get("cost"))*_d(part["quantity"]) for part in explicit_layers),ZERO)/out
                issued_layers=[[str(_d(part["quantity"])),str(_d(part.get("unit_cost") or part.get("cost")))] for part in explicit_layers]
            elif method == "fifo":
                taken=take_layers(out)
                total = sum((part[0] * part[1] for part in taken), ZERO)
                issued_cost = total / out if out else ZERO
                issued_layers=[{"quantity":str(part[0]),"unit_cost":str(part[1]),"source_document_id":part[3],"source_line_no":part[4]} for part in taken]
            else:
                issued_cost = (item["value"] / item["qty"]) if item["qty"] > 0 else (item.get("last_cost") or ZERO)
                for layer in item["layers"]: layer[1] = issued_cost
                issued_layers=[{"quantity":str(out),"unit_cost":str(issued_cost)}]
            item["qty"] -= out; item["value"] -= out * issued_cost; item["last_out"] = row["doc_date"]
            if issued_cost > 0: item["last_cost"] = issued_cost
            if item["qty"] <= 0: item["value"] = item["qty"] * issued_cost if item["qty"] < 0 else ZERO; item["layers"] = []
        if qty < 0 and row.get("movement_type") == "production_input":
            produced[row["document_id"]] = produced.get(row["document_id"], ZERO) + out * issued_cost
        if callback: callback(row, issued_cost, qty * issued_cost)
        if layers_callback and qty<0: layers_callback(row,issued_layers)
    if transfers: raise ValueError("Unpaired FIFO transfer in stock history")
    for item in state.values():
        if item["qty"]>0 and item["value"]<Decimal("-0.000001"):
            raise ValueError("Stock movement would make the remaining inventory value negative")
        item["warehouse_value"] = ({wid: sum((layer[0] * layer[1] for layer in layers), ZERO)
                                    for wid, layers in item["warehouse_layers"].items()} if method == "fifo"
                                   else {wid: qty * item["value"] / item["qty"] if item["qty"] else ZERO
                                         for wid, qty in item["by_warehouse"].items()})
        item["avg"] = (item["value"] / item["qty"]) if item["qty"] > 0 else ZERO
    return state


def _reported_warehouse_values(data):
    """Allocate any rounding penny to one warehouse so displayed lines sum to the inventory value."""
    values = {wid: value.quantize(Decimal("0.01")) for wid, value in data["warehouse_value"].items()}
    if values:
        difference = data["value"].quantize(Decimal("0.01")) - sum(values.values(), ZERO)
        if difference:
            largest = max(values, key=lambda wid: (values[wid], -wid))
            values[largest] += difference
    return values


def list_items(database, date_to=None, include_inactive=True):
    state = run_costing(database, iso_date(date_to) if date_to else None)
    with database.connect() as db:
        items = [dict(r) for r in db.execute("SELECT i.*,p.name supplier_name FROM inventory_items i LEFT JOIN parties p ON p.id=CAST(i.supplier_id AS INTEGER) ORDER BY i.sku")]
        last = {r["item_id"]: r["party_name"] for r in db.execute("""SELECT m.item_id,p.name party_name FROM stock_movements m JOIN stock_documents d ON d.id=m.document_id
            JOIN parties p ON p.id=d.party_id WHERE d.doc_type='receipt' ORDER BY d.doc_date,d.id""")}
    for item in items:
        item["supplier_name"] = item.get("supplier_name") or last.get(item["id"]) or ""
        data = state.get(item["id"], {})
        item["quantity"] = float(data.get("qty", ZERO)); item["average_cost"] = float(data.get("avg", ZERO)); item["stock_value"] = float(data.get("value", ZERO))
        item["reorder_level"] = float(_d(item.get("reorder_level"))); item["sales_price"] = float(_d(item.get("sales_price")))
    return [i for i in items if include_inactive or i["active"]]


# ---------------------------------------------------------------- stock documents
def next_number(database, doc_type, date):
    prefix = DOC_TYPES[doc_type][0]; year = iso_date(date)[:4]
    with database.connect() as db:
        numbers = [int(r["number"].rsplit("-", 1)[-1]) for r in db.execute("SELECT number FROM stock_documents WHERE number LIKE ?",
                (f"{prefix}-{year}-%",)) if r["number"].rsplit("-", 1)[-1].isdigit()]
    return f"{prefix}-{year}-{max(numbers, default=0) + 1:06d}"


def _recorded_conversion_rate(database, source, target, date):
    source=str(source or "").upper(); target=str(target or "").upper()
    if source==target: return Decimal("1")
    try: date_key=iso_date(date).replace("-","")
    except ValueError as exc: raise ValueError("A valid invoice date is required for inventory currency conversion") from exc
    sortable="""CASE WHEN rate_date GLOB '??-??-????' THEN substr(rate_date,7,4)||substr(rate_date,4,2)||substr(rate_date,1,2)
        ELSE replace(rate_date,'-','') END"""
    def rate(frm,to):
        with database.connect() as db:
            row=db.execute(f"SELECT rate FROM exchange_rates WHERE from_currency=? AND to_currency=? AND {sortable}<=? ORDER BY {sortable} DESC,id DESC LIMIT 1",
                           (frm,to,date_key)).fetchone()
            if row: return Decimal(str(row["rate"]))
            row=db.execute(f"SELECT rate FROM exchange_rates WHERE from_currency=? AND to_currency=? AND {sortable}<=? ORDER BY {sortable} DESC,id DESC LIMIT 1",
                           (to,frm,date_key)).fetchone()
            if row:
                value=Decimal(str(row["rate"]))
                return Decimal("1")/value if value else None
        return None
    direct=rate(source,target)
    if direct is not None and direct.is_finite() and direct>0: return direct
    first=rate(source,"USD") if source!="USD" else Decimal("1")
    second=rate("USD",target) if target!="USD" else Decimal("1")
    if first is not None and second is not None and first.is_finite() and second.is_finite() and first>0 and second>0:
        return first*second
    raise ValueError(f"No recorded exchange rate from {source} to inventory currency {target} on {date}; enter a reviewed rate before posting stock")


def _convert_inventory_cost(database, invoice, unit_cost):
    target=settings(database)["currency"]; source=str(invoice.get("currency") or target).upper()
    rate=_recorded_conversion_rate(database,source,target,invoice.get("invoice_date"))
    return _d(unit_cost)*rate


def _assert_nonnegative_history(db):
    """No document may leave an item below zero in a warehouse, unless that was confirmed (allow_negative)."""
    balances={}; shortages={}
    rows=db.execute("""SELECT m.item_id,m.warehouse_id,m.quantity,d.id document_id,d.number,d.doc_date,COALESCE(d.allow_negative,0) allow_negative,
        i.sku,w.code warehouse_code FROM stock_movements m JOIN stock_documents d ON d.id=m.document_id
        LEFT JOIN inventory_items i ON i.id=m.item_id LEFT JOIN warehouses w ON w.id=m.warehouse_id ORDER BY d.doc_date,d.id,m.id""")
    for row in rows:
        key=(row["item_id"],row["warehouse_id"])
        balances[key]=balances.get(key,ZERO)+_d(row["quantity"])
        if balances[key]<Decimal("-0.000001") and _d(row["quantity"])<0 and not row["allow_negative"]:
            shortages[(row["document_id"],key)]=(row["document_id"],
                    f"Stock movement {row['number']} on {display_date(row['doc_date'])} would make later stock negative ({row['sku']} in {row['warehouse_code']}: {balances[key]:,.3f})")
    if not shortages: return
    if not negative_allowed(): raise NegativeStock(_negative_message([text for _id,text in shortages.values()]))
    ids=sorted({doc_id for doc_id,_text in shortages.values()})
    db.execute(f"UPDATE stock_documents SET allow_negative=1 WHERE id IN ({','.join('?'*len(ids))})",ids)
    log.warning("Negative stock confirmed by the user: %s", "; ".join(text for _id,text in shortages.values()))


def _optional_id(db, table, value):
    """Project / branch of a stock document: an id, a code or a name; empty = none."""
    text = str(value or "").strip()
    if not text: return None
    column = "code" if table == "projects" else "name"
    row = db.execute(f"SELECT id FROM {table} WHERE id=? OR {column}=? OR name=?", (int(text) if text.isdigit() else -1, text, text)).fetchone()
    if not row: raise ValueError(f"{'Project' if table == 'projects' else 'Branch'} '{text}' was not found")
    return row["id"]


def save_document(database, header, lines, user_id, document_id=None):
    doc_type = str(header.get("doc_type") or "").lower()
    if doc_type not in DOC_TYPES: raise ValueError("Choose the document type")
    if doc_type == "production": raise ValueError("Production orders are saved from Inventory > Production")
    date = iso_date(header.get("doc_date"), "Date"); database._assert_period_open(date)
    if not isinstance(lines, list) or not lines: raise ValueError("Add at least one item line")
    with database.connect() as db:
        warehouse = db.execute("SELECT * FROM warehouses WHERE id=? OR code=?",
                (int(header["warehouse_id"]) if str(header.get("warehouse_id") or "").isdigit() else -1, str(header.get("warehouse_id") or "MAIN"))).fetchone()
        if not warehouse: raise ValueError("Choose the warehouse")
        target = None
        if doc_type == "transfer":
            target = db.execute("SELECT * FROM warehouses WHERE id=? OR code=?",
                    (int(header["to_warehouse_id"]) if str(header.get("to_warehouse_id") or "").isdigit() else -1,
                    str(header.get("to_warehouse_id") or ""))).fetchone()
            if not target or target["id"] == warehouse["id"]: raise ValueError("Choose a different destination warehouse for the transfer")
        items = {}; normalized = []
        for index, line in enumerate(lines, 1):
            code = str(line.get("sku") or "").strip().upper()
            item = db.execute("SELECT * FROM inventory_items WHERE sku=? OR id=?", (code, int(line["item_id"]) if str(line.get("item_id") or "").isdigit() else -1)).fetchone()
            if not item: raise ValueError(f"Line {index}: item {code or line.get('item_id')} was not found")
            qty = _d(line.get("quantity")); cost = _d(line.get("unit_cost"))
            if qty <= 0: raise ValueError(f"Line {index}: quantity must be above zero")
            if cost < 0: raise ValueError(f"Line {index}: unit cost cannot be negative")
            if DOC_TYPES[doc_type][2] > 0 and not cost and doc_type not in ("adjustment_in", "opening"):
                raise ValueError(f"Line {index}: enter the unit cost of {item['sku']}")
            normalized.append((item, qty, cost, _d(line.get("sales_price")),line.get("invoice_item_id"),
                               line.get("cost_layers"),line.get("movement_type") or doc_type))
            items[item["id"]] = items.get(item["id"], ZERO) + qty
    # Stock may not go negative: check the quantity available in the warehouse on the document date.
    if DOC_TYPES[doc_type][2] <= 0:
        state = run_costing(database, date) if not document_id else _state_without(database, date, document_id)
        for item_id, qty in items.items():
            available = state.get(item_id, {}).get("by_warehouse", {}).get(warehouse["id"], ZERO)
            if qty > available:
                sku = next(n[0]["sku"] for n in normalized if n[0]["id"] == item_id)
                if not negative_allowed():
                    raise NegativeStock(_negative_message([f"Not enough stock of {sku} in {warehouse['code']} on {display_date(date)}: available {available:,.3f}, requested {qty:,.3f}"]))
    with database.connect() as db:
        if document_id:
            old = db.execute("SELECT * FROM stock_documents WHERE id=?", (int(document_id),)).fetchone()
            if not old: raise KeyError("Stock document not found")
            if old["invoice_id"]:
                database._assert_no_active_linked_returns(db,old["invoice_id"],"edit stock for")
            database._assert_period_open(old["doc_date"]); number = old["number"]
            db.execute("DELETE FROM stock_movements WHERE document_id=?", (int(document_id),))
            db.execute("""UPDATE stock_documents SET doc_type=?,doc_date=?,warehouse_id=?,to_warehouse_id=?,party_id=?,reference=?,notes=?,project_id=?,branch_id=? WHERE id=?""",
                (doc_type, date, warehouse["id"], target["id"] if target else None, header.get("party_id") or None, header.get("reference") or None, header.get("notes") or None,
                 _optional_id(db, "projects", header.get("project_id")), _optional_id(db, "branches", header.get("branch_id")), int(document_id)))
            saved = int(document_id)
        else:
            number = str(header.get("number") or "").strip() or next_number(database, doc_type, date)
            saved = db.execute("""INSERT INTO stock_documents(number,doc_type,doc_date,warehouse_id,to_warehouse_id,party_id,invoice_id,reference,notes,created_by,created_at,project_id,branch_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (number, doc_type, date, warehouse["id"], target["id"] if target else None, header.get("party_id") or None,
                header.get("invoice_id") or None, header.get("reference") or None, header.get("notes") or None, user_id, utcnow(),
                _optional_id(db, "projects", header.get("project_id")), _optional_id(db, "branches", header.get("branch_id")))).lastrowid
        sign = DOC_TYPES[doc_type][2]
        for position, (item, qty, cost, price, invoice_item_id, cost_layers, movement_type) in enumerate(normalized, 1):
            if doc_type == "transfer":
                for warehouse_id, signed in ((warehouse["id"], -qty), (target["id"], qty)):
                    db.execute("""INSERT INTO stock_movements(item_id,movement_date,quantity,unit_cost,source_type,source_id,warehouse_id,document_id,movement_type,line_no)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""", (item["id"], date, str(signed), "0", "stock", saved, warehouse_id, saved, doc_type, position))
            else:
                db.execute("""INSERT INTO stock_movements(item_id,movement_date,quantity,unit_cost,source_type,source_id,warehouse_id,document_id,movement_type,sales_price,line_no,invoice_item_id,cost_layers)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (item["id"], date, str(qty * sign), str(cost), "stock", saved, warehouse["id"], saved,
                    movement_type, str(price), position,invoice_item_id,json.dumps(cost_layers) if cost_layers else None))
        _assert_nonnegative_history(db)
        run_costing(database,method=settings(database)["method"])
        db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, "save", "stock_document", saved, json.dumps({"number": number, "type": doc_type, "lines": len(normalized)}), utcnow()))
    return get_document(database, saved)


def _state_without(database, date, document_id):
    return run_costing(database, date, exclude_document_id=int(document_id))


def get_document(database, document_id):
    with database.connect() as db:
        doc = db.execute("""SELECT d.*,w.code warehouse_code,w.name warehouse_name,t.code to_warehouse_code,p.name party_name,pr.code project_code,pr.name project_name,b.name branch_name
            FROM stock_documents d JOIN warehouses w ON w.id=d.warehouse_id LEFT JOIN warehouses t ON t.id=d.to_warehouse_id LEFT JOIN parties p ON p.id=d.party_id
            LEFT JOIN projects pr ON pr.id=d.project_id LEFT JOIN branches b ON b.id=d.branch_id WHERE d.id=?""", (int(document_id),)).fetchone()
        if not doc: raise KeyError("Stock document not found")
        lines = [dict(r) for r in db.execute("""SELECT m.*,i.sku,i.name,i.unit FROM stock_movements m JOIN inventory_items i ON i.id=m.item_id
            WHERE m.document_id=? ORDER BY m.line_no,m.id""", (int(document_id),))]
    doc = dict(doc)
    if doc["doc_type"] == "transfer": lines = [l for l in lines if _d(l["quantity"]) > 0]
    for line in lines: line["quantity"] = float(abs(_d(line["quantity"]))); line["unit_cost"] = float(_d(line["unit_cost"])); line["sales_price"] = float(_d(line.get("sales_price")))
    doc["lines"] = lines
    return doc


def list_documents(database):
    with database.connect() as db:
        return [dict(r) for r in db.execute("""SELECT d.id,d.number,d.doc_type,d.doc_date,w.code warehouse_code,t.code to_warehouse_code,p.name party_name,d.reference,d.invoice_id,
            (SELECT COUNT(DISTINCT line_no) FROM stock_movements m WHERE m.document_id=d.id) lines FROM stock_documents d JOIN warehouses w ON w.id=d.warehouse_id
            LEFT JOIN warehouses t ON t.id=d.to_warehouse_id LEFT JOIN parties p ON p.id=d.party_id ORDER BY d.doc_date DESC,d.id DESC""")]


def delete_document(database, document_id, user_id):
    doc = get_document(database, document_id); database._assert_period_open(doc["doc_date"])
    if DOC_TYPES[doc["doc_type"]][2] > 0 or doc["doc_type"] == "production":  # removing stock that was already issued afterwards would make it negative
        _check_after_removal(database, document_id)
    with database.connect() as db:
        if doc.get("invoice_id"):
            database._assert_no_active_linked_returns(db,doc["invoice_id"],"delete stock for")
        db.execute("DELETE FROM stock_movements WHERE document_id=?", (int(document_id),)); db.execute("DELETE FROM stock_documents WHERE id=?", (int(document_id),))
        db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)", (user_id, "delete", "stock_document",
                int(document_id), json.dumps({"number": doc["number"]}), utcnow()))
    return {"deleted": int(document_id)}


def _check_after_removal(database, document_id):
    balances = {}
    for row in _movements(database, exclude_document_id=int(document_id)):
        key = (row["item_id"], row["warehouse_id"]); balances[key] = balances.get(key, ZERO) + _d(row["quantity"])
        if balances[key] < 0: raise ValueError(f"This document cannot be deleted: the stock issued later ({row['number']} on {display_date(row['doc_date'])}) would become negative")


def issue_for_invoice(database, invoice_id, lines, user_id):
    """Move stock for the item lines of an invoice, linked to that invoice.

    A normal sale takes goods out (Stock Issue) and a purchase brings them in (Stock Receipt).
    A credit note reverses that movement: a sales credit note (goods returned by the customer)
    brings the goods back in (Receipt), and a purchase credit note (goods returned to the supplier)
    sends them back out (Issue)."""
    with database.connect() as db:
        invoice=db.execute("SELECT * FROM invoices WHERE id=?",(int(invoice_id),)).fetchone()
        if not invoice: return None
        for old in db.execute("SELECT id FROM stock_documents WHERE invoice_id=?",(int(invoice_id),)).fetchall():
            db.execute("DELETE FROM stock_movements WHERE document_id=?",(old["id"],))
            db.execute("DELETE FROM stock_documents WHERE id=?",(old["id"],))
        invoice=dict(invoice)
        original_items=[dict(row) for row in db.execute("SELECT id,item_code,quantity,subtotal FROM invoice_items WHERE invoice_id=? ORDER BY id",(int(invoice_id),))]
    returned=invoice.get("doc_subtype")=="credit_note"
    is_sale=invoice["kind"]=="sale"
    if returned and invoice.get("linked_invoice_id"):
        if iso_date(invoice["invoice_date"])<iso_date(database.get_invoice(invoice["linked_invoice_id"])["invoice_date"]):
            raise ValueError("A return cannot be backdated before its original invoice; doing so would rewrite historical stock costing")
    indexed=[]
    for pos,(source,line) in enumerate(zip(original_items,lines)):
        code=line.get("item_code") or line.get("sku")
        if code:
            indexed.append({"sku":code,"quantity":line.get("quantity"),"sales_price":line.get("unit_price"),
                            "invoice_item_id":line.get("origin_item_id") if returned else source["id"],
                            "origin_item_id":line.get("origin_item_id") if returned else source["id"],"_source_item_id":source["id"],
                            "_source_cost":_d(source.get("subtotal"))/_d(source.get("quantity") or 1),
                            "unit_cost":0,"warehouse":line.get("warehouse") or "MAIN"})
    if not indexed: return None
    doc_type="issue" if (is_sale != returned) else "receipt"
    target=database.get_invoice(invoice["linked_invoice_id"]) if returned and invoice.get("linked_invoice_id") else invoice
    date=iso_date(invoice["invoice_date"])
    header={"doc_type":doc_type,"doc_date":date,"warehouse_id":indexed[0]["warehouse"],
        "party_id":invoice["party_id"],"invoice_id":int(invoice_id),"reference":invoice["invoice_number"],
        "notes":f"Invoice {invoice['invoice_number']}",
        "movement_type":"purchase_return" if returned and not is_sale else doc_type}
    if doc_type=="receipt" and is_sale and not invoice.get("linked_invoice_id"):
        # Older manually entered sales credit notes have no source invoice/item to
        # recover the original cost layer from. Use the current moving average as
        # an explicit fallback receipt layer so legacy notes remain postable under
        # either costing method.
        state=run_costing(database,date)
        for line in indexed:
            with database.connect() as db:
                item=db.execute("SELECT id FROM inventory_items WHERE sku=?",(str(line["sku"]).upper(),)).fetchone()
            cost=_d(state.get(item["id"],{}).get("avg")) if item else ZERO
            if cost<=0:
                raise ValueError(f"Cannot establish a positive stock cost for unlinked credit-note item {line['sku']}")
            line["unit_cost"]=cost
            line["cost_layers"]=[{"quantity":str(_d(line["quantity"])),"unit_cost":str(cost)}]
    if doc_type=="receipt" and is_sale and invoice.get("linked_invoice_id"):
        # Reintroduce the exact cost layers consumed by the original sales issue. Never
        # substitute today's average or the selling price for historical cost.
        for line in indexed:
            origin_id=int(line["origin_item_id"])
            with database.connect() as db:
                movements=[dict(r) for r in db.execute("""SELECT m.*,d.doc_date FROM stock_movements m JOIN stock_documents d ON d.id=m.document_id
                    WHERE d.invoice_id=? AND m.quantity<0 AND (m.invoice_item_id=? OR (m.invoice_item_id IS NULL AND m.item_id=(SELECT id FROM inventory_items WHERE sku=?)))
                    ORDER BY d.id,m.line_no,m.id""",(target["id"],origin_id,str(line["sku"]).upper()))]
            if not movements: raise ValueError(f"Original stock issue for {line['sku']} was not found; return not posted")
            selected=movements[0]
            try: layers=json.loads(selected.get("cost_layers") or "[]")
            except (TypeError,ValueError): layers=[]
            if not layers:
                captured={}
                def capture(row,values):
                    if row["id"]==selected["id"]: captured["layers"]=values
                run_costing(database,iso_date(target["invoice_date"]),layers_callback=capture)
                layers=captured.get("layers") or []
                if not layers: raise ValueError(f"Original cost layers for {line['sku']} cannot be reconstructed safely")
                with database.connect() as db:
                    db.execute("UPDATE stock_movements SET cost_layers=? WHERE id=?",(json.dumps(layers),selected["id"]))
            origin_detail=next((item for item in database.invoice_detail(target["id"])["items"] if int(item["id"])==origin_id),None)
            prior=_d(origin_detail.get("returned_quantity") or 0) if origin_detail else ZERO
            qty=_d(line["quantity"]); need=qty; remaining_layers=[{**part,"quantity":str(part.get("quantity"))} for part in layers]
            # Existing active returns have consumed the first part of the original cost-layer sequence.
            skip=prior; allocated=[]
            for part in remaining_layers:
                layer_qty=_d(part["quantity"]); cost=_d(part.get("unit_cost") or part.get("cost"))
                if skip>=layer_qty: skip-=layer_qty; continue
                available=layer_qty-skip; skip=ZERO
                take=min(need,available)
                if take:
                    allocated.append({"quantity":str(take),"unit_cost":str(cost)}); need-=take
                if not need: break
            if need: raise ValueError(f"Return quantity for {line['sku']} exceeds the original issued cost layers")
            line["cost_layers"]=allocated
            line["unit_cost"]=sum((_d(p["quantity"])*_d(p["unit_cost"]) for p in allocated),ZERO)/qty
    elif doc_type=="receipt" and not is_sale:
        rate=Decimal(str(invoice.get("exchange_rate") or 0))
        if rate<=0: raise ValueError("Invoice exchange rate must be a positive reviewed value")
        for line in indexed:
            source_line=next(item for item,original in zip(lines,original_items) if int(original["id"])==line["_source_item_id"])
            line["unit_cost"]=_convert_inventory_cost(database,invoice,line["_source_cost"])
    elif doc_type=="issue" and returned and not is_sale and not invoice.get("linked_invoice_id"):
        # 2.9.54: a purchase return typed directly (Purchases > Document: Return), not made from one invoice:
        # the goods leave at their current average cost.
        state=run_costing(database,date)
        for line in indexed:
            with database.connect() as db:
                item=db.execute("SELECT id FROM inventory_items WHERE sku=?",(str(line["sku"]).upper(),)).fetchone()
            cost=_d(state.get(item["id"],{}).get("avg")) if item else ZERO
            if cost<=0: raise ValueError(f"{line['sku']} has no stock cost yet; a return needs goods that were received first")
            line["unit_cost"]=cost; line["movement_type"]="purchase_return"
            line["cost_layers"]=[{"quantity":str(_d(line["quantity"])),"unit_cost":str(cost)}]
    elif doc_type=="issue" and returned and not is_sale:
        rate=Decimal(str(target.get("exchange_rate") or 0))
        if rate<=0: raise ValueError("Original purchase exchange rate is invalid")
        for line in indexed:
            origin_id=int(line["origin_item_id"])
            with database.connect() as db:
                movement=db.execute("""SELECT m.*,d.doc_date FROM stock_movements m JOIN stock_documents d ON d.id=m.document_id
                    WHERE d.invoice_id=? AND m.quantity>0 AND (m.invoice_item_id=? OR m.item_id=(SELECT id FROM inventory_items WHERE sku=?))
                    ORDER BY d.id,m.line_no,m.id LIMIT 1""",(target["id"],origin_id,str(line["sku"]).upper())).fetchone()
            if not movement: raise ValueError(f"Original purchase receipt for {line['sku']} was not found; return not posted")
            cost=_d(movement["unit_cost"])
            # Legacy receipts stored foreign currency values; convert from the original document's currency.
            if str(target["currency"]).upper()!=settings(database)["currency"]:
                origin_line=next((item for item in database.invoice_detail(target["id"])["items"] if int(item["id"])==origin_id),None)
                if not origin_line: raise ValueError(f"Original purchase line for {line['sku']} was not found")
                cost=_convert_inventory_cost(database,target,_d(origin_line.get("subtotal"))/_d(origin_line.get("quantity") or 1))
            line["unit_cost"]=cost
            line["movement_type"]="purchase_return"
            line["cost_layers"]=[{"quantity":str(_d(line["quantity"])),"unit_cost":str(cost),
                                  "source_document_id":movement["document_id"],"source_line_no":movement["line_no"]}]
    saved=save_document(database,header,indexed,user_id)
    if doc_type=="issue" and is_sale and not returned:
        mapped={}
        def capture(row,values):
            if row["document_id"]==saved["id"]: mapped[row["line_no"]]=values
        run_costing(database,date,layers_callback=capture)
        with database.connect() as db:
            for movement in db.execute("SELECT id,line_no FROM stock_movements WHERE document_id=?",(saved["id"],)).fetchall():
                if movement["line_no"] in mapped:
                    db.execute("UPDATE stock_movements SET cost_layers=? WHERE id=?",(json.dumps(mapped[movement["line_no"]]),movement["id"]))
    return saved


def remove_invoice_documents(db, invoice_id):
    for old in db.execute("SELECT id FROM stock_documents WHERE invoice_id=?", (int(invoice_id),)).fetchall():
        db.execute("DELETE FROM stock_movements WHERE document_id=?", (old["id"],)); db.execute("DELETE FROM stock_documents WHERE id=?", (old["id"],))


# ---------------------------------------------------------------- reports
def stock_value(database, date_to, method=None):
    state = run_costing(database, iso_date(date_to), method)
    return sum((data["value"] for data in state.values()), ZERO).quantize(Decimal("0.01"))


def post_stock_variation(database, year, user_id):
    """Periodic method: cancel the opening stock (Dr 6051 / Cr 37) and book the closing stock (Dr 37 / Cr 6052).
    2.9.79: done for each stock account used by the items, with its own variation accounts
    (37 -> 6051 / 6052, 31 -> 6151 / 6152, 33 -> 7211, 35 -> 7255)."""
    year = int(year); inv = settings(database); currency = inv["currency"]
    with database.connect() as db:
        for row in db.execute("SELECT id FROM journal_entries WHERE source_type='journal_voucher' AND voucher_type='06' AND description LIKE ?", (f"STOCK VARIATION - {year}%",)).fetchall():
            db.execute("DELETE FROM journal_entries WHERE id=?", (row["id"],))
        accounts = {r["id"]: (r["stock_account"] or STOCK_ACCOUNT) for r in db.execute("SELECT id,stock_account FROM inventory_items")}
    # The stock already in the ledger (at year end, before this voucher) is cancelled; the counted closing stock replaces it.
    state = run_costing(database, f"{year}-12-31")
    groups = {STOCK_ACCOUNT: {"opening": ZERO, "closing": ZERO}}
    for item_id, data in state.items():
        group = groups.setdefault(accounts.get(item_id, STOCK_ACCOUNT), {"opening": ZERO, "closing": ZERO}); group["closing"] += data["value"]
    keys = sorted(groups, key=len, reverse=True)
    for code, balance in _ledger_stock_accounts(database, f"{year}-12-31", currency).items():
        owner = next((key for key in keys if code.startswith(key)), None)
        if owner: groups[owner]["opening"] += balance  # a stock account no item uses (other than 37) is left as it is
    lines = []; total_opening = total_closing = ZERO; detail = []
    for stock, group in sorted(groups.items()):
        opening = group["opening"].quantize(Decimal("0.01")); closing = group["closing"].quantize(Decimal("0.01"))
        if not opening and not closing: continue
        _cost, opening_account, closing_account, _note = stock_link(stock)
        if opening > 0: lines += [{"account_code": opening_account, "line_currency": currency, "side": "D", "amount": str(opening)}, {"account_code": stock,
                "line_currency": currency, "side": "C", "amount": str(opening)}]
        elif opening < 0: lines += [{"account_code": stock, "line_currency": currency, "side": "D", "amount": str(-opening)}, {"account_code": opening_account,
                "line_currency": currency, "side": "C", "amount": str(-opening)}]
        if closing: lines += [{"account_code": stock, "line_currency": currency, "side": "D", "amount": str(closing)}, {"account_code": closing_account,
                "line_currency": currency, "side": "C", "amount": str(closing)}]
        total_opening += opening; total_closing += closing
        detail.append({"stock_account": stock, "opening_account": opening_account, "closing_account": closing_account, "opening": float(opening), "closing": float(closing)})
    if not lines: return {"year": year, "opening": 0.0, "closing": 0.0, "voucher": None, "groups": []}
    voucher = database.save_journal_voucher({"entry_date": f"31-12-{year}", "description": f"STOCK VARIATION - {year}: opening {total_opening:,.2f} / closing {total_closing:,.2f} {currency}",
                                             "currency": currency, "voucher_type": "06"}, lines, user_id)
    return {"year": year, "opening": float(total_opening), "closing": float(total_closing), "variation": float(total_closing - total_opening),
            "voucher": voucher["voucher"]["entry_number"], "groups": detail}


def _stock_groups(database, date_to, method=None):
    """{stock account: {"valuation", "items"}} at date_to, and the account of each item (37 when none)."""
    with database.connect() as db:
        accounts = {r["id"]: (r["stock_account"] or STOCK_ACCOUNT) for r in db.execute("SELECT id,stock_account FROM inventory_items")}
    groups = {STOCK_ACCOUNT: {"valuation": ZERO, "items": 0}}
    for item_id, data in run_costing(database, date_to, method).items():
        group = groups.setdefault(accounts.get(item_id, STOCK_ACCOUNT), {"valuation": ZERO, "items": 0})
        group["valuation"] += data["value"]
        if data["qty"]: group["items"] += 1
    return groups


def stock_ledger_check(database, date_to, method=None):
    """2.9.82: the stock valuation (costing) against the balance of each stock account in the ledger at date_to.
    With the periodic method the ledger only follows the stock when a stock variation is posted at that date."""
    date_to = iso_date(date_to); currency = settings(database)["currency"]
    groups = _stock_groups(database, date_to, method)
    for group in groups.values(): group["ledger"] = ZERO
    keys = sorted(groups, key=len, reverse=True); other = ZERO
    for code, balance in _ledger_stock_accounts(database, date_to, currency).items():
        owner = next((key for key in keys if code.startswith(key)), None)
        if owner: groups[owner]["ledger"] += balance
        else: other += balance
    with database.connect() as db:
        names = {r["code"]: r["name_en"] for r in db.execute("SELECT code,name_en FROM accounts")}
        variations = [r["description"] for r in db.execute("SELECT description FROM journal_entries WHERE source_type='journal_voucher' AND voucher_type='06' AND description LIKE 'STOCK VARIATION%'")]
    rows = []
    for stock in sorted(groups):
        g = groups[stock]; _cost, opening, closing, _note = stock_link(stock)
        rows.append({"stock_account": stock, "name": names.get(stock, ""), "items": g["items"], "valuation": g["valuation"].quantize(Decimal("0.01")),
                     "ledger": g["ledger"].quantize(Decimal("0.01")), "difference": (g["valuation"] - g["ledger"]).quantize(Decimal("0.01")),
                     "variation": opening if opening == closing else f"{opening} / {closing}"})
    rows = [r for r in rows if r["valuation"] or r["ledger"] or r["stock_account"] == STOCK_ACCOUNT]
    valuation = sum((r["valuation"] for r in rows), ZERO); ledger = sum((r["ledger"] for r in rows), ZERO)
    month = date_to[:7]; posted_here = any(d.startswith((f"STOCK VARIATION - {date_to[:4]}", f"STOCK VARIATION MONTH - {month}")) for d in variations)
    notes = ["Valuation = quantities x cost of the stock documents (Stock Card); Ledger = balance of the stock accounts (31 / 33 / 35 / 37) in the books.",
             "Periodic method: purchases go to 601 / 611 and the ledger follows the stock only through the Stock Variation voucher.",
             ("A stock variation is posted at this date: a difference means a stock document or an entry on a stock account was changed after it - post the variation again."
              if posted_here else "No stock variation at this date: the difference is what the monthly / year-end Stock Variation will book.")]
    if other: notes.append(f"Class 3 accounts with no item linked to them: {other:,.2f} {currency} (not in the table).")
    return {"date": date_to, "currency": currency, "groups": rows, "valuation": valuation, "ledger": ledger, "difference": valuation - ledger, "notes": notes, "posted": posted_here}


def post_monthly_stock_variation(database, month_end, user_id):
    """2.9.82: the Stock Variation of a month (Lebanese periodic method), so the P&L shows the month's cost of sales:
    the stock in the ledger is cancelled (Dr 6051 / Cr 37 ...) and the stock valuation at the month end is booked
    (Dr 37 / Cr 6052 ...), for each stock account. The later months already posted are posted again, in order."""
    from calendar import monthrange
    day = iso_date(month_end); year, month = int(day[:4]), int(day[5:7])
    last = f"{year}-{month:02d}-{monthrange(year, month)[1]:02d}"
    with database.connect() as db:
        posted = sorted({r["description"][len("STOCK VARIATION MONTH - "):][:7] for r in db.execute(
            "SELECT description FROM journal_entries WHERE source_type='journal_voucher' AND voucher_type='06' AND description LIKE ?", (f"STOCK VARIATION MONTH - {year}-%",))})
    months = sorted({f"{year}-{month:02d}"} | {m for m in posted if m > f"{year}-{month:02d}"})
    with database.connect() as db:
        for m in months:
            for row in db.execute("SELECT id FROM journal_entries WHERE source_type='journal_voucher' AND voucher_type='06' AND description LIKE ?", (f"STOCK VARIATION MONTH - {m}%",)).fetchall():
                db.execute("DELETE FROM journal_entries WHERE id=?", (row["id"],))
    results = []
    for m in months:
        y, mo = int(m[:4]), int(m[5:7]); end = f"{y}-{mo:02d}-{monthrange(y, mo)[1]:02d}"
        results.append(_post_variation_at(database, end, f"STOCK VARIATION MONTH - {m}", user_id))
    return {"month": last[:7], "posted": [r for r in results if r["voucher"]], "reposted": months[1:]}


def _post_variation_at(database, date_to, description, user_id):
    currency = settings(database)["currency"]
    groups = _stock_groups(database, date_to)
    for group in groups.values(): group["opening"] = ZERO
    keys = sorted(groups, key=len, reverse=True)
    for code, balance in _ledger_stock_accounts(database, date_to, currency).items():
        owner = next((key for key in keys if code.startswith(key)), None)
        if owner: groups[owner]["opening"] += balance
    lines = []; total_opening = total_closing = ZERO
    for stock, group in sorted(groups.items()):
        opening = group["opening"].quantize(Decimal("0.01")); closing = group["valuation"].quantize(Decimal("0.01"))
        if opening == closing: continue  # nothing changed on this account
        _cost, opening_account, closing_account, _note = stock_link(stock)
        if opening > 0: lines += [{"account_code": opening_account, "line_currency": currency, "side": "D", "amount": str(opening)}, {"account_code": stock,
                "line_currency": currency, "side": "C", "amount": str(opening)}]
        elif opening < 0: lines += [{"account_code": stock, "line_currency": currency, "side": "D", "amount": str(-opening)}, {"account_code": opening_account,
                "line_currency": currency, "side": "C", "amount": str(-opening)}]
        if closing: lines += [{"account_code": stock, "line_currency": currency, "side": "D", "amount": str(closing)}, {"account_code": closing_account,
                "line_currency": currency, "side": "C", "amount": str(closing)}]
        total_opening += opening; total_closing += closing
    if not lines: return {"date": date_to, "voucher": None, "opening": 0.0, "closing": 0.0}
    day = f"{date_to[8:10]}-{date_to[5:7]}-{date_to[:4]}"
    voucher = database.save_journal_voucher({"entry_date": day, "description": f"{description}: stock before {total_opening:,.2f} / at month end {total_closing:,.2f} {currency}",
                                             "currency": currency, "voucher_type": "06"}, lines, user_id)
    return {"date": date_to, "voucher": voucher["voucher"]["entry_number"], "opening": float(total_opening), "closing": float(total_closing)}


def _ledger_stock_accounts(database, date_to, currency):
    """2.9.79: the stock in the ledger at date_to by class 3 account (39 provisions excluded)."""
    from ledger_reports import _load_lines, _digits
    column = currency if currency in ("LBP", "USD") else "account"; totals = {}
    for row in _load_lines(database, {"posting_status": "posted"}):
        code = _digits(row["code"])
        if not code.startswith("3") or code.startswith("39") or row["iso_date"] > date_to: continue
        if column == "account" and row["account_currency"] != currency: continue
        totals[code] = totals.get(code, ZERO) + row["signed"][column]
    return {code: value.quantize(Decimal("0.01")) for code, value in totals.items() if value}


def _ledger_stock(database, date_to, currency):
    from ledger_reports import _load_lines, _digits
    column = currency if currency in ("LBP", "USD") else "account"
    total = sum((row["signed"][column] for row in _load_lines(database, {"posting_status": "posted"})
                 if _digits(row["code"]).startswith(STOCK_ACCOUNT) and row["iso_date"] <= date_to and (column != "account" or row["account_currency"] == currency)), ZERO)
    return total.quantize(Decimal("0.01"))


def _opening_value(database, year):
    value = stock_value(database, f"{int(year) - 1}-12-31")
    with database.connect() as db:
        rows = db.execute("""SELECT m.quantity,m.unit_cost FROM stock_movements m JOIN stock_documents d ON d.id=m.document_id
            WHERE d.doc_type='opening' AND d.doc_date>=? AND d.doc_date<=?""", (f"{int(year)}-01-01", f"{int(year)}-12-31")).fetchall()
    return (value + sum((_d(r["quantity"]) * _d(r["unit_cost"]) for r in rows), ZERO)).quantize(Decimal("0.01"))


def carry_forward(source, target, year, user_id):
    """New fiscal-year file: copy items and warehouses, and post the closing stock of year-1 as its Opening Stock."""
    year = int(year); method = settings(source)["method"]; state = run_costing(source, f"{year - 1}-12-31", method)
    with source.connect() as src: items = [dict(r) for r in src.execute("SELECT * FROM inventory_items")]; warehouses = [dict(r) for r in src.execute("SELECT * FROM warehouses")]
    with target.connect() as db:
        for w in warehouses: db.execute("INSERT OR IGNORE INTO warehouses(id,code,name,active) VALUES(?,?,?,?)", (w["id"], w["code"], w["name"], w["active"]))
        for i in items:
            db.execute("""INSERT INTO inventory_items(id,sku,name,unit,quantity,average_cost,category,reorder_level,sales_price,active,notes,barcode,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET sku=excluded.sku,name=excluded.name,unit=excluded.unit,category=excluded.category,reorder_level=excluded.reorder_level,sales_price=excluded.sales_price,active=excluded.active""",
                (i["id"], i["sku"], i["name"], i["unit"], "0", "0", i.get("category"), i.get("reorder_level") or "0", i.get("sales_price") or "0",
                        i.get("active", 1), i.get("notes"), i.get("barcode"), i.get("created_at")))
            # 2.9.79: the item keeps its stock and cost accounts in the new year
            target_columns = {row["name"] for row in db.execute("PRAGMA table_info(inventory_items)")}
            for column in ("stock_account", "cost_account"):
                if column in target_columns and i.get(column): db.execute(f"UPDATE inventory_items SET {column}=? WHERE id=?", (i[column], i["id"]))
        for old in db.execute("SELECT id FROM stock_documents WHERE doc_type='opening' AND number LIKE ?", (f"OPN-{year}-%",)).fetchall():
            db.execute("DELETE FROM stock_movements WHERE document_id=?", (old["id"],)); db.execute("DELETE FROM stock_documents WHERE id=?", (old["id"],))
    created = []
    by_warehouse = {}
    for item_id, data in state.items():
        for warehouse_id, qty in data["by_warehouse"].items():
            if qty <= 0: continue
            if method == "fifo":
                for layer in data["warehouse_layers"].get(warehouse_id, []):
                    by_warehouse.setdefault(warehouse_id, []).append({"item_id": item_id, "quantity": layer[0], "unit_cost": layer[1]})
            else:
                by_warehouse.setdefault(warehouse_id, []).append({"item_id": item_id, "quantity": qty, "unit_cost": data["avg"]})
    for warehouse_id, lines in by_warehouse.items():
        doc = save_document(target, {"doc_type": "opening", "doc_date": f"01-01-{year}", "warehouse_id": warehouse_id, "notes": f"Closing stock of {year - 1}"}, lines, user_id)
        created.append(doc["number"])
    return created


# ---------------------------------------------------------------- categories, units
def list_categories(database):
    with database.connect() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM item_categories ORDER BY name")]
        units = [r["name"] for r in db.execute("SELECT name FROM item_units ORDER BY name")]
        for name in {r["category"] for r in db.execute("SELECT DISTINCT category FROM inventory_items WHERE category IS NOT NULL AND category<>''")}:
            if not any(c["name"] == name and not c["parent_id"] for c in rows): rows.append({"id": None, "name": name, "parent_id": None})
    top = [c for c in rows if not c["parent_id"]]
    return {"categories": [{"id": c["id"], "name": c["name"],
            "subcategories": [s["name"] for s in rows if s["parent_id"] and s["parent_id"] == c["id"]]} for c in sorted(top, key=lambda c: c["name"])],
            "units": units}


def save_category(database, item, user_id):
    name = str(item.get("name") or "").strip(); kind = str(item.get("kind") or "category")
    if not name: raise ValueError("Enter the name")
    with database.connect() as db:
        if kind == "unit": db.execute("INSERT OR IGNORE INTO item_units(name) VALUES(?)", (name,))
        elif kind == "subcategory":
            parent = str(item.get("parent") or "").strip()
            if not parent: raise ValueError("Choose the category of the subcategory")
            db.execute("INSERT OR IGNORE INTO item_categories(name,parent_id) VALUES(?,NULL)", (parent,))
            parent_id = db.execute("SELECT id FROM item_categories WHERE name=? AND parent_id IS NULL", (parent,)).fetchone()["id"]
            db.execute("INSERT OR IGNORE INTO item_categories(name,parent_id) VALUES(?,?)", (name, parent_id))
        else:
            if not db.execute("SELECT 1 FROM item_categories WHERE name=? AND parent_id IS NULL", (name,)).fetchone(): db.execute("INSERT INTO item_categories(name,parent_id) VALUES(?,NULL)", (name,))
    return list_categories(database)


def item_name_key(name):
    """'Panel 4 mm', 'PANEL-4MM' and 'panel 4mm' are the same item name (2.9.51)."""
    import re
    return re.sub(r"[^0-9a-z\u0600-\u06ff]", "", str(name or "").casefold())


def similar_items(database, name, limit=3, threshold=0.82):
    """Items whose name is the same or close to `name` (best first): [{id, sku, name, unit, score}], score 1.0 = same."""
    from difflib import SequenceMatcher
    key = item_name_key(name)
    if not key: return []
    with database.connect() as db:
        rows = [dict(r) for r in db.execute("SELECT id,sku,name,unit FROM inventory_items WHERE COALESCE(active,1)=1")]
    found = []
    for row in rows:
        other = item_name_key(row["name"])
        if not other: continue
        score = 1.0 if other == key else SequenceMatcher(None, key, other).ratio()
        if score < 1.0 and (key in other or other in key) and min(len(key), len(other)) >= 4: score = max(score, 0.86)
        if score >= threshold: found.append({**row, "score": round(score, 3)})
    return sorted(found, key=lambda r: (-r["score"], r["sku"]))[:limit]


def set_item_details(database, details, user_id=None):
    """2.9.101: the category / subcategory / brand of new items, chosen in the table shown after a purchase creates them.
    details = [{"id": .., "category": .., "subcategory": .., "brand": ..}]; a key that is not given is not changed."""
    done = 0
    with database.connect() as db:
        for row in details or []:
            for key in ASK_KEYS:
                if key in row:
                    value = str(row.get(key) or "").strip() or None
                    db.execute(f"UPDATE inventory_items SET {key}=? WHERE id=?", (value, int(row["id"])))
                    if key == "category" and value:
                        db.execute("INSERT INTO item_categories(name,parent_id) SELECT ?,NULL WHERE NOT EXISTS "
                                   "(SELECT 1 FROM item_categories WHERE name=? AND parent_id IS NULL)", (value, value))
            done += 1
        db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                   (user_id, "update", "inventory_item", json.dumps({"details": details}, default=str)[:4000], utcnow()))
    return {"updated": done}


def set_item_accounts(database, item_ids, cost_account=None, sales_account=None, user_id=None):
    """2.9.90 (owner): the cost account (class 6) and the sales account (class 7) of several items at once - asked right
    after an upload creates new items. An empty value leaves that account as it is."""
    cost = str(cost_account or "").split(" - ", 1)[0].strip(); sales = str(sales_account or "").split(" - ", 1)[0].strip()
    if cost and not cost.startswith("6"): raise ValueError("The cost account must be a class 6 account (for example 601100000 purchases)")
    if sales and not sales.startswith("7"): raise ValueError("The sales account must be a class 7 account (for example 7011 sales of goods)")
    ids = [int(i) for i in item_ids or []]
    with database.connect() as db:
        for code in [c for c in (cost, sales) if c]:
            if not db.execute("SELECT 1 FROM accounts WHERE code=?", (code,)).fetchone(): raise ValueError(f"Account {code} was not found in the chart of accounts")
        for item_id in ids:
            if cost: db.execute("UPDATE inventory_items SET cost_account=? WHERE id=?", (cost, item_id))
            if sales: db.execute("UPDATE inventory_items SET sales_account=? WHERE id=?", (sales, item_id))
        db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                   (user_id, "update", "inventory_item_accounts", json.dumps({"items": ids, "cost_account": cost, "sales_account": sales}), utcnow()))
    return {"updated": len(ids)}


def find_or_create_item(database, name, unit="unit", code=None, user_id=None, supplier_id=None):
    """Used by the purchase import: an item that does not exist yet is created automatically.
    2.9.51: a name written differently (spaces, case, dashes) finds the existing item instead of creating a second one."""
    with database.connect() as db:
        row = db.execute("SELECT * FROM inventory_items WHERE (sku=? AND ?<>'') OR lower(name)=lower(?) ORDER BY id LIMIT 1", (str(code or "").upper(), str(code or ""), str(name or ""))).fetchone()
        if not row:
            key = item_name_key(name)
            if key:
                for candidate in db.execute("SELECT * FROM inventory_items ORDER BY COALESCE(active,1) DESC,id"):
                    if item_name_key(candidate["name"]) == key: row = candidate; break
    if row: return dict(row)
    created = save_item(database, {"sku": code or "", "name": name, "unit": unit or "unit", "supplier_id": supplier_id}, user_id)
    return {**created, "created": True}  # 2.9.86: the screens tell the user which items are new


# ---------------------------------------------------------------- physical inventory
def count_sheet(database, warehouse_id, date):
    """System quantity of every active item in a warehouse on a date, ready for counting."""
    date = iso_date(date); state = run_costing(database, date); warehouse = int(warehouse_id)
    return [{"item_id": i["id"], "sku": i["sku"], "name": i["name"], "unit": i["unit"], "category": i.get("category") or "", "location": i.get("location") or "",
             "system_qty": float(state.get(i["id"], {}).get("by_warehouse", {}).get(warehouse, ZERO)), "unit_cost": float(state.get(i["id"], {}).get("avg", ZERO))}
            for i in list_items(database, include_inactive=False)]


def save_count(database, header, lines, user_id, count_id=None, post=False):
    date = iso_date(header.get("count_date"), "Count date"); warehouse = int(header.get("warehouse_id") or 0)
    if not warehouse: raise ValueError("Choose the warehouse")
    stock = {row["item_id"]: row for row in count_sheet(database, warehouse, date)}
    clean = []
    for line in lines or []:
        if line.get("counted") in (None, ""): continue
        counted = _d(line["counted"])
        if counted < 0: raise ValueError(f"{line.get('sku')}: the counted quantity cannot be negative")
        item_id = int(line["item_id"])
        if item_id not in stock: raise ValueError(f"Item {item_id} is not on the stock sheet")
        clean.append({"item_id": item_id, "sku": line.get("sku"), "counted": str(counted),
                      "system_qty": str(stock[item_id]["system_qty"]), "unit_cost": str(stock[item_id]["unit_cost"])})
    with database.connect() as db:
        if count_id:
            row = db.execute("SELECT * FROM physical_counts WHERE id=?", (int(count_id),)).fetchone()
            if not row: raise KeyError("Count not found")
            if row["status"] == "posted": raise ValueError("This count is already posted to the stock")
            db.execute("UPDATE physical_counts SET count_date=?,warehouse_id=?,lines=?,notes=? WHERE id=?", (date, warehouse, json.dumps(clean),
                    header.get("notes"), int(count_id))); saved = int(count_id)
        else:
            numbers = [int(r["number"].rsplit("-", 1)[-1]) for r in db.execute("SELECT number FROM physical_counts WHERE number LIKE ?",
                    (f"PHC-{date[:4]}-%",)) if r["number"].rsplit("-", 1)[-1].isdigit()]
            saved = db.execute("INSERT INTO physical_counts(number,count_date,warehouse_id,lines,notes,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                (f"PHC-{date[:4]}-{max(numbers, default=0) + 1:06d}", date, warehouse, json.dumps(clean), header.get("notes"), user_id, utcnow())).lastrowid
    if post:
        system = {l["item_id"]: l for l in count_sheet(database, warehouse, date)}; gains = []; losses = []
        for line in clean:
            difference = _d(line["counted"]) - _d(system.get(line["item_id"], {}).get("system_qty", 0))
            if difference > 0: gains.append({"item_id": line["item_id"], "quantity": difference, "unit_cost": system.get(line["item_id"], {}).get("unit_cost", 0) or 0})
            elif difference < 0: losses.append({"item_id": line["item_id"], "quantity": -difference})
        numbers = []
        with database.connect() as db: number = db.execute("SELECT number FROM physical_counts WHERE id=?", (saved,)).fetchone()["number"]
        if gains: numbers.append(save_document(database, {"doc_type": "adjustment_in", "doc_date": date, "warehouse_id": warehouse, "reference": number,
                "notes": f"Physical count {number}"}, gains, user_id)["number"])
        if losses: numbers.append(save_document(database, {"doc_type": "adjustment_out", "doc_date": date, "warehouse_id": warehouse, "reference": number,
                "notes": f"Physical count {number}"}, losses, user_id)["number"])
        voucher = _post_count_voucher(database, number, date, system, clean, user_id)  # 2.9.97: the count difference in the journal
        if voucher: numbers.append(voucher)
        with database.connect() as db: db.execute("UPDATE physical_counts SET status='posted',adjustment_numbers=? WHERE id=?", (", ".join(numbers), saved))
    return get_count(database, saved)


def _post_count_voucher(database, number, date, system, lines, user_id):
    """2.9.97: the physical count in the journal. Only the DIFFERENCE found by the count, valued at the item's cost on the
    count date, per stock account: counted more -> Dr stock (37...) / Cr stock variation (6052...); counted less -> Dr stock
    variation / Cr stock. The month-end Stock Variation later starts from the ledger, so nothing is counted twice."""
    with database.connect() as db:
        accounts = {row["id"]: (row["stock_account"] or STOCK_ACCOUNT) for row in db.execute("SELECT id,stock_account FROM inventory_items")}
    by_account = {}
    for line in lines:
        before = system.get(line["item_id"], {})
        difference = _d(line["counted"]) - _d(before.get("system_qty", 0))
        value = (difference * _d(before.get("unit_cost", 0))).quantize(Decimal("0.01"))
        if value: by_account[accounts.get(line["item_id"], STOCK_ACCOUNT)] = by_account.get(accounts.get(line["item_id"], STOCK_ACCOUNT), ZERO) + value
    currency = settings(database)["currency"]; entries = []
    for stock, value in sorted(by_account.items()):
        if not value: continue
        variation = stock_link(stock)[2]
        debit, credit = (stock, variation) if value > 0 else (variation, stock)
        entries += [{"account_code": debit, "line_currency": currency, "side": "D", "amount": str(abs(value)), "description": f"Physical count {number}"},
                    {"account_code": credit, "line_currency": currency, "side": "C", "amount": str(abs(value)), "description": f"Physical count {number}"}]
    if not entries: return None
    gain = sum((v for v in by_account.values() if v > 0), ZERO); loss = -sum((v for v in by_account.values() if v < 0), ZERO)
    voucher = database.save_journal_voucher({"entry_date": display_date(date), "voucher_type": "06", "currency": currency,
                                             "description": f"PHYSICAL COUNT {number}: surplus {gain:,.2f} / shortage {loss:,.2f} {currency}"}, entries, user_id)
    return voucher["voucher"]["entry_number"]


def get_count(database, count_id):
    with database.connect() as db:
        row = db.execute("SELECT c.*,w.code warehouse_code FROM physical_counts c JOIN warehouses w ON w.id=c.warehouse_id WHERE c.id=?", (int(count_id),)).fetchone()
    if not row: raise KeyError("Count not found")
    result = dict(row); result["lines"] = json.loads(result["lines"] or "[]"); return result


def list_counts(database):
    with database.connect() as db:
        return [dict(r) for r in db.execute("SELECT c.id,c.number,c.count_date,c.status,c.adjustment_numbers,w.code warehouse_code FROM physical_counts c JOIN warehouses w ON w.id=c.warehouse_id ORDER BY c.id DESC")]



# 2.9.94: the reports live in inventory_reports.py; the names stay available here for every caller
# (loaded on first use, so either module can be imported first).
_REPORT_NAMES = frozenset(("AGEING_BUCKETS", "ANALYSIS_DIMENSIONS", "MOVEMENT_DIMENSIONS", "WarehouseChoice", "_ageing_data", "_bucket_labels",
                           "_buckets", "_names", "additional_inventory_report", "ageing_report", "build_report", "fifo_layers",
                           "inventory_analysis", "inventory_health", "summary_report"))


def __getattr__(name):
    if name in _REPORT_NAMES:
        import inventory_reports
        return getattr(inventory_reports, name)
    raise AttributeError(f"module 'inventory' has no attribute {name!r}")
