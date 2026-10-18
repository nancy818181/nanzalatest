"""Salary payment allocations retain the earning month independently of payment date."""
from decimal import Decimal, InvalidOperation
from database_common import atomic, iso_date, json, utcnow

METHODS = ("Cash", "Bank Transfer", "Cheque", "Card")


def migrate(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS salary_payments (
        id INTEGER PRIMARY KEY, payroll_id INTEGER NOT NULL, entry_id INTEGER NOT NULL,
        payment_date TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL,
        cash_account TEXT NOT NULL, payable_account TEXT NOT NULL, method TEXT NOT NULL,
        reference TEXT, status TEXT NOT NULL DEFAULT 'active', reversal_entry_id INTEGER,
        created_by INTEGER, created_at TEXT NOT NULL)""")


def history(db, payroll_id):
    with db.connect() as connection:
        return [dict(row) for row in connection.execute("""SELECT s.*,e.entry_number,
            COALESCE(NULLIF(e.approval_status,''),e.posting_status,'posted') posting_status
            FROM salary_payments s LEFT JOIN journal_entries e ON e.id=s.entry_id
            WHERE payroll_id=? ORDER BY s.id""", (int(payroll_id),))]


def outstanding(db, record):
    reserved = sum((Decimal(row["amount"]) for row in history(db, record["id"])
                    if row["status"] == "active" and row["entry_number"]), Decimal("0"))
    return Decimal(str(record["net_salary"])) - reserved


@atomic
def record(db, item, user_id, defer_posting=False):
    with db.connect() as connection:
        row = connection.execute("""SELECT p.*,e.full_name FROM payroll_records p
            JOIN employees e ON e.id=p.employee_id WHERE p.id=?""", (int(item.get("payroll_id") or 0),)).fetchone()
        if not row or row["status"] != "posted": raise ValueError("Select a posted payroll record")
        row = dict(row)
        day = iso_date(item.get("payment_date"), "Payment date")
        method = str(item.get("method") or "")
        if method not in METHODS: raise ValueError("Choose the salary payment method")
        try: amount = Decimal(str(item.get("amount") or "0").replace(",", ""))
        except InvalidOperation as exc: raise ValueError("Enter a valid salary payment amount") from exc
        if not amount.is_finite() or amount <= 0: raise ValueError("Salary payment must be finite and above zero")
        remaining = outstanding(db, row)
        if amount > remaining: raise ValueError(f"Payment exceeds the unpaid salary: {remaining} {row['currency']}")
        if amount != amount.quantize(Decimal(".01")): raise ValueError("Use at most two decimal places for the payment")
        payable = row.get("posted_payable_account")
        if not payable:
            # Older payroll: use the actual posted class-421 liability, never today's settings.
            accounts = list(connection.execute("""SELECT DISTINCT a.code FROM journal_lines l JOIN accounts a ON a.id=l.account_id
                WHERE l.entry_id=? AND a.code LIKE '421%' AND CAST(l.credit AS REAL)>0""", (row["journal_entry_id"],)))
            if len(accounts) != 1: raise ValueError("The original salary payable account is ambiguous; review the payroll journal")
            payable = accounts[0][0]
        cash = str(item.get("cash_account") or "").split(" - ", 1)[0].strip()
        account = connection.execute("SELECT type,active FROM accounts WHERE code=?", (cash,)).fetchone()
        if not cash.startswith("5") or not account or not account["active"] or account["type"] != "asset":
            raise ValueError("Choose an active cash or bank account")
        month = row["period_date"][5:7] + "/" + row["period_date"][:4]
        reference = str(item.get("reference") or "").strip()
        voucher = db.save_journal_voucher({"entry_date": day, "currency": row["currency"], "voucher_type": "03",
            "description": f"Salary payment {month} - {row['full_name']} - {row['payroll_number']}"},
            [{"account_code": payable, "debit": str(amount), "credit": "0", "reference": reference},
             {"account_code": cash, "debit": "0", "credit": str(amount), "reference": reference}], user_id,
            defer_posting=defer_posting)["voucher"]
        payment_id = connection.execute("""INSERT INTO salary_payments
            (payroll_id,entry_id,payment_date,amount,currency,cash_account,payable_account,method,reference,created_by,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (row["id"], voucher["id"], day, str(amount), row["currency"], cash,
                payable, method, reference, user_id, utcnow())).lastrowid
        connection.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, "pay", "payroll", row["id"], json.dumps({"salary_month": month, "payment_id": payment_id,
              "voucher": voucher["entry_number"], "amount": str(amount)}), utcnow()))
    return {"payment_id": payment_id, "entry_id": voucher["id"], "voucher": voucher["entry_number"],
            "salary_month": month, "remaining": str(remaining - amount), "currency": row["currency"]}


@atomic
def reverse(db, payment_id, day, user_id):
    day = iso_date(day, "Reversal date")
    with db.connect() as connection:
        payment = connection.execute("SELECT * FROM salary_payments WHERE id=?", (int(payment_id),)).fetchone()
        if not payment or payment["status"] != "active": raise ValueError("Select an active salary payment")
        db._assert_period_open(day)
        if day < payment["payment_date"]: raise ValueError("Reversal date cannot precede the payment date")
        entry = connection.execute("SELECT * FROM journal_entries WHERE id=?", (payment["entry_id"],)).fetchone()
        if not entry: raise ValueError("The salary payment journal is missing; review the books")
        if entry["approval_status"] not in (None, "", "approved"): raise ValueError("Resolve the pending approval before reversing this payment")
        voucher = db.save_journal_voucher({"entry_date": day, "currency": payment["currency"], "voucher_type": "03",
            "description": f"Reverse salary payment {entry['entry_number']}"},
            [{"account_code": payment["cash_account"], "debit": payment["amount"], "credit": "0"},
             {"account_code": payment["payable_account"], "debit": "0", "credit": payment["amount"]}], user_id)["voucher"]
        connection.execute("UPDATE salary_payments SET status='reversed',reversal_entry_id=? WHERE id=?", (voucher["id"], payment["id"]))
        connection.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, "reverse_salary_payment", "payroll", payment["payroll_id"], json.dumps({"payment_id": payment["id"],
             "voucher": voucher["entry_number"]}), utcnow()))
        return {"voucher": voucher["entry_number"]}
