"""2.9.136 (F1, owner decision 25-10-2026): a posted receipt / payment is never removed from the books.

Admin delete = void (record, number and posted entry kept; out of statement / ageing / allocations; reason + full audit).
Non-admin cannot void; editing a posted one = reversal dated on the edit date + a new document with a new number."""
import json
from decimal import Decimal

from contextlib import contextmanager


@contextmanager
def _raises(kind):
    """Works with pytest and with plain unittest (the CI 'Tests' job has no pytest)."""
    try: yield
    except kind: return
    raise AssertionError(f"{kind.__name__} was not raised")

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
    with _raises(ValueError):
        db.delete_payment(payment_id, 1, reason="", role="admin")  # a reason is required
    result = db.delete_payment(payment_id, 1, reason="Bounced cheque", role="admin")
    assert result["voided"] == payment_id
    row = next(r for r in db.list_payments() if r["id"] == payment_id)
    assert row["status"] == "Void" and row["void_reason"] == "Bounced cheque"
    assert len(_entries(db, payment_id)) == 1  # the posted entry is NOT deleted
    assert _tb_totals(db) == before  # ledger unchanged (owner accepted)
    docs = {d["id"]: d for d in db.open_documents(party["id"])}
    assert abs(docs[invoice_id]["open_amount"] - 100.0) < 0.005  # allocation released -> invoice open again
    statement = db.statement_of_account(party["id"]) if hasattr(db, "statement_of_account") else None
    if statement is not None:
        text = json.dumps(statement, default=str)
        assert row["payment_number"] not in text
    with db.connect() as c:
        audit = c.execute("SELECT details FROM audit_log WHERE action='void' AND entity='payment' AND entity_id=?", (payment_id,)).fetchone()
    details = json.loads(audit["details"])
    assert details["reason"] == "Bounced cheque" and details["journal_lines"] and details["allocations"][0]["invoice_id"] == invoice_id
    assert [r["payment_number"] for r in db.voided_payments_in_gl()][0] == row["payment_number"]
    with _raises(ValueError):
        db.delete_payment(payment_id, 1, reason="again", role="admin")


def test_non_admin_cannot_void_posted_payment(synthetic_db):
    _party, _invoice, payment_id = _setup(synthetic_db)
    with _raises(PermissionError):
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


def test_multicurrency_payment_reversal_preserves_lbp_and_usd_amounts(synthetic_db):
    """Declared fixture rate: 1 USD = 1,500 LBP; reversal mirrors stored line values exactly."""
    db = synthetic_db
    party, _invoice, payment_id = _setup(db)
    with db.connect() as c:
        entry = c.execute("SELECT id FROM journal_entries WHERE source_type='payment' AND source_id=?", (payment_id,)).fetchone()
        lines = c.execute("SELECT id,debit,credit FROM journal_lines WHERE entry_id=? ORDER BY id", (entry["id"],)).fetchall()
        for line in lines:
            amount = Decimal(str(line["debit"] or line["credit"]))
            c.execute("""UPDATE journal_lines SET line_currency='USD',amount=?,amount_lbp=?,amount_usd=?,rate_lbp='1500',rate_usd='1'
                         WHERE id=?""", (str(amount), str(amount * Decimal("1500")), str(amount), line["id"]))
    new_id = db.update_payment(payment_id, {"party_id": party["id"], "payment_date": DAY, "currency": "USD", "amount": "60.00"}, 1)
    with db.connect() as c:
        pair = c.execute("""SELECT e.source_type,j.* FROM journal_entries e JOIN journal_lines j ON j.entry_id=e.id
                           WHERE e.source_id=? AND e.source_type IN ('payment','payment_reversal') ORDER BY e.id,j.id""", (payment_id,)).fetchall()
        self_rows = c.execute("SELECT currency,amount FROM payments WHERE id=?", (new_id,)).fetchone()
    assert self_rows["currency"] == "USD"
    totals = {"USD": Decimal("0"), "LBP": Decimal("0")}
    for row in pair:
        sign = Decimal("1") if Decimal(str(row["debit"] or 0)) else Decimal("-1")
        totals["USD"] += sign * Decimal(str(row["amount_usd"] or 0))
        totals["LBP"] += sign * Decimal(str(row["amount_lbp"] or 0))
    assert totals == {"USD": Decimal("0"), "LBP": Decimal("0")}
    trial = db.trial_balance(to_date=DAY)
    assert sum((Decimal(str(row["debit"])) - Decimal(str(row["credit"])) for row in trial), Decimal("0")) == 0
    assert sum((Decimal(str(row["usd_debit"])) - Decimal(str(row["usd_credit"])) for row in trial), Decimal("0")) == 0
    assert sum((Decimal(str(row["lbp_debit"])) - Decimal(str(row["lbp_credit"])) for row in trial), Decimal("0")) == 0


