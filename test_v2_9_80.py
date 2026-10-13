"""2.9.80: findings of the full-year accounting test - payroll on 6311 / 6351, VAT credit through unsaved quarters,
planning tools in every currency, ageing with unallocated receipts, item cost account on every path."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import inventory
import vat_return
from database import Database


class _Book(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "books.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.db.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)

    def lines(self, source_type):
        return sorted((r["account_code"], r["debit"], r["credit"]) for r in self.db.journal() if r["source_type"] == source_type)


class PayrollAccountsTest(_Book):
    def test_salaries_on_6311_and_employer_nssf_on_6351(self):
        self.db.apply_lebanese_payroll_rules(1)
        employee = self.db.save_employee({"employee_number": "1000", "full_name": "Rami", "currency": "LBP", "base_salary": "89500000", "nssf_number": "1", "mof_number": "2"}, 1)
        self.assertIsNone(employee.get("salary_account"))  # empty = the Standard Posting Accounts
        saved = self.db.save_payroll({"employee_id": employee["id"], "period_date": "31-01-2025"}, 1); self.db.post_payroll(saved["id"], 1)
        codes = {code for code, _d, _c in self.lines("payroll")}
        self.assertIn("6311", codes); self.assertIn("6351", codes)
        self.assertFalse({"621100001", "621100002"} & codes)

    def test_manager_on_6316_and_a_chosen_account_is_kept(self):
        self.db.apply_lebanese_payroll_rules(1)
        manager = self.db.save_employee({"employee_number": "2000", "full_name": "Manager", "currency": "LBP", "base_salary": "89500000", "employee_group": "manager"}, 1)
        chosen = self.db.save_employee({"employee_number": "3000", "full_name": "Worker", "currency": "LBP", "base_salary": "50000000", "salary_account": "6312 - Manpower Wages"}, 1)
        for employee in (manager, chosen):
            saved = self.db.save_payroll({"employee_id": employee["id"], "period_date": "31-01-2025"}, 1); self.db.post_payroll(saved["id"], 1)
        codes = {code for code, _d, _c in self.lines("payroll")}
        self.assertTrue({"6316", "6312"} <= codes)

    def test_old_automatic_account_is_cleared_once(self):
        employee = self.db.save_employee({"full_name": "Old", "currency": "LBP", "base_salary": "1"}, 1)
        with self.db.connect() as db:
            db.execute("UPDATE employees SET salary_account='621100001' WHERE id=?", (employee["id"],))
            db.execute("DELETE FROM app_settings WHERE key='payroll_accounts_2980'")
        self.db.apply_lebanese_payroll_rules(1)
        with self.db.connect() as db:  # an older version wrote the staff map (6311) as the managers' map
            db.execute("UPDATE payroll_settings SET manager_account_map=employee_account_map")
            db.execute("DELETE FROM app_settings WHERE key='payroll_accounts_2980'")
        self.db.initialize("secret12345")  # the upgrade runs when the books are opened
        with self.db.connect() as db:
            self.assertIsNone(db.execute("SELECT salary_account FROM employees WHERE id=?", (employee["id"],)).fetchone()[0])
        self.assertEqual(self.db.payroll_settings_for("31-01-2025")["manager_account_map"]["salary"], "6316")


class VatCreditChainTest(_Book):
    def invoice(self, number, kind, subtotal, vat, day):
        self.db.import_invoice({"invoice_number": number, "invoice_date": day, "party_name": f"P {kind}", "kind": kind, "currency": "LBP",
                                "subtotal": subtotal, "vat": vat, "total": subtotal + vat}, 1)

    def test_credit_of_q1_reaches_q3_when_q2_is_not_saved(self):
        self.invoice("P-1", "purchase", 10000000, 1100000, "15-02-2025")  # Q1: credit 1,100,000
        self.invoice("S-1", "sale", 2000000, 220000, "15-08-2025")        # Q3: 220,000 output
        vat_return.save_return(self.db, 2025, 1, 1)
        q3 = vat_return.build_vat_return(self.db, 2025, 3)
        self.assertEqual(q3["credit_brought_forward_lbp"], Decimal("1100000"))
        self.assertEqual((q3["payable_lbp"], q3["credit_carried_forward_lbp"]), (Decimal("0"), Decimal("880000")))
        self.assertIn("not saved", q3["credit_source"])
        self.assertTrue(any("Q2 2025 is not saved" in w for w in q3["warnings"]))

    def test_nothing_before_the_first_document(self):
        self.invoice("S-1", "sale", 1000000, 110000, "15-05-2025")
        q2 = vat_return.build_vat_return(self.db, 2025, 2)
        self.assertEqual((q2["credit_brought_forward_lbp"], q2["credit_source"]), (Decimal("0"), "none"))


class ConvertedPlanningTest(_Book):
    def test_lbp_payroll_and_sales_are_in_the_usd_planning_figures(self):
        self.db.import_invoice({"invoice_number": "S-USD", "invoice_date": "10-01-2025", "party_name": "A", "kind": "sale", "currency": "USD", "subtotal": 1000, "vat": 0, "total": 1000}, 1)
        self.db.import_invoice({"invoice_number": "S-LBP", "invoice_date": "11-01-2025", "party_name": "B", "kind": "sale", "currency": "LBP", "subtotal": 89500000, "vat": 0, "total": 89500000}, 1)
        entered = sum(r["amount"] for r in self.db.profit_and_loss("2025-01-01", "2025-12-31", "USD") if r["type"] == "income")
        converted = sum(r["amount"] for r in self.db.profit_and_loss_converted("2025-01-01", "2025-12-31", "USD") if r["type"] == "income")
        self.assertEqual((entered, round(converted, 2)), (1000, 2000))

    def test_converted_cash_flow_leaves_out_the_opening_balances(self):
        self.db.save_journal_voucher({"entry_date": "01-01-2025", "description": "Opening", "currency": "USD", "voucher_type": "04"},
                                     [{"account_code": "531", "line_currency": "USD", "side": "D", "amount": "500"}, {"account_code": "101", "line_currency": "USD", "side": "C", "amount": "500"}], 1)
        self.db.save_journal_voucher({"entry_date": "05-01-2025", "description": "Cash sale", "currency": "LBP"},
                                     [{"account_code": "531", "line_currency": "LBP", "side": "D", "amount": "8950000"}, {"account_code": "713",
                                             "line_currency": "LBP", "side": "C", "amount": "8950000"}], 1)
        flows = self.db.cash_flow_converted("2025-01-01", "2025-12-31", "USD")
        self.assertEqual(round(sum(r["inflow"] for r in flows), 2), 100.0)
        cash = sum(r["balance"] for r in self.db.balance_sheet_converted("2025-12-31", "USD") if r["code"].startswith("5"))
        self.assertEqual(round(cash, 2), 600.0)


class AgeingTest(_Book):
    def test_unallocated_receipt_and_credit_note_settle_the_oldest_invoices(self):
        party = self.db.save_party({"kind": "customer", "name": "Client A", "currency": "USD"}, 1)
        for number, day, amount in (("S-1", "10-01-2025", 300), ("S-2", "10-02-2025", 200)):
            self.db.create_manual_invoice({"invoice_number": number, "invoice_date": day, "party_name": "Client A", "kind": "sales", "currency": "USD", "status": "posted"},
                                          [{"description": "x", "quantity": 1, "unit_price": amount, "vat_rate": 0}], 1)
        self.db.create_manual_invoice({"invoice_date": "15-02-2025", "party_name": "Client A", "kind": "sales", "currency": "USD", "status": "posted", "doc_subtype": "credit_note",
                                       "invoice_number": "CN-1", "supplier_side": "C - Credit", "vat_side": "D - Debit", "expense_side": "D - Debit", "expense_account": "709000001"},
                                      [{"description": "discount", "quantity": 1, "unit_price": 50, "vat_rate": 0}], 1)
        self.db.add_payment({"kind": "customer_receipt", "party_id": party["id"], "payment_date": "01-03-2025", "currency": "USD", "amount": "320", "cash_account": "531"}, 1)
        rows = {r["invoice_number"]: r["outstanding"] for r in self.db.aging_report("31-03-2025", "sale", "USD")}
        self.assertEqual(rows, {"S-2": 130.0})  # 300 + 200 - 50 - 320
        self.db.add_payment({"kind": "customer_receipt", "party_id": party["id"], "payment_date": "02-03-2025", "currency": "USD", "amount": "200", "cash_account": "531"}, 1)
        rows = {r["invoice_number"]: r["outstanding"] for r in self.db.aging_report("31-03-2025", "sale", "USD")}
        self.assertEqual(rows, {"On account (not allocated)": -70.0})

    def test_allocated_receipt_still_goes_to_its_invoice(self):
        party = self.db.save_party({"kind": "customer", "name": "Client B", "currency": "USD"}, 1)
        ids = [self.db.create_manual_invoice({"invoice_number": n, "invoice_date": d, "party_name": "Client B", "kind": "sales", "currency": "USD", "status": "posted"},
                                             [{"description": "x", "quantity": 1, "unit_price": 100, "vat_rate": 0}], 1) for n, d in (("B-1", "10-01-2025"), ("B-2", "10-02-2025"))]
        payment = self.db.add_payment({"kind": "customer_receipt", "party_id": party["id"], "payment_date": "01-03-2025", "currency": "USD", "amount": "100", "cash_account": "531"}, 1)
        self.db.save_allocations(payment, [{"invoice_id": ids[1], "amount": 100}], 1)
        rows = {r["invoice_number"]: r["outstanding"] for r in self.db.aging_report("31-03-2025", "sale", "USD")}
        self.assertEqual(rows, {"B-1": 100.0})


class ItemCostAccountTest(_Book):
    def test_purchase_of_a_raw_material_goes_to_its_cost_account_on_every_path(self):
        steel = inventory.save_item(self.db, {"name": "Steel", "stock_account": "311"}, 1)
        panel = inventory.save_item(self.db, {"name": "Panel"}, 1)
        self.db.create_manual_invoice({"invoice_number": "P-1", "invoice_date": "10-01-2025", "party_name": "Supplier", "kind": "purchases", "currency": "USD", "status": "posted"},
                                      [{"description": "Steel", "quantity": 10, "unit_price": 2, "vat_rate": 0, "item_code": steel["sku"]},
                                       {"description": "Panel", "quantity": 1, "unit_price": 50, "vat_rate": 0, "item_code": panel["sku"]}], 1)
        debits = {code: debit for code, debit, _c in self.lines("invoice") if debit}
        self.assertEqual((debits.get("611100000"), debits.get("601100000")), (20.0, 50.0))


if __name__ == "__main__":
    unittest.main()
