# Checklist Implementation Phases

This plan maps the MVP and UI checklist documents into work that fits the current Django app.

## Phase 1 - Critical MVP/UI Hardening

- Responsive baseline: viewport fit, mobile navigation adjustments, horizontal table scrolling.
- Accessibility baseline: skip-to-content link, visible focus rings, semantic table headers, ARIA live alerts, modal focus handling.
- UX quick wins: toast-style messages, reusable confirmation modal, export loading labels, overdue row highlighting, role/action/status badges.
- Print and motion safety: print stylesheet for reports/tables and reduced-motion support.
- Professional fallback pages: 403, 404, and 500 templates.

## Phase 2 - Current MVP Operations - Implemented

- Strengthened report and audit screens with report tabs, overdue emphasis, action filtering, immutable-log notice, and export affordances.
- Added filtered audit CSV export for compliance review.
- Added days-overdue display to transaction/report rows and fixed overdue row highlighting on report tables.
- Continued current-model UI polish without starting larger API/PWA/mobile tracks.

## Phase 3 - Admin, Notifications, and Reporting - Implemented

- Expanded settings into grouped General, Users & Roles, Notifications, Data, Appearance, and Security sections.
- Added inventory summary reporting with CSV/PDF export and print-specific report header.
- Added admin health summaries for user status, notification logs, data totals, session timeout, and login attempt limits.
- Left background queues/retry workers as a deployment-phase task because they require hosting/runtime decisions.

## Phase 4 - Future Platform Work

- Public item availability page implemented at `/public/items/`.
- UI checklist quick wins added: safe login redirect/remember-me UX, show/hide password, login loading state, visible topbar search and alert counters, persisted responsive navigation, breadcrumb baseline, mobile header/tab bar, dashboard status strip, item filter chips/category/sort controls, and borrower active/overdue status badges.
- Added a shared SVG icon system across the app shell, sidebar, mobile tabs, dashboard, forms, list actions, reports, settings, receipts, archives, and the public availability filters.
- MVP checklist continuation added: item forms now use centrally configured category suggestions from System Settings, with a sticky cancel/save action bar.
- Remaining: borrower self-service portal, PWA/offline installability, QR/barcode workflows, API/JWT/OpenAPI, mobile app, advanced charts, and external monitoring.
- These are larger product tracks and should be handled after the core admin/staff workflows are stable.

## Phase 5 - Borrow / Return Flow - Implemented

- Added a guided four-step borrow form with explicit borrower, item, due date, and receipt steps.
- Added stronger return lookup with search and Borrowed/Overdue filters.
- Added required notes for damaged returns so maintenance records have useful context.
- Added printable transaction receipts after both borrow and return processing.
- Added receipt links from transaction history.

## Phase 6 - Safety & Data Integrity - Implemented

- Kept borrow and return writes inside atomic transactions with row locks for borrower, item, and transaction records.
- Added graceful handling when an item is borrowed by another transaction during submit.
- Added a database-level unique constraint so each item can have only one active Borrowed/Overdue transaction.
- Added regression tests for borrow limits, damaged return validation, receipt flow, return lookup, and active-transaction uniqueness.

## Phase 7 - User Management - Implemented

- Added user search, role filters, status filters, and summary cards for active/inactive/admin/staff users.
- Polished user rows with avatars, role/status badges, icons, and clearer edit/reset/deactivate actions.
- Improved user edit and password reset pages with account context, role guidance, and sticky action bars.
- Added safeguards so admins cannot remove their own admin access or deactivate their own account.
- Added safeguards so the last active administrator cannot be deactivated or demoted.

## Phase 8 - Supabase / Backup Readiness - Implemented

- Added redacted database readiness details to System Settings, including provider, connection status, engine, host, database name, and SSL mode.
- Added a Backup & Restore settings section with backup folder visibility, recent backup history, LAN/debug readiness indicators, and a restore checklist.
- Added an admin-only Create JSON Backup action that runs the backup command from the web UI and records an audit log.
- Enhanced `backup_system_data` so each JSON export also writes a safe manifest with database metadata and record counts.
- Updated deployment notes with the backup and restore workflow for Supabase/local demos.

## Phase 9 - Notification Operations - Implemented

- Added an admin Notification Center with due-soon, due-today, overdue, and failed-log summary cards.
- Added searchable/filterable notification logs by channel, status, event type, recipient, message, item, borrower, or error.
- Added an admin-only Run Reminder Check action with dry-run support for safe testing.
- Linked notification readiness into System Settings so admins can see due queues and open the Notification Center.

## Phase 10 - Public Self-Service / QR Readiness - Implemented

- Added a public borrower lookup page that requires school ID and registered email before showing active borrows or recent returns.
- Added public item detail pages that show live availability and are ready to be used as QR label targets.
- Added QR Page links from the staff item list and public item availability cards.
- Added a Borrower Lookup link to the public equipment availability page.

## Phase 11 - Manual / Semi-Automatic Run Flow - Implemented

- Upgraded `Start Shared System.bat` into the main one-click shared starter.
- Enhanced `run_lan_server.ps1` to choose the next free port from `8000` to `8010` when the default port is busy.
- Added automatic Edge/Chrome opening for the local computer while still printing LAN links for other devices.
- Printed clear same-Wi-Fi URLs, backup IP URLs, and a warning not to browse to `0.0.0.0`.
- Forced local shared mode to allow LAN hosts for the starter process.
- Documented the new run flow and the optional `-NoBrowser` mode in the README.
