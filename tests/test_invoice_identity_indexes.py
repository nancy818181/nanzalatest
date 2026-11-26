"""The indexed prefilter must retain Python's existing invoice identity rule."""
from pathlib import Path
import tempfile
import unittest
from database import Database


class InvoiceIdentityIndexesTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.book = Database(Path(folder.name) / 'synthetic.db', pooled=True)
        self.book.initialize('Synthetic-identity-indexes-2026!')
        self.addCleanup(self.book.release)

    def add(self, number, kind='sale', party='Identity party', subtype='invoice'):
        return self.book.create_manual_invoice({
            'invoice_number': number, 'invoice_date': '01-01-2026',
            'kind': kind, 'party_name': party, 'currency': 'USD',
            'doc_subtype': subtype, 'allow_duplicate': True,
        }, [{'description': 'Synthetic', 'quantity': '1', 'unit_price': '10', 'vat_rate': '0'}], 1)

    def test_indexed_and_fallback_candidates_match_independent_full_scan(self):
        for number in ['INV#0045', 'INV-45', 'INV/0045', 'INV_46', 'SS-9', 'ß-009',
                       'ABC00000000000000000000000001', '0000', '2026-INV-0007',
                       'INV123456789012345678901', 'ONLYLETTERS', 'INV\t0048', 'INV.49']:
            self.add(number)
        self.add('INV45', 'purchase', 'Supplier one')
        self.add('INV0045', 'purchase', 'Supplier two')
        self.add('INV-45', subtype='credit_note')
        cancelled = self.add('INV-50')
        with self.book.connect() as c:
            c.execute("UPDATE invoices SET status='cancelled' WHERE id=?", (cancelled,))
            rows = [dict(r) for r in c.execute("SELECT * FROM invoices ORDER BY id")]
            parties = [r['party_id'] for r in rows if r['kind'] == 'purchase']
            cases = ['inv45', 'INV#0045', 'INV46', 'SS9', 'ABC1', '0', '2026INV7',
                     'INV123456789012345678901', 'ONLYLETTERS', 'INV48', 'INV49', 'INV50', 'ABSENT99']
            for number in cases:
                for kind, party, subtype in [('sale', None, 'invoice'), ('sale', None, 'credit_note'),
                                              ('purchase', parties[0], 'invoice'), ('purchase', parties[1], 'invoice')]:
                    for exclude in (None, rows[0]['id']):
                        matches = [r for r in rows if r['kind'] == kind and r['id'] != exclude
                                   and r['status'] not in ('cancelled', 'deleted', 'void')
                                   and str(r['doc_subtype'] or 'invoice').lower() == subtype
                                   and self.book.invoice_number_key(r['invoice_number']) == self.book.invoice_number_key(number)
                                   and (kind != 'purchase' or r['party_id'] == party)]
                        expected = matches[0]['id'] if matches else None
                        actual = self.book.find_same_invoice_number(c, number, kind, party, subtype, exclude)
                        self.assertEqual(actual['id'] if actual else None, expected,
                                         (number, kind, party, subtype, exclude))

    def test_migration_recreates_only_the_two_approved_indexes_without_document_changes(self):
        self.add('KEEP-001')
        with self.book.connect() as c:
            before = [tuple(r) for r in c.execute('SELECT * FROM invoices')]
            indexes = {r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            for name in ('idx_invoice_identity_numeric', 'idx_invoice_identity_other_chars'):
                c.execute('DROP INDEX ' + name)
            c.execute("UPDATE app_settings SET value='old-test-version' WHERE key='startup_schema_version'")
        self.book.initialize_if_needed('Synthetic-identity-indexes-2026!')
        with self.book.connect() as c:
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM invoices')], before)
            self.assertEqual({r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}, indexes)
            prefix = f"RTRIM({self.book._NUMBER_SQL},'0123456789')"
            suffix = f"CAST(SUBSTR({self.book._NUMBER_SQL},LENGTH({prefix})+1) AS INTEGER)"
            plan = c.execute(f"EXPLAIN QUERY PLAN SELECT i.id FROM invoices i WHERE i.kind=? "
                             f"AND i.status NOT IN ('cancelled','deleted','void') AND {prefix}=? AND {suffix}=?",
                             ('sale', 'KEEP', 1)).fetchall()
            self.assertTrue(any('idx_invoice_identity_numeric' in r['detail'] for r in plan))
