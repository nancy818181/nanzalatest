"""2.9.53: renaming a company keeps every year linked (by the company id) and its second backup copy follows."""
import tests_setup  # noqa: F401  2.9.74: the sample company of the tests (a new installation has none)
import os
import tempfile
import unittest
from pathlib import Path

from company_manager import CompanyManager
from database import Database


class RenameCompanyTest(unittest.TestCase):
    def test_years_stay_linked_and_second_copy_is_renamed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder); old_env = os.environ.get("SABER_DATA_DIR"); os.environ["SABER_DATA_DIR"] = str(root / "data")
            try:
                import backup_copy
                master = Database(root / "saber_accounting.db"); master.initialize("secret")
                manager = CompanyManager(root / "saber_accounting.db")
                company = manager.create_company({"name": "Old Name SARL", "year": 2025}, master)
                manager.create_year(company["id"], 2026, 1)
                backup_copy.save_settings(str(root / "OneDrive"))
                manager.database(company["id"], 2025).backup()
                self.assertTrue((root / "OneDrive" / "Old Name SARL" / "2025").is_dir())
                renamed = manager.update_company(company["id"], {"name": "New Name SAL"})
                self.assertEqual(sorted(Path(y["database"]).name for y in renamed["years"]), ["New Name SAL_2025.db", "New Name SAL_2026.db"])
                self.assertTrue((root / "OneDrive" / "New Name SAL" / "2025").is_dir()); self.assertFalse((root / "OneDrive" / "Old Name SARL").exists())
                self.assertIsNot(manager.database(company["id"], 2025), manager.database(company["id"], 2026))   # last year still found by id
                for path in list(manager._cache): manager._cache.pop(path).release()
                master.release()
            finally:
                if old_env is None: os.environ.pop("SABER_DATA_DIR", None)
                else: os.environ["SABER_DATA_DIR"] = old_env


if __name__ == "__main__":
    unittest.main()