def test_void_audit_snapshot_contains_every_journal_line_column(synthetic_db):
    db = synthetic_db
    _party, _invoice, payment_id = _setup(db)
    with db.connect() as c:
        line = c.execute("SELECT id FROM journal_lines WHERE entry_id=(SELECT id FROM journal_entries WHERE source_type='payment' AND source_id=?) LIMIT 1", (payment_id,)).fetchone()
        c.execute("""UPDATE journal_lines SET line_currency='USD',amount='100',amount_lbp='150000',amount_usd='100',
                     rate_lbp='1500',rate_usd='1',reference='REF-1' WHERE id=?""", (line["id"],))
    db.delete_payment(payment_id, 1, reason="Audit snapshot", role="admin")
    with db.connect() as c:
        details = json.loads(c.execute("SELECT details FROM audit_log WHERE action='void' AND entity_id=?", (payment_id,)).fetchone()[0])
        expected = {row["name"] for row in c.execute("PRAGMA table_info(journal_lines)")}
    assert expected <= set(details["journal_lines"][0])


def test_payment_void_http_role_and_reason():
    import tempfile, threading
    from http.server import ThreadingHTTPServer
    from pathlib import Path
    from company_manager import CompanyManager
    from client import ApiClient
    from database import Database
    from server import ApiHandler
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        master_path = Path(folder) / "master.db"
        master = Database(master_path); master.initialize("Synthetic-Http-F1-2026")
        manager = CompanyManager(master_path)
        company = manager.create_company({"name": "Synthetic F1 HTTP", "year": 2026}, master)
        handler = type("PaymentVoidHttpHandler", (ApiHandler,), dict(db=master, master_db=master,
                       company_manager=manager))
        http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
        try:
            admin = ApiClient(f"http://127.0.0.1:{http.server_port}"); admin.login("admin", "Synthetic-Http-F1-2026")
            admin.select_company_year(company["id"], int(company["years"][0]["year"]))
            admin.save_user({"username":"f1staff", "password":"F1-Staff-2026!", "role":"accountant"})
            staff = ApiClient(admin.base_url); staff.login("f1staff", "F1-Staff-2026!")
            staff.select_company_year(company["id"], int(company["years"][0]["year"]))
            db = manager.database(company["id"], int(company["years"][0]["year"]))
            party, _invoice, payment_id = _setup(db)
            for client, reason, expected in ((staff, "attempt", "administrator"), (admin, None, "reason")):
                try:
                    client.delete_payment(payment_id, reason)
                except RuntimeError as exc:
                    assert expected in str(exc).lower()
                else:
                    raise AssertionError(f"HTTP DELETE should have failed with {expected}")
            result = admin.delete_payment(payment_id, "HTTP approved reason")
            assert result.get("voided")
        finally:
            http.shutdown(); http.server_close(); thread.join(5); master.release()


def test_closed_period_blocks_void(synthetic_db):
    _party, _invoice, payment_id = _setup(synthetic_db)
    with synthetic_db.connect() as c:
        c.execute("INSERT OR IGNORE INTO fiscal_years(year,status,opened_at) VALUES(2026,'closed','2026-01-01T00:00:00')")
        c.execute("UPDATE fiscal_years SET status='closed' WHERE year=2026")
    with _raises(ValueError):
        synthetic_db.delete_payment(payment_id, 1, reason="late", role="admin")
    assert next(r for r in synthetic_db.list_payments() if r["id"] == payment_id)["status"] == "Active"


