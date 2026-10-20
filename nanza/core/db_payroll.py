"""Employees, payroll settings, payroll calculation and posting, NSSF.

Part of the Database class (split out of database.py in 2.9.63, code unchanged): Database inherits from PayrollStore."""
from __future__ import annotations

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, Decimal, display_date, iso_date, json, timedelta, utcnow
)
from decimal import InvalidOperation
from database_common import _soft_iso, atomic  # noqa: F401


class PayrollStore:
    # Payroll is deliberately settings-driven.  Rates and ceilings are effective-dated so
    # a Lebanese statutory change does not rewrite previously calculated payroll periods.
    # 2.9.44 employee register (like the official declaration workbooks): unit, recurring allowances,
    # NSSF branches the employee is not subject to, structured address, how the employee left.
    EMPLOYEE_MONEY_FIELDS = ("cost_of_living","extra_indemnity","representation_taxable","representation_exempt",
                             "eos_paid_before","leave_carried","leave_days_year")  # 2.9.82: end of service, leave
    EMPLOYEE_FLAG_FIELDS = ("nssf_no_end_service","nssf_no_family","nssf_no_medical")
    EMPLOYEE_REGISTER_FIELDS = ("unit_code","unit_name")+EMPLOYEE_MONEY_FIELDS+EMPLOYEE_FLAG_FIELDS+(
        "addr_governorate","addr_caza","addr_town","addr_district","addr_street","addr_building","addr_floor","phone2","pay_type","leave_reason",
        "marriage_date","children_birth_dates",  # 2.9.96: family changes during the year
        "full_name_ar","father_name_ar","mother_name_ar","birth_place_ar","nationality_ar","job_title_ar","address_ar",  # 2.9.108: Arabic, for the official forms
        "spouse_name","spouse_maiden_name","spouse_father","spouse_mother","spouse_nationality","spouse_birth_place","spouse_birth_date",
        "spouse_id","spouse_mof","spouse_employer","spouse_employer_mof","spouse_public_admin","family_dependents",  # 2.9.109: spouse, as on MOF R3
        "spouse_name_ar","spouse_maiden_name_ar","spouse_father_ar","spouse_mother_ar","spouse_nationality_ar","spouse_birth_place_ar",
        "registry_number","registry_place","registry_place_ar","birth_caza","sect","work_hours","work_time","hire_salary","work_permit",
        "other_employer","other_employer_nssf","previous_employer","previous_employer_nssf")  # 2.9.112: every box of the official forms

    @staticmethod
    def parse_birth_dates(text):
        """'05-03-2026, 10-11-2023' -> ['2023-11-10', '2026-03-05'] (ISO, sorted)."""
        import re as _re
        parts=[p.strip() for p in _re.split(r"[,;\n]+",str(text or "")) if p.strip()]
        return sorted(iso_date(p,"Child birth date") for p in parts)

    @classmethod
    def family_on(cls,employee,day):
        """2.9.96: marital status and number of children on a payroll month end, from the marriage date and the
        children's birth dates. 'Children' on the employee card is the number today; a child born after the month
        is not counted yet, and the spouse counts from the month of the marriage. Returns (married, children, notes)."""
        keys=employee.keys() if hasattr(employee,"keys") else []
        value=lambda name: (employee[name] if name in keys else None) or ""
        married=str(value("marital_status")).lower() in ("married","spouse"); notes=[]
        marriage=str(value("marriage_date")).strip()
        if marriage:
            married_by_then=iso_date(marriage)<=day
            if married_by_then and not married: notes.append(f"Married from {display_date(iso_date(marriage))}: spouse counted")
            if not married_by_then and married: notes.append(f"Married on {display_date(iso_date(marriage))}: not yet in this month")
            married=married_by_then
        births=cls.parse_birth_dates(value("children_birth_dates")) if str(value("children_birth_dates")).strip() else []
        total=max(int(value("children") or 0),len(births))
        later=[b for b in births if b>day]
        if later: notes.append(f"{len(later)} child(ren) born after this month not counted yet (born {', '.join(display_date(b) for b in later)})")
        new=[b for b in births if b<=day and b[:7]==day[:7]]
        if new: notes.append(f"New child born {', '.join(display_date(b) for b in new)}: counted from this month")
        return married,total-len(later),notes

    def list_employees(self, include_inactive=True):
        with self.connect() as db:
            where="" if include_inactive else "WHERE e.active=1"
            return [dict(row) for row in db.execute(f"""SELECT e.*,b.name branch_name
                FROM employees e LEFT JOIN branches b ON b.id=e.branch_id {where}
                ORDER BY e.employee_number""")]

    def nssf_filed_wages(self,year):
        year=int(year)
        if year<2000 or year>2100: raise ValueError("Enter a valid year")
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM nssf_filed_wages WHERE year=? ORDER BY month",(year,))]

    def save_nssf_filed_wages(self,item,user_id):
        year=int(item.get("year")); month=int(item.get("month"))
        if year<2000 or year>2100 or month<1 or month>12: raise ValueError("Enter a valid year and month")
        values=[]
        for key in ("sickness_wages","family_wages","end_service_wages","amount_paid"):
            raw=str(item.get(key) or "").strip().replace(",","")
            if raw:
                amount=Decimal(raw)
                if not amount.is_finite() or amount<0: raise ValueError(f"{key.replace('_',' ')} must be zero or positive")
                values.append(str(amount))
            else: values.append(None)
        with self.connect() as db:
            db.execute("""INSERT INTO nssf_filed_wages(year,month,sickness_wages,family_wages,end_service_wages,amount_paid,note,updated_by,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(year,month) DO UPDATE SET sickness_wages=excluded.sickness_wages,
                family_wages=excluded.family_wages,end_service_wages=excluded.end_service_wages,amount_paid=excluded.amount_paid,
                note=excluded.note,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                (year,month,*values,str(item.get("note") or "").strip(),user_id,utcnow()))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"update","nssf_filed_wages",None,json.dumps({"year":year,"month":month}),utcnow()))
        return next(row for row in self.nssf_filed_wages(year) if row["month"]==month)

    def next_employee_number(self, prefix="1000"):
        prefix="".join(ch for ch in str(prefix or "1000") if ch.isdigit())[:4]
        if len(prefix)!=4: raise ValueError("Employee prefix must contain 4 digits")
        with self.connect() as db:
            row=db.execute("""SELECT employee_number FROM employees
                WHERE employee_number LIKE ? AND length(employee_number)=9
                ORDER BY CAST(employee_number AS INTEGER) DESC LIMIT 1""",(prefix+"%",)).fetchone()
        suffix=int(row["employee_number"][4:])+1 if row else 1
        if suffix>99999: raise ValueError(f"No employee numbers remain under prefix {prefix}")
        return f"{prefix}{suffix:05d}"

    def save_employee(self,item,user_id):
        name=str(item.get("full_name") or "").strip()
        if not name: raise ValueError("Employee name is required")
        number="".join(ch for ch in str(item.get("employee_number") or "") if ch.isdigit())
        if len(number)==4: number=self.next_employee_number(number)
        elif not number: number=self.next_employee_number("1000")
        elif len(number)!=9: raise ValueError("Employee number must contain 9 digits (or enter a 4-digit prefix)")
        currency=str(item.get("currency") or "LBP").upper()
        if currency not in self.currency_codes(): raise ValueError("Invalid employee currency")
        try: base_salary = Decimal(str(item.get("base_salary") or 0))
        except (InvalidOperation, ValueError, TypeError) as exc: raise ValueError("Invalid base salary") from exc
        if not base_salary.is_finite() or base_salary < 0: raise ValueError("Base salary must be finite and cannot be negative")
        children=max(0,int(item.get("children") or 0)); spouse_works=1 if item.get("spouse_works",False) else 0; active=1 if item.get("active",True) else 0
        employee_group=str(item.get("employee_group") or "employee").lower()
        if employee_group not in ("employee","manager"): raise ValueError("Employee group must be Employee or Manager")
        hire_date=iso_date(item["hire_date"],"Starting date") if item.get("hire_date") else None
        leave_date=iso_date(item["leave_date"],"Leaving date") if item.get("leave_date") else None
        if hire_date and leave_date and leave_date<hire_date: raise ValueError("Leaving date cannot be before starting date")
        employee_id=item.get("id")
        values=(number,name,str(item.get("national_id") or "").strip(),str(item.get("mof_number") or "").strip(),
            str(item.get("nssf_number") or "").strip(),str(item.get("address") or "").strip(),str(item.get("contact_number") or "").strip(),
            str(item.get("nationality") or "").strip(),str(item.get("father_name") or "").strip(),str(item.get("mother_name") or "").strip(),
            iso_date(item["birth_date"]) if item.get("birth_date") else None,str(item.get("birth_place") or "").strip(),
            str(item.get("marital_status") or "single").lower(),spouse_works,children,employee_group,
            hire_date,leave_date,
            str(item.get("job_title") or "").strip(),int(item["branch_id"]) if item.get("branch_id") else None,currency,
            str(base_salary),str(item.get("salary_account") or "").split(" - ",1)[0].strip() or None,  # 2.9.80: empty = the Standard Posting Accounts (6311 / 6316)
            item.get("payable_account") or "421100001",active)
        with self.connect() as db:
            if employee_id:
                db.execute("""UPDATE employees SET employee_number=?,full_name=?,national_id=?,mof_number=?,nssf_number=?,address=?,contact_number=?,
                    nationality=?,father_name=?,mother_name=?,birth_date=?,birth_place=?,
                    marital_status=?,spouse_works=?,children=?,employee_group=?,hire_date=?,leave_date=?,job_title=?,branch_id=?,currency=?,base_salary=?,salary_account=?,payable_account=?,active=? WHERE id=?""",
                    values+(int(employee_id),)); saved_id=int(employee_id); action="update"
            else:
                saved_id=db.execute("""INSERT INTO employees(employee_number,full_name,national_id,mof_number,nssf_number,address,contact_number,
                    nationality,father_name,mother_name,birth_date,birth_place,
                    marital_status,spouse_works,children,employee_group,hire_date,leave_date,job_title,branch_id,currency,base_salary,salary_account,payable_account,active,created_by,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",values+(user_id,utcnow())).lastrowid; action="create"
            register={key:str(item.get(key) if item.get(key) is not None else "").strip() for key in self.EMPLOYEE_REGISTER_FIELDS if key in item}
            for key in self.EMPLOYEE_MONEY_FIELDS:
                if register.get(key):
                    try: amount=Decimal(register[key].replace(",",""))
                    except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError(f"{key.replace('_',' ').title()} must be a number") from exc
                    if amount<0: raise ValueError(f"{key.replace('_',' ').title()} cannot be negative")
                    register[key]=str(amount)
            for key in self.EMPLOYEE_FLAG_FIELDS:
                if key in register: register[key]="1" if register[key].lower() in ("1","true","yes","on") else "0"
            if register.get("marriage_date"): register["marriage_date"]=iso_date(register["marriage_date"],"Marriage date")  # 2.9.96
            if register.get("children_birth_dates"):
                births=self.parse_birth_dates(register["children_birth_dates"]); register["children_birth_dates"]=",".join(births)
                if len(births)>children: db.execute("UPDATE employees SET children=? WHERE id=?",(len(births),saved_id))  # every child listed is counted
            if register:
                db.execute(f"UPDATE employees SET {','.join(k+'=?' for k in register)} WHERE id=?",(*register.values(),saved_id))
            if "sex" in item:
                sex=str(item.get("sex") or "").strip().lower()
                sex={"m":"male","male":"male","ذكر":"male","f":"female","female":"female","أنثى":"female","انثى":"female"}.get(sex,"")
                db.execute("UPDATE employees SET sex=? WHERE id=?",(sex,saved_id))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,action,"employee",saved_id,json.dumps({"employee_number":number,"name":name}),utcnow()))
        return next(row for row in self.list_employees() if row["id"]==saved_id)

    def payroll_settings_for(self,period_date=None):
        try: target=iso_date(period_date) if period_date else datetime.now().strftime("%Y-%m-%d")
        except ValueError: target=datetime.now().strftime("%Y-%m-%d")
        with self.connect() as db:
            row=db.execute("""SELECT * FROM payroll_settings WHERE date_from<=? AND (date_to IS NULL OR date_to='' OR date_to>=?)
                ORDER BY date_from DESC LIMIT 1""",(target,target)).fetchone()
            if not row: row=db.execute("SELECT * FROM payroll_settings ORDER BY date_from DESC LIMIT 1").fetchone()
            official_auto=db.execute("SELECT value FROM app_settings WHERE key='lebanese_payroll_rules_auto'").fetchone()
        result=dict(row) if row else {}
        # Older auto-seeded company databases predate the schooling decree dates.
        # Apply published values in memory, keeping saved user settings untouched.
        schooling_keys=("schooling_public_child","schooling_public_cap","schooling_private_child","schooling_private_cap")
        if result and official_auto and all(Decimal(str(result.get(key) or 0))==0 for key in schooling_keys):
            import lebanese_payroll
            effective=[period for period in lebanese_payroll.official_periods() if period["date_from"]<=target]
            if effective:
                result.update({key:effective[-1][key] for key in schooling_keys})
                result["schooling_rules_date"]=effective[-1]["date_from"]
        if result:
            result["tax_brackets"]=json.loads(result["tax_brackets"])
            for key in ("employee_account_map","manager_account_map"):
                defaults=self.default_payroll_account_map(key)  # 2.9.80: managers default to 6316 (they took the staff 6311 map)
                try: result[key]={**defaults,**json.loads(result.get(key) or "{}")}
                except (TypeError,ValueError): result[key]=dict(defaults)
                if not result[key].get("family_allowance"): result[key]["family_allowance"] = "438"
        return result

    @staticmethod
    def default_payroll_account_map(key="employee_account_map"):
        import chart_extra
        return dict(chart_extra.MANAGER_PAYROLL_MAP if key=="manager_account_map" else chart_extra.PAYROLL_MAP)

    def list_payroll_settings(self):
        with self.connect() as db:
            rows=[dict(row) for row in db.execute("SELECT * FROM payroll_settings ORDER BY date_from")]
        for row in rows:
            row["tax_brackets"]=json.loads(row["tax_brackets"])
            for key in ("employee_account_map","manager_account_map"):
                try: row[key]=json.loads(row.get(key) or "{}")
                except (TypeError,ValueError): row[key]={}
        return rows

    def save_payroll_settings(self,item,user_id):
        if not str(item.get("date_from") or "").strip(): raise ValueError("Settings Date From is required")
        date_from=iso_date(item.get("date_from"),"Date From")
        date_to=iso_date(item.get("date_to"),"Date To") if str(item.get("date_to") or "").strip() else None
        if date_to and date_to<date_from: raise ValueError("Date To cannot be before Date From")
        if not isinstance(item.get("tax_brackets"),list) or not item.get("tax_brackets"): raise ValueError("At least one tax bracket is required")
        for field in ("employee_nssf_rate","medical_rate","end_service_rate","family_rate"):
            if item.get(field) not in (None,""):
                try: rate=Decimal(str(item.get(field)))
                except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError(f"{field.replace('_',' ').title()} must be a number such as 0.03") from exc
                if rate<0 or rate>=1: raise ValueError(f"{field.replace('_',' ').title()} must be a decimal rate between 0 and 1 (3% = 0.03)")
        for field in ("employee_ceiling","medical_ceiling","family_ceiling","end_service_ceiling","single_allowance","spouse_allowance","child_allowance"):
            if item.get(field) not in (None,""):
                try: value=Decimal(str(item.get(field)).replace(",",""))
                except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError(f"{field.replace('_',' ').title()} must be a number") from exc
                if value<0: raise ValueError(f"{field.replace('_',' ').title()} cannot be negative")
                item[field]=str(value)
        with self.connect() as db:
            later=db.execute("""SELECT date_from FROM payroll_settings WHERE date_from>? ORDER BY date_from LIMIT 1""",(date_from,)).fetchone()
            if later and (date_to is None or date_to>=later["date_from"]):
                if date_to is None: date_to=(datetime.strptime(later["date_from"],"%Y-%m-%d")-timedelta(days=1)).strftime("%Y-%m-%d")
                else: raise ValueError(f"This period overlaps the settings that start on {display_date(later['date_from'])}")
            closing=(datetime.strptime(date_from,"%Y-%m-%d")-timedelta(days=1)).strftime("%Y-%m-%d")
            db.execute("""UPDATE payroll_settings SET date_to=? WHERE date_from<? AND (date_to IS NULL OR date_to='' OR date_to>=?)""",(closing,date_from,date_from))
        item=dict(item); item["date_from"]=date_from; item["date_to"]=date_to
        brackets=item.get("tax_brackets")
        if not isinstance(brackets,list) or not brackets: raise ValueError("At least one tax bracket is required")
        fields=("single_allowance","spouse_allowance","child_allowance","employee_nssf_rate","medical_rate","end_service_rate","family_rate",
            "employee_ceiling","medical_ceiling","family_ceiling","end_service_ceiling","salary_account","salary_payable_account","payroll_tax_account","nssf_payable_account")
        values=[str(item.get(field) if item.get(field) is not None else self.payroll_settings_for(date_from).get(field,"0")) for field in fields]
        with self.connect() as db:
            db.execute("""INSERT INTO payroll_settings(date_from,date_to,tax_brackets,single_allowance,spouse_allowance,child_allowance,
                employee_nssf_rate,medical_rate,end_service_rate,family_rate,employee_ceiling,medical_ceiling,family_ceiling,end_service_ceiling,
                salary_account,salary_payable_account,payroll_tax_account,nssf_payable_account,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(date_from) DO UPDATE SET date_to=excluded.date_to,tax_brackets=excluded.tax_brackets,
                single_allowance=excluded.single_allowance,spouse_allowance=excluded.spouse_allowance,child_allowance=excluded.child_allowance,
                employee_nssf_rate=excluded.employee_nssf_rate,medical_rate=excluded.medical_rate,end_service_rate=excluded.end_service_rate,
                family_rate=excluded.family_rate,employee_ceiling=excluded.employee_ceiling,medical_ceiling=excluded.medical_ceiling,
                family_ceiling=excluded.family_ceiling,end_service_ceiling=excluded.end_service_ceiling,salary_account=excluded.salary_account,
                salary_payable_account=excluded.salary_payable_account,payroll_tax_account=excluded.payroll_tax_account,nssf_payable_account=excluded.nssf_payable_account""",
                (date_from,item.get("date_to") or None,json.dumps(brackets),*values,user_id,utcnow()))
            for key in ("employee_account_map","manager_account_map"):
                mapping={**self.default_payroll_account_map(key),**(item.get(key) or {})}
                db.execute(f"UPDATE payroll_settings SET {key}=? WHERE date_from=?",(json.dumps(mapping),date_from))
            for key in ("transport_daily_exempt","default_transport_days","schooling_annual_exempt","schooling_max_children",
                        "schooling_public_child","schooling_public_cap","schooling_private_child","schooling_private_cap","tax_rounding","minimum_wage",
                                "max_children_deduction","family_allowance_spouse","family_allowance_child","family_allowance_cap",
                                "family_allowance_max_children"):
                if item.get(key) not in (None,""):
                    try: value=str(Decimal(str(item[key]).replace(",","")))
                    except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError(f"{key.replace('_',' ').title()} must be a number") from exc
                    db.execute(f"UPDATE payroll_settings SET {key}=? WHERE date_from=?",(value,date_from))
        return self.payroll_settings_for(date_from)

    def apply_lebanese_payroll_rules(self,user_id):
        """Replace the effective-dated payroll settings with the official Lebanese periods (2024 onward), keeping the posting accounts."""
        import lebanese_payroll
        current=self.payroll_settings_for(None)
        maps={k:current.get(k) for k in ("employee_account_map","manager_account_map") if current.get(k)}
        accounts={k:current.get(k) for k in ("salary_account","salary_payable_account","payroll_tax_account","nssf_payable_account") if current.get(k)}
        with self.connect() as db: db.execute("DELETE FROM payroll_settings")
        for period in lebanese_payroll.official_periods():
            self.save_payroll_settings({**period,**accounts,**maps},user_id)
        with self.connect() as db:
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",(user_id,"apply","payroll_rules",
                    json.dumps({"periods":len(lebanese_payroll.PERIODS)}),utcnow()))
        return self.list_payroll_settings()

    @staticmethod
    def _progressive_tax(annual_taxable,brackets):
        remaining=max(Decimal("0"),annual_taxable); previous=Decimal("0"); tax=Decimal("0")
        for ceiling,rate in brackets:
            upper=Decimal(str(ceiling)) if ceiling is not None else None
            band=remaining if upper is None else min(remaining,max(Decimal("0"),upper-previous))
            tax+=band*Decimal(str(rate)); remaining-=band
            if remaining<=0: break
            if upper is not None: previous=upper
        return tax

    def calculate_payroll(self,item):
        """Monthly payroll under the Lebanese rules effective on the payroll date.

        - Recurring pay (salary, overtime, commission and the taxable part of transport / schooling) is taxed
          on the annualised basis: tax(12 x monthly - family deductions) / 12.
        - Bonus and 13th salary are one-off income: tax(annual regular + one-off) - tax(annual regular).
        - Retroactive salary is taxed as if paid in its own months (Retro From / To), and its NSSF uses the
          ceiling of each of those months.
        - Transport is exempt up to the daily amount x days worked; schooling up to the annual limit.
        - NSSF uses the earnings base under CNSS Contribution System 11; transport and schooling are still
          included even where part of them is exempt from salary tax. Branch ceilings are effective-dated.
        - Tax is rounded up to the rounding amount (LBP 10,000 from 25-11-2024) and converted to the salary currency."""
        employee_id=int(item.get("employee_id") or 0); period=str(item.get("period_date") or "").strip()
        if not employee_id or not period: raise ValueError("Select an employee and payroll period")
        period=iso_date(period,"Payroll period")
        with self.connect() as db: employee=db.execute("SELECT * FROM employees WHERE id=?",(employee_id,)).fetchone()
        if not employee: raise ValueError("Employee was not found")
        rules_date=self.month_end(period); settings=self.payroll_settings_for(rules_date); D=Decimal
        def setting(name,default="0"):
            try: return D(str(settings.get(name) if settings.get(name) not in (None,"") else default))
            except (InvalidOperation,ValueError,TypeError) as exc:  # 2.9.119: a payroll rate that is not a number stops the payroll
                raise ValueError(f"Payroll setting {name.replace('_',' ')} is not a number ({settings.get(name)!r}): correct it in Tax & NSSF Settings") from exc
        money={}
        # Director remuneration is paid with the payroll but is NOT subject to salary tax (and not to NSSF);
        # it is part of gross and net pay and is posted to its own account.
        for name in ("salary","transport","overtime","commission","retro_salary","schooling","bonus","thirteenth_month","director_remuneration"):
            raw=item.get(name) if item.get(name) not in (None,"") else (employee["base_salary"] if name=="salary" else 0)
            try: money[name]=D(str(raw).replace(",",""))
            except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError(f"{name.replace('_',' ').title()} must be a number") from exc
            if not money[name].is_finite() or money[name]<0: raise ValueError(f"{name.replace('_',' ').title()} cannot be negative")
        import payroll_lines
        allowances=payroll_lines.clean_allowances(item.get("allowances"))
        allowance_accounts = item.get("allowance_accounts") or {}
        if isinstance(allowance_accounts, str):
            try: allowance_accounts = json.loads(allowance_accounts)
            except ValueError as exc: raise ValueError("Invalid allowance accounts") from exc
        if not isinstance(allowance_accounts, dict): raise ValueError("Invalid allowance accounts")
        allowance_accounts = {key: str(code).split(" - ", 1)[0].strip() for key, code in allowance_accounts.items() if code}
        with self.connect() as db:
            for key, code in allowance_accounts.items():
                account = db.execute("SELECT type,active FROM accounts WHERE code=?", (code,)).fetchone()
                if key not in payroll_lines.ALLOWANCES or not account or not account["active"] or account["type"] != "expense":
                    raise ValueError(f"Choose an active expense account for allowance {key}")
        not_nssf=self.allowances_not_nssf()
        allowance_parts=payroll_lines.split(allowances,not_nssf)
        # The selected date identifies a payroll month. Prorate a monthly base salary
        # when the employee joined or left during that month; an edited salary is the actual amount.
        month_start=rules_date[:8]+"01"
        month_days=(datetime.strptime(rules_date,"%Y-%m-%d")-datetime.strptime(month_start,"%Y-%m-%d")).days+1
        active_start=max(month_start,iso_date(employee["hire_date"]) if employee["hire_date"] else month_start)
        active_end=min(rules_date,iso_date(employee["leave_date"]) if employee["leave_date"] else rules_date)
        worked_days=max(0,(datetime.strptime(active_end,"%Y-%m-%d")-datetime.strptime(active_start,"%Y-%m-%d")).days+1)
        if not worked_days: raise ValueError("Employee did not work in the selected payroll month")
        work_fraction=D(worked_days)/D(month_days)
        tax_days=max(0,(30 if active_end==rules_date else min(int(active_end[-2:]),30))-min(int(active_start[-2:]),30)+1)
        tax_fraction=D(tax_days)/D(30)
        base_salary=D(str(employee["base_salary"] or 0))
        if worked_days<month_days and money["salary"]==base_salary:
            money["salary"]=(base_salary*work_fraction).quantize(D("0.01"))
        currency=employee["currency"]; brackets=settings.get("tax_brackets",[]); notes=[]
        if worked_days<month_days:
            notes.append(f"Partial payroll: {worked_days}/{month_days} calendar days; base salary and tax bands/deductions prorated")
        to_lbp=lambda value,day=period: self._converted_amount(value,currency,"LBP",day)
        from_lbp=lambda value,day=period: self._converted_amount(value,"LBP",currency,day)
        try: days=int(D(str(item.get("transport_days") if item.get("transport_days") not in (None,"") else setting("default_transport_days","26"))))
        except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError("Transport days must be a whole number") from exc
        raw_days = D(str(item.get("transport_days") if item.get("transport_days") not in (None, "") else setting("default_transport_days", "26")))
        if raw_days != days: raise ValueError("Transport days must be a whole number")
        if days<0 or days>31: raise ValueError("Transport days must be between 0 and 31")
        if worked_days < month_days:
            if item.get("transport_days") in (None, ""):
                days = min(days, worked_days)
            elif days > worked_days:
                raise ValueError(f"Transport days cannot exceed {worked_days} days in the employee's employment period")
        import lebanese_payroll
        food_from,food_daily=lebanese_payroll.FOOD_DAILY_EXEMPT  # 2.9.92: Budget Law 2026 Art. 26
        if rules_date>=food_from and allowances.get("food_exempt"):
            limit=from_lbp(D(food_daily)*days).quantize(D("0.01"))
            if allowances["food_exempt"]>limit:
                excess=allowances["food_exempt"]-limit
                allowances["food_exempt"]=limit; allowances["food_taxable"]=allowances.get("food_taxable",D("0"))+excess
                allowance_parts=payroll_lines.split(allowances,not_nssf)
                notes.append(f"Food allowance above the exempt LBP {food_daily:,} x {days} days moved to taxable (Budget Law 2026 Art. 26)")
        exempt_transport_lbp=min(to_lbp(money["transport"]),setting("transport_daily_exempt")*days)
        married,children,family_notes=self.family_on(employee,rules_date); notes.extend(family_notes)  # 2.9.96: as on the month end
        schooling_limit=setting("schooling_annual_exempt") if min(children,int(setting("schooling_max_children","3")))>0 else D("0")
        with self.connect() as db:
            past_schooling=db.execute("""SELECT period_date,currency,exempt_schooling FROM payroll_records
                WHERE employee_id=? AND period_date>=? AND period_date<?""",
                (employee_id,period[:4]+"-01-01",month_start)).fetchall()
        already_exempt=sum((self._converted_amount(D(str(row["exempt_schooling"] or 0)),row["currency"],"LBP",row["period_date"])
                            for row in past_schooling),D("0"))
        exempt_schooling_lbp=min(to_lbp(money["schooling"]),max(D("0"),schooling_limit-already_exempt))
        taxable_transport_lbp=to_lbp(money["transport"])-exempt_transport_lbp; taxable_schooling_lbp=to_lbp(money["schooling"])-exempt_schooling_lbp
        if taxable_transport_lbp>0: notes.append(f"Transport above the exempt {int(setting('transport_daily_exempt')):,} LBP x {days} days is taxed")
        if taxable_schooling_lbp>0: notes.append("Schooling above the exempt annual limit is taxed")
        allowance=setting("single_allowance")
        spouse_works=married and bool(int(employee["spouse_works"] or 0))
        # The personal deduction belongs to each employee. A spouse deduction applies
        # only for a dependent spouse; when both parents work, split only the child deduction.
        dependent_spouse_deduction=setting("spouse_allowance") if married and not spouse_works else D("0")
        child_deduction=setting("child_allowance")*min(children,int(setting("max_children_deduction","5")))
        if spouse_works and child_deduction:
            child_deduction/=2
            notes.append("Child tax deduction split equally because both spouses work")
        allowance+=dependent_spouse_deduction+child_deduction
        if children>int(setting("max_children_deduction","5")): notes.append(f"Family deduction limited to {int(setting('max_children_deduction','5'))} children")
        regular_lbp=to_lbp(money["salary"]+money["overtime"]+money["commission"]+allowance_parts["taxable_recurring"])+taxable_transport_lbp+taxable_schooling_lbp
        tax=lambda annual: self._progressive_tax(max(D("0"),annual-allowance),brackets)
        annual_regular=regular_lbp*12/tax_fraction
        regular_tax=tax(annual_regular)*tax_fraction/12
        one_off_lbp=to_lbp(money["bonus"]+money["thirteenth_month"]+allowance_parts["taxable_one_off"])
        one_off_tax=(tax(annual_regular+one_off_lbp/tax_fraction)-tax(annual_regular))*tax_fraction
        retro_tax=D("0"); retro_months=[]
        if money["retro_salary"]:
            start=iso_date(item.get("retro_from") or period,"Retro From"); end=iso_date(item.get("retro_to") or period,"Retro To")
            if end<start: raise ValueError("Retro To cannot be before Retro From")
            y,m=int(start[:4]),int(start[5:7])
            while (y,m)<=(int(end[:4]),int(end[5:7])):
                retro_months.append(self.month_end(f"{y}-{m:02d}-01")); m+=1
                if m>12: y,m=y+1,1
            share=money["retro_salary"]/len(retro_months)
            for month in retro_months:
                month_settings=self.payroll_settings_for(month); month_brackets=month_settings.get("tax_brackets",brackets)
                month_allowance=D(str(month_settings.get("single_allowance") or 0))
                month_married,month_kids,_n=self.family_on(employee,month)  # 2.9.96: the family of THAT month
                month_spouse_works=month_married and bool(int(employee["spouse_works"] or 0))
                if month_married and not month_spouse_works:
                    month_allowance+=D(str(month_settings.get("spouse_allowance") or 0))
                month_children=min(month_kids,int(month_settings.get("max_children_deduction") or 5))
                month_child_allowance=D(str(month_settings.get("child_allowance") or 0))*month_children
                month_allowance+=month_child_allowance/2 if month_spouse_works else month_child_allowance
                monthly=lambda annual: self._progressive_tax(max(D("0"),annual-month_allowance),month_brackets)/12
                # 2.9.78: the retro is added to what was REALLY paid that month: tax on (pay of the month + retro) less the tax
                # already withheld that month. Without a saved payroll for that month, this month's pay stands in for it.
                with self.connect() as db:
                    paid=db.execute("""SELECT * FROM payroll_records WHERE employee_id=? AND period_date>=? AND period_date<=?
                        ORDER BY period_date DESC LIMIT 1""",(employee_id,month[:8]+"01",month)).fetchone()
                if paid:
                    gross=sum((D(str(paid[key] or 0)) for key in ("salary","transport","overtime","commission","schooling")),D("0"))+self._record_taxable_allowances(paid)
                    exempt=D(str(paid["exempt_transport"] or 0))+D(str(paid["exempt_schooling"] or 0))
                    paid_base=self._converted_amount(max(D("0"),gross-exempt),paid["currency"],"LBP",paid["period_date"])
                    earlier_retro=D(str(paid["retro_tax_lbp"] or 0)) if "retro_tax_lbp" in paid.keys() else \
                        self._converted_amount(D(str(paid["retro_tax"] or 0)),paid["currency"],"LBP",paid["period_date"]) if "retro_tax" in paid.keys() else D("0")
                    withheld=D(str(paid["income_tax_lbp"] or 0))-earlier_retro
                    one_off=self._converted_amount(D(str(paid["bonus"] or 0))+D(str(paid["thirteenth_month"] or 0)),paid["currency"],"LBP",paid["period_date"])
                    with_retro=monthly((paid_base+to_lbp(share,month))*12)+(monthly((paid_base+to_lbp(share,month))*12+one_off)-monthly((paid_base+to_lbp(share,month))*12))*12
                    retro_tax+=max(D("0"),with_retro-withheld)
                    notes.append(f"Retro {month[:7]}: tax on the pay of that month + retro, less {withheld:,.0f} LBP already withheld")
                else:
                    retro_tax+=monthly((regular_lbp+to_lbp(share,month))*12)-monthly(regular_lbp*12)
                    notes.append(f"Retro {month[:7]}: no payroll saved for that month - this month's pay used as its pay")
        # Salary tax withholding is cumulative across payrolls saved this year.
        # Retros use the separate prior-period treatment above.
        with self.connect() as db:
            previous=db.execute("""SELECT * FROM payroll_records
                WHERE employee_id=? AND period_date>=? AND period_date<? ORDER BY period_date""",
                (employee_id,period[:4]+"-01-01",month_start)).fetchall()
        if previous:
            prior_base=D("0"); prior_withheld=D("0"); elapsed=tax_fraction
            for record in previous:
                gross=sum((D(str(record[key] or 0)) for key in
                    ("salary","transport","overtime","commission","schooling","bonus","thirteenth_month")),D("0"))
                exempt=D(str(record["exempt_transport"] or 0))+D(str(record["exempt_schooling"] or 0))
                gross+=self._record_taxable_allowances(record)
                prior_base+=self._converted_amount(max(D("0"),gross-exempt),record["currency"],"LBP",record["period_date"])
                # Retro tax belongs to its own periods, outside this cumulative base.
                prior_retro=self._converted_amount(D(str(record["retro_tax"] or 0)),record["currency"],"LBP",record["period_date"])
                prior_withheld+=max(D("0"),D(str(record["income_tax_lbp"] or 0))-prior_retro)
                prior_end=self.month_end(record["period_date"])
                prior_start=prior_end[:8]+"01"
                active_from=max(prior_start,iso_date(employee["hire_date"]) if employee["hire_date"] else prior_start)
                active_to=min(prior_end,iso_date(employee["leave_date"]) if employee["leave_date"] else prior_end)
                prior_days=max(0,(30 if active_to==prior_end else min(int(active_to[-2:]),30))-min(int(active_from[-2:]),30)+1)
                elapsed+=D(prior_days)/30
            bands=[[D(str(ceiling))*elapsed/12 if ceiling is not None else None,rate] for ceiling,rate in brackets]
            def cumulative(base):
                return self._progressive_tax(max(D("0"),prior_base+base-allowance*elapsed/12),bands)
            base_due=cumulative(regular_lbp)
            full_due=cumulative(regular_lbp+one_off_lbp)
            regular_tax=max(D("0"),base_due-prior_withheld)
            one_off_tax=max(D("0"),full_due-prior_withheld)-regular_tax
            notes.append(f"Cumulative tax: {len(previous)+1} payroll months; total due {full_due:,.2f} LBP "
                         f"less {prior_withheld:,.2f} LBP already withheld = "
                         f"{regular_tax+one_off_tax:,.2f} LBP this month before rounding (retro tax separate)")
        rounding=setting("tax_rounding")
        def rounded(value):
            value=max(D("0"),value)
            if rounding>0 and value>0: return ((value/rounding).to_integral_value(rounding="ROUND_CEILING"))*rounding
            return value.quantize(D("0.01"))
        income_tax_lbp=rounded(regular_tax+one_off_tax+retro_tax)
        retro_tax_lbp=min(income_tax_lbp,max(D("0"),retro_tax).quantize(D("0.01")))
        income_tax=from_lbp(income_tax_lbp).quantize(D("0.01")); retro_tax_value=from_lbp(retro_tax_lbp).quantize(D("0.01"))
        taxable_lbp=max(D("0"),annual_regular-allowance)*tax_fraction/12+one_off_lbp
        # NSSF: salary, overtime, commission, bonus and 13th this month; retroactive salary in its own months.
        base_lbp=to_lbp(money["salary"]+money["overtime"]+money["commission"]+money["bonus"]+money["thirteenth_month"]+allowance_parts["nssf"])
        def contribution(ceiling_name,rate_name,base,month_settings):
            limit=D(str(month_settings.get(ceiling_name) or 0)); capped=min(base,limit) if limit>0 else base
            return capped*D(str(month_settings.get(rate_name) or 0))
        totals={name:contribution(ceiling,rate,base_lbp,settings) for name,ceiling,rate in (("employee","employee_ceiling","employee_nssf_rate"),("medical","medical_ceiling","medical_rate"),
                ("family","family_ceiling","family_rate"),("end_service","end_service_ceiling","end_service_rate"))}
        if money["retro_salary"]:
            share=money["retro_salary"]/len(retro_months)
            for month in retro_months:
                month_settings=self.payroll_settings_for(month); regular_month=to_lbp(money["salary"]+
                    money["overtime"]+money["commission"],month); extra=to_lbp(share,month)
                for name,ceiling,rate in (("employee","employee_ceiling","employee_nssf_rate"),("medical","medical_ceiling","medical_rate"),("family",
                        "family_ceiling","family_rate"),("end_service","end_service_ceiling","end_service_rate")):
                    totals[name]+=contribution(ceiling,rate,regular_month+extra,month_settings)-contribution(ceiling,rate,regular_month,month_settings)
        # Eligibility remains category-specific: the nationality/age shortcut below is only a warning-bearing
        # approximation. Confirm CNSS coverage and any reciprocal-agreement exception before relying on it.
        age=None
        if employee["birth_date"]:
            try:
                birth=iso_date(str(employee["birth_date"]),"Date of birth")
                age=int(period[:4])-int(birth[:4])-(1 if period[5:]<birth[5:] else 0)
            except (KeyError, TypeError, ValueError): age=None
        nationality=str(employee["nationality"] or "").strip().lower()
        lebanese_terms=("lebanese","lebanon","lb","\u0644\u0628\u0646\u0627\u0646\u064a","\u0644\u0628\u0646\u0627\u0646\u064a\u0629","\u0644\u0628\u0646\u0627\u0646")
        is_foreign=bool(nationality) and not any(term in nationality for term in lebanese_terms)
        if totals["end_service"]>0 and (is_foreign or (age is not None and age>64)):
            totals["end_service"]=D("0")
            reason="foreign national" if is_foreign else "over 64"
            notes.append(f"Employer end-of-service contribution was skipped by the app's nationality/age rule ({reason}); "
                         "eligibility depends on the employee's CNSS category and must be confirmed before filing")
        keys=employee.keys()
        flag=lambda name: name in keys and str(employee[name] or "0")=="1"
        if flag("nssf_no_end_service"): totals["end_service"]=D("0"); notes.append("Not subject to NSSF end-of-service (employee register)")
        if flag("nssf_no_family"): totals["family"]=D("0"); notes.append("Not subject to NSSF family allowances (employee register)")
        if flag("nssf_no_medical"): totals["medical"]=D("0"); totals["employee"]=D("0"); notes.append("Not subject to NSSF sickness & maternity (employee register)")
        nssf={name:(value.quantize(D("0.01")),from_lbp(value).quantize(D("0.01"))) for name,value in totals.items()}
        # NSSF family allowances paid with the salary on behalf of the NSSF (not taxable, offset against NSSF dues).
        allowance_lbp=D("0")
        if setting("family_allowance_cap")>0 or setting("family_allowance_child")>0:
            if married and not int(employee["spouse_works"] or 0): allowance_lbp+=setting("family_allowance_spouse")  # 2.9.96: married by the month end
            allowance_lbp+=setting("family_allowance_child")*min(children,int(setting("family_allowance_max_children","5")))
            if setting("family_allowance_cap")>0: allowance_lbp=min(allowance_lbp,setting("family_allowance_cap"))
        family_allowance=from_lbp(allowance_lbp).quantize(D("0.01"))
        override=str(item.get("family_allowance_override") if item.get("family_allowance_override") is not None else "").replace(",","").strip()
        if override:
            try: family_allowance=D(override).quantize(D("0.01"))
            except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError("Family Allocation must be a number") from exc
            if not family_allowance.is_finite() or family_allowance<0: raise ValueError("Family Allocation cannot be negative")
            notes.append("Family allocation entered manually for this payroll")
        if money["director_remuneration"]: notes.append("Director remuneration is not subject to salary tax or NSSF (as configured); confirm with your accountant")
        minimum=setting("minimum_wage")
        if minimum>0 and to_lbp(money["salary"])<minimum: notes.append(f"Salary is below the minimum wage of {int(minimum):,} LBP for this period")
        if not str(employee["nssf_number"] or "").strip(): notes.append("NSSF number missing in the employee file")
        if not str(employee["mof_number"] or "").strip(): notes.append("MOF (tax) number missing in the employee file")
        gross=sum(money.values(),D("0"))+allowance_parts["total"]
        net=(gross-income_tax-nssf["employee"][1]+family_allowance).quantize(D("0.01"))
        salary_base=money["salary"]+money["overtime"]+money["commission"]+money["retro_salary"]+money["bonus"]+money["thirteenth_month"]+allowance_parts["nssf"]
        return {**{k:float(v) for k,v in money.items()},"gross_salary":float(gross),"taxable_salary":float(from_lbp(taxable_lbp).quantize(D("0.01"))),
            "income_tax":float(income_tax),"income_tax_lbp":float(income_tax_lbp),"nssf_base":float(salary_base),"employee_nssf":float(nssf["employee"][1]),
            "employee_nssf_lbp":float(nssf["employee"][0]),"employer_medical":float(nssf["medical"][1]),"employer_end_service":float(nssf["end_service"][1]),
            "employer_family":float(nssf["family"][1]),"net_salary":float(net),"currency":currency,"retro_tax":float(retro_tax_value),"retro_tax_lbp":float(retro_tax_lbp),
            "regular_tax":float(from_lbp(rounded(regular_tax)).quantize(D("0.01"))),"one_off_tax":float(from_lbp(max(D("0"),one_off_tax)).quantize(D("0.01"))),
            "worked_days":worked_days,"calendar_days":month_days,"transport_days":days,
                    "exempt_transport":float(from_lbp(exempt_transport_lbp).quantize(D("0.01"))),
                    "exempt_schooling":float(from_lbp(exempt_schooling_lbp).quantize(D("0.01"))),
            "allowance_accounts": allowance_accounts, "family_allowance":float(family_allowance),"family_deduction_lbp":float(allowance),
            "annualized_recurring_lbp":float(annual_regular),"annualized_taxable_lbp":float(max(D("0"),annual_regular-allowance)),
            "compliance_notes":notes,"period_date":period,"allowances":{k:float(v) for k,v in allowances.items()},
            "allowances_total":float(allowance_parts["total"]),"allowances_taxable":float(allowance_parts["taxable_recurring"]+allowance_parts["taxable_one_off"]),
            "settings_period":{"date_from":settings.get("date_from"),"date_to":settings.get("date_to")},"rules_date":rules_date,
            "ceilings":{"medical":float(D(str(settings.get("medical_ceiling") or 0))),"family":float(D(str(settings.get("family_ceiling") or 0)))}}

    def allowances_not_nssf(self):
        """Taxable allowances the company treats as not subject to NSSF (app setting, JSON list of codes)."""
        try: value=json.loads(self.settings().get("payroll_allowances_not_nssf") or "[]")
        except ValueError: value=[]
        return tuple(code for code in value if isinstance(code,str))

    @staticmethod
    def _record_allowances(record):
        try: data=json.loads(record["allowances"] or "{}") if "allowances" in record.keys() else {}
        except (ValueError,TypeError): data={}
        return {k:Decimal(str(v)) for k,v in data.items() if v}

    def _record_taxable_allowances(self,record):
        import payroll_lines
        return sum((v for k,v in self._record_allowances(record).items() if k in payroll_lines.ALLOWANCES and payroll_lines.ALLOWANCES[k][1]),Decimal("0"))

    def list_payroll(self,period_from=None,period_to=None):
        conditions=[]; values=[]
        if period_from: conditions.append("p.period_date>=?"); values.append(iso_date(period_from))
        if period_to: conditions.append("p.period_date<=?"); values.append(iso_date(period_to))
        where=" WHERE "+" AND ".join(conditions) if conditions else ""
        with self.connect() as db:
            return [dict(row) for row in db.execute(f"""SELECT p.*,e.employee_number,e.full_name FROM payroll_records p
                JOIN employees e ON e.id=p.employee_id{where} ORDER BY p.period_date DESC,p.payroll_number DESC""",values)]

    @atomic
    def save_payroll(self,item,user_id):
        calc=self.calculate_payroll(item); employee_id=int(item["employee_id"]); period=calc["period_date"]
        self._assert_period_open(period)
        retro_from=iso_date(item["retro_from"],"Retro From") if item.get("retro_from") else None
        retro_to=iso_date(item["retro_to"],"Retro To") if item.get("retro_to") else None
        if calc["retro_salary"] and (not retro_from or not retro_to): raise ValueError("Enter Retro From and Retro To dates for the retroactive salary")
        if retro_from and retro_to and retro_to<retro_from: raise ValueError("Retro To cannot be before Retro From")
        number=str(item.get("payroll_number") or "").strip()
        with self.connect() as db:
            same_month=db.execute("SELECT period_date FROM payroll_records WHERE employee_id=? AND substr(period_date,1,7)=? AND period_date<>? LIMIT 1",
                                  (employee_id,period[:7],period)).fetchone()
            if same_month:
                raise ValueError(f"Payroll is already saved for this employee in {period[:7]} on {same_month['period_date']}; open that record instead")
            later=db.execute("SELECT period_date FROM payroll_records WHERE employee_id=? AND period_date>? AND substr(period_date,1,4)=? AND status='posted' ORDER BY period_date LIMIT 1",
                             (employee_id,self.month_end(period),period[:4])).fetchone()
            if later:
                raise ValueError(f"Cannot change {period[:7]} payroll: later payroll {later['period_date']} is posted; its cumulative tax would become incorrect")
            # 2.9.126: an update keeps its record and its number; a number is allocated only for a new record.
            record_id=item.get("id") or item.get("payroll_id")
            if record_id not in (None,""):
                existing=db.execute("SELECT id,employee_id,period_date,status,payroll_number FROM payroll_records WHERE id=?",(int(record_id),)).fetchone()
                if not existing: raise KeyError("Payroll record not found")
                if int(existing["employee_id"])!=employee_id: raise ValueError("This payroll record belongs to another employee")
                if existing["period_date"]!=period:
                    raise ValueError(f"This payroll record is for {existing['period_date']}; it cannot be moved to {period}")
            else:
                existing=db.execute("SELECT id,employee_id,period_date,status,payroll_number FROM payroll_records WHERE employee_id=? AND period_date=?",
                                    (employee_id,period)).fetchone()
            if existing and existing["status"]=="posted": raise ValueError("Posted payroll cannot be changed")
            if existing: number=existing["payroll_number"]
            elif not number:
                prefix=f"PAY-{period[:7].replace('-','')}-"; row=db.execute("SELECT payroll_number FROM payroll_records WHERE payroll_number LIKE ? ORDER BY payroll_number DESC LIMIT 1",
                        (prefix+"%",)).fetchone()
                number=f"{prefix}{(int(row['payroll_number'].rsplit('-',1)[-1])+1 if row else 1):06d}"
            fields=("salary","transport","overtime","commission","retro_salary","schooling","bonus","thirteenth_month","director_remuneration","gross_salary",
                    "taxable_salary","income_tax","income_tax_lbp",
                "nssf_base","employee_nssf","employer_medical","employer_end_service","employer_family","net_salary","retro_tax",
                "transport_days","exempt_transport","exempt_schooling","family_allowance","regular_tax","one_off_tax","compliance_notes","allowances","allowance_accounts")
            values=[json.dumps(calc[field]) if field in ("compliance_notes","allowances","allowance_accounts") else str(calc[field]) for field in fields]
            if existing:
                db.execute(f"UPDATE payroll_records SET payroll_number=?,currency=?,{','.join(field+'=?' for field in fields)},retro_from=?,retro_to=?,reference=?,notes=? WHERE id=?",
                    (number,calc["currency"],*values,retro_from,retro_to,item.get("reference"),item.get("notes"),existing["id"])); saved_id=existing["id"]
            else:
                columns=",".join(fields); marks=",".join("?" for _ in fields)
                saved_id=db.execute(f"INSERT INTO payroll_records(payroll_number,employee_id,period_date,currency,{columns},retro_from,retro_to,reference,notes,created_by,created_at) VALUES(?,?,?,?,{marks},?,?,?,?,?,?)",
                    (number,employee_id,period,calc["currency"],*values,retro_from,retro_to,item.get("reference"),item.get("notes"),user_id,utcnow())).lastrowid
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"update" if existing else "save","payroll",saved_id,json.dumps({"payroll_number":number}),utcnow()))
        return next(row for row in self.list_payroll() if row["id"]==saved_id)

    @atomic
    def post_payroll(self,payroll_id,user_id):
        with self.connect() as db:
            record=db.execute("""SELECT p.*,e.full_name,e.salary_account employee_salary_account,
                e.payable_account employee_payable_account,e.branch_id,e.employee_group FROM payroll_records p
                JOIN employees e ON e.id=p.employee_id WHERE p.id=?""",(int(payroll_id),)).fetchone()
            if not record: raise KeyError("Payroll record not found")
            if record["status"]=="posted": raise ValueError("Payroll is already posted")
            duplicate=db.execute("SELECT 1 FROM payroll_records WHERE employee_id=? AND substr(period_date,1,7)=? AND id<>? LIMIT 1",
                                 (record["employee_id"],record["period_date"][:7],record["id"])).fetchone()
            if duplicate: raise ValueError("More than one payroll exists for this employee in this month; correct the duplicate before posting")
            payload=dict(record); payload["allowances"]=self._record_allowances(record)
            payload["family_allowance_override"]=record["family_allowance"]
            current=self.calculate_payroll(payload)
            if abs(Decimal(str(current["income_tax_lbp"]))-Decimal(str(record["income_tax_lbp"] or 0)))>Decimal("0.01"):
                raise ValueError("Payroll tax is outdated: recalculate and save this payroll before posting")
            self._assert_period_open(record["period_date"])
            settings=self.payroll_settings_for(record["period_date"])
            mapping=dict(settings["manager_account_map"] if record["employee_group"]=="manager" else settings["employee_account_map"])
            salary_account=record["employee_salary_account"] or mapping["salary"]
            payable_account=record["employee_payable_account"] or mapping["payable"]
            mapping["salary"]=salary_account; mapping["payable"]=payable_account
            tax_account=mapping["tax"]; nssf_account=mapping["nssf"]
            employer_expense=str(mapping.get("employer_social") or "").strip() or "6351"  # 2.9.80: was 621100002 (6211 = sub-contractors in the Lebanese chart)
            component_names={"salary":"Salaries and Wages","transport":"Transportation","overtime":"Overtime","commission":"Commission",
                    "retro_salary":"Retroactive Salary","schooling":"Schooling Allowance","bonus":"Bonus","thirteenth_month":"13th Salary",
                    "director_remuneration":"Director Remuneration"}
            required=[(mapping[key],name,"expense") for key,name in component_names.items()]
            required+=((salary_account,"Salaries and Wages","expense"),(employer_expense,"Employer NSSF Contributions","expense"),
                (payable_account,"Salaries Payable","liability"),(tax_account,"Payroll Tax Payable","liability"),(nssf_account,"NSSF Payable","liability"))
            for code,name,kind in required:
                db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)",(code,name,kind))
            gross=Decimal(record["gross_salary"]); net=Decimal(record["net_salary"]); tax=Decimal(record["income_tax"])
            employee_nssf=Decimal(record["employee_nssf"])
            employer_nssf=sum((Decimal(record[name]) for name in ("employer_medical","employer_end_service","employer_family")),Decimal("0"))
            number=f'PAYJV-{record["payroll_number"]}'
            entry_id=db.execute("""INSERT INTO journal_entries(entry_number,entry_date,description,source_type,source_id,currency,branch_id,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",(number,display_date(record["period_date"]),f'Payroll {record["period_date"][5:7]}/{record["period_date"][:4]} - {record["full_name"]}',"payroll",record["id"],
                        record["currency"],record["branch_id"],user_id,utcnow())).lastrowid
            lines=[(mapping[key],Decimal(str(record[key] or 0)),Decimal("0")) for key in component_names]
            saved_allowance_accounts = json.loads(record["allowance_accounts"] or "{}")
            for allowance_code, allowance_amount in self._record_allowances(record).items():
                allowance_account = str(saved_allowance_accounts.get(allowance_code) or mapping.get(f"allowance_{allowance_code}") or mapping.get("allowances") or salary_account).strip()
                account = db.execute("SELECT type,active FROM accounts WHERE code=?", (allowance_account,)).fetchone()
                if not account or account["type"] != "expense" or not account["active"]:
                    raise ValueError(f"Choose an active expense account for allowance {allowance_code}")
                lines.append((allowance_account, allowance_amount, Decimal("0")))
            family_allowance=Decimal(str(record["family_allowance"] or 0)) if "family_allowance" in record.keys() else Decimal("0")
            # Family allocation: recoverable from social security on 438, or the configured account.
            family_account=str(mapping.get("family_allowance") or "438").strip()
            if family_account!=nssf_account: db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)",(family_account,"Family Allocation","asset"))
            lines+=((employer_expense,employer_nssf,Decimal("0")),(payable_account,Decimal("0"),net),(tax_account,Decimal("0"),tax),(nssf_account,Decimal("0"),
                    employee_nssf+employer_nssf),(family_account,family_allowance,Decimal("0")))
            # 2.9.84: the salary tax is due in LBP. For a USD (or other currency) payslip the tax line carries the exact LBP tax
            # (income_tax_lbp) as its LBP value, so 4411 in LBP agrees with the tax return; the LBP rounding goes to the salary line.
            special={}
            tax_lbp=Decimal(str(record["income_tax_lbp"] or 0)) if "income_tax_lbp" in record.keys() else Decimal("0")
            if record["currency"]!="LBP" and tax and tax_lbp:
                try:
                    rate=self._converted_amount(Decimal("1"),record["currency"],"LBP",record["period_date"])
                    usd=self._converted_amount(Decimal("1"),record["currency"],"USD",record["period_date"])
                except ValueError: rate=None
                if rate:
                    # the line stays in the payslip currency (each currency of the books balances on its own, as the year close needs)
                    special[(tax_account,"C")]={"line_currency":record["currency"],"amount":tax,"amount_lbp":tax_lbp,"amount_usd":(tax*usd).quantize(Decimal("0.01"))}
                    difference=tax_lbp-tax*rate
                    target=next(((code,d) for code,d,_c in lines if d>0 and code==salary_account),None) or next(((code,d) for code,d,_c in lines if d>0),None)
                    if difference and target:
                        special[(target[0],"D")]={"line_currency":record["currency"],"amount":target[1],"amount_lbp":(target[1]*rate+difference).quantize(Decimal("0.01")),
                                                  "amount_usd":(target[1]*usd).quantize(Decimal("0.01"))}
            for code,debit,credit in lines:
                if not debit and not credit: continue
                extra=special.pop((code,"D" if debit else "C"),None)
                if extra:
                    db.execute("INSERT INTO journal_lines(entry_id,account_id,description,debit,credit,line_currency,amount,amount_lbp,amount_usd) VALUES(?,?,?,?,?,?,?,?,?)",
                        (entry_id,self._account_id(db,code),f'Payroll {record["payroll_number"]}',str(debit),str(credit),extra["line_currency"],
                         str(extra["amount"]),str(extra["amount_lbp"]),str(extra["amount_usd"])))
                    continue
                db.execute("INSERT INTO journal_lines(entry_id,account_id,description,debit,credit) VALUES(?,?,?,?,?)",
                    (entry_id,self._account_id(db,code),f'Payroll {record["payroll_number"]}',str(debit),str(credit)))
            db.execute("UPDATE payroll_records SET status='posted',journal_entry_id=?,posted_payable_account=? WHERE id=?",(entry_id,payable_account,record["id"]))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"post","payroll",record["id"],json.dumps({"payroll_number":record["payroll_number"],"journal_entry":number}),utcnow()))
        return next(row for row in self.list_payroll() if row["id"]==int(payroll_id))

    # ---------------------------------------------------------------- NSSF payment
    def record_nssf_payment(self, item, user_id):
        """Payment of the NSSF statement: Dr NSSF payable / Cr cash or bank (payment voucher, type 03)."""
        try: amount = Decimal(str(item.get("amount") or 0).replace(",", ""))
        except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError("Enter the amount paid") from exc
        if amount <= 0: raise ValueError("The amount paid must be above zero")
        currency = str(item.get("currency") or "LBP").upper(); date = str(item.get("payment_date") or datetime.now().strftime("%d-%m-%Y"))
        cash = str(item.get("cash_account") or "531").split(" - ", 1)[0].strip()
        settings = self.payroll_settings_for(iso_date(date))
        try: payable = json.loads(settings.get("employee_account_map") or "{}").get("nssf") if isinstance(settings.get("employee_account_map"),
                str) else (settings.get("employee_account_map") or {}).get("nssf")
        except ValueError: payable = None
        payable = payable or "4431"
        period = str(item.get("period_label") or "").strip(); reference = str(item.get("reference") or "").strip()
        voucher = self.save_journal_voucher({"entry_date": date, "description": f"NSSF payment {period}".strip() + (f" - receipt {reference}" if reference else ""),
                                             "currency": currency, "voucher_type": "03"},
            [{"account_code": payable, "line_currency": currency, "side": "D", "amount": str(amount), "reference": reference},
             {"account_code": cash, "line_currency": currency, "side": "C", "amount": str(amount), "reference": reference}], user_id)
        return {"voucher": voucher["voucher"]["entry_number"], "amount": float(amount), "currency": currency}

    PERIOD_VALUE_FIELDS=("employee_ceiling","medical_ceiling","family_ceiling","end_service_ceiling","employee_nssf_rate","medical_rate","family_rate","end_service_rate",
                         "family_allowance_spouse","family_allowance_child","family_allowance_cap","family_allowance_max_children")

    def save_payroll_periods(self, periods, user_id):
        """Save the whole list of Tax & NSSF periods at once (edit Date From / Date To, ceilings and rates).

        Periods are checked together: sorted by Date From, no two on the same date, no overlap and no gap
        (an empty Date To closes the day before the next period; the last period may stay open). Every
        other setting of a period (tax brackets, allowances, posting accounts) is kept from the period it
        was edited from, or copied from the period that covered its new Date From."""
        if not isinstance(periods,list) or not periods: raise ValueError("At least one period is required")
        with self.connect() as db:
            existing={row["date_from"]:dict(row) for row in db.execute("SELECT * FROM payroll_settings ORDER BY date_from")}
        if not existing: raise ValueError("Load the payroll settings first")
        def covering(day):
            best=None
            for start,row in sorted(existing.items()):
                if start<=day: best=row
            return best or next(iter(sorted(existing.items())))[1]
        cleaned=[]
        for index,period in enumerate(periods,1):
            if not str(period.get("date_from") or "").strip(): raise ValueError(f"Period {index}: Date From is required")
            date_from=iso_date(period.get("date_from"),f"Period {index} Date From")
            text_to=str(period.get("date_to") or "").strip()
            date_to=iso_date(text_to,f"Period {index} Date To") if text_to and text_to.lower()!="open" else None
            base=dict(existing.get(str(period.get("original_from") or ""),None) or covering(date_from))
            for field in self.PERIOD_VALUE_FIELDS:
                if period.get(field) in (None,""): continue
                try: value=Decimal(str(period[field]).replace(",","").replace("%",""))
                except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError(f"Period {index}: {field.replace('_',' ')} must be a number") from exc
                if value<0: raise ValueError(f"Period {index}: {field.replace('_',' ')} cannot be negative")
                if field.endswith("rate") and value>=1: raise ValueError(f"Period {index}: {field.replace('_',' ')} must be a decimal rate (3% = 0.03)")
                base[field]=str(value)
            base["date_from"]=date_from; base["date_to"]=date_to; cleaned.append(base)
        cleaned.sort(key=lambda row:row["date_from"])
        for current,following in zip(cleaned,cleaned[1:]):
            if current["date_from"]==following["date_from"]: raise ValueError(f"Two periods start on {display_date(current['date_from'])}")
            day_before=(datetime.strptime(following["date_from"],"%Y-%m-%d")-timedelta(days=1)).strftime("%Y-%m-%d")
            if not current["date_to"]: current["date_to"]=day_before
            if current["date_to"]<current["date_from"]: raise ValueError(f"The period from {display_date(current['date_from'])} ends before it starts")
            if current["date_to"]>=following["date_from"]:
                raise ValueError(f"The period {display_date(current['date_from'])} - {display_date(current['date_to'])} overlaps the period starting {display_date(following['date_from'])}")
            if current["date_to"]<day_before:
                raise ValueError(f"Nothing covers {display_date((datetime.strptime(current['date_to'],'%Y-%m-%d')+timedelta(days=1)).strftime('%Y-%m-%d'))} to {display_date(day_before)}: "
                                 "change a Date From / Date To or add a period for those days")
        if cleaned[-1]["date_to"] and cleaned[-1]["date_to"]<cleaned[-1]["date_from"]: raise ValueError("The last period ends before it starts")
        with self.connect() as db:
            columns=[row["name"] for row in db.execute("PRAGMA table_info(payroll_settings)") if row["name"]!="id"]
            db.execute("DELETE FROM payroll_settings")
            for row in cleaned:
                row.setdefault("created_by",user_id); row.setdefault("created_at",utcnow())
                db.execute(f"INSERT INTO payroll_settings({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",[row.get(column) for column in columns])
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",(user_id,"save","payroll_periods",
                json.dumps([{"from":r["date_from"],"to":r["date_to"],**{f:r.get(f) for f in self.PERIOD_VALUE_FIELDS}} for r in cleaned]),utcnow()))
        return self.list_payroll_settings()

    def delete_payroll_period(self, date_from, user_id):
        """Remove one Tax & NSSF period; the period before it is extended to cover the gap."""
        date_from=iso_date(date_from,"Date From")
        with self.connect() as db:
            rows=[dict(r) for r in db.execute("SELECT id,date_from,date_to FROM payroll_settings ORDER BY date_from")]
            if len(rows)<=1: raise ValueError("At least one period must remain")
            target=next((r for r in rows if r["date_from"]==date_from),None)
            if not target: raise ValueError("Period not found")
            index=rows.index(target); db.execute("DELETE FROM payroll_settings WHERE id=?",(target["id"],))
            if index>0: db.execute("UPDATE payroll_settings SET date_to=? WHERE id=?",(target["date_to"],rows[index-1]["id"]))
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",(user_id,"delete","payroll_period",json.dumps({"date_from":date_from}),utcnow()))
        return self.list_payroll_settings()
