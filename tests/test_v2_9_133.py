"""2.9.133: output VAT is a liability (RPT-BS-001), exact P&L amounts (MONEY-FLOAT-001), the audit trail of an invoice delete,
and the trial simulation. All data is synthetic."""
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from database import Database


class OutputVatLiabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "books.db")
        self.db.initialize("Synthetic-Only-Password-2026!")
        self.addCleanup(self.db.release)

    def type_of(self, code):
        with self.db.connect() as c:
            row = c.execute("SELECT type FROM accounts WHERE code=?", (code,)).fetchone()
        return row["type"] if row else None

    def test_new_company_types_output_vat_as_liability_and_input_vat_as_asset(self):
        self.assertEqual(self.type_of("4427"), "liability")
        self.assertEqual(self.type_of("44210"), "asset")

    def test_balance_sheet_shows_output_vat_under_liabilities(self):
        self.db.save_journal_voucher({"entry_number": "V-1", "entry_date": "10-01-2026", "description": "output VAT", "currency": "USD"},
                                     [{"account_code": "531", "debit": "111.00"}, {"account_code": "701100001", "credit": "100.00"},
                                      {"account_code": "4427", "credit": "11.00"}], 1)
        rows = self.db.balance_sheet(to_date="31-12-2026", currency="USD")
        vat = [r for r in rows if r["code"] == "4427"]
        self.assertEqual([r["type"] for r in vat], ["liability"])
        assets = sum(Decimal(str(r["balance"])) for r in rows if r["type"] == "asset")
        liabilities = -sum(Decimal(str(r["balance"])) for r in rows if r["type"] == "liability")
        equity = -sum(Decimal(str(r["balance"])) for r in rows if r["type"] == "equity")
        self.assertEqual((assets, liabilities, equity), (Decimal("111"), Decimal("11"), Decimal("100")))

    def test_existing_file_is_migrated_once_and_no_entry_is_touched(self):
        self.db.save_journal_voucher({"entry_number": "V-1", "entry_date": "10-01-2026", "description": "x", "currency": "USD"},
                                     [{"account_code": "531", "debit": "5.00"}, {"account_code": "4427", "credit": "5.00"}], 1)
        with self.db.connect() as c:  # an older file: sub-account typed asset, migration flag absent, schema marker stale
            c.execute("INSERT INTO accounts(code,name_en,type,parent_id) VALUES('442700001','VAT - old customer','asset',(SELECT id FROM accounts WHERE code='4427'))")
            c.execute("UPDATE accounts SET type='asset' WHERE code='4427'")
            c.execute("DELETE FROM app_settings WHERE key='output_vat_liability_2933'")
            c.execute("UPDATE app_settings SET value='stale' WHERE key='startup_schema_version'")
            before = [tuple(r) for r in c.execute("SELECT id,entry_id,account_id,debit,credit FROM journal_lines ORDER BY id")]
        self.db.initialize_if_needed("Synthetic-Only-Password-2026!")
        self.assertEqual((self.type_of("4427"), self.type_of("442700001")), ("liability", "liability"))
        with self.db.connect() as c:
            after = [tuple(r) for r in c.execute("SELECT id,entry_id,account_id,debit,credit FROM journal_lines ORDER BY id")]
            audits = [json.loads(r["details"]) for r in c.execute("SELECT details FROM audit_log WHERE action='migrate' AND entity='chart_of_accounts'")]
        self.assertEqual(before, after)
        self.assertEqual(len(audits), 1)
        self.assertGreaterEqual(audits[0]["accounts"], 1)
        # second start: nothing more to change, no second audit line
        with self.db.connect() as c:
            c.execute("UPDATE app_settings SET value='stale' WHERE key='startup_schema_version'")
        self.db.initialize_if_needed("Synthetic-Only-Password-2026!")
        with self.db.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) n FROM audit_log WHERE action='migrate' AND entity='chart_of_accounts'").fetchone()["n"], 1)

    def test_chart_templates_type_output_vat_as_liability(self):
        import chart_templates
        for accounts in (chart_templates.COUNTRY["ksa"]["accounts"], chart_templates.COUNTRY["uae"]["accounts"]):
            for code, _en, _ar, _fr, kind, parent in accounts:
                if parent == "4427":
                    self.assertEqual(kind, "liability", code)


