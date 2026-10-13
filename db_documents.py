"""Legal documents of customers / suppliers and document cases.

Part of the Database class (split out of database.py in 2.9.63, code unchanged): Database inherits from DocumentsStore."""
from __future__ import annotations

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, Decimal, display_date, EXPENSE_ACCOUNT_9, iso_date, json, utcnow, VAT_ACCOUNT_9
)
from database_common import _soft_iso  # noqa: F401


class DocumentsStore:
    @staticmethod
    def _document_date(value, label):
        text=str(value or "").strip()
        if not text: return None
        try: return display_date(iso_date(text))
        except ValueError: raise ValueError(f"{label} must be a date (DD-MM-YYYY)")

    def _document_fields(self,item):
        issue=self._document_date(item.get("issue_date"),"Issue date"); expiry=self._document_date(item.get("expiry_date"),"Expiry date")
        if issue and expiry and iso_date(expiry)<iso_date(issue): raise ValueError("Expiry date cannot be before the issue date")
        active=item.get("active",True); active=1 if str(active).strip().lower() not in ("0","false","no","") else 0
        return str(item.get("document_type") or "Other").strip() or "Other",issue,expiry,str(item.get("notes") or "").strip(),active

    def add_party_document(self,party_id,item,content,user_id):
        """Save a customer / supplier legal document. The file is optional: the type, the "applies" tick and
        the issue / expiry dates can be saved on their own and the scanned copy uploaded later."""
        file_name=str(item.get("file_name") or "").strip() if content else ""
        content=content or b""
        if len(content)>15*1024*1024: raise ValueError("Document cannot exceed 15 MB")
        document_type,issue,expiry,notes,active=self._document_fields(item)
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM parties WHERE id=?",(int(party_id),)).fetchone(): raise KeyError(party_id)
            result=db.execute("""INSERT INTO party_documents(party_id,document_type,issue_date,expiry_date,notes,file_name,mime_type,content,uploaded_by,uploaded_at,active)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(int(party_id),document_type,issue,expiry,notes,file_name,
                str(item.get("mime_type") or "application/octet-stream") if content else "",content,user_id,utcnow(),active))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"attach","party",int(party_id),json.dumps({"document_type":document_type,"file_name":file_name,"issue_date":issue,"expiry_date":expiry,"active":bool(active)}),utcnow()))
            return result.lastrowid

    def update_party_document(self,document_id,item,content,user_id):
        """Change a saved legal document: type, applies tick, issue / expiry dates, notes and (optionally) a new file."""
        document_type,issue,expiry,notes,active=self._document_fields(item)
        if content and len(content)>15*1024*1024: raise ValueError("Document cannot exceed 15 MB")
        with self.connect() as db:
            row=db.execute("SELECT party_id FROM party_documents WHERE id=?",(int(document_id),)).fetchone()
            if not row: raise KeyError(document_id)
            db.execute("UPDATE party_documents SET document_type=?,issue_date=?,expiry_date=?,notes=?,active=? WHERE id=?",
                (document_type,issue,expiry,notes,active,int(document_id)))
            if content:
                db.execute("UPDATE party_documents SET file_name=?,mime_type=?,content=?,uploaded_by=?,uploaded_at=? WHERE id=?",
                    (str(item.get("file_name") or "document").strip(),str(item.get("mime_type") or "application/octet-stream"),content,user_id,utcnow(),int(document_id)))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"update","party_document",int(document_id),json.dumps({"party_id":row["party_id"],"document_type":document_type,"issue_date":issue,
                        "expiry_date":expiry,"active":bool(active),"new_file":bool(content)}),utcnow()))
            return int(document_id)

    def list_party_documents(self,party_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT id,party_id,document_type,issue_date,expiry_date,notes,file_name,mime_type,length(content) size,uploaded_at,active
                FROM party_documents WHERE party_id=? ORDER BY id DESC""",(int(party_id),))]

    def get_party_document(self,document_id):
        with self.connect() as db:
            row=db.execute("SELECT * FROM party_documents WHERE id=?",(int(document_id),)).fetchone()
            if not row: raise KeyError(document_id)
            return dict(row)

    def next_document_case_number(self,case_type,document_date):
        kind=str(case_type or "purchase").lower(); prefix={"purchase":"PUR","expense":"EXP","customs":"CUS"}.get(kind)
        if not prefix: raise ValueError("Case type must be Purchase, Expense, or Customs")
        year=datetime.now().year
        for pattern in ("%d-%m-%Y","%Y-%m-%d","%d%m%Y"):
            try: year=datetime.strptime(str(document_date),pattern).year; break
            except ValueError: pass
        with self.connect() as db:
            rows=db.execute("SELECT case_number FROM document_cases WHERE case_number LIKE ?",(f"{prefix}-{year}-%",)).fetchall()
        sequences=[]
        for row in rows:
            try: sequences.append(int(str(row["case_number"]).rsplit("-",1)[-1]))
            except ValueError: pass
        return f"{prefix}-{year}-{max(sequences,default=0)+1:06d}"

    def save_document_case(self,item,user_id):
        case_type=str(item.get("case_type") or "purchase").lower()
        if case_type not in ("purchase","expense","customs"): raise ValueError("Invalid document case type")
        document_date=str(item.get("document_date") or "").strip(); self._assert_period_open(document_date)
        party_id=int(item.get("party_id") or 0)
        currency=str(item.get("currency") or "USD").upper()
        if currency not in self.currency_codes(): raise ValueError("Invalid currency")
        amounts={key:Decimal(str(item.get(key) or 0)) for key in ("supplier_invoice_amount","freight","insurance","customs_duties","import_vat","broker_fees")}
        if min(amounts.values())<0: raise ValueError("Case amounts cannot be negative")
        if case_type!="customs":
            amounts["freight"]=amounts["insurance"]=amounts["customs_duties"]=amounts["broker_fees"]=Decimal("0")
        total=sum(amounts.values())
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM parties WHERE id=?",(party_id,)).fetchone(): raise ValueError("Choose a customer or supplier")
            case_number=str(item.get("case_number") or "").strip() or self.next_document_case_number(case_type,document_date)
            result=db.execute("""INSERT INTO document_cases(case_number,case_type,document_date,party_id,currency,reference,description,customs_declaration_no,broker_name,
                supplier_invoice_amount,freight,insurance,customs_duties,import_vat,broker_fees,total,status,supplier_account,expense_account,vat_account,branch_id,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(case_number,case_type,document_date,party_id,currency,str(item.get("reference") or ""),str(item.get("description") or ""),
                str(item.get("customs_declaration_no") or ""),str(item.get("broker_name") or ""),*[str(amounts[key]) for key in ("supplier_invoice_amount",
                        "freight","insurance","customs_duties","import_vat","broker_fees")],
                str(total),"draft",str(item.get("supplier_account") or ""),str(item.get("expense_account") or EXPENSE_ACCOUNT_9),
                        str(item.get("vat_account") or VAT_ACCOUNT_9),self._branch_id(db,item),user_id,utcnow()))
            case_id=result.lastrowid
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",(user_id,"create","document_case",
                    case_id,json.dumps({"case_number":case_number,"type":case_type}),utcnow()))
        return self.document_case(case_id)

    def add_case_attachment(self,case_id,role,file_name,mime_type,content,user_id):
        if not file_name or not content: raise ValueError("Choose a document file")
        if len(content)>15*1024*1024: raise ValueError("Document cannot exceed 15 MB")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM document_cases WHERE id=?",(int(case_id),)).fetchone(): raise KeyError(case_id)
            return db.execute("INSERT INTO case_attachments(case_id,document_role,file_name,mime_type,content,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?,?)",
                (int(case_id),str(role or "other"),str(file_name),str(mime_type or "application/octet-stream"),content,user_id,utcnow())).lastrowid

    def list_document_cases(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT c.*,p.name party_name,COALESCE(b.name,'Head Office') branch_name,
                (SELECT COUNT(*) FROM case_attachments a WHERE a.case_id=c.id) attachment_count
                FROM document_cases c LEFT JOIN parties p ON p.id=c.party_id LEFT JOIN branches b ON b.id=c.branch_id ORDER BY c.id DESC""")]

    def document_case(self,case_id):
        row=next((row for row in self.list_document_cases() if row["id"]==int(case_id)),None)
        if not row: raise KeyError(case_id)
        return row

    def list_case_attachments(self,case_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT id,document_role,file_name,mime_type,length(content) size,uploaded_at FROM case_attachments WHERE case_id=? ORDER BY id",(int(case_id),))]

    def get_case_attachment(self,attachment_id):
        with self.connect() as db:
            row=db.execute("SELECT * FROM case_attachments WHERE id=?",(int(attachment_id),)).fetchone()
            if not row: raise KeyError(attachment_id)
            return dict(row)

    def post_document_case(self,case_id,user_id):
        case=self.document_case(case_id)
        if case["status"]=="posted": raise ValueError("Document case is already posted")
        attachments=self.list_case_attachments(case_id)
        required={"purchase":{"supplier_invoice"},"expense":{"expense_document"},"customs":{"supplier_invoice","customs_declaration","broker_invoice"}}[case["case_type"]]
        missing=required-{row["document_role"] for row in attachments}
        if missing: raise ValueError("Attach required document(s): "+", ".join(sorted(missing)))
        base=Decimal(str(case["supplier_invoice_amount"]))+Decimal(str(case["freight"]))+Decimal(str(case["insurance"]))+Decimal(str(case["customs_duties"]))+Decimal(str(case["broker_fees"]))
        vat=Decimal(str(case["import_vat"])); items=[]
        components=(("Supplier invoice",case["supplier_invoice_amount"]),("Freight",case["freight"]),("Insurance",case["insurance"]),("Customs duties",
                case["customs_duties"]),("Customs broker fees",case["broker_fees"]))
        for description,amount in components:
            if Decimal(str(amount)):
                items.append({"description":description,"quantity":1,"unit_price":amount,"deductible_subtotal":amount,"vat_rate":0,"vat":0})
        if not items: raise ValueError("Enter an amount before posting")
        party=next(row for row in self.list_parties() if row["id"]==case["party_id"])
        invoice={"invoice_number":case["reference"] or case["case_number"],"invoice_date":case["document_date"],"party_name":party["name"],
            "kind":"expenses" if case["case_type"]=="expense" else "purchases","currency":case["currency"],"supplier_account":case["supplier_account"],
            "expense_account":case["expense_account"],"vat_account":case["vat_account"],"status":"posted","branch_id":case["branch_id"],
            "source_file":f'{case["case_type"].title()} Case',"description":case["description"]}
        if vat:
            items[0]["vat"]=str(vat); items[0]["vat_rate"]=str((vat/base*Decimal("100")) if base else 0)
        invoice_id=self.create_manual_invoice(invoice,items,user_id)
        with self.connect() as db:
            db.execute("UPDATE document_cases SET status='posted',invoice_id=? WHERE id=?",(invoice_id,int(case_id)))
            for row in db.execute("SELECT * FROM case_attachments WHERE case_id=?",(int(case_id),)):
                db.execute("INSERT INTO invoice_attachments(invoice_id,file_name,mime_type,content,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?)",
                    (invoice_id,row["file_name"],row["mime_type"],row["content"],user_id,utcnow()))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",(user_id,"post","document_case",
                    int(case_id),json.dumps({"invoice_id":invoice_id}),utcnow()))
        return self.document_case(case_id)

    # ---------------------------------------------------------------- legal documents
    def legal_document_alerts(self, days=30, today=None):
        """Expired and soon-to-expire legal documents of customers and suppliers."""
        today=datetime.strptime(iso_date(today),"%Y-%m-%d").date() if today else datetime.now().date()
        with self.connect() as db:
            rows=[dict(row) for row in db.execute("""SELECT d.id,d.party_id,p.name party_name,p.kind party_kind,d.document_type,
                d.issue_date,d.expiry_date,d.file_name,d.notes FROM party_documents d JOIN parties p ON p.id=d.party_id
                WHERE d.expiry_date IS NOT NULL AND d.expiry_date<>'' AND COALESCE(d.active,1)=1""")]  # untick "applies" to stop the alert
        alerts=[]
        for row in rows:
            try: expiry=datetime.strptime(iso_date(row["expiry_date"]),"%Y-%m-%d").date()
            except ValueError: continue
            remaining=(expiry-today).days
            if remaining>int(days): continue
            row["days_remaining"]=remaining; row["expiry_date"]=expiry.strftime("%d-%m-%Y")
            row["status"]="expired" if remaining<0 else "expires today" if remaining==0 else "expiring soon"
            alerts.append(row)
        alerts.sort(key=lambda row:row["days_remaining"])
        return {"items":alerts,"expired":sum(1 for row in alerts if row["days_remaining"]<0),
            "expiring":sum(1 for row in alerts if row["days_remaining"]>=0),"days":int(days)}
