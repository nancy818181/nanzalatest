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

NAVY, GOLD, LIGHT = "#102A43", "#B78B45", "#F4F7FA"
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


def run_with_progress(app, title, work, done, unit="page"):
    """Run work(progress, cancel) away from the screen (a long scanned PDF is read page by page with OCR), with a
    window showing the page being read and a Stop button; done(result) runs on the screen afterwards.
    Without a real window (tests) the work runs at once."""
    if not isinstance(app, tk.Misc):
        return done(work(None, None))
    cancel = threading.Event(); window = tk.Toplevel(app); window.title(title); window.configure(bg=LIGHT); window.transient(app)
    window.resizable(False, False); window.protocol("WM_DELETE_WINDOW", cancel.set)
    label = tk.Label(window, text="Preparing the download..." if unit == "bytes" else "Reading the PDF...",
                     bg=LIGHT, fg=NAVY, font=("Segoe UI", 10, "bold"), width=60, anchor="w")
    label.pack(padx=16, pady=(14, 6), fill="x")
    bar = ttk.Progressbar(window, mode="determinate", length=420, maximum=100); bar.pack(padx=16, pady=4)
    explanation = ("One-time download. You can stop it and use Install / Repair later to resume."
                   if unit == "bytes" else "Scanned pages are read with OCR (a few seconds each). You can keep this window open and wait.")
    tk.Label(window, text=explanation,
             bg=LIGHT, fg=MUTED, wraplength=440, justify="left").pack(padx=16, pady=4, anchor="w")
    tk.Button(window, text="Stop download" if unit == "bytes" else "Stop (keep what is read)", command=cancel.set,
              bg=RED, fg="white", border=0, padx=12, pady=5).pack(pady=(4, 12))

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
                        if unit == "bytes":
                            detail = f"{stage}: {done_pages // 1048576} / {total // 1048576} MB" if total else stage
                        else: detail = f"{stage}: page {done_pages + 1} of {total}"
                        label.config(text=detail + ("  -  stopping..." if cancel.is_set() else ""))
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


def checked_handwriting_fields(data, values):
    """Explicitly checked values, without deriving VAT, totals or dates from other fields."""
    import vision_reader
    from database_common import display_date, iso_date
    result = dict(data)
    result["invoice_number"] = values.get("invoice_number", "").strip()
    date = values.get("invoice_date", "").strip()
    result["invoice_date"] = display_date(iso_date(date)) if date else ""
    currency = values.get("currency", "").strip().upper()
    if currency and (len(currency) != 3 or not currency.isascii() or not currency.isalpha()):
        raise ValueError("Enter a three-letter currency code, for example USD or LBP")
    result["currency"] = currency
    result["party_name"] = values.get("party_name", "").strip()
    result["party_tax_number"] = values.get("party_tax_number", result.get("party_tax_number") or "").strip()
    result["supplier_hint"] = result["party_name"]
    for field in ("subtotal", "vat", "total"):
        raw = values.get(field, "").strip()
        amount = vision_reader._written_money(raw) if raw else None
        if raw and amount is None: raise ValueError(f"Enter a valid {field} amount or leave it blank")
        result[field] = amount
    result["acquisition_cost"] = result.get("subtotal")
    for key,evidence in (result.get("fields") or {}).items():
        old=evidence.get("value");current=result.get(key)
        if old != current:
            evidence["previous_origin"]=evidence.get("origin")
            evidence["origin"]="user_corrected"
        evidence["value"]=current;evidence["reviewed"]=True
    result["handwriting_confirmed"] = True
    result["review_required"] = True  # checking a transcription never approves the accounting entry
    result["notes"] = str(result.get("notes") or "") + "; Handwriting fields checked against the image"
    return result


def handwriting_review_image(path, page=0):
    """Keep photograph detail for human review; model-sized previews lose small digits."""
    from PIL import Image, ImageOps
    from pdf_import import IMAGE_SUFFIXES
    import vision_reader
    if Path(path).suffix.lower() in IMAGE_SUFFIXES:
        with Image.open(path) as source:
            if source.width * source.height > 25_000_000:
                raise ValueError("Image is too large for invoice review (maximum 25 megapixels)")
            return ImageOps.exif_transpose(source).convert("RGB")
    if Path(path).suffix.lower()==".pdf":
        import pypdfium2
        with pypdfium2.PdfDocument(str(path)) as document:
            if not 0<=page<len(document): raise ValueError("Choose an existing PDF page")
            rendered=document[page]
            try:
                w,h=rendered.get_size();scale=min(2.5,(8_000_000/max(1,w*h))**.5)
                bitmap=rendered.render(scale=scale)
                try:return bitmap.to_pil().convert("RGB").copy()
                finally:bitmap.close()
            finally:rendered.close()
    with tempfile.TemporaryDirectory(prefix="nanza_review_") as folder:
        preview = Path(folder) / "preview.png"
        vision_reader._prepare_image(path, preview)
        with Image.open(preview) as source: return source.copy()


