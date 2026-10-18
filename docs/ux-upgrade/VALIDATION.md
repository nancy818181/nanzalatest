# NANZA 2.9.129 — workflow upgrade validation

## Verdict and scope
Source upgrade validated on Linux/Python 3.12 with a real Tk graphical display (1366×900).
**Not a certification to deploy a new Windows installer to live accounting data.**
The installer was not built or exercised here. Windows-only checks remain for Windows CI.
Existing accounting/payroll calculations and all uploaded test files were retained.

## Exact results

| Run | Result |
|---|---|
| Uploaded source baseline, full pytest, headless | 1004 passed, 1 failed, 62 skipped; 164 subtests passed; 259.18s |
| Uploaded-source payroll/salary/employee tests, real GUI | 95 passed, 972 deselected; 40 subtests passed; 33.98s |
| Full unittest discovery with real GUI | **1093 tests run; OK, 2 skipped** (1091 successful); 522.820s |
| Final new-feature + release checks after final UI/export/lifecycle changes | **33 passed**, 12 subtests passed; 13.97s |
| Final payroll/salary/employee regression, real GUI | **95 passed**, 999 deselected; 40 subtests passed; 32.15s |

The full discovery run loaded the first 26 added test cases. A further window-lifecycle case
and the last UI/export refinements were validated in the final focused run (27 feature cases
plus 6 release checks). No old test was deleted, renamed, skipped or relaxed.
The original baseline release failure identified cache files from the uploaded archive and
the Linux-only test asset symlink in the unindexed source directory. The release package/index
excludes those development artifacts; release checks then pass without weakening their rules.

The two full-run skips are exactly:
- WindowsStartTest.test_speed_on_windows
- WindowsStartTest.test_start_while_the_shm_file_is_held

Some legacy full-suite GUI teardown paths emitted Tcl after-callback diagnostics. The focused
final run is clean. New workbench poll/scope/reminder timers and expense traces now cancel on
widget destruction; a new lifecycle regression verifies scheduled handles are removed.

## Coverage and protection
- 23 payroll/salary/employee source and related test files are byte-identical to the uploaded ZIP;
  see protected-payroll-sha256.json.
- Real SQLite tests cover date bucket boundaries, historical allocations, native currencies,
  credit-note signs, pending invoice exclusion, warehouse links without multiplied amounts,
  pagination/full export limits, user-isolated templates and reminder preferences.
- HTTP tests cover authentication, company/year selection, viewer write refusal and read-only GETs.
- GUI tests cover live preview, customer drill-down, template saving, actual PDF/Excel output,
  Arabic Excel RTL, clipboard copy, stale-result rejection and closure cleanup.
- Existing pre-save invoice duplicate confirmation remains active. The new optional inspection
  function also tests number/date/amount, currency and editing exclusion.
- New suggestions and forecasts do not post, create journals, alter payment status, change payroll,
  or call a paid/external AI API. Their GUI calls use the existing authenticated local data service.

## Measured query performance
20,000 synthetic invoice headers and lines, five runs on this Linux environment:
- First 500 matching custom-report lines: median **14.55ms**.
- Complete ageing grouping: median **249.54ms**.
These are query benchmarks only, not a reconciled company acceptance benchmark or Windows/end-to-end
latency guarantee. Raw measurements are in benchmark.json. No OCR accuracy benchmark was performed.

## Explicit remaining limits
1. **WhatsApp auto-send is not implemented/configured.** Preview, copy and a persisted 6pm local
   reminder are functional. The auto-send control is disabled and labelled as requiring a messaging
   gateway. Nothing is transmitted, no recipient is assumed, and no paid messaging API is used.
2. Custom reporting is an allowlisted **posted sales-line builder**, not arbitrary SQL/Odoo Studio.
   Header-only invoices are labelled as excluded. Full exports stop at 50,000 lines with an error.
   Date ranges are limited to the selected fiscal year's file; native currencies are never summed.
3. The 30-day chart is explicitly a historical cash-average illustration, not a commitment forecast.
   Existing analytic and longer-term cash-planning reports remain available.
4. The active project is Tk/ttk, not CustomTkinter. Existing theme and RTL hooks are retained.
   Native Windows fonts, compact-screen appearance, installer startup, update and backup/restore
   should be acceptance-tested on Windows before a live rollout. Linux bitmap-font screenshots
   are not evidence of final Windows Arabic typography.
5. Odoo/Zoho 8–9/10 is a product target, not a measured or certified result of this change.
6. The requested GitHub repository returned **404**, so publication is blocked by repository
   existence/access. No alternate repository, release or main branch was changed.

See USAGE.md for entry points, controls and operational limits. The four requested full-code files
are under nanza_delivery/; the active integration is nanza/ui/desktop_workbench.py, desktop.py,
desktop_expenses.py, core/server.py and core/client.py. The complete changed-file diff is included.
