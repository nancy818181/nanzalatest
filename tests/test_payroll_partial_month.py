"""Partial-month payroll uses hire/leave dates and prorates monthly tax bands."""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from database import Database


class PartialMonthPayrollTest(unittest.TestCase):
    def test_may_hire_prorates_base_salary_and_income_tax(self):
        with TemporaryDirectory() as folder:
            db=Database(Path(folder)/"company.db")
            db.initialize("secret12345")
            with db.connect() as connection:
                user=connection.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            db.apply_lebanese_payroll_rules(user)
            settings=db.payroll_settings_for("2026-05-31")
            db.save_payroll_settings({**settings,"tax_rounding":"0"},user)
            full=db.save_employee({"full_name":"Full Month","base_salary":"120000000",
                "currency":"LBP","hire_date":"01-01-2026"},user)
            partial=db.save_employee({"full_name":"Mid May","base_salary":"120000000",
                "currency":"LBP","hire_date":"16-05-2026"},user)
            whole=db.calculate_payroll({"employee_id":full["id"],"period_date":"31-05-2026"})
            short=db.calculate_payroll({"employee_id":partial["id"],"period_date":"31-05-2026"})
            self.assertEqual((short["worked_days"],short["calendar_days"]),(16,31))
            self.assertEqual(short["salary"],float((Decimal(120000000)*16/31).quantize(Decimal("0.01"))))
            tax_fraction=Decimal(15)/30  # May 16-31 is 15 days on the statutory 30-day month
            annualized=Decimal(str(short["salary"]))*12/tax_fraction
            annual_tax=db._progressive_tax(max(Decimal(0),annualized-Decimal(settings["single_allowance"])),settings["tax_brackets"])
            self.assertAlmostEqual(short["income_tax_lbp"],float(annual_tax*tax_fraction/12),delta=0.02)
            actual=db.calculate_payroll({"employee_id":partial["id"],"period_date":"31-05-2026",
                "salary":"70000000"})
            self.assertEqual(actual["salary"],70000000)
            self.assertEqual(actual["worked_days"],16)

    def test_actual_days_across_28_29_30_and_31_day_months(self):
        import calendar
        with TemporaryDirectory() as folder:
            db=Database(Path(folder)/"company.db"); db.initialize("secret12345")
            self.addCleanup(db.release)
            for year,month in ((2026,2),(2024,2),(2026,4),(2026,5)):
                count=calendar.monthrange(year,month)[1]
                employee=db.save_employee({"full_name":f"Partial {year}-{month}","base_salary":str(count*1000000),
                    "currency":"LBP","hire_date":f"10-{month:02d}-{year}","leave_date":f"{count-4:02d}-{month:02d}-{year}"},1)
                result=db.calculate_payroll({"employee_id":employee["id"],"period_date":f"{count:02d}-{month:02d}-{year}"})
                self.assertEqual(result["worked_days"],count-13)
                self.assertEqual(result["salary"],(count-13)*1000000)
                self.assertLessEqual(result["transport_days"],result["worked_days"])
                with self.assertRaisesRegex(ValueError,"employment period"):
                    db.calculate_payroll({"employee_id":employee["id"],"period_date":f"{count:02d}-{month:02d}-{year}","transport_days":count})
                with self.assertRaisesRegex(ValueError,"whole number"):
                    db.calculate_payroll({"employee_id":employee["id"],"period_date":f"{count:02d}-{month:02d}-{year}","transport_days":"1.5"})

    def test_leave_date_and_month_without_employment(self):
        with TemporaryDirectory() as folder:
            db=Database(Path(folder)/"company.db")
            db.initialize("secret12345")
            with db.connect() as connection:
                user=connection.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            employee=db.save_employee({"full_name":"Leaving","base_salary":"31000000",
                "currency":"LBP","hire_date":"01-01-2026","leave_date":"10-05-2026"},user)
            result=db.calculate_payroll({"employee_id":employee["id"],"period_date":"31-05-2026"})
            self.assertEqual(result["worked_days"],10)
            self.assertEqual(result["salary"],10000000)
            with self.assertRaisesRegex(ValueError,"did not work"):
                db.calculate_payroll({"employee_id":employee["id"],"period_date":"30-06-2026"})


if __name__=="__main__":
    unittest.main()
