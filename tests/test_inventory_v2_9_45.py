"""2.9.45: negative stock alert (confirm and continue), returns vs credit / debit notes, brand, project / branch
filters, what the inventory screens show, tidier reports."""
import tests_setup  # noqa: F401  2.9.74: the sample company of the tests (a new installation has none)
import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path

import inventory
from database import Database
from report_export import tidy_sections


class _Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "stock.db"); self.db.initialize("secret")
        self.user = self.db.user_for_token(self.db.login("admin", "secret")["token"])["id"]
        self.item = inventory.save_item(self.db, {"name": "HPL Sheet", "unit": "sheet", "brand": "Fundermax", "sales_price": "120"}, self.user)
        inventory.save_document(self.db, {"doc_type": "receipt", "doc_date": "2026-03-01", "warehouse_id": "MAIN"},
                                [{"sku": self.item["sku"], "quantity": 5, "unit_cost": 80}], self.user)

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        self.temp.cleanup()

    def qty(self):
        return next(i for i in inventory.list_items(self.db) if i["id"] == self.item["id"])["quantity"]

    def sale(self, quantity, subtype="invoice", number=None, **extra):
        invoice = {"invoice_number": number or f"S-{subtype}-{quantity}", "invoice_date": "2026-03-05", "party_name": "Customer", "kind": "sales",
                   "currency": "USD", "status": "posted", "source_file": "Sales Invoice", "supplier_account": "411100001", "vat_account": "4427",
                   "expense_account": "711000001", "doc_subtype": subtype}
        invoice.update(extra)
        return self.db.create_manual_invoice(invoice, [{"description": "HPL", "item_code": self.item["sku"], "quantity": quantity, "unit_price": 120, "vat_rate": 0}], self.user)


class NegativeStockTest(_Base):
    def test_shortage_asks_first_then_saves_when_confirmed(self):
        issue = {"doc_type": "issue", "doc_date": "2026-03-02", "warehouse_id": "MAIN"}
        with self.assertRaises(inventory.NegativeStock) as caught:
            inventory.save_document(self.db, issue, [{"sku": self.item["sku"], "quantity": 8}], self.user)
        self.assertTrue(str(caught.exception).startswith(inventory.NEGATIVE_MARKER))
        self.assertIn("available 5.000, requested 8.000", str(caught.exception))
        self.assertEqual(self.qty(), 5)
        with inventory.negative_stock_allowed():
            inventory.save_document(self.db, issue, [{"sku": self.item["sku"], "quantity": 8}], self.user)
        self.assertEqual(self.qty(), -3)
        # Later unrelated work is not blocked by the confirmed shortage; a receipt brings stock back.
        inventory.save_document(self.db, {"doc_type": "receipt", "doc_date": "2026-03-10", "warehouse_id": "MAIN"},
                                [{"sku": self.item["sku"], "quantity": 10, "unit_cost": 90}], self.user)
        self.assertEqual(self.qty(), 7)

    def test_sale_invoice_shortage_alert_and_confirm(self):
        with self.assertRaises(inventory.NegativeStock): self.sale(9)
        self.assertFalse([i for i in self.db.list_invoices() if i["invoice_number"] == "S-invoice-9"])  # nothing half-saved
        with inventory.negative_stock_allowed(): self.sale(9)
        self.assertEqual(self.qty(), -4)

    def test_fifo_negative_stock_values_and_settles(self):
        inventory.save_settings(self.db, {"currency": "USD", "method": "fifo"}, self.user)
        with inventory.negative_stock_allowed():
            inventory.save_document(self.db, {"doc_type": "issue", "doc_date": "2026-03-02", "warehouse_id": "MAIN"}, [{"sku": self.item["sku"], "quantity": 7}], self.user)
        inventory.save_document(self.db, {"doc_type": "receipt", "doc_date": "2026-03-10", "warehouse_id": "MAIN"},
                                [{"sku": self.item["sku"], "quantity": 4, "unit_cost": 100}], self.user)
        state = inventory.run_costing(self.db)[self.item["id"]]
        self.assertEqual(state["qty"], 2)
        self.assertEqual(state["warehouse_value"][1], Decimal("200"))  # 2 owed units settled from the new receipt; 2 left at 100

    def test_api_asks_through_the_client_and_resends(self):
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
            company = client.companies()[0]; client.select_company_year(company["id"], company["years"][0]["year"])
            sku = client.save_inventory_item({"name": "Panel", "unit": "unit"})["sku"]
            asked = []
            client.confirm_negative_stock = lambda text: asked.append(text) or False
            with self.assertRaises(RuntimeError) as refused:
                client.save_stock_document({"doc_type": "issue", "doc_date": "05-03-2026", "warehouse_id": "MAIN"}, [{"sku": sku, "quantity": 2}])
            self.assertEqual(len(asked), 1); self.assertIn("Not enough stock", asked[0]); self.assertIn("Not saved", str(refused.exception))
            client.confirm_negative_stock = lambda text: True
            client.save_stock_document({"doc_type": "issue", "doc_date": "05-03-2026", "warehouse_id": "MAIN"}, [{"sku": sku, "quantity": 2}])
            self.assertEqual(next(i for i in client.inventory_items() if i["sku"] == sku)["quantity"], -2)
        finally:
            app_runtime.LOCAL_URL, app_runtime.LOCAL_KEY = old
            for name, value in saved.items(): setattr(server.ApiHandler, name, value)
            try: folder.cleanup()
            except OSError: pass


