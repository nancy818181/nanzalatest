"""Inventory reports (split from inventory.py in 2.9.94, no change in behaviour): stock reports, analysis,
health, ageing and summary. inventory.py re-exports every name, so `inventory.build_report(...)` keeps working."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from database import display_date, iso_date
from inventory import (DOC_TYPES, ZERO, _d, _movements, _reported_warehouse_values, count_sheet, list_items, run_costing,
                       settings, stock_ledger_check)


def _names(database):
    with database.connect() as db:
        items = {r["id"]: dict(r) for r in db.execute("SELECT * FROM inventory_items")}
        warehouses = {r["id"]: dict(r) for r in db.execute("SELECT * FROM warehouses")}
    return items, warehouses


class WarehouseChoice:
    """2.9.51: the warehouse filter of the reports - none (all warehouses), one, or any combination."""

    def __init__(self, value):
        values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
        self.ids = frozenset(int(v) for v in values if str(v if v is not None else "").strip().isdigit())

    def __bool__(self): return bool(self.ids)

    def has(self, warehouse_id): return not self.ids or warehouse_id in self.ids

    def pick(self, by_warehouse):
        """Sum of a {warehouse_id: amount} dict over the chosen warehouses."""
        return sum((amount for wid, amount in (by_warehouse or {}).items() if wid in self.ids), ZERO)

    def qty(self, data):
        return self.pick(data.get("by_warehouse", {})) if self.ids else data.get("qty", ZERO)

    def label(self, warehouses):
        return ", ".join(warehouses[w]["code"] for w in sorted(self.ids) if w in warehouses)


def build_report(database, report, options):
    options = dict(options or {}); inv = settings(database); method = options.get("method") or inv["method"]; currency = inv["currency"]
    date_to = iso_date(options["date_to"]) if options.get("date_to") else datetime.now().strftime("%Y-%m-%d")
    date_from = iso_date(options["date_from"]) if options.get("date_from") else f"{date_to[:4]}-01-01"
    warehouse = WarehouseChoice(options.get("warehouse_id"))
    items, warehouses = _names(database); company = database.settings(); sections = []
    first_item=items.get(int(options["item_id"])) if options.get("item_id") else None
    last_item=items.get(int(options["item_to_id"])) if options.get("item_to_id") else first_item
    if options.get("item_id") and not first_item: raise ValueError("Choose a valid Item From")
    if options.get("item_to_id") and not last_item: raise ValueError("Choose a valid Item To")
    if first_item and last_item and first_item["sku"]>last_item["sku"]: raise ValueError("Item From must be before Item To")
    def many(key):
        """2.9.50: a filter holds one value or a list of values (any combination)."""
        value = options.get(key)
        values = value if isinstance(value, (list, tuple, set)) else [value]
        return [str(v).strip() for v in values if str(v if v is not None else "").strip()]
    def many_ids(key): return {int(v) for v in many(key) if v.isdigit()}
    filters = [f"{label}: {', '.join(many(key))}" for key, label in (("category", "Category"), ("subcategory", "Subcategory"), ("brand", "Brand"), ("unit", "Unit"), ("supplier_name", "Supplier"),
               ("project_name", "Project"), ("branch_name", "Branch")) if many(key)]
    brand_filter = {v.casefold() for v in many("brand")}
    project_filter = many_ids("project_id")
    branch_filter = many_ids("branch_id")
    def document_ok(row):
        """Project / branch of the stock document (movement reports)."""
        return (not project_filter or row.get("project_id") in project_filter) and (not branch_filter or row.get("branch_id") in branch_filter)
    wanted = lambda item_id: not options.get("item_id") or int(options["item_id"]) == item_id
    category = set(many("category")); subcategory = set(many("subcategory"))
    unit_filter = set(many("unit")); supplier_filter = set(many("supplier_id")); supplier_names = set(many("supplier_name"))
    listed = {i["id"]: i for i in list_items(database)} if supplier_filter else {}
    def in_category(item_id):
        item = items[item_id]
        if first_item and not (first_item["sku"]<=item["sku"]<=last_item["sku"]): return False
        if category and (item.get("category") or "") not in category: return False
        if subcategory and (item.get("subcategory") or "") not in subcategory: return False
        if unit_filter and (item.get("unit") or "") not in unit_filter: return False
        if brand_filter and (item.get("brand") or "").casefold() not in brand_filter: return False
        if supplier_filter:
            data = listed.get(item_id, {})
            if str(item.get("supplier_id") or "") not in supplier_filter and data.get("supplier_name") not in supplier_names: return False
        return True
    if report in ("turnover", "supplier_stock", "count_variances"):
        return additional_inventory_report(database, report, options, items, warehouses, in_category, currency, method, date_from, date_to, warehouse, company)
    if report == "analysis3d":
        return inventory_analysis(database, options, items, warehouses, in_category, currency, method, date_from, date_to, warehouse, company)
    if report == "health":
        return inventory_health(database, options, items, in_category, currency, method, date_to, warehouse, company)
    if report == "valuation":
        state = run_costing(database, date_to, method)
        headers = ["Item Code", "Item", "Category", "Unit", "Quantity", f"Unit Cost ({currency})", f"Stock Value ({currency})", "Sales Price", "Value at Sales Price", "Reorder Level", "Status"]
        rows = []; total = ZERO; sales_total = ZERO; quantities_by_unit = {}
        for item_id, item in sorted(items.items(), key=lambda pair: pair[1]["sku"]):
            if not in_category(item_id): continue
            data = state.get(item_id, {"qty": ZERO, "avg": ZERO, "by_warehouse": {}, "warehouse_value": {}})
            qty = warehouse.qty(data)
            if not qty and not options.get("include_zero"): continue
            # Round warehouse lines before adding so displayed warehouse totals reconcile to displayed item totals.
            values = _reported_warehouse_values(data) if data["qty"] else {}
            value = warehouse.pick(values) if warehouse else sum(values.values(), ZERO)
            unit_cost = data["avg"] if not warehouse else (warehouse.pick(data["warehouse_value"]) / qty if qty else ZERO)
            price = _d(item.get("sales_price")); reorder = _d(item.get("reorder_level"))
            total += value; sales_total += qty * price
            quantities_by_unit[item["unit"]]=quantities_by_unit.get(item["unit"],ZERO)+qty
            rows.append([item["sku"], item["name"], item.get("category") or "", item["unit"], qty, unit_cost.quantize(Decimal("0.0001")), value, price,
                    (qty * price).quantize(Decimal("0.01")), reorder,
                         "Reorder" if reorder and qty <= reorder else "OK"])
        # group by category with a subtotal per category
        grouped = []; totals_index = []
        for name in sorted({r[2] or "(no category)" for r in rows}):
            members = [r for r in rows if (r[2] or "(no category)") == name]
            grouped += members
            grouped.append([f"Subtotal {name}", f"{len(members)} item(s)", "", "", sum((m[4] for m in members), ZERO), "", sum((m[6] for m in members), ZERO), "",
                            sum((m[8] for m in members), ZERO), "", ""]); totals_index.append(len(grouped) - 1)
        count = len(rows); rows = grouped
        rows.append(["TOTAL", f"{count} item(s)", "", "", "", "", total, "", sales_total.quantize(Decimal("0.01")), "", ""])
        title = "Stock Valuation"; sections.append({"heading": f"Stock valuation at {display_date(date_to)} - {'weighted average' if method != 'fifo' else 'FIFO'}" + (f" - {warehouse.label(warehouses)}" if warehouse else " - all warehouses"),
                                                     "headers": headers, "rows": rows, "total_rows": totals_index + [len(rows) - 1]})
        if not warehouse and len(warehouses) > 1:
            by_wh = [[w["code"], w["name"], sum((_reported_warehouse_values(state[i]).get(wid, ZERO)
                      for i in state if in_category(i)), ZERO)] for wid, w in warehouses.items()]
            sections.append({"heading": "Value by warehouse", "headers": ["Warehouse", "Name", f"Value ({currency})"], "rows": by_wh, "total_rows": []})
        sections.append({"heading":"Total stock quantity by unit", "headers":["Unit","Total stock quantity"],
                         "rows":[[unit,quantity] for unit,quantity in sorted(quantities_by_unit.items())],"total_rows":[]})
    elif report == "stock_card":
        first = items.get(int(options.get("item_id") or 0))
        if not first: raise ValueError("Choose Stock Card Item From")
        last = items.get(int(options.get("item_to_id") or options["item_id"]))
        if not last: raise ValueError("Choose a valid Stock Card Item To")
        if first["sku"] > last["sku"]: raise ValueError("Stock Card Item From must be before Item To")
        selected = [item_id for item_id, item in sorted(items.items(), key=lambda pair: pair[1]["sku"])
                    if first["sku"] <= item["sku"] <= last["sku"] and in_category(item_id)]
        cards = {item_id: {"opening_qty": ZERO, "opening_value": ZERO, "lines": []} for item_id in selected}
        def record(row, unit, value):
            card = cards.get(row["item_id"])
            if card is None or not warehouse.has(row["warehouse_id"]): return
            qty = _d(row["quantity"]); cost_value = qty * (_d(row["unit_cost"]) if qty > 0 and row["doc_type"] != "transfer" else unit)
            if row["doc_date"] < date_from:
                card["opening_qty"] += qty; card["opening_value"] += cost_value; return
            card["lines"].append([display_date(row["doc_date"]), row["number"], DOC_TYPES[row["doc_type"]][1], row.get("warehouse_code") or "", row.get("party_name") or row.get("reference") or "",
                                  qty if qty > 0 else "", -qty if qty < 0 else "",
                                          (unit if qty < 0 or row["doc_type"] == "transfer" else _d(row["unit_cost"])).quantize(Decimal("0.0001")),
                                          cost_value.quantize(Decimal("0.01"))])
        run_costing(database, date_to, method, record)
        closing_state = run_costing(database, date_to, method)
        card_totals={}
        for item_id in selected:
            card = cards[item_id]; qty_balance = card["opening_qty"]; value_balance = card["opening_value"]
            rows = [["", "", "Opening balance", "", "", "", "", "", value_balance.quantize(Decimal("0.01")), qty_balance, value_balance.quantize(Decimal("0.01"))]]
            total_in = ZERO; total_out = ZERO
            for line in card["lines"]:
                qty = _d(line[5] or 0) - _d(line[6] or 0); qty_balance += qty; value_balance += line[8]
                total_in += _d(line[5] or 0); total_out += _d(line[6] or 0)
                rows.append(line + [qty_balance, value_balance.quantize(Decimal("0.01"))])
            closing = closing_state.get(item_id, {})
            target_value = (warehouse.pick(_reported_warehouse_values(closing)) if warehouse and closing
                            else closing.get("value", ZERO).quantize(Decimal("0.01")))
            difference = target_value - value_balance.quantize(Decimal("0.01"))
            if difference:
                value_balance += difference
                label = ("Company-wide average revaluation" if method != "fifo" else "Display rounding adjustment")
                rows.append(["", "", f"{label} (not a stock movement)", "", "",
                             "", "", "", difference, qty_balance, value_balance.quantize(Decimal("0.01"))])
            rows.append(["", "", "TOTAL / CLOSING", "", "", total_in, total_out, "", "", qty_balance, value_balance.quantize(Decimal("0.01"))])
            item = items[item_id]
            unit=item["unit"]; card_totals[unit]=card_totals.get(unit,ZERO)+qty_balance
            sections.append({"heading": f"{item['sku']} - {item['name']} ({item['unit']}) | {display_date(date_from)} to {display_date(date_to)}" + (f" - {warehouse.label(warehouses)}" if warehouse else ""),
                             "headers": ["Date", "Document", "Type", "Warehouse", "Party / Reference", "In", "Out", f"Unit Cost ({currency})", "Value", "Balance Qty", "Balance Value"],
                             "rows": rows, "total_rows": [0, len(rows) - 1]})
        title = "Stock Cards" if options.get("item_to_id") else "Stock Card"
        sections.append({"heading":"Total closing stock by unit", "headers":["Unit","Total closing quantity"],
                         "rows":[[unit,quantity] for unit,quantity in sorted(card_totals.items())],"total_rows":[]})
    elif report == "movements":
        rows = []
        def record(row, unit, value):
            if row["doc_date"] < date_from or not wanted(row["item_id"]) or not in_category(row["item_id"]) or not warehouse.has(row["warehouse_id"]) or not document_ok(row): return
            if options.get("doc_type") and row["doc_type"] != options["doc_type"]: return
            qty = _d(row["quantity"]); unit_cost = _d(row["unit_cost"]) if qty > 0 and row["doc_type"] != "transfer" else unit
            rows.append([display_date(row["doc_date"]), row["number"], DOC_TYPES[row["doc_type"]][1], items[row["item_id"]]["sku"], items[row["item_id"]]["name"], row.get("warehouse_code") or "",
                         row.get("party_name") or "", qty, unit_cost.quantize(Decimal("0.0001")), (qty * unit_cost).quantize(Decimal("0.01"))])
        run_costing(database, date_to, method, record); title = "Stock Movements"
        sections.append({"heading": f"Movements {display_date(date_from)} to {display_date(date_to)}", "headers": ["Date", "Document", "Type", "Item Code",
                "Item", "Warehouse", "Party", "Quantity (+in / -out)", "Unit Cost", "Value"],
                         "rows": rows or [["No movements"] + [""] * 9], "total_rows": []})
    elif report == "margin":
        sold = {}
        def record(row, unit, value):
            if row["doc_type"] != "issue" or row["doc_date"] < date_from or not in_category(row["item_id"]) or not document_ok(row): return
            data = sold.setdefault(row["item_id"], {"qty": ZERO, "cost": ZERO, "sales": ZERO})
            qty = -_d(row["quantity"]); data["qty"] += qty; data["cost"] += qty * unit; data["sales"] += qty * _d(row.get("sales_price"))
        run_costing(database, date_to, method, record)
        rows = []; totals = [ZERO, ZERO, ZERO]
        for item_id, data in sorted(sold.items(), key=lambda pair: -pair[1]["sales"]):
            margin = data["sales"] - data["cost"]; totals[0] += data["sales"]; totals[1] += data["cost"]; totals[2] += margin
            rows.append([items[item_id]["sku"], items[item_id]["name"], data["qty"], data["sales"].quantize(Decimal("0.01")), data["cost"].quantize(Decimal("0.01")), margin.quantize(Decimal("0.01")),
                         f"{(margin / data['sales'] * 100):.1f}%" if data["sales"] else ""])
        rows.append(["TOTAL", "", "", totals[0].quantize(Decimal("0.01")), totals[1].quantize(Decimal("0.01")), totals[2].quantize(Decimal("0.01")),
                f"{(totals[2] / totals[0] * 100):.1f}%" if totals[0] else ""])
        title = "Sales Margin (Cost of Goods Sold)"
        sections.append({"heading": f"Items issued {display_date(date_from)} to {display_date(date_to)} - sales at invoice price, cost at {'FIFO' if method == 'fifo' else 'weighted average'}",
                         "headers": ["Item Code", "Item", "Quantity Sold", f"Sales ({currency})", "Cost of Goods Sold", "Gross Margin", "Margin %"], "rows": rows, "total_rows": [len(rows) - 1]})
    elif report == "brands":
        state = run_costing(database, date_to, method); grouped = {}
        for item_id, data in state.items():
            if item_id not in items or not in_category(item_id): continue
            values = _reported_warehouse_values(data)
            for wid, qty in data.get("by_warehouse", {}).items():
                if not warehouse.has(wid): continue
                if not qty and not values.get(wid): continue
                key = (items[item_id].get("brand") or "(no brand)", warehouses.get(wid, {}).get("code", "?"))
                entry = grouped.setdefault(key, {"items": set(), "qty": ZERO, "value": ZERO, "negative": 0})
                entry["items"].add(item_id); entry["qty"] += qty; entry["value"] += values.get(wid, ZERO)
                if qty < 0: entry["negative"] += 1
        rows = []; total = ZERO
        for (brand, wh), entry in sorted(grouped.items()):
            total += entry["value"]
            rows.append([brand, wh, len(entry["items"]), entry["qty"], entry["value"].quantize(Decimal("0.01")), entry["negative"] or ""])
        rows.append(["TOTAL", "", "", "", total.quantize(Decimal("0.01")), ""])
        title = "Stock by Brand and Warehouse"
        sections.append({"heading": f"Stock on {display_date(date_to)} by brand and warehouse", "headers": ["Brand", "Warehouse", "Items", "Quantity", f"Value ({currency})", "Items below zero"],
                         "rows": rows, "total_rows": [len(rows) - 1]})
    elif report == "ageing":
        return ageing_report(database, options, items, warehouses, in_category, currency, method, date_to, company)
    elif report == "summary":
        return summary_report(database, options, items, warehouses, in_category, currency, method, date_to, company)
    elif report in ("reorder", "slow"):
        state = run_costing(database, date_to, method); rows = []
        cutoff = (datetime.strptime(date_to, "%Y-%m-%d") - timedelta(days=int(options.get("days") or 90))).strftime("%Y-%m-%d")
        for item_id, item in sorted(items.items(), key=lambda pair: pair[1]["sku"]):
            if not item["active"] or not in_category(item_id): continue
            data = state.get(item_id, {"qty": ZERO, "avg": ZERO, "last_out": None, "value": ZERO}); reorder = _d(item.get("reorder_level"))
            if report == "reorder" and reorder > 0 and data["qty"] <= reorder:
                rows.append([item["sku"], item["name"], item["unit"], data["qty"], reorder, max(ZERO, reorder * 2 - data["qty"]), data["avg"].quantize(Decimal("0.0001"))])
            if report == "slow" and data["qty"] > 0 and (not data.get("last_out") or data["last_out"] < cutoff):
                rows.append([item["sku"], item["name"], item["unit"], data["qty"], data["value"].quantize(Decimal("0.01")),
                        display_date(data.get("last_out")) if data.get("last_out") else "never sold"])
        if report == "reorder":
            title = "Reorder Report"; sections.append({"heading": f"Items at or below their reorder level on {display_date(date_to)}", "headers": ["Item Code",
                    "Item", "Unit", "On Hand", "Reorder Level", "Suggested Order", "Unit Cost"],
                                                          "rows": rows or [["No item below its reorder level"] + [""] * 6], "total_rows": []})
        else:
            title = "Slow-moving Stock"; sections.append({"heading": f"Items in stock with no issue since {display_date(cutoff)} ({int(options.get('days') or 90)} days)",
                                                          "headers": ["Item Code", "Item", "Unit", "On Hand", f"Value ({currency})", "Last Issue"],
                                                                  "rows": rows or [["No slow-moving items"] + [""] * 5], "total_rows": []})
    elif report == "ledger_check":  # 2.9.82: stock valuation against the stock accounts of the ledger
        check = stock_ledger_check(database, date_to, method)
        title = "Stock vs Ledger"
        sections.append({"heading": f"Stock valuation against the ledger on {display_date(date_to)} ({currency})",
                         "headers": ["Stock account", "Items", f"Valuation ({currency})", f"Ledger ({currency})", "Difference", "Variation accounts"],
                         "rows": [[g["stock_account"] + (f" - {g['name']}" if g.get("name") else ""), g["items"], g["valuation"], g["ledger"], g["difference"],
                                 g["variation"]] for g in check["groups"]]
                         + [["TOTAL", sum(g["items"] for g in check["groups"]), check["valuation"], check["ledger"], check["difference"], ""]],
                         "total_rows": [len(check["groups"])]})
        sections.append({"heading": "How to read it", "headers": ["Note"], "rows": [[n] for n in check["notes"]], "total_rows": []})
    else: raise ValueError("Unknown inventory report")
    meta = [f"Company: {company.get('company_name') or '-'}   Inventory currency: {currency}   Costing: {'FIFO' if method == 'fifo' else 'Weighted average'}",
            f"Period: {display_date(date_from)} to {display_date(date_to)}" + (("   Filters: " + ", ".join(filters)) if filters else "")]
    return {"title": title, "meta": meta, "sections": sections}


# ---------------------------------------------------------------- year end


# ---------------------------------------------------------------- ageing and summary
ANALYSIS_DIMENSIONS = ("item", "category", "subcategory", "brand", "supplier", "unit", "warehouse", "month", "project", "branch")
MOVEMENT_DIMENSIONS = ("month", "project", "branch")


def inventory_analysis(database, options, items, warehouses, in_category, currency, method, date_from, date_to, warehouse, company):
    """Inventory Analysis (3D), 2.9.54: any three dimensions - rows, columns and layers (one table per layer value,
    plus the total) - chosen from item, category, subcategory, brand, supplier, unit, warehouse, month, project and
    branch, measured in quantity or cost value. Stock at the To date, or the net movement of the period as soon as
    month, project or branch is one of the dimensions."""
    row_dim = options.get("rows") or "item"; col_dim = options.get("columns") or "warehouse"
    layer_dim = options.get("layers") or "none"; measure = options.get("measure") or "quantity"
    if row_dim not in ANALYSIS_DIMENSIONS or col_dim not in ANALYSIS_DIMENSIONS or layer_dim not in ANALYSIS_DIMENSIONS + ("none",) or measure not in ("quantity", "value"):
        raise ValueError("Choose the rows, the columns and the layers among " + ", ".join(d.title() for d in ANALYSIS_DIMENSIONS) + ", and Quantity or Value")
    chosen = [d for d in (row_dim, col_dim, layer_dim) if d != "none"]
    if len(set(chosen)) != len(chosen): raise ValueError("Choose three different dimensions")
    movements = any(d in MOVEMENT_DIMENSIONS for d in chosen)
    with database.connect() as db:
        suppliers = {str(r["id"]): r["name"] for r in db.execute("SELECT id,name FROM parties")}
        projects = {r["id"]: f'{r["code"]} - {r["name"]}' for r in db.execute("SELECT id,code,name FROM projects")}
        branches = {r["id"]: r["name"] for r in db.execute("SELECT id,name FROM branches")}
    def value_of(dim, item, warehouse_id, row):
        if dim == "item": return f"{item['sku']} - {item['name']}"
        if dim == "supplier": return suppliers.get(str(item.get("supplier_id") or ""), "(No supplier)")
        if dim in ("category", "subcategory", "brand", "unit"): return item.get(dim) or f"(No {dim})"
        if dim == "warehouse": return warehouses.get(warehouse_id, {}).get("code", "?")
        if dim == "month": return (row or {}).get("doc_date", "")[:7]
        if dim == "project": return projects.get((row or {}).get("project_id"), "(No project)")
        return branches.get((row or {}).get("branch_id"), "(No branch)")
    cube = {}; columns = set(); layers = set()
    def add(item_id, warehouse_id, quantity, unit_cost, row=None):
        item = items.get(item_id)
        if not item or not in_category(item_id): return
        if options.get("item_id") and item_id != int(options["item_id"]): return
        amount = quantity if measure == "quantity" else quantity * unit_cost
        layer = value_of(layer_dim, item, warehouse_id, row) if layer_dim != "none" else ""
        r = value_of(row_dim, item, warehouse_id, row); c = value_of(col_dim, item, warehouse_id, row)
        cell = cube.setdefault(layer, {}).setdefault(r, {}); cell[c] = cell.get(c, ZERO) + amount
        columns.add(c); layers.add(layer)
    if not movements:
        state = run_costing(database, date_to, method)
        for item_id, data in state.items():
            reported_values = _reported_warehouse_values(data) if measure == "value" else {}
            for warehouse_id, qty in data["by_warehouse"].items():
                if not warehouse.has(warehouse_id) or not qty and not reported_values.get(warehouse_id): continue
                add(item_id, warehouse_id, qty, reported_values.get(warehouse_id, ZERO) / qty if qty else ZERO)
        if col_dim == "warehouse":
            columns.update(w["code"] for wid, w in warehouses.items() if warehouse.has(wid))
    else:
        def record(row, unit, value):
            if row["doc_date"] < date_from or row["doc_type"] == "transfer" or not warehouse.has(row["warehouse_id"]): return
            add(row["item_id"], row["warehouse_id"], _d(row["quantity"]), unit, row)
        run_costing(database, date_to, method, record)
    ordered = sorted(columns)
    fmt = (lambda v: v.quantize(Decimal("0.01"))) if measure == "value" else (lambda v: v)
    def table(pivot):
        rows = []; totals = [ZERO] * len(ordered)
        for label, values in sorted(pivot.items()):
            amounts = [values.get(col, ZERO) for col in ordered]
            if not any(amounts): continue
            totals = [a + b for a, b in zip(totals, amounts)]
            rows.append([label] + [fmt(v) for v in amounts] + [fmt(sum(amounts, ZERO))])
        rows.append(["TOTAL"] + [fmt(v) for v in totals] + [fmt(sum(totals, ZERO))])
        return rows
    def chart(rows, title):
        body = sorted(rows[:-1], key=lambda r: -abs(float(r[-1] or 0)))[:8]
        return {"title": title, "series": [str(r[0])[:28] for r in body], "categories": [str(c)[:14] for c in ordered[:12]],
                "values": [[float(v or 0) for v in r[1:1 + min(12, len(ordered))]] for r in body]}
    basis = "Net stock movement (receipts less issues)" if movements else f"Stock at {display_date(date_to)}"
    headers = [f"{row_dim.title()} / {col_dim.title()}"] + ordered + ["Total"]
    sections = []
    if layer_dim == "none":
        rows = table(cube.get("", {}))
        sections.append({"heading": basis, "headers": headers, "rows": rows, "total_rows": [len(rows) - 1], "chart": chart(rows, f"{row_dim.title()} x {col_dim.title()} (3D)")})
    else:
        merged = {}
        for layer in sorted(layers):
            rows = table(cube.get(layer, {}))
            if len(rows) == 1: continue
            sections.append({"heading": f"{layer_dim.title()}: {layer} - {basis.lower()}", "headers": headers, "rows": rows, "total_rows": [len(rows) - 1]})
            for label, values in cube.get(layer, {}).items():
                target = merged.setdefault(label, {})
                for col, amount in values.items(): target[col] = target.get(col, ZERO) + amount
        layer_totals = [[layer] + [fmt(sum((cube[layer].get(r, {}).get(c, ZERO) for r in cube[layer]), ZERO)) for c in ordered] for layer in sorted(layers)]
        for row in layer_totals: row.append(fmt(sum((v for v in row[1:]), ZERO)))
        sections.insert(0, {"heading": f"{layer_dim.title()} x {col_dim.title()} - totals", "headers": [f"{layer_dim.title()} / {col_dim.title()}"] + ordered + ["Total"],
                            "rows": layer_totals, "total_rows": [], "chart": {"title": f"{layer_dim.title()} x {col_dim.title()} (3D)", "series": [str(r[0])[:28] for r in layer_totals[:8]],
                            "categories": [str(c)[:14] for c in ordered[:12]], "values": [[float(v or 0) for v in r[1:1 + min(12, len(ordered))]] for r in layer_totals[:8]]}})
        rows = table(merged)
        sections.append({"heading": f"All {layer_dim}s together - {basis.lower()}", "headers": headers, "rows": rows, "total_rows": [len(rows) - 1],
                         "chart": chart(rows, f"{row_dim.title()} x {col_dim.title()} (3D)")})
    if not sections: sections.append({"heading": basis, "headers": headers, "rows": [["No data"] + [""] * (len(headers) - 1)], "total_rows": []})
    return {"title": "Inventory Analysis (3D)", "meta": [f"Company: {company.get('company_name') or '-'}",
            f"Rows: {row_dim.title()}   Columns: {col_dim.title()}   Layers: {layer_dim.title()}   Measure: {measure.title()} ({currency} cost value when applicable)   Costing: {'FIFO by warehouse' if method == 'fifo' else 'Company-wide weighted average'}",
            f"From {display_date(date_from)} to {display_date(date_to)}"], "sections": sections}


def inventory_health(database, options, items, in_category, currency, method, date_to, warehouse, company):
    """List actionable stock issues with value at cost and item master data."""
    try: days = int(options.get("days") or 90)
    except ValueError as exc: raise ValueError("Slow-moving days must be a whole number") from exc
    if days < 1: raise ValueError("Slow-moving days must be at least 1")
    cutoff = (datetime.strptime(date_to, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    state = run_costing(database, date_to, method); rows = []; totals = {}
    for item_id, item in sorted(items.items(), key=lambda pair: pair[1]["sku"]):
        if not item["active"] or not in_category(item_id): continue
        data = state.get(item_id, {}); qty = warehouse.qty(data)
        reorder = _d(item.get("reorder_level")); issues = []
        if qty < 0: issues.append("Negative stock")
        if reorder > 0 and qty <= reorder: issues.append("Reorder")
        if qty > 0 and not data.get("avg", ZERO): issues.append("Missing unit cost")
        if qty > 0 and not item.get("supplier_id"): issues.append("No supplier")
        if qty > 0 and (not data.get("last_out") or data["last_out"] < cutoff): issues.append(f"No issue in {days} days")
        if not issues: continue
        value = (warehouse.pick(_reported_warehouse_values(data)) if warehouse
                 else data.get("value", ZERO).quantize(Decimal("0.01")))
        for issue in issues:
            rows.append([issue, item["sku"], item["name"], item.get("category") or "", qty, reorder, value, display_date(data["last_out"]) if data.get("last_out") else "Never"])
            count, amount = totals.get(issue, (0, ZERO)); totals[issue] = (count + 1, amount + value)
    summary = [[issue, count, value.quantize(Decimal("0.01"))] for issue, (count, value) in sorted(totals.items())]
    return {"title": "Inventory Health", "meta": [f"Company: {company.get('company_name') or '-'}", f"As of {display_date(date_to)}   Slow-moving threshold: {days} days"],
            "sections": [{"heading": "Action summary", "headers": ["Issue", "Items", f"Stock Value ({currency})"], "rows": summary or [["No inventory exceptions", 0, ZERO]], "total_rows": []},
                         {"heading": "Items to review (an item may appear for more than one issue)", "headers": ["Issue", "Item Code", "Item", "Category",
                                 "On Hand", "Reorder Level", f"Value ({currency})", "Last Issue"],
                          "rows": rows or [["No inventory exceptions"] + [""] * 7], "total_rows": []}]}


def additional_inventory_report(database, report, options, items, warehouses, in_category, currency, method, date_from, date_to, warehouse, company):
    """Turnover, stock by supplier, and saved physical count differences."""
    selected = lambda item_id: item_id in items and in_category(item_id) and (not options.get("item_id") or int(options["item_id"]) == item_id)
    money = lambda value: Decimal(value).quantize(Decimal("0.01"))
    meta = [f"Company: {company.get('company_name') or '-'}   Currency: {currency}", f"From {display_date(date_from)} to {display_date(date_to)}"]
    if report == "count_variances":
        with database.connect() as db:
            counts = [dict(row) for row in db.execute("SELECT number,count_date,warehouse_id,status,lines FROM physical_counts WHERE count_date BETWEEN ? AND ? ORDER BY count_date,number",
                    (date_from, date_to))]
        rows = []; total = ZERO
        for count in counts:
            if not warehouse.has(count["warehouse_id"]): continue
            snapshot = {row["item_id"]: row for row in count_sheet(database, count["warehouse_id"], count["count_date"])}
            if count["status"] == "posted":
                with database.connect() as db:
                    adjustments = db.execute("""SELECT m.item_id,m.quantity FROM stock_movements m JOIN stock_documents d ON d.id=m.document_id
                        WHERE d.reference=? AND d.doc_date=? AND d.warehouse_id=? AND d.notes=?""",
                        (count["number"], count["count_date"], count["warehouse_id"], f"Physical count {count['number']}")).fetchall()
                for change in adjustments:
                    if change["item_id"] in snapshot: snapshot[change["item_id"]]["system_qty"] -= float(change["quantity"])
            for line in json.loads(count["lines"]):
                item_id = int(line["item_id"])
                if not selected(item_id): continue
                system = _d(line.get("system_qty") if line.get("system_qty") is not None else snapshot.get(item_id, {}).get("system_qty"))
                counted = _d(line["counted"]); difference = counted - system
                if not difference: continue
                cost = _d(line.get("unit_cost") if line.get("unit_cost") is not None else snapshot.get(item_id, {}).get("unit_cost"))
                value = money(difference * cost); total += value
                rows.append([count["number"], display_date(count["count_date"]), warehouses[count["warehouse_id"]]["code"], items[item_id]["sku"],
                        items[item_id]["name"], system, counted, difference, value, count["status"]])
        rows.append(["TOTAL", "", "", "", "", "", "", "", money(total), ""])
        return {"title": "Physical Count Variances", "meta": meta, "sections": [{"heading": "Saved counts with differences", "headers": ["Count", "Date",
                "Warehouse", "Item Code", "Item", "Stock on Hand", "Counted", "Difference", f"Variance ({currency})", "Status"], "rows": rows,
                "total_rows": [len(rows)-1]}]}
    state = run_costing(database, date_to, method)
    if report == "turnover":
        issued = {}
        for row in _movements(database, date_to):
            item_id = row["item_id"]
            if date_from <= row["doc_date"] <= date_to and row["doc_type"] == "issue" and selected(item_id) and warehouse.has(row["warehouse_id"]):
                issued[item_id] = issued.get(item_id, ZERO) - _d(row["quantity"])
        rows = []; period_days = (datetime.strptime(date_to, "%Y-%m-%d") - datetime.strptime(date_from, "%Y-%m-%d")).days + 1
        for item_id, item in sorted(items.items(), key=lambda pair: pair[1]["sku"]):
            if not selected(item_id): continue
            data = state.get(item_id, {}); on_hand = warehouse.qty(data)
            sold = issued.get(item_id, ZERO)
            if not sold and not on_hand and not options.get("include_zero"): continue
            days = (on_hand / sold * Decimal(period_days)).quantize(Decimal("0.1")) if sold else "-"
            value = warehouse.pick(_reported_warehouse_values(data)) if warehouse and data else data.get("value", ZERO)
            rows.append([item["sku"], item["name"], item["unit"], sold, on_hand, days, money(value)])
        return {"title": "Stock Turnover", "meta": meta,
                "sections": [{"heading": "Issues during period and stock at To Date (coverage at the period's issue rate)", "headers": ["Item Code", "Item",
                "Unit", "Issued", "On Hand", "Coverage Days", f"On-hand Value ({currency})"], "rows": rows, "total_rows": []}]}
    with database.connect() as db:
        suppliers = {str(row["id"]): row["name"] for row in db.execute("SELECT id,name FROM parties")}
    groups = {}
    for item_id, item in items.items():
        if not selected(item_id): continue
        data = state.get(item_id, {}); qty = warehouse.qty(data)
        if not qty and not options.get("include_zero"): continue
        name = suppliers.get(str(item.get("supplier_id") or ""), "(No supplier)")
        value = warehouse.pick(_reported_warehouse_values(data)) if warehouse and data else data.get("value", ZERO)
        groups.setdefault(name, []).append([item["sku"], item["name"], item["unit"], qty, money(value)])
    rows = []; totals = []
    for name, members in sorted(groups.items()):
        rows.extend([[name, *member] for member in sorted(members)])
        rows.append([f"Subtotal {name}", "", "", "", sum((member[3] for member in members), ZERO), money(sum((member[4] for member in members), ZERO))]); totals.append(len(rows)-1)
    rows.append(["TOTAL", "", "", "", sum((member[3] for members in groups.values() for member in members), ZERO),
            money(sum((member[4] for members in groups.values() for member in members), ZERO))]); totals.append(len(rows)-1)
    return {"title": "Stock by Supplier", "meta": meta, "sections": [{"heading": f"On-hand stock at {display_date(date_to)} by item supplier",
            "headers": ["Supplier", "Item Code", "Item", "Unit", "On Hand", f"Value ({currency})"], "rows": rows, "total_rows": totals}]}

AGEING_BUCKETS = (30, 60, 90, 180, 365)


def fifo_layers(database, date_to):
    """Stock still on hand, split into the receipts it came from (FIFO): {item_id: [[qty, unit_cost, receipt_date], ...]}."""
    layers = {}
    for row in _movements(database, date_to):
        if row["doc_type"] == "transfer": continue
        qty = _d(row["quantity"]); item = layers.setdefault(row["item_id"], [])
        if qty > 0: item.append([qty, _d(row["unit_cost"]), row["doc_date"]])
        else:
            remaining = -qty
            while remaining > 0 and item:
                take = min(item[0][0], remaining); item[0][0] -= take; remaining -= take
                if item[0][0] <= 0: item.pop(0)
    return {k: [l for l in v if l[0] > 0] for k, v in layers.items()}


def _buckets(options):
    try: values = sorted({int(v) for v in str(options.get("buckets") or "").replace(" ", "").split(",") if v})
    except ValueError: raise ValueError("Ageing buckets must be days separated by commas, for example 30,60,90,180,365")
    return tuple(v for v in values if v > 0) or AGEING_BUCKETS


def _bucket_labels(limits):
    labels = []; start = 0
    for limit in limits: labels.append(f"{start}-{limit} days"); start = limit + 1
    return labels + [f"Over {limits[-1]} days"]


def _ageing_data(database, options, items, in_category, method, date_to):
    limits = _buckets(options); as_of = datetime.strptime(date_to, "%Y-%m-%d")
    state = run_costing(database, date_to, method)
    layers = fifo_layers(database, date_to) if method != "fifo" else {}
    warehouse = WarehouseChoice(options.get("warehouse_id"))
    result = []
    for item_id, item in sorted(items.items(), key=lambda pair: pair[1]["sku"]):
        data = state.get(item_id)
        if method == "fifo" and data:
            remaining = ([list(layer) for wid in sorted(warehouse.ids) for layer in data["warehouse_layers"].get(wid, [])] if warehouse
                         else [list(layer) for wh_layers in data["warehouse_layers"].values() for layer in wh_layers])
        else:
            remaining = layers.get(item_id, [])
        if not data or data["qty"] <= 0 or not in_category(item_id) or (options.get("item_id") and int(options["item_id"]) != item_id) or not remaining: continue
        on_hand = warehouse.qty(data)
        if on_hand <= 0: continue
        share = on_hand / data["qty"] if method != "fifo" else Decimal(1)  # average-cost warehouse age is estimated
        unit_cost = data["avg"]
        buckets = [[ZERO, ZERO] for _ in range(len(limits) + 1)]; weighted_age = ZERO; oldest = None
        for qty, layer_cost, day, *_origin in remaining:
            age = (as_of - datetime.strptime(day, "%Y-%m-%d")).days; qty = qty * share
            index = next((i for i, limit in enumerate(limits) if age <= limit), len(limits))
            value = qty * (layer_cost if method == "fifo" else unit_cost)
            buckets[index][0] += qty; buckets[index][1] += value; weighted_age += qty * age
            oldest = day if oldest is None or day < oldest else oldest
        total_qty = sum((b[0] for b in buckets), ZERO); total_value = sum((b[1] for b in buckets), ZERO)
        result.append({"item": item, "qty": total_qty, "value": total_value, "buckets": buckets, "avg_age": int(weighted_age / total_qty) if total_qty else 0,
                       "oldest": oldest, "last_out": data.get("last_out"), "last_in": remaining[-1][2] if remaining else None})
    return limits, result


def ageing_report(database, options, items, warehouses, in_category, currency, method, date_to, company):
    """Stock ageing: how long the stock on hand has been waiting, by receipt date (FIFO), valued at cost."""
    limits, data = _ageing_data(database, options, items, in_category, method, date_to)
    labels = _bucket_labels(limits); money = lambda v: Decimal(v).quantize(Decimal("0.01"))
    headers = ["Item Code", "Item", "Category", "Unit", "On Hand", f"Value ({currency})", "Avg Age (days)", "Oldest Receipt",
            "Last Issue"] + labels + [f"% over {limits[-2] if len(limits) > 1 else limits[-1]} days"]
    risk_from = len(limits) - 1 if len(limits) > 1 else len(limits)
    rows = []; totals = []; grand = [ZERO] * (len(labels)); grand_qty = ZERO; grand_value = ZERO
    for name in sorted({(d["item"].get("category") or "(no category)") for d in data}):
        members = [d for d in data if (d["item"].get("category") or "(no category)") == name]; sub = [ZERO] * len(labels)
        for d in members:
            values = [b[1] for b in d["buckets"]]; old_share = sum(values[risk_from:], ZERO) / d["value"] * 100 if d["value"] else ZERO
            rows.append([d["item"]["sku"], d["item"]["name"], name, d["item"]["unit"], d["qty"].quantize(Decimal("0.001")), money(d["value"]), d["avg_age"],
                         display_date(d["oldest"]) if d["oldest"] else "", display_date(d["last_out"]) if d.get("last_out") else "never"] + [money(v) for v in values] + [f"{old_share:.0f}%"])
            sub = [a + b for a, b in zip(sub, values)]
        sub_value = sum(sub, ZERO)
        rows.append([f"Subtotal {name}", f"{len(members)} item(s)", "", "", "", money(sub_value), "", "", ""] + [money(v) for v in sub] +
                    [f"{(sum(sub[risk_from:], ZERO) / sub_value * 100):.0f}%" if sub_value else ""]); totals.append(len(rows) - 1)
        grand = [a + b for a, b in zip(grand, sub)]; grand_value += sub_value; grand_qty += sum((d["qty"] for d in members), ZERO)
    rows.append(["TOTAL", f"{len(data)} item(s)", "", "", "", money(grand_value), "", "", ""] + [money(v) for v in grand] +
                [f"{(sum(grand[risk_from:], ZERO) / grand_value * 100):.0f}%" if grand_value else ""]); totals.append(len(rows) - 1)
    summary = [[label, money(value), f"{(value / grand_value * 100):.1f}%" if grand_value else "0.0%", sum(1 for d in data if d["buckets"][index][1] > 0)]
               for index, (label, value) in enumerate(zip(labels, grand))]
    summary.append(["TOTAL STOCK", money(grand_value), "100.0%" if grand_value else "0.0%", len(data)])
    old = sorted([d for d in data if sum((b[1] for b in d["buckets"][risk_from:]), ZERO) > 0], key=lambda d: -sum((b[1] for b in d["buckets"][risk_from:]), ZERO))
    risk = [[d["item"]["sku"], d["item"]["name"], d["item"].get("category") or "", money(sum((b[1] for b in d["buckets"][risk_from:]), ZERO)), d["avg_age"],
             display_date(d["last_out"]) if d.get("last_out") else "never"] for d in old[:25]]
    threshold = limits[-2] if len(limits) > 1 else limits[-1]
    sections = [{"heading": "Ageing summary", "headers": ["Age of stock", f"Value ({currency})", "% of stock value", "Items"], "rows": summary, "total_rows": [len(summary) - 1]},
                {"heading": f"Stock ageing by item at {display_date(date_to)} (by receipt date, first in - first out)", "headers": headers,
                 "rows": rows if data else [["No stock on hand"] + [""] * (len(headers) - 1)], "total_rows": totals if data else []},
                {"heading": f"Stock older than {threshold} days - review for slow-moving or obsolete items", "headers": ["Item Code", "Item", "Category",
                        f"Value over {threshold} days", "Avg Age (days)", "Last Issue"],
                 "rows": risk or [["No stock older than this"] + [""] * 5], "total_rows": []}]
    meta = [f"Company: {company.get('company_name') or '-'}   Inventory currency: {currency}   Costing: {'FIFO' if method == 'fifo' else 'Weighted average'}",
            f"Stock ageing as of {display_date(date_to)}   Buckets: {', '.join(labels)}" + (f"   Warehouse: {warehouses[int(options['warehouse_id'])]['code']}" if str(options.get('warehouse_id') or '').isdigit() else "")]
    if method != "fifo" and options.get("warehouse_id"):
        meta.append("Warehouse age buckets are estimated from the company-wide receipt mix; values use the company-wide moving average.")
    return {"title": "Stock Ageing Report", "meta": meta, "sections": sections}


def summary_report(database, options, items, warehouses, in_category, currency, method, date_to, company):
    """One-page inventory summary: key figures, value by category and warehouse, top items, ageing."""
    state = run_costing(database, date_to, method); money = lambda v: Decimal(v).quantize(Decimal("0.01"))
    rows = [(item_id, items[item_id], data) for item_id, data in state.items() if data["qty"] > 0 and item_id in items and in_category(item_id)]
    total_value = sum((sum(_reported_warehouse_values(d).values(), ZERO) for _i, _it, d in rows), ZERO)
    sales_value = sum((d["qty"] * _d(it.get("sales_price")) for _i, it, d in rows), ZERO)
    below = [it for _i, it, d in rows if _d(it.get("reorder_level")) > 0 and d["qty"] <= _d(it.get("reorder_level"))]
    cutoff = (datetime.strptime(date_to, "%Y-%m-%d") - timedelta(days=int(options.get("days") or 90))).strftime("%Y-%m-%d")
    limits, ageing = _ageing_data(database, options, items, in_category, method, date_to)
    # slow-moving: in stock for longer than the period AND nothing issued during it (new arrivals are not slow)
    slow = [(a["item"], state[a["item"]["id"]]) for a in ageing if a["oldest"] and a["oldest"] < cutoff and (not a.get("last_out") or a["last_out"] < cutoff)]
    old_value = sum((sum((b[1] for b in a["buckets"][len(limits) - 1:]), ZERO) for a in ageing), ZERO)
    kpis = [["Items in stock", len(rows)], [f"Stock value at cost ({currency})", money(total_value)], [f"Stock value at sales price ({currency})", money(sales_value)],
            ["Potential gross margin", money(sales_value - total_value)], ["Items at or below reorder level", len(below)],
            [f"Slow-moving stock value (no issue for {int(options.get('days') or 90)} days)", money(sum((d['value'] for _it, d in slow), ZERO))],
            [f"Stock value older than {limits[-2] if len(limits) > 1 else limits[-1]} days", money(old_value)],
            ["Share of old stock in total value", f"{(old_value / total_value * 100):.1f}%" if total_value else "0.0%"]]
    by_category = {}
    for _i, it, d in rows:
        category = it.get("category") or "(no category)"
        by_category.setdefault(category, [0, ZERO])
        by_category[category][0] += 1
        by_category[category][1] += sum(_reported_warehouse_values(d).values(), ZERO)
    category_rows = [[name, count, money(value), f"{(value / total_value * 100):.1f}%" if total_value else ""] for name, (count, value) in sorted(by_category.items(), key=lambda p: -p[1][1])]
    warehouse_rows = []
    for warehouse_id, warehouse in warehouses.items():
        value = sum((_reported_warehouse_values(d).get(warehouse_id, ZERO) for _i, _it, d in rows), ZERO)
        if value: warehouse_rows.append([warehouse["code"], warehouse["name"], money(value), f"{(value / total_value * 100):.1f}%" if total_value else ""])
    top = sorted(rows, key=lambda r: -r[2]["value"])[:10]
    top_rows = [[it["sku"], it["name"], it.get("category") or "", d["qty"].quantize(Decimal("0.001")), money(d["avg"]),
                 sum(_reported_warehouse_values(d).values(), ZERO), f"{(d['value'] / total_value * 100):.1f}%" if total_value else ""] for _i, it, d in top]
    labels = _bucket_labels(limits); age_totals = [sum((a["buckets"][i][1] for a in ageing), ZERO) for i in range(len(labels))]
    sections = [{"heading": "Key figures", "headers": ["Indicator", "Value"], "rows": kpis, "total_rows": [1]},
                {"heading": "Stock value by category", "headers": ["Category", "Items", f"Value ({currency})", "% of value"], "rows": category_rows or [["-", "", "", ""]], "total_rows": []},
                {"heading": "Stock value by warehouse", "headers": ["Warehouse", "Name", f"Value ({currency})", "% of value"], "rows": warehouse_rows or [["-", "", "", ""]], "total_rows": []},
                {"heading": "Top 10 items by value", "headers": ["Item Code", "Item", "Category", "On Hand", "Unit Cost", f"Value ({currency})", "% of value"],
                        "rows": top_rows or [["-"] + [""] * 6], "total_rows": []},
                {"heading": "Ageing of the stock", "headers": ["Age of stock", f"Value ({currency})", "% of value"],
                 "rows": [[label, money(value), f"{(value / total_value * 100):.1f}%" if total_value else ""] for label, value in zip(labels, age_totals)], "total_rows": []}]
    if below: sections.append({"heading": "Items to reorder", "headers": ["Item Code", "Item", "On Hand", "Reorder Level"],
                               "rows": [[it["sku"], it["name"], state[it["id"]]["qty"].quantize(Decimal("0.001")), _d(it.get("reorder_level"))] for it in below], "total_rows": []})
    meta = [f"Company: {company.get('company_name') or '-'}   Inventory currency: {currency}   Costing: {'FIFO' if method == 'fifo' else 'Weighted average'}", f"Situation at {display_date(date_to)}"]
    return {"title": "Inventory Summary", "meta": meta, "sections": sections}
