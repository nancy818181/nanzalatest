"""Commercial-document workspace using the existing local API and report exports."""

from decimal import Decimal
import tkinter as tk
from tkinter import ttk, messagebox
from uuid import uuid4
from desktop_common import flow_toolbar, main_currency, vat_rate

KINDS = {
    "Quotation": "quotation",
    "Purchase Order": "purchase_order",
    "Consignment Note": "consignment",
}


def open_commercial_documents(app, *, quotations_only=False):
    kinds = {"Quotation": "quotation"} if quotations_only else KINDS
    client = app.client
    company_context = (client.company_id, client.fiscal_year)

    def require_company_context():
        if app.client is not client or (client.company_id, client.fiscal_year) != company_context:
            raise ValueError("The company or fiscal year changed. Reopen Commercial Documents.")

    window = tk.Toplevel(app)
    window.title("Quotations" if quotations_only else "Quotations / Purchase Orders / Consignment")
    window.geometry(
        f"{min(1180,app.winfo_screenwidth()-50)}x{min(760,app.winfo_screenheight()-80)}"
    )
    window.transient(app)
    window._commercial = state = {"document": None, "rows": [], "lookup": {}}
    top = tk.Frame(window)
    top.pack(fill="x", padx=12, pady=8)
    number = tk.StringVar(value="New document — number assigned on Save")
    tk.Label(top, textvariable=number, font=("Segoe UI", 12, "bold")).pack(side="left")
    tk.Label(
        window,
        text=(
            "Save and confirm the quotation, then convert it to a sales invoice draft. Review it in Uploaded Data."
            if quotations_only
            else "Confirm a saved document before receiving or creating a draft invoice. Review and post invoices in Uploaded Data."
        ),
        wraplength=1000,
        justify="left",
    ).pack(fill="x", padx=12)
    bar = tk.Frame(window)
    bar.pack(side="bottom", fill="x", padx=12, pady=8)
    header = tk.Frame(window)
    header.pack(fill="x", padx=12, pady=8)
    fields = {}
    state["fields"] = fields
    parties = app.client.parties()
    party_map = {
        f"{p['name']} [{p['id']}]": p["id"]
        for p in parties if not quotations_only or p.get("kind") in ("customer", "both")
    }
    state["party_map"] = party_map
    currencies = [r["code"] for r in app.client.currencies()]
    for key, label, options, width in (
        ("kind", "Document", list(kinds), 20),
        ("doc_date", "Date", None, 13),
        ("party", "Customer" if quotations_only else "Customer / supplier", list(party_map), 30),
        ("currency", "Currency", currencies, 8),
        ("valid_until", "Valid until (optional)", None, 13),
    ):
        box = tk.Frame(header)
        box.pack(side="left", padx=(0, 8))
        tk.Label(box, text=label).pack(anchor="w")
        fields[key] = tk.StringVar()
        if options is None:
            tk.Entry(box, textvariable=fields[key], width=width).pack()
        else:
            ttk.Combobox(
                box,
                textvariable=fields[key],
                values=options,
                state="readonly",
                width=width,
            ).pack()
    flow_toolbar(header)
    text_fields = {}
    for key, label in (("terms", "Payment / delivery terms"), ("notes", "Notes")):
        row = tk.Frame(window)
        row.pack(fill="x", padx=12, pady=2)
        tk.Label(row, text=label, width=23, anchor="w").pack(side="left")
        text_fields[key] = tk.StringVar()
        tk.Entry(row, textvariable=text_fields[key]).pack(
            side="left", fill="x", expand=True
        )
    pane = ttk.Panedwindow(window, orient="vertical")
    pane.pack(fill="both", expand=True, padx=12, pady=8)
    line_frame = tk.LabelFrame(pane, text="Document lines")
    pane.add(line_frame, weight=3)
    controls = tk.Frame(line_frame)
    controls.pack(side="bottom",fill="x")
    columns = (
        "sku",
        "description",
        "quantity",
        "unit_price",
        "vat_rate",
        "received",
        "invoiced",
    )
    tree = ttk.Treeview(line_frame, columns=columns, show="headings", height=7)
    for key, label, width in zip(
        columns,
        (
            "Item code (optional)",
            "Description",
            "Qty",
            "Unit price",
            "VAT %",
            "Received",
            "Invoiced",
        ),
        (130, 290, 85, 100, 70, 85, 85),
    ):
        tree.heading(key, text=label)
        tree.column(key, width=width, stretch=key == "description")
    scroll = ttk.Scrollbar(line_frame, orient="horizontal", command=tree.xview)
    tree.configure(xscrollcommand=scroll.set)
    scroll.pack(side="bottom",fill="x")
    tree.pack(fill="both", expand=True)

    def refresh_lines():
        tree.delete(*tree.get_children())
        for index, line in enumerate(state["rows"]):
            tree.insert(
                "", "end", iid=str(index), values=[line.get(k, "") for k in columns]
            )

    def edit_line(new=False):
        if state["document"] and state["document"]["status"] != "draft":
            return messagebox.showwarning(
                "Document", "Confirmed documents cannot be edited", parent=window
            )
        selected = tree.selection()
        if not new and not selected:
            return
        index = len(state["rows"]) if new else int(selected[0])
        row = {} if new else state["rows"][index]
        dialog = tk.Toplevel(window)
        dialog.title("Document line")
        dialog.transient(window)
        values = {}
        for n, (key, label) in enumerate(
            zip(
                columns[:5],
                (
                    "Item code (optional)",
                    "Description",
                    "Quantity",
                    "Unit price",
                    "VAT %",
                ),
            )
        ):
            tk.Label(dialog, text=label).grid(
                row=n, column=0, sticky="w", padx=8, pady=5
            )
            values[key] = tk.StringVar(
                value=row.get(
                    key,
                    (
                        "1"
                        if key == "quantity"
                        else str(vat_rate(app)) if key == "vat_rate" else ""
                    ),
                )
            )
            entry = tk.Entry(dialog, textvariable=values[key], width=45)
            entry.grid(row=n, column=1, padx=8, pady=5)
            if key == "sku":
                item_code = entry

        def select_item(product):
            values["sku"].set(product["sku"])
            values["description"].set(product["name"])
            if fields["kind"].get() == "Quotation":
                if product.get("sales_price") is not None:
                    values["unit_price"].set(str(product["sales_price"]))
                if product.get("default_vat") not in (None, ""):
                    default_vat = str(product["default_vat"]).replace("%", "").strip()
                    values["vat_rate"].set("0" if default_vat in ("0", "0.0") else str(vat_rate(app)))

        def search_items(_event=None):
            perform(lambda: app.choose_sales_inventory_item(dialog, select_item, values["sku"].get().strip()))
            return "break"

        tk.Button(dialog, text="Search items (F2)", command=search_items).grid(row=0, column=2, padx=8)
        dialog.bind("<F2>", search_items)
        item_code.focus_set()

        def use():
            from commercial_documents import money

            try:
                result = {key: value.get().strip() for key, value in values.items()}
                if not result["description"]:
                    raise ValueError("Enter a description")
                for key in ("quantity", "unit_price", "vat_rate"):
                    money(result[key], key, key == "quantity")
                if new:
                    state["rows"].append(result)
                else:
                    state["rows"][index] = result
                refresh_lines()
                dialog.destroy()
            except ValueError as exc:
                messagebox.showwarning("Line", str(exc), parent=dialog)

        tk.Button(dialog, text="Use line", command=use).grid(
            row=5, column=0, columnspan=2, pady=8
        )
        dialog.grab_set()

    tk.Button(controls, text="Add line", command=lambda: edit_line(True)).pack(
        side="left"
    )
    tk.Button(controls, text="Edit selected", command=edit_line).pack(
        side="left", padx=4
    )

    def remove():
        if state["document"] and state["document"]["status"] != "draft":
            return
        if tree.selection():
            state["rows"].pop(int(tree.selection()[0]))
            refresh_lines()

    tk.Button(controls, text="Remove selected", command=remove).pack(side="left")
    tree.bind("<Double-1>", lambda _e: edit_line())
    records = tk.LabelFrame(pane, text="Saved documents — double-click to open")
    pane.add(records, weight=2)
    document_search = tk.StringVar()
    search_bar = tk.Frame(records)
    search_bar.pack(fill="x")
    tk.Label(search_bar, text="Find document").pack(side="left", padx=4)
    tk.Entry(search_bar, textvariable=document_search).pack(side="left", fill="x", expand=True, padx=4)
    saved_tree = ttk.Treeview(
        records,
        columns=("number", "kind", "date", "party", "currency", "status"),
        show="headings",
        height=5,
    )
    for key, label, width in (
        ("number", "Number", 165),
        ("kind", "Type", 120),
        ("date", "Date", 100),
        ("party", "Customer" if quotations_only else "Customer / supplier", 250),
        ("currency", "Currency", 80),
        ("status", "Status", 100),
    ):
        saved_tree.heading(key, text=label)
        saved_tree.column(key, width=width)
    scrollbar = ttk.Scrollbar(records, orient="vertical", command=saved_tree.yview)
    saved_tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    saved_tree.pack(fill="both", expand=True)
    saved_documents = []

    def filter_documents(*_args):
        keys = ("number", "kind", "doc_date", "party_name", "currency", "status")
        query = document_search.get().strip().casefold()
        saved_tree.delete(*saved_tree.get_children())
        for doc in saved_documents:
            values = [doc[key] for key in keys]
            if all(term in " ".join(str(value) for value in values).casefold() for term in query.split()):
                saved_tree.insert("", "end", iid=str(doc["id"]), values=values)

    document_search.trace_add("write", filter_documents)

    def load():
        saved_documents[:] = [
            doc for doc in app.client.request("GET", "/api/commercial")["items"]
            if not quotations_only or doc["kind"] == "quotation"
        ]
        filter_documents()

    def display(doc):
        state["document"] = doc
        state["rows"] = [dict(row) for row in doc["lines"]]
        number.set(f"{doc['number']}  |  {doc['status']}  |  {doc['currency']}")
        fields["kind"].set(
            next(label for label, kind in kinds.items() if kind == doc["kind"])
        )
        for key in ("doc_date", "currency", "valid_until"):
            fields[key].set(doc.get(key) or "")
        fields["party"].set(
            next(
                (label for label, pid in party_map.items() if pid == doc["party_id"]),
                "",
            )
        )
        for key in text_fields:
            text_fields[key].set(doc.get(key) or "")
        refresh_lines()

    def selected(_event=None):
        if saved_tree.selection():
            perform(
                lambda: display(
                    app.client.request(
                        "GET", "/api/commercial/" + saved_tree.selection()[0]
                    )
                )
            )

    saved_tree.bind("<Double-1>", selected)

    def new():
        state["document"] = None
        state["rows"] = []
        number.set("New document — number assigned on Save")
        fields["kind"].set("Quotation")
        fields["doc_date"].set(app.fiscal_today())
        fields["currency"].set(main_currency(app))
        fields["party"].set("")
        fields["valid_until"].set("")
        for value in text_fields.values():
            value.set("")
        refresh_lines()

    def perform(operation):
        try:
            require_company_context()
            return operation()
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Commercial documents", str(exc), parent=window)

    def save():
        header = {
            key: value.get().strip() for key, value in fields.items() if key != "party"
        }
        header["party_id"] = party_map.get(fields["party"].get())
        header["kind"] = kinds.get(header["kind"])
        header.update({key: value.get() for key, value in text_fields.items()})
        old = state["document"]
        header["revision"] = old["revision"] if old else None
        result = app.client.request(
            "POST",
            "/api/commercial",
            {"id": old["id"] if old else None, "header": header, "rows": state["rows"]},
        )
        display(result)
        load()

    def status(value):
        doc = state["document"]
        if not doc:
            raise ValueError("Save or open a document first")
        if not messagebox.askyesno(
            "Commercial document", f"{value.title()} {doc['number']}?", parent=window
        ):
            return
        display(
            app.client.request(
                "POST",
                f"/api/commercial/{doc['id']}/status",
                {"status": value, "revision": doc["revision"]},
            )
        )
        load()

    def output(format_name, matching=False):
        doc = state["document"]
        if not doc:
            raise ValueError("Save or open a document first")
        suffix = ("matching" if matching else "print") + "?language=" + app.language.get()
        report = app.client.request("GET", f"/api/commercial/{doc['id']}/{suffix}")
        for section in report["sections"]:
            for row in section["rows"]:
                for index, value in enumerate(row):
                    if (
                        isinstance(value, str)
                        and value
                        and index >= (3 if matching else 2)
                    ):
                        try:
                            row[index] = Decimal(value)
                        except ArithmeticError:
                            pass
        settings = app.client.settings()
        company = (
            settings.get("company_name")
            or getattr(app, "current_company", {}).get("name")
            or ""
        )
        if company:
            report["meta"].insert(0, company)
        app.output_sections(
            report["title"],
            report["meta"],
            report["sections"],
            doc["number"],
            format_name,
        )

    def operation(action):
        doc = state["document"]
        if not doc or doc["status"] != "confirmed":
            raise ValueError("Save and confirm the source document first")
        if action == "receive" and doc["kind"] != "purchase_order":
            raise ValueError("Only a purchase order can be received")
        if action == "invoice" and doc["kind"] == "consignment":
            raise ValueError(
                "A consignment note is not a sale; review the actual transaction separately"
            )
        sale = doc["kind"] == "quotation"
        dialog = tk.Toplevel(window)
        dialog.title("Convert to Sales Invoice" if sale else
                     "Receive goods" if action == "receive" else "Create invoice draft")
        dialog.transient(window)
        tk.Label(
            dialog,
            text=(
                "Tick the lines to transfer and enter their quantities. The sales invoice is saved as a draft."
                if sale
                else "Enter actual quantities. Blank / zero skips a line. Invoice creation always produces a draft for review."
            ),
            wraplength=650,
        ).grid(row=0, column=0, columnspan=4, padx=8, pady=8)
        day = tk.StringVar(value=app.fiscal_today())
        reference = tk.StringVar()
        warehouse = tk.StringVar()
        tk.Label(dialog, text="Date").grid(row=1, column=0)
        tk.Entry(dialog, textvariable=day).grid(row=1, column=1)
        if not sale:
            tk.Label(dialog, text="Receipt reference" if action == "receive" else "Supplier invoice no.").grid(
                row=2, column=0
            )
            tk.Entry(dialog, textvariable=reference).grid(row=2, column=1)
        if action == "receive":
            warehouses = {
                f"{w['code']} - {w['name']}": w["id"]
                for w in app.client.warehouses() if w["active"]
            }
            tk.Label(dialog, text="Warehouse").grid(row=3, column=0)
            ttk.Combobox(
                dialog,
                textvariable=warehouse,
                values=list(warehouses),
                state="readonly",
            ).grid(row=3, column=1)
        line_canvas = tk.Canvas(dialog, height=270, width=680, highlightthickness=0)
        line_canvas.grid(row=4, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
        vertical = ttk.Scrollbar(dialog, orient="vertical", command=line_canvas.yview)
        vertical.grid(row=4, column=3, sticky="ns")
        line_canvas.configure(yscrollcommand=vertical.set)
        line_body = tk.Frame(line_canvas)
        line_canvas.create_window((0, 0), window=line_body, anchor="nw")
        line_body.bind(
            "<Configure>",
            lambda _e: line_canvas.configure(scrollregion=line_canvas.bbox("all")),
        )
        quantities = []
        for index, line in enumerate(doc["lines"], 1):
            qty = tk.StringVar(value="0")
            transfer = tk.BooleanVar(value=False)
            price = tk.StringVar(value=line["unit_price"])
            remaining = (
                Decimal(line["quantity"]) - Decimal(line["received"])
                if action == "receive"
                else Decimal(
                    line["received"]
                    if doc["kind"] == "purchase_order"
                    else line["quantity"]
                )
                - Decimal(line["invoiced"])
            )
            if sale:
                qty.set(str(remaining))
                transfer.set(remaining > 0)
                tk.Checkbutton(
                    line_body, text="Transfer", variable=transfer,
                    state="normal" if remaining > 0 else "disabled",
                ).grid(row=index, column=3, sticky="w", padx=6)
            item = " · ".join(part for part in (line.get("sku"), line["description"]) if part)
            tk.Label(
                line_body, text=f"{index}. {item} (remaining {remaining})",
                wraplength=330, justify="left",
            ).grid(row=index, column=0, sticky="w", padx=8)
            tk.Entry(line_body, textvariable=qty, width=12).grid(row=index, column=1)
            if action == "invoice":
                tk.Entry(line_body, textvariable=price, width=14).grid(
                    row=index, column=2
                )
            quantities.append((index, qty, price, transfer))
        request_key = str(uuid4())

        def apply():
            try:
                require_company_context()
                from commercial_documents import money

                rows = [
                    {
                        "line": index,
                        "quantity": str(money(qty.get() or "0", "quantity", sale)),
                        "unit_price": price.get(),
                    }
                    for index, qty, price, transfer in quantities
                    if (transfer.get() if sale else money(qty.get() or "0", "quantity") > 0)
                ]
                body = {
                    "doc_date": day.get(),
                    "reference": (
                        request_key if action == "invoice" else reference.get()
                    ),
                    "rows": rows,
                }
                if action == "receive":
                    body["warehouse_id"] = warehouses.get(warehouse.get())
                else:
                    body["invoice_number"] = reference.get()
                result = app.client.request(
                    "POST", f"/api/commercial/{doc['id']}/{action}", body
                )
                if action == "invoice":
                    invoice = result["invoice"]
                    messagebox.showinfo(
                        "Invoice draft",
                        f"{invoice['invoice_number']} saved for review. Stock is recorded through receipts / Stock Documents.\nReview and approve in Uploaded Data, then use Payments.",
                        parent=dialog,
                    )
                dialog.destroy()
                if sale and "sales_open_box" in app.__dict__:
                    perform(app.load_sales_customer_list)
                perform(lambda: display(app.client.request("GET", f"/api/commercial/{doc['id']}")))
                perform(load)
            except (RuntimeError, ValueError, KeyError, ArithmeticError) as exc:
                messagebox.showwarning("Not saved", str(exc), parent=dialog)

        tk.Button(
            dialog,
            text=(
                "Save receipt" if action == "receive" else "Create draft — do not post"
            ),
            command=apply,
        ).grid(row=5, column=0, columnspan=3, pady=10)
        dialog.grab_set()

    actions = [
        ("New", new),
        ("Save draft", save),
        ("Open selected", selected),
        ("Confirm", lambda: status("confirmed")),
        ("Cancel document", lambda: status("cancelled")),
    ]
    if not quotations_only:
        actions.append(("Receive partial", lambda: operation("receive")))
    actions.extend((
        ("Convert to Sales Invoice" if quotations_only else "Create invoice draft", lambda: operation("invoice")),
        ("PDF", lambda: output("pdf")),
        ("Excel", lambda: output("xlsx")),
        ("Matching report", lambda: output("pdf", True)),
    ))
    for index, (label, action) in enumerate(actions):
        tk.Button(bar, text=label, command=lambda action=action: perform(action)).grid(
            row=index // 5, column=index % 5, sticky="ew", padx=2, pady=2
        )
    for column in range(5):
        bar.columnconfigure(column, weight=1)
    new()
    perform(load)
    return window
