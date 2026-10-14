"""2.9.108: a company file brought from another computer is added (button or copied into the companies folder)."""
import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from company_manager import CompanyManager
from database import Database


def installation(folder):
    master = Database(Path(folder) / "saber_accounting.db"); master.initialize("secret12345")
    return master, CompanyManager(Path(folder) / "saber_accounting.db")


class CompanyImportTest(unittest.TestCase):
    def setUp(self):
        self.seed = os.environ.pop("SABER_FIRST_COMPANY", None)  # a clean installation on each computer
        self.temp = TemporaryDirectory(); root = Path(self.temp.name)
        (root / "pc_a").mkdir(); (root / "pc_b").mkdir()
        master_a, self.pc_a = installation(root / "pc_a")
        company = self.pc_a.create_company({"name": "Alpha Universe", "year": 2026}, master_a)
        self.source = Path(company["years"][0]["database"])
        self.master_b, self.pc_b = installation(root / "pc_b")

    def tearDown(self):
        self.temp.cleanup()
        if self.seed is not None: os.environ["SABER_FIRST_COMPANY"] = self.seed

    def test_add_from_file_copies_and_lists_it(self):
        company = self.pc_b.add_company_file(self.source)
        self.assertEqual(company["name"], "Alpha Universe")
        self.assertEqual([f["year"] for f in company["years"]], [2026])
        copied = Path(company["years"][0]["database"])
        self.assertTrue(copied.is_file()); self.assertNotEqual(copied, self.source.resolve())
        self.assertTrue(self.source.is_file())                     # the original is left untouched
        self.assertIn("Alpha Universe", [c["name"] for c in self.pc_b.list_companies()])
        self.pc_b.database(company["id"], 2026).settings()          # it opens
        with self.assertRaises(ValueError):                         # the same year twice is refused
            self.pc_b.add_company_file(self.source)

    def test_file_copied_into_the_companies_folder_is_found(self):
        target = self.pc_b.root / "Alpha Universe" / "Alpha Universe_2026.db"
        target.parent.mkdir(parents=True); shutil.copy(self.source, target)
        added = self.pc_b.discover_files()
        self.assertEqual([(name, year) for _path, name, year in added], [("Alpha Universe", 2026)])
        self.assertEqual(self.pc_b.discover_files(), [])            # only once

    def test_a_file_that_is_not_a_company_is_refused(self):
        other = Path(self.temp.name) / "notes.db"; other.write_bytes(b"not a database")
        with self.assertRaises(ValueError):
            self.pc_b.add_company_file(other)


if __name__ == "__main__":
    unittest.main()
