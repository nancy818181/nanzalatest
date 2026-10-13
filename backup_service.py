"""Create daily per-company backups independently of the desktop window."""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from company_manager import CompanyManager


def backup_all(master_path):
    master_path = Path(master_path)
    if not master_path.is_file():
        return []
    # 2.9.87: the background backup only copies the files. It used to upgrade them too (an older backup program still
    # running after an update fought with the new program over the same files: "database is locked", the program could
    # not start and the setup could not replace the backup program).
    manager = CompanyManager(master_path, prepare=False)
    made = []
    for company in manager.list_companies(True):
        for year in company.get("years", []):
            try:
                database = manager.database(company["id"], year["year"])
                path = database.maybe_scheduled_backup()
                if path:
                    made.append(path)
            except Exception:
                logging.exception("Backup failed for %s / %s", company["id"], year.get("year"))
    return made


def _data_dir():
    import app_runtime
    return app_runtime.data_dir()


def _main_database():
    """The main file name used by the program; the backup service never renames anything itself."""
    import app_runtime
    folder = app_runtime.data_dir()
    new, old = folder/app_runtime.MAIN_DATABASE_NAME, folder/app_runtime.OLD_MAIN_DATABASE_NAME
    return new if new.exists() or not old.exists() else old


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--database", default=None, help="Main data file (default: the Saber data folder)")
    args = parser.parse_args()
    log_dir = Path(args.database).parent if args.database else _data_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_dir/"backup_service.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    while True:
        try:
            # Looked up every cycle: the main file may be renamed by the program (2.9.41) while this runs.
            database = args.database or str(_main_database())
            for path in backup_all(database):
                logging.info("Backup created: %s", path)
        except Exception:
            logging.exception("Automatic backup cycle failed")
        if args.once:
            break
        time.sleep(3600)


if __name__ == "__main__":
    main()
