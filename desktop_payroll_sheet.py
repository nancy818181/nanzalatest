"""Monthly payroll sheet (2.9.44): every employee of the month in one table, like the monthly movement sheet
of the declaration workbooks. Calculate, save and post all of them at once; export to Excel."""
from __future__ import annotations

import logging

from desktop_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, export_excel, filedialog, GOLD, json, LIGHT, messagebox, NAVY, tk
)
import payroll_lines as PL

log = logging.getLogger("saber.payroll_sheet")
RED = "#8B1E1E"

BASE_COLUMNS = (("salary", "Salary | الراتب"), ("overtime", "Overtime"), ("commission", "Commission"), ("bonus", "Bonus"),
                ("thirteenth_month", "13th"), ("transport", "Transport | نقل"), ("transport_days", "Days | أيام"))
RESULT_COLUMNS = (("gross_salary", "Gross | المجموع"), ("income_tax", "Tax | الضريبة"), ("employee_nssf", "Emp. NSSF"),
                  ("family_allowance", "Family alloc."), ("net_salary", "Net | الصافي"), ("status", "Status"))
INPUT_KEYS = tuple(k for k, _ in BASE_COLUMNS) + PL.ALLOWANCE_CODES


def month_bounds(text):
    """'03-2026' or '2026-03' -> ('2026-03-01', '2026-03-31')."""
    import calendar
    text = str(text or "").strip().replace("/", "-")
    parts = text.split("-")
    if len(parts) != 2: raise ValueError("Enter the month as MM-YYYY, for example 03-2026")
    month, year = (int(parts[0]), int(parts[1])) if len(parts[0]) <= 2 else (int(parts[1]), int(parts[0]))
    if not 1 <= month <= 12: raise ValueError("Month must be between 01 and 12")
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def _iso(value):
    text = str(value or "")
    return f"{text[6:10]}-{text[3:5]}-{text[:2]}" if len(text) == 10 and text[2] == "-" else text[:10]


def sheet_rows(employees, records, start, end):
    """One row per employee working in the month: the saved payroll when there is one, else the register defaults."""
    saved = {int(r["employee_id"]): r for r in records if str(r.get("period_date") or "")[:7] == start[:7]}
    rows = []
    for e in employees:
        hire, leave = _iso(e.get("hire_date")), _iso(e.get("leave_date"))
        if hire and hire > end: continue
        if leave and leave < start: continue
        if not int(e.get("active", 1) or 0) and not saved.get(int(e["id"])): continue
        row = {"employee_id": int(e["id"]), "number": e["employee_number"], "name": e["full_name"], "currency": e.get("currency") or "LBP"}
        record = saved.get(int(e["id"]))
        if record:
            try: allowances = json.loads(record.get("allowances") or "{}")
            except (TypeError, ValueError): allowances = {}
            for key, _ in BASE_COLUMNS: row[key] = _fmt(record.get(key))
            for code in PL.ALLOWANCE_CODES: row[code] = _fmt(allowances.get(code))
            for key, _ in RESULT_COLUMNS: row[key] = _fmt(record.get(key)) if key != "status" else record.get("status") or "draft"
            row["payroll_id"] = record.get("id"); row["payroll_number"] = record.get("payroll_number")
        else:
            row["salary"] = _fmt(e.get("base_salary"))
            for key in ("overtime", "commission", "bonus", "thirteenth_month", "transport", "transport_days"): row[key] = ""
            for code in PL.ALLOWANCE_CODES: row[code] = _fmt(e.get(code)) if code in PL.EMPLOYEE_DEFAULTS else ""
            for key, _ in RESULT_COLUMNS: row[key] = "" if key != "status" else "new"
        rows.append(row)
    return rows


def _fmt(value):
    try: number = float(str(value or 0).replace(",", ""))
    except ValueError: return str(value)
    if not number: return ""
    return f"{number:,.0f}" if number == int(number) else f"{number:,.2f}"


def payload_for(row, period_end):
    payload = {"employee_id": row["employee_id"], "period_date": period_end, "allowances": {}}
    for key, _ in BASE_COLUMNS:
        value = str(row.get(key) or "").replace(",", "").strip()
        if key == "transport_days":
            if value: payload[key] = value
        else: payload[key] = value or "0"
    for code in PL.ALLOWANCE_CODES:
        value = str(row.get(code) or "").replace(",", "").strip()
        if value: payload["allowances"][code] = value
    return payload


