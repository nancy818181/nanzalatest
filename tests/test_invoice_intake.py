"""Deterministic routing/safety tests, not real-invoice OCR accuracy benchmarks."""

import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import invoice_intake as intake
from pdf_import import _parse_invoice_text

CHART = [
    {"code": "626300099", "name_en": "Office rent", "name_fr": "Loyer bureau", "name_ar": "ايجار المكتب", "active": 1},
    {"code": "224400099", "name_en": "Computer equipment", "name_fr": "Ordinateur", "active": 1},
    {"code": "626300098", "name_en": "Office rent", "active": 0},
]
TEXT = "Vendor Example SARL\nInvoice No: TEST-151\nDate: 15-01-2026\nCurrency: USD\nSubtotal: 100.00\nVAT: 11.00\nGrand Total: 111.00\nOffice rent"


class IntakeSafetyTest(unittest.TestCase):
    def test_missing_read_currency_cannot_fall_back_to_default_at_purchase_save(self):
        from desktop_purchases import PurchasesMixin
        values = {key: SimpleNamespace(get=lambda value=value: value) for key, value in
                  {"account": "601", "type": "Purchases", "supplier": "Vendor", "currency": ""}.items()}
        app = SimpleNamespace(purchase_form={"vars": values}, purchase_items_changed=lambda: None)
        with self.assertRaisesRegex(ValueError, "invoice currency"):
            PurchasesMixin.purchase_payload(app)

    def test_item_sum_is_checked_without_replacing_the_read_subtotal(self):
        result = intake.enrich(self.reading(items=[
            {"description": "Rent", "quantity": 1, "unit_price": 90, "total": 90}
        ]))
        self.assertEqual(result["subtotal"], 100)
        self.assertTrue(any("Sum of item totals" in warning for warning in result["review_warnings"]))

    def test_custom_chart_types_override_numbering_and_headings_are_excluded(self):
        accounts = [
            {"id": 1, "code": "EXP", "name_en": "Office rent", "type": "expense"},
            {"id": 2, "parent_id": 1, "code": "R100", "name_en": "Office rent", "type": "expense"},
            {"id": 3, "code": "626999", "name_en": "Office rent", "type": "liability"},
        ]
        result = intake.chart_suggestion("Office rent", accounts, "operating_expense")
        self.assertEqual(result["account_code"], "R100")

    def reading(self, **kwargs):
        return {
            "text": TEXT,
            "invoice_number": "TEST-151",
            "invoice_date": "15-01-2026",
            "party_name": "Vendor Example SARL",
            "currency": "USD",
            "subtotal": 100,
            "vat": 11,
            "total": 111,
            "items": [],
            **kwargs,
        }

    def test_every_header_has_provenance_unknown_confidence_and_review(self):
        result = intake.enrich(self.reading(), CHART)
        self.assertEqual(set(result["fields"]), set(intake.FIELDS))
        self.assertTrue(all(field["requires_review"] for field in result["fields"].values()))
        self.assertIsNone(result["fields"]["total"]["confidence"])
        self.assertIsNone(result["payment_status"])
        self.assertTrue(result["review_required"])
        self.assertTrue(result["review_warnings"])

    def test_inferred_missing_uncertain_fields_are_not_presented_as_certain(self):
        result = intake.enrich(self.reading(subtotal=None, vat=None, inferred=["subtotal"]))
        self.assertEqual(result["fields"]["subtotal"]["origin"], "missing")
        result = intake.enrich(self.reading(inferred=["subtotal"], field_confidence={"SubTotal": 0.99}))
        self.assertEqual(result["fields"]["subtotal"]["origin"], "inferred")
        self.assertIsNone(result["fields"]["subtotal"]["confidence"])

    def test_languages_document_categories_and_original_descriptions(self):
        for text, kind in (
            ("Invoice office rent", "invoice"),
            ("Facture loyer bureau", "invoice"),
            ("فاتورة ايجار المكتب", "invoice"),
            ("Avoir fournisseur", "credit_note"),
            ("إشعار مدين", "debit_note"),
            ("Devis ordinateur", "quotation"),
        ):
            with self.subTest(text=text):
                result = intake.enrich(self.reading(text=text), CHART)
                self.assertEqual(result["document_type"], kind)
                self.assertEqual(result["text"], text)
        for text in ("Office rent", "Loyer bureau", "ايجار المكتب"):
            self.assertEqual(intake.category_for(text)["category"], "operating_expense")

    def test_invoice_and_line_accounts_belong_to_active_company_chart(self):
        result = intake.enrich(
            self.reading(
                text="Facture Loyer bureau",
                items=[{"description": "Loyer bureau", "quantity": 1, "unit_price": 100, "total": 100}],
            ),
            CHART,
        )
        self.assertEqual(result["account_suggestion"]["account_code"], "626300099")
        self.assertEqual(result["items"][0]["account_suggestion"]["account_code"], "626300099")
        self.assertIsNone(result["items"][0]["vat_suggestion"]["treatment"])
        for chart in ([], [{"code": "699999999", "name_en": "Unrelated consulting"}]):
            self.assertIsNone(intake.enrich(self.reading(), chart)["account_suggestion"]["account_code"])
        custom = [{"code": "621777777", "name_fr": "Loyer bureau", "active": 1}]
        self.assertEqual(
            intake.enrich(self.reading(text="Loyer bureau"), custom)["account_suggestion"]["account_code"], "621777777"
        )

    def test_mismatches_are_flagged_not_mathematically_repaired(self):
        result = intake.enrich(
            self.reading(total=112, items=[{"description": "Loyer", "quantity": 2, "unit_price": 20, "total": 35}]),
            CHART,
        )
        self.assertEqual(result["total"], 112)
        self.assertEqual(result["items"][0]["total"], 35)
        self.assertTrue(any("Subtotal + VAT" in w for w in result["review_warnings"]))
        self.assertTrue(any("quantity" in w for w in result["review_warnings"]))

    def test_duplicates_match_supplier_and_number_not_only_amount(self):
        result = intake.enrich(
            self.reading(),
            CHART,
            existing_documents=[
                {"id": 8, "invoice_number": "TEST-151", "party_name": "Vendor Example SARL"},
                {"id": 9, "invoice_number": "TEST-151", "party_name": "Different supplier"},
            ],
        )
        self.assertEqual([r["id"] for r in result["duplicate_candidates"]], [8])

    def test_azure_requires_explicit_reader_selection(self):
        with patch("pdf_import.read_invoice_pdf", return_value=self.reading()) as local, patch(
            "azure_reader.read_invoice", return_value=self.reading()
        ) as cloud:
            intake.read("a.pdf", CHART)
            local.assert_called_once()
            cloud.assert_not_called()
            intake.read("a.pdf", CHART, reader="azure")
            cloud.assert_called_once()
        with self.assertRaises(ValueError):
            intake.read("a.pdf", reader="automatic-cloud")

    def test_digital_pdf_uses_embedded_text_without_ocr(self):
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "digital.pdf"
            pdf = canvas.Canvas(str(path))
            y = 780
            for line in TEXT.splitlines():
                pdf.drawString(40, y, line)
                y -= 20
            pdf.save()
            with patch("vision_reader.ready", return_value=False), patch(
                "neural_reader.ready", return_value=False
            ), patch("pdf_import._ocr_pdf", side_effect=AssertionError("Digital PDF must use text")):
                result = intake.read(path, CHART)
            self.assertEqual(result["invoice_number"], "TEST-151")
            self.assertEqual(result["total"], 111)
            self.assertTrue(result["review_required"])

    def test_embedded_french_and_arabic_pdf_text_remains_local(self):
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from tests import ROOT

        pdfmetrics.registerFont(TTFont("IntakeArabic", str(ROOT / "Assets/fonts/Amiri-Regular.ttf")))
        with tempfile.TemporaryDirectory() as folder:
            for language, text in (
                ("fr", "Facture fournisseur\nLoyer bureau\nTotal HT: 100.00\nTVA: 11.00\nTotal TTC: 111.00\nUSD"),
                ("ar", "فاتورة\nشركة الارز\nايجار المكتب\nUSD 111.00"),
            ):
                path = Path(folder) / (language + ".pdf")
                pdf = canvas.Canvas(str(path))
                pdf.setFont("IntakeArabic", 14)
                for index, line in enumerate(text.splitlines()):
                    pdf.drawString(30, 780 - index * 24, line)
                pdf.save()
                with patch("vision_reader.ready", return_value=False), patch(
                    "neural_reader.ready", return_value=False
                ), patch("pdf_import._ocr_pdf", return_value=text) as ocr:
                    result = intake.read(path, CHART)
                self.assertTrue(result["review_required"])
                self.assertTrue(result["text"].strip())
                if language == "fr":
                    self.assertIn("Loyer", result["text"])
                else:
                    self.assertTrue(any("\u0600" <= c <= "\u06ff" for c in result["text"]))

    def test_scanned_pdf_and_photo_use_local_ocr_with_review(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder) / "scan.jpg"
            pdf = Path(folder) / "scan.pdf"
            image = Image.new("RGB", (500, 700), "white")
            image.save(photo)
            image.save(pdf, "PDF")
            image.close()
            for path in (pdf, photo):
                with self.subTest(path=path.suffix), patch("vision_reader.ready", return_value=False), patch(
                    "neural_reader.ready", return_value=False
                ), patch("pdf_import._ocr_pdf", return_value=TEXT) as ocr:
                    result = intake.read(path, CHART)
                    self.assertTrue(ocr.called)
                    self.assertTrue(result["review_required"])
                    self.assertEqual(result["total"], 111)

    def test_handwriting_abstention_is_preserved(self):
        reading = self.reading(
            reader="vision-local",
            total=None,
            invoice_date="",
            review_required=True,
            review_warnings=["Uncertain handwritten total"],
        )
        with patch("pdf_import.read_invoice_pdf", return_value=reading):
            result = intake.read("handwritten.jpg", CHART)
        self.assertIsNone(result["total"])
        self.assertEqual(result["fields"]["total"]["origin"], "missing")
        self.assertIn("Uncertain handwritten total", result["review_warnings"])

    def test_azure_computed_subtotal_and_missing_item_quantity_are_explicit(self):
        from azure_reader import to_result

        analysis = {
            "content": TEXT,
            "documents": [
                {
                    "fields": {
                        "InvoiceTotal": {"valueCurrency": {"amount": 111, "currencyCode": "USD"}},
                        "TotalTax": {"valueCurrency": {"amount": 11, "currencyCode": "USD"}},
                        "Items": {
                            "valueArray": [
                                {
                                    "valueObject": {
                                        "Description": {"valueString": "Loyer"},
                                        "Amount": {"valueCurrency": {"amount": 100}},
                                    }
                                }
                            ]
                        },
                    }
                }
            ],
        }
        # Force no locally read subtotal so this checks the Azure arithmetic fallback.
        with patch("pdf_import._parse_invoice_text", return_value=self.reading(subtotal=None)):
            result = intake.enrich(to_result("cloud.pdf", analysis), CHART)
        self.assertEqual(result["fields"]["subtotal"]["origin"], "inferred")
        self.assertIsNone(result["items"][0]["quantity"])
        self.assertIsNone(result["items"][0]["unit_price"])


if __name__ == "__main__":
    unittest.main()
