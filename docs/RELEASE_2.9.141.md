# Nanza Accounting 2.9.141 — Classic release candidate

Baseline: origin/main c7e8ad0e57ab4c3c0ec3fae6a273cc25c5ffac6d (2.9.140).
Prior fixes integrated from fix/volume-vat-layout-20261126 at 25699f3692d218f25d73aa7c7eb2c1c2d0e4a975.

Classic is the default theme in the existing Tk application. Existing grouped/upper navigation preferences remain supported. Shared theme colors cover entry, quotation, cash/payment, journal, report and dashboard callers. No product module was added, so no additional PyInstaller hidden import is required.

## Verification

Run from repository root:

    python -m unittest discover -v -s tests -t . -p "test_*.py"

Targeted UI/financial commands and source-tied results are delivered with the release evidence. Actual Windows display scaling is distinct from Tk scaling simulation. Screenshots must be paired with their captured client size, OS scaling and language. Main must not be marked published until the merged commit and its checks are verified remotely.

## Accounting and compatibility

Existing documents and account mappings remain intact. Explicit taxable advances follow the owner's approved policy (Q1 base100/VAT11; final invoice Q2 base300/VAT33; net Q2 VAT22). This is not a legal opinion on Lebanese declaration boxes. Fractional foreign-currency carrying differences remain a release gate pending the accountant's decision; do not silently apply a rounding plug. Previously approved additive tables/indexes are inherited from the integrated pilot branch.

## Publication status

Release candidate on a working branch. Publication and readiness are determined by the final evidence and PR checks, not this version heading. Pending financial gates must be disclosed and resolved before merge.
