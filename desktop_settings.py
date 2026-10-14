"""Chart of accounts and settings screens. (moved out of desktop.py in 2.9.41, unchanged)."""
from __future__ import annotations

from desktop_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, filedialog, flow_toolbars, GOLD, LIGHT, messagebox, NAVY, os, Path, tk, tr, ttk
)


class SettingsMixin:
    def build_accounts(self):
        controls=tk.Frame(self.accounts_tab,bg=LIGHT); controls.pack(fill="x",padx=10,pady=(10,0))
        self.new_account_code=tk.StringVar(); self.new_account_name=tk.StringVar(); self.new_account_parent=tk.StringVar(); self.new_account_type=tk.StringVar(value="expense")
        tk.Label(controls,text="Account (4-digit prefix = automatic):",bg=LIGHT,font=("Segoe UI",9,"bold"),fg=NAVY).pack(side="left",padx=(0,4))
        self.new_account_code_entry=tk.Entry(controls,textvariable=self.new_account_code,width=11); self.new_account_code_entry.pack(side="left",padx=3)
        self.new_account_code_entry.bind("<FocusOut>",self.preview_new_account_number); self.new_account_code_entry.bind("<Return>",self.preview_new_account_number)
        tk.Entry(controls,textvariable=self.new_account_name,width=22).pack(side="left",padx=3)
        tk.Entry(controls,textvariable=self.new_account_parent,width=9).pack(side="left",padx=3)
        ttk.Combobox(controls,textvariable=self.new_account_type,values=["asset","liability","equity","income","expense"],state="readonly",width=9).pack(side="left",padx=3)
        self.action_button(controls,"Create Account",self.save_new_account).pack(side="left",padx=5)
        tk.Button(controls,text="Edit Selected Account",command=self.edit_selected_account,bg=GOLD,fg=NAVY,border=0,padx=12,pady=6,font=("Segoe UI",9,"bold")).pack(side="left",padx=5)
        self.account_tool_buttons(controls)  # 2.9.66: delete (one or many), delete unused, move / transfer
        self.action_button(controls,tr(self.language.get(),"refresh"),self.load_accounts).pack(side="right")
        self.accounts_tree=self.table(self.accounts_tab,[
            ("code","Account",100),("parent","Parent",80),("english","English",270),
            ("french","French",270),("arabic","Arabic",270),("type","Type",90)])
        self.accounts_tree.bind("<Double-1>",lambda _event:self.edit_selected_account())
        self.accounts_tree.bind("<Return>",lambda _event:self.edit_selected_account())
        self.accounts_tree.bind("<Delete>",lambda _event:self.delete_selected_accounts())
        flow_toolbars(controls)
        self.load_accounts()

    def save_new_account(self):
        try: account=self.client.save_account({"code":self.new_account_code.get(),"name_en":self.new_account_name.get(),"parent_code":self.new_account_parent.get(),"type":self.new_account_type.get()})
        except Exception as exc: return messagebox.showerror("Chart of Accounts",str(exc))
        self._account_cache=None
        if hasattr(self,"_all_accounts"): self._all_accounts[account["code"]]=account["name_en"]
        self.new_account_code.set(""); self.new_account_name.set(""); self.new_account_parent.set(""); self.load_accounts()
        messagebox.showinfo("Chart of Accounts",f'Account {account["code"]} created successfully')

    def preview_new_account_number(self,_event=None):
        prefix=self.new_account_code.get().strip()
        if len(prefix)!=4 or not prefix.isdigit(): return
        try: number=self.client.next_account_number(prefix)
        except Exception as exc: return messagebox.showwarning("Chart of Accounts",str(exc))
        self.new_account_parent.set(prefix); self.new_account_code.set(number)

    def load_selected_account_name(self):
        selected=self.accounts_tree.selection()
        if not selected: return
        values=self.accounts_tree.item(selected[0],"values"); self.new_account_code.set(values[0]); self.new_account_name.set(values[2])

    def edit_selected_account(self):
        """Edit the selected account in its own window: names (English / French / Arabic) and type, then Save."""
        selected=self.accounts_tree.selection()
        if not selected: return messagebox.showwarning("Chart of Accounts","Select an account first (click it), then Edit")
        values=self.accounts_tree.item(selected[0],"values"); code=str(values[0])
        window=tk.Toplevel(self); window.title(f"Edit account {code}"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        fields={"name_en":tk.StringVar(value=values[2]),"name_fr":tk.StringVar(value=values[3]),"name_ar":tk.StringVar(value=values[4]),"type":tk.StringVar(value=values[5])}
        tk.Label(window,text=f"Account {code}"+(f"   (parent {values[1]})" if values[1] else ""),bg=LIGHT,fg=NAVY,font=("Segoe UI",11,"bold")).grid(row=0,
                column=0,columnspan=2,padx=14,pady=(12,6),sticky="w")
        for row,(key,label) in enumerate((("name_en","English name"),("name_fr","French name"),("name_ar","Arabic name | الاسم بالعربية")),1):
            tk.Label(window,text=label,bg=LIGHT).grid(row=row,column=0,padx=14,pady=5,sticky="w")
            entry=tk.Entry(window,textvariable=fields[key],width=44,justify="right" if key=="name_ar" else "left"); entry.grid(row=row,column=1,padx=14,pady=5)
            if key=="name_en": entry.focus_set(); entry.select_range(0,"end")
        tk.Label(window,text="Type",bg=LIGHT).grid(row=4,column=0,padx=14,pady=5,sticky="w")
        ttk.Combobox(window,textvariable=fields["type"],values=["asset","liability","equity","income","expense"],state="readonly",width=14).grid(row=4,column=1,padx=14,pady=5,sticky="w")
        def save(_event=None):
            try: self.client.update_account(code,{key:var.get().strip() for key,var in fields.items()})
            except Exception as exc: return messagebox.showerror("Chart of Accounts",str(exc),parent=window)
            window.destroy(); self._account_cache=None; self.load_accounts()
            for iid in self.accounts_tree.get_children():
                if str(self.accounts_tree.item(iid,"values")[0])==code: self.accounts_tree.selection_set(iid); self.accounts_tree.see(iid); break
            messagebox.showinfo("Chart of Accounts",f"Account {code} saved")
        buttons=tk.Frame(window,bg=LIGHT); buttons.grid(row=5,column=0,columnspan=2,pady=12)
        tk.Button(buttons,text="Save",command=save,bg=GOLD,fg=NAVY,border=0,padx=24,pady=7,font=("Segoe UI",10,"bold")).pack(side="left",padx=5)
        tk.Button(buttons,text="Cancel",command=window.destroy,bg=NAVY,fg="white",border=0,padx=18,pady=7).pack(side="left",padx=5)
        window.bind("<Return>",save); window.bind("<Escape>",lambda _e: window.destroy())
        return window

    def rename_selected_account(self):
        selected=self.accounts_tree.selection()
        if not selected: return messagebox.showwarning("Chart of Accounts","Select an account first")
        code=str(self.accounts_tree.item(selected[0],"values")[0]); name=self.new_account_name.get().strip()
        try: self.client.rename_account(code,name)
        except Exception as exc: return messagebox.showerror("Chart of Accounts",str(exc))
        self.load_accounts(); messagebox.showinfo("Chart of Accounts",f"Account {code} name updated")

    def load_accounts(self):
        try:
            rows=self.client.accounts()
        except Exception as exc:
            return messagebox.showerror("Error",str(exc))
        self._all_accounts={str(row["code"]):row["name_en"] for row in rows}
        self.accounts_tree.delete(*self.accounts_tree.get_children())
        for row in rows:
            self.accounts_tree.insert("","end",values=(row["code"],row.get("parent_code") or "",
                row["name_en"],row.get("name_fr") or "",row.get("name_ar") or "",row["type"]))

    def build_settings(self):
        nested=ttk.Notebook(self.settings_tab); nested.pack(fill="both",expand=True,padx=10,pady=10)
        users=tk.Frame(nested,bg=LIGHT); backups=tk.Frame(nested,bg=LIGHT); rates=tk.Frame(nested,bg=LIGHT); branches=tk.Frame(nested,bg=LIGHT); general=tk.Frame(nested,bg=LIGHT)
        is_admin=(self.current_user or {}).get("role")=="admin"
        if is_admin: nested.add(users,text="Users & Permissions")
        is_viewer=(self.current_user or {}).get("role")=="viewer"
        if not is_viewer: nested.add(backups,text="Backup & Restore" if is_admin else "My Backups")
        nested.add(rates,text="Exchange Rates"); nested.add(branches,text="Branches"); nested.add(general,text="General Settings"); self.build_dimensions_pages(nested)
        setup_page=tk.Frame(nested,bg=LIGHT); nested.add(setup_page,text="Accounting Settings"); self.build_accounting_setup_page(setup_page)  # 2.9.81
        if is_admin:  # 2.9.84: who added, changed, posted or deleted what, and when
            audit_page=tk.Frame(nested,bg=LIGHT); nested.add(audit_page,text="Audit Trail"); self.build_audit_trail_page(audit_page)
            renumber_page=tk.Frame(nested,bg=LIGHT); nested.add(renumber_page,text="Renumber"); self.build_renumber_page(renumber_page)  # 2.9.115
        if is_admin: self.build_users_page(users)
        if not is_viewer:
            backup_controls=tk.Frame(backups,bg=LIGHT); backup_controls.pack(fill="x",padx=10,pady=10)
            self.backup_scope=tk.Label(backups,text="",bg=LIGHT,fg=NAVY,font=("Segoe UI",10,"bold"),anchor="w"); self.backup_scope.pack(fill="x",padx=14,before=backup_controls)
            tk.Button(backup_controls,text="Create Backup Now",command=self.create_backup,bg=GOLD,fg=NAVY,border=0,padx=15,pady=7,font=("Segoe UI",9,"bold")).pack(side="left",padx=4)
            self.action_button(backup_controls,"Save Backup As... (USB / Drive)",self.save_backup_as).pack(side="left",padx=4)
            self.action_button(backup_controls,"Open Backup Folder",self.open_backup_folder).pack(side="left",padx=4)
            self.action_button(backup_controls,"Open Log Folder",self.open_log_folder).pack(side="left",padx=4)
            self.action_button(backup_controls,"Network Check",self.network_check).pack(side="left",padx=4)  # 2.9.98
            if is_admin: tk.Button(backup_controls,text="Restore Selected",command=self.restore_selected_backup,bg="#8B1E1E",fg="white",border=0,padx=15,pady=7).pack(side="left",padx=4)
            if is_admin:
                lock_bar=tk.LabelFrame(backups,text="Close the books (period lock)",bg=LIGHT,padx=8,pady=6); lock_bar.pack(fill="x",padx=10,pady=(0,6))
                self.books_lock_date=tk.StringVar()
                tk.Label(lock_bar,text="Lock up to (DD-MM-YYYY)",bg=LIGHT).pack(side="left",padx=(2,4))
                self.date_entry(lock_bar,self.books_lock_date,12).pack(side="left",padx=4)
                tk.Button(lock_bar,text="Lock",command=self.lock_books,bg=GOLD,fg=NAVY,border=0,padx=14,pady=5,font=("Segoe UI",9,"bold")).pack(side="left",padx=4)
                self.action_button(lock_bar,"Unlock",self.unlock_books).pack(side="left",padx=4)
                self.books_lock_label=tk.Label(lock_bar,text="",bg=LIGHT,fg=NAVY,font=("Segoe UI",9,"bold")); self.books_lock_label.pack(side="left",padx=12)
            if is_admin: self.build_second_copy_box(backups)
            tk.Label(backups,text="An automatic backup of this company and year is made every day when you open it (the newest 30 automatic copies are kept; manual and safety copies are never deleted). Keep a copy outside the computer too: Save Backup As... (USB / Drive).",
                    bg=LIGHT,fg="#5f6b76",wraplength=1050,justify="left").pack(fill="x",padx=14)
            self.backups_tree=self.table(backups,[("name","Backup File",400),("kind","Type",100),("checked","Checked",90),("size","Size",100),("modified","Created",170)])
        rate_controls=tk.Frame(rates,bg=LIGHT); rate_controls.pack(fill="x",padx=10,pady=10)
        self.rate_date=tk.StringVar(value=datetime.now().strftime("%d-%m-%Y")); self.rate_date_to=tk.StringVar(value=datetime.now().strftime("%d-%m-%Y")); self.rate_from=tk.StringVar(value="USD"); self.rate_to=tk.StringVar(value="LBP"); self.rate_value=tk.StringVar(value="1")
        tk.Label(rate_controls,text="Date From",bg=LIGHT).pack(side="left"); self.date_entry(rate_controls,self.rate_date,12).pack(side="left",padx=4)
        tk.Label(rate_controls,text="Date To",bg=LIGHT).pack(side="left"); self.date_entry(rate_controls,self.rate_date_to,12).pack(side="left",padx=4)
        self.rate_from_box=ttk.Combobox(rate_controls,textvariable=self.rate_from,values=self.currency_codes,state="readonly",width=7); self.rate_from_box.pack(side="left",padx=4)
        tk.Label(rate_controls,text="to",bg=LIGHT).pack(side="left")
        self.rate_to_box=ttk.Combobox(rate_controls,textvariable=self.rate_to,values=self.currency_codes,state="readonly",width=7); self.rate_to_box.pack(side="left",padx=4)
        tk.Entry(rate_controls,textvariable=self.rate_value,width=14).pack(side="left",padx=4)
        self.action_button(rate_controls,"Add Daily Rate",self.save_exchange_rate).pack(side="left",padx=5)
        self.action_button(rate_controls,"Restore EUR Rates 2024-Today",self.restore_euro_rates).pack(side="left",padx=5)
        self.action_button(rate_controls,"Restore ALL Currencies 2024-Today",self.restore_all_rates).pack(side="left",padx=5)
        currency_controls=tk.Frame(rates,bg=LIGHT); currency_controls.pack(fill="x",padx=12,pady=(0,6))
        self.new_currency_code=tk.StringVar(); self.new_currency_name=tk.StringVar()
        tk.Label(currency_controls,text="Create currency",bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left",padx=(0,6))
        tk.Entry(currency_controls,textvariable=self.new_currency_code,width=7).pack(side="left")
        tk.Label(currency_controls,text="Code (3 letters)",bg=LIGHT).pack(side="left",padx=(3,12))
        tk.Entry(currency_controls,textvariable=self.new_currency_name,width=22).pack(side="left")
        tk.Label(currency_controls,text="Name",bg=LIGHT).pack(side="left",padx=(3,8))
        self.action_button(currency_controls,"Add Currency",self.create_currency).pack(side="left",padx=4)
        tk.Label(currency_controls,text="Set a rate before using it in another currency's report.",bg=LIGHT,fg="#5f6b76").pack(side="left",padx=8)
        self.rates_tree=self.table(rates,[("date","Date",110),("from","From",80),("to","To",80),("rate","Daily Average",150),("samples","Entries",75),("created","Saved",180)])
        self.rates_tree.bind("<Double-1>",lambda _event:self.edit_selected_exchange_rate())
        branch_controls=tk.Frame(branches,bg=LIGHT); branch_controls.pack(fill="x",padx=10,pady=10)
        self.new_branch_name=tk.StringVar(); tk.Label(branch_controls,text="New Branch Name",bg=LIGHT).pack(side="left"); tk.Entry(branch_controls,
                textvariable=self.new_branch_name,width=32).pack(side="left",padx=6)
        self.action_button(branch_controls,"Save Branch",self.save_branch).pack(side="left",padx=4)
        self.branches_tree=self.table(branches,[("id","ID",80),("name","Branch Name",320),("active","Active",90)])
        self.base_currency=tk.StringVar(value="USD"); self.second_currency=tk.StringVar(value="LBP"); self.backup_hours=tk.StringVar(value="24")
        self.company_fields={key:tk.StringVar() for key in ("company_name","company_address","company_phone","company_mof","company_nssf","company_email","company_website","company_logo",
                                                            "company_name_ar","company_address_ar","company_trade_name","company_cr_number","company_cr_place")}
        tk.Label(general,text="Main Currency 1 (base)",bg=LIGHT).grid(row=0,column=0,padx=14,pady=(14,4),sticky="w")
        self.base_currency_box=ttk.Combobox(general,textvariable=self.base_currency,values=self.currency_codes,state="readonly",
                width=15); self.base_currency_box.grid(row=0,column=1,padx=14,pady=(14,4),sticky="w")
        # 2.9.71: the second main currency (USD + LBP, EUR + USD, AED + USD ...): the default of new documents and of the report columns
        tk.Label(general,text="Main Currency 2",bg=LIGHT).grid(row=1,column=0,padx=14,pady=4,sticky="w")
        self.second_currency_box=ttk.Combobox(general,textvariable=self.second_currency,values=self.currency_codes,state="readonly",
                width=15); self.second_currency_box.grid(row=1,column=1,padx=14,pady=4,sticky="w")

        for row,(key,label) in enumerate((("company_name","Company Name"),("company_address","Address"),("company_phone","Phone"),("company_mof",
                "MOF / VAT Number"),("company_nssf","NSSF Employer Number"),("company_email","Email"),("company_website","Website"),("company_logo",
                "Logo File Path")),2):
            tk.Label(general,text=label,bg=LIGHT).grid(row=row,column=0,padx=14,pady=7,sticky="w")
            tk.Entry(general,textvariable=self.company_fields[key],width=42).grid(row=row,column=1,padx=14,pady=7,sticky="w")
        # 2.9.108: Arabic name / address and the commercial register, written on the NSSF and MOF forms
        for row,(key,label) in enumerate((("company_name_ar","إسم الشركة (عربي)"),("company_address_ar","العنوان (عربي)"),
                ("company_trade_name","الشهرة التجارية"),("company_cr_number","رقم السجل التجاري"),("company_cr_place","مكان السجل التجاري")),2):
            tk.Label(general,text=label,bg=LIGHT).grid(row=row,column=2,padx=(24,6),pady=7,sticky="w")
            tk.Entry(general,textvariable=self.company_fields[key],width=34,justify="right").grid(row=row,column=3,padx=6,pady=7,sticky="w")
        self.company_vat_registered=tk.StringVar(value="Yes"); self.company_vat_date=tk.StringVar()
        tk.Label(general,text="Registered in VAT",bg=LIGHT).grid(row=10,column=0,padx=14,pady=7,sticky="w")
        ttk.Combobox(general,textvariable=self.company_vat_registered,values=["Yes","No"],state="readonly",width=15).grid(row=10,column=1,padx=14,pady=7,sticky="w")
        tk.Label(general,text="VAT Registration Date",bg=LIGHT).grid(row=11,column=0,padx=14,pady=7,sticky="w")
        self.date_entry(general,self.company_vat_date,42).grid(row=11,column=1,padx=14,pady=7,sticky="w")
        # 2.9.72: the VAT of this company - standard rate and the two currencies of its VAT return
        self.company_vat_rate=tk.StringVar(value="11"); self.company_vat_currency=tk.StringVar(value="LBP"); self.company_vat_second=tk.StringVar(value="USD")
        tk.Label(general,text="VAT Rate %",bg=LIGHT).grid(row=10,column=2,padx=(24,6),pady=7,sticky="w")
        tk.Entry(general,textvariable=self.company_vat_rate,width=8).grid(row=10,column=3,padx=6,pady=7,sticky="w")
        tk.Label(general,text="VAT Return Currency 1 / 2",bg=LIGHT).grid(row=11,column=2,padx=(24,6),pady=7,sticky="w")
        vat_boxes=tk.Frame(general,bg=LIGHT); vat_boxes.grid(row=11,column=3,padx=6,pady=7,sticky="w")
        self.vat_currency_box=ttk.Combobox(vat_boxes,textvariable=self.company_vat_currency,values=self.currency_codes,state="readonly",width=7); self.vat_currency_box.pack(side="left")
        self.vat_second_box=ttk.Combobox(vat_boxes,textvariable=self.company_vat_second,values=self.currency_codes,state="readonly",width=7); self.vat_second_box.pack(side="left",padx=(6,0))
        self.show_tax_tick=tk.BooleanVar(master=self,value=True)  # 2.9.113
        tk.Checkbutton(general,text="Show the tick \"Not deductible for income tax | غير مقبول ضريبياً\" on the entry screens",variable=self.show_tax_tick,
                       bg=LIGHT).grid(row=12,column=2,columnspan=2,padx=14,pady=7,sticky="w")
        self.enable_exempt_income=tk.BooleanVar(master=self,value=False)  # 2.9.113
        tk.Checkbutton(general,text="Sales: income not subject to income tax (already taxed / exempt by law, with the legal reason)",
                       variable=self.enable_exempt_income,bg=LIGHT).grid(row=14,column=1,columnspan=3,padx=14,pady=7,sticky="w")
        self.action_button(general,"Save Settings",self.save_general_settings).grid(row=12,column=0,columnspan=2,pady=14)
        import desktop_layout  # 2.9.60: menu style, kept on this computer
        tk.Label(general,text="Screen layout (this computer)",bg=LIGHT,font=("Segoe UI",9,"bold")).grid(row=13,column=0,padx=14,pady=7,sticky="w")
        self.layout_side_menu=tk.BooleanVar(master=self,value=desktop_layout.side_menu_on())
        tk.Checkbutton(general,text="Menu on the left, in groups (untick for the buttons above the pages)",variable=self.layout_side_menu,
                       command=self.change_menu_layout,bg=LIGHT).grid(row=13,column=1,padx=14,pady=7,sticky="w")
        self.load_settings_pages()

    def load_settings_pages(self):
        if not hasattr(self,"rates_tree"): return
        try:
            settings=self.client.settings(); rates=self.client.exchange_rates()
            self.refresh_books_lock()
            self.base_currency.set(settings.get("base_currency","USD")); self.second_currency.set(settings.get("second_currency",
                    "LBP")); self.backup_hours.set(settings.get("backup_interval_hours","24"))
            for box in (getattr(self,"base_currency_box",None),getattr(self,"second_currency_box",None)):
                if box is not None: box.configure(values=self.currency_codes)
            for key,var in self.company_fields.items(): var.set(settings.get(key,"Saber for Audit" if key=="company_name" else ""))
            if hasattr(self,"show_tax_tick"):  # 2.9.113
                import desktop_tax_flag; shown=str(settings.get("show_tax_tick","1") or "1")!="0"
                self.show_tax_tick.set(shown); desktop_tax_flag.set_visible(shown)
                self.exempt_income_enabled=str(settings.get("enable_exempt_income","0") or "0")=="1"
                self.enable_exempt_income.set(self.exempt_income_enabled)
                if hasattr(self,"sales_exempt_visibility"): self.sales_exempt_visibility()
            self.company_vat_registered.set(settings.get("company_vat_registered","Yes") or "Yes"); self.company_vat_date.set(settings.get("company_vat_date","") or "")
            if hasattr(self,"company_vat_rate"):
                self.company_vat_rate.set(settings.get("vat_rate") or "11"); self.company_vat_currency.set(settings.get("vat_currency") or "LBP"); self.company_vat_second.set(settings.get("vat_second_currency") or "USD")
                for box in (self.vat_currency_box,self.vat_second_box): box.configure(values=self.currency_codes)
        except Exception as exc: return messagebox.showerror("Settings",str(exc))
        self.rates_tree.delete(*self.rates_tree.get_children())
        for row in rates: self.rates_tree.insert("","end",values=(row["rate_date"],row["from_currency"],row["to_currency"],row["rate"],row.get("samples",0),row["created_at"][:19]))
        try: branch_rows=self.client.branches()
        except Exception: branch_rows=[]
        self.branches_tree.delete(*self.branches_tree.get_children())
        for row in branch_rows: self.branches_tree.insert("","end",values=(row["id"],row["name"],"Yes" if row["active"] else "No"))
        backups=[]
        if hasattr(self,"backups_tree"):
            try: backups=self.client.backups()
            except Exception: backups=[]
            self.backups_tree.delete(*self.backups_tree.get_children())
        if (self.current_user or {}).get("role")=="admin":
            try: users=self.client.users()
            except Exception: users=[]
            self.users_tree.delete(*self.users_tree.get_children()); self.fill_users_tree(users)
        if hasattr(self,"backups_tree"):
            for row in backups: self.backups_tree.insert("","end",iid=row["name"],values=(row["name"],row.get("kind","backup"),row.get("checked","not checked"),
                    f'{row["size"]/1024/1024:,.2f} MB',row["modified"][:19].replace("T"," ")))
        if hasattr(self,"backup_scope"): self.backup_scope.config(text=f'Backups of {getattr(self,"current_company",{}).get("name","")} - fiscal year {getattr(self,"current_fiscal_year","")}')

    def save_branch(self):
        try: branch=self.client.save_branch(self.new_branch_name.get().strip())
        except Exception as exc: return messagebox.showerror("Branches",str(exc))
        self.new_branch_name.set(""); self.load_settings_pages(); messagebox.showinfo("Branches",f'Branch {branch["name"]} saved successfully')

    def change_menu_layout(self):
        import desktop_layout
        desktop_layout.save_layout_settings(side_menu=bool(self.layout_side_menu.get()))
        if messagebox.askyesno("Screen layout","Saved. Re-open the screens now to see the new menu?\n(Unsaved work on other screens would be lost.)"):
            self.after(50,self.main_screen)

    def create_backup(self):
        try: result=self.client.create_backup()
        except Exception as exc: return messagebox.showerror("Backup",str(exc))
        self.load_settings_pages()
        import backup_copy
        config=backup_copy.settings(); extra=""
        if config["folder"]: extra=f"\n\nSecond copy: FAILED - {config['last_error']}" if config["last_error"] else f"\n\nSecond copy saved in {config['folder']}"
        if hasattr(self,"refresh_second_copy_status"): self.refresh_second_copy_status()
        messagebox.showinfo("Backup",f'Backup created:\n{result["path"]}{extra}')

    def save_backup_as(self):
        selected=self.backups_tree.selection()
        if not selected:
            if not messagebox.askyesno("Save Backup As","No backup is selected. Create a new backup now and save a copy?"): return
            try: name=Path(self.client.create_backup()["path"]).name
            except Exception as exc: return messagebox.showerror("Backup",str(exc))
            self.load_settings_pages()
        else: name=selected[0]
        path=filedialog.asksaveasfilename(initialfile=name,defaultextension=".db",filetypes=[("Nanza backup","*.db")])
        if not path: return
        try: Path(path).write_bytes(self.client.download_backup(name)["content"])
        except Exception as exc: return messagebox.showerror("Save Backup As",str(exc))
        messagebox.showinfo("Save Backup As",f"Backup copied to:\n{path}")

    def open_backup_folder(self):
        try: folder=self.client.backup_folder(); Path(folder).mkdir(parents=True,exist_ok=True)
        except Exception as exc: return messagebox.showerror("Backups",str(exc))
        try:
            if os.name=="nt": os.startfile(folder)
            else: raise RuntimeError
        except Exception: messagebox.showinfo("Backups",f"Backup folder:\n{folder}")

    # ------------------------------------------------------------ 2.9.52: second copy (OneDrive / USB / network)
    def build_second_copy_box(self,parent):
        import backup_copy
        box=tk.LabelFrame(parent,text="Second copy of every backup (OneDrive / USB / network folder)",bg=LIGHT,padx=8,pady=6); box.pack(fill="x",padx=10,pady=(0,6))
        config=backup_copy.settings()
        self.second_copy_folder=tk.StringVar(value=config["folder"]); self.second_copy_keep=tk.StringVar(value=str(config["keep"]))
        tk.Label(box,text="Folder",bg=LIGHT).pack(side="left"); tk.Entry(box,textvariable=self.second_copy_folder,width=48).pack(side="left",padx=4)
        self.action_button(box,"Browse...",self.choose_second_copy_folder).pack(side="left",padx=2)
        self.action_button(box,"Use OneDrive",self.use_onedrive_for_backups).pack(side="left",padx=2)
        tk.Label(box,text="Keep",bg=LIGHT).pack(side="left",padx=(8,2)); tk.Entry(box,textvariable=self.second_copy_keep,width=4).pack(side="left")
        tk.Button(box,text="Save",command=self.save_second_copy,bg=GOLD,fg=NAVY,border=0,padx=12,pady=4,font=("Segoe UI",9,"bold")).pack(side="left",padx=6)
        self.second_copy_status=tk.Label(parent,text="",bg=LIGHT,fg=NAVY,anchor="w"); self.second_copy_status.pack(fill="x",padx=14,after=box)
        self.refresh_second_copy_status()

    def refresh_second_copy_status(self):
        import backup_copy
        config=backup_copy.settings(); label=getattr(self,"second_copy_status",None)
        if label is None or not label.winfo_exists(): return
        if not config["folder"]: text,color="No second copy: backups stay only on this computer. Choose OneDrive or a USB / network folder.","#8a5a00"
        elif config["last_error"]: text,color=f"Last copy FAILED: {config['last_error']}","#8B1E1E"
        elif config["last_ok"]: text,color=f"Last copy: {config['last_ok']}",NAVY
        else: text,color=f"Every new backup will also be copied to {config['folder']}",NAVY
        label.config(text=text,fg=color)

    def choose_second_copy_folder(self):
        folder=filedialog.askdirectory(title="Folder for the second copy of the backups")
        if folder: self.second_copy_folder.set(folder)

    def use_onedrive_for_backups(self):
        import backup_copy
        folder=backup_copy.suggested_folder()
        if not folder: return messagebox.showinfo("Backups","OneDrive was not found on this computer. Choose a USB or network folder with Browse...")
        self.second_copy_folder.set(folder)

    def save_second_copy(self):
        import backup_copy
        try: backup_copy.save_settings(self.second_copy_folder.get(),self.second_copy_keep.get())
        except ValueError as exc: return messagebox.showwarning("Backups",str(exc))
        if self.second_copy_folder.get().strip() and messagebox.askyesno("Backups","Saved. Make a backup now to check the second copy?"):
            self.create_backup()
        self.refresh_second_copy_status()

    def network_check(self):
        """2.9.98: how this PC reaches the data service: address, encryption, office certificate and answer time (10 requests),
        with the steps for an office network of 2-3 PCs."""
        import time, statistics, app_runtime, office_tls
        url = self.client.base_url; local = bool(app_runtime.LOCAL_URL) and url == str(app_runtime.LOCAL_URL).rstrip("/")
        times = []; error = ""
        for _ in range(10):
            started = time.perf_counter()
            try: self.client.request("GET", "/api/companies")  # not kept on this PC: every request goes to the data service
            except Exception as exc: error = str(exc); break
            times.append((time.perf_counter() - started) * 1000)
        lines = [f"Data service: {url}" + (" (the private service of this PC)" if local else "")]
        if not local:
            lines.append("Encryption: " + ("HTTPS - passwords and data are encrypted on the network" if url.startswith("https") else
                                          "NONE (http) - use the office certificate: run_server.py --make-certificate"))
            trusted = office_tls.trusted_certificate()
            lines.append("Office certificate on this PC: " + (str(trusted) if trusted else "not found (copy server-cert.pem as office-server-cert.pem into the Nanza data folder)"))
        if times:
            average = statistics.mean(times)
            verdict = "excellent" if average < 30 else "good" if average < 120 else "slow - check the cable / Wi-Fi of this PC and of the server"
            lines.append(f"Answer time: {min(times):.0f} / {average:.0f} / {max(times):.0f} ms (fastest / average / slowest of 10) - {verdict}")
        if error: lines.append(f"Could not reach the data service: {error}")
        lines += ["", "Office network (2-3 PCs):", "1. On the server PC: python run_server.py --make-certificate SERVER-NAME,SERVER-IP",
                  "2. Start it: run_server.py --host 0.0.0.0 --tls-cert server-cert.pem --tls-key server-key.pem",
                  "3. Copy server-cert.pem (never the key) to each PC's Nanza data folder as office-server-cert.pem",
                  "4. On each PC sign in with https://SERVER-NAME:8765, then press Network Check here."]
        (messagebox.showwarning if error else messagebox.showinfo)("Network Check", "\n".join(lines))

    def open_log_folder(self):
        """Error log of this computer (logs/nanza.log - saber.log on older installations - in the Nanza data folder) - send it when reporting a problem."""
        import app_runtime
        folder=app_runtime.data_dir()/"logs"; folder.mkdir(parents=True,exist_ok=True)
        try:
            if os.name=="nt": os.startfile(folder)
            else: raise RuntimeError
        except Exception: messagebox.showinfo("Log",f"Log folder:\n{folder}")

    def restore_selected_backup(self):
        selected=self.backups_tree.selection()
        if not selected: return messagebox.showwarning("Restore","Select one backup")
        if not messagebox.askyesno("Restore Database","Restore this backup? A safety backup of current data will be created first."): return
        try: self.client.restore_backup(selected[0])
        except Exception as exc: return messagebox.showerror("Restore",str(exc))
        messagebox.showinfo("Restore","Database restored successfully. Refreshing all pages."); self.load_dashboard(); self.load_invoices(); self.load_journal(); self.load_trial(); self.load_settings_pages(); self.load_payroll(); self.load_transactions(); self.load_vat_return()

    def save_exchange_rate(self):
        try: self.client.save_exchange_rate({"date_from":self.rate_date.get(),"date_to":self.rate_date_to.get(),"from_currency":self.rate_from.get(),
                "to_currency":self.rate_to.get(),"rate":self.rate_value.get()})
        except Exception as exc: return messagebox.showerror("Exchange Rates",str(exc))
        self.load_settings_pages(); messagebox.showinfo("Exchange Rates","Rate added. The daily rate is the average of all entered rates for this date and currency pair.")

    def create_currency(self):
        try: item=self.client.save_currency(self.new_currency_code.get(),self.new_currency_name.get())
        except Exception as exc: return messagebox.showerror("Currencies",str(exc))
        previous=set(self.currency_codes)
        self.currency_codes=[row["code"] for row in self.client.currencies()]
        def refresh(widget):
            if isinstance(widget,ttk.Combobox):
                choices=list(widget["values"])
                existing=set(choices)
                if existing==previous: widget["values"]=self.currency_codes
                elif existing==previous|{"All Currencies"}: widget["values"]=["All Currencies"]+self.currency_codes
                elif existing==previous|{"account"}: widget["values"]=["account"]+self.currency_codes
                elif existing==previous|{"account","none"}: widget["values"]=["account"]+self.currency_codes+["none"]
            for child in widget.winfo_children(): refresh(child)
        refresh(self)
        for state in (getattr(self,"trial_state",None),getattr(self,"statement_state",None)):
            if state and item["code"] not in state["currencies"]:
                var=tk.BooleanVar(value=True); state["currencies"][item["code"]]=var
                tk.Checkbutton(state["dimension_row"],text=item["code"],variable=var,bg=LIGHT).pack(side="left")
        self.new_currency_code.set(""); self.new_currency_name.set("")
        messagebox.showinfo("Currencies",f'{item["code"]} added. Set its exchange rate before using cross-currency reports.')

    def edit_selected_exchange_rate(self):
        selected=self.rates_tree.selection()
        if not selected: return
        values=self.rates_tree.item(selected[0],"values")
        self.rate_date.set(values[0]); self.rate_date_to.set(values[0]); self.rate_from.set(values[1]); self.rate_to.set(values[2]); self.rate_value.set(values[3])

    def restore_euro_rates(self):
        if not messagebox.askyesno("Exchange Rates","Restore daily EUR to USD and EUR to LBP rates from 01-01-2024 until today?"): return
        try: result=self.client.restore_euro_rates()
        except Exception as exc: return messagebox.showerror("Exchange Rates",str(exc))
        self.load_settings_pages(); messagebox.showinfo("Exchange Rates",f'Restored {result.get("days",0)} days from 01-01-2024 until today')

    def restore_all_rates(self):
        """2.9.71: the daily rates of every currency of Settings > Currencies, from 01-01-2024 until today."""
        if not messagebox.askyesno("Exchange Rates","Restore the daily rates of ALL the currencies of Settings, from 01-01-2024 until today?\n\n"
            "EUR, GBP, CHF, CAD ... come from the European Central Bank (internet needed); AED, SAR, QAR, BHD, OMR and JOD use their fixed "
            "US dollar rate; LBP stays at 89,500. Rates you typed yourself are kept."): return
        try: result=self.client.restore_all_rates()
        except Exception as exc: return messagebox.showerror("Exchange Rates",str(exc))
        self.load_settings_pages()
        text=f'Restored from 01-01-2024 until today: {", ".join(result.get("restored") or [])}'
        if result.get("skipped"): text+=f'\n\nNo automatic source (enter these by hand): {", ".join(result["skipped"])}'
        if result.get("offline_years"): text+=f'\n\nNo internet for: {", ".join(str(y) for y in result["offline_years"])} - try again later.'
        messagebox.showinfo("Exchange Rates",text)

    def refresh_books_lock(self):
        label=getattr(self,"books_lock_label",None)
        if label is None or not label.winfo_exists(): return
        try: lock=self.client.books_lock()
        except Exception: return
        label.config(text=f"Books are LOCKED up to {lock['display']}: nothing dated on or before it can be posted, changed or deleted." if lock.get("display")
                     else "Books are open: no period is locked.", fg="#8B1E1E" if lock.get("display") else NAVY)
        if lock.get("display"): self.books_lock_date.set(lock["display"])

    def lock_books(self):
        date=self.books_lock_date.get().strip()
        if not date: return messagebox.showwarning("Close the books","Enter the last date to lock (for example the last day of the month or quarter you filed)")
        if not messagebox.askyesno("Close the books",
                f"Lock the books up to {date}?\n\nNo invoice, expense, payment, payroll or journal entry dated on or before {date} can be added, changed or deleted until an administrator unlocks it. A safety backup is made first."): return
        try: self.client.set_books_lock(date)
        except Exception as exc: return messagebox.showerror("Close the books",str(exc))
        self.refresh_books_lock(); self.load_settings_pages()

    def unlock_books(self):
        if not messagebox.askyesno("Close the books","Unlock all periods? Closed months can then be changed again. A safety backup is made first."): return
        try: self.client.set_books_lock("")
        except Exception as exc: return messagebox.showerror("Close the books",str(exc))
        self.books_lock_date.set(""); self.refresh_books_lock(); self.load_settings_pages()

    def save_general_settings(self):
        if self.base_currency.get()==self.second_currency.get(): return messagebox.showwarning("Settings","The two main currencies must be different")
        payload={"base_currency":self.base_currency.get(),"second_currency":self.second_currency.get(),"backup_interval_hours":self.backup_hours.get()}
        payload.update({key:var.get().strip() for key,var in self.company_fields.items()})
        payload["company_vat_registered"]=self.company_vat_registered.get(); payload["company_vat_date"]=self.company_vat_date.get().strip()
        if hasattr(self,"show_tax_tick"): payload["show_tax_tick"]="1" if self.show_tax_tick.get() else "0"  # 2.9.113
        if hasattr(self,"enable_exempt_income"): payload["enable_exempt_income"]="1" if self.enable_exempt_income.get() else "0"
        if hasattr(self,"company_vat_rate"):  # 2.9.72
            if self.company_vat_currency.get()==self.company_vat_second.get(): return messagebox.showwarning("Settings","The two VAT return currencies must be different")
            payload.update(vat_rate=self.company_vat_rate.get().strip(),vat_currency=self.company_vat_currency.get(),vat_second_currency=self.company_vat_second.get())
        try: self.client.save_settings(payload)
        except Exception as exc: return messagebox.showerror("Settings",str(exc))
        self._main_currency_cache=None  # 2.9.71: new documents use the new main currencies at once
        if hasattr(self,"show_tax_tick"):
            import desktop_tax_flag; desktop_tax_flag.set_visible(self.show_tax_tick.get())  # 2.9.113: at once on every screen
            self.exempt_income_enabled=self.enable_exempt_income.get()
            if hasattr(self,"sales_exempt_visibility"): self.sales_exempt_visibility()
        messagebox.showinfo("Settings","Settings saved successfully")
