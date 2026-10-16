"""Isolated, CPU-only PaddleOCR worker. No invoice is uploaded to a service."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys


def create_reader(language="arabic", prepare=False):
    # Model downloads happen during explicit setup, not during ordinary invoice reading.
    os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    from paddleocr import PaddleOCR
    options={}
    if not prepare:
        cache=Path(os.environ.get("PADDLE_PDX_CACHE_HOME", str(Path.home()/".paddlex")))/"official_models"
        for option,name in (("text_detection_model_dir","PP-OCRv5_server_det"),
                            ("text_recognition_model_dir",f"{language}_PP-OCRv5_mobile_rec")):
            directory=cache/name
            if not (directory/"inference.json").is_file() or not (directory/"inference.pdiparams").is_file():
                raise RuntimeError("Advanced OCR model is missing; run Install / Repair Advanced Reader")
            options[option]=str(directory)
    return PaddleOCR(**options, text_detection_model_name="PP-OCRv5_server_det",
                     text_recognition_model_name=f"{language}_PP-OCRv5_mobile_rec",
                     use_doc_orientation_classify=False, use_doc_unwarping=False,
                     use_textline_orientation=False, device="cpu", enable_mkldnn=False, cpu_threads=1)


def create_english(prepare=False):
    from paddleocr import TextRecognition
    options={}
    if not prepare:
        cache=Path(os.environ.get("PADDLE_PDX_CACHE_HOME",str(Path.home()/".paddlex")))/"official_models"/"en_PP-OCRv5_mobile_rec"
        if not (cache/"inference.pdiparams").is_file():raise RuntimeError("English OCR model is missing; repair the reader")
        options["model_dir"]=str(cache)
    return TextRecognition(model_name="en_PP-OCRv5_mobile_rec",device="cpu",enable_mkldnn=False,cpu_threads=1,**options)


def read(reader, path, english=None):
    import numpy as np
    from PIL import Image, ImageOps
    from contextlib import ExitStack
    with ExitStack() as stack:
        if Path(path).suffix.lower()==".pdf":
            import pypdfium2 as pdfium
            document=stack.enter_context(pdfium.PdfDocument(path))
            if len(document)!=1: raise ValueError("Advanced OCR requires one invoice page")
            page=document[0]; stack.callback(page.close)
            bitmap=page.render(scale=2); stack.callback(bitmap.close)
            original=bitmap.to_pil(); stack.callback(original.close)
        else:
            original=stack.enter_context(Image.open(path))
        image=ImageOps.exif_transpose(original).convert("RGB"); stack.callback(image.close)
        image.thumbnail((2200, 2200))
        def predict(picture):
            array=np.ascontiguousarray(np.asarray(picture)[:, :, ::-1])
            return list(reader.predict(array))[0].json["res"],array
        first,array=predict(image)
        boxes=first.get("rec_boxes", [])
        sideways=sum((box[3]-box[1]) > (box[2]-box[0])*1.5 for box in boxes)
        candidates=[(first,array)]
        if boxes and sideways > len(boxes)*.35:
            for angle in (90,270):
                turned=image.rotate(angle, expand=True); stack.callback(turned.close)
                candidates.append(predict(turned))
        readings=[]
        for r,array in candidates:
            boxes=r.get("rec_boxes", [])
            readings.append({"texts":r.get("rec_texts",[]),"scores":r.get("rec_scores",[]),"boxes":boxes})
            # Reuse detection boxes for English rather than loading a second large detector.
            if english is not None:
                crops=[]; kept=[]
                for box in boxes:
                    x1,y1,x2,y2=map(int,box)
                    crop=array[max(0,y1):max(0,y2),max(0,x1):max(0,x2)]
                    if crop.size:crops.append(np.ascontiguousarray(crop));kept.append(box)
                if crops:
                    results=[x.json["res"] for x in english.predict(crops,batch_size=1)]
                    readings.append({"texts":[x["rec_text"] for x in results],
                                     "scores":[x["rec_score"] for x in results],"boxes":kept})
        return readings


def serve():
    """2.9.126: stay loaded and read one invoice per request (JSON lines). stdout carries only the protocol;
    model and progress messages go to stderr."""
    protocol=sys.stdout
    sys.stdout=sys.stderr
    def send(message):
        protocol.write(json.dumps(message, ensure_ascii=False)+"\n"); protocol.flush()
    try:
        arabic=create_reader(); english=create_english()
    except Exception as exc:
        send({"ready": False, "error": f"{type(exc).__name__}: {exc}"}); return
    send({"ready": True, "pid": os.getpid()})
    for line in sys.stdin:
        line=line.strip()
        if not line: continue
        try: request=json.loads(line)
        except ValueError:
            send({"id": None, "error": "invalid request"}); continue
        if request.get("quit"): break
        try:
            send({"id": request.get("id"), "readings": read(arabic, Path(request["path"]), english)})
        except Exception as exc:  # one bad image never stops the worker
            send({"id": request.get("id"), "error": f"{type(exc).__name__}: {exc}"})


def main():
    from contextlib import redirect_stdout
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        return serve()
    # Keep the wire format separate from model initialization/progress messages.
    with redirect_stdout(sys.stderr):
        prepare=sys.argv[1] == "--prepare"
        arabic=create_reader(prepare=prepare); english=create_english(prepare=prepare)
        if prepare:
            result={"ready": True}
        else:
            readings=read(arabic, Path(sys.argv[1]), english)
            result={"readings": readings}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
