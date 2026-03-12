from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ingestion.models import Provider
from apps.ingestion.tasks import sync_provider


class Command(BaseCommand):
    help = "Run the demo/fixture ingestion adapters (creates SourceRecords + normalized models)."

    def handle(self, *args, **options):
        for provider, _label in Provider.choices:
            run_id = sync_provider(provider)
            self.stdout.write(self.style.SUCCESS(f"{provider}: sync_run={run_id}"))

