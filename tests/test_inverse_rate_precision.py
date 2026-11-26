"""An exact reciprocal must not turn a half-cent into a lower cent in reports."""
import tests_setup  # noqa: F401
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path
import tempfile
import unittest
from database import Database


class InverseRatePrecisionTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / 'synthetic.db')
        self.db.initialize('Synthetic-rate-precision-2026!')
        self.addCleanup(self.db.release)
        self.db.save_exchange_rate({'date_from': '01-01-2026', 'from_currency': 'USD',
                                    'to_currency': 'LBP', 'rate': '89500'}, 1)

    def test_inverse_conversion_retains_exact_half_cent_before_display_rounding(self):
        for amount, expected in [('57345014142.500', '640726.42'), ('-57345014142.500', '-640726.42')]:
            actual = self.db._converted_amount(D(amount), 'LBP', 'USD', '01-04-2026')
            self.assertEqual(actual.quantize(D('.01'), rounding=ROUND_HALF_UP), D(expected))

    def test_trial_balance_and_ledger_use_amount_before_inverse_division(self):
        self.db.save_journal_voucher({'entry_number': 'EXACT-INVERSE', 'entry_date': '01-04-2026',
                                     'currency': 'LBP'},
                                    [{'account_code': '601100001', 'debit': '57345014142.500'},
                                     {'account_code': '531', 'credit': '57345014142.500'}], 1)
        trial = next(r for r in self.db.trial_balance() if r['code'] == '601100001')
        self.assertEqual(D(str(trial['usd_balance'])).quantize(D('.01'), rounding=ROUND_HALF_UP), D('640726.42'))
        import ledger_reports
        lines = ledger_reports._load_lines(self.db, {'posting_status': 'posted', 'first_column': 'USD', 'second_column': 'none'})
        amount = sum((r['signed']['USD'] for r in lines if r['code'] == '601100001'), D(0))
        self.assertEqual(amount.quantize(D('.01'), rounding=ROUND_HALF_UP), D('640726.42'))

    def test_business_converter_uses_the_same_exact_inverse(self):
        from business_reports import _Converter
        actual = _Converter(self.db, 'USD')(D('57345014142.500'), 'LBP', '01-04-2026')
        self.assertEqual(actual.quantize(D('.01'), rounding=ROUND_HALF_UP), D('640726.42'))
