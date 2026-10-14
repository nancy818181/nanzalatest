"""2.9.116: a chart of accounts chosen when the company is created (Lebanon, IFRS, Saudi Arabia, UAE)."""
import ast
import glob
import re
import secrets
import tempfile
import unittest
from pathlib import Path

import chart_templates
from company_manager import CompanyManager
from database import Database
from lebanese_accounts import LEBANESE_ACCOUNTS

HERE = Path(__file__).resolve().parent


def program_account_codes():
    """Every account number written in the program (outside the Lebanese chart itself)."""
    lebanese = {r[0] for r in LEBANESE_ACCOUNTS}; found = set()
    for name in glob.glob(str(HERE / "*.py")):
        path = Path(name)
        if path.name.startswith("test_") or path.name in ("lebanese_accounts.py", "chart_templates.py"): continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(r"\d{1,9}(\.\d+)?", node.value) and node.value in lebanese:
                found.add(node.value)
    return found


class ChartTemplateTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.master = Database(Path(self.folder.name) / "main.db"); self.master.initialize(secrets.token_hex(8))
        self.manager = CompanyManager(Path(self.folder.name) / "main.db")

    def tearDown(self):
        self.folder.cleanup()

    def company(self, template, **extra):
        spec = chart_templates.TEMPLATES[template]
        item = {"name": f"Test {template} {secrets.token_hex(2)}", "year": 2026, "chart_template": template,
                "main_currency_1": spec["currencies"][0], "main_currency_2": spec["currencies"][1],
                "vat_rate": spec["vat_rate"], "vat_currency_1": spec["vat_currencies"][0], "vat_currency_2": spec["vat_currencies"][1], **extra}
        created = self.manager.create_company(item, self.master)
        db = Database(created["years"][0]["database"]); db.initialize_if_needed(secrets.token_hex(8))
        return db

    def codes(self, db):
        with db.connect() as c: return {r["code"]: dict(r) for r in c.execute("SELECT * FROM accounts")}

    def test_every_account_the_program_posts_to_is_in_every_chart(self):
        missing = program_account_codes() - set(chart_templates.SPINE)
        self.assertEqual(missing, set(), "add these accounts to chart_templates.SPINE")
        for key in chart_templates.TEMPLATES:
            self.assertTrue(set(chart_templates.SPINE) <= {r[0] for r in chart_templates.rows(key)}, key)

    def test_lebanese_company_is_exactly_as_before(self):
        db = self.company("lebanon")
        self.assertTrue({r[0] for r in LEBANESE_ACCOUNTS} <= set(self.codes(db)))
        self.assertEqual(self.codes(db)["1"]["name_en"], "Equity & Long Term Debts")

    def test_company_without_a_choice_gets_the_lebanese_chart(self):
        created = self.manager.create_company({"name": "Old Style SARL", "year": 2026}, self.master)
        db = Database(created["years"][0]["database"])
        with db.connect() as c: self.assertEqual(chart_templates.current(c), "lebanon")
        self.assertIn("4111", self.codes(db)); self.assertGreater(len(self.codes(db)), 500)

    def test_saudi_chart_names_accounts_and_upgrade(self):
        db = self.company("ksa")
        codes = self.codes(db)
        self.assertEqual(codes["22"]["name_en"], "Property, Plant and Equipment")
        self.assertIn("443300001", codes)  # Zakat payable
        self.assertNotIn("101", codes)      # a Lebanese detail account the chart does not use
        self.assertLess(len(codes), 300)
        with db.connect() as c:
            self.assertEqual(c.execute("SELECT value FROM app_settings WHERE key='vat_rate'").fetchone()[0], "15")
            c.execute("UPDATE accounts SET name_en='Our PPE' WHERE code='22'")
            c.execute("DELETE FROM app_settings WHERE key='startup_schema_signature'")  # force an upgrade
        db.initialize_if_needed(secrets.token_hex(8))
        codes = self.codes(db)
        self.assertEqual(codes["22"]["name_en"], "Our PPE")  # a name the user changed is kept
        self.assertNotIn("101", codes)                       # the upgrade does not bring the Lebanese chart back

    def test_every_chart_runs_the_daily_work_and_the_reports(self):
        import financial_statements as fs
        import vat_return
        for template in ("ifrs", "ksa", "uae"):
            with self.subTest(template=template):
                db = self.company(template)
                user = 1; money, second = chart_templates.TEMPLATES[template]["currencies"]
                for source, target, rate in ((money, second, "0.27"), (second, money, "3.7")):  # the user enters the rates
                    db.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-03-2026", "from_currency": source, "to_currency": target, "rate": rate}, user)
                party = db.save_party({"kind": "customer", "name": "Client One", "currency": money}, user)
                db.create_manual_invoice({"invoice_date": "05-02-2026", "party_name": "Client One", "kind": "sale", "currency": money},
                                         [{"description": "Service", "quantity": 1, "unit_price": 1000}], user)
                db.create_manual_invoice({"invoice_date": "06-02-2026", "party_name": "Supplier One", "kind": "purchase", "currency": money},
                                         [{"description": "Goods", "quantity": 2, "unit_price": 100}], user)
                db.add_payment({"kind": "customer_receipt", "payment_date": "10-02-2026", "party_id": party["id"], "currency": money, "amount": "500",
                                "cash_account": "531", "party_account": party["account_number"]}, user)
                db.add_expense({"expense_date": "11-02-2026", "description": "Office", "currency": money, "with_vat_subtotal": "100", "vat": "5"}, user)
                db.save_journal_voucher({"entry_date": "12-02-2026", "description": "Capital", "currency": money},
                                        [{"account_code": "531", "debit": 5000, "credit": 0}, {"account_code": "10", "debit": 0, "credit": 5000}], user)
                rows = db.trial_balance("01-01-2026", "31-12-2026")
                self.assertTrue(rows)
                fs.year_data(db, 2026, money)
                vat_return.build_vat_return(db, 2026, 1)


    def test_chart_from_excel_adds_and_names_but_never_deletes(self):
        from openpyxl import Workbook
        db = self.company("uae")
        book = Workbook(); sheet = book.active
        sheet.append(["Account", "Parent", "English", "French", "Arabic", "Type"])
        sheet.append(["626300100", "626300000", "Office Rent - Dubai", "Loyer bureau - Dubaï", "إيجار المكتب - دبي", "expense"])  # child first
        sheet.append(["626300000", "626", "Rent", "Loyers", "الإيجارات", "Expense"])
        sheet.append(["531", "", "Petty Cash AED", "", "", ""])          # an account already there: its name is filled in
        sheet.append(["ABC", "", "Wrong", "", "", "expense"])
        path = Path(self.folder.name) / "chart.xlsx"; book.save(path)
        items = chart_templates.read_excel(path)
        result = chart_templates.import_accounts(db, items, 1)
        self.assertEqual((result["added"], result["updated"], len(result["skipped"])), (2, 1, 1))
        codes = self.codes(db)
        self.assertEqual(codes["626300100"]["name_ar"], "إيجار المكتب - دبي"); self.assertEqual(codes["531"]["name_en"], "Petty Cash AED")
        self.assertIn("4111", codes)  # nothing deleted
        import server
        self.assertTrue(server.admin_only("POST", "/api/accounts/import"))

if __name__ == "__main__":
    unittest.main()
