"""2.9.97: see an attached document inside the program.

One Attachments window for every screen (invoices, purchases, expenses, fixed assets): double-click a file to see it. PDFs are
drawn page by page (pypdfium2, already used to read scanned PDFs - nothing leaves the computer), images are shown as they are.
Next / previous page, zoom, "Open in PDF reader" (the computer's own program) and Download."""
from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

NAVY, GOLD, LIGHT = "#102A43", "#B78B45", "#F4F7FA"
log = logging.getLogger("saber.attachments")
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")


def _button(parent, text, command, primary=False):
    return tk.Button(parent, text=text, command=command, bg=GOLD if primary else NAVY, fg=NAVY if primary else "white", border=0,
                     padx=12, pady=5, font=("Segoe UI", 9, "bold"), cursor="hand2")


def page_images(file_name, content, scale=1.5):
    """[(PIL image)] for each page of a PDF, or the image itself. Raises ValueError for a file that cannot be shown."""
    from PIL import Image
    suffix = Path(str(file_name)).suffix.lower()
    if suffix in IMAGE_TYPES or content[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"GIF8"):
        image = Image.open(io.BytesIO(content)); image.load(); return [image.convert("RGB")]
    if suffix == ".pdf" or content[:5] == b"%PDF-":
        import pypdfium2
        document = pypdfium2.PdfDocument(content)
        try: return [document[index].render(scale=scale).to_pil() for index in range(len(document))]
        finally: document.close()
    raise ValueError("This kind of file cannot be shown here - use 'Open in PDF reader' or Download.")


def open_externally(file_name, content):
    """Save a copy in the Saber data folder (Opened documents) and open it with the computer's own program."""
    import app_runtime
    folder = app_runtime.data_dir() / "Opened documents"; folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_. " else "_" for ch in Path(str(file_name)).name) or "document.pdf"
    target = folder / safe; target.write_bytes(content)
    if hasattr(os, "startfile"): os.startfile(str(target))  # Windows
    else: subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)])
    return target


def save_copy(parent, file_name, content):
    path = filedialog.asksaveasfilename(initialfile=Path(str(file_name)).name, parent=parent)
    if not path: return None
    Path(path).write_bytes(content); return path


