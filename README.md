## The Ballot Box

Production-minded voter information web app built with **Python + Django**, emphasizing **trustworthy, source-attributed data** and **server-rendered pages** with **HTMX** filtering.

**Project name**: The Ballot Box  
**Data note**: Included fixtures are **fictional demo data**. This project **does not** ship real political data by default.

## Repository goals

- **Trust**: show sources + last-updated timestamps on public records
- **Auditability**: store raw provider payloads (`SourceRecord.payload`)
- **Server-rendered UX**: HTMX for dynamic filtering, not a SPA
- **Safe embeds**: allowlisted video providers + safe rendering (no raw iframe HTML stored)

## Features (public)

- **Homepage** with hero search + CTAs
- **Current Officials** directory (`/officials/`)
- **Candidates** directory (`/candidates/`)
- **Person** detail (`/people/<public_id>/`)
- **Office** detail (`/offices/<public_id>/`)
- **Jurisdiction** detail (`/jurisdictions/<public_id>/`)
- **District** detail (`/districts/<public_id>/`)
- **Global search** (`/search/?q=...`)
- Pagination, sorting, and **shareable filter URLs**
- JSON endpoints under `/api/` (directories + filter metadata)

## Tech stack

- **Django** (server-rendered templates)
- **PostgreSQL + PostGIS**
- **Redis**
- **Celery** (worker + beat)
- **Tailwind CSS**
- **HTMX**
- Docker Compose (local development)

## Local development (Docker Compose)

### Prereqs

- Docker + Docker Compose
- If you’re on **WSL2**, Docker must be available *inside the distro* (see troubleshooting below).

### Quickstart

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f web
```

In another terminal, create an admin user:

```bash
docker compose exec web python manage.py createsuperuser
```

Load **demo fixtures** into normalized tables + audit `SourceRecord` rows:

```bash
docker compose exec web python manage.py sync_demo
```

Note: `sync_demo` runs **local fixtures only**. New election data is synced via **Ballotpedia geographic** (`sync_ballotpedia_geographic`) when `BALLOTPEDIA_API_KEY` is set; Democracy Works is optional legacy (`sync_democracy_works` or `seed_data --with-dw`).

### Seed everything (fixtures + Ballotpedia geographic)

With `BALLOTPEDIA_API_KEY` set, `seed_data` loads demo fixtures (except Ballotpedia demo rows, which are skipped when the API key is present) and runs a **quota-friendly** Potter/Randall geographic sync:

```bash
docker compose exec web bash -lc "cd /app/src && python manage.py seed_data"
```

Optional legacy Democracy Works (requires `DEMOCRACY_WORKS_API_KEY`): `python manage.py seed_data --with-dw --dw-state TX`

Then open:

- App: `http://localhost:8000/`
- Admin: `http://localhost:8000/admin/`

### Tailwind styling

- In dev, the `assets` service runs Tailwind in `--watch` mode and writes to `src/static/css/app.css`.
- As a safety net, templates also include a **dev-only Tailwind CDN fallback** (so pages are not unstyled if the CSS build is temporarily missing). Do not rely on the CDN fallback for production.

```bash
docker compose up -d assets
docker compose logs -f assets
```

### Common commands

- **Run Django management commands** from the repo root:

```bash
python manage.py <command>
```

The root `manage.py` wrapper delegates to Docker Compose when Django is not installed locally. The explicit Docker form is:

```bash
docker compose exec web bash -lc 'cd /app/src && python manage.py <command>'
```

- **Run tests**:

```bash
docker compose exec web pytest
```

- **Run migrations**:

```bash
docker compose exec web python manage.py migrate
```

- **Rebuild containers**:

```bash
docker compose up -d --build
```

Note: Postgres and Redis are **not published to host ports** by default to avoid port conflicts. Use `docker compose exec db ...` / `docker compose exec redis ...` if needed.

### Restarting after an interrupted `docker compose up`

If `docker compose up` stops due to an error (or you Ctrl+C it), just start it again:

```bash
docker compose up --build
```

Or run in the background:

```bash
docker compose up -d --build
docker compose logs -f web
```

Then re-run any commands that didn’t execute (e.g. `createsuperuser`, `sync_demo`).

### WSL2 troubleshooting: `The command 'docker' could not be found`

That message means **Docker isn’t installed/available in your WSL distro**, so `docker compose ...` can’t run.

Fix options:

1) **Recommended (Docker Desktop on Windows)**:
   - Install **Docker Desktop**
   - Docker Desktop → **Settings** → **Resources** → **WSL Integration**
   - Enable WSL integration for your distro (e.g. `Ubuntu-22.04`)
   - Restart your WSL terminal and verify:

```bash
docker version
docker compose version
```

2) **Alternative (install Docker Engine inside WSL)**:
   - Install Docker Engine + Compose plugin in the distro, and ensure the daemon can run (WSL needs systemd enabled).
   - Follow Docker’s official Linux install docs for your distro.

### Running without Docker (advanced)

This project targets **Python 3.12** (Django 5.x) and **PostgreSQL + PostGIS**.
If you don’t use Docker you must provide:

- Python **>= 3.10** (recommended 3.12)
- Postgres 16 + PostGIS 3.x
- Redis 7
- Node 20 (for Tailwind builds)

Then set `DATABASE_URL` to your local PostGIS instance and run:

