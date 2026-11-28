"""Bounded installer/upgrade smoke checks on disposable GitHub Windows runners.

Does not automate login or certify interactive accounting/package acceptance.
Installation is refused outside CI to protect an owner's installed application.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time


def runner_path(path):
    path = Path(path).resolve()
    root = Path(os.environ['RUNNER_TEMP']).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'Installer QA path must remain in RUNNER_TEMP: {path}')
    return path


def snapshot(folder):
    files = {}
    for path in sorted(folder.rglob('*.db')):
        if 'backup' in str(path.relative_to(folder)).lower():
            continue
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            state = {'integrity': db.execute('PRAGMA integrity_check').fetchone()[0]}
            for table in ('invoices', 'invoice_items', 'payments', 'payment_allocations',
                          'journal_entries', 'journal_lines', 'parties', 'users', 'audit_log'):
                if table not in tables:
                    continue
                rows = db.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
                state[table] = {'count': len(rows), 'sha256': hashlib.sha256(
                    json.dumps(rows, default=str, ensure_ascii=False).encode()).hexdigest()}
            state['books_lock'] = db.execute("SELECT value FROM app_settings WHERE key='books_locked_until'").fetchone()
            files[str(path.relative_to(folder))] = state
    return files


def seed(source, data):
    os.environ['SABER_DATA_DIR'] = str(data)
    os.environ.pop('SABER_FIRST_COMPANY', None)
    sys.path.insert(0, str(source))
    import nanza_paths  # noqa: F401
    import app_runtime
    from database import Database
    from company_manager import CompanyManager
    data.mkdir(parents=True, exist_ok=True)
    db = Database(app_runtime.main_database_path())
    db.initialize('Synthetic-installer-only-2026!')
    manager = CompanyManager(db.path)
    company = manager.create_company({'name': 'SYNTHETIC INSTALLER ACCEPTANCE', 'year': 2026}, db)
    ledger = Database(Path(company['years'][0]['database']))
    ledger.save_journal_voucher({'entry_number': 'INSTALL-OPEN', 'entry_date': '01-01-2026',
        'currency': 'USD', 'voucher_type': '04'}, [{'account_code': '531', 'debit': '1000'},
        {'account_code': '101', 'credit': '1000'}], 1)
    invoice = ledger.create_manual_invoice({'invoice_number': 'INSTALL-S-1',
        'invoice_date': '15-01-2026', 'party_name': 'SYNTHETIC INSTALLER BUYER',
        'kind': 'sale', 'currency': 'USD'}, [{'description': 'Upgrade reference',
        'quantity': '1', 'unit_price': '100', 'vat_rate': '11'}], 1)
    party = next(p for p in ledger.list_parties() if p['name'] == 'SYNTHETIC INSTALLER BUYER')
    ledger.add_payment({'payment_number': 'INSTALL-R-1', 'payment_date': '20-01-2026',
        'kind': 'customer_receipt', 'party_id': party['id'], 'currency': 'USD', 'amount': '50',
        'cash_account': '531', 'allocations': [{'invoice_id': invoice, 'amount': '50'}]}, 1)
    ledger.set_books_lock('31-01-2026', 1)
    ledger.backup()
    ledger.release()
    db.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path)
    parser.add_argument('--previous-installer', type=Path)
    parser.add_argument('--previous-source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', action='store_true')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--data', type=Path)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Windows':
        parser.error('Only a disposable GitHub Windows runner may execute this installer check.')
    output = runner_path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.seed:
        seed(args.source.resolve(), runner_path(args.data))
        return
    source = Path(__file__).resolve().parents[1]
    install = runner_path(output / 'application')
    install.mkdir(parents=True, exist_ok=True)
    result = {'source_sha': os.environ.get('GITHUB_SHA'), 'runner_os': os.environ.get('ImageOS'),
        'windows_version': sys.getwindowsversion().platform_version,
        'installer': str(args.installer), 'installer_sha256': hashlib.sha256(args.installer.read_bytes()).hexdigest(),
        'checks': [], 'limitations': ['No login or interactive document entry is automated.',
        'No claim of actual Windows125% display coverage.', 'Month close requires a separate accountant review.']}
    def check(name, passed, **details):
        result['checks'].append({'case': name, 'status': 'PASS' if passed else 'FAIL', **details})
        (output / 'installer-acceptance.json').write_text(json.dumps(result, indent=2, default=str))
        if not passed:
            raise AssertionError(name)
    def install_package(package, label):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        proc = subprocess.run([str(package.resolve()), '/VERYSILENT', '/SUPPRESSMSGBOXES',
            '/NORESTART', '/TASKS=', '/DIR=' + str(install), '/LOG=' + str(output / (label + '.log'))],
            timeout=240, startupinfo=startup, check=False)
        check(label, proc.returncode == 0, exit_code=proc.returncode)
    def prepare(data, seed_source):
        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--seed', '--source', str(seed_source),
            '--data', str(data), '--output', str(output)], check=True, timeout=120)
    def boot(data, label):
        exe = install / 'NanzaAccounting.exe'
        check(label + ' executable exists', exe.is_file())
        environment = {**os.environ, 'SABER_DATA_DIR': str(data)}
        environment.pop('SABER_FIRST_COMPANY', None)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        process = subprocess.Popen([str(exe)], cwd=install, env=environment, startupinfo=startup)
        started = time.monotonic()
        try:
            marker = data / '.nanza.window'
            while time.monotonic() - started < 90 and process.poll() is None:
                if marker.is_file():
                    break
                time.sleep(.2)
            check(label + ' reached desktop entry window', process.poll() is None and marker.is_file(),
                seconds=round(time.monotonic() - started, 3), proof='Packaged mainloop wrote its window marker; authentication not exercised')
        finally:
            # Only our exact child process tree, never an owner's named process.
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True, timeout=30)
            process.wait(timeout=30)
    try:
        install_package(args.installer, 'clean installation on disposable runner')
        clean = runner_path(output / 'clean-data')
        prepare(clean, source)
        before = snapshot(clean)
        boot(clean, 'clean installed package')
        check('clean package preserved seeded records', snapshot(clean) == before)
        if args.previous_installer and args.previous_source:
            install_package(args.previous_installer, 'install previous supported2.9.140')
            data = runner_path(output / 'upgrade-data')
            prepare(data, args.previous_source.resolve())
            boot(data, 'previous installed package')
            before = snapshot(data)
            (output / 'before-upgrade.json').write_text(json.dumps(before, indent=2))
            install_package(args.installer, 'upgrade previous package to candidate')
            boot(data, 'upgraded installed package')
            after = snapshot(data)
            (output / 'after-upgrade.json').write_text(json.dumps(after, indent=2))
            check('upgrade preserved documents journals allocations users audit and lock', before == after)
        result['scope'] = 'Actual Inno installation and packaged startup/migration; seeded reference documents made through source services, not installed GUI.'
    finally:
        (output / 'installer-acceptance.json').write_text(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()
