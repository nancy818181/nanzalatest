"""Unittest smoke certification using only literal synthetic ledger inputs.

The expected values below are calculated from fixture literals with Decimal;
they do not call a Nanza report function.
"""
import secrets
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from database import Database
from golden_ledger_fixture import ENTRIES, FIXTURE_RATES, PERIOD_END, RATE_DATE
from golden_ledger_expected import EXPECTED_NATIVE, EXPECTED_USD_BALANCE_SHEET


class SyntheticReportCertification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "synthetic-company.db")
        self.db.initialize("Synthetic-Only-2026!")
        self.addCleanup(self.db.release)
        self.user = self.db.user_for_token(self.db.login("admin", "Synthetic-Only-2026!")["token"])["id"]
        self.codes = {"cash": "531", "ar": "4111", "ap": "4011", "equity": "1013",
                      "income": "701100001", "expense": "601100000", "vat_input": "44210", "vat_output": "4427"}
        for source, target in (("USD", "LBP"), ("EUR", "USD")):
            self.db.save_exchange_rate({"date_from": "2026-01-01", "date_to": "2026-12-31",
                "from_currency": source, "to_currency": target,
                "rate": str(FIXTURE_RATES[(source, target)])}, self.user)
        ids = {}
        for number, date, currency, note, lines, reversal in ENTRIES:
            self.db.save_journal_voucher(
                {"entry_number": number, "entry_date": date, "description": "Synthetic fixture: " + note,
                 "currency": currency},
                [{"account_code": self.codes[account], "debit": debit, "credit": credit, "description": note}
                 for account, debit, credit in lines], self.user, reversal_of=ids.get(reversal))
            with self.db.connect() as c:
                ids[number] = c.execute("SELECT id FROM journal_entries WHERE entry_number=?", (number,)).fetchone()[0]

    def test_trial_balance_native_totals_per_currency(self):
        rows = self.db.trial_balance(to_date=PERIOD_END)
        # Independent Decimal aggregation directly from the handwritten fixture rows.
        expected_from_inputs = {}
        for _number, _date, currency, _note, lines, _reversal in ENTRIES:
            bucket = expected_from_inputs.setdefault(currency, [Decimal(0), Decimal(0)])
            bucket[0] += sum((Decimal(debit) for _account, debit, _credit in lines), Decimal(0))
            bucket[1] += sum((Decimal(credit) for _account, _debit, credit in lines), Decimal(0))
        for currency, expected in EXPECTED_NATIVE.items():
            debit = sum((Decimal(str(r["debit"])) for r in rows if r["currency"] == currency), Decimal(0))
            credit = sum((Decimal(str(r["credit"])) for r in rows if r["currency"] == currency), Decimal(0))
            self.assertEqual((debit, credit), tuple(expected_from_inputs[currency]))
            self.assertEqual((debit, credit), (Decimal(expected["debit"]), Decimal(expected["credit"])))

    def test_balance_sheet_and_net_income_reconcile_for_usd_fixture(self):
        rows = self.db.balance_sheet(to_date=PERIOD_END, currency="USD")
        totals = {kind: sum((Decimal(str(r["balance"])) for r in rows if r["type"] == kind), Decimal(0))
                  for kind in ("asset", "liability", "equity")}
        self.assertEqual(totals["asset"], Decimal(EXPECTED_USD_BALANCE_SHEET["assets"]))
        self.assertEqual(-totals["liability"], Decimal(EXPECTED_USD_BALANCE_SHEET["liabilities"]))
        self.assertEqual(-totals["equity"], Decimal(EXPECTED_USD_BALANCE_SHEET["equity"]))
        pnl = self.db.profit_and_loss("2026-01-01", PERIOD_END, "USD")
        net_income = sum((Decimal(str(r["amount"])) if r["type"] == "income" else -Decimal(str(r["amount"]))
                          for r in pnl), Decimal(0))
        self.assertEqual(net_income, Decimal("57.16"))
        current_result = next(Decimal(str(row["balance"])) for row in rows
                              if row["code"] == "13" and row["currency"] == "USD")
        self.assertEqual(-current_result, net_income)

    def test_vat_control_account_arithmetic(self):
        rows = self.db.trial_balance(to_date=PERIOD_END)
        input_vat = sum((Decimal(str(r["debit"])) - Decimal(str(r["credit"])) for r in rows
                         if r["code"] == self.codes["vat_input"] and r["currency"] == "USD"), Decimal(0))
        output_vat = sum((Decimal(str(r["credit"])) - Decimal(str(r["debit"])) for r in rows
                          if r["code"] == self.codes["vat_output"] and r["currency"] == "USD"), Decimal(0))
        self.assertEqual(input_vat, Decimal("4.95"))
        self.assertEqual(output_vat, Decimal("12.10"))

    def test_combined_invoice_payment_statement_ageing_and_vat_fixture(self):
        """One synthetic company with invoices, partial allocations, voids, and journal entries."""
        import vat_return

        customer = self.db.save_party({"name": "Certification Customer", "kind": "customer", "currency": "USD"}, self.user)
        supplier = self.db.save_party({"name": "Certification Supplier", "kind": "supplier", "currency": "USD"}, self.user)
        sale = self.db.import_invoice({"invoice_number": "CERT-S-1", "invoice_date": "2026-02-01", "due_date": "2026-02-28",
            "party_name": customer["name"], "commercial_party_id": customer["id"], "kind": "sale", "currency": "USD",
            "subtotal": "100.00", "vat": "11.00", "total": "111.00", "status": "posted"}, self.user)
        purchase = self.db.import_invoice({"invoice_number": "CERT-P-1", "invoice_date": "2026-02-02", "due_date": "2026-02-28",
            "party_name": supplier["name"], "commercial_party_id": supplier["id"], "kind": "purchase", "currency": "USD",
            "subtotal": "50.00", "vat": "5.50", "total": "55.50", "status": "posted"}, self.user)
        receipt = self.db.add_payment({"kind": "customer_receipt", "party_id": customer["id"], "payment_date": "2026-02-10",
            "currency": "USD", "amount": "40.00", "cash_account": "531", "party_account": customer["account_number"]}, self.user)
        self.db.save_allocations(receipt, [{"invoice_id": sale, "amount": "40.00"}], self.user)
        payment = self.db.add_payment({"kind": "supplier_payment", "party_id": supplier["id"], "payment_date": "2026-02-11",
            "currency": "USD", "amount": "20.00", "cash_account": "531", "party_account": supplier["account_number"]}, self.user)
        self.db.save_allocations(payment, [{"invoice_id": purchase, "amount": "20.00"}], self.user)
        void_receipt = self.db.add_payment({"kind": "customer_receipt", "party_id": customer["id"], "payment_date": "2026-02-12",
            "currency": "USD", "amount": "7.00", "cash_account": "531", "party_account": customer["account_number"]}, self.user)
        self.db.delete_payment(void_receipt, self.user, reason="synthetic void case", role="admin")
        void_invoice = self.db.import_invoice({"invoice_number": "CERT-S-VOID", "invoice_date": "2026-02-13", "due_date": "2026-02-28",
            "party_name": customer["name"], "commercial_party_id": customer["id"], "kind": "sale", "currency": "USD",
            "subtotal": "25.00", "vat": "2.75", "total": "27.75", "status": "posted"}, self.user)
        self.db.mark_invoice_deleted(void_invoice, self.user, reason="synthetic void invoice", role="admin", void_date="2026-02-14")

        # Independently hand-aggregated incremental expectations from the literal document inputs.
        # Sale: AR 111 / income 100 / VAT payable 11; purchase: expense 50 / input VAT 5.5 / AP 55.5.
        # Receipt and supplier payment settle 40 and 20; the voided receipt remains in GL by owner design.
        tb = self.db.trial_balance(to_date="2026-02-28")
        debit = sum((Decimal(str(r["debit"])) for r in tb if r["currency"] == "USD"), Decimal(0))
        credit = sum((Decimal(str(r["credit"])) for r in tb if r["currency"] == "USD"), Decimal(0))
        self.assertEqual(debit, credit)
        tb_expected = {"USD": Decimal("1795.74"), "LBP": Decimal("9039500"), "EUR": Decimal("4.45")}
        tb_actual = {}
        for currency, expected_total in tb_expected.items():
            currency_rows = [r for r in tb if r["currency"] == currency]
            actual_debit = sum((Decimal(str(r["debit"])) for r in currency_rows), Decimal(0))
            actual_credit = sum((Decimal(str(r["credit"])) for r in currency_rows), Decimal(0))
            tb_actual[currency] = (actual_debit, actual_credit)
            self.assertEqual((actual_debit, actual_credit), (expected_total, expected_total))

        bs = self.db.balance_sheet(to_date="2026-02-28", currency="USD")
        bs_totals = {kind: sum((Decimal(str(r["balance"])) for r in bs if r["type"] == kind), Decimal(0))
                     for kind in ("asset", "liability", "equity")}
        expected_bs = {"asset": Decimal("1395.71"), "liability": Decimal("-88.55"), "equity": Decimal("-1307.16")}
        self.assertEqual(bs_totals, expected_bs)
        pnl_rows = self.db.profit_and_loss("2026-01-01", "2026-02-28", "USD")
        pnl_net = sum((Decimal(str(r["amount"])) if r["type"] == "income" else -Decimal(str(r["amount"]))
                       for r in pnl_rows), Decimal(0))
        self.assertEqual(pnl_net, Decimal("107.16"))
        current_result = next(Decimal(str(r["balance"])) for r in bs if r["code"] == "13")
        self.assertEqual(-current_result, pnl_net)

        statement = self.db.statement_of_account(customer["id"], to_date="2026-02-28", currency="USD")
        statement_net = sum((Decimal(str(r["debit"])) - Decimal(str(r["credit"])) for r in statement["items"]), Decimal(0))
        self.assertEqual(statement_net, Decimal("71.00"))
        self.assertNotIn("CERT-S-VOID", str(statement))
        self.assertNotIn("CERT", str(statement).replace("CERT-S-1", ""))
        supplier_statement = self.db.statement_of_account(supplier["id"], to_date="2026-02-28", currency="USD")
        supplier_net = sum((Decimal(str(r["debit"])) - Decimal(str(r["credit"]))
                            for r in supplier_statement["items"]), Decimal(0))
        self.assertEqual(supplier_net, Decimal("-35.50"))

        aging = self.db.aging_report("2026-02-28", kind="sale", currency="USD")
        outstanding = {r["invoice_number"]: Decimal(str(r["outstanding"])) for r in aging}
        self.assertEqual(outstanding.get("CERT-S-1"), Decimal("71.0"))
        self.assertNotIn("CERT-S-VOID", outstanding)

        vat = vat_return.build_vat_return(self.db, 2026, 1, currency="USD")
        docs = {d["number"]: (Decimal(str(d["base"])), Decimal(str(d["vat"]))) for d in vat["documents"]}
        self.assertEqual(docs["CERT-S-1"], (Decimal("100.00"), Decimal("11.00")))
        self.assertEqual(docs["CERT-P-1"], (Decimal("50.00"), Decimal("5.50")))
        self.assertNotIn("CERT-S-VOID", docs)

        # These values are emitted so the executed comparison is reviewable from unittest output.
        print("CERTIFICATION TABLE | report | line | expected | app | difference | result")
        for currency, expected_total in tb_expected.items():
            actual = tb_actual[currency][0]
            print(f"trial balance | {currency} debit=credit | {expected_total:.2f} | {actual:.2f} | {actual-expected_total:.2f} | PASS")
        print(f"balance sheet | USD assets | 1395.71 | {bs_totals['asset']:.2f} | {bs_totals['asset']-Decimal('1395.71'):.2f} | PASS")
        print(f"balance sheet | USD liabilities | 88.55 | {-bs_totals['liability']:.2f} | {-bs_totals['liability']-Decimal('88.55'):.2f} | PASS")
        print(f"balance sheet | USD total equity | 1307.16 | {-bs_totals['equity']:.2f} | {-bs_totals['equity']-Decimal('1307.16'):.2f} | PASS")
        print(f"balance sheet | current-year result | 107.16 | {-current_result:.2f} | {-current_result-pnl_net:.2f} | PASS")
        print(f"income statement | USD net income | 107.16 | {pnl_net:.2f} | {pnl_net-Decimal('107.16'):.2f} | PASS")
        print(f"statement of account | customer net debit | 71.00 | {statement_net:.2f} | {statement_net-Decimal('71.00'):.2f} | PASS")
        print(f"statement of account | supplier net credit | 35.50 | {-supplier_net:.2f} | {-supplier_net-Decimal('35.50'):.2f} | PASS")
        print(f"ageing | customer open balance | 71.00 | {outstanding['CERT-S-1']:.2f} | {outstanding['CERT-S-1']-Decimal('71.00'):.2f} | PASS")
        print(f"VAT return | sales base / VAT | 100.00 / 11.00 | {docs['CERT-S-1'][0]:.2f} / {docs['CERT-S-1'][1]:.2f} | 0.00 | PASS")
        print(f"VAT return | purchases base / VAT | 50.00 / 5.50 | {docs['CERT-P-1'][0]:.2f} / {docs['CERT-P-1'][1]:.2f} | 0.00 | PASS")

    def test_voided_sale_gl_readers_reconcile_and_vat_lists_exclude_it(self):
        import books_check
        import financial_statements
        import vat_ledgers
        import vat_return
        from datetime import date
        from decimal import ROUND_HALF_UP
        from ledger_reports import _load_lines
        from nanza.ai_accountant.query_builder import query_expenses

        customer = self.db.save_party({"name":"Void reader customer", "kind":"customer", "currency":"USD",
                                       "account_number":"411100001"}, self.user)
        supplier = self.db.save_party({"name":"Void reader supplier", "kind":"supplier", "currency":"LBP",
                                       "account_number":"401100001"}, self.user)
        sale = self.db.import_invoice({"invoice_number":"CERT-VOID-S-USD", "invoice_date":"2026-02-12",
            "due_date":"2026-02-28", "party_name":customer["name"], "commercial_party_id":customer["id"],
            "kind":"sale", "currency":"USD", "supplier_account":"411100001", "expense_account":"701100001",
            "vat_account":"442700001", "subtotal":"100.00", "vat":"11.00", "total":"111.00", "status":"posted"}, self.user)
        purchase = self.db.import_invoice({"invoice_number":"CERT-P-LBP", "invoice_date":"2026-02-13",
            "due_date":"2026-02-28", "party_name":supplier["name"], "commercial_party_id":supplier["id"],
            "kind":"purchase", "currency":"LBP", "supplier_account":"401100001", "expense_account":"626340001",
            "vat_account":"442100001", "subtotal":"8950000.00", "vat":"984500.00", "total":"9934500.00",
            "status":"posted"}, self.user)
        self.db.mark_invoice_deleted(sale, self.user, reason="Synthetic void for reader certification",
                                     role="admin", void_date="2026-02-14")
        # A deliberately mismatched VAT account on the voided synthetic document
        # makes the VAT-ledger check prove that the void row is excluded.
        with self.db.connect() as connection:
            connection.execute("UPDATE invoices SET vat_account='442100001' WHERE id=?", (sale,))

        tb = self.db.trial_balance(to_date="2026-12-31")
        currencies = {row["currency"] for row in tb}
        for currency in currencies:
            dr = sum((Decimal(str(r["debit"])) for r in tb if r["currency"] == currency), Decimal(0))
            cr = sum((Decimal(str(r["credit"])) for r in tb if r["currency"] == currency), Decimal(0))
            self.assertEqual(dr, cr, currency)

        raw = financial_statements.load_period(self.db, "2026-01-01", "2026-12-31", "USD")
        statement = financial_statements.period_data(self.db, "2026-01-01", "2026-12-31", "USD", "Synthetic 2026")
        self.assertEqual(financial_statements.reconciliation_rows([statement])[0][1], Decimal("0.00"))
        fs_net_income = -sum(raw["pnl"].values(), Decimal(0))
        tb_net_income_usd = sum((Decimal(str(r["usd_credit"])) - Decimal(str(r["usd_debit"]))
                                 for r in tb if str(r["code"]).startswith(("6", "7"))), Decimal(0))
        self.assertEqual(fs_net_income.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                         tb_net_income_usd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        ledger_lines = _load_lines(self.db, {"date_to":"2026-12-31", "posting_status":"posted",
                                             "first_column":"account", "second_column":"none"})
        ledger_balances = {}
        for line in ledger_lines:
            key = (line["account_currency"], line["code"])
            ledger_balances[key] = ledger_balances.get(key, Decimal(0)) + line["signed"]["account"]
        tb_balances = {(r["currency"], r["code"]): Decimal(str(r["debit"])) - Decimal(str(r["credit"])) for r in tb}
        for key in set(ledger_balances) | set(tb_balances):
            self.assertEqual(ledger_balances.get(key, Decimal(0)), tb_balances.get(key, Decimal(0)), key)

        health = books_check.run(self.db, 2026)
        missing_entry = next(r for r in health["results"] if r["check"] == "Every document in the books")
        self.assertEqual(missing_entry["status"], "OK", missing_entry)

        vat_doc_rows = self.db.vat_report("2026-01-01", "2026-12-31")["items"]
        self.assertEqual([(r["currency"], r["kind"]) for r in vat_doc_rows], [("LBP", "purchase")])
        vat = vat_return.build_vat_return(self.db, 2026, 1)
        vat_numbers = {str(document.get("number")) for document in vat["documents"]}
        self.assertNotIn("CERT-VOID-S-USD", vat_numbers)
        self.assertIn("CERT-P-LBP", vat_numbers)
        self.assertNotIn("CERT-VOID-S-USD", str(vat_ledgers.test_vat_accounts(self.db)))

        ai = query_expenses(self.db, "expenses this year", today=date(2026, 12, 31))
        self.assertTrue(ai["ok"], ai)
        account_types = {r["code"]:r["type"] for r in self.db.list_accounts()}
        tb_expenses = {}
        for row in tb:
            if account_types.get(row["code"]) == "expense":
                tb_expenses[row["currency"]] = tb_expenses.get(row["currency"], Decimal(0)) + Decimal(str(row["debit"])) - Decimal(str(row["credit"]))
        self.assertEqual({c:Decimal(str(v)) for c,v in ai["totals"].items()}, tb_expenses)

        with self.db.connect() as connection:
            self.assertIsNone(self.db.find_same_invoice_number(connection, "CERT-VOID-S-USD", "sale", customer["id"]))
        self.assertNotIn(sale, {row["id"] for row in self.db.open_documents(customer["id"])})

    def test_f4_real_cast_preserves_large_lbp_cents(self):
        amount = Decimal("1000000000000000.01")
        self.db.save_journal_voucher(
            {"entry_number": "F4-LARGE-CENT", "entry_date": "2026-01-02",
             "description": "Synthetic large LBP cents; F4 probe", "currency": "LBP"},
            [{"account_code": "531", "debit": str(amount), "credit": "0"},
             {"account_code": "4011", "debit": "0", "credit": str(amount)}], self.user)
        rows = self.db.trial_balance(to_date="2026-12-31")
        observed = next(Decimal(str(row["debit"])) for row in rows
                        if row["code"] == "531" and row["currency"] == "LBP")
        # Intended exact result includes the existing 8,950,000 fixture opening debit.
        self.assertEqual(observed, Decimal("1000000008950000.01"))


if __name__ == "__main__":
    unittest.main()
