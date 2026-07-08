# Music Hub

Django music catalog with:
- Local-first search
- Optional MusicBrainz import on empty results
- Account-based favorites and protected edit actions
- Swiss-style responsive UI redesign

## Local Setup

1. Create and activate a virtual environment.
2. Install dependencies.
3. Run migrations.
4. Create an admin user.
5. Start the server.

```bash
python -m venv .venv
source .venv/bin/activate
pip install django pillow
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install django pillow
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Local Test Commands

```bash
python manage.py test
```

## Database Rebuild (Local)

If you want a clean rebuild:

Linux/macOS:

```bash
rm db.sqlite3
python manage.py migrate
python manage.py seed_music
```

Windows PowerShell:

```powershell
Remove-Item db.sqlite3
python manage.py migrate
python manage.py seed_music
```

## MusicBrainz Import Paths

### 1. From Search Page

- Search local data first.
- If no results, click **Try MusicBrainz import**.
- Imported records are cached into local DB immediately.

### 2. From JSON File

Use the management command:

```bash
python manage.py import_musicbrainz_json /path/to/file.json
python manage.py import_musicbrainz_json /path/to/file.json --limit 100
```

Supported JSON shapes:
- A single release object
- A list of release objects
- A payload like `{"releases": [...]}`

## About PostgreSQL MusicBrainz Dumps

Official MusicBrainz PostgreSQL dumps are not in the same schema as this app.
Recommended workflow:

1. Import the dump into a separate PostgreSQL database dedicated to MusicBrainz.
2. Extract only the fields you need (MBIDs, artist names, release titles, dates, tracks) into JSON.
3. Feed that JSON into `import_musicbrainz_json`.

If you share a real dump extract format, add a direct ETL command for it.

## Production Notes (Ubuntu + Nginx + Cloudflare)

1. Ensure `/static/` and `/media/` are both served by Nginx.
2. Run `python manage.py collectstatic --noinput` on deploy.
3. Keep `MEDIA_ROOT` persistent between deployments.
4. Purge Cloudflare cache after static updates.
5. Confirm Nginx has a dedicated `location /media/` block pointing at your media directory.

## Auth Routes

- Login: `/accounts/login/`
- Logout: `/accounts/logout/`
- Signup: `/accounts/signup/`
