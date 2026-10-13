"""Production (2.9.65): recipes (bills of materials) and production orders.

A recipe says what one batch of a finished product needs: for example 10 panels = 20 m2 of sheet + 4 kg of glue,
plus an extra cost per unit (labour, energy...). A production order takes the materials out of a warehouse and
puts the finished product in, in one stock document (type "production", number PRD-YYYY-000001):
- the quantities come from the recipe, scaled to the quantity produced; for a special order they can be changed
  on the order itself, the recipe stays as it is;
- the finished product costs the materials at their real cost (average or FIFO, as the company setting) plus the
  extra cost. If an earlier purchase is entered later, the cost follows by itself (the costing engine recomputes it).

Accounting: the inventory follows the periodic method of the Lebanese chart (inventory.py). Moving materials into a
finished product is inside the stock, so no journal entry is needed; the stock value at year end (37 / 6052) includes
the finished products at their production cost.
"""
from __future__ import annotations

import json
from decimal import Decimal

import inventory
from database import display_date, iso_date, utcnow
from inventory import ZERO, _d

INPUT, OUTPUT = "production_input", "production_output"


def _item(db, value, label="Item"):
    text = str(value or "").strip()
    if not text: raise ValueError(f"Choose the {label.lower()}")
    code = text.split(" - ", 1)[0].strip().upper()
    row = db.execute("SELECT * FROM inventory_items WHERE sku=? OR id=?", (code, int(text) if text.isdigit() else -1)).fetchone()
    if not row: raise ValueError(f"{label} {text} was not found")
    return row


def _warehouse(db, value, label="warehouse"):
    text = str(value or "MAIN").split(" - ", 1)[0].strip()
    row = db.execute("SELECT * FROM warehouses WHERE id=? OR code=?", (int(text) if text.isdigit() else -1, text)).fetchone()
    if not row: raise ValueError(f"Choose the {label}")
    return row


# ---------------------------------------------------------------- recipes
def list_boms(database):
    with database.connect() as db:
        rows = [dict(r) for r in db.execute("""SELECT b.*,i.sku,i.name,i.unit,(SELECT COUNT(*) FROM bom_lines l WHERE l.bom_id=b.id) components
            FROM bom_headers b JOIN inventory_items i ON i.id=b.item_id ORDER BY i.sku""")]
    for row in rows:
        row["output_qty"] = float(_d(row["output_qty"])); row["overhead_per_unit"] = float(_d(row["overhead_per_unit"]))
    return rows


def get_bom(database, item):
    with database.connect() as db:
        product = _item(db, item, "Product")
        header = db.execute("SELECT * FROM bom_headers WHERE item_id=?", (product["id"],)).fetchone()
        lines = [] if not header else [dict(r) for r in db.execute("""SELECT l.quantity,l.line_no,i.id component_id,i.sku,i.name,i.unit FROM bom_lines l
            JOIN inventory_items i ON i.id=l.component_id WHERE l.bom_id=? ORDER BY l.line_no,l.id""", (header["id"],))]
    for line in lines: line["quantity"] = float(_d(line["quantity"]))
    return {"item_id": product["id"], "sku": product["sku"], "name": product["name"], "unit": product["unit"], "exists": bool(header),
            "id": header["id"] if header else None, "output_qty": float(_d(header["output_qty"])) if header else 1.0,
            "overhead_per_unit": float(_d(header["overhead_per_unit"])) if header else 0.0, "notes": (header["notes"] if header else "") or "",
            "lines": lines}


