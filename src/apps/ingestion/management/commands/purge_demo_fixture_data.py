from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, OuterRef, Q

from apps.elections.models import Candidacy, OfficeholderTerm
from apps.ingestion.models import SourceRecord
from apps.people.models import Person


class Command(BaseCommand):
    help = (
        "Remove fictional demo fixture people (demo-* source ids) and their candidacies / officeholder terms, "
        "then delete remaining SourceRecord rows whose external_id starts with 'demo-'."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show counts only; do not delete.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        ct_person = ContentType.objects.get_for_model(Person)
        non_demo = SourceRecord.objects.filter(
            normalized_content_type=ct_person,
            normalized_object_id=OuterRef("pk"),
        ).exclude(external_id__startswith="demo-")
        has_demo = SourceRecord.objects.filter(
            normalized_content_type=ct_person,
            normalized_object_id=OuterRef("pk"),
            external_id__startswith="demo-",
        )
        demo_only_persons = Person.objects.annotate(
            _has_demo=Exists(has_demo),
            _has_non_demo=Exists(non_demo),
        ).filter(_has_demo=True, _has_non_demo=False)

        person_ids = list(demo_only_persons.values_list("id", flat=True))
        self.stdout.write(f"Demo-only persons to remove: {len(person_ids)}")
        demo_sources = SourceRecord.objects.filter(external_id__startswith="demo-")
        self.stdout.write(f"SourceRecord rows with demo-* external_id: {demo_sources.count()}")

        if dry:
            self.stdout.write(self.style.WARNING("Dry run; no changes made."))
            return

        with transaction.atomic():
            deleted_c, _ = Candidacy.objects.filter(person_id__in=person_ids).delete()
            deleted_t, _ = OfficeholderTerm.objects.filter(person_id__in=person_ids).delete()
            deleted_sr, _ = SourceRecord.objects.filter(
                Q(external_id__startswith="demo-")
                | Q(normalized_content_type=ct_person, normalized_object_id__in=person_ids)
            ).delete()
            deleted_p, _ = Person.objects.filter(id__in=person_ids).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted candidacies={deleted_c}, officeholder_terms={deleted_t}, source_records={deleted_sr}, "
                f"persons={deleted_p}."
            )
        )
