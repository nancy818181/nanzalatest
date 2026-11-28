"""Reference generator: it must never claim that planned records were posted."""
import json
from pathlib import Path
import tempfile
import unittest
from decimal import Decimal
from tools.plan_volume_210000 import line_expected, make_plan


class VolumeInputPlanTest(unittest.TestCase):
    def test_unit_price_precision_discount_and_tax_have_independent_known_values(self):
        result = line_expected({'quantity': '3', 'unit_price': '1.005',
                                'discount_percent': '0', 'vat_rate': '11'})
        self.assertEqual(result, {'base': Decimal('3.02'), 'vat': Decimal('.33'), 'total': Decimal('3.35')})
        result = line_expected({'quantity': '2', 'unit_price': '50',
                                'discount_percent': '5', 'vat_rate': '11'})
        self.assertEqual(result, {'base': Decimal('95'), 'vat': Decimal('10.45'), 'total': Decimal('105.45')})

    def test_plan_is_reproducible_and_contains_combined_split_and_open_documents(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder)/'a', Path(folder)/'b'
            manifest = make_plan(first, 26112026, sales=16, purchases=16)
            repeat = make_plan(second, 26112026, sales=16, purchases=16)
            self.assertEqual(manifest['input_sha256'], repeat['input_sha256'])
            self.assertEqual(manifest['planned_total'], 64)
            self.assertEqual(manifest['actual_application_documents_created_by_this_command'], 0)
            rows = [json.loads(line) for line in (first/'volume-inputs.jsonl').read_text().splitlines()]
            self.assertEqual({r['quarter'] for r in rows}, {1, 2, 3, 4})
            invoices = {r['reference']: Decimal(r['expected']['total']) for r in rows if 'invoice' in r}
            applied = {key: Decimal(0) for key in invoices}
            for payment in (r for r in rows if 'allocations' in r):
                self.assertEqual(sum((Decimal(a['amount']) for a in payment['allocations']), Decimal(0)), Decimal(payment['amount']))
                for a in payment['allocations']: applied[a['invoice_reference']] += Decimal(a['amount'])
            self.assertTrue(any(r.get('allocations') and len(r['allocations']) > 1 for r in rows))
            self.assertTrue(any(0 < applied[key] < total for key, total in invoices.items()))
            self.assertTrue(all(applied[key] <= total for key, total in invoices.items()))
            with self.assertRaises(FileExistsError): make_plan(first, sales=16, purchases=16)


if __name__ == '__main__': unittest.main()