def test_migration_adds_void_columns_idempotently(synthetic_db):
    with synthetic_db.connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(payments)")}
    assert {"voided_at", "voided_by", "void_reason", "reversal_entry_number", "replaced_by"} <= cols


def test_books_lock_blocks_void_and_edit(synthetic_db):
    party, _invoice, payment_id = _setup(synthetic_db)
    with synthetic_db.connect() as c:
        c.execute("INSERT INTO app_settings(key,value) VALUES('books_locked_until','2026-01-31') "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    with _raises(ValueError):
        synthetic_db.delete_payment(payment_id, 1, reason="locked", role="admin")
    with _raises(ValueError):
        synthetic_db.update_payment(payment_id, {"party_id": party["id"], "payment_date": DAY, "currency": "USD", "amount": "60.00"}, 1)
    assert next(r for r in synthetic_db.list_payments() if r["id"] == payment_id)["status"] == "Active"


# The CI "Tests" job runs unittest discovery: the same checks as a TestCase (a fresh synthetic company for each).
import tempfile as _tempfile  # noqa: E402
import unittest as _unittest  # noqa: E402
from pathlib import Path as _Path  # noqa: E402


class PaymentVoidRulesTest(_unittest.TestCase):
    def _run(self, check):
        from database import Database
        with _tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db = Database(_Path(folder) / "synthetic-company.db"); db.initialize("Synthetic-Only-Test-Password-2026")
            try: check(db)
            finally: db.release()

    def test_admin_void(self): self._run(test_admin_void_keeps_record_and_entry_and_releases_allocation)
    def test_non_admin_refused(self): self._run(test_non_admin_cannot_void_posted_payment)
    def test_edit_reverses(self): self._run(test_edit_posted_payment_reverses_and_posts_new_number)
    def test_closed_year(self): self._run(test_closed_period_blocks_void)
    def test_books_lock(self): self._run(test_books_lock_blocks_void_and_edit)
    def test_migration(self): self._run(test_migration_adds_void_columns_idempotently)
    def test_old_file_upgraded(self): self._run(test_existing_file_gets_the_void_columns_on_open)
    def test_fingerprint_tuples(self): self._run(test_schema_fingerprint_sees_columns_listed_in_tuples)
    def test_multicurrency_reversal(self): self._run(test_multicurrency_payment_reversal_preserves_lbp_and_usd_amounts)
    def test_full_void_audit_snapshot(self): self._run(test_void_audit_snapshot_contains_every_journal_line_column)
    def test_http_void_role_and_reason(self): test_payment_void_http_role_and_reason()


def test_existing_file_gets_the_void_columns_on_open(synthetic_db):
    """2.9.136 regression: a file made by 2.9.135 was not upgraded ('no such column: x.voided_at') because the schema
    fingerprint ignored column names listed in tuples. A stale schema stamp must bring the columns back."""
    import database
    with synthetic_db.connect() as c:
        for column in ("voided_at", "voided_by", "void_reason", "reversal_entry_number", "replaced_by"):
            c.execute(f"ALTER TABLE payments DROP COLUMN {column}")
        c.execute("UPDATE app_settings SET value='old' WHERE key='startup_schema_version'")
    synthetic_db.initialize_if_needed("Synthetic-Only-Test-Password-2026")
    with synthetic_db.connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(payments)")}
    assert {"voided_at", "reversal_entry_number"} <= cols
    synthetic_db.list_payments()


def test_schema_fingerprint_sees_columns_listed_in_tuples(synthetic_db):
    """The fingerprint must change when a column is added inside a tuple of the upgrade code."""
    import database
    original = database.Database._initialize
    before = database._schema_fingerprint()
    def changed(self, admin_password):
        _probe = (("payments_probe_column", "TEXT"),)  # noqa: F841 - only its presence in the code matters
        return original(self, admin_password)
    try:
        database.Database._initialize = changed
        assert database._schema_fingerprint() != before
    finally:
        database.Database._initialize = original
