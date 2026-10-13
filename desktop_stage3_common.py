"""Shared imports and helpers of desktop_stage3.py (split in 2.9.42)."""
from __future__ import annotations
import logging

import mimetypes
import os
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from importer import read_customs_costs, read_expenses, read_invoices
from chart_extra import EXPENSE_VAT, PURCHASE_VAT, SALES_VAT
from pdf_import import asset_pdf_details, read_invoice_pdf, read_invoice_pdf_pages
from report_export import export_excel, export_pdf
from desktop_common import bulk_action  # 2.9.72: several purchases / expenses / payments deleted at once (was "bulk_action is not defined")

NAVY, GOLD, LIGHT = "#102A43", "#B78B45", "#F4F7FA"  # 2.9.59: the same colours on every screen
PURCHASE_USES = {"Mixed (partial deduction)": "mixed", "Taxable sales only (100%)": "taxable", "Exempt sales only (0%)": "exempt",
                 "Utilities (no VAT recovery from 10-02-2026)": "utilities", "Passenger car (VAT recovered up to USD 30,000)": "passenger_car"}  # 2.9.92
RED, MUTED = "#8B1E1E", "#5f6b76"
TYPES = {"Purchases": ("purchase", "purchases"), "Sales": ("sale", "sales"), "Expenses": ("purchase", "expenses"), "Assets": ("purchase", "assets")}
METHODS = ["Cash", "Cheque", "Bank Transfer", "Card", "Other"]


def _num(value, default=0.0):
    try: return float(str(value).replace(",", "")) if str(value).strip() else default
    except ValueError: return None


def _dd(value):
    text = str(value or "").strip()
    for pattern in ("%d-%m-%Y", "%Y-%m-%d", "%d%m%Y"):
        try: return datetime.strptime(text, pattern).strftime("%d-%m-%Y")
        except ValueError: pass
    return text


def auto_upload_on(app):
    """2.9.50: 'Save automatically after upload' ticked (screens built without it keep the old manual flow)."""
    var = getattr(app, "auto_upload_var", None)
    try: return bool(var().get()) if callable(var) else False
    except Exception: return False


SIMILAR_ITEM_WARNING = 0.90  # 2.9.86 (owner): 90% of the name the same -> warning, the user decides


def _remember_new(app, item):
    if isinstance(item, dict) and item.get("created"):
        try:
            new = getattr(app, "_new_items", None)
            if new is None: new = []; app._new_items = new
            new.append(item)
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
    return item


def notify_new_items(app, title="Inventory"):
    """2.9.86: after an upload, tell the user which items did not exist and were created in Inventory."""
    new = list(getattr(app, "_new_items", None) or [])
    try: app._new_items = []
    except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
    if not new: return []
    if isinstance(app, tk.Misc) and hasattr(app, "account_search_box"):
        ask_new_item_details(app, new, title)  # 2.9.101: category / brand, when ticked in Inventory > Warehouses & Settings
        choose_new_item_accounts(app, new, title); return new  # 2.9.90: the accounts of the new items are chosen at once
    names = "\n".join(f'{i.get("sku", "")} - {i.get("name", "")} ({i.get("unit") or "unit"})' for i in new[:25])
    more = f"\n... and {len(new) - 25} more" if len(new) > 25 else ""
    messagebox.showinfo(title, f"{len(new)} new item(s) did not exist and were created in Inventory:\n\n{names}{more}\n\n"
                               "Check their category, unit and stock account in Inventory > Items.")
    return new


ASK_LABELS = (("category", "Category"), ("subcategory", "Subcategory"), ("brand", "Brand"))


def asked_item_details(app):
    """The details asked for each new item (ticked in Inventory > Warehouses & Settings)."""
    try: settings = app.client.inventory_settings()
    except Exception: return []
    return [key for key, _label in ASK_LABELS if settings.get(f"ask_{key}")]


