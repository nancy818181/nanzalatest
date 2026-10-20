"""Measure real OCR against human transcription, never against mocked output.

python -m nanza.ocr.benchmark image.png --gold handwritten_gold.json --out result.json
Gold: {"raw_text": "human transcription", "vendor": "...", "date": "2026-10-19",
       "total": "111.00", "vat": "11.00", "vat_rate": 11}
"""
import argparse
import json
from pathlib import Path
import unicodedata
from .engine import extract_invoice_data


def _distance(first, second):
    previous = list(range(len(second)+1))
    for i, left in enumerate(first, 1):
        row = [i]
        for j, right in enumerate(second, 1):
            row.append(min(row[-1]+1, previous[j]+1, previous[j-1]+(left != right)))
        previous = row
    return previous[-1]


def score_transcription(predicted, expected):
    if not str(expected).strip(): raise ValueError("A nonempty human transcription is required")
    normalize = lambda value: " ".join(unicodedata.normalize("NFKC", str(value)).split())
    predicted, expected = normalize(predicted), normalize(expected)
    words = expected.split()
    return {"cer": _distance(predicted, expected)/len(expected),
            "wer": _distance(predicted.split(), words)/len(words),
            "normalization": "NFKC and whitespace only; no removal of Arabic letters/digits"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--gold", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--country", default="LB")
    args = parser.parse_args()
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    if not gold.get("raw_text"): raise ValueError("Gold raw_text is required")
    result = extract_invoice_data(args.image, country=args.country)
    metrics = score_transcription(result["raw_text"], gold["raw_text"]) if result["raw_text"] else None
    fields = {key: str(result.get(key)) == str(gold[key])
              for key in ("vendor", "date", "total", "vat", "vat_rate") if key in gold}
    output = {"status": "measured" if result["raw_text"] else "inference_unavailable",
              "image": str(args.image), "metrics": metrics, "exact_field_match": fields,
              "field_accuracy": sum(fields.values())/len(fields) if fields and result["raw_text"] else None,
              "result": result}
    Path(args.out).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": output["status"], "metrics": metrics}, ensure_ascii=False))
    return 0 if output["status"] == "measured" else 2


if __name__ == "__main__":
    raise SystemExit(main())
