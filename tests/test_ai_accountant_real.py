"""Real, filtered-ledger tests for the local multilingual accountant assistant."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import nanza_paths  # noqa: F401
from database import Database
from nanza.ai_accountant.nlu import parse_question
from nanza.ai_accountant.query_builder import query_accountant, query_expenses
from nanza.ai_accountant.responder import respond


class RealAccountantQueryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "company.db")
        self.db.initialize("accountant-query-test")
        self.user = self.db.user_for_token(
            self.db.login("admin", "accountant-query-test")["token"])
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO accounts(code,name_en,type,active) VALUES(?,?,?,1)",
                ("699990001", "Fuel - Diesel", "expense"))
            connection.execute(
                "INSERT INTO accounts(code,name_en,type,active) VALUES(?,?,?,1)",
                ("699990002", "Fuel - Petrol", "expense"))
            connection.execute(
                "INSERT INTO accounts(code,name_en,type,active) VALUES(?,?,?,1)",
                ("699990003", "Office Rent", "expense"))
        self._post("699990001", "500", "Fuel invoice 1")
        self._post("699990002", "750", "Fuel invoice 2")
        self._post("699990003", "1000", "Office rent")

    def _post(self, account, amount, description):
        self.db.save_journal_voucher(
            {"entry_date": "05-09-2026", "description": description, "currency": "USD"},
            [{"account_code": account, "debit": amount, "credit": "0"},
             {"account_code": "531", "debit": "0", "credit": amount}], self.user["id"])

    def test_fuel_filter_returns_only_fuel_accounts_and_sources(self):
        result = query_expenses(
            self.db, "fuel last month", self.user, today=date(2026, 10, 18))
        answer = respond(result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["totals"], {"USD": 1250.0})
        self.assertEqual({row["account_code"] for row in answer["sources"]},
                         {"699990001", "699990002"})
        with self.db.connect() as connection:
            existing = {row["entry_number"] for row in connection.execute(
                "SELECT entry_number FROM journal_entries")}
        self.assertTrue({row["entry_number"] for row in answer["sources"]} <= existing)
        self.assertEqual(answer["confidence"], "Exact ledger query")
        self.assertIn(answer["sources"][0]["entry_number"], answer["message"])

    def test_arabic_question_maps_account_and_period(self):
        parsed = parse_question("مصاريف البنزين الشهر الماضي", today=date(2026, 10, 18))
        self.assertEqual(parsed["intent"], "expense_report")
        self.assertEqual(parsed["entities"]["account"], "fuel")
        self.assertEqual(parsed["entities"]["period"], "last_month")
        self.assertEqual(parsed["entities"]["date_from"], "2026-09-01")
        self.assertEqual(parsed["entities"]["date_to"], "2026-09-30")

    def test_requested_arabic_and_french_intents_are_detected(self):
        questions = {
            "أعمار الذمم المدينة": "ar_aging",
            "أعمار الذمم الدائنة": "ap_aging",
            "Prévision de trésorerie": "cash_forecast",
            "Factures en double": "duplicate_check",
            "لماذا انخفض الربح": "profit_why",
        }
        for question, expected in questions.items():
            with self.subTest(question=question):
                self.assertEqual(parse_question(question)["intent"], expected)

    def test_aging_forecast_duplicate_and_profit_intents_execute(self):
        for question, expected in (
                ("AR aging", "ar_aging"), ("AP aging", "ap_aging"),
                ("cash forecast", "cash_forecast"),
                ("duplicate invoice check", "duplicate_check"),
                ("why did profit change", "profit_why")):
            with self.subTest(question=question):
                result = query_accountant(
                    self.db, question, self.user, today=date(2026, 10, 18))
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["intent"], expected)

    def test_ar_aging_reconciles_to_posted_control_balance(self):
        self.db.create_manual_invoice(
            {"invoice_date": "01-10-2026", "party_name": "AI test customer",
             "kind": "sales", "currency": "USD", "status": "posted"},
            [{"description": "Service", "quantity": 1, "unit_price": 1250, "vat_rate": 0}],
            self.user["id"])
        result = query_accountant(
            self.db, "AR aging", self.user, today=date(2026, 10, 18))
        self.assertEqual(result["totals"], {"USD": 1250.0})
        self.assertTrue(result["reconciliation"]["USD"]["matches"])

    def test_duplicate_check_finds_supplier_invoices_within_seven_days(self):
        for number, invoice_date in (("DUP-A", "10-10-2026"), ("DUP-B", "15-10-2026")):
            self.db.create_manual_invoice(
                {"invoice_number": number, "invoice_date": invoice_date,
                 "party_name": "AI duplicate vendor", "kind": "purchases",
                 "currency": "USD", "status": "posted"},
                [{"description": "Supplies", "quantity": 1, "unit_price": 250, "vat_rate": 0}],
                self.user["id"])
        result = query_accountant(
            self.db, "duplicate invoice check", self.user, today=date(2026, 10, 18))
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual({item["number"] for item in result["rows"][0]["invoices"]},
                         {"DUP-A", "DUP-B"})


if __name__ == "__main__":
    unittest.main()
