"""The Nanza database (one SQLite file per company and year).

2.9.63: the methods are grouped in db_*.py files (invoices, payments, journal, reports, payroll, rates, VAT,
dimensions, documents); this file keeps the connection, setup, users, backups and settings. Database is still
the one class every other module uses."""
from __future__ import annotations

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    contextmanager, datetime, Decimal, DEFAULT_LEBANESE_ACCOUNTS, display_date, EXPENSE_ACCOUNT_9,
    EXPENSE_NO_VAT_ACCOUNT_9, hash_password, hashlib, InvalidOperation, iso_date, json, LEBANESE_ACCOUNTS,
    LEGACY_ACCOUNT_MAP, logging, os, parse_permissions, parse_ts, parse_vat_rate, Path, PERMISSION_MODULES, re,
    register_money_functions, SCHEMA, secrets, SESSION_HOURS, sqlite3, threading, timedelta, timezone,
    USER_VALIDITY_DAYS, utcnow, VAT_ACCOUNT_9, verify_password
)
from database_common import _soft_iso  # noqa: F401
from db_invoices import InvoicesStore
from db_journal import JournalStore
from db_documents import DocumentsStore
from db_payments import PaymentsStore
from db_rates import RatesStore
from db_reports import ReportsStore
from db_payroll import PayrollStore
from db_dimensions import DimensionsStore
from db_vat import VatStore
from db_accounts import AccountsStore


