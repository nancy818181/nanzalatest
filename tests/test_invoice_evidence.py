import json
import unittest
from unittest.mock import patch

import vision_reader as vr
from invoice_evidence import analyze


class InvoiceEvidenceTest(unittest.TestCase):
    def test_wrong_line_arithmetic_is_flagged_without_repairing_written_numbers(self):
        values = {"subtotal_as_written": "40", "items_as_written": [{"description_as_written": "تصليح",
            "quantity_as_written": "٢", "unit_price_as_written": "٢٠", "total_as_written": "٤"}]}
        evidence = analyze(values, vr._written_money)
        row = evidence["line_evidence"][0]
        self.assertEqual(row["numbers"]["total_as_written"], 4)
        self.assertEqual(row["literal"]["total_as_written"], "٤")
        self.assertTrue(evidence["warnings"])

    def test_uncertain_header_values_never_enter_consensus_even_if_both_readers_agree(self):
        values = {"total_as_written": "40", "date_as_written": "03/04/2026", "date_ambiguous": True,
                  "uncertain_fields": ["total_as_written"]}
        with patch.object(vr, "read_text", return_value=json.dumps(values)):
            result = vr.read_invoice("demo.jpg")
        self.assertIsNone(result["total"])
        self.assertEqual(result["invoice_date"], "")
        self.assertNotIn("total", result["consensus_fields"])

    def test_date_ambiguity_does_not_depend_on_the_model_admitting_uncertainty(self):
        evidence = analyze({"date_as_written": "٠٣/٠٤/٢٠٢٦", "date_ambiguous": False}, vr._written_money)
        self.assertIn("invoice_date", evidence["uncertain_fields"])
        self.assertNotIn("invoice_date", analyze({"date_as_written": "2026-04-03"}, vr._written_money)["uncertain_fields"])

    def test_partial_rows_never_masquerade_as_complete_item_extraction(self):
        values = {"items_truncated": True, "items_as_written": [{"description_as_written": "item",
            "quantity_as_written": "1", "unit_price_as_written": None, "total_as_written": "40"}]}
        evidence = analyze(values, vr._written_money)
        self.assertTrue(evidence["items_truncated"])
        self.assertIsNone(evidence["line_evidence"][0]["numbers"]["unit_price_as_written"])
        self.assertIsNone(evidence["line_evidence"][0]["arithmetic_difference"])
        self.assertTrue(evidence["warnings"])

    def test_item_evidence_never_becomes_an_accounting_line_without_review(self):
        values = {"items_as_written": [{"description_as_written": "item", "quantity_as_written": "1",
            "unit_price_as_written": "40", "total_as_written": "40"}]}
        with patch.object(vr, "read_text", return_value=json.dumps(values)):
            result = vr.read_invoice("demo.jpg")
        self.assertEqual(result["items"], [])
        self.assertEqual(len(result["reader_evidence"]["qwen4b"]["line_evidence"]), 1)
        self.assertEqual(len(result["reader_evidence"]["qwen2b"]["line_evidence"]), 1)

    def test_uncertain_item_amount_is_not_used_for_arithmetic(self):
        values = {"items_as_written": [{"description_as_written": "item", "quantity_as_written": "1",
            "unit_price_as_written": "40", "total_as_written": "4", "uncertain_fields": ["total_as_written"]}]}
        evidence = analyze(values, vr._written_money)
        self.assertIsNone(evidence["line_evidence"][0]["numbers"]["total_as_written"])

    def test_secondary_reader_warning_is_not_lost(self):
        from reader_consensus import merge_invoice_readings
        result = merge_invoice_readings({"total": 40}, {"total": 40, "review_warnings": ["Item row is doubtful"]})
        self.assertIn("Item row is doubtful", result["review_warnings"])

    def test_schema_marker_tracks_salary_payment_migrations(self):
        import database
        import payroll_payments
        before = database._schema_fingerprint()
        def changed(_connection):
            return "A future salary payment schema change"
        with patch.object(payroll_payments, "migrate", changed):
            self.assertNotEqual(before, database._schema_fingerprint())


if __name__ == "__main__": unittest.main()