def save_bom(database, item, user_id):
    output_qty = _d(item.get("output_qty") or 1); overhead = _d(item.get("overhead_per_unit"))
    if output_qty <= 0: raise ValueError("The recipe must make a quantity above zero")
    if overhead < 0: raise ValueError("The extra cost per unit cannot be negative")
    with database.connect() as db:
        product = _item(db, item.get("item_id") or item.get("sku"), "Product")
        lines = []; seen = set()
        for index, line in enumerate(item.get("lines") or [], 1):
            if not str(line.get("sku") or line.get("component_id") or "").strip(): continue
            component = _item(db, line.get("component_id") or line.get("sku"), f"Line {index}: material")
            qty = _d(line.get("quantity"))
            if qty <= 0: raise ValueError(f"Line {index}: the quantity of {component['sku']} must be above zero")
            if component["id"] == product["id"]: raise ValueError(f"Line {index}: a product cannot be a material of itself")
            if component["id"] in seen: raise ValueError(f"Line {index}: {component['sku']} is already in the recipe - put the total on one line")
            seen.add(component["id"]); lines.append((component["id"], qty))
        if not lines: raise ValueError("Add at least one material to the recipe")
        _check_no_loop(db, product["id"], [c for c, _q in lines])
        existing = db.execute("SELECT id FROM bom_headers WHERE item_id=?", (product["id"],)).fetchone()
        values = (str(output_qty), str(overhead), str(item.get("notes") or "").strip() or None, 1 if item.get("active", True) else 0, user_id, utcnow())
        if existing:
            bom_id = existing["id"]
            db.execute("UPDATE bom_headers SET output_qty=?,overhead_per_unit=?,notes=?,active=?,updated_by=?,updated_at=? WHERE id=?", values + (bom_id,))
            db.execute("DELETE FROM bom_lines WHERE bom_id=?", (bom_id,))
        else:
            bom_id = db.execute("INSERT INTO bom_headers(output_qty,overhead_per_unit,notes,active,updated_by,updated_at,item_id) VALUES(?,?,?,?,?,?,?)",
                                values + (product["id"],)).lastrowid
        db.executemany("INSERT INTO bom_lines(bom_id,component_id,quantity,line_no) VALUES(?,?,?,?)",
                       [(bom_id, component, str(qty), position) for position, (component, qty) in enumerate(lines, 1)])
        db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                   (user_id, "save", "recipe", bom_id, json.dumps({"product": product["sku"], "materials": len(lines)}), utcnow()))
    return get_bom(database, product["id"])


def _check_no_loop(db, product_id, components):
    """A material may itself be made from a recipe, but never (directly or further down) from the product."""
    recipes = {}
    for row in db.execute("SELECT b.item_id,l.component_id FROM bom_headers b JOIN bom_lines l ON l.bom_id=b.id"):
        recipes.setdefault(row["item_id"], set()).add(row["component_id"])
    recipes[product_id] = set(components)
    stack = list(components); seen = set()
    while stack:
        current = stack.pop()
        if current == product_id: raise ValueError("This recipe would go round in a circle (a material is made from this product)")
        if current in seen: continue
        seen.add(current); stack.extend(recipes.get(current, ()))


def delete_bom(database, item, user_id):
    with database.connect() as db:
        product = _item(db, item, "Product")
        row = db.execute("SELECT id FROM bom_headers WHERE item_id=?", (product["id"],)).fetchone()
        if not row: raise KeyError("Recipe not found")
        db.execute("DELETE FROM bom_lines WHERE bom_id=?", (row["id"],)); db.execute("DELETE FROM bom_headers WHERE id=?", (row["id"],))
        db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                   (user_id, "delete", "recipe", row["id"], json.dumps({"product": product["sku"]}), utcnow()))
    return {"deleted": product["sku"]}


