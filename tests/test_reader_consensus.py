"""Independent readings cannot certify handwriting or fill each other's missing amounts."""
import tests_setup  # noqa: F401
import json
import threading
import unittest
from unittest.mock import patch
from reader_consensus import merge_invoice_readings
import vision_reader


class ReaderConsensusTest(unittest.TestCase):
    def test_disputed_and_single_reader_amounts_are_withheld(self):
        first = {"subtotal": 40, "total": 40, "vat": None, "party_name": "Workshop A"}
        second = {"subtotal": 4, "total": None, "vat": None, "party_name": "Customer B"}
        result = merge_invoice_readings(first, second)
        for field in ("subtotal", "total", "vat", "acquisition_cost"): self.assertIsNone(result[field])
        self.assertEqual(result["party_name"], "")
        self.assertEqual(result["reader_candidates"]["qwen4b"]["total"], 40)
        self.assertEqual(first["total"], 40)

    def test_agreement_and_explicit_zero_still_require_review(self):
        result = merge_invoice_readings({"subtotal": "60.00", "total": 60, "vat": 0},
                                        {"subtotal": 60, "total": "60.0", "vat": "0.00"})
        self.assertEqual(result["vat"], 0)
        self.assertIn("total", result["consensus_fields"])
        self.assertTrue(result["review_required"])
        self.assertIn("same wrong value", " ".join(result["review_warnings"]))

    def test_reordered_or_unmatched_items_are_not_positionally_combined(self):
        first = {"items": [{"description": "Rent", "total": 100}, {"description": "Water", "total": 20}]}
        second = {"items": list(reversed(first["items"]))}
        result = merge_invoice_readings(first, second)
        self.assertEqual(result["items"], [])
        self.assertEqual(len(result["reader_item_candidates"]["qwen4b"]), 2)

    def test_boolean_and_nonfinite_values_are_not_agreements(self):
        for value in (True, float("nan"), float("inf")):
            with self.subTest(value=value):
                result = merge_invoice_readings({"total": value}, {"total": value})
                self.assertIsNone(result["total"])

    def test_the_two_readers_are_independent_and_their_conflict_reaches_the_result(self):
        def text(total):
            return json.dumps({"invoice_number": "02", "subtotal_as_written": total, "total_as_written": total,
                               "supplier_as_written": "Workshop", "date_as_written": "10/1/2026"})
        with patch.object(vision_reader, "read_text", side_effect=[text("40"), text("4")]) as read:
            result = vision_reader.read_invoice("synthetic.jpg")
        self.assertEqual(read.call_args_list[0].kwargs, {})
        self.assertEqual(read.call_args_list[1].kwargs, {"secondary": True})
        self.assertIsNone(result["total"])
        self.assertTrue(result["review_required"])

    def test_cancel_between_readers_does_not_start_the_second_model(self):
        event = threading.Event()
        def first(*args, **kwargs):
            event.set()
            return '{"total_as_written":"40"}'
        with patch.object(vision_reader, "read_text", side_effect=first) as read:
            with self.assertRaises(vision_reader.VisionReadCancelled):
                vision_reader.read_invoice("synthetic.jpg", event)
        self.assertEqual(read.call_count, 1)


if __name__ == "__main__": unittest.main()
