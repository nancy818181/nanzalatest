"""2.9.120: posting rules (memory per supplier) and classification of the lines - learned locally, free, only suggestions."""
import tests_setup  # noqa: F401
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import posting_rules
from test_final_features import new_db


def purchase(db, user, supplier, number, lines, **extra):
    """A purchase as the Purchases screen saves it."""
    invoice = {"invoice_number": number, "invoice_date": "10-03-2026", "party_name": supplier, "kind": "purchases", "currency": "USD", "status": "posted",
               "source_file": "Purchase Invoice", "expense_account": "6263.1", "vat_account": "4426", "vat_use": "taxable",
               "vat_treatment": "standard", "payment_method": "Credit (unpaid)", "amount_paid": "0", **extra}
    saved = db.create_manual_invoice(invoice, lines, user)
    return saved["id"] if isinstance(saved, dict) else int(saved)


class PostingRulesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db, self.user = new_db(self.folder.name)
        self.db.save_party({"kind": "supplier", "name": "Cedar Rentals SARL", "currency": "USD", "mof_number": "3344556-601"}, self.user)

    def test_keys_and_numbers(self):
        self.assertEqual(posting_rules.number_key("3344556-601"), "mof:3344556")
        self.assertEqual(posting_rules.number_key("3344556"), "mof:3344556")
        self.assertEqual(posting_rules.name_key("Cedar Rentals S.A.R.L."), posting_rules.name_key("cedar rentals sarl"))
        self.assertEqual(posting_rules.keys_for("Cedar Rentals", "111222, 3344556-601"), ["mof:111222", "mof:3344556", "name:cedar rentals"])
        self.assertEqual(posting_rules.numbers_in("MOF No: 3344556-601\nVAT Reg. 998877\nTotal 100"), "3344556-601,998877")
        self.assertEqual(posting_rules.tokens("2 x Office RENT for March 2026"), ["office", "rent", "march"])

    def test_learn_then_suggest_by_number_name_and_similar_name(self):
        invoice = purchase(self.db, self.user, "Cedar Rentals SARL", "R-1", [{"description": "Office rent March", "quantity": 1, "unit_price": 900}])
        self.assertIn("mof:3344556", posting_rules.learn_invoice(self.db, invoice))
        by_number = posting_rules.find_rule(self.db, "purchase", "Another name", "3344556")
        self.assertEqual((by_number["matched"], by_number["data"]["expense_account"], by_number["data"]["vat_use"]), ("number", "6263.1", "taxable"))
        self.assertEqual(posting_rules.find_rule(self.db, "purchase", "CEDAR RENTALS s.a.r.l")["matched"], "name")
        self.assertTrue(posting_rules.find_rule(self.db, "purchase", "Cedar Rentalls")["matched"].startswith("similar name"))
        self.assertIsNone(posting_rules.find_rule(self.db, "purchase", "Phoenix Fuel"))
        second = purchase(self.db, self.user, "Cedar Rentals SARL", "R-2", [{"description": "Office rent April", "quantity": 1, "unit_price": 900}])
        self.assertTrue(posting_rules.learn_invoice(self.db, second))
        self.assertEqual(posting_rules.find_rule(self.db, "purchase", None, "3344556")["times"], 2)
        found = posting_rules.suggest(self.db, "purchase", "Cedar Rentals SARL", None, "", ["rent"])
        self.assertEqual((found["account"]["code"], found["account"]["confidence"]), ("6263.1", 0.95))

    def test_buyer_and_supplier_numbers_are_disambiguated_by_supplier_name(self):
        for name, number, mof in (("Cedar Rentals SARL", "R-1", "3344556"), ("Buyer Trading", "B-1", "998877")):
            self.db.save_party({"kind": "supplier", "name": name, "currency": "USD", "mof_number": mof}, self.user)
            invoice = purchase(self.db, self.user, name, number, [{"description": "Rent", "quantity": 1, "unit_price": 20}])
            posting_rules.learn_invoice(self.db, invoice)
        found = posting_rules.find_rule(self.db, "purchase", "Cedar Rentals SARL", "998877,3344556")
        self.assertEqual(found["label"], "Cedar Rentals SARL")
        self.assertIsNone(posting_rules.find_rule(self.db, "purchase", "Unreadable", "998877,3344556"))

    def test_ocr_invoice_reuses_the_posting_of_a_previous_invoice(self):
        import azure_reader
        invoice=purchase(self.db,self.user,"Cedar Rentals SARL","MEM-1",[{"description":"Office rent","quantity":1,"unit_price":900}],
                         expense_account="6263.1",vat_account="4426",vat_use="taxable")
        posting_rules.learn_invoice(self.db,invoice)
        parsed=azure_reader.to_result(Path(self.folder.name)/"handwritten.jpg",{"content":"", "documents":[{"confidence":0.95,"fields":{
            "VendorName":{"valueString":"Cedar Rentals"},"VendorTaxId":{"valueString":"3344556-601"},
            "InvoiceId":{"valueString":"MEM-2"},"InvoiceDate":{"valueDate":"2026-04-10"},
            "SubTotal":{"valueCurrency":{"amount":900,"currencyCode":"USD"}},
            "TotalTax":{"valueCurrency":{"amount":99,"currencyCode":"USD"}},
            "InvoiceTotal":{"valueCurrency":{"amount":999,"currencyCode":"USD"}}}}]})
        suggested=posting_rules.suggest(self.db,"purchase",parsed["party_name"],parsed["party_tax_number"])
        self.assertEqual(suggested["rule"]["matched"],"number")
        self.assertEqual(suggested["rule"]["last_reference"],"MEM-1")
        self.assertEqual(suggested["rule"]["data"]["expense_account"],"6263.1")
        self.assertEqual(suggested["rule"]["data"]["vat_account"],"4426")
        self.assertTrue(parsed["review_warnings"])
        self.assertTrue(parsed["review_required"])

    def test_only_purchases_of_the_purchases_screen_are_learned(self):
        sale = self.db.create_manual_invoice({"invoice_number": "S-1", "invoice_date": "10-03-2026", "party_name": "Client", "kind": "sale", "currency": "USD"},
                                             [{"description": "Consulting", "quantity": 1, "unit_price": 10}], self.user)
        self.assertEqual(posting_rules.learn_invoice(self.db, sale["id"] if isinstance(sale, dict) else sale), [])
        imported = self.db.create_manual_invoice({"invoice_number": "F-9", "invoice_date": "10-03-2026", "party_name": "Cedar Rentals SARL", "kind": "purchase",
                                                  "currency": "USD"}, [{"description": "Rent", "quantity": 1, "unit_price": 10}], self.user)
        self.assertEqual(posting_rules.learn_invoice(self.db, imported["id"] if isinstance(imported, dict) else imported), [])
        self.assertEqual(posting_rules.list_rules(self.db), [])

    def test_confirmed_uploaded_invoice_can_teach_memory_without_learning_opening_balances(self):
        saved=self.db.create_manual_invoice({"invoice_number":"SCAN-1","invoice_date":"10-03-2026","party_name":"Cedar Rentals SARL",
            "kind":"purchases","currency":"USD","status":"posted","source_file":"rent.pdf - Page 1","expense_account":"6263.1"},
            [{"description":"Office rent","quantity":1,"unit_price":900}],self.user)
        invoice_id=saved["id"] if isinstance(saved,dict) else int(saved)
        self.assertEqual(posting_rules.learn_invoice(self.db,invoice_id),[])
        self.assertTrue(posting_rules.learn_invoice(self.db,invoice_id,allow_imported=True))
        self.assertEqual(posting_rules.find_rule(self.db,"purchase",None,"3344556")["last_reference"],"SCAN-1")
        with self.db.connect() as c:c.execute("UPDATE invoices SET source_file='Opening balances' WHERE id=?",(invoice_id,))
        self.assertEqual(posting_rules.learn_invoice(self.db,invoice_id,allow_imported=True),[])

    def test_classification_of_lines_and_fallbacks(self):
        invoice = purchase(self.db, self.user, "Cedar Rentals SARL", "R-1", [{"description": "Diesel generator fuel", "quantity": 1, "unit_price": 50}],
                           expense_account="6061.2")
        posting_rules.learn_invoice(self.db, invoice)
        lines = posting_rules.classify_lines(self.db, ["Generator diesel 200 litres", "Something unknown"])
        self.assertEqual((lines[0]["account"], lines[0]["confidence"]), ("6061.2", 1.0))
        self.assertEqual(lines[1]["account"], "")
        new_supplier = posting_rules.suggest(self.db, "purchase", "New Fuel Co", None, "", ["diesel for the generator"])
        self.assertIsNone(new_supplier["rule"])
        self.assertEqual((new_supplier["account"]["code"], new_supplier["account"]["source"]), ("6061.2", "lines saved before"))
        keywords = posting_rules.suggest(self.db, "purchase", "Electricite du Liban", None, "EDL electricity bill", [])
        self.assertTrue(keywords["account"]["source"].startswith("keywords"))
        self.assertTrue(keywords["account"].get("parent"))

    def test_tax_flag_follows_the_rule(self):
        invoice = purchase(self.db, self.user, "Cedar Rentals SARL", "R-1", [{"description": "Rent", "quantity": 1, "unit_price": 900}])
        posting_rules.learn_invoice(self.db, invoice)
        posting_rules.learn_tax_flag(self.db, "invoice", invoice, True)
        self.assertTrue(posting_rules.find_rule(self.db, "purchase", None, "3344556")["data"]["not_deductible"])
        posting_rules.learn_tax_flag(self.db, "invoice", invoice, False)
        self.assertFalse(posting_rules.find_rule(self.db, "purchase", None, "3344556")["data"]["not_deductible"])

    def test_expense_form_uses_learned_classification_for_a_new_supplier(self):
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from desktop_expenses import ExpensesMixin
        class Field:
            def __init__(self,value=""):self.value=value
            def get(self):return self.value
            def set(self,value):self.value=value
        variables={key:Field() for key in ("account","no_vat_account","without_vat")}
        variables["without_vat"].set("100")
        app=SimpleNamespace(expense_form={"vars":variables},client=SimpleNamespace(posting_suggestion=Mock(return_value={"rule":None,
            "account":{"code":"6263.1","confidence":0.9,"source":"lines saved before"}})))
        with patch("desktop_common.account_label",side_effect=lambda app,code:code):
            note=ExpensesMixin.apply_expense_rule(app,"New supplier",lines=["Office rent"])
        self.assertEqual(variables["account"].get(),"6263.1")
        self.assertEqual(variables["no_vat_account"].get(),"6263.1")
        self.assertIn("lines saved before",note)

    def test_bill_to_does_not_misidentify_the_currency_as_lbp(self):
        import pdf_import
        self.assertEqual(pdf_import._invoice_currency("Invoice\nBill to ABC\nSubtotal 60\nGrand Total 60"),"")
        self.assertEqual(pdf_import._invoice_currency("Bill to ABC\nGrand Total LL 60000"),"LBP")
        self.assertEqual(pdf_import._invoice_currency("Bill to ABC\nGrand Total $60"),"USD")

    def test_arabic_repairs_and_advertising_classification(self):
        import pdf_import
        self.assertEqual(pdf_import.expense_category("تصليح دواليب سيارة وغيار بوجي")[0],"Maintenance")
        self.assertEqual(pdf_import.expense_category("دعاية شهرية وتسويق")[0],"Advertising")
        self.assertEqual(pdf_import.expense_category("اعلان تجاري")[0],"Advertising")

    def test_expense_photo_is_sent_to_ocr_instead_of_only_attached(self):
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from desktop_expenses import ExpensesMixin
        app=SimpleNamespace(expense_form={"id":None,"pdf_label":Mock()})
        with patch("desktop_expenses.filedialog.askopenfilename",return_value="expense.jpg"), \
             patch("desktop_expenses.prepare_pdf_reading"), \
             patch("desktop_expenses.read_invoice_pdf",return_value={"party_name":"Supplier"}) as read, \
             patch.object(ExpensesMixin,"fill_expense_from_reading") as fill:
            ExpensesMixin.choose_expense_pdf(app)
        read.assert_called_once_with("expense.jpg")
        fill.assert_called_once_with(app,"expense.jpg",{"party_name":"Supplier"})

    def test_expense_rule_only_with_a_supplier(self):
        first = self.db.add_expense({"expense_date": "11-03-2026", "description": "Electricity March", "currency": "LBP", "with_vat_subtotal": "1000000",
                                     "vat": "110000", "expense_account": "6263.2", "payment_account": "5121"}, self.user)
        first = first["id"] if isinstance(first, dict) else first
        self.assertEqual(posting_rules.learn_expense(self.db, first), [])  # no supplier: words only
        self.assertEqual(posting_rules.list_rules(self.db), [])
        self.assertEqual(posting_rules.classify_lines(self.db, ["electricity april"])[0]["account"], "6263.2")
        self.assertEqual(posting_rules.learn_expense(self.db, first, "Electricite du Liban (EDL)"), ["name:electricite du liban edl"])
        rule = posting_rules.find_rule(self.db, "expense", "Electricite du Liban (EDL)")
        self.assertEqual((rule["data"]["expense_account"], rule["data"]["payment_account"], rule["data"]["vat_recoverable"]), ("6263.2", "5121", True))
        self.assertEqual(posting_rules.delete_rule(self.db, rule["id"]), {"deleted": rule["id"]})
        self.assertEqual(posting_rules.list_rules(self.db), [])


