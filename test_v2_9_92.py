"""2.9.92: Budget Law 2026 (Law 40, 10-02-2026) - no input VAT on utilities; VAT on passenger cars deductible on a cost
up to USD 30,000 (Art. 30); food allowance exempt up to LBP 300,000 a working day (Art. 26)."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import vat_return
from database import Database


class Budget2026Test(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        self.db = Database(Path(folder.name) / "b.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.db.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-12-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)
        self.db.save_settings({"base_currency": "USD", "vat_ratio_method": "quarter"}, 1)

    def expense(self, day, amount, vat, use, account="6262"):
        return self.db.add_expense({"expense_date": day, "description": f"{use} {day}", "currency": "USD", "with_vat_subtotal": str(amount), "vat": str(vat),
                                    "expense_account": account, "payment_account": "512", "vat_use": use}, 1)

    def test_utilities_and_passenger_car(self):
        self.db.create_manual_invoice({"invoice_date": "15-05-2026", "party_name": "Client", "kind": "sales", "currency": "USD", "status": "posted"},
                                      [{"description": "S", "quantity": 1, "unit_price": 100000, "vat_rate": 11}], 1)
        self.expense("20-01-2026", 1000, 110, "utilities")        # before the law: deductible
        self.expense("20-05-2026", 1000, 110, "utilities")        # after: not deductible
        self.db.create_manual_invoice({"invoice_date": "25-05-2026", "party_name": "Car dealer", "kind": "assets", "currency": "USD", "status": "posted",
                                       "expense_account": "2245", "vat_use": "passenger_car"},
                                      [{"description": "Car", "quantity": 1, "unit_price": 40000, "vat_rate": 11}], 1)
        q2 = vat_return.build_vat_return(self.db, 2026, 2)
        restricted = q2["totals_lbp"]["restricted"]
        self.assertEqual(restricted, Decimal(110 * 89500) + Decimal(1100 * 89500))  # utilities 110 + car 4,400 x 10,000 / 40,000
        docs = {d["number"]: d for d in q2["documents"] if d["category"] != "sales"}
        self.assertTrue(any("75.00% (2026 rule)" == d["deductible_share"] for d in docs.values()))
        q1 = vat_return.build_vat_return(self.db, 2026, 1)
        self.assertNotIn("restricted", q1["totals_lbp"])  # January: before the law
        lines = vat_return.settlement_lines(self.db, q2)["lines"]
        nd = [l for l in lines if l["account_code"] == "6459" and "2026" in l["description"]]
        self.assertEqual(Decimal(nd[0]["amount"]), restricted)

    def test_food_allowance_limit(self):
        self.db.apply_lebanese_payroll_rules(1)
        rami = self.db.save_employee({"employee_number": "100000001", "full_name": "Rami", "currency": "LBP", "base_salary": "60000000", "hire_date": "01-01-2020"}, 1)
        calc = self.db.calculate_payroll({"employee_id": rami["id"], "period_date": "31-03-2026", "transport_days": "20", "allowances": {"food_exempt": "8000000"}})
        self.assertEqual((Decimal(str(calc["allowances"]["food_exempt"])), Decimal(str(calc["allowances"]["food_taxable"]))), (Decimal("6000000"), Decimal("2000000")))
        self.assertTrue(any("Budget Law 2026" in n for n in calc["compliance_notes"]))
        before = self.db.calculate_payroll({"employee_id": rami["id"], "period_date": "31-01-2026", "transport_days": "20", "allowances": {"food_exempt": "8000000"}})
        self.assertEqual(Decimal(str(before["allowances"]["food_exempt"])), Decimal("8000000"))


if __name__ == "__main__":
    unittest.main()
