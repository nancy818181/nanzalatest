from __future__ import annotations
import logging
import os

import json
import re
import secrets
import sqlite3
from contextlib import closing
import uuid
from datetime import datetime
from pathlib import Path

from database import Database, utcnow


class CompanyManager:
    """Keeps every company/fiscal year in its own SQLite file."""

    def __init__(self, master_database, pooled=False, prepare=True):
        self.pooled=pooled  # the running data service keeps each company file open (faster)
        self.prepare=prepare  # 2.9.87: False for the background backup - it copies files, it never upgrades them
        self.master_path=Path(master_database).resolve()
        self.root=self.master_path.parent/"companies"; self.root.mkdir(parents=True,exist_ok=True)
        self.registry_path=self.root/"companies.json"; self._cache={}
        if not self.registry_path.exists():
            # 2.9.74: a new installation starts with NO company: the administrator creates his own (Create Company).
            # Installations that already have companies keep them exactly as they are, and a main file from a version
            # before the company list (books kept in the main file) still opens as a company under its own name.
            first=self._first_company()
            self._write({"companies":[first] if first else []})

    def _first_company(self):
        """None for a new installation. The tests ask for a sample company with SABER_FIRST_COMPANY="Name|year"
        (kept in the main file, as the versions before the company list did)."""
        seed=os.environ.get("SABER_FIRST_COMPANY","").strip()
        if seed:
            name,_,year=seed.partition("|")
            return {"id":re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-") or "company","name":name.strip(),"active":True,
                    "years":[{"year":int(year or datetime.now().year),"database":str(self.master_path),"status":"open"}]}
        if not self.master_path.exists(): return None
        try:
            with closing(sqlite3.connect(f"file:{self.master_path}?mode=ro",uri=True)) as db:
                tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "journal_entries" not in tables or not db.execute("SELECT 1 FROM journal_entries LIMIT 1").fetchone(): return None
                days=[str(row[0]) for row in db.execute("SELECT entry_date FROM journal_entries")]
                name=db.execute("SELECT value FROM app_settings WHERE key='company_name'").fetchone() if "app_settings" in tables else None
        except sqlite3.Error:
            return None
        found=[(day[:4] if day[4:5]=="-" else day[6:10]) for day in days if len(day)>=10]  # YYYY-MM-DD or DD-MM-YYYY
        years=sorted({int(y) for y in found if y.isdigit()})
        name=(name[0] if name and str(name[0] or "").strip() else "My Company")
        return {"id":re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-") or "my-company","name":name,"active":True,
                "years":[{"year":y,"database":str(self.master_path),"status":"open"} for y in (years[:1] or [datetime.now().year])]}

    # ------------------------------------------------------------ files named after the company
    @staticmethod
    def safe_name(name, fallback="company"):
        """The company name as it can be used for a Windows folder / file name (same rule as the backups)."""
        text="".join(ch for ch in str(name or "") if ch.isalnum() or ch in " -_&.").strip()
        if text not in ("", ".", ".."): return text
        safe_fallback="".join(ch for ch in str(fallback or "") if ch.isalnum() or ch in " -_&.").strip()
        return safe_fallback if safe_fallback not in ("", ".", "..") else "company"

    def company_folder(self, company, data=None):
        """companies/<Company Name>/ - two companies with the same name get their id added."""
        safe=self.safe_name(company.get("name"),company.get("id") or "company")
        others=[c for c in (data or self._read())["companies"] if c.get("id")!=company.get("id")]
        if any(self.safe_name(c.get("name"),c.get("id")).casefold()==safe.casefold() for c in others): safe=f'{safe} ({company.get("id")})'
        folder=(self.root/safe).resolve()
        if self.root.resolve() not in folder.parents: raise ValueError("Company folder must stay inside the companies directory")
        return folder

    def year_file(self, company, year, data=None):
        """companies/<Company Name>/<Company Name>_<year>.db - named like the backups (<Company Name>_<year>_<date>.db)."""
        folder=self.company_folder(company,data)
        return folder/f"{folder.name}_{int(year)}.db"

    def _database_path(self,value):
        path=Path(value).resolve()
        if self._inside(path): return path
        moved=self._relocated(value)  # 2.9.75: the data folder was copied to another computer / Windows user
        if moved is not None: return moved
        raise ValueError("Company database path must be inside the application data directory")

    def _inside(self,path):
        company_directory=self.root.resolve()
        return path==self.master_path or (path.suffix.lower()==".db" and (company_directory in path.parents or path.parent==self.master_path.parent))

    def _relocated(self,value):
        """The same file in THIS data folder, when the company list was written in another place (the SaberAccounting folder
        copied to a new computer or another Windows user: C:/Users/<old name>/... -> C:/Users/<new name>/...)."""
        parts=[part for part in str(value).replace("\\","/").split("/") if part]
        if not parts or not parts[-1].lower().endswith(".db"): return None
        lowered=[part.lower() for part in parts]
        if "companies" in lowered:
            index=len(lowered)-1-lowered[::-1].index("companies")
            candidate=self.root.joinpath(*parts[index+1:])
        else:
            candidate=self.master_path.parent/parts[-1]
        candidate=candidate.resolve()
        return candidate if self._inside(candidate) and candidate.is_file() else None

    def organize_files(self, only_company_id=None):
        """Move every company-year file to companies/<Company Name>/<Company Name>_<year>.db.

        Each file is copied with SQLite's backup (a consistent copy), checked (integrity and the number of
        rows of every table), the company list is updated, and only then is the old file removed. The main
        file (users and passwords) is never removed: a company year that was kept inside it is copied out.
        A file that cannot be moved now (for example open in another program) keeps working where it is
        and is moved on a later start. Returns the list of moves."""
        import os
        data=self._read(); moved=[]
        for company in data["companies"]:
            if only_company_id and company.get("id")!=only_company_id: continue
            for fiscal in company.get("years",[]):
                try: source=self._database_path(fiscal["database"])
                except (KeyError,TypeError,ValueError): continue
                target=self.year_file(company,fiscal["year"],data).resolve()
                if source==target or not source.exists(): continue
                if target.exists(): continue  # never overwrite; resolve by hand
                cached=self._cache.pop(str(source),None)
                if cached is not None: cached.release()
                try:
                    target.parent.mkdir(parents=True,exist_ok=True)
                    temporary=target.with_suffix(".moving")
                    if temporary.exists(): temporary.unlink()
                    with closing(sqlite3.connect(str(source))) as old,closing(sqlite3.connect(str(temporary))) as new: old.backup(new)
                    with closing(sqlite3.connect(str(source))) as old,closing(sqlite3.connect(str(temporary))) as new:
                        if new.execute("PRAGMA integrity_check").fetchone()[0]!="ok": raise ValueError("copy failed the integrity check")
                        for (table,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
                            if old.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]!=new.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]:
                                raise ValueError(f"table {table} differs after the copy")
                    os.replace(temporary,target)
                except Exception:
                    try: temporary.unlink()
                    except Exception: logging.getLogger("saber.ignored").debug("Ignored error", exc_info=True)
                    continue
                fiscal["database"]=str(target); self._write(data); moved.append((str(source),str(target)))
                if source!=self.master_path.resolve():
                    for suffix in ("","-wal","-shm"):
                        try: Path(str(source)+suffix).unlink()
                        except FileNotFoundError: pass
                        except OSError: pass
                    try: source.parent.rmdir()  # the old id-named folder, when it is now empty
                    except OSError: pass
        return moved

    def _read(self):
        try: return json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception: return {"companies":[]}

    def _write(self,data):
        temporary=self.registry_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8"); temporary.replace(self.registry_path)

    def list_companies(self,include_inactive=False):
        companies=self._read()["companies"]
        return companies if include_inactive else [c for c in companies if c.get("active",True)]

    def _company(self,company_id):
        company=next((c for c in self._read()["companies"] if c["id"]==company_id),None)
        if not company: raise KeyError("Company not found")
        return company

    def database(self,company_id=None,year=None):
        companies=self.list_companies(True)
        if not companies: raise KeyError("No company is configured")
        company=next((c for c in companies if c["id"]==company_id),None) if company_id else companies[0]
        if not company: raise KeyError("Company not found")
        years=company.get("years",[])
        selected=next((y for y in years if int(y["year"])==int(year)),None) if year else (max(years,key=lambda y:int(y["year"])) if years else None)
        if not selected: raise KeyError("Fiscal year not found")
        path=str(self._database_path(selected["database"]))
        if path!=str(Path(selected["database"]).resolve()):  # 2.9.75: remember the new place of a moved data folder
            try:
                data=self._read()
                for entry in data["companies"]:
                    for fiscal in entry.get("years",[]):
                        if entry["id"]==company["id"] and int(fiscal["year"])==int(selected["year"]): fiscal["database"]=path
                self._write(data)
            except Exception: logging.getLogger("saber.company").warning("Moved company file not saved in the list", exc_info=True)
        if path not in self._cache:
            database=Database(path,pooled=self.pooled)
            safe=self.safe_name(company["name"],company["id"])
            database.backup_folder=str(self.master_path.parent/"backups"/safe/str(selected["year"])); database.backup_label=f'{safe}_{selected["year"]}'
            # Bring files made by an older version up to date (new tables and columns); existing data is kept.
            if self.prepare and Path(path).exists() and Path(path)!=self.master_path: database.initialize_if_needed(secrets.token_urlsafe(24))
            self._cache[path]=database
        return self._cache[path]

    def year_databases(self,company_id):
        """2.9.83: {year: database} of every fiscal year of a company (for what is entered once for all years)."""
        companies=self.list_companies(True)
        company=next((c for c in companies if c["id"]==company_id),None) if company_id else (companies[0] if companies else None)
        if not company: return {}
        result={}
        for fiscal in company.get("years",[]):
            try: result[int(fiscal["year"])]=self.database(company["id"],int(fiscal["year"]))
            except Exception: logging.getLogger("saber.company").warning("Fiscal year %s not opened", fiscal.get("year"), exc_info=True)
        return result

    def year_status(self,company_id,year):
        company=self._company(company_id)
        selected=next((item for item in company.get("years",[]) if int(item["year"])==int(year)),None)
        if not selected: raise KeyError("Fiscal year not found")
        return selected.get("status","open")

    def create_company(self,item,master_db):
        name=str(item.get("name") or "").strip(); year=int(item.get("year") or datetime.now().year)
        if not name or year<2000 or year>2100: raise ValueError("Enter a valid company name and fiscal year")
        # 2.9.71: the two main currencies of this company (default USD and LBP), chosen when it is created
        main=[str(item.get(key) or default).strip().upper() for key,default in (("main_currency_1","USD"),("main_currency_2","LBP"))]
        if main[0]==main[1]: raise ValueError("The two main currencies must be different")
        for code in main:
            if not re.fullmatch(r"[A-Z]{3}",code): raise ValueError(f"Currency {code or '(empty)'} must be a 3-letter code (for example EUR)")
        # 2.9.72: the VAT of this company: rate and the two currencies of its VAT return (default 11%, LBP with USD)
        from database_common import parse_vat_rate
        vat_rate=parse_vat_rate(item.get("vat_rate") if str(item.get("vat_rate") or "").strip() else "11")
        vat_pair=[str(item.get(key) or default).strip().upper() for key,default in (("vat_currency_1","LBP"),("vat_currency_2","USD"))]
        if vat_pair[0]==vat_pair[1]: raise ValueError("The two VAT currencies must be different")
        for code in vat_pair:
            if not re.fullmatch(r"[A-Z]{3}",code): raise ValueError(f"VAT currency {code or '(empty)'} must be a 3-letter code (for example AED)")
        data=self._read(); company_id=re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-") or uuid.uuid4().hex[:10]
        if any(c["id"]==company_id or c["name"].casefold()==name.casefold() for c in data["companies"]): raise ValueError("Company already exists")
        company_id=f"{company_id}-{uuid.uuid4().hex[:6]}"
        path=self.year_file({"id":company_id,"name":name},year,data); path.parent.mkdir(parents=True,exist_ok=True)
        target=Database(path); target.initialize(secrets.token_urlsafe(24))
        # 2.9.90 (owner): a new company starts with the standard chart only - the accounts, customers / suppliers,
        # branches and settings of the other companies (kept in the main file) are not copied; the users are.
        self._copy_master_data(master_db,target,tables=("users",))
        with target.connect() as db:
            for code in main+vat_pair: db.execute("INSERT OR IGNORE INTO currencies(code,name) VALUES(?,?)",(code,code))
        settings={"base_currency":main[0],"second_currency":main[1],"vat_rate":str(vat_rate),"vat_currency":vat_pair[0],"vat_second_currency":vat_pair[1],
                "company_name":name,"company_address":item.get("address","").strip(),"company_phone":item.get("phone","").strip(),
            "company_mof":item.get("mof_number","").strip(),"company_email":item.get("email","").strip(),"company_website":item.get("website","").strip()}
        with target.connect() as db:
            for key,value in settings.items(): db.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,value))
        if item.get("vat_by_party",True):  # 2.9.97: Lebanese practice - every customer / supplier has its own VAT account (Accounting Setup to change)
            import vat_ledgers
            vat_ledgers.save_settings(target,{"enabled":True})
        company={"id":company_id,"name":name,"active":True,"years":[{"year":year,"database":str(path.resolve()),"status":"open"}]}
        data["companies"].append(company); self._write(data); return company

    # ------------------------------------------------------------ 2.9.108: company files brought from another computer
    @staticmethod
    def read_company_file(path):
        """(company name, fiscal year) of a Saber company file; ValueError when the file is not one."""
        path=Path(path)
        if not path.is_file(): raise ValueError(f"File not found: {path}")
        try:
            with closing(sqlite3.connect(f"file:{path}?mode=ro",uri=True)) as db:
                tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"journal_entries","app_settings","accounts"}<=tables: raise ValueError(f"{path.name} is not a Nanza Accounting company file")
                if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok": raise ValueError(f"{path.name} is damaged (integrity check failed)")
                row=db.execute("SELECT value FROM app_settings WHERE key='company_name'").fetchone()
                days=[str(r[0]) for r in db.execute("SELECT entry_date FROM journal_entries")]
        except sqlite3.Error as exc:
            raise ValueError(f"{path.name} cannot be read as a Nanza Accounting company file: {exc}") from exc
        name=str(row[0]).strip() if row and str(row[0] or "").strip() else re.sub(r"_\d{4}$","",path.stem).strip() or "Company"
        named=re.search(r"_(\d{4})$",path.stem)
        if named: year=int(named.group(1))
        else:
            found=[(d[:4] if d[4:5]=="-" else d[6:10]) for d in days if len(d)>=10]
            found=[int(y) for y in found if y.isdigit()]
            year=max(set(found),key=found.count) if found else datetime.now().year
        return name,year

    def add_company_file(self,source,copy=True):
        """Add a company file copied from another computer: a new company, or a new fiscal year of the company with the
        same name. The file is copied into companies/<Company Name>/ (the original is left untouched) and checked."""
        source=Path(source).resolve(); name,year=self.read_company_file(source)
        data=self._read()
        known={str(self._database_path(f["database"])) for c in data["companies"] for f in c.get("years",[]) if f.get("database")}
        if str(source) in known: raise ValueError(f"{source.name} is already in the company list")
        company=next((c for c in data["companies"] if c["name"].casefold()==name.casefold()),None)
        if company and any(int(f["year"])==year for f in company.get("years",[])):
            raise ValueError(f"{name} already has the year {year} on this computer - rename or remove it first")
        if not company:
            base=re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-") or "company"
            company={"id":f"{base}-{uuid.uuid4().hex[:6]}","name":name,"active":True,"years":[]}
            data["companies"].append(company)
        target=source
        if copy:
            target=self.year_file(company,year,data).resolve()
            if target!=source:
                if target.exists(): raise ValueError(f"{target} already exists - it was not overwritten")
                target.parent.mkdir(parents=True,exist_ok=True)
                with closing(sqlite3.connect(f"file:{source}?mode=ro",uri=True)) as old,closing(sqlite3.connect(str(target))) as new: old.backup(new)
        company["years"].append({"year":year,"database":str(target),"status":"open"})
        company["years"].sort(key=lambda f:int(f["year"]))
        self._write(data)
        return company

    def discover_files(self):
        """Company files placed in the companies folder by hand (copied from another computer) that are not in the list yet
        are added. Returns [(file, company name, year)]."""
        data=self._read()
        known={str(self._database_path(f["database"])) for c in data["companies"] for f in c.get("years",[]) if f.get("database")}
        added=[]
        for path in sorted(self.root.glob("*/*.db"))+sorted(self.root.glob("*.db")):
            resolved=path.resolve()
            if str(resolved) in known or resolved==self.master_path: continue
            try:
                company=self.add_company_file(resolved,copy=False)
                added.append((str(resolved),company["name"],max(int(f["year"]) for f in company["years"])))
            except ValueError as exc:
                logging.getLogger("saber.company").info("Company file not added: %s", exc)
        return added

    def update_company(self,company_id,item):
        data=self._read(); company=next((c for c in data["companies"] if c["id"]==company_id),None)
        if not company: raise KeyError("Company not found")
        old_backups=self.master_path.parent/"backups"/self.safe_name(company["name"],company["id"])
        if str(item.get("name") or "").strip(): company["name"]=str(item["name"]).strip()
        if "active" in item: company["active"]=bool(item["active"])
        self._write(data)
        for year in company.get("years",[]):
            db=Database(self._database_path(year["database"]))
            with db.connect() as connection:
                connection.execute("INSERT INTO app_settings(key,value) VALUES('company_name',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(company["name"],))
        # A renamed company: its files and its backups folder follow the new name.
        self.organize_files(company_id)
        new_backups=self.master_path.parent/"backups"/self.safe_name(company["name"],company["id"])
        if old_backups!=new_backups and old_backups.is_dir() and not new_backups.exists():
            try: old_backups.rename(new_backups)
            except OSError: pass
        if old_backups.name!=new_backups.name:  # 2.9.53: the second copy (OneDrive / USB) follows the new name too
            try:
                import backup_copy
                backup_copy.rename_company(old_backups.name,new_backups.name)
            except Exception: logging.getLogger("saber").warning("Second backup copy folder not renamed",exc_info=True)
        for path in [p for p in self._cache]: self._cache.pop(path).release()  # backup folders are set again on next use
        return next(c for c in self._read()["companies"] if c["id"]==company_id)

    def create_year(self,company_id,year,user_id):
        year=int(year)
        if year<2000 or year>2100: raise ValueError("Enter a valid fiscal year")
        data=self._read(); company=next((c for c in data["companies"] if c["id"]==company_id),None)
        if not company: raise KeyError("Company not found")
        if any(int(y["year"])==year for y in company["years"]): raise ValueError("Fiscal year already exists")
        previous=max((y for y in company["years"] if int(y["year"])<year),key=lambda y:int(y["year"]),default=None)
        if not previous: raise ValueError("Create fiscal years in chronological order")
        source=Database(self._database_path(previous["database"]))
        import fixed_assets
        fixed_assets.check_carry_forward(source,year)
        path=self.year_file(company,year,data); path.parent.mkdir(parents=True,
                exist_ok=True); target=Database(path); target.initialize(secrets.token_urlsafe(24)); self._copy_master_data(source,target)
        import inventory
        inventory.carry_forward(source,target,year,user_id)
        fixed_assets.carry_forward(source,target,year)
        self._carry_year_data(source,target,year)  # 2.9.84: employees, rates, asset accounts, departments / projects
        company["years"].append({"year":year,"database":str(path.resolve()),"status":"open"}); company["years"].sort(key=lambda y:int(y["year"]))
        self._write(data); return company

    def delete_year(self,company_id,year,user_id):
        """Remove the LAST fiscal year of a company (for example to redo the opening). The file is kept as a backup
        in the company's 'deleted_years' folder, and the previous year is reopened (its closing is removed)."""
        from datetime import datetime as _dt
        year=int(year); data=self._read(); company=next((c for c in data["companies"] if c["id"]==company_id),None)
        if not company: raise KeyError("Company not found")
        years=sorted(company.get("years",[]),key=lambda y:int(y["year"]))
        current=next((y for y in years if int(y["year"])==year),None)
        if not current: raise ValueError(f"Fiscal year {year} was not found for this company")
        if int(years[-1]["year"])!=year: raise ValueError(f"Only the last fiscal year can be deleted ({years[-1]['year']}). Delete the later years first.")
        if len(years)==1: raise ValueError("The only fiscal year of a company cannot be deleted")
        path=self._database_path(current["database"])
        if path==self.master_path.resolve(): raise ValueError("This year uses the main database file and cannot be deleted")
        backup_folder=self.company_folder(company,data)/"deleted_years"; backup_folder.mkdir(parents=True,exist_ok=True)
        token=uuid.uuid4().hex[:8]
        backup=backup_folder/f"{year}_deleted_{_dt.now():%Y%m%d_%H%M%S}_{token}.db"
        temporary=backup.with_suffix(".partial")
        retired=path.with_name(f"{path.name}.deleting-{token}")
        previous=years[-2]
        # A WAL-mode .db alone can omit committed transactions. Snapshot through SQLite
        # while blocking other requests for this company-year, then verify the archive.
        database=self.database(company_id,year)
        with database._lock:
            cached=self._cache.pop(str(path),None)
            if cached is not None: cached.release()
            if not path.is_file(): raise ValueError("The fiscal-year database file was not found; the year was not deleted")
            try:
                with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)) as source, \
                     closing(sqlite3.connect(str(temporary))) as archive:
                    source.backup(archive)
                Database._validate_backup_file(temporary)
                # Refuse to remove a file with readers holding an uncheckpointed WAL.
                with closing(sqlite3.connect(str(path))) as source:
                    if source.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                        raise ValueError("Close other programs using this fiscal year before deleting it")
                try:
                    path.replace(retired)
                except PermissionError as exc:
                    raise ValueError("Close other programs using this fiscal year before deleting it") from exc
                try:
                    temporary.replace(backup)
                    company["years"]=[y for y in company["years"] if int(y["year"])!=year]
                    self._write(data)
                except Exception:
                    retired.replace(path)
                    raise
            finally:
                if temporary.exists(): temporary.unlink()
            for suffix in ("-wal","-shm"):
                try: Path(str(path)+suffix).unlink()
                except OSError: pass
            try: retired.unlink()
            except OSError: pass  # archive is verified; leave a second copy rather than risk data loss
        reopened=self.reopen_year(company_id,int(previous["year"]),user_id)
        return {"deleted_year":year,"backup":str(backup),"reopened_year":int(previous["year"]),"removed_closing_entries":reopened.get("removed_closing_entries",0),
                "company":reopened["company"]}

    def reopen_year(self,company_id,year,user_id):
        year=int(year); data=self._read(); company=next((c for c in data["companies"] if c["id"]==company_id),None)
        if not company: raise KeyError("Company not found")
        current=next((item for item in company.get("years",[]) if int(item["year"])==year),None)
        if not current: raise ValueError("Fiscal year not found for this company")
        result=Database(self._database_path(current["database"])).reopen_fiscal_year(year,user_id)
        current["status"]="open"
        next_year=next((item for item in company.get("years",[]) if int(item["year"])==year+1),None)
        removed_opening=0
        if next_year:
            with Database(self._database_path(next_year["database"])).connect() as db:
                ids=[row["id"] for row in db.execute("SELECT id FROM journal_entries WHERE source_type='opening' AND entry_number LIKE ?",(f"OPEN-{year+1}-%",))]
                for entry_id in ids: db.execute("DELETE FROM journal_entries WHERE id=?",(entry_id,))
                removed_opening=len(ids)
        self._write(data); return {**result,"company":company,"removed_opening_entries":removed_opening}

    def refresh_opening(self,company_id,source_year,user_id):
        source_year=int(source_year); target_year=source_year+1; company=self._company(company_id)
        source_record=next((item for item in company.get("years",[]) if int(item["year"])==source_year),None)
        target_record=next((item for item in company.get("years",[]) if int(item["year"])==target_year),None)
        if not source_record or not target_record: raise ValueError(f"Both fiscal years {source_year} and {target_year} must exist")
        source=Database(self._database_path(source_record["database"])); target=Database(self._database_path(target_record["database"]))
        with target.connect() as db:
            ids=[row["id"] for row in db.execute("SELECT id FROM journal_entries WHERE source_type='opening' AND entry_number LIKE ?",(f"OPEN-{target_year}-%",))]
            for entry_id in ids: db.execute("DELETE FROM journal_entries WHERE id=?",(entry_id,))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"refresh_opening","fiscal_year",target_year,json.dumps({"source_year":source_year,"replaced":len(ids)}),utcnow()))
        vouchers=self._opening_balances(source,target,target_year,user_id)
        import inventory
        inventory.carry_forward(source,target,target_year,user_id)
        return {"source_year":source_year,"target_year":target_year,"opening_vouchers":vouchers,"replaced":len(ids),"provisional":source_record.get("status")!="closed"}

    def close_and_open_year(self,company_id,year,user_id):
        """Close one company year, create its next database, and post opening vouchers."""
        year=int(year); next_year=year+1; data=self._read()
        company=next((c for c in data["companies"] if c["id"]==company_id),None)
        if not company: raise KeyError("Company not found")
        current=next((y for y in company.get("years",[]) if int(y["year"])==year),None)
        if not current: raise ValueError("Fiscal year not found for this company")
        next_record=next((item for item in company.get("years",[]) if int(item["year"])==next_year),None)
        source=Database(self._database_path(current["database"]))
        source_backup=source.backup("safety")
        next_path=self._database_path(next_record["database"]) if next_record else None
        target_backup=Database(next_path).backup("safety") if next_path else None
        try:
            close_result=source.close_fiscal_year(year,user_id)
            current["status"]="closed"
            if next_record:
                path=next_path; target=Database(path)
                with target.connect() as db:
                    ids=[row["id"] for row in db.execute("SELECT id FROM journal_entries WHERE source_type='opening' AND entry_number LIKE ?",(f"OPEN-{next_year}-%",))]
                    for entry_id in ids: db.execute("DELETE FROM journal_entries WHERE id=?",(entry_id,))
            else:
                path=self.year_file(company,next_year,data); path.parent.mkdir(parents=True,exist_ok=True)
                target=Database(path); target.initialize(secrets.token_urlsafe(24)); self._copy_master_data(source,target)
            opening_vouchers=self._opening_balances(source,target,next_year,user_id)
            import inventory
            stock_openings=inventory.carry_forward(source,target,next_year,user_id)
            # 2.9.84: Close & Open used to leave the new year without employees, fixed-asset register, asset accounts,
            # exchange rates, departments / projects and the payroll posting accounts
            import fixed_assets
            with target.connect() as db: has_assets=db.execute("SELECT 1 FROM fixed_assets LIMIT 1").fetchone()
            if not has_assets:
                try: fixed_assets.carry_forward(source,target,next_year)
                except ValueError: logging.getLogger("saber.company").warning("Fixed assets not carried (depreciation not posted)",exc_info=True)
            self._carry_year_data(source,target,next_year)
            if not next_record: company["years"].append({"year":next_year,"database":str(path.resolve()),"status":"open"})
            company["years"].sort(key=lambda item:int(item["year"]))
            self._write(data)
        except Exception:
            # Restore both company-year files to their pre-close state; keep the safety copies.
            with closing(sqlite3.connect(source_backup)) as old,closing(sqlite3.connect(source.path)) as live: old.backup(live)
            if target_backup:
                with closing(sqlite3.connect(target_backup)) as old,closing(sqlite3.connect(next_path)) as live: old.backup(live)
            raise
        return {**close_result,"company":company,"opening_vouchers":opening_vouchers,"stock_openings":stock_openings}

    def _carry_year_data(self,source,target,year):
        """2.9.84: what the next fiscal year needs from the previous one besides the accounts and the parties:
        employees (their leave balance and end-of-service contributions carried), asset accounts, exchange rates,
        departments, projects and the payroll settings. Rows already in the new year are kept."""
        import payroll_extras
        def columns(db,table): return [row["name"] for row in db.execute(f'PRAGMA table_info("{table}")')]
        import fixed_assets
        with target.connect() as dst: fixed_assets._migrate_categories(dst)  # the asset accounts table is made when first used
        with source.connect() as src, target.connect() as dst:
            for table in ("asset_categories","exchange_rates","exchange_rate_samples","departments","projects","employees"):
                try: rows=src.execute(f'SELECT * FROM "{table}"').fetchall()
                except sqlite3.OperationalError: continue
                if not rows: continue
                wanted=[c for c in rows[0].keys() if c in set(columns(dst,table))]
                if not wanted: continue
                dst.executemany(f'INSERT OR IGNORE INTO "{table}"({",".join(wanted)}) VALUES({",".join("?"*len(wanted))})',[tuple(row[c] for c in wanted) for row in rows])
            # payroll settings with the company's own posting accounts (the new file starts with the program's)
            settings=src.execute("SELECT * FROM payroll_settings").fetchall()
            if settings:
                wanted=[c for c in settings[0].keys() if c in set(columns(dst,"payroll_settings")) and c!="id"]
                dst.execute("DELETE FROM payroll_settings")
                dst.executemany(f'INSERT INTO payroll_settings({",".join(wanted)}) VALUES({",".join("?"*len(wanted))})',[tuple(row[c] for c in wanted) for row in settings])
        # end-of-service contributions and leave carried into the employee files of the new year
        try:
            paid={}
            with source.connect() as src:
                for row in src.execute("SELECT employee_id,currency,period_date,employer_end_service FROM payroll_records WHERE status='posted'"):
                    paid[row["employee_id"]]=paid.get(row["employee_id"],0)+payroll_extras._lbp(source,row["employer_end_service"],row["currency"],row["period_date"])
            balances={r["employee_id"]:r["balance"] for r in payroll_extras.leave_balances(source,f"31-12-{int(year)-1}",with_ids=True)["rows"]}
            with source.connect() as src: before={r["id"]:r["eos_paid_before"] for r in src.execute("SELECT id,eos_paid_before FROM employees")}
            with target.connect() as dst:
                for employee_id,amount in paid.items():
                    total=payroll_extras._d(before.get(employee_id))+amount
                    dst.execute("UPDATE employees SET eos_paid_before=? WHERE id=?",(str(total.quantize(payroll_extras.Decimal("1"))),employee_id))
                for employee_id,balance in balances.items():
                    dst.execute("UPDATE employees SET leave_carried=? WHERE id=?",(str(balance),employee_id))
        except Exception: logging.getLogger("saber.company").warning("End-of-service / leave balances not carried",exc_info=True)

    def _copy_master_data(self,source,target,tables=("users","accounts","parties","branches","app_settings")):
        with source.connect() as src, target.connect() as dst:
            for table in tables:
                rows=src.execute(f"SELECT * FROM {table}").fetchall()
                if not rows: continue
                columns=list(rows[0].keys())
                if table=="accounts": dst.execute("UPDATE accounts SET parent_id=NULL")
                dst.execute(f"DELETE FROM {table}")
                placeholders=",".join("?" for _ in columns)
                if table=="accounts" and "parent_id" in columns:
                    # insert with parent_id detached, then re-link by code so row order never trips the FK
                    pid=columns.index("parent_id"); code_by_id={row["id"]:row["code"] for row in rows}
                    detached=[]
                    for row in rows:
                        vals=list(row[col] for col in columns); vals[pid]=None; detached.append(tuple(vals))
                    dst.executemany(f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})",detached)
                    for row in rows:
                        if row["parent_id"] and row["parent_id"] in code_by_id:
                            dst.execute("UPDATE accounts SET parent_id=(SELECT id FROM accounts WHERE code=?) WHERE code=?",(code_by_id[row["parent_id"]],row["code"]))
                else:
                    dst.executemany(f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})",[tuple(row[col] for col in columns) for row in rows])
            # 2.9.71: currencies added to the company (for example its main currencies GBP / CHF) reach the new year too
            dst.executemany("INSERT OR IGNORE INTO currencies(code,name) VALUES(?,?)",[(row["code"],row["name"]) for row in src.execute("SELECT code,name FROM currencies")])

    def _opening_balances(self,source,target,year,user_id):
        import year_end
        return year_end.post_opening(source,target,year,user_id)