def review_handwriting(app, path, data):
    """Review a local vision suggestion beside the image before it can fill an entry form."""
    if not data: return data
    from pdf_import import IMAGE_SUFFIXES
    photo_review = Path(path).suffix.lower() in IMAGE_SUFFIXES and (data.get("review_required") or data.get("ocr_used"))
    if not isinstance(app, tk.Misc):
        if data.get("reader") != "vision-local" and not photo_review: return data
        return None  # no UI means no implicit confirmation
    from PIL import Image, ImageTk
    import vision_reader
    from desktop_invoice_intake import annotate, review_items, validate_reviewed_items
    data=annotate(app,data)
    try:
        picture = handwriting_review_image(path,max(0,int((data.get("pages") or [1])[0])-1))
    except (OSError, ValueError, vision_reader.VisionReaderError) as exc:
        messagebox.showerror("Handwriting review", f"Could not show the original for review: {exc}")
        return None
    window = tk.Toplevel(app); window.title("Check the invoice reading"); window.configure(bg=LIGHT); window.transient(app)
    width = min(1160, max(700, app.winfo_screenwidth() - 80))
    height = min(820, max(520, app.winfo_screenheight() - 100))
    window.geometry(f"{width}x{height}")
    tk.Label(window, text="The reader can get amounts and dates wrong. Compare with the image, correct the fields, then confirm.",
             bg=LIGHT, fg=RED, wraplength=width - 40, justify="left").pack(fill="x", padx=12, pady=8)
    notification = data.get("notification_90") or {}
    if notification.get("notify"):
        tk.Label(window, text=notification["message"], bg=LIGHT,
                 fg="#146b37" if notification.get("type") == "success" else RED,
                 wraplength=width - 40, justify="right").pack(fill="x", padx=12, pady=4)
    body = tk.Frame(window, bg=LIGHT); body.pack(fill="both", expand=True, padx=12)
    image_frame = tk.Frame(body, bg=LIGHT); image_frame.pack(side="left", fill="both", expand=True)
    canvas = tk.Canvas(image_frame, bg="#d9dee3", highlightthickness=0)
    vertical = ttk.Scrollbar(image_frame, orient="vertical", command=canvas.yview)
    horizontal = ttk.Scrollbar(image_frame, orient="horizontal", command=canvas.xview)
    canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    vertical.pack(side="right", fill="y"); horizontal.pack(side="bottom", fill="x"); canvas.pack(fill="both", expand=True)
    form_panel=tk.Frame(body,bg=LIGHT,width=330);form_panel.pack(side="right",fill="y",padx=(12,0));form_panel.pack_propagate(False)
    form_actions=tk.Frame(form_panel,bg=LIGHT);form_actions.pack(side="bottom",fill="x")
    form_canvas=tk.Canvas(form_panel,bg=LIGHT,highlightthickness=0,width=305)
    form_scroll=ttk.Scrollbar(form_panel,orient="vertical",command=form_canvas.yview)
    form_scroll.pack(side="right",fill="y");form_canvas.pack(fill="both",expand=True)
    form_canvas.configure(yscrollcommand=form_scroll.set);form_canvas._saber_scroll_page=True
    form=tk.Frame(form_canvas,bg=LIGHT);form_window=form_canvas.create_window((0,0),window=form,anchor="nw")
    form.bind("<Configure>",lambda _e:form_canvas.configure(scrollregion=form_canvas.bbox("all")))
    form_canvas.bind("<Configure>",lambda e:form_canvas.itemconfigure(form_window,width=e.width))
    tk.Label(form,text="Document type (verify)",bg=LIGHT,anchor="w").pack(fill="x")
    document_type=tk.StringVar(value=data.get("document_type") or "unknown")
    ttk.Combobox(form,textvariable=document_type,values=["invoice","receipt","credit_note","debit_note","quotation","delivery_note","unknown"],state="readonly",width=24).pack(fill="x")
    fields = (("invoice_number", "Invoice number"), ("invoice_date", "Date (DD-MM-YYYY)"), ("currency", "Currency"),
              ("party_name", "Supplier / customer"), ("party_tax_number", "Supplier tax ID"),
              ("subtotal", "Subtotal"), ("vat", "VAT"), ("total", "Grand Total"))
    variables = {}
    for key, label in fields:
        tk.Label(form, text=label, bg=LIGHT, anchor="w").pack(fill="x", pady=(5, 1))
        value = data.get(key)
        text = f"{value:.2f}" if key in ("subtotal", "vat", "total") and value is not None else str(value or "")
        variables[key] = tk.StringVar(master=window, value=text)
        tk.Entry(form, textvariable=variables[key], width=30).pack(fill="x")
        evidence=(data.get("fields") or {}).get(key) or {}
        score=evidence.get("confidence")
        detail=f"{evidence.get('origin','unverified')} | confidence: {score:.0%}" if score is not None else f"{evidence.get('origin','unverified')} | confidence: unknown"
        tk.Label(form,text=detail,bg=LIGHT,fg=RED if evidence.get("origin") in ("inferred","missing") else MUTED,anchor="w").pack(fill="x")
        candidates = data.get("reader_candidates") or {}
        if candidates and key not in data.get("consensus_fields", []):
            first = (candidates.get("qwen4b") or {}).get(key)
            second = (candidates.get("qwen2b") or {}).get(key)
            if first not in (None, "") or second not in (None, ""):
                note = f"4B: {first if first not in (None, '') else '—'} | 2B: {second if second not in (None, '') else '—'}"
                tk.Label(form, text=note, bg=LIGHT, fg=RED, wraplength=280, justify="left").pack(fill="x")
    tk.Label(form, text="Blank means unreadable, not zero.\nNo accounting entry is saved here.", bg=LIGHT, fg=MUTED,
             justify="left").pack(fill="x", pady=10)
    classification=data.get("classification") or {}
    suggestion=data.get("account_suggestion") or {}
    classification_score=classification.get("confidence")
    classification_detail=(f"{classification_score:.0%} heuristic match" if classification_score is not None else "confidence unknown")
    tk.Label(form,text=(f"Type: {data.get('document_type','unknown')} / {classification.get('category','other')}\n"
                        f"{classification_detail}: {classification.get('reason') or ''}\n"
                        f"Account suggestion: {suggestion.get('account_code') or 'Choose manually'}\n{suggestion.get('reason') or ''}"),
             bg=LIGHT,fg=NAVY,wraplength=280,justify="left").pack(fill="x",pady=4)
    tk.Button(form,text="Review invoice lines",command=lambda:review_items(window,data)).pack(fill="x",pady=3)
    confirmed = tk.BooleanVar(master=window, value=False)
    tk.Checkbutton(form, text="I checked these fields against the image", variable=confirmed, bg=LIGHT,
                   wraplength=260, justify="left").pack(anchor="w", pady=8)
    answer = []
    def accept():
        if not confirmed.get():
            messagebox.showwarning("Handwriting review", "Check the image and tick the confirmation first", parent=window)
            return
        try:
            if document_type.get() in ("unknown","quotation","delivery_note"):
                raise ValueError("This is not a confirmed accounting invoice/receipt/note. Confirm the document type or cancel.")
            validate_reviewed_items(data)
            result = checked_handwriting_fields(data, {key: var.get() for key, var in variables.items()})
            result["document_type"]=document_type.get()
            result["intake_reviewed"]=True
            result.pop("_review_accounts",None)
        except ValueError as exc:
            messagebox.showwarning("Handwriting review", str(exc), parent=window)
            return
        answer.append(result); window.destroy()
    tk.Button(form_actions, text="Use checked fields", command=accept, bg=GOLD, fg=NAVY, border=0, padx=12, pady=7).pack(fill="x", pady=4)
    tk.Button(form_actions, text="Cancel", command=window.destroy, bg=NAVY, fg="white", border=0, padx=12, pady=7).pack(fill="x", pady=4)
    zoom = [min((width - 370) / picture.width, (height - 130) / picture.height, 1.0)]
    def draw(factor):
        zoom[0] = max(.05, min(3, (8_000_000 / (picture.width * picture.height)) ** .5, zoom[0] * factor))
        resized = picture.resize((max(1, int(picture.width * zoom[0])), max(1, int(picture.height * zoom[0]))), Image.Resampling.LANCZOS)
        try: canvas._handwriting_photo = ImageTk.PhotoImage(resized, master=window)
        finally: resized.close()
        canvas.delete("all"); canvas.create_image(0, 0, image=canvas._handwriting_photo, anchor="nw")
        canvas.configure(scrollregion=canvas.bbox("all"))
    controls = tk.Frame(window, bg=LIGHT); controls.pack(fill="x", padx=12, pady=6)
    tk.Button(controls, text="Zoom +", command=lambda: draw(1.3)).pack(side="left", padx=3)
    tk.Button(controls, text="Zoom -", command=lambda: draw(1 / 1.3)).pack(side="left", padx=3)
    def rotate():
        nonlocal picture
        turned = picture.transpose(Image.Transpose.ROTATE_270)
        picture.close(); picture = turned
        fit()
    def fit():
        zoom[0] = min((width - 370) / picture.width, (height - 130) / picture.height, 1.0)
        draw(1)
    tk.Button(controls, text="Rotate image", command=rotate).pack(side="left", padx=3)
    tk.Button(controls, text="Fit image", command=fit).pack(side="left", padx=3)
    if Path(path).suffix.lower()==".pdf":
        import pypdfium2
        with pypdfium2.PdfDocument(str(path)) as document: page_count=len(document)
        page_var=tk.StringVar(value=str((data.get("pages") or [1])[0]))
        tk.Label(controls,text="Page",bg=LIGHT).pack(side="left")
        page_box=ttk.Combobox(controls,textvariable=page_var,values=[str(n) for n in range(1,page_count+1)],width=4,state="readonly")
        page_box.pack(side="left",padx=3)
        def change_page(_event=None):
            nonlocal picture
            replacement=handwriting_review_image(path,int(page_var.get())-1)
            picture.close();picture=replacement;fit()
        page_box.bind("<<ComboboxSelected>>",change_page)
    def reading_checks():
        details = tk.Toplevel(window); details.title("Unverified invoice reading"); details.configure(bg=LIGHT)
        details.transient(window)
        details.geometry(f"{min(850, app.winfo_screenwidth() - 60)}x{min(560, app.winfo_screenheight() - 80)}")
        panel = tk.Frame(details, bg=LIGHT); panel.pack(fill="both", expand=True, padx=10, pady=10)
        scroll = ttk.Scrollbar(panel); scroll.pack(side="right", fill="y")
        text = tk.Text(panel, wrap="word", yscrollcommand=scroll.set, font=("Segoe UI", 10))
        text.pack(fill="both", expand=True); scroll.config(command=text.yview)
        messages = ["UNVERIFIED transcription: these item rows are not entered in the invoice automatically.",
                    "قراءة غير مؤكدة: هذه الأسطر لا تُضاف تلقائياً إلى الفاتورة. راجعها مع الصورة الأصلية.", ""]
        messages.extend(str(warning) for warning in data.get("review_warnings") or [])
        evidence = data.get("reader_evidence") or {"reader": data.get("transcription_evidence") or {}}
        for reader, candidate in evidence.items():
            messages.extend(["", str(reader)])
            for row in candidate.get("line_evidence") or []:
                literal = row["literal"]
                values = [literal.get(key) if literal.get(key) is not None else "[unreadable]" for key in
                          ("description_as_written", "quantity_as_written", "unit_price_as_written", "total_as_written")]
                messages.append(f"Row {row['row']}: {values[0]} | Qty: {values[1]} | Unit price: {values[2]} | Line total: {values[3]}")
                if row.get("uncertain_fields"): messages.append("Uncertain: " + ", ".join(row["uncertain_fields"]))
                if row.get("arithmetic_difference") is not None: messages.append("Arithmetic difference: " + row["arithmetic_difference"])
        text.insert("1.0", "\n".join(messages)); text.configure(state="disabled")
    tk.Button(controls, text="Reading checks / item rows", command=reading_checks).pack(side="left", padx=3)

    draw(1)
    window.bind("<Escape>", lambda _event: window.destroy())
    window.grab_set()
    try: app.wait_window(window)
    finally: picture.close()
    return answer[0] if answer else None