class PostingRulesApiTest(unittest.TestCase):
    """The data service learns when a purchase / expense is saved and answers the screens."""
    @classmethod
    def setUpClass(cls):
        from client import ApiClient
        from server import run_server
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
        threading.Thread(target=run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(Path(cls.folder.name) / "app.db"),
                                                    "admin_password": "secret12345"}, daemon=True).start()
        cls.client = ApiClient(f"http://127.0.0.1:{port}")
        for _ in range(100):
            try: cls.client.login("admin", "secret12345"); break
            except (OSError, RuntimeError): time.sleep(.05)
        company = cls.client.companies()[0]
        cls.client.select_company_year(company["id"], company["years"][0]["year"])

    @classmethod
    def tearDownClass(cls):
        cls.client.close(); cls.folder.cleanup()

    def test_confirmed_pdf_paths_teach_memory_through_the_api(self):
        year=self.client.companies()[0]["years"][0]["year"]
        self.client.create_manual_invoice({"invoice_number":"UPLOAD-API-1","invoice_date":f"10-03-{year}",
            "party_name":"Upload memory supplier","kind":"purchases","currency":"USD","status":"posted",
            "source_file":"uploaded.pdf - Page 1","remember_posting":True,"expense_account":"6263.1"},
            [{"description":"Office rent","quantity":1,"unit_price":100}])
        self.assertEqual(self.client.posting_suggestion("purchase","Upload memory supplier")["rule"]["last_reference"],"UPLOAD-API-1")
        result=self.client.import_invoices([{"invoice_number":"UPLOAD-API-2","invoice_date":f"11-03-{year}",
            "party_name":"Imported memory supplier","kind":"purchase","currency":"USD","status":"posted",
            "subtotal":100,"vat":11,"total":111,"source_file":"imported.pdf - Page 1","remember_posting":True,"expense_account":"6263.1"}],replace_existing=False)
        self.assertEqual(result["imported"],1)
        self.assertEqual(self.client.posting_suggestion("purchase","Imported memory supplier")["rule"]["last_reference"],"UPLOAD-API-2")
        for rule in self.client.posting_rules():self.client.delete_posting_rule(rule["id"])

    def test_saving_teaches_and_the_screen_gets_the_suggestion(self):
        year = self.client.companies()[0]["years"][0]["year"]
        self.client.create_manual_invoice({"invoice_number": "API-1", "invoice_date": f"10-03-{year}", "party_name": "Byblos Paper SAL", "kind": "purchases",
                                           "currency": "USD", "status": "posted", "source_file": "Purchase Invoice", "expense_account": "6263.1",
                                           "vat_account": "4426", "payment_method": "Credit (unpaid)", "amount_paid": "0"},
                                          [{"description": "A4 paper boxes", "quantity": 3, "unit_price": 20}])
        found = self.client.posting_suggestion("purchase", "BYBLOS PAPER s.a.l.", None, "", ["A4 paper"])
        self.assertEqual(found["rule"]["data"]["expense_account"], "6263.1")
        self.assertEqual(found["lines"][0]["account"], "6263.1")
        rules = self.client.posting_rules()
        self.assertEqual([r["label"] for r in rules], ["Byblos Paper SAL"])
        self.client.add_expense({"expense_date": f"11-03-{year}", "description": "Taxi", "currency": "USD", "with_vat_subtotal": "0",
                                 "without_vat_subtotal": "20", "vat": "0", "expense_account": "6263.2", "expense_without_vat_account": "6263.2",
                                 "payment_account": "531", "supplier": "Allo Taxi"})
        self.assertEqual(self.client.posting_suggestion("expense", "Allo Taxi")["rule"]["data"]["payment_account"], "531")
        for rule in self.client.posting_rules(): self.client.delete_posting_rule(rule["id"])
        self.assertEqual(self.client.posting_rules(), [])


if __name__ == "__main__":
    unittest.main()
