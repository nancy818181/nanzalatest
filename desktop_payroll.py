"""Payroll and employees screens. (moved out of desktop.py in 2.9.41, unchanged)."""
from __future__ import annotations
import logging

from desktop_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, Decimal, filedialog, formatted_user_date, GOLD, json, LIGHT, messagebox, NAVY, os, parse_user_date,
    safe_display_date, tk, ttk
)


class PayrollMixin:
    def build_payroll(self):
        nested=ttk.Notebook(self.payroll_tab); nested.pack(fill="both",expand=True,padx=8,pady=8); self.payroll_notebook=nested
        employees=tk.Frame(nested,bg=LIGHT); run=tk.Frame(nested,
                bg=LIGHT); settings_outer,settings_page=self.scrollable_page(nested); reports_page=tk.Frame(nested,bg=LIGHT); forms_page=tk.Frame(nested,
                bg=LIGHT)
        self.payroll_employees_page=employees
        self.cnss_forms_page=forms_page
        nested.add(employees,text="Employees"); nested.add(run,text="Payroll Entry"); nested.add(reports_page,
                text="Payroll Reports & Worksheets (R5 / R6 / R10)"); nested.add(forms_page,text="NSSF & MOF Forms (Excel)"); nested.add(settings_outer,
                text="Tax & NSSF Settings")
        extras_page=tk.Frame(nested,bg=LIGHT); nested.insert(2,extras_page,text="End of Service & Leave"); self.build_payroll_extras_page(extras_page)  # 2.9.82
        employee_actions=tk.Frame(employees,bg=LIGHT); employee_actions.pack(fill="x",padx=10,pady=8)
        self.action_button(employee_actions,"New Employee",lambda:self.employee_dialog()).pack(side="left",padx=4)
        self.action_button(employee_actions,"Edit Selected",self.edit_selected_employee).pack(side="left",padx=4)
        # 2.9.49 (owner request): the R3 / R3-1 worksheets and CNSS Employee Forms buttons are removed; the same forms are in "Official Forms (Excel)".
        
        nssf_forms=tk.Frame(employees,bg=LIGHT); nssf_forms.pack(fill="x",padx=10,pady=(0,5))
        tk.Label(nssf_forms,text="NSSF employee forms:",bg=LIGHT,fg=NAVY,font=("Segoe UI",9,"bold")).pack(side="left",padx=4)
        self.action_button(nssf_forms,"Employment Declaration Worksheet",lambda:self.employee_nssf_declaration("hire","preview")).pack(side="left",padx=4)
        self.action_button(nssf_forms,"Termination Declaration Worksheet",lambda:self.employee_nssf_declaration("leave","preview")).pack(side="left",padx=4)
        tk.Button(employee_actions,text="Official Forms (Excel)",command=self.official_excel_form,bg=GOLD,fg=NAVY,border=0,padx=12,pady=7,font=("Segoe UI",9,"bold")).pack(side="left",padx=4)
        self.action_button(employee_actions,"Refresh",self.load_payroll).pack(side="left",padx=4)
        self.employee_tree=self.table(employees,[("number","Employee ID",105),("name","Employee Name",220),("job","Job Title",150),
            ("start","Starting Date",110),("leaving","Leaving Date",110),("branch","Branch",120),("currency","Currency",70),
            ("salary","Base Salary",120),("nssf","NSSF Number",120),("active","Active",65)])
        self.employee_tree.bind("<Double-1>",lambda _event:self.edit_selected_employee())

        form=tk.LabelFrame(run,text="Monthly Payroll",bg=LIGHT); form.pack(fill="x",padx=10,pady=8)
        self.payroll_employee=tk.StringVar(); self.payroll_period=tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.payroll_vars={name:tk.StringVar(value="0") for name in ("salary","transport","overtime","commission","retro_salary","schooling","bonus","thirteenth_month","director_remuneration")}
        self.payroll_family_override=tk.StringVar()
        self.payroll_retro_from=tk.StringVar(); self.payroll_retro_to=tk.StringVar()
        tk.Label(form,text="Employee",bg=LIGHT).grid(row=0,column=0,padx=6,pady=5,sticky="w")
        self.payroll_employee_combo=ttk.Combobox(form,textvariable=self.payroll_employee,state="readonly",width=26); self.payroll_employee_combo.grid(row=0,column=1,padx=6,pady=5,sticky="w")
        self.payroll_employee_combo.bind("<<ComboboxSelected>>",lambda _event:self.payroll_employee_chosen())
        tk.Label(form,text="Period Date",bg=LIGHT).grid(row=0,column=2,padx=6,pady=5,sticky="w"); self.date_entry(form,self.payroll_period,14).grid(row=0,column=3,padx=6,pady=5,sticky="w")
        labels=(("salary","Salary"),("transport","Transport"),("overtime","Overtime"),("commission","Commission"),("retro_salary","Retroactive Salary"),
                ("schooling","Schooling"),("bonus","Bonus"),("thirteenth_month","13th Month"),("director_remuneration","Director Remuneration (not taxable)"))
        for index,(key,label) in enumerate(labels):
            row=1+index//3; column=(index%3)*2
            tk.Label(form,text=label,bg=LIGHT).grid(row=row,column=column,padx=6,pady=4,sticky="w")
            tk.Entry(form,textvariable=self.payroll_vars[key],width=16).grid(row=row,column=column+1,padx=6,pady=4,sticky="w")
        tk.Label(form,text="Retro From",bg=LIGHT).grid(row=4,column=0,padx=6,pady=4,sticky="w"); self.date_entry(form,self.payroll_retro_from,14).grid(row=4,column=1,padx=6,pady=4,sticky="w")
        tk.Label(form,text="Retro To",bg=LIGHT).grid(row=4,column=2,padx=6,pady=4,sticky="w"); self.date_entry(form,self.payroll_retro_to,14).grid(row=4,column=3,padx=6,pady=4,sticky="w")
        self.payroll_transport_days=tk.StringVar()
        tk.Label(form,text="Transport Days",bg=LIGHT).grid(row=4,column=4,padx=6,pady=4,sticky="w"); days_entry=tk.Entry(form,
                textvariable=self.payroll_transport_days,width=6); days_entry.grid(row=4,column=5,padx=6,pady=4,sticky="w")
        # Typing the transport days fills Transport at once: days x the daily transport of the period (Tax & NSSF Settings).
        days_entry.bind("<KeyRelease>",lambda _event:self.payroll_transport_from_days(),add="+"); days_entry.bind("<FocusOut>",lambda _event:self.payroll_transport_from_days(),add="+")
        tk.Label(form,text="Family Allocation",bg=LIGHT).grid(row=4,column=6,padx=6,pady=4,sticky="w")
        family_entry=tk.Entry(form,textvariable=self.payroll_family_override,width=12); family_entry.grid(row=4,column=7,padx=6,pady=4,sticky="w")
        # The automatic family allocation appears here as soon as the employee / period is chosen; typing in it
        # makes it a manual amount for this payroll (Calculate / Save use it).
        self._family_manual=False
        family_entry.bind("<KeyRelease>",lambda event:setattr(self,"_family_manual",True) if len(event.keysym)==1 or event.keysym in ("BackSpace","Delete") else None,add="+")
        period_widgets=[w for w in form.grid_slaves(row=0,column=3)]
        for widget in period_widgets: widget.bind("<FocusOut>",lambda _event:self.payroll_family_auto(),add="+")
        self.payroll_breakdown=tk.Label(form,text="",bg=LIGHT,fg="#5f6b76",anchor="w",justify="left",wraplength=1060); self.payroll_breakdown.grid(row=6,column=0,columnspan=8,padx=6,sticky="w")
        self.payroll_notes=tk.Label(form,text="",bg=LIGHT,fg="#8B1E1E",anchor="w",justify="left",font=("Segoe UI",9,"bold"),
                wraplength=1060); self.payroll_notes.grid(row=7,column=0,columnspan=8,padx=6,sticky="w")
        self.payroll_result=tk.StringVar(value="Gross: 0 | Tax: 0 | Employee NSSF: 0 | Net: 0")
        tk.Label(form,textvariable=self.payroll_result,bg=LIGHT,fg=NAVY,font=("Segoe UI",10,"bold"),wraplength=1000,justify="left").grid(row=5,column=0,columnspan=8,padx=6,pady=6,sticky="w")
        for variable in (self.payroll_employee,self.payroll_period,*self.payroll_vars.values(),self.payroll_transport_days):
            variable.trace_add("write",self.mark_payroll_stale)
        buttons=tk.Frame(form,bg=LIGHT); buttons.grid(row=0,column=4,columnspan=4,sticky="w",padx=6)
        self.action_button(buttons,"Schooling Law",self.schooling_law_dialog).pack(side="left",padx=3)
        self.action_button(buttons,"Calculate",self.calculate_payroll).pack(side="left",padx=3)
        tk.Button(buttons,text="Save Payroll",command=self.save_payroll,bg=GOLD,fg=NAVY,border=0,padx=15,pady=7,font=("Segoe UI",9,"bold")).pack(side="left",padx=3)
        payroll_actions=tk.Frame(run,bg=LIGHT); payroll_actions.pack(fill="x",padx=10)
        self.action_button(payroll_actions,"Post Selected to Accounting",self.post_selected_payroll).pack(side="left",padx=4,pady=3)
        tk.Button(payroll_actions,text="Monthly Payroll Sheet | الحركة الشهرية",command=self.open_payroll_sheet,bg=GOLD,fg=NAVY,border=0,padx=12,pady=6,
                font=("Segoe UI",9,"bold")).pack(side="left",padx=4,pady=3)
        self.payroll_tree=self.table(run,[("number","Payroll No.",135),("period","Period",95),("employee","Employee",190),("currency","Currency",65),
            ("gross","Gross",105),("tax","Tax",95),("nssf","Employee NSSF",110),("net","Net Salary",110),("status","Status",75)])
        self.payroll_setting_vars={key:tk.StringVar() for key in ("date_from","date_to","single_allowance","spouse_allowance","child_allowance",
                "employee_nssf_rate","medical_rate","end_service_rate","family_rate","employee_ceiling","medical_ceiling","family_ceiling",
                "end_service_ceiling","salary_account","salary_payable_account","payroll_tax_account","nssf_payable_account",
            "max_children_deduction","transport_daily_exempt","default_transport_days","schooling_annual_exempt","schooling_max_children",
                    "schooling_public_child","schooling_public_cap","schooling_private_child","schooling_private_cap","tax_rounding","minimum_wage",
                    "family_allowance_spouse","family_allowance_child","family_allowance_cap","family_allowance_max_children")}
        setting_labels=(("date_from","Date From"),("date_to","Date To"),("single_allowance","Single Allowance"),("spouse_allowance","Spouse Allowance"),
                ("child_allowance","Child Allowance"),("employee_nssf_rate","Employee NSSF Rate"),("medical_rate","Employer Medical Rate"),("end_service_rate",
                "End Service Rate"),("family_rate","Family Rate"),("employee_ceiling","Employee NSSF Ceiling"),("medical_ceiling","Medical Ceiling"),
                ("family_ceiling","Family Ceiling"),("end_service_ceiling","End Service Ceiling"),("salary_account","Salary Expense Account"),
                ("salary_payable_account","Salary Payable Account"),("payroll_tax_account","Payroll Tax Account"),("nssf_payable_account",
                "NSSF Payable Account"),
            ("max_children_deduction","Tax Deduction Children"),("transport_daily_exempt","Transport Exempt / Day"),("default_transport_days",
                    "Default Transport Days"),("schooling_annual_exempt","Schooling Tax Exempt / Year"),("schooling_max_children","Schooling Children"),
            ("schooling_public_child","Public School / Child"),("schooling_public_cap","Public School Cap"),
            ("schooling_private_child","Private School / Child"),("schooling_private_cap","Private School Cap"),
            ("tax_rounding","Round Tax Up To"),("minimum_wage","Minimum Wage"),("family_allowance_spouse","Allowance Spouse"),("family_allowance_child",
                    "Allowance per Child"),("family_allowance_cap","Allowance Maximum"),("family_allowance_max_children","Allowance Children"))
        # 2.9.100: three columns in their own frame (four columns made the tab wider than a laptop screen)
        fields=tk.Frame(settings_page,bg=LIGHT); fields.grid(row=0,column=0,rowspan=10,columnspan=8,sticky="nw")
        per_column=-(-len(setting_labels)//3)
        for index,(key,label) in enumerate(setting_labels):
            column=(index//per_column)*2; row=index%per_column
            tk.Label(fields,text=label,bg=LIGHT).grid(row=row,column=column,padx=(10,2),pady=3,sticky="w")
            tk.Entry(fields,textvariable=self.payroll_setting_vars[key],width=13).grid(row=row,column=column+1,padx=(2,10),pady=3,sticky="w")
        tk.Label(settings_page,text="Tax Brackets JSON (annual LBP): [[ceiling,rate], ... [null,rate]]   Rates as decimals: 3% = 0.03   Dates: DD-MM-YYYY",
                bg=LIGHT).grid(row=10,column=0,columnspan=4,padx=10,pady=4,sticky="w")
        self.payroll_brackets=tk.Text(settings_page,width=62,height=4); self.payroll_brackets.grid(row=11,column=0,columnspan=6,padx=10,pady=5,sticky="ew")
        # 2.9.100: one toolbar (it wraps on a small screen): settings | for the tax adviser | on paper
        toolbar=tk.Frame(settings_page,bg=LIGHT); toolbar.grid(row=12,column=0,columnspan=8,padx=10,pady=10,sticky="ew")
        self.action_button(toolbar,"Load Settings",self.load_payroll_settings).pack(side="left",padx=3)
        tk.Button(toolbar,text="Save Settings",command=self.save_payroll_settings,bg=GOLD,fg=NAVY,border=0,padx=14,pady=7,font=("Segoe UI",9,"bold")).pack(side="left",padx=3)
        self.action_button(toolbar,"Load Lebanese Law 2024-2026",self.apply_lebanese_payroll_rules).pack(side="left",padx=3)
        self.action_button(toolbar,"Print Settings",lambda:self.export_tax_settings("print")).pack(side="left",padx=(16,3))
        self.action_button(toolbar,"Settings PDF",lambda:self.export_tax_settings("pdf")).pack(side="left",padx=3)
        for label,fmt in (("Rules for the Adviser (PDF)","pdf"),("Rules (Excel)","xlsx")):  # 2.9.98
            self.action_button(toolbar,label,lambda f=fmt:self.export_tax_review(f)).pack(side="left",padx=3)
        self.action_button(toolbar,"Adviser confirmation...",self.tax_adviser_dialog).pack(side="left",padx=3)
        self.tax_adviser_label=tk.Label(toolbar,text="",bg=LIGHT,fg="#5f6b76"); self.tax_adviser_label.pack(side="left",padx=8)
        from desktop_common import flow_toolbar
        flow_toolbar(toolbar)
        self.after_idle(self.show_tax_adviser)
        self.build_payroll_periods_panel(settings_page,13)
        import lebanese_payroll
        family_reference=tk.LabelFrame(settings_page,text="Family allowance reference · 2024–2026 (monthly LBP)",bg=LIGHT,padx=8,pady=6)
        family_reference.grid(row=14,column=0,columnspan=6,padx=10,pady=8,sticky="ew")
        columns=("from","to","spouse","child","maximum")
        family_table=ttk.Treeview(family_reference,columns=columns,show="headings",height=3)
        for key,label,width in (("from","Effective from",120),("to","Through",120),("spouse","Spouse",130),
                                 ("child","Per child (up to 5)",165),("maximum","Monthly maximum",165)):
            family_table.heading(key,text=label)
            family_table.column(key,width=width,anchor="center" if key in ("from","to") else "e",stretch=True)
        for start,end,spouse,child,maximum in lebanese_payroll.FAMILY_ALLOWANCE_PERIODS:
            family_table.insert("", "end",values=(safe_display_date(start),safe_display_date(end) if end else "Open",
                f"{int(spouse):,}",f"{int(child):,}",f"{int(maximum):,}"))
        family_table.pack(fill="x")
        tk.Label(family_reference,text="Reference amounts only. Load Lebanese Law to apply them to this company-year; edit the period table above to customize. "
            "2024: Decrees 12599/12772 · 2025: Decree 422 / CNSS memo 793 · 2026: Decree 2923 / CNSS memo 831.",
            bg=LIGHT,fg="#5f6b76",anchor="w",justify="left",wraplength=950).pack(fill="x",pady=(4,0))
        tk.Label(settings_page,text="Salary-tax policy used here: no spouse deduction when the spouse works; half the child deduction. Confirm this dependent split with your accountant. Tax applies only above the taxable threshold.",
            bg=LIGHT,fg="#5f6b76",anchor="w",justify="left",wraplength=950).grid(row=15,column=0,columnspan=6,padx=10,pady=4,sticky="w")
        mapping_frame=tk.LabelFrame(settings_page,text="Standard Posting Accounts",bg=LIGHT,padx=8,pady=6); mapping_frame.grid(row=16,column=0,columnspan=6,padx=10,pady=8,sticky="ew")
        self.payroll_employee_accounts={key:tk.StringVar() for key in ("salary","transport","overtime","commission","retro_salary","schooling","bonus",
                "thirteenth_month","director_remuneration","family_allowance","employer_social","tax","nssf","payable")}
        self.payroll_manager_accounts={key:tk.StringVar() for key in self.payroll_employee_accounts}
        tk.Label(mapping_frame,text="Component",bg=LIGHT,font=("Segoe UI",9,"bold")).grid(row=0,column=0,padx=5); tk.Label(mapping_frame,text="Employees",
                bg=LIGHT,font=("Segoe UI",9,"bold")).grid(row=0,column=1,padx=5); tk.Label(mapping_frame,text="Managers",bg=LIGHT,font=("Segoe UI",9,
                "bold")).grid(row=0,column=2,padx=5)
        labels={"salary":"Salary","transport":"Transportation","overtime":"Overtime","commission":"Commission","retro_salary":"Retro Salary",
                "schooling":"Schooling","bonus":"Bonus","thirteenth_month":"13th Salary","director_remuneration":"Director Remuneration",
                "family_allowance":"Family Allocation (empty = NSSF account)","employer_social":"Employer NSSF (expense)","tax":"Payroll Tax","nssf":"NSSF",
                "payable":"Net Salary Payable"}
        for index,(key,label) in enumerate(labels.items(),1):
            tk.Label(mapping_frame,text=label,bg=LIGHT).grid(row=index,column=0,padx=5,pady=2,sticky="w")
            self.account_search_box(mapping_frame,self.payroll_employee_accounts[key],16).grid(row=index,column=1,padx=5,pady=2)
            self.account_search_box(mapping_frame,self.payroll_manager_accounts[key],16).grid(row=index,column=2,padx=5,pady=2)
        self.build_payroll_reports_page(reports_page)
        self.build_cnss_forms_page(forms_page)
        self.load_payroll()
        self.load_payroll_settings()

    def employee_dialog(self,employee=None):
        window=tk.Toplevel(self); window.title("Employee File"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        self.fit_dialog(window,960,760,480,360)
        save_bar=tk.Frame(window,bg=LIGHT); save_bar.pack(side="bottom",fill="x")  # 2.9.108: Save stays visible whatever the screen size
        outer,form=self.scrollable_page(window); outer.pack(fill="both",expand=True)
        data=employee or {}; fields={key:tk.StringVar(value=safe_display_date(data.get(key)) if key in ("birth_date","hire_date","leave_date")
                else str(data.get(key) or "")) for key in ("employee_number","full_name","national_id","mof_number",
                "nssf_number","address","contact_number","nationality","father_name","mother_name","birth_date","birth_place","job_title","hire_date",
                "leave_date","base_salary","salary_account","payable_account")}
        if not fields["employee_number"].get(): fields["employee_number"].set("1000")
        marital=tk.StringVar(value=data.get("marital_status","single")); spouse_works=tk.BooleanVar(value=bool(data.get("spouse_works",
                0))); children=tk.StringVar(value=str(data.get("children",0))); employee_group=tk.StringVar(value=data.get("employee_group",
                "employee")); currency=tk.StringVar(value=data.get("currency","LBP")); active=tk.BooleanVar(value=bool(data.get("active",1)))
        rows=(("employee_number","Employee ID / 4-digit prefix"),("full_name","Full Name"),("national_id","National ID"),("mof_number","MOF Number"),
                ("nssf_number","NSSF Number"),("address","Address"),("contact_number","Contact Number"),("nationality","Nationality"),("father_name",
                "Father's Name"),("mother_name","Mother's Name"),("birth_date","Date of Birth"),("birth_place","Place of Birth"),("job_title","Job Title"),
                ("hire_date","Hire Date"),("leave_date","Leave Date"),("base_salary","Base Salary"),("salary_account","Salary Expense Account"),
                ("payable_account","Payable Account"))
        for index,(key,label) in enumerate(rows):
            column=0 if index<9 else 2; row=index if index<9 else index-9
            tk.Label(form,text=label,bg=LIGHT).grid(row=row,column=column,padx=10,pady=5,sticky="w")
            (self.date_entry(form,fields[key],28) if key in ("hire_date","leave_date","birth_date") else tk.Entry(form,textvariable=fields[key],width=28)).grid(row=row,column=column+1,padx=10,pady=5)
        tk.Label(form,text="Marital Status",bg=LIGHT).grid(row=9,column=0,padx=10,pady=5,sticky="w"); ttk.Combobox(form,textvariable=marital,values=["single",
                "married","widowed","divorced"],state="readonly",width=25).grid(row=9,column=1)
        tk.Label(form,text="Children",bg=LIGHT).grid(row=10,column=0,padx=10,pady=5,sticky="w"); tk.Entry(form,textvariable=children,width=28).grid(row=10,column=1)
        tk.Label(form,text="Currency",bg=LIGHT).grid(row=9,column=2,padx=10,pady=5,sticky="w"); ttk.Combobox(form,textvariable=currency,
                values=self.currency_codes,state="readonly",width=25).grid(row=9,column=3)
        tk.Checkbutton(form,text="Spouse Works",variable=spouse_works,bg=LIGHT).grid(row=10,column=2,sticky="w")
        tk.Checkbutton(form,text="Active",variable=active,bg=LIGHT).grid(row=10,column=3,sticky="w")
        tk.Label(form,text="Payroll Group",bg=LIGHT).grid(row=11,column=0,padx=10,pady=5,sticky="w"); ttk.Combobox(form,textvariable=employee_group,
                values=["employee","manager"],state="readonly",width=25).grid(row=11,column=1)
        sex=tk.StringVar(value=data.get("sex") or "")
        tk.Label(form,text="Sex (for official forms)",bg=LIGHT).grid(row=11,column=2,padx=10,pady=5,sticky="w"); ttk.Combobox(form,textvariable=sex,
                values=["male","female"],state="readonly",width=25).grid(row=11,column=3)
        # 2.9.44 register (like the official declaration workbook): unit, recurring allowances, NSSF branches, address.
        # 2.9.96: family changes during the year - the spouse counts from the marriage month, a new child from the birth month
        family=tk.LabelFrame(form,text="Family changes | الوضع العائلي",bg=LIGHT,padx=6,pady=4)
        family.grid(row=12,column=0,columnspan=4,padx=10,pady=(8,0),sticky="ew")
        # 2.9.99: tick boxes and dates instead of typing a list - marriage during the year, new children one by one
        family_vars={"marriage_date":tk.StringVar(value=safe_display_date(data.get("marriage_date"))),"children_birth_dates":tk.StringVar()}
        married_now=tk.BooleanVar(value=bool(data.get("marriage_date")))
        marriage_box=tk.Checkbutton(family,text="Married during the year | تزوّج خلال السنة",variable=married_now,bg=LIGHT)
        marriage_box.grid(row=0,column=0,padx=6,pady=3,sticky="w")
        tk.Label(family,text="Date of marriage",bg=LIGHT).grid(row=0,column=1,padx=(12,4),pady=3,sticky="e")
        marriage_entry=self.date_entry(family,family_vars["marriage_date"],13); marriage_entry.grid(row=0,column=2,padx=4,pady=3,sticky="w")
        def marriage_toggled():
            marriage_entry.configure(state="normal" if married_now.get() else "disabled")
            if married_now.get():
                marital.set("married"); marriage_entry.focus_set()
            else: family_vars["marriage_date"].set("")
        marriage_box.configure(command=marriage_toggled)
        new_child=tk.BooleanVar(value=False); birth_var=tk.StringVar()
        child_box=tk.Checkbutton(family,text="New child | مولود جديد",variable=new_child,bg=LIGHT)
        child_box.grid(row=1,column=0,padx=6,pady=3,sticky="w")
        tk.Label(family,text="Date of birth",bg=LIGHT).grid(row=1,column=1,padx=(12,4),pady=3,sticky="e")
        birth_entry=self.date_entry(family,birth_var,13); birth_entry.grid(row=1,column=2,padx=4,pady=3,sticky="w")
        tk.Label(family,text="Children born:",bg=LIGHT,fg=NAVY).grid(row=0,column=3,padx=(14,2),pady=3,sticky="ne")
        births=tk.Listbox(family,height=3,width=16,exportselection=False)
        births.grid(row=0,column=4,rowspan=2,padx=(4,4),pady=3,sticky="nw")
        for day in str(data.get("children_birth_dates") or "").split(","):
            if day.strip(): births.insert("end",safe_display_date(day))
        def child_count(change):
            try: children.set(str(max(0,int(children.get() or 0)+change)))
            except ValueError: children.set(str(max(0,change)))
        def add_child():
            day=birth_var.get().strip()
            if not day: return messagebox.showwarning("New child","Enter the date of birth (DD-MM-YYYY)",parent=window)
            try: shown=safe_display_date(day); datetime.strptime(shown,"%d-%m-%Y")
            except ValueError: return messagebox.showwarning("New child","The date of birth must be DD-MM-YYYY",parent=window)
            if shown in births.get(0,"end"): return messagebox.showinfo("New child","This date is already in the list",parent=window)
            births.insert("end",shown); birth_var.set(""); new_child.set(False); child_toggled()
            child_count(+1)  # Children = the number today: the new child is added to it
        def remove_child():
            selected=births.curselection()
            if not selected: return messagebox.showinfo("New child","Select a date in the list first",parent=window)
            births.delete(selected[0]); child_count(-1)
        add_button=tk.Button(family,text="Add child",command=add_child,bg=NAVY,fg="white",border=0,padx=12,pady=4)
        add_button.grid(row=1,column=3,padx=4,pady=3,sticky="w")
        tk.Button(family,text="Remove",command=remove_child,bg="#8B1E1E",fg="white",border=0,padx=10,pady=3).grid(row=0,column=5,rowspan=2,padx=4,pady=3,sticky="w")
        def child_toggled():
            state="normal" if new_child.get() else "disabled"
            birth_entry.configure(state=state); add_button.configure(state=state)
            if new_child.get(): birth_entry.focus_set()
        child_box.configure(command=child_toggled)
        marriage_toggled() if not married_now.get() else None; child_toggled()
        family_vars["_births"]=births
        tk.Label(family,text="Payroll counts the spouse from the month of the marriage and each child from the month of birth (salary-tax deductions and NSSF family allowance). "
                 "Adding a child raises Children by one.",bg=LIGHT,fg="#5f6b76",wraplength=760,justify="left").grid(row=2,column=0,columnspan=6,padx=6,pady=(2,3),sticky="w")
        register=tk.LabelFrame(form,text="Employee register | سجل المستخدمين",bg=LIGHT,padx=6,pady=4)
        register.grid(row=13,column=0,columnspan=4,padx=10,pady=8,sticky="ew")
        register_vars={key:tk.StringVar(value=str(data.get(key) or "")) for key in ("unit_code","unit_name","cost_of_living","extra_indemnity","representation_taxable","representation_exempt",
            "addr_governorate","addr_caza","addr_town","addr_district","addr_street","addr_building","addr_floor","phone2","leave_reason",
            "eos_paid_before","leave_days_year","leave_carried",
            "full_name_ar","father_name_ar","mother_name_ar","birth_place_ar","nationality_ar","job_title_ar","address_ar",
            "spouse_name","spouse_maiden_name","spouse_father","spouse_mother","spouse_nationality","spouse_birth_place","spouse_birth_date","spouse_id","spouse_mof",
            "spouse_employer","spouse_employer_mof","spouse_public_admin","family_dependents","spouse_name_ar",
            "spouse_maiden_name_ar","spouse_father_ar","spouse_mother_ar","spouse_nationality_ar","spouse_birth_place_ar")}  # 2.9.82 / 2.9.108 / 2.9.109
        register_labels=(("unit_code","Unit code | رمز القسم"),("unit_name","Unit | القسم"),("cost_of_living","Cost of living / month"),("extra_indemnity","Extra indemnity (phone) / month"),
            ("representation_taxable","Representation taxable / month"),("representation_exempt","Representation not taxable / month"),
            ("addr_governorate","Governorate | محافظة"),("addr_caza","Caza | قضاء"),("addr_town","Town | بلدة"),("addr_district","District | حي"),
            ("addr_street","Street | شارع"),("addr_building","Building | مبنى"),("addr_floor","Floor | طابق"),("phone2","Phone 2"),("leave_reason","Leaving reason | سبب الترك"),
            ("eos_paid_before","End-of-service contributions before Saber (LBP)"),("leave_days_year","Annual leave days / year (empty = 15)"),("leave_carried","Leave days carried in"),
            ("full_name_ar","الإسم والشهرة (عربي)"),("father_name_ar","إسم الأب (عربي)"),("mother_name_ar","إسم الأم وشهرتها (عربي)"),
            ("birth_place_ar","محل الولادة (عربي)"),("nationality_ar","الجنسية (عربي)"),
            ("job_title_ar","العمل / الوظيفة (عربي)"),("address_ar","العنوان (عربي)"))
        for index,(key,label) in enumerate(register_labels):
            row,column=index//2,(index%2)*2
            tk.Label(register,text=label,bg=LIGHT).grid(row=row,column=column,padx=6,pady=3,sticky="w")
            if key=="leave_reason":  # 2.9.108: the reasons printed on the CNSS leaving notice
                from payroll_excel_forms import LEAVE_REASONS
                reasons=ttk.Combobox(register,textvariable=register_vars[key],values=("",)+LEAVE_REASONS,state="readonly",width=24)
                reasons.grid(row=row,column=column+1,padx=6,pady=3,sticky="w")
            else:
                tk.Entry(register,textvariable=register_vars[key],width=26,justify="right" if key.endswith("_ar") else "left").grid(row=row,column=column+1,padx=6,pady=3,sticky="w")
        # 2.9.109: spouse, as on MOF R3 (معلومات خاصة بالزوج/الزوجة)
        spouse=tk.LabelFrame(form,text="Spouse | معلومات خاصة بالزوج/الزوجة",bg=LIGHT,padx=6,pady=4)
        spouse.grid(row=14,column=0,columnspan=4,padx=10,pady=8,sticky="ew")
        spouse_rows=(("spouse_name","Spouse name | إسم الزوج/الزوجة","spouse_name_ar"),("spouse_maiden_name","Name before marriage | الشهرة قبل الزواج","spouse_maiden_name_ar"),
            ("spouse_father","Father's name | إسم الأب","spouse_father_ar"),("spouse_mother","Mother's name | إسم الأم وشهرتها","spouse_mother_ar"),
            ("spouse_nationality","Nationality | الجنسية","spouse_nationality_ar"),("spouse_birth_place","Place of birth | محل الولادة","spouse_birth_place_ar"))
        tk.Label(spouse,text="English",bg=LIGHT,fg=NAVY,font=("Segoe UI",8,"bold")).grid(row=0,column=1,sticky="w",padx=6)
        tk.Label(spouse,text="عربي (automatic - correct if needed)",bg=LIGHT,fg=NAVY,font=("Segoe UI",8,"bold")).grid(row=0,column=2,sticky="w",padx=6)
        for index,(key,label,ar_key) in enumerate(spouse_rows,1):
            tk.Label(spouse,text=label,bg=LIGHT).grid(row=index,column=0,padx=6,pady=2,sticky="w")
            tk.Entry(spouse,textvariable=register_vars[key],width=26).grid(row=index,column=1,padx=6,pady=2,sticky="w")
            tk.Entry(spouse,textvariable=register_vars[ar_key],width=26,justify="right").grid(row=index,column=2,padx=6,pady=2,sticky="w")
        for index,(key,label) in enumerate((("spouse_birth_date","Date of birth | تاريخ الولادة"),("spouse_id","ID card no. | رقم بطاقة الهوية"),
                ("family_dependents","Persons for family deduction | عدد الأشخاص المستفيدين من التنزيل العائلي"),("spouse_mof","Spouse MOF no. (if working) | رقم التسجيل الشخصي"),
                ("spouse_employer","Spouse's employer | إسم الشركة/المؤسسة"),("spouse_employer_mof","Employer MOF no. | رقم التسجيل"),
                ("spouse_public_admin","Or public administration | إسم الإدارة")),len(spouse_rows)+1):
            tk.Label(spouse,text=label,bg=LIGHT).grid(row=index,column=0,padx=6,pady=2,sticky="w")
            (self.date_entry(spouse,register_vars[key],26) if key=="spouse_birth_date" else tk.Entry(spouse,textvariable=register_vars[key],width=26)).grid(
                row=index,column=1,padx=6,pady=2,sticky="w")
        # 2.9.112: every box of the NSSF / MOF forms (registry, sect, hours, wage at hire, work permit, other / previous employer)
        official=tk.LabelFrame(form,text="Official forms details | معلومات النماذج الرسمية",bg=LIGHT,padx=6,pady=4)
        official.grid(row=15,column=0,columnspan=4,padx=10,pady=8,sticky="ew")
        from payroll_excel_forms import EMPLOYEE_FORM_FIELDS
        register_vars.update({key:tk.StringVar(value=str(data.get(key) or "")) for key in EMPLOYEE_FORM_FIELDS+("registry_place_ar",)})
        official_labels=(("registry_number","Registry no. | رقم السجل"),("registry_place","Registry place | مكان السجل"),
            ("registry_place_ar","مكان السجل (عربي)"),("birth_caza","Caza of birth | قضاء الولادة"),("sect","Sect | المذهب"),
            ("work_hours","Hours per month | عدد ساعات العمل في الشهر"),("work_time","Working time | دوام العمل"),
            ("hire_salary","Salary at hire (empty = current) | الاجر بتاريخ دخول العمل"),("work_permit","Work permit no. and date | رقم وتاريخ اجازة العمل"),
            ("other_employer","Other employer now (empty = none) | صاحب عمل آخر"),("other_employer_nssf","Other employer NSSF no. | رقمه في الضمان"),
            ("previous_employer","Previous employer, name and address | صاحب العمل السابق"),("previous_employer_nssf","Previous employer NSSF no. | رقمه"))
        for index,(key,label) in enumerate(official_labels):
            row,column=index//2,(index%2)*2
            tk.Label(official,text=label,bg=LIGHT).grid(row=row,column=column,padx=6,pady=3,sticky="w")
            if key=="work_time":
                ttk.Combobox(official,textvariable=register_vars[key],values=("","full","part"),state="readonly",width=24).grid(row=row,column=column+1,padx=6,pady=3,sticky="w")
            else:
                tk.Entry(official,textvariable=register_vars[key],width=26,justify="right" if key.endswith("_ar") else "left").grid(row=row,column=column+1,padx=6,pady=3,sticky="w")
        # 2.9.109: the Arabic boxes follow the English ones (until the user corrects the Arabic himself)
        from arabic_names import to_arabic
        def link_arabic(english,arabic,kind):
            proposed={"text":to_arabic(english.get(),kind)}  # an Arabic box still equal to the proposal keeps following
            def follow(*_args):
                current=arabic.get().strip()
                if current and current!=proposed["text"]: return  # corrected by the user: kept
                proposed["text"]=to_arabic(english.get(),kind); arabic.set(proposed["text"])
            english.trace_add("write",follow)
            if english.get().strip() and not arabic.get().strip(): follow()
        for english,arabic,kind in ((fields["full_name"],"full_name_ar","name"),(fields["father_name"],"father_name_ar","name"),
                (fields["mother_name"],"mother_name_ar","name"),(fields["birth_place"],"birth_place_ar","place"),(fields["nationality"],"nationality_ar","nationality"),
                (fields["job_title"],"job_title_ar","job"),(fields["address"],"address_ar","place"),
                (register_vars["spouse_name"],"spouse_name_ar","name"),(register_vars["spouse_maiden_name"],"spouse_maiden_name_ar","name"),
                (register_vars["spouse_father"],"spouse_father_ar","name"),(register_vars["spouse_mother"],"spouse_mother_ar","name"),
                (register_vars["spouse_nationality"],"spouse_nationality_ar","nationality"),(register_vars["spouse_birth_place"],"spouse_birth_place_ar","place"),
                (register_vars["registry_place"],"registry_place_ar","place")):
            link_arabic(english,register_vars[arabic],kind)
        flags={key:tk.BooleanVar(value=str(data.get(key) or "0")=="1") for key in ("nssf_no_end_service","nssf_no_family","nssf_no_medical")}
        flag_row=tk.Frame(register,bg=LIGHT); flag_row.grid(row=20,column=0,columnspan=4,sticky="w",pady=(4,0))
        tk.Label(flag_row,text="Not subject to NSSF:",bg=LIGHT,fg=NAVY).pack(side="left",padx=4)
        for key,label in (("nssf_no_end_service","End of service | تعويض نهاية الخدمة"),("nssf_no_family","Family allowances | التعويضات العائلية"),
                ("nssf_no_medical","Sickness & maternity | المرض والأمومة")):
            tk.Checkbutton(flag_row,text=label,variable=flags[key],bg=LIGHT).pack(side="left",padx=6)
        def save():
            payload={key:var.get().strip() for key,var in fields.items()}; payload.update({"id":data.get("id"),"marital_status":marital.get(),
                    "spouse_works":spouse_works.get(),"children":children.get(),"employee_group":employee_group.get(),"currency":currency.get(),
                    "active":active.get(),"sex":sex.get()})
            payload.update({key:var.get().strip() for key,var in register_vars.items()}); payload.update({key:"1" if var.get() else "0" for key,var in flags.items()})
            payload.update({"marriage_date":family_vars["marriage_date"].get().strip() if married_now.get() else "",  # 2.9.96 / 2.9.99
                            "children_birth_dates":", ".join(family_vars["_births"].get(0,"end"))})
            try: saved=self.client.save_employee(payload)
            except Exception as exc: return messagebox.showerror("Employee",str(exc),parent=window)
            window.destroy(); self.load_payroll(); messagebox.showinfo("Employee",f'Employee {saved["employee_number"]} saved successfully')
        tk.Button(save_bar,text="Save Employee",command=save,bg=GOLD,fg=NAVY,border=0,padx=18,pady=7,font=("Segoe UI",9,"bold")).pack(pady=8)  # 2.9.96: the main action is gold

    def edit_selected_employee(self):
        selected=self.employee_tree.selection()
        if not selected: return messagebox.showwarning("Employees","Select an employee first")
        employee=next((row for row in getattr(self,"employee_rows",[]) if str(row["id"])==str(selected[0])),None)
        if employee: self.employee_dialog(employee)

    def edit_employee_form(self,title,meta,sections,filename):
        """Review company/employee values and edit the prepared form before export."""
        dialog=tk.Toplevel(self)
        dialog.title(title); dialog.geometry("780x680"); dialog.transient(self)
        canvas=tk.Canvas(dialog,bg=LIGHT,highlightthickness=0)
        scrollbar=ttk.Scrollbar(dialog,orient="vertical",command=canvas.yview)
        body=tk.Frame(canvas,bg=LIGHT)
        body.bind("<Configure>",lambda _event:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0),window=body,anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left",fill="both",expand=True)
        scrollbar.pack(side="right",fill="y")
        variables=[]
        for section in sections:
            tk.Label(body,text=section["heading"],bg=LIGHT,fg=NAVY,
                     font=("Segoe UI",11,"bold")).pack(anchor="w",padx=12,pady=(12,5))
            for label,value in section["rows"]:
                line=tk.Frame(body,bg=LIGHT); line.pack(fill="x",padx=12,pady=2)
                tk.Label(line,text=label,bg=LIGHT,width=27,anchor="w").pack(side="left")
                variable=tk.StringVar(value="" if value=="MISSING" else str(value or ""))
                tk.Entry(line,textvariable=variable,width=58).pack(side="left",fill="x",expand=True)
                variables.append((section["heading"],label,variable))
        actions=tk.Frame(body,bg=LIGHT); actions.pack(fill="x",padx=12,pady=15)
        def export(kind):
            prepared=[]
            for section in sections:
                rows=[[label,(var.get().strip() or "MISSING")]
                      for heading,label,var in variables if heading==section["heading"]]
                prepared.append({**section,"rows":rows})
            missing=[label for _,label,var in variables if not var.get().strip()]
            notes=[line for line in meta if not line.startswith("Missing in the company or employee file:")]
            if missing: notes.append("Missing fields: "+", ".join(missing))
            self.output_sections(title,notes,prepared,filename,kind)
        for label,kind in (("Preview","preview"),("Save PDF","pdf"),("Save Excel","xlsx")):
            self.action_button(actions,label,lambda value=kind:export(value)).pack(side="left",padx=4)
        self.action_button(actions,"Close",dialog.destroy).pack(side="left",padx=4)

    def official_excel_form(self):
        """2.9.107: the official forms are all in Payroll > NSSF & MOF Forms (Excel); open it with the selected employee."""
        from cnss_forms import FORM_BY_KEY
        selected=self.employee_tree.selection() if hasattr(self,"employee_tree") else ()
        current=FORM_BY_KEY.get(self._selected_cnss_form()) if hasattr(self,"cnss_form_label_var") else None
        form=current.key if current and current.kind=="employee" else "cnss_employment_declaration"
        self.open_cnss_form(form,selected[0] if selected else None)

    def employee_r3_worksheet(self,format_name,form="R3"):
        selected=self.employee_tree.selection()
        if not selected: return messagebox.showwarning("R3 Registration","Select an employee first")
        employee=next((row for row in getattr(self,"employee_rows",[]) if str(row["id"])==str(selected[0])),None)
        if not employee: return messagebox.showwarning("R3 Registration","Refresh the employee list and select an employee")
        company=self.client.settings()
        employer=((("Employer / company",company.get("company_name")),("Employer address",company.get("company_address")),
                   ("Employer phone",company.get("company_phone")),("MOF / VAT number",company.get("company_mof")),
                   ("NSSF employer number",company.get("company_nssf"))))
        employer_rows=[[label,value if value not in (None,"") else "MISSING"] for label,value in employer]
        fields=(("Full name","full_name"),("Father's name","father_name"),("Mother's name","mother_name"),
                ("Nationality","nationality"),("Date of birth","birth_date"),("Place of birth","birth_place"),
                ("National ID","national_id"),("MOF personal number","mof_number"),("NSSF number","nssf_number"),
                ("Marital status","marital_status"),("Children","children"),("Address","address"),
                ("Phone","contact_number"),("Profession","job_title"),("Start date","hire_date"))
        rows=[[label,employee.get(key) if employee.get(key) not in (None,"") else "MISSING"] for label,key in fields]
        missing=[label for (label,key),row in zip(fields,rows) if row[1]=="MISSING"]
        missing+=[label for label,row in zip(("Employer / company","Employer address","Employer phone","MOF / VAT number","NSSF employer number"),employer_rows) if row[1]=="MISSING"]
        meta=[f'Employee ID: {employee["employee_number"]}',
              f"Preparation worksheet only. Complete and submit the Ministry of Finance {form} form separately.",
              "Official form: " + ("https://eservices.finance.gov.lb/Resources/Namazej/DASS1/%D8%B13.pdf" if form=="R3" else "https://www.finance.gov.lb/en-us/Taxation/Na/DASS1/%D8%B13-1.pdf"),
              "Check the official form for other details and supporting documents."]
        if missing: meta.append("Missing in the company or employee file: " + ", ".join(missing))
        self.edit_employee_form(f"{form} Employee Registration Worksheet",meta,
            [{"heading":"Employer information","headers":["Field","Value"],"rows":employer_rows,"total_rows":[]},
             {"heading":"Employee information","headers":["Field","Value"],"rows":rows,"total_rows":[]}],
            f'{form}_Worksheet_{employee["employee_number"]}')

    def employee_nssf_declaration(self,kind,format_name):
        titles={"hire":("NSSF Employment Declaration",
                "NSSF Employment Declaration (Estekhdam Ajir) Worksheet | \u0625\u0639\u0644\u0627\u0645 \u0627\u0633\u062a\u062e\u062f\u0627\u0645 \u0623\u062c\u064a\u0631",
                "NSSF-HIRE-NEW","hire_date","Start date"),
                "leave":("NSSF Termination Declaration",
                        "NSSF Termination Declaration (Tark Ajir) Worksheet | \u0625\u0639\u0644\u0627\u0645 \u062a\u0631\u0643 \u0623\u062c\u064a\u0631",
                        "NSSF-LEAVE","leave_date","Leaving date")}
        warn,title,form,date_key,date_label=titles[kind]
        selected=self.employee_tree.selection()
        if not selected: return messagebox.showwarning(warn,"Select an employee first")
        employee=next((row for row in getattr(self,"employee_rows",[]) if str(row["id"])==str(selected[0])),None)
        if not employee: return messagebox.showwarning(warn,"Refresh the employee list and select an employee")
        company=self.client.settings()
        employer=(("Employer / company",company.get("company_name")),("Employer address",company.get("company_address")),
                  ("Employer phone",company.get("company_phone")),("NSSF employer number",company.get("company_nssf")),
                  ("MOF / VAT number",company.get("company_mof")))
        employer_rows=[[label,value if value not in (None,"") else "MISSING"] for label,value in employer]
        fields=(("Full name","full_name"),("Father's name","father_name"),("Mother's name","mother_name"),
                ("Nationality","nationality"),("Date of birth","birth_date"),("Place of birth","birth_place"),
                ("National ID","national_id"),("NSSF number","nssf_number"),("Marital status","marital_status"),
                ("Children","children"),("Address","address"),("Phone","contact_number"),("Profession","job_title"),
                (date_label,date_key),("Base salary","base_salary"))
        rows=[[label,employee.get(key) if employee.get(key) not in (None,"") else "MISSING"] for label,key in fields]
        missing=[label for (label,key),row in zip(fields,rows) if row[1]=="MISSING"]
        missing+=[label for label,row in zip(("Employer / company","Employer address","Employer phone","NSSF employer number","MOF / VAT number"),employer_rows) if row[1]=="MISSING"]
        meta=[f'Employee ID: {employee["employee_number"]}',
              "Preparation worksheet only. Complete and submit the official CNSS form separately.",
              "Download the official blank form from the NSSF employee forms buttons."]
        if kind=="leave" and (employee.get("leave_date") in (None,"")): meta.append("No leaving date on file - set it in the employee file before you file the termination.")
        if missing: meta.append("Missing in the company or employee file: " + ", ".join(missing))
        self.edit_employee_form(title,meta,
            [{"heading":"Employer information","headers":["Field","Value"],"rows":employer_rows,"total_rows":[]},
             {"heading":"Employee information","headers":["Field","Value"],"rows":rows,"total_rows":[]}],
            f'NSSF_{kind}_Worksheet_{employee["employee_number"]}')

    def download_payroll_form(self,form):
        selected=self.employee_tree.selection() if hasattr(self,"employee_tree") else ()
        self.open_cnss_form(form,selected[0] if selected else None)

    def load_payroll(self):
        if not hasattr(self,"employee_tree"): return
        try: self.employee_rows=self.client.employees(); payroll=self.client.payroll()
        except Exception as exc: return messagebox.showerror("Payroll",str(exc))
        if hasattr(self,"cnss_employee_combo"): self.refresh_cnss_employee_options()
        self.employee_tree.delete(*self.employee_tree.get_children())
        for row in self.employee_rows: self.employee_tree.insert("","end",iid=str(row["id"]),values=(row["employee_number"],row["full_name"],
                "" if str(row.get("job_title") or "").strip().lower() in ("","none") else row["job_title"],safe_display_date(row.get("hire_date")),
                safe_display_date(row.get("leave_date")),row.get("branch_name") or "",row["currency"],row["base_salary"],row["nssf_number"],
                "Yes" if row["active"] else "No"))
        self.payroll_employee_map={f'{row["employee_number"]} - {row["full_name"]}':row for row in self.employee_rows if row["active"]}
        self.payroll_employee_combo["values"]=list(self.payroll_employee_map)
        if not self.payroll_employee.get() and self.payroll_employee_map: self.payroll_employee.set(next(iter(self.payroll_employee_map))); self.payroll_employee_chosen()
        self.payroll_tree.delete(*self.payroll_tree.get_children())
        for row in payroll: self.payroll_tree.insert("","end",iid=str(row["id"]),values=(row["payroll_number"],safe_display_date(row["period_date"]),
                row["full_name"],row["currency"],f'{float(row["gross_salary"]):,.2f}',f'{float(row["income_tax"]):,.2f}',f'{float(row["employee_nssf"]):,.2f}',
                f'{float(row["net_salary"]):,.2f}',row["status"]))

    def schooling_law_dialog(self):
        """Calculate the annual schooling grant under the dated public/private rules."""
        employee=getattr(self,"payroll_employee_map",{}).get(self.payroll_employee.get())
        if not employee: return messagebox.showwarning("Schooling","Select an employee first")
        try:
            period=formatted_user_date(self.payroll_period.get())
            rules=self.client.payroll_settings(period)
        except Exception as exc: return messagebox.showerror("Schooling",str(exc))
        public=tk.StringVar(value="0"); private=tk.StringVar(value="0")
        window=tk.Toplevel(self); window.title("Annual Schooling Grant"); window.transient(self)
        window.configure(bg=LIGHT); window.geometry("500x280")
        tk.Label(window,text=f"Schooling rules from {safe_display_date(rules.get('schooling_rules_date') or rules.get('date_from'))}  |  {employee['full_name']}",
            bg=LIGHT,fg=NAVY,font=("Segoe UI",10,"bold")).pack(anchor="w",padx=12,pady=10)
        for label,var in (("Public / free school or Lebanese University children",public),
                          ("Private school / university children",private)):
            line=tk.Frame(window,bg=LIGHT); line.pack(fill="x",padx=12,pady=4)
            tk.Label(line,text=label,bg=LIGHT,width=43,anchor="w").pack(side="left")
            tk.Entry(line,textvariable=var,width=5).pack(side="left")
        rates=(Decimal(str(rules.get("schooling_public_child") or 0)),Decimal(str(rules.get("schooling_public_cap") or 0)),
               Decimal(str(rules.get("schooling_private_child") or 0)),Decimal(str(rules.get("schooling_private_cap") or 0)))
        tk.Label(window,text=f"Public: {rates[0]:,.0f} / child (cap {rates[1]:,.0f})  |  Private: {rates[2]:,.0f} / child (cap {rates[3]:,.0f}) LBP",
            bg=LIGHT,fg=NAVY,wraplength=470).pack(anchor="w",padx=12,pady=8)
        tk.Label(window,text="Annual grant, paid once for the school year. Check supporting documents and prior payments. Tax-exempt amount is a separate setting.",
            bg=LIGHT,fg="#8B1E1E",wraplength=470,justify="left").pack(anchor="w",padx=12,pady=5)
        def apply():
            try:
                counts=[int(public.get()),int(private.get())]
                if any(value<0 for value in counts) or sum(counts)>min(3,int(employee.get("children") or 0)):
                    raise ValueError("Enter up to 3 eligible children, within the employee's recorded child count")
                if not any(rates): raise ValueError("No schooling grant rule is loaded for this period")
                amount=min(Decimal(counts[0])*rates[0],rates[1])+min(Decimal(counts[1])*rates[2],rates[3])
                currency=employee.get("currency") or "LBP"
                if currency!="LBP":
                    rate=Decimal(str(self.client.suggested_rates(currency,period)["rate_lbp"]))
                    if rate<=0: raise ValueError("Set the currency exchange rate first")
                    amount=(amount/rate).quantize(Decimal("0.01"))
                self.payroll_vars["schooling"].set(str(amount))
                window.destroy()
            except Exception as exc: messagebox.showerror("Schooling",str(exc),parent=window)
        self.action_button(window,"Use Amount in Payroll",apply).pack(anchor="w",padx=12,pady=8)

    def payroll_employee_chosen(self):
        employee=getattr(self,"payroll_employee_map",{}).get(self.payroll_employee.get())
        if employee: self.payroll_vars["salary"].set(str(employee.get("base_salary") or "0"))
        self._family_manual=False; self.payroll_family_auto()

    def payroll_family_auto(self):
        """Show the automatic family allocation of the chosen employee and period (unless it was typed by hand)."""
        if getattr(self,"_family_manual",False) or not hasattr(self,"payroll_family_override"): return
        try:
            payload=self.payroll_payload(); payload.pop("family_allowance_override",None)
            result=self.client.calculate_payroll(payload)
        except Exception: return
        value=float(result.get("family_allowance") or 0)
        self.payroll_family_override.set(f"{value:.0f}" if result.get("currency")=="LBP" else f"{value:.2f}")

    def payroll_transport_from_days(self):
        """Transport = transport days x daily transport of the payroll period, in the employee's currency."""
        text=self.payroll_transport_days.get().strip()
        if not text: return
        try: days=int(text)
        except ValueError: return
        if days<0 or days>31: return
        employee=getattr(self,"payroll_employee_map",{}).get(self.payroll_employee.get())
        currency=(employee or {}).get("currency") or "LBP"
        try: period=formatted_user_date(self.payroll_period.get())
        except ValueError: period=None
        key=(period,currency); cache=self.__dict__.setdefault("_transport_rate_cache",{})
        try:
            if key not in cache:
                daily=Decimal(str(self.client.payroll_settings(period).get("transport_daily_exempt") or 0))
                rate=Decimal("1") if currency=="LBP" else Decimal(str(self.client.suggested_rates(currency,period)["rate_lbp"]))
                cache[key]=(daily,rate)
            daily,rate=cache[key]
        except Exception: return
        if daily<=0 or rate<=0: return
        amount=daily*days/rate
        self.payroll_vars["transport"].set(f"{amount:.0f}" if currency=="LBP" else f"{amount.quantize(Decimal('0.01'))}")

    def mark_payroll_stale(self,*_args):
        if hasattr(self,"payroll_result"):
            self.payroll_result.set("Inputs changed - click Calculate for the current tax and net salary")
        if hasattr(self,"payroll_breakdown"): self.payroll_breakdown.config(text="")
        if hasattr(self,"payroll_notes"): self.payroll_notes.config(text="")

    def payroll_payload(self):
        employee=self.payroll_employee_map.get(self.payroll_employee.get())
        if not employee: raise ValueError("Select an employee")
        payload={"employee_id":employee["id"],"period_date":formatted_user_date(self.payroll_period.get())}
        payload.update({key:var.get().strip() or "0" for key,var in self.payroll_vars.items()})
        if self.payroll_transport_days.get().strip(): payload["transport_days"]=self.payroll_transport_days.get().strip()
        if getattr(self,"payroll_family_override",None) is not None and getattr(self,"_family_manual",False) and self.payroll_family_override.get().strip():
            payload["family_allowance_override"]=self.payroll_family_override.get().strip()
        if float(payload.get("retro_salary") or 0):
            if not self.payroll_retro_from.get().strip() or not self.payroll_retro_to.get().strip(): raise ValueError("Enter Retro From and Retro To dates")
            payload["retro_from"]=formatted_user_date(self.payroll_retro_from.get()); payload["retro_to"]=formatted_user_date(self.payroll_retro_to.get())
        return payload

    def calculate_payroll(self):
        try: result=self.client.calculate_payroll(self.payroll_payload())
        except Exception as exc:
            messagebox.showerror("Payroll",str(exc))
            return None
        if not getattr(self,"_family_manual",False) and hasattr(self,"payroll_family_override"):
            value=float(result.get("family_allowance") or 0)
            self.payroll_family_override.set(f"{value:.0f}" if result.get("currency")=="LBP" else f"{value:.2f}")
        retro=f' (of which retro tax {result["retro_tax"]:,.2f})' if result.get("retro_tax") else ""
        rules=result.get("settings_period") or {}
        period=f' | Rules from {safe_display_date(rules["date_from"])}' if rules.get("date_from") else ""
        self.payroll_breakdown.config(text=f'Worked {result.get("worked_days","?")}/{result.get("calendar_days","?")} days | Tax: regular {result.get("regular_tax",0):,.2f} + bonus/13th {result.get("one_off_tax",0):,.2f} + retro {result.get("retro_tax",0):,.2f}   |   Exempt: transport {result.get("exempt_transport",0):,.2f} ({result.get("transport_days","")} days), schooling {result.get("exempt_schooling",0):,.2f}   |   NSSF family allowance paid: {result.get("family_allowance",0):,.2f} {result["currency"]}')
        tax_detail=(f"Annualized recurring {result.get('annualized_recurring_lbp',0):,.0f} LBP"
                    f" - family deduction {result.get('family_deduction_lbp',0):,.0f} LBP"
                    f" = taxable {result.get('annualized_taxable_lbp',0):,.0f} LBP")
        self.payroll_breakdown.config(text=self.payroll_breakdown.cget("text")+"  |  "+tax_detail)
        self.payroll_notes.config(text=("Check: "+"  |  ".join(result.get("compliance_notes") or [])) if result.get("compliance_notes") else "Compliant with the rules of this period")
        self.payroll_notes.config(fg="#8B1E1E" if result.get("compliance_notes") else NAVY)
        self.payroll_result.set(f'Gross: {result["gross_salary"]:,.2f} | Tax: {result["income_tax"]:,.2f} {result["currency"]} ({result["income_tax_lbp"]:,.0f} LBP){retro} | Employee NSSF: {result["employee_nssf"]:,.2f} | Employer NSSF: {result["employer_medical"]+result["employer_family"]+result["employer_end_service"]:,.2f} | Net: {result["net_salary"]:,.2f}{period}')
        return result

    def save_payroll(self):
        if self.calculate_payroll() is None: return
        try: saved=self.client.save_payroll(self.payroll_payload())
        except Exception as exc: return messagebox.showerror("Payroll",str(exc))
        self.load_payroll(); messagebox.showinfo("Payroll",f'Payroll {saved["payroll_number"]} saved as draft')

    def post_selected_payroll(self):
        selected=self.payroll_tree.selection()
        if not selected: return messagebox.showwarning("Payroll","Select a payroll record first")
        if not messagebox.askyesno("Post Payroll","Post this payroll to the General Journal? Posted payroll cannot be edited."): return
        try: saved=self.client.post_payroll(int(selected[0]))
        except Exception as exc: return messagebox.showerror("Payroll",str(exc))
        self.load_payroll(); self.load_journal(); self.load_trial(); messagebox.showinfo("Payroll",f'Payroll {saved["payroll_number"]} posted successfully')

    def load_payroll_settings(self):
        self.__dict__.pop("_transport_rate_cache",None)  # settings may have changed: recalculate transport from days
        if not hasattr(self,"payroll_setting_vars"): return
        try: settings=self.client.payroll_settings(self.payroll_period.get().strip())
        except Exception as exc: return messagebox.showerror("Payroll Settings",str(exc))
        for key,var in self.payroll_setting_vars.items():
            value=settings.get(key,"") if settings.get(key) is not None else ""
            var.set(safe_display_date(value) if key in ("date_from","date_to") and value else value)
        for key,var in self.payroll_employee_accounts.items(): var.set(settings.get("employee_account_map",{}).get(key,""))
        for key,var in self.payroll_manager_accounts.items(): var.set(settings.get("manager_account_map",{}).get(key,""))
        self.payroll_brackets.delete("1.0","end"); self.payroll_brackets.insert("1.0",json.dumps(settings.get("tax_brackets",[])))

    def export_tax_settings(self, mode):  # 2.9.100: Print / PDF of Tax & NSSF Settings
        day = f"31-12-{getattr(self, 'current_fiscal_year', '') or datetime.now().year}"
        try: report = self.client.tax_settings_report(day)
        except Exception as exc: return messagebox.showerror("Tax & NSSF Settings", str(exc))
        if mode == "print": return self.output_sections(report["title"], report["meta"], report["sections"], "Tax_NSSF_Settings", "print")
        self.save_sections(report["title"], report["meta"], report["sections"], "Tax_NSSF_Settings", mode)

    def show_tax_adviser(self):
        try: checked = self.client.tax_adviser()
        except Exception: checked = {}
        if getattr(self, "tax_adviser_label", None) is not None:
            text = (f"Checked by {checked['name']} on {checked['date']}") if checked else "Not yet confirmed by a tax adviser"
            try: self.tax_adviser_label.config(text=text, fg="#2E7D5B" if checked else "#5f6b76")
            except tk.TclError: pass

    def tax_adviser_dialog(self):
        """2.9.100: the tax adviser who checked the rules - the rules then show as confirmed by him (Rules PDF, Settings PDF)."""
        try: checked = self.client.tax_adviser()
        except Exception: checked = {}
        window = tk.Toplevel(self); window.title("Tax adviser confirmation"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        tk.Label(window, text="The tax adviser checked the payroll and VAT rules of this company against Lebanese law.", bg=LIGHT, fg=NAVY,
                 font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 6), sticky="w")
        fields = {}
        for row, (key, label) in enumerate((("name", "Tax adviser (name)"), ("licence", "Licence / firm"), ("date", "Date of the check"), ("notes", "Notes")), start=1):
            tk.Label(window, text=label, bg=LIGHT).grid(row=row, column=0, padx=12, pady=4, sticky="w")
            fields[key] = tk.StringVar(value=str(checked.get(key) or (datetime.now().strftime("%d-%m-%Y") if key == "date" else "")))
            (self.date_entry(window, fields[key], 14) if key == "date" else tk.Entry(window, textvariable=fields[key], width=44)).grid(row=row, column=1, padx=12, pady=4, sticky="w")
        def save():
            try: self.client.save_tax_adviser({k: v.get().strip() for k, v in fields.items()})
            except Exception as exc: return messagebox.showerror("Tax adviser confirmation", str(exc), parent=window)
            window.destroy(); self.show_tax_adviser()
            messagebox.showinfo("Tax adviser confirmation", "Saved. The rules now show as confirmed by the tax adviser (Rules PDF and Settings PDF).")
        tk.Button(window, text="Save", command=save, bg=GOLD, fg=NAVY, border=0, padx=18, pady=7, font=("Segoe UI", 9, "bold")).grid(row=5, column=0, columnspan=2, pady=12)

    def export_tax_review(self, fmt):  # 2.9.98
        day = f"31-12-{getattr(self, 'current_fiscal_year', '') or datetime.now().year}"
        try: review = self.client.tax_review(day)
        except Exception as exc: return messagebox.showerror("Rules for the Tax Adviser", str(exc))
        self.save_sections(review["title"], review["meta"], review["sections"], "Rules_for_the_Tax_Adviser", fmt)

    def apply_lebanese_payroll_rules(self):
        if not messagebox.askyesno("Lebanese Payroll Rules","Replace ALL Tax & NSSF periods with the configured Lebanese payroll rules from 01-01-2024?\n\n"
            "- Budget Law 2024 brackets and family deductions\n- Transport exempt 450,000 LBP/day, schooling 6M/year\n- Tax rounded up to 10,000 LBP from 25-11-2024\n"
            "- NSSF sickness & maternity ceiling: 45M -> 90M (04-2024) -> 120M (08-2025); family 12M -> 18M (07-2025) -> 28M (05-2026)\n"
            "- Family benefits: 600k/330k from 01-2024, 1.2M/660k from 07-2025, 2.1M/1.155M from 05-2026 (spouse/child)\n\n"
            "Rates, employee eligibility, and any part-month minimum-wage treatment must be confirmed with CNSS / your accountant. "
            "These reports are preparation worksheets, not official filings. Posting accounts are kept. Already saved payroll is NOT recalculated."): return
        try: self.client.apply_lebanese_payroll_rules()
        except Exception as exc: return messagebox.showerror("Lebanese Payroll Rules",str(exc))
        self.load_payroll_periods(); self.load_payroll_settings(); messagebox.showinfo("Lebanese Payroll Rules","Lebanese payroll rules loaded. Recalculate draft payroll to apply them.")

    def save_payroll_settings(self):
        payload={key:var.get().strip() for key,var in self.payroll_setting_vars.items()}
        for key in ("date_from","date_to"):
            if payload.get(key):
                try: payload[key]=parse_user_date(payload[key]).strftime("%Y-%m-%d")
                except ValueError: return messagebox.showerror("Payroll Settings",f"{key.replace('_',' ').title()} must use DD-MM-YYYY")
        payload["employee_account_map"]={key:var.get().split(" - ",1)[0].strip() for key,var in self.payroll_employee_accounts.items()}
        payload["manager_account_map"]={key:var.get().split(" - ",1)[0].strip() for key,var in self.payroll_manager_accounts.items()}
        try: payload["tax_brackets"]=json.loads(self.payroll_brackets.get("1.0","end").strip()); self.client.save_payroll_settings(payload)
        except Exception as exc: return messagebox.showerror("Payroll Settings",str(exc))
        self.load_payroll_periods()
        messagebox.showinfo("Payroll Settings","Tax and NSSF settings saved. The previous period now ends the day before the new Date From.")
