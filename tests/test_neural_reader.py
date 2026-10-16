"""Neural OCR integration: isolated processes, physical rows, conflicts and manual review."""
import tests_setup  # noqa: F401
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
import neural_reader


def reading(*lines):
    return {"texts":list(lines),"scores":[.98]*len(lines),
            "boxes":[[0,index*40,600,index*40+20] for index in range(len(lines))]}


class NeuralReaderTest(unittest.TestCase):
    def test_tokens_are_joined_only_on_their_physical_row(self):
        data={"texts":["Subtotal", "Total", "60", "60"],"scores":[.99]*4,
              "boxes":[[0,0,100,20],[0,60,100,80],[200,0,240,20],[200,60,240,80]]}
        self.assertEqual(neural_reader.reading_text(data),"Subtotal   60\nTotal   60")

    def test_unreadable_tokens_and_bad_coordinates_are_ignored(self):
        data=reading("Good", "Noise", "Broken")
        data["scores"][1]=.3;data["boxes"][2][0]=float("nan")
        self.assertEqual(neural_reader.reading_text(data), "Good")

    def test_timeout_stops_the_extra_reader_and_is_recoverable(self):
        with patch("neural_reader.subprocess.run",side_effect=subprocess.TimeoutExpired("reader",120)):
            with self.assertRaisesRegex(neural_reader.NeuralReaderError,"too long"):
                neural_reader._run(["reader","file.jpg"],120)

    def test_full_neural_reading_is_reviewed_and_disagreement_is_visible(self):
        local={"text":"", "subtotal":6, "total":None,"notes":"Local"}
        candidate=reading("Invoice No: 51", "Date: 28/09/2026", "Supplier Company",
                          "Subtotal: 60.00 USD", "VAT: 0.00", "Grand Total: 60.00 USD")
        with patch("neural_reader.read",return_value=[candidate]):
            result=neural_reader.enhance("invoice.jpg",local)
        self.assertEqual(result["reader"],"paddle-local")
        self.assertEqual(result["invoice_number"],"51")
        self.assertEqual(result["invoice_date"],"28-09-2026")
        self.assertEqual(result["total"],60)
        self.assertTrue(result["review_required"])
        self.assertTrue(any("disagree on subtotal" in w for w in result["review_warnings"]))

    def test_failed_reader_preserves_local_result_with_warning(self):
        with patch("neural_reader.read",side_effect=neural_reader.NeuralReaderError("offline")):
            result=neural_reader.enhance("invoice.jpg",{"total":40,"notes":"Local"})
        self.assertEqual(result["total"],40)
        self.assertTrue(result["review_required"])
        self.assertIn("offline",result["review_warnings"])

    def test_phone_below_an_empty_heading_is_not_invoice_number(self):
        candidate=reading("فاتورة", "70350623", "Description: repairs", "Grand Total: 40.00 USD")
        with patch("neural_reader.read",return_value=[candidate]):
            result=neural_reader.enhance("invoice.jpg",{"text":"","notes":""})
        self.assertEqual(result["invoice_number"],"")

    def test_worker_is_packaged_with_existing_offline_ocr_assets(self):
        self.assertTrue(neural_reader.worker().is_file())
        self.assertIn('Assets/ocr;ocr', (Path(__file__).resolve().parents[1]/'.github/workflows/build-windows-installer.yml').read_text())

    def test_malformed_response_is_rejected(self):
        with patch("neural_reader.ready",return_value=True),patch("neural_reader._run",return_value='{}'):
            with self.assertRaises(neural_reader.NeuralReaderError):neural_reader.read("invoice.jpg")

    def test_install_prepares_models_before_marking_reader_ready(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            with patch("neural_reader.folder",return_value=base), \
                 patch("neural_reader._run",return_value='{"ready":true}') as run:
                neural_reader.install()
            calls=[list(call.args[0]) for call in run.call_args_list]
            self.assertIn("venv",calls[0])
            self.assertIn("pip",calls[1])
            self.assertEqual(calls[-1][-1],"--prepare")
            self.assertTrue((base/"ready.json").is_file())

    def test_busy_reader_returns_immediately_instead_of_queuing_more_work(self):
        with patch("neural_reader.ready",return_value=True):
            neural_reader._LOCK.acquire()
            try:
                with self.assertRaisesRegex(neural_reader.NeuralReaderError,"busy"):
                    neural_reader.read("invoice.jpg")
            finally:neural_reader._LOCK.release()

    def test_single_scan_uses_extra_reader_when_tesseract_is_unavailable(self):
        from pdf_import import read_invoice_pdf
        local={"text":"","notes":"No Tesseract","ocr_used":False}
        with patch("pdf_import._read_invoice_pdf_local",return_value=local), \
             patch("pdf_import._page_count",return_value=1), \
             patch("neural_reader.ready",return_value=True), \
             patch("neural_reader.enhance",return_value={"total":40}) as enhance:
            self.assertEqual(read_invoice_pdf("invoice.pdf")["total"],40)
        enhance.assert_called_once_with("invoice.pdf",local)

    def test_reader_can_be_disabled_without_removing_models(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);marker=base/"ready.json"
            marker.write_text('{"models":["arabic"]}')
            with patch("neural_reader.folder",return_value=base):
                neural_reader.set_enabled(False)
            state=json.loads(marker.read_text())
            self.assertFalse(state["enabled"])
            self.assertEqual(state["models"],["arabic"])
