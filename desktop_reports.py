"""Journal, profit & loss, fiscal year and financial reports screens. (moved out of desktop.py in 2.9.41, unchanged)."""
from __future__ import annotations

from desktop_common import (  # 2.9.102: the names this module uses (no more 'import *')
    bulk_action, chosen_values, datetime, export_excel, export_pdf, filedialog, flow_toolbars, GOLD, json, LIGHT,
    main_currency, messagebox, MultiSelect, natural_sort_value, NAVY, parse_user_date, print_rows, row_matches_search,
    safe_display_date, sortable_date, tk, ttk
)


MUTED = "#5f6b76"
FIN_FILTERS = {"branch": ("Branch", "branch_name"), "project": ("Project", "project_code"), "department": ("Department", "department_code"),
               "party": ("Customer / Supplier", "party_name"), "section": ("Section", "journal_category")}


JOURNAL_SHOWN = 5000


class ReportsMixin:
    def build_journal(self):
        filters=tk.Frame(self.journal_tab,bg=LIGHT); filters.pack(fill="x",padx=10,pady=(10,0))
        tk.Label(filters,text="View Year:",bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left")
        years=[str(item["year"]) for item in getattr(self,"current_company",{}).get("years",[])]
        if not self.journal_view_year.get(): self.journal_view_year.set(str(getattr(self,"current_fiscal_year",datetime.now().year)))
        ttk.Combobox(filters,textvariable=self.journal_view_year,values=years,state="readonly",width=7).pack(side="left",padx=(4,10))
        tk.Label(filters,text="From Date:",bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left")
        self.date_entry(filters,self.journal_from_date,13).pack(side="left",padx=(5,14))
        tk.Label(filters,text="To Date:",bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left")
        self.date_entry(filters,self.journal_to_date,13).pack(side="left",padx=(5,10))
        tk.Label(filters,text="DD-MM-YYYY",bg=LIGHT,fg="#5f6b76").pack(side="left",padx=(0,10))
        tk.Label(filters,text="Sort By:",bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left")
        ttk.Combobox(filters,textvariable=self.journal_sort_by,state="readonly",width=16,
            values=["Date","Voucher Number","Account Number","Account Name","Customer / Supplier","Debit","Credit","Currency"]).pack(side="left",padx=4)
        ttk.Combobox(filters,textvariable=self.journal_sort_order,state="readonly",width=10,
            values=["Ascending","Descending"]).pack(side="left",padx=(0,8))
        ttk.Combobox(filters,textvariable=self.journal_section,state="readonly",width=17,
            values=["All Sections","Payroll","Expenses","Purchases","Sales","Journal Vouchers","Opening / Closing"]).pack(side="left",padx=(0,8))
        tk.Button(filters,text="Apply",command=self.load_journal,bg=GOLD,fg=NAVY,
                  font=("Segoe UI",9,"bold"),border=0,padx=16,pady=6).pack(side="left")
        finder=tk.Frame(self.journal_tab,bg=LIGHT); finder.pack(fill="x",padx=10,pady=(6,0)); self.journal_find=tk.StringVar(); self.journal_find_details=tk.StringVar()
        tk.Label(finder,text="Find voucher No.",bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left")
        number_entry=tk.Entry(finder,textvariable=self.journal_find,width=16); number_entry.pack(side="left",padx=(4,10)); number_entry.bind("<Return>",lambda _event:self.load_journal())
        tk.Label(finder,text="Find in details",bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left")
        details_entry=tk.Entry(finder,textvariable=self.journal_find_details,width=28); details_entry.pack(side="left",padx=(4,10)); details_entry.bind("<Return>",lambda _event:self.load_journal())
        tk.Button(finder,text="Find",command=self.load_journal,bg=GOLD,fg=NAVY,border=0,padx=12,pady=5).pack(side="left",padx=2)
        tk.Button(finder,text="Clear",command=lambda:(self.journal_find.set(""),self.journal_find_details.set(""),self.load_journal()),bg=NAVY,fg="white",
                border=0,padx=10,pady=5).pack(side="left",padx=2)
        for text,mode in (("Print Preview","preview"),("PDF","pdf"),("Print","print")):
            tk.Button(finder,text=text,command=lambda m=mode:self.journal_document(m),bg=NAVY,fg="white",border=0,padx=10,pady=5).pack(side="right",padx=2)
        actions=tk.Frame(self.journal_tab,bg=LIGHT); actions.pack(anchor="w",padx=10,pady=(6,4))
        self.action_button(actions,"Refresh",self.load_journal).pack(side="left",padx=4)
        self.action_button(actions,"Export Excel",lambda:self.journal_report("xlsx")).pack(side="left",padx=4)
        self.action_button(actions,"Export PDF",lambda:self.journal_report("pdf")).pack(side="left",padx=4)
        self.action_button(actions,"Print",lambda:self.journal_report("print")).pack(side="left",padx=4)
        self.action_button(actions,"Check Balance",self.check_unbalanced_entries).pack(side="left",padx=4)
        tk.Button(actions,text="Edit Selected Entry",command=self.edit_journal_selection,bg=GOLD,fg=NAVY,border=0,padx=14,pady=7,font=("Segoe UI",9,"bold")).pack(side="left",padx=4)
        tk.Button(actions,text="Delete Selected Voucher",command=self.delete_selected_journal_voucher,bg="#6B1010",fg="white",border=0,padx=14,pady=7).pack(side="left",padx=4)
        self.journal_totals=tk.Label(actions,text="Debit: 0.00   Credit: 0.00",bg=LIGHT,font=("Segoe UI",10,"bold"))
        self.journal_totals.pack(side="left",padx=15)
        self.journal_tree=self.table(self.journal_tab,[
            ("entry","Entry No.",95),("date","Date",95),("description","Description",190),
            ("source","Source",75),("reference","Reference",75),("currency","Currency",70),
            ("account","Account",85),("account_name","Account Name",190),("party","Customer / Supplier",165),
            ("debit","Debit",105),("credit","Credit",105),("balance","Balance",110)])
        self.journal_tree.bind("<Double-1>",self.edit_journal_selection)  # double-click a line: edit its entry
        self.journal_tree._totals_skip={"balance"}
        self.journal_tree.bind("<Delete>",lambda _event:self.delete_selected_journal_voucher())  # running balance: not added up for the selected lines
        flow_toolbars(filters,finder,actions)  # 2.9.59: wrap instead of being cut off on 1366-px screens
        self.load_journal()

    def check_unbalanced_entries(self):
        """Since 2.9.43 no entry can be saved with Debit different from Credit. This lists entries saved
        before that (by older versions or imports) so they can be corrected with a journal voucher."""
        try: rows=self.client.unbalanced_entries()
        except Exception as exc: return messagebox.showerror("Check Balance",str(exc))
        if not rows: return messagebox.showinfo("Check Balance","All journal entries are balanced (total Debit = total Credit).")
        lines="\n".join(f'{r["entry_number"]}  {safe_display_date(r["entry_date"])}  Debit {r["debit"]}  Credit {r["credit"]}  Difference {r["difference"]}' for r in rows[:30])
        more=f"\n... and {len(rows)-30} more" if len(rows)>30 else ""
        messagebox.showwarning("Check Balance",f"{len(rows)} entr{'y is' if len(rows)==1 else 'ies are'} not balanced (saved before 2.9.43):\n\n{lines}{more}\n\nCorrect them with a Journal Voucher.")

    def journal_date_range(self):
        values=[]
        for label,raw in (("From Date",self.journal_from_date.get()),("To Date",self.journal_to_date.get())):
            value=raw.strip()
            if not value:
                values.append(None); continue
            try: values.append(parse_user_date(value).strftime("%Y-%m-%d"))
            except ValueError:
                messagebox.showwarning("General Journal",f"{label} must use DD-MM-YYYY"); return None
        if values[0] and values[1] and values[0]>values[1]:
            messagebox.showwarning("General Journal","From Date cannot be after To Date"); return None
        return values

    def load_journal(self):
        if not hasattr(self,"journal_tree"): return
        dates=self.journal_date_range()
        if dates is None: return
        currency=None if self.view_currency.get()=="All Currencies" else self.view_currency.get()
        view_year=int(self.journal_view_year.get() or self.current_fiscal_year)
        try: rows=self.client.journal(dates[0],dates[1],currency) if view_year==int(self.current_fiscal_year) else self.client.fiscal_year_journal(view_year,dates[0],dates[1],currency)
        except Exception as exc: return messagebox.showerror("General Journal",str(exc))
        if self.journal_section.get()!="All Sections": rows=[row for row in rows if row.get("journal_category")==self.journal_section.get()]
        number=self.journal_find.get().strip() if hasattr(self,"journal_find") else ""
        if number:
            if number.isdigit(): rows=[row for row in rows if str(row.get("entry_number") or "").rsplit("-",1)[-1].lstrip("0")==number.lstrip("0") or number in str(row.get("entry_number") or "")]
            else: rows=[row for row in rows if number.casefold() in str(row.get("entry_number") or "").casefold()]
        details=self.journal_find_details.get().strip() if hasattr(self,"journal_find_details") else ""
        if details: rows=[row for row in rows if row_matches_search((row.get("description"),row.get("line_description"),row.get("party_name"),row.get("reference"),row.get("account_name")),details)]
        sort_name=self.journal_sort_by.get()
        def journal_key(row):
            if sort_name=="Date": return sortable_date(row.get("entry_date"))
            if sort_name=="Voucher Number": return natural_sort_value(row.get("entry_number"))
            if sort_name=="Account Number": return natural_sort_value(row.get("account_code"))
            if sort_name=="Account Name": return str(row.get("account_name") or "").casefold()
            if sort_name=="Customer / Supplier": return str(row.get("party_name") or "").casefold()
            if sort_name=="Debit": return float(row.get("debit") or 0)
            if sort_name=="Credit": return float(row.get("credit") or 0)
            return str(row.get("currency") or "").casefold()
        rows.sort(key=journal_key,reverse=self.journal_sort_order.get()=="Descending")
        self.journal_rows=rows; self.journal_tree.delete(*self.journal_tree.get_children())
        shown_rows=rows[:JOURNAL_SHOWN]  # 2.9.91: a table of 25,000 lines took seconds to draw; totals and exports keep every line
        for row in shown_rows:
            self.journal_tree.insert("","end",values=(row["entry_number"],row["entry_date"],row["description"],
                "DOE" if row.get("voucher_type")=="07" else row["source_type"],row["source_id"],row["currency"],row["account_code"],row["account_name"],
                row["party_name"],f'{row["debit"]:,.2f}',f'{row["credit"]:,.2f}',f'{row["balance"]:,.2f}'))
        debit=sum(float(row["debit"] or 0) for row in rows); credit=sum(float(row["credit"] or 0) for row in rows)
        state="Balanced" if abs(debit-credit)<0.005 else "UNBALANCED"
        mode="Current Year" if view_year==int(self.current_fiscal_year) else f"{view_year} Read-Only"
        more=f"   (showing the first {JOURNAL_SHOWN:,} of {len(rows):,} lines - narrow the dates or search; totals are for all lines)" if len(rows)>JOURNAL_SHOWN else ""
        self.journal_totals.config(text=f"{mode}   Debit: {debit:,.2f}   Credit: {credit:,.2f}   {state}{more}")

    def delete_selected_journal_voucher(self):
        if int(self.journal_view_year.get() or self.current_fiscal_year)!=int(self.current_fiscal_year): return messagebox.showwarning("General Journal","Previous-year transactions are read-only")
        selected=self.journal_tree.selection()
        if not selected: return messagebox.showwarning("General Journal","Select a Journal Voucher line first")
        numbers=list(dict.fromkeys(str(self.journal_tree.item(iid,"values")[0]) for iid in selected))
        if len(numbers)>1:  # 2.9.69: several vouchers selected: delete them all (system entries are skipped)
            rows={str(item["entry_number"]):item for item in getattr(self,"journal_rows",[])}
            vouchers=[(rows[n]["entry_id"],n) for n in numbers if n in rows and rows[n].get("source_type")=="journal_voucher"]
            skipped=[n for n in numbers if not (n in rows and rows[n].get("source_type")=="journal_voucher")]
            if not vouchers: return messagebox.showwarning("General Journal","None of the selected entries is a Journal Voucher: system entries are changed from their own screen")
            text=f"Delete {len(vouchers)} journal voucher(s) and all their lines?"+(f"\n\n{len(skipped)} other entr(ies) are not vouchers and are kept: {', '.join(skipped[:8])}" if skipped else "")
            if not messagebox.askyesno("Delete Journal Vouchers",text+"\nThis is recorded in the audit log."): return
            bulk_action("Delete Journal Vouchers",vouchers,self.client.delete_journal_voucher)
            self.load_journal(); self.load_invoices(); self.load_dashboard(); self.load_trial(); return
        entry_number=numbers[0]
        row=next((item for item in getattr(self,"journal_rows",[]) if str(item["entry_number"])==entry_number),None)
        if not row: return messagebox.showwarning("General Journal","Selected entry was not found")
        if row.get("source_type")=="year_close":
            year=int(row.get("source_id") or str(row["entry_number"]).split("-")[1])
            if not messagebox.askyesno("Reopen Fiscal Year",f"This is a closing voucher. Reopen fiscal year {year} and remove all its closing entries?"): return
            try: self.client.reopen_fiscal_year(year)
            except Exception as exc: return messagebox.showerror("Reopen Fiscal Year",str(exc))
            self.load_journal(); return messagebox.showinfo("Fiscal Year",f"Fiscal year {year} reopened successfully")
        if row.get("source_type")=="opening":
            if not messagebox.askyesno("Delete Opening Voucher",f'Delete opening voucher {entry_number}? You can recreate it with Refresh Next-Year Opening.'): return
            try: self.client.delete_opening_voucher(row["entry_id"])
            except Exception as exc: return messagebox.showerror("Delete Opening Voucher",str(exc))
            self.load_journal(); self.load_trial(); return messagebox.showinfo("Opening Voucher","Opening voucher deleted")
        if row.get("source_type")!="journal_voucher":
            return messagebox.showwarning("General Journal","This system entry must be cancelled or reversed from its original module")
        if not messagebox.askyesno("Delete Journal Voucher",f"Delete {entry_number} and all its debit/credit lines?\nThis action is recorded in the audit log."): return
        try: self.client.delete_journal_voucher(row["entry_id"])
        except Exception as exc: return messagebox.showerror("Delete Journal Voucher",str(exc))
        self.load_journal(); self.load_invoices(); self.load_dashboard(); self.load_trial(); messagebox.showinfo("General Journal","Journal Voucher deleted")

    def journal_report(self,format_name):
        rows=getattr(self,"journal_rows",[])
        if not rows: return messagebox.showwarning("General Journal","No journal data to export")
        title="Saber Accounting - General Journal"
        headers=["Entry No.","Date","Description","Source","Reference","Currency","Account","Account Name","Customer / Supplier","Debit","Credit","Balance"]
        values=[[r["entry_number"],r["entry_date"],r["description"],r["source_type"],r["source_id"],r["currency"],
                 r["account_code"],r["account_name"],r["party_name"],r["debit"],r["credit"],r["balance"]] for r in rows]
        values.append(["","","","","","","","","TOTAL",sum(float(r["debit"] or 0) for r in rows),sum(float(r["credit"] or 0) for r in rows),""])
        try:
            if format_name=="print": print_rows(title,headers,values); return
            extension=".xlsx" if format_name=="xlsx" else ".pdf"
            path=filedialog.asksaveasfilename(defaultextension=extension,filetypes=[("Excel workbook","*.xlsx")] if format_name=="xlsx" else [("PDF document",
                    "*.pdf")],initialfile="Saber_Accounting_General_Journal"+extension)
            if not path: return
            (export_excel if format_name=="xlsx" else export_pdf)(path,title,headers,values)
            messagebox.showinfo("General Journal",f"Saved successfully:\n{path}")
        except Exception as exc: messagebox.showerror("General Journal",str(exc))

    def build_profit_loss(self):
        year=getattr(self,"current_fiscal_year",datetime.now().year)
        self.pnl_from_date.set(f"01-01-{year}"); self.pnl_to_date.set(f"31-12-{year}"); self.close_year.set(str(year))
        controls=tk.Frame(self.pnl_tab,bg=LIGHT); controls.pack(fill="x",padx=10,pady=(10,4))
        tk.Label(controls,text=f"Fiscal Year {year}",bg=NAVY,fg="white",font=("Segoe UI",10,"bold"),padx=10,pady=4).pack(side="left",padx=(0,10))
        tk.Label(controls,text="From:",bg=LIGHT).pack(side="left")
        self.date_entry(controls,self.pnl_from_date,11).pack(side="left",padx=(4,10))
        tk.Label(controls,text="To:",bg=LIGHT).pack(side="left")
        self.date_entry(controls,self.pnl_to_date,11).pack(side="left",padx=(4,10))
        tk.Button(controls,text="Apply",command=self.load_profit_loss,bg=GOLD,fg=NAVY,border=0,padx=15,pady=6).pack(side="left")
        self.fiscal_status=tk.Label(controls,text="",bg=LIGHT,font=("Segoe UI",9,"bold")); self.fiscal_status.pack(side="left",padx=12)
        closing=tk.LabelFrame(self.pnl_tab,text=f"Year-end closing {year}",bg=LIGHT,padx=8,pady=5); closing.pack(fill="x",padx=10,pady=4)
        self.action_button(closing,"Preview Closing 6&7",self.preview_closing).pack(side="left",padx=(0,4))
        tk.Button(closing,text=f"Close {year} & Open {year+1}",command=self.close_fiscal_year,bg="#8B1E1E",fg="white",border=0,padx=14,pady=7,font=("Segoe UI",9,"bold")).pack(side="left",padx=4)
        tk.Button(closing,text="Delete Closing & Reopen Year",command=self.reopen_fiscal_year,bg=NAVY,fg="white",border=0,padx=12,pady=7).pack(side="left",padx=4)
        tk.Button(closing,text=f"Refresh Opening of {year+1}",command=self.refresh_next_year_opening,bg=NAVY,fg="white",border=0,padx=12,pady=7).pack(side="left",padx=4)
        if (self.current_user or {}).get("role")=="admin":
            tk.Button(closing,text=f"Delete Year {year}",command=self.delete_fiscal_year,bg="#5a0f0f",fg="white",border=0,padx=10,pady=7).pack(side="left",padx=4)
        self.action_button(closing,"Year-End Check",self.show_year_end_check).pack(side="left",padx=4)  # 2.9.81
        tk.Label(closing,text="1 Journal Voucher per currency; result to 138 profit / 139 loss",bg=LIGHT,fg="#5f6b76",wraplength=190,justify="left").pack(side="left",padx=6)
        actions=tk.Frame(self.pnl_tab,bg=LIGHT); actions.pack(side="bottom",pady=(0,8))
        self.pnl_tree=self.table(self.pnl_tab,[("currency","Currency",85),("type","Type",90),("account","Account",100),
            ("name","Account Name",300),("debit","Debit",130),("credit","Credit",130),("amount","P&L Amount",140)])
        self.enable_drill_down(self.pnl_tree,2,lambda:(self.profit_loss_range() or (None,None)))  # 2.9.82: double-click = the entries
        self.action_button(actions,"Export Excel",lambda:self.profit_loss_report("xlsx")).pack(side="left",padx=4)
        self.action_button(actions,"Export PDF",lambda:self.profit_loss_report("pdf")).pack(side="left",padx=4)
        self.action_button(actions,"Print",lambda:self.profit_loss_report("print")).pack(side="left",padx=4)
        self.pnl_totals=tk.Label(actions,text="",bg=LIGHT,font=("Segoe UI",10,"bold")); self.pnl_totals.pack(side="left",padx=15)
        self.load_profit_loss()

    def refresh_fiscal_status(self):
        if not hasattr(self,"fiscal_status"): return
        year=getattr(self,"current_fiscal_year",None)
        record=next((y for y in (getattr(self,"current_company",{}) or {}).get("years",[]) if int(y["year"])==int(year or 0)),{})
        closed=record.get("status")=="closed"
        self.fiscal_status.config(text="CLOSED (read-only) - the P&L is shown before the closing voucher" if closed else "Open",fg="#8B1E1E" if closed else NAVY)

    def delete_fiscal_year(self):
        from tkinter import simpledialog
        year=int(getattr(self,"current_fiscal_year",0))
        answer=simpledialog.askstring("Delete Fiscal Year",f"This deletes ALL the data of {year} for {self.current_company['name']}\n(a backup copy of the file is kept),\n"
            f"and reopens {year-1} so you can close it again.\n\nType DELETE {year} to confirm:",parent=self)
        if (answer or "").strip().upper()!=f"DELETE {year}": return messagebox.showinfo("Delete Fiscal Year","Nothing was deleted")
        try: result=self.client.delete_fiscal_year(year)
        except Exception as exc: return messagebox.showerror("Delete Fiscal Year",str(exc))
        self.current_company=result["company"]
        messagebox.showinfo("Delete Fiscal Year",
                f"{year} deleted. Backup: {result['backup']}\n{result['reopened_year']} is open again (closing removed).\n\nOpen {result['reopened_year']} and close it again to make a new opening.")
        self.company_selection_screen()

    def preview_closing(self):
        year=int(self.close_year.get())
        try: data=self.client.closing_preview(year)
        except Exception as exc: return messagebox.showerror("Closing 6&7",str(exc))
        if not data: return messagebox.showinfo("Closing 6&7",f"There are no expense or revenue balances to close in {year}")
        sections=[]
        for currency,info in data.items():
            rows=[[code,name,round(amount,2) if amount>0 else 0,round(-amount,2) if amount<0 else 0,round(abs(lbp),0)] for code,amount,lbp,_usd,name in info["lines"]]
            rows.append(["","TOTAL",round(sum(r[2] for r in rows),2),round(sum(r[3] for r in rows),2),""])
            sections.append({"heading":f"CLOSING 6&7 - {year} ({currency})   Net result: {info['net_result']:,.2f} {'profit' if info['net_result']>=0 else 'loss'}",
                "headers":["Account","Account Name",f"Debit ({currency})",f"Credit ({currency})","LBP"],"rows":rows,"total_rows":[len(rows)-1]})
        window=tk.Toplevel(self); window.title(f"Preview closing {year}"); self.fit_dialog(window,900,480); window.configure(bg=LIGHT); window.transient(self)
        viewer=self.report_viewer(window); self.show_sections(viewer,sections)
        self.action_button(window,"Close",window.destroy).pack(pady=6)

    def profit_loss_range(self):
        values=[]
        for label,raw in (("From Date",self.pnl_from_date.get()),("To Date",self.pnl_to_date.get())):
            try: values.append(parse_user_date(raw).strftime("%Y-%m-%d"))
            except ValueError: messagebox.showwarning("Profit & Loss",f"{label} must use DD-MM-YYYY"); return None
        if values[0]>values[1]: messagebox.showwarning("Profit & Loss","From Date cannot be after To Date"); return None
        year=str(getattr(self,"current_fiscal_year",values[0][:4]))
        if values[0][:4]!=year or values[1][:4]!=year:
            messagebox.showwarning("Profit & Loss",f"The dates must be inside the selected fiscal year {year}. Use 'Switch Company / Year' to see another year.")
            self.pnl_from_date.set(f"01-01-{year}"); self.pnl_to_date.set(f"31-12-{year}"); return [f"{year}-01-01",f"{year}-12-31"]
        return values

    def load_profit_loss(self):
        if not hasattr(self,"pnl_tree"): return
        dates=self.profit_loss_range()
        if dates is None: return
        currency=None if self.view_currency.get()=="All Currencies" else self.view_currency.get()
        try: rows=self.client.profit_loss(dates[0],dates[1],currency)
        except Exception as exc: return messagebox.showerror("Profit & Loss",str(exc))
        self.pnl_rows=rows; self.pnl_tree.delete(*self.pnl_tree.get_children())
        for row in rows: self.pnl_tree.insert("","end",values=(row["currency"],row["type"],row["code"],row["name_en"],
            f'{row["debit"]:,.2f}',f'{row["credit"]:,.2f}',f'{row["amount"]:,.2f}'))
        totals={}
        for row in rows:
            totals.setdefault(row["currency"],0)
            totals[row["currency"]]+=row["amount"] if row["type"]=="income" else -row["amount"]
        self.pnl_totals.config(text="   ".join(f"{code} Net P&L: {amount:,.2f}" for code,amount in totals.items()) or "No activity")
        self.refresh_fiscal_status()

    def profit_loss_report(self,format_name):
        rows=getattr(self,"pnl_rows",[])
        if not rows: return messagebox.showwarning("Profit & Loss","No data to export")
        title=f"Saber Accounting - Profit & Loss ({self.pnl_from_date.get()} to {self.pnl_to_date.get()})"
        headers=["Currency","Type","Account","Account Name","Debit","Credit","P&L Amount"]
        values=[[r["currency"],r["type"],r["code"],r["name_en"],r["debit"],r["credit"],r["amount"]] for r in rows]
        try:
            if format_name=="print": print_rows(title,headers,values); return
            extension=".xlsx" if format_name=="xlsx" else ".pdf"
            path=filedialog.asksaveasfilename(defaultextension=extension,initialfile="Profit_and_Loss"+extension,
                filetypes=[("Excel workbook","*.xlsx")] if format_name=="xlsx" else [("PDF document","*.pdf")])
            if not path: return
            (export_excel if format_name=="xlsx" else export_pdf)(path,title,headers,values)
            messagebox.showinfo("Profit & Loss",f"Saved successfully:\n{path}")
        except Exception as exc: messagebox.showerror("Profit & Loss",str(exc))

    def close_fiscal_year(self):
        year=int(getattr(self,"current_fiscal_year",self.close_year.get()))
        if not self.show_year_end_check(before_closing=True): return  # 2.9.81: the Year-End Check comes first
        warning=(f"Close fiscal year {year}?\n\n- Any earlier closing of {year} is deleted first.\n- A 'CLOSING 6&7' Journal Voucher is made for each currency (result to 138 profit / 139 loss).\n"
                 f"- {year} becomes read-only and {year+1} is opened with the balance-sheet balances.\n\nYou can undo this with 'Delete Closing & Reopen Year'.")
        if not messagebox.askyesno("Close Fiscal Year",warning): return
        try: result=self.client.close_fiscal_year(year)
        except Exception as exc: return messagebox.showerror("Close Fiscal Year",str(exc))
        self.client.select_company_year(self.current_company["id"],year+1)
        self.current_company=result.get("company",self.current_company); self.current_fiscal_year=year+1
        self.pnl_from_date.set(f"01-01-{year+1}"); self.pnl_to_date.set(f"31-12-{year+1}"); self.close_year.set(str(year+1))
        vouchers=", ".join(result.get("opening_vouchers",[])) or "No opening balance required"
        closing_vouchers=", ".join(result.get("closing_vouchers",[])) or "no P&L balances"
        summary=" / ".join(f"{code}: {amount:,.2f}" for code,amount in result.get("net_results",{}).items()) or "No P&L activity"
        self.main_screen()
        messagebox.showinfo("Fiscal Year",
                f"Year {year} closed.\nClosing 6&7 vouchers: {closing_vouchers}\nYear {year+1} opened for {self.current_company['name']}.\nOpening vouchers: {vouchers}\nNet results: {summary}")

    def reopen_fiscal_year(self):
        year=int(getattr(self,"current_fiscal_year",self.close_year.get()))
        if not messagebox.askyesno("Delete Closing & Reopen",
                f"Delete ALL closing entries of {year} and open it again?\n\nThe opening vouchers of {year+1} are removed too, until you close {year} again."): return
        try: result=self.client.reopen_fiscal_year(year)
        except Exception as exc: return messagebox.showerror("Reopen Fiscal Year",str(exc))
        self.current_company=result.get("company",self.current_company); self.current_fiscal_year=year
        self.client.select_company_year(self.current_company["id"],year); self.main_screen()
        messagebox.showinfo("Fiscal Year",
                f"Fiscal year {year} is open again.\nRemoved closing entries: {result.get('removed_closing_entries',0)}\nRemoved old opening entries: {result.get('removed_opening_entries',0)}")

    def refresh_next_year_opening(self):
        year=int(getattr(self,"current_fiscal_year",self.close_year.get()))
        if not messagebox.askyesno("Refresh Opening",f"Replace the opening vouchers in {year+1} using the latest balances from {year}?"): return
        try: result=self.client.refresh_opening(year)
        except Exception as exc: return messagebox.showerror("Refresh Opening",str(exc))
        status="Provisional because the source year is still open" if result.get("provisional") else "Final from a closed source year"
        messagebox.showinfo("Refresh Opening",f'Opening {year+1} refreshed successfully.\nVouchers: {", ".join(result.get("opening_vouchers",[])) or "No balances"}\n{status}')

    def build_financial_reports(self):
        # 2.9.66: the Ageing Report page lives in Inventory; opening Financial Reports first (before the pages built in the
        # background reached Inventory) failed with "no attribute 'ageing_tab'". Build Inventory first in that case.
        if "ageing_tab" not in self.__dict__:
            pending=self.__dict__.get("_pending_builders") or []
            builder=next((b for b in pending if getattr(b,"__name__","")=="build_inventory"),None)
            if builder is not None: pending.remove(builder); self._run_page_builder(builder)
            if "ageing_tab" not in self.__dict__: self.ageing_tab=tk.Frame(self.reports_tab,bg=LIGHT)
        controls=tk.Frame(self.reports_tab,bg=LIGHT); controls.pack(fill="x",padx=10,pady=10)
        tk.Label(controls,text="From:",bg=LIGHT).pack(side="left"); self.date_entry(controls,self.report_from_date,13).pack(side="left",padx=(4,10))
        tk.Label(controls,text="To:",bg=LIGHT).pack(side="left"); self.date_entry(controls,self.report_to_date,13).pack(side="left",padx=(4,10))
        tk.Label(controls,text="Account From:",bg=LIGHT).pack(side="left"); self.account_search_box(controls,self.report_account_from,16).pack(side="left",padx=(4,6))
        tk.Label(controls,text="To:",bg=LIGHT).pack(side="left"); self.account_search_box(controls,self.report_account_to,16).pack(side="left",padx=(4,10))
        tk.Button(controls,text="Apply",command=self.load_financial_reports,bg=GOLD,fg=NAVY,border=0,padx=15,pady=6).pack(side="left")
        tk.Button(controls,text="Choose filters...",command=self.choose_financial_filters,bg=NAVY,fg="white",border=0,padx=10,pady=6).pack(side="left",padx=6)
        flow_toolbars(controls)
        # 2.9.49: optional filters - only the ones ticked in "Choose filters..." appear (kept on this computer).
        self.fin_filter_row=tk.Frame(self.reports_tab,bg=LIGHT); self.fin_filter_row.pack(fill="x",padx=10,pady=(0,4))
        self.fin_filters={key:tk.StringVar(value="All") for key in FIN_FILTERS}; self.fin_filter_boxes={}
        self.build_financial_filter_row()
        nested=ttk.Notebook(self.reports_tab); nested.pack(fill="both",expand=True,padx=10,pady=(0,10)); self.financial_notebook=nested
        gl=tk.Frame(nested,bg=LIGHT); bs=tk.Frame(nested,bg=LIGHT); vat=tk.Frame(nested,bg=LIGHT); cash=tk.Frame(nested,bg=LIGHT); cash_outlook=tk.Frame(nested,
                bg=LIGHT); aging=self.ageing_tab; comparative=tk.Frame(nested,bg=LIGHT)
        nested.add(gl,text="General Ledger"); nested.add(bs,text="Balance Sheet"); nested.add(vat,text="Lebanese VAT Report"); nested.add(cash,
                text="Cash Flow"); nested.add(cash_outlook,text="Cash Flow Outlook"); nested.add(comparative,
                text="Comparative P&L"); self.ageing_page=aging; self.build_budget_page(nested); self.build_projection_page(nested); self.build_business_reports_page(nested)
        self.build_management_pack_page(nested)  # 2.9.82
        self.ledger_tree=self.table(gl,[("date","Date",95),("entry","Entry",90),("account","Account",85),("currency","Currency",70),("name","Account Name",180),
                ("description","Description",200),("debit","Debit",105),("credit","Credit",105),("balance","Balance",110)])
        self.report_buttons(gl,"ledger"); self.ledger_tree._totals_skip={"balance"}
        self.balance_tree=self.table(bs,[("type","Type",90),("account","Account",90),("currency","Currency",80),("name","Account Name",280),("debit","Debit",
                120),("credit","Credit",120),("balance","Balance",130)])
        self.report_buttons(bs,"balance")
        self.vat_tree=self.table(vat,[("currency","Currency",85),("type","Type",100),("invoices","Count",75),("subtotal","Before VAT",130),("vat","VAT",110),("total","Total",130)])
        self.report_buttons(vat,"vat")
        self.vat_summary=tk.Label(vat,text="",bg=LIGHT,font=("Segoe UI",10,"bold")); self.vat_summary.pack(pady=(0,8))
        self.cash_tree=self.table(cash,[("currency","Currency",90),("category","Cash Flow Category",280),("inflow","Inflow",140),("outflow","Outflow",140),
                ("net","Net Cash Movement",160)]); self.report_buttons(cash,"cash")
        outlook_bar=tk.Frame(cash_outlook,bg=LIGHT); outlook_bar.pack(fill="x",padx=10,pady=8)
        self.cash_outlook_year=tk.StringVar(value=str(self.current_fiscal_year))
        self.cash_outlook_horizon=tk.StringVar(value="Quarter (3 months)")
        tk.Label(outlook_bar,text="Report year",bg=LIGHT,fg=NAVY).pack(side="left")
        tk.Entry(outlook_bar,textvariable=self.cash_outlook_year,width=6).pack(side="left",padx=(4,10))
        tk.Label(outlook_bar,text="Project ahead",bg=LIGHT,fg=NAVY).pack(side="left")
        ttk.Combobox(outlook_bar,textvariable=self.cash_outlook_horizon,values=["Quarter (3 months)","6 Months","Yearly (12 months)"],state="readonly",width=21).pack(side="left",padx=(4,10))
        tk.Label(outlook_bar,text="Projected values use the last 3 complete months.",bg=LIGHT,fg=NAVY).pack(side="left")
        self.action_button(outlook_bar,"Refresh Projection",self.load_cashflow_outlook).pack(side="right")
        self.cash_projection_tree=self.table(cash_outlook,[("month","Period",180),("status","Status",95),("currency","Currency",85),
            ("inflow","Inflow",130),("outflow","Outflow",130),("net","Net cash movement",150)])
        self.report_buttons(cash_outlook,"cash_projection")
        long_cash_bar=tk.Frame(cash_outlook,bg=LIGHT); long_cash_bar.pack(fill="x",padx=10,pady=(0,8))
        self.cash_long_target=tk.StringVar(value=""); self.cash_long_growth=tk.StringVar(value="0"); self.cash_long_growth_by_year=tk.StringVar(value="")
        tk.Label(long_cash_bar,text="5-Year Projection to date (DD-MM-YYYY)",bg=LIGHT,fg=NAVY).pack(side="left")
        tk.Entry(long_cash_bar,textvariable=self.cash_long_target,width=12).pack(side="left",padx=(4,10))
        tk.Label(long_cash_bar,text="Growth % per year",bg=LIGHT,fg=NAVY).pack(side="left")
        tk.Entry(long_cash_bar,textvariable=self.cash_long_growth,width=7).pack(side="left",padx=(4,10))
        tk.Label(long_cash_bar,text="Per-year % (e.g. 2027=10, 2028=5)",bg=LIGHT,fg=NAVY).pack(side="left")
        tk.Entry(long_cash_bar,textvariable=self.cash_long_growth_by_year,width=22).pack(side="left",padx=(4,10))
        self.action_button(long_cash_bar,"5-Year Projection",self.cashflow_long_term_projection).pack(side="left",padx=3)
        tk.Label(long_cash_bar,text="Uses \"Report year\" above as the base year; compounds the growth % each year ahead.",bg=LIGHT,fg=NAVY).pack(side="left",padx=10)
        self.cash_long_tree=self.table(cash_outlook,[("year","Year",70),("up_to","Up to",100),("currency","Currency",85),("source","Source",85),
            ("inflow","Inflow",130),("outflow","Outflow",130),("net","Net cash movement",150)])
        # 2.9.79: cash budget month by month - choose the base year and the % of cash in / cash out
        cash_budget_page=tk.Frame(nested,bg=LIGHT); nested.insert(nested.index(cash_outlook)+1,cash_budget_page,text="Cash Budget")
        budget_bar=tk.LabelFrame(cash_budget_page,text="Cash Budget - from a year + %",bg=LIGHT,padx=8,pady=4); budget_bar.pack(fill="x",padx=10,pady=(8,4))
        fiscal=int(self.current_fiscal_year)
        self.cash_budget_base=tk.StringVar(value=str(fiscal-1)); self.cash_budget_year=tk.StringVar(value=str(fiscal))
        self.cash_budget_in=tk.StringVar(value="10"); self.cash_budget_out=tk.StringVar(value="5")
        years=[str(y) for y in range(fiscal-6,fiscal+6)]
        for label,var,values in (("Base year (actual)",self.cash_budget_base,years[:7]),("Cash budget year",self.cash_budget_year,years[1:])):
            tk.Label(budget_bar,text=label,bg=LIGHT,fg=NAVY).pack(side="left")
            ttk.Combobox(budget_bar,textvariable=var,values=values,width=6).pack(side="left",padx=(4,12))
        for label,var in (("Cash in %",self.cash_budget_in),("Cash out %",self.cash_budget_out)):
            tk.Label(budget_bar,text=label,bg=LIGHT,fg=NAVY).pack(side="left"); tk.Entry(budget_bar,textvariable=var,width=6).pack(side="left",padx=(4,12))
        tk.Button(budget_bar,text="Build Cash Budget",command=self.build_cash_budget,bg=GOLD,fg=NAVY,border=0,padx=14,pady=5,font=("Segoe UI",9,"bold")).pack(side="left",padx=3)
        for label,mode in (("Excel","xlsx"),("PDF","pdf")):
            self.action_button(budget_bar,label,lambda fmt=mode:self.export_cash_budget(fmt)).pack(side="left",padx=2)
        self.cash_budget_info=tk.Label(cash_budget_page,text="Each month of the base year x (1 + %) per year ahead; opening cash = class 5 at the end of the base year (+ the years in between).",
                                       bg=LIGHT,fg=NAVY,anchor="w"); self.cash_budget_info.pack(fill="x",padx=12)
        self.cash_budget_tree=self.table(cash_budget_page,[("month","Month",110),("currency","Currency",80),("opening","Opening cash",140),("inflow","Cash in",130),
            ("outflow","Cash out",130),("net","Net",130),("closing","Closing cash",140)])
        ageing_controls=tk.Frame(aging,bg=LIGHT); ageing_controls.pack(fill="x",padx=8,pady=4)
        self.ageing_kind=tk.StringVar(value="Customers & Suppliers")
        tk.Label(ageing_controls,text="Show",bg=LIGHT).pack(side="left")
        kind_box=ttk.Combobox(ageing_controls,textvariable=self.ageing_kind,values=["Customers & Suppliers","Customers","Suppliers"],state="readonly",width=24)
        kind_box.pack(side="left",padx=6); kind_box.bind("<<ComboboxSelected>>",lambda _e:self.refresh_ageing_tree())
        tk.Label(ageing_controls,text="As of",bg=LIGHT).pack(side="left",padx=(8,2)); self.date_entry(ageing_controls,self.ageing_as_of,12).pack(side="left",padx=3)
        range_row=tk.Frame(aging,bg=LIGHT); range_row.pack(fill="x",padx=8,pady=(0,4))
        choices=[f'{p.get("account_number") or ""} - {p["name"]}' for p in self.client.parties()]
        for label,var in (("Account / Name From",self.ageing_from),("To",self.ageing_to)):
            tk.Label(range_row,text=label,bg=LIGHT).pack(side="left",padx=(6,2))
            ttk.Combobox(range_row,textvariable=var,values=choices,width=27).pack(side="left",padx=(2,8))
        self.action_button(range_row,"Apply",self.load_ageing_report).pack(side="left",padx=4)
        tk.Label(range_row,text="Type a number or name, or choose from the list.",bg=LIGHT,fg="#5f6b76").pack(side="left",padx=8)
        tk.Label(aging,text="Past dates use the current invoice outstanding balance; future dates show the expected lateness if no further payment is made.",
            bg=LIGHT,fg="#5f6b76",anchor="w").pack(fill="x",padx=12)
        self.aging_tree=self.table(aging,[("kind","Type",85),("party","Customer / Supplier",220),("invoice","Invoice",110),("due","Due Date",100),("currency",
                "Currency",75),("outstanding","Outstanding",120),("days","Days Overdue",110),("bucket","Aging Bucket",100)]); self.report_buttons(aging,"aging")
        self.comparative_tree=self.table(comparative,[("currency","Currency",75),("type","Type",85),("account","Account",95),("name","Account Name",260),
                ("current","Current Period",130),("prior","Prior Year",130),("variance","Variance",130)]); self.report_buttons(comparative,"comparative")
        self.enable_drill_down(self.comparative_tree,2,lambda:(self.financial_report_range() or (None,None)))  # 2.9.82
        self.enable_drill_down(self.balance_tree,1,lambda:(None,(self.financial_report_range() or (None,None))[1]))
        self.load_financial_reports()
        self.load_ageing_report()
        self.load_cashflow_outlook()

    # ------------------------------------------------------------ optional filters (2.9.49)
    def _financial_filter_file(self):
        import app_runtime
        return app_runtime.data_dir()/"report_filters.json"

    def shown_financial_filters(self):
        try: chosen=json.loads(self._financial_filter_file().read_text(encoding="utf-8"))
        except Exception: chosen=["branch","party"]
        return [key for key in FIN_FILTERS if key in chosen]

    def build_financial_filter_row(self):
        self._fill_financial_filter_row(); flow_toolbars(self.fin_filter_row)  # 2.9.59: wraps on small screens

    def _fill_financial_filter_row(self):
        for child in self.fin_filter_row.winfo_children(): child.destroy()
        shown=self.shown_financial_filters(); self.fin_filter_boxes={}
        if not shown:
            tk.Label(self.fin_filter_row,text="No filters chosen (Choose filters... to add Branch, Project, Department, Customer / Supplier, Section).",bg=LIGHT,fg=MUTED).pack(side="left"); return
        for key in shown:
            label,_field=FIN_FILTERS[key]
            tk.Label(self.fin_filter_row,text=label,bg=LIGHT).pack(side="left")
            box=MultiSelect(self.fin_filter_row,self.fin_filters[key],width=22 if key=="party" else 15,on_change=self.load_financial_reports,title=label,bg=LIGHT)
            box.pack(side="left",padx=(4,10)); self.fin_filter_boxes[key]=box
        tk.Label(self.fin_filter_row,text="Click a filter to tick one or several values. Filters apply to the General Ledger lines.",bg=LIGHT,fg=MUTED).pack(side="left",padx=6)

    def refresh_financial_filter_choices(self,rows):
        for key,box in getattr(self,"fin_filter_boxes",{}).items():
            field=FIN_FILTERS[key][1]
            values=sorted({str(row.get(field) or "") for row in rows if str(row.get(field) or "").strip()},key=str.casefold)
            if box.winfo_exists(): box["values"]=["All"]+values

    def financial_filter_ok(self,row):
        for key in self.shown_financial_filters():
            wanted={value.casefold() for value in chosen_values(self.fin_filters[key].get())}
            if wanted and str(row.get(FIN_FILTERS[key][1]) or "").strip().casefold() not in wanted: return False
        return True

    def choose_financial_filters(self):
        window=tk.Toplevel(self); window.title("Choose filters"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        shown=set(self.shown_financial_filters()); flags={key:tk.BooleanVar(value=key in shown) for key in FIN_FILTERS}
        tk.Label(window,text="Tick the filters you want to see above the financial reports:",bg=LIGHT,fg=NAVY,font=("Segoe UI",10,"bold")).pack(anchor="w",padx=14,pady=(12,6))
        for key,(label,_field) in FIN_FILTERS.items(): tk.Checkbutton(window,text=label,variable=flags[key],bg=LIGHT).pack(anchor="w",padx=24)
        def save():
            chosen=[key for key,var in flags.items() if var.get()]
            try: self._financial_filter_file().write_text(json.dumps(chosen),encoding="utf-8")
            except OSError as exc: return messagebox.showerror("Filters",str(exc),parent=window)
            for key in FIN_FILTERS:
                if key not in chosen: self.fin_filters[key].set("All")
            window.destroy(); self.build_financial_filter_row(); self.load_financial_reports()
        buttons=tk.Frame(window,bg=LIGHT); buttons.pack(pady=12)
        tk.Button(buttons,text="Save",command=save,bg=GOLD,fg=NAVY,border=0,padx=20,pady=6,font=("Segoe UI",9,"bold")).pack(side="left",padx=4)
        tk.Button(buttons,text="Cancel",command=window.destroy,bg=NAVY,fg="white",border=0,padx=14,pady=6).pack(side="left",padx=4)
        window.bind("<Escape>",lambda _e:window.destroy())

    def report_buttons(self,parent,report):
        frame=tk.Frame(parent,bg=LIGHT); frame.pack(pady=(0,8))
        self.action_button(frame,"Excel",lambda:self.financial_report_export(report,"xlsx")).pack(side="left",padx=4)
        self.action_button(frame,"PDF",lambda:self.financial_report_export(report,"pdf")).pack(side="left",padx=4)
        self.action_button(frame,"Print",lambda:self.financial_report_export(report,"print")).pack(side="left",padx=4)

    def financial_report_range(self):
        values=[]
        for raw in (self.report_from_date.get(),self.report_to_date.get()):
            try: values.append(parse_user_date(raw).strftime("%Y-%m-%d"))
            except ValueError: messagebox.showwarning("Financial Reports","Dates must use DD-MM-YYYY"); return None
        if values[0]>values[1]: messagebox.showwarning("Financial Reports","From Date cannot be after To Date"); return None
        return values

    def load_financial_reports(self):
        if not hasattr(self,"ledger_tree"): return
        dates=self.financial_report_range()
        if dates is None: return
        currency=None if self.view_currency.get()=="All Currencies" else self.view_currency.get()
        try:
            ledger=self.client.general_ledger(None,dates[0],dates[1],currency)
            balance=self.client.balance_sheet(dates[1],currency)
            # 2.9.63: a user without the VAT right still gets the ledger, balance sheet and cash flow (the whole page failed)
            vat=self.client.vat_report(dates[0],dates[1],currency) if self.can_use("vat") else {"items":[],"summary":[],"_hidden":True}
            cash=self.client.cash_flow(dates[0],dates[1],currency)
            comparative=self.client.comparative_reports(dates[0],dates[1],currency)
        except Exception as exc: return messagebox.showerror("Financial Reports",str(exc))
        account_from=self.report_account_from.get().split(" - ",1)[0].strip(); account_to=self.report_account_to.get().split(" - ",1)[0].strip()
        def in_account_range(code):
            digits=int(''.join(c for c in str(code) if c.isdigit()) or 0)
            low=int(''.join(c for c in account_from if c.isdigit()) or 0); high=int(''.join(c for c in account_to if c.isdigit()) or 999999999999)
            return low<=digits<=high
        self.refresh_financial_filter_choices(ledger["items"])
        self.ledger_rows=[row for row in ledger["items"] if in_account_range(row["account_code"]) and self.financial_filter_ok(row)]; self.balance_rows=[row for row in balance if in_account_range(row["code"])]; self.vat_rows=vat["items"]; self.cash_rows=cash; self.comparative_rows=comparative["items"]
        self.ledger_tree.delete(*self.ledger_tree.get_children()); self.balance_tree.delete(*self.balance_tree.get_children()); self.vat_tree.delete(*self.vat_tree.get_children()); self.cash_tree.delete(*self.cash_tree.get_children()); self.comparative_tree.delete(*self.comparative_tree.get_children())
        for r in self.ledger_rows: self.ledger_tree.insert("","end",values=(r["entry_date"],r["entry_number"],r["account_code"],r["currency"],r["account_name"],
                r["description"],f'{r["debit"]:,.2f}',f'{r["credit"]:,.2f}',f'{r["balance"]:,.2f}'))
        for r in balance: self.balance_tree.insert("","end",values=(r["type"],r["code"],r["currency"],r["name_en"],f'{r["debit"]:,.2f}',f'{r["credit"]:,.2f}',f'{r["balance"]:,.2f}'))
        for r in self.vat_rows: self.vat_tree.insert("","end",values=(r["currency"],r["kind"],r["invoices"],f'{r["subtotal"] or 0:,.2f}',f'{r["vat"] or 0:,.2f}',f'{r["total"] or 0:,.2f}'))
        for r in self.cash_rows: self.cash_tree.insert("","end",values=(r["currency"],r["category"],f'{r["inflow"]:,.2f}',f'{r["outflow"]:,.2f}',f'{r["net"]:,.2f}'))
        for r in self.comparative_rows: self.comparative_tree.insert("","end",values=(r["currency"],r["type"],r["code"],r["name_en"],f'{r["current"]:,.2f}',
                f'{r["prior"]:,.2f}',f'{r["variance"]:,.2f}'))
        self.vat_summary.config(text="VAT figures need the VAT right (ask the administrator)." if vat.get("_hidden") else
                                "   ".join(f'{r["currency"]} VAT payable: {r["vat_payable"]:,.2f}' for r in vat["summary"]) or "No VAT activity")

    def load_ageing_report(self):
        try: as_of=parse_user_date(self.ageing_as_of.get()).strftime("%Y-%m-%d")
        except ValueError: return messagebox.showwarning("Ageing Report","As of date must use DD-MM-YYYY")
        currency=None if self.view_currency.get()=="All Currencies" else self.view_currency.get()
        try: self.aging_rows=self.client.aging(as_of,None,currency)
        except Exception as exc: return messagebox.showerror("Ageing Report",str(exc))
        self.refresh_ageing_tree()

    def visible_ageing_rows(self):
        choice = self.ageing_kind.get()
        rows=[r for r in getattr(self,"aging_rows",[]) if choice=="Customers & Suppliers" or (r["kind"]=="sale")== (choice=="Customers")]
        lower=self.ageing_from.get().strip(); upper=self.ageing_to.get().strip()
        if lower and not upper and " - " not in lower:
            needle=lower.casefold()
            return [row for row in rows if needle in str(row.get("account_number") or "").casefold() or needle in str(row.get("party_name") or "").casefold()]
        def bound(value):
            if not value: return None
            code=value.split(" - ",1)[0].strip()
            if code.isdigit(): return ("account",code)
            match=next((r for r in rows if (r.get("party_name") or "").casefold()==value.casefold()),None)
            if match: return ("account",match.get("account_number") or "") if match.get("account_number") else ("name",value.casefold())
            return ("name",value.casefold())
        start,end=bound(lower),bound(upper)
        if start and end and start[0]!=end[0]: return []
        for edge,is_lower in ((start,True),(end,False)):
            if not edge: continue
            key="account_number" if edge[0]=="account" else "party_name"
            rows=[r for r in rows if (str(r.get(key) or "").casefold()>=edge[1] if is_lower else str(r.get(key) or "").casefold()<=edge[1])]
        return rows

    def refresh_ageing_tree(self):
        self.aging_tree.delete(*self.aging_tree.get_children())
        for r in self.visible_ageing_rows():
            self.aging_tree.insert("","end",values=("Receivable" if r["kind"]=="sale" else "Payable",r["party_name"],r["invoice_number"],
                    r.get("due_date") or r["invoice_date"],r["currency"],f'{r["outstanding"]:,.2f}',r["days_overdue"],r["bucket"]))

    def load_cashflow_outlook(self):
        from financial_projection import HORIZONS, completed_months, future_months, month_range, trailing_average
        try:
            year=int(self.cash_outlook_year.get()); last=completed_months(year)
            future=future_months(year,last,HORIZONS[self.cash_outlook_horizon.get()])
        except (ValueError,KeyError) as exc: return messagebox.showwarning("Cash Flow Outlook",str(exc))
        currency=None if self.view_currency.get()=="All Currencies" else self.view_currency.get()
        history={}; currencies=set()
        try:
            for month in range(1,last+1):
                start,end=month_range(year,month)
                rows=self.client.cash_flow(start,end,currency,convert=bool(currency))
                for row in rows:
                    key=row["currency"]; currencies.add(key)
                    values=history.setdefault((key,month),{"inflow":0.0,"outflow":0.0})
                    values["inflow"]+=float(row["inflow"]); values["outflow"]+=float(row["outflow"])
        except Exception as exc: return messagebox.showerror("Cash Flow Outlook",str(exc))
        self.cash_projection_rows=[]
        if not currencies: currencies={currency or "USD"}
        for code in sorted(currencies):
            actual_total={"inflow":0.0,"outflow":0.0}
            for month in range(1,last+1):
                values=history.get((code,month),{"inflow":0.0,"outflow":0.0})
                for key in actual_total: actual_total[key]+=values[key]
                self.cash_projection_rows.append({"month":f"{year}-{month:02d}","status":"Actual","currency":code,**values,
                    "net":values["inflow"]-values["outflow"]})
            self.cash_projection_rows.append({"month":f"{year} actual total (Jan–{last:02d})","status":"Actual total","currency":code,**actual_total,
                "net":actual_total["inflow"]-actual_total["outflow"]})
            monthly={month:history.get((code,month),{}) for month in range(1,last+1)}
            average={key:trailing_average(monthly,last,key) for key in ("inflow","outflow")}
            for projected_year,projected_month in future:
                self.cash_projection_rows.append({"month":f"{projected_year}-{projected_month:02d}","status":"Projected","currency":code,**average,
                    "net":average["inflow"]-average["outflow"]})
            totals={key:average[key]*len(future) for key in average}
            self.cash_projection_rows.append({"month":f"{future[0][0]}-{future[0][1]:02d} to {future[-1][0]}-{future[-1][1]:02d}",
                "status":"Forecast total","currency":code,**totals,"net":totals["inflow"]-totals["outflow"]})
        self.cash_projection_tree.delete(*self.cash_projection_tree.get_children())
        for row in self.cash_projection_rows:
            self.cash_projection_tree.insert("","end",values=(row["month"],row["status"],row["currency"],
                f'{row["inflow"]:,.2f}',f'{row["outflow"]:,.2f}',f'{row["net"]:,.2f}'))

    def build_cash_budget(self):
        """2.9.79: monthly cash budget of the chosen year from the base year's cash flow and the % typed."""
        from financial_projection import cash_budget, month_range
        try:
            base=int(self.cash_budget_base.get()); target=int(self.cash_budget_year.get())
            cash_budget({},0,base,target,self.cash_budget_in.get(),self.cash_budget_out.get())  # checks the years and the %
        except ValueError as exc: return messagebox.showwarning("Cash Budget",str(exc))
        # 2.9.80: one cash budget with every currency converted (All Currencies = the company's main currency 1);
        # opening balances and year closings are not cash movements
        currency=main_currency(self,1) if self.view_currency.get()=="All Currencies" else self.view_currency.get()
        flows={}; opening={}
        try:
            for month in range(1,13):
                start,end=month_range(base,month)
                try: rows=self.client.fiscal_year_cash_flow(base,start,end,currency,convert=bool(currency))
                except Exception: rows=self.client.cash_flow(start,end,currency,convert=bool(currency))
                for row in rows:
                    values=flows.setdefault(row["currency"],{}).setdefault(month,{"inflow":0.0,"outflow":0.0})
                    values["inflow"]+=float(row["inflow"] or 0); values["outflow"]+=float(row["outflow"] or 0)
            try: balance=self.client.fiscal_year_balance_sheet(base,f"{base}-12-31",currency,convert=bool(currency))
            except Exception: balance=self.client.balance_sheet(f"{base}-12-31",currency,convert=bool(currency))
            for row in balance:
                if str(row.get("code") or "").startswith("5"):
                    code=row.get("currency") or currency or "USD"; opening[code]=opening.get(code,0.0)+float(row.get("balance") or 0)
        except Exception as exc: return messagebox.showerror("Cash Budget",str(exc))
        if not flows: return messagebox.showwarning("Cash Budget",f"No cash movement in {base} to build the cash budget from")
        self.cash_budget_rows=[]; notes=[]
        for code in sorted(flows):
            result=cash_budget(flows[code],opening.get(code,0.0),base,target,self.cash_budget_in.get(),self.cash_budget_out.get())
            self.cash_budget_rows+= [{**row,"currency":code} for row in result["rows"]]
            self.cash_budget_rows.append({"month":f"{target} total","currency":code,"opening":result["opening"],**result["totals"],"closing":result["closing"]})
            notes.append(f"{code}: lowest cash {result['lowest']['closing']:,.2f} in {result['lowest']['month']}"+("  - NEGATIVE, plan financing" if result["lowest"]["closing"]<0 else ""))
        self.cash_budget_tree.delete(*self.cash_budget_tree.get_children())
        for row in self.cash_budget_rows:
            self.cash_budget_tree.insert("","end",values=(row["month"],row["currency"],f'{row["opening"]:,.2f}',f'{row["inflow"]:,.2f}',
                    f'{row["outflow"]:,.2f}',f'{row["net"]:,.2f}',f'{row["closing"]:,.2f}'))
        self.cash_budget_info.config(text=f"Cash budget {target} from {base} actuals: cash in {self.cash_budget_in.get()}%, cash out {self.cash_budget_out.get()}% per year.   "+"   |   ".join(notes),
                                     fg="#8B1E1E" if any("NEGATIVE" in n for n in notes) else NAVY)

    def export_cash_budget(self,format_name):
        rows=getattr(self,"cash_budget_rows",None)
        if not rows: return messagebox.showwarning("Cash Budget","Build the cash budget first")
        sections=[{"heading":"Cash budget by month","headers":["Month","Currency","Opening cash","Cash in","Cash out","Net","Closing cash"],
                   "rows":[[r["month"],r["currency"],r["opening"],r["inflow"],r["outflow"],r["net"],r["closing"]] for r in rows],
                   "total_rows":[i for i,r in enumerate(rows) if str(r["month"]).endswith("total")]}]
        meta=[f"Base year: {self.cash_budget_base.get()} actual cash flow",f"Cash in: {self.cash_budget_in.get()}% per year   Cash out: {self.cash_budget_out.get()}% per year",
              "Opening cash = class 5 accounts at the end of the base year (+ the projected years in between). A budget is an estimate."]
        self.save_sections(f"Cash Budget {self.cash_budget_year.get()}",meta,sections,f"Cash_Budget_{self.cash_budget_year.get()}",format_name)

    def _parse_growth_by_year(self,text):
        """Parse 'YYYY=rate%' pairs (comma/semicolon separated) into {year: decimal_rate}. Empty -> {}."""
        result={}
        for part in str(text or "").replace(";",",").split(","):
            part=part.strip()
            if not part: continue
            for sep in ("=",":"):
                if sep in part: key,_,value=part.partition(sep); break
            else: raise ValueError(f"Use YYYY=rate for per-year growth, not '{part}'")
            try: year=int(key.strip()); rate=float(value.strip().rstrip("%"))/100
            except ValueError: raise ValueError(f"Invalid per-year growth entry '{part}'")
            result[year]=rate
        return result

    def cashflow_long_term_projection(self):
        from financial_projection import long_term_projection
        try: base_year=int(self.cash_outlook_year.get())
        except ValueError: return messagebox.showwarning("5-Year Projection","Enter the base year in \"Report year\", for example 2026")
        try: target_date=datetime.strptime(self.cash_long_target.get().strip(),"%d-%m-%Y").strftime("%Y-%m-%d")
        except ValueError: return messagebox.showwarning("5-Year Projection","Enter the target date as DD-MM-YYYY, for example 31-12-2030")
        try: growth_rate=float(self.cash_long_growth.get() or 0)/100
        except ValueError: growth_rate=0
        try: growth_by_year=self._parse_growth_by_year(self.cash_long_growth_by_year.get())
        except ValueError as exc: return messagebox.showwarning("5-Year Projection",str(exc))
        currency=None if self.view_currency.get()=="All Currencies" else self.view_currency.get()
        try: actual_rows=self.client.cash_flow(f"01-01-{base_year}",f"31-12-{base_year}",currency,convert=bool(currency))
        except Exception as exc: return messagebox.showerror("5-Year Projection",str(exc))
        base_by_currency={}
        for row in actual_rows:
            values=base_by_currency.setdefault(row["currency"],{"inflow":0.0,"outflow":0.0})
            values["inflow"]+=float(row["inflow"]); values["outflow"]+=float(row["outflow"])
        if not base_by_currency: return messagebox.showwarning("5-Year Projection",f"No cash flow actuals in {base_year} to project from")
        rows=[]
        for code,base_values in sorted(base_by_currency.items()):
            try: projection=long_term_projection(base_values,base_year,target_date,growth_rate,growth_by_year=growth_by_year)
            except ValueError as exc: return messagebox.showwarning("5-Year Projection",str(exc))
            for entry in projection:
                inflow=entry["values"]["inflow"]; outflow=entry["values"]["outflow"]
                rows.append({"year":entry["year"],"up_to":entry["date_to"],"currency":code,"source":entry["source"].title(),
                    "inflow":inflow,"outflow":outflow,"net":inflow-outflow})
        self.cash_long_tree.delete(*self.cash_long_tree.get_children())
        for row in rows:
            self.cash_long_tree.insert("","end",values=(row["year"],row["up_to"],row["currency"],row["source"],
                f'{row["inflow"]:,.2f}',f'{row["outflow"]:,.2f}',f'{row["net"]:,.2f}'))
        if not rows: messagebox.showinfo("5-Year Projection","No rows to project (check the base year and target date)")

    def financial_report_export(self,report,format_name):
        if report=="ledger": title="General Ledger"; headers=["Date","Entry","Account","Currency","Name","Description","Debit","Credit",
                "Balance"]; rows=[[r["entry_date"],r["entry_number"],r["account_code"],r["currency"],r["account_name"],r["description"],r["debit"],r["credit"],
                r["balance"]] for r in getattr(self,"ledger_rows",[])]
        elif report=="balance": title="Balance Sheet"; headers=["Type","Account","Currency","Name","Debit","Credit","Balance"]; rows=[[r["type"],r["code"],
                r["currency"],r["name_en"],r["debit"],r["credit"],r["balance"]] for r in getattr(self,"balance_rows",[])]
        elif report=="vat": title="Lebanese VAT Report"; headers=["Currency","Type","Count","Before VAT","VAT","Total"]; rows=[[r["currency"],r["kind"],
                r["invoices"],r["subtotal"],r["vat"],r["total"]] for r in getattr(self,"vat_rows",[])]
        elif report=="cash": title="Cash Flow"; headers=["Currency","Category","Inflow","Outflow","Net"]; rows=[[r["currency"],r["category"],r["inflow"],
                r["outflow"],r["net"]] for r in getattr(self,"cash_rows",[])]
        elif report=="cash_projection": title="Cash Flow Actual and Projection"; headers=["Month","Status","Currency","Inflow","Outflow",
                "Net"]; rows=[[r["month"],r["status"],r["currency"],r["inflow"],r["outflow"],r["net"]] for r in getattr(self,"cash_projection_rows",[])]
        elif report=="aging": title=f"Customer and Supplier Ageing as of {self.ageing_as_of.get()}"; headers=["Type","Party","Invoice","Due Date","Currency",
                "Outstanding","Days Overdue","Bucket"]; rows=[["Receivable" if r["kind"]=="sale" else "Payable",r["party_name"],r["invoice_number"],
                r.get("due_date") or r["invoice_date"],r["currency"],r["outstanding"],r["days_overdue"],r["bucket"]] for r in self.visible_ageing_rows()]
        else: title="Comparative Profit and Loss"; headers=["Currency","Type","Account","Name","Current Period","Prior Year","Variance"]; rows=[[r["currency"],
                r["type"],r["code"],r["name_en"],r["current"],r["prior"],r["variance"]] for r in getattr(self,"comparative_rows",[])]
        if not rows: return messagebox.showwarning(title,"No data to export")
        try:
            if format_name=="print": print_rows(title,headers,rows); return
            extension=".xlsx" if format_name=="xlsx" else ".pdf"; path=filedialog.asksaveasfilename(defaultextension=extension,initialfile=title.replace(" ","_")+extension)
            if not path: return
            (export_excel if format_name=="xlsx" else export_pdf)(path,title,headers,rows); messagebox.showinfo(title,f"Saved successfully:\n{path}")
        except Exception as exc: messagebox.showerror(title,str(exc))
