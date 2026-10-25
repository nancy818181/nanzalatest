"""Review gates and background dispatch for document reading."""
import tests_setup  # noqa: F401
import tempfile
import unittest
import threading
from contextlib import ExitStack
import numpy  # Load before OCR tests patch sys.modules; native modules must not be re-imported.
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class ReadingSafetyTest(unittest.TestCase):
    def test_a_photo_cannot_be_implicitly_confirmed_without_a_review_window(self):
        from desktop_stage3_common import review_handwriting
        data = {"reader": "paddle-local", "ocr_used": True, "total": 60}
        self.assertIsNone(review_handwriting(SimpleNamespace(), "invoice.jpg", data))
        self.assertEqual(data["total"], 60)
        digital = {"total": 60}
        self.assertIs(review_handwriting(SimpleNamespace(), "invoice.pdf", digital), digital)

    def test_forced_document_review_cannot_be_bypassed_without_a_window(self):
        from desktop_stage3_common import review_handwriting, auto_upload_on
        data={"total":60}
        self.assertIsNone(review_handwriting(SimpleNamespace(),"invoice.pdf",data,force=True))
        self.assertFalse(auto_upload_on(SimpleNamespace(auto_upload_var=lambda:SimpleNamespace(get=lambda:True))))

    def test_reviewed_amount_checks_warn_without_rewriting_values(self):
        from desktop_stage3_common import reviewed_invoice_checks
        data={"currency":"USD","subtotal":"100.00","vat":"11.00","total":"120.00","duplicate_candidates":[{"id":1}]}
        reviewed_invoice_checks(SimpleNamespace(currency_codes=["USD","LBP"]),data)
        self.assertEqual((data["subtotal"],data["vat"],data["total"]),("100.00","11.00","120.00"))
        self.assertTrue(any("do not reconcile" in warning for warning in data["review_warnings"]))
        self.assertTrue(any("duplicate" in warning for warning in data["review_warnings"]))

    def test_batch_import_compatibility_callback_cannot_post(self):
        from desktop_stage3 import Stage3Mixin
        with patch("desktop_stage3.messagebox.showwarning") as warning:
            Stage3Mixin.send_import(SimpleNamespace(),auto=True)
        warning.assert_called_once()

    def test_pdf_batch_needs_original_review_before_manual_save(self):
        from desktop_stage3 import Stage3Mixin
        client=SimpleNamespace(import_invoices=Mock())
        screen=SimpleNamespace(import_mode="pdf",import_sheet=SimpleNamespace(ordered=lambda:[{"line":"1"}]),client=client)
        with patch("desktop_stage3.messagebox.showwarning") as warning:
            Stage3Mixin.send_import(screen)
        self.assertIn("Review the original",warning.call_args.args[1])
        client.import_invoices.assert_not_called()

    def test_cancelled_expense_review_keeps_the_previous_attachment(self):
        from desktop_expenses import ExpensesMixin
        form = {"id": None, "pdf": "previous.pdf", "pdf_suggested_type": "Expenses"}
        app = SimpleNamespace(expense_form=form)
        with patch("desktop_expenses.filedialog.askopenfilename", return_value="new.jpg"), \
             patch("desktop_expenses.prepare_pdf_reading"), \
             patch("desktop_expenses.run_with_progress") as background:
            ExpensesMixin.choose_expense_pdf(app)
        self.assertEqual(form["pdf"], "previous.pdf")
        with patch("desktop_stage3_common.review_handwriting", return_value=None):
            background.call_args.args[3]({"reader": "vision-local"})
        self.assertEqual(form["pdf"], "previous.pdf")
        self.assertEqual(form["pdf_suggested_type"], "Expenses")

    def test_window_dispatch_starts_work_and_delivers_result_on_ui_thread(self):
        import desktop_stage3_common as common
        real_thread = threading.Thread
        main_thread = threading.get_ident()
        for unit in ("page", "bytes"):
            with self.subTest(unit=unit), ExitStack() as stack:
                callbacks, threads, worker_ids, delivery_ids = [], [], [], []
                class Window:
                    def after(self, delay, callback): callbacks.append(callback)
                app = Window()
                stack.enter_context(patch.object(common.tk, "Misc", Window))
                for owner, name in ((common.tk, "Toplevel"), (common.tk, "Label"),
                                    (common.tk, "Button"), (common.ttk, "Progressbar")):
                    stack.enter_context(patch.object(owner, name))
                def start_thread(**kwargs):
                    thread = real_thread(**kwargs); threads.append(thread); return thread
                stack.enter_context(patch.object(common.threading, "Thread", side_effect=start_thread))
                def work(progress, cancel):
                    worker_ids.append(threading.get_ident()); progress(1, 2, "Reading")
                    return {"total": 60}
                def done(result):
                    self.assertEqual(result, {"total": 60}); delivery_ids.append(threading.get_ident())
                common.run_with_progress(app, "Read", work, done, unit=unit)
                self.assertEqual(len(threads), 1)
                threads[0].join(timeout=2)
                self.assertFalse(threads[0].is_alive())
                self.assertNotEqual(worker_ids, [main_thread])
                self.assertEqual(delivery_ids, [])
                callbacks.pop(0)()
                self.assertEqual(delivery_ids, [main_thread])

    def test_expense_reading_is_dispatched_before_ocr_starts(self):
        from desktop_expenses import ExpensesMixin
        app = SimpleNamespace(expense_form={"id": None})
        with patch("desktop_expenses.filedialog.askopenfilename", return_value="invoice.jpg"), \
             patch("desktop_expenses.prepare_pdf_reading"), \
             patch("desktop_expenses.run_with_progress") as background, \
             patch("desktop_expenses.read_invoice_pdf", return_value={"total": 40}) as read:
            ExpensesMixin.choose_expense_pdf(app)
            read.assert_not_called()
            self.assertEqual(background.call_args.args[2](None, None), {"total": 40})
            read.assert_called_once_with("invoice.jpg", cancel=None)

    def test_asset_reading_is_dispatched_before_ocr_starts(self):
        from desktop_asset_register import AssetRegisterMixin
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invoice.pdf"; path.write_bytes(b"test")
            with patch("desktop_asset_register.filedialog.askopenfilename", return_value=str(path)), \
                 patch("desktop_stage3_common.prepare_pdf_reading"), \
                 patch("desktop_asset_register.run_with_progress") as background, \
                 patch("desktop_asset_register.read_invoice_pdf", return_value={}) as read:
                AssetRegisterMixin.choose_asset_pdf(SimpleNamespace())
                read.assert_not_called()
                background.call_args.args[2](None, None)
            read.assert_called_once_with(str(path), cancel=None)

    def test_sales_reading_is_dispatched_before_ocr_starts(self):
        from desktop_v22 import V22Mixin
        with patch("desktop_v22.filedialog.askopenfilename", return_value="invoice.pdf"), \
             patch("desktop_stage3_common.prepare_pdf_reading"), \
             patch("desktop_stage3_common.run_with_progress") as background, \
             patch("pdf_import.read_invoice_pdf", return_value={}) as read:
            V22Mixin.import_sales_pdf(SimpleNamespace())
            read.assert_not_called()
            background.call_args.args[2](None, None)
            read.assert_called_once_with("invoice.pdf", cancel=None)

    def test_utility_total_is_not_fabricated_from_base_plus_vat(self):
        from pdf_import import _utility_bill
        self.assertIsNone(_utility_bill("TOTAL TRANCHES 671,250 TVA 73,838"))

    def test_photo_preparation_preserves_original(self):
        from PIL import Image, ImageDraw
        from ocr_photo import variants
        original=Image.new("RGB", (400, 500), "white")
        ImageDraw.Draw(original).text((40, 40), "Invoice 42", fill="black")
        before=original.tobytes()
        prepared=variants(original)
        self.assertEqual(original.tobytes(), before)
        self.assertEqual(len(prepared), 2)
        for image in prepared:
            self.assertGreater(image.width, 100)
            self.assertGreater(image.height, 100)
            image.close()

    def test_local_review_warning_is_idempotent(self):
        from pdf_import import _require_ocr_review
        result={"notes": "Read locally"}
        _require_ocr_review(result); _require_ocr_review(result)
        self.assertTrue(result["review_required"])
        self.assertEqual(len(result["review_warnings"]), len(set(result["review_warnings"])))
        self.assertTrue(any("VAT" in warning for warning in result["review_warnings"]))

    def test_merging_readings_preserves_inference_warnings(self):
        from pdf_import import _merge_invoice_suggestions, _require_ocr_review
        result = _merge_invoice_suggestions({}, {"total": 111, "inferred": ["total calculated"],
                                                 "review_warnings": ["Check inferred amount"]})
        _require_ocr_review(result)
        self.assertEqual(result["inferred"], ["total calculated"])
        self.assertIn("Check inferred amount", result["review_warnings"])
