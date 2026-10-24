"""Responsive workbench: workers do I/O; only Tk's thread reads/writes widgets."""

from __future__ import annotations
import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import date, datetime
from decimal import Decimal
from client import ApiClient
from desktop_common import NAVY, GOLD, LIGHT, flow_toolbars
from i18n import tr

LOG = logging.getLogger("nanza.workbench")


def frozen_client(source):
    """A running worker must not follow a mutable selection into another company."""
    client = ApiClient(source.base_url)
    client.token, client.company_id, client.fiscal_year = source.token, source.company_id, source.fiscal_year
    return client


def context_key(app):
    c = getattr(app, "client", None)
    return (c.base_url, c.token, c.company_id, c.fiscal_year) if c is not None else None


def async_call(owner, app, work, done, status=None):
    """Bounded one-worker queue per widget, replacing obsolete pending requests."""
    owner._wb_generation = getattr(owner, "_wb_generation", 0) + 1
    generation = owner._wb_generation
    key = context_key(app)
    if not hasattr(owner, "_wb_jobs"):
        owner._wb_jobs = queue.Queue(maxsize=1)
        owner._wb_results = queue.Queue()

        def worker():
            while True:
                job = owner._wb_jobs.get()
                if job is None:
                    return
                seq, scope, client, task, callback = job
                try:
                    result = task(client)
                    owner._wb_results.put((seq, scope, callback, result, None))
                except (OSError, RuntimeError, ValueError, TypeError, KeyError, ArithmeticError) as exc:
                    LOG.warning("Workbench operation failed", exc_info=True)
                    owner._wb_results.put((seq, scope, callback, None, str(exc)))
                finally:
                    client.close()

        owner._wb_thread = threading.Thread(target=worker, name="NanzaWorkbench", daemon=True)
        owner._wb_thread.start()

        def cleanup(event):
            if event.widget is not owner:
                return
            timer = getattr(owner, "_wb_poll_id", None)
            if timer:
                owner.after_cancel(timer)
            try:
                stale_job = owner._wb_jobs.get_nowait()
                if stale_job is not None:
                    stale_job[2].close()
            except queue.Empty:
                pass
            try:
                owner._wb_jobs.put_nowait(None)
            except queue.Full:
                pass

        owner.bind("<Destroy>", cleanup, add="+")

        def poll():
            if not owner.winfo_exists():
                return
            while True:
                try:
                    seq, scope, callback, value, error = owner._wb_results.get_nowait()
                except queue.Empty:
                    break
                if seq != owner._wb_generation or context_key(app) != scope:
                    continue
                if error:
                    if status is not None:
                        status.configure(text=error, fg="#a32032")
                    else:
                        messagebox.showerror("NANZA", error, parent=owner)
                else:
                    callback(value)
            owner._wb_poll_id = owner.after(60, poll)

        owner._wb_poll_id = owner.after(60, poll)
    job = (generation, key, frozen_client(app.client), work, done)
    try:
        stale = owner._wb_jobs.get_nowait()
        if stale is not None:
            stale[2].close()
    except queue.Empty:
        pass
    owner._wb_jobs.put_nowait(job)


def tooltip(widget, text):
    state = {"window": None, "timer": None}

    def leave(_event=None):
        if state["timer"]:
            widget.after_cancel(state["timer"])
            state["timer"] = None
        if state["window"]:
            state["window"].destroy()
            state["window"] = None

    def show():
        state["timer"] = None
        w = tk.Toplevel(widget)
        w.overrideredirect(True)
        w.geometry(f"+{widget.winfo_rootx()+10}+{widget.winfo_rooty()+widget.winfo_height()+4}")
        tk.Label(w, text=text, bg=NAVY, fg="white", padx=10, pady=6).pack()
        state["window"] = w

    widget.bind("<Enter>", lambda _e: state.update(timer=widget.after(500, show)), add="+")
    widget.bind("<Leave>", leave, add="+")
    widget.bind("<Destroy>", leave, add="+")


def button(parent, text, command, hint=""):
    b = tk.Button(
        parent,
        text=text,
        command=command,
        bg=NAVY,
        fg="white",
        activebackground=GOLD,
        activeforeground=NAVY,
        relief="flat",
        padx=12,
        pady=7,
        cursor="hand2",
    )
    b.pack(side="left", padx=4, pady=4)
    if hint:
        tooltip(b, hint)
    return b


