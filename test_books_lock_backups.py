"""Period lock (closed books) and automatic backups with retention (2.9.36)."""
import tempfile
import time
import unittest
from pathlib import Path

from database import Database


class BooksLockAndBackupTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self.folder.name) / "company.db"); self.db.initialize("secret12345")
        with self.db.connect() as connection:
            self.user = connection.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]

    def tearDown(self):
        self.db.release() if hasattr(self.db, "release") else None
        self.folder.cleanup()

    def sale(self, number, day):
        return self.db.import_invoice({"invoice_number": number, "invoice_date": day, "party_name": "Buyer", "kind": "sale",
                                       "currency": "LBP", "subtotal": 100000, "vat": 11000, "total": 111000}, self.user)

    def entries(self):
        with self.db.connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]

    def test_locked_period_refuses_new_changed_or_deleted_entries_and_unlock_allows_them(self):
        self.sale("S-1", "15-03-2026")
        before = self.entries()
        lock = self.db.set_books_lock("31-03-2026", self.user)
        self.assertEqual(lock["locked_until"], "2026-03-31"); self.assertEqual(lock["display"], "31-03-2026")
        with self.assertRaisesRegex(Exception, "PERIOD LOCKED"):
            self.sale("S-2", "31-03-2026")
        self.assertEqual(self.entries(), before)  # nothing half-posted
        with self.db.connect() as connection:
            entry = connection.execute("SELECT id FROM journal_entries ORDER BY id LIMIT 1").fetchone()[0]
        for statement, args in (("UPDATE journal_entries SET description='x' WHERE id=?", (entry,)),
                                ("DELETE FROM journal_entries WHERE id=?", (entry,)),
                                ("UPDATE journal_lines SET debit=debit WHERE entry_id=?", (entry,)),
                                ("DELETE FROM journal_lines WHERE entry_id=?", (entry,))):
            with self.subTest(statement=statement), self.assertRaisesRegex(Exception, "PERIOD LOCKED"):
                with self.db.connect() as connection: connection.execute(statement, args)
        self.sale("S-3", "01-04-2026")  # after the lock date: allowed
        self.assertGreater(self.entries(), before)
        self.db.set_books_lock("", self.user)
        self.sale("S-2", "31-03-2026")  # unlocked: allowed again
        self.assertEqual(self.db.books_lock()["locked_until"], "")
        with self.assertRaises(ValueError): self.db.set_books_lock("31/31/2026", self.user)

    def test_lock_is_kept_in_the_file_and_triggers_exist_after_reopening(self):
        self.db.set_books_lock("31-01-2026", self.user)
        reopened = Database(self.db.path); reopened.initialize_if_needed("secret12345")
        with reopened.connect() as connection:
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        self.assertTrue({"books_lock_entry_insert", "books_lock_entry_delete", "books_lock_line_insert"} <= names)
        self.assertEqual(reopened.books_lock()["locked_until"], "2026-01-31")

    def test_automatic_backup_once_per_interval_keeps_newest_30_and_never_deletes_manual_copies(self):
        manual = Path(self.db.backup())
        first = self.db.maybe_scheduled_backup()
        self.assertTrue(first and first.endswith("_auto.db"))
        self.assertIsNone(self.db.maybe_scheduled_backup())  # not due again within 24 hours
        folder = Path(first).parent
        for index in range(35):
            path = folder / f"older_{index:02d}_auto.db"; path.write_bytes(Path(first).read_bytes())
            stamp = time.time() - (index + 1) * 86400
            import os; os.utime(path, (stamp, stamp))
        removed = self.db.prune_auto_backups()
        self.assertEqual(len(list(folder.glob("*_auto.db"))), 30)
        self.assertEqual(len(removed), 6)
        self.assertTrue(manual.exists())
        self.assertTrue(Path(first).exists())  # the newest automatic copy stays
        kinds = {item["name"]: item["kind"] for item in self.db.list_backups()}
        self.assertEqual(kinds[Path(first).name], "automatic"); self.assertEqual(kinds[manual.name], "backup")

    def test_restore_brings_back_the_data_of_the_backup(self):
        self.sale("S-1", "15-03-2026")
        name = Path(self.db.backup()).name
        self.sale("S-2", "16-03-2026")
        self.db.restore_backup(name, self.user)
        numbers = {row["invoice_number"] for row in self.db.list_invoices()}
        self.assertEqual(numbers, {"S-1"})


if __name__ == "__main__":
    unittest.main()
