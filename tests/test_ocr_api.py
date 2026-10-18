"""Tests for company-scoped OCR receipt queue persistence."""
import tempfile
import unittest
from pathlib import Path

import nanza_paths  # noqa: F401
from database import Database
from nanza.api_ocr import queue_receipt, queue_status


class OcrQueueTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.db = Database(Path(folder.name) / "company.db")
        self.db.initialize("ocr-queue-test")
        self.addCleanup(self.db.release)
        self.user = self.db.user_for_token(
            self.db.login("admin", "ocr-queue-test")["token"])

    def test_upload_is_stored_and_scoped_to_company(self):
        result = queue_receipt(
            self.db, "company-test", "receipt.jpg", "image/jpeg",
            b"test-image", self.user["id"])
        self.assertEqual(result["status"], "queued")
        status = queue_status(self.db, result["queue_id"], "company-test")
        self.assertEqual(status["status"], "pending")
        with self.db.connect() as connection:
            stored = connection.execute(
                "SELECT file_path FROM ocr_queue WHERE id=?", (result["queue_id"],)
            ).fetchone()
        self.assertEqual(Path(stored["file_path"]).read_bytes(), b"test-image")
        with self.assertRaisesRegex(KeyError, "not found"):
            queue_status(self.db, result["queue_id"], "another-company")

    def test_rejects_unsupported_file_types_and_company_paths(self):
        with self.assertRaisesRegex(ValueError, "JPEG, PNG"):
            queue_receipt(self.db, "company-test", "receipt.exe", "application/octet-stream",
                          b"data", self.user["id"])
        with self.assertRaisesRegex(ValueError, "valid company"):
            queue_receipt(self.db, "../outside", "receipt.jpg", "image/jpeg",
                          b"data", self.user["id"])


if __name__ == "__main__":
    unittest.main()
