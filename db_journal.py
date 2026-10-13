"""Journal vouchers (manual entries) and their suggested rates.

Part of the Database class (split out of database.py in 2.9.63, code unchanged): Database inherits from JournalStore."""
from __future__ import annotations

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, Decimal, display_date, iso_date, json, utcnow
)
from database_common import _soft_iso  # noqa: F401


class JournalStore:
    def delete_journal_voucher(self,entry_id,user_id):
        with self.connect() as db:
            entry=db.execute("SELECT * FROM journal_entries WHERE id=?",(int(entry_id),)).fetchone()
            if not entry: raise KeyError(entry_id)
            self._assert_period_open(entry["entry_date"])
            invoice=None
            if entry["source_id"]:
                invoice=db.execute("SELECT id,source_file FROM invoices WHERE id=?",(entry["source_id"],)).fetchone()
            if entry["source_type"]!="journal_voucher" and (not invoice or invoice["source_file"]!="Journal Voucher"):
                raise ValueError("Only Journal Voucher entries can be deleted here")
            details={"entry_number":entry["entry_number"],"description":entry["description"]}
            if invoice: db.execute("DELETE FROM invoices WHERE id=?",(invoice["id"],))
            db.execute("DELETE FROM journal_entries WHERE id=?",(int(entry_id),))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"delete","journal_voucher",int(entry_id),json.dumps(details),utcnow()))
        return {"deleted":int(entry_id)}

    def delete_opening_voucher(self,entry_id,user_id):
        with self.connect() as db:
            entry=db.execute("SELECT * FROM journal_entries WHERE id=?",(int(entry_id),)).fetchone()
            if not entry: raise KeyError(entry_id)
            if entry["source_type"]!="opening": raise ValueError("Only opening vouchers can be deleted here")
            details={"entry_number":entry["entry_number"],"description":entry["description"]}
            db.execute("DELETE FROM journal_entries WHERE id=?",(int(entry_id),))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"delete","opening_voucher",int(entry_id),json.dumps(details),utcnow()))
        return {"deleted":int(entry_id)}

    def save_journal_voucher(self,item,lines,user_id,entry_id=None):
        date=str(item.get("entry_date") or "").strip(); self._assert_period_open(date)
        description=str(item.get("description") or "").strip() or f"Journal Voucher {str(item.get('entry_number') or '').strip() or 'Entry'}"
        currency=str(item.get("currency") or "USD").upper()
        if not date or not description or currency not in self.currency_codes(): raise ValueError("Enter voucher date, description, and currency")
        if not isinstance(lines,list) or len(lines)<2: raise ValueError("Journal Voucher requires at least two lines")
        normalized=[]; total_debit=Decimal("0"); total_credit=Decimal("0")
        voucher_type=str(item.get("voucher_type") or "01").strip()[:2] or "01"
        for index,line in enumerate(lines,1):
            code=str(line.get("account_code") or "").split(" - ",1)[0].strip()
            doe_basis=str(item.get("doe_basis") or "").upper() if voucher_type=="07" else ""
            extra=self._doe_line_amounts(line,code,doe_basis,currency,index) if doe_basis else self._voucher_line_amounts(line,currency,date,index)
            if extra: debit,credit=extra["debit"],extra["credit"]
            else:
                try: debit=Decimal(str(line.get("debit") or 0)); credit=Decimal(str(line.get("credit") or 0))
                except Exception as exc: raise ValueError(f"Line {index}: Debit and Credit must be numbers") from exc
            if not code or min(debit,credit)<0 or (debit>0 and credit>0) or (debit==0 and credit==0): raise ValueError(f"Line {index}: choose an account and enter either Debit or Credit")
            normalized.append((code,str(line.get("description") or "").strip(),debit,credit,extra,line)); total_debit+=debit; total_credit+=credit
        if abs(total_debit-total_credit)>=Decimal("0.005"): raise ValueError(f"Journal Voucher is unbalanced. Debit {total_debit}; Credit {total_credit}; Remaining {abs(total_debit-total_credit)}")
        if voucher_type=="07":
            from chart_extra import EXCHANGE_GAIN_ACCOUNT, EXCHANGE_LOSS_ACCOUNT
            # A DOE voucher revalues one or more class 4/5 accounts (Automatic DOE posts one voucher per
            # currency with all its accounts) against exchange gain 7751 (credit) / loss 6751 (debit).
            affected=[(code,debit,credit) for code,_desc,debit,credit,_extra,_raw in normalized if code.startswith(("4","5"))]
            chosen=self.default_accounts()  # 2.9.81: the gain / loss accounts of Accounting Settings are accepted too
            gains={EXCHANGE_GAIN_ACCOUNT,chosen["exchange_gain"]}; losses={EXCHANGE_LOSS_ACCOUNT,chosen["exchange_loss"]}
            offsets=[(code,debit,credit) for code,_desc,debit,credit,_extra,_raw in normalized if code in gains|losses]
            if not affected or not offsets or len(affected)+len(offsets)!=len(normalized):
                raise ValueError("DOE needs class 4 or 5 accounts and the exchange gain (7751) or loss (6751) account only")
            for code,debit,credit in offsets:
                if (code in gains and not credit) or (code in losses and not debit):
                    raise ValueError("DOE gains credit 7751 and losses debit 6751")
        with self.connect() as db:
            branch_id=self._branch_id(db,item)
            if entry_id:
                existing=db.execute("SELECT * FROM journal_entries WHERE id=? AND source_type='journal_voucher'",(int(entry_id),)).fetchone()
                if not existing: raise KeyError(entry_id)
                self._assert_period_open(existing["entry_date"]); voucher_number=str(item.get("entry_number") or existing["entry_number"]).strip()
                duplicate=db.execute("SELECT 1 FROM journal_entries WHERE entry_number=? AND id<>?",(voucher_number,int(entry_id))).fetchone()
                if duplicate: raise ValueError("Voucher number already exists")
                db.execute("UPDATE journal_entries SET entry_number=?,entry_date=?,description=?,currency=?,branch_id=?,voucher_type=? WHERE id=?",
                        (voucher_number,date,description,currency,branch_id,voucher_type,int(entry_id)))
                db.execute("DELETE FROM journal_lines WHERE entry_id=?",(int(entry_id),)); saved_id=int(entry_id); action="update"
            else:
                voucher_number=str(item.get("entry_number") or "").strip()
                if not voucher_number:
                    year=self._date_year(date); prefix=f"JV-{year}-"; row=db.execute("SELECT entry_number FROM journal_entries WHERE entry_number LIKE ? ORDER BY entry_number DESC LIMIT 1",
                            (prefix+"%",)).fetchone()
                    sequence=int(row["entry_number"].rsplit("-",1)[-1])+1 if row else 1; voucher_number=f"{prefix}{sequence:06d}"
                if db.execute("SELECT 1 FROM journal_entries WHERE entry_number=?",(voucher_number,)).fetchone(): raise ValueError("Voucher number already exists")
                saved_id=db.execute("INSERT INTO journal_entries(entry_number,entry_date,description,source_type,currency,branch_id,created_by,created_at,voucher_type) VALUES(?,?,?,?,?,?,?,?,?)",
                        (voucher_number,date,description,"journal_voucher",currency,branch_id,user_id,utcnow(),voucher_type)).lastrowid; action="create"
            for code,line_description,debit,credit,extra,raw_line in normalized:
                department_id,project_id=self._dimension_ids(db,{"department":raw_line.get("department") or item.get("department"),"project":raw_line.get("project") or item.get("project"),
                    "department_id":raw_line.get("department_id") or item.get("department_id"),"project_id":raw_line.get("project_id") or item.get("project_id")})
                account=db.execute("SELECT id FROM accounts WHERE code=?",(code,)).fetchone()
                if not account: raise ValueError(f"Account {code} was not found")
                party=db.execute("SELECT id FROM parties WHERE account_number=?",(code,)).fetchone()
                db.execute("""INSERT INTO journal_lines(entry_id,account_id,party_id,description,debit,credit,line_currency,amount,amount_lbp,amount_usd,rate_lbp,rate_usd,due_date,reference,revalue_currency,revalue_amount)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(saved_id,account["id"],party["id"] if party else None,line_description,str(debit),str(credit),
                    *( (extra["line_currency"],str(extra["amount"]),str(extra["amount_lbp"]),str(extra["amount_usd"]),str(extra["rate_lbp"]),
                            str(extra["rate_usd"]),extra["due_date"],extra["reference"],
                        extra.get("revalue_currency"),extra.get("revalue_amount")) if extra else (None,)*10 )))
                if department_id or project_id:
                    db.execute("UPDATE journal_lines SET department_id=?,project_id=? WHERE id=last_insert_rowid()",(department_id,project_id))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",(user_id,action,"journal_voucher",
                    saved_id,json.dumps({"entry_number":voucher_number,"debit":str(total_debit),"credit":str(total_credit)}),utcnow()))
        return self.journal_voucher_detail(saved_id)

    def suggested_rates(self,currency,date=None):
        """BRAINS convention: LBP rate = LBP for 1 unit; USD rate = USD for 1 unit (for LBP lines: LBP per 1 USD)."""
        currency=str(currency or "USD").upper(); day=date or datetime.now().strftime("%d-%m-%Y")
        usd_lbp=self._converted_amount(Decimal("1"),"USD","LBP",day)
        if currency=="LBP": return {"currency":"LBP","rate_lbp":Decimal("1"),"rate_usd":usd_lbp}
        if currency=="USD": return {"currency":"USD","rate_lbp":usd_lbp,"rate_usd":Decimal("1")}
        return {"currency":currency,"rate_lbp":self._converted_amount(Decimal("1"),currency,"LBP",day),"rate_usd":self._converted_amount(Decimal("1"),currency,"USD",day)}

    def doe_candidates_usd(self, posting_date):
        """Class 4/5 balances kept in LBP or another non-USD currency, with their USD equivalent (carrying USD)
        as of a date, for a DOE in the USD books. USD accounts need no USD DOE and are not listed."""
        day=iso_date(posting_date)
        normal="CASE WHEN e.entry_date GLOB '??-??-????' THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2) ELSE e.entry_date END"
        with self.connect() as db:
            lines=[dict(row) for row in db.execute(f"""SELECT a.code,a.name_en,e.currency voucher_currency,e.voucher_type,e.source_type,
                e.entry_date,COALESCE(j.line_currency,e.currency) line_currency,j.amount,j.amount_usd,j.debit,j.credit
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id JOIN accounts a ON a.id=j.account_id
                LEFT JOIN invoices i ON e.source_type='invoice' AND i.id=e.source_id
                WHERE (a.code LIKE '4%' OR a.code LIKE '5%') AND {normal}<=?
                AND (e.source_type!='invoice' OR i.status IN ('posted','cancelled')) ORDER BY a.code,e.id,j.id""",(day,))]
        accounts={}
        for line in lines:
            code=line["code"]; item=accounts.setdefault(code,{"name":line["name_en"],"currencies":set(),"balance":Decimal("0"),"carrying_usd":Decimal("0")})
            signed=Decimal("1") if Decimal(str(line["debit"] or 0))>0 else Decimal("-1")
            doe=line["source_type"]=="journal_voucher" and line["voucher_type"]=="07"
            native=Decimal(str(line["amount"] or 0)) if line["amount"] not in (None,"") else abs(Decimal(str(line["debit"] or 0))-Decimal(str(line["credit"] or 0)))
            if line["amount_usd"] not in (None,""): usd=Decimal(str(line["amount_usd"]))
            elif line["voucher_currency"]=="USD": usd=abs(Decimal(str(line["debit"] or 0))-Decimal(str(line["credit"] or 0)))
            else: usd=self._converted_amount(native,line["line_currency"],"USD",line["entry_date"]) if native else Decimal("0")
            item["carrying_usd"]+=signed*usd
            if doe: continue  # DOE lines only move equivalents, never the account's own balance
            if native<=0: continue
            item["currencies"].add(line["line_currency"]); item["balance"]+=signed*native
        results=[]; skipped=[]; rates={}
        for code,item in sorted(accounts.items()):
            if len(item["currencies"])!=1:
                if len(item["currencies"])>1: skipped.append(code)
                continue
            currency=next(iter(item["currencies"]))
            if currency=="USD" or not item["balance"]: continue
            if currency not in rates: rates[currency]=Decimal(str(self.suggested_rates(currency,posting_date)["rate_usd"]))
            results.append({"account":code,"name":item["name"],"currency":currency,"balance":str(item["balance"]),"carrying_usd":str(item["carrying_usd"]),
                            "suggested_rate":str(rates[currency])})
        return {"items":results,"skipped_accounts":skipped,"basis":"USD"}

    def doe_candidates_other(self, posting_date, basis):
        """2.9.78: DOE in EUR (or another currency than LBP / USD): class 4/5 balances kept in other currencies, their
        carrying value in `basis` (each movement at its own date's rate, as the reports show it, plus earlier DOEs in
        `basis`) and the rate of the DOE date."""
        day=iso_date(posting_date); basis=str(basis).upper()
        normal="CASE WHEN e.entry_date GLOB '??-??-????' THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2) ELSE e.entry_date END"
        with self.connect() as db:
            lines=[dict(row) for row in db.execute(f"""SELECT a.code,a.name_en,e.currency voucher_currency,e.voucher_type,e.source_type,
                {normal} day,COALESCE(j.line_currency,e.currency) line_currency,j.line_currency raw_line_currency,j.amount,j.debit,j.credit,j.revalue_currency,j.revalue_amount
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id JOIN accounts a ON a.id=j.account_id
                LEFT JOIN invoices i ON e.source_type='invoice' AND i.id=e.source_id
                WHERE (a.code LIKE '4%' OR a.code LIKE '5%') AND {normal}<=?
                AND (e.source_type!='invoice' OR i.status IN ('posted','cancelled')) ORDER BY a.code,e.id,j.id""",(day,))]
        accounts={}; rates={}
        def rate(code,date):
            key=(code,date)
            if key not in rates: rates[key]=self._converted_amount(Decimal("1"),code,basis,date)
            return rates[key]
        for line in lines:
            item=accounts.setdefault(line["code"],{"name":line["name_en"],"currencies":set(),"balance":Decimal("0"),"carrying":Decimal("0")})
            signed=Decimal(str(line["debit"] or 0))-Decimal(str(line["credit"] or 0)); sign=Decimal("1") if signed>=0 else Decimal("-1")
            if line["revalue_currency"]==basis and line["revalue_amount"] not in (None,""):
                item["carrying"]+=sign*Decimal(str(line["revalue_amount"])); continue
            if line["source_type"]=="journal_voucher" and line["voucher_type"]=="07": continue  # DOE of other books: no balance change
            native=(sign*Decimal(str(line["amount"]))) if line["raw_line_currency"] and line["amount"] not in (None,"") else signed
            if not native: continue
            currency=line["line_currency"]; item["currencies"].add(currency); item["balance"]+=native
            item["carrying"]+=native*(Decimal("1") if currency==basis else rate(currency,line["day"]))
        results=[]; skipped=[]
        for code,item in sorted(accounts.items()):
            if len(item["currencies"])!=1:
                if len(item["currencies"])>1: skipped.append(code)
                continue
            currency=next(iter(item["currencies"]))
            if currency==basis or not item["balance"]: continue
            results.append({"account":code,"name":item["name"],"currency":currency,"balance":str(item["balance"]),
                            f"carrying_{basis.lower()}":str(item["carrying"].quantize(Decimal("0.01"))),"carrying":str(item["carrying"].quantize(Decimal("0.01"))),
                            "suggested_rate":str(rate(currency,day))})
        return {"items":results,"skipped_accounts":skipped,"basis":basis}

    def doe_candidates(self, posting_date, basis="LBP"):
        if str(basis or "LBP").upper()=="USD": return self.doe_candidates_usd(posting_date)
        if str(basis or "LBP").upper()!="LBP": return self.doe_candidates_other(posting_date, basis)
        """Foreign class 4/5 balances and their original LBP carrying amounts as of a date.

        Local-currency activity is ignored except prior DOE corrections. Accounts with
        multiple foreign currencies are excluded because their DOE corrections cannot
        be assigned to one currency without an explicit allocation.
        """
        day=iso_date(posting_date)
        normal="CASE WHEN e.entry_date GLOB '??-??-????' THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2) ELSE e.entry_date END"
        with self.connect() as db:
            lines=[dict(row) for row in db.execute(f"""SELECT a.code,a.name_en,e.currency voucher_currency,e.voucher_type,e.source_type,
                e.entry_date,COALESCE(j.line_currency,e.currency) line_currency,j.amount,j.amount_lbp,j.debit,j.credit
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id JOIN accounts a ON a.id=j.account_id
                LEFT JOIN invoices i ON e.source_type='invoice' AND i.id=e.source_id
                WHERE (a.code LIKE '4%' OR a.code LIKE '5%') AND {normal}<=?
                AND (e.source_type!='invoice' OR i.status IN ('posted','cancelled')) ORDER BY a.code,e.id,j.id""",(day,))]
        groups={}; doe_corrections={}; currencies_by_account={}
        for line in lines:
            code=line["code"]; currency=line["line_currency"]
            signed=Decimal("1") if Decimal(str(line["debit"] or 0))>0 else Decimal("-1")
            if currency=="LBP":
                if line["source_type"]=="journal_voucher" and line["voucher_type"]=="07" and line["voucher_currency"]=="LBP":
                    doe_corrections[code]=doe_corrections.get(code,Decimal("0"))+Decimal(str(line["debit"] or 0))-Decimal(str(line["credit"] or 0))
                continue
            native=Decimal(str(line["amount"] or 0)) if line["amount"] not in (None,"") else abs(Decimal(str(line["debit"] or 0))-Decimal(str(line["credit"] or 0)))
            if native<=0: continue
            key=(code,currency); currencies_by_account.setdefault(code,set()).add(currency)
            item=groups.setdefault(key,{"account":code,"name":line["name_en"],"currency":currency,"balance":Decimal("0"),"carrying_lbp":Decimal("0")})
            item["balance"]+=signed*native
            if line["amount_lbp"] not in (None,""):
                item["carrying_lbp"]+=signed*Decimal(str(line["amount_lbp"]))
            else:
                item["carrying_lbp"]+=signed*self._converted_amount(native,currency,"LBP",line["entry_date"])
        results=[]; skipped=[]; rates={}
        for (account,currency),item in sorted(groups.items()):
            if len(currencies_by_account[account])>1:
                if account not in skipped: skipped.append(account)
                continue
            if not item["balance"]: continue
            item["carrying_lbp"]+=doe_corrections.get(account,Decimal("0"))
            if currency not in rates: rates[currency]=Decimal(str(self.suggested_rates(currency,posting_date)["rate_lbp"]))
            results.append({**item,"balance":str(item["balance"]),"carrying_lbp":str(item["carrying_lbp"]),"suggested_rate":str(rates[currency])})
        return {"items":results,"skipped_accounts":skipped}

    def _doe_line_amounts(self,line,code,basis,voucher_currency,index):
        """DOE line that changes ONLY the equivalent of the revaluation currency (LBP or USD books).

        - LBP DOE: the class 4/5 line is an LBP correction (as before) and the USD equivalent is left alone.
        - USD DOE: the class 4/5 line keeps its own currency with amount 0 (the foreign / LBP balance does
          not change) and only its USD equivalent moves.
        - The gain 7751 / loss 6751 line is in the revaluation currency only."""
        from chart_extra import EXCHANGE_GAIN_ACCOUNT, EXCHANGE_LOSS_ACCOUNT
        if basis not in self.currency_codes(): raise ValueError(f"DOE cannot be revalued in {basis}: add the currency first")
        if voucher_currency!=basis: raise ValueError(f"A {basis} DOE voucher must be in {basis}")
        try: debit=Decimal(str(line.get("debit") or 0)); credit=Decimal(str(line.get("credit") or 0))
        except Exception as exc: raise ValueError(f"Line {index}: Debit and Credit must be numbers") from exc
        value=(debit or credit).quantize(Decimal("0.01"))
        chosen=self.default_accounts()
        zero=Decimal("0"); offset=code in (EXCHANGE_GAIN_ACCOUNT,EXCHANGE_LOSS_ACCOUNT,chosen["exchange_gain"],chosen["exchange_loss"])
        native=str(line.get("native_currency") or basis).upper()
        other=basis not in ("LBP","USD")  # 2.9.78: EUR (or any) books - only that currency's value moves
        if offset or basis=="LBP": line_currency=basis if offset else "LBP"; amount=value
        else: line_currency=native; amount=zero
        return {"debit":value if debit else zero,"credit":value if credit else zero,"line_currency":line_currency,"amount":amount,
                "amount_lbp":value if basis=="LBP" else zero,"amount_usd":value if basis=="USD" else zero,"rate_lbp":zero,"rate_usd":zero,
                "due_date":None,"reference":str(line.get("reference") or "").strip() or None,
                "revalue_currency":basis if other and not offset else None,"revalue_amount":str(value) if other and not offset else None}

    def _voucher_line_amounts(self,line,voucher_currency,date,index):
        """Lines entered like BRAINS: currency, D/C, amount in the account currency and LBP / USD rates."""
        if line.get("amount") in (None,"") or not line.get("side"): return None
        side=str(line.get("side")).strip().upper()[:1]
        if side not in ("D","C"): raise ValueError(f"Line {index}: D/C must be D or C")
        currency=str(line.get("line_currency") or voucher_currency).upper()
        if currency not in self.currency_codes(): raise ValueError(f"Line {index}: invalid currency")
        try:
            amount=Decimal(str(line.get("amount")).replace(",","")); suggested=self.suggested_rates(currency,date)
            rate_lbp=Decimal(str(line.get("rate_lbp") or suggested["rate_lbp"]).replace(",","")); rate_usd=Decimal(str(line.get("rate_usd") or suggested["rate_usd"]).replace(",",""))
        except Exception as exc: raise ValueError(f"Line {index}: amount and rates must be numbers") from exc
        if amount<=0 or rate_lbp<=0 or rate_usd<=0: raise ValueError(f"Line {index}: amount and rates must be above zero")
        amount_lbp=(amount*rate_lbp).quantize(Decimal("0.01")); amount_usd=((amount/rate_usd) if currency=="LBP" else amount*rate_usd).quantize(Decimal("0.001"))
        if currency==voucher_currency: value=amount
        elif voucher_currency=="USD": value=amount_usd
        elif voucher_currency=="LBP": value=amount_lbp
        else: raise ValueError(f"Line {index}: a {voucher_currency} voucher can only contain {voucher_currency} lines. Use a USD or LBP voucher to mix currencies")
        value=value.quantize(Decimal("0.01"))
        due=str(line.get("due_date") or "").strip()
        return {"debit":value if side=="D" else Decimal("0"),"credit":value if side=="C" else Decimal("0"),"line_currency":currency,"amount":amount,
                "amount_lbp":amount_lbp,"amount_usd":amount_usd,"rate_lbp":rate_lbp,"rate_usd":rate_usd,"due_date":display_date(due) if due else None,
                "reference":str(line.get("reference") or "").strip() or None}

    def journal_voucher_detail(self,entry_id):
        with self.connect() as db:
            entry=db.execute("SELECT * FROM journal_entries WHERE id=? AND source_type='journal_voucher'",(int(entry_id),)).fetchone()
            if not entry: raise KeyError(entry_id)
            lines=[dict(row) for row in db.execute("""SELECT a.code account_code,a.name_en account_name,COALESCE(j.description,'') description,
                CAST(j.debit AS REAL) debit,CAST(j.credit AS REAL) credit,j.line_currency,CAST(j.amount AS REAL) amount,CAST(j.amount_lbp AS REAL) amount_lbp,
                CAST(j.amount_usd AS REAL) amount_usd,CAST(j.rate_lbp AS REAL) rate_lbp,CAST(j.rate_usd AS REAL) rate_usd,j.due_date,j.reference,
                d.code department,pr.code project
                FROM journal_lines j JOIN accounts a ON a.id=j.account_id LEFT JOIN departments d ON d.id=j.department_id LEFT JOIN projects pr ON pr.id=j.project_id
                WHERE j.entry_id=? ORDER BY j.id""",(int(entry_id),))]
        return {"voucher":dict(entry),"lines":lines}
