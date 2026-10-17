"""Literal interpretation and prompt safeguards; no model accuracy claim."""

import json
import unittest
from unittest.mock import patch
import vision_reader as reader
from invoice_evidence import PROMPT, literal_schema


class ReaderImprovementsTest(unittest.TestCase):
    def read(self, **changes):
        data = {
            "document_type": "invoice",
            "invoice_number": "E-1",
            "invoice_date": "2026-10-15",
            "supplier": {"name": "مؤسسة التجربة", "tax_id": "٠١٢٣٤٥٦"},
            "currency": "USD",
            "subtotal": 100,
            "tax": 11,
            "total": 111,
            "items": [],
        }
        data.update(changes)
        with patch.object(
            reader, "read_text", return_value=json.dumps(data, ensure_ascii=False)
        ):
            return reader.read_invoice("fixture.jpg")

    def test_owner_schema_reads_supplier_tax_id_original_script_and_explicit_amounts(
        self,
    ):
        data = self.read()
        self.assertEqual(data["party_name"], "مؤسسة التجربة")
        self.assertEqual(data["party_tax_number"], "0123456")
        self.assertEqual(data["total"], 111)
        self.assertEqual(data["prompt_version"], "nanza-literal-v2")
        self.assertTrue(data["review_required"])

    def test_self_confidence_and_payment_status_do_not_authorize_posting(self):
        data = self.read(
            confidence=1,
            needs_review=False,
            payment_method="cash",
            payment_status="paid",
        )
        self.assertTrue(data["review_required"])
        self.assertNotIn("payment_status", data)
        self.assertNotIn("field_confidence", data)

    def test_nested_uncertainty_withholds_tax_id_and_line_amount(self):
        data = self.read(
            uncertain_fields=["supplier.tax_id", "items[0].total"],
            items=[
                {"description": "صيانة", "quantity": 1, "unit_price": 100, "total": 100}
            ],
        )
        self.assertEqual(data["party_tax_number"], "")
        self.assertIsNone(
            data["transcription_evidence"]["line_evidence"][0]["numbers"][
                "total_as_written"
            ]
        )

    def test_unreadable_values_are_not_repaired_from_arithmetic(self):
        data = self.read(total=None, tax=None)
        self.assertIsNone(data["total"])
        self.assertIsNone(data["vat"])

    def test_french_and_arabic_explicit_separators(self):
        for value in ("1.234,56 EUR", "1\u202f234,56 €", "١٬٢٣٤٫٥٦", "1,234.56 USD"):
            self.assertEqual(reader._written_money(value), 1234.56, value)
        for value in ("1,234", "1,2,3", "12O,50", "1/7", True):
            self.assertIsNone(reader._written_money(value), value)

    def test_more_than_four_rows_remain_separate_evidence(self):
        data = self.read(
            items=[
                {
                    "description": f"Line {i}",
                    "quantity": 1,
                    "unit_price": 10,
                    "total": 10,
                }
                for i in range(8)
            ]
        )
        self.assertEqual(len(data["transcription_evidence"]["line_evidence"]), 8)
        self.assertEqual(data["items"], [])
        self.assertIn("twelve", PROMPT)

    def test_existing_literal_schema_is_preserved(self):
        original = {"date_as_written": "15/10/2026", "total_as_written": "100"}
        self.assertEqual(literal_schema(original), original)

    def test_disputed_tax_identity_is_not_selected_from_one_reader(self):
        first = {"supplier_tax_id_as_written": "123", "total_as_written": "100"}
        second = {"supplier_tax_id_as_written": "128", "total_as_written": "100"}
        with patch.object(
            reader, "read_text", side_effect=[json.dumps(first), json.dumps(second)]
        ):
            data = reader.read_invoice("fixture.jpg")
        self.assertEqual(data["party_tax_number"], "")


if __name__ == "__main__":
    unittest.main()
