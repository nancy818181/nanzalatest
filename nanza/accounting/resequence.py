"""2.9.115: renumber documents by date (like Odoo's "Resequence").

When a receipt, payment, journal voucher, expense or invoice was entered with a wrong date, its number no longer
follows the dates. The administrator chooses a series (for example RV of 2026), sees every change (old number ->
new number) and confirms. The rules that keep the books auditable:

- Only the program's own numbers are renumbered (RV-2026-000012). A number typed by hand or an imported supplier
  number (FAC/123) is never touched.
- Documents that may no longer change keep their number: books locked up to a date, a closed fiscal year, or a
  quarter whose VAT return is saved. Only the documents dated AFTER the last of those are renumbered, and the new
  numbers continue after the highest number kept.
- Posted journal vouchers are immutable and are never renumbered.
- A safety backup is made first, everything is changed in one step (all or nothing) and the audit trail keeps every
  old -> new number.
- Nothing else changes: amounts, dates, accounts, allocations, attachments and links all point at the document
  itself (its id), not at its number.
"""
from __future__ import annotations

import hashlib
import json
import re

from database_common import iso_date, utcnow

# kind -> where the number lives. "journal" says how the journal entry of the document carries the number:
#   "number"  the entry number is the document number (receipts, payments, expenses)
#   "self"    the document IS the journal entry (journal vouchers)
#   "text"    the entry has its own number (INV-<id>) and only mentions the document number in its description
SERIES = {
    "customer_receipt": {"label": "Customer receipts (RV)", "table": "payments", "column": "payment_number", "date": "payment_date",
                         "prefix": "RV", "where": "kind='customer_receipt'", "journal": "number", "source": "payment"},
    "supplier_payment": {"label": "Supplier payments (PV)", "table": "payments", "column": "payment_number", "date": "payment_date",
                         "prefix": "PV", "where": "kind='supplier_payment'", "journal": "number", "source": "payment"},
    "journal_voucher": {"label": "Journal vouchers (JV)", "table": "journal_entries", "column": "entry_number", "date": "entry_date",
                        "prefix": "JV", "where": "source_type='journal_voucher'", "journal": "self", "source": "journal_voucher"},
    "expense": {"label": "Expenses (EXP)", "table": "expenses", "column": "expense_number", "date": "expense_date",
                "prefix": "EXP", "where": "1=1", "journal": "number", "source": "expense"},
    "purchase": {"label": "Purchase invoices (PUR)", "table": "invoices", "column": "invoice_number", "date": "invoice_date",
                 "prefix": "PUR", "where": "kind='purchase'", "journal": "text", "source": "invoice"},
    "sale": {"label": "Sales invoices (SAL)", "table": "invoices", "column": "invoice_number", "date": "invoice_date",
             "prefix": "SAL", "where": "kind='sale'", "journal": "text", "source": "invoice"},
}
SALES_WARNING = ("Sales invoices already given to customers carry the old number: the customer's copy and the "
                 "VAT records must be corrected too. Renumber sales invoices only when they were not sent yet.")


def _iso(value):
    try: return iso_date(value)
    except ValueError: return ""


def _frozen_reason(database, iso, lock):
    """Why a document of this date may not change any more ('' when it may)."""
    if not iso: return "no valid date"
    if lock and iso <= lock: return f"books locked up to {lock}"
    try: database._assert_period_open(iso)
    except ValueError: return "fiscal year closed"
    try: database._assert_vat_open(iso)
    except ValueError: return "VAT return of the quarter saved"
    return ""


