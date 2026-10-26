"""Invoice identity: the same number twice (save-time check, import duplicate check, duplicate report).

Part of the Database class through InvoicesStore (moved unchanged from db_invoices.py in the 2.9.138 consolidation):
the methods run on the same Database object, connection and transaction rules as before."""
from __future__ import annotations

from database_common import iso_date


class InvoiceNumbersStore:

    # 2.9.51: the same invoice must not be recorded twice by an upload (same customer / supplier and same number)
    # 2.9.134 (D3): invoice identity. A sales invoice number is unique per document type across all customers (Lebanese sales
    # invoices are sequential); a purchase / expense document is unique per supplier + supplier's number. Cancelled and deleted
    # documents are ignored. Number comparison is the one the import screen already uses (INV-0045 = INV45).
    _NUMBER_SQL = "UPPER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(i.invoice_number,'-',''),' ',''),'/',''),'.',''),'_',''))"

    def find_same_invoice_number(self, db, number, kind, party_id, doc_subtype="invoice", exclude_id=None):
        """The first saved invoice with the same identity, or None. `db` is an open connection."""
        import re as _re
        key = self.invoice_number_key(number)
        if not key: return None
        digits = max(_re.findall(r"[0-9]+", key), key=len, default="")
        needle = digits or key  # SQL pre-filter only; the exact comparison is the key below
        sql = (f"SELECT i.id,i.invoice_number,i.invoice_date,i.party_id,COALESCE(i.doc_subtype,'invoice') st FROM invoices i "
               f"WHERE i.kind=? AND i.status NOT IN ('cancelled','deleted','void') AND {self._NUMBER_SQL} LIKE ?")
        args = [kind, f"%{needle}%"]
        if exclude_id is not None: sql += " AND i.id<>?"; args.append(int(exclude_id))
        subtype = str(doc_subtype or "invoice").lower()
        for row in db.execute(sql, args):
            if str(row["st"] or "invoice").lower() != subtype: continue
            if self.invoice_number_key(row["invoice_number"]) != key: continue
            if kind == "purchase" and row["party_id"] != party_id: continue
            return dict(row)
        return None

    def _assert_unique_invoice_number(self, db, item, kind, party_id, exclude_id=None):
        if item.get("allow_duplicate"): return  # only an administrator's request keeps this flag (server._approval_gate)
        if exclude_id is None and item.get("replaces_invoice_id") not in (None, ""): exclude_id = int(item["replaces_invoice_id"])  # an edit saved as a new document
        found = self.find_same_invoice_number(db, item.get("invoice_number"), kind, party_id, item.get("doc_subtype"), exclude_id)
        if found:
            raise ValueError(f"Duplicate invoice number {str(item.get('invoice_number')).strip()}: already saved as invoice ID {found['id']} "
                             f"({found['invoice_number']}, {found['invoice_date']}). Use another number; only an administrator can save a duplicate on purpose")

    def duplicate_invoice_report(self):
        """Report (never a block): groups of saved, not cancelled invoices that share an identity. For the first review of an existing file."""
        with self.connect() as db:
            rows = [dict(r) for r in db.execute("""SELECT i.id,i.invoice_number,i.invoice_date,i.kind,i.party_id,i.total,i.currency,
                COALESCE(i.doc_subtype,'invoice') st FROM invoices i WHERE i.status NOT IN ('cancelled','deleted','void') ORDER BY i.id""")]
        groups = {}
        for r in rows:
            key = self.invoice_number_key(r["invoice_number"])
            if not key: continue
            identity = (r["kind"], str(r["st"]).lower(), key) + ((r["party_id"],) if r["kind"] == "purchase" else ())
            groups.setdefault(identity, []).append(r)
        return [g for g in groups.values() if len(g) > 1]

    @staticmethod
    def invoice_number_key(number):
        import re as _re
        text = _re.sub(r"[^0-9A-Z]", "", str(number or "").upper())
        return _re.sub(r"(?<![0-9])0+(?=[0-9])", "", text)  # INV-0045 = INV45 = inv 45

    def find_invoice_duplicates(self, items):
        """For each {kind, party_name, invoice_number, total, doc_subtype}: the invoices already saved with the same
        type, the same customer / supplier and the same number (cancelled and deleted ones are ignored)."""
        with self.connect() as db:
            saved = [dict(r) for r in db.execute("""SELECT i.id,i.invoice_number,i.invoice_date,i.kind,i.currency,CAST(i.total AS REAL) total,
                COALESCE(i.doc_subtype,'invoice') doc_subtype,p.name party_name FROM invoices i LEFT JOIN parties p ON p.id=i.party_id
                WHERE i.status NOT IN ('cancelled','deleted','void')""")]
        index = {}; by_amount = {}
        for row in saved:
            party = str(row["party_name"] or "").strip().casefold()
            key = (row["kind"], party, self.invoice_number_key(row["invoice_number"]), row["doc_subtype"] or "invoice")
            index.setdefault(key, []).append(row)
            try: day = iso_date(row["invoice_date"])
            except Exception: day = str(row["invoice_date"] or "")
            by_amount.setdefault((row["kind"], party, day, round(float(row["total"] or 0), 2)), []).append(row)
        result = []
        for position, item in enumerate(items or []):
            kind = "sale" if self._entry_type(item) == "sales" else "purchase"
            party = str(item.get("party_name") or "").strip().casefold()
            if item.get("by_amount"):
                # 2.9.55: an Excel file without an invoice number column - the same customer / supplier, date and total
                try: day = iso_date(item.get("invoice_date"))
                except Exception: day = str(item.get("invoice_date") or "")
                try: total = round(float(item.get("total") or 0), 2)
                except (TypeError, ValueError): total = None
                found = by_amount.get((kind, party, day, total), []) if total else []
            else:
                number = self.invoice_number_key(item.get("invoice_number"))
                if not number: result.append([]); continue
                found = index.get((kind, party, number, str(item.get("doc_subtype") or "invoice")), [])
            result.append([{"id": r["id"], "invoice_number": r["invoice_number"], "invoice_date": r["invoice_date"], "total": r["total"],
                            "currency": r["currency"], "party_name": r["party_name"]} for r in found])
        return result
