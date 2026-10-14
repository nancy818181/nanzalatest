"""2.9.78: retro salary tax on the month's real pay, cash account for selected rows, DOE in EUR, daily AED / SAR rates."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

import ledger_reports
from database import Database


class _Book(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "company.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)


class RetroTaxTest(_Book):
    def test_retro_is_taxed_with_the_pay_of_its_month_less_the_tax_already_withheld(self):
        employee = self.db.save_employee({"full_name": "Rami", "base_salary": "2000", "currency": "USD", "hire_date": "01-01-2025", "marital_status": "single"}, 1)
        employee_id = employee["id"] if isinstance(employee, dict) else employee
        january = self.db.save_payroll({"employee_id": employee_id, "period_date": "31-01-2026"}, 1)
        self.assertEqual(Decimal(str(january["income_tax_lbp"])), Decimal("7060000"))   # 179,000,000 LBP a month, single
        february = self.db.calculate_payroll({"employee_id": employee_id, "period_date": "28-02-2026", "retro_salary": "500",
                                              "retro_from": "01-01-2026", "retro_to": "31-01-2026"})
        # January with the retro: 223,750,000 LBP -> 11,637,500 tax a month; 7,060,000 was already withheld
        self.assertEqual(Decimal(str(february["retro_tax_lbp"])), Decimal("4577500"))
        self.assertTrue(any("already withheld" in note for note in february["compliance_notes"]))


class CashAccountForSelectedTest(_Book):
    def test_paid_invoices_move_to_the_new_cash_account_unpaid_ones_are_listed(self):
        with self.db.connect() as db: db.execute("INSERT INTO accounts(code,name_en,type) VALUES('512100009','Bank Test','asset')")
        paid = self.db.import_invoice({"invoice_number": "P-1", "invoice_date": "10-02-2026", "party_name": "Supp", "kind": "purchase", "currency": "USD",
                                       "subtotal": 100, "vat": 11, "total": 111, "payment_method": "Cash", "amount_paid": 111}, 1)
        unpaid = self.db.import_invoice({"invoice_number": "P-2", "invoice_date": "10-02-2026", "party_name": "Supp", "kind": "purchase", "currency": "USD",
                                         "subtotal": 100, "vat": 11, "total": 111}, 1)
        ids = [x["id"] if isinstance(x, dict) else x for x in (paid, unpaid)]
        result = self.db.set_invoices_account(ids, "payment_account", "512100009", 1)
        self.assertEqual(result["done"], ["P-1"]); self.assertIn("not paid", result["skipped"][0])
        with self.db.connect() as db:
            codes = {r[0] for r in db.execute("""SELECT a.code FROM journal_lines j JOIN accounts a ON a.id=j.account_id JOIN journal_entries e ON e.id=j.entry_id
                                                 WHERE e.source_type='invoice_payment'""")}
        self.assertIn("512100009", codes); self.assertNotIn("531", codes)


class EuroDoeTest(_Book):
    def test_doe_in_eur_moves_only_the_eur_value(self):
        self.db.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-01-2026", "from_currency": "EUR", "to_currency": "USD", "rate": "1.25"}, 1)
        self.db.save_exchange_rate({"date_from": "01-03-2026", "date_to": "31-03-2026", "from_currency": "EUR", "to_currency": "USD", "rate": "1.0"}, 1)
        with self.db.connect() as db: db.execute("INSERT INTO accounts(code,name_en,type) VALUES('512100009','Bank USD','asset')")
        self.db.save_journal_voucher({"entry_date": "10-01-2026", "currency": "USD", "description": "capital"},
                                     [{"account_code": "512100009", "debit": "1000", "credit": "0"}, {"account_code": "101", "debit": "0", "credit": "1000"}], 1)
        row = next(r for r in self.db.doe_candidates("31-03-2026", "EUR")["items"] if r["account"] == "512100009")
        self.assertEqual((row["currency"], row["carrying"], row["suggested_rate"]), ("USD", "800.00", "1"))
        self.db.save_journal_voucher({"entry_date": "31-03-2026", "currency": "EUR", "description": "DOE EUR", "voucher_type": "07", "doe_basis": "EUR"},
                                     [{"account_code": "512100009", "debit": "200", "native_currency": "USD"}, {"account_code": "775100000", "credit": "200"}], 1)
        self.assertEqual(next(r for r in self.db.doe_candidates("31-03-2026", "EUR")["items"] if r["account"] == "512100009")["carrying"], "1000.00")
        report = ledger_reports.build_account_report(self.db, {"date_from": "01-01-2026", "date_to": "31-12-2026", "first_column": "EUR", "second_column": "USD"})
        rows = {r[0]: r for r in report["sections"][0]["rows"]}
        headers = report["sections"][0]["headers"]
        eur, usd = headers.index("Balance (EUR)"), headers.index("Balance (USD)")
        self.assertEqual((rows["512100009"][eur], rows["512100009"][usd]), (Decimal("1000.00"), Decimal("1000.00")))   # USD books unchanged
        self.assertEqual((rows["775100000"][eur], rows["775100000"][usd]), (Decimal("-200.00"), Decimal("0.00")))      # gain only in EUR
        self.assertEqual(rows["GRAND TOTAL"][eur], Decimal("0.00"))


class DailyGulfRatesTest(_Book):
    def test_aed_and_sar_have_a_rate_every_day(self):
        self.assertIn("SAR", self.db.currency_codes())
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.db.sync_historical_exchange_rates()
        self.assertEqual(self.db._converted_amount(100, "SAR", "LBP", "15-03-2025"), Decimal("2386667.00"))
        self.assertEqual(self.db._converted_amount(100, "AED", "LBP", "15-03-2025"), Decimal("2437032.00"))
        with self.db.connect() as db:
            days = db.execute("SELECT COUNT(DISTINCT rate_date) FROM exchange_rates WHERE from_currency='SAR' AND to_currency='USD'").fetchone()[0]
            usd_days = db.execute("SELECT COUNT(DISTINCT rate_date) FROM exchange_rates WHERE from_currency='USD' AND to_currency='LBP'").fetchone()[0]
        self.assertEqual(days, usd_days)


if __name__ == "__main__":
    unittest.main()