def ask_new_item_details(app, items, title="New items", asked=None):
    """2.9.101: a table of the new items a purchase created, to give each one its category, subcategory and brand.
    Pick the values above the table and press Apply: they go to the selected lines (or to all of them when none is
    selected); a value can also be typed (a new category or brand). Save writes them to Inventory."""
    asked = asked if asked is not None else asked_item_details(app)
    if not items or not asked: return False
    try: tree_data = app.client.item_categories()
    except Exception: tree_data = {"categories": []}
    try: brand_values = app.client.inventory_brands()
    except Exception: brand_values = []
    categories = [c["name"] for c in tree_data.get("categories", [])]
    subs = {c["name"]: c.get("subcategories", []) for c in tree_data.get("categories", [])}
    window = tk.Toplevel(app); window.title(f"{title} - category and brand of the new items"); window.configure(bg=LIGHT); window.transient(app)
    tk.Label(window, text=f"{len(items)} new item(s) were created. Give them their " + " / ".join(l.lower() for k, l in ASK_LABELS if k in asked) + ":",
             bg=LIGHT, fg=NAVY, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=14, pady=(12, 6))
    pick = tk.Frame(window, bg=LIGHT); pick.pack(fill="x", padx=14)
    chosen = {key: tk.StringVar(master=app) for key in asked}; boxes = {}
    for column, (key, label) in enumerate((k, l) for k, l in ASK_LABELS if k in asked):
        tk.Label(pick, text=label, bg=LIGHT, font=("Segoe UI", 9, "bold")).grid(row=0, column=column, sticky="w", padx=(0, 10))
        values = categories if key == "category" else brand_values if key == "brand" else sorted({s for v in subs.values() for s in v})
        boxes[key] = ttk.Combobox(pick, textvariable=chosen[key], values=values, width=24); boxes[key].grid(row=1, column=column, sticky="w", padx=(0, 10), pady=(2, 8))
    if "category" in boxes and "subcategory" in boxes:
        boxes["category"].bind("<<ComboboxSelected>>", lambda _e: boxes["subcategory"].configure(values=subs.get(chosen["category"].get(), [])))
    frame = tk.Frame(window, bg=LIGHT); frame.pack(fill="both", expand=True, padx=14)
    columns = ("sku", "name") + tuple(asked)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=min(14, max(4, len(items))), selectmode="extended")
    for key, label, width in (("sku", "Code", 100), ("name", "Item", 300)) + tuple((k, l, 150) for k, l in ASK_LABELS if k in asked):
        tree.heading(key, text=label); tree.column(key, width=width, anchor="w")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview); tree.configure(yscrollcommand=scroll.set)
    for item in items: tree.insert("", "end", iid=str(item["id"]), values=(item.get("sku"), item.get("name")) + tuple(item.get(k) or "" for k in asked))
    tree.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
    def apply():
        ids = list(tree.selection()) or list(tree.get_children())
        for iid in ids:
            for key in asked:
                if chosen[key].get().strip(): tree.set(iid, key, chosen[key].get().strip())
        tree.selection_remove(*ids)
    def save():
        rows = [{"id": int(iid), **{key: tree.set(iid, key) for key in asked}} for iid in tree.get_children()]
        try: app.client.set_item_details(rows)
        except Exception as exc: return messagebox.showerror(title, str(exc), parent=window)
        for item in items:
            for key in asked: item[key] = tree.set(str(item["id"]), key) if tree.exists(str(item["id"])) else item.get(key)
        window.destroy()
    tk.Label(window, text="Select lines (Ctrl / Shift for several), pick the values and press Apply; with no line selected, Apply sets all of them. "
             "Type a value that is not in the list to create it.", bg=LIGHT, fg=MUTED, wraplength=640, justify="left").pack(anchor="w", padx=14, pady=(6, 0))
    buttons = tk.Frame(window, bg=LIGHT); buttons.pack(fill="x", padx=14, pady=12)
    tk.Button(buttons, text="Save", command=save, bg=GOLD, fg=NAVY, border=0, padx=20, pady=7, font=("Segoe UI", 10, "bold")).pack(side="right", padx=3)
    tk.Button(buttons, text="Later", command=window.destroy, bg=NAVY, fg="white", border=0, padx=16, pady=7, font=("Segoe UI", 10)).pack(side="right", padx=3)
    tk.Button(buttons, text="Apply to selected / all", command=apply, bg=NAVY, fg="white", border=0, padx=16, pady=7, font=("Segoe UI", 10, "bold")).pack(side="left")
    window.grab_set(); app.wait_window(window)
    return True


