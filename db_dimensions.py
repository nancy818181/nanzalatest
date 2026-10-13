"""Departments, projects and budgets.

Part of the Database class (split out of database.py in 2.9.63, code unchanged): Database inherits from DimensionsStore."""
from __future__ import annotations

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, Decimal, iso_date, json, utcnow
)
from database_common import _soft_iso  # noqa: F401


class DimensionsStore:
    # ---------------------------------------------------------------- departments, projects, budgets
    def _dimension_ids(self, db, item):
        """Resolve a department / project given by id, code or name. Blank means none."""
        result = []
        for table, key in (("departments", "department"), ("projects", "project")):
            value = item.get(f"{key}_id") or item.get(key)
            if value in (None, "", 0, "0", "None"): result.append(None); continue
            text = str(value).split(" - ", 1)[0].strip()
            row = db.execute(f"SELECT id FROM {table} WHERE id=? OR code=? OR lower(name)=lower(?)",
                    (int(text) if text.isdigit() and not text.startswith("0") and len(text) < 6 else -1, text, text)).fetchone()
            if not row: raise ValueError(f"{key.title()} '{text}' was not found")
            result.append(row["id"])
        return tuple(result)

    def list_departments(self, include_inactive=True):
        with self.connect() as db:
            where = "" if include_inactive else " WHERE active=1"
            return [dict(row) for row in db.execute(f"SELECT * FROM departments{where} ORDER BY code")]

    def save_department(self, item, user_id):
        name = str(item.get("name") or "").strip(); code = str(item.get("code") or "").strip().upper()
        if not name: raise ValueError("Department name is required")
        with self.connect() as db:
            if not code:
                numbers = [int(r["code"][1:]) for r in db.execute("SELECT code FROM departments WHERE code GLOB 'D[0-9]*'") if r["code"][1:].isdigit()]
                code = f"D{max(numbers, default=0) + 1:02d}"
            clash = db.execute("SELECT id FROM departments WHERE code=? AND id<>?", (code, int(item.get("id") or 0))).fetchone()
            if clash: raise ValueError(f"Department code {code} is already used")
            active = 1 if item.get("active", True) else 0
            if item.get("id"):
                db.execute("UPDATE departments SET code=?,name=?,active=? WHERE id=?", (code, name, active, int(item["id"]))); saved = int(item["id"])
            else:
                saved = db.execute("INSERT INTO departments(code,name,active,created_at) VALUES(?,?,?,?)", (code, name, active, utcnow())).lastrowid
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, "save", "department", saved, json.dumps({"code": code, "name": name}), utcnow()))
            return dict(db.execute("SELECT * FROM departments WHERE id=?", (saved,)).fetchone())

    def list_projects(self, include_inactive=True):
        with self.connect() as db:
            where = "" if include_inactive else " WHERE p.active=1"
            return [dict(row) for row in db.execute(f"""SELECT p.*,c.name party_name FROM projects p LEFT JOIN parties c ON c.id=p.party_id{where} ORDER BY p.code""")]

    def save_project(self, item, user_id):
        name = str(item.get("name") or "").strip(); code = str(item.get("code") or "").strip().upper()
        if not name: raise ValueError("Project name is required")
        status = str(item.get("status") or "open").lower()
        if status not in ("open", "on hold", "completed", "cancelled"): raise ValueError("Status must be Open, On Hold, Completed or Cancelled")
        start = iso_date(item["start_date"], "Start date") if str(item.get("start_date") or "").strip() else None
        end = iso_date(item["end_date"], "End date") if str(item.get("end_date") or "").strip() else None
        if start and end and end < start: raise ValueError("End date cannot be before start date")
        with self.connect() as db:
            if not code:
                year = (start or datetime.now().strftime("%Y"))[:4]
                numbers = [int(r["code"].rsplit("-", 1)[-1]) for r in db.execute("SELECT code FROM projects WHERE code LIKE ?", (f"P{year}-%",)) if r["code"].rsplit("-", 1)[-1].isdigit()]
                code = f"P{year}-{max(numbers, default=0) + 1:03d}"
            clash = db.execute("SELECT id FROM projects WHERE code=? AND id<>?", (code, int(item.get("id") or 0))).fetchone()
            if clash: raise ValueError(f"Project code {code} is already used")
            party = item.get("party_id")
            if not party and str(item.get("party_name") or "").strip():
                row = db.execute("SELECT id FROM parties WHERE name=? ORDER BY id LIMIT 1", (str(item["party_name"]).strip(),)).fetchone()
                if not row: raise ValueError(f"Customer '{item['party_name']}' was not found")
                party = row["id"]
            values = (code, name, int(party) if party else None, start, end, status, str(item.get("notes") or "").strip() or None, 1 if item.get("active", True) else 0)
            if item.get("id"):
                db.execute("UPDATE projects SET code=?,name=?,party_id=?,start_date=?,end_date=?,status=?,notes=?,active=? WHERE id=?", values + (int(item["id"]),)); saved = int(item["id"])
            else:
                saved = db.execute("INSERT INTO projects(code,name,party_id,start_date,end_date,status,notes,active,created_at) VALUES(?,?,?,?,?,?,?,?,?)", values + (utcnow(),)).lastrowid
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, "save", "project", saved, json.dumps({"code": code, "name": name}), utcnow()))
        return next(p for p in self.list_projects() if p["id"] == saved)

    def list_budgets(self, year, currency="USD", department=None, project=None):
        with self.connect() as db:
            department_id, project_id = self._dimension_ids(db, {"department": department, "project": project})
            rows = [dict(row) for row in db.execute("""SELECT b.account_code,b.month,CAST(b.amount AS REAL) amount,a.name_en account_name,a.type account_type
                FROM budgets b LEFT JOIN accounts a ON a.code=b.account_code WHERE b.year=? AND b.currency=? AND b.department_id=? AND b.project_id=?
                ORDER BY b.account_code,b.month""", (int(year), str(currency).upper(), department_id or 0, project_id or 0))]
        accounts = {}
        for row in rows:
            item = accounts.setdefault(row["account_code"], {"account_code": row["account_code"], "account_name": row["account_name"] or "", "account_type": row["account_type"],
                                                               "annual": 0.0, "months": [0.0] * 12})
            if row["month"]: item["months"][row["month"] - 1] = row["amount"]
            else: item["annual"] = row["amount"]
        for item in accounts.values():
            if not item["annual"]: item["annual"] = round(sum(item["months"]), 2)
        return list(accounts.values())

    def save_budget(self, item, user_id):
        year = int(item.get("year") or 0); currency = str(item.get("currency") or "USD").upper()
        if year < 2000 or year > 2100: raise ValueError("Enter a valid budget year")
        if currency not in self.currency_codes(): raise ValueError("Invalid budget currency")
        lines = item.get("lines")
        if not isinstance(lines, list): raise ValueError("Budget lines are missing")
        with self.connect() as db:
            department_id, project_id = self._dimension_ids(db, {"department": item.get("department"), "project": item.get("project")})
            department_id = department_id or 0; project_id = project_id or 0
            db.execute("DELETE FROM budgets WHERE year=? AND currency=? AND department_id=? AND project_id=?", (year, currency, department_id, project_id))
            saved = 0
            for index, line in enumerate(lines, 1):
                code = str(line.get("account_code") or "").split(" - ", 1)[0].strip()
                if not code: continue
                if not db.execute("SELECT 1 FROM accounts WHERE code=?", (code,)).fetchone(): raise ValueError(f"Line {index}: account {code} was not found")
                months = [Decimal(str(v or 0).replace(",", "")) for v in (line.get("months") or [0] * 12)][:12]
                annual = Decimal(str(line.get("annual") or 0).replace(",", ""))
                if any(v < 0 for v in months) or annual < 0: raise ValueError(f"Line {index}: budget amounts cannot be negative")
                if any(months):
                    for month, value in enumerate(months, 1):
                        if value: db.execute("INSERT INTO budgets(year,currency,account_code,department_id,project_id,month,amount,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                             (year, currency, code, department_id, project_id, month, str(value), user_id, utcnow()))
                elif annual:
                    db.execute("INSERT INTO budgets(year,currency,account_code,department_id,project_id,month,amount,updated_by,updated_at) VALUES(?,?,?,?,?,0,?,?,?)",
                               (year, currency, code, department_id, project_id, str(annual), user_id, utcnow()))
                else: continue
                saved += 1
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                (user_id, "save", "budget", json.dumps({"year": year, "currency": currency, "department_id": department_id, "project_id": project_id, "accounts": saved}), utcnow()))
        return self.list_budgets(year, currency, department_id or None, project_id or None)

    def budget_for_period(self, currency, date_from, date_to, department_id=None, project_id=None):
        """Budget per account for a date range. Annual budgets are spread evenly over 12 months."""
        start = iso_date(date_from); end = iso_date(date_to); result = {}
        months = []; year, month = int(start[:4]), int(start[5:7])
        while (year, month) <= (int(end[:4]), int(end[5:7])):
            months.append((year, month)); month += 1
            if month > 12: year, month = year + 1, 1
        with self.connect() as db:
            for year, month in months:
                for row in db.execute("""SELECT account_code,month,amount FROM budgets WHERE year=? AND currency=? AND (month=? OR month=0)
                        AND department_id=? AND project_id=?""", (year, str(currency).upper(), month, department_id or 0, project_id or 0)):
                    value = Decimal(str(row["amount"])) / (12 if row["month"] == 0 else 1)
                    result[row["account_code"]] = result.get(row["account_code"], Decimal("0")) + value
        return result
