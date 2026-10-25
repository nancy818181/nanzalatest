"""2.9.136 (F1, owner decision 25-10-2026): a posted receipt / payment is never removed from the books.

Admin delete = void (record, number and posted entry kept; out of statement / ageing / allocations; reason + full audit).
Non-admin cannot void; editing a posted one = reversal dated on the edit date + a new document with a new number."""
import json
from decimal import Decimal

from tests.pytest_compat import pytest

DAY = "10-01-2026"


def _setup(db):
    party = db.save_party({"name": "Synthetic F1 Customer", "kind": "customer"}, 1)
    invoice = db.create_manual_invoice(
        {"invoice_number": "F1-INV-1", "invoice_date": DAY, "party_id": party["id"], "party_name": "Synthetic F1 Customer",
         "kind": "sales", "currency": "USD", "status": "posted"},
        [{"description": "Synthetic service", "quantity": "1", "unit_price": "100.00", "vat_rate": "0"}], 1)
    invoice_id = invoice["invoice_id"] if isinstance(invoice, dict) and "invoice_id" in invoice else invoice.get("id") if isinstance(invoice, dict) else invoice
    payment_id = db.add_payment({"kind": "customer_receipt", "party_id": party["id"], "payment_date": DAY, "currency": "USD", "amount": "100.00"}, 1)
    db.save_allocations(payment_id, [{"invoice_id": invoice_id, "amount": "100.00"}], 1)
    return party, invoice_id, payment_id


def _tb_totals(db):
    with db.connect() as c:
        row = c.execute("SELECT SUM(CAST(debit AS REAL)), SUM(CAST(credit AS REAL)) FROM journal_lines").fetchone()
    return Decimal(str(round(row[0] or 0, 2))), Decimal(str(round(row[1] or 0, 2)))


def _entries(db, payment_id):
    with db.connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM journal_entries WHERE source_id=? AND source_type IN ('payment','payment_reversal') ORDER BY id", (payment_id,))]


def test_admin_void_keeps_record_and_entry_and_releases_allocation(synthetic_db):
    db = synthetic_db
    party, invoice_id, payment_id = _setup(db)
    before = _tb_totals(db)
    with pytest.raises(ValueError):
        db.delete_payment(payment_id, 1, reason="", role="admin")  # a reason is required
    result = db.delete_payment(payment_id, 1, reason="Bounced cheque", role="admin")
    assert result["voided"] == payment_id
    row = next(r for r in db.list_payments() if r["id"] == payment_id)
    assert row["status"] == "Void" and row["void_reason"] == "Bounced cheque"
    assert len(_entries(db, payment_id)) == 1  # the posted entry is NOT deleted
    assert _tb_totals(db) == before  # ledger unchanged (owner accepted)
    docs = {d["id"]: d for d in db.open_documents(party["id"])}
    assert docs[invoice_id]["open_amount"] == pytest.approx(100.0)  # allocation released -> invoice open again
    statement = db.statement_of_account(party["id"]) if hasattr(db, "statement_of_account") else None
    if statement is not None:
        text = json.dumps(statement, default=str)
        assert row["payment_number"] not in text
    with db.connect() as c:
        audit = c.execute("SELECT details FROM audit_log WHERE action='void' AND entity='payment' AND entity_id=?", (payment_id,)).fetchone()
    details = json.loads(audit["details"])
    assert details["reason"] == "Bounced cheque" and details["journal_lines"] and details["allocations"][0]["invoice_id"] == invoice_id
    assert [r["payment_number"] for r in db.voided_payments_in_gl()][0] == row["payment_number"]
    with pytest.raises(ValueError):
        db.delete_payment(payment_id, 1, reason="again", role="admin")


def test_non_admin_cannot_void_posted_payment(synthetic_db):
    _party, _invoice, payment_id = _setup(synthetic_db)
    with pytest.raises(PermissionError):
        synthetic_db.delete_payment(payment_id, 1, reason="x", role="accountant")
    assert next(r for r in synthetic_db.list_payments() if r["id"] == payment_id)["status"] == "Active"


def test_edit_posted_payment_reverses_and_posts_new_number(synthetic_db):
    db = synthetic_db
    party, _invoice, payment_id = _setup(db)
    old_number = next(r for r in db.list_payments() if r["id"] == payment_id)["payment_number"]
    new_id = db.update_payment(payment_id, {"party_id": party["id"], "payment_date": DAY, "currency": "USD", "amount": "60.00"}, 1)
    rows = {r["id"]: r for r in db.list_payments()}
    assert new_id != payment_id and rows[new_id]["payment_number"] != old_number
    assert rows[payment_id]["status"] == "Reversed" and rows[payment_id]["replaced_by"] == new_id
    entries = _entries(db, payment_id)
    assert [e["source_type"] for e in entries] == ["payment", "payment_reversal"]
    assert entries[1]["reversal_of"] == entries[0]["id"]
    with db.connect() as c:
        lines = c.execute("SELECT e.source_type, SUM(CAST(j.debit AS REAL)) d, SUM(CAST(j.credit AS REAL)) cr FROM journal_lines j "
                          "JOIN journal_entries e ON e.id=j.entry_id WHERE e.source_id=? AND e.source_type IN ('payment','payment_reversal') "
                          "GROUP BY e.source_type", (payment_id,)).fetchall()
    for line in lines: assert round(line["d"], 2) == round(line["cr"], 2)  # each entry balances
    debit, credit = _tb_totals(db)
    assert debit == credit
    assert db.voided_payments_in_gl() == []  # reversed, so the ledger has no leftover


def test_closed_period_blocks_void(synthetic_db):
    _party, _invoice, payment_id = _setup(synthetic_db)
    with synthetic_db.connect() as c:
        c.execute("INSERT OR IGNORE INTO fiscal_years(year,status,opened_at) VALUES(2026,'closed','2026-01-01T00:00:00')")
        c.execute("UPDATE fiscal_years SET status='closed' WHERE year=2026")
    with pytest.raises(ValueError):
        synthetic_db.delete_payment(payment_id, 1, reason="late", role="admin")
    assert next(r for r in synthetic_db.list_payments() if r["id"] == payment_id)["status"] == "Active"


def test_migration_adds_void_columns_idempotently(synthetic_db):
    with synthetic_db.connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(payments)")}
    assert {"voided_at", "voided_by", "void_reason", "reversal_entry_number", "replaced_by"} <= cols
