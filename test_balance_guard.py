"""2.9.43: no journal entry can be saved with total Debit different from total Credit, from any path."""
import tempfile
import unittest
from pathlib import Path

from database import Database, utcnow


class BalanceGuardTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.folder.name) / "company_2026.db"))
        self.db.initialize("StrongPass123")
        with self.db.connect() as db:
            self.cash, self.sales = [db.execute("SELECT id FROM accounts WHERE code=?", (code,)).fetchone()[0] for code in ("121", "713")]

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        try: self.folder.cleanup()
        except OSError: pass

    def _entry(self, db, number):
        return db.execute("INSERT INTO journal_entries(entry_number,entry_date,description,source_type,currency,created_at) VALUES(?,?,?,?,?,?)",
                          (number, "2026-03-01", "test", "manual", "USD", utcnow())).lastrowid

    def _line(self, db, entry, account, debit, credit):
        return db.execute("INSERT INTO journal_lines(entry_id,account_id,debit,credit) VALUES(?,?,?,?)", (entry, account, str(debit), str(credit))).lastrowid

    def _count(self, number):
        with self.db.connect() as db:
            return db.execute("SELECT COUNT(*) FROM journal_entries WHERE entry_number=?", (number,)).fetchone()[0]

    def test_balanced_entry_is_saved(self):
        with self.db.connect() as db:
            entry = self._entry(db, "T-1"); self._line(db, entry, self.cash, "100.50", 0); self._line(db, entry, self.sales, 0, "100.50")
        self.assertEqual(self._count("T-1"), 1)

    def test_unbalanced_entry_is_refused_and_nothing_is_saved(self):
        with self.assertRaises(ValueError) as caught:
            with self.db.connect() as db:
                entry = self._entry(db, "T-2"); self._line(db, entry, self.cash, 100, 0); self._line(db, entry, self.sales, 0, 90)
        self.assertIn("T-2 is not balanced", str(caught.exception)); self.assertIn("difference 10.00", str(caught.exception))
        self.assertEqual(self._count("T-2"), 0)

    def test_one_sided_entry_is_refused(self):
        with self.assertRaises(ValueError):
            with self.db.connect() as db:
                entry = self._entry(db, "T-3"); self._line(db, entry, self.cash, 5, 0)
        self.assertEqual(self._count("T-3"), 0)

    def test_changing_or_removing_a_line_cannot_unbalance_a_saved_entry(self):
        with self.db.connect() as db:
            entry = self._entry(db, "T-4"); first = self._line(db, entry, self.cash, 100, 0); self._line(db, entry, self.sales, 0, 100)
        with self.assertRaises(ValueError):
            with self.db.connect() as db: db.execute("UPDATE journal_lines SET debit='120' WHERE id=?", (first,))
        with self.assertRaises(ValueError):
            with self.db.connect() as db: db.execute("DELETE FROM journal_lines WHERE id=?", (first,))
        with self.db.connect() as db:
            self.assertEqual(db.execute("SELECT debit FROM journal_lines WHERE id=?", (first,)).fetchone()[0], "100")
            db.execute("UPDATE journal_lines SET debit='80' WHERE id=?", (first,))
            db.execute("UPDATE journal_lines SET credit='80' WHERE entry_id=? AND id<>?", (entry, first))  # both sides together: allowed
            db.execute("DELETE FROM journal_entries WHERE id=?", (entry,))  # whole entry removed: allowed
        self.assertEqual(self._count("T-4"), 0)

    def test_rounding_up_to_one_cent_is_accepted(self):
        with self.db.connect() as db:
            entry = self._entry(db, "T-5"); self._line(db, entry, self.cash, "33.34", 0); self._line(db, entry, self.sales, 0, "33.333")
        self.assertEqual(self._count("T-5"), 1)

    def test_entries_saved_by_older_versions_are_listed_for_review(self):
        self.db._balance_check_paused = True  # as an older version would have written it
        try:
            with self.db.connect() as db:
                entry = self._entry(db, "OLD-1"); self._line(db, entry, self.cash, 50, 0)
        finally: self.db._balance_check_paused = False
        found = self.db.unbalanced_entries()
        self.assertEqual([r["entry_number"] for r in found], ["OLD-1"]); self.assertEqual(found[0]["difference"], "50")
        self.db.initialize("StrongPass123")  # an upgrade never fails because of old entries
        self.assertFalse(self.db._balance_check_paused)

    def test_a_failed_check_does_not_block_the_next_change(self):
        with self.assertRaises(ValueError):
            with self.db.connect() as db:
                entry = self._entry(db, "T-6"); self._line(db, entry, self.cash, 1, 0)
        with self.db.connect() as db:
            entry = self._entry(db, "T-7"); self._line(db, entry, self.cash, 1, 0); self._line(db, entry, self.sales, 0, 1)
        self.assertEqual((self._count("T-6"), self._count("T-7")), (0, 1))


if __name__ == "__main__":
    unittest.main()
