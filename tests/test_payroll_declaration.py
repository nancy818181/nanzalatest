"""2.9.44: payroll like the official declaration workbooks - allowances on R6 lines, register, official boxes,
audit statement, monthly / YTD movement, monthly payroll sheet."""
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import lebanese_payroll
import payroll_lines as PL
from database import Database
from payroll_reports import build_payroll_report


class _Base(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.folder.name) / "c_2026.db")); self.db.initialize("StrongPass123")
        self.db.save_payroll_periods(lebanese_payroll.official_periods(), 1)

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        try: self.folder.cleanup()
        except OSError: pass

    def employee(self, **extra):
        item = {"full_name": "Emp A", "employee_number": "1000", "currency": "LBP", "base_salary": "60000000", "hire_date": "01-01-2026",
                "mof_number": "11", "nssf_number": "22"}
        item.update(extra)
        return self.db.save_employee(item, 1)


class AllowanceCalculationTest(_Base):
    def test_taxable_allowances_raise_tax_and_nssf_exempt_ones_do_not(self):
        e = self.employee()
        plain = self.db.calculate_payroll({"employee_id": e["id"], "period_date": "31-01-2026"})
        exempt = self.db.calculate_payroll({"employee_id": e["id"], "period_date": "31-01-2026", "allowances": {"food_exempt": "5000000"}})
        taxable = self.db.calculate_payroll({"employee_id": e["id"], "period_date": "31-01-2026", "allowances": {"housing": "5000000"}})
        self.assertEqual(exempt["gross_salary"], plain["gross_salary"] + 5000000)
        self.assertEqual((exempt["income_tax"], exempt["employee_nssf"]), (plain["income_tax"], plain["employee_nssf"]))
        self.assertGreater(taxable["income_tax"], plain["income_tax"]); self.assertGreater(taxable["employee_nssf"], plain["employee_nssf"])
        self.assertEqual(exempt["net_salary"], plain["net_salary"] + 5000000)

    def test_one_off_grant_is_taxed_like_a_bonus(self):
        e = self.employee()
        grant = self.db.calculate_payroll({"employee_id": e["id"], "period_date": "31-01-2026", "allowances": {"marriage_taxable": "30000000"}})
        bonus = self.db.calculate_payroll({"employee_id": e["id"], "period_date": "31-01-2026", "bonus": "30000000"})
        self.assertEqual(grant["income_tax"], bonus["income_tax"])

    def test_company_can_mark_a_taxable_allowance_not_subject_to_nssf(self):
        e = self.employee()
        with self.db.connect() as db:
            db.execute("INSERT INTO app_settings(key,value) VALUES('payroll_allowances_not_nssf',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(["car"]),))
        plain = self.db.calculate_payroll({"employee_id": e["id"], "period_date": "31-01-2026"})
        car = self.db.calculate_payroll({"employee_id": e["id"], "period_date": "31-01-2026", "allowances": {"car": "5000000"}})
        self.assertEqual(car["employee_nssf"], plain["employee_nssf"]); self.assertGreater(car["income_tax"], plain["income_tax"])

    def test_nssf_branches_switched_off_in_the_register(self):
        e = self.employee(nssf_no_end_service="1", nssf_no_family="1")
        result = self.db.calculate_payroll({"employee_id": e["id"], "period_date": "31-01-2026"})
        self.assertEqual((result["employer_end_service"], result["employer_family"]), (0, 0)); self.assertGreater(result["employer_medical"], 0)

    def test_bad_allowances_are_refused(self):
        e = self.employee()
        for bad in ({"unknown": "1"}, {"car": "-5"}, {"car": "abc"}):
            with self.assertRaises(ValueError): self.db.calculate_payroll({"employee_id": e["id"], "period_date": "31-01-2026", "allowances": bad})

    def test_saved_and_posted_with_allowances_balanced_and_cumulative(self):
        e = self.employee()
        jan = self.db.save_payroll({"employee_id": e["id"], "period_date": "31-01-2026", "allowances": {"housing": "10000000", "food_exempt": "2000000"}}, 1)
        self.assertEqual(json.loads(jan["allowances"]), {"housing": 10000000.0, "food_exempt": 2000000.0})
        self.db.post_payroll(jan["id"], 1)
        self.assertEqual(self.db.unbalanced_entries(), [])
        feb_same = self.db.calculate_payroll({"employee_id": e["id"], "period_date": "28-02-2026", "allowances": {"housing": "10000000", "food_exempt": "2000000"}})
        self.assertAlmostEqual(feb_same["income_tax"], float(jan["income_tax"]), delta=10000)  # cumulative method sees January's allowance


class RegisterTest(_Base):
    def test_register_fields_are_saved_kept_and_checked(self):
        e = self.employee(unit_code="01", unit_name="Admin", cost_of_living="1,000,000", nssf_no_medical="yes", addr_town="Beirut", leave_reason="")
        row = next(r for r in self.db.list_employees() if r["id"] == e["id"])
        self.assertEqual((row["unit_code"], row["cost_of_living"], row["nssf_no_medical"], row["addr_town"]), ("01", "1000000", "1", "Beirut"))
        self.db.save_employee({**{k: row[k] for k in ("full_name", "employee_number", "currency", "base_salary")}, "id": e["id"]}, 1)
        again = next(r for r in self.db.list_employees() if r["id"] == e["id"])
        self.assertEqual(again["unit_code"], "01")  # saving without the field keeps it
        with self.assertRaises(ValueError): self.employee(employee_number="1000", cost_of_living="-1")


class OfficialStatementsTest(_Base):
    def setUp(self):
        super().setUp()
        self.e = self.employee(marital_status="married", children="2", unit_code="01")
        self.m = self.employee(full_name="Mgr B", currency="USD", base_salary="2000", employee_group="manager", leave_date="31-03-2026", leave_reason="resigned")
        for month in ("31-01-2026", "28-02-2026", "31-03-2026"):
            for emp, allowances, transport in ((self.e, {"housing": "10000000", "food_exempt": "2000000"}, "5000000"), (self.m, {"car": "300"}, "0")):
                p = self.db.save_payroll({"employee_id": emp["id"], "period_date": month, "transport": transport, "allowances": allowances}, 1)
                self.db.post_payroll(p["id"], 1)

    def rows(self, report, period="yearly", index=1):
        return build_payroll_report(self.db, report, period, 2026, index)

    def test_r6_lines_split_taxable_and_not(self):
        r6 = self.rows("R6_LINES")
        lines = {row[0]: row for row in r6["sections"][0]["rows"]}
        self.assertEqual(lines["170"][3:], [Decimal(30000000), Decimal(0), Decimal(30000000)])
        self.assertEqual(lines["180"][3:], [Decimal(6000000), Decimal(6000000), Decimal(0)])
        self.assertEqual(lines["150"][4], Decimal(15000000))  # transport within the exempt daily amount
        self.assertEqual(lines["330"][5], Decimal(191250000))  # (450M + 225M + 2 x 45M) x 3 / 12

    def test_r5_boxes_add_up_and_split_managers_from_employees(self):
        body = {row[0]: row for row in self.rows("R5_BOXES")["sections"][0]["rows"]}
        self.assertEqual((body["70"][3], body["80"][4]), (1, 1))
        for column in (3, 4):
            self.assertEqual(body["120"][column], body["100"][column] + body["110"][column])
            self.assertEqual(body["160"][column], body["120"][column] - body["130"][column] - body["140"][column] - body["150"][column])
            self.assertEqual(body["180"][column], body["160"][column] - body["170"][column])
        self.assertEqual(body["110"][3], Decimal(300 * 89500 * 3))  # manager's car allowance in LBP

    def test_r10_quarter_equals_r5_when_all_pay_is_in_the_quarter(self):
        r5 = {row[0]: row for row in self.rows("R5_BOXES")["sections"][0]["rows"]}
        r10 = {row[0]: row for row in self.rows("R10_BOXES", "quarterly", 1)["sections"][0]["rows"]}
        self.assertEqual(r10["190"][2:], r5["190"][2:]); self.assertEqual(r10["270"][4], r5["260"][4])

    def test_audit_statement_reconciles(self):
        audit = self.rows("AUDIT")
        self.assertTrue(audit["ok"], audit["sections"][2]["rows"])

    def test_movement_month_and_year_to_date(self):
        movement = self.rows("MOVEMENT", "monthly", 3)["sections"][0]
        employee = next(row for row in movement["rows"] if row[1] == "Emp A")
        self.assertEqual(employee[5], Decimal(60000000)); self.assertEqual(employee[12], Decimal(3) * employee[8])  # YTD = 3 equal months

    def test_registers(self):
        register = self.rows("REGISTER")["sections"][0]["rows"]
        self.assertEqual(len(register), 2)
        leavers = self.rows("LEAVERS")["sections"][0]["rows"]
        self.assertEqual([(r[1], r[-1]) for r in leavers], [("Mgr B", "resigned")])


class PayrollSheetTest(_Base):
    def test_rows_payloads_and_window(self):
        import desktop_payroll_sheet as S
        e = self.employee(cost_of_living="1000000", representation_exempt="500000")
        left = self.employee(full_name="Left Before", leave_date="31-12-2025", hire_date="01-01-2025")
        start, end = S.month_bounds("03-2026"); self.assertEqual((start, end), ("2026-03-01", "2026-03-31"))
        rows = S.sheet_rows(self.db.list_employees(), [], start, end)
        self.assertEqual([r["name"] for r in rows], ["Emp A"])  # left before the month: not listed
        self.assertEqual((rows[0]["cost_of_living"], rows[0]["representation_exempt"], rows[0]["status"]), ("1,000,000", "500,000", "new"))
        payload = S.payload_for(rows[0], end)
        self.assertEqual(payload["allowances"], {"cost_of_living": "1000000", "representation_exempt": "500000"})
        saved = self.db.save_payroll(payload, 1)
        again = S.sheet_rows(self.db.list_employees(), self.db.list_payroll(), start, end)
        self.assertEqual((again[0]["status"], again[0]["cost_of_living"], again[0]["payroll_id"]), ("draft", "1,000,000", saved["id"]))
        with self.assertRaises(ValueError): S.month_bounds("13-2026")
        self.assertIsNotNone(left)

    def test_sheet_window_calculates_saves_and_posts(self):
        try:
            import tkinter as tk
            import desktop
        except ImportError as exc: self.skipTest(f"tkinter not available: {exc}")
        e = self.employee()
        db = self.db

        class Client:
            employees = lambda self: db.list_employees()
            payroll = lambda self, a=None, b=None: db.list_payroll(a, b)
            calculate_payroll = lambda self, item: db.calculate_payroll(item)
            save_payroll = lambda self, item: db.save_payroll(item, 1)
            post_payroll = lambda self, pid: db.post_payroll(pid, 1)

        class App(desktop.PayrollSheetMixin, tk.Tk):
            fit_dialog = desktop.SaberApp.fit_dialog; action_button = desktop.SaberApp.action_button
            load_payroll = lambda self: None

        try: app = App()
        except tk.TclError as exc: self.skipTest(f"no display: {exc}")
        try:
            app.withdraw(); app.client = Client()
            import desktop_payroll_sheet as S
            from unittest.mock import patch
            with patch.object(S, "datetime") as fake_now:
                fake_now.now.return_value.strftime.return_value = "01-2026"
                window = app.open_payroll_sheet()
            buttons = {w.cget("text"): w for w in window.winfo_children()[0].winfo_children() if isinstance(w, tk.Button)}
            buttons["Calculate All"].invoke(); buttons["Save All (draft)"].invoke()
            self.assertEqual(db.list_payroll()[0]["status"], "draft")
            with patch("desktop_payroll_sheet.messagebox.askyesno", return_value=True): buttons["Post All"].invoke()
            self.assertEqual(db.list_payroll()[0]["status"], "posted")
            window.destroy()
        finally: app.destroy()
        self.assertIsNotNone(e)


class CatalogueTest(unittest.TestCase):
    def test_every_allowance_sits_on_an_r6_line(self):
        for code, (line, *_rest) in PL.ALLOWANCES.items(): self.assertIn(line, PL.LINE_NAMES, code)
        self.assertEqual(set(PL.SALARY_LINES) | set(PL.BENEFIT_LINES), set(PL.LINE_NAMES))


if __name__ == "__main__":
    unittest.main()
