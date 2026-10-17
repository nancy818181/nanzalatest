# Handwriting reader work in progress

These source changes are experimental. They do not establish reliable automatic
handwriting transcription and do not replace the released reader by default.

## Implemented

- An optional local Qwen3-VL 4B Q4 reader and an independent 2B Q4 reader run
  sequentially. Their pinned model files and portable llama.cpp runtime are
  downloaded only when setup is explicitly selected, with checksum verification.
- Setup needs approximately 4.5 GB of downloads and 5 GB of disk space. The runtime
  checks for approximately 6 GB of available RAM. Each model call has a deadline;
  cancellation kills the active process. Reading does not upload the document.
- Header and total suggestions are compared independently. Conflicting or singly
  read values are withheld, and both candidates are retained for review. Agreement
  is not verification: both models can produce the same incorrect answer.
- Invoice photos flagged for review open beside their editable fields. Conflicting
  4B/2B suggestions are displayed. The user must explicitly confirm checking the
  image before the suggestions fill an entry form. Cancelling an expense review
  preserves its previous attachment. This confirmation does not post an entry.
- Expense keyword classification exposes conflicting categories rather than
  selecting an arbitrary tied account. Repeated headers do not increase a keyword's
  weight. A conflicting current expense description prevents automatic reuse of
  a supplier's saved account. Ranking scores are not presented as measured accuracy
  percentages.
- Sales invoice fields use adjacent groups across the available viewport and
  reflow on smaller windows. Existing variables, actions and entry calculations
  are retained.

## Unfinished validation and limitations

- Previous manual trials showed incorrect amounts and dates with both small
  vision models, even with arithmetic-consistent output. Prompt length increased
  latency without establishing accurate transcription.
- Manually cropped regions improved some item descriptions and reduced latency,
  but also produced incorrect quantities, dates, currencies and amounts. Those
  crops were feasibility experiments, not an implemented automatic layout detector.
- The complete last regional benchmark was not recovered after the session's
  temporary files disappeared. Do not describe the full benchmark as passed or
  quote a handwriting accuracy percentage.
- The current vision parser extracts header and total fields. It does not yet
  provide verified line-item extraction. Candidate item lists must not be merged
  by position because the readers may omit or reorder rows.
- Classification does not determine VAT recoverability or income-tax deductibility.
- Real Windows setup, GUI behaviour and reading performance still need testing.
  Unit tests of mocked reader responses do not establish real OCR accuracy.

The existing UI tests and source checks should be run before publishing any new
version. Do not distribute the private invoice photographs, raw OCR output, model
weights, local caches or test credentials in the public source repository.

## Verification checkpoint (17 October 2026)

- A full test run completed 935 tests with no failures and 62 skips in the headless
  environment. Subsequent setup/resource-limit and supplier-memory changes were
  covered by a final focused run of 66 tests, all passing.
- Native Linux/Tk checks exercised the invoice field bounds at 1920, 1366 and 1024
  pixels, in left-to-right and right-to-left layouts. A real review dialog opened,
  and cancellation returned no fields. Arabic glyph appearance was not validated
  because the virtual display did not render the Arabic captions correctly.
- The new regression test confirms that the progress-window path actually starts
  its worker and delivers the result back on the calling UI thread.
- The optional reader remains disabled without an explicit successful setup.
- No Windows installer or real-model accuracy validation is claimed by these tests.

## Lightweight Arabic OCR experiment (17 October 2026)

Completed 32 local Tesseract Arabic+English passes on the four supplied photos:
24 full-page/header/amount-region readings using original and contrast variants,
and eight readings using the existing perspective/background/table-rule preparation.
Arabic tessdata_fast was downloaded from the official tesseract-ocr repository
for this experiment only; it is not bundled or enabled by this change.

The experiment did not establish a usable handwritten amount reader. Header crops
retained the first document's date in some variants, but the other handwritten
dates and totals remained missing or corrupted. On the printed electricity bill,
one prepared reading recognized the VAT amount 73838, stamp 100000 and rounding
912, while corrupting the grand total to 96000. These are raw transcription
observations, not validated structured extraction or a measured accuracy rate.

No automatic filling or posting logic was changed based on these results.
The regions were fixed experimental crops, not a general document detector.
Private crops, raw results and downloaded language weights remain outside git.


## Final 2.9.127 reader contract

The literal v2 prompt and parser accept the structured owner schema while retaining the existing evidence schema. Supplier tax identity and up to 12 as-written rows are retained. Explicit French/Arabic separators are supported; ambiguous or disputed monetary values stay unknown. Model-reported confidence and payment status are ignored for posting authorization. Human review remains mandatory. Real-model optical accuracy with this prompt remains unmeasured.
