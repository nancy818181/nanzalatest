"""2.9.136: small, display-independent helper that fits a Tk window to the screen (from the Phase 1 review)."""


def fit_window(win, w, h, *, max_fraction=0.90, min_width=560, min_height=360):
    """Size and centre a Tk window within 90% of its screen; it stays resizable."""
    screen_w, screen_h = int(win.winfo_screenwidth()), int(win.winfo_screenheight())
    max_w = max(1, int(screen_w * max_fraction))
    max_h = max(1, int(screen_h * max_fraction))
    width, height = min(int(w), max_w), min(int(h), max_h)
    win.resizable(True, True)
    win.minsize(min(width, int(min_width)), min(height, int(min_height)))
    x, y = max(0, (screen_w - width) // 2), max(0, (screen_h - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")
    return width, height, x, y
