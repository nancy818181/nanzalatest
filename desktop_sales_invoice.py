"""Sales invoice screen (split from desktop_invoices.py in 2.9.94, no change in behaviour)."""
from __future__ import annotations
from pathlib import Path

from desktop_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, export_excel, export_pdf, filedialog, flow_toolbar, formatted_user_date, GOLD, LIGHT, messagebox, NAVY,
    parse_user_date, print_rows, safe_display_date, SALE_TREATMENTS, sortable_date, TAXABLE_LABEL, tk, ttk
)
from desktop_common import vat_rate, vat_rate_text, vat_currency  # 2.9.72
from desktop_common import main_currency  # 2.9.71


class SalesInvoiceMixin:
    def build_sales_invoice(self):
        self.sales_items=[]; self.sales_edit_id=None
        header=tk.LabelFrame(self.sales_tab,text="Sales Invoice",bg=LIGHT,padx=6,pady=2)
        header.pack(fill="x",padx=10,pady=(2,1))
        self.sales_no=tk.StringVar(); self.sales_date=tk.StringVar(value=self.fiscal_today())
        self.sales_party=tk.StringVar(); self.sales_kind=tk.StringVar(value="sales"); self.sales_currency=tk.StringVar(value="USD")
        self.sales_supplier_account=tk.StringVar(value="")
        self.sales_vat_account=tk.StringVar(value="4427")
        self.sales_expense_account=tk.StringVar(value="713000001")
        self.sales_expense_no_vat_account=tk.StringVar(value="601100001")
        self.sales_supplier_side=tk.StringVar(value="D - Debit"); self.sales_vat_side=tk.StringVar(value="C - Credit"); self.sales_expense_side=tk.StringVar(value="C - Credit"); self.sales_expense_no_vat_side=tk.StringVar(value="C - Credit")
        self.sales_due_date=tk.StringVar(); self.sales_payment_method=tk.StringVar(value="On Account (Not Cash)"); self.sales_amount_paid=tk.StringVar(value="0"); self.sales_branch=tk.StringVar(value="Head Office")
        self.sales_open_choice=tk.StringVar(); self.sales_doc_type=tk.StringVar(value="Invoice"); self.sales_category=tk.StringVar(value="Services")
        # 2.9.95: "Find invoice" is a slim row above the form (beside it, it made the screen wider than a laptop)
        nav=tk.Frame(header,bg=LIGHT); nav.pack(fill="x",pady=(0,4))
        tk.Label(nav,text="Find invoice",bg=LIGHT,fg=NAVY,font=("Segoe UI",9,"bold")).pack(side="left",padx=(0,6))
        tabs_row=tk.Frame(header,bg=LIGHT); tabs_row.pack(fill="x")
        self.sales_open_box=ttk.Combobox(nav,textvariable=self.sales_open_choice,width=34); self.sales_open_box.pack(side="left",padx=(0,4))
        self.sales_open_box.bind("<<ComboboxSelected>>",lambda _event:self.open_sales_invoice()); self.sales_open_box.bind("<KeyRelease>",self.search_open_sales)
        self.sales_open_box.bind("<Return>",lambda _event:self.open_sales_by_number())
        self.sales_previous=tk.Button(nav,text="◀ Previous",command=lambda:self.navigate_sales_invoice(-1),bg=NAVY,fg="white",border=0,padx=7,pady=3)
        self.sales_previous.pack(side="left",padx=2)
        self.sales_next=tk.Button(nav,text="Next ▶",command=lambda:self.navigate_sales_invoice(1),bg=NAVY,fg="white",border=0,padx=7,pady=3)
        self.sales_next.pack(side="left",padx=2)
        details=ttk.Notebook(tabs_row); details.pack(side="left",fill="x",expand=True)
        invoice_details=tk.Frame(details,bg=LIGHT); account_details=tk.Frame(details,bg=LIGHT)
        details.add(invoice_details,text="Invoice details"); details.add(account_details,text="Posting accounts")
        top=tk.Frame(invoice_details,bg=LIGHT); top.pack(anchor="w",fill="x",pady=(1,0))
        doc_box=ttk.Combobox(top,textvariable=self.sales_doc_type,values=["Invoice","Return","Credit Note","Debit Note"],state="readonly",width=11)
        doc_box.pack(side="left",padx=(0,8)); doc_box.bind("<<ComboboxSelected>>",lambda _event:self.sales_doc_type_changed())
        tk.Label(top,text="Invoice No.",bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left",padx=(0,4))
        tk.Entry(top,textvariable=self.sales_no,width=18,font=("Segoe UI",10,"bold"),state="readonly",readonlybackground="white").pack(side="left",padx=(0,12))
        tk.Label(top,text="Customer",bg=LIGHT).pack(side="left")
        self.sales_party_box=ttk.Combobox(top,textvariable=self.sales_party,width=23); self.sales_party_box.pack(side="left",padx=(4,10))
        self.sales_party_box.bind("<KeyRelease>",self.search_sales_customers); self.sales_party_box.bind("<<ComboboxSelected>>",lambda _event:self.sales_customer_chosen())
        self.sales_party_box.bind("<Return>",lambda _event:self.select_searched_sales_customer())
        tk.Label(top,text="Client Account",bg=LIGHT).pack(side="left",padx=(0,4))
        tk.Entry(top,textvariable=self.sales_supplier_account,width=12).pack(side="left",padx=(0,10))
        tk.Label(top,text="Currency",bg=LIGHT).pack(side="left")
        ttk.Combobox(top,textvariable=self.sales_currency,values=self.currency_codes,state="readonly",width=6).pack(side="left",padx=(4,8))
        account_fields=[("Client Account",self.sales_supplier_account,self.sales_supplier_side),("VAT Account",self.sales_vat_account,self.sales_vat_side),
                ("Revenue Account",self.sales_expense_account,self.sales_expense_side)]
        accounts_grid=tk.Frame(account_details,bg=LIGHT); accounts_grid.pack(anchor="w",fill="x",pady=1)
        for col,(label,var,side) in enumerate(account_fields):
            cell=tk.Frame(accounts_grid,bg=LIGHT,bd=1,relief="groove"); cell.grid(row=0,column=col,padx=4,pady=2,sticky="nw")
            caption=tk.Label(cell,text=label,bg=LIGHT,anchor="w",font=("Segoe UI",9,"bold")); caption.pack(anchor="w",padx=(6,4),pady=(2,0))
            if label=="Revenue Account": self.sales_revenue_caption=caption
            self.account_search_box(cell,var,26).pack(anchor="w",padx=6,pady=1)
            side_box=ttk.Combobox(cell,textvariable=side,values=["D - Debit","C - Credit"],state="readonly",width=11); side_box.pack(anchor="w",padx=6,pady=(0,3))
            side_box.bind("<<ComboboxSelected>>",lambda _event:self.update_sales_totals())
        payment=tk.Frame(invoice_details,bg=LIGHT); payment.pack(anchor="w",fill="x",pady=(1,0))
        tk.Label(payment,text="Date",bg=LIGHT).pack(side="left"); self.date_entry(payment,self.sales_date,12).pack(side="left",padx=(4,10))
        tk.Label(payment,text="Sales Type",bg=LIGHT).pack(side="left")
        self.sales_category_box=ttk.Combobox(payment,textvariable=self.sales_category,values=["Goods","Products","Services"],state="readonly",width=9)
        self.sales_category_box.pack(side="left",padx=(4,10)); self.sales_category_box.bind("<<ComboboxSelected>>",lambda _event:self.sales_category_changed())
        self.sales_category_box.bind("<space>",lambda _event:self.cycle_sales_type())
        self.sales_category_box.bind("<Key-space>",lambda _event:self.cycle_sales_type())
        tk.Label(payment,text="Payment Mode",bg=LIGHT).pack(side="left")
        ttk.Combobox(payment,textvariable=self.sales_payment_method,values=["On Account (Not Cash)","Cash","Bank Transfer","Cheque","Card","Other"],
                state="readonly",width=16).pack(side="left",padx=(4,10))
        tk.Label(payment,text="Due Date",bg=LIGHT).pack(side="left"); self.date_entry(payment,self.sales_due_date,12).pack(side="left",padx=(4,10))
        dims=tk.Frame(invoice_details,bg=LIGHT); dims.pack(anchor="w",fill="x",pady=(1,0))
        self.sales_department=tk.StringVar(); self.sales_project=tk.StringVar(); self.dimension_selectors(dims,self.sales_department,self.sales_project)
        vat_row=tk.Frame(invoice_details,bg=LIGHT); vat_row.pack(anchor="w",fill="x",pady=(1,0))
        tk.Label(vat_row,text="Branch",bg=LIGHT).pack(side="left"); self.branch_selector(vat_row,self.sales_branch,14,False).pack(side="left",padx=(4,10))
        tk.Label(vat_row,text="Amount Paid",bg=LIGHT).pack(side="left"); tk.Entry(vat_row,textvariable=self.sales_amount_paid,width=10).pack(side="left",padx=(4,10))
        self.sales_cash_account=tk.StringVar()
        tk.Label(vat_row,text="Paid into",bg=LIGHT).pack(side="left"); self.account_search_box(vat_row,self.sales_cash_account,12).pack(side="left",padx=(4,10))
        self.sales_treatment=tk.StringVar(value=TAXABLE_LABEL)
        tk.Label(vat_row,text="VAT Treatment",bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left",padx=(6,4))
        treatment_box=ttk.Combobox(vat_row,textvariable=self.sales_treatment,values=list(SALE_TREATMENTS),state="readonly",width=19); treatment_box.pack(side="left")
        treatment_box.bind("<<ComboboxSelected>>",lambda _event:self.sales_treatment_changed())
        self.sales_mode_label=tk.Label(vat_row,text="NEW INVOICE",bg=GOLD,fg=NAVY,font=("Segoe UI",8,"bold"),padx=8)
        self.sales_mode_label.pack(side="left",padx=(12,0))
        self.sales_payment_method.trace_add("write",lambda *_args:self.sales_payment_changed())
        self.sales_supplier_account.trace_add("write",lambda *_args:self.sales_account_chosen())
        self.sales_currency.trace_add("write",lambda *_args:self.update_sales_totals())
        self.sales_date.trace_add("write",lambda *_args:self.sales_date_changed())

        self.sales_discount_percent=tk.StringVar(value="0"); self.sales_discount_amount=tk.StringVar(value="0")
        toolbar=tk.Frame(self.sales_tab,bg=LIGHT); toolbar.pack(fill="x",padx=10,pady=(2,0))
        self.action_button(toolbar,"New",self.new_sales_invoice).pack(side="left",padx=2)
        self.action_button(toolbar,"Add Line",self.add_sales_item).pack(side="left",padx=2)
        tk.Button(toolbar,text="Delete Line",command=self.remove_sales_item,bg="#8B1E1E",fg="white",border=0,padx=10,pady=4).pack(side="left",padx=2)
        tk.Button(toolbar,text="Save",command=lambda:self.save_sales_invoice(True),bg=GOLD,fg=NAVY,font=("Segoe UI",10,"bold"),border=0,padx=14,pady=4).pack(side="left",padx=(8,2))
        tk.Button(toolbar,text="Delete",command=self.delete_sales_invoice,bg="#8B1E1E",fg="white",border=0,padx=12,pady=4).pack(side="left",padx=2)
        tk.Button(toolbar,text="Return (goods back)",command=self.return_open_sales_invoice,bg=NAVY,fg="white",font=("Segoe UI",9,"bold"),border=0,padx=10,pady=4).pack(side="left",padx=2)
        self.action_button(toolbar,"Duplicate",self.duplicate_sales_invoice).pack(side="left",padx=(8,2))
        for text,command in (("Print Preview",lambda:self.sales_invoice_pdf("preview")),("PDF",lambda:self.sales_invoice_pdf("pdf")),("Print",lambda:self.sales_invoice_pdf("print")),
                             ("Excel",lambda:self.sales_entry_report("xlsx"))):
            tk.Button(toolbar,text=text,command=command,bg=NAVY,fg="white",border=0,padx=10,pady=4).pack(side="left",padx=2)
        for text,command in (("Import Excel",self.import_sales_excel),("Import PDF",self.import_sales_pdf)):
            tk.Button(toolbar,text=text,command=command,bg=NAVY,fg="white",border=0,padx=10,pady=4).pack(side="left",padx=(8 if text=="Import Excel" else 2,2))
        self.action_button(toolbar,"Free PDF Read",self.ai_read_sales_pdf).pack(side="left",padx=2)
        flow_toolbar(toolbar)  # 2.9.95: wraps onto a second line on a narrow screen instead of being cut off
        # Totals bar is pinned to the very bottom of the tab FIRST, so it can never be pushed off-screen by the table
        bottom=tk.Frame(self.sales_tab,bg=LIGHT); bottom.pack(side="bottom",fill="x",padx=10,pady=(0,4))
        body=tk.Frame(self.sales_tab,bg=LIGHT); body.pack(side="top",fill="both",expand=True,padx=10,pady=(2,4))
        # Item table on top, enlarged
        items_area=tk.Frame(body,bg=LIGHT); items_area.pack(side="top",fill="both",expand=True)
        sheet_frame=tk.Frame(items_area,bg=LIGHT); sheet_frame.pack(fill="both",expand=True)
        self.sales_columns=[("item_code","Item",90),("description","Description",250),("quantity","Qty",55),("unit","Unit",60),("unit_price","Unit Price",95),
            ("gross_amount","Total Amount",105),("discount_percent","Discount %",80),("vat_rate","VAT %",60),("total","Net",105)]
        self.sales_sheet=ttk.Treeview(sheet_frame,columns=[c[0] for c in self.sales_columns],show="headings",height=9,style="Sales.Treeview")
        for key,label,width in self.sales_columns: self.sales_sheet.heading(key,text=label); self.sales_sheet.column(key,width=width,anchor="w" if key=="description" else "e")
        scroll=ttk.Scrollbar(sheet_frame,orient="vertical",command=self.sales_sheet.yview)
        xscroll=ttk.Scrollbar(sheet_frame,orient="horizontal",command=self.sales_sheet.xview)
        self.sales_sheet.configure(yscrollcommand=scroll.set,xscrollcommand=xscroll.set)
        self.sales_sheet.grid(row=0,column=0,sticky="nsew"); scroll.grid(row=0,column=1,sticky="ns")
        xscroll.grid(row=1,column=0,sticky="ew")
        sheet_frame.grid_rowconfigure(0,weight=1); sheet_frame.grid_columnconfigure(0,weight=1)
        self.sales_sheet.bind("<Double-1>",self.edit_sales_cell); self.sales_sheet.bind("<Return>",self.edit_sales_cell)
        self.sales_sheet.bind("<Delete>",lambda _event:self.remove_sales_item())
        totals=tk.Frame(bottom,bg=LIGHT); totals.pack(side="right",fill="y",padx=(8,0))
        box=tk.Frame(totals,bg="#dfe6ee",padx=6,pady=3); box.pack(side="top",fill="x")
        self.sales_total_labels={}
        for key,caption,row,column in (("Total","Total",0,0),("Discount","Discount",0,1),("Total HT","Total HT",0,2),
                                       ("VAT",f"VAT {vat_rate_text(self)}",1,0),("TOTAL","TOTAL TTC",1,1)):
            label=tk.Label(box,text=caption,bg="#dfe6ee",font=("Segoe UI",9,"bold" if key=="TOTAL" else "normal"))
            label.grid(row=row,column=column*2,sticky="e",padx=(6,2),pady=1)
            if key=="VAT": self.sales_vat_caption=label
            value=tk.Label(box,text="0.00",bg="#dfe6ee",width=10,anchor="e",font=("Segoe UI",12 if key=="TOTAL" else 10,"bold"))
            value.grid(row=row,column=column*2+1,sticky="e",padx=(0,4)); self.sales_total_labels[key]=value
        discount=tk.Frame(box,bg="#dfe6ee"); discount.grid(row=1,column=4,columnspan=2,sticky="e",pady=1)
        tk.Label(discount,text="Discount %",bg="#dfe6ee").pack(side="left"); e1=tk.Entry(discount,textvariable=self.sales_discount_percent,width=5); e1.pack(side="left",padx=2)
        tk.Label(discount,text="or amount",bg="#dfe6ee").pack(side="left"); e2=tk.Entry(discount,textvariable=self.sales_discount_amount,width=9); e2.pack(side="left",padx=2)
        for entry in (e1,e2): entry.bind("<KeyRelease>",lambda _event:self.update_sales_totals())
        self.sales_totals=tk.Label(totals,text="",bg=LIGHT,fg=NAVY); self.sales_totals.pack(side="top",anchor="e",padx=8,pady=3)
        self.sales_words=tk.Label(bottom,text="",bg=LIGHT,fg="#5f6b76",anchor="w",justify="left",wraplength=380,font=("Segoe UI",8))
        self.sales_words.pack(side="left",fill="x",expand=True,padx=4,pady=(3,0))
        self.new_sales_invoice(confirm=False)

    # ---- sales invoice helpers
    def sales_treatment_changed(self):
        """Zero-rated and exempt sales carry no VAT: set every line to 0% (Taxable puts them back to the company's rate)."""
        rate=vat_rate(self) if self.sales_treatment.get()==TAXABLE_LABEL else 0
        for item in self.sales_items:
            item["vat_rate"]=rate; item["_vat_typed"]=False; self.recalculate_sales_item(item)
            if self.sales_sheet.exists(item.get("_iid","")): self.sales_sheet.item(item["_iid"],values=self.sales_row_values(item))
        self.update_sales_totals()

    def sales_payment_changed(self):
        if self.sales_payment_method.get().startswith("On Account"): self.sales_amount_paid.set("0")

    def sales_date_changed(self):
        self.update_sales_totals()
        if not self.sales_edit_id and len(self.sales_date.get())==10: self.refresh_sales_number()

    def refresh_sales_number(self):
        kind={"Credit Note":"credit_note","Return":"credit_note","Debit Note":"debit_note"}.get(self.sales_doc_type.get() if hasattr(self,"sales_doc_type") else "Invoice","sale")
        try: self.sales_no.set(self.client.next_invoice_number(kind,self.sales_date.get().strip() or None))
        except Exception: self.sales_no.set("")

    def load_sales_customer_list(self):
        try: parties=self.client.parties()
        except Exception: parties=[]
        self.sales_customers={f'{p["name"]}':p for p in parties if p["kind"] in ("customer","both")}
        self.sales_party_box["values"]=list(self.sales_customers)
        try: invoices=[r for r in self.client.invoices() if r["kind"]=="sale" and r.get("status")!="cancelled"]
        except Exception: invoices=[]
        invoices.sort(key=lambda r:(sortable_date(r["invoice_date"]),str(r["invoice_number"]),r["id"]))
        self.sales_open_map={}
        for row in invoices:
            number=str(row["invoice_number"])
            label=number; duplicate=2
            while label in self.sales_open_map:
                label=f"{number} ({duplicate})"; duplicate+=1
            self.sales_open_map[label]=row
        self.sales_open_all=invoices
        self.sales_open_box["values"]=list(self.sales_open_map)
        self.update_sales_navigation()

    def update_sales_navigation(self):
        keys=list(getattr(self,"sales_open_map",{}))
        current=next((i for i,key in enumerate(keys) if self.sales_edit_id and self.sales_open_map[key]["id"]==self.sales_edit_id),None)
        if hasattr(self,"sales_previous"):
            self.sales_previous.config(state="normal" if keys and (current is None or current>0) else "disabled")
            self.sales_next.config(state="normal" if keys and (current is None or current<len(keys)-1) else "disabled")

    def navigate_sales_invoice(self,step):
        keys=list(getattr(self,"sales_open_map",{}))
        current=next((i for i,key in enumerate(keys) if self.sales_edit_id and self.sales_open_map[key]["id"]==self.sales_edit_id),None)
        index=(len(keys)-1 if step<0 else 0) if current is None else current+step
        if not 0<=index<len(keys): return
        previous=self.sales_open_choice.get()
        self.sales_open_choice.set(keys[index])
        if not self.open_sales_invoice(): self.sales_open_choice.set(previous)

    def search_sales_customers(self,_event=None):
        typed=self.sales_party.get().strip().casefold(); names=list(getattr(self,"sales_customers",{}))
        found=[name for name in names if name.casefold().startswith(typed)]
        found += [name for name in names if typed in name.casefold() and name not in found]
        self.sales_party_box["values"]=found if typed else names
        if typed and found:
            if len(found)==1 and found[0].casefold()==typed:
                self.sales_party.set(found[0]); self.sales_customer_chosen()
            elif _event is not None and _event.keysym not in ("Up","Down","Return","Escape"):
                self.sales_party_box.after_idle(lambda:self.sales_party_box.event_generate("<Down>"))

    def select_searched_sales_customer(self):
        choices=list(self.sales_party_box["values"])
        if len(choices)==1:
            self.sales_party.set(choices[0]); self.sales_customer_chosen()

    def search_open_sales(self,_event=None):
        """Type only the number: 12 finds SAL-2026-000012 (and CN / DN numbers)."""
        typed=self.sales_open_choice.get().strip(); choices=list(getattr(self,"sales_open_map",{}))
        if typed.isdigit():
            wanted=int(typed); found=[c for c in choices if c.split(" (",1)[0].rsplit("-",1)[-1].isdigit() and int(c.split(" (",1)[0].rsplit("-",1)[-1])==wanted]
            self.sales_open_box["values"]=found or [c for c in choices if typed in c.split(" (",1)[0]]
        else: self.sales_open_box["values"]=[c for c in choices if typed.casefold() in c.casefold()] if typed else choices
        if typed and self.sales_open_box["values"] and _event is not None and _event.keysym not in ("Up","Down","Return","Escape","Tab"):
            self.sales_open_box.after_idle(lambda:self.sales_open_box.event_generate("<Down>"))

    def edit_sales_invoice(self):
        """Load the invoice picked in Find Invoice into the form for editing; then Save re-saves it."""
        if self.sales_open_choice.get().strip() and getattr(self,"sales_open_map",{}).get(self.sales_open_choice.get()):
            self.open_sales_invoice(); return
        choices=list(getattr(self,"sales_open_map",{}))
        if not choices:
            messagebox.showinfo("Sales Invoice","No saved invoices to edit yet."); return
        win=tk.Toplevel(self); win.title("Edit Invoice"); win.configure(bg=LIGHT); win.transient(self); win.grab_set()
        tk.Label(win,text="Pick the invoice you want to edit:",bg=LIGHT,font=("Segoe UI",10,"bold")).pack(padx=14,pady=(14,4))
        pick=tk.StringVar()
        box=ttk.Combobox(win,textvariable=pick,width=40,values=choices); box.pack(padx=14,pady=4)
        def do_edit():
            if pick.get() in getattr(self,"sales_open_map",{}):
                self.sales_open_choice.set(pick.get()); win.destroy(); self.open_sales_invoice()
        def filt(_e=None):
            t=pick.get().strip().casefold(); box["values"]=[c for c in choices if t in c.casefold()] if t else choices
            if t and box["values"] and _e is not None and _e.keysym not in ("Up","Down","Return","Escape","Tab"):
                box.after_idle(lambda:box.event_generate("<Down>"))
        box.bind("<KeyRelease>",filt); box.bind("<Return>",lambda _e:do_edit())
        tk.Button(win,text="Open for Editing",command=do_edit,bg=GOLD,fg=NAVY,font=("Segoe UI",10,"bold"),border=0,padx=14,pady=5).pack(pady=(8,14))
        box.focus_set()

    def sales_customer_chosen(self):
        party=getattr(self,"sales_customers",{}).get(self.sales_party.get())
        if party:
            self.sales_supplier_account.set(party.get("account_number") or "")
            if party.get("currency"): self.sales_currency.set(party["currency"])

    def sales_category_changed(self):
        self.sales_vat_account.set("4427")
        self.sales_expense_account.set(self.default_sales_posting_account())

    def default_sales_posting_account(self):
        category=self.sales_category.get()
        if self.sales_doc_type.get() in ("Credit Note","Return"): return "709000001" if category=="Goods" else "719000001"
        return {"Goods":"701100001","Products":"711100001","Services":"713000001"}.get(category,"713000001")

    def cycle_sales_type(self):
        """Space bar toggles Sales Type (Goods -> Products -> Services -> ...) and
        re-applies the matching posting accounts and data entry."""
        options=list(self.sales_category_box["values"]) or ["Goods","Products","Services"]
        try: index=options.index(self.sales_category.get())
        except ValueError: index=-1
        self.sales_category.set(options[(index+1)%len(options)])
        self.sales_category_changed()
        return "break"

    def sales_vat_in_lbp(self,vat_amount,currency=None):
        """Return (VAT expressed in LBP, LBP rate for one currency unit) for the
        invoice date. LBP invoices return the amount as-is; when no rate exists
        it returns (None, None)."""
        currency=currency or self.sales_currency.get()
        try: vat=float(vat_amount or 0)
        except (TypeError,ValueError): vat=0.0
        if currency=="LBP": return vat,None
        try:
            rates=self.sales_rates_for_date(self.client.exchange_rates(),self.sales_date.get())
            vat_lbp,_=self.exchange_equivalents(vat,currency,rates)
            unit_lbp,_=self.exchange_equivalents(1.0,currency,rates)
            return vat_lbp,unit_lbp
        except Exception:
            return None,None

    def sales_account_chosen(self):
        code=self.sales_supplier_account.get().split(" - ",1)[0].strip()
        if not code: return
        party=next((party for party in getattr(self,"sales_customers",{}).values()
                    if str(party.get("account_number") or "").strip()==code),None)
        if party:
            self.sales_party.set(party["name"])
            if party.get("currency"): self.sales_currency.set(party["currency"])

    def new_sales_invoice(self,confirm=True):
        if confirm and self.sales_items and not messagebox.askyesno("Sales Invoice","Start a new invoice? Lines that are not saved will be cleared."): return
        self.sales_edit_id=None; self.sales_items=[]; self.sales_pdf_path=None; self.sales_sheet.delete(*self.sales_sheet.get_children())
        self._sales_loaded_state=None
        self.sales_party.set(""); self.sales_supplier_account.set(""); self.sales_amount_paid.set("0"); getattr(self,"sales_cash_account",
                tk.StringVar()).set(""); self.sales_due_date.set(""); self.sales_open_choice.set("")
        self.sales_doc_type.set("Invoice"); self.sales_category.set("Services"); self.sales_currency.set(main_currency(self, 1))  # 2.9.71
        self.sales_category_box["values"]=["Goods","Products","Services"]
        self.sales_revenue_caption.config(text="Revenue Account")
        self.sales_supplier_side.set("D - Debit"); self.sales_vat_side.set("C - Credit"); self.sales_expense_side.set("C - Credit")
        self.sales_payment_method.set("On Account (Not Cash)"); self.sales_date.set(self.fiscal_today())
        self.sales_department.set("(none)"); self.sales_project.set("(none)"); self.sales_treatment.set(TAXABLE_LABEL)
        self.sales_discount_percent.set("0"); self.sales_discount_amount.set("0")
        self.sales_category_changed()
        self.sales_mode_label.config(text="NEW INVOICE",bg=GOLD); self.load_sales_customer_list(); self.refresh_sales_number()
        self.update_sales_navigation()
        self.add_sales_item(); self.update_sales_totals()

    def sales_row_values(self,item):
        return (item.get("item_code") or "",item.get("description",""),f'{float(item.get("quantity") or 0):g}',item.get("unit") or "",f'{float(item.get("unit_price") or 0):,.2f}',
                f'{float(item.get("gross_amount") or 0):,.2f}',f'{float(item.get("discount_percent") or 0):g}%' if float(item.get("discount_percent") or 0) else "",
                f'{float(item.get("vat_rate") or 0):g}',f'{float(item.get("net") or 0):,.2f}')

    def recalculate_sales_item(self,item):
        """Line: Amount = Qty x Price, less the line discount %. VAT and the invoice discount are shared in update_sales_totals."""
        item["quantity"]=float(item.get("quantity") or 0); item["unit_price"]=float(item.get("unit_price") or 0)
        item["discount_percent"]=float(item.get("discount_percent") or 0); item["vat_rate"]=float(item.get("vat_rate") if item.get("vat_rate") not in (None,"") else vat_rate(self))
        item["gross_amount"]=round(item["quantity"]*item["unit_price"],2); item["net"]=round(item["gross_amount"]*(1-item["discount_percent"]/100),2)
        item.setdefault("unit",""); item.setdefault("subtotal",item["net"]); item.setdefault("vat",0.0); item.setdefault("total",item["net"])
        return item

    def add_sales_item(self,item=None):
        item=self.recalculate_sales_item(dict(item or {"description":"","quantity":1,"unit":"","unit_price":0,"discount_percent":0,"vat_rate":0 if getattr(self,
                "sales_treatment",None) is not None and self.sales_treatment.get()!=TAXABLE_LABEL else vat_rate(self)}))
        self.sales_items.append(item); iid=self.sales_sheet.insert("","end",values=self.sales_row_values(item))
        item["_iid"]=iid; self.update_sales_totals()
        if not item["description"]:
            self.sales_sheet.selection_set(iid); self.sales_sheet.focus(iid)
            sheet = self.sales_sheet
            def edit_new_line():
                # A callback from a closed company/page must not rebuild its controls
                # or steal focus. Optional inventory data must not load every tab.
                if self.__dict__.get("sales_sheet") is sheet and sheet.winfo_exists() and sheet.winfo_ismapped():
                    self.edit_sales_cell(column_index=1 if not self.__dict__.get("inventory_rows") else 0,iid=iid)
            self.after(50,edit_new_line)
        return iid

    def sales_item_for(self,iid):
        return next((item for item in self.sales_items if item.get("_iid")==iid),None)

    def edit_sales_cell(self,event=None,column_index=None,iid=None):
        """Put an entry box over one cell of the sheet, like a spreadsheet."""
        tree=self.sales_sheet
        if event is not None and column_index is None:
            if getattr(event,"keysym","")=="Return": iid=tree.focus(); column_index=0
            else:
                iid=tree.identify_row(event.y); column=tree.identify_column(event.x) or "#1"
                column_index=max(0,int(column.lstrip("#") or 1)-1)
        iid=iid or tree.focus()
        if not iid or not tree.exists(iid) or not tree.winfo_ismapped(): return
        editable=[key for key,_label,_width in self.sales_columns if key not in ("total","gross_amount")]
        key=self.sales_columns[column_index][0]
        if key in ("total","gross_amount"): key="description"; column_index=1
        bbox=tree.bbox(iid,f"#{column_index+1}")
        if not bbox: return
        item=self.sales_item_for(iid)
        if item is None: return
        value=item.get(key,"")
        editor=tk.Entry(tree,justify="left" if key in ("description","item_code","unit") else "right"); editor.insert(0,str(value if key in ("description",
                "item_code","unit") else f"{float(value or 0):g}"))
        editor.place(x=bbox[0],y=bbox[1],width=bbox[2],height=bbox[3]); editor.focus_set(); editor.select_range(0,"end")
        def commit(move=0):
            text=editor.get().strip(); editor.destroy()
            if key=="description": item["description"]=text
            elif key=="unit": item["unit"]=text
            elif key=="item_code":
                product=self.item_by_code(text) if text else None
                if text and not product: return messagebox.showwarning("Sales Invoice",f"Item {text} was not found (Inventory > Items)")
                item["item_code"]=product["sku"] if product else ""
                if product:
                    item["description"]=product["name"]; item["unit"]=product.get("unit") or ""
                    if product["sales_price"]: item["unit_price"]=product["sales_price"]
                    if product.get("default_vat") not in (None,""):
                        item["vat_rate"]=0.0 if str(product["default_vat"]).replace("%","").strip() in ("0","0.0") else vat_rate(self); item["_vat_typed"]=False  # 2.9.72
            else:
                try: number=float(text.replace(",","") or 0)
                except ValueError: return messagebox.showwarning("Sales Invoice",f"{self.sales_columns[column_index][1]} must be a number")
                if number<0: return messagebox.showwarning("Sales Invoice","Amounts cannot be negative")
                item[key]=number
                if key=="deductible_subtotal": item["_taxable_typed"]=True
                if key in ("quantity","unit_price"): item["_taxable_typed"]=False
                if key=="vat": item["_vat_typed"]=True
                if key in ("quantity","unit_price","deductible_subtotal","vat_rate"): item["_vat_typed"]=False
            self.recalculate_sales_item(item); tree.item(iid,values=self.sales_row_values(item)); self.update_sales_totals()
            if move:
                position=editable.index(key) if key in editable else 0
                if position+1<len(editable): self.after(10,lambda:self.edit_sales_cell(column_index=[c[0] for c in self.sales_columns].index(editable[position+1]),iid=iid))
                else:
                    rows=tree.get_children(); index=rows.index(iid)
                    if index+1<len(rows): self.after(10,lambda:self.edit_sales_cell(column_index=0,iid=rows[index+1]))
                    elif item["description"]: self.add_sales_item()
        editor.bind("<Return>",lambda _event:commit(1)); editor.bind("<Tab>",lambda _event:(commit(1),"break")[1])
        editor.bind("<FocusOut>",lambda _event:commit(0) if editor.winfo_exists() else None); editor.bind("<Escape>",lambda _event:editor.destroy())

    def remove_sales_item(self):
        selected=self.sales_sheet.selection()
        if not selected: return messagebox.showwarning("Sales Invoice","Select a line first")
        for iid in selected:
            item=self.sales_item_for(iid)
            if item: self.sales_items.remove(item)
            self.sales_sheet.delete(iid)
        self.update_sales_totals()

    def sales_debit_credit_totals(self):
        total=sum(float(item.get("total",0)) for item in self.sales_items if item.get("description"))
        return total,total

    def calculate_sales_line(self): return None

    def update_sales_totals(self):
        import invoice_calc
        from tafqeet import amount_in_words
        lines=[i for i in self.sales_items if str(i.get("description") or "").strip() or float(i.get("unit_price") or 0)]
        export=getattr(self,"sales_treatment",None) is not None and self.sales_treatment.get()!=TAXABLE_LABEL
        try: result=invoice_calc.calculate(lines,self.sales_discount_percent.get() if hasattr(self,"sales_discount_percent") else 0,
                                           self.sales_discount_amount.get() if hasattr(self,"sales_discount_amount") else 0,export)
        except ValueError as exc:
            if hasattr(self,"sales_total_labels"): self.sales_total_labels["TOTAL"].config(text=str(exc),fg="#8B1E1E")
            return
        for item,calculated in zip(lines,result["lines"]):
            for key in ("deductible_subtotal","non_deductible_subtotal","vat","subtotal","total","gross_amount","discount_amount","discount_percent","vat_rate"): item[key]=calculated[key]
            iid=item.get("_iid")
            if iid and self.sales_sheet.exists(iid): self.sales_sheet.item(iid,values=self.sales_row_values(item))
        self.sales_calculation=result; currency=self.sales_currency.get()
        if hasattr(self,"sales_total_labels"):
            values={"Total":result["total"],"Discount":-result["discount"] if result["discount"] else 0,
                    "Total HT":result["total_ht"],"VAT":result["vat"],"TOTAL":result["grand_total"]}
            for key,label in self.sales_total_labels.items():
                label.config(text=f"{values[key]:,.2f} {currency}" if key=="TOTAL" else f"{values[key]:,.2f}",fg=NAVY)
            self.sales_vat_caption.config(text=f"VAT {vat_rate_text(self)}" if not export else f"VAT {vat_rate_text(self)}  ({self.sales_treatment.get()})",
                    font=("Segoe UI",9,"overstrike") if export else ("Segoe UI",9))
            from report_export import shape_arabic
            key=(str(result["grand_total"]),currency); cache=self.__dict__.setdefault("_sales_words_cache",{})  # 2.9.91: drawn once per amount
            if key not in cache:
                words=amount_in_words(result["grand_total"],currency); cache[key]=f'{words["en"]}\n{shape_arabic(words["ar"])}'
                if len(cache)>500: cache.clear()
            if self.sales_words.cget("text")!=cache[key]: self.sales_words.config(text=cache[key])
        self.sales_totals.config(text=f'{len(lines)} line(s)')

    def sales_type_changed(self):
        self.calculate_sales_line(); self.update_sales_totals()

    def exchange_equivalents(self,amount,currency,rates):
        def convert(value,source,target):
            if source==target: return value
            for row in rates:
                rate=float(row["rate"])
                if row["from_currency"]==source and row["to_currency"]==target: return value*rate
                if row["from_currency"]==target and row["to_currency"]==source and rate: return value/rate
            return None
        if currency=="LBP": return amount,convert(amount,"LBP","USD")
        lbp=convert(amount,currency,"LBP"); usd=amount if currency=="USD" else convert(amount,currency,"USD")
        if usd is None and lbp is not None: usd=convert(lbp,"LBP","USD")
        if lbp is None and usd is not None: lbp=convert(usd,"USD","LBP")
        return lbp,usd

    @staticmethod
    def sales_rates_for_date(rates,invoice_date):
        """Use the most recent available rate on or before the invoice date per pair."""
        try: day=parse_user_date(invoice_date)
        except (ValueError,TypeError): return rates
        selected={}
        for row in rates:
            rate_day=sortable_date(row.get("rate_date"))
            if rate_day==datetime.min or rate_day>day: continue
            pair=(row["from_currency"],row["to_currency"])
            if pair not in selected or rate_day>selected[pair][0]: selected[pair]=(rate_day,row)
        return [entry[1] for entry in selected.values()]

    def exchange_equivalent_text(self, amount, currency, rates=None):
        if not amount:
            return "Exchange equivalent: 0.00"
        if rates is None:
            try: rates=self.client.exchange_rates()
            except Exception: rates=[]
        lbp,usd=self.exchange_equivalents(amount,currency,rates)
        if currency=="LBP":
            return f"Exchange equivalent: USD {usd:,.2f}" if usd is not None else "Exchange equivalent: USD rate not entered"
        lbp_text=f"LBP {lbp:,.2f}" if lbp is not None else "LBP rate not entered"
        usd_text=f"USD {usd:,.2f}" if usd is not None else "USD rate not entered"
        return f"Exchange equivalent: {lbp_text}   |   {usd_text}"

    def sales_entry_report(self, format_name):
        if not self.sales_items:
            return messagebox.showwarning("Manual Entry","Add at least one invoice item")
        invoice_no=self.sales_no.get().strip() or "Draft"
        party=self.sales_party.get().strip() or "Unspecified"
        currency=self.sales_currency.get()
        title=f"Invoice {invoice_no} - {party} - {currency}"
        headers=["Description","Quantity","Unit Price","Deductible","Non-Deductible","VAT %","VAT Amount","After VAT","Debit","Credit"]
        rows=[[item["description"],item["quantity"],item["unit_price"],item.get("deductible_subtotal",item["subtotal"]),item.get("non_deductible_subtotal",0),
                item["vat_rate"],item["vat"],item["total"],
               item["total"] if self.sales_kind.get()=="sales" else 0,item["total"] if self.sales_kind.get()!="sales" else 0] for item in self.sales_items]
        total_amount=sum(float(item["total"]) for item in self.sales_items)
        rows.append(["","",f"TOTAL {currency}",sum(float(item.get("deductible_subtotal",item["subtotal"])) for item in self.sales_items),
                sum(float(item.get("non_deductible_subtotal",0)) for item in self.sales_items),
                     "",sum(float(item["vat"]) for item in self.sales_items),total_amount,
                     total_amount if self.sales_kind.get()=="sales" else 0,total_amount if self.sales_kind.get()!="sales" else 0])
        try:
            if format_name=="print":
                print_rows(title,headers,rows); return
            extension=".xlsx" if format_name=="xlsx" else ".pdf"
            path=filedialog.asksaveasfilename(defaultextension=extension,
                filetypes=[("Excel workbook","*.xlsx")] if format_name=="xlsx" else [("PDF document","*.pdf")],
                initialfile=f"Invoice_{invoice_no}_{currency}{extension}")
            if not path: return
            (export_excel if format_name=="xlsx" else export_pdf)(path,title,headers,rows)
            messagebox.showinfo("Manual Entry",f"Saved successfully:\\n{path}")
        except Exception as exc:
            messagebox.showerror("Manual Entry",str(exc))

    def open_sales_invoice(self):
        row=getattr(self,"sales_open_map",{}).get(self.sales_open_choice.get())
        if not row: return False
        if self.sales_edit_id and getattr(self,"_sales_loaded_state",None)!=self.sales_form_state():
            prompt="Reload this invoice?" if self.sales_edit_id==row["id"] else "Open another invoice?"
            if not messagebox.askyesno("Sales Invoice",f"{prompt} Unsaved changes will be cleared."):
                self.sales_open_choice.set(next((key for key,item in self.sales_open_map.items() if item["id"]==self.sales_edit_id),""))
                return False
        if self.sales_items and any(i.get("description") for i in self.sales_items) and not self.sales_edit_id:
            if not messagebox.askyesno("Sales Invoice","Open this invoice? The lines you are typing now will be cleared."):
                self.sales_open_choice.set("")
                return False
        try: items=self.client.invoice_items(row["id"]); detail=next(r for r in self.client.invoices() if r["id"]==row["id"])
        except Exception as exc: messagebox.showerror("Sales Invoice",str(exc)); return False
        self.sales_edit_id=row["id"]; self.sales_items=[]; self.sales_sheet.delete(*self.sales_sheet.get_children())
        self.sales_no.set(detail["invoice_number"]); self.sales_date.set(safe_display_date(detail["invoice_date"])); self.sales_party.set(detail["party_name"] or "")
        self.sales_supplier_account.set(detail.get("supplier_account") or ""); self.sales_party.set(detail["party_name"] or "")
        self.sales_currency.set(detail["currency"]); self.sales_vat_account.set(detail.get("vat_account") or "4427")
        self.sales_expense_account.set(detail.get("expense_account") or "713100000"); self.sales_payment_method.set(detail.get("payment_method") or "On Account (Not Cash)")
        self.sales_branch.set(detail.get("branch_name") or "Head Office")
        sides=(detail.get("supplier_side") or "D",detail.get("vat_side") or "C",detail.get("expense_side") or "C")
        if sides==("C","D","D") and detail.get("doc_subtype")!="credit_note":
            sides=("D","C","C")  # older sales stored purchase-side defaults despite posting Dr client / Cr revenue and VAT
        self.sales_supplier_side.set("D - Debit" if sides[0].startswith("D") else "C - Credit")
        self.sales_vat_side.set("D - Debit" if sides[1].startswith("D") else "C - Credit")
        self.sales_expense_side.set("D - Debit" if sides[2].startswith("D") else "C - Credit")
        lists=self.dimension_lists(refresh=True)
        self.sales_department.set(next((f'{d["code"]} - {d["name"]}' for d in lists["departments"] if d["id"]==detail.get("department_id")),"(none)"))
        self.sales_project.set(next((f'{p["code"]} - {p["name"]}' for p in lists["projects"] if p["id"]==detail.get("project_id")),"(none)"))
        self.sales_treatment.set(next((k for k,v in SALE_TREATMENTS.items() if v==(detail.get("vat_treatment") or "standard")),TAXABLE_LABEL))
        self.sales_cash_account.set(detail.get("payment_account") or "")
        self.sales_amount_paid.set(str(detail.get("amount_paid") or 0)); self.sales_due_date.set(safe_display_date(detail.get("due_date")) if detail.get("due_date") else "")
        self.sales_doc_type.set("Return" if detail.get("doc_subtype")=="credit_note" and detail.get("is_return") else
                                {"credit_note":"Credit Note","debit_note":"Debit Note"}.get(detail.get("doc_subtype") or "invoice","Invoice"))
        self.sales_revenue_caption.config(text="Returns Account" if self.sales_doc_type.get()=="Return" else "Discount Account" if self.sales_doc_type.get()=="Credit Note" else "Revenue Account")
        revenue_code=str(detail.get("expense_account") or "")
        if self.sales_doc_type.get() in ("Credit Note","Return"):
            category="Goods" if revenue_code.startswith("709") else "Products / Services"
            self.sales_category_box["values"]=["Goods","Products / Services"]
        else:
            category="Goods" if revenue_code.startswith("701") else "Products" if revenue_code.startswith("711") else "Services"
            self.sales_category_box["values"]=["Goods","Products","Services"]
        self.sales_category.set(category)
        self.sales_discount_percent.set(f'{float(detail.get("invoice_discount_percent") or 0):g}'); self.sales_discount_amount.set(f'{float(detail.get("invoice_discount_amount") or 0):g}')
        for line in items or [{"description":"Invoice total","quantity":1,"unit_price":float(detail["subtotal"] or 0),"vat_rate":11}]:
            item={"item_code":line.get("item_code") or "","description":line["description"],"quantity":float(line["quantity"]),"unit":line.get("unit") or "",
                  "unit_price":float(line["unit_price"]),"discount_percent":float(line.get("discount_percent") or 0),"vat_rate":float(line["vat_rate"])}
            self.add_sales_item(item)
        status={"posted":"POSTED","review":"DRAFT"}.get(detail.get("status"),str(detail.get("status")).upper())
        self.sales_mode_label.config(text=f"EDITING {detail['invoice_number']} ({status})",bg="#dfe6ee")
        self._sales_loaded_state=self.sales_form_state()
        self.update_sales_navigation()
        return True

    def sales_form_state(self):
        fields=(self.sales_no,self.sales_date,self.sales_party,self.sales_currency,self.sales_supplier_account,self.sales_vat_account,
                self.sales_expense_account,self.sales_supplier_side,self.sales_vat_side,self.sales_expense_side,self.sales_payment_method,
                self.sales_due_date,self.sales_amount_paid,self.sales_branch,self.sales_department,self.sales_project,self.sales_treatment,
                self.sales_doc_type,self.sales_category,self.sales_discount_percent,self.sales_discount_amount)
        lines=tuple((item.get("item_code"),item.get("description"),item.get("quantity"),item.get("unit"),
                     item.get("unit_price"),item.get("discount_percent"),item.get("vat_rate")) for item in self.sales_items)
        return tuple(field.get() for field in fields),lines

    def save_sales_invoice(self,post=False):
        self.update_sales_totals()
        lines=[{k:v for k,v in item.items() if not k.startswith("_") and k!="net"} for item in self.sales_items if str(item.get("description") or "").strip()]
        if not self.sales_party.get().strip(): return messagebox.showwarning("Sales Invoice","Choose or type the customer")
        orphan=[item for item in self.sales_items if not str(item.get("description") or "").strip() and float(item.get("quantity") or 0)*float(item.get("unit_price") or 0)]
        if orphan: return messagebox.showwarning("Sales Invoice",
                "A line has an amount but no description. Add a description or delete that line before saving, so the saved total matches what you see.")
        if not lines: return messagebox.showwarning("Sales Invoice","Add at least one line with a description")
        invoice={"invoice_number":self.sales_no.get().strip(),"invoice_date":self.sales_date.get().strip(),
                 "party_name":self.sales_party.get().strip(),"kind":"sales","currency":self.sales_currency.get(),
                 "supplier_account":self.sales_supplier_account.get().split(" - ",1)[0].strip(),
                 "vat_account":self.sales_vat_account.get().split(" - ",1)[0].strip() or "4427",
                 "expense_account":self.sales_expense_account.get().split(" - ",1)[0].strip() or self.default_sales_posting_account(),
                 "supplier_side":self.sales_supplier_side.get(),"vat_side":self.sales_vat_side.get(),"expense_side":self.sales_expense_side.get(),
                 "due_date":self.sales_due_date.get().strip(),"payment_method":self.sales_payment_method.get(),"amount_paid":self.sales_amount_paid.get().strip().replace(",","") or "0",
                 "cash_account":self.sales_cash_account.get().split(" - ",1)[0].strip(),
                 "branch":self.sales_branch.get(),"status":"posted" if post else "review","source_file":"Sales Invoice","source_row":None,
                 "department":self.dimension_code(self.sales_department.get()),"project":self.dimension_code(self.sales_project.get()),
                 "vat_treatment":SALE_TREATMENTS.get(self.sales_treatment.get(),"standard"),
                 "doc_subtype":{"Credit Note":"credit_note","Return":"credit_note","Debit Note":"debit_note"}.get(self.sales_doc_type.get(),"invoice"),
                 "is_return":self.sales_doc_type.get()=="Return",
                 "invoice_discount_percent":self.sales_discount_percent.get().strip() or "0","invoice_discount_amount":self.sales_discount_amount.get().strip() or "0",
                 "gross_before_discount":getattr(self,"sales_calculation",{}).get("total","")}
        if invoice["doc_subtype"]=="credit_note":
            invoice["amount_paid"]="0"
        try:
            invoice["invoice_date"]=formatted_user_date(invoice["invoice_date"])
            if invoice["due_date"]: invoice["due_date"]=formatted_user_date(invoice["due_date"])
        except ValueError as exc: return messagebox.showerror("Sales Invoice",str(exc))
        if self.sales_edit_id:
            if not messagebox.askyesno("Sales Invoice",f"Save the changes to invoice {invoice['invoice_number']}? Its journal entry will be replaced with the new figures."): return
        try:
            if self.sales_edit_id: self.client.replace_invoice(self.sales_edit_id,invoice,lines)
            else:
                created=self.client.create_manual_invoice(invoice,lines)
                pdf=getattr(self,"sales_pdf_path",None)  # 2.9.90: the PDF the invoice was read from stays attached to it
                if pdf and created.get("invoice_id"):
                    try: self.client.upload_attachment(created["invoice_id"],Path(pdf).name,"application/pdf",Path(pdf).read_bytes())
                    except Exception as exc: messagebox.showwarning("Sales Invoice",f"The invoice is saved, but its PDF was not attached: {exc}. Use Attach on the invoice.")
                self.sales_pdf_path=None
        except Exception as exc: return messagebox.showerror("Sales Invoice",str(exc))
        number=invoice["invoice_number"]
        waiting=bool(locals().get("created") and isinstance(locals().get("created"),dict) and locals()["created"].get("approval"))  # 2.9.93
        messagebox.showinfo("Sales Invoice",f'Invoice {number} saved as a draft: it waits for approval by another user.' if waiting else f'Invoice {number} saved as {"Posted" if post else "Draft"}.')
        self.new_sales_invoice(confirm=False)
        self.load_dashboard(); self.load_invoices(); self.load_journal(); self.load_trial()

    def delete_sales_invoice(self):
        if not self.sales_edit_id: return messagebox.showwarning("Sales Invoice","Open a saved invoice first")
        number=self.sales_no.get()
        if not messagebox.askyesno("Delete Invoice",f"Mark invoice {number} DELETED? Its number stays in the invoice list; the journal entry is removed."):
            return
        try: self.client.delete_invoice(self.sales_edit_id)
        except Exception as exc: return messagebox.showerror("Sales Invoice",str(exc))
        self.new_sales_invoice(confirm=False)
        self.load_invoices(); self.load_dashboard(); self.load_journal(); self.load_trial()
