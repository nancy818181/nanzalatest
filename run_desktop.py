"""Start Nanza Accounting: one copy per Windows user, its own private data service, an error log."""
import json
import logging
import secrets
import sys
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
from urllib.request import Request, urlopen

import app_runtime
from desktop import main
from server import run_server

log = logging.getLogger("saber.start")


def local_server_ready(url=None, key=None):
    url = url or app_runtime.LOCAL_URL; key = key or app_runtime.LOCAL_KEY
    if not url: return False
    try:
        request = Request(url + "/health", headers={app_runtime.KEY_HEADER: key or ""})
        with urlopen(request, timeout=0.5) as response:
            result = json.loads(response.read().decode("utf-8"))
        return result.get("application") == "Saber Accounting"
    except Exception:
        return False


def _ask_initial_password():
    root = tk.Tk(); root.withdraw()
    try:
        while True:
            password = simpledialog.askstring("Nanza Accounting", "Create the initial admin password (at least 10 characters):", show="*", parent=root)
            if password is None: return None
            if len(password) >= 10: return password
    finally: root.destroy()


def start_local_server(database=None):
    """Start the private per-PC data service invisibly inside the desktop app.

    Windows picks a free port (no clash with other programs) and a new secret key is made at every
    start; only this window knows it, so no other program on the PC can read or change the data.
    Returns False when the user cancelled the first-time admin password.
    """
    database = database or app_runtime.main_database_path()
    database.parent.mkdir(parents=True, exist_ok=True)
    initial_password = None
    if not database.exists():
        initial_password = _ask_initial_password()
        if initial_password is None: return False
    key = secrets.token_urlsafe(32); ready = threading.Event(); chosen = {}

    def on_ready(port):
        chosen["port"] = port; ready.set()

    def serve():
        try:
            run_server(host="127.0.0.1", port=0, database=str(database), admin_password=initial_password, local_key=key, on_ready=on_ready)
        except Exception as exc:
            log.exception("The data service stopped")
            chosen["error"] = f"{type(exc).__name__}: {exc}"
            ready.set()

    thread = threading.Thread(target=serve, name="SaberLocalDataService", daemon=True)
    thread.start()
    _wait_for_service(ready, thread)
    if "port" not in chosen:
        reason = chosen.get("error") or "the data service did not answer"
        hint = ("\n\nAnother Nanza program is using the data (the background backup or a second window): restart the computer, "
                "or end 'NanzaAccountingBackup' in the Task Manager, then open Nanza Accounting again.") if "locked" in reason.lower() else ""
        raise RuntimeError(f"Nanza Accounting could not start its local data service ({reason}).{hint}")
    app_runtime.LOCAL_URL = f"http://127.0.0.1:{chosen['port']}"; app_runtime.LOCAL_KEY = key
    if initial_password:
        from backup_service import backup_all
        try: backup_all(database)
        except Exception: log.exception("First backup failed")
    return True


def _wait_for_service(ready, thread, limit=1800):
    """2.9.87: the first start after an update upgrades every company file and can take minutes on large books; the
    program used to give up after 60 seconds. A small window says what is happening while the service is still working."""
    if ready.wait(5) or not thread.is_alive(): return
    root = None
    try:
        root = tk.Tk(); root.title("Nanza Accounting"); root.resizable(False, False)
        tk.Label(root, text="Preparing your company files...", font=("Segoe UI", 11, "bold"), padx=24, pady=(14)).pack()
        tk.Label(root, text="The first start after an update brings every company and year up to date.\nThis can take a few minutes on large books - please wait.",
                 justify="left", padx=24).pack(pady=(0, 14))
        root.update()
    except Exception:
        root = None
    import time
    started = time.monotonic()
    while not ready.is_set() and thread.is_alive() and time.monotonic() - started < limit:
        ready.wait(0.2)
        if root is not None:
            try: root.update()
            except Exception: root = None
    if root is not None:
        try: root.destroy()
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105


def _tell(message, error=False):
    root = tk.Tk(); root.withdraw()
    try: (messagebox.showerror if error else messagebox.showinfo)("Nanza Accounting", message, parent=root)
    finally: root.destroy()


def run():
    app_runtime.setup_logging()
    instance = app_runtime.SingleInstance()
    if not instance.acquire():
        if not instance.bring_existing_to_front():
            _tell("Nanza Accounting is already open on this computer.")
        return 0
    app_runtime.INSTANCE = instance
    try:
        if not start_local_server(): return 0
        main()
        return 0
    except Exception as exc:
        log.exception("Nanza Accounting stopped")
        _tell(f"Nanza Accounting could not continue:\n{exc}\n\nThe details are in the log file ({app_runtime.data_dir() / 'logs' / 'saber.log'}).", error=True)
        return 1
    finally:
        instance.release()


if __name__ == "__main__":
    sys.exit(run())
