import unittest
from tools.benchmark_invoice_reader import score


class ReaderBenchmarkTest(unittest.TestCase):
    def test_abstentions_and_high_confidence_do_not_inflate_accuracy(self):
        labels = [{"id": "one", "verified": True, "expected": {"total": 40, "vat": None, "invoice_date": "2026-01-10"}}]
        result = score(labels, {"one": {"confidence": 1, "total": None, "vat": 0, "invoice_date": "10-01-2026"}})
        self.assertEqual(result["reading_accuracy"], .5)
        self.assertEqual(result["false_fills"], 1)
        self.assertEqual(result["exact_documents"], 0)

    def test_all_empty_reading_is_zero_for_present_fields(self):
        result = score([{"id": "one", "verified": True, "expected": {"total": 40, "currency": "USD"}}], {})
        self.assertEqual(result["reading_accuracy"], 0)

    def test_unverified_or_duplicate_labels_are_rejected(self):
        with self.assertRaises(ValueError): score([{"id": "one", "expected": {"total": 40}}], {})
        row = {"id": "one", "verified": True, "expected": {"total": 40}}
        with self.assertRaises(ValueError): score([row, row], {})


if __name__ == "__main__": unittest.main()
