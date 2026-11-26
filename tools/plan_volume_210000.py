"""Build reproducible inputs/oracles; this does NOT create application documents.

Run: python tools/plan_volume_210000.py --output <isolated-evidence-folder>
Keep this output outside the source tree. Decimal calculations here deliberately
do not import Nanza calculators, databases, reports or service functions.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import random


def cents(value):
    return Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def line_expected(line):
    gross = Decimal(line['quantity']) * Decimal(line['unit_price'])
    base = cents(gross * (1 - Decimal(line['discount_percent']) / 100))
    vat = cents(base * Decimal(line['vat_rate']) / 100)
    return {'base': base, 'vat': vat, 'total': base + vat}


def make_plan(output: Path, seed=26112026, sales=80000, purchases=25000):
    if sales % 4 or purchases % 4:
        raise ValueError('Each invoice count must be a multiple of four')
    output.mkdir(parents=True, exist_ok=True)
    inputs = output / 'volume-inputs.jsonl'
    manifest = output / 'volume-input-manifest.json'
    if inputs.exists() or manifest.exists():
        raise FileExistsError('Preserve existing evidence: choose a new output directory')
    rng = random.Random(seed)
    counts, sums = Counter(), defaultdict(lambda: defaultdict(Decimal))
    digest = hashlib.sha256()
    with inputs.open('wb') as stream:
        def emit(record):
            raw = (json.dumps(record, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')
            stream.write(raw); digest.update(raw); counts[record['type']] += 1
        for kind, count, prefix in (('sale', sales, 'S'), ('purchase', purchases, 'P')):
            for first in range(0, count, 4):
                cluster = first // 4
                quarter = 1 + cluster % 4
                month = 1 + (quarter - 1) * 3
                currency = ('USD', 'LBP', 'EUR')[(cluster // 4) % 3]
                invoice_date, payment_date = f'15-{month:02}-2026', f'20-{month:02}-2026'
                party = f'VOLUME-{prefix}-{currency}-{cluster % 40:02}'
                invoices, totals = [], []
                for offset in range(4):
                    number = f'VOL-{prefix}-{first+offset+1:06}'
                    lines = []
                    for n in range(2 + (first + offset) % 3):
                        lines.append({'description': f'Volume item {n+1}', 'quantity': str(rng.randint(1, 5)),
                                      'unit_price': str(Decimal(rng.randint(100, 10000)) / 100 * (89500 if currency == 'LBP' else 1)),
                                      'discount_percent': '5' if n == 0 else '0',
                                      'vat_rate': '0' if n == 2 else '11'})
                        if n == 2:
                            # Match the normal screen's explicit exempt-line payload.
                            lines[-1].update(deductible_subtotal='0', non_deductible_subtotal=str(line_expected(lines[-1])['base']), vat='0')
                    results = [line_expected(line) for line in lines]
                    expected = {key: sum((r[key] for r in results), Decimal(0)) for key in ('base', 'vat', 'total')}
                    emit({'type': 'sales_invoice' if kind == 'sale' else 'purchase_invoice', 'reference': number,
                          'quarter': quarter, 'invoice': {'invoice_number': number, 'invoice_date': invoice_date,
                          'party_name': party, 'kind': kind, 'currency': currency, 'status': 'posted'},
                          'lines': lines, 'expected': {key: str(value) for key, value in expected.items()}})
                    counts['item_lines'] += len(lines)
                    for key, value in expected.items(): sums[f'{kind}/Q{quarter}/{currency}'][key] += value
                    invoices.append(number); totals.append(expected['total'])
                half = [cents(value / 2) for value in totals]
                # Four cash documents for four invoices, but deliberately not a
                # one-to-one pattern: split invoice 0, combined payments 0/2,
                # and a known half-open invoice 3 in every cluster.
                allocations = [
                    [(invoices[0], half[0]), (invoices[1], half[1])],
                    [(invoices[0], totals[0] - half[0])],
                    [(invoices[1], totals[1] - half[1]), (invoices[2], totals[2])],
                    [(invoices[3], half[3])],
                ]
                for offset, parts in enumerate(allocations):
                    amount = sum((value for _ref, value in parts), Decimal(0))
                    emit({'type': 'receipt' if kind == 'sale' else 'payment',
                          'reference': f'VOL-{ "R" if kind == "sale" else "D"}-{first+offset+1:06}',
                          'quarter': quarter, 'party_name': party, 'currency': currency, 'date': payment_date,
                          'amount': str(amount), 'allocations': [{'invoice_reference': ref, 'amount': str(value)} for ref, value in parts]})
                    counts['allocations'] += len(parts)
                    sums[f'{kind}/Q{quarter}/{currency}']['cash_native'] += amount
                sums[f'{kind}/Q{quarter}/{currency}']['open_native'] += totals[3] - half[3]
    document_counts = {key: counts[key] for key in ('sales_invoice', 'receipt', 'purchase_invoice', 'payment')}
    result = {'seed': seed, 'purpose': 'Inputs and independent Decimal oracle only; NOT an executed load test',
              'planned_documents': document_counts, 'planned_total': sum(document_counts.values()),
              'actual_application_documents_created_by_this_command': 0,
              'planned_item_lines': counts['item_lines'], 'planned_allocation_rows': counts['allocations'],
              'planned_minimum_source_entries': sum(document_counts.values()),
              'input_sha256': digest.hexdigest(), 'bytes': inputs.stat().st_size,
              'totals_native': {key: {k: str(v) for k, v in values.items()} for key, values in sums.items()},
              'fx_rate_fixture_required': 'Save explicit invoice/payment-date EUR/USD rates before execution. Do not infer base-currency expected balances from native totals.',
              'execution_gate': 'Small application reference sample including VAT advance timing must PASS before generating application documents.'}
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seed', default=26112026, type=int)
    args = parser.parse_args()
    result = make_plan(args.output, args.seed)
    print(json.dumps({key: result[key] for key in ('planned_documents', 'planned_total', 'actual_application_documents_created_by_this_command', 'planned_item_lines', 'planned_allocation_rows', 'input_sha256', 'bytes')}, indent=2))
