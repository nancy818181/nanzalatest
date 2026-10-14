"""2.9.114: the program files are named Nanza (NanzaAccounting.exe, NanzaAccountingBackup.exe, NanzaAccountingSetup.exe);
an installed copy updates in place and its data folder is untouched."""
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class NanzaProgramFileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installer = (HERE / "installer.iss").read_text(encoding="utf-8")
        cls.workflow = (HERE / ".github" / "workflows" / "build-windows-installer.yml").read_text(encoding="utf-8")

    def test_build_names_the_programs_nanza(self):
        self.assertIn("--name NanzaAccounting run_desktop.py", self.workflow)
        self.assertIn("--name NanzaAccountingBackup backup_service.py", self.workflow)
        self.assertIn("dist\\NanzaAccounting\\NanzaAccounting.exe", self.workflow)
        self.assertIn("installer-output/NanzaAccountingSetup.exe", self.workflow)
        self.assertNotIn("--name SaberAccounting", self.workflow)

    def test_programs_carry_nanza_file_details(self):
        self.assertIn("--version-file version_main.txt", self.workflow)
        self.assertIn("--version-file version_backup.txt", self.workflow)
        self.assertIn("StringStruct('ProductName', 'Nanza Accounting')", self.workflow)

    def test_installer_uses_new_files_and_removes_old_ones(self):
        self.assertIn("OutputBaseFilename=NanzaAccountingSetup", self.installer)
        self.assertIn('Source: "dist\\NanzaAccounting\\*"', self.installer)
        self.assertIn('Filename: "{app}\\NanzaAccounting.exe"', self.installer)
        self.assertNotIn('Filename: "{app}\\SaberAccounting.exe"', self.installer)
        for old in ('{app}\\SaberAccounting.exe', '{app}\\SaberAccountingBackup.exe', '{commonstartup}\\Saber Accounting Backups.lnk'):
            self.assertIn(f'Type: files; Name: "{old}"', self.installer)
        for name in ("NanzaAccounting.exe", "NanzaAccountingBackup.exe", "SaberAccounting.exe", "SaberAccountingBackup.exe"):
            self.assertIn(f"'/F /IM {name}'", self.installer)

    def test_installed_copies_update_in_place_and_keep_their_data(self):
        self.assertIn("AppId={{4C848D44-EF69-47C0-86F1-5A5AA3C34E8D}", self.installer)
        import os, tempfile, app_runtime
        from unittest import mock
        with tempfile.TemporaryDirectory() as home, mock.patch.dict("os.environ", {}, clear=False), \
             mock.patch.object(app_runtime.Path, "home", return_value=Path(home)):
            os.environ.pop("SABER_DATA_DIR", None)
            self.assertEqual(app_runtime.data_dir(), Path(home) / "NanzaAccounting")   # new computer: no Saber anywhere
            (Path(home) / "SaberAccounting").mkdir()
            self.assertEqual(app_runtime.data_dir(), Path(home) / "SaberAccounting")   # existing copy: data stays where it is
            (Path(home) / "NanzaAccounting").mkdir()
            self.assertEqual(app_runtime.data_dir(), Path(home) / "SaberAccounting")   # never switches away from existing data


class NanzaWordingTest(unittest.TestCase):
    def test_the_user_never_sees_saber_accounting(self):
        import re
        for path in HERE.glob("*.py"):
            if path.name.startswith("test_"): continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "Saber Accounting" not in line and "Saber_Accounting" not in line: continue
                allowed = ('"application"' in line or "Accounting Backups" in line or line.lstrip().startswith("#"))
                self.assertTrue(allowed, f"{path.name}:{number}: {line.strip()}")
        guide = (HERE / "Assets" / "user_guide.html").read_text(encoding="utf-8")
        self.assertNotIn("Saber Accounting", guide); self.assertNotIn("SaberAccountingSetup", guide)
        self.assertNotRegex(guide, re.compile(r"\bSaber\b(?! for Audit)"))

    def test_data_service_handshake_is_unchanged(self):
        # old and new copies (office server / desktop) must still recognise each other
        self.assertIn('"application": "Saber Accounting"', (HERE / "server.py").read_text(encoding="utf-8"))
        self.assertIn('== "Saber Accounting"', (HERE / "run_desktop.py").read_text(encoding="utf-8"))


class NanzaFileNamesTest(unittest.TestCase):
    def test_new_folder_gets_nanza_files_old_folder_keeps_saber_files(self):
        import tempfile, sqlite3, app_runtime
        from contextlib import closing
        with tempfile.TemporaryDirectory() as root:
            new = Path(root) / "NanzaAccounting"; new.mkdir()
            self.assertEqual(app_runtime.main_database_path(new).name, "nanza_accounting.db")
            self.assertEqual(app_runtime.log_file(new).name, "nanza.log")
            self.assertEqual(app_runtime.SingleInstance(new).lock_path.name, ".nanza.lock")
            old = Path(root) / "SaberAccounting"; (old / "logs").mkdir(parents=True)
            with closing(sqlite3.connect(old / "saber_accounting.db")) as db: db.execute("CREATE TABLE t(x)"); db.commit()
            (old / "logs" / "saber.log").write_text("x")
            self.assertEqual(app_runtime.main_database_path(old).name, "saber_accounting.db")   # never renamed
            self.assertEqual(app_runtime.log_file(old).name, "saber.log")
            self.assertEqual(app_runtime.SingleInstance(old).lock_path.name, ".saber.lock")

    def test_backups_of_the_nanza_main_file_are_listed(self):
        import tempfile, database
        with tempfile.TemporaryDirectory() as root:
            db = database.Database(str(Path(root) / "nanza_accounting.db")); db.initialize("Admin-Pass-2026!")
            made = db.backup()
            self.assertTrue(Path(made).name.startswith("nanza_accounting_"), made)
            self.assertIn(Path(made).name, [b["name"] for b in db.list_backups()])


if __name__ == "__main__":
    unittest.main()
