"""Focused regression tests for the six October 2026 audit findings."""
import ast
import gettext
import io
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import nanza_paths
from invoice_calc import calculate
from database import Database
import approvals
import ledger_reports


class InvoiceFixes(unittest.TestCase):
    def test_zero_quantity_is_rejected(self):
        for value in (0, 0.0, '0', '0.00'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Quantity'):
                calculate([{'quantity': value, 'unit_price': 100}])

    def test_missing_quantity_still_defaults_to_one(self):
        for value in (None, ''):
            self.assertEqual(calculate([{'quantity': value, 'unit_price': 100}])['grand_total'], 111)

    def test_negative_vat_rejected_even_with_zero_vat_override(self):
        for override in (False, True):
            with self.subTest(override=override), self.assertRaisesRegex(ValueError, 'VAT cannot be negative'):
                calculate([{'quantity': 1, 'unit_price': 100, 'vat_rate': -11}], zero_vat=override)

    def test_finite_inputs_required(self):
        for key in ('quantity', 'unit_price', 'vat_rate', 'discount_percent'):
            for value in ('NaN', 'Infinity', '-Infinity'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    calculate([{'quantity': 1, 'unit_price': 100, key: value}])

    def test_normal_vat_and_zero_vat(self):
        self.assertEqual(calculate([{'quantity': 2, 'unit_price': 100}])['grand_total'], 222)
        self.assertEqual(calculate([{'quantity': 2, 'unit_price': 100}], zero_vat=True)['grand_total'], 200)

    def test_discount_remainder_does_not_increase_last_line(self):
        result = calculate([{'quantity': 1, 'unit_price': '.01'} for _ in range(4)], invoice_discount_amount='.02')
        self.assertEqual(sum(Decimal(str(r['subtotal'])) for r in result['lines']), Decimal('.02'))
        self.assertTrue(all(0 <= r['subtotal'] <= r['net'] for r in result['lines']))

    def test_line_discount_rounds_final_amount(self):
        result = calculate([{'quantity': 1, 'unit_price': '.05', 'discount_percent': 10}])
        self.assertEqual(result['lines'][0]['net'], .05)  # .045 HALF_UP -> .05

    def test_full_and_empty_discounts(self):
        self.assertEqual(calculate([])['grand_total'], 0)
        result = calculate([{'quantity': 1, 'unit_price': 10}], invoice_discount_percent=100)
        self.assertEqual(result['grand_total'], 0)

    def test_discount_bounds_and_conservation(self):
        rng = random.Random(20261020)
        for _ in range(500):
            amounts = [Decimal(rng.randrange(0, 10000)) / 100 for _ in range(rng.randrange(1, 30))]
            total = sum(amounts)
            discount = Decimal(rng.randrange(int(total * 100) + 1)) / 100
            result = calculate([{'quantity': 1, 'unit_price': str(v)} for v in amounts], invoice_discount_amount=str(discount))
            after = sum((Decimal(str(r['subtotal'])) for r in result['lines']), Decimal(0))
            self.assertEqual(after, total - discount)
            self.assertTrue(all(0 <= r['subtotal'] <= r['net'] <= r['gross_amount'] for r in result['lines']))


class DatabaseFixes(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.previous_key = os.environ.get('SABER_AUDIT_KEY')
        os.environ['SABER_AUDIT_KEY'] = str(Path(self.temporary.name) / 'audit.key')
        self.db = Database(Path(self.temporary.name) / 'test.db')
        self.db.initialize('TestFixture-Only456!')
        with self.db.connect() as c:
            self.user = dict(c.execute('SELECT * FROM users LIMIT 1').fetchone())
            self.accounts = [dict(r) for r in c.execute("SELECT * FROM accounts WHERE type IN ('expense','asset') ORDER BY id LIMIT 2")]

    def tearDown(self):
        self.db.release()
        if self.previous_key is None: os.environ.pop('SABER_AUDIT_KEY', None)
        else: os.environ['SABER_AUDIT_KEY'] = self.previous_key
        self.temporary.cleanup()

    def voucher(self, deferred=False):
        return self.db.save_journal_voucher({'entry_date': '2026-01-15', 'currency': 'USD', 'description': 'Fixture'},
            [{'account_code': self.accounts[0]['code'], 'debit': '100'}, {'account_code': self.accounts[1]['code'], 'credit': '100'}],
            self.user['id'], defer_posting=deferred)['voucher']['id']

    def test_posted_excludes_draft_and_rejected_and_keeps_reversals(self):
        posted = self.voucher()
        self.voucher(True)
        rejected = self.voucher(True)
        approvals.hold(self.db, rejected, self.user['id'])
        approvals.reject_documents(self.db, [rejected], [], self.user, 'Rejected fixture')
        opts = {'posting_status': 'posted', 'first_column': 'account', 'second_column': 'none'}
        for flags in ({}, {'profit_loss_only': True}, {'balance_sheet_only': True}):
            rows = ledger_reports._load_lines(self.db, {**opts, **flags})
            self.assertTrue(all(r['entry_id'] == posted for r in rows))
        self.assertEqual({r['entry_id'] for r in ledger_reports._load_lines(self.db, opts)}, {posted})
        self.assertEqual(sum(Decimal(str(r['debit'])) for r in self.db.trial_balance()), Decimal('100'))
        native = self.db._native_trial_balance('2026-01-01', '2026-01-31', 'USD')
        self.assertEqual(sum(r['debit'] for r in native), Decimal('100'))
        reversal = self.db.reverse_journal_voucher(posted, '2026-01-16', self.user['id'])['voucher']['id']
        rows = ledger_reports._load_lines(self.db, opts)
        self.assertEqual({r['entry_id'] for r in rows}, {posted, reversal})
        self.assertEqual(sum(r['signed']['entry'] for r in rows), 0)

    def test_negative_or_nonfinite_salary_rejected_without_writes(self):
        for value in ('-100', 'NaN', 'Infinity', '-Infinity'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.db.save_employee({'full_name': 'Fixture', 'currency': 'USD', 'base_salary': value}, self.user['id'])
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM employees').fetchone()[0], 0)

    def test_salary_create_and_update(self):
        item = self.db.save_employee({'full_name': 'Fixture', 'currency': 'USD', 'base_salary': '100'}, self.user['id'])
        with self.assertRaises(ValueError):
            self.db.save_employee({**item, 'base_salary': '-1'}, self.user['id'])
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT base_salary FROM employees WHERE id=?', (item['id'],)).fetchone()[0], '100')
        self.assertEqual(self.db.save_employee({**item, 'base_salary': '0'}, self.user['id'])['base_salary'], '0')

    def test_restored_delivery_imports_and_empty_reports(self):
        from nanza_delivery import ageing_report, ai_accountant, complete_board_dashboard, custom_report_builder, whatsapp_daily_summary
        self.assertEqual(ageing_report.get_ageing_buckets('2026-01-31', self.db)['details'], [])
        self.assertEqual(custom_report_builder.build_report(self.db, {'date_from': '2026-01-01', 'date_to': '2026-01-31'})['rows'], [])
        self.assertIsInstance(whatsapp_daily_summary.generate_whatsapp_summary('2026-01-31', self.db), str)
        self.assertIsInstance(ai_accountant.cashflow_forecast(self.db, as_of='2026-01-31'), dict)
        self.assertIsInstance(complete_board_dashboard.build_board(self.db, '2026-01-01', '2026-01-31'), dict)


class TranslationFixes(unittest.TestCase):
    def test_core_terms_and_existing_ui_hooks(self):
        import i18n, arabic_ui
        terms = {'Invoice': 'فاتورة', 'Accounting': 'المحاسبة', 'Inventory': 'المخزون',
                 'Salary': 'الراتب', 'VAT': 'ضريبة القيمة المضافة', 'Reports': 'التقارير',
                 'Posted': 'مرحل', 'Rejected': 'مرفوض'}
        for en, ar in terms.items():
            self.assertEqual(i18n.tr('ar', en), ar)
            self.assertEqual(i18n.tr('en', en), en)
            self.assertEqual(arabic_ui.translate(en), ar)
        self.assertEqual(i18n.tr('ar', 'login'), 'تسجيل الدخول')

    def test_compiled_catalogues_match_json(self):
        data = json.loads((ROOT / 'nanza/translations.json').read_text(encoding='utf-8'))
        self.assertEqual(set(data['en']), set(data['ar']))
        for language in ('en', 'ar'):
            with (ROOT / f'nanza/locale/{language}/LC_MESSAGES/django.mo').open('rb') as stream:
                catalogue = gettext.GNUTranslations(stream)
            for source, target in data[language].items():
                self.assertEqual(catalogue.gettext(source), target)

    def test_language_preference_roundtrip_and_validation(self):
        import i18n
        previous = os.environ.get('SABER_DATA_DIR')
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.environ['SABER_DATA_DIR'] = directory
                self.assertEqual(i18n.saved_language(), 'en')
                for language in ('ar', 'en', 'fr'):
                    i18n.save_language(language)
                    self.assertEqual(i18n.saved_language(), language)
                with self.assertRaises(ValueError): i18n.save_language('../../bad')
                self.assertEqual(i18n.saved_language(), 'fr')
        finally:
            if previous is None: os.environ.pop('SABER_DATA_DIR', None)
            else: os.environ['SABER_DATA_DIR'] = previous


if __name__ == '__main__': unittest.main()