class PayrollSheetMixin:
    def open_payroll_sheet(self):
        window = tk.Toplevel(self); window.title("Monthly payroll sheet | الحركة الشهرية"); window.configure(bg=LIGHT)
        self.fit_dialog(window, 1280, 700, 700, 420)
        controls = tk.Frame(window, bg=LIGHT); controls.pack(fill="x", padx=10, pady=8)
        month = tk.StringVar(value=datetime.now().strftime("%m-%Y"))
        tk.Label(controls, text="Month (MM-YYYY)", bg=LIGHT).pack(side="left", padx=4)
        tk.Entry(controls, textvariable=month, width=9).pack(side="left", padx=4)
        info = tk.Label(window, text="", bg=LIGHT, fg=NAVY, anchor="w", justify="left", wraplength=1200); info.pack(fill="x", padx=12)
        columns = [("line", "#", 40, "center"), ("number", "Reg. No.", 95, "w"), ("name", "Name | الإسم", 180, "w")]
        columns += [(k, label, 95 if k != "transport_days" else 55, "e") for k, label in BASE_COLUMNS]
        columns += [(code, PL.ALLOWANCES[code][4] + f" ({PL.ALLOWANCES[code][0]})", 120, "e") for code in PL.ALLOWANCE_CODES]
        columns += [(k, label, 105 if k != "status" else 70, "e" if k != "status" else "center") for k, label in RESULT_COLUMNS]
        editable = [k for k, _ in BASE_COLUMNS] + list(PL.ALLOWANCE_CODES)
        state = {"start": None, "end": None}

        def changed(iid, key, text):
            row = sheet.rows[iid]
            if row.get("status") == "posted":
                messagebox.showwarning("Payroll sheet", "This payroll is posted and cannot be changed.", parent=window); return False
            row[key] = text.strip()
            if row.get("status") != "new": row["status"] = "changed"
            for k, _ in RESULT_COLUMNS[:-1]: row[k] = ""
            return True

        sheet = EditableSheetLazy(self, window, columns, editable, changed, height=18)

        def load():
            try:
                start, end = month_bounds(month.get())
                rows = sheet_rows(self.client.employees(), self.client.payroll(start, end), start, end)
            except Exception as exc: return messagebox.showerror("Payroll sheet", str(exc), parent=window)
            state["start"], state["end"] = start, end
            sheet.clear()
            for row in rows: sheet.insert(row)
            info.config(text=f"{len(rows)} employee(s) in {month.get()}. Double-click a cell to type. Allowances: enter each amount in the taxable "
                             f"or the not-taxable column; the R6 line is shown in brackets. Posted rows are locked.", fg=NAVY)

        def run(action):
            if not state["end"]: return
            done = errors = 0; messages = []
            for iid, row in list(sheet.rows.items()):
                if row.get("status") == "posted": continue
                try:
                    if action == "post":
                        if row.get("status") != "draft" or not row.get("payroll_id"): continue
                        result = self.client.post_payroll(int(row["payroll_id"])); row["status"] = "posted"
                    else:
                        payload = payload_for(row, state["end"])
                        result = self.client.calculate_payroll(payload) if action == "calculate" else self.client.save_payroll(payload)
                        for key, _ in RESULT_COLUMNS[:-1]: row[key] = _fmt(result.get(key))
                        if action == "save": row["status"] = "draft"; row["payroll_id"] = result.get("id"); row["payroll_number"] = result.get("payroll_number")
                    done += 1
                except Exception as exc:
                    errors += 1; messages.append(f"{row['number']} {row['name']}: {exc}"); row["status"] = "error"
                    log.warning("Payroll sheet %s failed for %s", action, row["number"], exc_info=True)
                sheet.refresh(iid)
            text = f"{action.title()}: {done} done" + (f", {errors} error(s):\n" + "\n".join(messages[:8]) if errors else ".")
            info.config(text=text, fg=RED if errors else NAVY)
            if action in ("save", "post"):
                try: self.load_payroll()
                except Exception: log.debug("Payroll list not refreshed", exc_info=True)

        def post_all():
            drafts = sum(1 for r in sheet.rows.values() if r.get("status") == "draft")
            if not drafts: return messagebox.showinfo("Payroll sheet", "Save the sheet first; only saved (draft) payrolls are posted.", parent=window)
            if messagebox.askyesno("Payroll sheet", f"Post {drafts} payroll(s) to the General Journal? Posted payroll cannot be edited.", parent=window): run("post")

        def export():
            if not sheet.rows: return
            path = filedialog.asksaveasfilename(parent=window, defaultextension=".xlsx", initialfile=f"Payroll_{month.get()}.xlsx", filetypes=[("Excel", "*.xlsx")])
            if not path: return
            headers = [label for _k, label, _w, _a in columns[1:]]
            rows = [[row.get(k, "") for k, _l, _w, _a in columns[1:]] for row in sheet.ordered()]
            try: export_excel(path, f"Payroll sheet {month.get()}", headers, rows)
            except Exception as exc: return messagebox.showerror("Payroll sheet", str(exc), parent=window)
            messagebox.showinfo("Payroll sheet", f"Saved: {path}", parent=window)

        for text, command in (("Load", load), ("Calculate All", lambda: run("calculate")), ("Save All (draft)", lambda: run("save"))):
            self.action_button(controls, text, command).pack(side="left", padx=4)
        tk.Button(controls, text="Post All", command=post_all, bg=GOLD, fg=NAVY, border=0, padx=14, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=4)
        self.action_button(controls, "Export Excel", export).pack(side="left", padx=4)
        load()
        return window


def EditableSheetLazy(*args, **kwargs):
    from desktop_brains import EditableSheet
    return EditableSheet(*args, **kwargs)
