"""2.9.42: every backup checked, update check, user guide, screens split further, ignored errors logged."""
import json
import re
import tempfile
import unittest
from pathlib import Path

import app_runtime
from database import Database

HERE = Path(__file__).resolve().parent


class BackupCheckTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.folder.name) / "company_2026.db"))
        self.db.initialize("StrongPass123")

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        try: self.folder.cleanup()
        except OSError: pass

    def test_new_backup_is_checked_and_marked_ok(self):
        path = Path(self.db.backup())
        self.assertTrue(path.exists())
        listed = {row["name"]: row for row in self.db.list_backups()}
        self.assertEqual(listed[path.name]["checked"], "ok")
        checks = json.loads((path.parent / Database.BACKUP_CHECKS_FILE).read_text(encoding="utf-8"))
        self.assertTrue(checks[path.name]["ok"])

    def test_damaged_copy_is_set_aside_and_reported(self):
        source = Path(self.db.path)
        bad = source.parent / "backups" / "company_2026_bad.db"
        bad.parent.mkdir(parents=True, exist_ok=True); bad.write_bytes(b"not a database" * 200)
        with self.assertRaises(RuntimeError) as caught:
            self.db._check_new_backup(source, bad)
        self.assertIn("could not be verified", str(caught.exception))
        self.assertFalse(bad.exists())
        self.assertTrue(bad.with_name(bad.name + ".damaged").exists())
        self.assertNotIn(bad.name, {row["name"] for row in self.db.list_backups()})

    def test_copy_missing_tables_fails(self):
        import sqlite3
        from contextlib import closing
        source = Path(self.db.path)
        partial = source.parent / "backups" / "company_2026_partial.db"
        partial.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(partial)) as db: db.execute("CREATE TABLE accounts(id INTEGER)"); db.commit()
        with self.assertRaises(RuntimeError) as caught:
            self.db._check_new_backup(source, partial)
        self.assertIn("missing tables", str(caught.exception))

    def test_older_backups_show_not_checked(self):
        old = Path(self.db.path).parent / "backups" / "company_2026_2020-01-01_000000.db"
        old.parent.mkdir(parents=True, exist_ok=True); old.write_bytes(Path(self.db.path).read_bytes())
        listed = {row["name"]: row for row in self.db.list_backups()}
        self.assertEqual(listed[old.name]["checked"], "not checked")


class UpdateCheckTest(unittest.TestCase):
    def test_versions_compare_as_numbers(self):
        self.assertGreater(app_runtime.version_tuple("v2.9.100"), app_runtime.version_tuple("2.9.42"))
        self.assertEqual(app_runtime.version_tuple("v2.9.42"), (2, 9, 42))

    def test_newer_release_is_reported_once_a_day(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return {"tag_name": "v2.9.50", "html_url": "https://example.com/release", "body": "notes"}
        with tempfile.TemporaryDirectory() as folder:
            found = app_runtime.check_for_update("2.9.42", Path(folder), fetch=fetch)
            self.assertEqual((found["version"], found["url"]), ("2.9.50", "https://example.com/release"))
            again = app_runtime.check_for_update("2.9.42", Path(folder), fetch=fetch)
            self.assertEqual(again["version"], "2.9.50"); self.assertEqual(len(calls), 1)  # cached for a day
            self.assertIsNone(app_runtime.check_for_update("2.9.50", Path(folder), fetch=fetch))  # after updating

    def test_same_or_older_version_and_simple_file_format(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(app_runtime.check_for_update("2.9.42", Path(folder), force=True, fetch=lambda url: {"tag_name": "v2.9.42"}))
            found = app_runtime.check_for_update("2.9.42", Path(folder), force=True, fetch=lambda url: {"version": "3.0.0", "url": "https://x/y"})
            self.assertEqual(found["url"], "https://x/y")

    def test_offline_or_broken_answer_never_raises(self):
        def offline(url): raise OSError("no internet")
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(app_runtime.check_for_update("2.9.42", Path(folder), fetch=offline))
            self.assertIsNone(app_runtime.check_for_update("2.9.42", Path(folder), force=True, fetch=lambda url: {"message": "Not Found"}))

    def test_address_can_be_changed_or_switched_off(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(app_runtime.update_url(Path(folder)), app_runtime.DEFAULT_UPDATE_URL)
            (Path(folder) / "update_url.txt").write_text("https://intranet/saber.json\n", encoding="utf-8")
            self.assertEqual(app_runtime.update_url(Path(folder)), "https://intranet/saber.json")
            (Path(folder) / "update_url.txt").write_text("off", encoding="utf-8")
            self.assertIsNone(app_runtime.check_for_update("2.9.42", Path(folder), force=True, fetch=lambda url: {"tag_name": "v9"}))


class PackagingTest(unittest.TestCase):
    def test_installer_and_program_have_the_same_version(self):
        installer = (HERE / "installer.iss").read_text(encoding="utf-8")
        self.assertEqual(re.search(r'#define MyAppVersion "([^"]+)"', installer).group(1), app_runtime.APP_VERSION)

    def test_user_guide_is_shipped_in_both_languages(self):
        guide = (HERE / "Assets" / "user_guide.html").read_text(encoding="utf-8")
        self.assertIn("Close the books", guide); self.assertIn("النسخ الاحتياطية", guide)
        workflow = (HERE / ".github" / "workflows" / "build-windows-installer.yml").read_text(encoding="utf-8")
        self.assertIn("Assets/user_guide.html;assets", workflow)

    def test_every_desktop_module_is_in_the_windows_build(self):
        workflow = (HERE / ".github" / "workflows" / "build-windows-installer.yml").read_text(encoding="utf-8")
        if "Get-ChildItem -Path . -Filter *.py" in workflow and "@modules" in workflow: return  # 2.9.46: modules added automatically
        for module in sorted(p.stem for p in HERE.glob("desktop_*.py")):
            self.assertIn(f"--hidden-import {module} ", workflow + " ", module)

    def test_screens_moved_in_2_9_42_are_still_part_of_the_window(self):
        try: import desktop
        except ImportError as exc: self.skipTest(f"tkinter not available: {exc}")
        for method, module in (("choose_purchase_pdf", "desktop_purchases"), ("choose_expense_pdf", "desktop_expenses"),
                               ("choose_asset_pdf", "desktop_asset_register"), ("build_import", "desktop_stage3"),
                               ("run_balance_report", "desktop_balance_reports"), ("build_manual", "desktop_brains"),
                               ("open_user_guide", "desktop"), ("start_update_check", "desktop")):
            self.assertEqual(getattr(desktop.SaberApp, method).__module__, module)


if __name__ == "__main__":
    unittest.main()