class ExactProfitAndLossTest(unittest.TestCase):
    def test_forty_one_cent_entries_leave_no_float_residue(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "books.db")
            db.initialize("Synthetic-Only-Password-2026!")
            try:
                for index in range(30):
                    db.save_journal_voucher({"entry_number": f"C-{index}", "entry_date": "10-01-2026", "description": "cr", "currency": "USD"},
                                            [{"account_code": "531", "debit": "0.01"}, {"account_code": "701100001", "credit": "0.01"}], 1)
                for index in range(10):
                    db.save_journal_voucher({"entry_number": f"D-{index}", "entry_date": "10-01-2026", "description": "dr", "currency": "USD"},
                                            [{"account_code": "701100001", "debit": "0.01"}, {"account_code": "531", "credit": "0.01"}], 1)
                row = next(r for r in db.profit_and_loss(currency="USD") if r["code"] == "701100001")
                self.assertEqual(Decimal(str(row["amount"])), Decimal("0.20"))
                converted = next(r for r in db.profit_and_loss_converted(currency="USD") if r["code"] == "701100001")
                self.assertEqual(Decimal(str(converted["amount"])), Decimal("0.20"))
            finally:
                db.release()


class InvoiceDeleteAuditTest(unittest.TestCase):
    def test_void_of_a_posted_invoice_keeps_its_journal_lines_and_reverses_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "books.db")
            db.initialize("Synthetic-Only-Password-2026!")
            try:
                db.save_party({"kind": "customer", "name": "Synthetic customer", "currency": "USD"}, 1)
                invoice_id = db.create_manual_invoice(
                    {"invoice_number": "SYN-DEL-1", "invoice_date": "05-01-2026", "party_name": "Synthetic customer",
                     "kind": "sales", "currency": "USD", "status": "posted"},
                    [{"description": "Service", "quantity": 1, "unit_price": "100.00", "vat_rate": 11}], 1)
                db.delete_invoice(invoice_id, 1, reason="synthetic correction")
                with db.connect() as c:
                    details = json.loads(c.execute("SELECT details FROM audit_log WHERE action='void' AND entity='invoice' ORDER BY id DESC LIMIT 1").fetchone()["details"])
                    left = c.execute("SELECT COUNT(*) n FROM journal_lines").fetchone()["n"]
                    original = c.execute("SELECT COUNT(*) n FROM journal_entries WHERE source_type='invoice' AND source_id=?", (invoice_id,)).fetchone()["n"]
                    reverse = c.execute("SELECT COUNT(*) n FROM journal_entries WHERE source_type='invoice_void' AND source_id=?", (invoice_id,)).fetchone()["n"]
                self.assertEqual(original, 1)
                self.assertEqual(reverse, 1)
                self.assertEqual(left, 6)
                lines = details["journal_lines"]
                self.assertEqual(len(lines), 6)
                self.assertEqual(sum(Decimal(l["debit"]) for l in lines), sum(Decimal(l["credit"]) for l in lines))
                self.assertEqual(sum(Decimal(l["debit"]) for l in lines), Decimal("222.00"))
                self.assertEqual(details["invoice_number"], "SYN-DEL-1")
            finally:
                db.release()


class TrialSimulationTest(unittest.TestCase):
    KNOWN_GAPS = {  # owner decisions still open (docs/TRIAL_PLAN.md): when one is implemented, remove it here
        "Control: a posted INVOICE entry resists a balanced raw-SQL change (owner decision D4 open)",
        "Control: a POSTED invoice cannot be hard-deleted (cancel / credit note only) (owner decision open)",
    }

    def test_core_checks_and_controls_pass_and_open_gaps_are_the_documented_ones(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        import trial_simulation
        results = trial_simulation.run()
        failed = [r for r in results if not r["ok"] and r["kind"] in ("core", "control")]
        self.assertEqual(failed, [], failed)
        gaps = {r["name"] for r in results if r["kind"] == "gap"}
        self.assertTrue(gaps <= self.KNOWN_GAPS, gaps - self.KNOWN_GAPS)
        self.assertGreaterEqual(len(results), 30)


if __name__ == "__main__":
    unittest.main()
