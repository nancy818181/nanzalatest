"""2.9.91: speed - dates read once, VAT return reads the documents once per calculation, dashboard reads only its
items, journal table shows the first 5,000 lines (totals on all), pages prepared while the user is idle."""
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import vat_return
from database import Database
from database_common import display_date, iso_date
from desktop_common import sortable_date
from ledger_reports import _digits


class FastDatesTest(unittest.TestCase):
    def test_same_results_and_errors(self):
        self.assertEqual((iso_date("05-03-2025"), iso_date("2025-03-05"), iso_date("05032025")), ("2025-03-05",) * 3)
        with self.assertRaisesRegex(ValueError, "Due date must use"): iso_date("31-02-2025", "Due date")
        self.assertEqual((display_date("2025-03-05"), display_date("bad")), ("05-03-2025", "bad"))
        self.assertEqual(sortable_date("05-03-2025").day, 5); self.assertEqual(_digits("6263.1"), "62631")


class VatOnceTest(unittest.TestCase):
    def test_documents_read_once_per_return(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        db = Database(Path(folder.name) / "v.db"); db.initialize("secret12345"); self.addCleanup(db.release)
        db.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)
        db.create_manual_invoice({"invoice_date": "10-11-2025", "party_name": "C", "kind": "sales", "currency": "USD", "status": "posted"},
                [{"description": "S", "quantity": 1, "unit_price": 100, "vat_rate": 11}], 1)
        memo = {}; vat_return.build_vat_return(db, 2025, 4, _memo=memo)
        self.assertEqual(sum(1 for key in memo if isinstance(key, tuple) and key and key[0] == "documents"), 1)


class IdlePagesTest(unittest.TestCase):
    def test_pages_wait_while_the_user_types(self):
        import desktop
        scheduled = []
        fake = types.SimpleNamespace(_page_generation=1, last_activity=time.monotonic(), after=lambda ms, fn: scheduled.append(ms), _run_page_builder=mock.Mock(),
                                     _finish_pages=mock.Mock())
        fake.__dict__["_pending_builders"] = [lambda: None]
        desktop.SaberApp._build_next_page(fake, 1)
        self.assertEqual(scheduled, [400]); fake._run_page_builder.assert_not_called()  # typing: later
        fake.last_activity = time.monotonic() - 5
        desktop.SaberApp._build_next_page(fake, 1)
        fake._run_page_builder.assert_called_once()  # idle: built


if __name__ == "__main__":
    unittest.main()
