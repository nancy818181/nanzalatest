"""2.9.100: selective approval, chosen per company (Accounting Setup > Approval).

For each kind of document - sales / purchase invoices, journal vouchers, receipts and payments, expenses - the company decides
whether it needs approval. A document of a selected kind saved by a user without the "Can approve" permission waits as a DRAFT:
its journal lines are set aside (held_journal_lines), so it is in no report, trial balance, statement or VAT return until a user
with "Can approve" approves it - never the user who prepared it (the administrator may, for a one-person office).
Invoices keep their own draft status (review), as since 2.9.93."""
from __future__ import annotations

import json

from database_common import display_date, utcnow

TYPES = {"invoices": "Sales / purchase invoices", "journal_vouchers": "Journal vouchers", "payments": "Receipts and payments", "expenses": "Expenses"}
SOURCE_OF = {"journal_vouchers": "journal_voucher", "payments": "payment", "expenses": "expense"}
SETTING = "approval_types"


def migrate(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(journal_entries)")}
    if "approval_status" not in columns: connection.execute("ALTER TABLE journal_entries ADD COLUMN approval_status TEXT")
    line_columns = [row[1] for row in connection.execute("PRAGMA table_info(journal_lines)")]
    held = {row[1] for row in connection.execute("PRAGMA table_info(held_journal_lines)")}
    if not held:
        connection.execute("CREATE TABLE held_journal_lines AS SELECT * FROM journal_lines WHERE 0")
        connection.execute("ALTER TABLE held_journal_lines ADD COLUMN held_at TEXT")
    else:
        for column in line_columns:  # a column added to journal_lines later is added here too
            if column not in held: connection.execute(f"ALTER TABLE held_journal_lines ADD COLUMN {column}")


def types_on(db):
    """The kinds of documents that need approval in this company (the 2.9.93 setting meant invoices)."""
    settings = db.settings()
    try: chosen = json.loads(settings.get(SETTING) or "null")
    except (TypeError, ValueError): chosen = None
    if chosen is None: chosen = ["invoices"] if str(settings.get("approval_required") or "0") == "1" else []
    return [kind for kind in chosen if kind in TYPES]


def save_types(db, kinds):
    kinds = [kind for kind in (kinds or []) if kind in TYPES]
    with db.connect() as connection:
        for key, value in ((SETTING, json.dumps(kinds)), ("approval_required", "1" if kinds else "0")):
            connection.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    return kinds


def _line_columns(connection):
    return [row[1] for row in connection.execute("PRAGMA table_info(journal_lines)")]


def hold(db, entry_id, user_id=None):
    """Set the journal lines of an entry aside: it waits for approval and is in no report."""
    with db.connect() as connection:
        columns = ",".join(_line_columns(connection))
        if not connection.execute("SELECT 1 FROM journal_lines WHERE entry_id=?", (int(entry_id),)).fetchone(): return False
        connection.execute("DELETE FROM held_journal_lines WHERE entry_id=?", (int(entry_id),))
        connection.execute(f"INSERT INTO held_journal_lines({columns},held_at) SELECT {columns},? FROM journal_lines WHERE entry_id=?", (utcnow(), int(entry_id)))
        connection.execute("DELETE FROM journal_lines WHERE entry_id=?", (int(entry_id),))
        connection.execute("UPDATE journal_entries SET approval_status='review' WHERE id=?", (int(entry_id),))
        connection.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                           (user_id, "hold", "journal_entry", int(entry_id), json.dumps({"waiting": "approval"}), utcnow()))
    return True


def entry_of(db, kind, result):
    """The journal entry made by a saved document (the response of the save)."""
    with db.connect() as connection:
        if kind == "journal_vouchers":
            voucher = (result or {}).get("voucher") or {}
            if voucher.get("id"): return int(voucher["id"])
            row = connection.execute("SELECT id FROM journal_entries WHERE entry_number=?", (voucher.get("entry_number"),)).fetchone()
        else:
            row = connection.execute("SELECT id FROM journal_entries WHERE source_type=? AND source_id=? ORDER BY id DESC LIMIT 1",
                                     (SOURCE_OF[kind], int(result))).fetchone()
    return int(row["id"]) if row else None


def pending(db):
    """Everything waiting for approval: invoices in review and held entries (vouchers, payments, expenses)."""
    with db.connect() as connection:
        users = {row["id"]: row["username"] for row in connection.execute("SELECT id,username FROM users")}
        invoices = [dict(r) for r in connection.execute("""SELECT i.id,i.invoice_number,i.invoice_date,i.kind,i.currency,i.total,i.created_by,p.name party
            FROM invoices i LEFT JOIN parties p ON p.id=i.party_id WHERE i.status='review' ORDER BY i.id""")]
        entries = [dict(r) for r in connection.execute("""SELECT e.id,e.entry_number,e.entry_date,e.description,e.source_type,e.currency,e.created_by,
            (SELECT DSUM(CAST(debit AS REAL)) FROM held_journal_lines h WHERE h.entry_id=e.id) amount
            FROM journal_entries e WHERE e.approval_status='review' ORDER BY e.id""")]
    kind_of = {value: key for key, value in SOURCE_OF.items()}
    rows = [{"kind": "invoices", "id": i["id"], "number": i["invoice_number"], "date": display_date(i["invoice_date"]),
             "description": f"{'Sale' if i['kind'] == 'sale' else 'Purchase'} - {i.get('party') or ''}", "currency": i["currency"],
             "amount": float(i["total"] or 0), "prepared_by": users.get(i["created_by"], "")} for i in invoices]
    rows += [{"kind": kind_of.get(e["source_type"], "journal_vouchers"), "id": e["id"], "number": e["entry_number"], "date": display_date(e["entry_date"]),
              "description": e["description"] or "", "currency": e["currency"], "amount": float(e["amount"] or 0),
              "prepared_by": users.get(e["created_by"], "")} for e in entries]
    return rows


def approve_entries(db, entry_ids, user, require_other=True):
    """Put the held lines back in the journal: the documents are posted. Never by the user who prepared them."""
    approved, skipped = [], []
    with db.connect() as connection:
        columns = ",".join(_line_columns(connection))
        for entry_id in entry_ids or []:
            row = connection.execute("SELECT id,entry_number,created_by,approval_status FROM journal_entries WHERE id=?", (int(entry_id),)).fetchone()
            if not row or row["approval_status"] != "review": skipped.append(f"{entry_id}: not waiting for approval"); continue
            if require_other and row["created_by"] == user["id"]: skipped.append(f"{row['entry_number']}: prepared by you - another user approves it"); continue
            back = ",".join(c for c in columns.split(",") if c != "id")  # new line numbers (the old ones may be used again meanwhile)
            connection.execute(f"INSERT INTO journal_lines({back}) SELECT {back} FROM held_journal_lines WHERE entry_id=? ORDER BY id", (int(entry_id),))
            connection.execute("DELETE FROM held_journal_lines WHERE entry_id=?", (int(entry_id),))
            connection.execute("UPDATE journal_entries SET approval_status=NULL WHERE id=?", (int(entry_id),))
            connection.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                               (user["id"], "approve", "journal_entry", int(entry_id), json.dumps({"entry": row["entry_number"], "prepared_by": row["created_by"]}), utcnow()))
            approved.append(row["entry_number"])
    return {"approved": approved, "skipped": skipped}
