"""2.9.52: warehouse multi-select, earlier fiscal years in reports and projections, a second backup copy,
the 'delete / cancel' permission, optional code signing of the installer."""
import tests_setup  # noqa: F401  2.9.74: the sample company of the tests (a new installation has none)
import os
import tempfile
import threading
import unittest
from pathlib import Path

import inventory
import projection_model as pm
from database import Database

HERE = Path(__file__).resolve().parent


class _Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "c.db"); self.db.initialize("secret")
        self.user = self.db.user_for_token(self.db.login("admin", "secret")["token"])["id"]

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        self.temp.cleanup()


class WarehouseChoiceTest(_Base):
    def test_any_combination_of_warehouses(self):
        for code in ("W2", "W3"): inventory.save_warehouse(self.db, {"code": code, "name": code}, self.user)
        ids = {w["code"]: w["id"] for w in inventory.list_warehouses(self.db)}
        item = inventory.save_item(self.db, {"name": "Panel", "unit": "sheet"}, self.user)
        for code, qty in (("MAIN", 1), ("W2", 2), ("W3", 4)):
            inventory.save_document(self.db, {"doc_type": "receipt", "doc_date": "2026-03-01", "warehouse_id": code}, [{"sku": item["sku"], "quantity": qty, "unit_cost": 10}], self.user)
        def qty(choice):
            rows = inventory.build_report(self.db, "valuation", {"date_to": "31-03-2026", "warehouse_id": choice})["sections"][0]["rows"]
            return next(r[4] for r in rows if r[0] == item["sku"])
        self.assertEqual(qty(None), 7); self.assertEqual(qty(ids["W2"]), 2); self.assertEqual(qty([ids["MAIN"], ids["W3"]]), 5)
        moves = inventory.build_report(self.db, "movements", {"date_from": "01-01-2026", "date_to": "31-03-2026", "warehouse_id": [ids["W2"], ids["W3"]]})["sections"][0]["rows"]
        self.assertEqual(sorted(r[5] for r in moves), ["W2", "W3"])
        heading = inventory.build_report(self.db, "valuation", {"date_to": "31-03-2026", "warehouse_id": [ids["W2"], ids["W3"]]})["sections"][0]["heading"]
        self.assertIn("W2, W3", heading)
        for report in ("health", "ageing", "analysis3d", "brands", "stock_card"):
            options = {"date_from": "01-01-2026", "date_to": "31-03-2026", "warehouse_id": [ids["W2"], ids["W3"]], "item_id": item["id"]}
            self.assertTrue(inventory.build_report(self.db, report, options)["sections"], report)


class EarlierYearsTest(unittest.TestCase):
    def test_comparative_reads_last_years_file_and_projection_history(self):
        with tempfile.TemporaryDirectory() as folder:
            dbs = {}
            for year in (2025, 2026):
                db = Database(Path(folder) / f"c_{year}.db"); db.initialize("secret")
                user = db.user_for_token(db.login("admin", "secret")["token"])["id"]
                db.create_manual_invoice({"invoice_number": f"S{year}", "invoice_date": f"10-03-{year}", "party_name": "Client", "kind": "sales", "currency": "USD",
                                          "status": "posted", "supplier_account": "411100001", "vat_account": "4427", "expense_account": "701100001"},
                                         [{"description": "x", "quantity": 1, "unit_price": 1000 if year == 2025 else 1500, "vat_rate": 0}], user)
                dbs[year] = db
            result = dbs[2026].comparative_reports("2026-01-01", "2026-12-31", "USD", prior_db=dbs[2025])
            row = next(r for r in result["items"] if r["code"] == "701100001")
            self.assertEqual((row["current"], row["prior"], row["variance"]), (1500, 1000, 500))
            history = [("Actual 2025", pm.statement_from_rows(dbs[2025].profit_and_loss("2025-01-01", "2025-12-31", "USD")))]
            base = pm.statement_from_rows(dbs[2026].profit_and_loss("2026-01-01", "2026-12-31", "USD"))
            self.assertEqual(pm.historical_growth(history, base), 50.0)
            accounts = pm.collect_base({3: dbs[2026].profit_and_loss("2026-03-01", "2026-03-31", "USD")}, 12)
            _p, sections = pm.report_sections(accounts, pm.default_assumptions(2026, 2), {"cash": 0, "receivables": 0, "payables": 0}, "Actual 2026", "USD", history=history)
            income = next(s for s in sections if s["heading"].startswith("Projected income statement"))
            self.assertEqual(income["headers"][:3], ["Item", "Actual 2025", "Actual 2026"])
            for db in dbs.values(): db.release()

    def test_server_reads_another_fiscal_year(self):
        import app_runtime, server
        from client import ApiClient
        saved = {name: getattr(server.ApiHandler, name) for name in ("db", "master_db", "company_manager", "local_key")}
        folder = tempfile.TemporaryDirectory(); ready = threading.Event(); port = {}
        threading.Thread(target=server.run_server, daemon=True, kwargs=dict(host="127.0.0.1", port=0, database=str(Path(folder.name) / "saber_accounting.db"),
            admin_password="StrongPass123", local_key="k", on_ready=lambda p: (port.setdefault("p", p), ready.set()))).start()
        self.assertTrue(ready.wait(30))
        old = (app_runtime.LOCAL_URL, app_runtime.LOCAL_KEY)
        try:
            url = f"http://127.0.0.1:{port['p']}"; app_runtime.LOCAL_URL, app_runtime.LOCAL_KEY = url, "k"
            client = ApiClient(url); client.login("admin", "StrongPass123")
            company = client.companies()[0]; year = company["years"][0]["year"]; client.select_company_year(company["id"], year)
            self.assertEqual(client.fiscal_year_profit_loss(year, f"{year}-01-01", f"{year}-12-31", "USD"), [])
            self.assertIsInstance(client.fiscal_year_balance_sheet(int(year) - 1, f"{int(year) - 1}-12-31", "USD"), list)   # no file for that year: this one
            # delete permission
            client.save_user({"username": "clerk", "password": "Clerk12345", "role": "accountant", "language": "en", "permissions": {"payroll": True, "vat": True, "delete": False}})
            clerk = ApiClient(url); clerk.login("clerk", "Clerk12345"); clerk.select_company_year(company["id"], year)
            invoice_id = clerk.create_manual_invoice({"invoice_number": "D1", "invoice_date": f"10-03-{year}", "party_name": "Client", "kind": "sales", "currency": "USD", "status": "posted",
                                                      "supplier_account": "411100001", "vat_account": "4427", "expense_account": "701100001"},
                                                     [{"description": "x", "quantity": 1, "unit_price": 10, "vat_rate": 0}])["invoice_id"]
            # an accountant can save in the company file (2.9.52: the user row is copied there)
            with self.assertRaises(Exception) as refused: clerk.delete_invoice(invoice_id)
            self.assertIn("permission to delete", str(refused.exception))
            client.delete_invoice(invoice_id)   # the administrator can
        finally:
            app_runtime.LOCAL_URL, app_runtime.LOCAL_KEY = old
            for name, value in saved.items(): setattr(server.ApiHandler, name, value)
            try: folder.cleanup()
            except OSError: pass