def plan(database, kind, year):
    """Every document of the series with its current and new number. Nothing is changed.
    Returns {kind, label, year, rows: [{id, date, old, new, change, kept}], changes, kept, token, warning}."""
    if kind not in SERIES: raise ValueError("Choose what to renumber")
    spec = SERIES[kind]
    try: year = int(str(year).strip())
    except ValueError: raise ValueError("Year must be a number such as 2026") from None
    import numbering  # 2.9.116: the prefix chosen in Settings > Numbering; each branch in the number counts on its own
    lock = str(database.settings().get("books_locked_until", "") or "")
    with database.connect() as db:
        prefix = numbering.settings(db)[kind]["prefix"]
        posting_column = ",posting_status" if kind == "journal_voucher" else ""
        found = db.execute(f"SELECT id, {spec['column']} number, {spec['date']} day{posting_column} "
                           f"FROM {spec['table']} WHERE {spec['where']}").fetchall()
    pattern = re.compile(rf"^{re.escape(prefix)}(?:-([A-Z][A-Z0-9]{{0,3}}))?-{year}-(\d+)$")
    groups = {}
    for row in found:
        match = pattern.match(str(row["number"] or "").strip())
        if not match: continue  # a number typed by hand, imported, or of another prefix: never touched
        iso = _iso(row["day"])
        frozen = _frozen_reason(database, iso, lock)
        if kind == "journal_voucher" and row["posting_status"] == "posted":
            frozen = "posted journal vouchers are immutable"
        groups.setdefault(match.group(1) or "", []).append({"id": int(row["id"]), "date": iso, "old": str(row["number"]).strip(),
                                                            "sequence": int(match.group(2)), "frozen": frozen, "branch": match.group(1) or ""})
    rows = []; kept = []
    for branch, members in sorted(groups.items()):
        members.sort(key=lambda r: (r["date"] or "9999-99-99", r["sequence"], r["id"]))
        # Documents up to the last one that may not change keep their numbers; the others follow on after them.
        last_frozen = max((i for i, r in enumerate(members) if r["frozen"]), default=-1)
        held = members[:last_frozen + 1]; kept += held
        width = max([6] + [len(r["old"].rsplit("-", 1)[-1]) for r in members])
        following = max([r["sequence"] for r in held], default=0)
        head = f"{prefix}-{branch}" if branch else prefix
        for r in held: r.update(new=r["old"], change=False, kept=True)
        for offset, r in enumerate(members[last_frozen + 1:], 1):
            r["new"] = f"{head}-{year}-{following + offset:0{width}d}"
            r["change"] = r["new"] != r["old"]; r["kept"] = False
        rows += members
    changes = [r for r in rows if r["change"]]
    token = hashlib.sha256(json.dumps([(r["id"], r["old"], r["new"]) for r in changes]).encode()).hexdigest()[:16]
    return {"kind": kind, "label": spec["label"], "year": year, "prefix": prefix, "rows": rows, "changes": len(changes), "kept": len(kept),
            "kept_reason": kept[-1]["frozen"] if kept else "", "token": token,
            "warning": SALES_WARNING if kind == "sale" and changes else ""}


def apply(database, kind, year, token, user_id):
    """Renumber as shown in the preview. `token` must be the preview's: if anything changed since, nothing is done."""
    current = plan(database, kind, year)
    if not current["changes"]: return {**current, "renumbered": 0}
    if str(token or "") != current["token"]:
        raise ValueError("The documents changed since the preview. Show the preview again, then confirm.")
    spec = SERIES[kind]; changes = [r for r in current["rows"] if r["change"]]
    database.backup("safety")
    with database.connect() as db:
        # Two steps so that no new number meets an old one that is still in place.
        moved_entries = []
        for r in changes:
            temporary = f"~renumber~{spec['source']}~{r['id']}"
            db.execute(f"UPDATE {spec['table']} SET {spec['column']}=? WHERE id=?", (temporary, r["id"]))
            if spec["journal"] == "number":
                entry = db.execute("SELECT id FROM journal_entries WHERE source_type=? AND source_id=? AND entry_number=?",
                                   (spec["source"], r["id"], r["old"])).fetchone()
                if entry:
                    db.execute("UPDATE journal_entries SET entry_number=? WHERE id=?", (temporary, entry["id"])); moved_entries.append((entry["id"], r["new"]))
        for r in changes:
            db.execute(f"UPDATE {spec['table']} SET {spec['column']}=? WHERE id=?", (r["new"], r["id"]))
        for entry_id, new in moved_entries:
            db.execute("UPDATE journal_entries SET entry_number=? WHERE id=?", (new, entry_id))
        for r in changes:
            if spec["journal"] in ("number", "text"):
                db.execute("UPDATE journal_entries SET description=replace(description,?,?) WHERE source_type IN (?,'invoice_reversal','vat_reclass') "
                           "AND source_id=? AND instr(description,?)>0", (r["old"], r["new"], spec["source"], r["id"], r["old"]))
        db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                   (user_id, "renumber", spec["source"], None,
                    json.dumps({"series": f"{current['prefix']}-{current['year']}", "changes": [[r["old"], r["new"]] for r in changes]}), utcnow()))
    return {**current, "renumbered": len(changes)}
