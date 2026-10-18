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
FOLDERS = ("core", "accounting", "tax", "payroll", "reports", "documents", "ui", "ai_accountant")

for _name in FOLDERS:
    _folder = ROOT / "nanza" / _name
    if _folder.is_dir() and str(_folder) not in sys.path:
        sys.path.insert(1, str(_folder))


def program_files():
    """Every module of the program (not the tests), for the release checks."""
    active_root = ROOT / "nanza"
    active_files = (path for path in active_root.rglob("*.py")
                    if "nanza_backup" not in path.relative_to(active_root).parts)
    return sorted([*ROOT.glob("*.py"), *active_files])


def source(name):
    """Find a module in the active source tree, never in backups or delivery copies."""
    active_root = ROOT / "nanza"
    for folder in FOLDERS:
        candidate = active_root / folder / name
        if candidate.is_file():
            return candidate
    for path in ROOT.glob("*.py"):
        if path.name == name:
            return path
    raise FileNotFoundError(name)
