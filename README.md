# ContentFlow — Client Approval Portal

A working, self-hosted MVP for video editors and social-media managers. Submit video drafts, share private client-review links, gather approvals or requested changes, and see status in your admin dashboard.

## What's included

- Password-protected **admin dashboard** and client management
- Upload MP4, MOV, WEBM, M4V reels (250 MB default maximum)
- Proposed captions and publishing dates
- Separate private client links with video preview
- One-click client approval or written revision requests
- Resubmit an item for another approval round
- Optional SMTP email when a reel is submitted, resubmitted, or reviewed
- SQLite data store and persistent local video storage
- Responsive interface, Docker support, and no paid dependencies required to run locally

**Not yet implemented:** automatic import from Google Drive, Instagram/Meta publishing, calendar view, replacement of video on the same post, analytics, WhatsApp notifications, multi-admin authentication, automated reminders. An approval **does not** publish the video. Keep manual publishing until a Meta-approved publishing integration is configured.

## Run locally (Mac / Windows / Linux)

1. Install Python 3.11+.
2. Open this project in VS Code / your terminal.
3. Create a virtual environment:

   ```bash
   python -m venv .venv
   # macOS/Linux
   source .venv/bin/activate
   # Windows PowerShell
   # .venv\\Scripts\\Activate.ps1
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and edit `APP_SECRET`, `ADMIN_PASSWORD`, and `PUBLIC_URL`.
5. Load the environment and start:

   **macOS/Linux:**
   ```bash
   set -a; source .env; set +a
   uvicorn app:app --reload
   ```

   **Windows PowerShell:**
   ```powershell
   Get-Content .env | Where-Object { $_ -match '^[A-Za-z_][A-Za-z0-9_]*=' } | ForEach-Object { $k,$v = $_ -split '=',2; [Environment]::SetEnvironmentVariable($k,$v,'Process') }
   uvicorn app:app --reload
   ```

6. Open **http://localhost:8000** and sign in with `ADMIN_PASSWORD`.
7. Create a client → submit content → copy their portal link. For local testing, open the client link in a private/incognito tab.

**Alternative with Docker:** edit `.env`, then run `docker compose up --build`. Visit http://localhost:8000. Docker data persists in `./data`.

## Email notifications

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` and `ADMIN_EMAIL` in `.env`; restart the app. SMTP STARTTLS defaults to on. Without SMTP, the portal still works and you can manually copy review links. Note that providers such as Gmail typically require app-specific authentication or a transactional email provider.

## Deploying

### Render

1. Push `render.yaml` to GitHub, then create a Blueprint in Render and connect this repository's `main` branch.
2. Set a strong `ADMIN_PASSWORD` when prompted and deploy. Render generates `APP_SECRET` automatically.
3. The Blueprint uses a paid `0.5c-512mb` (Starter) web service and a 1 GB persistent disk for the database and uploads. Persistent storage incurs a recurring charge; increase the disk size if needed.
4. Open the `*.onrender.com` URL shown by Render and sign in with the admin password you set. The app uses Render's assigned URL for client review links.

- Push code to a **private GitHub repository** (never commit `.env` or `data/`).
- Deploy the Docker container to a host with **persistent volume storage** for `/app/data` (database + videos). A host with an ephemeral filesystem will lose content on restart.
- Set `PUBLIC_URL` to the real HTTPS domain and use strong random `APP_SECRET` and `ADMIN_PASSWORD`.
- Add HTTPS, SMTP credentials and appropriate upload/reverse-proxy limits.
- Give each client only **their own** portal URL. These URLs function as bearer credentials. Anyone possessing one can view/review that client's content. Rotate tokens if compromised (token rotation UI not yet provided).
- Before use with real sensitive client content, add user accounts, token expiration or rotation, CSRF protection for cookie-based admin operations, production-grade object storage/backups, and rate limiting. Current login uses a single password and is intended for pilot use only.

## Working with Git

```bash
git init
git add .
git commit -m "Initial ContentFlow MVP"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/contentflow.git
git push -u origin main
```

Create an empty GitHub repository first. GitHub is source control, **not** the running backend.

## API integration notes

- `/api/health` provides a health check.
- Future n8n automation: Google Drive new-file trigger → authorized admin integration → new post submission → client notified; client approvals can be polled or a server-side webhook added.
- Instagram auto-publishing requires correctly authorized Meta accounts, OAuth permissions, media hosting, API limits and publication error handling. No credentials or capabilities are stubbed to falsely imply working posting.
