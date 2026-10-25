# Nanza 2.9.135 — release notes

Date: 25-10-2026. Previous version: 2.9.134.

## What changed

- Improved the Sales Invoice toolbar and compact field layout.
- Reorganized the Purchase Invoice header, account fields, and action area.
- Aligned Customer Receipt and Supplier Payment controls.
- Grouped Trial Balance and Statement of Account filters and actions.
- Separated Chart of Accounts browsing from account creation.
- Improved Customs Report filter layout and selection controls without changing report calculations or data sources.
- Made The Complete Board Dashboard open maximized and resize with the available window.

## Scope and validation

These changes are limited to presentation and the application version markers. They do not change accounting calculations, VAT rules, posting, permissions, account validation, database schema, or stored data.

Focused tests (`tests.test_workbench_upgrade`, `tests.test_advanced_reporting`, `tests.test_ui_design_blocks`, and translation-catalogue checks; 46 passed, 1 skipped because no GUI display was available), Python compile checks for changed modules, translation JSON validation and compilation, and `git diff --check` passed. GUI visual inspection was unavailable in the build environment. The Windows installer workflow must complete successfully before the new installer is considered ready to install.
