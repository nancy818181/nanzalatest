"""Chart of Accounts tools (2.9.66): delete the selected accounts, find and delete accounts without transactions,
move an account's transactions to another account, or transfer its balance."""
from __future__ import annotations
import logging

from desktop_common import (  # 2.9.102: the names this module uses (no more 'import *')
    enable_drag_select, GOLD, LIGHT, messagebox, NAVY, selection_totals, tk, ttk
)

SCOPE_LABELS = {"All accounts": "all", "Clients (411)": "clients", "Suppliers (401 / 403 / 404 / 408)": "suppliers", "Expenses (class 6)": "expenses",
                "Income (class 7)": "income", "Cash & banks (class 5)": "cash_bank", "Other payables (46)": "other_payables"}


class AccountToolsMixin:
    def account_tool_buttons(self, parent):
        tk.Button(parent, text="Delete Selected", command=self.delete_selected_accounts, bg="#8B1E1E", fg="white", border=0, padx=10, pady=6).pack(side="left", padx=4)
        self.action_button(parent, "Delete Unused Accounts...", self.unused_accounts_dialog).pack(side="left", padx=4)
        self.action_button(parent, "Move / Transfer...", self.move_account_dialog).pack(side="left", padx=4)

    def selected_account_codes(self):
        return [str(self.accounts_tree.item(iid, "values")[0]) for iid in self.accounts_tree.selection()]

    def _after_account_change(self):
        self._account_cache = None; self.__dict__.pop("_all_accounts", None)
        try: self.client.clear_cache()
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
        self.load_accounts()
        for loader in ("load_parties", "load_trial"):
            try: getattr(self, loader)()
            except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105

    def _delete_account_codes(self, codes, title="Delete Accounts"):
        if not codes: return messagebox.showwarning(title, "Select the accounts first (Ctrl / Shift or drag the mouse for several)")
        shown = "\n".join(codes[:15]) + (f"\n... and {len(codes) - 15} more" if len(codes) > 15 else "")
        if not messagebox.askyesno(title, f"Delete {len(codes)} account(s)?\n\n{shown}\n\nOnly accounts without any transaction are deleted; "
                                   "a customer / supplier file that only holds that account is deleted with it."): return None
        try: result = self.client.delete_accounts(codes)
        except Exception as exc: return messagebox.showerror(title, str(exc))
        self._after_account_change()
        lines = [f'Deleted: {len(result["deleted"])}']
        lines += [f'  {d["code"]} {d["name"]}' + (f' (and {", ".join(d["parties"])})' if d["parties"] else "") for d in result["deleted"][:12]]
        if result["kept"]:
            lines += ["", f'Kept: {len(result["kept"])}'] + [f'  {k["code"]}: {k["reason"]}' for k in result["kept"][:12]]
        messagebox.showinfo(title, "\n".join(lines))
        return result

    def delete_selected_accounts(self):
        return self._delete_account_codes(self.selected_account_codes())

    def unused_accounts_dialog(self):
        window = tk.Toplevel(self); window.title("Accounts without transactions"); window.configure(bg=LIGHT); window.transient(self); self.fit_dialog(window, 820, 520)
        scope = tk.StringVar(value="All accounts")
        bar = tk.Frame(window, bg=LIGHT); bar.pack(fill="x", padx=10, pady=8)
        tk.Label(bar, text="Show", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
        box = ttk.Combobox(bar, textvariable=scope, values=list(SCOPE_LABELS), state="readonly", width=32); box.pack(side="left", padx=6)
        info = tk.Label(window, text="", bg=LIGHT, fg=NAVY, anchor="w"); info.pack(fill="x", padx=12)
        frame = tk.Frame(window, bg=LIGHT); frame.pack(fill="both", expand=True, padx=10, pady=6)
        tree = ttk.Treeview(frame, columns=("code", "name", "type", "party"), show="headings", selectmode="extended")
        for key, label, width in (("code", "Account", 110), ("name", "Name", 330), ("type", "Type", 90), ("party", "Customer / Supplier", 220)):
            tree.heading(key, text=label); tree.column(key, width=width)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview); tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y"); enable_drag_select(tree)
        def load(_e=None):
            try: rows = self.client.unused_accounts(SCOPE_LABELS[scope.get()])
            except Exception as exc: return messagebox.showerror("Accounts", str(exc), parent=window)
            tree.delete(*tree.get_children())
            for r in rows: tree.insert("", "end", iid=r["code"], values=(r["code"], r["name"], r["type"], r.get("party") or ""))
            info.config(text=f"{len(rows)} account(s) without any transaction, sub-account or document (official chart accounts are never listed).")
        def delete(selected_only=True):
            codes = list(tree.selection()) if selected_only else list(tree.get_children())
            if self._delete_account_codes(codes, "Accounts without transactions"): load()
        box.bind("<<ComboboxSelected>>", load)
        buttons = tk.Frame(window, bg=LIGHT); buttons.pack(fill="x", padx=10, pady=8)
        tk.Button(buttons, text="Delete Selected", command=delete, bg="#8B1E1E", fg="white", border=0, padx=12, pady=6).pack(side="left")
        tk.Button(buttons, text="Delete All Listed", command=lambda: delete(False), bg="#6B1010", fg="white", border=0, padx=12, pady=6).pack(side="left", padx=6)
        tk.Button(buttons, text="Select All", command=lambda: tree.selection_set(tree.get_children()), bg=NAVY, fg="white", border=0, padx=12, pady=6).pack(side="left", padx=6)
        tk.Button(buttons, text="Close", command=window.destroy, bg=NAVY, fg="white", border=0, padx=12, pady=6).pack(side="right")
        load(); return window

    def move_account_dialog(self):
        """2.9.67: move the CHOSEN transactions of an account to another one (replacement on the same entries), move all of
        them, or transfer the balance with a voucher."""
        selected = self.selected_account_codes()
        window = tk.Toplevel(self); window.title("Move / Transfer between accounts"); window.configure(bg=LIGHT); window.transient(self); self.fit_dialog(window, 1060, 680, 900, 560)
        year = getattr(self, "current_fiscal_year", "")
        v = {"from": tk.StringVar(value=selected[0] if selected else ""), "to": tk.StringVar(), "mode": tk.StringVar(value="lines"), "merge": tk.BooleanVar(value=True),
             "date": tk.StringVar(value=self.fiscal_today()), "description": tk.StringVar(), "date_from": tk.StringVar(value=f"01-01-{year}" if year else ""),
             "date_to": tk.StringVar(value=f"31-12-{year}" if year else "")}
        grid = tk.Frame(window, bg=LIGHT); grid.pack(fill="x", padx=14, pady=(10, 4))
        for row, (label, key) in enumerate((("From account", "from"), ("To account", "to"))):
            tk.Label(grid, text=label, bg=LIGHT, font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky="w", pady=3)
            self.account_search_box(grid, v[key], 44).grid(row=row, column=1, sticky="w", padx=6, pady=3)
        modes = tk.LabelFrame(window, text="What to do", bg=LIGHT, padx=8, pady=4); modes.pack(fill="x", padx=14, pady=4)
        tk.Radiobutton(modes, text="Move the CHOSEN transactions below to the To account (the same entries, the account is replaced - no new voucher)",
                       variable=v["mode"], value="lines", bg=LIGHT).pack(anchor="w")
        tk.Radiobutton(modes, text="Move ALL its transactions to the To account", variable=v["mode"], value="move", bg=LIGHT).pack(anchor="w")
        tk.Checkbutton(modes, text="   both accounts are customers / suppliers: the documents moved go to the customer / supplier of the To account (Move ALL: merge them)",
                       variable=v["merge"], bg=LIGHT).pack(anchor="w")
        balance = tk.Frame(modes, bg=LIGHT); balance.pack(anchor="w", fill="x")
        tk.Radiobutton(balance, text="Transfer only its BALANCE on", variable=v["mode"], value="balance", bg=LIGHT).pack(side="left")
        self.date_entry(balance, v["date"], 11).pack(side="left", padx=4)
        tk.Label(balance, text="with a journal voucher (history stays). Details", bg=LIGHT).pack(side="left")
        tk.Entry(balance, textvariable=v["description"], width=22).pack(side="left", padx=4)
        lines_box = tk.LabelFrame(window, text="Transactions of the From account - choose with Ctrl / Shift or drag the mouse", bg=LIGHT, padx=6, pady=4)
        lines_box.pack(fill="both", expand=True, padx=14, pady=4)
        bar = tk.Frame(lines_box, bg=LIGHT); bar.pack(fill="x")
        tk.Label(bar, text="From", bg=LIGHT).pack(side="left"); self.date_entry(bar, v["date_from"], 11).pack(side="left", padx=(4, 8))
        tk.Label(bar, text="To", bg=LIGHT).pack(side="left"); self.date_entry(bar, v["date_to"], 11).pack(side="left", padx=(4, 8))
        self.action_button(bar, "Show Transactions", lambda: load()).pack(side="left", padx=4)
        tk.Button(bar, text="Select All", command=lambda: tree.selection_set(tree.get_children()), bg=NAVY, fg="white", border=0, padx=10, pady=4).pack(side="left", padx=4)
        totals = tk.Label(bar, text="", bg=LIGHT, fg=NAVY, font=("Segoe UI", 9, "bold")); totals.pack(side="left", padx=10)
        frame = tk.Frame(lines_box, bg=LIGHT); frame.pack(fill="both", expand=True, pady=4)
        columns = [("date", "Date", 90), ("entry", "Entry", 120), ("description", "Description", 300), ("party", "Customer / Supplier", 170),
                   ("currency", "Currency", 70), ("debit", "Debit", 100), ("credit", "Credit", 100)]
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="extended", height=10)
        for key, label, width in columns: tree.heading(key, text=label); tree.column(key, width=width, anchor="e" if key in ("debit", "credit") else "w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview); tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        enable_drag_select(tree); selection_totals(tree, columns, totals)
        def code(key): return v[key].get().split(" - ", 1)[0].strip()
        def load():
            if not code("from"): return messagebox.showwarning("Move / Transfer", "Choose the From account", parent=window)
            try: rows = self.client.account_lines(code("from"), v["date_from"].get().strip(), v["date_to"].get().strip())
            except Exception as exc: return messagebox.showerror("Move / Transfer", str(exc), parent=window)
            tree.delete(*tree.get_children())
            for r in rows:
                text = r["description"] + (f' - {r["line_description"]}' if r["line_description"] and r["line_description"] != r["description"] else "")
                tree.insert("", "end", iid=str(r["id"]), values=(r["entry_date"], r["entry_number"], text, r["party_name"], r["currency"],
                                                                f'{r["debit"]:,.2f}' if r["debit"] else "", f'{r["credit"]:,.2f}' if r["credit"] else ""))
            lines_box.config(text=f"{len(rows)} transaction(s) of {code('from')} - choose with Ctrl / Shift or drag the mouse")
        def run():
            source, target = code("from"), code("to")
            if not source or not target: return messagebox.showwarning("Move / Transfer", "Choose both accounts", parent=window)
            try:
                if v["mode"].get() == "lines":
                    chosen = list(tree.selection())
                    if not chosen: return messagebox.showwarning("Move / Transfer", "Show the transactions and choose the ones to move", parent=window)
                    if not messagebox.askyesno("Move / Transfer", f"Book {len(chosen)} transaction(s) of {source} on {target} instead?", parent=window): return
                    result = self.client.move_account_lines(source, target, chosen, bool(v["merge"].get()))
                    text = (f'{result["lines"]} transaction(s) moved from {source} to {target}; {result["documents"]} document(s) now name {target}.' +
                            (f'\nCustomer / supplier changed: {result["party_changed"]}.' if result.get("party_changed") else ""))
                elif v["mode"].get() == "move":
                    if not messagebox.askyesno("Move / Transfer", f"Move EVERY transaction of {source} to {target}?\nA backup is advised first.", parent=window): return
                    result = self.client.move_account(source, target, bool(v["merge"].get()))
                    text = (f'{result["lines"]} journal line(s) and {result["documents"]} document field(s) moved from {source} to {target}.' +
                            (f'\n{result["merged_party"]} merged into the customer / supplier of {target}.' if result.get("merged_party") else "") +
                            f"\n\n{source} has no transactions now: delete it with Delete Selected if you no longer need it.")
                else:
                    result = self.client.transfer_account_balance(source, target, v["date"].get(), v["description"].get())
                    text = "\n".join(f'{x["voucher"]}: {abs(x["amount"]):,.2f} {x["currency"]} from {source} to {target}' for x in result["vouchers"])
            except Exception as exc: return messagebox.showerror("Move / Transfer", str(exc), parent=window)
            self._after_account_change()
            try: self.load_journal()
            except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
            messagebox.showinfo("Move / Transfer", text, parent=window)
            if v["mode"].get() == "lines": load()
            else: window.destroy()
        buttons = tk.Frame(window, bg=LIGHT); buttons.pack(fill="x", padx=14, pady=8)
        tk.Button(buttons, text="Run", command=run, bg=GOLD, fg=NAVY, border=0, padx=22, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Button(buttons, text="Close", command=window.destroy, bg=NAVY, fg="white", border=0, padx=14, pady=6).pack(side="left", padx=6)
        window._load_lines = load; window._tree = tree; window._vars = v; window._run = run
        if v["from"].get(): window.after(50, load)
        return window
