# Manual Browser Walkthrough

Use Microsoft Edge or Chrome and press `Ctrl+F5` after UI changes.

## Staff Flow

1. Open `/login/`.
2. Select `Staff`, continue, and sign in.
3. Open Dashboard and confirm Today Focus plus attention cards are visible.
4. Add or edit a borrower.
5. Add or edit an item.
6. Borrow an available item and confirm the receipt page opens.
7. Print the receipt.
8. Return the item and confirm returned/damaged notes behavior.

## Admin Flow

1. Sign in as Admin.
2. Open Users and confirm filters, edit, reset password, and status toggles.
3. Open Notifications and use Dry run before running reminders.
4. Open Settings.
5. Create a JSON backup from Backup & Restore.
6. Confirm Database Status is connected and does not show passwords.

## Public Flow

1. Open `/public/items/`.
2. Filter by status and category.
3. Open a QR status page from an item card.
4. Open `/public/borrower/`.
5. Search with a valid school ID and registered email.
6. Try a wrong email and confirm borrower details stay hidden.

## Print / Export

1. Open `/items/qr-labels/` and print labels.
2. Open Reports and export CSV/PDF.
3. Print Reports.
4. Open a borrower profile and print history.

## GitHub Safety

1. Read `GITHUB_READY.md`.
2. Confirm `.env`, `db.sqlite3`, backups, and transfer files are not staged.
3. Push only after `manage.py check` and tests pass.
