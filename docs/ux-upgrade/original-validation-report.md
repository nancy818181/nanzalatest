# Validation Report

## Status

**Not certified for live accounting data.** The latest full test run found two release regressions; both were fixed and their targeted tests now pass, but the entire suite has not been rerun since those fixes. Flutter validation and OCR processing are also incomplete.

## Environment

- Windows
- Python 3.11.9
- pytest 9.1.1
- Flutter/Dart: unavailable

## Test results

The most recent full run, before the latest targeted fixes, reported:

- 1,061 passed
- 4 skipped
- 166 subtests passed
- 2 failed

The failures were investigated and addressed:

1. `ChartTemplateTest.test_every_account_the_program_posts_to_is_in_every_chart` identified the requested real accounts `6011`, `4211`, and `6264.1` missing from the cross-chart spine. Those codes are now included.
2. `ErrorHandlingTest.test_broad_excepts_do_not_grow` found one broad handler over the repository limit. The new invoice suggestion handler now catches the client and input errors it reports explicitly.

After the feature changes, targeted account-assistant, account API, AI, chart-template, and release-check tests passed: **29 passed, 16 subtests passed**. The invoice-edit UI regression also passed independently.

The full suite has **not** been rerun after the latest two fixes. Therefore, the latest full-suite counts are not a final all-green result.

## Free AI Account feature

- The chart loader discovered the active source file and loaded its real account codes, including all configured base accounts. The discovered chart in this repository contains 572 entries; it is not the 388-entry workbook described in the request.
- Arabic/English/French keyword suggestions and detailed-account creation are tested against both a fake client and an initialized company database.
- The test cases for electricity, generator/administration detail accounts, rent-office, and Ogero/internet passed. The company database generated `626340001` under `6263.4`, then reused it instead of duplicating the account.
- Focused feature tests: **6 passed** (included in the combined 29-test run above).

## Mobile and OCR limitations

- The Flutter project and mobile API wiring are present, but Flutter/Dart is unavailable in this environment. No `flutter analyze`, device test, or APK build was performed.
- OCR uploads can be queued and their status retrieved. An OCR processing worker was not demonstrated, so queueing does not establish OCR completion.

## Release gate

The source archive is a validation candidate, not a live-ready certification. Rerun `python -m pytest tests/ -q` after the final changes and complete Flutter/device and OCR-worker validation before using it with live accounting data.
