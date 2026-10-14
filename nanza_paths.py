"""2.9.117: where the program's modules are.

The modules are kept in folders by subject (nanza/core, nanza/accounting, nanza/tax, nanza/payroll, nanza/reports,
nanza/documents, nanza/ui). Importing this file once - the entry points run_desktop.py, run_server.py and
backup_service.py do it first - puts those folders on the import path, so every module still imports the others by
name exactly as before (import database, import vat_return ...). In the installed program (PyInstaller) the modules are
already together and this file only tells where the program's files are (ROOT)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # the program folder (Assets/ is here)
FOLDERS = ("core", "accounting", "tax", "payroll", "reports", "documents", "ui")

for _name in FOLDERS:
    _folder = ROOT / "nanza" / _name
    if _folder.is_dir() and str(_folder) not in sys.path:
        sys.path.insert(1, str(_folder))


def program_files():
    """Every module of the program (not the tests), for the release checks."""
    return sorted([*ROOT.glob("*.py"), *(ROOT / "nanza").rglob("*.py")])


def source(name):
    """The file of a module by its file name ("server.py"), wherever its folder is."""
    for path in program_files():
        if path.name == name: return path
    raise FileNotFoundError(name)
