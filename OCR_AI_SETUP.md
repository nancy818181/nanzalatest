# Local OCR and AI — light source package, NANZA 2.9.132

No OpenAI API or paid AI service is used. There is no Qwen2-VL-7B backend and no
qwen-vl-utils or accelerate requirement in this delivery. Existing NANZA AI and
OCR modules remain intact; the new APIs are additive.

## Install once while connected

Use Python 3.12 in a dedicated virtual environment:

```bash
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
# Optional CPU-first install avoids unnecessary CUDA downloads on Linux:
python -m pip install 'torch>=2.6,<2.9' --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_ocr.py tests/test_ai_accountant.py -v
```

`requirements-dev.txt` includes the production `requirements.txt` and pytest.
Production requirements retain desktop dependencies and add PaddleOCR,
Transformers 4.40.0, PyTorch, scikit-learn and Ollama. Pillow remains present once.
PaddlePaddle CPU is included because PaddleOCR needs its inference runtime.
Torch is required for local Falcon/TrOCR inference; removing the dependency
would not make those models work without an inference backend.

OpenCV is unified as opencv-contrib-python 4.10.0.84, the Paddle-compatible build,
so two distributions do not overwrite the same cv2 namespace. System Tk and
OpenCV runtime libraries may be needed on Linux.

For full regression checks from an unpacked ZIP, initialize a review Git checkout
first (`git init`, review files, `git add .`). The existing release check inspects
the Git index; without an index it sees Python-generated caches in the folder.
On case-sensitive Linux, create the untracked test link `ln -s Assets assets`.

## Model downloads: one-time internet, then offline

The ZIP contains code and test fixtures, not inference weights. The first setup
requires internet to install packages and obtain the Falcon/TrOCR/Paddle/Ollama
models. You can instead transfer a complete platform-specific wheelhouse and
model folders from another machine. Inference uses local files only and never
silently downloads a model.

### TrOCR English handwritten lines

On the connected setup computer:

```python
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
model_id = 'microsoft/trocr-base-handwritten'
TrOCRProcessor.from_pretrained(model_id).save_pretrained('models/trocr')
VisionEncoderDecoderModel.from_pretrained(model_id).save_pretrained(
    'models/trocr', safe_serialization=True)
```

Set `NANZA_TROCR_MODEL_DIR` to the absolute folder. This English handwriting
checkpoint expects a cropped line. It is not used as an Arabic handwriting model.

### Falcon-OCR-Arabic

Obtain a legitimately accessible, verified Arabic checkpoint and its complete
local inference/config/code files. Configure `NANZA_FALCON_ARABIC_MODEL_DIR`.
The attempted `tiiuae/falcon-ocr-arabic` config/README endpoint returned HTTP 401
in this session, so this package does not pretend that checkpoint was downloaded
or its recognition measured. Do not substitute the English base Falcon-OCR and
label it Arabic. Consult the publisher for the accessible Arabic checkpoint.

Falcon's official custom implementation uses AutoModelForCausalLM and
`model.generate(image)`. Review the downloaded local code/revision, then set
`NANZA_ALLOW_LOCAL_MODEL_CODE=1` to enable it. This adapter loads the reviewed
local model with PyTorch on CPU, `local_files_only=True`, and no accelerate.
Actual checkpoint compatibility with Transformers 4.40.0 still requires a real
checkpoint acceptance test; no model weights were supplied to certify that.

### PaddleOCR for printed text and bootstrap script detection

Obtain compatible PaddleOCR 3.3.2 inference folders, for example
PP-OCRv5_server_det plus arabic_PP-OCRv5_mobile_rec. Set
`NANZA_PADDLE_DET_MODEL_DIR` and `NANZA_PADDLE_REC_MODEL_DIR` to absolute folders.
They must contain complete model configurations/dictionaries,
`inference.pdiparams`, and `inference.json` or `inference.pdmodel`.
The recognizer is initialized with lang='ar'; the script bootstrap routes Arabic
text to Falcon. Test its Latin/mixed-script performance on your own invoices.
Empty/missing folders yield an explicit unavailable/review result, not a download.

