"""Read-only counts-only diagnostic tests using synthetic temporary SQLite data."""

import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC = REPOSITORY_ROOT / "tools" / "diagnose_decimals.py"


class DiagnoseDecimalsTest(unittest.TestCase):
    def _synthetic_database(self, path: Path) -> None:
        # closing(): `with connection` only commits; an open handle blocks temp cleanup on Windows (WinError 32).
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE journal_entries (
                    id INTEGER PRIMARY KEY,
                    currency TEXT NOT NULL,
                    posting_status TEXT NOT NULL
                );
                CREATE TABLE journal_lines (
                    id INTEGER PRIMARY KEY,
                    entry_id INTEGER NOT NULL,
                    debit TEXT NOT NULL,
                    credit TEXT NOT NULL,
                    line_currency TEXT
                );
                CREATE TABLE invoices (
                    id INTEGER PRIMARY KEY,
                    currency TEXT NOT NULL,
                    total TEXT,
                    vat TEXT
                );
                """
            )
            connection.executemany(
                "INSERT INTO journal_entries(id,currency,posting_status) VALUES(?,?,?)",
                [(1, "USD", "posted"), (2, "USD", "posted"),
                 (3, "LBP", "posted"), (4, "USD", "posted")],
            )
            connection.executemany(
                "INSERT INTO journal_lines(id,entry_id,debit,credit,line_currency) VALUES(?,?,?,?,?)",
                [
                    (1, 1, "100.000", "0", "USD"),
                    (2, 1, "0", "33.333", "USD"),
                    (3, 1, "0", "33.333", "USD"),
                    (4, 1, "0", "33.334", "USD"),
                    (5, 2, "100.005", "0", "USD"),
                    (6, 2, "0", "100.005", "USD"),
                    (7, 3, "1500000.004", "0", "LBP"),
                    (8, 3, "0", "1500000.004", "LBP"),
                    (9, 4, "10.00", "0", "USD"),
                    (10, 4, "0", "10.00", "USD"),
                ],
            )
            connection.executemany(
                "INSERT INTO invoices(id,currency,total,vat) VALUES(?,?,?,?)",
                [(1, "USD", "100.005", "11.005"),
                 (2, "LBP", "1500000.004", "150000.004"),
                 (3, "USD", "10.00", "0.00")],
            )

    def test_counts_exactly_and_database_is_read_only(self):
        with tempfile.TemporaryDirectory(prefix="nanza-decimal-diagnostic-") as folder:
            database_copy = Path(folder) / "synthetic-copy.db"
            self._synthetic_database(database_copy)
            result = subprocess.run(
                [sys.executable, str(DIAGNOSTIC), str(database_copy), "--confirm-copy"],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            output = result.stdout
            expected = {
                "journal_lines.precision_over_2dp.LBP": "2",
                "journal_lines.precision_over_2dp.non_LBP": "6",
                "journal_lines.text_has_more_than_2_decimal_digits.LBP": "2",
                "journal_lines.text_has_more_than_2_decimal_digits.non_LBP": "6",
                "journal_lines.has_nonzero_digit_beyond_2dp.LBP": "2",
                "journal_lines.has_nonzero_digit_beyond_2dp.non_LBP": "5",
                "invoices.total.precision_over_2dp.LBP": "1",
                "invoices.total.precision_over_2dp.non_LBP": "1",
                "invoices.total.text_has_more_than_2_decimal_digits.LBP": "1",
                "invoices.total.text_has_more_than_2_decimal_digits.non_LBP": "1",
                "invoices.total.has_nonzero_digit_beyond_2dp.LBP": "1",
                "invoices.total.has_nonzero_digit_beyond_2dp.non_LBP": "1",
                "invoices.vat.precision_over_2dp.LBP": "1",
                "invoices.vat.precision_over_2dp.non_LBP": "1",
                "invoices.vat.text_has_more_than_2_decimal_digits.LBP": "1",
                "invoices.vat.text_has_more_than_2_decimal_digits.non_LBP": "1",
                "invoices.vat.has_nonzero_digit_beyond_2dp.LBP": "1",
                "invoices.vat.has_nonzero_digit_beyond_2dp.non_LBP": "1",
                "posted_entries.unbalanced_after_line_rounding": "1",
                "posted_entries.unbalanced_before_rounding": "0",
                "posted_entries.balanced_before_unbalanced_after_rounding": "1",
                "journal_lines.total": "10",
                "journal_entries.total": "4",
            }
            for key, value in expected.items():
                self.assertIn(f"{key}: {value}\n", output)
            # 100.000 has extra textual scale but no non-zero digit beyond cents.
            self.assertIn("journal_lines.precision_over_2dp.non_LBP: 6\n", output)
            self.assertIn("journal_lines.has_nonzero_digit_beyond_2dp.non_LBP: 5\n", output)
            self.assertIn("schema_type.journal_lines.debit: TEXT", output)
            self.assertIn("schema_type.journal_lines.credit: TEXT", output)
            self.assertIn("schema_type.invoices.total: TEXT", output)
            self.assertIn("schema_type.invoices.vat: TEXT", output)
            self.assertIn("schema.non_text_amount_columns: none", output)
            self.assertNotIn(str(database_copy), output)

            read_only_uri = database_copy.resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(read_only_uri, uri=True)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("CREATE TABLE forbidden_write(id INTEGER)")
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