def show_document(parent, file_name, content):
    """The viewer window. Returns the window (or None when the file cannot be read)."""
    try: pages = page_images(file_name, content)
    except Exception as exc:
        if messagebox.askyesno("Attachment", f"{exc}\n\nOpen it with the program of this computer?", parent=parent):
            try: open_externally(file_name, content)
            except Exception as error: messagebox.showerror("Attachment", str(error), parent=parent)
        return None
    from PIL import ImageTk
    window = tk.Toplevel(parent); window.title(f"{Path(str(file_name)).name}"); window.configure(bg=LIGHT); window.transient(parent)
    width, height = min(1100, int(window.winfo_screenwidth() * 0.8)), min(900, int(window.winfo_screenheight() * 0.85))
    window.geometry(f"{width}x{height}")
    state = {"page": 0, "zoom": None, "photo": None}  # zoom None = fit the width of the window
    bar = tk.Frame(window, bg=LIGHT); bar.pack(fill="x", padx=8, pady=6)
    label = tk.Label(bar, text="", bg=LIGHT, fg=NAVY, font=("Segoe UI", 10, "bold"))
    frame = tk.Frame(window, bg="#5A6772"); frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    canvas = tk.Canvas(frame, bg="#5A6772", highlightthickness=0)
    vertical = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview); horizontal = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
    canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    canvas.grid(row=0, column=0, sticky="nsew"); vertical.grid(row=0, column=1, sticky="ns"); horizontal.grid(row=1, column=0, sticky="ew")
    frame.grid_rowconfigure(0, weight=1); frame.grid_columnconfigure(0, weight=1)

    def draw(*_args):
        image = pages[state["page"]]
        available = max(200, canvas.winfo_width() - 24)
        zoom = state["zoom"] if state["zoom"] else min(2.5, available / image.width)
        shown = image.resize((max(1, int(image.width * zoom)), max(1, int(image.height * zoom))))
        state["photo"] = ImageTk.PhotoImage(shown, master=window)
        canvas.delete("all")
        x = max(12, (canvas.winfo_width() - shown.width) // 2)
        canvas.create_image(x, 12, image=state["photo"], anchor="nw")
        canvas.configure(scrollregion=(0, 0, max(canvas.winfo_width(), shown.width + 24), shown.height + 24))
        label.configure(text=f"Page {state['page'] + 1} of {len(pages)}   ·   {int(zoom * 100)}%")

    def go(step):
        state["page"] = max(0, min(len(pages) - 1, state["page"] + step)); canvas.yview_moveto(0); draw()

    def zoom(factor):
        current = state["zoom"] or max(0.1, (canvas.winfo_width() - 24) / pages[state["page"]].width)
        state["zoom"] = max(0.2, min(4.0, current * factor)) if factor else None; draw()

    _button(bar, "◀ Previous", lambda: go(-1)).pack(side="left", padx=(0, 3))
    _button(bar, "Next ▶", lambda: go(1)).pack(side="left", padx=3)
    label.pack(side="left", padx=12)
    _button(bar, "−", lambda: zoom(1 / 1.25)).pack(side="left", padx=2)
    _button(bar, "Fit width", lambda: zoom(None)).pack(side="left", padx=2)
    _button(bar, "+", lambda: zoom(1.25)).pack(side="left", padx=2)
    _button(bar, "Close", window.destroy).pack(side="right", padx=3)
    _button(bar, "Download", lambda: save_copy(window, file_name, content)).pack(side="right", padx=3)
    _button(bar, "Open in PDF reader", lambda: _safe_open(window, file_name, content)).pack(side="right", padx=3)
    canvas.bind("<Configure>", lambda _e: draw() if state["zoom"] is None else None)
    window.bind("<Next>", lambda _e: go(1)); window.bind("<Prior>", lambda _e: go(-1)); window.bind("<Escape>", lambda _e: window.destroy())
    canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
    canvas.bind("<Button-4>", lambda _e: canvas.yview_scroll(-1, "units")); canvas.bind("<Button-5>", lambda _e: canvas.yview_scroll(1, "units"))
    window.after(50, draw)
    window._pages = pages; window._go = go; window._label = label  # for tests
    return window


def _safe_open(window, file_name, content):
    try: open_externally(file_name, content)
    except Exception as exc: messagebox.showerror("Attachment", f"Could not open it: {exc}", parent=window)


def attachments_window(parent, title, items, download, extra_buttons=()):
    """List the attached files; double-click / View shows the document. `download(record)` returns its bytes.
    With a single file the document opens straight away."""
    if not items:
        messagebox.showinfo("Attachments", f"No documents attached to {title}", parent=parent); return None
    def content_of(record):
        try: return download(record)
        except Exception as exc: messagebox.showerror("Attachments", str(exc), parent=parent); return None
    if len(items) == 1 and not extra_buttons:
        data = content_of(items[0])
        return show_document(parent, items[0]["file_name"], data) if data is not None else None
    window = tk.Toplevel(parent); window.title(f"Documents - {title}"); window.configure(bg=LIGHT); window.geometry("660x320"); window.transient(parent)
    tk.Label(window, text="Double-click a document to see it", bg=LIGHT, fg=NAVY, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
    tree = ttk.Treeview(window, columns=("file", "size", "uploaded"), show="headings")
    for key, label, width in (("file", "File", 340), ("size", "Size", 90), ("uploaded", "Uploaded", 170)): tree.heading(key, text=label); tree.column(key, width=width)
    tree.pack(fill="both", expand=True, padx=8, pady=8)
    for item in items: tree.insert("", "end", iid=str(item["id"]), values=(item["file_name"], f'{(item.get("size") or 0) / 1024:,.0f} KB', str(item.get("uploaded_at") or "")[:16]))
    tree.selection_set(str(items[0]["id"]))
    def selected():
        chosen = tree.selection()
        return next((i for i in items if str(i["id"]) == chosen[0]), None) if chosen else None
    def view():
        record = selected()
        if record and (data := content_of(record)) is not None: show_document(window, record["file_name"], data)
    def external():
        record = selected()
        if record and (data := content_of(record)) is not None: _safe_open(window, record["file_name"], data)
    def save():
        record = selected()
        if record and (data := content_of(record)) is not None and save_copy(window, record["file_name"], data):
            messagebox.showinfo("Attachments", "Saved.", parent=window)
    buttons = tk.Frame(window, bg=LIGHT); buttons.pack(pady=(0, 8))
    _button(buttons, "View", view, primary=True).pack(side="left", padx=3)
    _button(buttons, "Open in PDF reader", external).pack(side="left", padx=3)
    _button(buttons, "Download", save).pack(side="left", padx=3)
    for text, command in extra_buttons: _button(buttons, text, command).pack(side="left", padx=3)
    tree.bind("<Double-1>", lambda _e: view()); tree.bind("<Return>", lambda _e: view())
    window._tree = tree; window._view = view
    return window