### Optional Ollama books chat

Install the Ollama desktop/service application; the Python package alone does not
install the service or weights. While connected:

```bash
ollama pull llama3.1:8b
```

This is optional: books chat falls back to rules if the local service/model is
unavailable. Bind the service to loopback. No external provider is contacted.
The optional 8B model is not included in any small-footprint guarantee; the
rule-based path needs no language model download.

## Routing and API examples

```python
from nanza.ocr import extract_invoice_data, read_handwritten_line, read_handwritten_arabic_line
printed = extract_invoice_data('invoice.png', country='LB')
arabic = extract_invoice_data('invoice_ar.png', country='LB', language='ar')
hand_ar = extract_invoice_data('handwritten_ar.png', language='ar', handwriting=True)
english_line = read_handwritten_line('cropped_english_line.png')
arabic_line = read_handwritten_arabic_line('cropped_arabic_line.png')
```

- Arabic printed: local Falcon Arabic after bootstrap script detection or explicit hint.
- English printed: PaddleOCR result path.
- English handwriting: TrOCR line path / low-confidence line fallback.
- Arabic handwriting: Falcon Arabic with grayscale, autocontrast and contrast enhancement.

When no script can be detected because no model exists, language is unknown unless
provided by the caller. The engine never guesses from a sample filename.

Return fields include vendor/date/total/VAT/rate/confidence/raw_text/items,
needs_review/language/backend/warnings. Monetary amounts are exact decimal strings;
missing values are None. Country assumptions are flagged; rate entry does not
certify tax compliance. All extracted documents require review before posting.
Falcon confidence is conservatively 0.0 with an explicit uncalibrated warning;
it is not a measured probability or the sample's recognition accuracy.

```python
from nanza.ai_accountant.classifier import ExpenseClassifier
classifier = ExpenseClassifier('company_labels.sqlite3', company_id='company-A')
print(classifier.categorize('شراء بنزين للسيارة'))
classifier.learn('خدمة مهنية خاصة', 'professional_fees')

from nanza.ai_accountant.chat import ask_books, books_context
# db and user come from the host's authorized company/session.
with books_context(db, user):
    print(ask_books('How much did I spend on fuel last month?'))

from nanza.ai_accountant.anomaly import detect_anomalies
print(detect_anomalies([{'id': 1, 'vendor': 'Cedar', 'currency': 'USD',
                        'total': '150', 'vat': '50', 'country': 'LB'}]))
```

The classifier stores confirmed labels, not unsafe pickled models. Unknown or
ambiguous inputs abstain. Existing classify_expense/suggest_account/find_duplicates
functions remain. Chat accepts only supported validated intents and runs fixed
parameterized read queries, never model-generated SQL. The host must authorize
the selected company/principal. All-expense totals require payroll permission.
Anomaly flags identify review candidates, not proven fraud.

## Tests and actual accuracy

```bash
python -m pytest tests/test_ocr.py tests/test_ai_accountant.py -v
```

15 local tests verify code contracts, parsing, language routing, preprocessing,
low-confidence review policy, sklearn learning and SQLite queries. Model outputs
are explicit test doubles. `test_handwritten_arabic_accuracy` now tests the requested
policy: if confidence <0.7, needs_review is True. It does not invent a CER score.

The real user image and exact transcription are in tests/data/. For a real model
measurement after configuring local weights:

```bash
python -m nanza.ocr.benchmark tests/data/arabic_handwritten_sample.png --gold tests/data/arabic_handwritten_gold.json --out accuracy.json --country LB
# Inspect actual downloaded disk usage; never substitute nominal parameter counts:
du -h ~/.cache/huggingface/hub/
```

No model recognition accuracy, speed or total installed-size percentage/limit is
claimed without measurement. Source ZIP size is measured separately. First setup
requires downloads; subsequent inference is offline when all required files and
CPU runtimes are installed and configured.
