"""Customers / suppliers screen. (moved out of desktop.py in 2.9.41, unchanged)."""
from __future__ import annotations

from desktop_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, filedialog, formatted_user_date, GOLD, LIGHT, messagebox, mimetypes, NAVY, Path, similar_parties, tk,
    ttk
)
from desktop_common import main_currency  # 2.9.71


class PartiesMixin:
    def build_parties(self):
        form=tk.LabelFrame(self.parties_tab,text="Customer / Supplier File",bg=LIGHT,padx=10,pady=8); form.pack(fill="x",padx=10,pady=10)
        self.edit_party_id=None; self.party_name=tk.StringVar(); self.party_kind=tk.StringVar(value="client"); self.party_account_number=tk.StringVar(); self.party_tax=tk.StringVar(); self.party_mof=tk.StringVar(); self.party_address=tk.StringVar(); self.party_contact=tk.StringVar(); self.party_currency=tk.StringVar(value="USD"); self.party_due_days=tk.StringVar(value="0")
        tk.Label(form,text="Account Number",bg=LIGHT,font=("Segoe UI",10,"bold")).grid(row=0,column=0,sticky="w",padx=4,pady=4)
        account_entry=tk.Entry(form,textvariable=self.party_account_number,width=16,font=("Segoe UI",11,"bold")); account_entry.grid(row=0,column=1,sticky="w",padx=4,pady=4)
        self.party_account_hint=tk.Label(form,text="Type the first 4 digits (4111 client, 4011 supplier) - the full number fills in automatically",bg=LIGHT,fg="#5f6b76")
        self.party_account_hint.grid(row=0,column=2,columnspan=6,sticky="w",padx=4)
        account_entry.bind("<KeyRelease>",self.party_account_typed)
        tk.Label(form,text="Type",bg=LIGHT).grid(row=1,column=0,sticky="w",padx=4,pady=4)
        kind_box=ttk.Combobox(form,textvariable=self.party_kind,values=["client","supplier","asset_supplier","other_payable"],state="readonly",
                width=15); kind_box.grid(row=1,column=1,sticky="w",padx=4)
        kind_box.bind("<<ComboboxSelected>>",lambda _event:self.suggest_party_prefix())
        tk.Label(form,text="Name",bg=LIGHT).grid(row=1,column=2,sticky="w",padx=4); tk.Entry(form,textvariable=self.party_name,width=32).grid(row=1,column=3,sticky="w",padx=4)
        tk.Label(form,text="Currency",bg=LIGHT).grid(row=1,column=4,sticky="w",padx=4)
        ttk.Combobox(form,textvariable=self.party_currency,values=self.currency_codes,state="readonly",width=7).grid(row=1,column=5,sticky="w",padx=4)
        tk.Label(form,text="Due days from invoice",bg=LIGHT).grid(row=2,column=4,sticky="w",padx=4)
        tk.Entry(form,textvariable=self.party_due_days,width=6).grid(row=2,column=5,sticky="w",padx=4)
        for index,(label,var,width) in enumerate((("Tax Number",self.party_tax,16),("MOF Number",self.party_mof,16),("Address",self.party_address,32),("Contact Number",self.party_contact,16))):
            tk.Label(form,text=label,bg=LIGHT).grid(row=2+index//2,column=(index%2)*2,sticky="w",padx=4,pady=4)
            tk.Entry(form,textvariable=var,width=width).grid(row=2+index//2,column=(index%2)*2+1,sticky="w",padx=4,pady=4)
        buttons=tk.Frame(form,bg=LIGHT); buttons.grid(row=4,column=0,columnspan=6,sticky="w",padx=4,pady=(6,0))
        self.action_button(buttons,"New",self.new_party_account).pack(side="left",padx=3)
        tk.Button(buttons,text="Save",command=self.save_party,bg=GOLD,fg=NAVY,font=("Segoe UI",9,"bold"),border=0,padx=18,pady=7).pack(side="left",padx=3)
        self.action_button(buttons,"Edit Selected",self.edit_selected_party).pack(side="left",padx=3)
        self.action_button(buttons,"Legal Documents",self.party_documents_dialog).pack(side="left",padx=3)
        self.action_button(buttons,"Customer / Supplier Ageing",self.open_party_ageing).pack(side="left",padx=3)
        self.action_button(buttons,"Client Items: Qty & Value",self.open_client_items_report).pack(side="left",padx=3)
        self.parties_tree=self.table(self.parties_tab,[("id","ID",55),("account","9-Digit Account",115),("name","Name",180),("kind","Type",85),("tax",
                "Tax Number",110),("mof","MOF Number",110),("address","Address",180),("contact","Contact",110),("currency","Currency",70),("due_days",
                "Due Days",80)])
        self.parties_tree.bind("<Double-1>",lambda _event:self.edit_selected_party())
        self.load_parties_page()

    def party_account_typed(self,event=None):
        if event is not None and event.keysym in ("BackSpace","Delete","Left","Right","Tab"): return
        digits="".join(ch for ch in self.party_account_number.get() if ch.isdigit())
        if len(digits)!=4 or self.edit_party_id: return
        try: number=self.client.next_party_account_number(digits)
        except Exception as exc: self.party_account_hint.config(text=str(exc),fg="#8B1E1E"); return
        self.party_account_number.set(number); self.party_account_hint.config(text=f"Next free account under {digits}: {number}",fg=NAVY)

    def suggest_party_prefix(self):
        if self.edit_party_id: return
        prefix={"client":"4111","supplier":"4011","asset_supplier":"4031","other_payable":"4619"}.get(self.party_kind.get(),"4011")
        current="".join(ch for ch in self.party_account_number.get() if ch.isdigit())
        if not current or (len(current)==9 and current[:4] in ("4111","4011","4031","4619")):
            self.party_account_number.set(prefix); self.party_account_typed()

    def new_party_account(self):
        self.edit_party_id=None; self.party_name.set(""); self.party_kind.set("client"); self.party_account_number.set(""); self.party_tax.set(""); self.party_mof.set(""); self.party_address.set(""); self.party_contact.set(""); self.party_currency.set(main_currency(self,
                1)); self.party_due_days.set("0")
        self.suggest_party_prefix()

    def save_party(self):
        item={"id":self.edit_party_id,"name":self.party_name.get(),"account_category":self.party_kind.get(),"account_number":self.party_account_number.get(),
              "tax_number":self.party_tax.get(),"mof_number":self.party_mof.get(),"address":self.party_address.get(),"contact_number":self.party_contact.get(),
              "currency":self.party_currency.get(),"due_days":self.party_due_days.get()}
        try:
            matches=similar_parties(item["name"],self.client.parties(),exclude_id=self.edit_party_id) if item["name"].strip() else []
        except Exception as exc:
            return messagebox.showerror("Customers / Suppliers",str(exc))
        if matches:
            kind="customer" if item["account_category"] in ("client","customer") else "both" if item["account_category"]=="both" else "supplier"
            duplicate=next((match for match in matches if match["exact"] and match["kind"]==kind),None)
            if duplicate:
                return messagebox.showwarning("Customer / Supplier Already Exists",
                    f'{duplicate["name"]} already exists with account {duplicate["account_number"] or "(none)"}.\n'
                    "Select that record and use Edit Selected instead of creating a new one.")
            lines=[f'{match["name"]} — {match["kind"]} — account {match["account_number"] or "(none)"} '
                   f'({match["similarity"]:.0%} match)' for match in matches[:5]]
            extra=f"\n...and {len(matches)-5} more" if len(matches)>5 else ""
            if not messagebox.askyesno("Similar Customer / Supplier Name",
                    "A similar name already exists:\n\n"+"\n".join(lines)+extra+
                    "\n\nReview the existing record first. Save as a separate customer / supplier anyway?"):
                return
        try: saved=self.client.save_party(item)
        except Exception as exc: return messagebox.showerror("Customers / Suppliers",str(exc))
        self.edit_party_id=saved.get("id"); self.party_account_number.set(saved.get("account_number") or ""); self.load_parties_page(); self.load_statement_parties()
        messagebox.showinfo("Customers / Suppliers",f'Saved successfully\nAutomatic Account Number: {saved.get("account_number") or ""}')

    def edit_selected_party(self):
        selected=self.parties_tree.selection()
        if not selected: return messagebox.showwarning("Customers / Suppliers","Select a customer or supplier first")
        values=self.parties_tree.item(selected[0],
                "values"); self.edit_party_id=int(values[0]); self.party_account_number.set(values[1]); self.party_name.set(values[2]); self.party_kind.set(values[3]); self.party_tax.set(values[4]); self.party_mof.set(values[5]); self.party_address.set(values[6]); self.party_contact.set(values[7]); self.party_currency.set(values[8]); self.party_due_days.set(values[9])

    def load_parties_page(self):
        try: rows=self.client.parties()
        except Exception as exc: return messagebox.showerror("Customers / Suppliers",str(exc))
        self.party_rows=rows; self.parties_tree.delete(*self.parties_tree.get_children())
        for row in rows: self.parties_tree.insert("","end",values=(row["id"],row.get("account_number") or "",row["name"],
                row.get("account_category") or row["kind"],row.get("tax_number") or "",row.get("mof_number") or "",row.get("address") or "",
                row.get("contact_number") or "",row["currency"],row.get("due_days") or 0))

    def open_party_ageing(self):
        self.select_main_tab(self.inventory_tab)
        for widget in self.inventory_tab.winfo_children():
            if isinstance(widget,ttk.Notebook):
                widget.select(self.ageing_tab); break

    def open_client_items_report(self):
        self.select_main_tab(self.reports_tab)
        self.financial_notebook.select(self.business_reports_page)
        self.br["report"].set("Client Items: Qty & Value")
        self.run_business_report()

    def party_documents_dialog(self):
        """Legal documents of a customer / supplier. Tick "Applies" for the documents this party must have,
        enter the issue / expiry dates and Save: the scanned file is optional and can be attached later.
        Expiry alerts cover only the documents that apply."""
        selected=self.parties_tree.selection()
        if not selected: return messagebox.showwarning("Legal Documents","Select a customer or supplier first")
        party_id=int(self.parties_tree.item(selected[0],"values")[0]); party_name=self.parties_tree.item(selected[0],"values")[2]
        window=tk.Toplevel(self); window.title(f"Legal Documents - {party_name}"); window.configure(bg=LIGHT); self.fit_dialog(window,980,500); window.transient(self)
        controls=tk.Frame(window,bg=LIGHT); controls.pack(fill="x",padx=8,pady=(8,2))
        doc_type=tk.StringVar(value="MOF / VAT Certificate"); issue=tk.StringVar(); expiry=tk.StringVar(); notes=tk.StringVar(); active=tk.BooleanVar(value=True)
        editing={"id":None}; pending_file={"path":None}
        tk.Label(controls,text="Document",bg=LIGHT).pack(side="left")
        ttk.Combobox(controls,textvariable=doc_type,values=["MOF / VAT Certificate","Commercial Registration","ID / Passport","NSSF Document","Contract","Other"],width=24).pack(side="left",padx=3)
        tk.Checkbutton(controls,text="Applies",variable=active,bg=LIGHT).pack(side="left",padx=(6,6))
        tk.Label(controls,text="Issue",bg=LIGHT).pack(side="left"); self.date_entry(controls,issue,11).pack(side="left",padx=3)
        tk.Label(controls,text="Expiry",bg=LIGHT).pack(side="left"); self.date_entry(controls,expiry,11).pack(side="left",padx=3)
        tk.Label(controls,text="Notes",bg=LIGHT).pack(side="left"); tk.Entry(controls,textvariable=notes,width=22).pack(side="left",padx=3)
        status=tk.Label(window,text="New document: fill in the fields and press Save (attaching a file is optional).",bg=LIGHT,fg=NAVY,anchor="w"); status.pack(fill="x",padx=10)
        tree=self.table(window,[("type","Document Type",170),("applies","Applies",70),("state","Status",130),("issue","Issue Date",95),("expiry","Expiry Date",
                95),("file","File",200),("notes","Notes",160)])
        records={}
        def document_state(row):
            if not row.get("active",1): return "Not applicable"
            text=str(row.get("expiry_date") or "").strip()
            if not text: return "Valid (no expiry)"
            try: remaining=(datetime.strptime(formatted_user_date(text),"%d-%m-%Y").date()-datetime.now().date()).days
            except ValueError: return "Check expiry date"
            return "EXPIRED" if remaining<0 else "Expires today" if remaining==0 else f"Expires in {remaining} days" if remaining<=30 else "Valid"
        def refresh(select_id=None):
            nonlocal records
            try: rows=self.client.party_documents(party_id)
            except Exception as exc: return messagebox.showerror("Legal Documents",str(exc),parent=window)
            records={str(row["id"]):row for row in rows}; tree.delete(*tree.get_children())
            for row in rows:
                tree.insert("","end",iid=str(row["id"]),values=(row["document_type"],"Yes" if row.get("active",1) else "No",document_state(row),row.get("issue_date") or "",
                    row.get("expiry_date") or "",row["file_name"] or "(no file yet)",row.get("notes") or ""))
            if select_id and tree.exists(str(select_id)): tree.selection_set(str(select_id))
        def new_document():
            editing["id"]=None; pending_file["path"]=None; doc_type.set("MOF / VAT Certificate"); active.set(True); issue.set(""); expiry.set(""); notes.set("")
            tree.selection_remove(tree.selection()); status.config(text="New document: fill in the fields and press Save (attaching a file is optional).")
        def selected_changed(_event=None):
            chosen=tree.selection()
            if not chosen: return
            row=records.get(chosen[0])
            if not row: return
            editing["id"]=row["id"]; pending_file["path"]=None
            doc_type.set(row["document_type"]); active.set(bool(row.get("active",
                    1))); issue.set(row.get("issue_date") or ""); expiry.set(row.get("expiry_date") or ""); notes.set(row.get("notes") or "")
            status.config(text=f'Editing: {row["document_type"]}. Change the tick or dates and press Save.')
        tree.bind("<<TreeviewSelect>>",selected_changed,add="+")
        def fields():
            values={"document_type":doc_type.get().strip() or "Other","active":active.get(),"notes":notes.get().strip()}
            for key,variable,label in (("issue_date",issue,"Issue date"),("expiry_date",expiry,"Expiry date")):
                text=variable.get().strip()
                try: values[key]=formatted_user_date(text) if text else ""
                except ValueError: raise ValueError(f"{label} must be DD-MM-YYYY")
            return values
        def file_payload():
            path=pending_file["path"]
            if not path: return {},b""
            return {"file_name":Path(path).name,"mime_type":mimetypes.guess_type(path)[0] or "application/octet-stream"},Path(path).read_bytes()
        def save():
            try:
                values=fields(); extra,content=file_payload(); values.update(extra)
                if editing["id"]: document_id=self.client.update_party_document(editing["id"],values,content)["document_id"]
                else: document_id=self.client.upload_party_document(party_id,values,content)["document_id"]
            except Exception as exc: return messagebox.showerror("Legal Documents",str(exc),parent=window)
            editing["id"]=document_id; pending_file["path"]=None; refresh(document_id)
            status.config(text=f"Saved: {values['document_type']}"+("" if values["active"] else " (not applicable)")+".")
        def attach():
            path=filedialog.askopenfilename(parent=window,filetypes=[("Documents","*.pdf *.png *.jpg *.jpeg"),("All files","*.*")])
            if not path: return
            pending_file["path"]=path; save()
        def download():
            selected_doc=tree.selection()
            if not selected_doc: return
            record=records[selected_doc[0]]
            if not record.get("file_name"): return messagebox.showinfo("Legal Documents","No file is attached to this document yet. Use Attach File.",parent=window)
            path=filedialog.asksaveasfilename(parent=window,initialfile=record["file_name"])
            if path: Path(path).write_bytes(self.client.download_party_document(record["id"])["content"])
        buttons=tk.Frame(window,bg=LIGHT); buttons.pack(pady=8)
        self.action_button(buttons,"New",new_document).pack(side="left",padx=4)
        self.action_button(buttons,"Save",save).pack(side="left",padx=4)
        self.action_button(buttons,"Attach / Replace File…",attach).pack(side="left",padx=4)
        self.action_button(buttons,"Download File",download).pack(side="left",padx=4)
        refresh()
