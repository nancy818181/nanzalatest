"""Owner-approved void behavior for posted invoices; all data is synthetic."""
import tests_setup  # noqa: F401
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from database import Database


class PostedInvoiceVoidTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "company.db")
        self.db.initialize("Synthetic-Only-2026!")
        self.addCleanup(self.db.release)
        self.user = self.db.user_for_token(self.db.login("admin", "Synthetic-Only-2026!")["token"])["id"]

    def test_posted_invoice_requires_reason_and_void_reverses_without_deleting_original(self):
        invoice_id = self.db.import_invoice({"invoice_number": "S-VOID-1", "kind": "sale", "invoice_date": "10-02-2026",
            "party_name": "Synthetic customer", "currency": "USD", "subtotal": "100", "vat": "11", "total": "111",
            "status": "posted"}, self.user)
        with self.assertRaisesRegex(ValueError, "reason"):
            self.db.mark_invoice_deleted(invoice_id, self.user, role="admin")
        self.db.mark_invoice_deleted(invoice_id, self.user, reason="synthetic correction", role="admin", void_date="2026-02-11")
        with self.db.connect() as connection:
            invoice = connection.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
            original = connection.execute("SELECT id FROM journal_entries WHERE source_type='invoice' AND source_id=?", (invoice_id,)).fetchall()
            reversals = connection.execute("SELECT id,reversal_of FROM journal_entries WHERE source_type='invoice_void' AND source_id=?", (invoice_id,)).fetchall()
            audit = json.loads(connection.execute("SELECT details FROM audit_log WHERE entity='invoice' AND entity_id=? ORDER BY id DESC LIMIT 1", (invoice_id,)).fetchone()[0])
            lines = list(connection.execute("SELECT debit,credit FROM journal_lines WHERE entry_id IN (SELECT id FROM journal_entries WHERE source_type='invoice_void' AND source_id=?)", (invoice_id,)))
            source_line = dict(connection.execute("SELECT * FROM journal_lines WHERE entry_id=?", (original[0]["id"],)).fetchone())
            reverse_line = dict(connection.execute("SELECT * FROM journal_lines WHERE entry_id=?", (reversals[0]["id"],)).fetchone())
        self.assertEqual(invoice["status"], "void")
        self.assertEqual(invoice["void_reason"], "synthetic correction")
        self.assertTrue(invoice["voided_at"])
        self.assertEqual(invoice["voided_by"], self.user)
        listed = next(row for row in self.db.list_invoices() if row["id"] == invoice_id)
        self.assertEqual((listed["subtotal"], listed["vat"], listed["total"], listed["outstanding"]), ("0", "0", "0", 0))
        self.assertEqual(len(original), 1)
        self.assertEqual(len(reversals), 1)
        self.assertEqual(reversals[0]["reversal_of"], original[0]["id"])
        self.assertEqual(sum((Decimal(r["debit"]) for r in lines), Decimal(0)), Decimal("111"))
        self.assertEqual(sum((Decimal(r["credit"]) for r in lines), Decimal(0)), Decimal("111"))
        self.assertEqual(audit["reason"], "synthetic correction")
        self.assertTrue(audit["journal_lines"])
        for key in source_line.keys() - {"id", "entry_id", "debit", "credit"}:
            self.assertEqual(source_line[key], reverse_line[key], key)
        self.assertEqual((source_line["debit"], source_line["credit"]), (reverse_line["credit"], reverse_line["debit"]))

    def test_sales_vat_stock_reports_and_full_audit_reverse(self):
        import inventory
        import vat_return
        self.db.save_party({"kind": "customer", "name": "Stock customer", "currency": "USD"}, self.user)
        warehouse = inventory.save_warehouse(self.db, {"name": "Main warehouse"}, self.user)
        item = inventory.save_item(self.db, {"name": "Synthetic item", "unit": "each", "cost_account": "601100000"}, self.user)
        inventory.save_document(self.db, {"doc_type": "opening", "doc_date": "01-01-2026", "warehouse_id": warehouse["code"]},
                                [{"sku": item["sku"], "quantity": "5", "unit_cost": "20"}], self.user)
        invoice_id = self.db.create_manual_invoice({"invoice_number": "S-STOCK-VOID", "invoice_date": "2026-02-10",
            "party_name": "Stock customer", "kind": "sales", "currency": "USD", "status": "posted"},
            [{"description": "Synthetic item", "quantity": "2", "unit_price": "100", "vat_rate": "11", "item_code": item["sku"],
              "warehouse": warehouse["code"]}], self.user)
        invoice = self.db.get_invoice(invoice_id)
        before_stock = inventory.list_items(self.db)[0]
        before_tb = {(r["code"], r["currency"]): Decimal(str(r["debit"])) - Decimal(str(r["credit"]))
                     for r in self.db.trial_balance(to_date="2026-12-31")}
        self.assertEqual(Decimal(str(before_stock["quantity"])), Decimal("3"))
        self.db.mark_invoice_deleted(invoice_id, self.user, reason="synthetic stock correction", void_date="2026-02-11")
        after_stock = inventory.list_items(self.db)[0]
        after_tb = {(r["code"], r["currency"]): Decimal(str(r["debit"])) - Decimal(str(r["credit"]))
                    for r in self.db.trial_balance(to_date="2026-12-31")}
        tb_rows = self.db.trial_balance(to_date="2026-12-31")
        for currency in {r["currency"] for r in tb_rows}:
            self.assertEqual(sum((Decimal(str(r["debit"])) for r in tb_rows if r["currency"] == currency), Decimal("0")),
                             sum((Decimal(str(r["credit"])) for r in tb_rows if r["currency"] == currency), Decimal("0")))
        self.assertEqual((Decimal(str(after_stock["quantity"])), Decimal(str(after_stock["stock_value"]))), (Decimal("5"), Decimal("100")))
        self.assertNotEqual(before_tb, after_tb)
        self.assertTrue(all(value == Decimal("0") for value in after_tb.values()))
        self.assertEqual(after_tb.get(("4427", "USD"), Decimal("0")), Decimal("0"))
        with self.db.connect() as connection:
            party_id = connection.execute("SELECT party_id FROM invoices WHERE id=?", (invoice_id,)).fetchone()[0]
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM stock_documents WHERE invoice_id=?", (invoice_id,)).fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM stock_documents WHERE reference=?", (invoice["invoice_number"],)).fetchone()[0], 2)
            audit = json.loads(connection.execute("SELECT details FROM audit_log WHERE action='void' AND entity_id=?", (invoice_id,)).fetchone()[0])
        self.assertEqual(self.db.statement_of_account(party_id, to_date="2026-12-31")["items"], [])
        self.assertEqual(self.db.aging_report("31-12-2026", kind="sale"), [])
        result = vat_return.build_vat_return(self.db, 2026, 1)
        self.assertFalse(any(doc.get("invoice_number") == "S-STOCK-VOID" for doc in result["documents"]))
        self.assertEqual(audit["reason"], "synthetic stock correction")
        self.assertTrue(audit["stock_movements"][0]["movements"])
        self.assertTrue(audit["stock_movements"][0]["reversal_documents"])
        self.assertIn("reference", audit["journal_lines"][0])

    def test_void_obeys_period_locks_and_allocations(self):
        party_id = self.db.save_party({"kind": "customer", "name": "Lock customer", "currency": "USD"}, self.user)["id"]
        invoice_id = self.db.import_invoice({"invoice_number": "S-LOCK", "kind": "sale", "invoice_date": "10-02-2026",
            "party_name": "Synthetic customer", "currency": "USD", "subtotal": "10", "vat": "0", "total": "10", "status": "posted"}, self.user)
        with self.db.connect() as connection:
            connection.execute("INSERT INTO fiscal_years(year,status,opened_at) VALUES(2026,'closed','now')")
        with self.assertRaisesRegex(ValueError, "closed"):
            self.db.mark_invoice_deleted(invoice_id, self.user, reason="test", void_date="2026-02-11")
        with self.db.connect() as connection:
            connection.execute("UPDATE fiscal_years SET status='open' WHERE year=2026")
            connection.execute("INSERT INTO app_settings(key,value) VALUES('books_locked_until','2026-02-10') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        with self.assertRaisesRegex(ValueError, "PERIOD LOCKED"):
            self.db.mark_invoice_deleted(invoice_id, self.user, reason="test", void_date="2026-02-11")
        with self.db.connect() as connection:
            connection.execute("UPDATE app_settings SET value='' WHERE key='books_locked_until'")
            payment_id = connection.execute("INSERT INTO payments(kind,party_id,payment_date,currency,amount,cash_account,party_account,created_at) VALUES('customer_receipt',?,'2026-02-11','USD','1','531','4111','now')", (party_id,)).lastrowid
            connection.execute("INSERT INTO payment_allocations(payment_id,invoice_id,amount,created_at) VALUES(?,?, '1','now')", (payment_id, invoice_id))
        with self.assertRaisesRegex(ValueError, "allocated payments"):
            self.db.mark_invoice_deleted(invoice_id, self.user, reason="test", void_date="2026-02-11")

    def test_existing_file_gets_idempotent_invoice_void_columns(self):
        self.db.release()
        with self.db.connect() as connection:
            for column in ("void_reason", "voided_by", "voided_at"):
                connection.execute(f"ALTER TABLE invoices DROP COLUMN {column}")
            connection.execute("UPDATE app_settings SET value='old-schema-fingerprint' WHERE key='startup_schema_version'")
        self.db.initialize_if_needed("Synthetic-Only-2026!")
        with self.db.connect() as connection:
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(invoices)")}
            entries = connection.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]
        self.assertTrue({"void_reason", "voided_by", "voided_at"}.issubset(columns))
        self.assertEqual(entries, 0)
        self.db.initialize_if_needed("Synthetic-Only-2026!")
        with self.db.connect() as connection:
            self.assertTrue({"void_reason", "voided_by", "voided_at"}.issubset({r["name"] for r in connection.execute("PRAGMA table_info(invoices)")}))


if __name__ == "__main__":
    unittest.main()