class Database(InvoicesStore, JournalStore, DocumentsStore, PaymentsStore, RatesStore, ReportsStore, PayrollStore, DimensionsStore, VatStore, AccountsStore):
    _locks = {}
    _locks_guard = threading.Lock()

    def __init__(self, path, pooled=False):
        self.path = str(Path(path))
        self._transaction = threading.local()
        # pooled=True (used by the running data service) keeps ONE open SQLite connection for this
        # file and reuses it for every request instead of opening, configuring and closing a new
        # connection each time. All access is already serialised by the per-file lock below, so
        # the results are identical; only the per-request overhead disappears.
        self.pooled = pooled; self._pooled_connection = None; self._pooled_identity = None
        with self._locks_guard:
            self._lock = self._locks.setdefault(str(Path(path).resolve()), threading.RLock())

    def _file_identity(self):
        try:
            info = os.stat(self.path); return (info.st_dev, info.st_ino)
        except OSError:
            return None

    def _open_connection(self):
        # 2.9.87: wait up to 30 s for another writer (the background backup, a second window) instead of failing at
        # once with "database is locked" - that error stopped the program from starting while a backup was running.
        connection = sqlite3.connect(self.path, check_same_thread=not self.pooled, timeout=30)
        connection.row_factory = sqlite3.Row
        register_money_functions(connection)  # 2.9.97: DSUM(x) adds money exactly
        import audit_chain; audit_chain.register(connection)  # 2.9.97: fingerprints of the audit trail
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        # Performance PRAGMAs: WAL keeps reads fast while writing, NORMAL
        # sync is safe under WAL, and a larger page cache / memory temp
        # store cut disk churn. These only speed things up; the data and
        # every existing behaviour are unchanged.
        self._set_wal(connection)
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA cache_size=-16000")  # ~16 MB page cache
        return connection

    def _set_wal(self, connection):
        """2.9.87: switching to WAL needs the -wal / -shm files next to the data file. On Windows they can be held for a
        moment by an antivirus scan, a backup or sync tool, or left behind by a program that was closed by force, and
        SQLite then answers "disk I/O error": the program stopped at start ("could not start its local data service" in
        the user's log). Now: a few short retries; a left-over -shm file (rebuilt by SQLite from the -wal) is removed
        when nothing holds it; then the program carries on - nothing is lost."""
        import time
        for attempt in range(10):
            try:
                connection.execute("PRAGMA journal_mode=WAL"); return True
            except sqlite3.OperationalError as exc:
                text = str(exc).lower()
                if not any(word in text for word in ("disk i/o", "locked", "busy", "unable to open")): raise  # Windows: a held -shm gives "unable to open database file"
                logging.getLogger("saber").warning("Data file busy (%s), attempt %s: %s", self.path, attempt + 1, exc)
                if attempt == 3:
                    try: os.remove(str(self.path) + "-shm")  # fails harmlessly while another program really holds it
                    except OSError: pass
                time.sleep(0.2 * (attempt + 1))
        logging.getLogger("saber").warning("Opening %s without switching to WAL (its -wal / -shm files are held by another program)", self.path)
        return False

    def release(self):
        """Close the kept-open connection (before the file is moved, deleted or replaced)."""
        with self._lock:
            connection, self._pooled_connection, self._pooled_identity = self._pooled_connection, None, None
            if connection is not None:
                try: connection.close()
                except Exception: logging.getLogger("saber.ignored").debug("Ignored error", exc_info=True)

    @contextmanager
    def connect(self):
        with self._lock:
            active = getattr(self._transaction, "connection", None)
            if active is not None:
                yield active
                return
            if self.pooled:
                identity = self._file_identity()
                if self._pooled_connection is not None and (identity is None or identity != self._pooled_identity):
                    self.release()  # the file was replaced or removed: never keep using a stale handle
                if self._pooled_connection is None:
                    self._pooled_connection = self._open_connection(); self._pooled_identity = self._file_identity()
                connection = self._pooled_connection
            else:
                connection = self._open_connection()
            self._transaction.connection = connection
            try:
                self._watch_journal_lines(connection)
                yield connection
                self._refuse_unbalanced_entries(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                self._transaction.connection = None
                if not self.pooled: connection.close()

    # ------------------------------------------------------------ every journal entry must balance (2.9.43)
    BALANCE_TOLERANCE = Decimal("0.01")
    _balance_check_paused = False  # only while initialize() repairs entries written by older versions

    @staticmethod
    def _watch_journal_lines(connection):
        """Note (per connection, in a TEMP table) every journal entry whose lines are added, changed or
        deleted, so the whole entry can be checked once, just before the change is saved."""
        if connection.execute("SELECT 1 FROM sqlite_temp_master WHERE type='trigger' AND name='saber_touch_line_insert'").fetchone():
            return
        if not connection.execute("SELECT 1 FROM main.sqlite_master WHERE type='table' AND name='journal_lines'").fetchone():
            return  # brand-new file: the tables are created in this transaction, checked from the next one
        connection.executescript("""
            CREATE TEMP TABLE IF NOT EXISTS saber_touched_entries(entry_id INTEGER PRIMARY KEY);
            CREATE TEMP TRIGGER IF NOT EXISTS saber_touch_line_insert AFTER INSERT ON main.journal_lines
              BEGIN INSERT OR IGNORE INTO saber_touched_entries VALUES(NEW.entry_id); END;
            CREATE TEMP TRIGGER IF NOT EXISTS saber_touch_line_update AFTER UPDATE ON main.journal_lines
              BEGIN INSERT OR IGNORE INTO saber_touched_entries VALUES(OLD.entry_id); INSERT OR IGNORE INTO saber_touched_entries VALUES(NEW.entry_id); END;
            CREATE TEMP TRIGGER IF NOT EXISTS saber_touch_line_delete AFTER DELETE ON main.journal_lines
              BEGIN INSERT OR IGNORE INTO saber_touched_entries VALUES(OLD.entry_id); END;
        """)

    def _refuse_unbalanced_entries(self, connection):
        """Total Debit must equal total Credit for every entry changed in this transaction, whatever screen,
        import or upgrade path wrote it. Otherwise nothing of the change is saved."""
        if not connection.execute("SELECT 1 FROM sqlite_temp_master WHERE type='table' AND name='saber_touched_entries'").fetchone():
            return
        rows = connection.execute("""SELECT e.id, e.entry_number, l.debit, l.credit FROM temp.saber_touched_entries t
            JOIN main.journal_entries e ON e.id=t.entry_id JOIN main.journal_lines l ON l.entry_id=e.id""").fetchall()
        connection.execute("DELETE FROM temp.saber_touched_entries")
        if self._balance_check_paused or not rows: return
        totals = {}
        for row in rows:
            entry = totals.setdefault(row[0], [row[1], Decimal(0), Decimal(0)])
            try: entry[1] += Decimal(str(row[2] or 0)); entry[2] += Decimal(str(row[3] or 0))
            except (InvalidOperation, ValueError): raise ValueError(f"Journal entry {row[1]} has an amount that is not a number")
        for number, debit, credit in totals.values():
            if abs(debit - credit) > self.BALANCE_TOLERANCE:
                logging.getLogger("saber.database").warning("Unbalanced entry %s refused: debit %s, credit %s", number, debit, credit)
                raise ValueError(f"Journal entry {number} is not balanced: total Debit {debit:,.2f}, total Credit {credit:,.2f}, "
                                 f"difference {abs(debit - credit):,.2f}. Nothing was saved.")

    def unbalanced_entries(self):
        """Entries already saved with Debit different from Credit (written before 2.9.43), for review."""
        with self.connect() as db:
            rows = db.execute("SELECT e.id, e.entry_number, e.entry_date, e.description, l.debit, l.credit FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id ORDER BY e.id").fetchall()
        totals = {}
        for row in rows:
            item = totals.setdefault(row["id"], {"id": row["id"], "entry_number": row["entry_number"], "entry_date": row["entry_date"],
                    "description": row["description"], "debit": Decimal(0), "credit": Decimal(0)})
            try: item["debit"] += Decimal(str(row["debit"] or 0)); item["credit"] += Decimal(str(row["credit"] or 0))
            except (InvalidOperation, ValueError): item["debit"] = item["credit"] = None
        result = []
        for item in totals.values():
            if item["debit"] is None or abs(item["debit"] - item["credit"]) > self.BALANCE_TOLERANCE:
                result.append({**item, "debit": str(item["debit"]), "credit": str(item["credit"]),
                               "difference": None if item["debit"] is None else str(item["debit"] - item["credit"])})
        return result

    # Bump whenever initialize(), SCHEMA, seed accounts or its migration helpers change.
    # 2.9.64: the upgrade marker is computed from the upgrade code itself (see _schema_fingerprint at the end of this file).
    # It used to be a number changed by hand; columns added since 2.9.54 (payment_account ...) kept the same number, so
    # company files already marked were never upgraded: "no such column: i.payment_account".
    STARTUP_SCHEMA_VERSION = "4"

    @staticmethod
    def _startup_schema_signature(db):
        # Metadata only: no invoice, journal or other business rows are scanned.
        rows = db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        return hashlib.sha256(json.dumps([tuple(row) for row in rows]).encode("utf-8")).hexdigest()

    def initialize_if_needed(self, admin_password):
        """Prepare a file once per schema revision, including restored older files.

        The marker lives in the database, not process memory. Failed migrations never
        stamp it. Explicit initialize() remains available for full repair/reseeding.
        """
        with self._lock:
            with self.connect() as db:
                table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings'").fetchone()
                version = db.execute("SELECT value FROM app_settings WHERE key='startup_schema_version'").fetchone() if table else None
                signature = db.execute("SELECT value FROM app_settings WHERE key='startup_schema_signature'").fetchone() if table else None
                current = self._startup_schema_signature(db) if signature else None
            if version and version["value"] == self._schema_version() and signature and signature["value"] == current:
                return
            self.initialize(admin_password)

    def initialize(self, admin_password):
        # Upgrades and repairs may rebuild old entries: the period lock is paused only while they run, then restored.
        lock = None
        try:
            with self.connect() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings'").fetchone():
                    row = db.execute("SELECT value FROM app_settings WHERE key='books_locked_until'").fetchone()
                    lock = row["value"] if row else None
                    if lock: db.execute("UPDATE app_settings SET value='' WHERE key='books_locked_until'")
            self._balance_check_paused = True  # repairs of old entries must not be blocked; new work always is checked
            try: return self._initialize(admin_password)
            finally: self._balance_check_paused = False
        finally:
            if lock:
                with self.connect() as db:
                    db.execute("UPDATE app_settings SET value=? WHERE key='books_locked_until'", (lock,))

    def _initialize(self, admin_password):
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.executemany("INSERT OR IGNORE INTO currencies(code,name) VALUES(?,?)",
                           (("USD","US Dollar"),("LBP","Lebanese Pound"),("EUR","Euro"),("AED","UAE Dirham"),("SAR","Saudi Riyal")))  # 2.9.78: SAR
            invoice_columns = {row["name"] for row in db.execute("PRAGMA table_info(invoices)")}
            if "currency_issue" not in invoice_columns:
                db.execute("ALTER TABLE invoices ADD COLUMN currency_issue TEXT NOT NULL DEFAULT ''")
            account_columns = {
                "supplier_account": DEFAULT_LEBANESE_ACCOUNTS["accounts_payable"],
                "vat_account": DEFAULT_LEBANESE_ACCOUNTS["vat_receivable"],
                "expense_account": DEFAULT_LEBANESE_ACCOUNTS["purchases"],
            }
            for column, default_code in account_columns.items():
                if column not in invoice_columns:
                    db.execute(
                        f"ALTER TABLE invoices ADD COLUMN {column} "
                        f"TEXT NOT NULL DEFAULT '{default_code}'"
                    )
            lifecycle_columns = {
                "due_date": "TEXT",
                "payment_status": "TEXT NOT NULL DEFAULT 'unpaid'",
                "amount_paid": "TEXT NOT NULL DEFAULT '0'",
                "payment_method": "TEXT",
                "cancelled_at": "TEXT",
                "cancellation_reason": "TEXT",
                "entry_type": "TEXT NOT NULL DEFAULT 'purchase'",
                "debit_override": "TEXT",
                "credit_override": "TEXT",
                "supplier_side": "TEXT NOT NULL DEFAULT 'C'",
                "vat_side": "TEXT NOT NULL DEFAULT 'D'",
                "expense_side": "TEXT NOT NULL DEFAULT 'D'",
                "expense_no_vat_account": "TEXT NOT NULL DEFAULT '601100001'",
                "expense_no_vat_side": "TEXT NOT NULL DEFAULT 'D'",
                "deductible_subtotal": "TEXT NOT NULL DEFAULT '0'",
                "non_deductible_subtotal": "TEXT NOT NULL DEFAULT '0'",
                "description": "TEXT",
                "branch_id": "INTEGER REFERENCES branches(id)",
            }
            for column, definition in lifecycle_columns.items():
                if column not in invoice_columns:
                    db.execute(f"ALTER TABLE invoices ADD COLUMN {column} {definition}")
            item_columns={row["name"] for row in db.execute("PRAGMA table_info(invoice_items)")}
            if "item_code" not in item_columns: db.execute("ALTER TABLE invoice_items ADD COLUMN item_code TEXT")
            for column in ("deductible_subtotal","non_deductible_subtotal"):
                if column not in item_columns: db.execute(f"ALTER TABLE invoice_items ADD COLUMN {column} TEXT NOT NULL DEFAULT '0'")
            journal_line_columns={row["name"] for row in db.execute("PRAGMA table_info(journal_lines)")}
            if "description" not in journal_line_columns: db.execute("ALTER TABLE journal_lines ADD COLUMN description TEXT")
            journal_columns={row["name"] for row in db.execute("PRAGMA table_info(journal_entries)")}
            if "branch_id" not in journal_columns: db.execute("ALTER TABLE journal_entries ADD COLUMN branch_id INTEGER REFERENCES branches(id)")
            db.execute("INSERT OR IGNORE INTO branches(name) VALUES('Head Office')")
            db.execute("UPDATE invoices SET branch_id=(SELECT id FROM branches WHERE name='Head Office') WHERE branch_id IS NULL")
            db.execute("UPDATE journal_entries SET branch_id=(SELECT id FROM branches WHERE name='Head Office') WHERE branch_id IS NULL")
            db.execute("UPDATE invoices SET deductible_subtotal=subtotal WHERE CAST(deductible_subtotal AS REAL)=0 AND CAST(non_deductible_subtotal AS REAL)=0 AND CAST(subtotal AS REAL)<>0")
            db.execute("UPDATE invoice_items SET deductible_subtotal=subtotal WHERE CAST(deductible_subtotal AS REAL)=0 AND CAST(non_deductible_subtotal AS REAL)=0 AND CAST(subtotal AS REAL)<>0")
            expense_columns={row["name"] for row in db.execute("PRAGMA table_info(expenses)")}
            for column,definition in (("with_vat_subtotal","TEXT NOT NULL DEFAULT '0'"),("without_vat_subtotal","TEXT NOT NULL DEFAULT '0'"),
                    ("expense_without_vat_account","TEXT NOT NULL DEFAULT '601100001'"),("expense_side","TEXT NOT NULL DEFAULT 'D'"),
                    ("expense_without_vat_side","TEXT NOT NULL DEFAULT 'D'"),("vat_side","TEXT NOT NULL DEFAULT 'D'"),("payment_side",
                    "TEXT NOT NULL DEFAULT 'C'")):
                if column not in expense_columns: db.execute(f"ALTER TABLE expenses ADD COLUMN {column} {definition}")
            db.execute("UPDATE expenses SET with_vat_subtotal=subtotal WHERE CAST(with_vat_subtotal AS REAL)=0 AND CAST(without_vat_subtotal AS REAL)=0 AND CAST(subtotal AS REAL)<>0")
            party_columns={row["name"] for row in db.execute("PRAGMA table_info(parties)")}
            if "account_number" not in party_columns:
                db.execute("ALTER TABLE parties ADD COLUMN account_number TEXT")
            for column in ("mof_number","address","contact_number"):
                if column not in party_columns: db.execute(f"ALTER TABLE parties ADD COLUMN {column} TEXT")
            if "account_category" not in party_columns: db.execute("ALTER TABLE parties ADD COLUMN account_category TEXT")
            if "due_days" not in party_columns: db.execute("ALTER TABLE parties ADD COLUMN due_days INTEGER NOT NULL DEFAULT 0")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_parties_account_number ON parties(account_number) WHERE account_number IS NOT NULL")
            employee_columns={row["name"] for row in db.execute("PRAGMA table_info(employees)")}
            if "spouse_works" not in employee_columns: db.execute("ALTER TABLE employees ADD COLUMN spouse_works INTEGER NOT NULL DEFAULT 0")
            if "employee_group" not in employee_columns: db.execute("ALTER TABLE employees ADD COLUMN employee_group TEXT NOT NULL DEFAULT 'employee'")
            payroll_columns={row["name"] for row in db.execute("PRAGMA table_info(payroll_records)")}
            if "income_tax_lbp" not in payroll_columns: db.execute("ALTER TABLE payroll_records ADD COLUMN income_tax_lbp TEXT NOT NULL DEFAULT '0'")
            if "retro_salary" not in payroll_columns: db.execute("ALTER TABLE payroll_records ADD COLUMN retro_salary TEXT NOT NULL DEFAULT '0'")
            if "retro_from" not in payroll_columns: db.execute("ALTER TABLE payroll_records ADD COLUMN retro_from TEXT")
            if "retro_to" not in payroll_columns: db.execute("ALTER TABLE payroll_records ADD COLUMN retro_to TEXT")
            payroll_setting_columns={row["name"] for row in db.execute("PRAGMA table_info(payroll_settings)")}
            for column,default in (("transport_daily_exempt","450000"),("default_transport_days","26"),("schooling_annual_exempt","6000000"),("schooling_max_children","3"),
                                   ("schooling_public_child","0"),("schooling_public_cap","0"),("schooling_private_child","0"),("schooling_private_cap","0"),
                                   ("tax_rounding","0"),("minimum_wage","0"),("max_children_deduction","5"),("family_allowance_spouse","0"),("family_allowance_child","0"),
                                   ("family_allowance_cap","0"),("family_allowance_max_children","5")):
                if column not in payroll_setting_columns: db.execute(f"ALTER TABLE payroll_settings ADD COLUMN {column} TEXT NOT NULL DEFAULT '{default}'")
            payroll_record_columns={row["name"] for row in db.execute("PRAGMA table_info(payroll_records)")}
            for column in ("transport_days","exempt_transport","exempt_schooling","family_allowance","regular_tax","one_off_tax","compliance_notes","director_remuneration"):
                if column not in payroll_record_columns: db.execute(f"ALTER TABLE payroll_records ADD COLUMN {column} TEXT")
            if "employee_account_map" not in payroll_setting_columns: db.execute("ALTER TABLE payroll_settings ADD COLUMN employee_account_map TEXT NOT NULL DEFAULT '{}'")
            if "manager_account_map" not in payroll_setting_columns: db.execute("ALTER TABLE payroll_settings ADD COLUMN manager_account_map TEXT NOT NULL DEFAULT '{}'")
            if "retro_tax" not in payroll_columns: db.execute("ALTER TABLE payroll_records ADD COLUMN retro_tax TEXT NOT NULL DEFAULT '0'")
            db.execute("""UPDATE OR IGNORE payroll_records SET period_date=substr(period_date,7,4)||'-'||substr(period_date,4,2)||'-'||substr(period_date,1,2)
                WHERE period_date GLOB '??-??-????'""")
            # Older versions saved payroll dates exactly as typed (DD-MM-YYYY, DDMMYYYY...). Store them as YYYY-MM-DD.
            for table,column in (("payroll_settings","date_from"),("payroll_settings","date_to"),("payroll_records","period_date"),
                                 ("payroll_records","retro_from"),("payroll_records","retro_to")):
                for row in db.execute(f"SELECT id,{column} value FROM {table} WHERE {column} IS NOT NULL AND {column}<>''").fetchall():
                    try: fixed=iso_date(row["value"])
                    except ValueError: continue
                    if fixed!=row["value"]: db.execute(f"UPDATE OR IGNORE {table} SET {column}=? WHERE id=?",(fixed,row["id"]))
            document_columns={row["name"] for row in db.execute("PRAGMA table_info(party_documents)")}
            if "active" not in document_columns:  # "applies to this party" tick; existing documents stay active
                db.execute("ALTER TABLE party_documents ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
            line_columns={row["name"] for row in db.execute("PRAGMA table_info(journal_lines)")}
            for column in ("line_currency","amount","amount_lbp","amount_usd","rate_lbp","rate_usd","due_date","reference",
                           "revalue_currency","revalue_amount"):  # 2.9.78: DOE in EUR (or another currency than LBP / USD)
                if column not in line_columns: db.execute(f"ALTER TABLE journal_lines ADD COLUMN {column} TEXT")
            for column in ("department_id","project_id"):
                if column not in line_columns: db.execute(f"ALTER TABLE journal_lines ADD COLUMN {column} INTEGER")
            for table in ("invoices","expenses"):
                columns={row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                for column in ("department_id","project_id"):
                    if column not in columns: db.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER")
            payment_columns={row["name"] for row in db.execute("PRAGMA table_info(payments)")}
            for column,definition in (("payment_number","TEXT"),("payment_method","TEXT"),("department_id","INTEGER"),("project_id","INTEGER"),
                                      ("bank_commission","TEXT NOT NULL DEFAULT '0'"),("commission_account","TEXT"),
                                      ("exchange_difference","TEXT NOT NULL DEFAULT '0'"),("exchange_account","TEXT"),
                                      ("exchange_gain_account","TEXT"),("exchange_loss_account","TEXT")):  # 2.9.79
                if column not in payment_columns: db.execute(f"ALTER TABLE payments ADD COLUMN {column} {definition}")
            expense_cols={row["name"] for row in db.execute("PRAGMA table_info(expenses)")}
            if "expense_number" not in expense_cols: db.execute("ALTER TABLE expenses ADD COLUMN expense_number TEXT")
            invoice_cols={row["name"] for row in db.execute("PRAGMA table_info(invoices)")}
            if "linked_invoice_id" not in invoice_cols: db.execute("ALTER TABLE invoices ADD COLUMN linked_invoice_id INTEGER")
            if "vat_treatment" not in invoice_cols: db.execute("ALTER TABLE invoices ADD COLUMN vat_treatment TEXT NOT NULL DEFAULT 'standard'")
            if "vat_use" not in invoice_cols: db.execute("ALTER TABLE invoices ADD COLUMN vat_use TEXT NOT NULL DEFAULT 'mixed'")
            expense_cols={row["name"] for row in db.execute("PRAGMA table_info(expenses)")}
            if "vat_use" not in expense_cols: db.execute("ALTER TABLE expenses ADD COLUMN vat_use TEXT NOT NULL DEFAULT 'mixed'")
            return_cols={row["name"] for row in db.execute("PRAGMA table_info(vat_returns)")}
            if "refund_requested_lbp" not in return_cols: db.execute("ALTER TABLE vat_returns ADD COLUMN refund_requested_lbp TEXT NOT NULL DEFAULT '0'")
            if "deduction_ratio" not in return_cols: db.execute("ALTER TABLE vat_returns ADD COLUMN deduction_ratio TEXT")
            entry_columns={row["name"] for row in db.execute("PRAGMA table_info(journal_entries)")}
            if "voucher_type" not in entry_columns: db.execute("ALTER TABLE journal_entries ADD COLUMN voucher_type TEXT NOT NULL DEFAULT '01'")
            import inventory
            inventory.migrate(db)
            import fixed_assets
            fixed_assets.migrate(db)
            import bank_rec
            bank_rec.migrate(db)
            import payroll_extras  # 2.9.82: end-of-service provision, leave
            payroll_extras.migrate(db)
            import audit_chain  # 2.9.97: tamper-evident audit trail (fingerprint chain + triggers)
            audit_chain.migrate(db)
            import approvals  # 2.9.100: drafts waiting for approval (journal vouchers, payments, expenses)
            approvals.migrate(db)
            employee_cols={row["name"] for row in db.execute("PRAGMA table_info(employees)")}
            for column in ("nationality","father_name","mother_name","birth_date","birth_place","sex")+self.EMPLOYEE_REGISTER_FIELDS:
                if column not in employee_cols: db.execute(f"ALTER TABLE employees ADD COLUMN {column} TEXT")
            payroll_cols={row["name"] for row in db.execute("PRAGMA table_info(payroll_records)")}
            for column in ("allowances",):
                if column not in payroll_cols: db.execute(f"ALTER TABLE payroll_records ADD COLUMN {column} TEXT")
            import chart_extra
            chart_extra.ensure_accounts(db)
            item_cols={row["name"] for row in db.execute("PRAGMA table_info(invoice_items)")}
            for column,definition in (("unit","TEXT"),("discount_percent","TEXT"),("discount_amount","TEXT"),("gross_amount","TEXT")):
                if column not in item_cols: db.execute(f"ALTER TABLE invoice_items ADD COLUMN {column} {definition}")
            inv_cols={row["name"] for row in db.execute("PRAGMA table_info(invoices)")}
            for column,definition in (("doc_subtype","TEXT NOT NULL DEFAULT 'invoice'"),("invoice_discount_percent","TEXT"),("invoice_discount_amount","TEXT"),
                    ("gross_before_discount","TEXT"),("notes","TEXT")):
                if column not in inv_cols: db.execute(f"ALTER TABLE invoices ADD COLUMN {column} {definition}")
            if "return_request_id" not in inv_cols: db.execute("ALTER TABLE invoices ADD COLUMN return_request_id TEXT")
            if "payment_account" not in inv_cols: db.execute("ALTER TABLE invoices ADD COLUMN payment_account TEXT")
            if "is_return" not in inv_cols:
                # 2.9.45: a return (goods back, stock moves) is told apart from a credit note (discount / price
                # adjustment, no stock). Credit notes made by "Return" from an invoice are returns.
                db.execute("ALTER TABLE invoices ADD COLUMN is_return INTEGER NOT NULL DEFAULT 0")
                linked=("OR (linked_invoice_id IS NOT NULL AND EXISTS(SELECT 1 FROM invoice_items x WHERE x.invoice_id=invoices.id AND x.origin_item_id IS NOT NULL))"
                        if "linked_invoice_id" in inv_cols and "origin_item_id" in {r["name"] for r in db.execute("PRAGMA table_info(invoice_items)")} else "")
                db.execute(f"UPDATE invoices SET is_return=1 WHERE doc_subtype='credit_note' AND (source_file IN ('Sales Return','Purchase Return') {linked})")
            if "return_request_hash" not in inv_cols: db.execute("ALTER TABLE invoices ADD COLUMN return_request_hash TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_invoice_return_request ON invoices(return_request_id) WHERE return_request_id IS NOT NULL")
            item_cols={row["name"] for row in db.execute("PRAGMA table_info(invoice_items)")}
            if "origin_item_id" not in item_cols: db.execute("ALTER TABLE invoice_items ADD COLUMN origin_item_id INTEGER")
            db.execute("""CREATE TABLE IF NOT EXISTS payment_allocations (id INTEGER PRIMARY KEY, payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
                invoice_id INTEGER NOT NULL, amount TEXT NOT NULL, created_at TEXT NOT NULL)""")
            # new default posting accounts for payroll (only where the old defaults were never changed)
            for row in db.execute("SELECT id,employee_account_map,manager_account_map FROM payroll_settings").fetchall():
                for column,new_map in (("employee_account_map",chart_extra.PAYROLL_MAP),("manager_account_map",chart_extra.MANAGER_PAYROLL_MAP)):
                    try: current=json.loads(row[column] or "{}")
                    except ValueError: current={}
                    if not current or current==chart_extra.OLD_PAYROLL_MAP: db.execute(f"UPDATE payroll_settings SET {column}=? WHERE id=?",(json.dumps(new_map),row["id"]))
            db.execute("""UPDATE payroll_settings SET payroll_tax_account='4411',nssf_payable_account='4431',salary_account='6311'
                WHERE payroll_tax_account='443100001' AND nssf_payable_account='447100001'""")
            # 2.9.80: employees saved with the old automatic salary account 621100001 (6211 = sub-contractors) follow the
            # Standard Posting Accounts again (6311 staff / 6316 managers). Payroll already posted is not changed. Once only.
            if not db.execute("SELECT 1 FROM app_settings WHERE key='payroll_accounts_2980'").fetchone():
                db.execute("UPDATE employees SET salary_account=NULL WHERE salary_account='621100001'")
                # the managers' map was written as a copy of the staff map (6311): managers go to 6316 again
                for row in db.execute("SELECT id,employee_account_map,manager_account_map FROM payroll_settings").fetchall():
                    try: staff=json.loads(row["employee_account_map"] or "{}"); managers=json.loads(row["manager_account_map"] or "{}")
                    except ValueError: continue
                    if managers and managers==staff and managers.get("salary")=="6311":
                        managers.update({key:"6316" for key in ("salary","overtime","retro_salary")})
                        db.execute("UPDATE payroll_settings SET manager_account_map=? WHERE id=?",(json.dumps(managers),row["id"]))
                db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('payroll_accounts_2980','done')")
            user_columns={row["name"] for row in db.execute("PRAGMA table_info(users)")}
            if "expires_at" not in user_columns: db.execute("ALTER TABLE users ADD COLUMN expires_at TEXT")
            if "permissions" not in user_columns: db.execute("ALTER TABLE users ADD COLUMN permissions TEXT NOT NULL DEFAULT '{}'")
            if "view_hidden" not in user_columns: db.execute("ALTER TABLE users ADD COLUMN view_hidden TEXT NOT NULL DEFAULT '[]'")  # 2.9.81: what this user hides
            if "created_at" not in user_columns: db.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
            import owner_access  # 2.9.101: the hidden owner account
            owner_access.migrate(db)
            invoice_columns={row["name"] for row in db.execute("PRAGMA table_info(invoices)")}
            if "vat_recoverable" not in invoice_columns: db.execute("ALTER TABLE invoices ADD COLUMN vat_recoverable INTEGER NOT NULL DEFAULT 1")
            expense_columns={row["name"] for row in db.execute("PRAGMA table_info(expenses)")}
            if "vat_recoverable" not in expense_columns: db.execute("ALTER TABLE expenses ADD COLUMN vat_recoverable INTEGER NOT NULL DEFAULT 1")
            # 2.9.110: an expense without an official invoice stays in the books but is added back to the taxable profit
            if "tax_deductible" not in expense_columns: db.execute("ALTER TABLE expenses ADD COLUMN tax_deductible INTEGER NOT NULL DEFAULT 1")
            # 2.9.113: the same tick on journal vouchers, purchases and payments (one row = that entry is not deductible for income tax)
            db.execute("CREATE TABLE IF NOT EXISTS tax_flags(source_type TEXT NOT NULL,source_id INTEGER NOT NULL,PRIMARY KEY(source_type,source_id))")
            db.execute("""CREATE TABLE IF NOT EXISTS income_exemptions(source_type TEXT NOT NULL,source_id INTEGER NOT NULL,reason TEXT NOT NULL,
                PRIMARY KEY(source_type,source_id))""")  # 2.9.113: income not subject to income tax, with its legal reason
            db.execute("INSERT OR IGNORE INTO users(username,password_hash,role) VALUES(?,?,?)", ("admin", hash_password(admin_password), "admin"))
            db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('base_currency','USD')")
            db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('second_currency','LBP')")  # 2.9.71: the 2 main currencies
            # 2.9.72: the VAT of the company - rate (Lebanon 11%) and the 2 currencies of the VAT return (LBP, with USD)
            db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('vat_rate','11')")
            db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('vat_currency','LBP')")
            db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('vat_second_currency','USD')")
            db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('backup_interval_hours','24')")
            db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('last_scheduled_backup','')")
            default_brackets=json.dumps([[360000000,.02],[900000000,.04],[1800000000,.07],[3600000000,.11],[7200000000,.15],[13500000000,.20],[None,.25]])
            if not db.execute("SELECT 1 FROM payroll_settings LIMIT 1").fetchone():
                db.execute("""INSERT INTO payroll_settings(date_from,date_to,tax_brackets,created_at)
                    VALUES('2025-01-01',NULL,?,?)""",(default_brackets,utcnow()))
            else:
                # Older startups inserted the factory 2025 row even after effective-dated rules
                # existed. Remove only that untouched, overlapping factory row, never a user's row.
                db.execute("""DELETE FROM payroll_settings WHERE date_from='2025-01-01'
                    AND date_to IS NULL AND created_by IS NULL AND tax_brackets=?
                    AND single_allowance='450000000' AND spouse_allowance='225000000' AND child_allowance='45000000'
                    AND CAST(employee_ceiling AS REAL)=0 AND CAST(medical_ceiling AS REAL)=0 AND CAST(family_ceiling AS REAL)=0
                    AND CAST(family_allowance_spouse AS REAL)=0 AND CAST(family_allowance_child AS REAL)=0
                    AND EXISTS(SELECT 1 FROM payroll_settings AS previous
                               WHERE previous.date_from<'2025-01-01' AND previous.date_to>='2025-01-01')
                    AND EXISTS(SELECT 1 FROM payroll_settings AS following WHERE following.date_from>'2025-01-01')""",
                    (default_brackets,))
            import chart_templates  # 2.9.116: a company created with another chart keeps it (IFRS, Saudi Arabia, UAE)
            if chart_templates.current(db) != "lebanon": chart_templates.ensure(db, chart_templates.current(db))
            else:
                db.executemany("""INSERT INTO accounts(code,name_en,name_ar,name_fr,type)
                    VALUES(?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET
                    name_en=excluded.name_en,name_ar=excluded.name_ar,name_fr=excluded.name_fr,type=excluded.type""",
                    [row[:5] for row in LEBANESE_ACCOUNTS])
                for code, _name_en, _name_ar, _name_fr, _type, parent_code in LEBANESE_ACCOUNTS:
                    if parent_code:
                        db.execute("UPDATE accounts SET parent_id=(SELECT id FROM accounts WHERE code=?) WHERE code=?",
                                   (parent_code, code))
            for old_code, new_code in LEGACY_ACCOUNT_MAP.items():
                old = db.execute("SELECT id FROM accounts WHERE code=?", (old_code,)).fetchone()
                new = db.execute("SELECT id FROM accounts WHERE code=?", (new_code,)).fetchone()
                if old and new and old["id"] != new["id"]:
                    db.execute("UPDATE journal_lines SET account_id=? WHERE account_id=?", (new["id"], old["id"]))
                    db.execute("DELETE FROM accounts WHERE id=?", (old["id"],))
            db.execute("UPDATE invoices SET supplier_account=? WHERE supplier_account='2100'",
                       (DEFAULT_LEBANESE_ACCOUNTS["accounts_payable"],))
            db.execute("UPDATE invoices SET vat_account=? WHERE vat_account='1300'",
                       (DEFAULT_LEBANESE_ACCOUNTS["vat_receivable"],))
            db.execute("UPDATE invoices SET expense_account=? WHERE expense_account='5100'",
                       (DEFAULT_LEBANESE_ACCOUNTS["purchases"],))
            db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type,parent_id) VALUES(?,?,?,(SELECT id FROM accounts WHERE code='6011'))",
                       (EXPENSE_ACCOUNT_9,"General Expenses - 9 Digit","expense"))
            db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type,parent_id) VALUES(?,?,?,(SELECT id FROM accounts WHERE code='4426.6'))",
                       ("442660000","VAT Receivable - 9 Digit","asset"))
            db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type,parent_id) VALUES(?,?,?,(SELECT id FROM accounts WHERE code='6011'))",
                       (EXPENSE_NO_VAT_ACCOUNT_9,"Expenses without VAT - 9 Digit","expense"))
            db.execute("UPDATE invoices SET expense_account=? WHERE expense_account='6011'",(EXPENSE_ACCOUNT_9,))
            db.execute("UPDATE invoices SET vat_account=? WHERE vat_account='4426.6'",(VAT_ACCOUNT_9,))
            db.execute("UPDATE invoices SET entry_type=kind WHERE entry_type IS NULL OR entry_type='' OR (entry_type='purchase' AND kind='sale')")
            db.execute("UPDATE invoices SET entry_type='purchases' WHERE entry_type IN ('purchase','expense_without_vat')")
            db.execute("UPDATE invoices SET entry_type='sales' WHERE entry_type='sale'")
            suppliers=db.execute("SELECT id,name,account_number FROM parties WHERE kind IN ('supplier','both') ORDER BY id").fetchall()
            for supplier in suppliers:
                account_number=supplier["account_number"] or f"4011{supplier['id']:05d}"
                db.execute("UPDATE parties SET account_number=? WHERE id=?",(account_number,supplier["id"]))
                db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type,parent_id) VALUES(?,?,?,(SELECT id FROM accounts WHERE code='4011'))",
                    (account_number,f"Supplier - {supplier['name']}","liability"))
                db.execute("UPDATE invoices SET supplier_account=? WHERE party_id=? AND kind='purchase' AND supplier_account='4011'",
                    (account_number,supplier["id"]))
            # Performance indexes on the columns used for filtering and joins.
            # Placed at the very end of initialize so every table (including
            # those created by later migrations) already exists. Without these
            # SQLite falls back to full-table scans, which get slow as
            # invoices / journal lines / payments grow. IF NOT EXISTS makes
            # this idempotent and it applies to every company database.
            for index_sql in (
                "CREATE INDEX IF NOT EXISTS idx_invoices_party ON invoices(party_id)",
                "CREATE INDEX IF NOT EXISTS idx_invoices_kind ON invoices(kind)",
                "CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date)",
                "CREATE INDEX IF NOT EXISTS idx_invoices_branch ON invoices(branch_id)",
                "CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id)",
                "CREATE INDEX IF NOT EXISTS idx_invoice_attachments_invoice ON invoice_attachments(invoice_id)",
                "CREATE INDEX IF NOT EXISTS idx_party_documents_party ON party_documents(party_id)",
                "CREATE INDEX IF NOT EXISTS idx_case_attachments_case ON case_attachments(case_id)",
                "CREATE INDEX IF NOT EXISTS idx_document_cases_party ON document_cases(party_id)",
                "CREATE INDEX IF NOT EXISTS idx_document_cases_invoice ON document_cases(invoice_id)",
                "CREATE INDEX IF NOT EXISTS idx_journal_entries_source ON journal_entries(source_type,source_id)",
                "CREATE INDEX IF NOT EXISTS idx_journal_entries_date ON journal_entries(entry_date)",
                "CREATE INDEX IF NOT EXISTS idx_journal_entries_branch ON journal_entries(branch_id)",
                "CREATE INDEX IF NOT EXISTS idx_journal_lines_entry ON journal_lines(entry_id)",
                "CREATE INDEX IF NOT EXISTS idx_journal_lines_account ON journal_lines(account_id)",
                "CREATE INDEX IF NOT EXISTS idx_journal_lines_party ON journal_lines(party_id)",
                "CREATE INDEX IF NOT EXISTS idx_stock_movements_item ON stock_movements(item_id)",
                "CREATE INDEX IF NOT EXISTS idx_stock_movements_source ON stock_movements(source_type,source_id)",
                "CREATE INDEX IF NOT EXISTS idx_payments_party ON payments(party_id)",
                "CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date)",
                "CREATE INDEX IF NOT EXISTS idx_payment_allocations_payment ON payment_allocations(payment_id)",
                "CREATE INDEX IF NOT EXISTS idx_payment_allocations_invoice ON payment_allocations(invoice_id)",
                "CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date)",
                "CREATE INDEX IF NOT EXISTS idx_payroll_records_employee ON payroll_records(employee_id)",
                "CREATE INDEX IF NOT EXISTS idx_payroll_records_period ON payroll_records(period_date)",
                "CREATE INDEX IF NOT EXISTS idx_employees_active ON employees(active)",
                "CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity,entity_id)",
                "CREATE INDEX IF NOT EXISTS idx_budgets_year ON budgets(year)",
            ):
                db.execute(index_sql)
            # Refresh the query planner statistics so it actually uses the
            # indexes above.
            db.execute("ANALYZE")
        self._auto_lebanese_payroll_rules()
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES('startup_schema_version',?)",
                       (self._schema_version(),))
            db.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES('startup_schema_signature',?)",
                       (self._startup_schema_signature(db),))

    def _auto_lebanese_payroll_rules(self):
        """If the Tax & NSSF settings were never filled in (all NSSF ceilings are 0), load the official Lebanese
        periods automatically so the 2024-2026 ceilings apply month by month without any manual step."""
        with self.connect() as db:
            rows=db.execute("SELECT employee_ceiling,medical_ceiling,family_ceiling FROM payroll_settings").fetchall()
            done=db.execute("SELECT value FROM app_settings WHERE key='lebanese_payroll_rules_auto'").fetchone()
        unconfigured=not rows or all(Decimal(str(r["employee_ceiling"] or 0))==0 and Decimal(str(r["medical_ceiling"] or 0))==0 and Decimal(str(r["family_ceiling"] or 0))==0 for r in rows)
        if done:
            self._upgrade_default_family_allowance_periods()
            return
        if not unconfigured: return
        self.apply_lebanese_payroll_rules(None)
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES('lebanese_payroll_rules_auto',?)",(utcnow(),))

    def _upgrade_default_family_allowance_periods(self):
        """Fill old zero-valued CNSS benefits only in unmodified auto-loaded periods."""
        import lebanese_payroll
        expected={period["date_from"]:period for period in lebanese_payroll.official_periods()}
        unchanged=("tax_brackets","single_allowance","spouse_allowance","child_allowance",
                   "employee_nssf_rate","medical_rate","family_rate","end_service_rate",
                   "employee_ceiling","medical_ceiling","family_ceiling","end_service_ceiling",
                   "max_children_deduction","transport_daily_exempt","default_transport_days",
                   "schooling_annual_exempt","schooling_max_children","tax_rounding","minimum_wage",
                   "family_allowance_max_children")
        with self.connect() as db:
            for row in db.execute("SELECT * FROM payroll_settings WHERE created_by IS NULL").fetchall():
                preset=expected.get(row["date_from"])
                if not preset or row["date_to"]!=preset["date_to"]: continue
                try:
                    if any((json.loads(row[field]) if field=="tax_brackets" else str(row[field]))!=
                           (preset[field] if field=="tax_brackets" else str(preset[field])) for field in unchanged): continue
                    if any(Decimal(str(row[field] or 0))!=0 for field in ("family_allowance_spouse","family_allowance_child","family_allowance_cap")): continue
                except (ValueError,TypeError,ArithmeticError):
                    continue  # Do not reinterpret a manually edited or malformed period.
                db.execute("""UPDATE payroll_settings SET family_allowance_spouse=?, family_allowance_child=?, family_allowance_cap=?
                    WHERE id=?""",(preset["family_allowance_spouse"],preset["family_allowance_child"],preset["family_allowance_cap"],row["id"]))

    @staticmethod
    def month_end(value):
        """Payroll is monthly: the rules of a month are those in force on its last day."""
        day=datetime.strptime(iso_date(value),"%Y-%m-%d")
        import calendar
        return day.replace(day=calendar.monthrange(day.year,day.month)[1]).strftime("%Y-%m-%d")

    @staticmethod
    def user_is_expired(user, today=None):
        expires=user["expires_at"] if "expires_at" in user.keys() else None
        if not expires: return False
        today=today or datetime.now().strftime("%Y-%m-%d")
        return str(expires) < today

    def login(self, username, password, remote_addr=None):
        """Authenticate with a persistent 15-minute lockout and audit every denial."""
        username=str(username or "").strip(); now=datetime.now(timezone.utc)
        keys=["user:"+username.casefold()]
        if remote_addr: keys.append("ip:"+str(remote_addr))
        with self.connect() as db:
            attempts={row["key"]:row for row in db.execute(
                f"SELECT * FROM login_attempts WHERE key IN ({','.join('?' for _ in keys)})",keys)}
            locked=any(row["locked_until"] and (parse_ts(row["locked_until"]) or now)>now for row in attempts.values())
            import licence  # 2.9.103: no hidden account any more - the installation has a signed licence
            user = db.execute("SELECT * FROM users WHERE username=? AND active=1 AND COALESCE(hidden,0)=0", (username,)).fetchone()
            if locked:
                db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                           (user["id"] if user else None,"login_blocked","auth",json.dumps({"username":username,"remote_addr":remote_addr}),utcnow()))
                return {"rate_limited": True}
            if not user or not verify_password(password, user["password_hash"]):
                for key in keys:
                    previous=attempts.get(key)
                    first=parse_ts(previous["first_failed_at"]) if previous else None
                    count=(previous["failed_count"]+1) if first and now-first<timedelta(minutes=15) else 1
                    limit=5 if key.startswith("user:") else 30
                    until=(now+timedelta(minutes=15)).isoformat() if count>=limit else None
                    db.execute("INSERT INTO login_attempts(key,failed_count,first_failed_at,locked_until) VALUES(?,?,?,?) "
                               "ON CONFLICT(key) DO UPDATE SET failed_count=excluded.failed_count,first_failed_at=excluded.first_failed_at,locked_until=excluded.locked_until",
                               (key,count,previous["first_failed_at"] if first and now-first<timedelta(minutes=15) else utcnow(),until))
                db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                           (user["id"] if user else None,"login_failed","auth",json.dumps({"username":username,"remote_addr":remote_addr}),utcnow()))
                return None
            db.execute("DELETE FROM login_attempts WHERE key=?",(keys[0],))
            state = licence.status(db)
            if state["expired"]: raise PermissionError(state["message"])
            if self.user_is_expired(user):
                raise PermissionError(f"This account expired on {display_date(user['expires_at'])}. Ask the administrator to renew it.")
            token = secrets.token_urlsafe(32)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=SESSION_HOURS)
            stale = [row["token"] for row in db.execute("SELECT token,created_at FROM sessions")
                     if (parse_ts(row["created_at"]) or datetime.now(timezone.utc)) < cutoff]
            for stale_token in stale:
                db.execute("DELETE FROM sessions WHERE token=?", (stale_token,))
            db.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token, user["id"], utcnow()))
            return {"token": token, "username": user["username"], "role": user["role"], "language": user["language"],
                "expires_at": user["expires_at"], "permissions": parse_permissions(user["permissions"]) if user["role"]!="admin" else {m:True for m in PERMISSION_MODULES},
                "licence": state}

    def user_for_token(self, token):
        if not token: return None
        with self.connect() as db:
            row=db.execute("""SELECT u.*, s.created_at AS session_created_at FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token=? AND u.active=1""", (token,)).fetchone()
        if not row: return None
        created=parse_ts(row["session_created_at"])
        if created is None or (datetime.now(timezone.utc)-created) > timedelta(hours=SESSION_HOURS): return None
        if self.user_is_expired(row): return None
        import licence
        with self.connect() as db:
            if licence.status(db)["expired"]: return None
        return row

    def ensure_user_row(self, user):
        """Copy a signed-in user (from the main file) into this company-year file once: same id, no password
        (signing in always happens on the main file)."""
        user_id = int(user["id"]); cache = self.__dict__.setdefault("_known_user_ids", set())
        if user_id in cache: return
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
                name = str(user["username"])
                if db.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (name,)).fetchone(): name = f"{name}#{user_id}"
                db.execute("INSERT INTO users(id,username,password_hash,role,language,active) VALUES(?,?,?,?,?,1)",
                           (user_id, name, "!", user["role"], user["language"] if "language" in user.keys() else "en"))
        cache.add(user_id)

    def user_can(self, user, module):
        if not user: return False
        if user["role"]=="admin": return True
        return parse_permissions(user["permissions"] if "permissions" in user.keys() else "{}").get(module, module != "approve")

    def list_users(self):
        today=datetime.now().date()
        with self.connect() as db:
            rows=[dict(row) for row in db.execute("SELECT id,username,role,language,active,expires_at,permissions FROM users WHERE COALESCE(hidden,0)=0 ORDER BY username")]
        for row in rows:
            row["permissions"]=parse_permissions(row.get("permissions"))
            if row.get("expires_at"):
                row["days_remaining"]=(datetime.strptime(row["expires_at"],"%Y-%m-%d").date()-today).days
                row["status"]="expired" if row["days_remaining"]<0 else "active"
            else:
                row["days_remaining"]=None; row["status"]="active"
            if not row["active"]: row["status"]="disabled"
        return rows

    def save_user(self, item, acting_user_id):
        username=str(item.get("username") or "").strip(); role=str(item.get("role") or "viewer").strip()
        language=str(item.get("language") or "en").strip(); password=str(item.get("password") or "")
        active=1 if item.get("active",True) else 0; user_id=item.get("id")
        if not username or role not in ("admin","accountant","viewer") or language not in ("en","ar","fr"):
            raise ValueError("Enter a valid username, role, and language")
        if password and len(password)<6: raise ValueError("Password must contain at least 6 characters")
        permissions=json.dumps(parse_permissions(item.get("permissions")))
        one_year=(datetime.now()+timedelta(days=USER_VALIDITY_DAYS)).strftime("%Y-%m-%d")
        with self.connect() as db:
            existing=db.execute("SELECT * FROM users WHERE id=?",(int(user_id),)).fetchone() if user_id else None
            if existing and "hidden" in existing.keys() and existing["hidden"]: existing=None  # 2.9.101: the owner account is not the client's
            if user_id and not existing: raise ValueError("User was not found")

            clash=db.execute("SELECT id FROM users WHERE lower(username)=lower(?) AND id<>?",(username,int(user_id or 0))).fetchone()
            if clash: raise ValueError(f"Username '{username}' is already used")
            if item.get("renew"): expires=one_year
            elif "expires_at" in item: expires=iso_date(item["expires_at"],"Expiry date") if str(item.get("expires_at") or "").strip() else None
            elif existing: expires=existing["expires_at"]
            else: expires=None if role=="admin" else one_year
            if existing and existing["role"]=="admin" and (role!="admin" or not active):
                admins=db.execute("SELECT COUNT(*) n FROM users WHERE role='admin' AND active=1 AND COALESCE(hidden,0)=0 AND id<>?",(int(user_id),)).fetchone()["n"]
                if not admins: raise ValueError("At least one active administrator must remain")
            if user_id:
                db.execute("UPDATE users SET username=?,role=?,language=?,active=?,expires_at=?,permissions=? WHERE id=?",
                    (username,role,language,active,expires,permissions,int(user_id)))
                if password: db.execute("UPDATE users SET password_hash=? WHERE id=?",(hash_password(password),int(user_id)))
                if not active or password: db.execute("DELETE FROM sessions WHERE user_id=?",(int(user_id),))
                saved_id=int(user_id)
            else:
                if not password: raise ValueError("Password is required for a new user")
                saved_id=db.execute("INSERT INTO users(username,password_hash,role,language,active,expires_at,permissions,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (username,hash_password(password),role,language,active,expires,permissions,utcnow())).lastrowid
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (acting_user_id,"save","user",saved_id,json.dumps({"username":username,"role":role,"active":active,"expires_at":expires,"permissions":json.loads(permissions)}),utcnow()))
        return next(row for row in self.list_users() if row["id"]==saved_id)

    def _account_id(self, db, code):
        row = db.execute("SELECT id FROM accounts WHERE code=?", (code,)).fetchone()
        return row["id"]

    def _entry_type(self,item):
        value=str(item.get("entry_type") or item.get("kind") or "purchases").strip().lower().replace(" ","_")
        aliases={"sale":"sales","purchase":"purchases","expense_without_vat":"expenses"}
        value=aliases.get(value,value)
        if value not in ("assets","expenses","purchases","sales"):
            raise ValueError("Type must be Assets, Expenses, Purchases, or Sales")
        return value

    def _side(self,value,default):
        side=str(value or default).strip().upper()[:1]
        if side not in ("D","C"): raise ValueError("Account side must be D or C")
        return side

    def _line_for_side(self,code,amount,side):
        return (code,amount,Decimal("0")) if side=="D" else (code,Decimal("0"),amount)

    def _branch_id(self,db,item):
        value=item.get("branch_id") if isinstance(item,dict) else None
        if value:
            row=db.execute("SELECT id FROM branches WHERE id=? AND active=1",(int(value),)).fetchone()
            if not row: raise ValueError("Branch was not found")
            return row["id"]
        name=str(item.get("branch") or "Head Office").strip() if isinstance(item,dict) else "Head Office"
        db.execute("INSERT OR IGNORE INTO branches(name) VALUES(?)",(name,))
        return db.execute("SELECT id FROM branches WHERE name=?",(name,)).fetchone()["id"]

    def _ensure_party_account(self, db, party):
        if party["kind"] not in ("customer","supplier","both"): return None
        category=(party["account_category"] or ("client" if party["kind"]=="customer" else "supplier")) if "account_category" in party.keys() else ("client" if party["kind"]=="customer" else "supplier")
        prefix={"client":"4111","supplier":"4011","asset_supplier":"4031","other_payable":"4619"}.get(category,"4011")
        account_number=party["account_number"]
        if not account_number:
            last=db.execute("SELECT account_number FROM parties WHERE account_number LIKE ? AND length(account_number)=9 ORDER BY CAST(account_number AS INTEGER) DESC LIMIT 1",
                    (prefix+"%",)).fetchone()
            next_suffix=(int(last["account_number"][4:])+1) if last else 1
            if next_suffix>99999: raise ValueError(f"No account numbers remain under prefix {prefix}")
            account_number=f"{prefix}{next_suffix:05d}"
        db.execute("UPDATE parties SET account_number=? WHERE id=?",(account_number,party["id"]))
        parent="4111" if party["kind"]=="customer" else "4011"
        label={"client":"Client","supplier":"Supplier","asset_supplier":"Asset Supplier","other_payable":"Other Payable"}.get(category,"Supplier")
        account_type="asset" if party["kind"]=="customer" else "liability"
        db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type,parent_id) VALUES(?,?,?,(SELECT id FROM accounts WHERE code=?))",
            (account_number,f"{label} - {party['name']}",account_type,parent))
        import vat_ledgers  # 2.9.97: every customer / supplier has its own VAT account (when the rule is on)
        if vat_ledgers.enabled(db): vat_ledgers.ensure_party_vat_account(db,account_number)
        return account_number

    def _date_year(self, value):
        text = str(value or "").strip()
        for pattern in ("%d-%m-%Y", "%d%m%Y", "%Y-%m-%d", "%Y%m%d"):
            try: return datetime.strptime(text, pattern).year
            except ValueError: pass
        raise ValueError("Date must use DD-MM-YYYY")

    def _assert_period_open(self, value):
        year = self._date_year(value)
        with self.connect() as db:
            row = db.execute("SELECT status FROM fiscal_years WHERE year=?", (year,)).fetchone()
        if row and row["status"] == "closed":
            raise ValueError(f"Fiscal year {year} is closed; entries cannot be added or changed")

    def _assert_vat_open(self, *values):
        """2.9.84: a document dated in a quarter whose VAT return is saved cannot be added, changed or deleted
        (the filed return would no longer agree with the books). An administrator reopens the return first."""
        for value in values:
            text = str(value or "").strip()
            if not text: continue
            parsed = None
            for pattern in ("%d-%m-%Y", "%d%m%Y", "%Y-%m-%d", "%Y%m%d"):
                try: parsed = datetime.strptime(text[:10], pattern); break
                except ValueError: pass
            if not parsed: continue
            quarter = (parsed.month - 1) // 3 + 1
            with self.connect() as db:
                try: saved = db.execute("SELECT 1 FROM vat_returns WHERE year=? AND quarter=?", (parsed.year, quarter)).fetchone()
                except Exception: saved = None
            if saved:
                raise ValueError(f"The Q{quarter} {parsed.year} VAT return is saved; an administrator must reopen it "
                                 "(VAT > Reopen) before documents of that quarter can be added, changed or deleted")

    backup_folder = None   # set by CompanyManager: backups/<company>/<year>
    backup_label = None    # "<company>_<year>"

    def _backups_dir(self):
        return Path(self.backup_folder) if self.backup_folder else Path(self.path).parent / "backups"

    def backup(self, kind="backup"):
        """Consistent copy of this company-year file (SQLite backup API, safe while others are writing).
        Stored in backups/<company>/<year>/<company>_<year>_<date>_<time>.db"""
        source = Path(self.path)
        if not source.exists(): return None
        folder = self._backups_dir(); folder.mkdir(parents=True, exist_ok=True)
        label = self.backup_label or ("nanza_accounting" if Path(self.path).stem == "nanza_accounting" else "saber_accounting")  # 2.9.114
        target = folder / f"{label}_{datetime.now():%Y-%m-%d_%H%M%S}{'_' + kind if kind != 'backup' else ''}.db"
        if target.exists(): target = folder / f"{target.stem}_{datetime.now():%f}.db"
        with self._lock:
            source_connection = sqlite3.connect(str(source)); target_connection = sqlite3.connect(str(target))
            try: source_connection.backup(target_connection)
            finally: target_connection.close(); source_connection.close()
        self._check_new_backup(source, target)
        try:  # 2.9.52: second copy outside the computer's Saber folder (OneDrive / USB / network), when set
            import backup_copy
            backup_copy.copy_backup(target, folder)
        except Exception:
            logging.getLogger("saber").warning("Second backup copy skipped", exc_info=True)
        return str(target)

    BACKUP_CHECKS_FILE = "backup_checks.json"

    def _check_new_backup(self, source, target):
        """2.9.42: every new backup is opened and checked at once (integrity check, same tables as the
        original, can be read). A bad copy is set aside as .damaged (never listed, restored or counted)
        and the backup fails loudly, so nobody relies on it."""
        problem = None
        try:
            connection = sqlite3.connect(Path(target).resolve().as_uri() + "?mode=ro", uri=True)
            try:
                result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok": problem = f"integrity check: {result}"
                copied = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            finally: connection.close()
            if problem is None:
                original_connection = sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)
                try: original = {row[0] for row in original_connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                finally: original_connection.close()
                missing = original - copied
                if missing: problem = "missing tables: " + ", ".join(sorted(missing))
        except sqlite3.DatabaseError as exc:
            problem = f"cannot be opened: {exc}"
        target = Path(target)
        self._record_backup_check(target.parent, target.name, problem is None, problem)
        if problem:
            logging.getLogger("saber.backup").error("Backup %s failed its check (%s)", target.name, problem)
            try: target.replace(target.with_name(target.name + ".damaged"))
            except OSError: pass
            raise RuntimeError(f"The backup could not be verified ({problem}). Your data was not changed; please try again and tell support if it repeats.")

    def _record_backup_check(self, folder, name, ok, problem=None):
        path = Path(folder) / self.BACKUP_CHECKS_FILE
        try: checks = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError): checks = {}
        checks[name] = {"ok": bool(ok), "checked_at": utcnow(), **({"problem": problem} if problem else {})}
        existing = {p.name for p in Path(folder).glob("*.db")}
        checks = {key: value for key, value in checks.items() if key in existing or key == name}
        try:
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(json.dumps(checks, indent=1), encoding="utf-8"); os.replace(temporary, path)
        except OSError:
            logging.getLogger("saber.backup").warning("Backup check result was not saved", exc_info=True)

    def _backup_checks(self):
        checks = {}
        for folder in {self._backups_dir(), Path(self.path).parent / "backups"}:
            try: checks.update(json.loads((folder / self.BACKUP_CHECKS_FILE).read_text(encoding="utf-8")))
            except (OSError, ValueError): pass
        return checks

    @staticmethod
    def _validate_backup_file(path):
        try:
            connection=sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)
            try:
                if connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok": raise ValueError("Backup file is damaged")
                tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally: connection.close()
        except sqlite3.DatabaseError as exc: raise ValueError("Selected file is not a valid Nanza Accounting backup") from exc
        if not {"accounts","journal_entries","invoices"}.issubset(tables): raise ValueError("Selected file is not a Nanza Accounting backup")

    def _backup_files(self):
        folders=[self._backups_dir()]
        legacy=Path(self.path).parent/"backups"
        if legacy.resolve()!=folders[0].resolve(): folders.append(legacy)
        files={}
        for index,folder in enumerate(folders):
            if not folder.exists(): continue
            for path in ([*folder.glob("*.db")] if index==0 else [*folder.glob("saber_accounting_*.db"),*folder.glob("nanza_accounting_*.db")]): files.setdefault(path.name,path)
        return files

    def list_backups(self):
        files=self._backup_files(); checks=self._backup_checks()
        return [{"checked":("ok" if checks[path.name].get("ok") else "FAILED") if path.name in checks else "not checked","name":path.name,
                "size":path.stat().st_size,"modified":datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                 "kind":"safety" if "_safety" in path.stem else "automatic" if path.stem.endswith("_auto") else "older version" if path.name.startswith(("saber_accounting_","nanza_accounting_")) and self.backup_label else "backup"}
                for path in sorted(files.values(),key=lambda p:p.stat().st_mtime,reverse=True)]

    def backup_path(self, name):
        path=self._backup_files().get(Path(str(name)).name)
        if not path or not path.exists(): raise ValueError("Backup was not found")
        return path

    def restore_backup(self, name, user_id):
        source=self.backup_path(name).resolve()
        self._validate_backup_file(source)
        safety=self.backup("safety")
        with self._lock:
            self.release()  # nobody may read or write this file while it is being replaced
            source_connection=sqlite3.connect(str(source)); target_connection=sqlite3.connect(self.path)
            try: source_connection.backup(target_connection)
            finally: target_connection.close(); source_connection.close()
        # 2.9.70: a backup made by an older version lacks the newer tables / columns ("no such column:
        # i.payment_account" until the program was restarted). Upgrade it now; data is kept, an existing admin is untouched.
        self.__dict__.pop("_rate_state", None); self.__dict__.pop("_known_user_ids", None)
        self.initialize_if_needed(secrets.token_urlsafe(24))
        with self.connect() as db:
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                (user_id,"restore","database",json.dumps({"backup":source.name,"safety_backup":safety}),utcnow()))
        return {"restored":source.name,"safety_backup":safety}

    def vat_rate_percent(self):
        """2.9.72: the standard VAT rate of this company in % (Lebanon 11; for example 5 in the Emirates, 15 in Saudi Arabia)."""
        try: return parse_vat_rate(self.settings().get("vat_rate") or "11")
        except ValueError: return Decimal("11")

    def vat_currencies(self):
        """2.9.72: the currency of the VAT return (LBP in Lebanon) and the second one shown next to it (USD)."""
        values=self.settings()
        return (str(values.get("vat_currency") or "LBP").upper(), str(values.get("vat_second_currency") or "USD").upper())

    def settings(self):
        with self.connect() as db: return {row["key"]:row["value"] for row in db.execute("SELECT key,value FROM app_settings")}

    def default_accounts(self):
        """2.9.81: the default posting accounts of this company (Settings > Accounting Settings)."""
        import accounting_setup
        try: return accounting_setup.default_accounts(self)
        except Exception: return {key: spec[1] for key, spec in accounting_setup.DEFAULT_ACCOUNTS.items()}

    def default_account(self, key):
        return self.default_accounts()[key]

    def currencies(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT code,name FROM currencies ORDER BY CASE code WHEN 'USD' THEN 0 WHEN 'LBP' THEN 1 WHEN 'EUR' THEN 2 WHEN 'AED' THEN 3 ELSE 4 END,code")]

    def currency_codes(self):
        return {item["code"] for item in self.currencies()}

    def cash_check(self, account, currency, date, amount):
        """2.9.84: balance of a cash / bank account (class 5) in its own currency on `date`, and after paying `amount` out of it.
        Lets the screens warn before a payment or an expense makes the cash or the bank negative."""
        code = str(account or "").split(" - ", 1)[0].strip(); currency = str(currency or "").upper()
        try: amount = Decimal(str(amount or 0).replace(",", ""))
        except Exception as exc: raise ValueError("Amount must be a number") from exc
        day = iso_date(date)
        if not code.startswith("5"): return {"account": code, "checked": False}
        balance = Decimal("0")
        with self.connect() as db:
            for row in db.execute("""SELECT j.debit,j.credit,j.line_currency,j.amount,e.currency,e.entry_date FROM journal_lines j
                    JOIN journal_entries e ON e.id=j.entry_id JOIN accounts a ON a.id=j.account_id
                    LEFT JOIN invoices i ON e.source_type='invoice' AND i.id=e.source_id
                    WHERE a.code=? AND (e.source_type!='invoice' OR i.status IN ('posted','cancelled') OR i.status IS NULL)""", (code,)):
                try:
                    if iso_date(row["entry_date"]) > day: continue
                except ValueError: continue
                signed = Decimal(str(row["debit"] or 0)) - Decimal(str(row["credit"] or 0))
                own = (row["line_currency"] or row["currency"] or "").upper()
                if own != currency: continue
                if row["line_currency"] and row["amount"] not in (None, ""): signed = Decimal(str(row["amount"])) * (1 if signed >= 0 else -1)
                balance += signed
        after = balance - amount
        return {"account": code, "currency": currency, "checked": True, "balance": float(balance.quantize(Decimal("0.01"))),
                "after": float(after.quantize(Decimal("0.01"))), "negative": after < 0}

    def audit_trail(self,date_from=None, date_to=None, username=None, entity=None, action=None, text=None, limit=5000):
        """2.9.84: the audit trail of this company-year (who added, changed, posted, deleted what and when), newest first.
        Dates DD-MM-YYYY or YYYY-MM-DD (the day of the change, UTC); username / entity / action exact; text searched in the details."""
        conditions, values = [], []
        for value, sign in ((date_from, ">="), (date_to, "<=")):
            if str(value or "").strip():
                day = iso_date(value); conditions.append(f"substr(l.created_at,1,10){sign}?"); values.append(day)
        for value, column in ((username, "u.username"), (entity, "l.entity"), (action, "l.action")):
            if str(value or "").strip(): conditions.append(f"{column}=?"); values.append(str(value).strip())
        if str(text or "").strip(): conditions.append("COALESCE(l.details,'') LIKE ?"); values.append(f"%{str(text).strip()}%")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.connect() as db:
            rows = [dict(r) for r in db.execute(f"""SELECT l.id,l.created_at,COALESCE(u.username,CASE WHEN l.user_id IS NULL THEN 'system' ELSE '#'||l.user_id END) username,
                l.action,l.entity,l.entity_id,COALESCE(l.details,'') details FROM audit_log l LEFT JOIN users u ON u.id=l.user_id{where}
                ORDER BY l.id DESC LIMIT ?""", values + [max(1, min(int(limit or 5000), 50000))])]
            choices = {"users": sorted({r[0] for r in db.execute("SELECT DISTINCT COALESCE(u.username,'system') FROM audit_log l LEFT JOIN users u ON u.id=l.user_id")}),
                       "entities": sorted({r[0] for r in db.execute("SELECT DISTINCT entity FROM audit_log")}),
                       "actions": sorted({r[0] for r in db.execute("SELECT DISTINCT action FROM audit_log")})}
        return {"items": rows, **choices}

    def save_currency(self, code, name, user_id):
        code=str(code or "").strip().upper(); name=str(name or "").strip()
        if not re.fullmatch(r"[A-Z]{3}",code): raise ValueError("Currency code must be three letters")
        if not name or len(name)>80: raise ValueError("Enter a currency name up to 80 characters")
        with self.connect() as db:
            if db.execute("SELECT 1 FROM currencies WHERE code=?",(code,)).fetchone(): raise ValueError(f"Currency {code} already exists")
            db.execute("INSERT INTO currencies(code,name) VALUES(?,?)",(code,name))
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                       (user_id,"create","currency",json.dumps({"code":code,"name":name}),utcnow()))
        return {"code":code,"name":name}

    def save_settings(self, values, user_id):
        allowed={"base_currency","second_currency","vat_rate","vat_currency","vat_second_currency","backup_interval_hours","company_name","company_address",
                "company_phone","company_mof","company_nssf","company_email","company_website","company_logo","company_vat_registered","company_vat_date",
                "vat_ratio_method","company_name_ar","company_address_ar","company_trade_name","company_cr_number","company_cr_place",
                "show_tax_tick","enable_exempt_income"}
        if str(values.get("base_currency") or "USD") not in self.currency_codes(): raise ValueError("Invalid base currency")
        if "vat_ratio_method" in values and str(values["vat_ratio_method"]).strip().lower() not in ("quarter","annual"):  # 2.9.83
            raise ValueError("VAT ratio method must be quarter or annual")
        if "vat_rate" in values: values=dict(values); values["vat_rate"]=str(parse_vat_rate(values["vat_rate"]))  # 2.9.72
        current=self.settings()
        vat_pair=[str(values.get(key) or current.get(key) or default).upper() for key,default in (("vat_currency","LBP"),("vat_second_currency","USD"))]
        if "vat_currency" in values or "vat_second_currency" in values:
            if any(code not in self.currency_codes() for code in vat_pair): raise ValueError("Invalid VAT currency")
            if vat_pair[0]==vat_pair[1]: raise ValueError("The two VAT currencies must be different")
        if "second_currency" in values:  # 2.9.71
            if str(values.get("second_currency") or "") not in self.currency_codes(): raise ValueError("Invalid second main currency")
            if str(values["second_currency"])==str(values.get("base_currency") or self.settings().get("base_currency") or "USD"):
                raise ValueError("The two main currencies must be different")
        try: hours=int(values.get("backup_interval_hours",24))
        except Exception as exc: raise ValueError("Backup interval must be a number") from exc
        if hours<1 or hours>720: raise ValueError("Backup interval must be between 1 and 720 hours")
        with self.connect() as db:
            for key in allowed:
                if key in values: db.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(values[key])))
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                (user_id,"update","settings",json.dumps({key:values[key] for key in allowed if key in values}),utcnow()))
        return self.settings()

    AUTO_BACKUPS_KEPT = 30

    def maybe_scheduled_backup(self):
        """Automatic backup when the interval (default 24 hours) has passed; keeps the newest 30 automatic copies.
        Manual and safety backups are never deleted."""
        settings=self.settings(); hours=int(settings.get("backup_interval_hours","24")); last=settings.get("last_scheduled_backup","")
        try: due=(datetime.now(timezone.utc)-datetime.fromisoformat(last)).total_seconds()>=hours*3600
        except Exception: due=True
        if not due: return None
        path=self.backup("auto")
        with self.connect() as db:
            db.execute("INSERT INTO app_settings(key,value) VALUES('last_scheduled_backup',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(utcnow(),))
        self.prune_auto_backups()
        return path

    def prune_auto_backups(self, keep=None):
        keep=self.AUTO_BACKUPS_KEPT if keep is None else int(keep)
        folder=self._backups_dir()
        if not folder.exists(): return []
        automatic=sorted(folder.glob("*_auto.db"),key=lambda p:(p.stat().st_mtime,p.name),reverse=True)
        removed=[]
        for path in automatic[keep:]:
            try: path.unlink(); removed.append(path.name)
            except OSError: pass
        return removed

    def books_lock(self):
        value=self.settings().get("books_locked_until","")
        return {"locked_until":value,"display":display_date(value) if value else ""}

    def set_books_lock(self, value, user_id):
        """Lock the books up to a date (DD-MM-YYYY), or unlock with an empty value. A backup is made first."""
        text=str(value or "").strip()
        iso=iso_date(text,"Lock date") if text else ""
        self.backup("safety")
        with self.connect() as db:
            db.execute("INSERT INTO app_settings(key,value) VALUES('books_locked_until',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(iso,))
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                (user_id,"lock" if iso else "unlock","books",json.dumps({"locked_until":iso}),utcnow()))
        return self.books_lock()

    # ---------------------------------------------------------------- numbering helpers
    def _next_number(self, db, table, column, prefix, date):
        try: year = self._date_year(date)
        except ValueError: year = datetime.now().year
        pattern = f"{prefix}-{year}-"
        numbers = [int(row["value"].rsplit("-", 1)[-1]) for row in db.execute(f"SELECT {column} value FROM {table} WHERE {column} LIKE ?", (pattern + "%",))
                   if str(row["value"]).rsplit("-", 1)[-1].isdigit()]
        return f"{pattern}{max(numbers, default=0) + 1:06d}"

    def next_document_number(self, kind, date=None, branch=None):
        date = date or datetime.now().strftime("%d-%m-%Y")
        import numbering  # 2.9.116: Settings > Numbering
        with self.connect() as db:
            if kind in ("customer_receipt", "supplier_payment"): return self._next_payment_number(db, kind, date)
            if kind == "expense": return self._next_number(db, "expenses", "expense_number", numbering.series(db, "expense"), date)
            if kind == "journal_voucher": return self._next_number(db, "journal_entries", "entry_number", numbering.series(db, "journal_voucher", branch), date)
            if kind == "purchase": return self.next_invoice_number("purchase", date)
        raise ValueError("Unknown document type")



def _schema_fingerprint():
    """'4-' + a short hash of the schema and of every text in the upgrade code (CREATE / ALTER TABLE ...), including
    the inventory, fixed assets and bank upgrades and the extra accounts. Any new column, table or account changes it,
    so every company / year file is upgraded once when the new version opens it."""
    import approvals, audit_chain, bank_rec, chart_extra, fixed_assets, inventory, payroll_extras
    texts = [SCHEMA, repr(getattr(chart_extra, "EXTRA_ACCOUNTS", ""))]
    def collect(code):
        for constant in code.co_consts:
            if isinstance(constant, str): texts.append(constant)
            elif hasattr(constant, "co_consts"): collect(constant)
    functions = [getattr(Database, name, None) for name in ("_initialize", "_auto_lebanese_payroll_rules", "_upgrade_default_family_allowance_periods")]
    functions += [inventory.migrate, fixed_assets.migrate, bank_rec.migrate, payroll_extras.migrate, chart_extra.ensure_accounts,
                  audit_chain.migrate, approvals.migrate, __import__('owner_access').migrate] + list(getattr(inventory, "MIGRATIONS", ()))
    # 2.9.101 / 2.9.103: the approval table and the end of the hidden account are part of the upgrade of older files
    for function in functions:
        if function is not None: collect(function.__code__)
    return "4-" + hashlib.sha256("\x00".join(texts).encode("utf-8")).hexdigest()[:16]


def _schema_version(_self=None):
    """Computed once, when a file is first opened (the inventory module imports database, so not at import time)."""
    if not Database.__dict__.get("_schema_version_value"):
        Database._schema_version_value = _schema_fingerprint()
        Database.STARTUP_SCHEMA_VERSION = Database._schema_version_value
    return Database._schema_version_value


Database._schema_version = _schema_version
