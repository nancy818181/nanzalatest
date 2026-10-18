"""Purchase intake coverage is a review hint, never OCR accuracy or posting permission."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tests  # noqa: F401
from database import Database
from invoice_intake import enrich
from pdf_import import suggest_invoice_type
from purchase_intake import (
    check_90_percent_rule, find_chart_file, suggest_and_autocreate, annotate_purchase,
)


class PurchaseCoverageTest(unittest.TestCase):
    def test_nine_of_ten_notifies_success_but_never_authorizes_posting(self):
        result = check_90_percent_rule([{'suggested_account': '601100001'}] * 9 + [{}])
        self.assertEqual((result['percent'], result['classified'], result['total']), (90, 9, 10))
        self.assertEqual(result['type'], 'success')
        self.assertIn('9/10', result['message'])
        self.assertFalse(result['can_post'])
        self.assertTrue(result['requires_review'])

    def test_below_threshold_empty_and_truncated_documents_warn(self):
        for items, complete in (([], True), ([{}] * 10, True),
                                ([{'suggested_account': '626340001'}] * 8 + [{}, {}], True),
                                ([{'suggested_account': '626340001'}], False)):
            with self.subTest(items=len(items), complete=complete):
                self.assertEqual(check_90_percent_rule(items, complete)['type'], 'warning')

    def test_threshold_uses_exact_counts_not_rounded_percentage(self):
        items = [{'suggested_account': '601100001'}] * 179 + [{}] * 21
        self.assertEqual(check_90_percent_rule(items)['type'], 'warning')

    def test_supplier_evidence_overrides_sales_in_every_requested_language(self):
        for text in ('شراء', 'مورد', 'fournisseur', 'supplier', 'فاتورة شراء', '6011', '4011'):
            with self.subTest(text=text):
                result = enrich({'text': text, 'suggested_type': 'Sales', 'direction': 'sale'})
                self.assertEqual(result['direction'], 'purchase')
                self.assertEqual(result['suggested_type'], 'Purchases')
                self.assertEqual(suggest_invoice_type(text), 'Purchases')
                self.assertIn('notification_90', result)

    def test_credit_note_type_and_uncertain_amounts_are_preserved(self):
        result = enrich({'text': 'supplier credit note', 'document_type': 'credit_note',
                         'total': None, 'items': [{'description': 'Unknown', 'quantity': None}]})
        self.assertEqual(result['document_type'], 'credit_note')
        self.assertIsNone(result['total'])
        self.assertIsNone(result['items'][0]['quantity'])
        self.assertTrue(result['review_required'])

    def test_sales_without_supplier_evidence_is_not_forced_to_purchase(self):
        result = enrich({'text': 'Sales invoice', 'direction': 'sale', 'suggested_type': 'Sales'})
        self.assertEqual(result['direction'], 'sale')
        self.assertNotIn('notification_90', result)

    def test_nested_uppercase_chart_discovery_and_missing_chart(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertIsNone(find_chart_file(root))
            file = root / 'company' / 'PLAN_COMPTABLE_OSCAR.XLS'
            file.parent.mkdir()
            file.write_bytes(b'test discovery only')
            self.assertEqual(find_chart_file(root), file)


class PurchaseAccountTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / 'books.db')
        self.db.initialize('Test-account-2026!')
        self.addCleanup(self.db.release)
        with self.db.connect() as connection:
            connection.execute("""INSERT INTO accounts(code,name_en,type) VALUES('6263.4','Special supplies','expense')
                ON CONFLICT(code) DO UPDATE SET name_en='Special supplies'""")

    def test_create_real_child_and_reuse_it_without_duplicate(self):
        first = suggest_and_autocreate(self.db, 'Special supplies', 1, '6263.4', True)
        second = suggest_and_autocreate(self.db, 'Special supplies', 1, '6263.4', True)
        self.assertEqual(first['account_code'], '626340001')
        self.assertEqual(second['account_code'], first['account_code'])
        self.assertTrue(first['created'])
        self.assertFalse(second['created'])
        with self.db.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0], 0)

    def test_missing_parent_does_not_fabricate_chart(self):
        result = suggest_and_autocreate(self.db, 'Unmapped service', 1, '6269.9876', True)
        self.assertIsNone(result['account_code'])

    def test_creation_can_be_disabled(self):
        result = suggest_and_autocreate(self.db, 'Special supplies', 1, '6263.4', False)
        self.assertIsNone(result['account_code'])

    def test_nine_real_classifications_are_in_api_result(self):
        reading = {'text': 'Supplier invoice', 'items':
                   [{'description': 'Special supplies', 'account_prefix': '6263.4'}] * 9
                   + [{'description': 'Unmapped mystery'}]}
        result = annotate_purchase(reading, self.db, 1, True)
        self.assertEqual(result['notification_90']['classified'], 9)
        self.assertEqual(result['notification_90']['type'], 'success')

    def test_completed_upload_returns_notification_and_scoped_status(self):
        from nanza.api_ocr import queue_receipt, process_purchase_receipt, queue_status
        queued = queue_receipt(self.db, 'company1', 'receipt.png', 'image/png', b'fake-reader-input', 1)
        reading = {'text': 'Supplier invoice', 'items': [{'description': 'Special supplies', 'account_prefix': '6263.4'}]}
        with patch('pdf_import.read_invoice_pdf', return_value=reading):
            result = process_purchase_receipt(self.db, queued['queue_id'], 'company1', 1)
        self.assertEqual(result['notification_90']['percent'], 100)
        self.assertEqual(queue_status(self.db, queued['queue_id'], 'company1')['notification_90']['type'], 'success')
        with self.assertRaises(KeyError):
            process_purchase_receipt(self.db, queued['queue_id'], 'other-company', 1)
