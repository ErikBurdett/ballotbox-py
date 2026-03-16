from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ingestion.models import Provider
from apps.ingestion.tasks import sync_provider


class Command(BaseCommand):
    help = "Run the demo/fixture ingestion adapters (creates SourceRecords + normalized models)."

    def handle(self, *args, **options):
        # Demo fixtures only. Democracy Works is a real API integration and is synced via `sync_democracy_works`.
        providers = [p for p, _label in Provider.choices if p != Provider.DEMOCRACY_WORKS]
        for provider in providers:
            run_id = sync_provider(provider)
            self.stdout.write(self.style.SUCCESS(f"{provider}: sync_run={run_id}"))

