"""Lazy, local Falcon Arabic OCR. No large-model download or remote API."""
from functools import lru_cache
import os
from pathlib import Path
import threading
import time
from .handwriting import HandwritingUnavailable

_LOCK = threading.Lock()


def _image(image, handwriting=False):
    from PIL import Image, ImageOps, ImageEnhance
    if isinstance(image, (str, Path)):
        with Image.open(image) as opened:
            if opened.width*opened.height > 25_000_000:
                raise ValueError("Image exceeds 25 million pixels")
            rgb = ImageOps.exif_transpose(opened).convert("RGB")
    else:
        if image.width*image.height > 25_000_000:
            raise ValueError("Image exceeds 25 million pixels")
        rgb = image.convert("RGB")
    if handwriting:
        gray = ImageOps.autocontrast(ImageOps.grayscale(rgb))
        improved = ImageEnhance.Contrast(gray).enhance(1.8).convert("RGB")
        gray.close(); rgb.close()
        return improved
    return rgb


@lru_cache(maxsize=1)
def _falcon():
    folder = os.environ.get("NANZA_FALCON_ARABIC_MODEL_DIR", "")
    if not folder or not Path(folder).is_dir():
        raise HandwritingUnavailable("Falcon Arabic local directory is not configured")
    if os.environ.get("NANZA_ALLOW_LOCAL_MODEL_CODE") != "1":
        raise HandwritingUnavailable("Review Falcon local model code before setting NANZA_ALLOW_LOCAL_MODEL_CODE=1")
    try:
        import torch
        from transformers import AutoModelForCausalLM
        model = AutoModelForCausalLM.from_pretrained(
            folder, local_files_only=True, trust_remote_code=True,
            use_safetensors=True, torch_dtype=torch.float32,
            device_map=None).to("cpu").eval()
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise HandwritingUnavailable(
            "Falcon needs compatible local CPU backend and weights: "+str(exc)) from exc
    return model, torch


def _read_falcon(image):
    model, torch = _falcon()
    with torch.inference_mode():
        texts = model.generate(image)
    return str(texts[0]).strip() if texts else ""


def read_arabic_document(image, *, handwriting=False):
    """Return a review proposal. 0.0 means uncalibrated, not measured accuracy.

    PyTorch is installed for CPU inference and loaded only on use. Model
    weights are prepared once separately and are never downloaded implicitly.
    Missing backends fail explicitly rather than supplying a fake transcription.
    """
    rgb = _image(image, handwriting=handwriting)
    start = time.monotonic()
    try:
        with _LOCK:
            text = _read_falcon(rgb)
        if not text:
            raise HandwritingUnavailable("Falcon returned no text")
        return {"text": text, "backend": "falcon", "language": "ar",
                "confidence": 0.0, "seconds": time.monotonic()-start,
                "warnings": ["falcon_confidence_uncalibrated_requires_review"],
                "needs_review": True, "mock": False}
    finally:
        rgb.close()
