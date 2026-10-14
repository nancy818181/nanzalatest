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
        import app_runtime
        from unittest import mock
        with mock.patch.dict("os.environ", {}, clear=False):
            __import__("os").environ.pop("SABER_DATA_DIR", None)
            self.assertEqual(app_runtime.data_dir().name, "SaberAccounting")  # company data stays where it is


if __name__ == "__main__":
    unittest.main()