class ReturnsAndNotesTest(_Base):
    def test_return_brings_goods_back_but_credit_and_debit_notes_do_not(self):
        source = self.sale(2, number="S-1")
        self.assertEqual(self.qty(), 3)
        self.sale(1, "credit_note", number="CN-1"); self.assertEqual(self.qty(), 3)   # discount: no stock
        self.sale(1, "debit_note", number="DN-1"); self.assertEqual(self.qty(), 3)    # price adjustment: no stock
        item_id = self.db.invoice_detail(source)["items"][0]["id"]
        created = self.db.create_invoice_return(source, [{"item_id": item_id, "quantity": "1"}], "2026-03-06", self.user, "req-1")
        self.assertEqual(self.qty(), 4)                                               # return: goods back
        rows = {r["invoice_number"]: r for r in self.db.list_invoices()}
        self.assertEqual((rows["CN-1"]["is_return"], rows["DN-1"]["is_return"]), (0, 0))
        self.assertEqual(next(r for r in rows.values() if r["id"] == (created["id"] if isinstance(created, dict) else created))["is_return"], 1)


class BrandAndFiltersTest(_Base):
    def test_brand_saved_listed_filtered_and_reported(self):
        other = inventory.save_item(self.db, {"name": "Aluminium", "unit": "m", "brand": "Alucobond"}, self.user)
        inventory.save_document(self.db, {"doc_type": "receipt", "doc_date": "2026-03-01", "warehouse_id": "MAIN"}, [{"sku": other["sku"], "quantity": 3, "unit_cost": 10}], self.user)
        self.assertEqual(inventory.brands(self.db), ["Alucobond", "Fundermax"])
        valuation = inventory.build_report(self.db, "valuation", {"date_to": "31-03-2026", "brand": "fundermax"})
        codes = [row[0] for row in valuation["sections"][0]["rows"]]
        self.assertIn(self.item["sku"], codes); self.assertNotIn(other["sku"], codes)
        by_brand = inventory.build_report(self.db, "brands", {"date_to": "31-03-2026"})["sections"][0]["rows"]
        self.assertEqual([(r[0], r[1], r[4]) for r in by_brand[:-1]], [("Alucobond", "MAIN", Decimal("30.00")), ("Fundermax", "MAIN", Decimal("400.00"))])

    def test_project_and_branch_on_stock_documents_filter_movements(self):
        with self.db.connect() as db:
            project = db.execute("INSERT INTO projects(code,name,created_at) VALUES('P1','Tower',?)", ("2026-01-01",)).lastrowid
            db.execute("INSERT OR IGNORE INTO branches(name) VALUES('Riyadh')")
        doc = inventory.save_document(self.db, {"doc_type": "issue", "doc_date": "2026-03-03", "warehouse_id": "MAIN", "project_id": "P1", "branch_id": "Riyadh"},
                                      [{"sku": self.item["sku"], "quantity": 1}], self.user)
        self.assertEqual((doc["project_code"], doc["branch_name"]), ("P1", "Riyadh"))
        rows = inventory.build_report(self.db, "movements", {"date_from": "01-01-2026", "date_to": "31-03-2026", "project_id": str(project)})["sections"][0]["rows"]
        self.assertEqual([r[1] for r in rows], [doc["number"]])
        with self.assertRaises(ValueError): inventory.save_document(self.db, {"doc_type": "issue", "doc_date": "2026-03-03", "warehouse_id": "MAIN", "project_id": "NOPE"},
                                                                    [{"sku": self.item["sku"], "quantity": 1}], self.user)

    def test_screens_show_only_the_ticked_fields(self):
        defaults = inventory.settings(self.db)
        self.assertEqual({k: defaults[f"show_{k}"] for k in inventory.SHOW_KEYS}, {"brand": True, "warehouse": True, "project": True, "branch": True})
        inventory.save_settings(self.db, {"currency": "USD", "method": "average", "show_brand": False, "show_project": False}, self.user)
        values = inventory.settings(self.db)
        self.assertEqual((values["show_brand"], values["show_project"], values["show_warehouse"], values["show_branch"]), (False, False, True, True))


class TidyReportsTest(unittest.TestCase):
    def test_empty_and_zero_columns_are_left_out_except_fixed_layouts(self):
        section = {"heading": "x", "compact": True, "headers": ["Code", "Name", "Salary", "Bonus", "Note"], "rows": [["1", "A", 10, 0, ""], ["TOTAL", "", 10, Decimal(0), None]], "total_rows": [1]}
        tidy = tidy_sections([section])[0]
        self.assertEqual(tidy["headers"], ["Code", "Name", "Salary"]); self.assertEqual(tidy["rows"], [["1", "A", 10], ["TOTAL", "", 10]])
        self.assertEqual(tidy["hidden_columns"], ["Bonus", "Note"])
        self.assertEqual(tidy_sections([{**section, "fixed": True}])[0]["headers"], section["headers"])
        plain = {k: v for k, v in section.items() if k != "compact"}  # financial and other reports keep every column
        self.assertEqual(tidy_sections([plain])[0]["headers"], section["headers"])


if __name__ == "__main__":
    unittest.main()
