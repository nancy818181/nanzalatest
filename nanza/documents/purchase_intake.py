"""Local purchase hints and coverage notifications; never create or post an invoice."""
from pathlib import Path
import re

from invoice_intake import normalized


def purchase_evidence(text):
    value = normalized(text)
    return bool(re.search(
        r"شراء|(?:ال)?مورد|\bfournisseurs?\b|\bsuppliers?\b|(?<!\d)(?:6011|4011)(?!\d)", value))


def find_chart_file(root):
    """Discover the optional Oscar workbook without assuming a machine-specific path."""
    matches = sorted(p for p in Path(root).rglob('*')
                     if p.is_file() and p.suffix.casefold() == '.xls'
                     and p.stem.casefold() == 'plan_comptable_oscar')
    return matches[0] if len(matches) == 1 else None


def check_90_percent_rule(items, complete=True):
    total = len(items)
    classified = sum(bool(item.get('suggested_account')) for item in items)
    percent = classified / total * 100 if total else 0
    success = bool(total and classified * 10 >= total * 9 and complete)
    label = f'{percent:.1f}'.rstrip('0').rstrip('.')
    message = (f'تم التعرف على {label}% من البنود تلقائيا - {classified}/{total}'
               if success else f'تم التعرف على {label}% فقط - {classified}/{total} - راجع البنود')
    if not complete:
        message += ' - بعض البنود غير مقروءة أو ناقصة'
    return {'notify': True, 'message': message, 'type': 'success' if success else 'warning',
            'percent': round(percent, 2), 'classified': classified, 'total': total,
            'requires_review': True, 'can_post': False, 'complete': complete}


def suggest_and_autocreate(database, description, user_id=None, account_hint=None, allow_create=False):
    """Reuse the actual chart; create a child only under a unique, unused expense parent.

    Missing Oscar data never causes fabricated parent accounts or changes to payroll.
    Number allocation and the existing audited save run in one write transaction.
    """
    from invoice_intake import chart_suggestion, category_for
    accounts = database.list_accounts()
    suggestion = chart_suggestion(description, accounts, category_for(description)['category'])
    code = str(suggestion.get('account_code') or '')
    hint_prefix = re.sub(r'\D', '', str(account_hint or ''))
    if len(code) == 9 and code.isdigit() and (not hint_prefix or code.startswith(hint_prefix)):
        return {**suggestion, 'created': False}
    candidates = [a for a in accounts if a.get('is_active', a.get('active', True))
                  and a.get('type') == 'expense'
                  and re.match(r'^(?:6011|626)', re.sub(r'\D', '', str(a.get('code') or '')))
                  and len(re.sub(r'\D', '', str(a.get('code') or ''))) < 9]
    if account_hint:
        candidates = [a for a in candidates if str(a['code']) == str(account_hint)]
    else:
        candidates = [a for a in candidates if normalized(description).strip()
                      in {normalized(a.get(k)).strip() for k in ('name_en', 'name_fr', 'name_ar')}]
    if len(candidates) != 1:
        return {'account_code': None, 'reason': 'No unique Oscar/company expense parent; choose manually', 'created': False}
    parent = candidates[0]
    prefix = re.sub(r'\D', '', str(parent['code']))
    with database.connect() as connection:
        if not connection.in_transaction:
            connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT id,active FROM accounts WHERE code=?', (parent['code'],)).fetchone()
        if not row or not row['active']:
            return {'account_code': None, 'created': False, 'reason': 'Parent unavailable'}
        children = [dict(r) for r in connection.execute(
            'SELECT code,name_en,name_ar,name_fr FROM accounts WHERE parent_id=? AND active=1', (row['id'],))]
        matching = [a for a in children if len(a['code']) == 9 and a['code'].isdigit()
                    and normalized(description).strip() in {normalized(a.get(k)).strip() for k in ('name_en', 'name_fr', 'name_ar')}]
        if len(matching) == 1:
            return {'account_code': matching[0]['code'], 'created': False, 'reason': 'Existing company child account'}
        if not allow_create or matching or connection.execute(
                'SELECT 1 FROM journal_lines WHERE account_id=? LIMIT 1', (row['id'],)).fetchone():
            return {'account_code': None, 'created': False, 'reason': 'Account creation requires review or parent is already used'}
        used = [int(r['code']) for r in connection.execute(
            "SELECT code FROM accounts WHERE length(code)=9 AND code LIKE ?", (prefix + '%',)) if str(r['code']).isdigit()]
        next_code = str(max(used, default=int(prefix.ljust(9, '0'))) + 1)
        if len(next_code) != 9 or not next_code.startswith(prefix):
            raise ValueError('This account prefix has no available nine-digit numbers')
        saved = database.save_account({'code': next_code, 'name_en': description[:200],
                                       'type': 'expense', 'parent_code': parent['code']}, user_id)
        return {'account_code': saved['code'], 'account_name': saved['name_en'], 'created': True,
                'reason': 'New audited company expense child; accountant review required'}


def annotate_purchase(reading, database, user_id=None, allow_create=False):
    from invoice_intake import enrich
    result = enrich(reading, database.list_accounts(), database.list_parties())
    import nanza_paths
    workbook = find_chart_file(nanza_paths.ROOT)
    result['chart_source'] = 'selected company database'
    result['oscar_workbook_available'] = workbook is not None
    if result.get('direction') != 'purchase':
        return result
    for item in result.get('items') or []:
        suggestion = suggest_and_autocreate(database, str(item.get('description') or ''), user_id,
                                           item.get('account_prefix'), allow_create)
        item['account_suggestion'] = suggestion
        item['suggested_account'] = suggestion.get('account_code') or ''
    complete = not (result.get('transcription_evidence') or {}).get('items_truncated')
    result['notification_90'] = check_90_percent_rule(result.get('items') or [], complete)
    return result
