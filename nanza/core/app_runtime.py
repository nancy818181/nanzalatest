"""Runtime plumbing for the installed program (2.9.41).

- Where the data lives, and the one-time safe rename of the main data file
  (saber_accounting_v0_7.db -> saber_accounting.db).
- The private link between the window and its built-in data service: a free port chosen by
  Windows and a secret key generated at every start, so no other program can use the service.
- Only one copy of Saber open per Windows user (a second start brings the first window forward).
- An error log in <data folder>/logs/saber.log, so problems on a client PC can be found.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sqlite3
import sys
import threading
from contextlib import closing
from pathlib import Path

log = logging.getLogger("saber")

MAIN_DATABASE_NAME = "saber_accounting.db"
OLD_MAIN_DATABASE_NAME = "saber_accounting_v0_7.db"
NEW_MAIN_DATABASE_NAME = "nanza_accounting.db"  # 2.9.114: the main data file in a folder that never had a Saber one
KEY_HEADER = "X-Saber-Key"

# Filled in by run_desktop.py once the private data service is running.
LOCAL_URL: str | None = None
LOCAL_KEY: str | None = None


DATA_FOLDER_NAME = "NanzaAccounting"      # 2.9.114: the data folder on a computer that never had the program
OLD_DATA_FOLDER_NAME = "SaberAccounting"  # kept for every computer that already has it - nothing is moved or renamed


def data_dir() -> Path:
    """C:\\Users\\<name>\\NanzaAccounting on a new computer; SaberAccounting where that folder already exists
    (an installed copy keeps its companies, backups, licence and log exactly where they are)."""
    override = os.environ.get("SABER_DATA_DIR")
    if override: return Path(override)
    home = Path.home()
    old = home / OLD_DATA_FOLDER_NAME
    return old if old.exists() else home / DATA_FOLDER_NAME


# ------------------------------------------------------------------ logging
def log_file(folder: Path | None = None) -> Path:
    """logs/nanza.log; logs/saber.log where that log already exists (2.9.114: an installed copy keeps its log)."""
    logs = Path(folder or data_dir()) / "logs"
    old = logs / "saber.log"
    return old if old.exists() else logs / "nanza.log"


def setup_logging(folder: Path | None = None) -> Path:
    """Write warnings and errors (with the full details) to logs/nanza.log (saber.log on older installations); 5 x 1 MB kept."""
    folder = Path(folder or data_dir()) / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    path = log_file(folder.parent)
    root = logging.getLogger()
    if not any(getattr(h, "_saber", False) for h in root.handlers):
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"))
        handler._saber = True
        root.addHandler(handler)
        # SABER_DEBUG_LOG=1 also writes the small errors the program ignores on purpose (for support).
        root.setLevel(logging.DEBUG if os.environ.get("SABER_DEBUG_LOG") else logging.INFO)

    def excepthook(kind, value, tb):
        log.critical("Unhandled error", exc_info=(kind, value, tb))
        sys.__excepthook__(kind, value, tb)

    def thread_hook(args):
        log.error("Unhandled error in thread %s", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    return path


# ------------------------------------------------------------------ main data file
def _registry_points_to(registry: Path, old: Path, new: Path) -> bool:
    """Make companies/companies.json use the new main file name. Returns True when it changed."""
    if not registry.is_file():
        return False
    data = json.loads(registry.read_text(encoding="utf-8"))
    changed = False
    old_resolved = old.resolve()
    for company in data.get("companies", []):
        for year in company.get("years", []):
            value = year.get("database")
            if value and Path(value).resolve() == old_resolved:
                year["database"] = str(new.resolve()); changed = True
    if changed:
        backup = registry.with_name(registry.name + ".before-2.9.41")
        if not backup.exists():
            backup.write_bytes(registry.read_bytes())
        temporary = registry.with_name(registry.name + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, registry)
    return changed


def main_database_path(folder: Path | None = None) -> Path:
    """The main data file, renamed once from the old 0.7 name without any risk to the data.

    The old file is copied with SQLite's own backup (safe even with an open WAL), the copy is
    checked, and only then is it put in place. The old file is kept as
    saber_accounting_v0_7.db.before-2.9.41. If anything fails, the old file keeps being used.
    """
    folder = Path(folder or data_dir())
    new, old = folder / MAIN_DATABASE_NAME, folder / OLD_MAIN_DATABASE_NAME
    registry = folder / "companies" / "companies.json"
    if not new.exists() and not old.exists():
        return folder / NEW_MAIN_DATABASE_NAME  # 2.9.114: a new data folder gets the Nanza name; an existing file is never renamed
    if new.exists():
        # Finish an interrupted rename: the company list must not point at the old name.
        try: _registry_points_to(registry, old, new)
        except Exception: log.exception("Could not update the company list to %s", new.name)
        if old.exists(): _retire_old_file(old)
        return new
    temporary = folder / (MAIN_DATABASE_NAME + ".copying")
    try:
        if temporary.exists(): temporary.unlink()
        # Connections are closed explicitly: Windows cannot rename a file that is still open.
        with closing(sqlite3.connect(old)) as source, closing(sqlite3.connect(temporary)) as target:
            source.backup(target)
            result = target.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok": raise RuntimeError(f"copy check failed: {result}")
            copied = target.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
            original = source.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
            if copied != original: raise RuntimeError("copy is missing tables")
            target.execute("PRAGMA journal_mode=DELETE")  # one self-contained file before it is put in place
        os.replace(temporary, new)
        _registry_points_to(registry, old, new)
        log.info("Main data file renamed: %s -> %s", old.name, new.name)
    except Exception:
        log.exception("Main data file was not renamed; the old file %s is still used", old.name)
        try:
            if temporary.exists(): temporary.unlink()
        except OSError: pass
        if new.exists():
            # The copy is complete but the company list could not be updated: keep using the old file.
            try: new.replace(folder / (MAIN_DATABASE_NAME + ".unused"))
            except OSError: pass
        return old
    _retire_old_file(old)
    return new


def _retire_old_file(old: Path) -> None:
    """Keep the old file under a name nothing opens any more (best effort: it may still be open)."""
    target = old.with_name(old.name + ".before-2.9.41")
    try:
        if not target.exists():
            old.replace(target)
            for suffix in ("-wal", "-shm"):
                extra = old.with_name(old.name + suffix)
                if extra.exists():
                    try: extra.unlink()
                    except OSError: pass
    except OSError:
        log.warning("Old data file %s is still in use; it will be set aside next time", old.name)


# ------------------------------------------------------------------ one copy open
class SingleInstance:
    """Hold an OS file lock for as long as the program runs. A second copy cannot take it."""

    def __init__(self, folder: Path | None = None):
        self.folder = Path(folder or data_dir()); self.folder.mkdir(parents=True, exist_ok=True)
        # 2.9.114: ".nanza.*" in a new data folder; a SaberAccounting folder keeps ".saber.*" (every copy there agrees)
        tag = "saber" if self.folder.name == OLD_DATA_FOLDER_NAME or (self.folder / ".saber.window").exists() else "nanza"
        self.lock_path = self.folder / f".{tag}.lock"
        self.window_path = self.folder / f".{tag}.window"
        self._handle = None

    def acquire(self) -> bool:
        handle = open(self.lock_path, "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close(); return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is not None:
            try: self._handle.close()
            finally: self._handle = None
            try: self.window_path.unlink()
            except OSError: pass

    def remember_window(self, tk_root) -> None:
        """Note the main window so a second start can bring it to the front."""
        try: self.window_path.write_text(str(int(tk_root.wm_frame(), 16)), encoding="ascii")
        except Exception: log.warning("Could not note the main window", exc_info=True)

    def bring_existing_to_front(self) -> bool:
        if sys.platform != "win32": return False
        try:
            import ctypes
            hwnd = int(self.window_path.read_text(encoding="ascii").strip())
            user32 = ctypes.windll.user32
            if not user32.IsWindow(hwnd): return False
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            return bool(user32.SetForegroundWindow(hwnd))
        except Exception:
            return False


INSTANCE: SingleInstance | None = None


# ------------------------------------------------------------------ update check (2.9.42)
APP_VERSION = "2.9.122"
# Newest GitHub Release of the program. Another address can be put in <data folder>/update_url.txt
# (one line), for example when the repository is private and the installers are shared elsewhere.
DEFAULT_UPDATE_URL = "https://api.github.com/repos/nancy818181/nanzalatest/releases/latest"
UPDATE_CHECK_HOURS = 24


def version_tuple(text) -> tuple:
    import re
    numbers = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in numbers[:4]) if numbers else (0,)


def update_url(folder: Path | None = None) -> str | None:
    override = Path(folder or data_dir()) / "update_url.txt"
    try:
        text = override.read_text(encoding="utf-8").strip()
        if text.lower() == "off": return None
        if text: return text
    except OSError:
        pass
    return DEFAULT_UPDATE_URL


def parse_release(body: dict) -> dict | None:
    """GitHub Release ({tag_name, html_url}) or a simple file ({version, url})."""
    version = body.get("version") or body.get("tag_name")
    if not version: return None
    return {"version": str(version).lstrip("vV"), "url": body.get("url") if "version" in body else body.get("html_url"),
            "notes": (body.get("notes") or body.get("body") or "")[:500]}


def check_for_update(current: str = APP_VERSION, folder: Path | None = None, fetch=None, force=False) -> dict | None:
    """Returns {version, url, notes} when a newer version exists, else None. At most once a day,
    never raises, never downloads or installs anything by itself (the user decides)."""
    from datetime import datetime, timezone
    folder = Path(folder or data_dir()); folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / ".update_check.json"
    try: state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError): state = {}
    now = datetime.now(timezone.utc)
    if not force:
        try:
            if (now - datetime.fromisoformat(state["checked_at"])).total_seconds() < UPDATE_CHECK_HOURS * 3600:
                found = state.get("found")
                return found if found and version_tuple(found["version"]) > version_tuple(current) else None
        except (KeyError, ValueError, TypeError):
            pass
    url = update_url(folder)
    if not url: return None
    try:
        if fetch is None:
            from urllib.request import Request, urlopen
            request = Request(url, headers={"User-Agent": f"SaberAccounting/{current}", "Accept": "application/vnd.github+json"})
            with urlopen(request, timeout=6) as response: body = json.loads(response.read().decode("utf-8"))
        else:
            body = fetch(url)
        release = parse_release(body)
    except Exception as exc:
        log.info("Update check skipped: %s", exc)  # offline or private address: normal, not an error
        return None
    found = release if release and version_tuple(release["version"]) > version_tuple(current) else None
    try: state_path.write_text(json.dumps({"checked_at": now.isoformat(), "found": found}), encoding="utf-8")
    except OSError: pass
    if found: log.info("Newer version available: %s", found["version"])
    return found
