"""Files attached to an invoice and its change history (audit log).

Part of the Database class through InvoicesStore (moved unchanged from db_invoices.py in the 2.9.138 consolidation):
the methods run on the same Database object, connection and transaction rules as before."""
from __future__ import annotations

from database_common import json, utcnow


class InvoiceAttachmentsStore:
    def add_attachment(self, invoice_id, file_name, mime_type, content, user_id):
        if not file_name or not content:
            raise ValueError("Attachment file is required")
        if len(content) > 15 * 1024 * 1024:
            raise ValueError("Attachment cannot exceed 15 MB")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM invoices WHERE id=?", (invoice_id,)).fetchone():
                raise KeyError(invoice_id)
            result = db.execute("""INSERT INTO invoice_attachments(invoice_id,file_name,mime_type,content,uploaded_by,uploaded_at)
                VALUES(?,?,?,?,?,?)""", (invoice_id,file_name,mime_type or "application/octet-stream",content,user_id,utcnow()))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"attach","invoice",invoice_id,json.dumps({"file_name":file_name}),utcnow()))
            return result.lastrowid

    def list_attachments(self, invoice_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT id,file_name,mime_type,length(content) size,uploaded_at
                FROM invoice_attachments WHERE invoice_id=? ORDER BY id DESC""", (invoice_id,))]

    def get_attachment(self, attachment_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM invoice_attachments WHERE id=?", (attachment_id,)).fetchone()
            if not row: raise KeyError(attachment_id)
            return dict(row)

    def invoice_history(self, invoice_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT l.id,l.action,l.details,l.created_at,u.username
                FROM audit_log l LEFT JOIN users u ON u.id=l.user_id
                WHERE l.entity='invoice' AND l.entity_id=? ORDER BY l.id DESC""", (invoice_id,))]
