"""2.9.120: Settings > Accounting Settings - the posting rules the program learned, and the optional Azure reader (own free key).
Also the "Read with Azure" buttons of Purchases and Expenses (shown only on a computer where Azure is set up)."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

NAVY, GOLD, LIGHT = "#102A43", "#B78B45", "#F4F7FA"
RED, MUTED = "#8B1E1E", "#5f6b76"
FILE_TYPES = [("Invoice PDF or photo", "*.pdf *.jpg *.jpeg *.png *.tif *.tiff *.bmp")]
SCOPE_NAMES = {"purchase": "Purchases", "expense": "Expenses"}


class LearningMixin:
    # ------------------------------------------------------------ Settings boxes
    def build_learning_boxes(self, page):
        rules = tk.LabelFrame(page, text="Posting rules (learned from your invoices)", bg=LIGHT, padx=8, pady=6); rules.pack(fill="x", padx=8, pady=6)
        tk.Label(rules, text="Each supplier's next invoice is filled the way you posted its last one (account, VAT, department, how it was paid). "
                 "Only a suggestion: you check it before Save.", bg=LIGHT, fg=MUTED, wraplength=760, justify="left").pack(side="left")
        tk.Button(rules, text="Show Posting Rules", command=self.show_posting_rules, bg=NAVY, fg="white", border=0, padx=14, pady=6).pack(side="left", padx=8)
        azure = tk.LabelFrame(page, text="Read invoices with Azure (optional, your own free key)", bg=LIGHT, padx=8, pady=6); azure.pack(fill="x", padx=8, pady=6)
        tk.Label(azure, text="For handwritten or hard-to-read invoices: Microsoft Azure Document Intelligence, free tier F0 = 500 pages a month. "
                 "Without it the free local reading is used, as before.", bg=LIGHT, fg=MUTED, wraplength=760, justify="left").pack(side="left")
        tk.Button(azure, text="Azure Settings", command=self.azure_settings_window, bg=NAVY, fg="white", border=0, padx=14, pady=6).pack(side="left", padx=8)
        advanced = tk.LabelFrame(page, text="Advanced Local OCR (Arabic and English)", bg=LIGHT, padx=8, pady=6)
        advanced.pack(fill="x", padx=8, pady=6)
        tk.Label(advanced, text="An extra neural reader for difficult photos. One-time download; invoices stay on this computer. "
                 "Slower than normal OCR; handwriting still needs review before Save.", bg=LIGHT, fg=MUTED, wraplength=760, justify="left").pack(anchor="w")
        advanced_controls=tk.Frame(advanced,bg=LIGHT);advanced_controls.pack(fill="x",pady=(6,0))
        import neural_reader
        self.neural_reader_enabled=tk.BooleanVar(value=neural_reader.ready())
        def toggle_neural():
            try:neural_reader.set_enabled(self.neural_reader_enabled.get())
            except neural_reader.NeuralReaderError as exc:
                self.neural_reader_enabled.set(False)
                messagebox.showwarning("Advanced Local OCR",str(exc))
        tk.Checkbutton(advanced_controls,text="Use advanced reader for photos / scans",variable=self.neural_reader_enabled,
                       command=toggle_neural,bg=LIGHT).pack(side="left",padx=6)
        tk.Button(advanced_controls, text="Install / Repair Advanced Reader", command=self.install_neural_reader,
                  bg=NAVY, fg="white", border=0, padx=14, pady=6).pack(side="left", padx=8)

    def install_neural_reader(self):
        import neural_reader
        from desktop_stage3_common import run_with_progress
        def installed(note):
            if hasattr(self,"neural_reader_enabled"):self.neural_reader_enabled.set(True)
            messagebox.showinfo("Advanced Local OCR",note)
        return run_with_progress(self, "Advanced Local OCR setup", neural_reader.install,installed)


    # ------------------------------------------------------------ 2.9.121: many PDFs at once (Uploaded Data)
    def import_row_rule(self, row, data):
        """Fill an Uploaded Data row read from a PDF the way its supplier was posted before (type, cost / asset account, VAT
        account). Returns the note ('' when nothing was learned for this supplier)."""
        import posting_rules
        name = data.get("supplier_hint") or data.get("party_name") or ""
        if not name: return ""
        try: found = self.client.posting_suggestion("purchase", name, data.get("party_tax_number") or posting_rules.numbers_in(data.get("text") or ""),
                                                    data.get("text") or "", [i.get("description") or "" for i in data.get("items") or []])
        except (RuntimeError, OSError, ValueError, AttributeError): return ""
        rule = (found or {}).get("rule") if isinstance(found, dict) else None
        if not rule: return ""
        learned = rule["data"]
        row["entry_type"] = "Assets" if learned.get("entry_type") == "assets" else "Purchases"
        for key in ("expense_account", "vat_account"):
            if learned.get(key): row[key] = learned[key]
        if not row.get("party_name"): row["party_name"] = rule.get("label") or name
        return f"Posted like {rule.get('last_reference') or 'the last invoice'} of {rule['label']} (learned from {rule['times']} invoice(s))"

    # ------------------------------------------------------------ the rules learned
    def show_posting_rules(self):
        try: rows = self.client.posting_rules()
        except (RuntimeError, OSError, ValueError) as exc: return messagebox.showerror("Posting Rules", str(exc))
        window = tk.Toplevel(self); window.title("Posting Rules"); window.configure(bg=LIGHT); window.geometry("1080x480")
        tk.Label(window, text="What the program learned from the invoices you saved. Delete a rule to stop it (it is learned again from the next invoice saved).",
                 bg=LIGHT, fg=MUTED).pack(anchor="w", padx=10, pady=(8, 2))
        columns = ("Screen", "Supplier", "Found by", "Account", "VAT A/C", "Paid from", "Times", "Last")
        tree = ttk.Treeview(window, columns=columns, show="headings", height=16)
        for column, width in zip(columns, (80, 220, 150, 110, 100, 100, 60, 160)):
            tree.heading(column, text=column); tree.column(column, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=10, pady=4)
        for row in rows:
            data = row.get("data") or {}
            found_by = "MOF " + row["key"][4:] if str(row["key"]).startswith("mof:") else "name"
            tree.insert("", "end", iid=str(row["id"]), values=(SCOPE_NAMES.get(row["scope"], row["scope"]), row.get("label") or "", found_by,
                        data.get("expense_account") or "", data.get("vat_account") or "", data.get("payment_account") or "",
                        row.get("times") or 1, f"{row.get('last_reference') or ''} {row.get('last_date') or ''}".strip()))

        def delete():
            chosen = tree.selection()
            if not chosen: return messagebox.showinfo("Posting Rules", "Select the rule(s) to delete", parent=window)
            if not messagebox.askyesno("Posting Rules", f"Delete {len(chosen)} rule(s)? Invoices already saved are not changed.", parent=window): return
            for iid in chosen:
                try: self.client.delete_posting_rule(int(iid)); tree.delete(iid)
                except (RuntimeError, OSError, ValueError) as exc: return messagebox.showerror("Posting Rules", str(exc), parent=window)
        bar = tk.Frame(window, bg=LIGHT); bar.pack(fill="x", padx=10, pady=(0, 8))
        tk.Button(bar, text="Delete", command=delete, bg=RED, fg="white", border=0, padx=14, pady=6).pack(side="left")
        tk.Label(bar, text=f"{len(rows)} rule(s)", bg=LIGHT, fg=MUTED).pack(side="left", padx=10)

    # ------------------------------------------------------------ Azure settings (this computer only)
    def azure_settings_window(self):
        import azure_reader
        state = azure_reader.status()
        window = tk.Toplevel(self); window.title("Read invoices with Azure"); window.configure(bg=LIGHT); window.resizable(False, False)
        steps = ("1. portal.azure.com > Create a resource > Document Intelligence (Form Recognizer).\n"
                 "2. Pricing tier: Free F0 (500 pages a month, no charge). Choose the region closest to you.\n"
                 "3. Keys and Endpoint: copy the Endpoint and KEY 1 here.")
        tk.Label(window, text=steps, bg=LIGHT, justify="left").grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 6))
        endpoint, key, limit = tk.StringVar(value=state["endpoint"]), tk.StringVar(), tk.StringVar(value=str(state["limit"]))
        for row, (label, variable, extra) in enumerate((("Endpoint", endpoint, {}), ("Key", key, {"show": "•"}), ("Pages a month (limit)", limit, {})), 1):
            tk.Label(window, text=label, bg=LIGHT).grid(row=row, column=0, sticky="w", padx=10, pady=3)
            tk.Entry(window, textvariable=variable, width=60 if row < 3 else 8, **extra).grid(row=row, column=1, sticky="w", padx=4, pady=3)
        if state["ready"]: tk.Label(window, text="(a key is kept: leave empty to keep it)", bg=LIGHT, fg=MUTED).grid(row=2, column=2, sticky="w")
        tk.Label(window, text=f"Used this month: {state['used']} of {state['limit']} pages", bg=LIGHT, fg=NAVY,
                 font=("Segoe UI", 9, "bold")).grid(row=4, column=0, columnspan=3, sticky="w", padx=10, pady=(6, 2))
        tk.Label(window, text=azure_reader.PRIVACY, bg=LIGHT, fg=MUTED, wraplength=620, justify="left").grid(row=5, column=0, columnspan=3, sticky="w", padx=10)

        def save():
            typed = key.get().strip() or (azure_reader.load().get("key") if state["ready"] else "")
            try: azure_reader.save(endpoint.get(), typed, limit.get())
            except (ValueError, OSError) as exc: return messagebox.showerror("Azure", str(exc), parent=window)
            self.refresh_azure_buttons(); window.destroy()
            messagebox.showinfo("Azure", "Saved on this computer. 'Read with Azure' is on the Purchases and Expenses screens." if typed else "Azure is off.")

        def remove():
            try: azure_reader.save("", "", limit.get() or azure_reader.FREE_PAGES)
            except (ValueError, OSError) as exc: return messagebox.showerror("Azure", str(exc), parent=window)
            self.refresh_azure_buttons(); window.destroy(); messagebox.showinfo("Azure", "The key is removed from this computer. Azure is off.")
        bar = tk.Frame(window, bg=LIGHT); bar.grid(row=6, column=0, columnspan=3, sticky="w", padx=10, pady=10)
        tk.Button(bar, text="Save", command=save, bg=GOLD, fg=NAVY, border=0, padx=18, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        tk.Button(bar, text="Remove Key", command=remove, bg=RED, fg="white", border=0, padx=12, pady=6).pack(side="left")

    # ------------------------------------------------------------ the buttons
    def azure_button(self, parent, command, after):
        """'Read with Azure', shown after <after> only when Azure is set up on this computer."""
        button = self.action_button(parent, "Read with Azure", command)
        buttons = self.__dict__.setdefault("_azure_buttons", [])
        buttons.append((button, after)); self.refresh_azure_buttons()
        return button

    def refresh_azure_buttons(self):
        import azure_reader
        try: on = azure_reader.ready()
        except (OSError, ValueError): on = False
        for button, after in self.__dict__.get("_azure_buttons", []):
            try:
                if on and not button.winfo_manager(): button.pack(side="left", padx=3, after=after)
                elif not on and button.winfo_manager(): button.pack_forget()
            except tk.TclError: continue

    def read_with_azure(self, path, done):
        """Read <path> with Azure off the screen's thread, then done(data). Azure failing: the free local reading is used."""
        import azure_reader
        import pdf_import

        def work(_key):
            try: return azure_reader.read_invoice(path)
            except azure_reader.AzureReaderError as exc:
                data = pdf_import.read_invoice_pdf(path)
                data["notes"] = f"Azure: {exc} - free local reading used; {data.get('notes') or ''}".strip("; ")
                data.setdefault("review_warnings", []).append("Azure reading unavailable; check the free local reading against the original")
                return data
        self.run_ai_task(work, done)

    def azure_read_purchase(self):
        path = filedialog.askopenfilename(filetypes=FILE_TYPES)
        if path: self.ai_read_purchase_pdf(path=path, reader=lambda done: self.read_with_azure(path, done))

    def azure_read_expense(self):
        path = filedialog.askopenfilename(filetypes=FILE_TYPES)
        if not path: return
        f = self.expense_form
        if f["id"]: return messagebox.showinfo("Read with Azure", "Press New first: the reading fills a new expense.")
        f["pdf_label"].config(text=f"Reading {Path(path).name} with Azure...", fg=NAVY)
        self.read_with_azure(path, lambda data: self.fill_expense_from_reading(path, data))
