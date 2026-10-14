"""2.9.116: New company setup wizard (as in Zoho): four short steps instead of one long form.

1. Company - name and contact details
2. Country and chart of accounts - Lebanon, IFRS, Saudi Arabia or UAE (sets the currencies and VAT below)
3. Currencies and VAT - the two main currencies, the VAT rate and the two VAT return currencies
4. Fiscal year and summary - the first year, then Create

It sends exactly what the old form sent, plus the chosen chart; a company created without a choice keeps the
Lebanese chart as before."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import chart_templates
from desktop_common import GOLD, LIGHT, NAVY

CURRENCIES = ["USD", "LBP", "EUR", "AED", "SAR", "QAR", "KWD", "BHD", "OMR", "GBP", "CHF", "CAD", "JOD", "EGP", "TRY"]
STEPS = ("Company", "Country & Chart", "Currencies & VAT", "Fiscal Year")


class SetupWizardMixin:
    def create_company_dialog(self):
        window = tk.Toplevel(self); window.title("New Company"); window.configure(bg=LIGHT); window.transient(self); window.grab_set()
        window.geometry("640x520"); window.minsize(600, 480)
        v = {key: tk.StringVar(value="") for key in ("name", "address", "phone", "mof_number", "email", "website")}
        v["year"] = tk.StringVar(value=str(datetime.now().year))
        first = chart_templates.TEMPLATES[chart_templates.DEFAULT]
        v["chart"] = tk.StringVar(value=first["label"])
        v["main1"], v["main2"] = tk.StringVar(value=first["currencies"][0]), tk.StringVar(value=first["currencies"][1])
        v["vat_rate"] = tk.StringVar(value=first["vat_rate"])
        v["vat1"], v["vat2"] = tk.StringVar(value=first["vat_currencies"][0]), tk.StringVar(value=first["vat_currencies"][1])
        state = {"step": 0}

        header = tk.Frame(window, bg=NAVY); header.pack(fill="x")
        tk.Label(header, text="New Company", bg=NAVY, fg="white", font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(12, 2))
        progress = tk.Frame(header, bg=NAVY); progress.pack(fill="x", padx=18, pady=(0, 12))
        marks = []
        for index, title in enumerate(STEPS):
            mark = tk.Label(progress, text=f"{index + 1}  {title}", bg=NAVY, fg="#9FB3C8", font=("Segoe UI", 9, "bold"))
            mark.pack(side="left", padx=(0, 16)); marks.append(mark)
        body = tk.Frame(window, bg=LIGHT); body.pack(fill="both", expand=True, padx=22, pady=14)
        footer = tk.Frame(window, bg=LIGHT); footer.pack(fill="x", padx=22, pady=(0, 16))
        back = tk.Button(footer, text="Back", bg="white", fg=NAVY, border=0, padx=16, pady=6)
        forward = tk.Button(footer, text="Next", bg=GOLD, fg=NAVY, border=0, padx=18, pady=6, font=("Segoe UI", 9, "bold"))
        forward.pack(side="right"); back.pack(side="right", padx=8)

        def row(parent, r, label, widget, hint=""):
            tk.Label(parent, text=label, bg=LIGHT, anchor="w").grid(row=r, column=0, sticky="w", pady=6, padx=(0, 12))
            widget.grid(row=r, column=1, sticky="w", pady=6)
            if hint: tk.Label(parent, text=hint, bg=LIGHT, fg="#6B7A89", font=("Segoe UI", 8)).grid(row=r, column=2, sticky="w", padx=8)

        def chart_chosen(_event=None):
            spec = chart_templates.TEMPLATES[chart_templates.template_key(v["chart"].get())]
            v["main1"].set(spec["currencies"][0]); v["main2"].set(spec["currencies"][1]); v["vat_rate"].set(spec["vat_rate"])
            v["vat1"].set(spec["vat_currencies"][0]); v["vat2"].set(spec["vat_currencies"][1])

        def page(step):
            for child in body.winfo_children(): child.destroy()
            for index, mark in enumerate(marks): mark.configure(fg=GOLD if index == step else ("white" if index < step else "#9FB3C8"))
            grid = tk.Frame(body, bg=LIGHT); grid.pack(fill="both", expand=True, anchor="nw")
            if step == 0:
                tk.Label(grid, text="Who is the company?", bg=LIGHT, fg=NAVY, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
                for r, (key, label) in enumerate((("name", "Company Name *"), ("address", "Address"), ("phone", "Phone"),
                                                  ("mof_number", "Tax / VAT Number"), ("email", "Email"), ("website", "Website")), 1):
                    entry = tk.Entry(grid, textvariable=v[key], width=40); row(grid, r, label, entry)
                    if key == "name": entry.focus_set()
            elif step == 1:
                tk.Label(grid, text="Where does it work, and which chart of accounts?", bg=LIGHT, fg=NAVY, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
                for r, (key, label) in enumerate(chart_templates.choices(), 1):
                    tk.Radiobutton(grid, text=label, value=label, variable=v["chart"], command=chart_chosen, bg=LIGHT, anchor="w",
                                   activebackground=LIGHT, selectcolor="white").grid(row=r, column=0, columnspan=3, sticky="w", pady=3)
                tk.Label(grid, text=("Every chart keeps the same classes (1 equity ... 7 income), so the VAT return, the ledgers, the financial statements "
                                     "and payroll work with all of them. You can add accounts later, one by one or from Excel "
                                     "(Accounts & Statements > Chart of Accounts). The chart cannot be changed once the company is created."),
                         bg=LIGHT, fg="#6B7A89", justify="left", wraplength=560).grid(row=9, column=0, columnspan=3, sticky="w", pady=(12, 0))
            elif step == 2:
                tk.Label(grid, text="Currencies and VAT (filled from the country - change them if needed)", bg=LIGHT, fg=NAVY, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
                row(grid, 1, "Main Currency 1 (base)", ttk.Combobox(grid, textvariable=v["main1"], values=CURRENCIES, width=10))
                row(grid, 2, "Main Currency 2", ttk.Combobox(grid, textvariable=v["main2"], values=CURRENCIES, width=10))
                row(grid, 3, "VAT Rate %", tk.Entry(grid, textvariable=v["vat_rate"], width=8), "0 when the company does not charge VAT")
                pair = tk.Frame(grid, bg=LIGHT)
                ttk.Combobox(pair, textvariable=v["vat1"], values=CURRENCIES, width=8).pack(side="left")
                ttk.Combobox(pair, textvariable=v["vat2"], values=CURRENCIES, width=8).pack(side="left", padx=(6, 0))
                row(grid, 4, "VAT Return Currencies", pair)
            else:
                tk.Label(grid, text="First fiscal year, then create", bg=LIGHT, fg=NAVY, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
                row(grid, 1, "Opening Fiscal Year", tk.Entry(grid, textvariable=v["year"], width=8))
                summary = (f"Company:  {v['name'].get().strip() or '-'}\nChart:  {v['chart'].get()}\n"
                           f"Currencies:  {v['main1'].get()} + {v['main2'].get()}\nVAT:  {v['vat_rate'].get()}%  (return in {v['vat1'].get()} / {v['vat2'].get()})")
                tk.Label(grid, text=summary, bg="white", fg=NAVY, justify="left", anchor="w", padx=14, pady=12, highlightthickness=1,
                         highlightbackground="#DDE4EC").grid(row=2, column=0, columnspan=3, sticky="we", pady=(14, 0))
            back.configure(state="normal" if step else "disabled", command=lambda: go(-1))
            from desktop_theme import polish
            polish(window)  # every step gets the same inputs and buttons as the rest of the program
            forward.configure(text="Create Company" if step == len(STEPS) - 1 else "Next", command=lambda: go(1))

        def check(step):
            if step == 0 and not v["name"].get().strip(): return "Enter the company name"
            if step == 2:
                if v["main1"].get().strip().upper() == v["main2"].get().strip().upper(): return "Choose two different main currencies"
                if v["vat1"].get().strip().upper() == v["vat2"].get().strip().upper(): return "Choose two different VAT return currencies"
            return ""

        def go(direction):
            if direction > 0:
                problem = check(state["step"])
                if problem: return messagebox.showwarning("New Company", problem, parent=window)
                if state["step"] == len(STEPS) - 1: return create()
            state["step"] = max(0, min(len(STEPS) - 1, state["step"] + direction)); page(state["step"])

        def create():
            payload = {key: v[key].get().strip() for key in ("name", "year", "address", "phone", "mof_number", "email", "website")}
            payload.update(main_currency_1=v["main1"].get().strip().upper(), main_currency_2=v["main2"].get().strip().upper(),
                           vat_rate=v["vat_rate"].get().strip(), vat_currency_1=v["vat1"].get().strip().upper(), vat_currency_2=v["vat2"].get().strip().upper(),
                           chart_template=chart_templates.template_key(v["chart"].get()))
            try: self.client.create_company(payload)
            except (RuntimeError, ValueError, OSError) as exc: return messagebox.showerror("New Company", str(exc), parent=window)
            window.destroy(); self.company_selection_screen()

        window.bind("<Return>", lambda _e: go(1)); window.bind("<Escape>", lambda _e: window.destroy())
        page(0)
        return window
