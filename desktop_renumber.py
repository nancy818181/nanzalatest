"""2.9.115: Settings > Renumber Documents (administrator).

Choose the documents (receipts, payments, journal vouchers, expenses, purchase or sales invoices) and the year, press
Preview to see every old -> new number in date order, then Renumber. The rules are in resequence.py: only the
program's own numbers change, locked / closed / VAT-filed periods keep theirs, a safety backup is made first and the
audit trail keeps every change."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from desktop_common import GOLD, LIGHT, NAVY

KINDS = (("customer_receipt", "Customer receipts (RV)"), ("supplier_payment", "Supplier payments (PV)"),
         ("journal_voucher", "Journal vouchers (JV)"), ("expense", "Expenses (EXP)"),
         ("purchase", "Purchase invoices (PUR)"), ("sale", "Sales invoices (SAL)"))


class RenumberMixin:
    def build_renumber_page(self, page):
        year = str(getattr(self, "current_fiscal_year", "") or "")
        self.renumber_kind = tk.StringVar(value=KINDS[0][1]); self.renumber_year = tk.StringVar(value=year)
        self.renumber_state = {"token": None, "kind": None, "year": None}
        intro = ("Puts the numbers back in date order after a document was entered with a wrong date. Only the program's own "
                 "numbers change (RV-2026-000012); numbers typed by hand or imported are kept. Documents in locked books, a closed "
                 "year or a quarter whose VAT return is saved keep their numbers. A safety backup is made first and the Audit Trail "
                 "keeps every old -> new number.")
        tk.Label(page, text=intro, bg=LIGHT, fg="#5f6b76", justify="left", wraplength=980, anchor="w").pack(fill="x", padx=12, pady=(10, 4))
        bar = tk.Frame(page, bg=LIGHT); bar.pack(fill="x", padx=10, pady=4)
        tk.Label(bar, text="Documents", bg=LIGHT).pack(side="left")
        ttk.Combobox(bar, textvariable=self.renumber_kind, values=[label for _k, label in KINDS], state="readonly", width=26).pack(side="left", padx=(4, 10))
        tk.Label(bar, text="Year", bg=LIGHT).pack(side="left")
        tk.Entry(bar, textvariable=self.renumber_year, width=7).pack(side="left", padx=(4, 10))
        tk.Button(bar, text="Preview", command=self.preview_renumbering, bg=NAVY, fg="white", border=0, padx=14, pady=5).pack(side="left", padx=4)
        self.renumber_button = tk.Button(bar, text="Renumber", command=self.apply_renumbering, bg=GOLD, fg=NAVY, border=0, padx=14, pady=5, state="disabled")
        self.renumber_button.pack(side="left", padx=4)
        self.renumber_summary = tk.Label(page, text="Choose the documents and the year, then press Preview.", bg=LIGHT, fg=NAVY,
                                         font=("Segoe UI", 9, "bold"), anchor="w", justify="left", wraplength=980)
        self.renumber_summary.pack(fill="x", padx=12, pady=(4, 0))
        self.renumber_tree = self.table(page, [("date", "Date", 110), ("old", "Current Number", 170), ("arrow", "", 40),
                                               ("new", "New Number", 170), ("status", "Status", 360)])
        self.renumber_tree.tag_configure("change", foreground=NAVY, font=("Segoe UI", 10, "bold"))
        self.renumber_tree.tag_configure("kept", foreground="#7A8794")

    def _renumber_kind(self):
        return next((key for key, label in KINDS if label == self.renumber_kind.get()), KINDS[0][0])

    def preview_renumbering(self):
        try: result = self.client.renumber_preview(self._renumber_kind(), self.renumber_year.get())
        except (RuntimeError, ValueError, OSError) as exc:  # the data service's answer (refused, offline)
            self.renumber_button.configure(state="disabled"); return messagebox.showerror("Renumber Documents", str(exc))
        tree = self.renumber_tree; tree.delete(*tree.get_children())
        for row in result["rows"]:
            day = row["date"]; shown = f"{day[8:10]}-{day[5:7]}-{day[:4]}" if len(day) == 10 else day
            if row["kept"]: status, tag = f"Kept ({row['frozen']})" if row.get("frozen") else "Kept (before a locked document)", "kept"
            elif row["change"]: status, tag = "Will change", "change"
            else: status, tag = "Already in order", ""
            tree.insert("", "end", values=(shown, row["old"], "→" if row["change"] else "", row["new"], status), tags=(tag,) if tag else ())
        self.renumber_state = {"token": result["token"], "kind": result["kind"], "year": result["year"], "changes": result["changes"],
                               "warning": result.get("warning", "")}
        if not result["rows"]: text = f"No {result['label'].lower()} with the program's numbers in {result['year']}."
        elif not result["changes"]: text = f"{result['label']} {result['year']}: every number already follows the dates. Nothing to change."
        else:
            text = f"{result['label']} {result['year']}: {result['changes']} number(s) will change"
            if result["kept"]: text += f"; {result['kept']} kept ({result.get('kept_reason') or 'locked'})"
            text += ". Press Renumber to apply."
        if result.get("warning"): text += "\n" + result["warning"]
        self.renumber_summary.configure(text=text)
        self.renumber_button.configure(state="normal" if result["changes"] else "disabled")

    def apply_renumbering(self):
        state = self.renumber_state
        if not state.get("token") or not state.get("changes"): return
        question = (f"Renumber {state['changes']} document(s)? A safety backup is made first and the Audit Trail keeps every "
                    "old and new number.")
        if state.get("warning"): question += "\n\n" + state["warning"]
        if not messagebox.askyesno("Renumber Documents", question): return
        try: result = self.client.renumber(state["kind"], state["year"], state["token"])
        except (RuntimeError, ValueError, OSError) as exc:  # the data service's answer (refused, offline)
            return messagebox.showerror("Renumber Documents", str(exc))
        messagebox.showinfo("Renumber Documents", f"{result.get('renumbered', 0)} document(s) renumbered.")
        self.preview_renumbering()
