"""Logo pictures drawn sharply for the screens (2.9.58).

Tk's own PhotoImage can only shrink a picture by dropping pixels (subsample), which made the header logo blurry and
unreadable. Pillow (installed with ReportLab) resizes with proper filtering. For the dark header bar, the "SA" mark is
used alone, with the navy parts in white so it stands out on navy; the full logo is used on the white login card."""
from __future__ import annotations

NAVY_RGB = (16, 42, 67)


def _load(path):
    from PIL import Image
    return Image.open(path).convert("RGBA")


def _transparent_background(img):
    """Near-white background becomes transparent, with soft edges."""
    pixels = img.load(); w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]; low = min(r, g, b)
            if low > 238: pixels[x, y] = (r, g, b, 0)
            elif low > 200: pixels[x, y] = (r, g, b, int(a * (238 - low) / 38))
    return img


_MARKS = {}


def header_mark(path, height=46):
    """2.9.87: drawn once per run (it took a third of a second every time the main screen opened)."""
    key = (str(path), int(height))
    if key not in _MARKS: _MARKS[key] = _header_mark(path, height)
    return _MARKS[key].copy()


def _header_mark(path, height=46):
    """The SA monogram only, navy parts in white, gold kept, transparent background, `height` pixels high."""
    from PIL import Image
    img = _load(path); w, h = img.size
    mark = img.crop((0, 0, w, int(h * 0.78)))            # the monogram sits above the company name
    mark = _transparent_background(mark)
    box = mark.getbbox()
    if box: mark = mark.crop(box)
    pixels = mark.load(); mw, mh = mark.size
    for y in range(mh):
        for x in range(mw):
            r, g, b, a = pixels[x, y]
            if a and b > r + 10: pixels[x, y] = (255, 255, 255, a)     # navy (and its soft edge) -> white
    return mark.resize((max(1, round(mw * height / mh)), height), Image.LANCZOS)


def full_logo(path, width=250):
    from PIL import Image
    img = _load(path); w, h = img.size
    return img.resize((width, max(1, round(h * width / w))), Image.LANCZOS)


def photo(image, master):
    from PIL import ImageTk
    return ImageTk.PhotoImage(image, master=master)
