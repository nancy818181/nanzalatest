"""2.9.71: two main currencies per company, rates of all currencies, journal voucher account typing,
one account for the selected Uploaded Data rows, audit report notes without account numbers."""
import tests_setup  # noqa: F401  2.9.74: the sample company of the tests (a new installation has none)
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from company_manager import CompanyManager
from database import Database
import financial_statements as fs

try:
    import tkinter  # noqa: F401
    HAS_TK = True
except ImportError:
    HAS_TK = False


class _Book(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "company.db"); self.db.initialize("secret12345")
        self.addCleanup(self.db.release)

    def purchase(self, number, subtotal=100, vat=11):
        result = self.db.import_invoice({"invoice_number": number, "invoice_date": "15-03-2026", "party_name": "Supplier One", "kind": "purchase",
                                         "currency": "USD", "subtotal": subtotal, "vat": vat, "total": subtotal + vat}, 1)
        return result["id"] if isinstance(result, dict) else int(result)

    def balances(self):
        return {r["code"]: (Decimal(str(r["debit"])), Decimal(str(r["credit"]))) for r in self.db.trial_balance() if r.get("debit") or r.get("credit")}


class MainCurrenciesTest(unittest.TestCase):
    def test_company_is_created_with_its_two_main_currencies_and_a_new_year_keeps_them(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder); old_env = os.environ.get("SABER_DATA_DIR"); os.environ["SABER_DATA_DIR"] = str(root / "data")
            try:
                master = Database(root / "saber_accounting.db"); master.initialize("secret")
                manager = CompanyManager(root / "saber_accounting.db")
                company = manager.create_company({"name": "Euro Trading SARL", "year": 2025, "main_currency_1": "eur", "main_currency_2": "GBP"}, master)
                book = manager.database(company["id"], 2025)
                self.assertEqual((book.settings()["base_currency"], book.settings()["second_currency"]), ("EUR", "GBP"))
                self.assertIn("GBP", book.currency_codes())
                manager.create_year(company["id"], 2026, 1)
                later = manager.database(company["id"], 2026)
                self.assertEqual(later.settings()["second_currency"], "GBP"); self.assertIn("GBP", later.currency_codes())
                default = manager.create_company({"name": "Local SAL", "year": 2025}, master)
                self.assertEqual(manager.database(default["id"], 2025).settings()["second_currency"], "LBP")
                with self.assertRaisesRegex(ValueError, "different"):
                    manager.create_company({"name": "Same Twice", "year": 2025, "main_currency_1": "USD", "main_currency_2": "usd"}, master)
                self.assertFalse(any(c["name"] == "Same Twice" for c in manager.list_companies(True)))
                for path in list(manager._cache): manager._cache.pop(path).release()
                master.release()
            finally:
                if old_env is None: os.environ.pop("SABER_DATA_DIR", None)
                else: os.environ["SABER_DATA_DIR"] = old_env

    def test_settings_save_and_check_the_second_main_currency(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db = Database(Path(folder) / "c.db"); db.initialize("secret12345")
            try:
                self.assertEqual(db.settings()["second_currency"], "LBP")
                db.save_settings({"base_currency": "AED", "second_currency": "USD"}, 1)
                self.assertEqual((db.settings()["base_currency"], db.settings()["second_currency"]), ("AED", "USD"))
                with self.assertRaisesRegex(ValueError, "different"): db.save_settings({"base_currency": "USD", "second_currency": "USD"}, 1)
                with self.assertRaisesRegex(ValueError, "Invalid second"): db.save_settings({"base_currency": "USD", "second_currency": "XYZ"}, 1)
            finally: db.release()

    @unittest.skipUnless(HAS_TK, "needs tkinter")
    def test_screens_read_the_main_currencies_once_per_company(self):
        from desktop_common import main_currency
        calls = []
        class Client:
            company_id = "c1"; fiscal_year = 2025
            def settings(self): calls.append(1); return {"base_currency": "EUR", "second_currency": "USD"}
        class App: client = Client()
        app = App()
        self.assertEqual((main_currency(app, 1), main_currency(app, 2), main_currency(app, 1)), ("EUR", "USD", "EUR"))
        self.assertEqual(len(calls), 1)
        app.client.company_id = "c2"; main_currency(app, 1); self.assertEqual(len(calls), 2)
        self.assertEqual((main_currency(object(), 1), main_currency(object(), 2)), ("USD", "LBP"))  # no company yet


class AllRatesTest(_Book):
    def test_every_currency_of_settings_gets_daily_rates_and_typed_rates_are_kept(self):
        self.db.save_currency("GBP", "Pound sterling", 1); self.db.save_currency("XAF", "Central African franc", 1)
        self.db.save_exchange_rate({"date_from": "10-03-2025", "from_currency": "GBP", "to_currency": "USD", "rate": "1.5"}, 1)
        def fake(_self, url, timeout=10):
            if "from=USD" in url: return {"rates": {"2024-01-02": {"GBP": "0.80"}, "2025-06-02": {"GBP": "0.75"}}}
            return {"rates": {"2024-01-02": {"USD": "1.10"}}}
        with mock.patch.object(Database, "_download_json", fake), mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            result = self.db.restore_all_rates()
        self.assertEqual(result["restored"], ["USD", "LBP", "EUR", "AED", "SAR", "GBP"])  # 2.9.78: SAR is a standard currency
        self.assertEqual(result["skipped"], ["XAF"])  # no automatic source: typed by hand
        self.assertEqual(self.db._converted_amount(100, "AED", "USD", "15-03-2025").quantize(Decimal("0.01")), Decimal("27.23"))
        self.assertEqual(self.db._converted_amount(100, "GBP", "USD", "15-03-2025").quantize(Decimal("0.01")), Decimal("125.00"))
        self.assertEqual(self.db._converted_amount(100, "GBP", "USD", "15-07-2025").quantize(Decimal("0.01")), Decimal("133.33"))
        self.assertEqual(self.db._converted_amount(100, "GBP", "USD", "10-03-2025").quantize(Decimal("0.01")), Decimal("150.00"))  # typed rate kept

    def test_offline_years_are_reported_not_fatal(self):
        self.db.save_currency("GBP", "Pound sterling", 1)
        with mock.patch.object(Database, "_download_json", side_effect=OSError("offline")), mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            result = self.db.restore_all_rates()
        self.assertIn("GBP", result["skipped"]); self.assertTrue(result["offline_years"]); self.assertIn("AED", result["restored"])


class OneAccountForSelectedTest(_Book):
    def test_chosen_account_replaces_the_expense_account_of_the_selected_rows_only(self):
        ids = [self.purchase(f"P-{n}") for n in range(3)]
        old = self.db.get_invoice(ids[0])["expense_account"]
        with self.db.connect() as connection:
            target = connection.execute("SELECT code FROM accounts WHERE code LIKE '6%' AND length(code)>=9 AND code<>? ORDER BY code LIMIT 1", (old,)).fetchone()[0]
        before = self.balances()
        result = self.db.set_invoices_account(ids[:2], "expense_account", target, 1)
        self.assertEqual(result["done"], ["P-0", "P-1"]); self.assertEqual(result["skipped"], [])
        after = self.balances()
        self.assertEqual(after[target], (Decimal("200"), Decimal("0"))); self.assertEqual(after[old], (Decimal("100"), Decimal("0")))
        self.assertEqual(sum(d for d, _ in after.values()), sum(d for d, _ in before.values()))  # same totals, nothing else moved
        self.assertEqual([self.db.get_invoice(i)["expense_account"] for i in ids], [target, target, old])
        again = self.db.set_invoices_account(ids[:1], "expense_account", target, 1)
        self.assertEqual(again["done"], []); self.assertIn("already", again["skipped"][0])

    def test_unknown_account_or_field_is_refused(self):
        invoice = self.purchase("P-9")
        with self.assertRaisesRegex(ValueError, "not found"): self.db.set_invoices_account([invoice], "expense_account", "999999999", 1)
        with self.assertRaisesRegex(ValueError, "Choose which account"): self.db.set_invoices_account([invoice], "party_name", "601100000", 1)


class AuditNotesTest(_Book):
    def test_note_tables_show_names_without_account_numbers(self):
        self.db.save_journal_voucher(dict(entry_date="01-03-2025", currency="USD", description="FS test"),
                                     [dict(account_code="531", debit="1000", credit=0), dict(account_code="7011", debit=0, credit="1000")], 1)
        pack = fs.build({2025: self.db}, {"years": "2025", "basis": "USD"})
        notes = [s for s in pack["sections"] if s["heading"][:1].isdigit() and s.get("fixed") and not s.get("narrative")]
        self.assertTrue(notes)
        for section in notes:
            self.assertEqual(section["headers"][0], "Description"); self.assertNotIn("Account", section["headers"])
            for row in section["rows"][:-1]:
                self.assertFalse(str(row[0]).isdigit(), f"account number shown in note {section['heading']}: {row}")


@unittest.skipUnless(HAS_TK, "needs tkinter")
class VoucherAccountTypingTest(unittest.TestCase):
    def journal(self, codes):
        from desktop_brains import BrainsScreensMixin
        journal = BrainsScreensMixin()
        journal._account_cache = {code: {"code": code, "name_en": f"Account {code}"} for code in codes}
        journal.client = None
        return journal

    def test_only_account_starting_with_the_typed_number_is_taken(self):
        journal = self.journal(["531000001", "601100000", "601100001", "4011"])
        self.assertEqual(journal.voucher_account_by_prefix("5310")["code"], "531000001")
        self.assertIsNone(journal.voucher_account_by_prefix("6011"))  # two accounts: the search opens
        self.assertIsNone(journal.voucher_account_by_prefix("cash"))

    def test_unknown_number_asks_for_the_search_instead_of_an_error(self):
        journal = self.journal(["531000001", "601100000", "601100001"])
        tree = type("Tree", (), {"get_children": lambda self: ("r1",)})()
        journal.voucher_sheet = type("Sheet", (), {"rows": {"r1": {}}, "tree": tree, "refresh": lambda self, iid: None})()
        journal.party_rows = []
        journal.recalculate_voucher_line = lambda row: row
        journal.update_manual_totals = lambda: None
        journal.voucher_line_selected = lambda selection: None
        self.assertEqual(journal.voucher_cell_changed("r1", "account", "6011"), "lookup")
        journal.voucher_cell_changed("r1", "account", "531")
        self.assertEqual(journal.voucher_sheet.rows["r1"]["account"], "531000001")


if __name__ == "__main__":
    unittest.main()
