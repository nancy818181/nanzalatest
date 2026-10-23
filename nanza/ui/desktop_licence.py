"""2.9.103: the licence screens.

- licence_box: Settings > Users (administrator) - Installation ID, licence state, paste a new code.
- enter_code_dialog: on the sign-in screen when the licence or the trial has ended.
- make_licence_dialog / change_key_password_dialog: the seller's side, used only on the seller's computer with the
  seller key file (saber_seller.key) and its password. Without that file these windows can do nothing."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

NAVY, GOLD, LIGHT, MUTED, RED = "#102A43", "#B78B45", "#F4F7FA", "#5f6b76", "#8B1E1E"
FONT = "Segoe UI"


def _show(day):
    return f"{day[8:10]}-{day[5:7]}-{day[:4]}" if day and len(day) == 10 else (day or "")


def describe(state):
    if not state: return ""
    if state.get("expired"): return "ENDED on " + _show(state.get("valid_until"))
    what = f"Trial until {_show(state['valid_until'])}" if state.get("trial") else f"Licensed to {state.get('company')} until {_show(state['valid_until'])}"
    return f"{what} ({state.get('days')} day(s) left)"


def _button(parent, text, command, gold=False):
    return tk.Button(parent, text=text, command=command, bg=GOLD if gold else NAVY, fg=NAVY if gold else "white", border=0,
                     padx=14, pady=6, font=(FONT, 9, "bold"), cursor="hand2", activebackground=GOLD)


def _copy(widget, text):
    widget.clipboard_clear(); widget.clipboard_append(text)


def licence_box(app, parent):
    box = tk.LabelFrame(parent, text="Licence of this installation | ترخيص البرنامج", bg=LIGHT, fg=NAVY, font=(FONT, 10, "bold"), padx=8, pady=6)
    box.pack(fill="x", padx=10, pady=8)
    ident, state_text, code = tk.StringVar(), tk.StringVar(), tk.StringVar()
    def refresh(state=None):
        try: state = state or app.client.licence()
        except Exception as exc: state_text.set(str(exc)); return
        ident.set(state.get("installation_id", "")); state_text.set(describe(state))
        label.configure(fg=RED if state.get("expired") or (state.get("days") or 99) <= 30 else NAVY)
    tk.Label(box, text="Installation ID", bg=LIGHT).grid(row=0, column=0, sticky="w")
    tk.Entry(box, textvariable=ident, width=22, state="readonly", font=(FONT, 10, "bold")).grid(row=0, column=1, sticky="w", padx=6)
    _button(box, "Copy", lambda: _copy(box, ident.get())).grid(row=0, column=2, padx=3)
    label = tk.Label(box, textvariable=state_text, bg=LIGHT, font=(FONT, 10, "bold")); label.grid(row=0, column=3, columnspan=3, sticky="w", padx=12)
    tk.Label(box, text="New licence code", bg=LIGHT).grid(row=1, column=0, sticky="w", pady=(8, 0))
    tk.Entry(box, textvariable=code, width=60).grid(row=1, column=1, columnspan=3, sticky="we", padx=6, pady=(8, 0))
    def apply():
        try: refresh(app.client.install_licence(code.get()))
        except Exception as exc: return messagebox.showerror("Licence", str(exc))
        code.set(""); messagebox.showinfo("Licence", "Licence saved: " + state_text.get())
    _button(box, "Apply Code", apply, gold=True).grid(row=1, column=4, padx=3, pady=(8, 0))
    _button(box, "Make a licence (seller)...", lambda: make_licence_dialog(app, ident.get())).grid(row=1, column=5, padx=3, pady=(8, 0))
    tk.Label(box, text="Send the Installation ID to Saber for Audit to receive a licence code, then paste it here and press Apply Code.",
             bg=LIGHT, fg=MUTED).grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))
    refresh()
    return box


def enter_code_dialog(app, client, message):
    """Sign-in refused because the licence ended: show the Installation ID and take a new code. True when a code was saved."""
    try: state = client.licence()
    except Exception: state = {}
    window = tk.Toplevel(app); window.title("Licence | الترخيص"); window.configure(bg="white", padx=22, pady=18); window.transient(app); window.grab_set()
    tk.Label(window, text=message, bg="white", fg=RED, wraplength=520, justify="left", font=(FONT, 10, "bold")).pack(anchor="w")
    row = tk.Frame(window, bg="white"); row.pack(anchor="w", pady=(12, 4))
    tk.Label(row, text="Installation ID", bg="white").pack(side="left")
    ident = tk.StringVar(value=state.get("installation_id", ""))
    tk.Entry(row, textvariable=ident, state="readonly", width=22, font=(FONT, 10, "bold")).pack(side="left", padx=6)
    _button(row, "Copy", lambda: _copy(window, ident.get())).pack(side="left")
    tk.Label(window, text="Licence code", bg="white").pack(anchor="w", pady=(10, 2))
    code = tk.Text(window, width=64, height=4, wrap="char"); code.pack(fill="x")
    saved = {"ok": False}
    def apply():
        try: client.install_licence(code.get("1.0", "end"))
        except Exception as exc: return messagebox.showerror("Licence", str(exc), parent=window)
        saved["ok"] = True; window.destroy()
    buttons = tk.Frame(window, bg="white"); buttons.pack(fill="x", pady=(12, 0))
    _button(buttons, "Apply Code and Sign in", apply, gold=True).pack(side="right")
    _button(buttons, "Close", window.destroy).pack(side="right", padx=6)
    app.wait_window(window)
    return saved["ok"]


def _key_file(parent):
    path = filedialog.askopenfilename(parent=parent, title="Seller key file", filetypes=[("Seller key", "*.key"), ("All files", "*.*")])
    return Path(path) if path else None


def make_licence_dialog(app, installation=""):
    """The seller makes a licence code (needs the seller key file and its password)."""
    import licence
    window = tk.Toplevel(app); window.title("Make a licence code (seller)"); window.configure(bg=LIGHT, padx=18, pady=14); window.transient(app)
    values = {key: tk.StringVar() for key in ("key", "password", "installation", "company", "until")}
    values["installation"].set(installation if installation else "")
    rows = (("Seller key file", "key"), ("Key password", "password"), ("Client Installation ID", "installation"), ("Company name", "company"),
            ("Valid until (DD-MM-YYYY)", "until"))
    for index, (label, key) in enumerate(rows):
        tk.Label(window, text=label, bg=LIGHT).grid(row=index, column=0, sticky="w", pady=4)
        tk.Entry(window, textvariable=values[key], width=40, show="*" if key == "password" else "").grid(row=index, column=1, sticky="w", padx=6, pady=4)
    _button(window, "Browse...", lambda: values["key"].set(str(_key_file(window) or values["key"].get()))).grid(row=0, column=2)
    output = tk.Text(window, width=70, height=4, wrap="char"); output.grid(row=len(rows), column=0, columnspan=3, pady=(10, 4))
    def make():
        try:
            code = licence.make_code(Path(values["key"].get()).read_bytes(), values["password"].get(), values["installation"].get(),
                                     values["company"].get(), values["until"].get())
        except (OSError, ValueError) as exc: return messagebox.showerror("Licence", str(exc), parent=window)
        output.delete("1.0", "end"); output.insert("1.0", code); _copy(window, code)
        messagebox.showinfo("Licence", "Licence code made and copied: send it to the client.", parent=window)
    buttons = tk.Frame(window, bg=LIGHT); buttons.grid(row=len(rows) + 1, column=0, columnspan=3, sticky="we", pady=(6, 0))
    _button(buttons, "Make Code", make, gold=True).pack(side="right")
    _button(buttons, "Change Key Password...", lambda: change_key_password_dialog(window)).pack(side="left")
    return window


def change_key_password_dialog(parent):
    import licence
    path = _key_file(parent)
    if not path: return
    window = tk.Toplevel(parent); window.title("Seller key password"); window.configure(bg=LIGHT, padx=18, pady=14); window.transient(parent); window.grab_set()
    old, new, again = tk.StringVar(), tk.StringVar(), tk.StringVar()
    for index, (label, var) in enumerate((("Current password", old), ("New password (10+ characters)", new), ("New password again", again))):
        tk.Label(window, text=label, bg=LIGHT).grid(row=index, column=0, sticky="w", pady=4)
        tk.Entry(window, textvariable=var, show="*", width=30).grid(row=index, column=1, padx=6, pady=4)
    def save():
        if new.get() != again.get(): return messagebox.showerror("Key password", "The two new passwords are not the same", parent=window)
        try:
            data = licence.change_key_password(path.read_bytes(), old.get(), new.get())
            backup = path.with_suffix(".key.old"); backup.write_bytes(path.read_bytes()); path.write_bytes(data)
        except (OSError, ValueError) as exc: return messagebox.showerror("Key password", str(exc), parent=window)
        messagebox.showinfo("Key password", f"Password changed. The old file is kept as {backup.name} - delete it once you have checked the new password.",
                            parent=window); window.destroy()
    _button(window, "Save", save, gold=True).grid(row=3, column=1, sticky="e", pady=(10, 0))
