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

    def test_only_purchases_of_the_purchases_screen_are_learned(self):
        sale = self.db.create_manual_invoice({"invoice_number": "S-1", "invoice_date": "10-03-2026", "party_name": "Client", "kind": "sale", "currency": "USD"},
                                             [{"description": "Consulting", "quantity": 1, "unit_price": 10}], self.user)
        self.assertEqual(posting_rules.learn_invoice(self.db, sale["id"] if isinstance(sale, dict) else sale), [])
        imported = self.db.create_manual_invoice({"invoice_number": "F-9", "invoice_date": "10-03-2026", "party_name": "Cedar Rentals SARL", "kind": "purchase",
                                                  "currency": "USD"}, [{"description": "Rent", "quantity": 1, "unit_price": 10}], self.user)
        self.assertEqual(posting_rules.learn_invoice(self.db, imported["id"] if isinstance(imported, dict) else imported), [])
        self.assertEqual(posting_rules.list_rules(self.db), [])

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
