"""2.9.113: the "not deductible for income tax" tick on every screen that makes entries (journal voucher, purchase, payment).
The entry stays in the books; the tick only lists it in the add-back report and leaves it out of the P&L on the tax basis."""

import logging
import tkinter as tk

log = logging.getLogger("saber")
LABEL = "Not deductible for income tax (no official invoice) | غير مقبول ضريبياً"


_TICKS = []          # every tick on the screens, with how it is packed (Settings can hide them all)
_STATE = {"show": True}


def tax_tick(parent, variable, background):
    """The tick, the same wording on every screen."""
    return tk.Checkbutton(parent, text=LABEL, variable=variable, bg=background, fg="#9A3412", anchor="w")


def place(widget, **pack):
    """Pack a tick (when Settings shows it) and remember it for Settings > "Show the tick"."""
    _TICKS.append((widget, pack))
    if _STATE["show"]: widget.pack(**pack)
    return widget


def set_visible(show):
    """2.9.113: Settings > show / hide the tick on every entry screen. Hiding never changes a tick already saved:
    the ticked entries stay in the add-back report and out of the P&L on the tax basis."""
    _STATE["show"] = bool(show)
    for widget, pack in list(_TICKS):
        try:
            if show and not widget.winfo_manager(): widget.pack(**pack)
            elif not show: widget.pack_forget()
        except tk.TclError:
            _TICKS.remove((widget, pack))  # the screen was closed


def visible():
    return _STATE["show"]


def save_tax_flag(client, source_type, source_id, variable):
    """Store the tick for the entry just saved; a failure is shown in the log and never undoes the saved entry."""
    if not source_id: return
    try: client.set_tax_flag(source_type, int(source_id), bool(variable.get()))
    except (RuntimeError, OSError, ValueError) as exc:  # 2.9.119: said on the screen too - the income tax figures depend on it
        log.warning("tax flag not saved for %s %s", source_type, source_id, exc_info=True)
        from tkinter import messagebox
        messagebox.showwarning("Not deductible for income tax", f"The entry is saved, but its 'not deductible' tick was not: {exc}\n"
                               "Open the entry again and save it to set the tick.")


def load_tax_flag(client, source_type, source_id, variable):
    """Show the tick of an entry opened for editing (unticked for a new entry)."""
    if not source_id: return variable.set(False)
    try: variable.set(int(source_id) in client.tax_flags(source_type))
    except Exception:
        log.warning("tax flag not read for %s %s", source_type, source_id, exc_info=True); variable.set(False)
