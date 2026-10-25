"""Purchases & Expenses tab and the purchases page (moved out of desktop_stage3.py in 2.9.42, unchanged)."""
from __future__ import annotations
from desktop_common import search_arrows  # 2.9.78
from desktop_tax_flag import tax_tick, save_tax_flag, load_tax_flag, place as place_tick  # 2.9.113
import logging

from desktop_stage3_common import (  # 2.9.102: the names this module uses (no more 'import *')
    ask_new_item_details, asked_item_details, auto_upload_on, bulk_action, filedialog, GOLD, LIGHT, messagebox,
    mimetypes, MUTED, NAVY, notify_new_items, Path, prepare_pdf_reading, PURCHASE_USES, read_customs_costs,
    read_invoice_pdf, RED, resolve_item, run_with_progress, simpledialog, tk, ttk
)
from desktop_common import flow_toolbars, vat_rate, vat_rate_text, vat_currency  # compact responsive invoice fields
from desktop_common import main_currency  # 2.9.71
from desktop_stage3_common import _dd, _num


PURCHASE_DOCUMENTS = ("Invoice", "Return", "Credit Note", "Debit Note")
PAID_BY = ["On Account (Not Cash)", "Cash", "Bank Transfer", "Cheque", "Card"]


class PurchasesMixin:
    # ================================================================ Purchases & Expenses
    def build_purchases_expenses(self):
        nested = ttk.Notebook(self.purchases_tab); nested.pack(fill="both", expand=True, padx=8, pady=8)
        self.purchase_notebook=nested
        purchases_outer=tk.Frame(nested,bg=LIGHT)
        purchase_totals=tk.Frame(purchases_outer,bg=LIGHT); purchase_totals.pack(side="bottom",fill="x")
        purchase_costs=tk.Frame(nested,bg=LIGHT)
        expenses_outer, expenses = self.scrollable_page(nested)
        nested.add(purchases_outer, text="Purchase Invoice")
        self.purchase_invoice_page=purchases_outer
        nested.add(purchase_costs,text="Cost on Purchase")
        assets_outer=tk.Frame(nested,bg=LIGHT); nested.add(assets_outer,text="Assets & Depreciation")
        assets_tabs=ttk.Notebook(assets_outer); assets_tabs.pack(fill="both",expand=True,padx=4,pady=4); self.assets_tabs=assets_tabs
        asset_accounts_page=tk.Frame(assets_tabs,bg=LIGHT); assets_tabs.add(asset_accounts_page,text="1. Asset Accounts & Depreciation %")
        assets_page=tk.Frame(assets_tabs,bg=LIGHT); assets_tabs.add(assets_page,text="2. Asset Data Entry")
        depreciation_page=tk.Frame(assets_tabs,bg=LIGHT); assets_tabs.add(depreciation_page,text="3. Monthly Depreciation Table")
        self.build_asset_accounts_page(asset_accounts_page); self.build_depreciation_table_page(depreciation_page)
        nested.add(expenses_outer, text="Expenses")
        self.build_purchases_page(purchases_outer,purchase_totals,purchase_costs); self.build_expenses_page(expenses)
        self.build_assets_page(assets_page); self.add_asset_category_selector(assets_page)
        import desktop_design
        desktop_design.tab_bar(nested,min_tabs=4)
        self.load_purchases(); self.load_expenses()

    # ---- purchases
    def build_purchases_page(self, page, totals_parent=None, cost_parent=None):
        f = {"id": None, "pdf": None, "vars": {k: tk.StringVar() for k in ("supplier", "number", "date", "due", "currency", "type", "taxable", "exempt", "rate", "vat", "account", "vat_account")}}
        v = f["vars"]; v["date"].set(self.fiscal_today()); v["currency"].set(main_currency(self,
                1)); v["type"].set("Purchases"); v["rate"].set(f"{vat_rate(self):g}"); v["account"].set("601100000"); v["vat_account"].set("44210")
        f["department"] = tk.StringVar(); f["project"] = tk.StringVar(); f["vat_typed"] = False; self.purchase_form = f
        f["use"] = tk.StringVar(value="Mixed (partial deduction)"); f["reverse"] = tk.BooleanVar(value=False)
        f["discount_percent"] = tk.StringVar(value="0"); f["discount_amount"] = tk.StringVar(value="0"); f["discount_mode"] = "percent"
        f["doc"] = tk.StringVar(value="Invoice")  # 2.9.54: Invoice / Return (goods back to the supplier) / Debit Note / Credit Note
        import desktop_design as design  # 2.9.134: a framed panel with a gold-marked title instead of the plain group box
        box_outer, box = design.panel(page, pady=5); box_outer.pack(fill="x", padx=8, pady=(2, 3))
        # Title and lookup/import actions share one wrapping row to reduce the repeated heading space.
        heading = tk.Frame(box, bg=LIGHT); heading.pack(fill="x", pady=(0, 3))
        tk.Label(heading, text="Purchase Invoice", bg=LIGHT, fg=NAVY, font=("Segoe UI", 11, "bold")).pack(side="left", padx=(0, 8))
        find = tk.Frame(heading, bg=LIGHT); find.pack(side="left", fill="x", expand=True)
        f["find"] = tk.StringVar()
        tk.Label(find, text="Find purchase", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
        f["find_box"] = ttk.Combobox(find, textvariable=f["find"], width=36); f["find_box"].pack(side="left", padx=5)
        f["find_box"].bind("<<ComboboxSelected>>", lambda _e: self.purchase_found()); f["find_box"].bind("<KeyRelease>", lambda _e: self.filter_found_purchases())
        f["find_box"].bind("<Return>", lambda _e: self.purchase_found())
        self.action_button(find, "Import Excel", self.import_purchases_excel).pack(side="left", padx=(5, 3))
        self.action_button(find, "Excel Template", lambda: self.save_invoice_template("purchases")).pack(side="left", padx=3)
        from desktop_common import flow_toolbar
        flow_toolbar(find)
        # The existing controls and callbacks stay in the same order below.
        actions = tk.Frame(box, bg=LIGHT); actions.pack(side="bottom", fill="x", pady=(4, 2))
        fields = tk.Frame(box, bg=LIGHT); fields.pack(side="top", fill="x", expand=True)
        metadata = tk.Frame(fields, bg=LIGHT); metadata.pack(fill="x")
        purchase_fields=[]
        def field(label, make_widget):
            cell=tk.Frame(metadata,bg=LIGHT)
            caption=tk.Label(cell,text=label,bg=LIGHT,fg=NAVY,font=("Segoe UI",9,"bold")); caption.pack(anchor="w",padx=3)
            widget=make_widget(cell); widget.pack(fill="x",expand=True,padx=3,pady=(1,2))
            purchase_fields.append(cell)
            return widget
        f["supplier_box"] = field("Supplier",lambda parent:ttk.Combobox(parent,textvariable=v["supplier"],width=30))
        f["supplier_box"].bind("<KeyRelease>", lambda _e: self.filter_suppliers()); f["supplier_box"].bind("<<ComboboxSelected>>", lambda _e: self.purchase_supplier_chosen())
        field("Supplier Invoice No.",lambda parent:tk.Entry(parent,textvariable=v["number"],width=16))
        field("Date",lambda parent:self.date_entry(parent,v["date"],11))
        field("Due",lambda parent:self.date_entry(parent,v["due"],11))
        field("Currency",lambda parent:ttk.Combobox(parent,textvariable=v["currency"],values=self.currency_codes,state="readonly",width=9))
        field("Type",lambda parent:ttk.Combobox(parent,textvariable=v["type"],values=["Purchases","Assets"],state="readonly",width=12))
        doc_box=field("Document",lambda parent:ttk.Combobox(parent,textvariable=f["doc"],values=list(PURCHASE_DOCUMENTS),state="readonly",width=14))
        doc_box.bind("<<ComboboxSelected>>",lambda _e:self.purchase_doc_changed())
        responsive={"columns":0,"pending":False}
        def arrange_purchase_fields(_event=None):
            if responsive["pending"]: return
            responsive["pending"]=True
            def apply():
                responsive["pending"]=False
                if not metadata.winfo_exists(): return
                width=max(1,metadata.winfo_width())
                columns=4 if width>=1100 else 2 if width>=570 else 1
                if responsive["columns"]==columns: return
                responsive["columns"]=columns
                for index,cell in enumerate(purchase_fields):
                    if columns==2 and index>=4:
                        # Put Currency, Type and Document together in the compact row.
                        row,column=2,index-4
                    else:
                        row,column=index//columns,index%columns
                    cell.grid(row=row,column=column,sticky="ew",padx=2,pady=1)
                for column in range(4): metadata.grid_columnconfigure(column,weight=1 if (column<columns or (columns==2 and column<3)) else 0)
            metadata.after_idle(apply)
        metadata.bind("<Configure>",arrange_purchase_fields,add="+")
        arrange_purchase_fields()
        # Keep account captions visible and let each lookup grow with its cell width.
        accounts_row=tk.Frame(fields,bg=LIGHT); accounts_row.pack(fill="x",pady=(2,0))
        account_cells=[]
        for label,var,width in (("Cost / Asset A/C",v["account"],40),("VAT A/C",v["vat_account"],36)):
            cell=tk.Frame(accounts_row,bg=LIGHT); tk.Label(cell,text=label,bg=LIGHT,fg=NAVY,font=("Segoe UI",9,"bold")).pack(anchor="w",padx=3)
            self.account_search_box(cell,var,width).pack(fill="x",expand=True,padx=3,pady=(1,2)); account_cells.append(cell)
        accounts_row.grid_columnconfigure(0,weight=1,uniform="purchase-accounts"); accounts_row.grid_columnconfigure(1,weight=1,uniform="purchase-accounts")
        for column,cell in enumerate(account_cells): cell.grid(row=0,column=column,sticky="ew",padx=2)
        # Payment mode and account stay together on one horizontal line.
        paid_row=tk.Frame(fields,bg=LIGHT); paid_row.pack(fill="x",pady=(2,0))
        f["paid_by"]=tk.StringVar(value=PAID_BY[0]); f["paid_account"]=tk.StringVar()
        tk.Label(paid_row,text="Paid",bg=LIGHT,fg=NAVY,font=("Segoe UI",9,"bold")).grid(row=0,column=0,sticky="w",padx=(3,4),pady=2)
        ttk.Combobox(paid_row,textvariable=f["paid_by"],values=PAID_BY,state="readonly",width=22).grid(row=0,column=1,sticky="ew",padx=(0,16),pady=2)
        tk.Label(paid_row,text="from A/C",bg=LIGHT,fg=NAVY,font=("Segoe UI",9,"bold")).grid(row=0,column=2,sticky="w",padx=(0,4),pady=2)
        self.account_search_box(paid_row,f["paid_account"],36).grid(row=0,column=3,sticky="ew",padx=(0,4),pady=2)
        tk.Label(paid_row,text="(empty = automatic cash / bank)",bg=LIGHT,fg=MUTED).grid(row=0,column=4,sticky="w",padx=4,pady=2)
        paid_row.grid_columnconfigure(1,weight=1,uniform="purchase-paid")
        paid_row.grid_columnconfigure(3,weight=2,uniform="purchase-paid")
        totals_box = tk.LabelFrame(totals_parent or page, text="Purchase totals", bg="#dfe6ee", padx=10, pady=4)
        r2 = tk.Frame(totals_box, bg="#dfe6ee"); r2.pack(fill="x", pady=(2, 4))
        for label, key, width in (("Taxable Amount", "taxable", 12), ("Exempt Amount", "exempt", 11), ("VAT %", "rate", 5), ("VAT", "vat", 11)):
            tk.Label(r2, text=label, bg="#dfe6ee").pack(side="left"); entry = tk.Entry(r2, textvariable=v[key], width=width); entry.pack(side="left", padx=(4, 8))
            entry.bind("<KeyRelease>", lambda e, k=key: self.purchase_amounts_changed(k))
        f["total"] = tk.Label(r2, text="Total: 0.00", bg="#dfe6ee", fg=NAVY, font=("Segoe UI", 10, "bold")); f["total"].pack(side="left", padx=6)
        summary = tk.Frame(totals_box, bg="#dfe6ee"); summary.pack(fill="x", padx=8)
        tk.Label(summary,text="Total before discount",bg="#dfe6ee").pack(side="left")
        f["gross_summary"] = tk.Label(summary,text="0.00",bg="#dfe6ee",fg=NAVY,width=13,anchor="e"); f["gross_summary"].pack(side="left",padx=(2,16))
        tk.Label(summary,text="Discount %",bg="#dfe6ee").pack(side="left")
        percent_entry=tk.Entry(summary,textvariable=f["discount_percent"],width=6); percent_entry.pack(side="left",padx=4)
        tk.Label(summary,text="or amount",bg="#dfe6ee").pack(side="left")
        amount_entry=tk.Entry(summary,textvariable=f["discount_amount"],width=10); amount_entry.pack(side="left",padx=4)
        percent_entry.bind("<KeyRelease>",lambda _e:self.purchase_discount_changed("percent"))
        amount_entry.bind("<KeyRelease>",lambda _e:self.purchase_discount_changed("amount"))
        f["discount_summary"] = tk.Label(summary,text="Total HT: 0.00",bg="#dfe6ee",fg=NAVY,font=("Segoe UI",9,"bold")); f["discount_summary"].pack(side="right",padx=8)
        # Keep the invoice header focused on supplier, account and payment details.
        # The treatment/dimension controls are placed after the items table below,
        # where they remain part of this same invoice workflow and scroll together.
        tax_options=tk.LabelFrame(page,text="VAT treatment and dimensions",bg=LIGHT,padx=6,pady=3)
        dimensions=tk.Frame(tax_options,bg=LIGHT); dimensions.pack(fill="x")
        self.dimension_selectors(dimensions,f["department"],f["project"])
        treatment=tk.Frame(tax_options,bg=LIGHT); treatment.pack(fill="x",pady=(2,0))
        tk.Label(treatment,text="VAT use",bg=LIGHT,fg=NAVY,font=("Segoe UI",9,"bold")).pack(side="left")
        use_box=ttk.Combobox(treatment,textvariable=f["use"],values=list(PURCHASE_USES),state="readonly",width=23)
        use_box.pack(side="left",padx=(4,6)); use_box.bind("<<ComboboxSelected>>",lambda _e:self.purchase_amounts_changed("use"))
        tk.Label(treatment,text="Mixed prorates input VAT by taxable / total use.",bg=LIGHT,fg=MUTED).pack(side="left",padx=4)
        tk.Checkbutton(treatment,text="Reverse charge",variable=f["reverse"],bg=LIGHT).pack(side="left")
        f["not_deductible"]=tk.BooleanVar(value=False); place_tick(tax_tick(treatment,f["not_deductible"],LIGHT),side="left",padx=(10,0))
        items = tk.LabelFrame(page, text="Purchase Invoice Items · F2 to find an item · double-click a cell to edit", bg=LIGHT, padx=6, pady=2)
        items.pack(fill="both",expand=True,padx=8,pady=2,after=box_outer)
        if totals_parent is not None: totals_box.pack(fill="x", padx=8, pady=(2,4))
        else: totals_box.pack(fill="x", padx=8, pady=(2,4), after=items)
        wh = tk.Frame(items, bg=LIGHT); wh.pack(fill="x"); f["warehouse"] = tk.StringVar()
        tk.Label(wh, text="Warehouse", bg=LIGHT).pack(side="left"); f["warehouse_box"] = ttk.Combobox(wh, textvariable=f["warehouse"], state="readonly",
                width=20); f["warehouse_box"].pack(side="left", padx=4)
        self.action_button(wh, "Add Item Line", lambda: self.purchase_item_line()).pack(side="left", padx=6)
        tk.Button(wh, text="Delete Line", command=lambda: (f["items_sheet"].delete_selected(), self.purchase_items_changed()), bg="#8B1E1E", fg="white",
                border=0, padx=10, pady=5).pack(side="left", padx=2)
        from desktop_brains import EditableSheet
        f["items_sheet"] = EditableSheet(self, items, [("line", "#", 35, "center"), ("item_code", "Item", 125, "w"), ("name", "Description", 410, "w"), ("quantity", "Qty", 70, "e"),
            ("unit", "Unit", 60, "center"), ("unit_cost", "Unit Price", 95, "e"), ("discount_percent", "Discount %", 85, "e"), ("vat_flag", "VAT", 50, "center"), ("total", "Net", 105, "e")],
            ["item_code", "name", "quantity", "unit", "unit_cost", "discount_percent", "vat_flag"], self.purchase_item_changed,
                    height=8)  # 2.9.87: VAT Yes / No per line; 2.9.94: 8 rows so the totals show on a laptop screen
        f["items_sheet"].tree.bind("<F2>", lambda _e: self.purchase_item_lookup())
        f["items_sheet"].tree.master.pack_configure(expand=True,fill="both")
        tax_options.pack(fill="x",padx=8,pady=(2,3),after=items)
        r4 = tk.Frame(actions, bg=LIGHT); r4.pack(side="top", anchor="w", pady=(2, 0))
        r5 = tk.Frame(actions, bg=LIGHT); r5.pack(side="top", anchor="w", pady=(6, 0))  # 2.9.95: row 1 the invoice, row 2 the PDF
        f["pdf_label"] = tk.Label(r5, text="No PDF", bg=LIGHT, fg=MUTED)
        self.action_button(r4, "New", self.new_purchase).pack(side="left", padx=(0, 3))
        tk.Button(r4, text="Auto Calculate", command=self.purchase_auto_calculate, bg=NAVY, fg="white", border=0, padx=12, pady=6).pack(side="left", padx=3)  # 2.9.90
        tk.Button(r4, text="Save Purchase", command=self.save_purchase, bg=GOLD, fg=NAVY, border=0, padx=18, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=3)
        tk.Button(r4, text="Delete", command=self.delete_purchase, bg=RED, fg="white", border=0, padx=12, pady=6).pack(side="left", padx=3)
        tk.Button(r4, text="Cancel Purchase", command=self.cancel_purchase, bg=RED, fg="white", border=0, padx=12, pady=6).pack(side="left", padx=3)  # 2.9.97
        tk.Button(r4, text="Return (goods back)", command=self.return_open_purchase, bg=NAVY, fg="white", border=0, padx=10, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=3)
        self.action_button(r5, "Upload PDF", self.choose_purchase_pdf).pack(side="left", padx=3)
        free_read = self.action_button(r5, "Free PDF Read", self.ai_read_purchase_pdf); free_read.pack(side="left", padx=3)
        self.action_button(r5, "Attachments", lambda: self.purchase_attachments()).pack(side="left", padx=3)
        self.azure_button(r5, self.azure_read_purchase, free_read)  # 2.9.120: only where Azure is set up
        tk.Checkbutton(r5, text="Save automatically after upload", variable=self.auto_upload_var(), bg=LIGHT, fg=NAVY,
                       command=self.remember_auto_upload).pack(side="left", padx=6)
        f["pdf_label"].pack(side="left", padx=8)
        cost = tk.LabelFrame(cost_parent or page, text="Cost on Purchase (customs / freight / insurance) for the selected purchase", bg=LIGHT, padx=8, pady=4); cost.pack(fill="x", padx=8, pady=3)
        f["lc"] = {k: tk.StringVar() for k in ("freight", "insurance", "customs_duties", "customs_group_1", "customs_group_2", "broker_fees", "other_costs",
                                               "import_vat", "customs_declaration_no", "party_name")}
        f["lc"]["party_name"].set("")
        f["lc_payment_method"] = tk.StringVar(value="On Account (Not Cash)")
        f["lc_cash_account"] = tk.StringVar()
        import chart_extra
        f["lc_accounts"] = {key: tk.StringVar(value=code) for key, code in chart_extra.LANDED_COST_ACCOUNTS.items()}
        from landed_costs import COMPONENTS
        f["lc_currency"] = tk.StringVar(value="USD")
        f["lc_rate"] = tk.StringVar()
        f["lc_usd"] = {key: tk.StringVar() for key, _ in COMPONENTS}
        f["lc_lbp"] = {key: tk.StringVar() for key, _ in COMPONENTS}
        settings = tk.Frame(cost, bg=LIGHT); settings.pack(fill="x", pady=4)
        tk.Label(settings, text="Posting currency", bg=LIGHT).pack(side="left")
        ttk.Combobox(settings, textvariable=f["lc_currency"], values=["USD", "LBP"], state="readonly", width=7).pack(side="left", padx=6)
        tk.Label(settings, text="LBP per USD", bg=LIGHT).pack(side="left")
        tk.Entry(settings, textvariable=f["lc_rate"], width=14).pack(side="left", padx=6)
        tk.Label(settings, text="Enter the reviewed exchange rate for these costs.", bg=LIGHT, fg=MUTED).pack(side="left")
        grid = tk.Frame(cost, bg=LIGHT); grid.pack(fill="x", pady=4)
        for col, title in enumerate(("Cost component", "USD amount", "LBP amount", "Allocation")):
            tk.Label(grid, text=title, bg=LIGHT, fg=NAVY, font=("Segoe UI", 9, "bold")).grid(row=0, column=col, sticky="w", padx=6, pady=4)
        for index, (key, label) in enumerate(COMPONENTS, 1):
            tk.Label(grid, text=label, bg=LIGHT).grid(row=index, column=0, sticky="w", padx=6, pady=2)
            tk.Entry(grid, textvariable=f["lc_usd"][key], width=17, justify="right").grid(row=index, column=1, padx=6, pady=2)
            tk.Entry(grid, textvariable=f["lc_lbp"][key], width=17, justify="right").grid(row=index, column=2, padx=6, pady=2)
            allocation = "VAT return, excluded from item cost" if key == "import_vat" else "Items subject to customs" if key.startswith("customs_group") else "All items by purchase value"
            tk.Label(grid, text=allocation, bg=LIGHT, fg=MUTED).grid(row=index, column=3, sticky="w", padx=6)
        f["lc_preview"] = tk.Label(cost, text="", bg=LIGHT, fg=NAVY, anchor="w", justify="left")
        f["lc_preview"].pack(fill="x", pady=4)
        for var in [*f["lc_usd"].values(), *f["lc_lbp"].values(), f["lc_currency"], f["lc_rate"]]:
            var.trace_add("write", lambda *_: self.preview_landed_cost())
        c2 = tk.Frame(cost, bg=LIGHT); c2.pack(fill="x", pady=(4, 0))
        tk.Label(c2, text="Declaration No.", bg=LIGHT).pack(side="left"); tk.Entry(c2, textvariable=f["lc"]["customs_declaration_no"], width=14).pack(side="left", padx=(3, 8))
        tk.Label(c2, text="Paid to", bg=LIGHT).pack(side="left"); f["lc_party_box"] = ttk.Combobox(c2, textvariable=f["lc"]["party_name"], width=28); f["lc_party_box"].pack(side="left", padx=(3, 8))
        payment = tk.Frame(cost, bg=LIGHT); payment.pack(fill="x", pady=3)
        tk.Label(payment, text="Payment Mode", bg=LIGHT).pack(side="left")
        ttk.Combobox(payment, textvariable=f["lc_payment_method"], values=PAID_BY, state="readonly", width=22).pack(side="left", padx=6)
        tk.Label(payment, text="Paid from", bg=LIGHT).pack(side="left")
        self.account_search_box(payment, f["lc_cash_account"], 20).pack(side="left", padx=6)
        actions = tk.Frame(cost, bg=LIGHT); actions.pack(fill="x", pady=3)
        attachments = tk.Frame(cost, bg=LIGHT); attachments.pack(fill="x", pady=3)
        tk.Button(actions, text="Add Cost on Purchase", command=self.save_landed_cost, bg=GOLD, fg=NAVY, border=0, padx=12, pady=5, font=("Segoe UI", 9, "bold")).pack(side="left", padx=3)
        self.action_button(actions, "Edit Cost Accounts", self.edit_landed_cost_accounts).pack(side="left", padx=3)
        self.action_button(attachments, "Import Customs Excel", self.import_customs_excel).pack(side="left", padx=3)
        self.action_button(attachments, "Attach Customs PDF", self.attach_customs_pdf).pack(side="left", padx=3)
        f["lc_label"] = tk.Label(cost, text="", bg=LIGHT, fg=NAVY, anchor="w"); f["lc_label"].pack(fill="x", padx=8)
        report_bar = tk.Frame(cost, bg=LIGHT); report_bar.pack(fill="x", pady=4)
        self.action_button(report_bar, "Cost breakdown PDF", lambda: self.landed_cost_report("pdf")).pack(side="left", padx=3)
        self.action_button(report_bar, "Cost breakdown Excel", lambda: self.landed_cost_report("xlsx")).pack(side="left", padx=3)
        f["pdf_label"].configure(wraplength=600,justify="left")
        flow_toolbars(heading,find,paid_row,treatment,r4,r5,wh,r2,summary,
                      settings,c2,payment,actions,attachments,report_bar)
        f["tree"] = ttk.Treeview(page, columns=[f"c{i}" for i in range(12)])  # kept hidden: the Find box replaces the list
        f["tree"].bind("<<TreeviewSelect>>", lambda _e: self.purchase_selected())

    def purchase_item_line(self, row=None):
        f = self.purchase_form; row = row or {"item_code": "", "name": "", "quantity": 1, "unit": "", "unit_cost": 0, "discount_percent": 0}
        row.setdefault("vat_flag", "Yes")
        self.purchase_item_total(row); iid = f["items_sheet"].insert(row); f["items_sheet"].tree.selection_set(iid); f["items_sheet"].tree.focus(iid); return iid

    def purchase_item_total(self, row):
        qty = _num(row.get("quantity")) or 0; cost = _num(row.get("unit_cost")) or 0; percent = _num(row.get("discount_percent")) or 0
        row["total"] = round(qty * cost * (1 - percent / 100), 2)
        row["_display"] = {"quantity": f"{qty:g}", "unit_cost": f"{cost:,.4f}", "discount_percent": f"{percent:g}" if percent else "", "total": f'{row["total"]:,.2f}',
                           "vat_flag": row.get("vat_flag") or "Yes"}

    def purchase_item_changed(self, iid, key, text):
        row = self.purchase_form["items_sheet"].rows[iid]
        if key in ("item_code", "name"):
            item = self.item_by_code(text) if key == "item_code" else next((i for i in getattr(self, "inventory_rows", []) if i["name"].casefold() == text.strip().casefold()), None)
            if item: row.update(item_code=item["sku"], name=item["name"], unit=item["unit"], unit_cost=row.get("unit_cost") or item["average_cost"])
            elif key == "item_code" and text: messagebox.showwarning("Purchases", f"Item {text} was not found. Type the item name instead: a new item is created on saving."); return False
            else: row[key] = text.strip()
        elif key == "unit": row["unit"] = text.strip()
        elif key == "vat_flag": row["vat_flag"] = "No" if text.strip().casefold() in ("no", "n", "0", "0%", "exempt", "x", "-") else "Yes"
        else:
            value = _num(text, None)
            if value is None or value < 0: messagebox.showwarning("Purchases", "Enter a positive number"); return False
            row[key] = value
        self.purchase_item_total(row); self.purchase_items_changed()

    def purchase_items_changed(self):
        f = self.purchase_form; rows = [r for r in f["items_sheet"].ordered() if (r.get("item_code") or r.get("name")) and _num(r.get("quantity"))]
        if rows:
            f["vars"]["taxable"].set(f'{sum(r["total"] for r in rows if r.get("vat_flag", "Yes") != "No"):.2f}')
            if any(r.get("vat_flag") == "No" for r in rows):  # 2.9.87: lines without VAT make the exempt amount
                f["vars"]["exempt"].set(f'{sum(r["total"] for r in rows if r.get("vat_flag") == "No"):.2f}')
            self.purchase_amounts_changed("taxable")

    def purchase_auto_calculate(self):
        """2.9.90 (owner): the amounts worked out again - taxable / exempt from the item lines (VAT Yes / No), then
        VAT = (taxable - discount) x VAT %, and the total TTC. Use it when a PDF total was read wrongly."""
        f = self.purchase_form; v = f["vars"]
        self.purchase_items_changed()
        taxable = _num(v["taxable"].get()) or 0; rate = _num(v["rate"].get()) or 0
        try: discount = self.purchase_discount(taxable)
        except ValueError as exc: return messagebox.showwarning("Purchases", str(exc))
        v["vat"].set(f"{(taxable - discount) * rate / 100:.2f}"); f["vat_typed"] = False; f["pdf_vat_review"] = False
        self.purchase_amounts_changed("none")
        return float(v["vat"].get())

    def purchase_discount_changed(self, mode):
        self.purchase_form["discount_mode"] = mode
        self.purchase_amounts_changed("discount")

    def purchase_discount(self, taxable):
        f=self.purchase_form
        percent=_num(f["discount_percent"].get(),0)
        amount=_num(f["discount_amount"].get(),0)
        if percent is None or amount is None or percent<0 or percent>100 or amount<0:
            raise ValueError("Discount must be between 0% and 100%, or a positive amount")
        if f["discount_mode"]=="percent":
            amount=round(taxable*percent/100,2)
            f["discount_amount"].set(f"{amount:.2f}")
        else:
            if amount>taxable: raise ValueError("Discount cannot exceed taxable amount")
            f["discount_percent"].set(f"{amount/taxable*100:.4f}" if taxable else "0")
        return amount

    def purchase_item_lookup(self):
        iid, row = self.purchase_form["items_sheet"].selected()
        if not row: return
        window = tk.Toplevel(self); window.title("Items - F2"); window.geometry("640x420"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        search = tk.StringVar(); entry = tk.Entry(window, textvariable=search, width=40); entry.pack(padx=10, pady=8); entry.focus_set()
        list_frame = tk.Frame(window, bg=LIGHT); list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tree = ttk.Treeview(list_frame, columns=("sku", "name", "unit", "cost"), show="headings")
        yscroll = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(list_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew"); yscroll.grid(row=0, column=1, sticky="ns"); xscroll.grid(row=1, column=0, sticky="ew")
        list_frame.grid_rowconfigure(0, weight=1); list_frame.grid_columnconfigure(0, weight=1)
        for key, label, width in (("sku", "Item Code", 130), ("name", "Item Name", 390), ("unit", "Unit", 75), ("cost", "Average Cost", 120)):
            tree.heading(key, text=label); tree.column(key, width=width, minwidth=65, stretch=key == "name", anchor="e" if key == "cost" else "w")
        def fill(*_a):
            tree.delete(*tree.get_children()); text = search.get().casefold()
            for i in getattr(self, "inventory_rows", []):
                if i["active"] and (not text or text in f'{i["sku"]} {i["name"]} {i.get("category") or ""}'.casefold()): tree.insert("", "end",
                        values=(i["sku"], i["name"], i["unit"], f'{i["average_cost"]:,.4f}'))
        def choose(_e=None):
            if tree.selection(): self.purchase_item_changed(iid, "item_code", tree.item(tree.selection()[0], "values")[0]); self.purchase_form["items_sheet"].refresh(iid); window.destroy()
        search.trace_add("write", fill); tree.bind("<Double-1>", choose); tree.bind("<Return>", choose); fill(); search_arrows(entry, tree, choose, search)  # 2.9.78

    def filter_found_purchases(self):
        from desktop import row_matches_search
        f = self.purchase_form; typed = f["find"].get().strip(); choices = list(f.get("find_map", {}))
        f["find_box"]["values"] = [c for c in choices if row_matches_search((c,),typed)]

    def purchase_doc_changed(self):
        doc = self.purchase_form["doc"].get()
        notes = {"Return": "RETURN: goods go back to the supplier (stock out); the supplier owes the amount. Add the returned items below.",
                 "Credit Note": "CREDIT NOTE: a discount from the supplier, no stock movement.",
                 "Debit Note": "DEBIT NOTE: an extra charge from the supplier, no stock movement."}
        self.purchase_form["pdf_label"].config(text=notes.get(doc, "No PDF"), fg=RED if doc in notes else MUTED)

    def return_open_purchase(self):
        """Purchases screen: send goods of the open purchase invoice back to the supplier (2.9.49)."""
        invoice_id = getattr(self, "purchase_form", {}).get("id")
        if not invoice_id: return messagebox.showwarning("Return", "Open the posted purchase invoice first (Find), then press Return.")
        return self.return_selected_invoice(invoice_id)

    def purchase_found(self):
        f = self.purchase_form; invoice_id = f.get("find_map", {}).get(f["find"].get())
        if not invoice_id:
            matches=list(f["find_box"]["values"])
            if len(matches)==1: f["find"].set(matches[0]); invoice_id=f.get("find_map",{}).get(matches[0])
        if not invoice_id: return
        f["tree"].selection_set(str(invoice_id)); self.edit_purchase(); self.purchase_selected()
        f["items_sheet"].clear()
        try: lines = self.client.invoice_items(invoice_id)
        except Exception: lines = []
        for line in lines:
            if line.get("item_code"):
                row = {"item_code": line["item_code"], "name": line["description"], "quantity": float(line["quantity"]), "unit": line.get("unit") or "", "unit_cost": float(line["unit_price"]),
                       "discount_percent": float(line.get("discount_percent") or 0)}
                self.purchase_item_line(row)

    def import_purchases_excel(self):
        from importer import read_invoice_lines
        path = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xlsm")])
        if not path: return
        try: invoices = read_invoice_lines(path, "purchases")
        except Exception as exc: return messagebox.showerror("Import Purchases", f"The Excel file could not be read: {exc}")
        if not messagebox.askyesno("Import Purchases", f"Import {len(invoices)} purchase invoice(s)? Items that do not exist are created automatically."): return
        done = 0; created = 0; errors = []
        for invoice in invoices:
            try:
                lines = []
                for line in invoice["lines"]:
                    before = len(getattr(self, "inventory_rows", []))
                    item = resolve_item(self, line["description"], line.get("unit") or "unit", line.get("item_code") or None)
                    if not self.item_by_code(item["sku"]): created += 1
                    cost = line["unit_price"] * (1 - (line.get("discount_percent") or 0) / 100)
                    lines.append({"item_code": item["sku"], "description": item["name"], "quantity": line["quantity"], "unit": line.get("unit") or item.get("unit"), "unit_price": round(cost, 4),
                                  "vat_rate": line.get("vat_rate", vat_rate(self)), "discount_percent": line.get("discount_percent") or 0, "warehouse": invoice.get("warehouse") or "MAIN"})
                self.client.create_manual_invoice({"invoice_number": invoice["invoice_number"], "invoice_date": invoice["invoice_date"], "party_name": invoice["party_name"], "kind": "purchases",
                                                   "currency": invoice["currency"], "status": "posted", "source_file": Path(path).name}, lines); done += 1
                self.load_inventory()
            except Exception as exc: errors.append(f"{invoice['invoice_number']}: {exc}")
        notify_new_items(self, "Import Purchases")  # 2.9.86: which items were new
        (messagebox.showwarning if errors else messagebox.showinfo)("Import Purchases",
                f"{done} purchase(s) imported and received into stock; {created} new item(s) created." + ("\n" + "\n".join(errors[:12]) if errors else ""))
        self.load_purchases(); self.load_invoices(); self.load_journal(); self.load_trial()

    def filter_suppliers(self):
        f = self.purchase_form; typed = f["vars"]["supplier"].get().strip().casefold(); names = list(f.get("supplier_map", {}))
        f["supplier_box"]["values"] = [n for n in names if typed in n.casefold()] if typed else names

    def purchase_supplier_chosen(self):
        f = self.purchase_form; party = f.get("supplier_map", {}).get(f["vars"]["supplier"].get())
        if party and party.get("currency"): f["vars"]["currency"].set(party["currency"])
        if party and not f.get("id"):  # 2.9.120: posted like this supplier's last invoice
            note = PurchasesMixin.apply_purchase_rule(self, party["name"], party.get("mof_number") or party.get("tax_number"))
            if note: f["pdf_label"].config(text=note, fg=NAVY)

    def apply_purchase_rule(self, name, number=None, text="", lines=()):
        """2.9.120: fill the posting the program learned for this supplier (or the account of similar lines). Returns what was done."""
        from desktop_common import account_label
        f = self.purchase_form; v = f["vars"]
        try: found = self.client.posting_suggestion("purchase", name, number, text, lines)
        except (RuntimeError, OSError, ValueError, AttributeError): return ""
        if not isinstance(found, dict): return ""  # an old data service
        rule = found.get("rule"); account = found.get("account")
        if rule:
            data = rule["data"]
            v["type"].set("Assets" if data.get("entry_type") == "assets" else "Purchases")
            if data.get("expense_account"): v["account"].set(account_label(self, data["expense_account"]))
            if data.get("vat_account"): v["vat_account"].set(account_label(self, data["vat_account"]))
            use = next((label for label, key in PURCHASE_USES.items() if key == data.get("vat_use")), None)
            if use: f["use"].set(use)
            f["reverse"].set(data.get("vat_treatment") == "reverse_charge")
            for key, variable, choices in (("department", f["department"], self.department_choices), ("project", f["project"], self.project_choices)):
                code = data.get(key) or ""
                match = next((c for c in choices() if self.dimension_code(c) == code), None) if code else None
                if match: variable.set(match)
            method = data.get("payment_method") or ""
            if method in PAID_BY and "paid_by" in f:
                f["paid_by"].set(method); f["paid_account"].set(account_label(self, data.get("payment_account") or "") if method != PAID_BY[0] else "")
            if "not_deductible" in f: f["not_deductible"].set(bool(data.get("not_deductible")))
            return (f"Posted like {rule.get('last_reference') or 'the last invoice'} of {rule['label']} "
                    f"(learned from {rule['times']} invoice(s)) - check before Save")
        if account and account.get("code") and float(account.get("confidence") or 0) >= 0.6 and v["account"].get().split(" - ", 1)[0].strip() in ("", "601100000"):
            code = account["code"]
            if account.get("parent"):  # a keyword category: its 9-digit account, opened under the chart account when missing
                try:
                    known = {str(a.get("code")) for a in self.client.accounts()}
                    if code not in known: self.client.save_account({"code": code, "name_en": account.get("name") or f"Expense {code}", "type": "expense",
                                                                     "parent_code": account["parent"] if account["parent"] in known else ""})
                except (RuntimeError, OSError, ValueError): code = account["parent"]
            v["account"].set(account_label(self, code))
            return f"Account {code} suggested ({account['source']}) - check before Save"
        return ""

    def purchase_amounts_changed(self, key):
        f = self.purchase_form; v = f["vars"]
        if key == "vat": f["vat_typed"] = True
        if key in ("taxable", "rate") and not f.get("pdf_vat_review"): f["vat_typed"] = False
        taxable = _num(v["taxable"].get()) or 0; exempt = _num(v["exempt"].get()) or 0; rate = _num(v["rate"].get()) or 0
        try: discount=self.purchase_discount(taxable)
        except ValueError as exc:
            f["discount_summary"].config(text=str(exc),fg=RED); return
        if not f["vat_typed"] and not f.get("pdf_vat_review"): v["vat"].set(f"{(taxable-discount) * rate / 100:.2f}" if taxable else "")
        vat = _num(v["vat"].get()) or 0
        rows=[r for r in f["items_sheet"].ordered() if (r.get("item_code") or r.get("name"))] if "items_sheet" in f else []
        line_discount=sum(round((_num(r.get("quantity")) or 0)*(_num(r.get("unit_cost")) or 0)*(_num(r.get("discount_percent")) or 0)/100,2) for r in rows)
        f["gross_summary"].config(text=f"{taxable+exempt+line_discount:,.2f}")
        f["discount_summary"].config(text=f"−{discount+line_discount:,.2f}  |  Total HT: {taxable+exempt-discount:,.2f}",fg=NAVY)
        f["total"].config(text=f"TOTAL TTC: {taxable+exempt-discount+vat:,.2f} {v['currency'].get()}")

    def new_purchase(self):
        f = self.purchase_form; v = f["vars"]; f["id"] = None; f["pdf"] = None; f["pdf_pending_invoice_id"] = None
        if "not_deductible" in f: f["not_deductible"].set(False)
        f["vat_typed"] = False; f["pdf_vat_review"] = False; f["pdf_suggested_type"] = ""; f["pdf_review_warnings"] = []
        for key in ("supplier", "number", "due", "taxable", "exempt", "vat"): v[key].set("")
        v["date"].set(self.fiscal_today()); v["rate"].set("11"); v["type"].set("Purchases"); v["account"].set("601100000"); f["department"].set("(none)"); f["project"].set("(none)")
        f["use"].set("Mixed (partial deduction)"); f["reverse"].set(False)
        f["discount_mode"]="percent"; f["discount_percent"].set("0"); f["discount_amount"].set("0")
        if "doc" in f: f["doc"].set("Invoice")
        if "paid_by" in f: f["paid_by"].set(PAID_BY[0]); f["paid_account"].set("")
        f["pdf_label"].config(text="No PDF", fg=MUTED); f["total"].config(text="TOTAL TTC: 0.00"); f["tree"].selection_remove(*f["tree"].selection())
        f["items_sheet"].clear(); f["find"].set("")

    def choose_purchase_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF invoice", "*.pdf"), ("Images", "*.png *.jpg *.jpeg")])
        if not path: return
        f = self.purchase_form
        try:
            size = Path(path).stat().st_size
            if not size or size > 15 * 1024 * 1024:
                raise ValueError("Choose a non-empty file smaller than 15 MB")
        except (OSError, ValueError) as exc:
            return messagebox.showerror("Purchase PDF", f"Could not select this file: {exc}")
        if f.get("id"):
            try:
                self.client.upload_attachment(f["id"], Path(path).name, mimetypes.guess_type(path)[0] or "application/pdf", Path(path).read_bytes())
            except Exception as exc:
                return messagebox.showerror("Purchase PDF", f"Could not confirm the PDF attached to purchase {f['id']}: {exc}\nCheck Attachments before trying again.")
            f["pdf"] = None
            f["pdf_label"].config(text=f"{Path(path).name} attached to purchase {f['id']}", fg=NAVY)
            self.load_purchases()
            return
        if path.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):  # 2.9.85: read off the screen; 2.9.118: photos are read too
            prepare_pdf_reading(self)
            return run_with_progress(self, "Purchase PDF", lambda _progress, _cancel: read_invoice_pdf(path, cancel=_cancel),
                                     lambda data: PurchasesMixin._apply_purchase_pdf(self, path, data))
        PurchasesMixin._apply_purchase_pdf(self, path, None)

    def _apply_purchase_pdf(self, path, data):
        from desktop_stage3_common import review_handwriting
        if data is not None:
            data = review_handwriting(self, path, data)
            if data is None: return
        f = self.purchase_form; v = f["vars"]
        if data and data.get("intake_reviewed") and "doc" in f:
            f["doc"].set({"credit_note":"Credit Note","debit_note":"Debit Note"}.get(data.get("document_type"),"Invoice"))
        f["pdf"] = path; f["pdf_suggested_type"] = ""
        f["pdf_review_warnings"] = list((data or {}).get("review_warnings") or [])
        if data is not None:
            f["pdf_suggested_type"] = data.get("suggested_type") or ""
            if not f["id"]:
                f["pdf_vat_review"] = True
                f["vat_typed"] = True
                v["vat"].set(f'{data["vat"]:.2f}' if data.get("vat") is not None else "")
                if data.get("invoice_number") and not v["number"].get(): v["number"].set(data["invoice_number"])
                elif not v["number"].get():
                    typed = simpledialog.askstring(
                        "Purchase invoice number",
                        "The PDF number could not be read. Enter the invoice number as printed, or leave it for later.",
                        parent=self,
                    )
                    if str(typed or "").strip(): v["number"].set(typed.strip())
                if data.get("invoice_date"): v["date"].set(data["invoice_date"])
                elif v["date"].get() == self.fiscal_today(): v["date"].set("")
                v["currency"].set(data.get("currency") or "")
                subtotal=data.get("subtotal")
                if data.get("taxable_subtotal") is not None and "exempt" in v and not v["taxable"].get():  # 2.9.85: rows with and without VAT
                    v["taxable"].set(f'{data["taxable_subtotal"]:.2f}'); v["exempt"].set(f'{data["exempt_subtotal"]:.2f}')
                elif subtotal is not None and not v["taxable"].get(): v["taxable"].set(f'{subtotal:.2f}')
                if data.get("party_name") and not v["supplier"].get(): v["supplier"].set(data["party_name"])
                item_note = self.add_purchase_pdf_items(data)
                self.purchase_amounts_changed("none")
                import posting_rules  # 2.9.120: how this supplier's invoices were posted before
                party = f.get("supplier_map", {}).get(v["supplier"].get())
                rule_note = PurchasesMixin.apply_purchase_rule(self, v["supplier"].get(), (party or {}).get("mof_number") or posting_rules.numbers_in(data.get("text") or ""),
                                                     data.get("text") or "", [i.get("description") for i in data.get("items") or []])
                if rule_note: item_note = f"{item_note}; {rule_note}"
            suggestion=f["pdf_suggested_type"]
            f["pdf_label"].config(text=f"{Path(path).name}: {data.get('notes', '')}" +
                                  (f"; Suggested Type: {suggestion} (review before Save)" if suggestion else
                                   "; Type unclear; review Purchases vs Assets before Save") +
                                  f"; {item_note}; PDF attaches when you press Save", fg=NAVY)
            if not f["id"] and auto_upload_on(self): self.after_idle(self.auto_save_purchase_upload)
        else:
            item_note = self.add_purchase_pdf_items({"items": [], "subtotal": None})
            f["pdf_label"].config(text=f"{Path(path).name}: {item_note}; attachment saves with purchase on Save", fg=NAVY)

    def add_purchase_pdf_items(self, data):
        """Create inventory records at upload time; only reviewed lines enter the invoice on Save."""
        f = self.purchase_form
        if f["items_sheet"].ordered():
            return "existing item lines kept; review them before Save"
        items = data.get("items") or []
        subtotal = data.get("subtotal")
        line_total = lambda i: float(i.get("total") if i.get("total") not in (None, "") else float(i.get("quantity") or 0) * float(i.get("unit_price") or 0))
        if items and subtotal and abs(sum(line_total(i) for i in items) - float(subtotal)) > max(0.05, float(subtotal) * 0.01):
            # 2.9.90: the lines read do not make the invoice (a page missing from the file): the invoice amounts are kept
            return (f"item lines not added: the {len(items)} line(s) read total {sum(line_total(i) for i in items):,.2f} but the invoice says "
                    f"{float(subtotal):,.2f} before VAT (a page may be missing from the PDF) - add the lines by hand or use Auto Calculate")
        if not items and auto_upload_on(self):
            return "no item line read from the PDF; the invoice is posted on its amount (add item lines and Save to move stock)"
        if not items:
            name = simpledialog.askstring(
                "Purchase PDF item",
                "No readable item row was found. Enter the item name to create it in Inventory now, or Cancel to enter it manually later.",
                parent=self,
            )
            if not str(name or "").strip():
                return "no item created; enter an item name and upload again"
            items = [{"description": name.strip(), "quantity": 1, "unit_price": data.get("subtotal") or 0, "unit": "unit"}]
        party = f.get("supplier_map", {}).get(f["vars"]["supplier"].get())
        created = 0
        for row in items:
            try:
                item = resolve_item(self, row["description"], row.get("unit") or "unit", None, party["id"] if party else None)
            except Exception as exc:
                messagebox.showerror("Purchase PDF item", f"{created} item(s) added; could not create {row['description']}: {exc}")
                break
            self.purchase_item_line({
                "item_code": item["sku"], "name": item["name"], "quantity": row["quantity"],
                "unit": item["unit"], "unit_cost": row["unit_price"], "discount_percent": 0,
                "vat_flag": "No" if row.get("vat") == 0 else "Yes",  # 2.9.87: the VAT column of the PDF row
            })
            created += 1
        if created:
            self.load_inventory()
        new = notify_new_items(self, "Purchase PDF")  # 2.9.86
        return f"{created} item(s) created or matched in Inventory ({len(new)} new); review quantity and price before Save"

    def ai_read_purchase_pdf(self, path=None, reader=None):
        """Free PDF Read; 2.9.120: also 'Read with Azure' (path chosen, reader(done) reads it with Azure)."""
        path=path or filedialog.askopenfilename(filetypes=[("PDF invoice","*.pdf")])
        if not path: return
        try:
            size = Path(path).stat().st_size
            if not size or size > 15 * 1024 * 1024:
                raise ValueError("Choose a non-empty PDF smaller than 15 MB")
        except (OSError, ValueError) as exc:
            return messagebox.showerror("Purchase PDF", f"Could not select this file: {exc}")
        from ai_service import read_invoice_pdf as read_ai_pdf
        def show(data):
            from desktop_stage3_common import review_handwriting
            data=review_handwriting(self,path,data)
            if data is None: return
            f=self.purchase_form; v=f["vars"]; f["pdf"]=path
            if data.get("intake_reviewed") and "doc" in f:
                f["doc"].set({"credit_note":"Credit Note","debit_note":"Debit Note"}.get(data.get("document_type"),"Invoice"))
            f["pdf_review_warnings"] = list(data.get("review_warnings") or [])
            f["pdf_vat_review"] = True; f["vat_typed"] = True
            v["vat"].set(f'{data["vat"]:.2f}' if data.get("vat") is not None else "")
            for key,source in (("number","invoice_number"),("date","invoice_date"),("currency","currency"),("supplier","party_name")):
                if data.get(source): v[key].set(data[source])
            if data.get("subtotal") is not None: v["taxable"].set(f'{(data.get("deductible") if data.get("deductible") is not None else data["subtotal"] - (data.get("non_deductible") or 0)):.2f}')
            if data.get("non_deductible") is not None: v["exempt"].set(f'{data["non_deductible"]:.2f}')
            if data.get("vat") is not None: v["vat"].set(f'{data["vat"]:.2f}'); f["vat_typed"]=True
            if data.get("items"):
                if f["items_sheet"].ordered() and not messagebox.askyesno("AI PDF preview", "Replace the current purchase item lines with the suggested lines?"):
                    return
                f["items_sheet"].clear()
            item_note = self.add_purchase_pdf_items(data)
            self.purchase_amounts_changed("none")
            import posting_rules  # 2.9.120: post it like this supplier's earlier invoices
            text = data.get("text") or ""
            rule_note = PurchasesMixin.apply_purchase_rule(self, v["supplier"].get(), data.get("party_tax_number") or posting_rules.numbers_in(text), text,
                                                 [i.get("description") or "" for i in data.get("items") or []])
            if rule_note: item_note = f"{item_note}; {rule_note}"
            if reader: item_note = f"{data.get('notes') or ''}; {item_note}"
            f["pdf_label"].config(text=f"{'Read' if reader else 'Local preview of page 1'}: {Path(path).name} — {item_note}; PDF attaches on Save",fg=NAVY)
            if not f["id"] and auto_upload_on(self): self.after_idle(self.auto_save_purchase_upload)
        if reader: return reader(show)
        self.run_ai_task(lambda key:read_ai_pdf(path,key),show)

    def ai_read_sales_pdf(self):
        path=filedialog.askopenfilename(filetypes=[("PDF invoice","*.pdf")])
        if not path: return
        from ai_service import read_invoice_pdf as read_ai_pdf
        def show(data):
            self.new_sales_invoice(confirm=False)
            if data.get("invoice_date"): self.sales_date.set(data["invoice_date"])
            if data.get("invoice_number"): self.sales_no.set(str(data["invoice_number"]).strip())
            if data.get("party_name"): self.sales_party.set(data["party_name"])
            if data.get("currency"): self.sales_currency.set(data["currency"])
            extracted = [item for item in data.get("items", []) if item.get("quantity") and item.get("unit_price") is not None
                         and item.get("total") is not None and abs(item["quantity"] * item["unit_price"] - item["total"]) <= 0.02]
            if extracted:
                line = self.sales_items[0]
                for index, item in enumerate(extracted):
                    target = line if index == 0 else None
                    values = {"description": item["description"], "quantity": item["quantity"], "unit": "unit",
                              "unit_price": item["unit_price"], "discount_percent": 0,
                              "vat_rate": round(data["vat"] / data["subtotal"] * 100, 4) if data.get("subtotal") and data.get("vat") is not None else 0}
                    if target is None: self.add_sales_item(values)
                    else:
                        target.update(values); self.recalculate_sales_item(target)
                        self.sales_sheet.item(target["_iid"], values=self.sales_row_values(target))
            else:
                line=self.sales_items[0]
                line.update(description=f"As per {Path(path).name}",quantity=1,unit_price=data.get("subtotal") or data.get("total") or 0)
                if data.get("subtotal") and data.get("vat") is not None:
                    line["vat_rate"]=round(data["vat"] / data["subtotal"]*100,4)
                self.recalculate_sales_item(line)
                self.sales_sheet.item(line["_iid"],values=self.sales_row_values(line))
            self.update_sales_totals()
            messagebox.showinfo("PDF preview",f"Read page 1 of {Path(path).name}. Check the customer, VAT, amounts and invoice number before Save.")
        self.run_ai_task(lambda key:read_ai_pdf(path,key),show)

    def purchase_payload(self):
        f = self.purchase_form; v = f["vars"]
        if f.get("pdf_vat_review") and not v["vat"].get().strip():
            raise ValueError("Confirm VAT from the PDF before saving; type 0 if there is no VAT")
        asset_account = v["account"].get().split(" - ", 1)[0].strip()
        if v["type"].get() == "Assets" and not asset_account.startswith("2"):
            raise ValueError("Assets require a class 2 fixed-asset account in Cost / Asset A/C")
        if v["type"].get() == "Purchases" and asset_account and not asset_account.startswith("6"):
            raise ValueError("Purchases require a class 6 purchase cost account; choose Assets for a fixed-asset account")
        self.purchase_items_changed()
        if not v["supplier"].get().strip(): raise ValueError("Choose or type the supplier")
        if not v["currency"].get().strip(): raise ValueError("Choose the invoice currency; the reader did not identify it")
        taxable = _num(v["taxable"].get()); exempt = _num(v["exempt"].get()); vat = _num(v["vat"].get()); rate = _num(v["rate"].get())
        if None in (taxable, exempt, vat, rate) or min(taxable, exempt, vat) < 0: raise ValueError("Amounts must be positive numbers")
        if not taxable and not exempt: raise ValueError("Enter the taxable or exempt amount")
        discount=self.purchase_discount(taxable)
        net_taxable=round(taxable-discount,2)
        party = f.get("supplier_map", {}).get(v["supplier"].get())
        invoice = {"invoice_number": v["number"].get().strip(), "invoice_date": v["date"].get().strip(), "due_date": v["due"].get().strip(),
                "party_name": party["name"] if party else v["supplier"].get().strip(),
                   "kind": "assets" if v["type"].get() == "Assets" else "purchases", "currency": v["currency"].get(), "status": "posted", "source_file": "Purchase Invoice",
                   "expense_account": asset_account or "601100000", "vat_account": v["vat_account"].get().split(" - ", 1)[0].strip() or "442660000",
                   "department": self.dimension_code(f["department"].get()), "project": self.dimension_code(f["project"].get()),
                   "vat_use": PURCHASE_USES.get(f["use"].get(), "mixed"), "vat_treatment": "reverse_charge" if f["reverse"].get() else "standard",
                   "invoice_discount_percent": f["discount_percent"].get(), "invoice_discount_amount": str(discount), "gross_before_discount": str(taxable+exempt)}
        if party and party.get("account_number"): invoice["supplier_account"] = party["account_number"]
        if v["type"].get() == "Assets": invoice["expense_no_vat_account"] = asset_account
        doc = f["doc"].get() if "doc" in f else "Invoice"
        if doc in ("Return", "Credit Note"):  # the supplier owes us: Dr supplier / Cr purchases and VAT
            invoice.update(doc_subtype="credit_note", is_return=doc == "Return", supplier_side="D", vat_side="C", expense_side="C", expense_no_vat_side="C")
        elif doc == "Debit Note": invoice["doc_subtype"] = "debit_note"
        paid_by = f["paid_by"].get() if "paid_by" in f else PAID_BY[0]
        if doc in ("Invoice", "Debit Note") and paid_by != PAID_BY[0]:
            invoice.update(payment_method=paid_by, amount_paid="full",
                           cash_account=f["paid_account"].get().split(" - ", 1)[0].strip())
        else: invoice.update(payment_method=PAID_BY[0], amount_paid="0")
        stock = [r for r in f["items_sheet"].ordered() if (r.get("item_code") or r.get("name")) and _num(r.get("quantity"))]
        exempt_rows = sum(round((_num(r["unit_cost"]) or 0) * (_num(r["quantity"]) or 0) * (1 - (_num(r.get("discount_percent")) or 0) / 100), 2) for r in stock if r.get("vat_flag") == "No")
        taxable_rows = [r for r in stock if r.get("vat_flag") != "No"]
        if stock:
            lines = []; warehouse = (f["warehouse"].get() or "MAIN").split(" - ", 1)[0]
            for r in stock:
                code = r.get("item_code")
                if not code:
                    item = resolve_item(self, r["name"], r.get("unit") or "unit", None, party["id"] if party else None); code = item["sku"]
                cost = (_num(r["unit_cost"]) or 0) * (1 - (_num(r.get("discount_percent")) or 0) / 100)
                if r.get("vat_flag") != "No": cost *= net_taxable/taxable if taxable else 1
                item_row = next((i for i in getattr(self, "inventory_rows", []) if i.get("sku") == code), None)
                line = {"item_code": code, "description": r.get("name") or code, "quantity": _num(r["quantity"]), "unit": r.get("unit") or "", "unit_price": round(cost, 6),
                              "discount_percent": _num(r.get("discount_percent")) or 0, "vat_rate": rate, "warehouse": warehouse}
                if item_row and item_row.get("cost_account") and v["type"].get() != "Assets": line["expense_account"] = item_row["cost_account"]
                if r.get("vat_flag") == "No":  # 2.9.87: a line without VAT
                    line.update(vat_rate=0, vat=0, deductible_subtotal=0, non_deductible_subtotal=round(line["quantity"] * line["unit_price"], 2))
                lines.append(line)
            taxed = [line for line in lines if line.get("vat_rate") != 0 or "non_deductible_subtotal" not in line]
            remaining_subtotal=net_taxable; remaining_vat=vat
            for index,line in enumerate(taxed):
                subtotal=(round(line["quantity"]*line["unit_price"],2) if index<len(taxed)-1 else remaining_subtotal)
                line["deductible_subtotal"]=subtotal
                line_vat=(round(subtotal*rate/100,2) if index<len(taxed)-1 else remaining_vat)
                line["vat"]=line_vat
                remaining_subtotal=round(remaining_subtotal-subtotal,2); remaining_vat=round(remaining_vat-line_vat,2)
            if any(line["deductible_subtotal"]<0 or line["vat"]<0 for line in lines) or (vat and not taxed):
                raise ValueError("Item totals do not match the purchase amount and VAT. Check the item lines")
            extra_exempt = round(exempt - exempt_rows, 2)
            if extra_exempt > 0.004: lines.append({"description": "Exempt part", "quantity": 1, "unit_price": extra_exempt, "deductible_subtotal": 0,
                    "non_deductible_subtotal": extra_exempt, "vat_rate": 0, "vat": 0})
            return invoice, lines
        line = {"description": f"Supplier invoice {invoice['invoice_number']}".strip(), "quantity": 1, "unit_price": net_taxable, "deductible_subtotal": net_taxable,
                "non_deductible_subtotal": exempt, "vat_rate": rate, "vat": vat}
        return invoice, [line]

    # ------------------------------------------------------------ 2.9.50: upload = saved, posted and in stock
    def auto_upload_var(self):
        if getattr(self, "_auto_upload", None) is None:
            import app_runtime, json as _json
            try: value = bool(_json.loads((app_runtime.data_dir() / "upload_settings.json").read_text(encoding="utf-8")).get("auto_save", True))
            except (OSError, UnicodeError, ValueError, TypeError, AttributeError): value = True
            self._auto_upload = tk.BooleanVar(master=self, value=value)
        return self._auto_upload

    def remember_auto_upload(self):
        import app_runtime, json as _json
        try: (app_runtime.data_dir() / "upload_settings.json").write_text(_json.dumps({"auto_save": bool(auto_upload_on(self))}), encoding="utf-8")
        except OSError: pass

    def purchase_upload_missing(self):
        f = self.purchase_form; v = f["vars"]; missing = []
        if not v["supplier"].get().strip(): missing.append("supplier")
        if not v["number"].get().strip(): missing.append("invoice number")
        if not v["date"].get().strip(): missing.append("date")
        if not (_num(v["taxable"].get()) or _num(v["exempt"].get())): missing.append("amount")
        if v["vat"].get().strip() == "": missing.append("VAT (type 0 if none)")
        suggestion = f.get("pdf_suggested_type")
        if suggestion and suggestion != v["type"].get(): missing.append(f"type check (the PDF looks like {suggestion})")
        return missing

    def auto_save_purchase_upload(self):
        """After an upload: save, post the entry and receive the items at once when everything needed was read."""
        f = self.purchase_form
        if f.get("id"): return
        warnings = f.get("pdf_review_warnings") or []
        if warnings:
            f["pdf_label"].config(text="Not saved automatically - review the original invoice: " + "; ".join(warnings) + "; then press Save Purchase", fg=RED)
            return
        missing = self.purchase_upload_missing()
        if missing:
            f["pdf_label"].config(text=f"Not saved automatically - complete: {', '.join(missing)}; then press Save Purchase", fg=RED)
            return
        self.save_purchase(auto=True)

    def save_purchase(self, auto=False):
        f = self.purchase_form
        pending_id = f.get("pdf_pending_invoice_id")
        if pending_id and f.get("id") == pending_id and f.get("pdf"):
            try:
                content = Path(f["pdf"]).read_bytes()
                attachments = self.client.attachments(pending_id)
                matching = (a for a in attachments if a["file_name"] == Path(f["pdf"]).name and a["size"] == len(content))
                if not any(self.client.download_attachment(a["id"])["content"] == content for a in matching):
                    self.client.upload_attachment(pending_id, Path(f["pdf"]).name,
                                                  mimetypes.guess_type(f["pdf"])[0] or "application/pdf", content)
            except Exception as exc:
                return messagebox.showwarning("Purchases",
                    f"Purchase {pending_id} is already SAVED; PDF is not confirmed attached: {exc}\n"
                    "Press Save to retry ONLY the PDF, or check Attachments. Do not create the invoice again.")
            self.new_purchase(); self.load_purchases(); self.load_invoices(); self.load_journal(); self.load_trial()
            return messagebox.showinfo("Purchases", f"PDF attached to the already saved purchase {pending_id}; invoice was not posted again.")
        if pending_id:
            f["pdf_pending_invoice_id"] = None
        try:
            pdf_content = Path(f["pdf"]).read_bytes() if f.get("pdf") else None
            if pdf_content is not None and (not pdf_content or len(pdf_content) > 15 * 1024 * 1024):
                raise ValueError("PDF must be non-empty and smaller than 15 MB")
        except (OSError, ValueError) as exc:
            return messagebox.showerror("Purchases", f"PDF cannot be read; purchase not saved: {exc}")
        try: invoice, lines = self.purchase_payload()
        except ValueError as exc: return messagebox.showwarning("Purchases", str(exc))
        suggestion=f.get("pdf_suggested_type")
        if suggestion and suggestion != f["vars"]["type"].get():
            if not messagebox.askyesno("Review PDF type",
                    f"This PDF suggests {suggestion}, but the form is set to {f['vars']['type'].get()}.\n"
                    "A paid Expense belongs in Expenses; an unpaid supplier bill belongs in Purchases. "
                    "Confirm the type and accounts before posting.\n\nSave with the selected type anyway?"):
                return
        if not f["id"]:
            try: found = self.client.invoice_duplicates([{**invoice, "kind": invoice.get("kind")}])[0]
            except Exception: found = []
            if isinstance(found, list) and found:
                old = found[0]; text = f"Invoice {invoice['invoice_number']} of {invoice['party_name']} is already saved (ID {old['id']}, {old['invoice_date']}, total {float(old['total'] or 0):,.2f} {old['currency']})."
                if auto:
                    f["pdf_label"].config(text=text + " Not saved again.", fg=RED); return
                if not messagebox.askyesno("Already saved", text + "\n\nSave it again anyway?"): return
        asked = asked_item_details(self)
        try: items_before = {i["id"] for i in self.client.inventory_items()} if asked else set()
        except Exception: items_before = set(); asked = []
        try:
            invoice_id = self.client.replace_invoice(f["id"], invoice, lines) if f["id"] else self.client.create_manual_invoice({**invoice, "duplicate_ok": True}, lines)["invoice_id"]
        except Exception as exc:
            return messagebox.showerror("Purchases", f"{exc}\nIf the result is uncertain, check the purchase list before retrying.")
        if "not_deductible" in f: save_tax_flag(self.client, "invoice", invoice_id, f["not_deductible"])
        if pdf_content is not None:
            try:
                self.client.upload_attachment(invoice_id, Path(f["pdf"]).name,
                                              mimetypes.guess_type(f["pdf"])[0] or "application/pdf", pdf_content)
            except Exception as exc:
                f["id"] = invoice_id
                f["pdf_pending_invoice_id"] = invoice_id
                f["pdf_label"].config(text=f"Purchase {invoice_id} SAVED, PDF not attached; press Save to retry PDF only", fg=RED)
                self.load_purchases(); self.load_invoices(); self.load_journal(); self.load_trial()
                return messagebox.showwarning("Purchases",
                    f"Purchase {invoice_id} is SAVED, but the PDF attachment failed: {exc}\n"
                    "Press Save again to retry ONLY the PDF; the purchase and its items will not be posted twice.")
        if asked:  # 2.9.101: the items this purchase created get their category / brand in a table
            try: created = [i for i in self.client.inventory_items() if i["id"] not in items_before]
            except Exception: created = []
            if created: ask_new_item_details(self, created, "Purchase", asked); self.load_inventory()
        if auto:
            messagebox.showinfo("Purchases", f"Uploaded invoice {invoice['invoice_number']} saved automatically: journal entry INV-{invoice_id} posted"
                                + (", items received in stock" if len(lines) > 1 or lines[0].get("item_code") else "") + (" and PDF attached." if f["pdf"] else "."))
        else:
            messagebox.showinfo("Purchases", "Purchase invoice saved" + (" with its PDF" if f["pdf"] else ""))
        self.new_purchase(); self.load_purchases(); self.load_invoices(); self.load_journal(); self.load_trial()

    def purchase_rows_list(self):
        try: rows = self.client.invoices()
        except Exception: return []
        return [r for r in rows if r["kind"] == "purchase" and r.get("entry_type") in ("purchases", "assets") and r.get("status") != "cancelled"]

    def load_purchases(self):
        f = getattr(self, "purchase_form", None)
        if not f or not f["tree"].winfo_exists(): return
        try: parties = self.client.parties()
        except Exception: parties = []
        f["supplier_map"] = {f'{p["name"]} | {p.get("account_number") or ""}': p for p in parties if p["kind"] in ("supplier", "both")}
        f["supplier_box"]["values"] = list(f["supplier_map"])
        f["lc_party_map"] = {f'{p["name"]} | {p.get("account_number") or ""}': p for p in parties
                             if (p.get("account_category") in ("supplier", "asset_supplier", "other_payable")) or p["kind"] in ("supplier", "both")}
        if f.get("lc_party_box"): f["lc_party_box"]["values"] = list(f["lc_party_map"])
        rows = self.purchase_rows_list(); lists = self.dimension_lists()
        departments = {d["id"]: d["code"] for d in lists["departments"]}; projects = {p["id"]: p["code"] for p in lists["projects"]}
        landed = {}
        for r in rows:
            if r.get("description") and str(r.get("description")).startswith("Landed cost of"): continue
        customs = [r for r in rows if (r.get("description") or "").startswith("Landed cost of")]
        f["rows"] = {str(r["id"]): r for r in rows if not (r.get("description") or "").startswith("Landed cost of")}
        for r in customs:
            key = (r.get("description") or "").split("Landed cost of ", 1)[-1].split(" (", 1)[0]
            totals = landed.setdefault(key, {}); totals[r["currency"]] = totals.get(r["currency"], 0) + float(r.get("total") or 0)
        f["find_map"] = {f'{r["invoice_number"]} | {_dd(r["invoice_date"])} | {r.get("party_name") or ""} | {float(r.get("total") or 0):,.2f} {r["currency"]}': r["id"] for r in f["rows"].values()}
        f["find_box"]["values"] = list(f["find_map"])
        try: f["warehouse_box"]["values"] = [f'{w["code"]} - {w["name"]}' for w in self.client.warehouses() if w["active"]]
        except Exception: logging.getLogger("saber.ignored").debug("Ignored error", exc_info=True)
        if not f["warehouse"].get() and f["warehouse_box"]["values"]: f["warehouse"].set(f["warehouse_box"]["values"][0])
        f["tree"].delete(*f["tree"].get_children())
        for r in f["rows"].values():
            f["tree"].insert("", "end", iid=str(r["id"]), values=(r["invoice_number"], _dd(r["invoice_date"]), r.get("party_name") or "", (r.get("entry_type") or "").title(), r["currency"],
                f'{float(r.get("deductible_subtotal") or 0):,.2f}', f'{float(r.get("non_deductible_subtotal") or 0):,.2f}', f'{float(r.get("vat") or 0):,.2f}', f'{float(r.get("total") or 0):,.2f}',
                " / ".join(f"{value:,.2f} {code}" for code, value in sorted(landed.get(r["invoice_number"], {}).items())), r.get("attachment_count") or "",
                " / ".join(x for x in (departments.get(r.get("department_id")), projects.get(r.get("project_id"))) if x)))

    def selected_purchase(self):
        selected = self.purchase_form["tree"].selection()
        return self.purchase_form.get("rows", {}).get(selected[0]) if selected else None

    def purchase_selected(self):
        row = self.selected_purchase(); f = self.purchase_form
        if not row: f["lc_label"].config(text=""); return
        try: costs = self.client.landed_costs(row["id"])
        except Exception: costs = []
        totals = {}
        for cost in costs: totals[cost["currency"]] = totals.get(cost["currency"], 0) + cost["total"]
        amounts = " / ".join(f"{total:,.2f} {currency}" for currency, total in sorted(totals.items()))
        f["lc_label"].config(text=f"{row['invoice_number']}: {len(costs)} cost line(s), {amounts}" if costs else f"{row['invoice_number']}: no cost on purchase yet")

    def edit_purchase(self):
        row = self.selected_purchase(); f = self.purchase_form; v = f["vars"]
        if not row: return
        if row.get("status") in ("deleted","cancelled"):
            return messagebox.showwarning("Purchases","Deleted or cancelled purchases cannot be edited")
        f["id"] = row["id"]; f["pdf"] = None; f["vat_typed"] = True
        if "not_deductible" in f: load_tax_flag(self.client, "invoice", row["id"], f["not_deductible"])
        discount=_num(row.get("invoice_discount_amount")) or 0
        net_taxable=float(row.get("deductible_subtotal") or 0)
        gross_taxable=round(net_taxable+discount,2)
        f["discount_mode"]="amount"; f["discount_amount"].set(f"{discount:.2f}")
        f["discount_percent"].set(str(row.get("invoice_discount_percent") or "0"))
        f["items_sheet"].clear()
        try: saved_items=self.client.invoice_detail(row["id"]).get("items",[])
        except Exception: saved_items=[]
        factor=net_taxable/gross_taxable if gross_taxable else 1
        for item in saved_items:
            if not item.get("item_code"): continue
            line_percent=_num(item.get("discount_percent")) or 0
            unit_cost=float(item.get("unit_price") or 0)/max((1-line_percent/100)*factor,0.000001)
            self.purchase_item_line({"item_code":item["item_code"],"name":item.get("description") or "", "quantity":_num(item.get("quantity")) if item.get("quantity") not in (None, "") else 1,
                                     "unit":item.get("unit") or "", "unit_cost":unit_cost,"discount_percent":line_percent})
        label = next((n for n, p in f.get("supplier_map", {}).items() if p["name"] == row.get("party_name")), row.get("party_name") or "")
        for key, value in (("supplier", label), ("number", row["invoice_number"]), ("date", _dd(row["invoice_date"])), ("due", _dd(row.get("due_date")) if row.get("due_date") else ""),
                           ("currency", row["currency"]), ("type", "Assets" if row.get("entry_type") == "assets" else "Purchases"), ("taxable", f'{gross_taxable:.2f}'),
                           ("exempt", f'{float(row.get("non_deductible_subtotal") or 0):.2f}'), ("vat", f'{float(row.get("vat") or 0):.2f}'), ("account", row.get("expense_account") or ""),
                           ("vat_account", row.get("vat_account") or "")):
            v[key].set(value)
        taxable = float(row.get("deductible_subtotal") or 0); v["rate"].set(f'{float(row.get("vat") or 0) / taxable * 100:g}' if taxable else f"{vat_rate(self):g}")
        lists = self.dimension_lists()
        f["department"].set(next((f'{d["code"]} - {d["name"]}' for d in lists["departments"] if d["id"] == row.get("department_id")), "(none)"))
        f["project"].set(next((f'{p["code"]} - {p["name"]}' for p in lists["projects"] if p["id"] == row.get("project_id")), "(none)"))
        f["use"].set(next((k for k, val in PURCHASE_USES.items() if val == (row.get("vat_use") or "mixed")),
                "Mixed (partial deduction)")); f["reverse"].set(row.get("vat_treatment") == "reverse_charge")
        if "paid_by" in f:
            paid = float(row.get("amount_paid") or 0); method = row.get("payment_method") or ""
            f["paid_by"].set(method if paid and method in PAID_BY else PAID_BY[0]); f["paid_account"].set(row.get("payment_account") or "")
        if "doc" in f: f["doc"].set("Return" if row.get("doc_subtype") == "credit_note" and row.get("is_return") else
                                    {"credit_note": "Credit Note", "debit_note": "Debit Note"}.get(row.get("doc_subtype") or "", "Invoice"))
        f["pdf_label"].config(text=f"Editing {row['invoice_number']} ({row.get('attachment_count') or 0} document(s) attached)", fg=NAVY); self.purchase_amounts_changed("none")

    def delete_purchase(self):
        f = self.purchase_form; selected = f["tree"].selection()
        if len(selected) > 1:  # 2.9.69: several selected
            items = [(f["rows"][iid]["id"], f["rows"][iid]["invoice_number"]) for iid in selected if iid in f["rows"]]
            if not messagebox.askyesno("Purchases", f"Mark {len(items)} purchases DELETED? Their numbers stay in the invoice list; their journal entries are removed."): return
            bulk_action("Purchases", items, self.client.delete_invoice)
            self.new_purchase(); self.load_purchases(); self.load_invoices(); self.load_journal(); self.load_trial(); return
        row = self.selected_purchase() if not self.purchase_form["id"] else self.purchase_form["rows"].get(str(self.purchase_form["id"]))
        if not row: return messagebox.showwarning("Purchases", "Select a purchase first")
        if not messagebox.askyesno("Purchases", f"Mark purchase {row['invoice_number']} DELETED? Its number stays in the invoice list; the journal entry is removed."): return
        try: self.client.delete_invoice(row["id"])
        except Exception as exc: return messagebox.showerror("Purchases", str(exc))
        self.new_purchase(); self.load_purchases(); self.load_invoices(); self.load_journal(); self.load_trial()

    def cancel_purchase(self):
        """2.9.97: a saved purchase that came out wrong is CANCELLED: a reversing journal entry is posted, the purchase stays in
        the list as Cancelled (its number and the reason are kept for the audit). Then enter it again correctly."""
        row = self.selected_purchase() if not self.purchase_form["id"] else self.purchase_form["rows"].get(str(self.purchase_form["id"]))
        if not row: return messagebox.showwarning("Cancel Purchase", "Select the purchase in the list first")
        if str(row.get("status") or "") in ("cancelled", "deleted"): return messagebox.showwarning("Cancel Purchase", f"Purchase {row['invoice_number']} is already {row['status']}")
        window = tk.Toplevel(self); window.title("Cancel Purchase"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        tk.Label(window, text=f"Cancel purchase {row['invoice_number']} ({row.get('party_name') or ''}, {row.get('currency') or ''} {row.get('total') or ''})",
                 bg=LIGHT, fg=NAVY, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=2, padx=14, pady=(14, 4), sticky="w")
        tk.Label(window, text="A reversing entry is posted; the purchase stays in the list as Cancelled. Then enter it again correctly.",
                 bg=LIGHT, fg=MUTED).grid(row=1, column=0, columnspan=2, padx=14, sticky="w")
        reason = tk.StringVar(value="Wrong total")
        tk.Label(window, text="Reason", bg=LIGHT).grid(row=2, column=0, padx=14, pady=12, sticky="w")
        entry = tk.Entry(window, textvariable=reason, width=45); entry.grid(row=2, column=1, padx=14, pady=12); entry.focus_set(); entry.select_range(0, "end")
        def confirm():
            if not reason.get().strip(): return messagebox.showwarning("Cancel Purchase", "Enter the reason", parent=window)
            try: self.client.cancel_invoice(row["id"], reason.get().strip())
            except Exception as exc: return messagebox.showerror("Cancel Purchase", str(exc), parent=window)
            window.destroy(); self.new_purchase(); self.load_purchases(); self.load_invoices(); self.load_journal(); self.load_trial()
            messagebox.showinfo("Cancel Purchase", f"Purchase {row['invoice_number']} cancelled: the reversing entry was posted.")
        buttons = tk.Frame(window, bg=LIGHT); buttons.grid(row=3, column=0, columnspan=2, pady=(0, 12))
        tk.Button(buttons, text="Confirm Cancellation", command=confirm, bg=RED, fg="white", border=0, padx=18, pady=7, font=("Segoe UI", 9, "bold")).pack(side="left", padx=4)
        tk.Button(buttons, text="Keep the purchase", command=window.destroy, bg=NAVY, fg="white", border=0, padx=18, pady=7).pack(side="left", padx=4)

    def purchase_attachments(self):
        row = self.selected_purchase()
        if not row: return messagebox.showwarning("Purchases", "Select a purchase first")
        self.invoice_rows = {**getattr(self, "invoice_rows", {}), str(row["id"]): row}
        self.invoice_tree.selection_set(()) if hasattr(self, "invoice_tree") else None
        self.show_attachments_for(row["id"], row["invoice_number"])

    def show_attachments_for(self, invoice_id, number):
        try: items = self.client.attachments(invoice_id)
        except Exception as exc: return messagebox.showerror("Attachments", str(exc))
        from desktop_attachments import attachments_window  # 2.9.97: see the document inside the program
        attachments_window(self, number, items, lambda record: self.client.download_attachment(record["id"])["content"])

    def landed_cost_payload(self):
        f = self.purchase_form
        item = {k: v.get().strip() for k, v in f["lc"].items() if k in ("party_name", "customs_declaration_no")}
        item["currency"] = f["lc_currency"].get()
        item["usd_lbp_rate"] = f["lc_rate"].get().strip()
        item["payment_method"] = f["lc_payment_method"].get()
        item["cash_account"] = f["lc_cash_account"].get().split(" - ", 1)[0].strip()
        item["currency_amounts"] = {key: {"USD": f["lc_usd"][key].get().strip(), "LBP": f["lc_lbp"][key].get().strip()} for key in f["lc_usd"]}
        from landed_costs import normalize
        normalize(item, item["currency"])
        party = f.get("lc_party_map", {}).get(f["lc"]["party_name"].get().strip())
        if party: item["party_id"] = party["id"]; item["party_name"] = party["name"]
        item["cost_accounts"] = {key: var.get().split(" - ", 1)[0].strip() for key, var in f["lc_accounts"].items()}
        return item

    def preview_landed_cost(self):
        from decimal import Decimal
        from landed_costs import normalize, COMPONENTS
        f = self.purchase_form
        if "lc_preview" not in f: return
        try:
            normalized, _sources = normalize(self.landed_cost_payload(), f["lc_currency"].get())
            cost = sum((Decimal(normalized[key]) for key, _ in COMPONENTS if key != "import_vat"), Decimal("0"))
            vat = Decimal(normalized["import_vat"])
            text = f"Item cost: {cost:,.2f}   |   Import VAT: {vat:,.2f}   |   Total payable: {cost + vat:,.2f} {normalized['currency']}"
        except ValueError as exc:
            text = str(exc)
        f["lc_preview"].config(text=text)

    def landed_cost_report(self, format_name):
        from landed_costs import COMPONENTS
        row = self.selected_purchase()
        if not row: return messagebox.showwarning("Cost on Purchase", "Select the purchase invoice first")
        try: costs = self.client.landed_costs(row["id"])
        except Exception as exc: return messagebox.showerror("Cost on Purchase", str(exc))
        labels = dict(COMPONENTS)
        from decimal import Decimal
        summary = [[c["invoice_number"], _dd(c["invoice_date"]), c["currency"], c["subtotal"], c["vat"], c["total"]] for c in costs]
        def factor(value):
            rate = Decimal(value)
            return "1 / " + format(1 / rate, ".8g") if rate < 1 else format(rate, ".8g")
        detail = [[c["invoice_number"], labels.get(s["component"], s["component"]), s["currency"], Decimal(s["amount"]),
                   factor(s["conversion_rate"]), c["currency"], Decimal(s["converted_amount"])]
                  for c in costs for s in c.get("source_amounts", [])]
        sections = [{"heading": "Posted purchase costs", "headers": ["Document", "Date", "Currency", "Item cost", "Import VAT", "Payable"], "rows": summary},
                    {"heading": "Original amounts and conversion (before component rounding)", "headers": ["Document", "Component", "Source currency", "Original amount",
                        "Conversion factor (display rounded)", "Posting currency", "Converted amount"], "rows": detail}]
        meta = [f"Purchase: {row['invoice_number']}", "Import VAT is excluded from item cost. Amounts in different currencies are not added together."]
        if any(not c.get("source_amounts") for c in costs): meta.append("Original currency breakdown was not recorded for older costs.")
        self.output_sections("Cost on Purchase", meta, sections, "Purchase_Cost_Breakdown", format_name)

    def edit_landed_cost_accounts(self):
        import chart_extra
        window = tk.Toplevel(self); window.title("Cost on Purchase Accounts"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        tk.Label(window, text="Default accounts are filled in. Edit an account when this purchase needs a different posting.", bg=LIGHT, fg=NAVY).pack(anchor="w", padx=12, pady=10)
        for key, var in self.purchase_form["lc_accounts"].items():
            row = tk.Frame(window, bg=LIGHT); row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=key.replace("_", " ").title(), width=18, anchor="w", bg=LIGHT).pack(side="left")
            self.account_search_box(row, var, 24).pack(side="left")
        self.action_button(window, "Restore defaults", lambda: [var.set(chart_extra.LANDED_COST_ACCOUNTS[key]) for key,
                var in self.purchase_form["lc_accounts"].items()]).pack(side="left", padx=12, pady=12)
        self.action_button(window, "Done", window.destroy).pack(side="right", padx=12, pady=12)

    def save_landed_cost(self):
        row = self.selected_purchase()
        if not row: return messagebox.showwarning("Cost on Purchase", "Select the purchase invoice in the list first")
        try:
            item = self.landed_cost_payload()
            if not item["party_name"]: raise ValueError("Enter the customs broker / payee name")
            self.client.add_landed_cost(row["id"], item)
        except Exception as exc: return messagebox.showerror("Cost on Purchase", str(exc))
        for var in [*self.purchase_form["lc"].values(), *self.purchase_form["lc_usd"].values(), *self.purchase_form["lc_lbp"].values()]: var.set("")
        self.purchase_form["lc"]["party_name"].set("")
        self.purchase_form["lc_payment_method"].set("On Account (Not Cash)"); self.purchase_form["lc_cash_account"].set("")
        messagebox.showinfo("Cost on Purchase", f"Cost on purchase added to {row['invoice_number']}. Import VAT goes to the VAT return as customs VAT.")
        self.load_purchases(); self.purchase_form["tree"].selection_set(str(row["id"])); self.load_invoices(); self.load_journal(); self.load_trial()

    def import_customs_excel(self):
        path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xlsm")])
        if not path: return
        try: costs = read_customs_costs(path)
        except Exception as exc: return messagebox.showerror("Cost on Purchase", f"The Excel file could not be read: {exc}")
        for key, value in costs.items():
            if value in (None, "", 0): continue
            target = self.purchase_form["lc_usd"] if self.purchase_form["lc_currency"].get() == "USD" else self.purchase_form["lc_lbp"]
            if key in target: target[key].set(str(value))
            elif key in self.purchase_form["lc"]: self.purchase_form["lc"][key].set(str(value))
        messagebox.showinfo("Cost on Purchase", "Amounts filled from the Excel file. Check them, select the purchase, then press 'Add Cost on Purchase'.")

    def attach_customs_pdf(self):
        row = self.selected_purchase()
        if not row: return messagebox.showwarning("Cost on Purchase", "Select the purchase invoice first")
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf"), ("Images", "*.png *.jpg *.jpeg")])
        if not path: return
        try:
            costs = self.client.landed_costs(row["id"]); target = costs[-1]["id"] if costs else row["id"]
            self.client.upload_attachment(target, Path(path).name, mimetypes.guess_type(path)[0] or "application/pdf", Path(path).read_bytes())
        except Exception as exc: return messagebox.showerror("Cost on Purchase", str(exc))
        messagebox.showinfo("Cost on Purchase", f"Customs document attached to {'the cost on purchase' if costs else row['invoice_number']}"); self.load_purchases()
