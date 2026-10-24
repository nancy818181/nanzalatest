"""Imports, constants, schema and small helpers shared by database.py and the db_*.py parts (2.9.63)."""
from __future__ import annotations

import logging
import hashlib
import hmac
import json
import re
import secrets
import os
import sqlite3
import tempfile
import threading
import urllib.request
from contextlib import closing, contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lebanese_accounts import DEFAULT_LEBANESE_ACCOUNTS, LEBANESE_ACCOUNTS

EXPENSE_ACCOUNT_9 = "601100000"
VAT_ACCOUNT_9 = "44210"  # VAT on purchases (was 442660000)
EXPENSE_NO_VAT_ACCOUNT_9 = "601100001"
SESSION_HOURS = 12  # 2.9.103: a session ends after 12 hours (was 24)
USER_VALIDITY_DAYS = 365
PERMISSION_MODULES = ("payroll", "vat", "delete",
        "approve")  # 2.9.93: "approve" = approve and post documents others prepared  # 2.9.52: "delete" = delete / cancel posted documents, replace all invoices

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','accountant','viewer')), language TEXT NOT NULL DEFAULT 'en', active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (
 key TEXT PRIMARY KEY, failed_count INTEGER NOT NULL, first_failed_at TEXT NOT NULL, locked_until TEXT
);
CREATE TABLE IF NOT EXISTS parties (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('customer','supplier','both')),
 name TEXT NOT NULL, tax_number TEXT, mof_number TEXT, address TEXT, contact_number TEXT,
 currency TEXT NOT NULL DEFAULT 'USD', account_number TEXT, account_category TEXT, due_days INTEGER NOT NULL DEFAULT 0, UNIQUE(kind,name)
);
CREATE TABLE IF NOT EXISTS branches (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS accounts (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name_en TEXT NOT NULL, name_ar TEXT, name_fr TEXT,
 type TEXT NOT NULL CHECK(type IN ('asset','liability','equity','income','expense')), parent_id INTEGER REFERENCES accounts(id), active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS invoices (
 id INTEGER PRIMARY KEY, invoice_number TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('sale','purchase')),
 invoice_date TEXT, party_id INTEGER REFERENCES parties(id), currency TEXT NOT NULL, exchange_rate TEXT NOT NULL DEFAULT '1',
 subtotal TEXT, vat TEXT, total TEXT, status TEXT NOT NULL DEFAULT 'posted', currency_issue TEXT NOT NULL DEFAULT '',
 posted_at TEXT, posted_by INTEGER REFERENCES users(id), rejection_reason TEXT,
 deductible_subtotal TEXT NOT NULL DEFAULT '0', non_deductible_subtotal TEXT NOT NULL DEFAULT '0',
 supplier_account TEXT NOT NULL DEFAULT '4011', vat_account TEXT NOT NULL DEFAULT '442660000', expense_account TEXT NOT NULL DEFAULT '601100000',
 entry_type TEXT NOT NULL DEFAULT 'purchase', debit_override TEXT, credit_override TEXT,
 supplier_side TEXT NOT NULL DEFAULT 'C', vat_side TEXT NOT NULL DEFAULT 'D', expense_side TEXT NOT NULL DEFAULT 'D',
 expense_no_vat_account TEXT NOT NULL DEFAULT '601100001', expense_no_vat_side TEXT NOT NULL DEFAULT 'D',
 source_file TEXT, source_row INTEGER, due_date TEXT, payment_status TEXT NOT NULL DEFAULT 'unpaid',
 amount_paid TEXT NOT NULL DEFAULT '0', payment_method TEXT, description TEXT, branch_id INTEGER REFERENCES branches(id), cancelled_at TEXT, cancellation_reason TEXT,
 created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoice_items (
 id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
 description TEXT NOT NULL, quantity TEXT NOT NULL, unit_price TEXT NOT NULL,
 subtotal TEXT NOT NULL, deductible_subtotal TEXT NOT NULL DEFAULT '0', non_deductible_subtotal TEXT NOT NULL DEFAULT '0',
 vat_rate TEXT NOT NULL, vat TEXT NOT NULL, total TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoice_attachments (
 id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
 file_name TEXT NOT NULL, mime_type TEXT NOT NULL, content BLOB NOT NULL,
 uploaded_by INTEGER REFERENCES users(id), uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS party_documents (
 id INTEGER PRIMARY KEY, party_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
 document_type TEXT NOT NULL, issue_date TEXT, expiry_date TEXT, notes TEXT,
 file_name TEXT NOT NULL, mime_type TEXT NOT NULL, content BLOB NOT NULL,
 uploaded_by INTEGER REFERENCES users(id), uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_cases (
 id INTEGER PRIMARY KEY, case_number TEXT NOT NULL UNIQUE,
 case_type TEXT NOT NULL CHECK(case_type IN ('purchase','expense','customs')),
 document_date TEXT NOT NULL, party_id INTEGER REFERENCES parties(id), currency TEXT NOT NULL DEFAULT 'USD',
 reference TEXT, description TEXT, customs_declaration_no TEXT, broker_name TEXT,
 supplier_invoice_amount TEXT NOT NULL DEFAULT '0', freight TEXT NOT NULL DEFAULT '0', insurance TEXT NOT NULL DEFAULT '0',
 customs_duties TEXT NOT NULL DEFAULT '0', import_vat TEXT NOT NULL DEFAULT '0', broker_fees TEXT NOT NULL DEFAULT '0',
 total TEXT NOT NULL DEFAULT '0', status TEXT NOT NULL DEFAULT 'draft', invoice_id INTEGER REFERENCES invoices(id),
 supplier_account TEXT, expense_account TEXT, vat_account TEXT, branch_id INTEGER REFERENCES branches(id),
 created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS case_attachments (
 id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES document_cases(id) ON DELETE CASCADE,
 document_role TEXT NOT NULL, file_name TEXT NOT NULL, mime_type TEXT NOT NULL, content BLOB NOT NULL,
 uploaded_by INTEGER REFERENCES users(id), uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal_entries (
 id INTEGER PRIMARY KEY, entry_number TEXT NOT NULL UNIQUE, entry_date TEXT, description TEXT, source_type TEXT,
 source_id INTEGER, currency TEXT NOT NULL, branch_id INTEGER REFERENCES branches(id), created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL,
 posting_status TEXT NOT NULL DEFAULT 'posted', reversal_of INTEGER REFERENCES journal_entries(id),
 posted_at TEXT, posted_by INTEGER REFERENCES users(id), rejection_reason TEXT
);
CREATE TABLE IF NOT EXISTS journal_lines (
 id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
 account_id INTEGER NOT NULL REFERENCES accounts(id), party_id INTEGER REFERENCES parties(id), description TEXT, debit TEXT NOT NULL DEFAULT '0', credit TEXT NOT NULL DEFAULT '0'
);
CREATE TABLE IF NOT EXISTS inventory_items (
 id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE, name TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'unit', quantity TEXT NOT NULL DEFAULT '0', average_cost TEXT NOT NULL DEFAULT '0'
);
CREATE TABLE IF NOT EXISTS stock_movements (
 id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES inventory_items(id), movement_date TEXT NOT NULL,
 quantity TEXT NOT NULL, unit_cost TEXT NOT NULL, source_type TEXT, source_id INTEGER
);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, entity TEXT NOT NULL,
 entity_id INTEGER, details TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fiscal_years (
 id INTEGER PRIMARY KEY, year INTEGER NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'open',
 opened_at TEXT NOT NULL, closed_at TEXT, closed_by INTEGER REFERENCES users(id), details TEXT
);
CREATE TABLE IF NOT EXISTS payments (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('customer_receipt','supplier_payment')),
 party_id INTEGER NOT NULL REFERENCES parties(id), payment_date TEXT NOT NULL, currency TEXT NOT NULL,
 amount TEXT NOT NULL, cash_account TEXT NOT NULL, party_account TEXT NOT NULL,
 reference TEXT, description TEXT, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expenses (
 id INTEGER PRIMARY KEY, expense_date TEXT NOT NULL, description TEXT NOT NULL, category TEXT,
 currency TEXT NOT NULL, subtotal TEXT NOT NULL, vat TEXT NOT NULL, total TEXT NOT NULL,
 with_vat_subtotal TEXT NOT NULL DEFAULT '0', without_vat_subtotal TEXT NOT NULL DEFAULT '0',
 expense_account TEXT NOT NULL, expense_without_vat_account TEXT NOT NULL DEFAULT '601100001', vat_account TEXT NOT NULL, payment_account TEXT NOT NULL,
 expense_side TEXT NOT NULL DEFAULT 'D', expense_without_vat_side TEXT NOT NULL DEFAULT 'D',
 vat_side TEXT NOT NULL DEFAULT 'D', payment_side TEXT NOT NULL DEFAULT 'C',
 reference TEXT, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ocr_queue (
 id INTEGER PRIMARY KEY, company_id TEXT NOT NULL, expense_id INTEGER REFERENCES expenses(id),
 attachment_id INTEGER, file_path TEXT NOT NULL, file_name TEXT NOT NULL,
 mime_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 result_json TEXT, error TEXT, created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL, processed_at TEXT
);
CREATE TABLE IF NOT EXISTS exchange_rates (
 id INTEGER PRIMARY KEY, rate_date TEXT NOT NULL, from_currency TEXT NOT NULL, to_currency TEXT NOT NULL,
 rate TEXT NOT NULL, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL,
 UNIQUE(rate_date,from_currency,to_currency)
);
CREATE TABLE IF NOT EXISTS exchange_rate_samples (
 id INTEGER PRIMARY KEY, rate_date TEXT NOT NULL, from_currency TEXT NOT NULL, to_currency TEXT NOT NULL,
 rate TEXT NOT NULL, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS currencies (
 code TEXT PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS employees (
 id INTEGER PRIMARY KEY, employee_number TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL,
 national_id TEXT, mof_number TEXT, nssf_number TEXT, address TEXT, contact_number TEXT,
 nationality TEXT, father_name TEXT, mother_name TEXT, birth_date TEXT, birth_place TEXT,
 marital_status TEXT NOT NULL DEFAULT 'single', spouse_works INTEGER NOT NULL DEFAULT 0, children INTEGER NOT NULL DEFAULT 0, employee_group TEXT NOT NULL DEFAULT 'employee',
 hire_date TEXT, leave_date TEXT, job_title TEXT, branch_id INTEGER REFERENCES branches(id),
 currency TEXT NOT NULL DEFAULT 'LBP', base_salary TEXT NOT NULL DEFAULT '0',
 salary_account TEXT, payable_account TEXT, active INTEGER NOT NULL DEFAULT 1,
 created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nssf_filed_wages (
 year INTEGER NOT NULL, month INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
 sickness_wages TEXT, family_wages TEXT, end_service_wages TEXT, amount_paid TEXT,
 note TEXT, updated_by INTEGER REFERENCES users(id), updated_at TEXT NOT NULL,
 PRIMARY KEY(year,month)
);
CREATE TABLE IF NOT EXISTS payroll_settings (
 id INTEGER PRIMARY KEY, date_from TEXT NOT NULL, date_to TEXT,
 tax_brackets TEXT NOT NULL, single_allowance TEXT NOT NULL DEFAULT '450000000',
 spouse_allowance TEXT NOT NULL DEFAULT '225000000', child_allowance TEXT NOT NULL DEFAULT '45000000',
 employee_nssf_rate TEXT NOT NULL DEFAULT '0.03', medical_rate TEXT NOT NULL DEFAULT '0.08',
 end_service_rate TEXT NOT NULL DEFAULT '0.085', family_rate TEXT NOT NULL DEFAULT '0.06',
 employee_ceiling TEXT NOT NULL DEFAULT '0', medical_ceiling TEXT NOT NULL DEFAULT '0',
 family_ceiling TEXT NOT NULL DEFAULT '0', end_service_ceiling TEXT NOT NULL DEFAULT '0',
 salary_account TEXT NOT NULL DEFAULT '621100001', salary_payable_account TEXT NOT NULL DEFAULT '421100001',
 payroll_tax_account TEXT NOT NULL DEFAULT '443100001', nssf_payable_account TEXT NOT NULL DEFAULT '447100001',
 employee_account_map TEXT NOT NULL DEFAULT '{}', manager_account_map TEXT NOT NULL DEFAULT '{}',
 created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL,
 UNIQUE(date_from)
);
CREATE TABLE IF NOT EXISTS payroll_records (
 id INTEGER PRIMARY KEY, payroll_number TEXT NOT NULL UNIQUE, employee_id INTEGER NOT NULL REFERENCES employees(id),
 period_date TEXT NOT NULL, currency TEXT NOT NULL, salary TEXT NOT NULL DEFAULT '0',
 transport TEXT NOT NULL DEFAULT '0', overtime TEXT NOT NULL DEFAULT '0', commission TEXT NOT NULL DEFAULT '0', retro_salary TEXT NOT NULL DEFAULT '0', retro_from TEXT, retro_to TEXT,
 schooling TEXT NOT NULL DEFAULT '0', bonus TEXT NOT NULL DEFAULT '0', thirteenth_month TEXT NOT NULL DEFAULT '0',
 gross_salary TEXT NOT NULL DEFAULT '0', taxable_salary TEXT NOT NULL DEFAULT '0', income_tax TEXT NOT NULL DEFAULT '0', income_tax_lbp TEXT NOT NULL DEFAULT '0',
 nssf_base TEXT NOT NULL DEFAULT '0', employee_nssf TEXT NOT NULL DEFAULT '0', employer_medical TEXT NOT NULL DEFAULT '0',
 employer_end_service TEXT NOT NULL DEFAULT '0', employer_family TEXT NOT NULL DEFAULT '0', net_salary TEXT NOT NULL DEFAULT '0',
 reference TEXT, notes TEXT, status TEXT NOT NULL DEFAULT 'draft', journal_entry_id INTEGER REFERENCES journal_entries(id),
 created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, UNIQUE(employee_id,period_date)
);
CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS expense_attachments (
 id INTEGER PRIMARY KEY, expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
 file_name TEXT NOT NULL, mime_type TEXT NOT NULL, content BLOB NOT NULL, uploaded_by INTEGER, uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vat_settings (
 year INTEGER PRIMARY KEY, provisional_ratio TEXT, updated_by INTEGER, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS departments (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT
);
CREATE TABLE IF NOT EXISTS projects (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, party_id INTEGER REFERENCES parties(id),
 start_date TEXT, end_date TEXT, status TEXT NOT NULL DEFAULT 'open', notes TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT
);
CREATE TABLE IF NOT EXISTS budgets (
 id INTEGER PRIMARY KEY, year INTEGER NOT NULL, currency TEXT NOT NULL, account_code TEXT NOT NULL,
 department_id INTEGER NOT NULL DEFAULT 0, project_id INTEGER NOT NULL DEFAULT 0, month INTEGER NOT NULL DEFAULT 0 CHECK(month BETWEEN 0 AND 12),
 amount TEXT NOT NULL, updated_by INTEGER, updated_at TEXT,
 UNIQUE(year,currency,account_code,department_id,project_id,month)
);
CREATE TABLE IF NOT EXISTS vat_adjustments (
 id INTEGER PRIMARY KEY, year INTEGER NOT NULL, quarter INTEGER NOT NULL CHECK(quarter BETWEEN 1 AND 4),
 currency TEXT NOT NULL, adjustment_type TEXT NOT NULL CHECK(adjustment_type IN ('output','input','non_deductible')),
 amount TEXT NOT NULL, reason TEXT NOT NULL, created_by INTEGER, created_by_name TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vat_returns (
 id INTEGER PRIMARY KEY, year INTEGER NOT NULL, quarter INTEGER NOT NULL CHECK(quarter BETWEEN 1 AND 4),
 net_lbp TEXT NOT NULL, credit_brought_forward_lbp TEXT NOT NULL DEFAULT '0', payable_lbp TEXT NOT NULL DEFAULT '0',
 credit_carried_forward_lbp TEXT NOT NULL DEFAULT '0', snapshot TEXT NOT NULL,
 saved_by INTEGER, saved_by_name TEXT, saved_at TEXT NOT NULL, UNIQUE(year,quarter)
);
-- Books locked up to a date (app_settings 'books_locked_until', ISO date): no journal entry dated on or before it
-- can be added, changed or deleted, whatever screen or import tries it. Unlock (administrator) to correct a closed period.
-- Entry dates are stored as DD-MM-YYYY (older files may hold YYYY-MM-DD); both are compared as ISO dates.
DROP TRIGGER IF EXISTS books_lock_entry_insert;
CREATE TRIGGER books_lock_entry_insert BEFORE INSERT ON journal_entries
 WHEN (CASE WHEN substr(NEW.entry_date,3,1)='-' THEN substr(NEW.entry_date,7,4)||'-'||substr(NEW.entry_date,4,2)||'-'||substr(NEW.entry_date,1,2) ELSE substr(NEW.entry_date,1,10) END) <= (SELECT value FROM app_settings WHERE key='books_locked_until' AND value<>'')
 BEGIN SELECT RAISE(ABORT,'PERIOD LOCKED: the books are closed up to this date. An administrator must unlock the period first'); END;
DROP TRIGGER IF EXISTS books_lock_entry_update;
CREATE TRIGGER books_lock_entry_update BEFORE UPDATE ON journal_entries
 WHEN (CASE WHEN substr(OLD.entry_date,3,1)='-' THEN substr(OLD.entry_date,7,4)||'-'||substr(OLD.entry_date,4,2)||'-'||substr(OLD.entry_date,1,2) ELSE substr(OLD.entry_date,1,10) END) <= (SELECT value FROM app_settings WHERE key='books_locked_until' AND value<>'') OR (CASE WHEN substr(NEW.entry_date,3,1)='-' THEN substr(NEW.entry_date,7,4)||'-'||substr(NEW.entry_date,4,2)||'-'||substr(NEW.entry_date,1,2) ELSE substr(NEW.entry_date,1,10) END) <= (SELECT value FROM app_settings WHERE key='books_locked_until' AND value<>'')
 BEGIN SELECT RAISE(ABORT,'PERIOD LOCKED: the books are closed up to this date. An administrator must unlock the period first'); END;
DROP TRIGGER IF EXISTS books_lock_entry_delete;
CREATE TRIGGER books_lock_entry_delete BEFORE DELETE ON journal_entries
 WHEN (CASE WHEN substr(OLD.entry_date,3,1)='-' THEN substr(OLD.entry_date,7,4)||'-'||substr(OLD.entry_date,4,2)||'-'||substr(OLD.entry_date,1,2) ELSE substr(OLD.entry_date,1,10) END) <= (SELECT value FROM app_settings WHERE key='books_locked_until' AND value<>'')
 BEGIN SELECT RAISE(ABORT,'PERIOD LOCKED: the books are closed up to this date. An administrator must unlock the period first'); END;
DROP TRIGGER IF EXISTS books_lock_line_insert;
CREATE TRIGGER books_lock_line_insert BEFORE INSERT ON journal_lines
 WHEN (CASE WHEN substr((SELECT entry_date FROM journal_entries WHERE id=NEW.entry_id),3,1)='-' THEN substr((SELECT entry_date FROM journal_entries WHERE id=NEW.entry_id),7,4)||'-'||substr((SELECT entry_date FROM journal_entries WHERE id=NEW.entry_id),4,2)||'-'||substr((SELECT entry_date FROM journal_entries WHERE id=NEW.entry_id),1,2) ELSE substr((SELECT entry_date FROM journal_entries WHERE id=NEW.entry_id),1,10) END) <= (SELECT value FROM app_settings WHERE key='books_locked_until' AND value<>'')
 BEGIN SELECT RAISE(ABORT,'PERIOD LOCKED: the books are closed up to this date. An administrator must unlock the period first'); END;
DROP TRIGGER IF EXISTS books_lock_line_update;
CREATE TRIGGER books_lock_line_update BEFORE UPDATE ON journal_lines
 WHEN (CASE WHEN substr((SELECT entry_date FROM journal_entries WHERE id=OLD.entry_id),3,1)='-' THEN substr((SELECT entry_date FROM journal_entries WHERE id=OLD.entry_id),7,4)||'-'||substr((SELECT entry_date FROM journal_entries WHERE id=OLD.entry_id),4,2)||'-'||substr((SELECT entry_date FROM journal_entries WHERE id=OLD.entry_id),1,2) ELSE substr((SELECT entry_date FROM journal_entries WHERE id=OLD.entry_id),1,10) END) <= (SELECT value FROM app_settings WHERE key='books_locked_until' AND value<>'')
 BEGIN SELECT RAISE(ABORT,'PERIOD LOCKED: the books are closed up to this date. An administrator must unlock the period first'); END;
DROP TRIGGER IF EXISTS books_lock_line_delete;
CREATE TRIGGER books_lock_line_delete BEFORE DELETE ON journal_lines
 WHEN (CASE WHEN substr((SELECT entry_date FROM journal_entries WHERE id=OLD.entry_id),3,1)='-' THEN substr((SELECT entry_date FROM journal_entries WHERE id=OLD.entry_id),7,4)||'-'||substr((SELECT entry_date FROM journal_entries WHERE id=OLD.entry_id),4,2)||'-'||substr((SELECT entry_date FROM journal_entries WHERE id=OLD.entry_id),1,2) ELSE substr((SELECT entry_date FROM journal_entries WHERE id=OLD.entry_id),1,10) END) <= (SELECT value FROM app_settings WHERE key='books_locked_until' AND value<>'')
 BEGIN SELECT RAISE(ABORT,'PERIOD LOCKED: the books are closed up to this date. An administrator must unlock the period first'); END;
"""

LEGACY_ACCOUNT_MAP = {
    "1100": DEFAULT_LEBANESE_ACCOUNTS["accounts_receivable"],
    "2100": DEFAULT_LEBANESE_ACCOUNTS["accounts_payable"],
    "2200": DEFAULT_LEBANESE_ACCOUNTS["vat_payable"],
    "1300": DEFAULT_LEBANESE_ACCOUNTS["vat_receivable"],
    "4100": DEFAULT_LEBANESE_ACCOUNTS["sales"],
    "5100": DEFAULT_LEBANESE_ACCOUNTS["purchases"],
    "9999": DEFAULT_LEBANESE_ACCOUNTS["import_variance"],
}
def utcnow():
    return datetime.now(timezone.utc).isoformat()

def parse_ts(value):
    """Parse a stored ISO timestamp into an aware UTC datetime.
    Timestamps without an explicit offset are assumed to be UTC. Returns None if unparseable.
    Comparing timestamps as datetimes (not as text) avoids the timezone-offset bug where
    two ISO strings with different offsets sort incorrectly as plain strings."""
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def iso_date(value, field="Date"):
    """Accept DD-MM-YYYY, DDMMYYYY, YYYY-MM-DD or YYYYMMDD and return YYYY-MM-DD."""
    found = _iso_date_cached(str(value or "").strip())
    if found is None: raise ValueError(f"{field} must use DD-MM-YYYY")
    return found


import functools as _functools


@_functools.lru_cache(maxsize=65536)
def _iso_date_cached(text):
    """2.9.91: every report reads thousands of dates (300,000 strptime calls for one screen of 3,000 invoices); the same
    text always gives the same date, so each one is worked out once. Invalid dates still fail."""
    for pattern in ("%Y-%m-%d", "%d-%m-%Y", "%d%m%Y", "%Y%m%d", "%d/%m/%Y"):
        try: return datetime.strptime(text, pattern).strftime("%Y-%m-%d")
        except ValueError: pass
    return None

def _soft_iso(value):
    """A report date given as DD-MM-YYYY or YYYY-MM-DD -> YYYY-MM-DD (dates are compared as text). Anything else is kept."""
    if value in (None, ""): return value
    try: return iso_date(value)
    except ValueError: return value

def display_date(value):
    found = _iso_date_cached(str(value or "").strip())
    return f"{found[8:10]}-{found[5:7]}-{found[:4]}" if found else str(value or "")

def parse_permissions(value):
    try: data = json.loads(value or "{}") if isinstance(value, str) else dict(value or {})
    except (TypeError, ValueError): data = {}
    return {module: bool(data.get(module, module != "approve")) for module in PERMISSION_MODULES}  # approve: off unless given

def parse_vat_rate(value):
    """2.9.72: a VAT rate in % ("11", "5%", "15.0") -> Decimal 11 / 5 / 15; between 0 and 100."""
    text = str(value if value is not None else "").replace("%", "").replace(",", ".").strip()
    try: rate = Decimal(text)
    except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError("The VAT rate must be a number, for example 11 or 5") from exc
    if rate < 0 or rate > 100: raise ValueError("The VAT rate must be between 0 and 100")
    return rate.normalize() if rate != rate.to_integral() else rate.quantize(Decimal("1"))


# 2.9.134 (D7): scrypt N=2^17, r=8, p=1 (128 MiB) is the first setting in the OWASP Password Storage Cheat Sheet (checked online 24-10-2026).
# The hash text is versioned ("scrypt$17$8$1$salt$digest"); a hash written before 2.9.134 ("salt:digest", N=2^14) still verifies and is
# written again in the new format at that user's next sign-in. NANZA_SCRYPT_LOG_N lowers the cost for automated tests only (never below 10).
SCRYPT_LOG_N = 17


def _scrypt_log_n():
    try: return max(10, min(20, int(os.environ.get("NANZA_SCRYPT_LOG_N") or SCRYPT_LOG_N)))
    except ValueError: return SCRYPT_LOG_N


def _scrypt(password, salt, log_n, r=8, p=1):
    return hashlib.scrypt(password.encode(), salt=salt, n=2**log_n, r=r, p=p, maxmem=2**29).hex()


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16); log_n = _scrypt_log_n()
    return f"scrypt${log_n}$8$1${salt.hex()}${_scrypt(password, salt, log_n)}"


def verify_password(password, encoded):
    encoded = str(encoded or "")
    if encoded.startswith("scrypt$"):
        try:
            _tag, log_n, r, p, salt_hex, digest_hex = encoded.split("$")
            candidate = _scrypt(password, bytes.fromhex(salt_hex), int(log_n), int(r), int(p))
        except (ValueError, TypeError): return False
        return hmac.compare_digest(candidate, digest_hex)
    if ":" not in encoded: return False  # "!" = a copy of the user in a company-year file: no password there
    salt_hex, digest_hex = encoded.split(":", 1)
    try: candidate = _scrypt(password, bytes.fromhex(salt_hex), 14)  # before 2.9.134
    except (ValueError, TypeError): return False
    return hmac.compare_digest(candidate, digest_hex)


def password_needs_rehash(encoded):
    """True for a hash written before 2.9.134 or with a lower cost than today's."""
    encoded = str(encoded or "")
    if not encoded.startswith("scrypt$"): return ":" in encoded
    try: return int(encoded.split("$")[1]) < _scrypt_log_n()
    except (ValueError, IndexError): return True


def session_token_hash(token):
    """2.9.134 (D7): the sessions table keeps only a hash of the token; the program keeps the token itself."""
    return "h1:" + hashlib.sha256(str(token).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 2.9.97: exact money sums in SQL
_SIX_PLACES = Decimal("0.000001")


class DecimalSum:
    """SQL aggregate DSUM(x): adds money exactly (Decimal) instead of floating point. Each value is read to 6 decimals
    (that also removes float noise such as 0.30000000000000004 from an expression), the result is returned once.
    Whole numbers stay whole (DSUM(1) counts); no rows gives NULL, like SUM."""

    def __init__(self):
        self.total = Decimal("0"); self.seen = False; self.whole = True

    def step(self, value):
        if value is None or value == "": return
        if not isinstance(value, int): self.whole = False
        try: self.total += Decimal(str(value)).quantize(_SIX_PLACES)
        except (ArithmeticError, ValueError): return
        self.seen = True

    def finalize(self):
        if not self.seen: return None
        return int(self.total) if self.whole else float(self.total)


def register_money_functions(connection):
    connection.create_aggregate("DSUM", 1, DecimalSum)
    return connection


def atomic(method):
    """2.9.121: the whole method is ONE transaction: a document is saved completely (invoice, its lines, its entry, the stock,
    the VAT reclass, the payment) or not at all - also when the program or the computer stops halfway. Database.connect()
    is re-entrant: the steps inside join this transaction, and an error anywhere rolls all of them back."""
    import functools

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.connect() as connection:
            # the write lock is taken at the start (waiting for another program's save, up to the busy timeout): a transaction
            # that first reads and then writes could otherwise be refused at once ("database is locked") by SQLite
            if not connection.in_transaction: connection.execute("BEGIN IMMEDIATE")
            return method(self, *args, **kwargs)
    return wrapper