def plan(database, item, quantity, warehouse=None, date=None):
    """The materials for `quantity` of the product, from its recipe, with what is on hand and the expected cost."""
    quantity = _d(quantity)
    if quantity <= 0: raise ValueError("Enter the quantity to produce")
    bom = get_bom(database, item)
    if not bom["exists"]: raise ValueError(f"{bom['sku']} has no recipe yet: add it under Production > Recipes")
    factor = quantity / _d(bom["output_qty"])
    state = inventory.run_costing(database, iso_date(date) if date else None)
    with database.connect() as db: wh = _warehouse(db, warehouse) if warehouse else None
    lines = []
    for line in bom["lines"]:
        data = state.get(line["component_id"], {})
        need = (_d(line["quantity"]) * factor).quantize(Decimal("0.000001")).normalize()
        on_hand = data.get("by_warehouse", {}).get(wh["id"], ZERO) if wh else data.get("qty", ZERO)
        lines.append({"sku": line["sku"], "name": line["name"], "unit": line["unit"], "quantity": float(need), "on_hand": float(on_hand),
                      "unit_cost": float(data.get("avg", ZERO)), "short": float(max(ZERO, need - on_hand))})
    return {"item": bom["sku"], "name": bom["name"], "unit": bom["unit"], "quantity": float(quantity),
            "extra_cost": float(_d(bom["overhead_per_unit"]) * quantity), "lines": lines}