class SecondCopyTest(_Base):
    def test_each_backup_is_copied_and_old_automatic_copies_pruned(self):
        import backup_copy
        old = os.environ.get("SABER_DATA_DIR"); os.environ["SABER_DATA_DIR"] = str(Path(self.temp.name) / "data")
        try:
            self.assertIsNone(backup_copy.copy_backup(__file__))                              # nothing set: nothing copied
            second = Path(self.temp.name) / "OneDrive" / "Saber"
            backup_copy.save_settings(str(second), 2)
            self.db.backup_folder = str(Path(self.temp.name) / "backups" / "ACME" / "2026")
            made = [Path(self.db.backup("auto")) for _ in range(3)] + [Path(self.db.backup())]
            copies = sorted(p.name for p in (second / "ACME" / "2026").glob("*.db"))
            self.assertEqual(len(copies), 3)                                                   # 2 newest automatic + the manual one
            self.assertIn(made[-1].name, copies); self.assertNotIn(made[0].name, copies)
            status = backup_copy.settings(); self.assertIsNone(status["last_error"]); self.assertIn(made[-1].name, status["last_ok"])
            with self.assertRaises(ValueError): backup_copy.save_settings(__file__)            # a file is not a folder
        finally:
            if old is None: os.environ.pop("SABER_DATA_DIR", None)
            else: os.environ["SABER_DATA_DIR"] = old

    def test_a_failed_copy_never_fails_the_backup(self):
        import backup_copy
        from unittest.mock import patch
        old = os.environ.get("SABER_DATA_DIR"); os.environ["SABER_DATA_DIR"] = str(Path(self.temp.name) / "data")
        try:
            backup_copy.save_settings(str(Path(self.temp.name) / "copy"))
            with patch("backup_copy.shutil.copy2", side_effect=OSError("disk full")):
                self.assertTrue(Path(self.db.backup()).exists())
            self.assertIn("disk full", backup_copy.settings()["last_error"])
        finally:
            if old is None: os.environ.pop("SABER_DATA_DIR", None)
            else: os.environ["SABER_DATA_DIR"] = old


class PermissionAndSigningTest(_Base):
    def test_delete_permission_defaults(self):
        import database
        self.assertIn("delete", database.PERMISSION_MODULES)
        self.assertEqual(database.parse_permissions("{}")["delete"], True)     # existing users keep what they could do
        user = self.db.save_user({"username": "x", "password": "Secret12", "role": "accountant", "permissions": {"delete": False}}, self.user)
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username='x'").fetchone()
        self.assertFalse(self.db.user_can(row, "delete")); self.assertTrue(self.db.user_can(row, "vat"))
        self.assertIsNotNone(user)

    def test_signing_is_optional_in_the_build(self):
        workflow = (HERE / ".github" / "workflows" / "build-windows-installer.yml").read_text(encoding="utf-8")
        self.assertIn("secrets.SIGN_CERT_PFX_BASE64", workflow); self.assertEqual(workflow.count("if: env.SIGN_CERT != ''"), 2)


if __name__ == "__main__":
    unittest.main()
