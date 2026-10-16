"""Optional local neural OCR: isolated runtime, explicit setup, bounded document reads."""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading

PACKAGES = ("paddlepaddle==3.2.2", "paddleocr==3.3.2", "pypdfium2==5.6.0", "paddlex==3.3.13")
MODELS = ("PP-OCRv5_server_det", "arabic_PP-OCRv5_mobile_rec", "en_PP-OCRv5_mobile_rec")
_LOCK = threading.Lock()
_SETUP_LOCK = threading.Lock()


class NeuralReaderError(RuntimeError):
    pass


def folder():
    import app_runtime
    return app_runtime.data_dir() / "neural_ocr"


def worker():
    import nanza_paths
    root=nanza_paths.ROOT
    return next((p for p in (root/"ocr"/"neural_reader.py", root/"Assets"/"ocr"/"neural_reader.py") if p.is_file()),
                root/"ocr"/"neural_reader.py")


def runtime():
    override=os.environ.get("NANZA_NEURAL_PYTHON")
    if override: return Path(override)
    return folder()/"runtime"/("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ready():
    if not runtime().is_file(): return False
    if os.environ.get("NANZA_NEURAL_PYTHON"): return True
    try:
        state=json.loads((folder()/"ready.json").read_text(encoding="utf-8"))
        return isinstance(state,dict) and bool(state.get("enabled",True))
    except (OSError,ValueError): return False


def set_enabled(enabled):
    marker=folder()/"ready.json"
    try: state=json.loads(marker.read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:
        raise NeuralReaderError("Install the advanced reader first") from exc
    if not isinstance(state,dict):raise NeuralReaderError("Repair the advanced reader first")
    state["enabled"]=bool(enabled)
    marker.write_text(json.dumps(state),encoding="utf-8")


def _run(command, timeout, env=None):
    try:
        result=subprocess.run([str(v) for v in command], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=env,
                              creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    except subprocess.TimeoutExpired as exc:
        raise NeuralReaderError("Advanced OCR took too long; use the local reading or enter the missing fields") from exc
    except OSError as exc:
        raise NeuralReaderError(f"Advanced OCR could not start: {exc}") from exc
    if result.returncode:
        import logging
        logging.getLogger("saber.ocr").error("Advanced OCR process failed (%s): %s", result.returncode, result.stderr[-6000:])
        raise NeuralReaderError("Advanced OCR failed; see the application log or use Install / Repair Advanced Reader in Settings")
    return result.stdout


def _environment():
    env=os.environ.copy()
    env["PYTHONIOENCODING"]="utf-8"; env["PYTHONUTF8"]="1"
    # Each installation owns its models; a normal reading never has to download them.
    if not os.environ.get("NANZA_NEURAL_PYTHON"):
        env["PADDLE_PDX_CACHE_HOME"]=str(folder()/"models")
    return env


IDLE_SECONDS = 300
READ_TIMEOUT = 120
START_TIMEOUT = 180


class _Worker:
    """2.9.126: one PaddleOCR process kept loaded between invoices (the models load once, not for every photo).
    Requests are serialized; a timeout or crash kills the process and the next reading starts a clean one; the
    process stops after IDLE_SECONDS without a request."""

    def __init__(self):
        self.process=None; self.lines=None; self.next_id=0; self.last_used=0.0; self.timer=None

    def _start(self):
        import queue, time
        try:
            process=subprocess.Popen([str(runtime()),str(worker()),"--serve"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",bufsize=1,env=_environment(),
                                     creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        except OSError as exc:
            raise _ProtocolError(f"Advanced OCR could not start: {exc}") from exc
        lines=queue.Queue(); tail=[]
        def pump_out():
            try:
                for line in process.stdout: lines.put(line)
            except (OSError,ValueError): logging.getLogger("saber.ocr").debug("Advanced OCR output ended", exc_info=True)
            finally:
                lines.put(None)
                try: process.stdout.close()
                except OSError: logging.getLogger("saber.ocr").debug("ignored error", exc_info=True)
        def pump_err():
            try:
                for line in process.stderr:
                    tail.append(line)
                    if len(tail)>200: del tail[:100]
            except (OSError,ValueError): logging.getLogger("saber.ocr").debug("Advanced OCR log ended", exc_info=True)
            finally:
                try: process.stderr.close()
                except OSError: logging.getLogger("saber.ocr").debug("ignored error", exc_info=True)
        threading.Thread(target=pump_out,daemon=True,name="NanzaOcrOut").start()
        threading.Thread(target=pump_err,daemon=True,name="NanzaOcrErr").start()
        self.process,self.lines,self.tail=process,lines,tail
        try: hello=self._receive(START_TIMEOUT)
        except TimeoutError as exc:
            self.stop(); raise _ProtocolError("Advanced OCR did not start in time") from exc
        except _ProtocolError:
            self.stop(); raise  # never leave a half-started reader running without its idle stop
        if not isinstance(hello,dict) or not hello.get("ready"):
            self.stop()
            raise _ProtocolError((hello or {}).get("error") if isinstance(hello,dict) else "Advanced OCR did not start")
        self.last_used=time.monotonic()

    def _receive(self, timeout):
        import queue
        try: line=self.lines.get(timeout=timeout)
        except queue.Empty: raise TimeoutError
        if line is None: raise _ProtocolError("Advanced OCR stopped unexpectedly")
        try: return json.loads(line)
        except ValueError as exc: raise _ProtocolError("Advanced OCR sent an unreadable answer") from exc

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def read(self, path):
        import time
        if not self.alive(): self._start()
        self.next_id+=1; request_id=self.next_id
        try:
            self.process.stdin.write(json.dumps({"id":request_id,"path":str(Path(path).resolve())})+"\n"); self.process.stdin.flush()
        except OSError as exc:
            self.stop(); raise _ProtocolError("Advanced OCR could not receive the invoice") from exc
        try:
            while True:
                answer=self._receive(READ_TIMEOUT)
                if isinstance(answer,dict) and answer.get("id")==request_id: break  # an older, abandoned answer is skipped
        except TimeoutError:
            self.stop()  # a stuck reading never blocks the next one
            raise NeuralReaderError("Advanced OCR took too long; use the local reading or enter the missing fields")
        except _ProtocolError:
            import logging
            logging.getLogger("saber.ocr").error("Advanced OCR worker failed: %s","".join(getattr(self,"tail",[]))[-6000:])
            self.stop(); raise
        self.last_used=time.monotonic(); self._schedule_idle()
        if answer.get("error"):
            import logging
            logging.getLogger("saber.ocr").warning("Advanced OCR could not read %s: %s",path,answer["error"])
            raise NeuralReaderError("Advanced OCR could not read this document; review the local reading")
        return answer.get("readings")

    def _schedule_idle(self):
        import time
        if self.timer is not None: self.timer.cancel()
        def check():
            if _LOCK.acquire(blocking=False):  # never stopped while a reading is running
                try:
                    if time.monotonic()-self.last_used>=IDLE_SECONDS: self.stop()
                    else: self._schedule_idle()
                finally: _LOCK.release()
            else: self._schedule_idle()
        self.timer=threading.Timer(IDLE_SECONDS,check); self.timer.daemon=True; self.timer.start()

    def stop(self):
        process,self.process=self.process,None
        if process is None: return
        import logging
        log=logging.getLogger("saber.ocr")
        try:
            if process.poll() is None:
                try: process.stdin.write(json.dumps({"quit":True})+"\n"); process.stdin.flush()
                except (OSError,ValueError): log.debug("Advanced OCR worker closed its input", exc_info=True)
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        except (OSError,subprocess.SubprocessError):  # cleanup must never raise
            log.warning("Advanced OCR worker did not stop cleanly", exc_info=True)
            try: process.kill()
            except OSError: log.debug("Advanced OCR worker already ended", exc_info=True)
        finally:
            try: process.stdin.close()
            except (OSError,ValueError): log.debug("Advanced OCR input already closed", exc_info=True)


class _ProtocolError(NeuralReaderError):
    pass


_WORKER=_Worker()
import atexit as _atexit
_atexit.register(lambda: _WORKER.stop())


def read(path):
    if not ready(): raise NeuralReaderError("Install Advanced Local OCR in Settings first")
    # One invoice at a time; a second request is answered within seconds (its local reading stays) instead of
    # queuing behind a long reading. The short wait only covers the idle check, which holds the lock for an instant.
    if not _LOCK.acquire(timeout=2):
        raise NeuralReaderError("Advanced OCR is busy; review the local reading or try again after it finishes")
    try:
        try:
            readings=_WORKER.read(path)
        except _ProtocolError:
            # The kept-loaded worker could not start or broke its protocol: the one-shot reader is the fallback.
            # A timeout or a failed reading is NOT retried (the same image would wait as long again).
            text=_run([runtime(),worker(),Path(path).resolve()],READ_TIMEOUT,env=_environment())
            try: readings=json.loads(text).get("readings")
            except (ValueError,AttributeError) as exc: raise NeuralReaderError("Advanced OCR returned an unreadable response") from exc
    finally:
        _LOCK.release()
    if not isinstance(readings,list) or not all(isinstance(reading,dict) for reading in readings):
        raise NeuralReaderError("Advanced OCR returned an unreadable response")
    return readings


def reading_text(reading):
    """Restore physical rows before parsing; don't join a label to another row's amount."""
    import math
    tokens=[]
    for text,score,box in zip(reading.get("texts",[]),reading.get("scores",[]),reading.get("boxes",[])):
        try:
            score=float(score); x1,y1,x2,y2=map(float,box)
            if not math.isfinite(score) or score < .5 or x2<=x1 or y2<=y1: continue
            if not all(math.isfinite(v) for v in (x1,y1,x2,y2)):continue
        except (ValueError,TypeError):continue
        if str(text).strip():tokens.append((str(text).strip(),score,x1,y1,x2,y2))
    rows=[]
    for token in sorted(tokens,key=lambda t:((t[3]+t[5])/2,t[2])):
        middle=(token[3]+token[5])/2
        matching=next((r for r in reversed(rows) if abs(r[0]-middle)<=min(r[1],token[5]-token[3])*.45),None)
        if matching is None:rows.append([middle,token[5]-token[3],[token]])
        else:matching[2].append(token)
    return "\n".join("   ".join(t[0] for t in sorted(row[2],key=lambda t:t[2])) for row in rows)


def install(progress=None, cancel=None):
    if not _SETUP_LOCK.acquire(blocking=False): raise NeuralReaderError("Advanced OCR setup is already running")
    try: return _install(progress,cancel)
    finally: _SETUP_LOCK.release()


def _install(progress=None, cancel=None):
    """Install a per-user CPU runtime. The ordinary accounting environment is unchanged."""
    import shutil
    import urllib.request
    base=folder(); base.mkdir(parents=True,exist_ok=True)
    marker=base/"ready.json"
    def report(stage):
        if cancel is not None and cancel.is_set(): raise NeuralReaderError("Installation stopped")
        if progress: progress(0,1,stage)
    def setup_run(command,timeout):
        try:
            return _run(command,timeout,env=_environment())
        except NeuralReaderError:
            raise
    report("Preparing the advanced local OCR runtime")
    python=Path(sys.executable) if not getattr(sys,"frozen",False) else None
    if python is None and os.name == "nt":
        # Reuse the private Python when this setup has already downloaded it.
        python=base/"python"/"python.exe"
        if not python.is_file():
            report("Downloading Python from python.org (one-time setup)")
            installer=base/"python-3.12.10-amd64.exe"
            with urllib.request.urlopen("https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe",timeout=60) as source, installer.open("wb") as target:
                shutil.copyfileobj(source,target)
            # Check the publisher before executing the downloaded installer.
            import base64
            quoted=str(installer).replace("'", "''")
            verify=f"$s=Get-AuthenticodeSignature -LiteralPath '{quoted}'; if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Python Software Foundation'){{exit 1}}"
            encoded=base64.b64encode(verify.encode("utf-16le")).decode("ascii")
            setup_run(["powershell.exe","-NoProfile","-NonInteractive","-EncodedCommand",encoded],60)
            setup_run([installer,"/quiet","InstallAllUsers=0",f"TargetDir={python.parent}","Include_pip=1","Include_test=0","PrependPath=0","Shortcuts=0","AssociateFiles=0"],600)
            installer.unlink(missing_ok=True)
    if python is None: raise NeuralReaderError("Install the advanced reader from a Python source installation on this system")
    report("Installing the separate CPU reader (one-time setup)")
    if not runtime().is_file(): setup_run([python,"-m","venv",str(base/"runtime")],180)
    setup_run([runtime(),"-m","pip","install",*PACKAGES],1800)
    report("Downloading and checking the Arabic and English OCR models")
    prepared=json.loads(setup_run([runtime(),worker(),"--prepare"],900))
    if not isinstance(prepared,dict) or not prepared.get("ready"): raise NeuralReaderError("The OCR model check did not finish; repair the reader")
    report("Finishing advanced reader setup")
    marker.write_text(json.dumps({"packages":PACKAGES,"models":MODELS}),encoding="utf-8")
    return "Advanced Local OCR is ready. Photos are read on this computer; review before Save."


def enhance(path, local):
    """Choose a whole reading; never assemble a total from conflicting OCR amounts."""
    import re
    from pdf_import import _parse_invoice_text, _photo_reading_score, _require_ocr_review, _warn_on_invoice_total_mismatch
    try: readings=read(path)
    except NeuralReaderError as exc:
        local.setdefault("review_warnings",[]).append(str(exc))
        return _require_ocr_review(local)
    candidates=[]
    for reading in readings:
        text=reading_text(reading)
        result=_parse_invoice_text(path,text)
        number=result.get("invoice_number") or ""
        # A phone on the row below a numberless heading is not an invoice number.
        if number and not any(number in line and re.search(r"(?i)invoice|facture|فاتورة|\binv\b",line)
                              for line in text.splitlines()):
            result["invoice_number"]=""
        candidates.append((result,text,reading))
    if not candidates:return _require_ocr_review(local)
    def rank(candidate):
        result,text,_=candidate
        score=_photo_reading_score(text)
        original=_parse_invoice_text(path,text)
        if original.get("invoice_number") and not result.get("invoice_number"):score-=2
        return score
    result,text,reading=max(candidates,key=rank)
    # The legacy reader remains useful for printed documents and faint currency symbols.
    if _photo_reading_score(local.get("text") or "") > rank((result,text,reading)):
        selected=dict(local)
    else:
        selected=result
        selected["ocr_used"]=True
        selected["reader"]="paddle-local"
        selected["ocr_line_confidence"]=reading.get("scores",[])
    warnings=selected.setdefault("review_warnings",[])
    for key,label in (("invoice_number","invoice number"),("invoice_date","invoice date"),("currency","currency"),
                      ("subtotal","subtotal"),("vat","VAT"),("total","total")):
        values={str(c[0][key]) for c in candidates if c[0].get(key) not in (None,"")}
        if local.get(key) not in (None,""):values.add(str(local[key]))
        if len(values)>1:
            warnings.append(f"OCR readers disagree on {label}: check the original")
            if key == "invoice_number": selected[key]=""
    _warn_on_invoice_total_mismatch(selected)
    return _require_ocr_review(selected)
