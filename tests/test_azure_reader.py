"""2.9.120: the optional Azure reader - own key kept on this computer, monthly page limit, Azure's answer in the local reading's shape.
Azure itself is never called here: a fake answers as Azure does."""
import tests_setup  # noqa: F401
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError

import azure_reader

ANSWER = {"status": "succeeded", "analyzeResult": {
    "content": "شركة الأرز للتجارة ش.م.ل.\nفاتورة رقم 7781\nالرقم المالي 3344556-601\nورق A4 3 x 20.00 = 60.00\nالمجموع 66.60",
    "documents": [{"confidence": 0.91, "fields": {
        "VendorName": {"type": "string", "valueString": "شركة الأرز للتجارة"}, "VendorTaxId": {"valueString": "3344556-601"},
        "InvoiceId": {"valueString": "7781"}, "InvoiceDate": {"valueDate": "2026-10-03"},
        "SubTotal": {"valueCurrency": {"amount": 60.0, "currencyCode": "USD"}}, "TotalTax": {"valueCurrency": {"amount": 6.6, "currencyCode": "USD"}},
        "InvoiceTotal": {"valueCurrency": {"amount": 66.6, "currencyCode": "USD"}},
        "Items": {"valueArray": [{"valueObject": {"Description": {"valueString": "ورق A4"}, "Quantity": {"valueNumber": 3},
                                                   "UnitPrice": {"valueCurrency": {"amount": 20.0}}, "Amount": {"valueCurrency": {"amount": 60.0}}}}]}}}]}}


class FakeResponse:
    def __init__(self, status, headers=None, body=b""):
        self.status, self.headers, self.body = status, headers or {}, body

    def __enter__(self): return self

    def __exit__(self, *_): return False

    def read(self): return self.body


class FakeAzure:
    """Answers as Azure: 202 + Operation-Location, then 'running', then the result."""
    def __init__(self, answer=ANSWER, refuse=None):
        self.calls, self.answer, self.refuse, self.polls = [], answer, refuse, 0

    def __call__(self, request, timeout=None):
        self.calls.append((request.get_method(), request.full_url, dict(request.header_items())))
        if self.refuse: raise HTTPError(request.full_url, self.refuse, "refused", {}, None)
        if request.get_method() == "POST": return FakeResponse(202, {"Operation-Location": "https://x.cognitiveservices.azure.com/op/1"})
        self.polls += 1
        if self.polls == 1: return FakeResponse(200, {"Retry-After": "1"}, json.dumps({"status": "running"}).encode())
        return FakeResponse(200, {}, json.dumps(self.answer).encode())


class AzureReaderTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.photo = Path(self.folder.name) / "invoice.jpg"; self.photo.write_bytes(b"\xff\xd8\xff fake jpeg")
        self.today = date(2026, 10, 16)

    def setup_key(self, limit=500):
        return azure_reader.save("https://my-company.cognitiveservices.azure.com/", "secret-key-1", limit, self.folder.name)

    def test_settings_stay_on_this_computer_and_the_key_is_not_written_as_typed(self):
        self.assertFalse(azure_reader.ready(self.folder.name))
        state = self.setup_key()
        self.assertEqual((state["ready"], state["endpoint"], state["limit"]), (True, "https://my-company.cognitiveservices.azure.com", 500))
        self.assertNotIn("secret-key-1", (Path(self.folder.name) / azure_reader.SETTINGS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(azure_reader.load(self.folder.name)["key"], "secret-key-1")
        with self.assertRaises(ValueError): azure_reader.save("http://not-secure.example", "k", 500, self.folder.name)
        with self.assertRaises(ValueError): azure_reader.save("https://x.azure.com", "k", "lots", self.folder.name)
        azure_reader.save("", "", 500, self.folder.name)
        self.assertFalse(azure_reader.ready(self.folder.name))

    def test_reading_is_mapped_like_the_local_reading_and_pages_are_counted(self):
        self.setup_key(); fake = FakeAzure(); waits = []
        result = azure_reader.read_invoice(self.photo, self.folder.name, fake, waits.append, self.today)
        method, url, headers = fake.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("/documentintelligence/documentModels/prebuilt-invoice:analyze?api-version=2024-11-30", url)
        self.assertEqual((headers["Ocp-apim-subscription-key"], headers["Content-type"]), ("secret-key-1", "image/jpeg"))
        self.assertEqual(waits, [1.0])
        self.assertEqual((result["invoice_number"], result["invoice_date"], result["currency"]), ("7781", "03-10-2026", "USD"))
        self.assertEqual((result["subtotal"], result["vat"], result["total"]), (60.0, 6.6, 66.6))
        self.assertEqual((result["party_name"], result["supplier_hint"], result["party_tax_number"]), ("شركة الأرز للتجارة",) * 2 + ("3344556-601",))
        self.assertEqual(result["items"], [{"description": "ورق A4", "quantity": 3.0, "unit_price": 20.0, "total": 60.0}])
        self.assertEqual(result["reader"], "azure"); self.assertIn("91% sure", result["notes"])
        self.assertEqual(azure_reader.status(self.folder.name, self.today)["used"], 1)

    def test_the_monthly_limit_stops_before_azure_is_called(self):
        self.setup_key(limit=2)
        for _ in range(2): azure_reader.read_invoice(self.photo, self.folder.name, FakeAzure(), lambda _s: None, self.today)
        fake = FakeAzure()
        with self.assertRaisesRegex(azure_reader.AzureReaderError, "limit is reached"):
            azure_reader.read_invoice(self.photo, self.folder.name, fake, lambda _s: None, self.today)
        self.assertEqual(fake.calls, [])
        self.assertEqual(azure_reader.status(self.folder.name, date(2026, 11, 1))["used"], 0)  # a new month starts at 0

    def test_refusals_say_what_to_do(self):
        with self.assertRaisesRegex(azure_reader.AzureReaderError, "not set up"):
            azure_reader.read_invoice(self.photo, self.folder.name, FakeAzure(), today=self.today)
        self.setup_key()
        with self.assertRaisesRegex(azure_reader.AzureReaderError, "refused the key"):
            azure_reader.read_invoice(self.photo, self.folder.name, FakeAzure(refuse=401), lambda _s: None, self.today)
        with self.assertRaisesRegex(azure_reader.AzureReaderError, "free quota"):
            azure_reader.read_invoice(self.photo, self.folder.name, FakeAzure(refuse=429), lambda _s: None, self.today)
        failed = FakeAzure({"status": "failed", "error": {"message": "Unsupported content"}})
        with self.assertRaisesRegex(azure_reader.AzureReaderError, "Unsupported content"):
            azure_reader.read_invoice(self.photo, self.folder.name, failed, lambda _s: None, self.today)
        big = Path(self.folder.name) / "big.png"; big.write_bytes(b"0" * (azure_reader.FREE_MAX_BYTES + 1))
        with self.assertRaisesRegex(azure_reader.AzureReaderError, "4 MB"):
            azure_reader.read_invoice(big, self.folder.name, FakeAzure(), lambda _s: None, self.today)
        with self.assertRaisesRegex(azure_reader.AzureReaderError, "PDF or a photo"):
            azure_reader.read_invoice(Path(self.folder.name) / "notes.txt", self.folder.name, FakeAzure(), lambda _s: None, self.today)

    def test_a_pdf_counts_at_most_two_pages(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        for _ in range(5): writer.add_blank_page(width=200, height=200)
        pdf = Path(self.folder.name) / "five.pdf"
        with pdf.open("wb") as handle: writer.write(handle)
        self.assertEqual(azure_reader.pages_of(pdf), 2)
        self.assertEqual(azure_reader.pages_of(self.photo), 1)


if __name__ == "__main__":
    unittest.main()
