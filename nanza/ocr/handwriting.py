"""TrOCR for cropped handwritten lines, with local model files only.

microsoft/trocr-base-handwritten is trained on English handwriting. It is not
an Arabic handwriting solution. No model downloads occur during inference.
"""
from functools import lru_cache
import os
from pathlib import Path
import threading

MODEL_ID = "microsoft/trocr-base-handwritten"
_LOCK = threading.Lock()


class HandwritingUnavailable(RuntimeError):
    """Install dependencies and pre-cache the model before offline inference."""


@lru_cache(maxsize=1)
def _load_handwriting_model():
    try:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        import torch
    except ImportError as exc:
        raise HandwritingUnavailable("Install transformers, torch and Pillow") from exc
    location = os.environ.get("NANZA_TROCR_MODEL_DIR") or MODEL_ID
    try:
        processor = TrOCRProcessor.from_pretrained(location, local_files_only=True)
        model = VisionEncoderDecoderModel.from_pretrained(
            location, local_files_only=True, use_safetensors=True).to("cpu").eval()
    except (OSError, ValueError, RuntimeError) as exc:
        raise HandwritingUnavailable(
            "TrOCR model is not available locally; set NANZA_TROCR_MODEL_DIR") from exc
    return processor, model, torch


def read_handwritten_line(image):
    """Return text for one cropped PIL image or image path; never auto-download.

    Raises HandwritingUnavailable when dependencies or cached weights are absent.
    Returned text is an unverified hypothesis, not a calibrated confidence score.
    """
    from PIL import Image, ImageOps
    owned = isinstance(image, (str, Path))
    if owned:
        path = Path(image)
        if path.stat().st_size > 15 * 1024 * 1024:
            raise ValueError("Handwriting image exceeds 15 MB")
        image = Image.open(path)
    try:
        if image.width * image.height > 25_000_000:
            raise ValueError("Handwriting crop exceeds 25 million pixels")
        rgb = ImageOps.exif_transpose(image).convert("RGB")
        with _LOCK:
            processor, model, torch = _load_handwriting_model()
            pixels = processor(images=rgb, return_tensors="pt").pixel_values
            with torch.inference_mode():
                generated = model.generate(pixels, max_new_tokens=128, num_beams=2)
            text = processor.batch_decode(generated, skip_special_tokens=True)
        return str(text[0]).strip() if text else ""
    finally:
        if owned:
            image.close()


def read_handwritten_arabic_line(image):
    """Falcon Arabic with grayscale/autocontrast/contrast preprocessing."""
    from .arabic import read_arabic_document
    return read_arabic_document(image, handwriting=True)["text"]
