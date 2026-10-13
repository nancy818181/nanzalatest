"""2.9.70: a backup made by an older version is brought up to date when it is restored; payroll help shows the 120M ceiling."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import Database
import lebanese_payroll


class RestoreOlderBackupTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self.folder.name) / "company.db"); self.db.initialize("secret12345")
        with self.db.connect() as connection:
            self.user = connection.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        self.db.import_invoice({"invoice_number": "S-1", "invoice_date": "15-03-2026", "party_name": "Buyer", "kind": "sale",
                                "currency": "LBP", "subtotal": 100000, "vat": 11000, "total": 111000}, self.user)

    def tearDown(self):
        self.db.release()
        self.folder.cleanup()

    def _older_backup(self):
        """A backup as an older version would have left it: a later column missing and no upgrade marker."""
        self.db.backup("manual")
        files = self.db._backup_files(); name = sorted(files)[-1]
        connection = sqlite3.connect(files[name])
        try:
            connection.execute("ALTER TABLE invoices DROP COLUMN payment_account")
            connection.execute("DELETE FROM app_settings WHERE key='startup_schema_version'")
            connection.commit()
        finally: connection.close()
        return name

    def test_restored_older_backup_gets_the_new_columns_and_keeps_the_data(self):
        name = self._older_backup()
        self.db.restore_backup(name, self.user)
        with self.db.connect() as connection:
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(invoices)")}
            self.assertIn("payment_account", columns)
            connection.execute("SELECT i.payment_account FROM invoices i").fetchall()  # the 2.9.64 error must not come back
            self.assertEqual(connection.execute("SELECT invoice_number FROM invoices").fetchone()[0], "S-1")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users WHERE username='admin'").fetchone()[0], 1)

    def test_restore_keeps_the_admin_password(self):
        name = self._older_backup()
        self.db.restore_backup(name, self.user)
        session = self.db.login("admin", "secret12345")
        self.assertTrue(session and session.get("token"))


class PayrollCeilingTextTest(unittest.TestCase):
    def test_sickness_ceiling_from_august_2025_is_120m_in_rules_and_help(self):
        august = next(p for p in lebanese_payroll.official_periods() if p["date_from"] == "2025-08-01")
        self.assertEqual(august["medical_ceiling"], "120000000")
        help_text = Path(__file__).with_name("desktop_payroll.py").read_text(encoding="utf-8")
        self.assertIn("120M (08-2025)", help_text)
        self.assertNotIn("140M", help_text)

    def test_no_openai_key_prompt_is_left(self):
        source = Path(__file__).with_name("desktop_stage3.py").read_text(encoding="utf-8")
        self.assertNotIn("OpenAI API key", source)


if __name__ == "__main__":
    unittest.main()