# ---------------------------------------------------------------- production orders
def save_order(database, header, lines, user_id, document_id=None):
    """Save a production order. lines = the materials actually used [{sku, quantity}] (from the recipe, changed if needed)."""
    date = iso_date(header.get("doc_date"), "Date"); database._assert_period_open(date)
    quantity = _d(header.get("quantity")); extra = _d(header.get("extra_cost"))
    if quantity <= 0: raise ValueError("Enter the quantity produced")
    if extra < 0: raise ValueError("The extra cost cannot be negative")
    with database.connect() as db:
        product = _item(db, header.get("item_id") or header.get("sku"), "Product")
        source = _warehouse(db, header.get("warehouse_id"), "warehouse of the materials")
        target = _warehouse(db, header.get("to_warehouse_id") or source["id"], "warehouse of the finished product")
        materials = {}; order = []
        for index, line in enumerate(lines or [], 1):
            if not str(line.get("sku") or line.get("item_id") or "").strip(): continue
            component = _item(db, line.get("item_id") or line.get("sku"), f"Line {index}: material")
            qty = _d(line.get("quantity"))
            if qty < 0: raise ValueError(f"Line {index}: quantity cannot be negative")
            if not qty: continue
            if component["id"] == product["id"]: raise ValueError(f"Line {index}: the product cannot be used to make itself")
            if component["id"] not in materials: order.append(component)
            materials[component["id"]] = materials.get(component["id"], ZERO) + qty
        if not materials: raise ValueError("Add the materials used (at least one line with a quantity)")
        if document_id:
            old = db.execute("SELECT * FROM stock_documents WHERE id=?", (int(document_id),)).fetchone()
            if not old or old["doc_type"] != "production": raise KeyError("Production order not found")
            database._assert_period_open(old["doc_date"])
    # enough material in the warehouse on that date (unless the user confirmed negative stock)
    state = inventory.run_costing(database, date, exclude_document_id=int(document_id) if document_id else None)
    short = []
    for component in order:
        available = state.get(component["id"], {}).get("by_warehouse", {}).get(source["id"], ZERO)
        if materials[component["id"]] > available:
            short.append(f"Not enough {component['sku']} in {source['code']} on {display_date(date)}: available {available:,.3f}, needed {materials[component['id']]:,.3f}")
    if short and not inventory.negative_allowed(): raise inventory.NegativeStock(inventory._negative_message(short))
    with database.connect() as db:
        project_id = inventory._optional_id(db, "projects", header.get("project_id")); branch_id = inventory._optional_id(db, "branches", header.get("branch_id"))
        reference = str(header.get("reference") or "").strip() or None; notes = str(header.get("notes") or "").strip() or None
        if document_id:
            saved = int(document_id); number = old["number"]
            db.execute("DELETE FROM stock_movements WHERE document_id=?", (saved,))
            db.execute("""UPDATE stock_documents SET doc_date=?,warehouse_id=?,to_warehouse_id=?,reference=?,notes=?,project_id=?,branch_id=?,extra_cost=? WHERE id=?""",
                       (date, source["id"], target["id"], reference, notes, project_id, branch_id, str(extra), saved))
        else:
            number = str(header.get("number") or "").strip() or inventory.next_number(database, "production", date)
            saved = db.execute("""INSERT INTO stock_documents(number,doc_type,doc_date,warehouse_id,to_warehouse_id,reference,notes,created_by,created_at,project_id,branch_id,extra_cost)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (number, "production", date, source["id"], target["id"], reference, notes, user_id, utcnow(), project_id, branch_id, str(extra))).lastrowid
        # materials first, then the product: the costing engine needs the materials' cost before it values the product
        for position, component in enumerate(order, 1):
            db.execute("""INSERT INTO stock_movements(item_id,movement_date,quantity,unit_cost,source_type,source_id,warehouse_id,document_id,movement_type,line_no)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (component["id"], date, str(-materials[component["id"]]), "0", "stock", saved, source["id"], saved, INPUT, position))
        db.execute("""INSERT INTO stock_movements(item_id,movement_date,quantity,unit_cost,source_type,source_id,warehouse_id,document_id,movement_type,line_no)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", (product["id"], date, str(quantity), "0", "stock", saved, target["id"], saved, OUTPUT, len(order) + 1))
        inventory._assert_nonnegative_history(db)
    _store_costs(database)
    with database.connect() as db:
        db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                   (user_id, "save", "production", saved, json.dumps({"number": number, "product": product["sku"], "quantity": str(quantity)}), utcnow()))
    return get_order(database, saved)


def _store_costs(database):
    """Write the cost the engine finds on every production line, so documents and exports show it."""
    costs = {}
    def record(row, unit, _value):
        if row.get("movement_type") == INPUT: costs[row["id"]] = unit
        elif row.get("movement_type") == OUTPUT: costs[row["id"]] = _d(row["unit_cost"])
    inventory.run_costing(database, callback=record)
    if costs:
        with database.connect() as db:
            db.executemany("UPDATE stock_movements SET unit_cost=? WHERE id=?", [(str(cost.quantize(Decimal("0.000001"))), movement_id) for movement_id, cost in costs.items()])


def get_order(database, document_id):
    doc = inventory.get_document(database, document_id)
    if doc["doc_type"] != "production": raise KeyError("Production order not found")
    costs = {}
    def record(row, unit, _value):
        if row["document_id"] == doc["id"]: costs[row["id"]] = _d(row["unit_cost"]) if row.get("movement_type") == OUTPUT else unit
    inventory.run_costing(database, doc["doc_date"], callback=record)
    materials = []; product = None
    for line in doc["lines"]:
        cost = costs.get(line["id"], _d(line["unit_cost"]))
        entry = {"sku": line["sku"], "name": line["name"], "unit": line["unit"], "quantity": line["quantity"], "unit_cost": float(cost),
                 "value": float((cost * _d(line["quantity"])).quantize(Decimal("0.01")))}
        if line.get("movement_type") == OUTPUT: product = entry
        else: materials.append(entry)
    material_cost = sum((_d(m["value"]) for m in materials), ZERO); extra = _d(doc.get("extra_cost"))
    with database.connect() as db:
        target = db.execute("SELECT code,name FROM warehouses WHERE id=?", (doc.get("to_warehouse_id") or doc["warehouse_id"],)).fetchone()
    doc.update(product=product, materials=materials, material_cost=float(material_cost), extra_cost=float(extra),
               total_cost=float(material_cost + extra), to_warehouse_code=target["code"] if target else "", to_warehouse_name=target["name"] if target else "")
    return doc


def list_orders(database):
    with database.connect() as db:
        rows = [dict(r) for r in db.execute("""SELECT d.id,d.number,d.doc_date,d.reference,d.notes,i.sku,i.name,m.id movement_id,m.quantity,d.extra_cost
            FROM stock_documents d JOIN stock_movements m ON m.document_id=d.id AND m.movement_type='production_output'
            JOIN inventory_items i ON i.id=m.item_id WHERE d.doc_type='production' ORDER BY d.doc_date DESC,d.id DESC""")]
    costs = {}
    def record(row, _unit, _value):
        if row.get("movement_type") == OUTPUT: costs[row["id"]] = _d(row["unit_cost"])
    if rows: inventory.run_costing(database, callback=record)
    for row in rows:
        cost = costs.get(row.pop("movement_id"), ZERO); qty = _d(row["quantity"])
        row.update(quantity=float(qty), unit_cost=float(cost), extra_cost=float(_d(row.get("extra_cost"))), total_cost=float((qty * cost).quantize(Decimal("0.01"))))
    return rows


def report(database, date_from, date_to):
    """Production report: what was made (cost per unit) and what was used, between two dates."""
    date_from = iso_date(date_from); date_to = iso_date(date_to)
    made = {}; used = {}; orders = {}
    def record(row, unit, _value):
        if row["doc_type"] != "production" or not (date_from <= row["doc_date"] <= date_to): return
        qty = abs(_d(row["quantity"]))
        if row.get("movement_type") == OUTPUT:
            cost = _d(row["unit_cost"]); orders[row["document_id"]] = [display_date(row["doc_date"]), row["number"], row["item_id"], qty, cost, _d(row.get("extra_cost"))]
            entry = made.setdefault(row["item_id"], [ZERO, ZERO]); entry[0] += qty; entry[1] += qty * cost
        else:
            entry = used.setdefault(row["item_id"], [ZERO, ZERO]); entry[0] += qty; entry[1] += qty * unit
    inventory.run_costing(database, date_to, callback=record)
    items, _warehouses = inventory._names(database); currency = inventory.settings(database)["currency"]
    q = lambda value, places="0.01": value.quantize(Decimal(places))
    order_rows = [[d, n, items[i]["sku"], items[i]["name"], qty, q(cost, "0.0001"), q(extra), q(qty * cost)] for d, n, i, qty, cost, extra in orders.values()]
    made_rows = [[items[i]["sku"], items[i]["name"], items[i]["unit"], qty, q(value / qty, "0.0001") if qty else ZERO, q(value)] for i, (qty,
            value) in sorted(made.items(), key=lambda p: items[p[0]]["sku"])]
    used_rows = [[items[i]["sku"], items[i]["name"], items[i]["unit"], qty, q(value)] for i, (qty, value) in sorted(used.items(), key=lambda p: items[p[0]]["sku"])]
    total = lambda rows, column: sum((r[column] for r in rows), ZERO)
    if made_rows: made_rows.append(["TOTAL", "", "", "", "", total(made_rows, 5)])
    if used_rows: used_rows.append(["TOTAL", "", "", "", total(used_rows, 4)])
    period = f"{display_date(date_from)} to {display_date(date_to)}"
    return {"title": "Production Report", "meta": [f"Period: {period}", f"Currency: {currency}"], "sections": [
        {"heading": f"Production orders | {period}", "headers": ["Date", "Order", "Product", "Name", "Quantity", "Unit Cost", "Extra Cost", "Total Cost"],
         "rows": order_rows or [["No production in this period"] + [""] * 7], "total_rows": []},
        {"heading": "Products made", "headers": ["Product", "Name", "Unit", "Quantity", "Average Unit Cost", f"Value ({currency})"],
         "rows": made_rows or [["-"] + [""] * 5], "total_rows": [len(made_rows) - 1] if made_rows else []},
        {"heading": "Materials used", "headers": ["Material", "Name", "Unit", "Quantity", f"Value ({currency})"],
         "rows": used_rows or [["-"] + [""] * 4], "total_rows": [len(used_rows) - 1] if used_rows else []}]}
