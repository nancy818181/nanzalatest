"""Executive metric provenance, interrupted transactions and concurrent numbering."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import MagicMock,patch
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from database import Database
import executive_dashboard as dashboard
import commercial_documents as commercial


class ExecutiveRecoveryTest(unittest.TestCase):
    def test_damaged_indexes_block_initialization_before_migration(self):
        context=MagicMock();connection=context.__enter__.return_value
        connection.execute.return_value=[("wrong # of entries in index example",)]
        with patch.object(self.db,"connect",return_value=context),patch.object(self.db,"_initialize") as migrate:
            with self.assertRaisesRegex(ValueError,"integrity failed"):self.db.initialize("Recovery-Test-2026!")
        migrate.assert_not_called()
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "books.db"
        self.db = Database(self.path, pooled=True)
        self.db.initialize("Recovery-Test-2026!")
        self.addCleanup(self.db.release)

    def voucher(self, date, debit, credit, amount):
        self.db.save_journal_voucher(
            {"entry_date": date, "currency": "USD", "description": "Acceptance"},
            [
                {"account_code": debit, "debit": amount},
                {"account_code": credit, "credit": amount},
            ],
            1,
        )

    def test_monthly_values_reconcile_and_unavailable_metrics_stay_blank(self):
        self.voucher("15-01-2026", "531", "7011", "100.10")
        self.voucher("20-01-2026", "6263.1", "531", "20.01")
        report = dashboard.build(self.db, "01-01-2026", "31-03-2026", "USD")
        self.assertEqual(report["metrics"]["profit"], Decimal("80.09"))
        self.assertEqual(
            sum(m["profit"] for m in report["months"]), report["metrics"]["profit"]
        )
        for key in (
            "budget_profit",
            "prior_profit",
            "gross_margin",
            "operating_cash_flow",
            "free_cash_flow",
            "forecast",
        ):
            self.assertIsNone(report["metrics"][key], key)
        self.assertFalse(report["budget_available"])

    def test_full_and_partial_month_budget_proration_is_explicit(self):
        self.db.save_budget(
            {
                "year": 2026,
                "currency": "USD",
                "lines": [
                    {"account_code": "7011", "months": [310] + [0] * 11},
                    {"account_code": "6263.1", "months": [62] + [0] * 11},
                ],
            },
            1,
        )
        report = dashboard.build(self.db, "01-01-2026", "10-01-2026", "USD")
        self.assertEqual(report["metrics"]["budget_profit"], Decimal("80"))
        self.assertIn("prorated", " ".join(report["notes"]))

    def test_zero_income_margin_is_unavailable_and_arabic_is_preserved(self):
        report = dashboard.build(
            self.db, "01-01-2026", "31-01-2026", "USD", language="ar"
        )
        self.assertIsNone(report["metrics"]["profit_margin"])
        self.assertTrue(report["rtl"])
        self.assertIn("لوحة", report["title"])

    def test_base_exception_rolls_back_pooled_transaction_before_next_request(self):
        with self.assertRaises(KeyboardInterrupt):
            with self.db.connect() as connection:
                connection.execute(
                    "INSERT INTO app_settings(key,value) VALUES('interruption_probe','not committed')"
                )
                raise KeyboardInterrupt()
        with self.db.connect() as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM app_settings WHERE key='interruption_probe'"
                ).fetchone()
            )
        self.voucher("01-01-2026", "531", "10", "10")
        self.assertEqual(
            dashboard.build(self.db, "01-01-2026", "31-01-2026")["metrics"]["cash"],
            Decimal(10),
        )

    def test_process_death_during_transaction_recovers_without_partial_invoice(self):
        self.db.release()
        code = """import sys,os
import tests
from database import Database
db=Database(sys.argv[1],pooled=True)
with db.connect() as c:
 c.execute('BEGIN IMMEDIATE')
 db.create_manual_invoice({'kind':'sale','invoice_date':'01-01-2026','party_name':'Crash fixture','currency':'USD'},
  [{'description':'Interrupted invoice','quantity':1,'unit_price':100,'vat_rate':0}],1)
 os._exit(19)
"""
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.path)],
            cwd=root,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 19, result.stderr.decode())
        self.assertEqual(self.db.list_invoices(), [])
        with self.db.connect() as c:
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                c.execute(
                    "SELECT COUNT(*) FROM journal_entries WHERE source_type='invoice'"
                ).fetchone()[0],
                0,
            )

    def test_separate_connections_serialize_commercial_numbers_without_duplicates(self):
        party = self.db.save_party(
            {"kind": "supplier", "name": "Concurrency supplier", "currency": "USD"}, 1
        )

        def create(_number):
            db = Database(self.path, pooled=True)
            try:
                return commercial.save(
                    db,
                    {
                        "kind": "purchase_order",
                        "doc_date": "01-01-2026",
                        "party_id": party["id"],
                        "currency": "USD",
                    },
                    [
                        {
                            "description": "Item",
                            "quantity": "1",
                            "unit_price": "1",
                            "vat_rate": "0",
                        }
                    ],
                    1,
                )["number"]
            finally:
                db.release()

        with ThreadPoolExecutor(max_workers=3) as pool:
            numbers = list(pool.map(create, range(12)))
        self.assertEqual(len(set(numbers)), 12)
        with self.db.connect() as c:
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
