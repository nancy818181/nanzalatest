"""Regression coverage for posting controls, short-term cash, bank allocations and permissions."""
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

import server
import approvals
import bank_rec
import cash_forecast_13_week
import diagnostics
from database import Database, utcnow


class PhaseOneControlsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.db = Database(Path(folder.name) / "company.db")
        self.db.initialize("phase1-controls-test")
        self.addCleanup(self.db.release)

    def accounts(self):
        with self.db.connect() as db:
            cash = db.execute("SELECT code FROM accounts WHERE code='531'").fetchone()["code"]
            counterpart = db.execute(
                "SELECT code FROM accounts WHERE type='income' ORDER BY code LIMIT 1"
            ).fetchone()["code"]
            return cash, counterpart

    def voucher(self, amount, day="10-01-2026", defer_posting=False):
        cash, counterpart = self.accounts()
        return self.db.save_journal_voucher(
            {"entry_date": day, "description": "Control test", "currency": "USD"},
            [{"account_code": cash, "debit": str(amount), "credit": "0"},
             {"account_code": counterpart, "debit": "0", "credit": str(amount)}], 1,
            defer_posting=defer_posting)

    def test_posted_voucher_is_immutable_and_reversal_is_linked(self):
        voucher = self.voucher(100)
        entry = voucher["voucher"]
        with self.db.connect() as db:
            line_id = db.execute("SELECT id FROM journal_lines WHERE entry_id=? ORDER BY id LIMIT 1",
                                 (entry["id"],)).fetchone()["id"]
            with self.assertRaisesRegex(sqlite3.IntegrityError, "(?i)immutable"):
                db.execute("UPDATE journal_lines SET description='tampered' WHERE id=?", (line_id,))
        with self.assertRaisesRegex(ValueError, "(?i)immutable"):
            self.db.save_journal_voucher({"entry_date": "10-01-2026", "currency": "USD"},
                [{"account_code": self.accounts()[0], "debit": "100", "credit": "0"},
                 {"account_code": self.accounts()[1], "debit": "0", "credit": "100"}], 1, entry["id"])
        reversal = self.db.reverse_journal_voucher(entry["id"], "12-01-2026", 1)
        self.assertEqual(reversal["voucher"]["reversal_of"], entry["id"])
        self.assertEqual(reversal["voucher"]["posting_status"], "posted")
        with self.db.connect() as db:
            original = db.execute("SELECT posting_status FROM journal_entries WHERE id=?", (entry["id"],)).fetchone()
            self.assertEqual(original["posting_status"], "posted")

    def test_approval_transitions_draft_back_to_posted(self):
        voucher = self.voucher(25, defer_posting=True)["voucher"]
        self.assertTrue(approvals.hold(self.db, voucher["id"], 1))
        with self.db.connect() as db:
            row = db.execute("SELECT posting_status,approval_status FROM journal_entries WHERE id=?",
                             (voucher["id"],)).fetchone()
            self.assertEqual((row["posting_status"], row["approval_status"]), ("draft", "review"))
        result = approvals.approve_entries(
            self.db, [voucher["id"]], {"id": 1, "role": "admin"}, require_other=False)
        self.assertEqual(result["approved"], [voucher["entry_number"]])
        with self.db.connect() as db:
            self.assertEqual(db.execute("SELECT posting_status FROM journal_entries WHERE id=?",
                                        (voucher["id"],)).fetchone()["posting_status"], "posted")

    def test_posted_entry_cannot_be_moved_back_to_draft_for_approval(self):
        voucher = self.voucher(25)["voucher"]
        with self.assertRaisesRegex(ValueError, "immutable"):
            approvals.hold(self.db, voucher["id"], 1)
        with self.db.connect() as db:
            self.assertEqual(db.execute(
                "SELECT posting_status FROM journal_entries WHERE id=?",
                (voucher["id"],),
            ).fetchone()["posting_status"], "posted")

    def test_rejection_restores_draft_lines_and_records_reason(self):
        voucher = self.voucher(25, defer_posting=True)["voucher"]
        approvals.hold(self.db, voucher["id"], 1)
        result = approvals.reject_documents(
            self.db, [voucher["id"]], [], {"id": 1, "role": "admin"}, "Incorrect account")
        self.assertEqual(result["rejected"], [voucher["entry_number"]])
        with self.db.connect() as db:
            row = db.execute(
                "SELECT posting_status,approval_status,rejection_reason FROM journal_entries WHERE id=?",
                (voucher["id"],)).fetchone()
            self.assertEqual((row["posting_status"], row["approval_status"], row["rejection_reason"]),
                             ("draft", "rejected", "Incorrect account"))
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM journal_lines WHERE entry_id=?", (voucher["id"],)
            ).fetchone()[0], 2)

    def test_closed_year_blocks_direct_journal_writes(self):
        with self.db.connect() as db:
            db.execute("INSERT INTO fiscal_years(year,status,opened_at) VALUES(2025,'closed',?)", (utcnow(),))
            with self.assertRaisesRegex(sqlite3.IntegrityError, "FISCAL YEAR CLOSED"):
                db.execute("""INSERT INTO journal_entries(entry_number,entry_date,source_type,currency,created_at)
                    VALUES('CLOSED-2025','10-01-2025','test','USD',?)""", (utcnow(),))

    def test_bank_partial_allocations_reconcile_and_prevent_overallocation(self):
        cash, _counterpart = self.accounts()
        entries = [self.voucher(60), self.voucher(40)]
        with self.db.connect() as db:
            line_ids = [
                db.execute(
                    "SELECT l.id FROM journal_lines l JOIN accounts a ON a.id=l.account_id "
                    "WHERE l.entry_id=? AND a.code=?",
                    (entry["voucher"]["id"], cash),
                ).fetchone()["id"]
                for entry in entries
            ]
        bank_rec.add_statement_lines(self.db, cash, "USD",
            [{"date": "2026-01-10", "description": "Deposit", "amount": "100"}], 1)
        with self.db.connect() as db:
            statement_id = db.execute("SELECT id FROM bank_statement_lines ORDER BY id DESC LIMIT 1").fetchone()["id"]
        bank_rec.match_partial(self.db, statement_id,
            [{"journal_line_id": line_ids[0], "amount": "60"}, {"journal_line_id": line_ids[1], "amount": "40"}], 1)
        with self.db.connect() as db:
            statement = bank_rec.statement_lines(self.db, cash, "2026-01-10", "2026-01-10")[0]
            self.assertTrue(statement["is_matched"])
        bank_rec.add_statement_lines(self.db, cash, "USD",
            [{"date": "2026-01-10", "description": "Second deposit", "amount": "1"}], 1)
        with self.db.connect() as db:
            second_statement_id = db.execute(
                "SELECT id FROM bank_statement_lines ORDER BY id DESC LIMIT 1"
            ).fetchone()["id"]
        with self.assertRaisesRegex(ValueError, "remaining book amount"):
            bank_rec.match_partial(self.db, second_statement_id,
                [{"journal_line_id": line_ids[0], "amount": "1"}], 1)

    def test_forecast_has_thirteen_week_buckets_and_structured_diagnostics(self):
        forecast = cash_forecast_13_week.build(self.db, date(2026, 1, 7))
        self.assertEqual(forecast["weeks"], 13)
        self.assertEqual(len(forecast["rows"]), 13)
        result = diagnostics.build(self.db, "2026-01-07")
        self.assertEqual(result["status"], "passed")
        self.assertEqual({check["id"] for check in result["checks"]},
                         {"audit_chain", "journal_balance", "stock_to_gl", "books_lock"})

    def test_permission_matrix_keeps_diagnostics_admin_only(self):
        admin = {"role": "admin", "permissions": "{}"}
        accountant = {"role": "accountant", "permissions": json.dumps({
            "payroll": False, "vat": True, "delete": False})}
        viewer = {"role": "viewer", "permissions": "{}"}
        self.assertTrue(self.db.user_can(admin, "payroll"))
        self.assertFalse(self.db.user_can(accountant, "payroll"))
        self.assertTrue(self.db.user_can(accountant, "vat"))
        self.assertFalse(self.db.user_can(accountant, "delete"))
        self.assertTrue(self.db.user_can(viewer, "payroll"))
        self.assertFalse(self.db.user_can(viewer, "approve"))
        self.assertTrue(server.admin_only("GET", "/api/diagnostics"))
        self.assertTrue(server.admin_only("GET", "/api/audit-verify"))
        self.assertFalse(server.admin_only("GET", "/api/invoices"))


if __name__ == "__main__":
    unittest.main()
