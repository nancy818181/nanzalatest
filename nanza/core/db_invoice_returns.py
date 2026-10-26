"""Returns of goods / services against a posted sales or purchase invoice (credit / debit note with its stock movements).

Part of the Database class through InvoicesStore (moved unchanged from db_invoices.py in the 2.9.138 consolidation):
the methods run on the same Database object, connection and transaction rules as before."""
from __future__ import annotations

from database_common import Decimal, hashlib, iso_date, json, utcnow


class InvoiceReturnsStore:
    def create_invoice_return(self, invoice_id, returns, return_date, user_id, request_id):
        request_id=str(request_id or "").strip()
        if not request_id or len(request_id)>128:
            raise ValueError("A stable return request ID is required")
        request_hash=hashlib.sha256(json.dumps({"invoice_id":int(invoice_id),"items":returns,"return_date":return_date},
            sort_keys=True,separators=(",",":"),default=str).encode("utf-8")).hexdigest()
        with self.connect() as db:
            if not db.in_transaction: db.execute("BEGIN IMMEDIATE")  # its own transaction (2.9.121: or the one of a larger save)
            previous=db.execute("SELECT * FROM invoices WHERE return_request_id=?",(request_id,)).fetchone()
            if previous:
                if int(previous["linked_invoice_id"] or 0)!=int(invoice_id):
                    raise ValueError("This return request ID was already used for a different invoice")
                if previous["return_request_hash"]!=request_hash:
                    raise ValueError("This return request ID was already used with different return details")
                return self.get_invoice(previous["id"])
            return self._create_invoice_return_locked(invoice_id,returns,return_date,user_id,request_id,request_hash)

    def _create_invoice_return_locked(self, invoice_id, returns, return_date, user_id, request_id, request_hash):
        """Post a linked credit note for reviewed quantities; never create a payment or allocation."""
        from decimal import ROUND_HALF_UP
        source=self.get_invoice(int(invoice_id))
        if source.get("status")!="posted":
            raise ValueError("Returns can only be created from a posted invoice")
        if source.get("doc_subtype")=="credit_note":
            raise ValueError("A credit note cannot itself be returned")
        try:
            source_exchange_rate=Decimal(str(source.get("exchange_rate") or "0"))
            if not source_exchange_rate.is_finite() or source_exchange_rate<=0: raise ValueError
        except (ArithmeticError, ValueError, TypeError, KeyError) as exc:
            raise ValueError("The original invoice has no valid positive exchange rate; return not posted") from exc
        originals=self.invoice_detail(int(invoice_id))["items"]
        if not originals: raise ValueError("This invoice has no item lines to return; no return was created")
        with self.connect() as db:
            stock_source=db.execute("""SELECT w.code FROM stock_documents d JOIN warehouses w ON w.id=d.warehouse_id
                WHERE d.invoice_id=? ORDER BY d.id DESC LIMIT 1""",(int(invoice_id),)).fetchone()
        warehouse_code=stock_source["code"] if stock_source else "MAIN"
        if not isinstance(returns,list) or not returns: raise ValueError("Select at least one return quantity")
        by_id={int(row["id"]):row for row in originals}; requested={}
        for row in returns:
            try:
                item_id=int(row["item_id"]); qty=Decimal(str(row["quantity"]))
            except (ArithmeticError, ValueError, TypeError, KeyError) as exc:
                raise ValueError("Return lines need a valid invoice item and quantity") from exc
            if item_id not in by_id or qty<=0:
                raise ValueError("Return quantities must be positive and belong to the original invoice")
            if item_id in requested: raise ValueError("A return line may only be selected once")
            original=by_id[item_id]
            remaining=Decimal(str(original["quantity"]))-Decimal(str(original["returned_quantity"] or 0))
            if qty>remaining: raise ValueError(f"{original['description']}: only {remaining} remains returnable")
            requested[item_id]=qty
        cent=Decimal("0.01"); micro=Decimal("0.000001"); lines=[]
        for item_id,qty in requested.items():
            original=by_id[item_id]
            remaining_qty=Decimal(str(original["quantity"]))-Decimal(str(original["returned_quantity"] or 0))
            ratio=qty/remaining_qty
            def part(field):
                remainder=Decimal(str(original.get(field) or 0))-Decimal(str(original.get("returned_"+field) or 0))
                return (remainder*ratio).quantize(cent,rounding=ROUND_HALF_UP)
            deductible=part("deductible_subtotal"); non_deductible=part("non_deductible_subtotal"); vat=part("vat")
            price=(deductible+non_deductible)/qty
            lines.append({"description":original["description"],"quantity":str(qty),
                "unit_price":str(price.quantize(micro,rounding=ROUND_HALF_UP)),
                "deductible_subtotal":str(deductible),"non_deductible_subtotal":str(non_deductible),
                "vat_rate":str(original["vat_rate"]),"vat":str(vat),"item_code":original.get("item_code"),
                "unit":original.get("unit"),"discount_percent":"0","warehouse":warehouse_code,"origin_item_id":item_id})
        is_sale=source["kind"]=="sale"; date=iso_date(return_date or source["invoice_date"],"Return date")
        def opposite(side,default):
            return "C" if str(side or default).upper()=="D" else "D"
        invoice={"invoice_number":self.next_invoice_number("credit_note" if is_sale else "supplier_credit_note",date),
            "invoice_date":date,"party_name":source["party_name"],"kind":"sales" if is_sale else "purchases",
            "currency":source["currency"],"exchange_rate":str(source_exchange_rate),"status":"posted","source_file":"Sales Return" if is_sale else "Purchase Return",
            "supplier_account":source["supplier_account"],"vat_account":source["vat_account"],
            "expense_account":source["expense_account"],"expense_no_vat_account":source.get("expense_no_vat_account"),
            "supplier_side":opposite(source.get("supplier_side"),"D" if is_sale else "C"),
            "vat_side":opposite(source.get("vat_side"),"C" if is_sale else "D"),
            "expense_side":opposite(source.get("expense_side"),"C" if is_sale else "D"),
            "expense_no_vat_side":opposite(source.get("expense_no_vat_side"),"D"),
            "vat_treatment":source.get("vat_treatment") or "standard","vat_use":source.get("vat_use") or "mixed",
            "doc_subtype":"credit_note","is_return":True,"amount_paid":"0","payment_method":"On Account (Not Cash)",
            "notes":f"Return against {source['invoice_number']}","skip_vat_reclass":True,
            "branch":source.get("branch_name"),"department_id":source.get("department_id"),"project_id":source.get("project_id"),
            "linked_invoice_id":int(invoice_id)}
        created=self.create_manual_invoice(invoice,lines,user_id)
        with self.connect() as db:
            db.execute("UPDATE invoices SET linked_invoice_id=?,return_request_id=?,return_request_hash=? WHERE id=?",
                       (int(invoice_id),request_id,request_hash,created))
            created_item_ids=[row["id"] for row in db.execute("SELECT id FROM invoice_items WHERE invoice_id=? ORDER BY id",(created,))]
            for item_id,line in zip(created_item_ids,lines):
                db.execute("UPDATE invoice_items SET origin_item_id=? WHERE id=?",(line["origin_item_id"],item_id))
            returned_vat=sum(Decimal(str(line["vat"])) for line in lines)
            if not is_sale and not source.get("vat_recoverable",1):
                # Reverse the original non-deductible VAT reclassification (Dr VAT / Cr cost).
                db.execute("UPDATE invoices SET vat_recoverable=0 WHERE id=?",(created,))
                if returned_vat:
                    row=db.execute("SELECT party_id,branch_id,currency,invoice_date,expense_account,vat_account FROM invoices WHERE id=?",(created,)).fetchone()
                    entry=db.execute("""INSERT INTO journal_entries(entry_number,entry_date,description,source_type,source_id,currency,branch_id,created_by,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?)""",(f"VATND-INV-{created}",row["invoice_date"],f"Reverse non-deductible VAT {source['invoice_number']}",
                        "vat_reclass",created,row["currency"],row["branch_id"],user_id,utcnow())).lastrowid
                    for code,debit,credit in ((row["vat_account"],returned_vat,Decimal("0")),(row["expense_account"],Decimal("0"),returned_vat)):
                        db.execute("INSERT INTO journal_lines(entry_id,account_id,party_id,description,debit,credit) VALUES(?,?,?,?,?,?)",
                            (entry,self._account_id(db,code),row["party_id"],"Reverse non-deductible VAT reclassification",str(debit),str(credit)))
        self._store_invoice_format(created,invoice,lines)
        return self.get_invoice(created)
