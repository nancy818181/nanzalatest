"""2.9.90 (owner): VAT read wrong from the amount in words; Purchases Auto Calculate and partial PDFs; accounts of new
items (cost / sales) and sales posted to the item's sales account; a new company does not copy other companies' accounts."""
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import inventory
import pdf_import
from database import Database


class _Var:
    def __init__(self, value=""): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class PdfTotalsTest(unittest.TestCase):
    def test_amount_in_words_is_not_the_vat(self):
        text = ("DIWAN GROUP C.S.\nInvoice # : SJ20251714\n02/09/2025\nCurrency:USD\n"
                "V.A.T. (LBP)   203,080,199     Eighty One Thousand Two Hundred Seventeen  and  94/100 USD\n"
                "78,948.89    المجموع قبل الضریبة\n2,269.05        V.A.T. 11%\n81,217.94      $ المجموع الصافي")
        parsed = pdf_import._parse_invoice_text("diwan1.pdf", text)
        self.assertEqual((parsed["subtotal"], parsed["vat"], parsed["total"]), (78948.89, 2269.05, 81217.94))  # VAT was 100 (from 94/100)


class PurchaseScreenTest(unittest.TestCase):
    def screen(self, rows, taxable="", rate="11"):
        from desktop_purchases import PurchasesMixin
        form = {"items_sheet": types.SimpleNamespace(ordered=lambda: rows), "vars": {"taxable": _Var(taxable), "exempt": _Var(""), "vat": _Var(""), "rate": _Var(rate)},
                "discount_mode": "percent", "discount_percent": _Var("0"), "discount_amount": _Var("0")}
        screen = types.SimpleNamespace(purchase_form=form, purchase_amounts_changed=lambda key: None)
        screen.purchase_items_changed = lambda: PurchasesMixin.purchase_items_changed(screen)
        screen.purchase_discount = lambda taxable: PurchasesMixin.purchase_discount(screen, taxable)
        return PurchasesMixin, screen

    def test_auto_calculate(self):
        mixin, screen = self.screen([{"name": "Spices", "quantity": 10, "unit_cost": 5, "total": 50.0, "vat_flag": "Yes"},
                                     {"name": "Rice", "quantity": 20, "unit_cost": 2, "total": 40.0, "vat_flag": "No"}])
        self.assertEqual(mixin.purchase_auto_calculate(screen), 5.5)  # 11% of the 50 taxable only
        self.assertEqual((screen.purchase_form["vars"]["taxable"].get(), screen.purchase_form["vars"]["exempt"].get()), ("50.00", "40.00"))
        mixin, screen = self.screen([], taxable="1000")
        self.assertEqual(mixin.purchase_auto_calculate(screen), 110.0)

    def test_partial_pdf_keeps_the_invoice_amounts(self):
        from desktop_purchases import PurchasesMixin
        screen = types.SimpleNamespace(purchase_form={"items_sheet": types.SimpleNamespace(ordered=lambda: [])})
        note = PurchasesMixin.add_purchase_pdf_items(screen, {"subtotal": 78948.89, "items": [{"description": "Basil", "quantity": 300, "unit_price": 0.625, "total": 187.5}]})
        self.assertIn("item lines not added", note); self.assertIn("78,948.89", note)


class ItemAccountsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        self.db = Database(Path(folder.name) / "b.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.db.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)

    def test_accounts_of_new_items_and_sales_routing(self):
        nuts = inventory.save_item(self.db, {"name": "Cashews"}, 1); spices = inventory.save_item(self.db, {"name": "Cumin"}, 1)
        with self.assertRaisesRegex(ValueError, "class 7"): inventory.set_item_accounts(self.db, [nuts["id"]], "601100000", "601100000")
        inventory.set_item_accounts(self.db, [nuts["id"], spices["id"]], "601100000", "701100001", 1)
        inventory.set_item_accounts(self.db, [spices["id"]], None, "713", 1)
        items = {i["name"]: i for i in inventory.list_items(self.db)}
        self.assertEqual((items["Cashews"]["cost_account"], items["Cumin"]["sales_account"]), ("601100000", "713"))
        self.db.create_manual_invoice({"invoice_date": "01-03-2025", "party_name": "Supplier", "kind": "purchases", "currency": "USD", "status": "posted"},
            [{"description": "Cashews", "quantity": 5, "unit_price": 40, "vat_rate": 0, "item_code": nuts["sku"]},
             {"description": "Cumin", "quantity": 5, "unit_price": 20, "vat_rate": 0, "item_code": spices["sku"]}], 1)
        number = self.db.create_manual_invoice({"invoice_date": "10-03-2025", "party_name": "Client", "kind": "sales", "currency": "USD", "status": "posted"},
            [{"description": "Cashews", "quantity": 1, "unit_price": 100, "vat_rate": 11, "item_code": nuts["sku"]},
             {"description": "Cumin", "quantity": 1, "unit_price": 50, "vat_rate": 11, "item_code": spices["sku"]}], 1)
        lines = {(r["account_code"]): round(r["credit"] - r["debit"], 2) for r in self.db.journal() if r["account_code"].startswith("7")}
        self.assertEqual(lines, {"701100001": 100.0, "713": 50.0})


class NewCompanyTest(unittest.TestCase):
    def test_new_company_has_the_standard_chart_only(self):
        from company_manager import CompanyManager
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        master = Database(Path(folder.name) / "m.db"); master.initialize("secret12345")
        with master.connect() as db:
            db.execute("INSERT INTO accounts(code,name_en,type) VALUES('401199999','Supplier of another company','liability')")
            db.execute("INSERT INTO parties(kind,name,account_number,currency) VALUES('supplier','Other Co Supplier','401199999','USD')")
        manager = CompanyManager(Path(folder.name) / "m.db")
        company = manager.create_company({"name": "Fresh SARL", "year": 2025}, master)
        fresh = manager.database(company["id"], 2025)
        with fresh.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM accounts WHERE code='401199999'").fetchone())
            self.assertIsNone(db.execute("SELECT 1 FROM parties WHERE name='Other Co Supplier'").fetchone())
            self.assertTrue(db.execute("SELECT 1 FROM accounts WHERE code='4427'").fetchone())  # the standard Lebanese chart
            self.assertTrue(db.execute("SELECT 1 FROM users").fetchone())  # the users can sign in
        master.release(); fresh.release()


if __name__ == "__main__":
    unittest.main()
