"""2.9.132: end-to-end VAT quarter (Art. 31 ratio, prorata in whole LBP, credit chain, rounding to LBP 10,000, due date),
ledger check with an exempt-use purchase, Assets invoices need a class 2 account, and reversing a depreciation voucher
frees its register period. Expected figures are worked out by hand in the comments."""
import tests_setup  # noqa: F401
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import fixed_assets as fa
import vat_return
from database import Database


class _Company(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "c.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.user = self.db.user_for_token(self.db.login("admin", "secret12345")["token"])["id"]
        self.db.save_exchange_rate({"date_from": "01-01-2026", "date_to": "30-06-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, self.user)

    def inv(self, number, kind, day, currency, amount, vat_rate="11", **extra):
        item = {"invoice_number": number, "kind": kind, "entry_type": extra.pop("entry_type", "sales" if kind == "sale" else "purchases"),
                "invoice_date": day, "party_name": f"Party {number}", "currency": currency, "status": "posted", **extra}
        return self.db.create_manual_invoice(item, [{"description": "line", "quantity": "1", "unit_price": amount, "vat_rate": vat_rate}], self.user)


class VatQuarterEndToEndTest(_Company):
    def setUp(self):
        super().setUp()
        s1 = self.inv("S1", "sale", "10-01-2026", "LBP", "100000000")                                 # VAT 11,000,000
        self.inv("S2", "sale", "15-02-2026", "USD", "10000")                                          # 1,100 USD = 98,450,000
        self.inv("S3", "sale", "20-02-2026", "LBP", "50000000", vat_rate="0", vat_treatment="exempt")  # exempt 50,000,000
        self.inv("S4", "sale", "25-02-2026", "USD", "2000", vat_rate="0", vat_treatment="zero_rated")  # 179,000,000
        self.inv("P1", "purchase", "12-01-2026", "LBP", "40000000", vat_use="mixed")                   # 4,400,000 mixed
        self.inv("P2", "purchase", "13-01-2026", "USD", "1000", vat_use="taxable")                     # 9,845,000 full
        self.inv("A1", "purchase", "05-01-2026", "USD", "12000", entry_type="assets", vat_use="mixed", expense_account="2262")  # 118,140,000 mixed
        self.inv("P3", "purchase", "14-01-2026", "LBP", "10000000", vat_use="exempt")                  # 1,100,000 blocked
        self.db.add_expense({"expense_date": "20-01-2026", "description": "Rent", "currency": "LBP", "with_vat_subtotal": "5000000", "vat": "550000"}, self.user)
        item = self.db.invoice_detail(s1)["items"][0]
        self.db.create_invoice_return(s1, [{"item_id": item["id"], "quantity": "0.1"}], "28-03-2026", self.user, "ret-s1")  # -10,000,000 / -1,100,000

    def test_q1_return_in_whole_pounds_and_agreed_with_the_books(self):
        result = vat_return.build_vat_return(self.db, 2026, 1); t = result["totals_lbp"]
        self.assertEqual(result["deduction_ratio"], Decimal("0.958814"))   # 1,164,000,000 / 1,214,000,000
        self.assertEqual(t["total_output"], Decimal("108350000"))
        self.assertEqual(t["prorata"], Decimal("-5069585"))                # 123,090,000 x 0.041186 = 5,069,584.74 -> whole LBP
        self.assertEqual(t["non_deductible"], Decimal("6169585"))          # + 1,100,000 blocked
        self.assertEqual(t["total_input"], Decimal("127865415"))
        self.assertEqual(result["credit_carried_forward_lbp"], Decimal("19515415"))
        check = vat_return.ledger_check(self.db, result)
        self.assertTrue(check["agreed"], check["sections"][2]["rows"])     # the exempt-use purchase P3 is not a difference
        vat_return.save_return(self.db, 2026, 1, self.user)
        plan = vat_return.post_settlement(self.db, 2026, 1, self.user)
        lines = {(l["account_code"], l["side"]): Decimal(l["amount"]) for l in plan["lines"]}
        self.assertEqual(lines[("6459", "D")], -t["prorata"])              # the settlement posts the return's figure
        self.assertEqual(lines[("4429", "D")], result["credit_carried_forward_lbp"])

    def test_q2_uses_the_credit_and_rounds_up(self):
        vat_return.save_return(self.db, 2026, 1, self.user)
        self.inv("S5", "sale", "10-04-2026", "LBP", "300000000")
        self.inv("P4", "purchase", "11-04-2026", "LBP", "20000000", vat_use="taxable")
        q2 = vat_return.build_vat_return(self.db, 2026, 2)
        self.assertEqual(q2["credit_brought_forward_lbp"], Decimal("19515415"))
        self.assertEqual(q2["payable_lbp"], Decimal("11290000"))           # 30,800,000 - 19,515,415 = 11,284,585 -> 11,290,000


class DueDateTest(unittest.TestCase):
    def test_last_day_of_the_month_after_the_quarter_from_2026(self):
        self.assertEqual([vat_return.due_date(2026, q) for q in (1, 2, 3, 4)], ["2026-04-30", "2026-07-31", "2026-10-31", "2027-01-31"])
        self.assertEqual(vat_return.due_date(2025, 2), "2025-07-20")        # before 2026: 20 days, unchanged


class AssetsAccountTest(_Company):
    def test_assets_invoice_without_class_2_account_is_refused(self):
        with self.assertRaisesRegex(ValueError, "class 2"):
            self.db.import_invoice({"invoice_number": "AX", "kind": "purchase", "entry_type": "assets", "invoice_date": "05-01-2026",
                                    "party_name": "Dell", "currency": "USD", "subtotal": "100", "vat": "11", "total": "111"}, self.user)
        self.db.import_invoice({"invoice_number": "AY", "kind": "purchase", "entry_type": "assets", "invoice_date": "05-01-2026", "expense_account": "2262",
                                "party_name": "Dell", "currency": "USD", "subtotal": "100", "vat": "11", "total": "111"}, self.user)


class DepreciationReversalTest(_Company):
    def setUp(self):
        super().setUp()
        self.asset = fa.save_asset(self.db, {"asset_code": "FA-1", "name": "Server", "acquired_on": "05-01-2026", "start_on": "05-01-2026",
            "currency": "USD", "cost": "9000", "residual": "0", "useful_months": "36", "asset_account": "2262",
            "depreciation_account": "6512.4", "accumulated_account": "2826"}, user_id=self.user)

    def posted(self, period):
        return next(r for r in fa.schedule(self.db, self.asset["id"]) if r["period_end"] == period)["posted"]

    def test_reversal_frees_the_period_and_it_can_be_posted_again(self):
        fa.post_period(self.db, self.asset["id"], "31-01-2026", self.user)
        feb = fa.post_period(self.db, self.asset["id"], "28-02-2026", self.user)["voucher"]["id"]
        jan = next(p for p in fa.schedule(self.db, self.asset["id"]) if p["period_end"] == "2026-01-31")["entry_id"]
        with self.assertRaisesRegex(ValueError, "2026-02-28 first"): self.db.reverse_journal_voucher(jan, "31-01-2026", self.user)
        self.db.reverse_journal_voucher(feb, "28-02-2026", self.user)
        self.assertFalse(self.posted("2026-02-28")); self.assertTrue(self.posted("2026-01-31"))
        roll = fa.rollforward(self.db, 2026)["totals"]["USD"]
        self.assertEqual(roll["depreciation_posted"], "250.00")             # the register follows the ledger: 9,000 / 36
        fa.post_period(self.db, self.asset["id"], "28-02-2026", self.user)
        self.assertTrue(self.posted("2026-02-28"))
        with self.db.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_log WHERE action='depreciation_reversed'").fetchone()[0], 1)


class DisposalAndReconciliationTest(DepreciationReversalTest):
    """IAS 16.67-72: an asset sold / scrapped leaves the register and the ledger; the register agrees with the ledger."""
    def setUp(self):
        super().setUp()
        self.inv("A1", "purchase", "05-01-2026", "USD", "9000", entry_type="assets", expense_account="2262", expense_no_vat_account="2262", vat_use="taxable")

    def test_dispose_after_three_months(self):
        for day in ("31-01-2026", "28-02-2026", "31-03-2026"): fa.post_period(self.db, self.asset["id"], day, self.user)
        check = fa.reconcile_gl(self.db, "31-03-2026")
        self.assertTrue(check["agreed"], check["rows"])                       # cost 9,000 and accumulated 750 in both
        with self.assertRaisesRegex(ValueError, "2026-04-30 first"): fa.dispose_asset(self.db, self.asset["id"], "15-05-2026", self.user)
        result = fa.dispose_asset(self.db, self.asset["id"], "20-04-2026", self.user)
        self.assertEqual((result["accumulated"], result["book_value"]), ("750.00", "8250.00"))   # 9,000 / 36 x 3 = 750
        tb = {(r["code"], r["currency"]): Decimal(str(r["closing_balance"])) for r in self.db.trial_balance(None, "30-04-2026")}
        self.assertEqual(tb[("2262", "USD")], Decimal("0")); self.assertEqual(tb[("2826", "USD")], Decimal("0"))
        self.assertEqual(tb[("6812", "USD")], Decimal("8250"))
        self.assertEqual(fa.list_assets(self.db), [])
        roll = fa.rollforward(self.db, 2026)["totals"]["USD"]
        self.assertEqual((roll["disposals_cost"], roll["disposals_accumulated"], roll["closing_net_book_value"]), ("9000.00", "750.00", "0.00"))
        self.assertTrue(fa.reconcile_gl(self.db, "30-04-2026")["agreed"])
        with self.db.connect() as connection:
            entry = connection.execute("SELECT disposal_entry_id FROM fixed_assets WHERE id=?", (self.asset["id"],)).fetchone()[0]
        self.db.reverse_journal_voucher(entry, "20-04-2026", self.user)        # the reversal puts the asset back
        self.assertEqual([a["asset_code"] for a in fa.list_assets(self.db)], ["FA-1"])

    def test_register_without_purchase_entry_is_a_difference(self):
        fa.save_asset(self.db, {"asset_code": "FA-2", "name": "Desk", "acquired_on": "05-01-2026", "start_on": "05-01-2026", "currency": "USD",
                                "cost": "500", "residual": "0", "useful_months": "12", "asset_account": "2262", "depreciation_account": "6512.4",
                                "accumulated_account": "2826"}, user_id=self.user)
        check = fa.reconcile_gl(self.db, "31-01-2026")
        self.assertFalse(check["agreed"])
        cost = next(r for r in check["rows"] if r["kind"] == "cost")
        self.assertEqual((cost["register"], cost["ledger"], cost["difference"]), ("9500.00", "9000.00", "500.00"))


class HistoricalRateTest(DepreciationReversalTest):
    """IAS 21.23(b): depreciation of a USD asset is translated at the purchase-date rate, not at the month-end rate."""
    def test_depreciation_keeps_the_purchase_rate(self):
        self.db.save_exchange_rate({"date_from": "01-02-2026", "date_to": "30-06-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "100000"}, self.user)
        fa.post_period(self.db, self.asset["id"], "31-01-2026", self.user)
        feb = fa.post_period(self.db, self.asset["id"], "28-02-2026", self.user)["voucher"]["id"]
        fa.post_period(self.db, self.asset["id"], "31-03-2026", self.user)
        fa.post_category_month(self.db, "2262", "30-04-2026", self.user)
        with self.db.connect() as connection:
            values = {Decimal(str(r[0])) for r in connection.execute("""SELECT j.amount_lbp FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id
                         WHERE e.description LIKE 'Asset amortisation%' OR e.description LIKE 'Depreciation %'""")}
            feb_lines = connection.execute("SELECT amount_lbp FROM journal_lines WHERE entry_id=?", (feb,)).fetchall()
        self.assertEqual(values, {Decimal("22375000")})                     # 250 USD x 89,500 every month (not x 100,000)
        self.assertEqual(len(feb_lines), 2)


class CashFlowOverdraftTest(_Company):
    """IAS 7.8: a credit balance on a cash / bank account is a liability in the balance sheet but part of cash in the cash flow."""
    def test_overdraft_is_net_cash(self):
        import financial_statements as fs
        jv = lambda day, lines: self.db.save_journal_voucher({"entry_date": day, "description": "t", "currency": "USD"},
                                                             [{"account_code": c, "debit": d, "credit": k} for c, d, k in lines], self.user)
        jv("01-01-2026", [("512", "1000", ""), ("101", "", "1000")])
        jv("10-01-2026", [("601100000", "300", ""), ("531", "", "300")])      # cash on hand goes to -300
        pack = fs.build({2026: self.db}, {"years": "2026", "basis": "USD"})
        cash = next(s for s in pack["sections"] if s["kind"] == "cash")["rows"]
        value = lambda label: next(r[2] for r in cash if r[0] == label)
        self.assertEqual(value("Net cash from operating activities"), Decimal("-300.00"))
        self.assertEqual(value("CASH AND CASH EQUIVALENTS AT END"), Decimal("700.00"))
        self.assertEqual(value("Bank overdrafts (in other current liabilities)"), Decimal("-300.00"))
        checks = next(s for s in pack["sections"] if s["kind"] == "checks")["rows"]
        self.assertEqual(checks[1][1], Decimal("0.00"))
        review = " ".join(r[0] for r in next(s for s in pack["sections"] if s["kind"] == "review")["rows"])
        self.assertIn("cash on hand with a credit balance (531)", review)


class GuardsTest(_Company):
    def test_ratio_is_between_0_and_1(self):
        self.assertEqual(vat_return._ratio(Decimal("-10"), Decimal("50")), Decimal("0"))   # -10 / 40 = -25% -> 0
        self.assertEqual(vat_return._ratio(Decimal("150"), Decimal("50")), Decimal("0.75"))

    def test_posted_invoice_with_a_wrong_total_is_refused(self):
        base = {"invoice_number": "X1", "kind": "purchase", "invoice_date": "05-01-2026", "party_name": "S", "currency": "USD",
                "subtotal": "100", "vat": "11", "status": "posted"}
        with self.assertRaisesRegex(ValueError, "not subtotal \\+ VAT"): self.db.import_invoice({**base, "total": "150"}, self.user)
        self.db.import_invoice({**base, "invoice_number": "X2", "total": "111.40"}, self.user)   # rounding up to 1 unit: accepted
        self.db.import_invoice({**base, "invoice_number": "X3", "total": "150", "status": ""}, self.user)  # no status: goes to Review


class ReportLayoutTest(unittest.TestCase):
    """PDF layout only - no figure changes: a 10-column trial balance fits one band, amounts are not broken over two lines,
    a column with cents shows 2 decimals on every amount, one date line."""
    def test_trial_balance_layout(self):
        import pypdf
        import report_export as rx
        headers = ["Account", "Account Name", "Opening (USD)", "Debit (USD) (period)", "Credit (USD) (period)", "Balance (USD)",
                   "Opening (LBP)", "Debit (LBP) (period)", "Credit (LBP) (period)", "Balance (LBP)"]
        rows = [["101", "Capital (Company or Individual)", Decimal("0"), Decimal("0"), Decimal("50000"), Decimal("-50000"),
                 Decimal("0"), Decimal("0"), Decimal("4475000000"), Decimal("-4475000000")],
                ["601", "General Expenses", Decimal("0"), Decimal("2275.5"), Decimal("0"), Decimal("2275.5"),
                 Decimal("0"), Decimal("203657250"), Decimal("0"), Decimal("203657250")]]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path = Path(folder) / "tb.pdf"
            rx.export_sections_pdf(str(path), "Trial Balance", ["Company: X", "Printed: 31-12-2026"],
                                   [{"heading": "Trial balance", "headers": headers, "rows": rows, "total_rows": []}])
            text = "".join(page.extract_text() for page in pypdf.PdfReader(str(path)).pages)
        self.assertNotIn("first column repeated", text)
        self.assertIn("(4,475,000,000)", text)   # negative in brackets
        self.assertIn("50,000.00", text); self.assertIn("2,275.50", text)
        self.assertNotIn("Generated", text)


if __name__ == "__main__":
    unittest.main()
