from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.people.models import Person

from .adapters.registry import get_adapters
from .models import MergeReview, MergeStatus, Provider, SyncRun, SyncStatus


logger = logging.getLogger(__name__)


@shared_task
def sync_provider(provider: str) -> str:
    provider_value = provider
    run = SyncRun.objects.create(provider=provider_value, status=SyncStatus.RUNNING)

    try:
        adapters = [a for a in get_adapters() if a.provider == provider_value]
        if not adapters:
            run.status = SyncStatus.FAILED
            run.error_text = f"No adapter registered for provider={provider_value}"
            return run.public_id.hex

        adapter = adapters[0]
        payloads = adapter.fetch()
        run.stats = {"fetched": len(payloads)}
        run.save(update_fields=["stats", "updated_at"])

        errors = 0
        for payload in payloads:
            try:
                adapter.normalize(payload, sync_run=run)
            except Exception as exc:
                errors += 1
                logger.exception("normalize failed provider=%s", provider_value)
                run.error_text = (run.error_text + "\n" if run.error_text else "") + str(exc)

        run.stats = {**(run.stats or {}), "errors": errors}
        run.status = SyncStatus.PARTIAL if errors else SyncStatus.SUCCESS
        return run.public_id.hex
    finally:
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_text", "stats", "finished_at", "updated_at"])


@shared_task
def sync_all_providers() -> list[str]:
    results: list[str] = []
    for provider, _label in Provider.choices:
        results.append(sync_provider(provider))
    return results


@shared_task
def detect_person_duplicates(max_groups: int = 50) -> int:
    """
    Very conservative duplicate detection: same first+last (case-insensitive).
    Creates MergeReview records for human review.
    """
    ct = ContentType.objects.get_for_model(Person)
    groups = (
        Person.objects.exclude(first_name="")
        .exclude(last_name="")
        .values("first_name", "last_name")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .order_by("-n")[:max_groups]
    )

    created = 0
    for g in groups:
        people = list(
            Person.objects.filter(first_name=g["first_name"], last_name=g["last_name"]).order_by("id")[:5]
        )
        if len(people) < 2:
            continue
        a = people[0]
        for b in people[1:]:
            exists = MergeReview.objects.filter(
                status=MergeStatus.OPEN,
                candidate_a_content_type=ct,
                candidate_a_object_id=a.id,
                candidate_b_content_type=ct,
                candidate_b_object_id=b.id,
            ).exists()
            if exists:
                continue
            MergeReview.objects.create(
                candidate_a_content_type=ct,
                candidate_a_object_id=a.id,
                candidate_b_content_type=ct,
                candidate_b_object_id=b.id,
                merge_reason=f"Auto-detected potential duplicate: {a.display_name}",
            )
            created += 1

    return created

