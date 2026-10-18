"""Company-scoped receipt uploads and OCR queue status storage."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from database_common import utcnow


MAX_RECEIPT_BYTES = 15 * 1024 * 1024
MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}


def queue_receipt(database, company_id, file_name, mime_type, content, user_id, expense_id=None):
    company_id = str(company_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", company_id):
        raise ValueError("Select a valid company before uploading a receipt")
    mime_type = str(mime_type or "").split(";", 1)[0].strip().lower()
    extension = MIME_EXTENSIONS.get(mime_type)
    if not extension:
        raise ValueError("Receipt must be a JPEG, PNG, WebP, or PDF file")
    content = bytes(content or b"")
    if not content:
        raise ValueError("Choose a receipt file")
    if len(content) > MAX_RECEIPT_BYTES:
        raise ValueError("Receipt cannot exceed 15 MB")
    safe_name = Path(str(file_name or "")).name.strip()
    if not safe_name or safe_name in (".", ".."):
        raise ValueError("Receipt file name is required")

    queue_id = uuid.uuid4().hex
    upload_directory = Path(database.path).resolve().parent / "uploads" / "ocr" / company_id
    upload_directory.mkdir(parents=True, exist_ok=True)
    file_path = upload_directory / f"{queue_id}{extension}"
    try:
        with file_path.open("xb") as receipt:
            receipt.write(content)
        with database.connect() as connection:
            attachment_id = None
            if expense_id not in (None, ""):
                attachment_id = database.add_expense_attachment(
                    int(expense_id), safe_name, mime_type, content, user_id)
            cursor = connection.execute("""INSERT INTO ocr_queue
                (company_id,expense_id,attachment_id,file_path,file_name,mime_type,status,created_by,created_at)
                VALUES(?,?,?,?,?,?,'pending',?,?)""", (
                    company_id, int(expense_id) if expense_id not in (None, "") else None,
                    attachment_id, str(file_path), safe_name, mime_type, user_id, utcnow()))
            record_id = int(cursor.lastrowid)
    except BaseException:
        try:
            file_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return {"queue_id": record_id, "status": "queued"}


def queue_status(database, queue_id, company_id):
    try:
        record_id = int(queue_id)
    except (TypeError, ValueError) as exc:
        raise KeyError("OCR queue item not found") from exc
    with database.connect() as connection:
        row = connection.execute("""SELECT id,status,file_name,mime_type,expense_id,error,
            result_json,created_at,processed_at FROM ocr_queue
            WHERE id=? AND company_id=?""", (record_id, str(company_id))).fetchone()
    if not row:
        raise KeyError("OCR queue item not found")
    result = dict(row)
    if result.get("result_json"):
        import json
        result["notification_90"] = json.loads(result["result_json"]).get("notification_90")
    return result


def process_purchase_receipt(database, queue_id, company_id, user_id):
    """Read a company-owned upload locally, returning advisory line coverage."""
    import json
    from pdf_import import read_invoice_pdf
    from purchase_intake import annotate_purchase
    with database.connect() as connection:
        row = connection.execute('SELECT file_path FROM ocr_queue WHERE id=? AND company_id=?',
                                 (int(queue_id), str(company_id))).fetchone()
    if not row:
        raise KeyError('OCR queue item not found')
    try:
        result = annotate_purchase(read_invoice_pdf(row['file_path']), database, user_id, allow_create=True)
        with database.connect() as connection:
            connection.execute("UPDATE ocr_queue SET status='completed',result_json=?,processed_at=? WHERE id=? AND company_id=?",
                               (json.dumps(result, ensure_ascii=False, default=str), utcnow(), int(queue_id), str(company_id)))
        return {**result, 'queue_id': int(queue_id)}
    except (ValueError, OSError, RuntimeError) as exc:
        with database.connect() as connection:
            connection.execute("UPDATE ocr_queue SET status='failed',error=?,processed_at=? WHERE id=? AND company_id=?",
                               (str(exc)[:1000], utcnow(), int(queue_id), str(company_id)))
        raise
