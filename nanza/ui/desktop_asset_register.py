"""Fixed assets page of Purchases & Expenses (moved out of desktop_stage3.py in 2.9.42, unchanged)."""
from __future__ import annotations
import logging
from desktop_common import add_search_bar  # 2.9.78

from desktop_stage3_common import (  # 2.9.102: the names this module uses (no more 'import *')
    asset_pdf_details, export_excel, export_pdf, filedialog, GOLD, LIGHT, messagebox, MUTED, NAVY, os, Path,
    read_invoice_pdf, run_with_progress, RED, subprocess, sys, tempfile, tk, ttk
)
from desktop_stage3_common import _dd, _num


class AssetRegisterMixin:
    def build_assets_page(self,page):
        """Tab 2 - Asset Data Entry: choose the asset account (from tab 1), enter the purchase, save.
        Rates and accounts come from the asset account; the depreciation table is in tab 3."""
        self.asset_edit_id=None
        defaults={"asset_code":"","name":"","acquired_on":self.fiscal_today(),"start_on":self.fiscal_today(),
                  "currency":"USD","cost":"","residual":"0","useful_months":"60","frequency":"monthly",
                  "asset_account":"","depreciation_account":"","accumulated_account":"","invoice_id":"","opening_date":""}
        self.asset_fields={key:tk.StringVar(value=value) for key,value in defaults.items()}
        self.asset_rate=tk.StringVar(value="")
        form=tk.LabelFrame(page,text="Asset",bg=LIGHT,padx=10,pady=6); form.pack(fill="x",padx=8,pady=(6,0))
        layout=[[("Asset code","asset_code",14),("Description","name",34),("Currency","currency",8)],
                [("Purchase date","acquired_on",12),("Purchase value","cost",16),("Residual value","residual",12)],
                [("Depreciation start","start_on",12),("Purchase invoice No./ID","invoice_id",16),("Booked before Nanza up to","opening_date",12)]]
        for row,items in enumerate(layout):
            for index,(label,key,width) in enumerate(items):
                if not key: continue
                column=index*2
                tk.Label(form,text=label,bg=LIGHT).grid(row=row,column=column,sticky="w",padx=4,pady=4)
                if key in ("acquired_on","start_on"): widget=self.date_entry(form,self.asset_fields[key],width)
                elif key=="currency": widget=ttk.Combobox(form,textvariable=self.asset_fields[key],state="readonly",width=width,values=getattr(self,"currency_codes",None) or ["USD","LBP","EUR","AED"])
                else: widget=tk.Entry(form,textvariable=self.asset_fields[key],width=width)
                widget.grid(row=row,column=column+1,sticky="w",padx=(2,14),pady=4)
        rules=tk.LabelFrame(page,text="Depreciation (filled from the asset account in tab 1 - change only if needed)",bg=LIGHT,padx=10,pady=4); rules.pack(fill="x",padx=8,pady=(6,0))
        tk.Label(rules,text="Rate % / year",bg=LIGHT).grid(row=0,column=0,sticky="w",padx=4)
        tk.Entry(rules,textvariable=self.asset_rate,width=8).grid(row=0,column=1,sticky="w",padx=(2,14))
        tk.Label(rules,text="Useful life (months)",bg=LIGHT).grid(row=0,column=2,sticky="w",padx=4)
        tk.Entry(rules,textvariable=self.asset_fields["useful_months"],width=8).grid(row=0,column=3,sticky="w",padx=(2,14))
        tk.Label(rules,text="Post",bg=LIGHT).grid(row=0,column=4,sticky="w",padx=4)
        ttk.Combobox(rules,textvariable=self.asset_fields["frequency"],state="readonly",width=9,values=["monthly","yearly"]).grid(row=0,column=5,sticky="w",padx=(2,14))
        for column,(label,key) in enumerate((("Asset account","asset_account"),("Expense account","depreciation_account"),("Accumulated account","accumulated_account"))):
            tk.Label(rules,text=label,bg=LIGHT).grid(row=1,column=column*2,sticky="w",padx=4,pady=(4,0))
            self.account_search_box(rules,self.asset_fields[key],14).grid(row=1,column=column*2+1,sticky="w",padx=(2,14),pady=(4,0))
        self.asset_rate.trace_add("write",self.asset_rate_changed)
        for key in ("cost","residual"):
            self.asset_fields[key].trace_add("write",self.asset_rate_changed)
        actions=tk.Frame(page,bg=LIGHT); actions.pack(fill="x",padx=8,pady=6)
        tk.Button(actions,text="Save",command=self.save_asset_entry,bg=GOLD,fg=NAVY,border=0,padx=20,pady=6,font=("Segoe UI",9,"bold")).pack(side="left",padx=3)
        for label,command in (("New",self.new_asset),("Delete",self.delete_asset_entry)):
            self.action_button(actions,label,command).pack(side="left",padx=3)
        tk.Label(actions,text="  |  ",bg=LIGHT,fg=MUTED).pack(side="left")
        for label,command in (("Fill from PDF",self.choose_asset_pdf),("PDF Attachments",self.asset_attachments_window),
                              ("Schedule of this asset",self.show_asset_schedule),("Record Asset Purchase",self.open_asset_purchase),
                              ("Dispose / Scrap",self.dispose_asset_entry),("Register vs Ledger",self.show_asset_reconcile)):  # 2.9.132
            self.action_button(actions,label,command).pack(side="left",padx=3)
        lists=tk.LabelFrame(page,text="Asset register - click a line to edit it",bg=LIGHT,padx=4,pady=4); lists.pack(fill="both",expand=True,padx=8,pady=(0,6))
        self.asset_list=ttk.Treeview(lists,columns=("code","name","purchase","cost","currency","previous","yearly","cumulative","net"),show="headings")
        for key,title,width in (("code","Asset",90),("name","Description",190),("purchase","Purchase date",100),("cost","Purchase value",110),("currency","Currency",70),
                                ("previous","Old deprec.",100),("yearly","This year",100),("cumulative","Total deprec.",110),("net","Net value",110)):
            self.asset_list.heading(key,text=title); self.asset_list.column(key,width=width,stretch=key=="name",anchor="w" if key in ("code","name","purchase","currency") else "e")
        self.asset_list.pack(fill="both",expand=True); self.asset_list.bind("<<TreeviewSelect>>",lambda _e:self.select_asset()); add_search_bar(self.asset_list)  # 2.9.78
        self.asset_schedule_tree=None
        self.load_assets()

    def show_asset_schedule(self):
        if not self.asset_edit_id: return messagebox.showwarning("Assets","Select an asset in the register first")
        window=tk.Toplevel(self); window.title("Depreciation schedule of the selected asset"); window.geometry("720x460"); window.configure(bg=LIGHT)
        tree=ttk.Treeview(window,columns=("date","amount","accumulated","net","status"),show="headings")
        for key,title,width in (("date","Period end",120),("amount","Depreciation",130),("accumulated","Accumulated",130),("net","Net book value",130),("status","Status",90)):
            tree.heading(key,text=title); tree.column(key,width=width,anchor="w" if key in ("date","status") else "e")
        tree.pack(fill="both",expand=True,padx=8,pady=8); self.asset_schedule_tree=tree
        bar=tk.Frame(window,bg=LIGHT); bar.pack(fill="x",padx=8,pady=(0,8))
        self.action_button(bar,"Post selected period",self.post_asset_period).pack(side="left",padx=3)
        tk.Label(bar,text="Monthly posting by account is in tab 3.",bg=LIGHT,fg=MUTED).pack(side="left",padx=10)
        window.bind("<Destroy>",lambda e:setattr(self,"asset_schedule_tree",None) if e.widget is window else None)
        self.select_asset()

    def new_asset(self):
        self.asset_edit_id=None
        self.asset_rate.set("")
        for key,var in self.asset_fields.items():
            var.set({"acquired_on":self.fiscal_today(),"start_on":self.fiscal_today(),"currency":"USD","residual":"0",
                     "useful_months":"60","frequency":"monthly"}.get(key,""))
        if getattr(self,"asset_schedule_tree",None) is not None: self.asset_schedule_tree.delete(*self.asset_schedule_tree.get_children())

    def choose_asset_pdf(self):
        path=filedialog.askopenfilename(filetypes=[("PDF asset invoice","*.pdf")])
        if not path: return
        try:
            size=Path(path).stat().st_size
            if not size or size>15*1024*1024: raise ValueError("Choose a non-empty PDF smaller than 15 MB")
            from desktop_stage3_common import prepare_pdf_reading; prepare_pdf_reading(self)  # 2.9.85
        except Exception as exc:
            return messagebox.showerror("Asset PDF",f"Could not read the PDF: {exc}")
        return run_with_progress(self, "Asset PDF", lambda _progress, _cancel: read_invoice_pdf(path, cancel=_cancel),
                                 lambda data: AssetRegisterMixin._apply_asset_pdf(self, path, data))

    def _apply_asset_pdf(self, path, data):
        from desktop_stage3_common import review_handwriting
        data = review_handwriting(self, path, data)
        if data is None: return
        details=asset_pdf_details(data)
        self.new_asset()
        for key in ("name","acquired_on","start_on","currency","cost"):
            self.asset_fields[key].set("")
        for key in ("name","acquired_on","currency","cost"):
            value=details.get(key)
            if value not in (None,""):
                self.asset_fields[key].set(f"{value:.2f}" if key=="cost" else str(value))
        if details.get("acquired_on"):
            self.asset_fields["start_on"].set(details["acquired_on"])
        self.review_asset_pdf(path,data.get("notes",""),on_created=lambda created:self.offer_asset_purchase(created,data,path))

    def offer_asset_purchase(self,asset,data,path):
        """2.9.87: the register item alone posts nothing - the books would miss the asset. Offer to book the supplier's
        invoice read from the same PDF (Dr asset account + VAT / Cr supplier) and link it to the register item."""
        if asset.get("invoice_id") or asset.get("_already_registered"): return None
        cost=data.get("subtotal") or data.get("acquisition_cost"); vat=data.get("vat") or 0; party=(data.get("party_name") or "").strip()
        if not cost or not party: return None
        account=str(asset.get("asset_account") or "").split(" - ",1)[0]; total=round(float(cost)+float(vat),2)
        if not messagebox.askyesno("Book the asset purchase",
                f"The register item does not post an entry. Book the supplier's invoice now?\n\n"
                f"{data.get('invoice_number') or ''}  {data.get('invoice_date') or ''}  {party}\n"
                f"Dr {account} (asset)  {float(cost):,.2f}\nDr deductible VAT  {float(vat):,.2f}\nCr {party}  {total:,.2f} {data.get('currency') or asset.get('currency')}\n\n"
                "Choose No if this invoice is already entered in Purchases."): return None
        rate=round(float(vat)/float(cost)*100,4) if cost else 0
        try:
            invoice_id=self.client.create_manual_invoice({"invoice_number":data.get("invoice_number") or "","invoice_date":data.get("invoice_date") or asset.get("acquired_on"),
                "party_name":party,"kind":"assets","currency":data.get("currency") or asset.get("currency") or "USD","status":"posted","source_file":Path(path).name,
                "expense_account":account,"expense_no_vat_account":account},
                [{"description":asset.get("name") or "Fixed asset","quantity":1,"unit_price":float(cost),"deductible_subtotal":float(cost),"vat_rate":rate,"vat":float(vat)}])["invoice_id"]
            try: self.client.upload_attachment(invoice_id,Path(path).name,"application/pdf",Path(path).read_bytes())
            except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
            fields={k:asset.get(k) for k in ("asset_code","name","acquired_on","start_on","currency","cost","residual","useful_months","frequency",
                    "asset_account","depreciation_account","accumulated_account","annual_rate","opening_date")}
            fields.update(acquired_on=_dd(fields["acquired_on"]),start_on=_dd(fields["start_on"]),
                    opening_date=_dd(fields.get("opening_date")) if fields.get("opening_date") else "",invoice_id=invoice_id)
            try: self.client.save_asset(fields,asset["id"])
            except (RuntimeError, OSError, ValueError) as exc:  # 2.9.119: the invoice is booked; the missing link is said
                return messagebox.showwarning("Book the asset purchase",f"Purchase booked, but not linked to asset {asset.get('asset_code')}: {exc}")
        except Exception as exc:
            return messagebox.showerror("Book the asset purchase",f"The register item is saved, but the invoice was not booked: {exc}\nRecord it in Purchases (type Assets).")
        messagebox.showinfo("Book the asset purchase",f"Purchase booked and linked to asset {asset.get('asset_code')}."); self.load_assets()
        return invoice_id

    def review_asset_pdf(self,path,parser_notes="",on_created=None):
        """Editable, explicit review of all register-defining fields before creation."""
        window=tk.Toplevel(self); window.title("Review PDF fixed asset"); window.configure(bg=LIGHT)
        window.transient(self)
        tk.Label(window,text="Review asset details before creating the register item",
                 bg=LIGHT,fg=NAVY,font=("Segoe UI",12,"bold")).pack(anchor="w",padx=12,pady=(10,4))
        tk.Label(window,text="PDF values are suggestions only. Verify the asset code, class-2 cost account, "
                 "depreciation and accumulated accounts, and enter a rate you have independently verified. "
                 "No Lebanese legal rate is assumed.",bg=LIGHT,fg=RED,wraplength=690,justify="left").pack(fill="x",padx=12,pady=4)
        tk.Label(window,text=f"{Path(path).name} — {parser_notes or 'Review extracted fields'}",
                 bg=LIGHT,fg=MUTED,wraplength=690,justify="left").pack(fill="x",padx=12,pady=4)
        fields=tk.Frame(window,bg=LIGHT); fields.pack(fill="x",padx=12,pady=4)
        prompts=(("Asset code","asset_code"),("Asset name","name"),("Purchase date","acquired_on"),
                 ("Currency","currency"),("Acquisition cost","cost"),("Class-2 asset account","asset_account"),
                 ("Depreciation expense account","depreciation_account"),
                 ("Accumulated depreciation account","accumulated_account"),("Annual rate % (review-required)","rate"))
        for row,(label,key) in enumerate(prompts):
            tk.Label(fields,text=label,bg=LIGHT).grid(row=row,column=0,sticky="w",padx=4,pady=3)
            if key in ("asset_account","depreciation_account","accumulated_account"):
                widget=self.account_search_box(fields,self.asset_fields[key],32)
            elif key=="currency":
                widget=ttk.Combobox(fields,textvariable=self.asset_fields[key],state="readonly",width=28,
                                    values=["USD","LBP","EUR","AED"])
            elif key=="rate":
                widget=tk.Entry(fields,textvariable=self.asset_rate,width=31)
            else:
                widget=tk.Entry(fields,textvariable=self.asset_fields[key],width=34)
            widget.grid(row=row,column=1,sticky="ew",padx=5,pady=3)
        fields.grid_columnconfigure(1,weight=1)
        agreed=tk.BooleanVar(value=False)
        tk.Checkbutton(window,text="I reviewed and verified the asset classification, all three accounts, and annual rate.",
                       variable=agreed,bg=LIGHT,fg=NAVY,wraplength=680,justify="left").pack(anchor="w",padx=12,pady=7)
        tk.Label(window,text="The source PDF will be saved as an attachment to this register item. "
                 "Creating this register item does not post a journal entry or stock movement.",
                 bg=LIGHT,fg=MUTED,wraplength=690,justify="left").pack(fill="x",padx=12,pady=3)
        controls=tk.Frame(window,bg=LIGHT); controls.pack(fill="x",padx=12,pady=(4,10))
        def create():
            if not agreed.get():
                return messagebox.showwarning("Review required","Confirm that you reviewed the accounts and annual rate.",parent=window)
            created=self.save_asset_entry(review_confirmed=True)
            if created:
                asset_id=created["id"]
                was_duplicate=bool(created.pop("_already_registered",False))
                window.destroy()
                try:
                    self.upload_asset_pdf(asset_id,path)
                except Exception as exc:
                    if on_created:
                        try: on_created(created)
                        except Exception as callback_exc:
                            messagebox.showwarning("Asset saved",f"Register item saved, but preview refresh failed: {callback_exc}")
                    messagebox.showwarning("Asset saved; PDF attachment failed",
                        f"Asset {created['asset_code']} is SAVED in the register, but the PDF attachment is not confirmed: {exc}\n"
                        "Select this asset and use PDF Attachments → Attach / Retry PDF. That action retries the attachment only; "
                        "it will not create an asset, invoice, journal entry, or stock movement.")
                    return
                if on_created:
                    try: on_created(created)
                    except Exception as exc:
                        messagebox.showwarning("Asset saved",f"Asset and PDF attachment were saved, but preview refresh failed: {exc}")
                action="already existed in the register" if was_duplicate else "was added to the fixed-asset register"
                messagebox.showinfo("Asset PDF",
                    f"Asset {created['asset_code']} {action}; its schedule is visible and the source PDF is attached.\n"
                    "No journal entry or stock movement was posted.")
        self.action_button(controls,"Create register item",create).pack(side="right",padx=4)
        self.action_button(controls,"Cancel",window.destroy).pack(side="right",padx=4)
        window.grab_set()
        self.fit_dialog(window,760,650,min_width=600,min_height=520)

    def load_assets(self):
        try: self.asset_rows=self.client.fixed_assets()
        except Exception as exc: return messagebox.showerror("Assets",str(exc))
        self.asset_list.delete(*self.asset_list.get_children())
        year=str(self.current_fiscal_year)
        for asset in self.asset_rows:
            try: periods=self.client.asset_schedule(asset["id"])
            except Exception as exc: return messagebox.showerror("Assets",str(exc))
            previous=sum(float(p["amount"]) for p in periods if p["period_end"][:4]<year)
            yearly=sum(float(p["amount"]) for p in periods if p["period_end"][:4]==year)
            cost=float(asset["cost"]); accumulated=min(cost,previous+yearly)
            self.asset_list.insert("","end",iid=str(asset["id"]),values=(asset["asset_code"],asset["name"],_dd(asset["acquired_on"]),
                f"{cost:,.2f}",asset["currency"],f"{previous:,.2f}",f"{yearly:,.2f}",f"{accumulated:,.2f}",f"{max(0,cost-accumulated):,.2f}"))

    def show_asset_rollforward(self):
        year=int(self.current_fiscal_year)
        try: report=self.client.asset_rollforward(year)
        except Exception as exc: return messagebox.showerror("Fixed Asset Rollforward",str(exc))
        window=tk.Toplevel(self); window.title(f"Fixed Asset Register & Depreciation Rollforward — {year}")
        window.configure(bg=LIGHT); window.transient(self)
        title=f"Fixed Asset Register & Depreciation Rollforward — {year}"
        tk.Label(window,text=title,bg=LIGHT,fg=NAVY,font=("Segoe UI",14,"bold")).pack(anchor="w",padx=14,pady=(12,4))
        tk.Label(window,text="Posted depreciation is shown separately from the unposted schedule; amounts remain in each asset's currency.",
                 bg=LIGHT,fg=MUTED,wraplength=1250,justify="left").pack(anchor="w",padx=14,pady=(0,8))
        headers=("Asset code","Description","Currency","Opening cost","Additions","Disposals (cost)","Closing cost","Opening accumulated depreciation",
                 "Depreciation posted","Disposals (depreciation)","Closing accumulated depreciation","Closing net book value","Unposted schedule")  # 2.9.132
        keys=("asset_code","name","currency","opening_cost","additions","disposals_cost","closing_cost","opening_accumulated","depreciation_posted",
              "disposals_accumulated","closing_accumulated","closing_net_book_value","unposted_scheduled")
        container=tk.Frame(window,bg=LIGHT); container.pack(fill="both",expand=True,padx=12,pady=4)
        tree=ttk.Treeview(container,columns=keys,show="headings")
        vertical=ttk.Scrollbar(container,orient="vertical",command=tree.yview)
        horizontal=ttk.Scrollbar(container,orient="horizontal",command=tree.xview)
        tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        for key,label in zip(keys,headers):
            tree.heading(key,text=label)
            tree.column(key,width=100 if key in ("currency","asset_code") else 145,
                        minwidth=82,stretch=key in ("name",))
        tree.grid(row=0,column=0,sticky="nsew"); vertical.grid(row=0,column=1,sticky="ns")
        horizontal.grid(row=1,column=0,sticky="ew")
        container.grid_rowconfigure(0,weight=1); container.grid_columnconfigure(0,weight=1)
        for index,row in enumerate(report["items"]):
            values=tuple(row.get(key,"") if key in ("asset_code","name","currency") else f'{float(row.get(key) or 0):,.2f}' for key in keys)
            tree.insert("","end",iid=f"asset-{index}",values=values)
        total_lines=[]
        for currency,amounts in report["totals"].items():
            total_lines.append(f'{currency}: Opening cost {float(amounts["opening_cost"]):,.2f} · Additions {float(amounts["additions"]):,.2f} · '
                f'Depreciation posted {float(amounts["depreciation_posted"]):,.2f} · Closing net book value {float(amounts["closing_net_book_value"]):,.2f} · '
                f'Unposted schedule {float(amounts["unposted_scheduled"]):,.2f}')
        tk.Label(window,text="\n".join(total_lines) if total_lines else "No active fixed assets for this year.",
                 bg=LIGHT,fg=NAVY,wraplength=1350,justify="left",anchor="w").pack(fill="x",padx=14,pady=8)
        controls=tk.Frame(window,bg=LIGHT); controls.pack(fill="x",padx=12,pady=(0,10))
        def save_report(kind):
            suffix=".xlsx" if kind=="Excel" else ".pdf"
            path=filedialog.asksaveasfilename(parent=window,defaultextension=suffix,
                filetypes=[("Excel workbook","*.xlsx")] if kind=="Excel" else [("PDF report","*.pdf")],
                initialfile=f"Fixed_Asset_Rollforward_{year}{suffix}")
            if not path: return
            try:
                rows=[[row.get(key,"") if key in ("asset_code","name","currency") else float(row.get(key) or 0) for key in keys]
                      for row in report["items"]]
                (export_excel if kind=="Excel" else export_pdf)(path,title,headers,rows)
            except Exception as exc: return messagebox.showerror("Fixed Asset Rollforward",str(exc),parent=window)
            messagebox.showinfo("Fixed Asset Rollforward",f"Report saved to:\n{path}",parent=window)
        self.action_button(controls,"Export Excel",lambda:save_report("Excel")).pack(side="left",padx=4)
        self.action_button(controls,"Export PDF",lambda:save_report("PDF")).pack(side="left",padx=4)
        self.action_button(controls,"Close",window.destroy).pack(side="right",padx=4)
        self.fit_dialog(window,1450,680,min_width=920,min_height=460)

    def select_asset(self):
        selected=self.asset_list.selection()
        if not selected: return
        self.asset_edit_id=int(selected[0]); asset=next(row for row in self.asset_rows if row["id"]==self.asset_edit_id)
        for key,var in self.asset_fields.items():
            value=asset.get(key) or ""
            var.set(_dd(value) if key in ("acquired_on","start_on","opening_date") and value else str(value))
        self.asset_rate.set(str(asset.get("annual_rate") or ""))
        tree=getattr(self,"asset_schedule_tree",None)
        if tree is None or not tree.winfo_exists(): return
        tree.delete(*tree.get_children())
        try: rows=self.client.asset_schedule(self.asset_edit_id)
        except Exception as exc: return messagebox.showerror("Assets",str(exc))
        for row in rows: tree.insert("","end",iid=row["period_end"],values=(_dd(row["period_end"]),row["amount"],row["accumulated"],row["net_book_value"],"Posted" if row["posted"] else "Draft"))

    def upload_asset_pdf(self,asset_id,path):
        path=Path(path)
        size=path.stat().st_size
        if not size or size>15*1024*1024:
            raise ValueError("Choose a non-empty PDF smaller than 15 MB")
        if path.suffix.lower()!=".pdf":
            raise ValueError("Choose a PDF file")
        content=path.read_bytes()
        if not content.startswith(b"%PDF-"):
            raise ValueError("The selected file is not a valid PDF")
        return self.client.upload_asset_attachment(asset_id,path.name,"application/pdf",content)

    def asset_attachments_window(self):
        if not self.asset_edit_id:
            return messagebox.showwarning("Asset PDF","Select a fixed asset first")
        asset=next((row for row in self.asset_rows if row["id"]==self.asset_edit_id),None)
        if not asset: return messagebox.showwarning("Asset PDF","Select a fixed asset first")
        asset_id=asset["id"]
        window=tk.Toplevel(self); window.title(f"PDF Attachments — {asset['asset_code']}"); window.configure(bg=LIGHT)
        window.transient(self)
        tk.Label(window,text=f"Source PDFs for {asset['asset_code']} — {asset['name']}",
                 bg=LIGHT,fg=NAVY,font=("Segoe UI",11,"bold")).pack(anchor="w",padx=10,pady=(10,3))
        tree=ttk.Treeview(window,columns=("file","size","uploaded","hash"),show="headings",height=8)
        for key,label,width in (("file","File",260),("size","Size",80),("uploaded","Uploaded",145),("hash","Content hash",230)):
            tree.heading(key,text=label); tree.column(key,width=width,stretch=key=="file")
        tree.pack(fill="both",expand=True,padx=8,pady=6)
        records=[]
        def refresh():
            try: records[:]=self.client.asset_attachments(asset_id)
            except Exception as exc:
                messagebox.showerror("Asset PDF",str(exc),parent=window); return
            tree.delete(*tree.get_children())
            for record in records:
                tree.insert("","end",iid=str(record["id"]),values=(record["file_name"],
                    f'{record["size"]/1024:,.0f} KB',str(record["uploaded_at"])[:16],record.get("sha256","")[:20]))
        def attach():
            path=filedialog.askopenfilename(parent=window,filetypes=[("PDF files","*.pdf")])
            if not path: return
            try: result=self.upload_asset_pdf(asset_id,path)
            except Exception as exc:
                return messagebox.showwarning("Asset saved; retry PDF attachment",
                    f"Asset {asset['asset_code']} remains SAVED; attachment was not confirmed: {exc}\n"
                    "You can retry this PDF attachment here. The register and accounting postings will not be changed.",parent=window)
            refresh()
            messagebox.showinfo("Asset PDF","PDF attachment saved" + (" (identical content already attached)." if result.get("duplicate") else ".")
                                + "\nThe register was not recreated and no posting was made.",parent=window)
        def selected_record():
            selected=tree.selection()
            return next((item for item in records if str(item["id"])==selected[0]),None) if selected else None
        def download(open_after=False):
            record=selected_record()
            if not record: return messagebox.showwarning("Asset PDF","Select an attachment first",parent=window)
            try: content=self.client.download_asset_attachment(record["id"])["content"]
            except Exception as exc: return messagebox.showerror("Asset PDF",str(exc),parent=window)
            if open_after:
                try:
                    with tempfile.NamedTemporaryFile(prefix="saber-asset-",suffix=".pdf",delete=False) as temp:
                        temp.write(content); saved=temp.name
                    if hasattr(os,"startfile"): os.startfile(saved)
                    else: subprocess.Popen(["open" if sys.platform=="darwin" else "xdg-open",saved])
                except Exception as exc: return messagebox.showerror("Open PDF",f"Could not open the PDF: {exc}",parent=window)
            else:
                target=filedialog.asksaveasfilename(parent=window,initialfile=Path(record["file_name"]).name,
                    defaultextension=".pdf",filetypes=[("PDF files","*.pdf")])
                if not target: return
                try: Path(target).write_bytes(content)
                except Exception as exc: return messagebox.showerror("Download PDF",str(exc),parent=window)
                messagebox.showinfo("Asset PDF",f"PDF downloaded to:\n{target}",parent=window)
        def view():  # 2.9.97: see the PDF inside the program
            record=selected_record()
            if not record: return messagebox.showwarning("Asset PDF","Select an attachment first",parent=window)
            try: content=self.client.download_asset_attachment(record["id"])["content"]
            except Exception as exc: return messagebox.showerror("Asset PDF",str(exc),parent=window)
            from desktop_attachments import show_document
            show_document(window,record["file_name"],content)
        tree.bind("<Double-1>",lambda _event:view())
        controls=tk.Frame(window,bg=LIGHT); controls.pack(fill="x",padx=8,pady=(0,8))
        tk.Button(controls,text="View",command=view,bg=GOLD,fg=NAVY,border=0,padx=16,pady=6,font=("Segoe UI",9,"bold")).pack(side="left",padx=3)
        self.action_button(controls,"Attach / Retry PDF",attach).pack(side="left",padx=3)
        self.action_button(controls,"Download selected",lambda:download(False)).pack(side="left",padx=3)
        self.action_button(controls,"Open in PDF reader",lambda:download(True)).pack(side="left",padx=3)
        self.action_button(controls,"Refresh",refresh).pack(side="left",padx=3)
        self.action_button(controls,"Close",window.destroy).pack(side="right",padx=3)
        tk.Label(window,text="Attach / Retry affects only this saved asset's PDF documents; it never saves or posts the asset.",
                 bg=LIGHT,fg=MUTED,wraplength=690,justify="left").pack(anchor="w",padx=10,pady=(0,6))
        refresh(); self.fit_dialog(window,760,420,min_width=650,min_height=320)

    def save_asset_entry(self,review_confirmed=False):
        payload={key:var.get().strip() for key,var in self.asset_fields.items()}
        payload["annual_rate"]=self.asset_rate.get().strip()
        if not payload["invoice_id"]: payload["invoice_id"]=None
        if not payload["annual_rate"]:
            messagebox.showwarning("Assets","Enter and independently verify an annual depreciation rate; it is review-required.")
            return None
        if not payload["asset_account"].split(" - ",1)[0].strip().startswith("2"):
            messagebox.showwarning("Assets","Choose a class-2 asset account.")
            return None
        if review_confirmed:
            try: existing=self.client.fixed_assets()
            except Exception as exc: return messagebox.showerror("Assets",f"Cannot check for duplicate assets: {exc}")
            def amount(value):
                try: return round(float(str(value).replace(",","")),2)
                except (TypeError,ValueError): return None
            duplicate=next((row for row in existing if
                str(row.get("name","")).strip().casefold()==payload["name"].strip().casefold()
                and _dd(row.get("acquired_on"))==_dd(payload["acquired_on"])
                and row.get("currency")==payload["currency"].upper()
                and amount(row.get("cost"))==amount(payload["cost"])),None)
            if duplicate:
                self.load_assets()
                self.asset_list.selection_set(str(duplicate["id"])); self.select_asset()
                messagebox.showwarning("Asset PDF",f"This asset appears to already be registered as {duplicate['asset_code']}. "
                    "No duplicate register item will be created; the selected PDF will be attached to this existing item.")
                return {"_already_registered":True,**duplicate}
        try: asset=self.client.save_asset(payload,self.asset_edit_id)
        except Exception as exc: return messagebox.showerror("Assets",str(exc))
        self.load_assets()
        if self.asset_list.exists(str(asset["id"])):
            self.asset_list.selection_set(str(asset["id"])); self.select_asset()
        else:
            self.asset_edit_id=asset["id"]
        if not review_confirmed: messagebox.showinfo("Assets",f"Asset {asset['asset_code']} saved")
        return asset

    def asset_rate_changed(self,*_args):
        try:
            rate=float(self.asset_rate.get())
            if not 0<rate<=100: return
            import math
            try:
                cost=float(self.asset_fields["cost"].get().replace(",",""))
                residual=float(self.asset_fields["residual"].get().replace(",",""))
                months=math.ceil((cost-residual)*1200/(cost*rate)) if 0<=residual<cost else math.ceil(1200/rate)
            except (ValueError,ZeroDivisionError): months=math.ceil(1200/rate)
            self.asset_fields["useful_months"].set(str(months))
        except ValueError: pass

    def open_asset_purchase(self):
        self.purchase_form["vars"]["type"].set("Assets")
        self.purchase_notebook.select(self.purchase_invoice_page)

    def delete_asset_entry(self):
        if not self.asset_edit_id: return messagebox.showwarning("Assets","Select an asset first")
        if not messagebox.askyesno("Assets","Delete this unposted asset from the register?"): return
        try: self.client.delete_asset(self.asset_edit_id)
        except Exception as exc: return messagebox.showerror("Assets",str(exc))
        self.new_asset(); self.load_assets()

    def dispose_asset_entry(self):
        """2.9.132: derecognition of a sold or scrapped asset (IAS 16.67): one voucher, the sale itself by a sales invoice."""
        if not self.asset_edit_id: return messagebox.showwarning("Assets","Select an asset in the register first")
        from tkinter import simpledialog
        day=simpledialog.askstring("Dispose / Scrap","Disposal date (DD-MM-YYYY):",initialvalue=self.fiscal_today(),parent=self)
        if not day: return
        if not messagebox.askyesno("Dispose / Scrap","Post the disposal voucher (Dr accumulated depreciation, Dr 6812 book value, Cr asset cost)?\n"
                                   "Record the sale price with a sales invoice to 7812 so its VAT is declared."): return
        try: result=self.client.dispose_asset(self.asset_edit_id,day.strip())
        except (RuntimeError, ValueError, OSError, KeyError) as exc: return messagebox.showerror("Dispose / Scrap",str(exc))
        messagebox.showinfo("Dispose / Scrap",f"Voucher {result['voucher']}: cost {float(result['cost']):,.2f}, accumulated {float(result['accumulated']):,.2f}, "
                            f"book value {float(result['book_value']):,.2f} to {result['nbv_account']}.\n{result['note']}")
        self.new_asset(); self.load_assets(); self.load_journal(); self.load_trial()

    def show_asset_reconcile(self):
        """2.9.132: the register against the ledger at the end of the fiscal year (or today)."""
        try: report=self.client.asset_reconcile(self.fiscal_today())
        except (RuntimeError, ValueError, OSError, KeyError) as exc: return messagebox.showerror("Register vs Ledger",str(exc))
        lines=[f"{r['account']} {r['currency']} {'cost' if r['kind']=='cost' else 'accumulated depreciation'}: register {float(r['register']):,.2f} - "
               f"ledger {float(r['ledger']):,.2f} = difference {float(r['difference']):,.2f}" for r in report["rows"]]
        head="Register and ledger agree." if report["agreed"] else "DIFFERENCES - check the asset purchases and manual entries:"
        messagebox.showinfo("Register vs Ledger",head+"\n\n"+("\n".join(lines) or "No asset in the register."))

    def post_asset_period(self):
        tree=getattr(self,"asset_schedule_tree",None)
        selected=tree.selection() if tree is not None and tree.winfo_exists() else ()
        if not self.asset_edit_id or not selected: return messagebox.showwarning("Assets","Select an asset and an amortisation period")
        period=selected[0]
        if not messagebox.askyesno("Assets",f"Post amortisation for {period} to the journal?"): return
        try: self.client.post_asset_period(self.asset_edit_id,period)
        except Exception as exc: return messagebox.showerror("Assets",str(exc))
        self.select_asset(); self.load_journal(); self.load_trial()
