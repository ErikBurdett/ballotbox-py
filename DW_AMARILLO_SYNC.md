## Democracy Works → Amarillo (Potter + Randall) sync process

This document explains how to ingest Democracy Works (DW) data specifically for **Amarillo, Texas**, including ballots that cover **Potter County** and **Randall County**, and how to handle key/quota issues.

## What this sync does

- **Fetches elections** from DW using an “Amarillo metro” mode (multiple representative Amarillo addresses/ZIPs).
- Normalizes DW `elections → contests → candidates` into the app’s models:
  - **`Election`**
  - **`Race`**
  - **`Candidacy`**
  - **`Person`**
  - (Best-effort) **`OfficeholderTerm`** when DW marks a candidate as an incumbent

## Prerequisites

- Docker services running (`web`, `worker`, `beat`, `db`, `redis`)
- A valid DW key in `.env`:

```bash
DEMOCRACY_WORKS_API_KEY=...
```

## Step 1 — Update/rotate your Democracy Works API key

If you suspect the key is revoked/expired, get a new one from Democracy Works and update your local `.env`.

Then restart containers so the new key is loaded everywhere:

```bash
docker compose restart web worker beat
```

## Step 2 — Run an Amarillo (metro) sync for 2026

Run the targeted Amarillo metro sync for the 2026 election year:

```bash
docker compose exec -T web bash -lc "cd /app/src && python manage.py sync_democracy_works --state TX --amarillo-metro --election-year 2026"
```

### Notes

- `--amarillo-metro` uses multiple Amarillo-area addresses to cover ballots that should include both **Potter** and **Randall** county coverage.
- This is intentionally **more precise** than a full TX state backfill.

## Step 3 — Verify the data landed

Check counts for Potter/Randall:

```bash
docker compose exec -T web bash -lc "cd /app/src && python manage.py shell -c \"from apps.elections.models import Race,Candidacy,OfficeholderTerm; counties=['Potter','Randall']; print('races_2026', Race.objects.filter(election__date__year=2026, office__jurisdiction__county__in=counties).count()); print('candidacies_2026', Candidacy.objects.filter(race__election__date__year=2026, race__office__jurisdiction__county__in=counties).count()); print('terms_total', OfficeholderTerm.objects.filter(office__jurisdiction__county__in=counties).count())\""
```

And inspect the most recent DW `SyncRun`:

```bash
docker compose exec -T web bash -lc "cd /app/src && python manage.py shell -c \"from apps.ingestion.models import SyncRun,Provider; r=SyncRun.objects.filter(provider=Provider.DEMOCRACY_WORKS).order_by('-created_at').first(); print(r.public_id, r.status, r.stats, (r.error_text or '')[:200])\""
```

## Troubleshooting

### `HTTP 429 Limit Exceeded`

This means **quota/rate-limit is exhausted** for the key/account at the moment.

- **What you’ll see**: `DW HTTP 429 ... {"message":"Limit Exceeded"}`
- **What to do**:
  - Wait for the quota window to reset, or
  - Rotate to a key/account with a fresh quota, or
  - Request a quota increase from Democracy Works

The management command will **fail fast** when DW is returning 429 so you don’t end up with stuck “RUNNING” sync runs.

### `HTTP 403 Forbidden`

This usually means the key is **invalid/revoked** (or not being provided).

- Confirm `.env` has `DEMOCRACY_WORKS_API_KEY=...`
- Restart `web/worker/beat` after editing `.env`

### DW sync runs stuck in `RUNNING`

If you previously had jobs that were interrupted, you may see old `SyncRun` rows left as `RUNNING`.
You can cancel them like this:

```bash
docker compose exec -T web bash -lc "cd /app/src && python - <<'PY'\nimport os\nos.environ.setdefault('DJANGO_SETTINGS_MODULE','american_voter_directory.settings')\nimport django\ndjango.setup()\n\nfrom django.utils import timezone\nfrom apps.ingestion.models import SyncRun,Provider,SyncStatus\n\nqs = SyncRun.objects.filter(provider=Provider.DEMOCRACY_WORKS, status=SyncStatus.RUNNING)\nprint('running_before', qs.count())\nnow = timezone.now()\nfor r in qs:\n    r.status = SyncStatus.CANCELLED\n    r.error_text = (r.error_text + '\\n' if r.error_text else '') + 'Cancelled manually'\n    r.finished_at = now\n    r.save(update_fields=['status','error_text','finished_at','updated_at'])\nprint('running_after', SyncRun.objects.filter(provider=Provider.DEMOCRACY_WORKS, status=SyncStatus.RUNNING).count())\nPY"
```

## Recommended operational approach

- Use **Amarillo metro** sync for Amarillo-area completeness (Potter/Randall).
- Use **state-wide TX sync** only when needed (it is much more likely to hit quotas).
- Prefer running DW syncs manually during development when you can watch output and avoid running multiple DW syncs concurrently.

