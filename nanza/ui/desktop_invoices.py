"""Invoices and sales invoice screens. (moved out of desktop.py in 2.9.41, unchanged)."""
from __future__ import annotations
from pathlib import Path

from desktop_common import (  # 2.9.102: the names this module uses (no more 'import *')
    bulk_action, column_toggles, datetime, Decimal, export_excel, export_invoice_pdf, filedialog, flow_toolbars,
    formatted_user_date, GOLD, LIGHT, messagebox, mimetypes, natural_sort_value, NAVY, PURCHASE_USES, resource_path,
    ROUND_HALF_UP, SALE_TREATMENTS, sortable_date, TAXABLE_LABEL, tk, tr, ttk, uuid
)
from tkinter import simpledialog
from desktop_common import vat_rate, vat_rate_text, vat_currency  # 2.9.72
from desktop_common import main_currency  # 2.9.71
from desktop_sales_invoice import SalesInvoiceMixin  # 2.9.94: the sales invoice screen
from free_accounts import suggest_and_autocreate


class InvoicesMixin(SalesInvoiceMixin):
    def _bind_ai_account_suggestion(self, parent, description, account_variable=None, row=0, columnspan=4,
                                    kind_variable=None):
        frame = tk.Frame(parent, bg=LIGHT)
        frame.grid(row=row, column=0, columnspan=columnspan, sticky="w", padx=8, pady=(2, 6))
        label = tk.Label(frame, text="", bg=LIGHT, fg=NAVY, anchor="w", justify="left", wraplength=620)
        label.pack(side="left", padx=(0, 8))
        use_button = None
        if account_variable is not None:
            use_button = tk.Button(frame, text="Use account", bg="#e7f0e8", fg="#176b2c", border=0,
                                   padx=8, pady=2)
        state = {"after_id": None, "code": None}

        def apply_suggestion():
            state["after_id"] = None
            if not parent.winfo_exists():
                return
            if kind_variable is not None and kind_variable.get().strip().casefold() in ("sale", "sales"):
                state["code"] = None
                label.config(text="")
                if use_button:
                    use_button.pack_forget()
                return
            text = description.get().strip()
            if not text:
                state["code"] = None
                label.config(text="")
                if use_button:
                    use_button.pack_forget()
                return
            try:
                result = suggest_and_autocreate(text, self.client)
            except (RuntimeError, ValueError, OSError) as exc:
                state["code"] = None
                label.config(text=f"AI account suggestion unavailable: {exc}", fg="#8B1E1E")
                if use_button:
                    use_button.pack_forget()
                return
            if not result.get("found"):
                state["code"] = None
                label.config(text="")
                if use_button:
                    use_button.pack_forget()
                return
            state["code"] = result.get("new_9digit_code") or result["base_code"]
            label.config(
                text=f'اقتراح AI: {result["base_code"]} - {result["base_name"]}'
                + (f'   |   تم إنشاء {result["new_9digit_code"]} تلقائيا - 9 digits'
                   if result.get("auto_created") else ""),
                fg="#176b2c" if result.get("auto_created") else NAVY,
            )
            if use_button:
                use_button.config(command=lambda: account_variable.set(state["code"]))
                use_button.pack(side="left")

        def schedule(*_args):
            if state["after_id"] is not None:
                try:
                    parent.after_cancel(state["after_id"])
                except tk.TclError:
                    pass
            if parent.winfo_exists():
                state["after_id"] = parent.after(450, apply_suggestion)

        description.trace_add("write", schedule)
        if kind_variable is not None:
            kind_variable.trace_add("write", schedule)
        schedule()
        return frame

    def build_invoices(self):
        l=self.language.get(); self.invoice_tree=self.table(self.invoices_tab,[("no",tr(l,"invoice_no"),125),("status","Status",70),("date",tr(l,"date"),88),
                ("party",tr(l,"party"),160),("branch","Branch",120),("kind","Type",90),("currency",tr(l,"currency"),60),("deductible","Deductible",95),
                ("non_deductible","Non-Deductible",105),("total",tr(l,"total"),90),("payment_method","Payment Method",110),("paid","Paid Amount",100),("lbp",
                "LBP Eq.",105),("usd","USD Eq.",90),("debit","D",80),("credit","C",80),("vat_status","VAT Deductible",95)])
        invoice_actions=tk.Frame(self.invoices_tab,bg=LIGHT); invoice_actions.pack(fill="x",anchor="w",pady=(0,10))
        # 2.9.68: Branch and Type are tick lists (one, several or All); D / C show the debit and / or credit rows
        from multi_select import MultiSelect
        if self.invoice_branch.get() in ("","All Branches"): self.invoice_branch.set("All")
        self.invoice_type_filter=tk.StringVar(master=self,value="All"); self.invoice_show_debit=tk.BooleanVar(master=self,value=True); self.invoice_show_credit=tk.BooleanVar(master=self,value=True)
        def branch_names(box=None):
            try: names=[row["name"] for row in self.client.branches()]
            except Exception: names=[]
            if box is not None: box["values"]=names
            return names
        tk.Label(invoice_actions,text="Branch:",bg=LIGHT).pack(side="left")
        MultiSelect(invoice_actions,self.invoice_branch,branch_names(),width=15,title="Branch",on_change=self.load_invoices,before_open=branch_names,bg=LIGHT).pack(side="left",padx=4)
        tk.Label(invoice_actions,text="Type:",bg=LIGHT).pack(side="left",padx=(6,0))
        self.invoice_type_box=MultiSelect(invoice_actions,self.invoice_type_filter,[],width=14,title="Type",on_change=self.load_invoices,bg=LIGHT); self.invoice_type_box.pack(side="left",padx=4)
        tk.Checkbutton(invoice_actions,text="D",variable=self.invoice_show_debit,command=self.load_invoices,bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left")
        tk.Checkbutton(invoice_actions,text="C",variable=self.invoice_show_credit,command=self.load_invoices,bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left",padx=(0,6))
        tk.Label(invoice_actions,text="Sort By:",bg=LIGHT).pack(side="left",padx=(8,2))
        ttk.Combobox(invoice_actions,textvariable=self.invoice_sort_by,state="readonly",width=16,
            values=["Date","Invoice Number","Customer / Supplier","Account","Amount","Currency"]).pack(side="left",padx=2)
        ttk.Combobox(invoice_actions,textvariable=self.invoice_sort_order,state="readonly",width=10,
            values=["Ascending","Descending"]).pack(side="left",padx=2)
        tk.Button(invoice_actions,text=tr(l,"refresh"),command=self.load_invoices,bg=NAVY,fg="white",border=0,padx=20,pady=7).pack(side="left",padx=4)
        # 2.9.107: Select All / Clear Selection (Ctrl+A does the same in the table)
        def select_all_invoices():
            rows=list(self.invoice_tree.get_children())
            if rows: self.invoice_tree.selection_set(rows); self.invoice_tree.focus_set()
        self.action_button(invoice_actions,"Select All",select_all_invoices).pack(side="left",padx=4)
        self.action_button(invoice_actions,"Clear Selection",lambda:self.invoice_tree.selection_remove(*self.invoice_tree.selection())).pack(side="left",padx=4)
        # 2.9.94: the buttons in three labelled rows (Edit / Accounts & VAT / Documents) instead of one long pile
        def group(title):
            row=tk.Frame(self.invoices_tab,bg=LIGHT); row.pack(fill="x",anchor="w",pady=(0,6))
            tk.Label(row,text=title,bg=LIGHT,fg="#5f6b76",font=("Segoe UI",8,"bold"),anchor="w").pack(side="left",padx=(4,6))
            return row
        lifecycle=group("EDIT")
        tk.Button(lifecycle,text="Edit Selected",command=self.edit_selected_invoice,bg=GOLD,fg=NAVY,
                  font=("Segoe UI",9,"bold"),border=0,padx=20,pady=7).pack(side="left",padx=4)
        self.action_button(lifecycle,"Add Invoice Row",self.add_invoice_row).pack(side="left",padx=4)
        self.action_button(lifecycle,"Add Item",self.add_item_to_selected_invoice).pack(side="left",padx=4)
        self.action_button(lifecycle,"Duplicate",self.duplicate_selected_invoice).pack(side="left",padx=4)
        self.action_button(lifecycle,"Create Return (goods back)",self.return_selected_invoice).pack(side="left",padx=4)
        self.action_button(lifecycle,"Approve Selected",self.approve_selected_invoices).pack(side="left",padx=4)  # 2.9.93
        tk.Button(lifecycle,text="Cancel Invoice",command=self.cancel_selected_invoice,bg="#8B1E1E",fg="white",border=0,padx=15,pady=7).pack(side="left",padx=(16,4))
        tk.Button(lifecycle,text="Delete Selected",command=self.delete_selected_invoice,bg="#6B1010",fg="white",border=0,padx=15,pady=7).pack(side="left",padx=4)
        accounts=group("ACCOUNTS & VAT")
        self.action_button(accounts,"One Account for Selected...",self.set_account_for_selected_invoices).pack(side="left",padx=4)
        self.action_button(accounts,"Check Sales Accounts...",self.check_sales_accounts).pack(side="left",padx=4)
        self.action_button(accounts,"VAT Deductible / Non-Deductible",self.toggle_selected_invoice_vat).pack(side="left",padx=4)
        self.action_button(accounts,"VAT Treatment",self.vat_classification_dialog).pack(side="left",padx=4)
        tk.Button(accounts,text="Create Missing Payment Entries",command=self.create_missing_payment_entries,bg=NAVY,fg="white",
                  font=("Segoe UI",9,"bold"),border=0,padx=14,pady=7).pack(side="left",padx=4)
        documents=group("DOCUMENTS")
        self.action_button(documents,"Save Data",self.confirm_invoice_data_saved).pack(side="left",padx=4)
        self.action_button(documents,"Export Excel",self.export_invoices_excel).pack(side="left",padx=4)
        self.action_button(documents,"Branded Invoice PDF",self.export_selected_invoice_pdf).pack(side="left",padx=4)
        self.action_button(documents,"Attach PDF / Image",self.attach_to_selected_invoice).pack(side="left",padx=4)
        self.action_button(documents,"Attachments",self.show_selected_attachments).pack(side="left",padx=4)
        self.action_button(documents,"History",self.show_invoice_history).pack(side="left",padx=4)
        self.invoice_tree.bind("<Double-1>",lambda _event:self.edit_selected_invoice())
        self.invoice_tree.bind("<Delete>",lambda _event:self.delete_selected_invoice())
        column_toggles(self.invoice_tree,["branch","kind","debit","credit"],"uploaded_data")  # 2.9.69: show / hide next to Search
        flow_toolbars(invoice_actions,lifecycle,accounts,documents)  # 2.9.59
        self.load_invoices()

    def create_missing_payment_entries(self):
        """Invoices uploaded before 2.9.47 as paid in cash / bank: make their settlement entries now."""
        if not messagebox.askyesno("Payment entries","Create the payment entry (Dr cash or bank / Cr customer, or Dr supplier / Cr cash or bank) "
                                   "for every invoice marked as paid that does not have one yet?\n\nCash goes to 531 and other methods to 512, "
                                   "unless an account was chosen on the invoice (Edit Selected > Cash / Bank Account)."): return
        try: result=self.client.create_missing_invoice_payments()
        except Exception as exc: return messagebox.showerror("Payment entries",str(exc))
        text=f'{len(result["created"])} payment entr{"y" if len(result["created"])==1 else "ies"} created.'
        if result["skipped"]:
            text+="\n\nNot done (locked or closed period, or other reason):\n"+"\n".join(f'{s["invoice_number"]}: {s["reason"]}' for s in result["skipped"][:15])
        messagebox.showinfo("Payment entries",text)
        self.load_invoices(); self.load_journal(); self.load_trial()

    def load_invoices(self):
        # An empty invoice list requires no currency conversion. Avoid a blocking
        # historical EUR download when opening an empty company offline.
        try: rows=self.client.invoices(); rates=self.client.exchange_rates() if rows else []
        except Exception as exc: return messagebox.showerror("Error",str(exc))
        account=self.invoice_account_search.get().split(" - ",1)[0].strip()
        if account: rows=[row for row in rows if account in (str(row.get("supplier_account") or ""),str(row.get("vat_account") or ""),
                str(row.get("expense_account") or ""),str(row.get("expense_no_vat_account") or ""))]
        selected=self.view_currency.get()
        rows=[r for r in rows if selected=="All Currencies" or r["currency"]==selected]
        from multi_select import chosen_values, matches
        branches=chosen_values(self.invoice_branch.get()) if self.invoice_branch.get()!="All Branches" else []
        if branches: rows=[r for r in rows if matches(r.get("branch_name") or "Head Office",self.invoice_branch.get())]
        if hasattr(self,"invoice_type_box"):  # 2.9.68: Type tick list, D / C ticks
            self.invoice_type_box["values"]=sorted({self.invoice_entry_label(r) for r in rows})
            if chosen_values(self.invoice_type_filter.get()): rows=[r for r in rows if matches(self.invoice_entry_label(r),self.invoice_type_filter.get())]
            show_debit,show_credit=self.invoice_show_debit.get(),self.invoice_show_credit.get()
            if not (show_debit and show_credit):
                rows=[r for r in rows if (show_debit and float(r.get("debit") or 0)) or (show_credit and float(r.get("credit") or 0))]
        sort_name=self.invoice_sort_by.get()
        def invoice_key(row):
            if sort_name=="Date": return sortable_date(row.get("invoice_date"))
            if sort_name=="Invoice Number": return natural_sort_value(row.get("invoice_number"))
            if sort_name=="Customer / Supplier": return str(row.get("party_name") or "").casefold()
            if sort_name=="Account": return natural_sort_value(row.get("supplier_account"))
            if sort_name=="Amount": return float(row.get("total") or 0)
            return str(row.get("currency") or "").casefold()
        rows.sort(key=invoice_key,reverse=self.invoice_sort_order.get()=="Descending")
        self.invoice_rows={str(r["id"]):r for r in rows}
        self.invoice_tree.delete(*self.invoice_tree.get_children())
        def money(value):  # 2.9.94: 1,637.25 like the other amounts (was 1637.25 / 1475.0)
            try: return f"{float(value or 0):,.2f}"
            except (TypeError, ValueError): return value
        for r in rows:
            lbp,usd=self.exchange_equivalents(float(r["total"] or 0),r["currency"],rates)
            entry_label=self.invoice_entry_label(r)
            self.invoice_tree.insert("","end",iid=str(r["id"]),values=(r["invoice_number"],
                    "DELETED" if r.get("status")=="deleted" else str(r.get("status") or "").title(),r["invoice_date"],r["party_name"],
                    r.get("branch_name") or "Head Office",entry_label,r["currency"],money(r.get("deductible_subtotal",r["subtotal"])),
                    money(r.get("non_deductible_subtotal",0)),money(r["total"]),r.get("payment_method") or "",money(r.get("settled_amount",r.get("amount_paid"))),
                    "" if lbp is None else f"{lbp:,.2f}","" if usd is None else f"{usd:,.2f}",money(r["debit"]),money(r["credit"]),
                    ("Yes" if r.get("vat_recoverable",1) else "NO") if r.get("kind")=="purchase" and float(r.get("vat") or 0) else ""),
                    tags=("deleted",) if r.get("status")=="deleted" else ())
        self.invoice_tree.tag_configure("deleted",foreground="#8B1E1E")

    @staticmethod
    def invoice_entry_label(r):
        return (("Sales" if r.get("kind")=="sale" else "Purchase")+" Return" if r.get("is_return")
                else ("Sales" if r.get("kind")=="sale" else "Supplier")+" Credit Note" if r.get("doc_subtype")=="credit_note"
                else ("Sales" if r.get("kind")=="sale" else "Supplier")+" Debit Note" if r.get("doc_subtype")=="debit_note"
                else r.get("entry_type") or r["kind"])

    def vat_classification_dialog(self):
        selected=self.invoice_tree.selection()
        if not selected: return messagebox.showwarning("VAT Treatment","Select an invoice first")
        row=self.invoice_rows.get(selected[0])
        if not row: return
        sale=row["kind"]=="sale"
        window=tk.Toplevel(self); window.title(f"VAT Treatment - {row['invoice_number']}"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        treatment=tk.StringVar(); use=tk.StringVar(); reverse=tk.BooleanVar(value=row.get("vat_treatment")=="reverse_charge")
        if sale:
            treatment.set(next((k for k,v in SALE_TREATMENTS.items() if v==(row.get("vat_treatment") or "standard")),TAXABLE_LABEL))
            tk.Label(window,text="Sale type (Law 379/2001)",bg=LIGHT,font=("Segoe UI",9,"bold")).grid(row=0,column=0,padx=12,pady=10,sticky="w")
            ttk.Combobox(window,textvariable=treatment,values=list(SALE_TREATMENTS),state="readonly",width=24).grid(row=0,column=1,padx=12,pady=10)
            tk.Label(window,text="Zero-rated: exports and like transactions (Art. 19-21), deductible input VAT.\nExempt: Art. 16-17 activities and goods, reduces the deduction ratio.",
                    bg=LIGHT,fg="#5f6b76",justify="left").grid(row=1,column=0,columnspan=2,padx=12,sticky="w")
        else:
            use.set(next((k for k,v in PURCHASE_USES.items() if v==(row.get("vat_use") or "mixed")),"Mixed (partial deduction)"))
            tk.Label(window,text="Input VAT used for",bg=LIGHT,font=("Segoe UI",9,"bold")).grid(row=0,column=0,padx=12,pady=10,sticky="w")
            ttk.Combobox(window,textvariable=use,values=list(PURCHASE_USES),state="readonly",width=26).grid(row=0,column=1,padx=12,pady=10)
            tk.Checkbutton(window,text="Service from abroad - reverse charge (Art. 40)",variable=reverse,bg=LIGHT).grid(row=1,column=0,columnspan=2,padx=12,sticky="w")
        def save():
            try: self.client.set_vat_classification("invoice",row["id"],
                    SALE_TREATMENTS[treatment.get()] if sale else ("reverse_charge" if reverse.get() else "standard"),
                    None if sale else PURCHASE_USES[use.get()])
            except Exception as exc: return messagebox.showerror("VAT Treatment",str(exc),parent=window)
            window.destroy(); self.load_invoices()
        self.action_button(window,"Save",save).grid(row=2,column=0,columnspan=2,pady=12)

    def edit_selected_invoice(self):
        selected=self.invoice_tree.selection()
        if not selected:
            return messagebox.showwarning("Invoices","Select one invoice row to edit")
        invoice_id=selected[0]
        row=self.invoice_rows.get(invoice_id)
        if not row:
            return messagebox.showerror("Invoices","The selected invoice could not be found")
        window=tk.Toplevel(self); window.title(f'Edit Invoice {row["invoice_number"]}')
        window.configure(bg=LIGHT); window.transient(self); window.grab_set(); window.resizable(False,False)
        variables={
            "invoice_number":tk.StringVar(value=row["invoice_number"]),
            "invoice_date":tk.StringVar(value=row["invoice_date"]),
            "party_name":tk.StringVar(value=row["party_name"]),
            "kind":tk.StringVar(value=row.get("entry_type") or ("sales" if row["kind"]=="sale" else "purchases")),
            "currency":tk.StringVar(value=row["currency"]),
            "deductible_subtotal":tk.StringVar(value=row.get("deductible_subtotal") or row["subtotal"]),
            "non_deductible_subtotal":tk.StringVar(value=row.get("non_deductible_subtotal") or "0"),
            "vat":tk.StringVar(value=row["vat"]),
            "total":tk.StringVar(value=row["total"]),
            "supplier_account":tk.StringVar(value=row["supplier_account"]),
            "vat_account":tk.StringVar(value=row["vat_account"]),
            "expense_account":tk.StringVar(value=row["expense_account"]),
            "expense_no_vat_account":tk.StringVar(value=row.get("expense_no_vat_account") or "601100001"),
            "supplier_side":tk.StringVar(value="C - Credit" if (row.get("supplier_side") or "C")=="C" else "D - Debit"),
            "vat_side":tk.StringVar(value="C - Credit" if (row.get("vat_side") or "D")=="C" else "D - Debit"),
            "expense_side":tk.StringVar(value="C - Credit" if (row.get("expense_side") or "D")=="C" else "D - Debit"),
            "expense_no_vat_side":tk.StringVar(value="C - Credit" if (row.get("expense_no_vat_side") or "D")=="C" else "D - Debit"),
            "status":tk.StringVar(value=row["status"]),
            "due_date":tk.StringVar(value=row.get("due_date") or ""),
            "amount_paid":tk.StringVar(value=row.get("amount_paid") or "0"),
            "payment_method":tk.StringVar(value=row.get("payment_method") or ("Cash" if float(row.get("amount_paid") or 0) else "On Account (Not Cash)")),
            "cash_account":tk.StringVar(value=row.get("payment_account") or ""),
            "description":tk.StringVar(value=row.get("description") or ""),
            "branch":tk.StringVar(value=row.get("branch_name") or "Head Office"),
        }
        # 2.9.78: details on top; below, one line per posting - account, D/C and amount - and the payment (method, account,
        # amount). Amounts follow each other: VAT = rate x amount with VAT (until typed), Total = sum, and a paid method
        # (Cash / Bank ...) fills its account (531 / 512) and the amount paid with the Total.
        details=tk.Frame(window,bg=LIGHT); details.grid(row=0,column=0,sticky="ew",padx=6,pady=(6,0))
        fields=[("Invoice Number","invoice_number"),("Date (DD-MM-YYYY)","invoice_date"),("Description","description"),("Branch","branch"),
                ("Customer / Supplier","party_name"),("Type","kind"),("Currency","currency"),("Status","status"),("Due Date (DD-MM-YYYY)","due_date")]
        for index,(label,key) in enumerate(fields):
            grid_row=index//2; grid_column=(index%2)*2
            tk.Label(details,text=label,bg=LIGHT,anchor="w").grid(row=grid_row,column=grid_column,sticky="w",padx=(8,5),pady=6)
            if key=="kind": widget=ttk.Combobox(details,textvariable=variables[key],values=["assets","expenses","purchases","sales"],state="readonly",width=24)
            elif key=="currency": widget=ttk.Combobox(details,textvariable=variables[key],values=self.currency_codes,state="readonly",width=24)
            elif key=="status": widget=ttk.Combobox(details,textvariable=variables[key],values=["posted","review"],state="readonly",width=24)
            elif key=="branch": widget=self.branch_selector(details,variables[key],24,False)
            elif key in ("invoice_date","due_date"): widget=self.date_entry(details,variables[key],27)
            else: widget=tk.Entry(details,textvariable=variables[key],width=27)
            widget.grid(row=grid_row,column=grid_column+1,padx=(5,14),pady=6,sticky="w")
        self._bind_ai_account_suggestion(details, variables["description"], variables["expense_account"],
                                         row=(len(fields)+1)//2, columnspan=4, kind_variable=variables["kind"])

        postings=tk.LabelFrame(window,text="Accounts and amounts",bg=LIGHT,padx=8,pady=6); postings.grid(row=1,column=0,sticky="ew",padx=12,pady=(8,0))
        for column,title in enumerate(("Line","Account","D / C","Amount")):
            tk.Label(postings,text=title,bg=LIGHT,fg=NAVY,font=("Segoe UI",9,"bold")).grid(row=0,column=column,sticky="w",padx=6,pady=(0,4))
        sale=variables["kind"].get()=="sales"
        lines=[("VAT","vat_account","vat_side","vat"),
               ("Sales (with VAT)" if sale else "Purchases / Expenses with VAT","expense_account","expense_side","deductible_subtotal"),
               ("Without VAT (non-deductible)","expense_no_vat_account","expense_no_vat_side","non_deductible_subtotal"),
               ("Customer" if sale else "Supplier","supplier_account","supplier_side","total")]
        amount_entries={}
        def account_cell(parent,variable):
            frame=tk.Frame(parent,bg=LIGHT)
            self.account_search_box(frame,variable,16,replace_on_focus=True).pack(side="left")
            tk.Button(frame,text="Find",command=lambda v=variable:self.open_account_lookup(v,include_groups=True),bg=NAVY,fg="white",border=0,padx=6,pady=2).pack(side="left",padx=(3,0))
            return frame
        for index,(label,account_key,side_key,amount_key) in enumerate(lines,1):
            tk.Label(postings,text=label,bg=LIGHT,anchor="w").grid(row=index,column=0,sticky="w",padx=6,pady=4)
            account_cell(postings,variables[account_key]).grid(row=index,column=1,sticky="w",padx=6,pady=4)
            ttk.Combobox(postings,textvariable=variables[side_key],values=["D - Debit","C - Credit"],state="readonly",width=10).grid(row=index,column=2,sticky="w",padx=6,pady=4)
            entry=tk.Entry(postings,textvariable=variables[amount_key],width=16,justify="right",state="readonly" if amount_key=="total" else "normal")
            entry.grid(row=index,column=3,sticky="w",padx=6,pady=4); amount_entries[amount_key]=entry
        payment_row=len(lines)+1
        ttk.Separator(postings,orient="horizontal").grid(row=payment_row,column=0,columnspan=4,sticky="ew",pady=(6,6))
        tk.Label(postings,text="Payment",bg=LIGHT,anchor="w",font=("Segoe UI",9,"bold")).grid(row=payment_row+1,column=0,sticky="w",padx=6,pady=4)
        account_cell(postings,variables["cash_account"]).grid(row=payment_row+1,column=1,sticky="w",padx=6,pady=4)
        method_box=ttk.Combobox(postings,textvariable=variables["payment_method"],values=["On Account (Not Cash)","Cash","Bank Transfer","Cheque","Card","Other"],state="readonly",width=20)
        method_box.grid(row=payment_row+1,column=2,sticky="w",padx=6,pady=4)
        paid_entry=tk.Entry(postings,textvariable=variables["amount_paid"],width=16,justify="right"); paid_entry.grid(row=payment_row+1,column=3,sticky="w",padx=6,pady=4)
        tk.Label(postings,text="Cash -> 531, Bank Transfer / Cheque / Card -> 512 (change the account if needed); the amount paid follows the Total.",
                 bg=LIGHT,fg="#5f6b76").grid(row=payment_row+2,column=0,columnspan=4,sticky="w",padx=6)

        exchange_label=tk.Label(window,text="",bg=LIGHT,fg=NAVY,font=("Segoe UI",9,"bold"))
        import decimal as _decimal
        def number(key):
            try: return _decimal.Decimal(str(variables[key].get() or "0").replace(",",""))
            except _decimal.InvalidOperation: return None
        auto={"vat":abs((number("deductible_subtotal") or 0)*_decimal.Decimal(str(vat_rate(self)))/100-(number("vat") or 0))<_decimal.Decimal("0.02"),
              "paid":(number("amount_paid") or 0)==(number("total") or 0) and (number("total") or 0)>0,"busy":False}
        def recompute(*_a):
            if auto["busy"]: return
            auto["busy"]=True
            try:
                deductible=number("deductible_subtotal"); non_deductible=number("non_deductible_subtotal")
                if deductible is None or non_deductible is None: return
                if auto["vat"]: variables["vat"].set(f'{(deductible*_decimal.Decimal(str(vat_rate(self)))/100).quantize(_decimal.Decimal("0.01"))}')
                vat=number("vat")
                if vat is None: return
                total=deductible+non_deductible+vat; variables["total"].set(f"{total.quantize(_decimal.Decimal('0.01'))}")
                if auto["paid"] and not variables["payment_method"].get().lower().startswith("on account"): variables["amount_paid"].set(f"{total.quantize(_decimal.Decimal('0.01'))}")
                exchange_label.config(text=self.exchange_equivalent_text(float(total),variables["currency"].get()))
            finally: auto["busy"]=False
        def method_changed(_event=None):
            method=variables["payment_method"].get().lower()
            if method.startswith("on account"):
                variables["amount_paid"].set("0"); variables["cash_account"].set(""); auto["paid"]=False; return
            current=variables["cash_account"].get().split(" - ",1)[0].strip()
            if not current or current in ("531","512"): variables["cash_account"].set("531" if method=="cash" else "512")
            variables["amount_paid"].set(variables["total"].get()); auto["paid"]=True
        amount_entries["vat"].bind("<Key>",lambda _e:auto.__setitem__("vat",False))
        paid_entry.bind("<Key>",lambda _e:auto.__setitem__("paid",False))
        for key in ("deductible_subtotal","non_deductible_subtotal","vat"): variables[key].trace_add("write",recompute)
        method_box.bind("<<ComboboxSelected>>",method_changed)

        def save_update():
            values={key:variable.get().strip() for key,variable in variables.items()}
            if not all(values[key] for key in ("invoice_number","invoice_date","party_name")):
                return messagebox.showwarning("Invoices","Invoice number, date, and customer/supplier are required",parent=window)
            for key in ("supplier_account","vat_account","expense_account","expense_no_vat_account"):
                code=values[key].split(" - ",1)[0].strip()
                if code and not code.replace(".","").isdigit():
                    return messagebox.showwarning("Invoices",f"Choose a valid {key.replace('_',' ')} from the account list",parent=window)
                values[key]=code
            try:
                values["invoice_date"]=formatted_user_date(values["invoice_date"])
                if values.get("due_date"): values["due_date"]=formatted_user_date(values["due_date"])
            except ValueError: return messagebox.showwarning("Invoices","Enter 8 date digits: DDMMYYYY",parent=window)
            try:
                deductible=float(values["deductible_subtotal"]); non_deductible=float(values["non_deductible_subtotal"]); subtotal=deductible+non_deductible; \
                    vat=float(values["vat"]); total=float(values["total"])
                amount_paid=float(values["amount_paid"] or 0)
            except ValueError:
                return messagebox.showwarning("Invoices","Deductible, Non-Deductible, VAT, and Total must be valid numbers",parent=window)
            if abs((subtotal+vat)-total)>0.005:
                return messagebox.showwarning("Invoices","Total must equal Before VAT plus VAT",parent=window)
            if amount_paid<0 or amount_paid>total:
                return messagebox.showwarning("Invoices","Amount paid must be between zero and Total",parent=window)
            method=values.get("payment_method") or ""
            if amount_paid==0 and method and not method.lower().startswith("on account"):
                # 2.9.54: choosing Cash / Bank on an uploaded invoice means it was paid: the payment goes to the cash or bank statement.
                answer=messagebox.askyesnocancel("Invoices",f"Payment method is {method} but Amount Paid is 0.\n\nYes = paid in full ({total:,.2f}): the payment is posted to "
                    f"{values.get('cash_account') or ('531 cash' if method.lower()=='cash' else '512 bank')} and shows in its statement\nNo = keep it unpaid (on account)",parent=window)
                if answer is None: return
                if answer: values["amount_paid"]=f"{total:.2f}"
                else: values["payment_method"]="On Account (Not Cash)"
            try:
                self.client.update_invoice(int(invoice_id),values)
            except Exception as exc:
                return messagebox.showerror("Invoices",str(exc),parent=window)
            window.destroy()
            self.load_invoices(); self.load_dashboard(); self.load_journal(); self.load_trial()
            paid=float(values.get("amount_paid") or 0)
            messagebox.showinfo("Invoices",
                    "Invoice updated successfully"+(f". Payment of {paid:,.2f} posted to {values.get('cash_account') or ('531' if (values.get('payment_method') or '').lower()=='cash' else '512')} (see its account statement)." if paid else ""))

        exchange_label.config(text=self.exchange_equivalent_text(float(row["total"] or 0),row["currency"]))
        exchange_label.grid(row=2,column=0,pady=(6,0))
        tk.Label(window,text="Accounts: click the number and type a replacement, or use Find. Tab moves to the next field.",
                 bg=LIGHT,fg="#5f6b76").grid(row=3,column=0,pady=(5,0))
        buttons=tk.Frame(window,bg=LIGHT); buttons.grid(row=4,column=0,pady=16)
        tk.Button(buttons,text="Save Update",command=save_update,bg=GOLD,fg=NAVY,font=("Segoe UI",10,"bold"),
                  border=0,padx=24,pady=8).pack(side="left",padx=5)
        tk.Button(buttons,text="Cancel",command=window.destroy,bg=NAVY,fg="white",border=0,padx=20,pady=8).pack(side="left",padx=5)

    def selected_invoice_id(self):
        selected=self.invoice_tree.selection()
        if not selected:
            messagebox.showwarning("Invoices","Select one invoice row first"); return None
        return int(selected[0])

    def delete_selected_invoice(self):
        """Delete drafts and void posted invoices selected with Ctrl / Shift / drag."""
        selected=[iid for iid in self.invoice_tree.selection()
                  if self.invoice_rows.get(iid,{}).get("status") not in ("deleted", "cancelled", "void")]
        if not selected: return messagebox.showwarning("Invoices","Select the invoice rows first (Ctrl / Shift or drag the mouse for several)")
        names=[(int(iid),self.invoice_rows.get(iid,{}).get("invoice_number") or iid) for iid in selected]
        shown=", ".join(str(n) for _i,n in names[:10])+(f" ... (+{len(names)-10})" if len(names)>10 else "")
        posted=any(self.invoice_rows.get(iid,{}).get("status")=="posted" for iid in selected)
        reason=simpledialog.askstring("Void Invoices", "Reason for voiding selected posted invoices (required):", parent=self) if posted else None
        if posted and not str(reason or "").strip(): return
        action="Void" if posted else "Delete"
        explanation=("Original entries remain; reversing entries will be added." if posted
                     else "Draft invoices will be deleted.")
        if not messagebox.askyesno("Invoices",f"{action} {len(names)} selected invoice(s)?\n{shown}\n\n{explanation}"): return
        bulk_action("Invoices",names,lambda invoice_id:self.client.delete_invoice(invoice_id,reason=reason))
        self.load_invoices(); self.load_dashboard(); self.load_journal(); self.load_trial()

    INVOICE_ACCOUNT_FIELDS = (("expense_account","Purchases / Expense / Sales account"),("vat_account","VAT account"),
                              ("expense_no_vat_account","Non-deductible account"),("supplier_account","Customer / Supplier account"),
                              ("payment_account","Cash / Bank account (paid invoices)"))  # 2.9.78

    def set_account_for_selected_invoices(self):
        """2.9.71: choose ONE account and it replaces that account on every selected row (Ctrl / Shift / drag)."""
        selected=[iid for iid in self.invoice_tree.selection() if self.invoice_rows.get(iid,{}).get("status") not in ("deleted","cancelled")]
        if not selected: return messagebox.showwarning("Invoices","Select the invoice rows first (Ctrl / Shift or drag the mouse for several)")
        window=tk.Toplevel(self); window.title("One Account for the Selected Rows"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        tk.Label(window,text=f"{len(selected)} row(s) selected",bg=LIGHT,fg=NAVY,font=("Segoe UI",10,"bold")).grid(row=0,column=0,columnspan=2,sticky="w",padx=14,pady=(14,6))
        labels=dict(self.INVOICE_ACCOUNT_FIELDS); field=tk.StringVar(value=labels["expense_account"]); account=tk.StringVar()
        tk.Label(window,text="Account to change",bg=LIGHT).grid(row=1,column=0,sticky="w",padx=14,pady=5)
        ttk.Combobox(window,textvariable=field,values=list(labels.values()),state="readonly",width=36).grid(row=1,column=1,sticky="w",padx=14,pady=5)
        tk.Label(window,text="New account (number or F2)",bg=LIGHT).grid(row=2,column=0,sticky="w",padx=14,pady=5)
        self.account_search_box(window,account,38).grid(row=2,column=1,sticky="w",padx=14,pady=5)
        tk.Label(window,text="Only that account changes, on the invoice and its journal lines; amounts and the other lines stay as they are.",
                 bg=LIGHT,fg="#5f6b76",wraplength=520,justify="left").grid(row=3,column=0,columnspan=2,sticky="w",padx=14,pady=(4,8))
        def apply():
            key=next((k for k,v in labels.items() if v==field.get()),"expense_account"); code=account.get().split(" - ",1)[0].strip()
            if not code: return messagebox.showwarning("Invoices","Choose the new account",parent=window)
            if not messagebox.askyesno("Invoices",f"Put account {code} as the {field.get().lower()} of {len(selected)} row(s)?",parent=window): return
            try: result=self.client.set_invoices_account([int(i) for i in selected],key,code)
            except Exception as exc: return messagebox.showerror("Invoices",str(exc),parent=window)
            window.destroy(); self.load_invoices(); self.load_dashboard(); self.load_journal(); self.load_trial()
            skipped=result.get("skipped") or []
            text=f'{len(result.get("done") or [])} row(s) now use {result.get("account")}.'
            if skipped: text+=f"\n\nNot changed ({len(skipped)}):\n"+"\n".join(skipped[:15])+(f"\n... and {len(skipped)-15} more" if len(skipped)>15 else "")
            (messagebox.showwarning if skipped else messagebox.showinfo)("Invoices",text)
        buttons=tk.Frame(window,bg=LIGHT); buttons.grid(row=4,column=0,columnspan=2,sticky="e",padx=14,pady=(0,14))
        tk.Button(buttons,text="Apply to Selected",command=apply,bg=GOLD,fg=NAVY,border=0,padx=16,pady=7,font=("Segoe UI",9,"bold")).pack(side="left",padx=4)
        tk.Button(buttons,text="Cancel",command=window.destroy,bg="white",fg=NAVY,border=0,padx=14,pady=7).pack(side="left",padx=4)

    def check_sales_accounts(self):
        """2.9.77: sales that earlier versions booked on wrong accounts (Excel import: customer on 4011 suppliers, revenue on
        601 expenses, VAT on deductible VAT) - listed, then corrected only when the user confirms."""
        try: problems=self.client.sales_account_problems()
        except Exception as exc: return messagebox.showerror("Check Sales Accounts",str(exc))
        if not problems: return messagebox.showinfo("Check Sales Accounts","Every sale is on the right accounts: its customer, a class 7 revenue account and output VAT (4427).")
        window=tk.Toplevel(self); window.title("Check Sales Accounts"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        if hasattr(self,"fit_dialog"): self.fit_dialog(window,980,520,600,320)
        tk.Label(window,text=f"{len(problems)} sale(s) are on wrong accounts. Fix moves only those accounts on the invoice and its journal lines; amounts, dates and VAT stay the same.",
                 bg=LIGHT,fg=NAVY,wraplength=900,justify="left",font=("Segoe UI",9,"bold")).pack(fill="x",padx=12,pady=(12,6))
        frame=tk.Frame(window,bg=LIGHT); frame.pack(fill="both",expand=True,padx=12)
        tree=ttk.Treeview(frame,columns=("no","date","party","total","what"),show="headings",selectmode="extended")
        for key,label,width in (("no","Invoice",110),("date","Date",90),("party","Customer",180),("total","Total",100),("what","What is corrected",460)):
            tree.heading(key,text=label); tree.column(key,width=width,anchor="e" if key=="total" else "w")
        scroll=ttk.Scrollbar(frame,orient="vertical",command=tree.yview); tree.configure(yscrollcommand=scroll.set); tree.pack(side="left",fill="both",expand=True); scroll.pack(side="right",fill="y")
        for problem in problems:
            tree.insert("","end",iid=str(problem["id"]),values=(problem["invoice_number"],problem["invoice_date"],problem.get("party_name") or "",
                        f'{float(problem.get("total") or 0):,.2f} {problem.get("currency") or ""}',"; ".join(problem["reasons"])))
        def fix(ids):
            if not ids: return messagebox.showwarning("Check Sales Accounts","Select the sales to correct",parent=window)
            if not messagebox.askyesno("Check Sales Accounts",f"Correct the accounts of {len(ids)} sale(s)? A backup is recommended first (Settings > Backup & Restore).",parent=window): return
            try: result=self.client.fix_sales_accounts([int(i) for i in ids])
            except Exception as exc: return messagebox.showerror("Check Sales Accounts",str(exc),parent=window)
            window.destroy(); self.load_invoices(); self.load_dashboard(); self.load_journal(); self.load_trial()
            skipped=result.get("skipped") or []
            text=f'{len(result.get("done") or [])} sale(s) corrected.'+(f"\n\nNot corrected ({len(skipped)}):\n"+"\n".join(skipped[:15]) if skipped else "")
            (messagebox.showwarning if skipped else messagebox.showinfo)("Check Sales Accounts",text)
        buttons=tk.Frame(window,bg=LIGHT); buttons.pack(fill="x",padx=12,pady=10)
        tk.Button(buttons,text="Correct Selected",command=lambda:fix(tree.selection()),bg=GOLD,fg=NAVY,border=0,padx=14,pady=7,font=("Segoe UI",9,"bold")).pack(side="left",padx=4)
        tk.Button(buttons,text="Correct All",command=lambda:fix(tree.get_children()),bg=NAVY,fg="white",border=0,padx=14,pady=7).pack(side="left",padx=4)
        tk.Button(buttons,text="Close",command=window.destroy,bg="white",fg=NAVY,border=0,padx=14,pady=7).pack(side="right",padx=4)

    def duplicate_selected_invoice(self):
        invoice_id=self.selected_invoice_id()
        if invoice_id is None: return
        try: created=self.client.duplicate_invoice(invoice_id)
        except Exception as exc: return messagebox.showerror("Invoices",str(exc))
        self.load_invoices(); self.load_dashboard(); self.load_journal(); self.load_trial()
        messagebox.showinfo("Invoices",f'Invoice duplicated as {created["invoice_number"]}')

    def cancel_selected_invoice(self):
        invoice_id=self.selected_invoice_id()
        if invoice_id is None: return
        row=self.invoice_rows.get(str(invoice_id),{})
        if row.get("status")=="cancelled": return messagebox.showwarning("Invoices","Invoice is already cancelled")
        window=tk.Toplevel(self); window.title("Cancel Invoice"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        reason=tk.StringVar()
        tk.Label(window,text="Cancellation reason:",bg=LIGHT).grid(row=0,column=0,padx=14,pady=14)
        tk.Entry(window,textvariable=reason,width=45).grid(row=0,column=1,padx=14,pady=14)
        def confirm():
            if not reason.get().strip(): return messagebox.showwarning("Cancel Invoice","Enter a cancellation reason",parent=window)
            try: self.client.cancel_invoice(invoice_id,reason.get().strip())
            except Exception as exc: return messagebox.showerror("Cancel Invoice",str(exc),parent=window)
            window.destroy(); self.load_invoices(); self.load_dashboard(); self.load_journal(); self.load_trial()
            messagebox.showinfo("Cancel Invoice","Invoice cancelled and reversing journal entry created")
        tk.Button(window,text="Confirm Cancellation",command=confirm,bg="#8B1E1E",fg="white",border=0,padx=18,pady=7).grid(row=1,column=0,columnspan=2,pady=12)

    def return_open_sales_invoice(self):
        """Sales Invoice screen: return goods of the invoice that is open (2.9.49)."""
        if not getattr(self,"sales_edit_id",None): return messagebox.showwarning("Return","Open the posted invoice first (Find), then press Return.")
        return self.return_selected_invoice(self.sales_edit_id)

    def return_selected_invoice(self,invoice_id=None):
        if invoice_id is None:
            invoice_id=self.selected_invoice_id()
            if invoice_id is None: return
            summary=self.invoice_rows.get(str(invoice_id),{})
        else:
            try: summary=next((r for r in self.client.invoices() if r["id"]==int(invoice_id)),{})
            except Exception as exc: return messagebox.showerror("Return",str(exc))
        if summary.get("status")!="posted":
            return messagebox.showwarning("Return / Credit Note","Only a posted invoice can be returned. Cancellation is a separate action.")
        if summary.get("doc_subtype")=="credit_note":
            return messagebox.showwarning("Return / Credit Note","A credit note cannot itself be returned.")
        try: detail=self.client.invoice_detail(invoice_id)
        except Exception as exc: return messagebox.showerror("Return / Credit Note",str(exc))
        invoice=detail["invoice"]; items=detail.get("items") or []
        return_request_id=str(uuid.uuid4())
        if not items:
            return messagebox.showwarning("Return / Credit Note","This invoice has no item lines, so a quantity-reviewed return cannot be safely created.")
        is_sale=invoice.get("kind")=="sale"; title="Sales Return (goods back)" if is_sale else "Purchase Return (goods back to the supplier)"
        window=tk.Toplevel(self); window.title(title); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        tk.Label(window,text=f"Return against {invoice['invoice_number']} — {invoice.get('party_name') or ''}",
                 bg=LIGHT,font=("Segoe UI",10,"bold")).pack(anchor="w",padx=12,pady=(12,4))
        tk.Label(window,text="Enter quantities to return. Value and VAT are calculated proportionally from the posted lines.\n"
                 "The goods go back into stock (or out to the supplier). No cash is refunded and no payment is allocated.",
                 bg=LIGHT,fg="#5f6b76",justify="left").pack(anchor="w",padx=12,pady=(0,8))
        date_line=tk.Frame(window,bg=LIGHT); date_line.pack(anchor="w",padx=12,pady=4)
        tk.Label(date_line,text="Return date (DD-MM-YYYY)",bg=LIGHT).pack(side="left")
        date_var=tk.StringVar(value=self.fiscal_today()); tk.Entry(date_line,textvariable=date_var,width=14).pack(side="left",padx=7)
        grid=tk.Frame(window,bg=LIGHT); grid.pack(fill="both",expand=True,padx=12,pady=6)
        for col,label in enumerate(("Description","Original Qty","Returned","Available","Return Qty","Line incl. VAT")):
            tk.Label(grid,text=label,bg=NAVY,fg="white",padx=5,pady=4).grid(row=0,column=col,sticky="ew")
        qty_vars={}
        def preview_value(record,qty,available):
            if not available: return 0.0
            ratio=Decimal(str(qty))/Decimal(str(available)); cent=Decimal("0.01")
            fields=(("deductible_subtotal","returned_deductible_subtotal"),
                    ("non_deductible_subtotal","returned_non_deductible_subtotal"),("vat","returned_vat"))
            return float(sum(((Decimal(str(record.get(source) or 0))-Decimal(str(record.get(returned) or 0)))*ratio)
                             .quantize(cent,rounding=ROUND_HALF_UP) for source,returned in fields))
        for index,line in enumerate(items,1):
            original=float(line.get("quantity") or 0); already=float(line.get("returned_quantity") or 0); available=max(0,original-already)
            tk.Label(grid,text=line["description"],bg=LIGHT,anchor="w").grid(row=index,column=0,sticky="w",padx=4,pady=3)
            for col,value in ((1,original),(2,already),(3,available)):
                tk.Label(grid,text=f"{value:g}",bg=LIGHT).grid(row=index,column=col,padx=4,pady=3)
            var=tk.StringVar(value="0"); qty_vars[int(line["id"])]=(var,line,available)
            entry=tk.Entry(grid,textvariable=var,width=10,justify="right"); entry.grid(row=index,column=4,padx=4,pady=3)
            amount=tk.StringVar(value="0.00")
            tk.Label(grid,textvariable=amount,bg=LIGHT,anchor="e").grid(row=index,column=5,sticky="e",padx=4,pady=3)
            def update_amount(*_args,v=var,record=line,limit=available,out=amount):
                try:
                    qty=float(v.get() or 0)
                    if qty<0 or qty>limit: raise ValueError
                    out.set(f"{preview_value(record,qty,limit):,.2f}")
                except (ValueError,ZeroDivisionError): out.set("Review quantity")
            var.trace_add("write",update_amount)
        total_label=tk.StringVar(value="Total return: 0.00 "+str(invoice.get("currency") or ""))
        tk.Label(window,textvariable=total_label,bg=LIGHT,fg=NAVY,font=("Segoe UI",10,"bold")).pack(anchor="e",padx=16,pady=4)
        def update_total(*_args):
            try:
                total=0.0
                for var,line,available in qty_vars.values():
                    qty=float(var.get() or 0)
                    if qty<0 or qty>available: raise ValueError
                    total+=preview_value(line,qty,available)
                total_label.set(f"Total return: {total:,.2f} {invoice.get('currency') or ''}")
            except (ValueError,ZeroDivisionError): total_label.set("Correct quantities to see the credit-note total")
        for var,_,_ in qty_vars.values(): var.trace_add("write",update_total)
        def save_return():
            try:
                parsed_date=formatted_user_date(date_var.get().strip())
                selections=[]
                for item_id,(var,line,available) in qty_vars.items():
                    value=float(var.get().replace(",","") or 0)
                    if value<0 or value>available: raise ValueError(f"{line['description']}: quantity must be from 0 to {available:g}")
                    if value: selections.append({"item_id":item_id,"quantity":str(value)})
                if not selections: raise ValueError("Enter at least one quantity to return")
                if not messagebox.askyesno(title,f"Post the reviewed return against {invoice['invoice_number']}?\n"
                        "A credit note and any applicable stock reversal will be created. No cash refund or payment allocation is created.",parent=window):
                    return
                created=self.client.create_invoice_return(invoice_id,selections,parsed_date,return_request_id)
            except Exception as exc:
                return messagebox.showerror(title,str(exc),parent=window)
            window.destroy(); self.load_invoices(); self.load_dashboard(); self.load_journal(); self.load_trial()
            messagebox.showinfo(title,f"Posted {created['invoice_number']} linked to {invoice['invoice_number']}. "
                              "No cash refund or allocation was created.")
        buttons=tk.Frame(window,bg=LIGHT); buttons.pack(pady=10)
        tk.Button(buttons,text="Post Return / Credit Note",command=save_return,bg=NAVY,fg="white",border=0,padx=16,pady=7).pack(side="left",padx=4)
        tk.Button(buttons,text="Cancel",command=window.destroy,bg="#5f6b76",fg="white",border=0,padx=16,pady=7).pack(side="left",padx=4)

    def approve_selected_invoices(self):
        """2.9.93: post the selected drafts (approval). The program refuses drafts you prepared yourself."""
        ids=[int(i) for i in self.invoice_tree.selection() if str(i).isdigit()]
        if not ids: return messagebox.showwarning("Approve","Select the draft invoices to approve")
        try: result=self.client.approve_invoices(ids)
        except Exception as exc: return messagebox.showerror("Approve",str(exc))
        text=f"{len(result['approved'])} invoice(s) approved and posted."
        if result["skipped"]: text+="\n\nNot approved:\n"+"\n".join(result["skipped"][:15])
        messagebox.showinfo("Approve",text); self.load_invoices(); self.load_journal(); self.load_trial()

    def attach_to_selected_invoice(self):
        invoice_id=self.selected_invoice_id()
        if invoice_id is None: return
        path=filedialog.askopenfilename(filetypes=[("Invoice files","*.pdf *.png *.jpg *.jpeg"),("All files","*.*")])
        if not path: return
        try:
            content=Path(path).read_bytes()
            mime=mimetypes.guess_type(path)[0] or "application/octet-stream"
            self.client.upload_attachment(invoice_id,Path(path).name,mime,content)
        except Exception as exc: return messagebox.showerror("Attachments",str(exc))
        self.load_invoices(); messagebox.showinfo("Attachments","File attached successfully")

    def show_selected_attachments(self):
        invoice_id=self.selected_invoice_id()
        if invoice_id is None: return
        try: items=self.client.attachments(invoice_id)
        except Exception as exc: return messagebox.showerror("Attachments",str(exc))
        # 2.9.97: double-click a document to see it (PDF pages / image) inside the program
        from desktop_attachments import attachments_window
        number=(getattr(self,"invoice_rows",{}).get(str(invoice_id)) or {}).get("invoice_number") or f"invoice {invoice_id}"
        attachments_window(self,number,items,lambda record:self.client.download_attachment(record["id"])["content"])

    def show_invoice_history(self):
        invoice_id=self.selected_invoice_id()
        if invoice_id is None: return
        try: items=self.client.invoice_history(invoice_id)
        except Exception as exc: return messagebox.showerror("History",str(exc))
        window=tk.Toplevel(self); window.title("Invoice Modification History"); self.fit_dialog(window,760,380)
        tree=ttk.Treeview(window,columns=("date","user","action","details"),show="headings")
        for key,label,width in (("date","Date",170),("user","User",100),("action","Action",100),("details","Details",370)):
            tree.heading(key,text=label); tree.column(key,width=width)
        for item in items: tree.insert("","end",values=(item["created_at"][:19],item.get("username") or "",item["action"],item.get("details") or ""))
        tree.pack(fill="both",expand=True,padx=10,pady=10)

    def export_selected_invoice_pdf(self):
        invoice_id=self.selected_invoice_id()
        if invoice_id is None: return
        try: detail=self.client.invoice_detail(invoice_id)
        except Exception as exc: return messagebox.showerror("Invoice PDF",str(exc))
        invoice=detail["invoice"]; path=filedialog.asksaveasfilename(defaultextension=".pdf",initialfile=f'Invoice_{invoice["invoice_number"]}.pdf',filetypes=[("PDF document","*.pdf")])
        if not path: return
        try:
            company=self.client.settings(); custom_logo=company.get("company_logo")
            logo=Path(custom_logo) if custom_logo and Path(custom_logo).exists() else resource_path("assets/Saber_for_Audit_logo.png")
            export_invoice_pdf(path,invoice,detail["items"],logo,company)
        except Exception as exc: return messagebox.showerror("Invoice PDF",str(exc))
        messagebox.showinfo("Invoice PDF",f"Saved successfully:\n{path}")

    def confirm_invoice_data_saved(self):
        try:
            rows=self.client.invoices()
        except Exception as exc:
            return messagebox.showerror("Invoices",str(exc))
        self.load_invoices()
        messagebox.showinfo("Invoices",f"{len(rows)} invoice rows are saved in the shared database")

    def export_invoices_excel(self):
        rows=list(getattr(self,"invoice_rows",{}).values())
        if not rows: return messagebox.showwarning("Invoices","No invoice data to export")
        headers=["Invoice Number","Date","Customer / Supplier","Type","Currency","Before VAT Deductible","Before VAT Non-Deductible","VAT","Total","Payment Method","Paid Amount","Debit","Credit",
                 "Supplier Account","VAT Account","Expense Account","Expense without VAT","Status","Source Row"]
        values=[[r["invoice_number"],r["invoice_date"],r["party_name"],r.get("entry_type") or r["kind"],r["currency"],r.get("deductible_subtotal",r["subtotal"]),r.get("non_deductible_subtotal",0),
                 r["vat"],r["total"],r.get("payment_method") or "",r.get("amount_paid") or 0,r["debit"],r["credit"],r["supplier_account"],r["vat_account"],
                         r["expense_account"],r.get("expense_no_vat_account","601100001"),r["status"],r["source_row"]] for r in rows]
        path=filedialog.asksaveasfilename(defaultextension=".xlsx",filetypes=[("Excel workbook","*.xlsx")],
                                          initialfile="Nanza_Accounting_Invoices.xlsx")
        if not path: return
        try:
            export_excel(path,"Nanza Accounting - Invoices",headers,values)
            messagebox.showinfo("Invoices",f"Saved successfully:\n{path}")
        except Exception as exc:
            messagebox.showerror("Invoices",str(exc))

    def add_invoice_row(self):
        window=tk.Toplevel(self); window.title("Add Invoice Row"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        self.fit_dialog(window,820,620,480,360)
        outer,form=self.scrollable_page(window); outer.pack(fill="both",expand=True)
        defaults={"invoice_number":"","invoice_date":datetime.now().strftime("%d-%m-%Y"),"party_name":"",
                  "kind":"purchases","currency":"USD","deductible_subtotal":"0","non_deductible_subtotal":"0","vat":"0","total":"0",
                  "supplier_account":"4011","vat_account":"442660000","expense_account":"601100000",
                  "expense_no_vat_account":"601100001",
                  "description":"","branch":"Head Office","due_date":"","payment_method":"Cash","amount_paid":"0","cash_account":""}
        variables={key:tk.StringVar(value=value) for key,value in defaults.items()}
        fields=[("Invoice Number","invoice_number"),("Date (DD-MM-YYYY)","invoice_date"),("Customer / Supplier","party_name"),
                ("Description","description"),("Branch","branch"),("Type","kind"),("Currency","currency"),("Before VAT Deductible","deductible_subtotal"),
                        ("Before VAT Non-Deductible","non_deductible_subtotal"),("VAT","vat"),("Total","total"),
                ("Supplier Account (C - Credit)","supplier_account"),("VAT Account (D - Debit)","vat_account"),("Expense Account (D - Debit)",
                        "expense_account"),("Expense without VAT","expense_no_vat_account"),
                ("Due Date (DD-MM-YYYY)","due_date"),("Payment Method","payment_method"),("Paid Amount","amount_paid"),("Cash / Bank Account (paid)","cash_account")]
        for index,(label,key) in enumerate(fields):
            rr=index//2; cc=(index%2)*2
            tk.Label(form,text=label,bg=LIGHT).grid(row=rr,column=cc,sticky="w",padx=(14,5),pady=7)
            if key=="kind": widget=ttk.Combobox(form,textvariable=variables[key],values=["assets","expenses","purchases","sales"],state="readonly",width=24)
            elif key=="currency": widget=ttk.Combobox(form,textvariable=variables[key],values=self.currency_codes,state="readonly",width=24)
            elif key=="payment_method": widget=ttk.Combobox(form,textvariable=variables[key],values=["On Account (Not Cash)","Cash","Bank Transfer","Cheque","Card","Other"],state="readonly",width=24)
            elif key=="cash_account": widget=self.account_search_box(form,variables[key],24)
            elif key=="branch": widget=self.branch_selector(form,variables[key],24,False)
            elif key in ("supplier_account","vat_account","expense_account","expense_no_vat_account"): widget=self.account_search_box(form,variables[key],24)
            elif key in ("invoice_date","due_date"): widget=self.date_entry(form,variables[key],27)
            else: widget=tk.Entry(form,textvariable=variables[key],width=27)
            widget.grid(row=rr,column=cc+1,padx=(5,14),pady=7)
        self._bind_ai_account_suggestion(form, variables["description"], variables["expense_account"],
                                         row=(len(fields)+1)//2, columnspan=4, kind_variable=variables["kind"])
        def save():
            values={key:var.get().strip() for key,var in variables.items()}
            try:
                values["invoice_date"]=formatted_user_date(values["invoice_date"])
                if values.get("due_date"): values["due_date"]=formatted_user_date(values["due_date"])
                deductible=float(values["deductible_subtotal"]); non_deductible=float(values["non_deductible_subtotal"]); subtotal=deductible+non_deductible; \
                    vat=float(values["vat"]); total=float(values["total"])
            except ValueError:
                return messagebox.showwarning("Invoices","Check the date and amounts",parent=window)
            if not values["party_name"] or abs(subtotal+vat-total)>0.005:
                return messagebox.showwarning("Invoices","Enter customer/supplier; Total must equal Before VAT plus VAT",parent=window)
            item={"description":"Manual invoice row","quantity":1,"unit_price":deductible,"deductible_subtotal":deductible,"non_deductible_subtotal":non_deductible,
                  "vat_rate":0 if deductible==0 else vat*100/deductible,"vat":vat,"total":total}
            try: self.client.create_manual_invoice(values,[item])
            except Exception as exc: return messagebox.showerror("Invoices",str(exc),parent=window)
            window.destroy(); self.load_invoices(); self.load_dashboard(); self.load_journal(); self.load_trial(); self.load_statement_parties()
            messagebox.showinfo("Invoices","Invoice row added successfully")
        tk.Button(form,text="Save Invoice",command=save,bg=GOLD,fg=NAVY,font=("Segoe UI",10,"bold"),border=0,padx=24,pady=8).grid(row=11,column=0,columnspan=4,pady=16)

    def add_item_to_selected_invoice(self):
        selected=self.invoice_tree.selection()
        if not selected: return messagebox.showwarning("Invoices","Select one invoice row")
        invoice_id=int(selected[0]); window=tk.Toplevel(self); window.title("Add Item to Invoice"); window.configure(bg=LIGHT); window.transient(self); window.grab_set(); self.fit_dialog(window,
                520,420,360,300)
        defaults={"description":"","quantity":"1","unit_price":"0","subtotal":"0","vat_rate":f"{vat_rate(self):g}","vat":"0"}
        variables={key:tk.StringVar(value=value) for key,value in defaults.items()}
        fields=[("Description","description"),("Quantity","quantity"),("Unit Price","unit_price"),
                ("Before VAT","subtotal"),("VAT %","vat_rate"),("VAT Amount","vat")]
        for index,(label,key) in enumerate(fields):
            tk.Label(window,text=label,bg=LIGHT).grid(row=index,column=0,sticky="w",padx=14,pady=6)
            tk.Entry(window,textvariable=variables[key],width=30).grid(row=index,column=1,padx=14,pady=6)
        invoice_row = self.invoice_rows.get(str(invoice_id), {})
        item_kind = tk.StringVar(master=window, value=invoice_row.get("kind") or "")
        self._bind_ai_account_suggestion(window, variables["description"], row=len(fields), columnspan=2,
                                         kind_variable=item_kind)
        def save():
            item={key:var.get().strip() for key,var in variables.items()}
            try:
                if not item["description"]: raise ValueError
                for key in ("quantity","unit_price","subtotal","vat_rate","vat"): float(item[key])
            except ValueError:
                return messagebox.showwarning("Invoices","Enter a description and valid amounts",parent=window)
            try: self.client.add_invoice_item(invoice_id,item)
            except Exception as exc: return messagebox.showerror("Invoices",str(exc),parent=window)
            window.destroy(); self.load_invoices(); self.load_dashboard(); self.load_journal(); self.load_trial()
            messagebox.showinfo("Invoices","Item added and invoice totals updated")
        tk.Button(window,text="Add Item",command=save,bg=GOLD,fg=NAVY,font=("Segoe UI",10,"bold"),border=0,padx=24,pady=8).grid(row=7,column=0,columnspan=2,pady=14)
