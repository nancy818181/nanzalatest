"""Synthetic, headless tests for the read-only baseline snapshot command."""

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "baseline_snapshot.py"

EXPECTED = """HEADER: stored-data snapshot only; application report functions NOT run; report-query-only changes are not detected
[CURRENCY USD]
journal_entries.posted: 1
journal_entries.draft: 1
journal_entries.other: 0
journal_lines.count: 6
trial_balance.posted_only.debits: 110.00
trial_balance.posted_only.credits: 110.00
trial_balance.posted_only.difference: 0.00
account_balance.posted_only.asset: 110.00
account_balance.posted_only.liability: 10.00
account_balance.posted_only.equity: 0
account_balance.posted_only.income: 100.00
account_balance.posted_only.expense: 0
trial_balance.all_statuses.debits: 115.00
trial_balance.all_statuses.credits: 115.00
trial_balance.all_statuses.difference: 0.00
account_balance.all_statuses.asset: 105.00
account_balance.all_statuses.liability: 10.00
account_balance.all_statuses.equity: 0
account_balance.all_statuses.income: 100.00
account_balance.all_statuses.expense: 5.00
account.4427.type: liability
account.4427.posted_debits: 0
account.4427.posted_credits: 8.00
account.4427.posted_net_credit_minus_debit: 8.00
account.4427_descendants.count: 2
account.4427_descendants.type.asset: 1
account.4427_descendants.type.liability: 1
account.4427_descendants.type.equity: 0
account.4427_descendants.type.income: 0
account.4427_descendants.type.expense: 0
account.4427_descendants.type.other: 0
account.4427_descendants.posted_debits: 0
account.4427_descendants.posted_credits: 2.00
account.4427_descendants.posted_net_credit_minus_debit: 2.00
invoices.status_kind_count status=draft kind=purchase: 1
invoices.status_kind_count status=posted kind=sale: 1
invoices.linked_entry_not_posted: 1
journal_lines.precision_over_2dp.count: 0
[ALL_CURRENCIES (raw units; no FX conversion)]
journal_entries.posted: 1
journal_entries.draft: 1
journal_entries.other: 0
journal_lines.count: 6
trial_balance.posted_only.debits: 110.00
trial_balance.posted_only.credits: 110.00
trial_balance.posted_only.difference: 0.00
account_balance.posted_only.asset: 110.00
account_balance.posted_only.liability: 10.00
account_balance.posted_only.equity: 0
account_balance.posted_only.income: 100.00
account_balance.posted_only.expense: 0
trial_balance.all_statuses.debits: 115.00
trial_balance.all_statuses.credits: 115.00
trial_balance.all_statuses.difference: 0.00
account_balance.all_statuses.asset: 105.00
account_balance.all_statuses.liability: 10.00
account_balance.all_statuses.equity: 0
account_balance.all_statuses.income: 100.00
account_balance.all_statuses.expense: 5.00
account.4427.type: liability
account.4427.posted_debits: 0
account.4427.posted_credits: 8.00
account.4427.posted_net_credit_minus_debit: 8.00
account.4427_descendants.count: 2
account.4427_descendants.type.asset: 1
account.4427_descendants.type.liability: 1
account.4427_descendants.type.equity: 0
account.4427_descendants.type.income: 0
account.4427_descendants.type.expense: 0
account.4427_descendants.type.other: 0
account.4427_descendants.posted_debits: 0
account.4427_descendants.posted_credits: 2.00
account.4427_descendants.posted_net_credit_minus_debit: 2.00
invoices.status_kind_count status=draft kind=purchase: 1
invoices.status_kind_count status=posted kind=sale: 1
invoices.linked_entry_not_posted: 1
journal_lines.precision_over_2dp.count: 0
vat_return year=2026 quarter=1 deduction_ratio=0.75 net_lbp=10.00 credit_brought_forward_lbp=1.00 payable_lbp=9.00 credit_carried_forward_lbp=0.00 refund_requested_lbp=0.00
books_locked_until.setting: 1
fiscal_years.closed: 1
period_locks: not found
period_closings: not found
"""


class BaselineSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nanza-baseline-synthetic-")
        self.database = Path(self.temp.name) / "synthetic-copy.db"
        self._create_database()

    def tearDown(self):
        self.temp.cleanup()

    def _create_database(self):
        with sqlite3.connect(self.database) as connection:
            connection.executescript(
                """
                CREATE TABLE accounts(id INTEGER PRIMARY KEY, code TEXT UNIQUE, type TEXT);
                CREATE TABLE journal_entries(
                    id INTEGER PRIMARY KEY, currency TEXT NOT NULL, posting_status TEXT NOT NULL,
                    source_type TEXT, source_id INTEGER
                );
                CREATE TABLE journal_lines(
                    id INTEGER PRIMARY KEY, entry_id INTEGER, account_id INTEGER,
                    debit TEXT NOT NULL, credit TEXT NOT NULL
                );
                CREATE TABLE invoices(
                    id INTEGER PRIMARY KEY, currency TEXT, status TEXT, kind TEXT
                );
                CREATE TABLE vat_returns(
                    id INTEGER PRIMARY KEY, year INTEGER, quarter INTEGER, net_lbp TEXT,
                    credit_brought_forward_lbp TEXT, payable_lbp TEXT,
                    credit_carried_forward_lbp TEXT, refund_requested_lbp TEXT,
                    deduction_ratio TEXT, snapshot TEXT, saved_by_name TEXT, saved_at TEXT
                );
                CREATE TABLE app_settings(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE fiscal_years(id INTEGER PRIMARY KEY, year INTEGER, status TEXT);
                INSERT INTO accounts VALUES(1,'1000','asset');
                INSERT INTO accounts VALUES(2,'4427','liability');
                INSERT INTO accounts VALUES(3,'4000','income');
                INSERT INTO accounts VALUES(4,'6000','expense');
                INSERT INTO accounts VALUES(5,'442700001','liability');
                INSERT INTO accounts VALUES(6,'442700002','asset');
                INSERT INTO journal_entries VALUES(1,'USD','posted','invoice',1);
                INSERT INTO journal_entries VALUES(2,'USD','draft','invoice',2);
                INSERT INTO journal_lines VALUES(1,1,1,'110.00','0');
                INSERT INTO journal_lines VALUES(2,1,2,'0','8.00');
                INSERT INTO journal_lines VALUES(3,1,3,'0','100.00');
                INSERT INTO journal_lines VALUES(4,2,4,'5.00','0');
                INSERT INTO journal_lines VALUES(5,2,1,'0','5.00');
                INSERT INTO journal_lines VALUES(6,1,5,'0','2.00');
                INSERT INTO invoices VALUES(1,'USD','posted','sale');
                INSERT INTO invoices VALUES(2,'USD','draft','purchase');
                INSERT INTO vat_returns VALUES(1,2026,1,'10.00','1.00','9.00','0.00','0.00','0.75','PRIVATE SNAPSHOT','PRIVATE USER','PRIVATE DATE');
                INSERT INTO app_settings VALUES('books_locked_until','2025-12-31');
                INSERT INTO fiscal_years VALUES(1,2025,'closed');
                """
            )

    def _run(self, confirm=True):
        command = [sys.executable, str(SCRIPT), str(self.database)]
        if confirm:
            command.append("--confirm-copy")
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=30)

    def test_exact_output_and_deterministic_repeat(self):
        first = self._run()
        second = self._run()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, EXPECTED)
        self.assertEqual(second.stdout.encode("utf-8"), first.stdout.encode("utf-8"))
        self.assertNotIn("PRIVATE", first.stdout)
        self.assertNotIn(str(self.database), first.stdout)

    def test_script_connection_is_read_only(self):
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            from baseline_snapshot import connect_read_only
            connection = connect_read_only(self.database)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("CREATE TABLE forbidden_write(id INTEGER)")
            finally:
                connection.close()
        finally:
            sys.path.remove(str(ROOT / "tools"))

    def test_refuses_without_confirm_copy(self):
        result = self._run(confirm=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirm-copy", result.stderr)

    def test_missing_legacy_tables_are_reported_without_failure(self):
        old_database = Path(self.temp.name) / "older-copy.db"
        with sqlite3.connect(old_database):
            pass
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(old_database), "--confirm-copy"],
            cwd=ROOT, capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("currencies: not found", result.stdout)
        self.assertIn("vat_returns: not found", result.stdout)
        self.assertIn("period_locks: not found", result.stdout)
        self.assertIn("period_closings: not found", result.stdout)

    def test_missing_vat_return_columns_are_reported(self):
        old_database = Path(self.temp.name) / "older-vat-copy.db"
        with sqlite3.connect(old_database) as connection:
            connection.execute("CREATE TABLE vat_returns(year INTEGER,quarter INTEGER,net_lbp TEXT)")
            connection.execute("INSERT INTO vat_returns VALUES(2025,4,'12.50')")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(old_database), "--confirm-copy"],
            cwd=ROOT, capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("vat_return year=2025 quarter=4 deduction_ratio=not found net_lbp=12.50", result.stdout)
        self.assertIn("refund_requested_lbp=not found", result.stdout)


if __name__ == "__main__":
    unittest.main()
