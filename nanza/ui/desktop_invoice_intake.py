"""Editable item review and company-aware annotations for the existing intake view."""

from decimal import Decimal
import tkinter as tk
from tkinter import ttk, messagebox


def annotate(app, data):
    from invoice_intake import enrich

    accounts = []
    parties = []
    documents = []
    try:
        accounts = app.client.accounts()
        parties = app.client.parties()
    except (RuntimeError, OSError, ValueError, TypeError):
        import logging

        logging.getLogger("saber.intake").warning(
            "Company chart or supplier lookup unavailable; suggestions withheld", exc_info=True
        )
    result = enrich(data, accounts, parties, documents)
    if result.get("direction") == "purchase" and callable(getattr(app.client, "purchase_intake", None)):
        try:
            remote = app.client.purchase_intake(result)
            if isinstance(remote, dict):
                result = remote
        except (RuntimeError, OSError, ValueError, TypeError):
            result["review_warnings"].append("Server account suggestions unavailable; choose missing accounts manually")
    if result.get("invoice_number") and hasattr(app.client, "invoice_duplicates"):
        try:
            found = app.client.invoice_duplicates(
                [
                    {
                        "kind": "sale" if result.get("suggested_type") == "Sales" else "purchase",
                        "party_name": result.get("party_name"),
                        "invoice_number": result.get("invoice_number"),
                        "doc_subtype": "credit_note" if result.get("document_type") == "credit_note" else "invoice",
                    }
                ]
            )[0]
            result["duplicate_candidates"] = found
            if found:
                result["review_warnings"].append("Possible existing invoice: verify duplicate before saving")
        except (RuntimeError, OSError, ValueError, TypeError, IndexError):
            result["review_warnings"].append("Duplicate lookup unavailable; verify before saving")
    result["_review_accounts"] = accounts
    return result


def review_items(parent, data):
    window = tk.Toplevel(parent)
    window.title("Review invoice lines")
    window.transient(parent)
    window.geometry("980x500")
    tk.Label(
        window,
        text="Edit the transcribed lines. Account/VAT suggestions are advisory; select final posting accounts in the entry screen.",
        wraplength=930,
    ).pack(fill="x", padx=10, pady=8)
    items = data.setdefault("items", [])
    tree = ttk.Treeview(
        window,
        columns=("description", "qty", "price", "total", "origin", "account", "confidence", "reason"),
        show="headings",
    )
    for key, label, width in (
        ("description", "Description", 240),
        ("qty", "Qty", 65),
        ("price", "Unit price", 90),
        ("total", "Total", 90),
        ("origin", "Reading / confidence", 150),
        ("account", "Suggested account", 110),
        ("confidence", "Match score", 85),
        ("reason", "Reason / VAT review", 270),
    ):
        tree.heading(key, text=label)
        tree.column(key, width=width, stretch=key in ("description", "reason"))
    scroll = ttk.Scrollbar(window, orient="horizontal", command=tree.xview)
    tree.configure(xscrollcommand=scroll.set)
    tree.pack(fill="both", expand=True, padx=10)
    scroll.pack(fill="x", padx=10)

    def refresh():
        tree.delete(*tree.get_children())
        for n, item in enumerate(items):
            suggestion = item.get("account_suggestion") or {}
            score = suggestion.get("confidence")
            tree.insert(
                "",
                "end",
                iid=str(n),
                values=(
                    item.get("description") or "",
                    item.get("quantity"),
                    item.get("unit_price"),
                    item.get("total"),
                    "User corrected" if item.get("reviewed") else "Unverified / unknown",
                    suggestion.get("account_code") or "Choose manually",
                    f"{score:.0%} heuristic" if score is not None else "Unknown",
                    (suggestion.get("reason") or "Choose account manually") + "; VAT: accountant review required (confidence unknown)",
                ),
            )

    def edit(new=False):
        selected = tree.selection()
        if not selected and not new:
            return
        index = len(items) if new else int(selected[0])
        item = {} if new else items[index]
        editor = tk.Toplevel(window)
        editor.title("Edit transcribed item")
        editor.transient(window)
        variables = {}
        for row, (key, label) in enumerate(
            (
                ("description", "Description"),
                ("quantity", "Quantity"),
                ("unit_price", "Unit price"),
                ("total", "Written total"),
            )
        ):
            tk.Label(editor, text=label).grid(row=row, column=0, padx=8, pady=6, sticky="w")
            variables[key] = tk.StringVar(value="" if item.get(key) is None else str(item[key]))
            tk.Entry(editor, textvariable=variables[key], width=45).grid(row=row, column=1, padx=8, pady=6)
            origin = "User corrected" if item.get("reviewed") else "Unverified"
            tk.Label(editor, text=origin + " / confidence unknown").grid(row=row, column=2, padx=8, sticky="w")

        def save():
            from invoice_intake import number, category_for, chart_suggestion

            updated = dict(item)
            updated["description"] = variables["description"].get().strip()
            if not updated["description"]:
                return messagebox.showwarning("Item", "Enter the description", parent=editor)
            for key in ("quantity", "unit_price", "total"):
                value = number(variables[key].get().strip())
                if value is None or value < 0 or (key == "quantity" and value == 0):
                    return messagebox.showwarning("Item", f"Enter a valid {key}", parent=editor)
                updated[key] = float(value)
            # Keep discrepancies visible; no mathematical repair.
            updated["reviewed"] = True
            updated["classification"] = category_for(updated["description"])
            updated["account_suggestion"] = chart_suggestion(
                updated["description"], data.get("_review_accounts", []), updated["classification"]["category"]
            )
            if new:
                items.append(updated)
            else:
                items[index] = updated
            refresh()
            editor.destroy()

        tk.Button(editor, text="Use corrected line", command=save).grid(row=4, column=0, columnspan=2, pady=10)

    def remove():
        selected = tree.selection()
        if selected:
            items.pop(int(selected[0]))
            refresh()

    bar = tk.Frame(window)
    bar.pack(fill="x", padx=10, pady=8)
    tk.Button(bar, text="Edit selected", command=edit).pack(side="left")
    tk.Button(bar, text="Add line", command=lambda: edit(True)).pack(side="left", padx=5)
    tk.Button(bar, text="Remove selected", command=remove).pack(side="left", padx=5)
    tk.Button(bar, text="Done", command=window.destroy).pack(side="right")
    tree.bind("<Double-1>", lambda _event: edit())
    refresh()
    window.grab_set()
    parent.wait_window(window)
    if parent.winfo_exists():
        parent.grab_set()


def validate_reviewed_items(data):
    from invoice_intake import number

    for index, item in enumerate(data.get("items") or [], 1):
        if not str(item.get("description") or "").strip():
            raise ValueError(f"Item {index}: enter a description or remove the unreadable row")
        for key in ("quantity", "unit_price", "total"):
            value = number(item.get(key))
            if value is None or value < 0 or (key == "quantity" and value == 0):
                raise ValueError(f"Item {index}: verify {key} in Review invoice lines, or remove the unreadable row")
    return data
