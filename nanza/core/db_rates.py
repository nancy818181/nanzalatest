"""Exchange rates: saving, automatic download, and conversion of amounts.

Part of the Database class (split out of database.py in 2.9.63, code unchanged): Database inherits from RatesStore."""
from __future__ import annotations

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, Decimal, iso_date, json, logging, timedelta, urllib, utcnow
)
from database_common import _soft_iso  # noqa: F401


class RatesStore:
    def save_exchange_rate(self, item, user_id):
        self.__dict__.pop("_rate_state", None)  # 2.9.58: rates change - forget the cached ones
        date_from=str(item.get("date_from") or item.get("rate_date") or "").strip(); date_to=str(item.get("date_to") or date_from).strip()
        self._date_year(date_from); self._date_year(date_to)
        def parsed(value):
            for pattern in ("%d-%m-%Y","%Y-%m-%d"):
                try: return datetime.strptime(value,pattern).date()
                except ValueError: pass
            raise ValueError("Date must use DD-MM-YYYY")
        start=parsed(date_from); end=parsed(date_to)
        if end<start: raise ValueError("Date To cannot be before Date From")
        if (end-start).days>3660: raise ValueError("Exchange-rate period cannot exceed 10 years")
        source=str(item.get("from_currency") or "").upper(); target=str(item.get("to_currency") or "").upper()
        rate=Decimal(str(item.get("rate") or 0))
        if source not in self.currency_codes() or target not in self.currency_codes() or source==target or rate<=0:
            raise ValueError("Enter two different currencies and a positive rate")
        with self.connect() as db:
            rows=[]; current=start
            while current<=end:
                rows.append((current.strftime("%d-%m-%Y"),source,target,str(rate),user_id,utcnow())); current+=timedelta(days=1)
            db.executemany("INSERT INTO exchange_rate_samples(rate_date,from_currency,to_currency,rate,created_by,created_at) VALUES(?,?,?,?,?,?)", rows)
            averaged=[]
            for rate_date,_,_,_,_,_ in rows:
                values=[Decimal(sample["rate"]) for sample in db.execute("SELECT rate FROM exchange_rate_samples WHERE rate_date=? AND from_currency=? AND to_currency=?",(rate_date,source,target))]
                averaged.append((rate_date,source,target,str(sum(values)/len(values)),user_id,utcnow()))
            db.executemany("""INSERT INTO exchange_rates(rate_date,from_currency,to_currency,rate,created_by,created_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(rate_date,from_currency,to_currency) DO UPDATE SET rate=excluded.rate,
                created_by=excluded.created_by,created_at=excluded.created_at""",averaged)
            if (source,target) in (("EUR","USD"),("USD","LBP")):
                derived=[]
                for rate_date,_,_,_,_,_ in rows:
                    eur_usd=next((Decimal(x[3]) for x in averaged if x[0]==rate_date),None) if (source,target)==("EUR","USD") else None
                    usd_lbp=next((Decimal(x[3]) for x in averaged if x[0]==rate_date),None) if (source,target)==("USD","LBP") else None
                    if eur_usd is None:
                        found=db.execute("SELECT rate FROM exchange_rates WHERE rate_date=? AND from_currency='EUR' AND to_currency='USD'",(rate_date,)).fetchone()
                        eur_usd=Decimal(str(found["rate"])) if found else Decimal("1")
                    if usd_lbp is None:
                        found=db.execute("SELECT rate FROM exchange_rates WHERE rate_date=? AND from_currency='USD' AND to_currency='LBP'",(rate_date,)).fetchone()
                        usd_lbp=Decimal(str(found["rate"])) if found else Decimal("89500")
                    derived.append((rate_date,"EUR","LBP",str(eur_usd*usd_lbp),user_id,utcnow()))
                db.executemany("""INSERT INTO exchange_rates(rate_date,from_currency,to_currency,rate,created_by,created_at)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(rate_date,from_currency,to_currency) DO UPDATE SET rate=excluded.rate,
                    created_by=excluded.created_by,created_at=excluded.created_at""",derived)
        return {"date_from":date_from,"date_to":date_to,"days":len(rows),"calculation":"average of manually entered daily rates"}

    def list_exchange_rates(self):
        loaded=self.settings().get("exchange_history_loaded_through","")
        expected=(datetime.now().date()-datetime(2024,1,1).date()).days+1
        with self.connect() as db:
            eur_days=db.execute("SELECT COUNT(DISTINCT rate_date) count FROM exchange_rates WHERE from_currency='EUR' AND to_currency='USD'").fetchone()["count"]
        # 2.9.58: the internet is asked at most once every 6 hours. Before, every refresh of a screen that shows rates
        # (Uploaded Data after each save, sales invoice ...) could wait up to 30 seconds when offline.
        if (loaded!=datetime.now().date().isoformat() or eur_days<expected) and self._may_download_rates("history"): self.sync_historical_exchange_rates()
        self._ensure_automatic_rates()
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT r.id,r.rate_date,r.from_currency,r.to_currency,CAST(r.rate AS REAL) rate,r.created_at,
                COALESCE(s.samples,0) samples FROM exchange_rates r
                LEFT JOIN (SELECT rate_date,from_currency,to_currency,COUNT(*) samples FROM exchange_rate_samples GROUP BY rate_date,from_currency,to_currency) s
                  ON s.rate_date=r.rate_date AND s.from_currency=r.from_currency AND s.to_currency=r.to_currency
                ORDER BY r.id DESC""")]  # 2.9.91: one pass instead of one count per rate

    _RATE_DOWNLOADS = {}

    def _may_download_rates(self, kind, hours=6):
        """True when the EUR rates were not asked from the internet for this file in the last `hours`."""
        import time as _time
        key = (str(self.path), kind); now = _time.time()
        if now - type(self)._RATE_DOWNLOADS.get(key, 0) < hours * 3600: return False
        type(self)._RATE_DOWNLOADS[key] = now
        return True

    DAILY_PEGGED = ("AED", "SAR")  # 2.9.78: filled every day like EUR (fixed to the US dollar, no internet needed)

    def _pegged_rows(self, display):
        """AED / SAR -> USD and -> LBP for one day (DD-MM-YYYY), for the currencies the company has."""
        codes=self.currency_codes(); rows=[]
        for code in self.DAILY_PEGGED:
            if code not in codes: continue
            per_usd=Decimal(self.PEGGED_TO_USD[code]); to_usd=(Decimal("1")/per_usd).quantize(Decimal("0.0000000001"))
            rows.append((display,code,"USD",str(to_usd),utcnow())); rows.append((display,code,"LBP",str((Decimal("89500")/per_usd).quantize(Decimal("0.01"))),utcnow()))
        return rows

    def _ensure_automatic_rates(self):
        self.__dict__.pop("_rate_state", None)  # 2.9.58: rates change - forget the cached ones
        today=datetime.now().strftime("%d-%m-%Y")
        with self.connect() as db:
            db.executemany("""INSERT INTO exchange_rates(rate_date,from_currency,to_currency,rate,created_at)
                VALUES(?,?,?,?,?) ON CONFLICT(rate_date,from_currency,to_currency) DO NOTHING""",self._pegged_rows(today))
            db.execute("""INSERT INTO exchange_rates(rate_date,from_currency,to_currency,rate,created_at)
                VALUES(?,?,?,?,?) ON CONFLICT(rate_date,from_currency,to_currency) DO NOTHING""",
                (today,"USD","LBP","89500",utcnow()))
            exists=db.execute("SELECT 1 FROM exchange_rates WHERE rate_date=? AND from_currency='EUR' AND to_currency='USD'",(today,)).fetchone()
        if exists or not self._may_download_rates("today"): return
        try:
            request=urllib.request.Request("https://api.frankfurter.app/latest?from=EUR&to=USD",headers={"User-Agent":"SaberAccounting/1.4"})
            with urllib.request.urlopen(request,timeout=5) as response: eur_usd=Decimal(str(json.loads(response.read().decode("utf-8"))["rates"]["USD"]))
            eur_lbp=(eur_usd*Decimal("89500")).quantize(Decimal("0.01"))
            with self.connect() as db:
                for source,target,rate in (("EUR","USD",eur_usd),("EUR","LBP",eur_lbp)):
                    db.execute("""INSERT INTO exchange_rates(rate_date,from_currency,to_currency,rate,created_at)
                        VALUES(?,?,?,?,?) ON CONFLICT(rate_date,from_currency,to_currency) DO NOTHING""",
                        (today,source,target,str(rate),utcnow()))
        except Exception as exc:
            # No internet is normal: note it without the full details.
            logging.getLogger("saber.database").info("Today's EUR rate was not downloaded: %s", exc)

    def sync_historical_exchange_rates(self):
        self.__dict__.pop("_rate_state", None)  # 2.9.58: rates change - forget the cached ones
        start=datetime(2024,1,1).date(); end=datetime.now().date(); collected={}
        previous=None
        for year in range(start.year,end.year+1):
            year_start=max(start,datetime(year,1,1).date()); year_end=min(end,datetime(year,12,31).date())
            url=f"https://api.frankfurter.app/{year_start.isoformat()}..{year_end.isoformat()}?from=EUR&to=USD"
            try:
                request=urllib.request.Request(url,headers={"User-Agent":"SaberAccounting/1.5"})
                with urllib.request.urlopen(request,timeout=10) as response: payload=json.loads(response.read().decode("utf-8"))
                for rate_date,values in payload.get("rates",{}).items(): collected[rate_date]=Decimal(str(values["USD"]))
            except Exception:
                continue
        if collected: previous=collected[min(collected)]
        else:
            try:
                request=urllib.request.Request("https://api.frankfurter.app/latest?from=EUR&to=USD",headers={"User-Agent":"SaberAccounting/1.5"})
                with urllib.request.urlopen(request,timeout=5) as response: previous=Decimal(str(json.loads(response.read().decode("utf-8"))["rates"]["USD"]))
            except Exception: previous=Decimal("1")
        rows=[]; current=start
        while current<=end:
            if current.isoformat() in collected: previous=collected[current.isoformat()]
            display=current.strftime("%d-%m-%Y"); eur_lbp=(previous*Decimal("89500")).quantize(Decimal("0.01"))
            rows.extend(((display,"USD","LBP","89500",utcnow()),(display,"EUR","USD",str(previous),utcnow()),(display,"EUR","LBP",str(eur_lbp),utcnow())))
            rows.extend(self._pegged_rows(display))  # 2.9.78: AED and SAR every day too
            current+=timedelta(days=1)
        with self.connect() as db:
            db.executemany("""INSERT INTO exchange_rates(rate_date,from_currency,to_currency,rate,created_at)
                VALUES(?,?,?,?,?) ON CONFLICT(rate_date,from_currency,to_currency) DO NOTHING""",rows)
            db.execute("INSERT INTO app_settings(key,value) VALUES('exchange_history_loaded_through',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(end.isoformat(),))
        return {"from":start.isoformat(),"to":end.isoformat(),"days":(end-start).days+1,"rates":len(rows)}

    def restore_euro_rates(self):
        self.__dict__.pop("_rate_state", None)  # 2.9.58: rates change - forget the cached ones
        with self.connect() as db:
            db.execute("DELETE FROM exchange_rate_samples WHERE from_currency='EUR' AND to_currency IN ('USD','LBP')")
            db.execute("DELETE FROM exchange_rates WHERE from_currency='EUR' AND to_currency IN ('USD','LBP')")
            db.execute("DELETE FROM app_settings WHERE key='exchange_history_loaded_through'")
        return self.sync_historical_exchange_rates()

    # 2.9.71: currencies fixed to the US dollar (units of the currency for 1 USD); the internet is not needed for them.
    PEGGED_TO_USD = {"AED": "3.6725", "SAR": "3.75", "QAR": "3.64", "BHD": "0.376", "OMR": "0.3845", "JOD": "0.709"}
    # Currencies published by the European Central Bank (api.frankfurter.app).
    ECB_CURRENCIES = {"AUD", "BGN", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP", "HKD", "HUF", "IDR", "ILS", "INR", "ISK",
                      "JPY", "KRW", "MXN", "MYR", "NOK", "NZD", "PHP", "PLN", "RON", "SEK", "SGD", "THB", "TRY", "USD", "ZAR"}

    def _download_json(self, url, timeout=10):
        request=urllib.request.Request(url,headers={"User-Agent":"SaberAccounting/2.9.71"})
        with urllib.request.urlopen(request,timeout=timeout) as response: return json.loads(response.read().decode("utf-8"))

    def restore_all_rates(self):
        """2.9.71: the daily rate to USD from 01-01-2024 to today of EVERY currency of Settings > Currencies (EUR as before,
        GBP, CHF, CAD ... from the European Central Bank, AED / SAR / QAR / BHD / OMR / JOD at their fixed USD rate).
        Rates typed by hand are kept; only the automatic ones are replaced. LBP stays at 89,500 per USD."""
        result=self.restore_euro_rates()
        start=datetime(2024,1,1).date(); end=datetime.now().date()
        others=sorted(code for code in self.currency_codes() if code not in ("USD","LBP","EUR"))  # 2.9.78: same order on every PC
        pegged=[code for code in others if code in self.PEGGED_TO_USD]
        downloadable=[code for code in others if code in self.ECB_CURRENCIES]
        skipped=[code for code in others if code not in pegged and code not in downloadable]
        collected={code:{} for code in downloadable}; failed=set()
        if downloadable:
            for year in range(start.year,end.year+1):
                year_start=max(start,datetime(year,1,1).date()); year_end=min(end,datetime(year,12,31).date())
                try:
                    payload=self._download_json(f"https://api.frankfurter.app/{year_start.isoformat()}..{year_end.isoformat()}?from=USD&to={','.join(downloadable)}")
                except Exception as exc:
                    logging.getLogger("saber.database").info("Rates of %s were not downloaded: %s", year, exc); failed.add(year); continue
                for rate_date,values in (payload.get("rates") or {}).items():
                    for code,value in (values or {}).items():
                        if code in collected and Decimal(str(value))>0: collected[code][rate_date]=Decimal(str(value))
        rows=[]; restored=[]
        for code in pegged+downloadable:
            per_usd=None; days=collected.get(code,{})
            if code in downloadable:
                if not days: skipped.append(code); continue
                per_usd=days[min(days)]
            current=start
            while current<=end:
                if code in pegged: per_usd=Decimal(self.PEGGED_TO_USD[code])
                elif current.isoformat() in days: per_usd=days[current.isoformat()]
                rows.append((current.strftime("%d-%m-%Y"),code,"USD",str((Decimal("1")/per_usd).quantize(Decimal("0.0000000001"))),utcnow()))
                current+=timedelta(days=1)
            restored.append(code)
        self.__dict__.pop("_rate_state", None)
        with self.connect() as db:
            for code in restored:
                db.execute("DELETE FROM exchange_rates WHERE from_currency=? AND to_currency='USD' AND created_by IS NULL",(code,))
            db.executemany("""INSERT INTO exchange_rates(rate_date,from_currency,to_currency,rate,created_at)
                VALUES(?,?,?,?,?) ON CONFLICT(rate_date,from_currency,to_currency) DO NOTHING""",rows)
        restored_all=["USD","LBP","EUR"]+restored
        return {**result,"restored":[c for c in restored_all if c in self.currency_codes()],"skipped":sorted(skipped),
                "offline_years":sorted(failed),"rates":result.get("rates",0)+len(rows)}

    def _converted_amount(self, amount, source, target, rate_date):
        """amount x the rate of that day. 2.9.58: the rate of a (currency pair, day) is looked up once and kept while the
        exchange-rate table does not change (reports used to query the rates for every journal line: a trial balance of
        3,000 invoices took 40 seconds)."""
        amount=Decimal(str(amount or 0)); source=str(source or "USD").upper(); target=str(target or source).upper()
        if source==target: return amount
        try: target_key=iso_date(rate_date).replace("-","")
        except ValueError: target_key=datetime.now().strftime("%Y%m%d")
        cache=self._rate_cache(); key=(source,target,target_key)
        if key not in cache: cache[key]=self._rate_factor(source,target,rate_date,target_key)
        return amount*cache[key]

    def _rate_cache(self):
        import time as _time
        state=self.__dict__.setdefault("_rate_state",{"checked":0.0,"signature":None,"cache":{}})
        now=_time.monotonic()
        if now-state["checked"]>1.0:  # at most one cheap check per second: a new or removed rate empties the cache
            with self.connect() as db:
                signature=tuple(db.execute("SELECT COUNT(*),MAX(id),COALESCE(DSUM(LENGTH(rate)),0) FROM exchange_rates").fetchone())
            if signature!=state["signature"]: state["cache"]={}; state["signature"]=signature
            state["checked"]=now
        return state["cache"]

    def _rate_table(self):
        """2.9.63: every exchange rate read ONCE (per change of the rate table) and kept per currency pair, sorted by day.
        Looking a rate up used to open a database connection and sort the table each time: a trial balance of
        20,000 invoices spent 28 seconds there."""
        state=self.__dict__.setdefault("_rate_state",{"checked":0.0,"signature":None,"cache":{}})
        table=state.get("table")
        if table is not None and state.get("table_signature")==state["signature"]: return table
        def sortable(value):
            text=str(value)
            if len(text)==10 and text[2]=="-" and text[5]=="-": return text[6:10]+text[3:5]+text[0:2]  # GLOB '??-??-????'
            return text.replace("-","")
        table={}
        with self.connect() as db:
            for row in db.execute("SELECT id,from_currency,to_currency,rate_date,rate FROM exchange_rates WHERE rate_date IS NOT NULL"):
                table.setdefault((row["from_currency"],row["to_currency"]),[]).append((sortable(row["rate_date"]),row["id"],row["rate"]))
        for pair,rows in table.items():
            rows.sort(key=lambda r:(r[0],r[1])); table[pair]=([r[0] for r in rows],rows)
        state["table"]=table; state["table_signature"]=state["signature"]
        return table

    def _rate_factor(self, source, target, rate_date, target_key):
        amount=Decimal("1")
        import bisect
        table=self._rate_table()
        def latest(frm,to):  # same as: WHERE day<=target ORDER BY day DESC,id DESC LIMIT 1
            found=table.get((frm,to))
            if not found: return None
            keys,rows=found; index=bisect.bisect_right(keys,target_key)
            return rows[index-1] if index else None
        def find_rate(frm,to):
            row=latest(frm,to)
            if row: return Decimal(str(row[2]))
            row=latest(to,frm)
            return Decimal("1")/Decimal(str(row[2])) if row and Decimal(str(row[2])) else None
        direct=find_rate(source,target)
        if direct is not None: return amount*direct
        usd_rates={"USD":Decimal("1"),"LBP":Decimal("1")/Decimal("89500"),
                   "EUR":find_rate("EUR","USD") or Decimal("1"),
                   "AED":Decimal("1")/Decimal("3.6725")}
        if source in usd_rates and target in usd_rates:
            to_usd=find_rate(source,"USD") or usd_rates[source]
            from_usd=find_rate("USD",target)
            if from_usd is None: from_usd=Decimal("1")/usd_rates[target]
            return amount*to_usd*from_usd
        # any other currency goes through USD (for example LBP -> USD -> SAR for payroll paid in SAR)
        first=find_rate(source,"USD") if source!="USD" else Decimal("1")
        if first is None and source in usd_rates: first=usd_rates[source]
        second=find_rate("USD",target) if target!="USD" else Decimal("1")
        if second is None and target in usd_rates: second=Decimal("1")/usd_rates[target]
        if first is not None and second is not None: return amount*first*second
        raise ValueError(f"No exchange rate available for {source} to {target} on {rate_date}")
