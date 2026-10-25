"""HTTP coverage for company selection on current and comparative report routes."""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import server
from client import ApiClient
from company_manager import CompanyManager


class CompanyYearHttpIsolationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.addClassCleanup(cls.folder.cleanup)
        database = Path(cls.folder.name) / "master.db"
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=server.run_server, kwargs={"host": "127.0.0.1", "port": port,
            "database": str(database), "admin_password": "Synthetic-Admin-2026!"}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        cls.database_path = database
        cls.admin = ApiClient(cls.url)
        for _ in range(200):
            try:
                cls.admin.login("admin", "Synthetic-Admin-2026!"); break
            except Exception:
                time.sleep(0.05)
        else:
            raise RuntimeError("Synthetic test server did not start")
        cls.company_a = cls.admin.create_company({"name": "Synthetic Company A", "year": 2025})["id"]
        cls.company_b = cls.admin.create_company({"name": "Synthetic Company B", "year": 2026})["id"]
        cls.admin.save_user({"username": "limited-a", "password": "Synthetic-Limited-2026!",
            "role": "accountant", "language": "en", "companies": [cls.company_a]})
        # Place a distinctive synthetic marker in B so denied responses can be checked for leakage.
        manager = CompanyManager(database)
        b_db = manager.database(cls.company_b, 2026)
        b_db.save_party({"name": "PRIVATE COMPANY B SYNTHETIC MARKER", "kind": "customer", "currency": "USD"}, 1)
        for db_path in list(manager._cache): manager._cache.pop(db_path).release()
        cls.manager = manager

    @classmethod
    def tearDownClass(cls):
        try:
            for db in list(cls.manager._cache.values()): db.release()
        except Exception:
            pass
        cls.admin.close()

    def setUp(self):
        self.limited = ApiClient(self.url)
        self.limited.login("limited-a", "Synthetic-Limited-2026!")
        self.limited.select_company_year(self.company_a, 2025)

    def tearDown(self):
        self.limited.close()

    def test_mismatched_company_is_denied_on_current_and_multi_year_routes(self):
        routes = (
            ("GET", "/api/parties"),
            ("GET", "/api/dashboard/brief?date_from=2026-01-01&date_to=2026-12-31"),
            ("GET", "/api/dashboard/executive?date_from=2026-01-01&date_to=2026-12-31"),
            ("GET", "/api/management-pack?month_end=2026-12-31"),
            ("GET", "/api/analytic-study?date_from=2026-01-01&date_to=2026-12-31"),
            ("GET", "/api/year-end-check?year=2026"),
            ("GET", "/api/reports/accounts?options=%7B%22view_year%22%3A2026%7D"),
            ("GET", "/api/fiscal-year/journal?year=2026"),
            ("GET", "/api/fiscal-year/cash-flow?year=2026"),
            ("GET", "/api/fiscal-year/profit-loss?year=2026"),
            ("GET", "/api/fiscal-year/balance-sheet?year=2026"),
            ("GET", "/api/cash-flow/monthly?from_date=2026-01-01&to_date=2026-12-31"),
            ("GET", "/api/comparative-reports?from_date=2026-01-01&to_date=2026-12-31"),
            ("GET", "/api/reports/financial-config?year=2026"),
            ("GET", "/api/reports/business?report=financial_statements&options=%7B%22years%22%3A%5B2026%5D%7D"),
            ("GET", "/api/comparative-trial-balance?from_date=01-01-2026&to_date=31-12-2026"),
            ("GET", "/api/workbench/board?date_from=2026-01-01&date_to=2026-12-31"),
            ("POST", "/api/reports/financial-config"),
            ("POST", "/api/parties"),
        )
        for method, path in routes:
            with self.subTest(method=method, path=path):
                self.limited.company_id = self.company_b
                self.limited.fiscal_year = 2026
                body = {"name": "ATTEMPTED SYNTHETIC WRITE", "kind": "customer", "currency": "USD"} if method == "POST" else None
                with self.assertRaisesRegex(RuntimeError, "do not have access to this company") as denied:
                    self.limited.request(method, path, body)
                self.assertNotIn("PRIVATE COMPANY B SYNTHETIC MARKER", str(denied.exception))
                self.limited.company_id = self.company_a
                self.limited.fiscal_year = 2025
        b_manager = CompanyManager(self.database_path)
        b_db = b_manager.database(self.company_b, 2026)
        with b_db.connect() as connection:
            names = {row[0] for row in connection.execute("SELECT name FROM parties")}
        self.assertIn("PRIVATE COMPANY B SYNTHETIC MARKER", names)
        self.assertNotIn("ATTEMPTED SYNTHETIC WRITE", names)
        for db_path in list(b_manager._cache): b_manager._cache.pop(db_path).release()

    def test_missing_or_malformed_fiscal_year_does_not_fall_through_to_another_company(self):
        self.limited.company_id = self.company_a
        self.limited.fiscal_year = 2025
        self.limited.company_id = None
        try:
            fallback = self.limited.request("GET", "/api/parties")
            self.assertNotIn("PRIVATE COMPANY B SYNTHETIC MARKER", str(fallback))
        except RuntimeError as denied:
            self.assertNotIn("PRIVATE COMPANY B SYNTHETIC MARKER", str(denied))
        self.limited.company_id = "malformed-company-id"
        with self.assertRaisesRegex(RuntimeError, "do not have access to this company"):
            self.limited.request("GET", "/api/parties")
        self.limited.company_id = self.company_a
        # 2026 exists only in Company B; Company A's year selection must not fall through by year number.
        self.limited.fiscal_year = 2026
        with self.assertRaisesRegex(RuntimeError, "Fiscal year not found") as denied:
            self.limited.request("GET", "/api/parties")
        self.assertNotIn("PRIVATE COMPANY B SYNTHETIC MARKER", str(denied.exception))
        self.limited.fiscal_year = "not-a-year"
        with self.assertRaises(RuntimeError):
            self.limited.request("GET", "/api/parties")


if __name__ == "__main__":
    unittest.main()
