"""Local OCR entry points. Model dependencies are loaded only when used."""
from .engine import extract_invoice_data
from .handwriting import read_handwritten_line, read_handwritten_arabic_line

__all__ = ["extract_invoice_data", "read_handwritten_line", "read_handwritten_arabic_line"]
