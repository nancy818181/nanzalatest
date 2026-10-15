"""Preview only: Linux Tk (no Xft) neither joins nor orders Arabic. Shape + reorder the text so the screenshots look as
on Windows. Never shipped."""
import re
import unicodedata

FORMS = {}
for code in range(0x0621, 0x064B):
    ch = chr(code)
    try: base = unicodedata.name(ch)
    except ValueError: continue
    forms = {}
    for kind in ("ISOLATED", "FINAL", "INITIAL", "MEDIAL"):
        try: forms[kind] = unicodedata.lookup(f"{base} {kind} FORM")
        except KeyError: pass
    if forms: FORMS[ch] = forms
LAM_ALEF = {"ا": ("ﻻ", "ﻼ"), "أ": ("ﻷ", "ﻸ"), "إ": ("ﻹ", "ﻺ"), "آ": ("ﻵ", "ﻶ")}
HARAKAT = re.compile("[ً-ْ]")


def joins_next(ch): return ch in FORMS and "INITIAL" in FORMS[ch]


def shape_word(text):
    text = HARAKAT.sub("", text)
    out = []; i = 0; chars = list(text)
    while i < len(chars):
        ch = chars[i]
        prev = chars[i - 1] if i > 0 else ""
        joined_before = joins_next(prev) and ch in FORMS
        if ch == "ل" and i + 1 < len(chars) and chars[i + 1] in LAM_ALEF:
            out.append(LAM_ALEF[chars[i + 1]][1 if joined_before else 0]); i += 2; continue
        if ch not in FORMS: out.append(ch); i += 1; continue
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        joined_after = joins_next(ch) and nxt in FORMS
        forms = FORMS[ch]
        kind = ("MEDIAL" if joined_before and joined_after else "FINAL" if joined_before else "INITIAL" if joined_after else "ISOLATED")
        out.append(forms.get(kind) or forms.get("FINAL" if joined_before else "ISOLATED") or ch); i += 1
    return "".join(out)


ARABIC = re.compile("[؀-ۿ]")
RUN = re.compile(r"([؀-ۿ][؀-ۿ\s،؟]*[؀-ۿ]|[؀-ۿ])")


def visual(text):
    if not isinstance(text, str) or not ARABIC.search(text): return text
    lines = []
    for line in text.split("\n"):
        parts = RUN.split(line)
        pieces = [shape_word(p)[::-1] if ARABIC.search(p) else p for p in parts]
        lines.append("".join(reversed(pieces)))
    return "\n".join(lines)
