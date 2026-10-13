"""2.9.75: the SaberAccounting folder copied to another computer / Windows user still opens every company."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from company_manager import CompanyManager
from database import Database


class MovedDataFolderTest(unittest.TestCase):
    def test_copied_folder_opens_its_companies_and_remembers_the_new_place(self):
        environment = dict(os.environ); environment.pop("SABER_FIRST_COMPANY", None)
        with mock.patch.dict(os.environ, environment, clear=True), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            old, new = Path(folder) / "OldUser" / "SaberAccounting", Path(folder) / "NewUser" / "SaberAccounting"
            old.mkdir(parents=True)
            master = Database(old / "saber_accounting.db"); master.initialize("secret")
            manager = CompanyManager(old / "saber_accounting.db")
            company = manager.create_company({"name": "Moved Books SAL", "year": 2026}, master)
            manager.database(company["id"], 2026).create_manual_invoice({"invoice_date": "15-03-2026", "party_name": "C", "kind": "sales", "currency": "USD"},
                                                                         [{"description": "S", "quantity": 1, "unit_price": 100}], 1)
            for path in list(manager._cache): manager._cache.pop(path).release()
            master.release()
            shutil.copytree(old, new)
            moved = CompanyManager(new / "saber_accounting.db")
            books = moved.database(company["id"], 2026)
            self.assertEqual(len(books.list_invoices()), 1)
            saved = json.loads((new / "companies" / "companies.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["companies"][0]["years"][0]["database"].startswith(str(new.resolve())))
            books.release()

    def test_a_path_outside_the_data_folder_is_still_refused(self):
        environment = dict(os.environ); environment.pop("SABER_FIRST_COMPANY", None)
        with mock.patch.dict(os.environ, environment, clear=True), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder) / "SaberAccounting"; root.mkdir()
            (Path(folder) / "outside.db").write_bytes(b"")
            manager = CompanyManager(root / "saber_accounting.db")
            with self.assertRaisesRegex(ValueError, "inside the application data directory"):
                manager._database_path(str(Path(folder) / "outside.db"))


if __name__ == "__main__":
    unittest.main()