def choose_new_item_accounts(app, items, title="New items"):
    """2.9.90 (owner): right after an upload creates items, choose for all of them (or the selected ones) the cost account
    (class 6, used on purchases) and the sales account (class 7, used on sales invoices)."""
    from desktop_common import account_label
    try: defaults = {d["key"]: d["account"] for d in app.client.accounting_setup().get("defaults", [])}  # Settings > Accounting Settings
    except Exception: defaults = {}
    cost = tk.StringVar(master=app, value=account_label(app, (defaults or {}).get("purchases") or "601100000"))
    sales = tk.StringVar(master=app, value=account_label(app, (defaults or {}).get("sales_goods") or "701100001"))
    window = tk.Toplevel(app); window.title(f"{title} - accounts of the new items"); window.configure(bg=LIGHT); window.transient(app)
    tk.Label(window, text=f"{len(items)} new item(s) were created in Inventory. Choose their accounts:", bg=LIGHT, fg=NAVY,
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
    frame = tk.Frame(window, bg=LIGHT); frame.pack(fill="both", expand=True, padx=12)
    tree = ttk.Treeview(frame, columns=("sku", "name", "unit"), show="headings", height=min(12, max(3, len(items))), selectmode="extended")
    for key, label, width in (("sku", "Code", 100), ("name", "Item", 330), ("unit", "Unit", 70)): tree.heading(key, text=label); tree.column(key, width=width, anchor="w")
    for item in items: tree.insert("", "end", iid=str(item["id"]), values=(item.get("sku"), item.get("name"), item.get("unit")))
    tree.pack(side="left", fill="both", expand=True)
    form = tk.Frame(window, bg=LIGHT); form.pack(fill="x", padx=12, pady=8)
    for row, (label, var) in enumerate((("Cost account (purchases, class 6)", cost), ("Sales account (sales, class 7)", sales))):
        tk.Label(form, text=label, bg=LIGHT).grid(row=row, column=0, sticky="w", pady=3)
        app.account_search_box(form, var, 36).grid(row=row, column=1, sticky="w", padx=6, pady=3)
    tk.Label(window, text="Applies to the selected items, or to all of them when none is selected. You can change one item later in Inventory > Items.",
             bg=LIGHT, fg=MUTED, wraplength=520, justify="left").pack(anchor="w", padx=12)
    def apply():
        ids = list(tree.selection()) or [str(i["id"]) for i in items]
        try: app.client.set_item_accounts(ids, cost.get(), sales.get())
        except Exception as exc: return messagebox.showerror(title, str(exc), parent=window)
        for iid in ids: tree.delete(iid)
        if not tree.get_children(): window.destroy()
    buttons = tk.Frame(window, bg=LIGHT); buttons.pack(fill="x", padx=12, pady=10)
    tk.Button(buttons, text="Apply", command=apply, bg=GOLD, fg=NAVY, border=0, padx=18, pady=6, font=("Segoe UI", 9, "bold")).pack(side="right", padx=3)
    tk.Button(buttons, text="Later", command=window.destroy, bg=NAVY, fg="white", border=0, padx=14, pady=6).pack(side="right", padx=3)
    window.grab_set(); app.wait_window(window)


def resolve_item(app, name, unit="unit", code=None, supplier_id=None):
    """2.9.51: the inventory item for a purchase line. The same name written differently is matched by the service.
    2.9.86 (owner): an item that does not exist is created and listed in a notice after the upload; when an item
    with 90% or more of the same name exists (e.g. 'HPL Panel 4mm Wht' and 'HPL Panel 4mm White'), a warning asks:
    use the existing item or create a new one. The answer is remembered for the rest of the session."""
    client = app.client
    if code or not isinstance(app, tk.Misc):
        return _remember_new(app, client.find_or_create_item(name, unit, code, supplier_id))
    memory = getattr(app, "_item_choices", None)
    if memory is None:
        memory = {}
        try: app._item_choices = memory
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
    key = str(name or "").strip().casefold()
    if key in memory:
        chosen = memory[key]
        return chosen if chosen else _remember_new(app, client.find_or_create_item(name, unit, None, supplier_id))
    try: candidates = client.similar_items(name)
    except Exception: candidates = []
    candidates = [c for c in candidates if c.get("score", 0) >= SIMILAR_ITEM_WARNING] if isinstance(candidates, list) else []
    if not candidates or candidates[0].get("score", 0) >= 1:
        return _remember_new(app, client.find_or_create_item(name, unit, None, supplier_id))
    chosen = choose_similar_item(app, name, candidates)
    memory[key] = chosen
    return chosen if chosen else _remember_new(app, client.find_or_create_item(name, unit, None, supplier_id))


def choose_similar_item(app, name, candidates):
    """Small window: use one of the close items, or create a new item. Returns the chosen item or None (create)."""
    window = tk.Toplevel(app); window.title("Warning - same item?"); window.transient(app); window.grab_set()
    tk.Label(window, text=f"Warning: the invoice line\n\"{name}\"\nhas 90% or more of the name of an item you already have. Decide:", justify="left",
             fg=RED, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(12, 6))
    choice = tk.IntVar(master=window, value=0)
    for index, item in enumerate(candidates):
        tk.Radiobutton(window, text=f'Use {item["sku"]} - {item["name"]} ({item.get("unit") or ""}, {item["score"] * 100:.0f}% alike)', variable=choice, value=index,
                       anchor="w").pack(fill="x", padx=20)
    tk.Radiobutton(window, text="Create a new item with this name", variable=choice, value=-1, anchor="w").pack(fill="x", padx=20, pady=(4, 0))
    result = {"item": None}
    def ok(_e=None):
        result["item"] = candidates[choice.get()] if choice.get() >= 0 else None; window.destroy()
    tk.Button(window, text="OK", command=ok, width=10).pack(pady=12)
    window.bind("<Return>", ok); window.protocol("WM_DELETE_WINDOW", ok)
    app.wait_window(window)
    return result["item"]


# ---------------------------------------------------------------- 2.9.85: reading PDFs
def prepare_pdf_reading(app):
    """Tell the PDF reader who the company is (the buyer, never the supplier; pages not addressed to it are
    supporting papers) and which suppliers / customers it already knows (a name printed on the page is used)."""
    import pdf_import
    try:
        names = [(getattr(app, "current_company", None) or {}).get("name")]
        try: names.append((app.client.settings() or {}).get("company_name"))
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
        pdf_import.set_own_company(*names)
    except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
    try: pdf_import.set_known_parties([p.get("name") for p in app.client.parties()])
    except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105


def run_with_progress(app, title, work, done):
    """Run work(progress, cancel) away from the screen (a long scanned PDF is read page by page with OCR), with a
    window showing the page being read and a Stop button; done(result) runs on the screen afterwards.
    Without a real window (tests) the work runs at once."""
    if not isinstance(app, tk.Misc):
        return done(work(None, None))
    cancel = threading.Event(); window = tk.Toplevel(app); window.title(title); window.configure(bg=LIGHT); window.transient(app)
    window.resizable(False, False); window.protocol("WM_DELETE_WINDOW", cancel.set)
    label = tk.Label(window, text="Reading the PDF...", bg=LIGHT, fg=NAVY, font=("Segoe UI", 10, "bold"), width=60, anchor="w")
    label.pack(padx=16, pady=(14, 6), fill="x")
    bar = ttk.Progressbar(window, mode="determinate", length=420, maximum=100); bar.pack(padx=16, pady=4)
    tk.Label(window, text="Scanned pages are read with OCR (a few seconds each). You can keep this window open and wait.",
             bg=LIGHT, fg=MUTED, wraplength=440, justify="left").pack(padx=16, pady=4, anchor="w")
    tk.Button(window, text="Stop (keep what is read)", command=cancel.set, bg=RED, fg="white", border=0, padx=12, pady=5).pack(pady=(4, 12))

    import queue
    events = queue.Queue()  # 2.9.87: the reading thread never touches the window; the screen polls this queue

    def progress(done_pages, total, stage="OCR"):
        events.put(("progress", (done_pages, total, stage)))

    def run():
        try: events.put(("done", work(progress, cancel)))
        except Exception as exc: events.put(("error", str(exc)))

    def poll():
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == "progress":
                    done_pages, total, stage = value
                    if window.winfo_exists():
                        label.config(text=f"{stage}: page {done_pages + 1} of {total}" + ("  -  stopping..." if cancel.is_set() else ""))
                        bar.config(value=100 * done_pages / max(total, 1))
                    continue
                try: window.destroy()
                except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
                if kind == "error": messagebox.showerror(title, value)
                else: done(value)
                return
        except queue.Empty:
            pass
        app.after(100, poll)
    app.after(100, poll)
    threading.Thread(target=run, daemon=True, name="SaberPdfRead").start()
