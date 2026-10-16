"""Optional local neural OCR: isolated runtime, explicit setup, bounded document reads."""
from __future__ import annotations
import json
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


def read(path):
    if not ready(): raise NeuralReaderError("Install Advanced Local OCR in Settings first")
    if not _LOCK.acquire(blocking=False):
        raise NeuralReaderError("Advanced OCR is busy; review the local reading or try again after it finishes")
    try:
        text=_run([runtime(),worker(),Path(path).resolve()],120,env=_environment())
    finally:
        _LOCK.release()
    try:
        result=json.loads(text)
        if not isinstance(result,dict) or not isinstance(result.get("readings"),list): raise ValueError("missing readings")
        if not all(isinstance(reading,dict) for reading in result["readings"]): raise ValueError("invalid reading")
        return result["readings"]
    except (ValueError,TypeError) as exc:
        raise NeuralReaderError("Advanced OCR returned an unreadable response") from exc


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
