"""2.9.61: a failing request says what failed; values json cannot write no longer fail a request."""
import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

import server


class ErrorDetailTests(unittest.TestCase):
    def test_json_values(self):
        text = json.dumps({"a": Decimal("1.50"), "d": date(2024, 1, 16), "b": b"x", "s": {1}}, default=server._json_value)
        self.assertEqual(json.loads(text), {"a": "1.50", "d": "2024-01-16", "b": None, "s": [1]})

    def test_500_message_names_the_request_and_error(self):
        source = (Path(server.__file__)).read_text(encoding="utf-8")
        self.assertIn("{self.command} {urlparse(self.path).path} - {detail}", source)

    def test_open_entry_reports_the_step(self):
        from types import SimpleNamespace
        from unittest import mock
        import desktop_balance_reports as reports
        def broken(): raise RuntimeError("boom")
        app = SimpleNamespace(client=SimpleNamespace(invoices=broken))
        shown = []
        with mock.patch.object(reports.messagebox, "showerror", side_effect=lambda title, text: shown.append(text)):
            result = reports.BalanceReportsMixin.open_entry_source(app, {"source_type": "invoice", "source_id": 5, "entry_number": "INV-1249"})
        self.assertFalse(result)
        self.assertIn("Step: reading the invoice list (INV-1249)", shown[0])


if __name__ == "__main__":
    unittest.main()
