"""2.9.74: a new installation starts with no company; a main file from a version before the company list still opens."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from company_manager import CompanyManager
from database import Database


def _without_sample_company():
    environment = dict(os.environ); environment.pop("SABER_FIRST_COMPANY", None)
    return mock.patch.dict(os.environ, environment, clear=True)


class NewInstallationTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_new_installation_has_no_company_and_the_first_one_is_created_by_the_user(self):
        with _without_sample_company():
            master = Database(self.root / "saber_accounting.db"); master.initialize("secret"); self.addCleanup(master.release)
            manager = CompanyManager(self.root / "saber_accounting.db")
            self.assertEqual(manager.list_companies(True), [])
            with self.assertRaisesRegex(KeyError, "No company"): manager.database()
            created = manager.create_company({"name": "My Own SARL", "year": 2026}, master)
            self.assertEqual([c["name"] for c in CompanyManager(self.root / "saber_accounting.db").list_companies(True)], ["My Own SARL"])
            for path in list(manager._cache): manager._cache.pop(path).release()

    def test_old_main_file_with_books_opens_as_its_own_company(self):
        with _without_sample_company():
            master = Database(self.root / "saber_accounting.db"); master.initialize("secret"); self.addCleanup(master.release)
            master.save_settings({"company_name": "Old Books SAL"}, 1)
            master.save_journal_voucher({"entry_date": "01-03-2023", "currency": "USD", "description": "old"},
                                        [{"account_code": "531", "debit": "10", "credit": "0"}, {"account_code": "101", "debit": "0", "credit": "10"}], 1)
            companies = CompanyManager(self.root / "saber_accounting.db").list_companies(True)
            self.assertEqual([(c["name"], [y["year"] for y in c["years"]]) for c in companies], [("Old Books SAL", [2023])])


if __name__ == "__main__":
    unittest.main()
