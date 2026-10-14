"""Shared imports and helpers of desktop_brains.py (split in 2.9.42)."""
from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk
from datetime import datetime
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk

from report_export import export_sections_pdf

NAVY, GOLD, LIGHT = "#102A43", "#B78B45", "#F4F7FA"  # 2.9.59: the same colours on every screen
RED, MUTED = "#8B1E1E", "#5f6b76"
VOUCHER_TYPES = ["01 - General Voucher", "02 - Receipt Voucher", "03 - Payment Voucher", "04 - Opening Voucher", "05 - Closing Voucher", "06 - Adjustment", "07 - DOE (Difference of Exchange)"]


def _num(value):
    try: return float(str(value or 0).replace(",", ""))
    except ValueError: return 0.0


def _fmt(value, places=2):
    return f"{_num(value):,.{places}f}"


def _date_text(value):
    text = str(value or "").strip()
    for pattern in ("%d-%m-%Y", "%d%m%Y", "%Y-%m-%d"):
        try: return datetime.strptime(text, pattern).strftime("%d-%m-%Y")
        except ValueError: pass
    return text


def currency_from_prefix(value, codes):
    """Expand an unambiguous currency prefix; preserve full codes."""
    value = str(value or "").strip().upper()
    choices = [code for code in codes if code.upper().startswith(value)] if value else []
    return choices[0] if len(choices) == 1 else value
