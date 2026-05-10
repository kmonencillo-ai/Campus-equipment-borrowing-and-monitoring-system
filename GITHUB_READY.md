# GitHub Readiness

This project is ready to upload to GitHub after you review the checklist below.

## Safe To Commit

- Django source code in `core/` and `myproject/`
- Templates and static assets
- `requirements.txt`
- `.env.example`
- `CHECKLIST_PHASES.md`
- `DEPLOYMENT_NOTES.md`
- `run_lan_server.ps1`
- `Start Shared System.bat`

## Do Not Commit

These are ignored by `.gitignore`:

- `.env` and any real environment file
- `db.sqlite3`
- `backups/`
- `test-backups/`
- `test-view-backups/`
- `supabase-transfer.json`
- `staticfiles/`
- virtual environments such as `venv/` or `.venv/`

## Before First Push

1. Check that `.env` is not staged.
2. Check that `db.sqlite3`, backups, and transfer files are not staged.
3. Rotate any secret that was ever pasted into chat, screenshots, or a public place.
4. Keep real Supabase, Telegram, email, and Django secret values only in `.env` or hosting environment variables.
5. Use `.env.example` as the template for other machines.

## Suggested Git Commands

```powershell
git init
git add .
git status
git commit -m "Initial campus equipment system"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
git push -u origin main
```

Run `git status` carefully before committing. If you see `.env`, `db.sqlite3`, `backups`, or `supabase-transfer.json`, stop and remove them from staging before pushing.
