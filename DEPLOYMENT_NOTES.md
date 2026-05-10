# Deployment Notes

## Environment Variables

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_ALLOW_LAN_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `SUPABASE_DATABASE_URL`
- `DJANGO_SECURE_SSL_REDIRECT`
- `DJANGO_DB_CONN_MAX_AGE`
- `DJANGO_SQLITE_NAME`
- `DJANGO_EMAIL_BACKEND`
- `DJANGO_EMAIL_HOST`
- `DJANGO_EMAIL_PORT`
- `DJANGO_EMAIL_HOST_USER`
- `DJANGO_EMAIL_HOST_PASSWORD`
- `DJANGO_EMAIL_USE_TLS`
- `DJANGO_EMAIL_USE_SSL`
- `DJANGO_DEFAULT_FROM_EMAIL`
- `DJANGO_SERVER_EMAIL`
- `DJANGO_LOG_LEVEL`
- `DJANGO_LOGIN_RATE_LIMIT_ATTEMPTS`
- `DJANGO_LOGIN_RATE_LIMIT_WINDOW`
- `DJANGO_CONTENT_SECURITY_POLICY`
- `DJANGO_PERMISSIONS_POLICY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Recommended Production Steps

1. Set `DJANGO_DEBUG=False`.
2. Set a strong `DJANGO_SECRET_KEY`.
3. Configure `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` for the deployment domain. Keep `DJANGO_ALLOW_LAN_HOSTS=False` in production.
4. Run:
   - `python manage.py migrate`
   - `python manage.py collectstatic`
5. Serve the app behind HTTPS in production.
6. If you are using Supabase, install dependencies from `requirements.txt` and configure:
   - `SUPABASE_DATABASE_URL=<your Supabase database URI>`
   - local helper: `.\connect_supabase.ps1 -DatabaseUrl "<your Supabase database URI>"` writes the URL to `.env`, runs migrations, and verifies the connection
   - add `-ImportCurrentData` to the helper command when you want to move the existing local SQLite users, borrowers, items, transactions, and logs into Supabase
7. If your app is behind Nginx or a platform proxy, make sure it forwards `X-Forwarded-Proto=https`.
8. Verify password reset emails:
   - development: console backend
   - production: set a real email backend and SMTP credentials
9. Verify the health endpoint after deploy:
   - `GET /health/`
   - expect HTTP `200` and JSON status `ok`
10. Create an application backup:
   - `python manage.py backup_system_data`
   - optional: `python manage.py backup_system_data --output-dir C:\path\to\backups`
11. If you want Telegram notifications enabled, set:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
12. Run or schedule due-date notifications:
   - `python manage.py send_due_notifications`
   - optional preview: `python manage.py send_due_notifications --dry-run`

## Local Phone / Tablet Access

For local development, keep `DJANGO_DEBUG=True` and `DJANGO_ALLOW_LAN_HOSTS=True`, then start the server on all interfaces:

```powershell
.\run_lan_server.ps1
```

Or run the equivalent command manually:

```powershell
..\..\venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

Open the displayed preferred `http://<your-computer-name>:8000/` URL on any phone, tablet, or laptop connected to the same Wi-Fi/network. If that name does not resolve on a device, use one of the displayed backup `http://<your-computer-ip>:8000/` URLs. If the page does not load, allow Python through Windows Firewall and confirm both devices are on the same network.

For a double-click startup, run `Start Shared System.bat` from the project folder. Keep the window open while people are using the system.

## Due-Date Email Notifications

Run this command once per day to send borrower reminders and overdue alerts:

```powershell
..\..\venv\Scripts\python.exe manage.py send_due_notifications
```

The command:
- sends borrower reminders before the due date based on `reminder_days_before_due`
- sends borrower reminders on the due date
- marks overdue borrowed transactions as `Overdue`
- emails the borrower and active Admin/Staff users about overdue items
- records every sent, skipped, or failed email in `NotificationLog`

Use Windows Task Scheduler for local/demo scheduling, or a production scheduler/Celery-style worker after deployment.

Admins can also run the same reminder pass from the in-app Notification Center. Use dry-run first when checking a new deployment or email configuration.

## Public Self-Service / QR Pages

- Public equipment list: `/public/items/`
- Public borrower lookup: `/public/borrower/`
- Public item QR target: `/public/items/detail/<item-id>/`

Borrower lookup requires both school ID and registered email. Item QR target pages are intended for QR labels attached to equipment and show live public availability without exposing borrower details.

## Backup Guidance

- Back up `db.sqlite3` regularly if you continue using SQLite.
- For multi-user production use, prefer Supabase over local SQLite.
- Admin users can create a dated JSON backup from Settings -> Backup & Restore.
- Each backup includes a `.manifest.json` file with safe metadata, database provider, and record counts. It does not include database passwords or full connection strings.
- Recommended Supabase backup pattern:
  - enable automated Supabase backups in the dashboard
  - keep dated application JSON exports from `backup_system_data`
  - test restore on a non-production Supabase project before relying on backups
- Restore checklist:
  - stop the running Django server
  - copy the newest backup JSON to a safe folder
  - run `python manage.py migrate`
  - restore with `python manage.py loaddata path\to\backup.json`
  - run `python manage.py check` and open `/health/`

## Example Supabase Environment

```env
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=replace-with-a-real-secret
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,your-domain.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.com
SUPABASE_DATABASE_URL=copy-your-supabase-database-uri-here
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_EMAIL_HOST=smtp.your-provider.com
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_HOST_USER=your-smtp-user
DJANGO_EMAIL_HOST_PASSWORD=your-smtp-password
DJANGO_EMAIL_USE_TLS=True
DJANGO_DEFAULT_FROM_EMAIL=noreply@your-domain.com
DJANGO_LOG_LEVEL=INFO
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-telegram-chat-id
```
