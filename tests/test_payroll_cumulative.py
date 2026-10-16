"""Cumulative withholding and the annual schooling tax exemption."""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from database import Database


class CumulativePayrollTest(unittest.TestCase):
    def test_variable_pay_uses_prior_withholding(self):
        with TemporaryDirectory() as folder:
            db=Database(Path(folder)/"company.db"); db.initialize("secret12345")
            with db.connect() as c: user=c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            db.apply_lebanese_payroll_rules(user)
            rules=db.payroll_settings_for("2026-06-30")
            db.save_payroll_settings({**rules,"tax_rounding":"0"},user)
            employee=db.save_employee({"full_name":"Variable pay","base_salary":"120000000",
                "currency":"LBP","hire_date":"01-01-2026"},user)
            first=db.save_payroll({"employee_id":employee["id"],"period_date":"31-05-2026"},user)
            second=db.calculate_payroll({"employee_id":employee["id"],"period_date":"30-06-2026",
                "salary":"200000000"})
            elapsed=Decimal(2)/12
            brackets=[[Decimal(str(ceiling))*elapsed if ceiling is not None else None,rate]
                      for ceiling,rate in rules["tax_brackets"]]
            expected=db._progressive_tax(Decimal(320000000)-Decimal(rules["single_allowance"])*elapsed,brackets)
            self.assertAlmostEqual(second["income_tax_lbp"],float(expected)-float(first["income_tax_lbp"]),delta=0.02)

    def test_three_months_deduct_both_previous_months(self):
        with TemporaryDirectory() as folder:
            db=Database(Path(folder)/"company.db"); db.initialize("secret12345")
            with db.connect() as c: user=c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            db.apply_lebanese_payroll_rules(user)
            rules=db.payroll_settings_for("2026-03-31")
            db.save_payroll_settings({**rules,"tax_rounding":"0"},user)
            employee=db.save_employee({"full_name":"Three months","base_salary":"120000000",
                "currency":"LBP","hire_date":"01-01-2026"},user)
            previous=[]
            for day, salary in (("31-01-2026",120000000),("28-02-2026",200000000),("31-03-2026",160000000)):
                current=db.save_payroll({"employee_id":employee["id"],"period_date":day,"salary":str(salary)},user)
                fraction=Decimal(len(previous)+1)/12
                base=sum((Decimal(str(row["salary"])) for row in previous),Decimal(salary))
                bands=[[Decimal(str(cap))*fraction if cap is not None else None,rate] for cap,rate in rules["tax_brackets"]]
                expected=db._progressive_tax(max(Decimal(0),base-Decimal(rules["single_allowance"])*fraction),bands)
                withheld=sum((Decimal(str(row["income_tax_lbp"])) for row in previous),Decimal(0))
                self.assertAlmostEqual(float(current["income_tax_lbp"]),float(expected-withheld),delta=0.02)
                previous.append(current)

    def test_every_month_accumulates_through_december_and_new_year_resets(self):
        import calendar
        with TemporaryDirectory() as folder:
            db=Database(Path(folder)/"company.db"); db.initialize("secret12345")
            with db.connect() as c: user=c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            db.apply_lebanese_payroll_rules(user)
            rules=db.payroll_settings_for("2026-01-31")
            # Disable rounding in every effective settings period, including May's NSSF update.
            for settings in db.list_payroll_settings():
                db.save_payroll_settings({**settings,"tax_rounding":"0"},user)
            employee=db.save_employee({"full_name":"Full year","base_salary":"120000000",
                "currency":"LBP","hire_date":"01-01-2026"},user)
            accumulated=Decimal(0); withheld=Decimal(0)
            for month in range(1,13):
                with self.subTest(month=month):
                    salary=Decimal(120000000+month*5000000)
                    day=f"{calendar.monthrange(2026,month)[1]:02d}-{month:02d}-2026"
                    accumulated+=salary
                    fraction=Decimal(month)/12
                    bands=[[Decimal(str(cap))*fraction if cap is not None else None,rate]
                           for cap,rate in rules["tax_brackets"]]
                    due=db._progressive_tax(max(Decimal(0),accumulated-Decimal(rules["single_allowance"])*fraction),bands)
                    saved=db.save_payroll({"employee_id":employee["id"],"period_date":day,"salary":str(salary)},user)
                    current=Decimal(str(saved["income_tax_lbp"]))
                    self.assertAlmostEqual(float(current),float(due-withheld),delta=0.02)
                    withheld+=current
                    self.assertAlmostEqual(float(withheld),float(due),delta=0.02)
            annual_due=db._progressive_tax(accumulated-Decimal(rules["single_allowance"]),rules["tax_brackets"])
            self.assertAlmostEqual(float(withheld),float(annual_due),delta=0.02)
            # January must not subtract any of the previous year's twelve deductions.
            fresh=db.save_employee({"full_name":"New year control","base_salary":"120000000",
                "currency":"LBP","hire_date":"01-01-2027"},user)
            january={"period_date":"31-01-2027","salary":"180000000"}
            continuing=db.calculate_payroll({**january,"employee_id":employee["id"]})
            new_employee=db.calculate_payroll({**january,"employee_id":fresh["id"]})
            self.assertGreater(continuing["income_tax_lbp"],0)
            self.assertEqual(continuing["income_tax_lbp"],new_employee["income_tax_lbp"])

    def test_partial_first_month_is_not_a_whole_month_in_cumulative_bands(self):
        with TemporaryDirectory() as folder:
            db=Database(Path(folder)/"company.db"); db.initialize("secret12345")
            with db.connect() as c: user=c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            db.apply_lebanese_payroll_rules(user)
            rules=db.payroll_settings_for("2026-06-30")
            db.save_payroll_settings({**rules,"tax_rounding":"0"},user)
            employee=db.save_employee({"full_name":"Partial start","base_salary":"120000000",
                "currency":"LBP","hire_date":"16-05-2026"},user)
            first=db.save_payroll({"employee_id":employee["id"],"period_date":"31-05-2026"},user)
            second=db.calculate_payroll({"employee_id":employee["id"],"period_date":"30-06-2026"})
            fraction=Decimal("1.5")/12
            bands=[[Decimal(str(cap))*fraction if cap is not None else None,rate] for cap,rate in rules["tax_brackets"]]
            taxable=Decimal(str(first["salary"]))+Decimal("120000000")-Decimal(rules["single_allowance"])*fraction
            expected=db._progressive_tax(taxable,bands)-Decimal(str(first["income_tax_lbp"]))
            self.assertAlmostEqual(second["income_tax_lbp"],float(expected),delta=0.02)

    def test_prior_withholding_offsets_bonus_before_current_tax_is_clamped(self):
        with TemporaryDirectory() as folder:
            db=Database(Path(folder)/"company.db"); db.initialize("secret12345")
            with db.connect() as c: user=c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            db.apply_lebanese_payroll_rules(user)
            employee=db.save_employee({"full_name":"Prior withholding","base_salary":"120000000","currency":"LBP"},user)
            first=db.save_payroll({"employee_id":employee["id"],"period_date":"31-01-2026"},user)
            with db.connect() as c:
                c.execute("UPDATE payroll_records SET income_tax_lbp='1000000000' WHERE id=?",(first["id"],))
            second=db.calculate_payroll({"employee_id":employee["id"],"period_date":"28-02-2026","bonus":"10000000"})
            self.assertEqual(second["income_tax_lbp"],0)
            self.assertTrue(any("already withheld" in note for note in second["compliance_notes"]))

    def test_duplicate_month_and_changes_before_posted_month_are_refused(self):
        with TemporaryDirectory() as folder:
            db=Database(Path(folder)/"company.db"); db.initialize("secret12345")
            with db.connect() as c: user=c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            db.apply_lebanese_payroll_rules(user)
            employee=db.save_employee({"full_name":"Monthly guard","currency":"LBP","base_salary":"120000000"},user)
            db.save_payroll({"employee_id":employee["id"],"period_date":"31-01-2026"},user)
            with self.assertRaisesRegex(ValueError,"already saved"):
                db.save_payroll({"employee_id":employee["id"],"period_date":"15-01-2026"},user)
            feb=db.save_payroll({"employee_id":employee["id"],"period_date":"28-02-2026"},user)
            # A draft after an earlier change must be recalculated before it is posted.
            db.save_payroll({"employee_id":employee["id"],"period_date":"31-01-2026","salary":"400000000"},user)
            with self.assertRaisesRegex(ValueError,"outdated"):
                db.post_payroll(feb["id"],user)
            feb=db.save_payroll({"employee_id":employee["id"],"period_date":"28-02-2026"},user)
            db.post_payroll(feb["id"],user)
            with self.assertRaisesRegex(ValueError,"later payroll.*posted"):
                db.save_payroll({"employee_id":employee["id"],"period_date":"31-01-2026","salary":"120000000"},user)
            self.assertEqual(len(db.list_payroll()),2)

    def test_schooling_exemption_is_annual_remaining_balance(self):
        with TemporaryDirectory() as folder:
            db=Database(Path(folder)/"company.db"); db.initialize("secret12345")
            with db.connect() as c: user=c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            db.apply_lebanese_payroll_rules(user)
            employee=db.save_employee({"full_name":"Parent","base_salary":"50000000","children":1,
                "currency":"LBP"},user)
            first=db.save_payroll({"employee_id":employee["id"],"period_date":"31-01-2026",
                "schooling":"5000000"},user)
            second=db.calculate_payroll({"employee_id":employee["id"],"period_date":"28-02-2026",
                "schooling":"5000000"})
            self.assertEqual(float(first["exempt_schooling"]),5000000)
            self.assertEqual(second["exempt_schooling"],1000000)


if __name__=="__main__":
    unittest.main()
