"""2.9.96: family changes during the year - the spouse counts from the month of the marriage and a new child from the
month of birth (salary-tax family deduction, NSSF family allowance and retro months)."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from database import Database


class FamilyDatesTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        self.db = Database(Path(folder.name) / "f.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.db.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-12-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)
        self.db.apply_lebanese_payroll_rules(1)
        # one child born in 2020 (no date given) and a new baby on 10-05-2026; married on 15-04-2026
        self.rami = self.db.save_employee({"employee_number": "100000001", "full_name": "Rami", "currency": "LBP", "base_salary": "150000000",
                                           "hire_date": "01-01-2020", "marital_status": "married", "children": "2",
                                           "marriage_date": "15-04-2026", "children_birth_dates": "10-05-2026"}, 1)

    def month(self, day):
        return self.db.calculate_payroll({"employee_id": self.rami["id"], "period_date": day})

    def test_family_counted_from_the_month_of_the_event(self):
        self.assertEqual((self.rami["marriage_date"], self.rami["children_birth_dates"]), ("2026-04-15", "2026-05-10"))
        march, april, may = self.month("31-03-2026"), self.month("30-04-2026"), self.month("31-05-2026")
        # salary-tax family deduction (Law 324/2024): single 450M, spouse 225M, child 45M a year
        self.assertEqual([Decimal(str(m["family_deduction_lbp"])) for m in (march, april, may)],
                         [Decimal(450000000 + 45000000), Decimal(450000000 + 225000000 + 45000000), Decimal(450000000 + 225000000 + 90000000)])
        self.assertGreater(march["income_tax"], april["income_tax"]); self.assertGreater(april["income_tax"], may["income_tax"])
        # NSSF family allowance: 1 child (July 2025 rates), + spouse, then 2 children at the May 2026 rates
        self.assertEqual([m["family_allowance"] for m in (march, april, may)], [660000.0, 1860000.0, 2100000.0 + 2 * 1155000.0])
        self.assertTrue(any("Married on 15-04-2026" in n for n in march["compliance_notes"]))
        self.assertTrue(any("New child born 10-05-2026" in n for n in may["compliance_notes"]))

    def test_listed_children_and_bad_dates(self):
        more = self.db.save_employee({"employee_number": "100000002", "full_name": "Lina", "currency": "LBP", "base_salary": "50000000",
                                      "children": "0", "children_birth_dates": "01-02-2019; 03-04-2021"}, 1)
        self.assertEqual(more["children"], 2)  # every child listed is counted
        with self.assertRaises(ValueError): self.db.save_employee({"employee_number": "100000003", "full_name": "X", "currency": "LBP", "marriage_date": "31-02-2026"}, 1)
        married, children, _notes = self.db.family_on({"marital_status": "single", "children": 0, "marriage_date": "2026-01-10", "children_birth_dates": ""}, "2026-01-31")
        self.assertEqual((married, children), (True, 0))  # the marriage date wins over the status


if __name__ == "__main__":
    unittest.main()
