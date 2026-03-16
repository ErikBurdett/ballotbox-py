from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ingestion.models import Provider
from apps.ingestion.tasks import sync_provider


class Command(BaseCommand):
    help = "Sync Democracy Works elections + contests + candidates into normalized tables."

    def handle(self, *args, **options):
        run_id = sync_provider(Provider.DEMOCRACY_WORKS)
        self.stdout.write(self.style.SUCCESS(f"democracy_works: sync_run={run_id}"))

