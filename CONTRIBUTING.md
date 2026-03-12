## Contributing

### Ground rules

- Do not add real voter PII or real political datasets to this repo.
- Keep public pages **data-first**: no campaign-style content, no sensational language.
- All user-visible content must be sanitized; videos must remain allowlisted providers + safe rendering.

### Development setup

Use Docker Compose (recommended):

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py sync_demo
```

### Tests

```bash
docker compose exec web pytest
```

### Pull requests

Include:

- Summary of changes
- Test plan (commands run)
- Any migration notes (`makemigrations` output)

