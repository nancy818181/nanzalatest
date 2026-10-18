# Purchase intake validation — Nanza 2.9.128

## Result

The source regression suite passed on Linux with a virtual graphical display:

    1071 passed, 2 skipped, 177 subtests passed in 705.52s (0:11:45)

The two skips are Windows-only startup checks:
- tests/test_v2_9_88.py::WindowsStartTest::test_speed_on_windows
- tests/test_v2_9_88.py::WindowsStartTest::test_start_while_the_shm_file_is_held

This is source validation, not a Windows installer/upgrade or live-data deployment certificate.

## Preservation

- All original uploaded Python paths remain present.
- All 24 protected payroll, salary, employee and related test files are byte-for-byte identical to the uploaded ZIP. Hashes are supplied alongside this report.
- The uploaded reports, AI Accountant, payroll calculations, salary entries and employee modules were retained. No payroll account mapping was changed.
- Missing Assets and build definitions were restored from the preceding complete archive; existing source was not replaced with that older source.
- Windows backslash ZIP paths were normalized into standard archive directories.

## Exact checks

| Check | Before | After |
|---|---|---|
| Payroll, with graphical display | 78 passed; 37 subtests | 78 passed; 37 subtests |
| Salary / employee selection | 29 passed; 15 subtests | 29 passed; 15 subtests |
| Entire original ZIP, headless | 17 failed, 976 passed, 62 skipped, 6 errors, 160 subtests passed in 335.24s (0:05:35) | See graphical full-suite result above |
| Focused purchase, PDF intake, chart and release checks | Not applicable | 64 passed; 18 subtests |

Commands used: python -m pytest tests/ -q -k payroll -p no:cacheprovider;
python -m pytest tests/ -q -p no:cacheprovider. PYTHONDONTWRITEBYTECODE=1 was enabled.
Python 3.12, pytest 9.1.1, pytest-subtests 0.15.0; Xvfb supplied the graphical display.
The screenshot is an actual capture of a read-only viewer showing the captured pytest output, not a Windows installer screenshot.

## What was fixed

The previous parser lacked supplier/purchase evidence rules, and enrichment retained an erroneous Sales hint. Purchase evidence now overrides that hint while preserving credit/debit-note type, unknown monetary values and human review.

check_90_percent_rule() counts suggested accounts across all observed rows. Nine out of ten produces a success coverage notice; lower coverage, empty or explicitly truncated readings warn. The count is not OCR accuracy. It never grants posting permission.

Desktop purchase intake displays the notice above its document details and in photo review. POST /api/purchase/intake returns notification_90 after annotation. POST /api/purchase/upload reads image/PDF content with the existing local reader and returns the same field; company-scoped OCR status includes it after processing. Existing generic receipt-queue behavior remains available.

A real HTTP/database integration probe passed intake, upload and company-scoped status with 9/10 classified rows; OCR was mocked in that probe. This does not benchmark optical accuracy on real invoices.

## Account creation and Oscar limitation

suggest_and_autocreate() uses the selected company's actual active chart. It reuses existing nine-digit posting accounts or creates an audited child under one uniquely identified, unused expense parent in the 6011/626 families. It never invents missing parents, changes payroll or posts invoices. The tested 6263.4 example allocates 626340001 and reuses it on the next call.

No PLAN_COMPTABLE_OSCAR.XLS was supplied in the ZIP. Automatic workbook discovery is implemented, and the selected company database remains authoritative. The claimed 388-account workbook contents could not be independently verified. No paid/cloud API was added or used; existing explicitly selected Azure functionality is retained.

## Changed existing Python files relative to the upload

- nanza/api_ocr.py
- nanza/core/client.py
- nanza/core/server.py
- nanza/core/app_runtime.py
- nanza/ui/desktop_stage3_common.py
- nanza/ui/desktop_invoice_intake.py
- nanza/ui/desktop_purchases.py
- nanza/documents/invoice_intake.py
- nanza/documents/pdf_import.py

New code: nanza/documents/purchase_intake.py and tests/test_purchase_90.py.
Version/changelog/build metadata and these validation artifacts were updated as well.