def table(parent, headers):
    frame = tk.Frame(parent, bg="white")
    frame.pack(fill="both", expand=True, padx=10, pady=8)
    tree = ttk.Treeview(frame, columns=list(range(len(headers))), show="headings", height=12)
    for i, h in enumerate(headers):
        tree.heading(i, text=h)
        tree.column(i, width=125, minwidth=75)
    y = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    x = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
    tree.grid(row=0, column=0, sticky="nsew")
    y.grid(row=0, column=1, sticky="ns")
    x.grid(row=1, column=0, sticky="ew")
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)

    def fit_columns(event):
        # Keep totals visible at laptop widths; horizontal scrolling remains for very narrow windows.
        width = max(60, (event.width - 20) // max(1, len(headers)))
        for column in tree["columns"]:
            tree.column(column, width=width, minwidth=60, stretch=True)

    frame.bind("<Configure>", fit_columns, add="+")
    return tree


def show_rows(tree, rows):
    tree.delete(*tree.get_children())
    for row in rows:
        tree.insert("", "end", values=[f"{v:,.2f}" if isinstance(v, Decimal) else v for v in row])


def write_export(path, title, headers, rows, extension, language):
    from report_export import export_sections_excel, export_sections_pdf

    if extension == "xlsx":
        rows = [
            [
                (
                    "'" + value
                    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                    else value
                )
                for value in row
            ]
            for row in rows
        ]
    sections = [
        {"heading": title, "headers": headers, "rows": rows, "total_rows": [], "report_language": language}
    ]
    writer = export_sections_excel if extension == "xlsx" else export_sections_pdf
    writer(path, title, [], sections)
    return path


def export_current(owner, title, headers, rows, extension="xlsx"):
    if not rows:
        return
    path = filedialog.asksaveasfilename(
        parent=owner, defaultextension="." + extension, filetypes=[(extension.upper(), "*." + extension)]
    )
    if not path:
        return
    app = getattr(owner, "app", None) or getattr(owner.master, "app", None)
    if app is None:
        raise RuntimeError("Export needs a selected application session")
    language = app.language.get()
    if language == "ar":
        import arabic_ui

        title = arabic_ui.translate(title)
        headers = [arabic_ui.translate(h) for h in headers]
    # Independent owner: changing filters does not cancel an explicitly requested export.
    job = tk.Frame(owner)
    owner._wb_export_done = False

    def completed(_result):
        owner._wb_export_done = True
        if hasattr(owner, "status"):
            owner.status.configure(text="Export saved / تم حفظ الملف", fg=NAVY)
        job.destroy()

    async_call(
        job,
        app,
        lambda _client: write_export(path, title, headers, rows, extension, language),
        completed,
        getattr(owner, "status", None),
    )


class WorkbenchWindow(tk.Toplevel):
    def __init__(self, app, title):
        super().__init__(app)
        self.app, self.scope = app, context_key(app)
        self.title(title)
        self.configure(bg=LIGHT)
        self.geometry("1120x680")
        self.minsize(780, 500)
        self.status = tk.Label(
            self,
            text="",
            bg=LIGHT,
            fg=NAVY,
            anchor="e" if app.language.get() == "ar" else "w",
            wraplength=1000,
        )
        self.status.pack(side="bottom", fill="x", padx=12, pady=8)
        self.bind("<Control-w>", lambda _e: app.open_whatsapp_summary())
        self._wb_scope_id = self.after(300, self.check_scope)

    def check_scope(self):
        if context_key(self.app) != self.scope:
            self.destroy()
            return
        self._wb_scope_id = self.after(300, self.check_scope)

    def destroy(self):
        for timer in (getattr(self, "_wb_scope_id", None), getattr(self, "pending", None)):
            if timer:
                self.after_cancel(timer)
        super().destroy()


class AgeingWindow(WorkbenchWindow):
    def __init__(self, app):
        super().__init__(app, "Ageing • أعمار الذمم")
        self.data = None
        self.visible = []
        self.drill = None
        controls = tk.Frame(self, bg=LIGHT)
        controls.pack(fill="x", padx=8)
        self.day = tk.StringVar(value=app.fiscal_today())
        ttk.Entry(controls, textvariable=self.day, width=12).pack(side="left", padx=4)
        self.kind = tk.StringVar(value="sale")
        self.currency = tk.StringVar(value="")
        ttk.Combobox(
            controls, textvariable=self.kind, values=["sale", "purchase"], state="readonly", width=10
        ).pack(side="left")
        self.kind.trace_add("write", lambda *_: self.load())
        button(
            controls,
            "Refresh / تحديث",
            self.load,
            "تحديث الذمم حسب تاريخ الاستحقاق والدفعات في التاريخ المختار",
        )
        button(controls, "Excel", self.export, "تصدير العرض الحالي إلى إكسل — Ctrl+E")
        self.bind("<Control-e>", lambda _e: self.export())
        chips = tk.Frame(self, bg=LIGHT)
        chips.pack(fill="x", padx=8)
        self.bucket = "All"
        from nanza_delivery.ageing_report import BUCKETS, COLORS

        for b in ("All", *BUCKETS):
            chip = tk.Button(
                chips,
                text=b,
                bg=COLORS.get(b, "white"),
                relief="flat",
                padx=18,
                pady=8,
                command=lambda value=b: self.filter(value),
            )
            chip.pack(side="left", padx=4, pady=4)
            tooltip(chip, "فلتر بنقرة واحدة؛ 90+ يعني أكثر من 90 يوماً")
        self.headers = ["Customer / Supplier", "Currency", *BUCKETS, "Credit", "Total", "Overdue"]
        self.tree = table(self, self.headers)
        for b, color in COLORS.items():
            self.tree.tag_configure(b, background=color)
        self.tree.bind("<Double-1>", self.open_invoices)
        self.load()

    def load(self):
        day, kind = self.day.get(), self.kind.get()
        self.status.configure(text="Loading / جارٍ التحميل…")
        async_call(
            self, self.app, lambda c: c.workbench("ageing", date=day, kind=kind), self.loaded, self.status
        )

    def loaded(self, result):
        self.data = result
        self.filter(self.bucket)

    def filter(self, bucket):
        self.bucket = bucket
        if self.data is None:
            return
        from nanza_delivery.ageing_report import BUCKETS

        self.visible = [
            r for r in self.data["parties"] if bucket == "All" or Decimal(str(r["buckets"][bucket])) > 0
        ]
        self.rows = [
            [
                r["party_name"],
                r["currency"],
                *(Decimal(str(r["buckets"][b])) for b in BUCKETS),
                Decimal(str(r["credit"])),
                Decimal(str(r["total"])),
                Decimal(str(r["overdue"])),
            ]
            for r in self.visible
        ]
        self.tree.delete(*self.tree.get_children())
        for index, (row, party) in enumerate(zip(self.rows, self.visible)):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=[f"{v:,.2f}" if isinstance(v, Decimal) else v for v in row],
                tags=(party["severity"],),
            )
        totals = "; ".join(f"{c}: {Decimal(str(r['overdue'])):,.2f}" for c, r in self.data["totals"].items())
        self.status.configure(
            text=f'Overdue / المتأخر: {totals or "0"} | Double-click to view invoices. 0-30 includes not due; credits separate.',
            fg=NAVY,
        )

    def export(self):
        export_current(self, "Ageing", self.headers, getattr(self, "rows", []))

    def open_invoices(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        party = self.visible[int(selection[0])]
        dialog = tk.Toplevel(self)
        dialog.title(party["party_name"])
        dialog.geometry("920x450")
        headers = ["Invoice", "Date", "Due", "Currency", "Outstanding", "Days", "Bucket"]
        rows = [
            [
                r["invoice_number"],
                r["invoice_date"],
                r.get("due_date") or "",
                r["currency"],
                Decimal(str(r["outstanding"])),
                r["days_overdue"],
                r["bucket"],
            ]
            for r in party["invoices"]
        ]
        actions = tk.Frame(dialog)
        actions.pack(fill="x")
        button(actions, "Excel", lambda: export_current(dialog, "Customer invoices", headers, rows))
        show_rows(table(dialog, headers), rows)


class CustomReportWindow(WorkbenchWindow):
    def __init__(self, app):
        super().__init__(app, tr(app.language.get(), "custom_reports_title"))
        self.pending = None
        self.page = 0
        self.result = None
        self.matches = {}
        self._applying = False
        self.vars = {
            k: tk.StringVar()
            for k in ("date_from", "date_to", "customer", "product", "warehouse", "currency")
        }
        today = app.fiscal_today()
        from desktop_common import parse_user_date

        day = parse_user_date(today).date()
        self.vars["date_from"].set(day.replace(day=1).isoformat())
        self.vars["date_to"].set(day.isoformat())
        self.filters_bar = tk.Frame(self, bg=LIGHT)
        self.filters_bar.pack(fill="x", padx=8, pady=6)
        self.cards = []
        self.boxes = {}
        self.dragging = None
        labels = {
            "date_from": "From / من",
            "date_to": "To / إلى",
            "customer": "Customer / العميل",
            "product": "Product / الصنف",
            "warehouse": "Warehouse / المستودع",
            "currency": "Currency / العملة",
        }
        for k, var in self.vars.items():
            card = tk.Frame(
                self.filters_bar,
                bg="white",
                padx=6,
                pady=5,
                highlightthickness=1,
                highlightbackground="#dce2eb",
            )
            card.grid(sticky="ew", padx=3, pady=3)
            grip = tk.Label(card, text="⋮⋮ " + labels[k], bg="white", fg=NAVY, cursor="fleur")
            grip.pack(anchor="w")
            grip.bind("<ButtonPress-1>", lambda _e, c=card: setattr(self, "dragging", c))
            grip.bind("<ButtonRelease-1>", self.drop_filter)
            tooltip(grip, "اسحب عنوان الفلتر لترتيبه؛ اكتب للبحث والقائمة تتحدّث تلقائياً")
            entry = (
                ttk.Entry(card, textvariable=var, width=12)
                if k.startswith("date_")
                else ttk.Combobox(card, textvariable=var, width=17)
            )
            entry.pack(fill="x")
            self.boxes[k] = entry
            self.cards.append(card)
            if not k.startswith("date_"):
                entry.bind("<KeyRelease>", lambda _e, field=k: self.search_choices(field))
            var.trace_add("write", self.changed)
        self.filters_bar.bind("<Configure>", self.arrange_filter_cards, add="+")
        self.arrange_filter_cards()
        self.ledger_controls()
        actions = tk.Frame(self, bg=LIGHT)
        actions.pack(fill="x", padx=8)
        button(actions, "Excel", lambda: self.export("xlsx"), "تصدير كل النتائج المطابقة — Ctrl+E")
        button(actions, "PDF", lambda: self.export("pdf"), "تصدير كل النتائج المطابقة إلى PDF")
        button(actions, "Save template / حفظ", self.save_template, "حفظ الفلاتر باسم لإعادة استخدامها")
        self.template = tk.StringVar()
        self.template_box = ttk.Combobox(actions, textvariable=self.template, state="readonly", width=24)
        self.template_box.pack(side="left", padx=4)
        self.template_box.bind("<<ComboboxSelected>>", self.apply_template)
        button(actions, "←", lambda: self.change_page(-1), "الصفحة السابقة")
        button(actions, "→", lambda: self.change_page(1), "الصفحة التالية")
        flow_toolbars(actions)
        from nanza_delivery.custom_report_builder import HEADERS

        self.tree = table(self, HEADERS)
        self.bind("<Control-e>", lambda _e: self.export("xlsx"))
        # Metadata owner is separate: preview requests must not cancel dropdown population.
        self.meta_owner = tk.Frame(self)
        async_call(
            self.meta_owner,
            app,
            lambda c: {
                "customers": c.parties(),
                "products": c.inventory_items(),
                "warehouses": c.warehouses(),
                "currencies": c.currencies(),
                "templates": c.workbench("templates")["items"],
            },
            self.metadata,
            self.status,
        )
        self.changed()

    def arrange_filter_cards(self, _event=None):
        """Lay filters out in readable columns while keeping their saved drag order."""
        width = self.filters_bar.winfo_width()
        columns = 3 if width >= 900 or width <= 1 else 2 if width >= 620 else 1
        for column in range(6):
            self.filters_bar.grid_columnconfigure(column, weight=0, uniform="")
        for column in range(columns):
            self.filters_bar.grid_columnconfigure(column, weight=1, uniform="custom_report_filters")
        for index, card in enumerate(self.cards):
            card.grid(row=index // columns, column=index % columns, sticky="ew", padx=3, pady=3)

    def ledger_controls(self):
        from nanza_delivery.custom_report_builder import LEDGER_DIMENSIONS, LEDGER_MEASURES
        panel = tk.Frame(self, bg=LIGHT)
        panel.pack(fill="x", padx=8)
        self.ledger_controls_panel = panel
        self.report_kind = tk.StringVar(value="sales")
        self.reporting_currencies = tk.StringVar(value="native")
        self.report_accounts = tk.StringVar()
        self._ledger_control_frames = []
        for label, variable, choices in (
            ("Layout / نوع التقرير", self.report_kind, ("sales", "pnl", "balance")),
            ("Currencies / العملات (USD,LBP)", self.reporting_currencies, None),
            ("9-digit accounts / الحسابات (comma separated)", self.report_accounts, None),
        ):
            frame = tk.Frame(panel, bg=LIGHT)
            frame.grid(sticky="nw", padx=4, pady=3)
            tk.Label(frame, text=label, bg=LIGHT).pack(anchor="w")
            widget = ttk.Combobox(frame, textvariable=variable, values=choices, state="readonly", width=12) if choices else ttk.Entry(frame, textvariable=variable, width=22)
            widget.pack(fill="x")
            variable.trace_add("write", self.changed)
            self._ledger_control_frames.append(frame)
        self.layout_boxes = {}
        for field, values, label in (
            ("group_by", LEDGER_DIMENSIONS, "Dimensions: select + drag / الأبعاد"),
            ("columns", LEDGER_MEASURES, "Columns: select + drag / الأعمدة"),
        ):
            frame = tk.Frame(panel, bg=LIGHT)
            frame.grid(sticky="nw", padx=4, pady=3)
            tk.Label(frame, text=label, bg=LIGHT).pack(anchor="w")
            box = tk.Listbox(frame, height=3, width=24, selectmode="extended", exportselection=False)
            box.insert("end", *values)
            box.selection_set(0 if field == "group_by" else len(values) - 1)
            box.pack()
            box.bind("<<ListboxSelect>>", self.changed)
            box.bind("<ButtonPress-1>", lambda e, b=box: setattr(b, "_drag_index", b.nearest(e.y)), add="+")
            box.bind("<ButtonRelease-1>", lambda e, b=box: self.drop_layout(e, b))
            self.layout_boxes[field] = box
            self._ledger_control_frames.append(frame)
        panel.bind("<Configure>", self.arrange_ledger_controls, add="+")
        self.arrange_ledger_controls()

    def arrange_ledger_controls(self, _event=None):
        """Keep report type, currency, account and layout selectors on screen."""
        width = self.ledger_controls_panel.winfo_width()
        columns = 3 if width >= 1000 or width <= 1 else 2 if width >= 650 else 1
        for column in range(5):
            self.ledger_controls_panel.grid_columnconfigure(column, weight=0, uniform="")
        for column in range(columns):
            self.ledger_controls_panel.grid_columnconfigure(column, weight=1, uniform="ledger_controls")
        for index, frame in enumerate(self._ledger_control_frames):
            frame.grid(row=index // columns, column=index % columns, sticky="nw", padx=4, pady=3)

    def drop_layout(self, event, box):
        source = getattr(box, "_drag_index", None)
        target = box.nearest(event.y)
        if source is None or source == target:
            return
        selected = {box.get(i) for i in box.curselection()}
        values = list(box.get(0, "end"))
        values.insert(target, values.pop(source))
        box.delete(0, "end")
        box.insert("end", *values)
        for i, value in enumerate(values):
            if value in selected:
                box.selection_set(i)
        self.changed()

    def report_rows(self, result):
        start = len(result["headers"]) - len(result["definition"]["columns"]) if result.get("definition") else 6
        return [[*row[:start], *(Decimal(str(v)) for v in row[start:])] for row in result["rows"]]

    def drop_filter(self, event):
        dragged = self.dragging
        target = self.winfo_containing(event.x_root, event.y_root)
        while target is not None and target not in self.cards:
            target = getattr(target, "master", None)
        if dragged is not None and target is not None and dragged is not target:
            self.cards.remove(dragged)
            self.cards.insert(self.cards.index(target), dragged)
            self.arrange_filter_cards()
        self.dragging = None

    def metadata(self, data):
        self.matches = {
            "customer": {
                f"{r['name']} · {r['id']}": str(r["id"])
                for r in data["customers"]
                if r.get("kind") in ("customer", "both")
            },
            "product": {f"{r['sku']} · {r['name']}": r["sku"] for r in data["products"]},
            "warehouse": {f"{r['code']} · {r['name']}": str(r["id"]) for r in data["warehouses"]},
            "currency": {r["code"]: r["code"] for r in data["currencies"]},
        }
        for field, choices in self.matches.items():
            self.boxes[field].configure(values=["", *choices])
        self.templates = {r["name"]: r["filters"] for r in data["templates"]}
        self.template_box.configure(values=list(self.templates))
        self.changed()

    def search_choices(self, field):
        text = self.vars[field].get().casefold()
        self.boxes[field].configure(
            values=["", *(label for label in self.matches.get(field, {}) if text in label.casefold())]
        )

    def filters(self):
        if self.report_kind.get() != "sales":
            import json
            from nanza_delivery.custom_report_builder import validate_definition
            dates = {k: self.vars[k].get().strip() for k in ("date_from", "date_to")}
            layout = {"version": 1, "kind": self.report_kind.get(), **dates,
                      "currencies": [c.strip() for c in self.reporting_currencies.get().split(",") if c.strip()],
                      "account_codes": [c.strip() for c in self.report_accounts.get().split(",") if c.strip()]}
            for field, box in self.layout_boxes.items():
                layout[field] = [box.get(i) for i in box.curselection()]
            layout = validate_definition(layout)
            return {**dates, "definition": json.dumps(layout, ensure_ascii=False)}
        filters = {}
        for k, var in self.vars.items():
            value = var.get().strip()
            if value and k in self.matches:
                if value not in self.matches[k]:
                    raise ValueError("Select a matching " + k + " / اختر قيمة من القائمة")
                value = self.matches[k][value]
            if value:
                filters[k] = value
        return filters

    def changed(self, *_):
        if self._applying:
            return
        self.page = 0
        self.result = None
        if self.pending:
            self.after_cancel(self.pending)
        # Invalidate the active request immediately, before debounce elapses.
        self._wb_generation = getattr(self, "_wb_generation", 0) + 1
        self.pending = self.after(350, self.refresh)

    def refresh(self):
        self.pending = None
        try:
            filters = self.filters()
            from nanza_delivery.custom_report_builder import validate_filters

            validate_filters(filters)
        except ValueError as exc:
            self.result = None
            self.tree.delete(*self.tree.get_children())
            self.status.configure(text=str(exc))
            return
        self.status.configure(text="Updating preview / تحديث المعاينة…")
        page = self.page
        async_call(
            self,
            self.app,
            lambda c: c.workbench("report", **filters, limit=500, offset=page * 500),
            self.loaded,
            self.status,
        )

    def loaded(self, result):
        self.result = result
        result["rows"] = self.report_rows(result)
        self.tree.configure(columns=list(range(len(result["headers"]))))
        for i, header in enumerate(result["headers"]):
            self.tree.heading(i, text=header)
            self.tree.column(i, width=125, minwidth=60)
        show_rows(self.tree, result["rows"])
        totals = "; ".join(f"{code}: {Decimal(str(value)):,.2f}" for code, value in result["totals"].items())
        self.status.configure(
            text=f"Page {self.page+1} • {len(result['rows'])} lines • {totals} • {result['note']}", fg=NAVY
        )

    def change_page(self, direction):
        if direction < 0 and self.page > 0 or direction > 0 and self.result and self.result["has_more"]:
            self.page += direction
            self.result = None
            self.refresh()

    def export(self, extension):
        self._wb_export_done = False
        if not self.result:
            return
        filters = dict(self.result["filters"])
        self.status.configure(text="Preparing complete export / تحضير التصدير الكامل…")

        def done(result):
            rows = self.report_rows(result)
            export_current(self, result["title"], result["headers"], rows, extension)
            self.status.configure(text=f"Complete export: {len(rows)} lines / تصدير كامل")

        async_call(self, self.app, lambda c: c.workbench("report-export", **filters), done, self.status)

    def save_template(self):
        try:
            filters = self.filters()
        except ValueError as exc:
            self.status.configure(text=str(exc))
            return
        name = simpledialog.askstring("Template", "Name / اسم التقرير", parent=self)
        if not name:
            return

        def saved(result):
            self.templates[result["name"]] = result["filters"]
            self.template_box.configure(values=list(self.templates))
            self.template.set(result["name"])
            self.status.configure(text="Template saved / تم الحفظ")

        async_call(
            self.meta_owner, self.app, lambda c: c.save_custom_report(name, filters), saved, self.status
        )

    def apply_template(self, _event=None):
        filters = getattr(self, "templates", {}).get(self.template.get(), {})
        self._applying = True
        import json
        layout = json.loads(filters["definition"]) if filters.get("definition") else None
        self.report_kind.set(layout["kind"] if layout else "sales")
        if layout:
            self.reporting_currencies.set(",".join(layout["currencies"]))
            self.report_accounts.set(",".join(layout.get("account_codes", [])))
            for field, box in self.layout_boxes.items():
                selected = layout[field]
                values = [*selected, *(v for v in box.get(0, "end") if v not in selected)]
                box.delete(0, "end")
                box.insert("end", *values)
                box.selection_set(0, len(selected) - 1)
        for k, var in self.vars.items():
            raw = str(filters.get(k, ""))
            var.set(next((label for label, value in self.matches.get(k, {}).items() if value == raw), raw))
        self._applying = False
        self.changed()


class WhatsAppWindow(WorkbenchWindow):
    def __init__(self, app):
        super().__init__(app, "WhatsApp summary • ملخّص واتساب")
        self.geometry("850x590")
        self.ready = False
        controls = tk.Frame(self, bg=LIGHT)
        controls.pack(fill="x", padx=8)
        self.day = tk.StringVar(value=app.fiscal_today())
        self.currency = tk.StringVar(value="USD")
        ttk.Entry(controls, textvariable=self.day, width=13).pack(side="left", padx=4)
        currency_box = ttk.Combobox(
            controls, textvariable=self.currency, values=["USD", "LBP", "EUR"], width=9
        )
        currency_box.pack(side="left")
        button(controls, "Preview / معاينة", self.load, "معاينة قبل النسخ؛ لا يتم إرسال أي بيانات تلقائياً")
        self.copy_button = button(
            controls, "Copy / نسخ", self.copy, "نسخ النص المعروض للمشاركة يدوياً — Ctrl+W"
        )
        self.copy_button.configure(state="disabled")
        self.text = tk.Text(self, wrap="word", font=("Segoe UI", 12), padx=18, pady=15, bg="white", fg=NAVY)
        self.text.pack(fill="both", expand=True, padx=12, pady=8)
        self.reminder = tk.BooleanVar(value=getattr(app, "_wb_reminder", False))
        bar = tk.Frame(self, bg=LIGHT)
        bar.pack(fill="x", padx=12)
        ttk.Checkbutton(
            bar,
            text="6pm local reminder / تذكير الساعة ٦ (البرنامج مفتوح)",
            variable=self.reminder,
            command=self.save_reminder,
        ).pack(anchor="w")
        auto = ttk.Checkbutton(
            bar,
            text="Auto-send at 6pm / إرسال تلقائي: requires a configured messaging gateway",
            state="disabled",
        )
        auto.pack(anchor="w")
        tooltip(auto, "الإرسال التلقائي غير مهيأ؛ النسخ والتذكير محليان ومجانيان")
        self.bind("<Control-w>", lambda _e: self.copy())
        self.day.trace_add("write", lambda *_: self.invalidate())
        self.currency.trace_add("write", lambda *_: self.invalidate())
        self.load()

    def invalidate(self):
        self.ready = False
        self.copy_button.configure(state="disabled")
        self._wb_generation = getattr(self, "_wb_generation", 0) + 1

    def load(self):
        day, currency, language = self.day.get(), self.currency.get(), self.app.language.get()
        self.invalidate()
        self.status.configure(text="Preparing local preview / تحضير المعاينة…")
        async_call(
            self,
            self.app,
            lambda c: c.workbench("summary", date=day, currency=currency, language=language),
            self.loaded,
            self.status,
        )

    def loaded(self, result):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", result["text"])
        self.text.configure(state="disabled")
        self.ready = True
        self.copy_button.configure(state="normal")
        self.status.configure(
            text="Review then copy. Nothing is sent automatically. / راجع النص ثم انسخه.", fg=NAVY
        )

    def copy(self):
        if self.ready:
            self.clipboard_clear()
            self.clipboard_append(self.text.get("1.0", "end-1c"))
            self.status.configure(text="Copied / تم النسخ")

    def save_reminder(self):
        enabled = self.reminder.get()
        last_day = getattr(self.app, "_wb_last_day", None)
        async_call(
            self,
            self.app,
            lambda c: c.save_workbench_preferences(enabled, last_day),
            self.preferences_saved,
            self.status,
        )

    def preferences_saved(self, result):
        self.app._wb_reminder = result["reminder_6pm"]
        self.status.configure(text="Reminder saved / تم حفظ التذكير")


class WorkbenchMixin:
    def build_workbench_tools(self, parent):
        panel = tk.Frame(parent, bg="white", highlightbackground="#dce2eb", highlightthickness=1)
        panel.pack(fill="x", padx=12, pady=8)
        language = self.language.get()
        tk.Label(panel, text=tr(language, "workbench_tools_title"), bg="white", fg="#5f6b76",
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=10, pady=(5, 0))
        actions = tk.Frame(panel, bg="white")
        actions.pack(fill="x", padx=8)
        button(
            actions,
            tr(language, "custom_reports_title"),
            self.open_custom_reports,
            tr(language, "custom_reports_hint"),
        )
        ai_button = button(actions, tr(language, "ai_accountant_title"), self.open_ai_accountant,
                           tr(language, "ai_accountant_hint"))
        ai_button.configure(bg=GOLD, fg=NAVY, activebackground="#e3c178", activeforeground=NAVY)
        button(
            actions, "Ageing / أعمار الذمم", self.open_ageing_workbench, "الذمم المتأخرة والتفاصيل بنقرتين"
        )
        button(
            actions,
            "Explain P&L / تفسير الربح",
            self.open_profit_explanation,
            "تفسير تغيّر الربح من الحسابات الفعلية",
        )
        button(
            actions, "Copy WhatsApp Summary", self.open_whatsapp_summary, "معاينة ونسخ ملخص اليوم — Ctrl+W"
        )
        self._wb_badge = tk.Label(
            actions, text="Overdue…", bg="#ffe1e5", fg="#a32032", padx=10, pady=7, cursor="hand2"
        )
        self._wb_badge.pack(side="right", padx=5)
        self._wb_badge.bind("<Button-1>", lambda _e: self.open_ageing_workbench())
        self._wb_canvas = tk.Canvas(panel, height=85, bg="white", highlightthickness=0)
        self._wb_canvas.pack(fill="x", padx=12, pady=4)
        self._wb_status = tk.Label(
            panel, text="30-day cash illustration / تقدير نقدي ٣٠ يوماً", bg="white", fg=NAVY, anchor="w"
        )
        self._wb_status.pack(fill="x", padx=12)
        self.bind("<Control-w>", lambda _e: self.open_whatsapp_summary())
        self.bind("<Control-W>", lambda _e: self.open_whatsapp_summary())
        self.bind("<Control-e>", self.export_workbench_shortcut)
        self._wb_canvas.bind(
            "<Configure>", lambda _e: self.draw_workbench_forecast(getattr(self, "_wb_forecast", {}))
        )
        flow_toolbars(actions)
        self.refresh_workbench()
        if not getattr(self, "_wb_clock_started", False):
            self._wb_clock_started = True
            self._wb_clock_id = self.after(60000, self.workbench_clock)
            self.bind("<Destroy>", self.cancel_workbench_clock, add="+")

    def export_workbench_shortcut(self, _event=None):
        self.open_custom_reports()

    def refresh_workbench(self):
        owner = getattr(self, "_wb_canvas", None)
        if owner is None or not owner.winfo_exists():
            return
        day = self.fiscal_today()
        currency = self.dashboard_base_currency.get()
        if currency == "All Currencies":
            currency = "USD"
        self._wb_canvas.delete("all")
        self._wb_forecast = {}
        self._wb_reminder = False
        self._wb_last_day = None
        self._wb_badge.configure(text="Overdue…")

        def work(c):
            return {
                "ageing": c.workbench("ageing", date=day, kind="sale"),
                "forecast": c.workbench("forecast", date=day, currency=currency),
                "preferences": c.workbench("preferences"),
            }

        async_call(owner, self, work, self.fill_workbench, self._wb_status)

    def fill_workbench(self, result):
        totals = result["ageing"]["totals"]
        self._wb_badge.configure(
            text="Overdue / متأخر: "
            + ("; ".join(f"{code} {Decimal(str(r['overdue'])):,.2f}" for code, r in totals.items()) or "0")
        )
        self._wb_forecast = result["forecast"]
        self.draw_workbench_forecast(self._wb_forecast)
        self._wb_reminder = result["preferences"]["reminder_6pm"]
        self._wb_last_day = result["preferences"]["last_day"]

    def draw_workbench_forecast(self, result):
        canvas = getattr(self, "_wb_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return
        canvas.delete("all")
        points = result.get("points", [])
        width = max(400, canvas.winfo_width())
        if not points:
            canvas.create_text(
                12, 32, anchor="w", text="Insufficient cash history / لا توجد حركة نقدية كافية", fill=NAVY
            )
            return
        values = [float(p["balance"]) for p in points]
        lower, upper = min(values), max(values)
        spread = upper - lower or max(1, abs(upper) * 0.1)
        coords = []
        for i, value in enumerate(values):
            coords.extend([12 + i * (width - 24) / 30, 65 - (value - lower) / spread * 45])
        canvas.create_line(*coords, fill="#187d67", width=3)
        canvas.create_text(12, 77, anchor="w", text=f"Today {values[0]:,.2f} {result['currency']}", fill=NAVY)
        canvas.create_text(
            width - 12, 77, anchor="e", text=f"Day 30 {values[-1]:,.2f} {result['currency']}", fill=NAVY
        )
        self._wb_status.configure(
            text=f"30-day illustration • {result['currency']} • {result['assumption']}", fg=NAVY
        )

    def workbench_clock(self):
        from nanza_delivery.whatsapp_daily_summary import reminder_due

        if getattr(self, "client", None) and reminder_due(
            datetime.now(), getattr(self, "_wb_reminder", False), getattr(self, "_wb_last_day", None)
        ):
            self._wb_last_day = date.today().isoformat()
            day = self._wb_last_day
            owner = getattr(self, "_wb_canvas", None)
            if owner is not None and owner.winfo_exists():
                async_call(
                    owner,
                    self,
                    lambda c: c.save_workbench_preferences(True, day),
                    lambda _r: self.open_whatsapp_summary(),
                    self._wb_status,
                )
        self._wb_clock_id = self.after(60000, self.workbench_clock)

    def cancel_workbench_clock(self, event):
        if event.widget is self and getattr(self, "_wb_clock_id", None):
            self.after_cancel(self._wb_clock_id)

    def open_profit_explanation(self):
        window = WorkbenchWindow(self, "Profit explanation / تفسير الربح")
        text = tk.Text(window, wrap="word", padx=15, pady=15, font=("Segoe UI", 12))
        text.pack(fill="both", expand=True, padx=12, pady=12)
        from desktop_common import parse_user_date

        end = parse_user_date(self.fiscal_today()).date()
        start = end.replace(day=1)
        currency = self.dashboard_base_currency.get()
        if currency == "All Currencies":
            currency = "USD"
        language = self.language.get()

        def done(result):
            text.insert("1.0", result["text"])
            text.configure(state="disabled")
            window.status.configure(text="Posted P&L only; preceding equal-length period / حسابات مرحّلة فقط")

        async_call(
            window,
            self,
            lambda c: c.workbench(
                "explain",
                date_from=start.isoformat(),
                date_to=end.isoformat(),
                currency=currency,
                language=language,
            ),
            done,
            window.status,
        )
        return window

    def open_board_dashboard(self):
        notebook = getattr(self, "main_notebook", None)
        if (
            getattr(self, "client", None) is None
            or not getattr(self, "current_user", None)
            or notebook is None
            or not notebook.winfo_exists()
        ):
            return None
        from nanza_delivery.complete_board_dashboard import open_board

        return open_board(self)

    def open_ageing_workbench(self):
        return AgeingWindow(self)

    def open_custom_reports(self):
        return CustomReportWindow(self)

    def open_ai_accountant(self):
        """Open Financial Reports directly on the AI Accountant page."""
        container = self.main_tab_container(self.reports_tab)
        if container not in getattr(self, "main_tab_pages", ()):
            return self.select_main_tab(self.reports_tab)
        self.select_main_tab(container)
        page = getattr(self, "ai_accountant_page", None)
        notebook = getattr(self, "financial_notebook", None)
        if page is not None and notebook is not None:
            self.after_idle(lambda: notebook.select(page) if notebook.winfo_exists() else None)

    def open_whatsapp_summary(self):
        return WhatsAppWindow(self)
