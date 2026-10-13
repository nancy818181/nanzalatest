"""A second copy of every backup outside the Saber folder (2.9.52): OneDrive, a USB disk or a network folder.

Each new backup, once checked, is copied to <second folder>/<company>/<year>/. The newest copies are kept there
(30 per company-year by default, older automatic ones are removed; manual and safety copies are never removed).
A copy that fails never stops the backup itself: the error is written to the log and shown in Backup & Restore.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

log = logging.getLogger("saber")
SETTINGS_FILE = "backup_copy.json"


def _settings_path():
    import app_runtime
    return app_runtime.data_dir() / SETTINGS_FILE


def settings():
    try: data = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError): data = {}
    return {"folder": data.get("folder") or "", "keep": int(data.get("keep") or 30), "last_ok": data.get("last_ok"), "last_error": data.get("last_error")}


def _write(data):
    path = _settings_path(); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp"); temporary.write_text(json.dumps(data, indent=2), encoding="utf-8"); os.replace(temporary, path)


def save_settings(folder, keep=30):
    folder = str(folder or "").strip()
    if folder:
        target = Path(folder)
        try: target.mkdir(parents=True, exist_ok=True)
        except OSError as exc: raise ValueError(f"The folder cannot be used: {exc}")
        probe = target / ".saber_write_test"
        try: probe.write_text("ok", encoding="utf-8"); probe.unlink()
        except OSError as exc: raise ValueError(f"Saber cannot write in this folder: {exc}")
    keep = int(keep or 30)
    if keep < 1: raise ValueError("Keep at least one copy")
    data = settings(); data.update(folder=folder, keep=keep); _write(data)
    return data


def suggested_folder():
    """OneDrive (business first) when it is on this computer, else empty."""
    for name in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        base = os.environ.get(name)
        if base and Path(base).is_dir(): return str(Path(base) / "Saber Accounting Backups")
    return ""


def _status(ok, message):
    data = settings(); stamp = datetime.now().strftime("%d-%m-%Y %H:%M")
    if ok: data["last_ok"] = f"{stamp} {message}"; data["last_error"] = None
    else: data["last_error"] = f"{stamp} {message}"
    try: _write(data)
    except OSError: pass


def copy_backup(backup_file, backups_folder=None):
    """Copy one checked backup to the second folder. Returns the copy path, or None when no second folder is set."""
    config = settings(); folder = config["folder"]
    if not folder: return None
    source = Path(backup_file)
    parts = Path(backups_folder or source.parent).parts
    relative = Path(*parts[-2:]) if len(parts) >= 2 else Path("main")
    target_folder = Path(folder) / relative
    try:
        target_folder.mkdir(parents=True, exist_ok=True)
        target = target_folder / source.name; temporary = target_folder / (source.name + ".copying")
        shutil.copy2(source, temporary)
        if temporary.stat().st_size != source.stat().st_size: raise OSError("the copy is incomplete")
        os.replace(temporary, target)
        _prune(target_folder, config["keep"])
    except Exception as exc:
        log.warning("Second backup copy failed for %s: %s", source.name, exc)
        _status(False, f"{source.name}: {exc}")
        return None
    _status(True, f"{source.name} -> {target_folder}")
    return str(target)


def _prune(folder, keep):
    """Keep the newest `keep` automatic copies; manual / safety copies (with a kind in the name) are never removed."""
    automatic = sorted((p for p in folder.glob("*.db") if "_auto" in p.stem), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in automatic[keep:]:
        try: old.unlink()
        except OSError: pass


def rename_company(old_name, new_name):
    """A renamed company: its folder in the second copy gets the new name as well (never merged or overwritten)."""
    folder = settings()["folder"]
    if not folder or not old_name or old_name == new_name: return False
    source = Path(folder) / old_name; target = Path(folder) / new_name
    if not source.is_dir() or target.exists(): return False
    source.rename(target)
    return True
