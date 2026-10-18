"""2.9.109: Accounts & Statements read another fiscal year of the company (read only) without switching."""
import tests_setup  # noqa: F401  the sample company of the tests
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from client import ApiClient
from company_manager import CompanyManager
from database import Database
from server import ApiHandler


class ViewYearTest(unittest.TestCase):
    def test_statement_of_another_year(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path = Path(folder) / "master.db"; db = Database(path); db.initialize("secret12345")
            manager = CompanyManager(path)
            handler = type("ViewYearHandler", (ApiHandler,), dict(db=db, master_db=db, company_manager=manager))
            http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=http.serve_forever, daemon=True).start()
            try:
                api = ApiClient(f"http://127.0.0.1:{http.server_port}"); api.login("admin", "secret12345")
                company = api.companies()[0]
                first_year = int(company["years"][0]["year"]); next_year = first_year + 1
                manager.create_year(company["id"], next_year, 1)
                old_books = manager.database(company["id"], first_year)
                old_books.import_invoice({"invoice_number": "OLD-1", "invoice_date": f"10-03-{first_year}", "party_name": "Old Client",
                                          "kind": "sale", "currency": "USD", "subtotal": 100, "vat": 11, "total": 111}, 1)
                api.select_company_year(company["id"], next_year)
                options = {"account_from": "4", "account_to": "4z", "date_from": f"01-01-{first_year}", "date_to": f"31-12-{first_year}",
                           "statement": True, "detailed": True, "posting_status": "all", "currencies": []}
                text = lambda result: repr(result)
                self.assertNotIn("OLD-1", text(api.account_report(dict(options))))               # the current year does not have it
                self.assertIn("OLD-1", text(api.account_report(dict(options, view_year=str(first_year)))))  # the other year does
                with self.assertRaisesRegex(RuntimeError, "Historical data for FY 1999 unavailable"):
                    api.account_report(dict(options, view_year="1999"))
            finally:
                http.shutdown(); http.server_close()
                for cached in list(manager._cache): manager._cache.pop(cached).release()
                db.release()


if __name__ == "__main__":
    unittest.main()
