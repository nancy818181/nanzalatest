"""2.9.41: private data service (free port + secret key), one copy open, error log, main file rename, screen split."""
import tests_setup  # noqa: F401  2.9.74: the sample company of the tests (a new installation has none)
import json
import logging
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app_runtime
import server
from client import ApiClient


def _get(url, key=None):
    headers = {app_runtime.KEY_HEADER: key} if key else {}
    with urlopen(Request(url, headers=headers), timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


class PrivateDataServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = {name: getattr(server.ApiHandler, name) for name in ("db", "master_db", "company_manager", "local_key")}
        cls.saved_runtime = (app_runtime.LOCAL_URL, app_runtime.LOCAL_KEY)
        cls.folder = tempfile.TemporaryDirectory()
        cls.key = "test-secret-key-1234567890"
        ready = threading.Event(); cls.ports = []

        def on_ready(port): cls.ports.append(port); ready.set()

        threading.Thread(target=server.run_server, daemon=True, kwargs=dict(
            host="127.0.0.1", port=0, database=str(Path(cls.folder.name) / "saber_accounting.db"),
            admin_password="StrongPass123", local_key=cls.key, on_ready=on_ready)).start()
        assert ready.wait(30), "data service did not start"
        cls.url = f"http://127.0.0.1:{cls.ports[0]}"

    @classmethod
    def tearDownClass(cls):
        for name, value in cls.saved.items(): setattr(server.ApiHandler, name, value)
        app_runtime.LOCAL_URL, app_runtime.LOCAL_KEY = cls.saved_runtime
        # The service thread is a daemon; its files are left for the OS to clean up on Windows.
        try: cls.folder.cleanup()
        except OSError: pass

    def test_free_port_is_chosen(self):
        self.assertNotEqual(self.ports[0], 8765)
        self.assertGreater(self.ports[0], 0)

    def test_requests_without_the_key_are_refused(self):
        for key in (None, "wrong-key"):
            with self.assertRaises(HTTPError) as caught: _get(self.url + "/health", key)
            self.assertEqual(caught.exception.code, 403)
        with self.assertRaises(HTTPError) as caught: _get(self.url + "/api/me", "wrong-key")
        self.assertEqual(caught.exception.code, 403)

    def test_requests_with_the_key_work(self):
        status, body = _get(self.url + "/health", self.key)
        self.assertEqual((status, body["application"]), (200, "Saber Accounting"))

    def test_client_sends_the_key_only_to_the_private_service(self):
        app_runtime.LOCAL_URL, app_runtime.LOCAL_KEY = self.url, self.key
        client = ApiClient(self.url)
        self.assertTrue(client.login("admin", "StrongPass123")["token"])
        self.assertEqual(client._local_key(), self.key)
        self.assertIsNone(ApiClient("https://server.example.com:8443")._local_key())
        self.assertIsNone(ApiClient(self.url.replace("127.0.0.1", "localhost"))._local_key())


class SingleInstanceTest(unittest.TestCase):
    def test_second_copy_cannot_start_until_the_first_closes(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = app_runtime.SingleInstance(Path(folder)), app_runtime.SingleInstance(Path(folder))
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()


class ErrorLogTest(unittest.TestCase):
    def test_errors_are_written_to_the_log_file(self):
        root = logging.getLogger(); handlers = list(root.handlers); level = root.level
        hooks = (sys.excepthook, threading.excepthook)
        with tempfile.TemporaryDirectory() as folder:
            try:
                path = app_runtime.setup_logging(Path(folder))
                try: raise ValueError("sample failure 2.9.41")
                except ValueError: logging.getLogger("saber.test").exception("Something failed")
                for handler in root.handlers: handler.flush()
                text = path.read_text(encoding="utf-8")
                self.assertIn("Something failed", text); self.assertIn("sample failure 2.9.41", text)
                self.assertIn("Traceback", text)
            finally:
                for handler in root.handlers:
                    if handler not in handlers: handler.close()
                root.handlers[:] = handlers; root.setLevel(level)
                sys.excepthook, threading.excepthook = hooks


class MainFileRenameTest(unittest.TestCase):
    def _old_file(self, folder, rows=3):
        old = folder / app_runtime.OLD_MAIN_DATABASE_NAME
        with closing(sqlite3.connect(old)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE invoices(id INTEGER PRIMARY KEY, amount TEXT)")
            db.executemany("INSERT INTO invoices(amount) VALUES(?)", [(str(i * 100),) for i in range(rows)])
            db.commit()
        (folder / "companies").mkdir()
        (folder / "companies" / "companies.json").write_text(json.dumps({"companies": [
            {"id": "c1", "name": "Test", "years": [{"year": 2024, "database": str(old.resolve()), "status": "open"},
                                                   {"year": 2025, "database": str(folder / "companies" / "Test" / "Test_2025.db"), "status": "open"}]}]}), encoding="utf-8")
        return old

    def test_old_file_is_copied_checked_and_the_company_list_follows(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name); old = self._old_file(folder)
            path = app_runtime.main_database_path(folder)
            self.assertEqual(path.name, "saber_accounting.db")
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 3)
            years = json.loads((folder / "companies" / "companies.json").read_text(encoding="utf-8"))["companies"][0]["years"]
            self.assertEqual(Path(years[0]["database"]).resolve(), path.resolve())
            self.assertTrue(years[1]["database"].endswith("Test_2025.db"))  # other years untouched
            self.assertFalse(old.exists())
            self.assertTrue((folder / "saber_accounting_v0_7.db.before-2.9.41").exists())
            self.assertTrue((folder / "companies" / "companies.json.before-2.9.41").exists())
            self.assertEqual(app_runtime.main_database_path(folder), path)  # second start: nothing more to do

    def test_interrupted_rename_is_finished_next_time(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name); old = self._old_file(folder)
            new = folder / "saber_accounting.db"; new.write_bytes(old.read_bytes())
            path = app_runtime.main_database_path(folder)
            self.assertEqual(path, new)
            years = json.loads((folder / "companies" / "companies.json").read_text(encoding="utf-8"))["companies"][0]["years"]
            self.assertEqual(Path(years[0]["database"]).resolve(), new.resolve())

    def test_damaged_old_file_is_left_alone_and_still_used(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name); old = folder / app_runtime.OLD_MAIN_DATABASE_NAME
            old.write_bytes(b"this is not a database" * 100)
            self.assertEqual(app_runtime.main_database_path(folder), old)
            self.assertTrue(old.exists())
            self.assertFalse((folder / "saber_accounting.db").exists())

    def test_new_installation_uses_the_new_name(self):
        with tempfile.TemporaryDirectory() as name:
            self.assertEqual(app_runtime.main_database_path(Path(name)).name, "saber_accounting.db")


class ScreenSplitTest(unittest.TestCase):
    def test_screens_moved_out_of_desktop_are_still_part_of_the_window(self):
        try: import desktop
        except ImportError as exc: self.skipTest(f"tkinter not available: {exc}")
        for method, module in (("build_invoices", "desktop_invoices"), ("build_parties", "desktop_parties"),
                               ("build_payroll", "desktop_payroll"), ("build_journal", "desktop_reports"),
                               ("build_settings", "desktop_settings"), ("open_log_folder", "desktop_settings")):
            self.assertEqual(getattr(desktop.SaberApp, method).__module__, module)
        self.assertTrue(callable(desktop.row_matches_search))  # still importable from desktop


if __name__ == "__main__":
    unittest.main()
