# Campus Equipment Borrowing & Monitoring System

A Django-based campus equipment system for Admin and Staff workflows, with Supabase database support, borrower/item management, borrow and return processing, receipts, reports, notifications, backups, public availability pages, borrower self-service lookup, and QR label printing.

## Features

- Admin/Staff role-based login
- Borrower and item management
- Borrow and return transactions
- Printable receipts
- Reports with CSV/PDF export
- Activity logs
- Email and Telegram notification logging
- Notification Center with dry-run reminder checks
- Supabase-ready database configuration
- JSON backups with manifests
- Public equipment availability page
- Public borrower lookup
- QR-ready item status pages and printable QR labels
- LAN sharing helper for same-Wi-Fi demos

## Local Setup

```powershell
cd C:\Users\juneh\Documents\SDPROJECT\myproject\myproject
..\..\venv\Scripts\python.exe manage.py migrate
..\..\venv\Scripts\python.exe manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

## Same-Wi-Fi Sharing

Run:

```powershell
.\run_lan_server.ps1
```

The script prints the preferred local network URL and backup IP URL. Keep the terminal window open while other devices use the system.

## Environment Variables

Copy `.env.example` to `.env`, then fill in real values locally.

Never commit `.env`.

Important variables:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `SUPABASE_DATABASE_URL`
- `DJANGO_EMAIL_*`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Tests

Use SQLite override for local tests so they do not touch Supabase:

```powershell
$env:SUPABASE_DATABASE_URL=' '
..\..\venv\Scripts\python.exe manage.py check
..\..\venv\Scripts\python.exe manage.py test core
```

## Backups

Create a backup from Admin Settings, or run:

```powershell
..\..\venv\Scripts\python.exe manage.py backup_system_data
```

Backups are written to `backups/`, which is intentionally ignored by Git.

## GitHub Safety

Read `GITHUB_READY.md` before pushing. Confirm these are not staged:

- `.env`
- `db.sqlite3`
- `backups/`
- `test-backups/`
- `supabase-transfer.json`
- `venv/`

## Deployment

Deployment is intentionally separate. See `DEPLOYMENT_NOTES.md` when you are ready for a permanent public link or hosted domain.
