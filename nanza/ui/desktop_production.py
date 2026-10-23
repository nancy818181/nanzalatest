"""Inventory > Production (2.9.65): recipes (bills of materials), production orders and the production report."""
from __future__ import annotations
import logging
from desktop_common import add_search_bar  # 2.9.78

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from desktop_brains import EditableSheet
from desktop_common import flow_toolbars

NAVY, GOLD, LIGHT = "#102A43", "#B78B45", "#F4F7FA"
RED, MUTED, AMBER = "#8B1E1E", "#5f6b76", "#B7791F"


def _num(value):
    try: return float(str(value if value not in (None, "") else 0).replace(",", ""))
    except ValueError: return None


def _dd(value):
    text = str(value or "")
    return f"{text[8:10]}-{text[5:7]}-{text[:4]}" if len(text) == 10 and text[4] == "-" else text


def _qty(value):
    number = _num(value) or 0
    return f"{number:,.3f}".rstrip("0").rstrip(".") if number else ""


class ProductionMixin:
    def build_production_page(self, page):
        nested = ttk.Notebook(page); nested.pack(fill="both", expand=True, padx=4, pady=4); self.prod_notebook = nested
        orders, recipes, report = (tk.Frame(nested, bg=LIGHT) for _ in range(3))
        nested.add(orders, text="Production Orders"); nested.add(recipes, text="Recipes (materials per product)"); nested.add(report, text="Production Report")
        self.build_recipe_page(recipes); self.build_production_order_page(orders); self.build_production_report_page(report)

    def item_label(self, item):
        return f'{item["sku"]} - {item["name"]}'

    def item_choices(self):
        return [self.item_label(i) for i in getattr(self, "inventory_rows", []) if i.get("active", 1)]

    def production_item(self, text):
        code = str(text or "").split(" - ", 1)[0].strip().upper()
        return next((i for i in getattr(self, "inventory_rows", []) if i["sku"].upper() == code), None)

    # ------------------------------------------------------------ recipes
    def build_recipe_page(self, page):
        self.rc_vars = {k: tk.StringVar() for k in ("product", "output_qty", "overhead", "notes")}
        self.rc_vars["output_qty"].set("1"); self.rc_vars["overhead"].set("0")
        side = tk.Frame(page, bg=LIGHT); side.pack(side="right", fill="y", padx=(4, 8), pady=6)
        tk.Label(side, text="Recipes saved", bg=LIGHT, fg=NAVY, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.rc_list = ttk.Treeview(side, columns=("sku", "name", "makes", "materials"), show="headings", height=14)
        for key, label, width in (("sku", "Product", 90), ("name", "Name", 170), ("makes", "Makes", 60), ("materials", "Materials", 70)):
            self.rc_list.heading(key, text=label); self.rc_list.column(key, width=width, anchor="e" if key in ("makes", "materials") else "w")
        self.rc_list.pack(fill="y", expand=True); self.rc_list.bind("<Double-1>", lambda _e: self.open_selected_recipe()); add_search_bar(self.rc_list)  # 2.9.78
        main = tk.Frame(page, bg=LIGHT); main.pack(side="left", fill="both", expand=True)
        bar = tk.Frame(main, bg=LIGHT); bar.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(bar, text="Product made", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
        self.rc_product_box = ttk.Combobox(bar, textvariable=self.rc_vars["product"], width=34); self.rc_product_box.pack(side="left", padx=(4, 10))
        self.rc_product_box.bind("<<ComboboxSelected>>", lambda _e: self.load_recipe())
        self.rc_product_box.bind("<KeyRelease>", lambda e: self.filter_item_box(e, self.rc_product_box, self.rc_vars["product"]))
        self.rc_product_box.bind("<Return>", lambda _e: self.load_recipe())
        tk.Label(bar, text="The materials below make", bg=LIGHT).pack(side="left")
        tk.Entry(bar, textvariable=self.rc_vars["output_qty"], width=8, justify="right").pack(side="left", padx=4)
        self.rc_unit = tk.Label(bar, text="unit(s)", bg=LIGHT); self.rc_unit.pack(side="left", padx=(0, 10))
        bar2 = tk.Frame(main, bg=LIGHT); bar2.pack(fill="x", padx=8, pady=2)
        tk.Label(bar2, text="Extra cost per unit (labour, energy...)", bg=LIGHT).pack(side="left")
        tk.Entry(bar2, textvariable=self.rc_vars["overhead"], width=10, justify="right").pack(side="left", padx=(4, 10))
        tk.Label(bar2, text="Notes", bg=LIGHT).pack(side="left"); tk.Entry(bar2, textvariable=self.rc_vars["notes"], width=40).pack(side="left", padx=4)
        bottom = tk.Frame(main, bg=LIGHT); bottom.pack(side="bottom", fill="x", padx=8, pady=6)
        self.action_button(bottom, "New", self.new_recipe).pack(side="left", padx=(0, 3))
        self.action_button(bottom, "Add Material", lambda: self.add_recipe_line()).pack(side="left", padx=3)
        tk.Button(bottom, text="Delete Line", command=lambda: self.rc_sheet.delete_selected(), bg=RED, fg="white", border=0, padx=12, pady=7).pack(side="left", padx=3)
        tk.Button(bottom, text="Save Recipe", command=self.save_recipe, bg=GOLD, fg=NAVY, border=0, padx=18, pady=7, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(12, 3))
        tk.Button(bottom, text="Delete Recipe", command=self.delete_recipe, bg=RED, fg="white", border=0, padx=12, pady=7).pack(side="left", padx=3)
        self.rc_info = tk.Label(main, text="Choose the product, then the materials for the quantity above (F2 in Item Code to search). "
                                "A material can itself have a recipe.", bg=LIGHT, fg=MUTED, anchor="w")
        self.rc_info.pack(side="bottom", fill="x", padx=10)
        flow_toolbars(bar, bar2, bottom)
        self.rc_sheet = EditableSheet(self, main, [("line", "#", 40, "center"), ("sku", "Item Code", 120, "w"), ("name", "Material", 260, "w"),
                                                   ("unit", "Unit", 70, "center"), ("quantity", "Quantity", 110, "e"), ("cost", "Average Cost", 110, "e")],
                                      ["sku", "quantity"], self.recipe_cell_changed, height=10)
        self.rc_sheet.tree.bind("<F2>", lambda _e: self.item_picker(lambda sku: self.recipe_pick(sku)))
        self.new_recipe()

    def filter_item_box(self, event, box, variable):
        if event is not None and event.keysym in ("Up", "Down", "Return", "Escape", "Tab"): return
        text = variable.get().casefold()
        box["values"] = [label for label in self.item_choices() if not text or text in label.casefold()]

    def add_recipe_line(self, row=None):
        row = row or {"sku": "", "name": "", "unit": "", "quantity": "", "cost": ""}
        return self.rc_sheet.insert(row)

    def recipe_pick(self, sku):
        iid, _row = self.rc_sheet.selected()
        if not iid: iid = self.add_recipe_line()
        self.recipe_cell_changed(iid, "sku", sku); self.rc_sheet.refresh(iid)

    def recipe_cell_changed(self, iid, key, text):
        row = self.rc_sheet.rows[iid]
        if key == "sku":
            item = self.production_item(text) if text else None
            if text and not item: messagebox.showwarning("Recipes", f"Item {text} was not found (F2 to search)"); return False
            if item: row.update(sku=item["sku"], name=item["name"], unit=item["unit"], cost=f'{item["average_cost"]:,.4f}')
        else:
            value = _num(text)
            if value is None or value < 0: messagebox.showwarning("Recipes", "Enter a positive number"); return False
            row["quantity"] = value
        row["_display"] = {"quantity": _qty(row.get("quantity"))}
        rows = self.rc_sheet.tree.get_children()
        if rows and iid == rows[-1] and row.get("sku") and row.get("quantity"): self.add_recipe_line()

    def new_recipe(self):
        for key, value in (("product", ""), ("output_qty", "1"), ("overhead", "0"), ("notes", "")): self.rc_vars[key].set(value)
        self.rc_sheet.clear(); [self.add_recipe_line() for _ in range(3)]
        self.rc_product_box["values"] = self.item_choices(); self.load_recipe_list()

    def load_recipe_list(self):
        if not hasattr(self, "rc_list") or not self.rc_list.winfo_exists(): return
        try: self.recipe_rows = self.client.production_recipes()
        except Exception: self.recipe_rows = []
        self.rc_list.delete(*self.rc_list.get_children())
        for r in self.recipe_rows: self.rc_list.insert("", "end", iid=r["sku"], values=(r["sku"], r["name"], _qty(r["output_qty"]), r["components"]))
        if hasattr(self, "po_product_box"): self.po_product_box["values"] = [f'{r["sku"]} - {r["name"]}' for r in self.recipe_rows]

    def open_selected_recipe(self):
        selected = self.rc_list.selection()
        if not selected: return
        item = self.production_item(selected[0])
        self.rc_vars["product"].set(self.item_label(item) if item else selected[0]); self.load_recipe()

    def load_recipe(self):
        item = self.production_item(self.rc_vars["product"].get())
        if not item: return
        self.rc_vars["product"].set(self.item_label(item)); self.rc_unit.config(text=f'{item["unit"]}(s)')
        try: bom = self.client.production_recipe(item["sku"])
        except Exception as exc: return messagebox.showerror("Recipes", str(exc))
        self.rc_vars["output_qty"].set(_qty(bom["output_qty"]) or "1"); self.rc_vars["overhead"].set(f'{bom["overhead_per_unit"]:g}'); self.rc_vars["notes"].set(bom.get("notes") or "")
        self.rc_sheet.clear()
        for line in bom["lines"]:
            stock = self.production_item(line["sku"]) or {}
            self.add_recipe_line({"sku": line["sku"], "name": line["name"], "unit": line["unit"], "quantity": line["quantity"],
                                  "cost": f'{stock.get("average_cost", 0):,.4f}', "_display": {"quantity": _qty(line["quantity"])}})
        self.add_recipe_line()
        self.rc_info.config(text=f'Recipe of {item["sku"]} opened.' if bom["exists"] else f'{item["sku"]} has no recipe yet: add its materials and Save Recipe.')

    def save_recipe(self):
        item = self.production_item(self.rc_vars["product"].get())
        if not item: return messagebox.showwarning("Recipes", "Choose the product made")
        lines = [{"sku": r["sku"], "quantity": r["quantity"]} for r in self.rc_sheet.ordered() if r.get("sku") and _num(r.get("quantity"))]
        if not lines: return messagebox.showwarning("Recipes", "Add at least one material with a quantity")
        try:
            self.client.save_production_recipe({"sku": item["sku"], "output_qty": self.rc_vars["output_qty"].get(), "overhead_per_unit": self.rc_vars["overhead"].get(),
                                                "notes": self.rc_vars["notes"].get(), "lines": lines})
        except Exception as exc: return messagebox.showerror("Recipes", str(exc))
        self.load_recipe_list(); self.rc_info.config(text=f'Recipe of {item["sku"]} saved ({len(lines)} material(s)).')
        messagebox.showinfo("Recipes", f'Recipe of {item["sku"]} saved')

    def delete_recipe(self):
        item = self.production_item(self.rc_vars["product"].get())
        if not item: return messagebox.showwarning("Recipes", "Choose the product first")
        if not messagebox.askyesno("Recipes", f'Delete the recipe of {item["sku"]}? Production orders already saved stay as they are.'): return
        try: self.client.delete_production_recipe(item["sku"])
        except Exception as exc: return messagebox.showerror("Recipes", str(exc))
        self.new_recipe()

    # ------------------------------------------------------------ production orders
    def build_production_order_page(self, page):
        self.po_id = None
        self.po_vars = {k: tk.StringVar() for k in ("number", "date", "product", "quantity", "warehouse", "to_warehouse", "extra", "reference", "notes", "find")}
        v = self.po_vars; v["date"].set(self.fiscal_today()); v["quantity"].set("1"); v["extra"].set("0")
        bar = tk.Frame(page, bg=LIGHT); bar.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(bar, text="Order", bg=LIGHT).pack(side="left")
        tk.Entry(bar, textvariable=v["number"], width=16, state="readonly", readonlybackground="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(4, 8))
        tk.Label(bar, text="Date", bg=LIGHT).pack(side="left"); self.date_entry(bar, v["date"], 11).pack(side="left", padx=(4, 8))
        tk.Label(bar, text="Product", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
        self.po_product_box = ttk.Combobox(bar, textvariable=v["product"], width=30); self.po_product_box.pack(side="left", padx=(4, 8))
        self.po_product_box.bind("<<ComboboxSelected>>", lambda _e: self.production_from_recipe())
        tk.Label(bar, text="Quantity", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
        quantity = tk.Entry(bar, textvariable=v["quantity"], width=9, justify="right"); quantity.pack(side="left", padx=(4, 8))
        quantity.bind("<Return>", lambda _e: self.production_from_recipe()); quantity.bind("<FocusOut>", lambda _e: self.production_quantity_changed())
        tk.Label(bar, text="Find", bg=LIGHT).pack(side="left", padx=(8, 0))
        self.po_find_box = ttk.Combobox(bar, textvariable=v["find"], width=34); self.po_find_box.pack(side="left", padx=4)
        self.po_find_box.bind("<<ComboboxSelected>>", lambda _e: self.open_production_order())
        bar2 = tk.Frame(page, bg=LIGHT); bar2.pack(fill="x", padx=8, pady=2)
        tk.Label(bar2, text="Materials from", bg=LIGHT).pack(side="left")
        self.po_wh_box = ttk.Combobox(bar2, textvariable=v["warehouse"], state="readonly", width=18); self.po_wh_box.pack(side="left", padx=(4, 8))
        tk.Label(bar2, text="Product into", bg=LIGHT).pack(side="left")
        self.po_to_box = ttk.Combobox(bar2, textvariable=v["to_warehouse"], state="readonly", width=18); self.po_to_box.pack(side="left", padx=(4, 8))
        tk.Label(bar2, text="Extra cost (total)", bg=LIGHT).pack(side="left")
        extra = tk.Entry(bar2, textvariable=v["extra"], width=10, justify="right"); extra.pack(side="left", padx=(4, 8)); extra.bind("<FocusOut>", lambda _e: self.update_production_total())
        tk.Label(bar2, text="Reference / client order", bg=LIGHT).pack(side="left"); tk.Entry(bar2, textvariable=v["reference"], width=16).pack(side="left", padx=(4, 8))
        tk.Label(bar2, text="Notes", bg=LIGHT).pack(side="left"); tk.Entry(bar2, textvariable=v["notes"], width=24).pack(side="left", padx=4)
        bottom = tk.Frame(page, bg=LIGHT); bottom.pack(side="bottom", fill="x", padx=8, pady=6)
        self.action_button(bottom, "New", self.new_production_order).pack(side="left", padx=(0, 3))
        self.action_button(bottom, "Materials from Recipe", self.production_from_recipe).pack(side="left", padx=3)
        self.action_button(bottom, "Add Material", lambda: self.add_production_line()).pack(side="left", padx=3)
        tk.Button(bottom, text="Delete Line", command=lambda: (self.po_sheet.delete_selected(), self.update_production_total()), bg=RED, fg="white", border=0,
                padx=12, pady=7).pack(side="left", padx=3)
        tk.Button(bottom, text="Save Production", command=self.save_production_order, bg=GOLD, fg=NAVY, border=0, padx=18, pady=7, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(12, 3))
        tk.Button(bottom, text="Delete Order", command=self.delete_production_order, bg=RED, fg="white", border=0, padx=12, pady=7).pack(side="left", padx=3)
        self.po_total = tk.Label(bottom, text="", bg=LIGHT, fg=NAVY, font=("Segoe UI", 10, "bold")); self.po_total.pack(side="left", padx=12)
        self.po_info = tk.Label(page, text="Choose the product and the quantity: the materials come from its recipe. For a special order change the quantities "
                                "or add / delete materials here - the recipe itself is not changed.", bg=LIGHT, fg=MUTED, anchor="w", justify="left")
        self.po_info.pack(side="bottom", fill="x", padx=10)
        flow_toolbars(bar, bar2, bottom)
        self.po_sheet = EditableSheet(self, page, [("line", "#", 40, "center"), ("sku", "Item Code", 120, "w"), ("name", "Material", 240, "w"), ("unit", "Unit", 60, "center"),
                                                   ("recipe", "Recipe Qty", 100, "e"), ("quantity", "Qty Used", 100, "e"), ("on_hand", "On Hand", 100, "e"),
                                                   ("unit_cost", "Unit Cost", 100, "e"), ("value", "Value", 110, "e")],
                                      ["sku", "quantity"], self.production_cell_changed, height=10)
        self.po_sheet.tree.tag_configure("short", foreground=RED); self.po_sheet.tree.tag_configure("changed", foreground=AMBER)
        self.po_sheet.tree.bind("<F2>", lambda _e: self.item_picker(lambda sku: self.production_pick(sku)))
        self.new_production_order()

    def warehouse_labels(self):
        return [f'{w["code"]} - {w["name"]}' for w in getattr(self, "warehouse_rows", []) if w["active"]]

    def add_production_line(self, row=None):
        row = row or {"sku": "", "name": "", "unit": "", "recipe": "", "quantity": "", "on_hand": "", "unit_cost": "", "value": ""}
        self.refresh_production_row(row); return self.po_sheet.insert(row)

    def refresh_production_row(self, row):
        item = self.production_item(row.get("sku")) if row.get("sku") else None
        if item:
            row.update(name=item["name"], unit=item["unit"])
            row.setdefault("on_hand", item["quantity"])
            if row.get("unit_cost") in ("", None): row["unit_cost"] = item["average_cost"]
        qty = _num(row.get("quantity")) or 0; cost = _num(row.get("unit_cost")) or 0
        row["value"] = f"{qty * cost:,.2f}" if qty else ""
        row["_display"] = {"quantity": _qty(qty), "recipe": _qty(row.get("recipe")), "on_hand": _qty(row.get("on_hand")) if row.get("sku") else "",
                           "unit_cost": f"{cost:,.4f}" if row.get("sku") else ""}

    def tag_production_rows(self):
        for iid, row in self.po_sheet.rows.items():
            qty = _num(row.get("quantity")) or 0
            tags = ["odd"] if self.po_sheet.tree.exists(iid) and "odd" in self.po_sheet.tree.item(iid, "tags") else []
            if row.get("sku") and qty > (_num(row.get("on_hand")) or 0) + 1e-9: tags.append("short")
            elif row.get("recipe") not in ("", None) and abs(qty - (_num(row.get("recipe")) or 0)) > 1e-9: tags.append("changed")
            if self.po_sheet.tree.exists(iid): self.po_sheet.tree.item(iid, tags=tuple(tags))

    def production_pick(self, sku):
        iid, _row = self.po_sheet.selected()
        if not iid: iid = self.add_production_line()
        self.production_cell_changed(iid, "sku", sku); self.po_sheet.refresh(iid)

    def production_cell_changed(self, iid, key, text):
        row = self.po_sheet.rows[iid]
        if key == "sku":
            item = self.production_item(text) if text else None
            if text and not item: messagebox.showwarning("Production", f"Item {text} was not found (F2 to search)"); return False
            for field in ("on_hand", "unit_cost"): row.pop(field, None)
            row["sku"] = item["sku"] if item else ""
        else:
            value = _num(text)
            if value is None or value < 0: messagebox.showwarning("Production", "Enter a positive number"); return False
            row["quantity"] = value
        self.refresh_production_row(row); self.after_idle(self.update_production_total)
        rows = self.po_sheet.tree.get_children()
        if rows and iid == rows[-1] and row.get("sku") and row.get("quantity"): self.add_production_line()

    def update_production_total(self):
        rows = [r for r in self.po_sheet.ordered() if r.get("sku") and _num(r.get("quantity"))]
        materials = sum((_num(r["quantity"]) or 0) * (_num(r.get("unit_cost")) or 0) for r in rows)
        extra = _num(self.po_vars["extra"].get()) or 0; qty = _num(self.po_vars["quantity"].get()) or 0
        unit = (materials + extra) / qty if qty else 0
        prefix = "Cost" if self.po_id else "Expected cost (current average)"
        self.po_total.config(text=f"{prefix}: materials {materials:,.2f} + extra {extra:,.2f} = {materials + extra:,.2f}   |   per unit {unit:,.4f} {getattr(self, 'inventory_currency', '')}")
        self.tag_production_rows()

    def production_quantity_changed(self):
        if self.po_id is None and getattr(self, "_po_planned_for", None) not in (None, (self.po_vars["product"].get(), self.po_vars["quantity"].get())):
            self.production_from_recipe(ask=False)
        else: self.update_production_total()

    def new_production_order(self):
        self.po_id = None; v = self.po_vars
        for key, value in (("product", ""), ("quantity", "1"), ("extra", "0"), ("reference", ""), ("notes", ""), ("find", "")): v[key].set(value)
        v["date"].set(self.fiscal_today()); self._po_planned_for = None
        labels = self.warehouse_labels(); self.po_wh_box["values"] = labels; self.po_to_box["values"] = labels
        if labels and v["warehouse"].get() not in labels: v["warehouse"].set(labels[0])
        if labels and v["to_warehouse"].get() not in labels: v["to_warehouse"].set(v["warehouse"].get())
        try: v["number"].set(self.client.next_stock_number("production", v["date"].get()))
        except Exception: v["number"].set("")
        self.po_sheet.clear(); [self.add_production_line() for _ in range(3)]
        self.load_production_orders(); self.update_production_total()

    def production_from_recipe(self, ask=True):
        v = self.po_vars; item = self.production_item(v["product"].get())
        if not item: return messagebox.showwarning("Production", "Choose the product to make") if ask else None
        qty = _num(v["quantity"].get())
        if not qty or qty <= 0: return messagebox.showwarning("Production", "Enter the quantity to make") if ask else None
        if ask and any(r.get("sku") for r in self.po_sheet.ordered()) and self.po_id and not messagebox.askyesno(
                "Production", "Replace the materials of this order with the recipe quantities?"): return
        try: plan = self.client.production_plan(item["sku"], qty, v["warehouse"].get().split(" - ", 1)[0], v["date"].get())
        except Exception as exc: return messagebox.showwarning("Production", str(exc))
        v["product"].set(self.item_label(item)); v["extra"].set(f'{plan["extra_cost"]:.2f}'); self._po_planned_for = (v["product"].get(), v["quantity"].get())
        self.po_sheet.clear()
        for line in plan["lines"]:
            self.add_production_line({"sku": line["sku"], "name": line["name"], "unit": line["unit"], "recipe": line["quantity"], "quantity": line["quantity"],
                                      "on_hand": line["on_hand"], "unit_cost": line["unit_cost"]})
        self.add_production_line(); self.update_production_total()
        short = [l["sku"] for l in plan["lines"] if l["short"] > 0]
        self.po_info.config(text=(f"Not enough in stock: {', '.join(short)} (in red). " if short else "") +
                            "Change Qty Used for a special order (shown in amber); the recipe is not changed.")

    def load_production_orders(self):
        if not hasattr(self, "po_find_box"): return
        try: orders = self.client.production_orders()
        except Exception: orders = []
        self.po_order_map = {f'{o["number"]} | {_dd(o["doc_date"])} | {o["sku"]} x {_qty(o["quantity"])}': o["id"] for o in orders}
        self.po_find_box["values"] = list(self.po_order_map)
        if getattr(self, "recipe_rows", None) is not None: self.po_product_box["values"] = [f'{r["sku"]} - {r["name"]}' for r in self.recipe_rows]

    def open_production_order(self, order_id=None):
        order_id = order_id or getattr(self, "po_order_map", {}).get(self.po_vars["find"].get())
        if not order_id: return
        try: order = self.client.production_order(order_id)
        except Exception as exc: return messagebox.showerror("Production", str(exc))
        self.po_id = order["id"]; v = self.po_vars; product = order.get("product") or {}
        v["number"].set(order["number"]); v["date"].set(_dd(order["doc_date"])); v["quantity"].set(_qty(product.get("quantity")))
        v["product"].set(f'{product.get("sku", "")} - {product.get("name", "")}'); v["extra"].set(f'{order.get("extra_cost", 0):.2f}')
        v["warehouse"].set(f'{order["warehouse_code"]} - {order["warehouse_name"]}'); v["to_warehouse"].set(f'{order["to_warehouse_code"]} - {order["to_warehouse_name"]}')
        v["reference"].set(order.get("reference") or ""); v["notes"].set(order.get("notes") or ""); self._po_planned_for = (v["product"].get(), v["quantity"].get())
        recipe = {}
        try:
            bom = self.client.production_recipe(product.get("sku"))
            factor = (_num(product.get("quantity")) or 0) / (bom["output_qty"] or 1)
            recipe = {l["sku"]: l["quantity"] * factor for l in bom["lines"]}
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
        self.po_sheet.clear()
        for line in order["materials"]:
            stock = self.production_item(line["sku"]) or {}
            self.add_production_line({"sku": line["sku"], "name": line["name"], "unit": line["unit"], "recipe": recipe.get(line["sku"], ""), "quantity": line["quantity"],
                                      "on_hand": (stock.get("quantity") or 0) + line["quantity"], "unit_cost": line["unit_cost"]})
        self.add_production_line(); self.update_production_total()
        self.po_info.config(text=f'{order["number"]}: {_qty(product.get("quantity"))} x {product.get("sku")} at {product.get("unit_cost", 0):,.4f} per unit '
                            f'(materials {order["material_cost"]:,.2f} + extra {order["extra_cost"]:,.2f}). Change and Save Production to correct it.')

    def save_production_order(self):
        v = self.po_vars; item = self.production_item(v["product"].get())
        if not item: return messagebox.showwarning("Production", "Choose the product made")
        lines = [{"sku": r["sku"], "quantity": r["quantity"]} for r in self.po_sheet.ordered() if r.get("sku") and _num(r.get("quantity"))]
        if not lines: return messagebox.showwarning("Production", "Add the materials used (Materials from Recipe)")
        header = {"doc_date": v["date"].get().strip(), "sku": item["sku"], "quantity": v["quantity"].get(), "extra_cost": v["extra"].get() or "0",
                  "warehouse_id": v["warehouse"].get().split(" - ", 1)[0], "to_warehouse_id": (v["to_warehouse"].get() or v["warehouse"].get()).split(" - ", 1)[0],
                  "reference": v["reference"].get(), "notes": v["notes"].get()}
        try: saved = self.client.save_production_order(header, lines, self.po_id)
        except Exception as exc: return messagebox.showerror("Production", str(exc))
        product = saved.get("product") or {}
        messagebox.showinfo("Production", f'{saved["number"]} saved: {_qty(product.get("quantity"))} x {item["sku"]} at {product.get("unit_cost", 0):,.4f} per unit '
                            f'(total {saved["total_cost"]:,.2f}).')
        self.load_inventory(); self.new_production_order()

    def delete_production_order(self):
        if not self.po_id: return messagebox.showwarning("Production", "Open a saved order first (Find)")
        if not messagebox.askyesno("Production", f'Delete {self.po_vars["number"].get()}? The materials go back to stock and the product is taken out.'): return
        try: self.client.delete_stock_document(self.po_id)
        except Exception as exc: return messagebox.showerror("Production", str(exc))
        self.load_inventory(); self.new_production_order()

    # ------------------------------------------------------------ report
    def build_production_report_page(self, page):
        year = getattr(self, "current_fiscal_year", datetime.now().year)
        self.pr_from = tk.StringVar(value=f"01-01-{year}"); self.pr_to = tk.StringVar(value=f"31-12-{year}")
        bar = tk.Frame(page, bg=LIGHT); bar.pack(fill="x", padx=8, pady=6)
        tk.Label(bar, text="From", bg=LIGHT).pack(side="left"); self.date_entry(bar, self.pr_from, 11).pack(side="left", padx=(4, 8))
        tk.Label(bar, text="To", bg=LIGHT).pack(side="left"); self.date_entry(bar, self.pr_to, 11).pack(side="left", padx=(4, 8))
        tk.Button(bar, text="Show", command=self.run_production_report, bg=GOLD, fg=NAVY, border=0, padx=18, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=6)
        for text, fmt in (("Print", "print"), ("Excel", "xlsx"), ("PDF", "pdf")):
            self.action_button(bar, text, lambda f=fmt: self.export_production_report(f)).pack(side="left", padx=3)
        self.pr_viewer = self.report_viewer(page)

    def run_production_report(self):
        try: self.production_report_result = self.client.production_report(self.pr_from.get().strip(), self.pr_to.get().strip())
        except Exception as exc: return messagebox.showerror("Production Report", str(exc))
        self.show_sections(self.pr_viewer, self.production_report_result["sections"])

    def export_production_report(self, format_name):
        if not getattr(self, "production_report_result", None): self.run_production_report()
        result = getattr(self, "production_report_result", None)
        if result: self.output_sections(result["title"], result["meta"], result["sections"], "Production_Report", format_name)
