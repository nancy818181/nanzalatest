"""Synthetic regressions for the Task 7b invoice lookup and read-path indexes."""
import tempfile
import unittest
from pathlib import Path

from database import Database


class Task7bDatabasePathTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "layout-perf.db")
        self.db.initialize("synthetic-test-password")
        self.addCleanup(self.db.release)

    def test_targeted_invoice_lookup_matches_full_list_and_indexes_preserve_reports(self):
        invoice_id = self.db.create_manual_invoice(
            {"invoice_date": "15-05-2026", "party_name": "Synthetic Customer", "kind": "sales",
             "currency": "USD", "status": "posted"},
            [{"description": "Synthetic service", "quantity": "1", "unit_price": "100.01", "vat_rate": "11"}], 1)
        expected = next(row for row in self.db.list_invoices() if row["id"] == invoice_id)
        self.assertEqual(self.db.get_invoice(invoice_id), expected)
        party_id = expected["party_id"] if "party_id" in expected else None
        if party_id is None:
            with self.db.connect() as connection:
                party_id = connection.execute("SELECT party_id FROM invoices WHERE id=?", (invoice_id,)).fetchone()[0]

        before = (self.db.open_documents(party_id), self.db.statement_of_account(party_id), self.db.trial_balance())
        with self.db.connect() as connection:
            connection.execute("DROP INDEX idx_invoices_party_status_date")
            connection.execute("DROP INDEX idx_journal_lines_entry_account_amounts")
        self.db.initialize_if_needed("synthetic-test-password")
        after = (self.db.open_documents(party_id), self.db.statement_of_account(party_id), self.db.trial_balance())
        self.assertEqual(after, before)
        with self.db.connect() as connection:
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("idx_invoices_party_status_date", names)
        self.assertIn("idx_journal_lines_entry_account_amounts", names)


if __name__ == "__main__":
    unittest.main()