```bash
pip install -r requirements.txt
python src/manage.py migrate
python src/manage.py runserver
```

## Staff workflow (admin/editor/reviewer)

On `migrate`, the app creates two staff groups:

- **`editor`**: view/add/change core directory models
- **`reviewer`**: editor permissions + ingestion models (`SyncRun`, `SourceRecord`, `MergeReview`) and video approvals

Assign staff users to these groups in Django admin.

## Ingestion architecture (first version)

This repo includes an ingestion “spine” designed for real providers:

- **Adapter interface**: `apps/ingestion/adapters/base.py`
- **Provider stubs**: `apps/ingestion/adapters/*.py`
- **Normalization** (demo): `apps/ingestion/normalizers/demo.py`
- **Raw payload retention**: `apps/ingestion/models.py` (`SourceRecord.payload`)
- **Scheduled jobs**: `apps/ingestion/tasks.py` (Celery beat schedule configured in settings)
- **Duplicate detection**: creates `MergeReview` records for human review

Provider priority for conflicting fields is defined in `apps/ingestion/priority.py`. Manual overrides on `Person` always win.

## Democracy Works integration

This repo can ingest **Democracy Works Elections API v2** data (elections, contests, candidates). It stores raw payloads as `SourceRecord` rows for auditability.

### Configure

1) Put your key in `.env` (never commit it):

```bash
DEMOCRACY_WORKS_API_KEY=...your key...
```

2) Choose a sync scope:

- **State-wide**:

```bash
DEMOCRACY_WORKS_STATE_CODE=TX
DEMOCRACY_WORKS_ELECTION_YEAR=2026
```

- **Optional date range** (state-wide sync only):
  - If you don’t set dates, the app defaults to the **current election year** (useful for focusing on 2026).
  - If you set dates, they override `DEMOCRACY_WORKS_ELECTION_YEAR`.

```bash
# DEMOCRACY_WORKS_START_DATE=2020-01-01
# DEMOCRACY_WORKS_END_DATE=2029-12-31
```

- **Address-based** (recommended):

```bash
DEMOCRACY_WORKS_ADDRESS_STREET=813 Howard Street
DEMOCRACY_WORKS_ADDRESS_CITY=Oswego
DEMOCRACY_WORKS_ADDRESS_STATE_CODE=NY
DEMOCRACY_WORKS_ADDRESS_ZIP=13126
```

### Run a sync

```bash
docker compose exec web python manage.py sync_democracy_works
```

### Amarillo (Potter + Randall) targeted sync

For a step-by-step guide (including handling `429 Limit Exceeded` vs `403 Forbidden`), see `DW_AMARILLO_SYNC.md`.

To run Amarillo metro sync for 2026:

```bash
docker compose exec -T web bash -lc "cd /app/src && python manage.py sync_democracy_works --state TX --amarillo-metro --election-year 2026"
```

After sync:

- `/candidates/` is populated from contests/candidates.
- If a DW candidate is flagged as `isIncumbent=true`, the app creates a **reviewable inferred** `OfficeholderTerm` so they can appear in `/officials/` (with a review note).

## Ballotpedia photo enrichment (headshots)

Democracy Works does **not** include headshots directly. When DW provides a `ballotpediaUrl` for a candidate, the app stores it as an `ExternalLink(kind=ballotpedia)` on the `Person`.

You can then enrich `Person.photo_url` by fetching and parsing the Ballotpedia profile page (best-effort) and extracting a likely headshot image URL. Raw results are stored as `SourceRecord` rows for auditability.

Run it manually:

```bash
docker compose exec web bash -lc "cd /app/src && python manage.py sync_ballotpedia_photos --limit 250 --sleep-ms 300"
```

Notes:
- This **never overwrites** `manual_photo_url` (staff override).
- Placeholder images (e.g. “Submit photo”) are ignored in the UI.
- The Celery beat schedule runs a **small batch hourly** by default (see `CELERY_BEAT_SCHEDULE` in `settings.py`).

## Code organization

Apps live under `src/apps/`:

- `apps/core`
- `apps/geo`
- `apps/people`
- `apps/offices`
- `apps/elections`
- `apps/media`
- `apps/search`
- `apps/ingestion`
- `apps/api`

## Testing

Tests are written with `pytest` + `pytest-django`.

```bash
docker compose exec web pytest
```

Coverage includes:

- Model behaviors and factories
- Demo normalization + provider priority
- Directory filters (including HTMX partial responses)
- Safe video URL handling and embed URL generation
- Duplicate detection creating `MergeReview`
- Public page smoke tests

## Publishing to GitHub

This workspace is not initialized as a git repository by default. To publish:

```bash
git init
git add .
git commit -m "Initial commit: The Ballot Box"
```

Then create a new repository on GitHub and add the remote:

```bash
git remote add origin git@github.com:<your-org-or-user>/<repo>.git
git push -u origin main
```

## Next steps

- Replace fixture adapters with real provider clients (BallotReady/CivicEngine, Ballotpedia, OpenStates, OpenFEC, YouTube API)
- Add richer dedupe heuristics and an admin merge action that actually merges records
- Add computed search vectors + background indexing for `Person`/`Office`
- Harden moderation flows (video approval queues, review status gating for public visibility)
- Add real geospatial lookup flows (address → district matching) using PostGIS geometry

